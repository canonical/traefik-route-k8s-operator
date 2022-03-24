#!/usr/bin/env python3
# Copyright 2022 pietro
# See LICENSE file for licensing details.

"""Charm the service.

"""

import logging
from typing import Optional

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Relation, WaitingStatus
from charms.traefik_k8s.v0.ingress_per_unit import IngressPerUnitProvider
from charms.traefik_route_k8s.v0.traefik_route import TraefikRouteRequirer

logger = logging.getLogger(__name__)


class TraefikRouteK8SCharm(CharmBase):
    """Charm the service."""
    _ingress_endpoint = 'ingress'
    _traefik_route_endpoint = 'traefik_route'

    def __init__(self, *args):
        super().__init__(*args)

        self.ingress_per_unit = IngressPerUnitProvider(self,
                                                       self._ingress_endpoint)
        self.traefik_route = TraefikRouteRequirer(self,
                                                  self._traefik_route_endpoint)
        if url := self.traefik_route.proxied_endpoint:
            self.ingress_per_unit.get_request(self._ipu_relation).respond(
                self.unit, url)

        observe = self.framework.observe
        observe(self.on.config_changed, self._on_config_changed)
        observe(self.ingress_per_unit.on.request, self._on_ingress_request)

    @property
    def _ipu_relation(self) -> Optional[Relation]:
        return self.model.relations.get(self._ingress_endpoint, None)

    @property
    def rule(self) -> Optional[str]:
        """The Traefik rule this charm is responsible for configuring."""
        return self.config.get("rule", None)

    def _on_config_changed(self, _):
        """Check the config; set an active status if all is good."""
        error = self._check_config(**self._traefik_config)

        if error:
            self.unit.status = BlockedStatus(error)
            return

        self.unit.status = ActiveStatus()

    @property
    def _traefik_config(self):
        """Extract from the charm config the keys that are meant for traefik."""
        return {'rule': self.rule}

    def _check_config(self, rule) -> Optional[str]:
        # TODO: think about further validating `rule` (regex?)

        error = None
        # None or empty string or whitespace-only string
        if not rule or not rule.strip():
            error = (f"`rule` not configured; do `juju config {self.unit.name} "
                     f"rule=<RULE>;juju resolve {self.unit.name}`")

        if rule != (stripped := rule.strip()):
            error = (f"Rule {rule!r} starts or ends with whitespace;"
                     f"it should be {stripped!r}.")

        if error:
            logger.error(error)

        return error

    def _on_ingress_request(self, event):
        if not self._ipu_relation:
            self.unit.status = BlockedStatus(
                f"Ingress requested, but ingress-per-unit relation is "
                f"not available."
            )
            return event.defer()
        elif self.ingress_per_unit.is_failed:
            self.unit.status = BlockedStatus(
                f"Ingress requested, but ingress-per-unit relation is"
                f"broken (failed)."
            )
            return event.defer()
        elif not self.ingress_per_unit.is_available:
            self.unit.status = WaitingStatus(
                f"ingress-per-unit is not available yet.")
            return event.defer()

        logger.info('Ingress request event received. IPU ready; Relaying...')
        ingress_request = self.ingress_per_unit.get_request(self._ipu_relation)
        self.traefik_route.relay_ingress_request(
            ingress=dict(model=ingress_request.model,
                         unit=ingress_request.units[0]  # it's a 1:1 relation.
                         ),
            config=self._traefik_config
        )


if __name__ == "__main__":
    main(TraefikRouteK8SCharm)
