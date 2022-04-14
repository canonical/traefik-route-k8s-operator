#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from pytest_operator.plugin import OpsTest


async def test_deploy_traefik_mock(ops_test: OpsTest, traefik_mock_charm):
    await ops_test.model.deploy(traefik_mock_charm)


async def test_deploy_ingress_requirer_mock(ops_test: OpsTest,
                                            ingress_requirer_mock_charm):
    await ops_test.model.deploy(ingress_requirer_mock_charm)
