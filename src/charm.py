#!/usr/bin/env python3
# Copyright 2022 pietro
# See LICENSE file for licensing details.

"""Charm the service.

"""

import logging
import typing
from typing import Optional, Sequence

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Relation, WaitingStatus, Unit
from charms.traefik_k8s.v0.ingress_per_unit import IngressPerUnitProvider, \
    IngressRequest
from charms.traefik_route_k8s.v0.traefik_route import TraefikRouteRequirer, \
    TraefikRouteIngressReadyEvent

logger = logging.getLogger(__name__)


class _HasUnits(typing.Protocol):
    @property
    def units(self) -> typing.Sequence[Unit]:
        pass


def _check_has_one_unit(obj: _HasUnits):
    """Checks that the obj has exactly one unit."""
    if not obj.units:
        logger.error(f"{obj} has no units")
        return False
    if len(obj.units) > 1:
        logger.error(f"{obj} has too many units")
        return False
    return True


class TraefikRouteK8SCharm(CharmBase):
    """Charm the service."""
    _ingress_endpoint = 'ingress_per_unit'
    _traefik_route_endpoint = 'traefik_route'

    def __init__(self, *args):
        super().__init__(*args)

        self.ingress_per_unit = IngressPerUnitProvider(
            self, self._ingress_endpoint)
        self.traefik_route = TraefikRouteRequirer(
            self, self._traefik_route_endpoint)

        # if the remote app (traefik) has published the url: we give it
        # forward to the charm who's requesting ingress.
        if url := self.traefik_route.proxied_endpoint:
            self.ingress_per_unit.get_request(self._ipu_relation).respond(
                self.unit, url)

        observe = self.framework.observe
        observe(self.on.config_changed, self._on_config_changed)
        observe(self.ingress_per_unit.on.request, self._on_ingress_request)
        observe(self.traefik_route.on.ingress_ready, self._on_ingress_ready)

    def _get_relation(self, endpoint: str) -> Optional[Relation]:
        """Fetches the Relation for endpoint and checks that there's only 1."""
        relations = self.model.relations.get(endpoint)
        if not relations:
            logger.info(f"no relations yet for {endpoint}")
            return None
        if len(relations) > 1:
            logger.warning(f"more than one relation for {endpoint}")
        return relations[0]

    @property
    def _ipu_relation(self) -> Optional[Relation]:
        return self._get_relation(self._ingress_endpoint)

    @property
    def _remote_traefik_unit(self) -> Optional[Unit]:
        """The traefik unit providing ingress."""
        if not self._traefik_route_relation:
            return None
        if not _check_has_one_unit(self._traefik_route_relation):
            return None
        return next(iter(self._traefik_route_relation.units))

    @property
    def _traefik_route_relation(self) -> Optional[Relation]:
        return self._get_relation(self._traefik_route_endpoint)

    @property
    def _remote_routed_unit(self) -> Optional[Unit]:
        """The remote unit in need of ingress."""
        if not self._ipu_relation:
            return None
        if not _check_has_one_unit(self._ipu_relation):
            return None
        return next(iter(self._ipu_relation.units))

    @property
    def ingress_request(self) -> Optional[IngressRequest]:
        """Get the request for ingress, if ingress_per_unit is active."""
        if ipu := self._ipu_relation:
            return self.ingress_per_unit.get_request(ipu)

    @property
    def rule(self) -> Optional[str]:
        """The Traefik rule this charm is responsible for configuring."""
        return self.config.get("rule", None)

    def _on_config_changed(self, _):
        """Check the config; set an active status if all is good."""
        error = self._check_config(**self._traefik_config)

        if error:
            # we block until the user fixes the config
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

        elif rule != (stripped := rule.strip()):
            error = (f"Rule {rule!r} starts or ends with whitespace;"
                     f"it should be {stripped!r}.")

        if error:
            logger.error(error)

        return error

    def _on_ingress_request(self, event):
        # validate config
        error = self._check_config(**self._traefik_config)
        if error:
            logger.error(f"cannot process ingress request: {error}")
            self.unit.status = BlockedStatus(
                f"cannot process ingress request: {error}"
            )
            return event.defer()

        # validate relation statuses
        ipu_relation = self._ipu_relation
        if not ipu_relation:
            self.unit.status = BlockedStatus(
                f"Ingress requested, but ingress-per-unit relation is "
                f"not available."
            )
            return event.defer()
        elif self.ingress_per_unit.is_failed(ipu_relation):
            self.unit.status = BlockedStatus(
                f"Ingress requested, but ingress-per-unit relation is"
                f"broken (failed)."
            )
            return event.defer()
        elif not self.ingress_per_unit.is_available(ipu_relation):
            self.unit.status = WaitingStatus(
                f"ingress-per-unit is not available yet.")
            return event.defer()

        logger.info('Ingress request event received. IPU ready; Relaying...')

        # ingress_request should not be None since ipu is available.
        ingress_request: IngressRequest = self.ingress_request
        _check_has_one_unit(ingress_request)

        # it's a 1:1 relation, we can assume there's only one unit
        # but we do cowardly check after all
        if not (no_units := len(ingress_request.units)) == 0:
            logger.warning(f"Illegal number of units requesting ingress: {no_units}")

        ingress = ingress_request._data[ingress_request.units[0]]
        self.traefik_route.relay_ingress_request(
            ingress={'data': ingress},
            config=self._traefik_config
        )

    def _on_ingress_ready(self, event: TraefikRouteIngressReadyEvent):
        """Traefik has published ingress data via `traefik_route`.

        We are going to publish it forward to the charm requesting ingress via
        ingress_per_unit.
        """
        ingress_request: IngressRequest = self.ingress_request
        remote_unit_name = ingress_request._data[ingress_request.units[0]]['name']

        remote_unit_ingress_data = event.ingress.get(remote_unit_name)
        if not remote_unit_ingress_data:
            logger.debug(f'ingress is ready but no ingress for '
                         f'{remote_unit_name} has been shared yet; '
                         f'deferring ingress_ready')
            self.unit.status = WaitingStatus('Waiting for ingress...')
            return event.defer()

        # should we be checking that it is a dict?
        url = remote_unit_ingress_data.get('url')
        if not url:
            logger.debug(f'traefik shared ingress data for {remote_unit_name}; '
                         f'but it has an unexpected format. '
                         f'{remote_unit_ingress_data!r}')
            self.unit.status = BlockedStatus(
                f"Traefik shared badly formatted data."
            )
            return

        self.ingress_request.respond(self._remote_traefik_unit, url)


if __name__ == "__main__":
    main(TraefikRouteK8SCharm)
