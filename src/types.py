from typing import List, Mapping

try:
    from typing import TypedDict
except ModuleNotFoundError:
    from typing_extensions import TypedDict

RouterName = ServiceName = str


class Router(TypedDict):
    rule: str
    service: str
    entryPoints: List[str]


class Url(TypedDict):
    url: str


class Servers(TypedDict):
    servers: List[Url]


class Service(TypedDict):
    loadBalancer: Servers


class UnitConfig(TypedDict):
    router_name: str
    router: Router
    service_name: str
    service: Service


class Http(TypedDict):
    routers: Mapping[RouterName, Router]
    services: Mapping[ServiceName, Router]


class TraefikConfig(TypedDict):
    http: Http
