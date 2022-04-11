#!/usr/bin/env python3
# Copyright 2022 pietro
# See LICENSE file for licensing details.

"""Charm the service.

"""

import logging
from dataclasses import dataclass
from itertools import starmap
from typing import Iterable, Optional, Protocol, Sequence, Tuple
from urllib.parse import urlparse

from charms.traefik_k8s.v0.ingress_per_unit import (IngressPerUnitProvider,
                                                    RequirerData)
from charms.traefik_route_k8s.v0.traefik_route import (
    TraefikRouteIngressReadyEvent, TraefikRouteRequestEvent,
    TraefikRouteRequirer)
from ops.charm import CharmBase
from ops.main import main
from ops.model import (ActiveStatus, BlockedStatus, Relation, Unit,
                       WaitingStatus)

logger = logging.getLogger(__name__)


class _HasUnits(Protocol):
    @property
    def units(self) -> Sequence[Unit]:
        pass


class RuleDerivationError(RuntimeError):
    def __init__(self, url, *args, **kwargs):
        msg = f"Unable to derive Rule from {url}; ensure that the url is valid."
        super(RuleDerivationError, self).__init__(msg, *args, **kwargs)


def _check_has_one_unit(obj: _HasUnits):
    """Checks that the obj has at least one unit."""
    if not obj.units:
        logger.error(f"{obj} has no units")
        return False
    return True


@dataclass
class RouteConfig:
    rule: str
    root_url: str
    id_: str


@dataclass
class _RouteConfig:
    root_url: str
    rule: str = None

    @property
    def is_valid(self):
        def _check_var(obj: str, name):
            error = None
            # None or empty string or whitespace-only string
            if not obj or not obj.strip():
                error = (
                    f"`{name}` not configured; do `juju config <traefik-route-charm> "
                    f"{name}=<{name.upper()}>; juju resolve <traefik-route-charm>`"
                )

            elif obj != (stripped := obj.strip()):
                error = (
                    f"{name} {obj!r} starts or ends with whitespace;"
                    f"it should be {stripped!r}."
                )

            if error:
                logger.error(error)
            return not error

        if not self.rule:
            # we can guess the rule from the root_url.
            return _check_var(self.root_url, "root_url")

        # TODO: think about further validating `rule` (regex?)
        valid = starmap(_check_var, ((self.rule, "rule"), (self.root_url, "root_url")))
        return all(valid)

    def render(self, model_name: str, unit_name: str, app_name: str):
        """Fills in the blanks in the templates."""

        # todo make proper jinja2 thing here
        def _render(obj: str):
            for key, value in (
                ("{{juju_model}}", model_name),
                ("{{juju_application}}", app_name),
                ("{{juju_unit}}", unit_name),
            ):
                if key in obj:
                    obj = obj.replace(key, value)
            return obj

        url = _render(self.root_url)
        if not self.rule:
            rule = self.generate_rule_from_url(url)
        else:
            rule = _render(self.rule)

        # an easily recognizable id for the traefik services
        id_ = "-".join((unit_name, model_name))
        return RouteConfig(rule=rule, root_url=url, id_=id_)

    @staticmethod
    def generate_rule_from_url(url) -> str:
        """Derives a Traefik router Host rule from the provided `url`'s hostname."""
        url_ = urlparse(url)
        if not url_.hostname:
            raise RuleDerivationError(url)
        return f"Host(`{url_.hostname}`)"


