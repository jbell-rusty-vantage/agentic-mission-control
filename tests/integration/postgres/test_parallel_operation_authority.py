"""Real restricted PostgreSQL authority: distinct parallel journal effects and exact replay."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from mission_control.adapters.postgres.operations.operation_journal import (
    PostgresAtomicOperationJournalRepository,
)
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadAddress
from mission_control.application.execution.operations.journaled_operation_execution import (
    JournaledOperationExecutionCoordinator,
)
from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
)
from mission_control.application.execution.operations.operation_journal import (
    OperationJournalService,
)
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationSettlement,
    RuntimeUsage,
)
from mission_control.domain.policies.contracts import (
    CommandStatus,
    ReserveBudgetAction,
    StartAction,
)
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.integration.postgres.runtime_common import scoped_command, scoped_request
from tests.unit.operations.test_operation_execution import operation_request
from tests.unit.run_control.test_run_control import NOW, actor, service

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]


class Payloads:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    async def stage(
        self, *, artifact_id: str, content: bytes, content_digest: str, media_type: str
    ) -> ArtifactPayloadAddress:
        del media_type
        self.values[artifact_id] = content
        return ArtifactPayloadAddress(
            object_ref=f"artifact:{artifact_id}",
            content_digest=content_digest,
            size_bytes=len(content),
        )

    async def retrieve(self, address: ArtifactPayloadAddress) -> bytes:
        return self.values[address.object_ref.removeprefix("artifact:")]


async def test_distinct_parallel_journal_claim_observe_settle_and_exact_replay(
    common_db: CommonDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = common_db.scope()
    pool = await common_db.pool("mission_control_runtime", max_size=6)
    try:
        repository = PostgresRunControlRepository(pool)
        control, _ = service(cast(Any, repository))
        admitted = await control.admit(scoped_request(common_db))
        assert admitted.run_id is not None
        run_id = admitted.run_id
        await control.execute(scoped_command(common_db, run_id, 1, "start", StartAction()))
        await control.execute(
            scoped_command(
                common_db,
                run_id,
                2,
                "reserve-right",
                ReserveBudgetAction(reservation_id="right", amounts={"tokens.total": 20}),
            )
        )
        bindings = tuple(
            bind_operation_execution_request(
                operation_request().model_copy(
                    update={
                        "request_scope": scope,
                        "identity": OperationAttemptIdentity(
                            run_id=run_id,
                            operation_id=name,
                            operation_attempt=1,
                        ),
                        "run_control_revision": 3,
                        "budget_reservation_id": "baseline" if name == "left" else "right",
                        "budget_limits": {"tokens.total": 20},
                        "idempotency_key": f"effect:{name}",
                    }
                )
            )
            for name in ("left", "right")
        )
        journal = OperationJournalService(PostgresAtomicOperationJournalRepository(pool))
        coordinator = JournaledOperationExecutionCoordinator(
            journal=journal,
            run_control=control,
            results=Payloads(),
            actor=actor(),
        )
        barriers = {kind: asyncio.Barrier(2) for kind in ("claim", "observation", "settlement")}
        seen: dict[str, set[str]] = {kind: set() for kind in barriers}
        attempts: list[Any] = []
        original = repository.commit_command

        async def commit(mutation: Any):  # type: ignore[no-untyped-def]
            result = mutation.result
            if result.idempotency_issuer == "operation-journal":
                attempts.append(mutation)
                kind = next(
                    (
                        name
                        for name, prefix in (
                            ("claim", "operation-effect-claim:"),
                            ("observation", "operation-effect-observation:"),
                            ("settlement", "operation-authority-settlement:"),
                        )
                        if result.command_id.startswith(prefix)
                    ),
                    None,
                )
                if kind is not None and result.command_id not in seen[kind] and len(seen[kind]) < 2:
                    seen[kind].add(result.command_id)
                    await asyncio.wait_for(barriers[kind].wait(), 20)
            return await original(mutation)

        monkeypatch.setattr(repository, "commit_command", commit)
        claims = await asyncio.gather(
            *(
                coordinator.acquire(binding, claimed_by=f"worker:{binding.operation_id}")
                for binding in bindings
            )
        )
        assert all(item.status == "acquired" and item.claim is not None for item in claims)
        results = await asyncio.gather(
            *(
                coordinator.settle(
                    binding,
                    cast(Any, acquired.claim),
                    OperationSettlement(
                        settlement_id=f"settlement:{binding.operation_id}",
                        binding_id=binding.binding_id,
                        status="completed",
                        output_text=binding.operation_id,
                        usage=RuntimeUsage(amounts={"tokens.total": 5}),
                        provider_run_id=f"provider:{binding.operation_id}",
                        settled_at=NOW,
                    ),
                    started_at=NOW,
                )
                for binding, acquired in zip(bindings, claims, strict=True)
            )
        )
        for binding, result in zip(bindings, results, strict=True):
            assert await coordinator.get_settlement(binding) == result
            replay = await coordinator.acquire(binding, claimed_by=f"worker:{binding.operation_id}")
            assert replay.status == "existing"
        budget = await control.get_budget(scope, run_id)
        effects = await control.get_effects(scope, run_id)
        assert budget.consumed["tokens.total"] == 10
        assert not any(budget.reserved.values())
        assert len(budget.usage_records) == len(effects.claims) == 2
        assert all(effect.settlement is not None for effect in effects.claims.values())
        assert all(len(values) == 2 for values in seen.values())
        assert all(item.result.status is CommandStatus.ACCEPTED for item in attempts)
    finally:
        await pool.close()
