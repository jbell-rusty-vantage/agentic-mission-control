"""Builders, constants and fakes that other test files import.

Moved from tests/unit/mission_control/test_completion_evidence.py.
"""

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.programs.completion import CompletionValidation
from mission_control.domain.programs.contracts import StageGraphDecisionMutation
from tests.support.run_control import DIGEST
from tests.support.unit.mission_control.run_evidence import NOW


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
