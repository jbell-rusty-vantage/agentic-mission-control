"""Two genuine parallel stages through signed public HTTP, real PostgreSQL and Temporal.

The admitted fixture blueprint has independent draft/review stages and concurrency two.
Production Deep Agents executes the registered deterministic model, sync child, writable
workspace and local MCP tool. No model vendor or external service is called.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.bootstrap.settings import get_settings
from mission_control.domain.policies.contracts import CommandStatus
from mission_control.domain.programs.contracts import (
    StageGraphAcceptedProjection,
    StageGraphDecisionMutation,
)
from tests.fixtures import rrm009_production_stack as technical
from tests.fixtures.scoped_api_stack import admit_and_launch, inspect, scoped_stack, until
from tests.integration.temporal.test_manifest_launch_production import host_pins

pytestmark = pytest.mark.common_db


def test_parallel_stages_complete_under_the_canonical_root_without_stale_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
    asyncio.run(_prove(tmp_path, monkeypatch), loop_factory=loop_factory)


def test_producer_closes_while_sibling_has_inflight_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
    asyncio.run(_prove(tmp_path, monkeypatch, hold_sibling=True), loop_factory=loop_factory)


async def _prove(
    root: Path, monkeypatch: pytest.MonkeyPatch, *, hold_sibling: bool = False
) -> None:
    monkeypatch.setenv("MISSION_CONTROL_APPLICATION", "biotech")
    get_settings.cache_clear()
    monkeypatch.setenv("CAPABILITY_PINS_PATH", str(host_pins(root / "capability-pins.json")))
    sequential = technical.stage_blueprint()
    parallel = sequential.model_copy(
        update={
            "stages": tuple(
                stage.model_copy(update={"input_slots": ()}) for stage in sequential.stages
            ),
            "joins": (),
            "dependencies": (),
            "waits": (),
        }
    )
    monkeypatch.setattr(technical, "stage_blueprint", lambda: parallel)
    stage_input = technical.stage_input
    monkeypatch.setattr(
        technical,
        "stage_input",
        lambda *args, **kwargs: replace(
            stage_input(*args, **kwargs),
            max_concurrency=2,
        ),
    )
    held = asyncio.Event()
    release = asyncio.Event()
    native_generate = technical.TechnicalModel._agenerate

    async def generate(model: Any, *args: Any, **kwargs: Any):
        if hold_sibling and ":stage:review:" in model.operation_id:
            held.set()
            await asyncio.wait_for(release.wait(), 120)
        return await native_generate(model, *args, **kwargs)

    monkeypatch.setattr(technical.TechnicalModel, "_agenerate", generate)
    held_proof: dict[str, Any] = {}
    original = PostgresRunControlRepository.commit_command
    barrier = asyncio.Barrier(2)
    claim_ids: set[str] = set()
    attempted_statuses: list[str] = []

    async def commit(repository: Any, mutation: Any):  # type: ignore[no-untyped-def]
        result = mutation.result
        if result.idempotency_issuer == "operation-journal":
            attempted_statuses.append(result.status.value)
            if (
                result.command_id.startswith("operation-effect-claim:")
                and result.command_id not in claim_ids
            ):
                claim_ids.add(result.command_id)
                await asyncio.wait_for(barrier.wait(), 60)
        return await original(repository, mutation)

    monkeypatch.setattr(PostgresRunControlRepository, "commit_command", commit)
    async with scoped_stack(root, monkeypatch) as stack:
        run_id, root_id = await admit_and_launch(stack, "StageGraph")

        async def completed() -> bool:
            state = await inspect(stack, run_id)
            if state["phase"] == "terminal":
                assert state["lifecycle"] == "completed", state
                return True
            return False

        try:
            if hold_sibling:
                await asyncio.wait_for(held.wait(), 90)
                repository = PostgresRunControlRepository(stack.pool)

                async def first_producer_closed() -> bool:
                    head = await repository.get_family_head(
                        stack.scope,
                        run_id,
                        "stagegraph",
                        StageGraphDecisionMutation,
                    )
                    if head is None:
                        return False
                    current = TypeAdapter(StageGraphAcceptedProjection).validate_python(
                        head.decision_payload["projection"]
                    )
                    own = next(
                        (
                            item
                            for key, item in current.producer_liabilities.items()
                            if ":stage:draft:" in key
                        ),
                        None,
                    )
                    sibling = next(
                        (
                            item
                            for key, item in current.producer_liabilities.items()
                            if ":stage:review:" in key
                        ),
                        None,
                    )
                    if own is None or not own.closed or sibling is None:
                        return False
                    effects = await repository.get_effects(stack.scope, run_id)
                    pending = [
                        claim.effect_id
                        for claim in effects.claims.values()
                        if claim.reservation_id == sibling.reservation_id
                        and claim.settlement is None
                    ]
                    assert pending, effects
                    assert not sibling.effects_settled and not sibling.closed
                    state = await inspect(stack, run_id)
                    assert state["phase"] != "terminal", state
                    held_proof.update(
                        {
                            "producer_closed": own.closed,
                            "sibling_closed": sibling.closed,
                            "sibling_pending_effects": pending,
                            "family_version": current.family_version,
                        }
                    )
                    return True

                await until(first_producer_closed, seconds=90)
                release.set()
            await until(completed, seconds=240)
        finally:
            release.set()
            state = await inspect(stack, run_id)
            (root / "parallel-stage-authority.json").write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "root_id": root_id,
                        "inspection": state,
                        "claim_ids": sorted(claim_ids),
                        "attempted_statuses": attempted_statuses,
                        "model_log": stack.model_log,
                        "held_sibling_proof": held_proof,
                    },
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
        handle = stack.client.get_workflow_handle(root_id)
        assert (await handle.describe()).workflow_type == "mc.mission_run.v1"
        await asyncio.wait_for(handle.result(), 30)
        if hold_sibling:
            assert held_proof["producer_closed"] and held_proof["sibling_pending_effects"]
        assert len(claim_ids) == 2
        assert set(attempted_statuses) == {CommandStatus.ACCEPTED.value}
        projection = state["projection"]
        assert len(projection["accepted_output_evidence"]) == 2
        assert len(projection["accepted_operation_settlement_evidence"]) == 4
        assert {item["operation"] for item in stack.model_log if item["model"] == "parent"} == {
            item["operation"] for item in stack.model_log if item["model"] == "child"
        }
