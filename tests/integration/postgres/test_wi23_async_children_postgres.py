"""OVE-184 on real PostgreSQL (restricted ``mission_control_runtime`` login, forced RLS).

- **Sealed binding custody**: the governed spawn writes the parent's sealed contract (its
  ``child_binding`` included) to ``subordinate_contract`` before any provider call; the Agent
  Server's custody read returns exactly that contract under the parent's scope, re-verified,
  and nothing under another tenant's scope.
- **Check-time admission**: a completed child is decided once through the registered policy
  while the parent runs (PostgreSQL authority, link detail and the run-control decision
  agree); a second check reads the decision back; the parent boundary then settles the child
  exactly once against the parent run (effect succeeded, usage settled) without re-deciding.

No schema change: OVE-184 reuses the immutable, scoped ``subordinate_contract`` row as the
sealed binding's custody (no migration 0062).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.async_subagents.async_subagent_detail_repository import (
    PostgresAsyncSubagentDetailRepository,
)
from mission_control.adapters.postgres.async_subagents.async_subagents import (
    PostgresAsyncSubagentAuthority,
)
from mission_control.adapters.postgres.async_subagents.sealed_child_custody import (
    PostgresSealedChildCustody,
)
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.application.subordinates.admission import CheckTimeAdmission
from mission_control.application.subordinates.parent_completion import (
    ASYNC_RESULT_POLICIES,
    AsyncChildCompletion,
)
from mission_control.application.subordinates.parent_effects import (
    RunControlAsyncChildEffects,
    async_child_effect_id,
)
from mission_control.application.subordinates.service import AsyncSubagentService
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.async_subagent_reconciliation import (
    AsyncServedGraphIdentity,
)
from mission_control.domain.execution.contracts import (
    AsyncSubagentContract,
    AsyncSubagentDependencyClass,
    AsyncSubagentLifecycle,
    OperationExecutionBinding,
)
from mission_control.domain.policies.contracts import (
    CommandStatus,
    EffectDisposition,
    ReserveBudgetAction,
    StartAction,
)
from tests.acceptance.control_plane.test_wp_cp_040 import exact_fixture
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.integration.postgres.runtime_common import owner_rows, scoped_command, scoped_request
from tests.unit.operations.test_async_child_check_time_admission import (
    TEXT,
    ExactProvider,
    _sealed_contract,
)
from tests.unit.operations.test_async_child_parent_budget import spawn
from tests.unit.run_control.test_run_control import actor
from tests.unit.run_control.test_run_control import service as run_control_service

pytestmark = pytest.mark.common_db


class SealedHostProvider(ExactProvider):
    """The deterministic provider serving the sealed-child graph's host identity."""

    async def verify_served_graph(
        self, contract: AsyncSubagentContract
    ) -> AsyncServedGraphIdentity:
        self.events.append("provider.verify")
        return AsyncServedGraphIdentity(
            graph_id=contract.graph_id,
            graph_revision=contract.graph_revision,
            graph_binding_digest=sha256_digest("sealed-child host template"),
            deepagents_version="0.7.5",
            binding_mode="sealed_child",
        )


@dataclass(frozen=True)
class Stack:
    db: CommonDatabase
    pool: asyncpg.Pool
    scope: str
    run_id: str
    run_control: Any
    service: AsyncSubagentService
    provider: SealedHostProvider
    authority: PostgresAsyncSubagentAuthority


