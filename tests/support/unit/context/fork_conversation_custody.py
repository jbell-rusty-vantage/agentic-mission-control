"""Builders, constants and fakes that other test files import.

Moved from tests/unit/context/test_fork_conversation_custody.py.
"""

from __future__ import annotations

from mission_control.adapters.cursor.conversation import (
    conversation_export,
    fork_conversation_export,
)
from mission_control.domain.context.snapshot_evidence import (
    CONVERSATION_MEDIA_TYPE,
    ConversationEnvelope,
    ConversationEvidence,
    ConversationOrigin,
    digest_bytes,
)
from mission_control.domain.policies.forks import RunSnapshotManifest
from tests.support.knowledge.stores import InMemoryStaging
from tests.support.run_forks import technical_snapshot


async def custody(
    *, value: object = "Source decision and unfinished work"
) -> tuple[RunSnapshotManifest, InMemoryStaging, bytes]:
    origin = ConversationOrigin(
        request_scope="tenant-1",
        run_id="source",
        repository="https://example.invalid/repo",
        branch="mc/source",
        head_commit="a" * 40,
        session_ref="agent-1",
        run_ref="native-1",
    )
    raw = fork_conversation_export(
        conversation_export(
            value,
            session_ref=origin.session_ref,
            run_ref=origin.run_ref,
            source="cursor.v0.conversation",
        ),
        origin=origin,
    )
    files = InMemoryStaging()
    ref = await files.stage(
        request_scope=origin.request_scope,
        name="conversation",
        content=raw,
        media_type=CONVERSATION_MEDIA_TYPE,
    )
    evidence = ConversationEvidence(
        origin=origin,
        disposition=ConversationEnvelope.model_validate_json(raw).conversation.disposition,
        durable_ref=ref,
        content_digest=digest_bytes(raw),
        content_bytes=len(raw),
    )
    snapshot = RunSnapshotManifest.create(
        **{
            **technical_snapshot("source").model_dump(mode="python"),
            "sandbox_snapshot_refs": (origin.restore_ref,),
            "conversation": evidence,
        }
    )
    return snapshot, files, raw
