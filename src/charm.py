#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Traefik Route charm for kubernetes."""

import logging
import textwrap
from dataclasses import dataclass
from itertools import starmap
from typing import Iterable, Optional, Tuple, cast
from urllib.parse import urlparse

import jinja2
from charms.traefik_k8s.v1.ingress_per_unit import (
    IngressDataReadyEvent,
    IngressPerUnitProvider,
    RequirerData,
)
from charms.traefik_route_k8s.v0.traefik_route import TraefikRouteRequirer
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Relation, Unit

from types_ import TraefikConfig, UnitConfig

logger = logging.getLogger(__name__)


class RuleDerivationError(RuntimeError):
    """Raised when a rule cannot be derived from other config parameters.

    Solution: provide the rule manually, or fix what's broken.
    """

    def __init__(self, url: str, *args):
        msg = f"Unable to derive Rule from {url!r}; ensure that the url is valid."
        super().__init__(msg, *args)


class TemplateKeyError(RuntimeError):
    """Raised when a template contains a key which we cannot provide.

    Solution: fix the template to only include the variables:
        - `juju_model`
        - `juju_application`
        - `juju_unit`
    """

    def __init__(self, template: str, key: str, *args):
        msg = textwrap.dedent(
            f"""Unable to render the template {template!r}: {key!r} unknown.
                - `juju_model`
                - `juju_application`
                - `juju_unit`"""
        )
        super().__init__(msg, *args)


@dataclass
class RouteConfig:
    """Route configuration."""

    root_url: str
    rule: str
    service_name: str
    strip_prefix: bool = False


@dataclass
class _RouteConfig:
    root_url: str
    rule: Optional[str] = None

    @property
    def is_valid(self):
        def _check_var(obj: str, name):
            error = None
            # None or empty string or whitespace-only string
            if not obj or not obj.strip():
                error = (
                    f"`{name}` not configured; run `juju config <traefik-route-charm> "
                    f"{name}=<{name.upper()}>"
                )

            elif obj != (stripped := obj.strip()):
                error = (
                    f"{name} {obj!r} starts or ends with whitespace;" f"it should be {stripped!r}."
                )

            if error:
                logger.error(error)
            return not error

        if self.root_url:
            # has no sense checking this unless root_url is set
            try:
                # try rendering with dummy values; it should succeed.
                self.render(model_name="foo", unit_name="bar", app_name="baz")
            except (TemplateKeyError, RuleDerivationError) as e:
                logger.error(e)
                return False

        if not self.rule:
            # we can guess the rule from the root_url.
            return _check_var(self.root_url, "root_url")

        # TODO: think about further validating `rule` (regex?)
        valid = starmap(_check_var, ((self.rule, "rule"), (self.root_url, "root_url")))
        return all(valid)

    def render(self, model_name: str, unit_name: str, app_name: str, strip_prefix: bool = False):
        """Fills in the blanks in the templates."""

        def _render(obj: str):
            # StrictUndefined will raise an exception if some undefined
            # variables are left unrendered in the template
            template = jinja2.Template(obj, undefined=jinja2.StrictUndefined)
            try:
                return template.render(
                    juju_model=model_name, juju_application=app_name, juju_unit=unit_name
                )
            except jinja2.UndefinedError as e:
                undefined_key = e.message.split()[0].strip(r"'")  # type: ignore
                raise TemplateKeyError(obj, undefined_key) from e

        url = _render(self.root_url)
        if not self.rule:
            rule = self.generate_rule_from_url(url)
        else:
            rule = _render(self.rule)

        # an easily recognizable id for the traefik services
        service_name = "-".join((unit_name, model_name))
        return RouteConfig(
            rule=rule, root_url=url, service_name=service_name, strip_prefix=strip_prefix
        )

    @staticmethod
    def generate_rule_from_url(url) -> str:
        """Derives a Traefik router Host rule from the provided `url`'s hostname."""
        url_ = urlparse(url)
        if not url_.hostname:
            raise RuleDerivationError(url)
        return f"Host(`{url_.hostname}`)"


