# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

r"""# Interface Library for traefik_route.

This library wraps relation endpoints for traefik_route. The requirer of this
relation is a charm in need of ingress (or a proxy thereof), the
provider is the traefik-k8s charm.

## Getting Started

To get started using the library, you just need to fetch the library using `charmcraft`.

```shell
cd some-charm
charmcraft fetch-lib charms.traefik_route_k8s.v0.traefik_route
```

```yaml
requires:
    traefik_route:
        interface: traefik_route
        limit: 1
```

Then, to initialise the library:

```python
# ...
from charms.traefik_route_k8s.v0.traefik_route import TraefikRouteRequirer

class SomeCharm(CharmBase):
  def __init__(self, *args):
    # ...
    self.ingress_per_unit = TraefikRouteProvider(self)
    self.traefik_route = TraefikRouteRequirer(self)

    self.framework.observe(
        self.ingress_per_unit.on.request, self.traefik_route.relay
    )
    self.framework.observe(
        self.traefik_route.on.response, self.ingress_per_unit.respond
    )
```
"""
import json
import logging
from typing import Optional, Dict

import yaml
from ops.charm import CharmBase, RelationEvent, RelationRole, CharmEvents
from ops.framework import EventSource, Object
from ops.model import Relation, Unit

# The unique Charmhub library identifier, never change it
LIBID = ""

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 0

log = logging.getLogger(__name__)


def _deserialize_data(data):
    return json.loads(data)


def _serialize_data(data):
    return json.dumps(data, indent=2)


class TraefikRouteException(RuntimeError):
    """Base class for exceptions raised by TraefikRoute."""


class UnauthorizedError(TraefikRouteException):
    """Raised when the unit needs leadership to perform some action."""


class TraefikRouteRequestEvent(RelationEvent):
    """Event representing an incoming request.

    This is equivalent to the "ready" event, but is more meaningful.
    """


class TraefikRouteIngressReadyEvent(RelationEvent):
    """Event representing a ready state from the traefik charm."""
    def __init__(self, handle, relation, ingress, app=None, unit=None):
        super().__init__(handle, relation, app=app, unit=unit)
        self.ingress = ingress

    def snapshot(self) -> dict:
        """Used by the framework to serialize the event to disk.

        Not meant to be called by charm code.
        """
        snap = super().snapshot()
        snap['ingress'] = self.ingress
        return snap

    def restore(self, snapshot: dict) -> None:
        """Used by the framework to deserialize the event from disk.

        Not meant to be called by charm code.
        """
        self.ingress = snapshot.pop('ingress')
        super().restore(snapshot)


class TraefikRouteProviderEvents(CharmEvents):
    """Container for TRP events."""
    ready = EventSource(TraefikRouteRequestEvent)


class TraefikRouteRequirerEvents(CharmEvents):
    """Container for TRR events."""
    ingress_ready = EventSource(TraefikRouteIngressReadyEvent)


class TraefikRouteProvider(Object):
    """Implementation of the provider of traefik_route.

    This will presumably be owned by a Traefik charm.
    The main idea is that traefik will observe the `request` event and, upon
    receiving it, will
    """
    on = TraefikRouteProviderEvents()

    def __init__(self, charm: CharmBase, endpoint: str = 'traefik-route'):
        """Constructor for TraefikRouteProvider.

        Args:
            charm: The charm that is instantiating the instance.
            endpoint: The name of the relation endpoint to bind to
                (defaults to "traefik-route").
        """
        super().__init__(charm, endpoint)
        self.framework.observe(self.on[endpoint].relation_joined,
                               self._emit_ready_event)

    def _emit_ready_event(self, event):
        self.on.ready.emit(event.relation)


class TraefikNotReadyError(TraefikRouteException):
    """Raised when TraefikRouteRequirer is asked for a rule which """


class TraefikRouteRequirer(Object):
    """Wrapper for the requirer side of traefik-route.

    traefik_route will publish to the application databag an object like:
    {
        'config': <Traefik_config>
    }

    'ingress' is provided by the ingress end-user via ingress_per_unit,
    'config' is provided by the cloud admin via the traefik-route-k8s charm.

    TraefikRouteRequirer does no validation; it assumes that ingress_per_unit
    validates its part of the data, and that the traefik-route-k8s charm will
    do its part by validating the config before this provider is invoked to
    share it with traefik.
    """
    on = TraefikRouteRequirerEvents()

    def __init__(self, charm: CharmBase, relation, endpoint: str = 'traefik-route'):
        super(TraefikRouteRequirer, self).__init__(charm, endpoint)
        self._charm = charm
        self._endpoint = endpoint
        self._relation = relation

    def is_ready(self):
        """Is the TraefikRouteRequirer ready to submit data to Traefik?"""
        return self._relation is not None

    def submit_to_traefik(self, config):
        """Relay an ingress configuration data structure to traefik.

        This will publish to TraefikRoute's traefik-route relation databag
        the config traefik needs to route the units behind this charm.
        """
        if not self._charm.unit.is_leader():
            raise UnauthorizedError()

        app_databag = self._relation.data[self._charm.app]
        app_databag['config'] = _serialize_data(config)

        # we emit the ready immediately, although...
        self.on.ready.emit(self._relation)
