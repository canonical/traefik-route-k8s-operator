#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import Mock

import pytest
import yaml
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import TraefikRouteK8SCharm
from tests.unit.conftest import (
    REMOTE_UNIT_NAME,
    SAMPLE_INGRESS_DATA_ENCODED,
    mock_config,
    mock_happy_path,
)

EXPECTED_TRAEFIK_CONFIG = {
    "http": {
        "routers": {
            "juju-remote-0-model-router": {
                "rule": "Host(`foo.bar/model-remote-0`)",
                "service": "juju-remote-0-model-service",
                "entryPoints": ["web"],
            }
        },
        "services": {
            "juju-remote-0-model-service": {
                "loadBalancer": {"servers": [{"url": "http://foo.bar/model-remote-0"}]}
            }
        },
    }
}


def test_baseline(harness: Harness[TraefikRouteK8SCharm]):
    charm = harness.charm

    assert not charm._config.is_valid, "default config is not OK"
    assert isinstance(charm.unit.status, BlockedStatus)

    assert charm._ipu_relation is None
    assert charm._traefik_route_relation is None
    assert charm._remote_routed_units == ()
    assert charm._remote_traefik_unit is None
    assert charm.rule is None


def test_blocked_status_on_default_config_changed(harness: Harness[TraefikRouteK8SCharm]):
    charm = harness.charm
    assert not charm._config.is_valid
    charm._on_config_changed(None)
    assert isinstance(charm.unit.status, BlockedStatus)


@pytest.mark.parametrize(
    "config, valid",
    (
        ({"root_url": ""}, False),
        ({"root_url": " http://foo.com"}, False),
        ({"root_url": "http://foo.com "}, False),
        ({"root_url": "http://foo.com"}, True),
        ({"root_url": "http://{{juju_unit}}.com"}, True),
        ({"root_url": "http://{{kadoodle}}.com"}, False),
    ),
)
def test_config_validity(harness: Harness[TraefikRouteK8SCharm], config: dict, valid: bool):
    harness.update_config(config)
    assert harness.charm._config.is_valid == valid
    assert harness.charm._is_configuration_valid == valid


def test_blocked_status_on_bad_config(harness: Harness[TraefikRouteK8SCharm]):
    charm = harness.charm
    harness.update_config({"root_url": " ! "})
    assert isinstance(charm.unit.status, BlockedStatus)


def test_active_status_on_good_config(harness: Harness[TraefikRouteK8SCharm]):
    charm = harness.charm
    mock_config(harness)  # this will call on_config_changed
    assert charm._config.is_valid
    assert charm._is_configuration_valid
    assert not charm._is_ready
    assert isinstance(charm.unit.status, BlockedStatus)


def test_ingress_request_relaying_preconditions(harness: Harness[TraefikRouteK8SCharm]):
    """Check that in happy-path scenario all is set up for relaying."""
    ipu_relation_id, route_relation_id = mock_happy_path(harness)
    charm = harness.charm

    assert charm.unit.is_leader()
    assert (ipu_relation := charm._ipu_relation)
    assert not charm.ingress_per_unit.is_failed(ipu_relation)
    assert charm.ingress_per_unit.is_available(ipu_relation)
    assert not charm.ingress_per_unit.is_ready(ipu_relation)  # nothing's been shared yet

    tr_relation = charm.traefik_route._relation
    assert tr_relation.data[tr_relation.app] == {}

    assert isinstance(charm.unit.status, ActiveStatus)


def test_on_ingress_request_called(harness: Harness[TraefikRouteK8SCharm]):
    """Test that _on_ingress_ready is being called on ipu relation change."""
    ipu_relation_id, route_relation_id = mock_happy_path(harness)
    charm = harness.charm

    # check that _on_ingress_ready would have been called
    # original_ingress_request = charm._on_ingress_ready
    charm._on_ingress_ready = Mock(return_value=None)
    # simulate the remote unit setting ingress data, as it would in response
    # to ingress-per-unit-relation-joined
    harness.update_relation_data(ipu_relation_id, REMOTE_UNIT_NAME, SAMPLE_INGRESS_DATA_ENCODED)
    assert charm._on_ingress_ready.called
    assert charm.ingress_per_unit.is_ready(charm._ipu_relation)


def test_ingress_submit_to_traefik_called(harness: Harness[TraefikRouteK8SCharm]):
    """Test the charm's relaying functionality.

    Check that if an ingress request comes up in the ingress-per-unit databag
    it gets pushed to the traefik_route databag.
    """
    ipu_relation_id, route_relation_id = mock_happy_path(harness)
    charm = harness.charm

    # check that submit_to_traefik would have been called
    charm.traefik_route.submit_to_traefik = Mock(return_value=None)

    harness.update_relation_data(ipu_relation_id, REMOTE_UNIT_NAME, SAMPLE_INGRESS_DATA_ENCODED)
    charm.traefik_route.submit_to_traefik.assert_called_with(config=EXPECTED_TRAEFIK_CONFIG)


def test_ingress_request_forwarding_data(harness: Harness[TraefikRouteK8SCharm]):
    """Test the charm's relaying functionality.

    Check that if an ingress request comes up in the ingress-per-unit databag
    it gets pushed to the traefik_route databag.
    """
    ipu_relation_id, route_relation_id = mock_happy_path(harness)
    charm = harness.charm

    # remote app requesting ingress: publish ingress data
    harness.update_relation_data(ipu_relation_id, REMOTE_UNIT_NAME, SAMPLE_INGRESS_DATA_ENCODED)
    route_data = charm.traefik_route._relation.data
    assert route_data.get(charm.unit) == {}
    assert yaml.safe_load(route_data[charm.app]["config"]) == EXPECTED_TRAEFIK_CONFIG
