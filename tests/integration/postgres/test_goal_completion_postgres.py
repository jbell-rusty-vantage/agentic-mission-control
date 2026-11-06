"""Goal schema checks and request-bound replay survive actual database recomposition."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from unittest.mock import AsyncMock

import pytest

from mission_control.adapters.operations.runtime_ports import FilesystemArtifactPayloadStore
from mission_control.adapters.postgres.context.artifact_bytes import PostgresArtifactBytes
from mission_control.adapters.postgres.orchestration.goal_completion_evidence import (
    PostgresGoalCompletionEvidenceReader,
)
from mission_control.adapters.postgres.orchestration.goal_directed_repository import (
    PostgresGoalDirectedDocumentRepository,
)
from mission_control.adapters.postgres.workspace_candidate_contents import (
    PostgresWorkspaceCandidateContents,
)
from mission_control.application.programs.completion_validation import ArtifactPublicationPending
from mission_control.application.programs.goal_directed import GoalDirectedOperationResultService
from mission_control.domain.execution.contracts import CapturedWorkspaceCandidate, WorkspaceOwner
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.unit.orchestration.test_artifact_schema_validation import Custody, captured
from tests.unit.orchestration.test_goal_schema_completion import (
    OUTPUT,
    SUMMARY,
    ScopedCustody,
    goal_request,
    multi_goal_request,
)

pytestmark = pytest.mark.common_db


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign_summary", [False, True])
async def test_named_goal_reads_only_registered_same_scope_bytes(
    common_db, tmp_path, foreign_summary
):
    scope = common_db.scope()
    request = multi_goal_request(scope).model_copy(
        update={"recorded_at": datetime.now(UTC) - timedelta(minutes=16)}
    )
    pool = await common_db.pool()
    payloads = FilesystemArtifactPayloadStore(tmp_path / "payloads")
    try:
        for slot, ref, raw in (
            ("report", OUTPUT, b'{"count":1}'),
            ("summary", SUMMARY, b'{"summary":"qualified"}'),
        ):
            custody_scope = (
                common_db.scope("tenant-2") if slot == "summary" and foreign_summary else scope
            )
            candidate = CapturedWorkspaceCandidate(
                namespace_id="run/goal-proof",
                workspace_id="workspace:goal-proof",
                output_slot=slot,
                logical_path=f"/work/{slot}.json",
                owner=WorkspaceOwner(kind="run", owner_id="goal-proof"),
                candidate_id=ref.removeprefix("workspace-candidate://"),
                content_digest="sha256:" + sha256(raw).hexdigest(),
                media_type="application/json",
                size_bytes=len(raw),
            )
            await PostgresWorkspaceCandidateContents(
                pool, payloads, request_scope=custody_scope
            ).put(candidate, raw)
        payloads.retrieve = AsyncMock(wraps=payloads.retrieve)
        service = GoalDirectedOperationResultService(
            PostgresGoalDirectedDocumentRepository(pool),
            artifacts=PostgresArtifactBytes(pool, payloads),
        )
        result = await service.reconcile(request)
        assert result.verification_result.decision == (
            "rejected" if foreign_summary else "accepted"
        )
        assert payloads.retrieve.await_count == (1 if foreign_summary else 2)
        assert bool(result.verification_result.accepted_obligation_refs) == (not foreign_summary)
        payloads.retrieve.reset_mock()
        assert await service.reconcile(request) == result
        assert payloads.retrieve.await_count == 0
    finally:
        await pool.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "expected"), [('{"count":1}', "satisfied"), ('{"count":"bad"}', "unsatisfied")]
)
async def test_goal_publication_recomposition_and_receipt_retrieval(common_db, body, expected):
    request = goal_request(common_db.scope())
    pool = await common_db.pool()
    try:
        service = GoalDirectedOperationResultService(
            PostgresGoalDirectedDocumentRepository(pool), artifacts=Custody(None)
        )
        with pytest.raises(ArtifactPublicationPending):
            await service.reconcile(request)
    finally:
        await pool.close()
    pool = await common_db.pool()
    try:
        service = GoalDirectedOperationResultService(
            PostgresGoalDirectedDocumentRepository(pool),
            artifacts=Custody(captured(body, source_ref=OUTPUT)),
        )
        result = await service.reconcile(request)
        assert result.completion_validation.status == expected
        reader = PostgresGoalCompletionEvidenceReader(pool)
        run_id = request.claim.identity.iteration.run_id
        page = await reader.read(common_db.scope(), run_id, None, 1)
        assert len(page.decisions) == 1
        assert page.decisions[0].validation == result.completion_validation
        assert (await reader.read(common_db.scope("tenant-2"), run_id, None, 1)).decisions == ()
        cursor = page.decisions[0].verification.verification_id
        assert (await reader.read(common_db.scope(), run_id, cursor, 1)).decisions == ()
        with pytest.raises(ValueError, match="cursor"):
            await reader.read(common_db.scope("tenant-2"), run_id, cursor, 1)
    finally:
        await pool.close()
    pool = await common_db.pool()
    try:
        custody = Custody(None)
        resumed = await GoalDirectedOperationResultService(
            PostgresGoalDirectedDocumentRepository(pool), artifacts=custody
        ).reconcile(request)
        assert resumed == result and custody.calls == []
    finally:
        await pool.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["valid", "missing", "extra", "invalid", "cross_scope"])
async def test_named_goal_receipts_preserve_every_output_and_reject_altered_bindings(
    common_db, case
):
    scope = common_db.scope()
    request = multi_goal_request(scope)
    custody = ScopedCustody(scope)
    if case == "missing":
        request = request.model_copy(
            update={
                "executor_result": replace(
                    request.executor_result,
                    output_refs=(OUTPUT,),
                    output_bindings={"report": (OUTPUT,)},
                )
            }
        )
    elif case == "extra":
        request = request.model_copy(
            update={
                "executor_result": replace(
                    request.executor_result,
                    output_refs=(OUTPUT, SUMMARY, "workspace-candidate://extra"),
                )
            }
        )
    elif case == "invalid":
        custody.contents[(scope, SUMMARY)] = captured('{"summary":42}', source_ref=SUMMARY)
    elif case == "cross_scope":
        custody.contents[(common_db.scope("tenant-2"), SUMMARY)] = custody.contents.pop(
            (scope, SUMMARY)
        )
        request = request.model_copy(
            update={"recorded_at": datetime.now(UTC) - timedelta(minutes=16)}
        )
    pool = await common_db.pool()
    try:
        service = GoalDirectedOperationResultService(
            PostgresGoalDirectedDocumentRepository(pool), artifacts=custody
        )
        result = await service.reconcile(request)
        assert result.verification_result.decision == (
            "accepted" if case == "valid" else "rejected"
        )
        assert bool(result.verification_result.accepted_obligation_refs) == (case == "valid")
    finally:
        await pool.close()
    pool = await common_db.pool()
    try:
        custody.contents.clear()
        custody.calls.clear()
        service = GoalDirectedOperationResultService(
            PostgresGoalDirectedDocumentRepository(pool), artifacts=custody
        )
        assert await service.reconcile(request) == result
        assert custody.calls == []
        reader = PostgresGoalCompletionEvidenceReader(pool)
        run_id = request.claim.identity.iteration.run_id
        page = await reader.read(scope, run_id, None, 100)
        assert len(page.decisions) == 1
        assert page.decisions[0].validation == result.completion_validation
        assert not (await reader.read(common_db.scope("tenant-2"), run_id, None, 100)).decisions
        changed = request.model_copy(
            update={
                "executor_result": replace(
                    request.executor_result,
                    output_bindings={"report": (SUMMARY,), "summary": (OUTPUT,)},
                )
            }
        )
        with pytest.raises(ValueError, match="replay differs"):
            await service.reconcile(changed)
    finally:
        await pool.close()
