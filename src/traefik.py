#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Traefik configuration interface."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Mapping, Iterable

from route_config import RouteConfig

try:
    from typing import TypedDict
except ModuleNotFoundError:
    from typing_extensions import TypedDict

RouterName = ServiceName = MiddlewareName = str


# D101 'missing docstrings in public class'
# N815 'no camelCase'


class Router(TypedDict):  # noqa: D101
    rule: str
    service: str
    entryPoints: List[str]  # noqa N815
    middlewares: List[str]


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
    middlewares: Dict[str, Dict]


class Http(TypedDict):  # noqa: D101
    routers: Dict[RouterName, Router]
    services: Dict[ServiceName, Router]
    middlewares: Dict[MiddlewareName, Dict]

class TraefikConfig(TypedDict):  # noqa: D101
    http: Http


class Middleware(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def to_dict(self) -> dict:
        ...


class StripPrefixMiddleware(Middleware):
    def __init__(self, prefix):
        self.prefix = prefix

    @property
    def name(self):
        return f"juju-{self.prefix}-stripprefix"

    def to_dict(self):
        return {
            "stripPrefix": {
                "prefixes": [f"/{self.prefix}"],
            }
        }


def generate_unit_config(config: RouteConfig) -> "UnitConfig":
    rule, config_id, url = config.rule, config.id_, config.root_url

    traefik_router_name = f"juju-{config_id}-router"
    traefik_service_name = f"juju-{config_id}-service"

    middlewares: List[Middleware] = []
    if config.strip_prefix:
        middlewares.append(StripPrefixMiddleware(config.strip_prefix))

    config: "UnitConfig" = {
        "router": {
            "rule": rule,
            "service": traefik_service_name,
            "entryPoints": ["web"],
            "middlewares": [mw.name for mw in middlewares],
        },
        "router_name": traefik_router_name,
        "service": {"loadBalancer": {"servers": [{"url": url}]}},
        "service_name": traefik_service_name,
        "middlewares": {mw.name: mw.to_dict() for mw in middlewares},
    }
    return config


def merge_configs(configs: Iterable["UnitConfig"]) -> "TraefikConfig":
    middlewares = {}
    for config in configs:
        middlewares.update(config['middlewares'])

    traefik_config = {
        "http": {
            "routers": {config["router_name"]: config["router"] for config in configs},
            "services": {config["service_name"]: config["service"] for config in configs},
            "middlewares": middlewares
        }
    }
    return traefik_config
