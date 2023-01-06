#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import textwrap
import unittest

import ops
from charms.traefik_route_k8s.v0.traefik_route import TraefikRouteProvider, TraefikRouteProviderReadyEvent, TraefikRouteProviderDataRemovedEvent
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.testing import Harness
from charms.harness_extensions.v0.capture_events import capture

ops.testing.SIMULATE_CAN_CONNECT = True


class DummyProviderCharm(CharmBase):
    """Mimic functionality needed to test the provider."""

    # define custom metadata - without this the harness would parse the metadata.yaml in this repo,
    # which would result in expressions like self.harness.model.app.name to return
    # "traefik-route-k8s", which is not what we want in a provider test
    metadata_yaml = textwrap.dedent(
        """
        name: DummyProviderCharm
        provides:
          traefik-route:
            interface: traefik_route
        """
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        # relation name must match metadata
        self.traefik_route = TraefikRouteProvider(self, relation_name="traefik-route")


class TestProviderEvents(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(DummyProviderCharm, meta=DummyProviderCharm.metadata_yaml)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

    def _relate_to_consumer(self, name: str = "consumer-app") -> int:
        """Create relation between 'this app' (e.g. traefik) and a remote app (traefik-route)."""
        rel_id = self.harness.add_relation(relation_name="traefik-route", remote_app=name)
        self.harness.add_relation_unit(rel_id, f"{name}/0")
        return rel_id

    def test_custom_event_emitted_on_join(self):
        app = "trfk-rt"
        rel_id = self._relate_to_consumer(app)
        with capture(self.harness.charm, TraefikRouteProviderReadyEvent):
            self.harness.update_relation_data(rel_id, app, {"config": "blob"})

    def test_custom_event_emitted_on_depart(self):
        rel_id = self._relate_to_consumer()
        with capture(self.harness.charm, TraefikRouteProviderDataRemovedEvent):
            self.harness.remove_relation(rel_id)
