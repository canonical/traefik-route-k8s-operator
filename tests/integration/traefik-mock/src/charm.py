#!/usr/bin/env python3
# Copyright 2022 pietro
# See LICENSE file for licensing details.

"""Charm the service."""

import logging

from charms.traefik_route_k8s.v0.traefik_route import TraefikRouteProvider
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Model, WaitingStatus

logger = logging.getLogger(__name__)


class TraefikMockCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)
        if not self.unit.is_leader():
            self.unit.status = BlockedStatus("no leadership")
            return

        traefik_route = TraefikRouteProvider(charm=self)
        model: Model = self.model
        tr_relations = model.relations.get("traefik-route")

        if tr_relations:
            tr_relation = tr_relations[0]
            if traefik_route.is_ready(tr_relation):
                config = traefik_route.get_config(tr_relation)
                if config:
                    self.unit.status = ActiveStatus("all good!")
                else:
                    self.unit.status = BlockedStatus("no config!")
            else:
                self.unit.status = WaitingStatus("traefik-route not ready yet")
        else:
            self.unit.status = BlockedStatus("traefik-route not related")


if __name__ == "__main__":
    main(TraefikMockCharm)
