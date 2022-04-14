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


async def wait_for(ops_test, status):
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status=status,
        timeout=1000,
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
        await wait_for(ops_test, "blocked")


async def test_unit_blocked_after_config(ops_test: OpsTest):
    # configure
    root_url = "http://foo.bar{{juju_unit}}/"
    await ops_test.juju("config", APP_NAME, "root_url=" + root_url)

    # now we're blocked still
    async with fast_forward(ops_test):
        await wait_for(ops_test, "blocked")


async def test_unit_related_active(ops_test: OpsTest):
    # configure
    root_url = "http://foo.bar{{juju_unit}}/"
    await ops_test.juju("config", APP_NAME, "root_url=" + root_url)

    # todo: should we be pinning some versions to test with,
    #  or develop our own tester charms?
    await ops_test.juju("deploy", "prometheus-k8s", "--channel", "edge")
    await ops_test.juju("deploy", "")
    await ops_test.juju("config", "traefik-k8s", "external_hostname=foo.bar")

    await ops_test.juju("relate", "prometheus-k8s", APP_NAME)
    await ops_test.juju("relate", "traefik-k8s", APP_NAME)

    # now we'll get to active
    async with fast_forward(ops_test):
        await wait_for(ops_test, "active")
