from unittest.mock import AsyncMock

import pytest
from tests.unit.mission_control.test_run_evidence import ACTOR, DIGEST, NOW, setup

from mission_control.adapters.postgres.orchestration.completion_evidence import _decision
from mission_control.application.missions.completion_evidence import CompletionEvidenceCorrupt
from mission_control.application.missions.retrieval import (
    RunEvidenceInconsistent,
    RunEvidenceService,
)
from mission_control.contracts.contracts import MissionControlRejected
from mission_control.contracts.run_evidence import CompletionEvidencePage
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.programs.completion import CompletionValidation
from mission_control.domain.programs.contracts import StageGraphDecisionMutation


def receipt_row(run_id="run-1", scope="tenant-1", version=1, legacy=False):
    validation = (
        {
            "schema_version": "mc.stage_completion_validation.v1",
            "artifact_schema_validation": "not_evaluated",
        }
        if legacy
        else CompletionValidation(
            execution_disposition="completed",
            status="pending",
            candidate_digest=DIGEST,
            reason_codes=("artifact_not_published",),
        ).model_dump(mode="json")
    )
    mutation = StageGraphDecisionMutation(
        mutation_id=f"result-{version}",
        request_scope=scope,
        run_id=run_id,
        expected_family_version=version - 1,
        exact_operation_request_ref="operation:test",
        decided_at=NOW,
        decision_kind="result_decided",
        prior_projection_digest=DIGEST,
        next_projection_digest="sha256:" + "b" * 64,
        decision_payload={"completion_validation": validation},
    )
    return {
        "mutation": mutation.model_dump(mode="json"),
        "mutation_key": mutation.mutation_id,
        "family_version": version,
        "mutation_fingerprint": sha256_digest(
            mutation.model_dump(mode="json", exclude={"decided_at"})
        ),
        "decided_at": NOW,
    }


def test_journal_receipt_preserves_pending_and_legacy_validation():
    record = _decision(receipt_row(), "tenant-1", "run-1")
    assert isinstance(record.validation, CompletionValidation)
    assert record.validation.status == "pending"
    assert record.validation.reason_codes == ("artifact_not_published",)
    legacy = _decision(receipt_row(legacy=True), "tenant-1", "run-1")
    assert legacy.validation["artifact_schema_validation"] == "not_evaluated"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mutation_fingerprint", "sha256:" + "f" * 64),
        ("family_version", 8),
        ("mutation_key", "another"),
    ],
)
def test_journal_integrity_mismatch_is_not_returned(field, value):
    row = receipt_row()
    row[field] = value
    with pytest.raises(CompletionEvidenceCorrupt):
        _decision(row, "tenant-1", "run-1")


def test_cross_run_or_scope_and_invalid_v2_fail_closed():
    for scope, run_id in (("other", "run-1"), ("tenant-1", "another")):
        with pytest.raises(CompletionEvidenceCorrupt):
            _decision(receipt_row(), scope, run_id)
    row = receipt_row()
    row["mutation"]["decision_payload"]["completion_validation"]["status"] = "guessed"
    row["mutation_fingerprint"] = sha256_digest(
        {key: value for key, value in row["mutation"].items() if key != "decided_at"}
    )
    with pytest.raises(CompletionEvidenceCorrupt):
        _decision(row, "tenant-1", "run-1")


@pytest.mark.asyncio
async def test_scoped_completion_page_is_authorized_and_included_in_evidence():
    _, lifecycle, _, _, run_id = await setup()
    reader = AsyncMock()
    record = _decision(receipt_row(run_id=run_id), "tenant-1", run_id)
    reader.list.return_value = CompletionEvidencePage(
        run_id=run_id,
        status="recorded",
        decisions=(record,),
        next_after_family_version=1,
    )
    evidence = RunEvidenceService(lifecycle, completion=reader)
    with pytest.raises(MissionControlRejected):
        await evidence.completion(
            run_id, actor=ActorContext(actor_id="reader", permissions={"workflow_run.read"})
        )
    reader.list.assert_not_awaited()
    page = await evidence.completion(run_id, actor=ACTOR, limit=1)
    assert page.decisions[0].validation.status == "pending"
    reader.list.assert_awaited_once_with("tenant-1", run_id, after_family_version=0, limit=1)
    assert (await evidence.get(run_id, actor=ACTOR)).completion == page
    reader.list.return_value = page.model_copy(update={"next_after_family_version": 9})
    with pytest.raises(RunEvidenceInconsistent, match="cursor"):
        await evidence.completion(run_id, actor=ACTOR)
    reader.list.side_effect = CompletionEvidenceCorrupt("corrupt")
    with pytest.raises(RunEvidenceInconsistent):
        await evidence.completion(run_id, actor=ACTOR)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["duplicate", "reversed", "wrong_scope", "stale_cursor"])
async def test_completion_page_rejects_bad_identity_or_order(case):
    _, lifecycle, _, _, run_id = await setup()
    one = _decision(receipt_row(run_id=run_id), "tenant-1", run_id)
    two = _decision(receipt_row(run_id=run_id, version=2), "tenant-1", run_id)
    records = {
        "duplicate": (one, one),
        "reversed": (two, one),
        "wrong_scope": (one.model_copy(update={"request_scope": "other"}),),
        "stale_cursor": (one,),
    }[case]
    reader = AsyncMock()
    reader.list.return_value = CompletionEvidencePage(
        run_id=run_id, status="recorded", decisions=records
    )
    evidence = RunEvidenceService(lifecycle, completion=reader)
    with pytest.raises(RunEvidenceInconsistent):
        await evidence.completion(
            run_id, actor=ACTOR, after_family_version=1 if case == "stale_cursor" else 0
        )