@pytest_asyncio.fixture
async def stack(common_db: CommonDatabase) -> AsyncIterator[Stack]:
    pool = await common_db.pool(max_size=8)
    try:
        run_control, _ = run_control_service(PostgresRunControlRepository(pool))  # type: ignore[arg-type]
        admitted = await run_control.admit(scoped_request(common_db, request_id="wi23-parent"))
        assert admitted.run_id is not None
        run_id = admitted.run_id
        started = await run_control.execute(
            scoped_command(common_db, run_id, 1, "wi23-start", StartAction())
        )
        assert started.status == CommandStatus.ACCEPTED
        reserved = await run_control.execute(
            scoped_command(
                common_db,
                run_id,
                started.resulting_run_version,
                "wi23-reserve-parent",
                ReserveBudgetAction(
                    reservation_id="reservation:parent-operation", amounts={"tokens.total": 20}
                ),
            )
        )
        assert reserved.status == CommandStatus.ACCEPTED
        authority = PostgresAsyncSubagentAuthority(pool)
        provider = SealedHostProvider([])
        service = AsyncSubagentService(
            PostgresAsyncSubagentDetailRepository(pool),
            authority,
            provider,
            parent_effects=RunControlAsyncChildEffects(run_control, actor=actor()),
            allow_new_spawns=True,
        )
        yield Stack(
            common_db,
            pool,
            common_db.scope(),
            run_id,
            run_control,
            service,
            provider,
            authority,
        )
    finally:
        await pool.close()


def _parent(stack: Stack) -> OperationExecutionBinding:
    from types import SimpleNamespace

    return cast(
        OperationExecutionBinding,
        SimpleNamespace(request_scope=stack.scope, run_id=stack.run_id, binding_id="binding-1"),
    )


async def _spawn_sealed(stack: Stack) -> tuple[AsyncSubagentContract, str]:
    base, _profile, _bundle = exact_fixture()
    contract = _sealed_contract(base.model)
    request = spawn(stack.run_id).model_copy(
        update={
            "request_scope": stack.scope,
            "contract": contract,
            "dependency_class": AsyncSubagentDependencyClass.NONBLOCKING,
        }
    )
    child = await stack.service.spawn(request)
    return contract, child.child_execution_id


@pytest.mark.asyncio
async def test_the_sealed_binding_is_in_scoped_custody_before_any_provider_call(
    stack: Stack,
) -> None:
    contract, child_id = await _spawn_sealed(stack)
    assert stack.provider.events[:2] == ["provider.verify", "provider.start"]
    custody = PostgresSealedChildCustody(stack.pool)
    stored = await custody.contract(stack.scope, contract.contract_digest)
    assert stored == contract
    assert stored is not None and stored.child_binding == contract.child_binding
    await stack.db.add_tenants(["tenant-2"])
    assert await custody.contract(stack.db.scope("tenant-2"), contract.contract_digest) is None
    assert await custody.contract(stack.scope, sha256_digest("another contract")) is None
    rows = await owner_rows(
        stack.db,
        "SELECT payload->'child_binding'->>'sealed_digest' AS sealed "
        "FROM mission_control.subordinate_contract WHERE contract_digest = $1",
        contract.contract_digest,
    )
    assert [row["sealed"] for row in rows] == [contract.graph_binding_digest]
    execution = await stack.service.execution(stack.scope, child_id)
    assert execution.contract_digest == contract.contract_digest


