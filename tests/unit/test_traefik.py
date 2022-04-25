import pytest

from route_config import RouteConfig
from traefik import generate_unit_config

CONFIG_NO_MIDDLEWARE = {
    "router_name": "juju-remote-0-model-router",
    "router": {
        "rule": "Host(`foo.bar/model-remote-0`)",
        "service": "juju-remote-0-model-service",
        "entryPoints": ["web"],
        "middlewares": []
    },
    "service_name": "juju-remote-0-model-service",
    "service": {"loadBalancer": {
        "servers": [{"url": "http://foo.bar/model-remote-0"}]}
    },
    "middlewares": {}
}
CONFIG_STRIP_PREFIX_MIDDLEWARE = {
    "router_name": "juju-remote-0-model-router",
    "router": {
        "rule": "Host(`foo.bar/model-remote-0`)",
        "service": "juju-remote-0-model-service",
        "entryPoints": ["web"],
        "middlewares": ["juju-strip_model-remote-0-stripprefix"]
    },
    "service_name": "juju-remote-0-model-service",
    "service": {"loadBalancer": {
        "servers": [{"url": "http://foo.bar/model-remote-0"}]}
    },
    "middlewares": {
        "juju-strip_model-remote-0-stripprefix":
            {
                'stripPrefix': {
                    'prefixes': ["/strip_model-remote-0"],
                }
            }
    }
}


@pytest.mark.parametrize("route_config,expected_traefik_unit_config", (
        (RouteConfig(root_url="http://foo.bar/model-remote-0",
                     rule="Host(`foo.bar/model-remote-0`)",
                     id_="remote-0-model",
                     ), CONFIG_NO_MIDDLEWARE),
        (RouteConfig(root_url="http://foo.bar/model-remote-0",
                     rule="Host(`foo.bar/model-remote-0`)",
                     id_="remote-0-model",
                     strip_prefix="strip_model-remote-0",
                     ), CONFIG_STRIP_PREFIX_MIDDLEWARE),

))
def test_generate_unit_config(route_config, expected_traefik_unit_config):
    assert generate_unit_config(route_config) == expected_traefik_unit_config
