from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mission_control.domain.authoring.canonical import contract_fingerprint
from mission_control.domain.policies.contracts import (
    ClaimEffectAction,
    CommandStatus,
    RunPhase,
    StartAction,
)
from mission_control.domain.policies.errors import CommandRejected, IdempotencyConflict
from tests.unit.run_control.test_run_control import DIGEST, command, request, service


def claim(run_id: str, name: str):  # type: ignore[no-untyped-def]
    return command(
        run_id,
        2,
        f"claim:{name}",
        ClaimEffectAction(
            effect_id=f"effect:{name}",
            effect_kind="operation.runtime",
            operation_ref=f"binding:{name}",
            provider_idempotency_key=f"provider:{name}",
            reservation_id="baseline",
            claim_payload_digest=DIGEST,
        ),
    ).model_copy(update={"idempotency_issuer": "operation-journal"})


def active(run: Any, budget: Any, effects: Any) -> None:
    del budget, effects
    if run.phase != RunPhase.ACTIVE:
        raise ValueError("dispatch authority changed")


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate", [False, True])
async def test_parallel_fixed_journal_commands_retry_cas_without_stored_stale(
    monkeypatch: pytest.MonkeyPatch,
    duplicate: bool,
) -> None:
    control, repository = service()
    admission = await control.admit(request())
    run_id = admission.run_id
    assert run_id is not None
    await control.execute(command(run_id, 1, "start", StartAction()))
    original = repository.commit_command
    barrier = asyncio.Barrier(2)
    attempts: list[Any] = []

    async def commit(mutation: Any):  # type: ignore[no-untyped-def]
        attempts.append(mutation)
        if len(attempts) <= 2:
            await barrier.wait()
        return await original(mutation)

    monkeypatch.setattr(repository, "commit_command", commit)
    first, second = await asyncio.gather(
        control.execute_operation_authority(claim(run_id, "left"), validate_authority=active),
        control.execute_operation_authority(
            claim(run_id, "left" if duplicate else "right"),
            validate_authority=active,
        ),
    )
    assert all(result.status is CommandStatus.ACCEPTED for _, result in (first, second))
    assert len((await control.get_effects("tenant-1", run_id)).claims) == (1 if duplicate else 2)
    assert all(mutation.result.status is CommandStatus.ACCEPTED for mutation in attempts)
    for issued, accepted in (first, second):
        assert accepted.command_fingerprint == contract_fingerprint(issued, exclude={"occurred_at"})
        replay = await control.execute_operation_authority(
            issued.model_copy(update={"expected_run_version": 999}),
            validate_authority=active,
        )
        assert replay == (issued, accepted)
    if duplicate:
        assert first == second


@pytest.mark.asyncio
async def test_public_stale_and_preexisting_failed_journal_receipts_remain_immutable() -> None:
    control, _ = service()
    admitted = await control.admit(request())
    assert admitted.run_id is not None
    stale = claim(admitted.run_id, "old")
    failed = await control.execute(stale)
    assert failed.status is CommandStatus.STALE
    with pytest.raises(IdempotencyConflict, match="not accepted"):
        await control.execute_operation_authority(stale, validate_authority=active)
    assert (
        await control.get_command_result(
            "tenant-1",
            admitted.run_id,
            "operation-journal",
            stale.command_id,
        )
        == failed
    )


@pytest.mark.asyncio
async def test_current_authority_cannot_refresh_public_controls_or_alter_payload() -> None:
    control, _ = service()
    admitted = await control.admit(request())
    assert admitted.run_id is not None
    run_id = admitted.run_id
    start = command(run_id, 1, "start", StartAction())
    with pytest.raises(CommandRejected, match="restricted"):
        await control.execute_operation_authority(start, validate_authority=active)
    await control.execute(start)
    original = claim(run_id, "bound")
    await control.execute_operation_authority(original, validate_authority=active)
    changed = original.model_copy(update={"evidence_refs": ("forged:context",)})
    with pytest.raises(IdempotencyConflict, match="conflicting payload"):
        await control.execute_operation_authority(changed, validate_authority=active)
