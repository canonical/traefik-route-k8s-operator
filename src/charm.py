#!/usr/bin/env python3
# Copyright 2022 pietro
# See LICENSE file for licensing details.

"""Charm the service.

"""

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
from itertools import starmap
from typing import Optional, Sequence, Tuple, Iterable, Protocol

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Relation, WaitingStatus, Unit
from charms.traefik_k8s.v0.ingress_per_unit import IngressPerUnitProvider, \
    IngressRequest
from charms.traefik_route_k8s.v0.traefik_route import TraefikRouteRequirer, \
    TraefikRouteIngressReadyEvent, TraefikRouteRequestEvent

logger = logging.getLogger(__name__)


class _HasUnits(Protocol):
    @property
    def units(self) -> Sequence[Unit]:
        pass


def _check_has_one_unit(obj: _HasUnits):
    """Checks that the obj has at least one unit."""
    if not obj.units:
        logger.error(f"{obj} has no units")
        return False
    return True


@dataclass
class _RouteConfig:
    rule: str = None
    url: str = None


@dataclass
class RouteConfig(_RouteConfig):
    @property
    def is_valid(self):
        def _check_var(obj: str, name):
            error = None
            # None or empty string or whitespace-only string
            if not obj or not obj.strip():
                error = (
                    f"`{name}` not configured; do `juju config <traefik-route-charm> "
                    f"{name}=<{name.upper()}>; juju resolve <traefik-route-charm>`")

            elif obj != (stripped := obj.strip()):
                error = (f"{name} {obj!r} starts or ends with whitespace;"
                         f"it should be {stripped!r}.")

            if error:
                logger.error(error)
            return error

        # TODO: think about further validating `rule` (regex?)
        errors = starmap(_check_var, ((self.rule, 'rule'),
                                      (self.url, 'url')))
        return not any(errors)

    def render(self, **kwargs):
        # todo make proper jinja2 thing here
        def _render(rule: str, **kwargs_):
            for key, value in (
                    ('{{juju_model}}', kwargs_.get("model")),
                    ('{{juju_unit}}', kwargs_.get("name")),
            ):
                if key in rule:
                    rule = rule.replace(key, value)
            return rule

        rule = _render(self.rule, **kwargs)
        url = _render(self.url, **kwargs)
        return RouteConfig(rule, url)


class TraefikRouteK8SCharm(CharmBase):
    """Charm the service."""
    _ingress_endpoint = "ingress-per-unit"
    _traefik_route_endpoint = "traefik-route"

    def __init__(self, *args):
        super().__init__(*args)

        self.ingress_per_unit = IngressPerUnitProvider(
            self, self._ingress_endpoint)
        self.traefik_route = TraefikRouteRequirer(
            self, self._traefik_route_relation,
            self._traefik_route_endpoint)

        # if the remote app (traefik) has published the url: we give it
        # forward to the charm who's requesting ingress.
        # if url := self.traefik_route.proxied_endpoint:
        #     self.ingress_per_unit.get_request(self._ipu_relation).respond(
        #         self.unit, url)

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
    def _get_remote_units_from_relation(relation: Optional[Relation]) -> Tuple[
        Unit]:
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
            self._traefik_route_relation)
        if not traefik_units:
            return None
        return traefik_units[0]

    @property
    def ingress_request(self) -> Optional[IngressRequest]:
        """Get the request for ingress, if ingress_per_unit is active."""
        if ipu := self._ipu_relation:
            return self.ingress_per_unit.get_request(ipu)

    @cached_property
    def _config(self) -> RouteConfig:
        return RouteConfig(self.config['rule'], self.config['url'])

    @property
    def rule(self) -> Optional[str]:
        """The Traefik rule this charm is responsible for configuring."""
        return self._config.rule

    @property
    def url(self) -> Optional[str]:
        """The advertised url for the charm requesting ingress."""
        return self._config.url

    def _render_config(self, **kwargs):
        return self._config.render(**kwargs)

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
            self.unit.status = BlockedStatus(
                "bad config; see logs for more"
            )
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
            self.unit.status = WaitingStatus(
                f"ingress-per-unit is not available yet.")
            return False

        # validate traefik-route relation status
        if not self._traefik_route_relation:
            self.unit.status = WaitingStatus(
                f"traefik-route is not available yet. "
                f"Relate traefik-route to traefik.")
            return False

        return True

    def _on_ingress_request(self, event: TraefikRouteRequestEvent):
        if not self._is_ready():
            return event.defer()

        logger.info('Ingress request event received. IPU ready; '
                    'TR ready; Relaying...')
        self._update()

    def _update(self):
        """Publish the urls to the units requesting it and configure traefik."""
        # we assume that self._is_ready().

        ingress: IngressRequest = self.ingress_request
        traefik_unit: Unit = self._remote_traefik_unit

        traefik_configs = []
        for unit in ingress.units:  # units requesting ingress
            unit_name = ingress.get_unit_name(unit)
            assert unit_name is not None
            model = ingress.model

            config = self._render_config(model=model,
                                         name=unit_name)

            # we generate an easily recognizable id for the traefik services
            config_id = '-'.join((unit_name, model))
            traefik_config = self._generate_traefik_config_data(
                config.rule, config_id, config.url)

            traefik_configs.append(traefik_config)

            # we can publish the url to the unit immediately
            ingress.respond(unit, config.url)

        # merge configs?
        config = self._merge_traefik_configs(traefik_configs)
        self.traefik_route.submit_to_traefik(config=config)

    def _generate_traefik_config_data(self, rule: str, config_id: str,
                                      url: str) -> dict:
        config = {"router": {}, "service": {}}

        traefik_router_name = f"juju-{config_id}-router"
        traefik_service_name = f"juju-{config_id}-service"

        config["router"][traefik_router_name] = {
            "rule": rule,
            "service": traefik_service_name,
            "entryPoints": ["web"],
        }

        config["service"][traefik_service_name] = {
            "loadBalancer": {
                "servers": [{"url": url}]
            }
        }
        return config

    def _merge_traefik_configs(self, configs: Iterable[dict]) -> dict:
        master_config = {"http": {"routers": {}, "services": {}}}

        for config in configs:
            master_config["http"]['routers'].update(config['router'])
            master_config["http"]['services'].update(config['service'])

        return master_config


if __name__ == "__main__":
    main(TraefikRouteK8SCharm)
