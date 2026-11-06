"""OVE-166 / WI-02: the launch-time promise registrar every launch route composes."""

from __future__ import annotations

import asyncpg

from mission_control.adapters.postgres.knowledge.output_fulfillment import (
    compose_output_fulfillment,
)
from mission_control.application.outputs.launch import LaunchPromiseRegistrar


def compose_launch_promises(pool: asyncpg.Pool) -> LaunchPromiseRegistrar:
    """Launch registers the admitted ``output_promises`` through the production output service
    (`adapters/postgres/knowledge/output_fulfillment.compose_output_fulfillment`)."""

    # Registration only (no fulfillment decision): no trusted pin is needed, fail closed.
    return LaunchPromiseRegistrar(compose_output_fulfillment(pool, trusted_validators=None))


__all__ = ["compose_launch_promises"]
