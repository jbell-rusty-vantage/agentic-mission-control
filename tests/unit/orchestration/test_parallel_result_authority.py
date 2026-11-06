from __future__ import annotations

from typing import Any

import pytest

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.policies.contracts import (
    AcceptedOutputEvidence,
    CommandStatus,
    RecordOutputEvidenceAction,
)
from tests.unit.orchestration.test_completion_validation_service import prepared
from tests.unit.run_control.test_run_control import DIGEST, command


@pytest.mark.asyncio
async def test_sibling_authority_cas_loss_rebuilds_result_without_poisoning_decision_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = await prepared()
    original = fixture.repository.commit_family_admission
    attempts: list[Any] = []

    async def commit(mutation: Any):  # type: ignore[no-untyped-def]
        attempts.append(mutation)
        if len(attempts) == 1:
            run = await fixture.run_control.get_run(fixture.scope, fixture.result.run_id)
            sibling = await fixture.run_control.execute(
                command(
                    run.run_id,
                    run.version,
                    "sibling-completed",
                    RecordOutputEvidenceAction(
                        evidence=AcceptedOutputEvidence(
                            output_ref="output:sibling",
                            evidence_digest=DIGEST,
                            accepted_by_authority_ref="authority:lifecycle",
                        ),
                    ),
                ).model_copy(update={"request_scope": fixture.scope})
            )
            assert sibling.status is CommandStatus.ACCEPTED
        return await original(mutation)

    monkeypatch.setattr(fixture.repository, "commit_family_admission", commit)
    result = await fixture.service.decide_result(fixture.result)
    assert result.accepted and len(attempts) == 2
    assert all(item.receipt.command_result.status is CommandStatus.ACCEPTED for item in attempts)
    assert attempts[0].family_mutation.mutation_id == attempts[1].family_mutation.mutation_id
    assert attempts[0].family_mutation.prior_projection_digest == (
        attempts[1].family_mutation.prior_projection_digest
    )
    command_id = (
        "stagegraph:result-"
        + sha256_digest(
            fixture.result.observation.identity.semantic_key,
        )[7:]
    )
    persisted = await fixture.repository.get_family_admission_receipt(
        fixture.scope,
        fixture.result.run_id,
        fixture.result.idempotency_issuer,
        command_id,
    )
    assert persisted is not None and persisted.command_result.status is CommandStatus.ACCEPTED
    assert await fixture.service.decide_result(fixture.result) == result
    assert len(attempts) == 2
