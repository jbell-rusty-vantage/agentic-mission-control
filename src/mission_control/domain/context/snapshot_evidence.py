"""Bounded conversation custody attached to a particular provider branch snapshot."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONVERSATION_MEDIA_TYPE = "application/vnd.mission-control.fork-conversation.v1+json"
MAX_CONVERSATION_BYTES = 262_144
MAX_EXCERPT_BYTES = 32_768
DIGEST = r"^sha256:[0-9a-f]{64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConversationOrigin(_Strict):
    request_scope: str = Field(min_length=1, max_length=256)
    run_id: str = Field(min_length=1, max_length=512)
    repository: str = Field(min_length=1, max_length=2048)
    branch: str = Field(min_length=1, max_length=256)
    head_commit: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    session_ref: str = Field(min_length=1, max_length=512)
    run_ref: str = Field(min_length=1, max_length=512)

    @property
    def restore_ref(self) -> str:
        return f"branch:{self.branch}@{self.head_commit}"


class ConversationExport(_Strict):
    schema_version: Literal["mc.cursor_conversation_export.v1"]
    source: Literal["cursor.v0.conversation"]
    session_ref: str = Field(min_length=1, max_length=512)
    run_ref: str = Field(min_length=1, max_length=512)
    disposition: Literal["exported", "missing"]
    excerpt: str = Field(max_length=MAX_EXCERPT_BYTES)
    truncated: bool
    excerpt_digest: str = Field(pattern=DIGEST)

    @model_validator(mode="after")
    def bounded_excerpt(self) -> ConversationExport:
        raw = self.excerpt.encode("utf-8")
        if len(raw) > MAX_EXCERPT_BYTES or digest_bytes(raw) != self.excerpt_digest:
            raise ValueError("conversation excerpt size or digest differs")
        if self.disposition == "missing" and (raw or self.truncated):
            raise ValueError("missing conversation cannot carry an excerpt")
        if self.disposition == "exported" and not raw:
            raise ValueError("exported conversation needs an excerpt")
        return self


class ConversationEnvelope(_Strict):
    schema_version: Literal["mc.fork_conversation.v1"] = "mc.fork_conversation.v1"
    origin: ConversationOrigin
    conversation: ConversationExport

    @model_validator(mode="after")
    def native_origin(self) -> ConversationEnvelope:
        if (self.origin.session_ref, self.origin.run_ref) != (
            self.conversation.session_ref,
            self.conversation.run_ref,
        ):
            raise ValueError("conversation native origin differs")
        return self


class ConversationEvidence(_Strict):
    schema_version: Literal["mc.fork_conversation_evidence.v1"] = "mc.fork_conversation_evidence.v1"
    origin: ConversationOrigin
    disposition: Literal["exported", "missing"]
    durable_ref: str = Field(min_length=1, max_length=4096)
    content_digest: str = Field(pattern=DIGEST)
    content_bytes: int = Field(gt=0, le=MAX_CONVERSATION_BYTES)


class LaneSnapshotEvidence(_Strict):
    """Restore ref and conversation selected atomically from one released lease."""

    refs: tuple[str, ...] = ()
    conversation: ConversationEvidence | None = None


def digest_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()
