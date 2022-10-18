#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import contextlib
import logging
import textwrap
from pathlib import Path

import pytest
import yaml
from juju.application import Application
from pytest_operator.plugin import OpsTest

from tests.integration.conftest import INGRESS_REQUIRER_MOCK_NAME, TRAEFIK_MOCK_NAME

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
MOCK_ROOT_URL_TEMPLATE = "http://{{juju_unit}}.foo/bar/"


async def assert_status_reached(ops_test, status: str, apps=(APP_NAME,), raise_on_blocked=True):
    print(f"waiting for {apps} to reach {status}...")

    await ops_test.model.wait_for_idle(
        apps=apps,
        status=status,
        timeout=180,
        raise_on_blocked=False if status == "blocked" else raise_on_blocked,
    )
    for app in apps:
        assert ops_test.model.applications[app].units[0].workload_status == status


@contextlib.asynccontextmanager
async def fast_forward(ops_test, interval: str = "10s"):
    # temporarily speed up update-status firing rate
    await ops_test.model.set_config({"update-status-hook-interval": interval})
    yield
    await ops_test.model.set_config({"update-status-hook-interval": "60m"})


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, traefik_route_charm):
    await ops_test.model.deploy(traefik_route_charm, application_name=APP_NAME, series="bionic")


async def test_unit_blocked_on_deploy(ops_test: OpsTest):
    async with fast_forward(ops_test):
        # Route will go to blocked until configured
        await assert_status_reached(ops_test, "blocked")


# both mock charms should start as blocked until they're related
async def test_deploy_traefik_mock(ops_test: OpsTest, traefik_mock_charm):
    await ops_test.model.deploy(
        traefik_mock_charm, application_name=TRAEFIK_MOCK_NAME, series="bionic"
    )
    await ops_test.model.wait_for_idle([TRAEFIK_MOCK_NAME], status="blocked")


async def test_deploy_ingress_requirer_mock(ops_test: OpsTest, ingress_requirer_mock_charm):
    await ops_test.model.deploy(
        ingress_requirer_mock_charm, application_name=INGRESS_REQUIRER_MOCK_NAME, series="bionic"
    )
    await ops_test.model.wait_for_idle([INGRESS_REQUIRER_MOCK_NAME], status="blocked")


async def test_unit_blocked_after_config(ops_test: OpsTest):
    # configure
    app: Application = ops_test.model.applications.get(APP_NAME)
    await app.set_config({"root_url": "http://foo/"})

    # now we're blocked still, because we have no relations.
    async with fast_forward(ops_test):
        await assert_status_reached(ops_test, "blocked")

    # cleanup!
    await app.reset_config(["root_url"])


async def test_relations(ops_test: OpsTest):
    # all is already deployed by now, so we should just be able to...
    await asyncio.gather(
        ops_test.model.add_relation(
            f"{TRAEFIK_MOCK_NAME}:traefik-route", f"{APP_NAME}:traefik-route"
        ),
        # prometheus' endpoint is called 'ingress',
        # but our mock charm calls it 'ingress-per-unit'
        ops_test.model.add_relation(
            f"{INGRESS_REQUIRER_MOCK_NAME}:ingress-per-unit", f"{APP_NAME}:ingress-per-unit"
        ),
    )

    async with fast_forward(ops_test):
        # route will go to blocked until it's configured properly
        # so let's make sure it's configured:
        await ops_test.juju("config", APP_NAME, f"root_url={MOCK_ROOT_URL_TEMPLATE}")
        # after this it will eventually reach active

        # both mock charms will go to WaitingStatus until their relation
        # interfaces are 'ready', but that's hard to test.
        # So we check straight away for active:
        await assert_status_reached(
            ops_test,
            apps=[APP_NAME, INGRESS_REQUIRER_MOCK_NAME, TRAEFIK_MOCK_NAME],
            status="active",
            # However, route was blocked moments ago, so it might still be blocked by the time
            # we start awaiting active; so we trust it will eventually unblock itself.
            raise_on_blocked=False,
        )


async def test_relation_data(ops_test: OpsTest):
    # check databag content to verify it's what we think it should be
    traefik_unit = TRAEFIK_MOCK_NAME + "/0"
    return_code, stdout, stderr = await ops_test.juju("show-unit", traefik_unit)
    data = yaml.safe_load(stdout)
    try:
        config = data[traefik_unit]["relation-info"][0]["application-data"]["config"]
    except Exception:
        print(return_code, stdout, stderr, data)
        raise

    model_name = ops_test.model_name
    unit_name = INGRESS_REQUIRER_MOCK_NAME + "-0"
    url = MOCK_ROOT_URL_TEMPLATE.replace("{{juju_unit}}", unit_name)

    expected_config = textwrap.dedent(
        f"""
    http:
      routers:
        juju-{unit_name}-{model_name}-router:
          entryPoints:
          - web
          rule: Host(`{unit_name}.foo`)
          service: juju-{unit_name}-{model_name}-service
      services:
        juju-{unit_name}-{model_name}-service:
          loadBalancer:
            servers:
            - url: {url}
    """
    )
    assert config.strip() == expected_config.strip(), config
