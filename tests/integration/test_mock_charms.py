#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from pytest_operator.plugin import OpsTest


async def test_deploy_traefik_mock(ops_test: OpsTest, traefik_mock_charm, traefik_mock_name):
    await ops_test.model.deploy(traefik_mock_charm, application_name=traefik_mock_name)


async def test_deploy_ingress_requirer_mock(
    ops_test: OpsTest, ingress_requirer_mock_charm, ingress_requirer_mock_name
):
    await ops_test.model.deploy(
        ingress_requirer_mock_charm, application_name=ingress_requirer_mock_name
    )


# both mock charms should start as blocked until they're related
async def test_traefik_mock_initial_status_blocked(ops_test: OpsTest, traefik_mock_name):
    assert await ops_test.model.wait_for_idle(
        [traefik_mock_name], status="blocked", raise_on_blocked=False
    )


async def test_ingress_requirer_mock_initial_status_blocked(
    ops_test: OpsTest, ingress_requirer_mock_name
):
    assert await ops_test.model.wait_for_idle(
        [ingress_requirer_mock_name], status="blocked", raise_on_blocked=False
    )
