#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import contextlib
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]


async def assert_status_reached(ops_test, status: str, apps=(APP_NAME,)):
    await ops_test.model.wait_for_idle(
        apps=apps,
        status=status,
        timeout=1000,
        raise_on_blocked=False if status == "blocked" else True,
    )
    assert ops_test.model.applications[APP_NAME].units[0].workload_status == status


@contextlib.asynccontextmanager
async def fast_forward(ops_test, interval: str = "10s"):
    # temporarily speed up update-status firing rate
    await ops_test.model.set_config({"update-status-hook-interval": interval})
    yield
    await ops_test.model.set_config({"update-status-hook-interval": "60m"})


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, traefik_route_charm):
    await ops_test.model.deploy(traefik_route_charm, application_name=APP_NAME)


async def test_unit_blocked_on_deploy(ops_test: OpsTest):
    async with fast_forward(ops_test):
        # Route will go to blocked until configured
        await assert_status_reached(ops_test, "blocked")


async def test_unit_blocked_after_config(ops_test: OpsTest):
    # configure
    root_url = "http://foo.bar{{juju_unit}}/"
    await ops_test.juju("config", APP_NAME, "root_url=" + root_url)

    # now we're blocked still
    async with fast_forward(ops_test):
        await assert_status_reached(ops_test, "blocked")


def test_relations(
    ops_test: OpsTest,
    traefik_mock_charm,
    traefik_mock_name,
    ingress_requirer_mock_charm,
    ingress_requirer_mock_name,
):
    await ops_test.model.deploy(traefik_mock_charm, application_name=traefik_mock_name)
    await ops_test.model.deploy(
        ingress_requirer_mock_charm, application_name=ingress_requirer_mock_name
    )

    # route is already deployed by now, so we should just be able to...
    await ops_test.model.add_relation(
        f"{traefik_mock_name}:traefik-route", f"{APP_NAME}:traefik-route"
    )

    # prometheus' endpoint is called 'ingress',
    # but our mock charm calls it 'ingress-per-unit'
    await ops_test.model.add_relation(
        f"{ingress_requirer_mock_name}:ingress-per-unit", f"{APP_NAME}:ingress-per-unit"
    )

    async with fast_forward(ops_test):
        # route will go to blocked until it's configured properly
        await assert_status_reached(ops_test, apps=[APP_NAME], status="blocked")

        # let's configure it:
        root_url = "http://foo.bar.{{juju_unit}}/"
        await ops_test.juju("config", APP_NAME, "root_url=" + root_url)

        # both mock charms will go to WaitingStatus until their relation
        # interfaces are 'ready', but that's hard to test.
        # So we check straight away for active:
        await assert_status_reached(
            ops_test,
            apps=[APP_NAME, ingress_requirer_mock_name, traefik_mock_name],
            status="active",
        )

        # todo check databag content to verify it's what we think it should be