class TraefikRouteK8SCharm(CharmBase):
    """Charm the service."""

    _ingress_relation_name = "ingress-per-unit"
    _traefik_route_relation_name = "traefik-route"

    def __init__(self, *args):
        super().__init__(*args)
        if not self.unit.is_leader():
            self.unit.status = BlockedStatus("Traefik-Route cannot be scaled > n1.")
            logger.error(f"{self} was initialized without leadership.")
            # skip initializing the listeners: charm will be dead unreactive
            return

        self.ingress_per_unit = IngressPerUnitProvider(self, self._ingress_relation_name)
        self.traefik_route = TraefikRouteRequirer(
            self, self._traefik_route_relation, self._traefik_route_relation_name  # type: ignore
        )

        observe = self.framework.observe
        observe(self.on.config_changed, self._on_config_changed)
        observe(
            self.ingress_per_unit.on.data_provided,  # pyright: ignore
            self._on_ingress_data_provided,
        )

        # todo wipe all data if and when TR 'stops' being ready
        #  (e.g. config change breaks the config)

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
        return self._get_relation(self._ingress_relation_name)

    @property
    def _traefik_route_relation(self) -> Optional[Relation]:
        """The relation with the (Traefik) charm providing traefik-route."""
        return self._get_relation(self._traefik_route_relation_name)

    @property
    def _remote_routed_units(self) -> Tuple[Unit, ...]:
        """The remote units in need of ingress."""
        return self._get_remote_units_from_relation(self._ipu_relation)

    @property
    def _remote_traefik_unit(self) -> Optional[Unit]:
        """The traefik unit providing ingress.

        We're going to assume there's only one.
        """
        traefik_units = self._get_remote_units_from_relation(self._traefik_route_relation)
        if not traefik_units:
            return None
        assert len(traefik_units) == 1, "There should be exactly 1 remote Traefik unit."
        return traefik_units[0]

    @property
    def _config(self) -> _RouteConfig:
        return _RouteConfig(rule=self.config.get("rule"), root_url=self.config.get("root_url"))  # type: ignore

    @property
    def rule(self) -> Optional[str]:
        """The Traefik rule this charm is responsible for configuring."""
        return self._config.rule

    @property
    def root_url(self) -> Optional[str]:
        """The advertised url for the charm requesting ingress."""
        return self._config.root_url

    def _render_config(
        self, model_name: str, unit_name: str, app_name: str, strip_prefix: bool = False
    ):
        return self._config.render(
            model_name=model_name,
            unit_name=unit_name,
            app_name=app_name,
            strip_prefix=strip_prefix,
        )

    def _on_config_changed(self, _):
        """Check the config; set an active status if all is good."""
        if not self._is_ready:
            # also checks self._is_configuration_valid
            return

        self._update()
        self.unit.status = ActiveStatus()

    @property
    def _is_configuration_valid(self):
        """This charm is available if it's correctly configured."""
        if not self._config.is_valid:
            self.unit.status = BlockedStatus("bad config; see logs for more")
            return False

        return True

    @property
    def _is_ready(self):
        # check that the charm config is ok
        if not self._is_configuration_valid:
            return False

        # validate IPU relation status
        ipu_relation = self._ipu_relation
        if not ipu_relation:
            self.unit.status = BlockedStatus("Awaiting to be related via ingress-per-unit.")
            return False
        if not self.ingress_per_unit.is_ready(ipu_relation):
            self.unit.status = BlockedStatus("ingress-per-unit relation is not ready.")
            return False

        # validate traefik-route relation status
        if not self._traefik_route_relation:
            self.unit.status = BlockedStatus(
                "traefik-route is not available yet. Relate traefik-route to traefik."
            )
            return False

        return True

    def _on_ingress_data_provided(self, event: IngressDataReadyEvent):
        """The route requirer (aka this charm) is ready.

        That is, it can forward to Traefik the config Traefik will need to provide ingress.
        """
        # ingress may be ready, but am I too?
        if not self._is_ready:
            return event.defer()

        logger.info(
            "TraefikRouteRequirerReadyEvent received. IPU ready; TR ready; Config OK; Relaying..."
        )
        self._update()
        self.unit.status = ActiveStatus()
        return None

    def _config_for_unit(self, unit_data: RequirerData) -> RouteConfig:
        """Get the _RouteConfig for the provided `unit_data`."""
        # we assume self.ingress_request is there; if not, you should probably
        # put this codepath behind:
        #   if self._is_ready()...
        unit_name = unit_data["name"]  # pyright: ignore
        model_name = unit_data["model"]  # pyright: ignore
        strip_prefix = bool(unit_data.get("strip-prefix", None))

        # sanity checks
        assert unit_name is not None, "remote unit did not provide its name"
        assert "/" in unit_name, unit_name

        return self._render_config(
            model_name=model_name,
            strip_prefix=strip_prefix,
            unit_name=unit_name.replace("/", "-"),
            app_name=unit_name.split("/")[0],
        )

    def _update(self):
        """Publish the urls to the units requesting it and configure traefik."""
        # we assume that self._is_ready().

        ingress: IngressPerUnitProvider = self.ingress_per_unit
        relation = self._ipu_relation

        unit_configs = []
        ready_units = filter(lambda unit_: ingress.is_unit_ready(relation, unit_), relation.units)  # type: ignore
        for unit in ready_units:  # units requesting ingress
            unit_data = ingress.get_data(self._ipu_relation, unit)  # type: ignore
            config_data = self._config_for_unit(unit_data)
            unit_config = self._generate_traefik_unit_config(config_data)
            unit_configs.append(unit_config)

            # we can publish the url to the unit immediately, but this might race
            # with traefik loading the config. Point is, we don't need Traefik to
            # tell us the url, but Traefik needs the config before it can start routing.
            # To be reconsidered if this leads to too much outage or bugs downstream.
            logger.info(
                f"publishing to {unit_data['name']}: {config_data.root_url}"  # pyright: ignore
            )
            ingress.publish_url(relation, unit_data["name"], config_data.root_url)  # type: ignore

        # merge configs?
        config = self._merge_traefik_configs(unit_configs)
        if self.traefik_route.is_ready():
            self.traefik_route.submit_to_traefik(config=config)

    @staticmethod
    def _generate_traefik_unit_config(route_config: RouteConfig) -> "UnitConfig":
        rule, service_name, url = (
            route_config.rule,
            route_config.service_name,
            route_config.root_url,
        )

        traefik_router_name = f"juju-{service_name}-router"
        traefik_service_name = f"juju-{service_name}-service"

        config = {
            "router": {
                "rule": rule,
                "service": traefik_service_name,
                "entryPoints": ["web"],
            },
            "router_name": traefik_router_name,
            "service": {"loadBalancer": {"servers": [{"url": url}]}},
            "service_name": traefik_service_name,
        }

        if route_config.strip_prefix:
            traefik_middleware_name = f"juju-sidecar-noprefix-{service_name}-service"
            config["middleware_name"] = traefik_middleware_name
            config["middleware"] = {"forceSlash": False, "prefixes": [f"/{service_name}"]}

        return cast("UnitConfig", config)

    @staticmethod
    def _merge_traefik_configs(configs: Iterable["UnitConfig"]) -> "TraefikConfig":
        middlewares = {
            config.get("middleware_name"): config.get("middleware")
            for config in configs
            if config.get("middleware")
        }
        traefik_config = {
            "http": {
                "routers": {config["router_name"]: config["router"] for config in configs},
                "services": {config["service_name"]: config["service"] for config in configs},
            }
        }
        if middlewares:
            traefik_config["http"]["middlewares"] = middlewares

        return traefik_config  # type: ignore


if __name__ == "__main__":
    main(TraefikRouteK8SCharm)
