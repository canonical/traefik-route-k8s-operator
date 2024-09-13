import pytest
import yaml
from scenario import Context, Relation, State

from charm import TraefikRouteK8SCharm


@pytest.fixture
def ctx():
    return Context(TraefikRouteK8SCharm)


@pytest.mark.parametrize("strip_prefix", (True, False))
def test_config_generation(ctx, strip_prefix):
    ipu = Relation(
        "ingress-per-unit",
        remote_units_data={
            0: {
                "port": "81",
                "host": "foo.com",
                "model": "mymodel",
                "name": "MimirMcPromFace/0",
                "mode": "http",
                "strip-prefix": "true" if strip_prefix else "false",
                "redirect-https": "true",
                "scheme": "http",
            }
        },
        remote_app_name="prometheus",
    )

    route = Relation("traefik-route", remote_app_name="traefik")

    state = State(
        leader=True,
        config={
            "root_url": "{{juju_model}}-{{juju_unit}}.foo.bar/baz",
            "rule": "Host(`{{juju_unit}}.bar.baz`)",
        },
        relations=[ipu, route],
    )

    state_out = ctx.run(ipu.changed_event, state)
    route_out = state_out.get_relations("traefik-route")[0]
    strip_prefix_cfg = {
        "middlewares": {
            "juju-sidecar-noprefix-MimirMcPromFace-0-mymodel-service": {
                "forceSlash": False,
                "prefixes": ["/MimirMcPromFace-0-mymodel"],
            }
        }
    }
    raw_expected_cfg = {
        "http": {
            "routers": {
                "juju-MimirMcPromFace-0-mymodel-router": {
                    "entryPoints": ["web"],
                    "rule": "Host(`MimirMcPromFace-0.bar.baz`)",
                    "service": "juju-MimirMcPromFace-0-mymodel-service",
                }
            },
            "services": {
                "juju-MimirMcPromFace-0-mymodel-service": {
                    "loadBalancer": {"servers": [{"url": "mymodel-MimirMcPromFace-0.foo.bar/baz"}]}
                }
            },
            **(strip_prefix_cfg if strip_prefix else {}),
        }
    }

    assert route_out.local_app_data == {"config": yaml.safe_dump(raw_expected_cfg)}
