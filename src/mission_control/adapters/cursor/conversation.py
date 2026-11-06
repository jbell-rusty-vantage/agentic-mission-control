"""Bounded scrubbed conversation evidence; absence is explicit, never synthesized."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from mission_control.adapters.cursor.frames import scrub
from mission_control.adapters.cursor.snapshot import bytes_digest
from mission_control.domain.context.snapshot_evidence import (
    MAX_CONVERSATION_BYTES,
    ConversationEnvelope,
    ConversationExport,
    ConversationOrigin,
)

CONVERSATION_PATH = ".mission/conversation-export.json"
MAX_EXCERPT_BYTES = 32_768


def conversation_export(
    value: Any, *, session_ref: str, run_ref: str | None, source: str, secrets: Iterable[str] = ()
) -> bytes:
    from mission_control.adapters.cursor.bridge import _jsonable

    sanitized = scrub(_jsonable(value), secrets=secrets)
    text = json.dumps(sanitized, ensure_ascii=False, sort_keys=True)
    original = text.encode("utf-8")
    excerpt = original[:MAX_EXCERPT_BYTES].decode("utf-8", errors="ignore")
    body = {
        "schema_version": "mc.cursor_conversation_export.v1",
        "source": source,
        "session_ref": session_ref,
        "run_ref": run_ref,
        "disposition": "exported" if value else "missing",
        "excerpt": excerpt if value else "",
        "truncated": len(original) > MAX_EXCERPT_BYTES,
        "excerpt_digest": bytes_digest(excerpt.encode("utf-8") if value else b""),
    }
    return json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")


def fork_conversation_export(content: bytes, *, origin: ConversationOrigin) -> bytes:
    """Bind the existing scrubbed export to the exact read-back workspace origin."""
    if len(content) > MAX_CONVERSATION_BYTES:
        raise ValueError("conversation export exceeds the custody bound")
    envelope = ConversationEnvelope(
        origin=origin, conversation=ConversationExport.model_validate_json(content)
    )
    raw = envelope.model_dump_json().encode("utf-8")
    if len(raw) > MAX_CONVERSATION_BYTES:
        raise ValueError("conversation envelope exceeds the custody bound")
    return raw
