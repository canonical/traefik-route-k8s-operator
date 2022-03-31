# Copyright 2022 pietro
# See LICENSE file for licensing details.
import json
from functools import cached_property
from inspect import getmembers

import pytest as pytest
from ops.testing import Harness

from charm import TraefikRouteK8SCharm

MODEL_NAME = 'model'
REMOTE_APP_NAME = 'remote'  # the app requesting ingress
REMOTE_UNIT_NAME = f'{REMOTE_APP_NAME}/0'  # the unit requesting ingress
TRAEFIK_APP_NAME = 'traefik'  # the app providing ingress
TRAEFIK_UNIT_NAME = f'{TRAEFIK_APP_NAME}/0'  # the unit providing ingress
SAMPLE_RULE = 'Host(`foo.bar/{{juju_model}}-{{juju_unit}}`)'
SAMPLE_CONFIG = {'rule': SAMPLE_RULE}

# mock of the data that the unit requesting ingress might share
# when requesting ingress; as implemented by ipuRequirer
SAMPLE_INGRESS_DATA = {
    'data': {
        'model': MODEL_NAME,
        'name': REMOTE_UNIT_NAME,
        'host': 'foo',
        'port': 42
    }
}
SAMPLE_INGRESS_DATA_ENCODED = {
    'data': json.dumps(SAMPLE_INGRESS_DATA['data'])
}
# mock of the data traefik might share when providing ingress to our remote unit
SAMPLE_TRAEFIK_DATA = {
    'data': {
        REMOTE_UNIT_NAME: {'url': 'https://foo.bar/baz'}
    }
}
SAMPLE_TRAEFIK_DATA_ENCODED = {
    'data': json.dumps(SAMPLE_TRAEFIK_DATA['data'])
}



# @pytest.hookimpl(hookwrapper=True)
@pytest.fixture(autouse=True, scope='session')
def disable_caching():
    # We use the caching helpers from functools to save recalculations, but during
    # tests they can interfere with seeing the updated state, so we strip them off.
    is_cp = lambda v: isinstance(v, cached_property)  # noqa: E731
    # functool's lru_cache
    is_cf = lambda v: hasattr(v, "cache_clear")  # noqa: E731

    from charms.traefik_k8s.v0 import ingress_per_unit
    classes = (ingress_per_unit.IPUBase,
               ingress_per_unit.IngressPerUnitRequirer,
               ingress_per_unit.IngressPerUnitRequirer)

    for cls in classes:
        for attr, prop in getmembers(cls, lambda v: is_cp(v) or is_cf(v)):
            if is_cp(prop):
                setattr(cls, attr, property(prop.func))
            else:
                setattr(cls, attr, prop.__wrapped__)

            print(f'cleaned up: {attr}')

    yield

    # todo: undo if we ever want to test something **with caching**


@pytest.fixture
def harness() -> Harness[TraefikRouteK8SCharm]:
    harness = Harness(TraefikRouteK8SCharm)
    harness.set_leader(True)  # this charm can't be scaled
    harness.begin_with_initial_hooks()
    yield harness
    harness.cleanup()


@pytest.fixture
def charm(harness):
    return harness.charm


def mock_ipu_relation(harness):
    # mock ipu relation
    ipu_relation_id = harness.add_relation(
        TraefikRouteK8SCharm._ingress_endpoint, REMOTE_APP_NAME)
    harness.add_relation_unit(ipu_relation_id, REMOTE_UNIT_NAME)
    return ipu_relation_id


def mock_route_relation(harness):
    # mock traefik_route relation
    route_relation_id = harness.add_relation(
        TraefikRouteK8SCharm._traefik_route_endpoint, TRAEFIK_APP_NAME)
    harness.add_relation_unit(route_relation_id, TRAEFIK_UNIT_NAME)
    return route_relation_id


def mock_config(harness):
    # init the config in a good way
    harness.update_config(SAMPLE_CONFIG)


def mock_happy_path(harness):
    # set the harness up in its 'happy path' scenario: all relations green,
    # config good.
    ipu_relation_id = mock_ipu_relation(harness)
    route_relation_id = mock_route_relation(harness)
    mock_config(harness)
    return ipu_relation_id, route_relation_id
