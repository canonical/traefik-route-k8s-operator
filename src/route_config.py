#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Configuration classes for traefik-route."""

import logging
from dataclasses import dataclass
from itertools import starmap
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class RuleDerivationError(RuntimeError):
    """Raised when a rule cannot be derived from other config parameters.

    Solution: provide the rule manually, or fix what's broken.
    """

    def __init__(self, url, *args):
        msg = f"Unable to derive Rule from {url}; ensure that the url is valid."
        super(RuleDerivationError, self).__init__(msg, *args)


@dataclass
class RouteConfig:
    """Route configuration."""

    root_url: str
    rule: str
    id_: str
    strip_prefix: str = None


@dataclass
class _RouteConfig:
    root_url: str
    rule: str = None
    strip_prefix: str = None

    @property
    def is_valid(self):
        def _check_var(obj: str, name):
            error = None
            # None or empty string or whitespace-only string
            if not obj or not obj.strip():
                error = (
                    f"`{name}` not configured; do `juju config <traefik-route-charm> "
                    f"{name}=<{name.upper()}>; juju resolve <traefik-route-charm>`"
                )

            elif obj != (stripped := obj.strip()):
                error = (
                    f"{name} {obj!r} starts or ends with whitespace;" f"it should be {stripped!r}."
                )

            if error:
                logger.error(error)
            return not error

        if not self.rule:
            # we can guess the rule from the root_url.
            return _check_var(self.root_url, "root_url")

        # TODO: think about further validating `rule` (regex?)
        valid = starmap(_check_var, ((self.rule, "rule"), (self.root_url, "root_url")))

        prefix = self.strip_prefix
        if prefix:
            if not isinstance(prefix, str):
                logger.error("strip_prefix should be a string")
                return False
            if " " in prefix:
                logger.error("strip_prefix should have no whitespace")
                return False
        return all(valid)

    def render(self, model_name: str, unit_name: str, app_name: str):
        """Fills in the blanks in the templates."""

        # todo make proper jinja2 thing here
        def _render(obj: str):
            for key, value in (
                ("{{juju_model}}", model_name),
                ("{{juju_application}}", app_name),
                ("{{juju_unit}}", unit_name),
            ):
                if key in obj:
                    obj = obj.replace(key, value)
            return obj

        url = _render(self.root_url)
        if not self.rule:
            rule = self.generate_rule_from_url(url)
        else:
            rule = _render(self.rule)

        # an easily recognizable id for the traefik services
        id_ = "-".join((unit_name, model_name))
        return RouteConfig(rule=rule, root_url=url, id_=id_, strip_prefix=self.strip_prefix)

    @staticmethod
    def generate_rule_from_url(url) -> str:
        """Derives a Traefik router Host rule from the provided `url`'s hostname."""
        url_ = urlparse(url)
        if not url_.hostname:
            raise RuleDerivationError(url)
        return f"Host(`{url_.hostname}`)"
