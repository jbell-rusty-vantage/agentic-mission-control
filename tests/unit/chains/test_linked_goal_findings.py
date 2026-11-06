"""Full verifier findings follow only the exact finalized producer attempt."""

import copy
import json
from unittest.mock import AsyncMock

import pytest

from mission_control.adapters.postgres.chains.goal_findings import (
    bind_goal_findings,
    load_goal_findings,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.context.transfer_builders import linked_mission
from tests.unit.context.test_linked_transfer import setup
from tests.unit.context.test_transfer_materializer import FakeBackend, dependent
from tests.unit.orchestration.test_goal_exact_context import fixture


def document(identity, payload):
    payload = json.loads(json.dumps(payload))
    return {"identity": identity, "payload": payload, "digest": sha256_digest(payload)}


async def rows():
    request, source, feedback, binding, _, _, iteration, verification = await fixture()
    return {
        "scope": request.request_scope,
        "run_id": binding.run_id,
        "operation_ref": binding.operation_id,
        "operation_attempt": binding.operation_attempt,
        "execution_generation": binding.lane_dispatch.execution_generation,
        "binding_row": document(binding.semantic_attempt_key, binding.model_dump(mode="json")),
        "iteration_row": document(
            json.dumps([binding.run_id, source.identity.semantic_key]), iteration
        ),
        "verification_rows": [
            document(json.dumps([binding.run_id, feedback.verification_id]), verification)
        ],
    }


async def test_full_findings_and_all_document_pins_are_retained():
    args = await rows()
    result = bind_goal_findings(**args)
    assert len(result) == 1
    assert result[0].payload == args["verification_rows"][0]["payload"]
    assert len(result[0].payload["verification"]["findings"][0]) > 50000
    assert result[0].binding_digest == args["binding_row"]["digest"]
    assert result[0].iteration_digest == args["iteration_row"]["digest"]


@pytest.mark.parametrize(
    "change",
    [
        "attempt",
        "generation",
        "scope",
        "run",
        "operation",
        "document_digest",
        "verification_digest",
        "sibling",
        "revision",
    ],
)
async def test_wrong_attempt_sibling_or_digest_fails_closed(change):
    args = await rows()
    if change in {"attempt", "generation"}:
        key = "operation_attempt" if change == "attempt" else "execution_generation"
        args[key] += 1
    elif change in {"scope", "run", "operation"}:
        args[{"scope": "scope", "run": "run_id", "operation": "operation_ref"}[change]] += "-other"
    elif change == "document_digest":
        args["binding_row"]["digest"] = "sha256:" + "0" * 64
    else:
        row = args["verification_rows"][0]
        payload = row["payload"]
        if change == "verification_digest":
            payload["verification"]["findings"] = ["tampered after verifier"]
        elif change == "sibling":
            payload["verification"]["executor_identity"]["agent_run"] += 1
        else:
            payload["goal_revision_id"] = "sibling-revision"
        row["digest"] = sha256_digest(payload)
    with pytest.raises(ValueError):
        bind_goal_findings(**args)


async def test_goal_missing_verifier_refuses_and_non_goal_needs_no_documents():
    args = await rows()
    args["verification_rows"] = []
    with pytest.raises(ValueError, match="full actual verifier"):
        bind_goal_findings(**args)
    connection = AsyncMock()
    assert (
        await load_goal_findings(
            connection,
            (),
            scope="scope",
            run_id="run",
            operation_ref="run:stage:produce:1",
            operation_attempt=1,
            execution_generation=1,
        )
        is None
    )
    connection.fetch.assert_not_called()


async def test_repair_file_contains_full_frozen_goal_payload_and_no_official_use(monkeypatch):
    args = await rows()
    snapshots = bind_goal_findings(**args)
    h = setup(monkeypatch, repair=True)
    old = h.export.model_dump(mode="json")
    assert "goal_findings" not in old["outputs"][0]
    h.exports.export = h.export.model_copy(
        update={
            "placement": "file",
            "outputs": (h.export.outputs[0].model_copy(update={"goal_findings": snapshots}),),
        }
    )
    selection = linked_mission(dependent(), (h.exports.export,))
    result = await h.s.materializer.materialize(h.s.request(selection), FakeBackend())
    findings = [
        json.loads(content)["payload"]
        for _, content in result.files
        if b"mc.linked-subject-findings.v1" in content
    ]
    assert len(findings) == 1 and findings[0]["official_use"] is False
    assert findings[0]["goal_findings"][0]["payload"] == args["verification_rows"][0]["payload"]
    assert not h.s.outputs.accepted
    # Default field omission preserves already released positive and legacy repair identities.
    assert h.export.model_dump(mode="json") == old
    assert h.export.digest == type(h.export).model_validate(copy.deepcopy(old)).digest
