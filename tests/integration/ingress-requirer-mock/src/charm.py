#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm the service."""

import logging

from charms.traefik_k8s.v1.ingress_per_unit import IngressPerUnitRequirer
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus

logger = logging.getLogger(__name__)


class TraefikMockCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)
        if not self.unit.is_leader():
            self.unit.status = BlockedStatus("no leadership")
            return

        self.ingress = IngressPerUnitRequirer(charm=self, host="0.0.0.0", port=80)
        self.framework.observe(self.on.install, self._set_blocked)
        self.framework.observe(self.ingress.on.ready_for_unit, self._set_ready)
        self.framework.observe(self.ingress.on.revoked_for_unit, self._set_blocked)

    def _set_blocked(self, _):
        self.unit.status = BlockedStatus("no ingress")

    def _set_ready(self, _):
        self.unit.status = ActiveStatus("all good!")


if __name__ == "__main__":
    main(TraefikMockCharm)
