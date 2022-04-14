import shutil
from os import unlink

import pytest
from pytest_operator.plugin import OpsTest


@pytest.fixture(scope="session")
def traefik_mock_name():
    return "traefik-mock"


@pytest.fixture(scope="session")
def ingress_requirer_mock_name():
    return "ingress-requirer-mock"


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
    library_path = "lib/charms/traefik_k8s/v0/ingress_per_unit.py"
    install_path = f"tests/integration/ingress-requirer-mock/{library_path}"
    shutil.copyfile(library_path, install_path)
    yield
    # be nice and clean up
    unlink(install_path)


# only pack charms once
@pytest.fixture(scope="session")
def session_scoped_ops_test(request, tmp_path_factory):
    return OpsTest(request, tmp_path_factory)


@pytest.mark.abort_on_fail
@pytest.fixture(scope="session")
def traefik_route_charm(session_scoped_ops_test: OpsTest):
    charm = await session_scoped_ops_test.build_charm(".")


@pytest.mark.abort_on_fail
@pytest.fixture(scope="session")
def traefik_mock_charm(session_scoped_ops_test: OpsTest):
    charm = await session_scoped_ops_test.build_charm("./traefik-mock")


@pytest.mark.abort_on_fail
@pytest.fixture(scope="session")
def ingress_requirer_mock_charm(session_scoped_ops_test: OpsTest):
    charm = await session_scoped_ops_test.build_charm("./ingress-requirer-mock")
