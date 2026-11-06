"""Provider webhooks as wake signals (SPEC-06 section 3, SPEC-10 section 2; HL-17).

Managed Agents and the Agents API sign their webhooks with Standard Webhooks; the service
verifies the signature and timestamp, and SQL dedupes on the `webhook-id`. What is stored is a
`ProviderWake`: the event type and the id of the resource the envelope names, read where each
provider documents them. Everything else in the body (status, required actions, URLs, usage)
is dropped unread, because a webhook is never trusted for state: deliveries arrive unordered,
may repeat and may be dropped, so the worker re-reads the named resource from the provider.

* `anthropic`: `{"type": "event", "id", "created_at", "data": {"type", "id", ...}}`; the event
  type is `data.type` and the resource id `data.id` (`anthropic` SDK `UnwrapWebhookEvent`);
* `openai`: `{"object": "event", "id", "created_at", "type", "data": {"id", ...}}`; the event
  type is `type` and the resource id `data.id` (Agents API sessions webhooks guide).

The top-level `id` of both envelopes is the provider's event id, kept for audit only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from pydantic import ValidationError

from mission_control.application.signals.contracts import IngressRejected, ProviderWake

_EVENT_TYPE: Final[Mapping[str, tuple[str, ...]]] = {
    "anthropic": ("data", "type"),
    "openai": ("type",),
}
_RESOURCE_ID: Final = ("data", "id")


def _at(document: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = document
    for name in path:
        value = value.get(name) if isinstance(value, Mapping) else None
    return value


def provider_wake(provider: str, envelope: Mapping[str, Any]) -> ProviderWake:
    """The wake a verified envelope names; `invalid_body` when it names no event or resource."""

    path = _EVENT_TYPE.get(provider)
    if path is None:
        raise ValueError(f"{provider} webhooks are not reduced to wakes")
    event_id = envelope.get("id")
    try:
        return ProviderWake(
            event_type=_at(envelope, path),
            resource_ref=_at(envelope, _RESOURCE_ID),
            event_id=event_id if isinstance(event_id, str) else None,
        )
    except ValidationError:
        raise IngressRejected(422, "invalid_body") from None


__all__ = ["provider_wake"]
