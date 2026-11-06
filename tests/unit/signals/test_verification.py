"""Ingress caller verification: each tier's signature accepts the genuine and refuses the rest."""

from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from mission_control.application.signals.contracts import IngressRejected
from mission_control.application.signals.verification import (
    bearer_token,
    derive_secret,
    verify_environment_signature,
    verify_hex_signature,
    verify_standard_webhook,
)

NOW = 1_800_000_000.0
BODY = b'{"type":"session.status_idled","id":"sesn_1"}'
KEY = b"provider-signing-key"
WHSEC = "whsec_" + base64.b64encode(KEY).decode()


def _standard(webhook_id: str = "msg_1", stamp: int = int(NOW), key: bytes = KEY) -> str:
    signed = f"{webhook_id}.{stamp}.".encode() + BODY
    return "v1," + base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()


def _code(call: object, *args: object, **kwargs: object) -> str:
    with pytest.raises(IngressRejected) as refusal:
        call(*args, **kwargs)  # type: ignore[operator]
    return refusal.value.code


def test_bearer_token_reads_only_the_bearer_scheme() -> None:
    assert bearer_token("Bearer abc") == "abc"
    assert bearer_token("bearer  abc ") == "abc"
    assert bearer_token("Basic abc") is None
    assert bearer_token("Bearer ") is None
    assert bearer_token(None) is None


def test_derived_secrets_are_stable_and_separated_by_purpose_and_identifier() -> None:
    master = b"master"
    key = derive_secret(master, "environment_key", "biotech/claude/env_1")
    assert key == derive_secret(master, "environment_key", "biotech/claude/env_1")
    assert key != derive_secret(master, "environment_key", "biotech/claude/env_2")
    assert key != derive_secret(master, "cursor_webhook", "biotech/claude/env_1")
    assert key != derive_secret(b"other", "environment_key", "biotech/claude/env_1")
    with pytest.raises(ValueError):
        derive_secret(b"", "environment_key", "x")


def test_standard_webhooks_accept_any_listed_signature_and_refuse_forgery_and_replay() -> None:
    accepted = verify_standard_webhook(
        WHSEC,
        webhook_id="msg_1",
        timestamp=str(int(NOW)),
        signature=f"v1,AAAA {_standard()}",
        body=BODY,
        now=NOW,
    )
    assert accepted == "msg_1"
    common = {"timestamp": str(int(NOW)), "body": BODY, "now": NOW}
    assert (
        _code(
            verify_standard_webhook,
            WHSEC,
            webhook_id="msg_1",
            signature=_standard(key=b"x"),
            **common,
        )
        == "invalid_signature"
    )
    # A signature for another delivery id does not transfer.
    assert (
        _code(verify_standard_webhook, WHSEC, webhook_id="msg_2", signature=_standard(), **common)
        == "invalid_signature"
    )
    assert (
        _code(
            verify_standard_webhook,
            WHSEC,
            webhook_id="msg_1",
            timestamp=str(int(NOW) - 301),
            signature=_standard(stamp=int(NOW) - 301),
            body=BODY,
            now=NOW,
        )
        == "stale_timestamp"
    )
    assert (
        _code(verify_standard_webhook, WHSEC, webhook_id=None, signature=_standard(), **common)
        == "invalid_signature"
    )


def test_hex_signatures_cover_github_and_cursor_v0() -> None:
    good = "sha256=" + hmac.new(b"secret", BODY, hashlib.sha256).hexdigest()
    verify_hex_signature(b"secret", signature=good, body=BODY)
    for bad in (None, good.replace("sha256=", "sha1="), good[:-1] + "0", "sha256=é"):
        assert _code(verify_hex_signature, b"secret", signature=bad, body=BODY) == (
            "invalid_signature"
        )
    assert _code(verify_hex_signature, b"secret", signature=good, body=BODY + b" ") == (
        "invalid_signature"
    )


def test_environment_key_signatures_bind_timestamp_and_body() -> None:
    stamp = str(int(NOW))
    signature = "v1=" + hmac.new(KEY, stamp.encode() + b"." + BODY, hashlib.sha256).hexdigest()
    verify_environment_signature(KEY, timestamp=stamp, signature=signature, body=BODY, now=NOW)
    assert (
        _code(
            verify_environment_signature,
            KEY,
            timestamp=stamp,
            signature=signature,
            body=BODY + b"x",
            now=NOW,
        )
        == "invalid_signature"
    )
    assert (
        _code(
            verify_environment_signature,
            KEY,
            timestamp=stamp,
            signature=signature,
            body=BODY,
            now=NOW + 301,
        )
        == "stale_timestamp"
    )
    assert (
        _code(
            verify_environment_signature,
            KEY,
            timestamp="soon",
            signature=signature,
            body=BODY,
            now=NOW,
        )
        == "invalid_signature"
    )
