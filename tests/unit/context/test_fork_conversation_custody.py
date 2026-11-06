"""CM07: mandatory fork context follows sealed, scoped, bounded conversation custody."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from mission_control.adapters.cursor.conversation import (
    conversation_export,
    fork_conversation_export,
)
from mission_control.application.context.fork_context import ForkContextReader
from mission_control.application.context.pack_service import ContextPackRejected, ContextPackService
from mission_control.domain.context.snapshot_evidence import (
    CONVERSATION_MEDIA_TYPE,
    MAX_CONVERSATION_BYTES,
    ConversationEnvelope,
    ConversationEvidence,
    ConversationOrigin,
    digest_bytes,
)
from mission_control.domain.policies.forks import RunSnapshotManifest
from mission_control.domain.policies.mailbox import MailboxEntry
from tests.fixtures.run_forks import technical_snapshot
from tests.unit.context.packets import SEALED_AT
from tests.unit.operations.test_ft_b2_stage_handoff import (
    FakeArtifacts,
    FakeSelections,
    FakeStaging,
)


@dataclass
class Snapshots:
    value: RunSnapshotManifest | None

    async def get(self, request_scope: str, snapshot_id: str) -> RunSnapshotManifest | None:
        if self.value and (self.value.request_scope, self.value.snapshot_id) == (
            request_scope,
            snapshot_id,
        ):
            return self.value
        return None


async def custody(
    *, value: object = "Source decision and unfinished work"
) -> tuple[RunSnapshotManifest, FakeStaging, bytes]:
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
    files = FakeStaging()
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


def entries(snapshot: RunSnapshotManifest) -> tuple[MailboxEntry, MailboxEntry]:
    assert snapshot.conversation is not None
    common = {
        "request_scope": snapshot.request_scope,
        "run_id": "derived",
        "command_issuer": "fork-seed",
        "kind": "add_context",
        "generation": 1,
        "boundary": "next_turn",
        "accepted_at": SEALED_AT,
        "content_digest": snapshot.snapshot_digest,
    }
    return (
        MailboxEntry(
            **common,
            entry_id="workspace",
            command_id="workspace",
            admission_sequence=1,
            content_ref=snapshot.sandbox_snapshot_refs[0],
            content_bytes=0,
            media_type="application/x-mission-control-run-snapshot",
            expand="workspace",
        ),
        MailboxEntry(
            **common,
            entry_id="conversation",
            command_id="conversation",
            admission_sequence=2,
            content_ref=f"run-snapshot://{snapshot.snapshot_id}",
            content_bytes=snapshot.conversation.content_bytes,
            media_type=CONVERSATION_MEDIA_TYPE,
            expand="inline",
        ),
    )


def packs(
    snapshot: RunSnapshotManifest, files: FakeStaging, *, composed: bool = True
) -> ContextPackService:
    return ContextPackService(
        artifacts=FakeArtifacts({}, scope=None),
        selections=FakeSelections(),
        staging=files,
        fork_contexts=ForkContextReader(Snapshots(snapshot), files) if composed else None,
    )


async def test_conversation_is_mandatory_admitted_data_with_exact_custody_bytes() -> None:
    snapshot, files, raw = await custody()
    candidates = await packs(snapshot, files).queued_candidates(
        entries(snapshot), request_scope="tenant-1"
    )
    assert len(candidates) == 2
    conversation = candidates[1]
    assert conversation.mandatory and conversation.trust == "admitted_input"
    assert conversation.text == raw.decode() and conversation.bytes == len(raw)
    assert conversation.content_digest == digest_bytes(raw)


async def test_mandatory_conversation_overflow_refuses_the_whole_packet() -> None:
    from mission_control.domain.context.packet import (
        ContextPurpose,
        PackFailure,
        PackFailureCode,
        pack,
    )
    from tests.unit.context.packets import profile, target, worked_example_request

    snapshot, files, _ = await custody(value="x" * 32_000)
    candidates = await packs(snapshot, files).queued_candidates(
        entries(snapshot), request_scope="tenant-1"
    )
    result = pack(
        worked_example_request(
            candidates=candidates,
            bindings=(),
            producer_refs=(),
            profile=profile(context_window=56_000),
            target=target(ContextPurpose.FORK),
        )
    )
    assert isinstance(result, PackFailure)
    assert result.code == PackFailureCode.CONTEXT_BUDGET_EXCEEDED
    assert result.source_ref == candidates[1].source_ref


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_reader",
        "missing_payload",
        "digest",
        "size",
        "oversize",
        "scope",
        "snapshot_digest",
        "restore",
        "origin",
        "native",
        "missing",
    ],
)
async def test_missing_or_mismatched_custody_never_degrades_to_optional_reference(
    corruption: str,
) -> None:
    snapshot, files, raw = await custody(value=None if corruption == "missing" else "evidence")
    workspace, conversation = entries(snapshot)
    assert snapshot.conversation is not None
    key = snapshot.conversation.durable_ref.partition("#")[0]
    if corruption == "missing_payload":
        files.objects.clear()
    elif corruption in {"digest", "size", "oversize"}:
        files.objects[key] = b"X" * (
            len(raw)
            if corruption == "digest"
            else len(raw) + 1
            if corruption == "size"
            else MAX_CONVERSATION_BYTES + 1
        )
    elif corruption == "snapshot_digest":
        conversation = conversation.model_copy(update={"content_digest": "sha256:" + "f" * 64})
    elif corruption == "restore":
        workspace = workspace.model_copy(update={"content_ref": "branch:foreign@" + "b" * 40})
    elif corruption in {"origin", "native"}:
        body = json.loads(raw)
        body["origin"]["head_commit" if corruption == "origin" else "run_ref"] = (
            "b" * 40 if corruption == "origin" else "different-native"
        )
        forged = json.dumps(body).encode()
        ref = await files.stage(
            request_scope="tenant-1",
            name="forged",
            content=forged,
            media_type=CONVERSATION_MEDIA_TYPE,
        )
        # Even self-consistent bytes/digest cannot rewrite the sealed origin.
        evidence = snapshot.conversation.model_copy(
            update={
                "durable_ref": ref,
                "content_digest": digest_bytes(forged),
                "content_bytes": len(forged),
            }
        )
        snapshot = RunSnapshotManifest.create(
            **{**snapshot.model_dump(mode="python"), "conversation": evidence}
        )
        workspace, conversation = entries(snapshot)
    with pytest.raises(ContextPackRejected) as refused:
        await packs(snapshot, files, composed=corruption != "missing_reader").queued_candidates(
            (workspace, conversation),
            request_scope="foreign-scope" if corruption == "scope" else "tenant-1",
        )
    assert refused.value.code == "CONTEXT_MANDATORY_ITEM_UNAVAILABLE"


def test_scrubbed_export_is_bounded() -> None:
    export = conversation_export(
        {"text": "secret-value" + "é" * 40_000},
        session_ref="agent-1",
        run_ref="native-1",
        source="cursor.v0.conversation",
        secrets=("secret-value",),
    )
    body = json.loads(export)
    assert "secret-value" not in body["excerpt"]
    assert len(body["excerpt"].encode()) <= 32_768 and body["truncated"]
    with pytest.raises(ValueError, match="bound"):
        fork_conversation_export(
            b"x" * (MAX_CONVERSATION_BYTES + 1),
            origin=ConversationOrigin(
                request_scope="tenant-1",
                run_id="source",
                repository="repo",
                branch="mc/source",
                head_commit="a" * 40,
                session_ref="agent-1",
                run_ref="native-1",
            ),
        )
