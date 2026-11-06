"""Signed provider webhook deliveries for Signal Ingress tests (HL-17; FIXTURE).

The bodies follow the documented envelopes: Managed Agents from the `anthropic` 0.120.2 SDK
types (`UnwrapWebhookEvent` with `BetaWebhookEventData`), the Agents API from
https://developers.openai.com/api/docs/guides/agents-api/sessions/webhooks.md. They are signed
here with test-only secrets exactly as Standard Webhooks specifies (HMAC-SHA256 over
`id.timestamp.body` with the base64-decoded `whsec_` secret). No webhook is registered with any
provider and no delivery comes from one.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Final

ANTHROPIC_TEST_SECRET: Final = "whsec_" + base64.b64encode(b"anthropic-fixture-secret").decode()
OPENAI_TEST_SECRET: Final = "whsec_" + base64.b64encode(b"openai-fixture-secret").decode()

ANTHROPIC_SESSION_IDLED: Final[dict[str, Any]] = {
    "type": "event",
    "id": "wevt_011CTnB7d1xE2fixture",
    "created_at": "2026-10-13T12:00:00Z",
    "data": {
        "type": "session.status_idled",
        "id": "sesn_011CTnB7fixture",
        "organization_id": "org_fixture",
        "workspace_id": "wrkspc_fixture",
    },
}
OPENAI_ACTION_REQUIRED: Final[dict[str, Any]] = {
    "id": "evt_fixture_action",
    "object": "event",
    "created_at": 1_791_892_800,
    "type": "agent.session.action_required",
    "data": {"id": "sess_fixture123", "required_action": {"type": "function_call"}},
}
OPENAI_SESSION_CREATED: Final[dict[str, Any]] = {
    "id": "evt_fixture_created",
    "object": "event",
    "created_at": 1_791_892_790,
    "type": "agent.session.created",
    "data": {
        "id": "sess_fixture123",
        "environment_id": "ccarenv_fixture",
        "environment_type": "self_hosted",
        "connect": {"remote_url": "https://untrusted.invalid/v1/agents/api"},
    },
}


def delivery_body(envelope: dict[str, Any]) -> bytes:
    return json.dumps(envelope, separators=(",", ":")).encode()


def standard_headers(
    secret: str, body: bytes, webhook_id: str, *, timestamp: int | None = None
) -> dict[str, str]:
    """The `webhook-*` headers a Standard Webhooks sender attaches to `body`."""

    stamp = str(int(time.time()) if timestamp is None else timestamp)
    key = base64.b64decode(secret.removeprefix("whsec_"))
    signed = f"{webhook_id}.{stamp}.".encode() + body
    signature = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": stamp,
        "webhook-signature": f"v1,{signature}",
    }


__all__ = [
    "ANTHROPIC_SESSION_IDLED",
    "ANTHROPIC_TEST_SECRET",
    "OPENAI_ACTION_REQUIRED",
    "OPENAI_SESSION_CREATED",
    "OPENAI_TEST_SECRET",
    "delivery_body",
    "standard_headers",
]
