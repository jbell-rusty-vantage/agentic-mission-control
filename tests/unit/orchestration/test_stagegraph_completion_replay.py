"""A lost completion reply must not turn a committed terminalization into stale work."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from mission_control.application.programs.service import StageGraphDecisionService
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.policies.errors import RunControlNotFound
from mission_control.domain.programs.contracts import (
    StageGraphCompletionActivityRequest,
    StageGraphDecisionMutation,
)
from tests.unit.orchestration.test_budget_admission_failure import prepared


async def completion():
    control, repository, candidate, interpreter = await prepared()
    refused = await StageGraphDecisionService(control, repository).admit_operation(candidate)
    run = await control.get_run(candidate.request_scope, candidate.run_id)
    proposal = interpreter.failure_completion(refused.projection)
    assert proposal is not None
    request = StageGraphCompletionActivityRequest(
        run_id=candidate.run_id,
        request_scope=candidate.request_scope,
        projection=refused.projection,
        proposal=proposal,
        workflow_type_digest=run.workflow_type_ref.digest,
        occurred_at=candidate.occurred_at,
        idempotency_issuer=candidate.idempotency_issuer,
        correlation_id=candidate.correlation_id,
    )
    return control, repository, request


def snapshot(repository):
    return deepcopy(
        {
            key: value
            for key, value in vars(repository).items()
            if key not in {"_lock", "_before_commit", "mailbox"} and not callable(value)
        }
    )


@pytest.mark.asyncio
async def test_exact_completion_retry_after_restart_reads_committed_receipt(monkeypatch):
    control, repository, request = await completion()
    result = await StageGraphDecisionService(control, repository).complete(request)
    assert result.accepted and result.terminal_outcome.value == "failed"
    before = snapshot(repository)

    async def no_commit(_):
        pytest.fail("a committed request must replay before any second commit")

    monkeypatch.setattr(repository, "commit_family_admission", no_commit)
    service = StageGraphDecisionService(control, repository)
    assert await service.complete(request) == result
    assert await service.complete(request) == result
    assert snapshot(repository) == before


@pytest.mark.asyncio
async def test_completion_commit_reply_loss_replays_without_second_commit(monkeypatch):
    control, repository, request = await completion()
    commit = repository.commit_family_admission
    calls = 0
    committed = None

    async def lose_reply(mutation):
        nonlocal calls, committed
        calls += 1
        committed = await commit(mutation)
        raise TimeoutError("reply lost after the atomic commit returned")

    monkeypatch.setattr(repository, "commit_family_admission", lose_reply)
    with pytest.raises(TimeoutError, match="reply lost"):
        await StageGraphDecisionService(control, repository).complete(request)
    before = snapshot(repository)
    result = await StageGraphDecisionService(control, repository).complete(request)
    assert committed is not None and result.accepted
    assert result.resulting_run_version == committed.command_result.resulting_run_version
    assert result.terminal_outcome == committed.command_result.terminal_outcome
    assert calls == 1 and snapshot(repository) == before


@pytest.mark.asyncio
async def test_completion_replays_the_postgres_json_journal_representation(monkeypatch):
    control, repository, request = await completion()
    result = await StageGraphDecisionService(control, repository).complete(request)
    before = snapshot(repository)
    read = repository.get_family_mutation

    async def persisted(*args):
        mutation = await read(*args)
        return StageGraphDecisionMutation.model_validate_json(mutation.model_dump_json())

    monkeypatch.setattr(repository, "get_family_mutation", persisted)
    assert await StageGraphDecisionService(control, repository).complete(request) == result
    assert snapshot(repository) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field", ["correlation", "timestamp", "workflow", "proposal", "issuer", "scope", "run", "epoch"]
)
async def test_completion_rejects_conflicting_identity_or_request(field):
    control, repository, request = await completion()
    await StageGraphDecisionService(control, repository).complete(request)
    before = snapshot(repository)
    changed = {
        "correlation": {"correlation_id": request.correlation_id + "-changed"},
        "timestamp": {"occurred_at": request.occurred_at + timedelta(microseconds=1)},
        "workflow": {"workflow_type_digest": "sha256:" + "f" * 64},
        "proposal": {"proposal": replace(request.proposal, valid_output_refs=("different",))},
        "issuer": {"idempotency_issuer": request.idempotency_issuer + "-changed"},
        "scope": {"request_scope": request.request_scope + "-changed"},
        "run": {"run_id": request.run_id + "-changed"},
        "epoch": {
            "projection": replace(
                request.projection,
                identity=replace(
                    request.projection.identity,
                    execution_epoch=request.projection.identity.execution_epoch + 1,
                ),
            )
        },
    }[field]
    with pytest.raises((ValueError, RunControlNotFound)):
        await StageGraphDecisionService(control, repository).complete(replace(request, **changed))
    assert snapshot(repository) == before


@pytest.mark.asyncio
async def test_stale_uncommitted_completion_still_rejects_without_writing():
    control, repository, request = await completion()
    stale = replace(request, projection=replace(request.projection, family_version=0))
    before = snapshot(repository)
    with pytest.raises(ValueError, match="stale against the family head"):
        await StageGraphDecisionService(control, repository).complete(stale)
    assert snapshot(repository) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    ["missing", "legacy", "projection", "fingerprint", "family_version", "identity", "outcome"],
)
async def test_completion_replay_refuses_inconsistent_persisted_evidence(monkeypatch, corruption):
    control, repository, request = await completion()
    await StageGraphDecisionService(control, repository).complete(request)
    before = snapshot(repository)
    read_mutation, read_receipt = (
        repository.get_family_mutation,
        repository.get_family_admission_receipt,
    )

    async def mutation(*args):
        value = await read_mutation(*args)
        if value is None or not value.mutation_id.startswith("complete-"):
            return value
        if corruption == "missing":
            return None
        payload = dict(value.decision_payload)
        if corruption == "legacy":
            payload.pop("completion_request_digest")
        if corruption == "projection":
            payload["projection"] = {**payload["projection"], "run_version": 999}
        return value.model_copy(update={"decision_payload": payload})

    async def receipt(*args):
        value = await read_receipt(*args)
        if value is None or value.family_receipt is None:
            return value
        if corruption == "fingerprint":
            return value.model_copy(update={"family_mutation_fingerprint": sha256_digest("wrong")})
        if corruption == "family_version":
            return value.model_copy(
                update={
                    "family_receipt": value.family_receipt.model_copy(
                        update={"family_version": 999}
                    )
                }
            )
        if corruption in {"identity", "outcome"}:
            change = (
                {"command_id": "different"}
                if corruption == "identity"
                else {"terminal_outcome": None}
            )
            return value.model_copy(
                update={"command_result": value.command_result.model_copy(update=change)}
            )
        return value

    monkeypatch.setattr(repository, "get_family_mutation", mutation)
    monkeypatch.setattr(repository, "get_family_admission_receipt", receipt)
    with pytest.raises(ValueError):
        await StageGraphDecisionService(control, repository).complete(request)
    assert snapshot(repository) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_rejected_completion_replays_and_later_proposal_uses_next_identity(
    monkeypatch, legacy
):
    from mission_control.domain.policies.errors import IdempotencyConflict

    control, repository, request = await completion()
    budget = repository._budgets[request.run_id]
    repository._budgets[request.run_id] = budget.model_copy(
        update={
            "reserved": {"tokens.total": 1},
            "reservations": {"held": {"tokens.total": 1}},
        }
    )
    service = StageGraphDecisionService(control, repository)
    original = service._mutation

    def old_mutation(*args, **kwargs):
        kwargs["decision_payload"].pop("completion_request_digest", None)
        return original(*args, **kwargs)

    if legacy:
        monkeypatch.setattr(service, "_mutation", old_mutation)
    result = await service.complete(request)
    assert not result.accepted and result.reason_code == "budget_not_settled"
    before = snapshot(repository)
    fresh = StageGraphDecisionService(control, repository)
    assert await fresh.complete(request) == result
    assert snapshot(repository) == before
    with pytest.raises(IdempotencyConflict):
        await fresh.complete(replace(request, correlation_id=request.correlation_id + "-changed"))
    assert snapshot(repository) == before
    later = replace(request, occurred_at=request.occurred_at + timedelta(seconds=1))
    assert not (await fresh.complete(later)).accepted
    ids = [
        key[-1] for key in repository._family_results if key[-1].startswith("stagegraph:complete-")
    ]
    assert len(ids) == 2 and any(key.endswith(":retry:1") for key in ids)