class TraefikRouteK8SCharm(CharmBase):
    """Charm the service."""

    _ingress_endpoint = "ingress-per-unit"
    _traefik_route_endpoint = "traefik-route"

    def __init__(self, *args):
        super().__init__(*args)

        self.ingress_per_unit = IngressPerUnitProvider(self, self._ingress_endpoint)
        self.traefik_route = TraefikRouteRequirer(
            self, self._traefik_route_relation, self._traefik_route_endpoint
        )

        observe = self.framework.observe
        observe(self.on.config_changed, self._on_config_changed)
        observe(self.ingress_per_unit.on.request, self._on_ingress_request)

    def _get_relation(self, endpoint: str) -> Optional[Relation]:
        """Fetches the Relation for endpoint and checks that there's only 1."""
        relations = self.model.relations.get(endpoint)
        if not relations:
            logger.info(f"no relations yet for {endpoint}")
            return None
        if len(relations) > 1:
            logger.warning(f"more than one relation for {endpoint}")
        return relations[0]

    @staticmethod
    def _get_remote_units_from_relation(
        relation: Optional[Relation],
    ) -> Tuple[Unit, ...]:
        if not relation:
            return ()
        return tuple(relation.units)

    @property
    def _ipu_relation(self) -> Optional[Relation]:
        """The relation with the unit requesting ingress."""
        return self._get_relation(self._ingress_endpoint)

    @property
    def _traefik_route_relation(self) -> Optional[Relation]:
        """The relation with the (Traefik) charm providing traefik-route."""
        return self._get_relation(self._traefik_route_endpoint)

    @property
    def _remote_routed_units(self) -> Tuple[Unit]:
        """The remote units in need of ingress."""
        return self._get_remote_units_from_relation(self._ipu_relation)

    @property
    def _remote_traefik_unit(self) -> Optional[Unit]:
        """The traefik unit providing ingress.

        We're going to assume there's only one."""
        traefik_units = self._get_remote_units_from_relation(
            self._traefik_route_relation
        )
        if not traefik_units:
            return None
        return traefik_units[0]

    @property
    def _config(self) -> _RouteConfig:
        return _RouteConfig(
            rule=self.config.get("rule"), root_url=self.config.get("root_url")
        )

    @property
    def rule(self) -> Optional[str]:
        """The Traefik rule this charm is responsible for configuring."""
        return self._config.rule

    @property
    def root_url(self) -> Optional[str]:
        """The advertised url for the charm requesting ingress."""
        return self._config.root_url

    def _render_config(self, model_name: str, unit_name: str, app_name: str):
        return self._config.render(
            model_name=model_name, unit_name=unit_name, app_name=app_name
        )

    def _on_config_changed(self, _):
        """Check the config; set an active status if all is good."""
        if not self._config.is_valid:
            # we block until the user fixes the config
            self.unit.status = BlockedStatus("bad config; see logs for more")
            return

        if self._is_ready():
            self._update()

        self.unit.status = ActiveStatus()

    def _is_ready(self):
        # check that the charm config is ok
        if not self._config.is_valid:
            self.unit.status = BlockedStatus("bad config; see logs for more")
            return False

        # validate IPU relation status
        ipu_relation = self._ipu_relation
        if not ipu_relation:
            self.unit.status = BlockedStatus(
                f"Ingress requested, but ingress-per-unit relation is "
                f"not available."
            )
            return False
        elif self.ingress_per_unit.is_failed(ipu_relation):
            self.unit.status = BlockedStatus(
                f"Ingress requested, but ingress-per-unit relation is"
                f"broken (failed)."
            )
            return False
        elif not self.ingress_per_unit.is_available(ipu_relation):
            self.unit.status = WaitingStatus(f"ingress-per-unit is not available yet.")
            return False

        # validate traefik-route relation status
        if not self._traefik_route_relation:
            self.unit.status = WaitingStatus(
                f"traefik-route is not available yet. "
                f"Relate traefik-route to traefik."
            )
            return False

        return True

    def _on_ingress_request(self, event: TraefikRouteRequestEvent):
        if not self._is_ready():
            return event.defer()

        logger.info(
            "Ingress request event received. IPU ready; " "TR ready; Relaying..."
        )
        self._update()

    def _config_for_unit(self, unit_data: RequirerData) -> RouteConfig:
        """Get the _RouteConfig for the provided `unit_data`."""
        # we assume self.ingress_request is there; if not, you should probably
        # put this codepath behind:
        #   if self._is_ready()...
        unit_name = unit_data["name"]
        model_name = unit_data["model"]

        # sanity checks
        assert unit_name is not None, f"remote unit did not provide its name"
        assert "/" in unit_name, unit_name

        return self._render_config(
            model_name=model_name,
            unit_name=unit_name.replace("/", "-"),
            app_name=unit_name.split("/")[0],
        )

    def _update(self):
        """Publish the urls to the units requesting it and configure traefik."""
        # we assume that self._is_ready().

        ingress: IngressPerUnitProvider = self.ingress_per_unit
        traefik_unit: Unit = self._remote_traefik_unit
        relation = self._ipu_relation

        traefik_configs = []
        ready_units = filter(
            lambda unit_: ingress.is_unit_ready(relation, unit_), relation.units
        )
        for unit in ready_units:  # units requesting ingress
            unit_data = ingress.get_data(self._ipu_relation, unit, validate=True)
            config = self._config_for_unit(unit_data)

            traefik_config = self._generate_traefik_config_data(
                config.rule, config.id_, config.root_url
            )

            traefik_configs.append(traefik_config)

            # FIXME:
            #  we can publish the url to the unit immediately, but this might race
            #  with traefik loading the config. Point is, we don't need Traefik to
            #  tell us the url, but Traefik needs the config before it can start routing.
            #  Consider whether we should only forward the url to the unit after Traefik
            #  gives us some kind of ok.
            ingress.publish_url(relation, unit_data["name"], config.root_url)

        # merge configs?
        config = self._merge_traefik_configs(traefik_configs)
        if self.traefik_route.is_ready():
            self.traefik_route.submit_to_traefik(config=config)

    @staticmethod
    def _generate_traefik_config_data(rule: str, config_id: str, url: str) -> dict:
        config = {"router": {}, "service": {}}

        traefik_router_name = f"juju-{config_id}-router"
        traefik_service_name = f"juju-{config_id}-service"

        config["router"][traefik_router_name] = {
            "rule": rule,
            "service": traefik_service_name,
            "entryPoints": ["web"],
        }

        config["service"][traefik_service_name] = {
            "loadBalancer": {"servers": [{"url": url}]}
        }
        return config

    @staticmethod
    def _merge_traefik_configs(configs: Iterable[dict]) -> dict:
        master_config = {"http": {"routers": {}, "services": {}}}

        for config in configs:
            master_config["http"]["routers"].update(config["router"])
            master_config["http"]["services"].update(config["service"])

        return master_config


if __name__ == "__main__":
    main(TraefikRouteK8SCharm)
