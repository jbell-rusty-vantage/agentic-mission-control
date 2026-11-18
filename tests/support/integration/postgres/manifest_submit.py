"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_manifest_submit.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest_asyncio

from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.postgres.control_plane.manifest_submission import (
    PostgresManifestSubmissionRepository,
)
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.adapters.postgres.scope import apply_scope
from mission_control.adapters.postgres.subscriptions.store import PostgresSubscriptionStore
from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_service import (
    ManifestCompileService,
    ManifestProgramCompiler,
)
from mission_control.application.authoring.manifest_submit import (
    ManifestSubmitService,
    SubmitRequest,
    register_manifest_admission_policies,
)
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.execution.run_launch import RunLaunchService
from mission_control.application.execution.service import (
    AdmissionPolicyRegistry,
    F1RunConfigurationVerifier,
    RunControlService,
)
from mission_control.application.programs.service import GoalDirectedLaunchService
from mission_control.application.subscriptions.service import SubscriptionService
from mission_control.application.watchers.ports import WatcherStartPort
from mission_control.bootstrap.launch_promises import compose_launch_promises
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.domain.coordinator.launch import BlueprintFamily, WorkflowSubmission
from mission_control.domain.policies.contracts import ActorContext
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.fixtures.mission_control_common_db import CommonDatabase, catalog_scope

ROOT = Path(__file__).resolve().parents[4]
MINIMAL = ROOT / "tests/fixtures/manifests/minimal-stage-graph.yml"


OWNER = ActorContext(
    actor_id="owner",
    authority_refs=frozenset({"authority:owner"}),
    permissions=frozenset({"workflow_run.admit", "workflow_run.start", "workflow_run.read"}),
)


class RecordingSubmitter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def submit(
        self,
        workflow_input: object,
        *,
        workflow_id: str,
        blueprint_family: BlueprintFamily,
        parent_run_id: str | None = None,
        mission_id: str | None = None,
    ) -> WorkflowSubmission:
        self.calls.append(
            {"family": blueprint_family.value, "mission_id": mission_id, "input": workflow_input}
        )
        return WorkflowSubmission(workflow_id=f"wf:{workflow_id}", temporal_run_id="run-1")


class GoalInputs:
    """The admitted run's GoalDirected input, with a test semantic binding reference."""

    def __init__(self, launches: GoalDirectedLaunchService) -> None:
        self._launches = launches

    async def family_input(
        self, *, request_scope: str, run_id: str, family: str, initial_goal: str | None
    ) -> dict[str, Any]:
        assert family == "GoalDirected" and initial_goal is not None
        prepared = await self._launches.prepare(
            request_scope,
            run_id,
            initial_goal=initial_goal,
            semantic_input_binding_ref="semantic-input:manifest-test",
        )
        return asdict(prepared)


class Stack:
    def __init__(self, db: CommonDatabase, pool: asyncpg.Pool) -> None:
        self.db = db
        self.pool = pool
        self.scope = db.scope()
        self.submitter = RecordingSubmitter()

    async def build(self, *, watchers: WatcherStartPort | None = None) -> ManifestSubmitService:
        definitions, search = await fast_track_catalog()
        catalog = PostgresDefinitionRepository(self.pool, catalog_scope=catalog_scope("biotech"))
        programs = ManifestProgramCompiler(catalog, ExtensionRegistry(), InMemoryPayloadStore())
        control_plane = ControlPlaneService(catalog, ExtensionRegistry(), InMemoryPayloadStore())
        policies = AdmissionPolicyRegistry()
        register_manifest_admission_policies(policies)
        register_manifest_admission_policies(policies)  # idempotent composition
        run_control = RunControlService(
            PostgresRunControlRepository(self.pool),
            F1RunConfigurationVerifier(control_plane),
            policies,
        )
        self.run_control = run_control
        self.submissions = PostgresManifestSubmissionRepository(self.pool)
        return ManifestSubmitService(
            compiler=ManifestCompileService(
                definitions=definitions, search=search, programs=programs
            ),
            programs=programs,
            run_control=run_control,
            submissions=self.submissions,
            request_scope=self.scope,
            # Production wires the promise registrar on every launch route (WI-02); a launcher
            # without it refuses a run with promises (`promises_unwired`).
            launches=RunLaunchService(
                run_control=run_control,
                submitter=self.submitter,
                promises=compose_launch_promises(self.pool),
            ),
            launch_inputs=GoalInputs(GoalDirectedLaunchService(run_control, control_plane)),
            subscriptions=SubscriptionService(PostgresSubscriptionStore(self.pool, self.scope)),
            watchers=watchers,
        )

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        async with self.pool.acquire() as connection, connection.transaction():
            await apply_scope(connection, self.scope)
            return list(await connection.fetch(query, *args))

    async def val(self, query: str, *args: Any) -> Any:
        async with self.pool.acquire() as connection, connection.transaction():
            await apply_scope(connection, self.scope)
            return await connection.fetchval(query, *args)


@pytest_asyncio.fixture
async def stack(common_db: CommonDatabase) -> AsyncIterator[Stack]:
    pool = await common_db.pool("mission_control_runtime")
    try:
        yield Stack(common_db, pool)
    finally:
        await pool.close()


def request(manifest_yaml: str, request_id: UUID | None = None) -> SubmitRequest:
    return SubmitRequest(
        manifest_yaml=manifest_yaml,
        request_id=request_id or uuid4(),
        actor=OWNER,
        sponsorship_refs=frozenset({"sponsorship:test"}),
    )


def goal_loop_manifest(title: str = "Goal loop sweep") -> str:
    document = load_manifest_yaml(MINIMAL.read_text(encoding="utf-8"))
    mission = document["mission"]
    mission["key"] = "goal-sweep"
    mission["title"] = title
    mission["program"] = {
        "key": "root",
        "behavior": "goal_loop",
        "objective": "evidence_map",
        "action_space": ["pubmed"],
        "outputs": [{"name": "claims", "schema": "claim_table@1"}],
    }
    mission["controls"]["subscriptions"] = [
        {"events": ["run.completed", "chain_link.released"], "channel": "stream"}
    ]
    return canonical_manifest_bytes(document).decode("utf-8")
