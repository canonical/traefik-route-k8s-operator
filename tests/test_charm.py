# Copyright 2022 pietro
# See LICENSE file for licensing details.
import json
from unittest.mock import Mock

from ops.model import ActiveStatus, BlockedStatus

from tests.conftest import (
    REMOTE_UNIT_NAME, SAMPLE_CONFIG, SAMPLE_INGRESS_DATA,
    mock_config, mock_happy_path, MODEL_NAME, TRAEFIK_UNIT_NAME,
    SAMPLE_TRAEFIK_DATA, TRAEFIK_APP_NAME, SAMPLE_INGRESS_DATA_ENCODED,
    SAMPLE_TRAEFIK_DATA_ENCODED
)


def test_baseline(harness, charm):
    assert charm._ipu_relation is None
    assert charm._traefik_route_relation is None
    assert charm._remote_routed_unit is None
    assert charm._remote_traefik_unit is None
    assert charm.rule is None


def test_blocked_status_on_default_config(harness, charm):
    assert charm._check_config(**charm._traefik_config)  # error present
    assert isinstance(charm.unit.status, BlockedStatus)


def test_active_status_on_good_config(harness, charm):
    mock_config(harness)
    assert charm._check_config(**charm._traefik_config) is None
    assert isinstance(charm.unit.status, ActiveStatus)


def test_ingress_request_relaying_preconditions(harness, charm):
    """Check that in happy-path scenario all is set up for relaying."""
    ipu_relation_id, route_relation_id = mock_happy_path(harness)

    assert charm.unit.is_leader()
    assert (ipu_relation := charm._ipu_relation)
    assert not charm.ingress_per_unit.is_failed(ipu_relation)
    assert charm.ingress_per_unit.is_available(ipu_relation)
    assert not charm.ingress_per_unit.is_ready(
        ipu_relation)  # nothing's been shared yet
    assert charm.traefik_route.relation.data[
               charm.traefik_route.relation.app] == {}
    assert isinstance(charm.unit.status, ActiveStatus)


def test_on_ingress_request_called(harness, charm):
    """ Test that _on_ingress_request is being called on ipu relation change."""
    ipu_relation_id, route_relation_id = mock_happy_path(harness)

    # remote app requesting ingress: publish ingress data
    ipu_relation = charm._ipu_relation
    remote_unit = next(iter(ipu_relation.units))

    # check that _on_ingress_request would have been called
    # original_ingress_request = charm._on_ingress_request
    charm._on_ingress_request = Mock(return_value=None)
    # simulate the remote unit setting ingress data, as it would in response
    # to ingress-per-unit-relation-joined
    harness.update_relation_data(ipu_relation_id, REMOTE_UNIT_NAME,
                                 SAMPLE_INGRESS_DATA_ENCODED)
    assert charm._on_ingress_request.called

    ingress_data = charm.ingress_per_unit._fetch_ingress_data(ipu_relation)
    assert ingress_data[remote_unit] == SAMPLE_INGRESS_DATA['data']
    assert charm.ingress_per_unit.is_ready(ipu_relation)

    # original_ingress_request(*charm._on_ingress_request.call_args[1:])


def test_ingress_request_relaying_called(harness, charm):
    """ Test the charm's relaying functionality.

    Check that if an ingress request comes up in the ingress-per-unit databag
    it gets pushed to the traefik_route databag."""
    ipu_relation_id, route_relation_id = mock_happy_path(harness)

    # remote app requesting ingress: publish ingress data
    remote_unit = next(iter(charm._ipu_relation.units))

    # check that relay_ingress_request would have been called
    original_relay_fn = charm.traefik_route.relay_ingress_request
    charm.traefik_route.relay_ingress_request = Mock(return_value=None)

    harness.update_relation_data(ipu_relation_id, REMOTE_UNIT_NAME,
                                 SAMPLE_INGRESS_DATA_ENCODED)
    charm.traefik_route.relay_ingress_request.assert_called_with(
            ingress=SAMPLE_INGRESS_DATA,
            config=SAMPLE_CONFIG,
    )


def test_ingress_request_forwarding_data(harness, charm):
    """ Test the charm's relaying functionality.

    Check that if an ingress request comes up in the ingress-per-unit databag
    it gets pushed to the traefik_route databag."""
    ipu_relation_id, route_relation_id = mock_happy_path(harness)

    # remote app requesting ingress: publish ingress data
    harness.update_relation_data(
        ipu_relation_id, REMOTE_UNIT_NAME, SAMPLE_INGRESS_DATA_ENCODED)
    route_data = charm.traefik_route.relation.data
    assert route_data.get(charm.unit) == {}
    assert json.loads(route_data[charm.app]['config']) == SAMPLE_CONFIG
    assert json.loads(route_data[charm.app]['ingress']) == SAMPLE_INGRESS_DATA


def test_ingress_response_flow(harness, charm):
    """Test that if traefik provides ingress, the route charm will correctly
    forward it to the charm requesting ingress.
    """

    ipu_relation_id, route_relation_id = mock_happy_path(harness)

    # remote app requesting ingress: publish ingress data
    harness.update_relation_data(
        ipu_relation_id, REMOTE_UNIT_NAME, SAMPLE_INGRESS_DATA_ENCODED)

    original_on_ingress_ready = charm._on_ingress_ready
    charm._on_ingress_ready = Mock(return_value=None)
    # traefik app responds by publishing ingress;
    # i.e. an URL for the unit requesting it
    harness.update_relation_data(
        route_relation_id, TRAEFIK_APP_NAME, SAMPLE_TRAEFIK_DATA_ENCODED)

    assert charm.ingress_per_unit.is_ready(charm._ipu_relation)
    # intercept and propagate
    assert charm._on_ingress_ready.called
    original_on_ingress_ready(*charm._on_ingress_ready.call_args[1:])

    assert charm.ingress_per_unit.proxied_endpoints

    # route_data = charm.traefik_route.relation.data
    # assert json.loads(route_data[charm.app]['ingress']) == SAMPLE_TRAEFIK_DATA_ENCODED


