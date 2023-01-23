#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Types for TraefikRoute charm."""

from typing import List, Mapping

try:
    from typing import TypedDict
except ModuleNotFoundError:
    from typing_extensions import TypedDict

RouterName = ServiceName = str


# D101 'missing docstrings in public class'
# N815 'no camelCase'


class Router(TypedDict):  # noqa: D101
    rule: str
    service: str
    entryPoints: List[str]  # noqa N815


class Url(TypedDict):  # noqa: D101
    url: str


class Servers(TypedDict):  # noqa: D101
    servers: List[Url]


class Service(TypedDict):  # noqa: D101
    loadBalancer: Servers  # noqa N815


class UnitConfig(TypedDict):  # noqa: D101
    router_name: str
    router: Router
    service_name: str
    service: Service


class Http(TypedDict):  # noqa: D101
    routers: Mapping[RouterName, Router]  # type: ignore
    services: Mapping[ServiceName, Router]  # type: ignore


class TraefikConfig(TypedDict):  # noqa: D101
    http: Http
