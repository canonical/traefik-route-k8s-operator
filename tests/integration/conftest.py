#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import shutil
from os import unlink

import pytest
import pytest_asyncio
from pytest_operator.plugin import OpsTest, check_deps

TRAEFIK_MOCK_NAME = "traefik-mock"

INGRESS_REQUIRER_MOCK_NAME = "ingress-requirer-mock"


@pytest.fixture(scope="session", autouse=True)
def copy_route_lib_to_tester_charm():
    library_path = "lib/charms/traefik_route_k8s/v0/traefik_route.py"
    install_path = f"tests/integration/traefik-mock/{library_path}"
    shutil.copyfile(library_path, install_path)
    yield
    # be nice and clean up
    unlink(install_path)


@pytest.fixture(scope="session", autouse=True)
def copy_ingress_lib_to_tester_charm():
    library_path = "lib/charms/traefik_k8s/v1/ingress_per_unit.py"
    install_path = f"tests/integration/ingress-requirer-mock/{library_path}"
    shutil.copyfile(library_path, install_path)
    yield
    # be nice and clean up
    unlink(install_path)


@pytest.mark.abort_on_fail
@pytest_asyncio.fixture
async def traefik_route_charm(ops_test: OpsTest):
    return await ops_test.build_charm(".")


@pytest.mark.abort_on_fail
@pytest_asyncio.fixture
async def traefik_mock_charm(ops_test: OpsTest):
    return await ops_test.build_charm("./tests/integration/traefik-mock")


@pytest.mark.abort_on_fail
@pytest_asyncio.fixture
async def ingress_requirer_mock_charm(ops_test: OpsTest):
    return await ops_test.build_charm("./tests/integration/ingress-requirer-mock")


@pytest_asyncio.fixture(scope="module")
async def ops_test(request, tmp_path_factory):
    check_deps("juju", "charmcraft")
    ops_test = OpsTest(request, tmp_path_factory)
    await ops_test._setup_model()
    OpsTest._instance = ops_test
    yield ops_test
    OpsTest._instance = None
