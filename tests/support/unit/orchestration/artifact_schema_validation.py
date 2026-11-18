"""Builders, constants and fakes that other test files import.

Moved from tests/unit/orchestration/test_artifact_schema_validation.py.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

from mission_control.application.context.pack_service import ArtifactContent

SCOPE = "mc/install/app/tenant"
REF = f"artifact://{SCOPE}/run/report"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["count"],
    "properties": {"count": {"type": "integer", "minimum": 1}},
    "additionalProperties": False,
}


def captured(raw_text: str = '{"count": 1}', **changes: Any) -> ArtifactContent:
    raw = raw_text.encode("utf-8")
    return replace(
        ArtifactContent(
            source_ref=REF,
            durable_ref="object://report",
            content_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            media_type="application/json",
            text=raw_text,
        ),
        **changes,
    )


class Custody:
    def __init__(self, content: ArtifactContent | None) -> None:
        self.content = content
        self.calls: list[tuple[str, str, int]] = []

    async def capture(
        self, source_ref: str, *, request_scope: str, max_text_bytes: int
    ) -> ArtifactContent | None:
        self.calls.append((source_ref, request_scope, max_text_bytes))
        return self.content