@pytest.mark.asyncio
async def test_check_time_admission_decides_once_and_the_boundary_settles_once(
    stack: Stack,
) -> None:
    contract, child_id = await _spawn_sealed(stack)
    admission = CheckTimeAdmission(stack.service, policies=ASYNC_RESULT_POLICIES)
    running = await stack.service.reconcile(stack.scope, child_id)
    pending = await admission.admit(_parent(stack), contract, running, current_generation=1)
    assert (pending.status, pending.reason) == ("pending", "child_active")

    stack.provider.next_status = "success"
    completed = await stack.service.reconcile(stack.scope, child_id)
    assert completed.lifecycle == AsyncSubagentLifecycle.COMPLETED
    first = await admission.admit(_parent(stack), contract, completed, current_generation=1)
    second = await admission.admit(_parent(stack), contract, completed, current_generation=1)
    assert (first.status, first.newly_decided, first.output_text) == ("admitted", True, TEXT)
    assert (second.status, second.newly_decided) == ("admitted", False)
    assert second.entry == first.entry

    manifest = completed.result_manifest
    assert manifest is not None
    rows = await owner_rows(
        stack.db,
        "SELECT result_decision, result_manifest_digest FROM mission_control.subordinate_admission "
        "WHERE subordinate_key = $1",
        child_id,
    )
    assert [(row["result_decision"], row["result_manifest_digest"]) for row in rows] == [
        ("admit", manifest.manifest_digest)
    ]
    run = await stack.run_control.get_run(stack.scope, stack.run_id)
    (child,) = [item for item in run.async_children if item.child_execution_id == child_id]
    assert len(child.decisions) == 1

    (record,) = await AsyncChildCompletion(
        stack.service, stack.authority, policies=ASYNC_RESULT_POLICIES, wait_seconds=0
    ).complete(_parent(stack), execution_generation=1)
    assert (record.result_decision, record.usage_disposition) == ("admit", "settled")
    link = await stack.service.link(stack.scope, child_id)
    assert link.settled and link.settlement_revision == 1
    # Review S2: the child's provider-attributed usage settles into the parent run's budget
    # (manifest usage -> AsyncSubagentService.settle -> parent effects settle_usage).
    assert manifest.usage.attribution == "provider_attributed"
    assert link.usage_disposition == "settled"
    effects = await stack.run_control.get_effects(stack.scope, stack.run_id)
    assert effects.claims[async_child_effect_id(child_id)].disposition == (
        EffectDisposition.SUCCEEDED
    )
    run = await stack.run_control.get_run(stack.scope, stack.run_id)
    (child,) = [item for item in run.async_children if item.child_execution_id == child_id]
    assert len(child.decisions) == 1  # the boundary never decided again


@pytest.mark.asyncio
async def test_concurrent_checks_admit_exactly_once(stack: Stack) -> None:
    """Review B2: two parent checks race on one completed child; the row lock lets exactly
    one writer move the link to decided and report it, and both read the same admission."""

    contract, child_id = await _spawn_sealed(stack)
    stack.provider.next_status = "success"
    completed = await stack.service.reconcile(stack.scope, child_id)
    admission = CheckTimeAdmission(stack.service, policies=ASYNC_RESULT_POLICIES)
    results = await asyncio.gather(
        *(
            admission.admit(_parent(stack), contract, completed, current_generation=1)
            for _ in range(2)
        )
    )
    assert [item.status for item in results] == ["admitted", "admitted"]
    assert sorted(item.newly_decided for item in results) == [False, True]
    assert results[0].entry == results[1].entry
    run = await stack.run_control.get_run(stack.scope, stack.run_id)
    (child,) = [item for item in run.async_children if item.child_execution_id == child_id]
    assert len(child.decisions) == 1


@pytest.mark.asyncio
async def test_concurrent_defer_to_admit_transitions_change_the_decision_once(
    stack: Stack,
) -> None:
    """Review S-B2a: a deferred child admitted by two racing deciders changes once."""

    _contract, child_id = await _spawn_sealed(stack)
    stack.provider.next_status = "success"
    await stack.service.reconcile(stack.scope, child_id)
    at = datetime(2026, 10, 28, 12, tzinfo=UTC)
    deferred, first = await stack.service.decide_result_once(
        stack.scope, child_id, "defer", parent_open=True, current_generation=1, decided_at=at
    )
    assert deferred.result_decision == "defer" and first
    results = await asyncio.gather(
        *(
            stack.service.decide_result_once(
                stack.scope,
                child_id,
                "admit",
                parent_open=True,
                current_generation=1,
                decided_at=at,
            )
            for _ in range(2)
        )
    )
    assert sorted(changed for _link, changed in results) == [False, True]
    assert {link.result_decision for link, _changed in results} == {"admit"}
    assert (await stack.service.link(stack.scope, child_id)).result_decision == "admit"
