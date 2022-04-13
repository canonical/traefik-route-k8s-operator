#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import contextlib
import logging
import urllib.request
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
    assert ops_test.model.applications[APP_NAME].units[
               0].workload_status == status


@contextlib.asynccontextmanager
async def fast_forward(ops_test, interval: str = '10s'):
    # speed up update-status firing
    await ops_test.model.set_config({"update-status-hook-interval": interval})
    yield
    await ops_test.model.set_config({"update-status-hook-interval": "60m"})


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    charm = await ops_test.build_charm(".")
    await ops_test.model.deploy(charm, application_name=APP_NAME)


async def test_unit_blocked_on_deploy(ops_test: OpsTest):
    async with fast_forward(ops_test):
        # Route will go to blocked until configured
        await wait_for(ops_test, 'blocked')


async def test_unit_active_after_config(ops_test: OpsTest):
    # configure
    root_url = "http://foo.bar{{juju_unit}}/"
    await ops_test.juju(*f"config {APP_NAME}/0 root_url={root_url}".split(" "))

    # now we'll get to active
    async with fast_forward(ops_test):
        await wait_for(ops_test, 'active')


@pytest.mark.abort_on_fail
async def test_application_is_up(ops_test: OpsTest):
    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][APP_NAME]["units"][f"{APP_NAME}/0"][
        "address"]

    url = f"http://{address}"

    logger.info("querying app address: %s", url)
    response = urllib.request.urlopen(url, data=None, timeout=2.0)
    assert response.code == 200
