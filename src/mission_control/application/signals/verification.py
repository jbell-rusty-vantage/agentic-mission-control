"""Caller verification for the Signal Ingress tiers (SPEC-10 section 2; research/vercel-ingress.md
section 2.2). Pure functions over the raw body and headers; authority stays in SQL.

* `bearer_token`: the `Authorization: Bearer` value (run token, launch token or Cursor OIDC JWT).
* `derive_secret`: `HMAC-SHA256(master, "<purpose>:<identifier>")`, so the edge holds one
  master per purpose instead of one key per environment or run. The Secret Broker derives the
  same value when it writes an environment secret or registers a Cursor webhook.
* `verify_environment_signature` (`environment_key`): `X-MC-Signature: v1=<hex HMAC(key,
  timestamp + "." + body)>` with `X-MC-Timestamp` within the tolerance.
* `verify_standard_webhook` (Anthropic, OpenAI): Standard Webhooks `webhook-id`,
  `webhook-timestamp`, `webhook-signature: v1,<base64>` over `id.timestamp.body` with the
  base64-decoded `whsec_` secret; any listed signature may match (secret rotation).
* `verify_hex_signature` (GitHub `X-Hub-Signature-256`, Cursor v0 `X-Webhook-Signature`):
  `sha256=<hex HMAC(secret, body)>`.

Every comparison is constant-time and every failure is the same `invalid_signature` (or
`stale_timestamp`) rejection; no expected value is ever echoed.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from typing import Final

from mission_control.application.signals.contracts import IngressRejected

SIGNATURE_TOLERANCE_SECONDS: Final = 300
ENVIRONMENT_KEY_PURPOSE: Final = "environment_key"
CURSOR_WEBHOOK_PURPOSE: Final = "cursor_webhook"
_WHSEC_PREFIX: Final = "whsec_"


def _invalid() -> IngressRejected:
    return IngressRejected(401, "invalid_signature")


def bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, _space, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None


def derive_secret(master: bytes, purpose: str, identifier: str) -> bytes:
    if not master or not purpose or not identifier:
        raise ValueError("a derived secret needs a master, a purpose and an identifier")
    message = f"{purpose}:{identifier}".encode()
    return hmac.new(master, message, hashlib.sha256).digest()


def _timestamp(value: str | None, now: float, tolerance: int) -> str:
    if value is None or not value.isdigit() or len(value) > 12:
        raise _invalid()
    if abs(now - int(value)) > tolerance:
        raise IngressRejected(401, "stale_timestamp")
    return value


def verify_environment_signature(
    key: bytes,
    *,
    timestamp: str | None,
    signature: str | None,
    body: bytes,
    now: float,
    tolerance: int = SIGNATURE_TOLERANCE_SECONDS,
) -> None:
    stamp = _timestamp(timestamp, now, tolerance)
    if signature is None or not signature.startswith("v1="):
        raise _invalid()
    expected = hmac.new(key, stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature[3:].encode(), expected.encode()):
        raise _invalid()


def verify_standard_webhook(
    secret: str,
    *,
    webhook_id: str | None,
    timestamp: str | None,
    signature: str | None,
    body: bytes,
    now: float,
    tolerance: int = SIGNATURE_TOLERANCE_SECONDS,
) -> str:
    """The verified `webhook-id` (the dedupe key)."""

    if not webhook_id or len(webhook_id) > 256 or not signature:
        raise _invalid()
    stamp = _timestamp(timestamp, now, tolerance)
    encoded = secret.removeprefix(_WHSEC_PREFIX)
    try:
        key = base64.b64decode(encoded, validate=True)
    except binascii.Error:
        raise ValueError("the webhook signing secret is not base64") from None
    signed = webhook_id.encode() + b"." + stamp.encode() + b"." + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    for candidate in signature.split():
        version, _comma, value = candidate.partition(",")
        if version == "v1" and hmac.compare_digest(value.encode(), expected.encode()):
            return webhook_id
    raise _invalid()


def verify_hex_signature(secret: bytes, *, signature: str | None, body: bytes) -> None:
    if signature is None or not signature.startswith("sha256="):
        raise _invalid()
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature[7:].encode(), expected.encode()):
        raise _invalid()


__all__ = [
    "CURSOR_WEBHOOK_PURPOSE",
    "ENVIRONMENT_KEY_PURPOSE",
    "SIGNATURE_TOLERANCE_SECONDS",
    "bearer_token",
    "derive_secret",
    "verify_environment_signature",
    "verify_hex_signature",
    "verify_standard_webhook",
]
