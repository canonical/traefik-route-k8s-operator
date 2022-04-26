#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm the service."""

import logging
from typing import Iterable, Optional, Tuple

from charms.traefik_k8s.v0.ingress_per_unit import IngressPerUnitProvider, RequirerData
from charms.traefik_route_k8s.v0.traefik_route import (
    TraefikRouteRequirer,
    TraefikRouteRequirerReadyEvent,
)
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Relation, Unit, WaitingStatus

# if typing.TYPE_CHECKING:
from route_config import RouteConfig, _RouteConfig
from traefik import TraefikConfig, UnitConfig, generate_unit_config, merge_configs

logger = logging.getLogger(__name__)


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
            self, self._traefik_route_relation, self._traefik_route_relation_name
        )

        observe = self.framework.observe
        observe(self.on.config_changed, self._on_config_changed)
        observe(self.ingress_per_unit.on.ready, self._on_ingress_ready)

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
    def _remote_routed_units(self) -> Tuple[Unit]:
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
        return _RouteConfig(
            rule=self.config.get("rule"),
            root_url=self.config.get("root_url"),
            strip_prefix=self.config.get("strip_prefix"),
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
        return self._config.render(model_name=model_name, unit_name=unit_name, app_name=app_name)

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
        elif self.ingress_per_unit.is_failed(ipu_relation):
            self.unit.status = BlockedStatus("ingress-per-unit relation is broken (failed).")
            return False
        elif not self.ingress_per_unit.is_available(ipu_relation):
            self.unit.status = WaitingStatus("ingress-per-unit is not available yet.")
            return False

        # validate traefik-route relation status
        if not self._traefik_route_relation:
            self.unit.status = BlockedStatus(
                "traefik-route is not available yet. Relate traefik-route to traefik."
            )
            return False

        return True

    def _on_ingress_ready(self, event: TraefikRouteRequirerReadyEvent):
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

    def _config_for_unit(self, unit_data: RequirerData) -> RouteConfig:
        """Get the _RouteConfig for the provided `unit_data`."""
        # we assume self.ingress_request is there; if not, you should probably
        # put this codepath behind:
        #   if self._is_ready()...
        unit_name = unit_data["name"]
        model_name = unit_data["model"]

        # sanity checks
        assert unit_name is not None, "remote unit did not provide its name"
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
        relation = self._ipu_relation

        unit_configs = []
        ready_units = filter(lambda unit_: ingress.is_unit_ready(relation, unit_), relation.units)
        for unit in ready_units:  # units requesting ingress
            unit_data = ingress.get_data(self._ipu_relation, unit)
            config_data = self._config_for_unit(unit_data)
            unit_config = generate_unit_config(config_data)
            unit_configs.append(unit_config)

            # we can publish the url to the unit immediately, but this might race
            # with traefik loading the config. Point is, we don't need Traefik to
            # tell us the url, but Traefik needs the config before it can start routing.
            # To be reconsidered if this leads to too much outage or bugs downstream.
            logger.info(f"publishing to {unit_data['name']}: {config_data.root_url}")
            ingress.publish_url(relation, unit_data["name"], config_data.root_url)

        config = merge_configs(unit_configs)
        if self.traefik_route.is_ready():
            self.traefik_route.submit_to_traefik(config=config)


if __name__ == "__main__":
    main(TraefikRouteK8SCharm)
