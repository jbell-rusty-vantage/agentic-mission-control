"""Provider webhooks are wake-ups, never state (ADR-0052, ADR-0045; SPEC-06 section 3).

Signal Ingress verifies a provider webhook (Standard Webhooks for Managed Agents and the Agents
API) and deduplicates it on the delivery id before anything reaches a worker. What a Remote
Session Lane receives is a `SessionWake`: the event type and the id of the resource it names,
with the rest of the payload dropped. Webhooks arrive unordered, may repeat and may be dropped
after a few attempts, so the lane re-reads the named session from the provider (its history
and turn record) and a timer-driven reconcile remains the safety net.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SessionWake:
    """A verified, deduplicated provider webhook reduced to the identity it names."""

    lane_profile: str
    delivery_id: str
    event_type: str
    resource_ref: str


def session_wake(
    lane_profile: str,
    delivery_id: str,
    payload: Mapping[str, Any],
    *,
    type_field: str = "type",
    id_path: tuple[str, ...] = ("id",),
) -> SessionWake | None:
    """The wake a payload names, or None when it names no resource. Only the event type and
    the resource id (at `id_path`, as the provider documents it) are read: status, results and
    usage in a payload are never trusted."""

    event_type = payload.get(type_field)
    resource: Any = payload
    for name in id_path:
        resource = resource.get(name) if isinstance(resource, Mapping) else None
    if not isinstance(event_type, str) or not event_type:
        return None
    if not isinstance(resource, str) or not resource:
        return None
    return SessionWake(
        lane_profile=lane_profile,
        delivery_id=delivery_id,
        event_type=event_type,
        resource_ref=resource,
    )


__all__ = ["SessionWake", "session_wake"]
