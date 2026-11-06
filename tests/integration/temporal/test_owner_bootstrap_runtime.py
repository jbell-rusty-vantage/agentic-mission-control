"""Real PostgreSQL/Temporal bootstrap dispatch; Managed Agents transport is offline fixture.

This proves the operator dispatch and duplicate lifecycle, not paid provider qualification
or signed ingress receipt verification. Both workers use per-test UUID task queues.
"""

from functools import partial
from uuid import uuid4

import pytest
from temporalio.client import Client
from temporalio.worker import Worker

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.lanes.placement import PostgresPlacementStore
from mission_control.adapters.postgres.operations.checkpoint_lineage import (
    PostgresCheckpointLineageRepository,
)
from mission_control.adapters.temporal.coordinator_runtime import coordinator_task_queues
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
)
from mission_control.application.prerequisites.bootstrap_probe import (
    bootstrap_identity,
    bounded_probe_request,
)
from mission_control.application.workspaces.placement import PlacementAdmission
from mission_control.bootstrap.owner_probe import InstalledBootstrapProbe
from mission_control.bootstrap.settings import Settings
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import OperationAttemptIdentity
from mission_control.domain.execution.placement import PlacementLimit
from mission_control.domain.policies.contracts import RunPhase
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.lane_turns import lane_stack
from tests.fixtures.managed_lane import managed_stack
from tests.integration.anthropic_managed import test_session_lifecycle_live as lifecycle
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import (
    common_db,  # noqa: F401
    owner_rows,
)
from tests.unit.prerequisites.test_owner_bootstrap import probe_template


@pytest.mark.common_db
async def test_bootstrap_dispatch_runs_real_workflow_and_reuses_completed_probe(
    common_db,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    pool = await common_db.pool("mission_control_runtime")
    base_queue = "bootstrap-" + uuid4().hex
    lane_queue = "bootstrap-lane-" + uuid4().hex
    settings = Settings(
        _env_file=None,
        temporal_address="127.0.0.1:7233",
        temporal_namespace="default",
        temporal_task_queue=base_queue,
    )
    temporal = await Client.connect(settings.temporal_address, namespace="default")
    stack = managed_stack(tmp_path)
    try:
        admitted = await admit_unit_attempt(pool, common_db, start=False)
        original_plan, original = probe_template()
        from mission_control.domain.execution.bindings import ProviderExecutionBinding

        binding = ProviderExecutionBinding.carried_by(original)
        assert binding is not None

        binding = ProviderExecutionBinding.sealed(
            **{
                **binding.model_dump(exclude={"binding_digest"}),
                "materialization_digest": stack.pack.materialization_digest,
                "task_queue": lane_queue,
            }
        )
        template = original.model_copy(
            update={
                "request_scope": common_db.scope(),
                **lane_fields(binding),
                "identity": OperationAttemptIdentity(
                    run_id=admitted.run_key,
                    operation_id="bootstrap-probe",
                    operation_attempt=1,
                ),
            }
        )
        plan = original_plan.model_copy(
            update={
                "request_scope": template.request_scope,
                "run_id": admitted.run_key,
                "template_digest": sha256_digest(template),
                "configuration_digest": template.effective_configuration_digest,
                "provider_binding_digest": binding.binding_digest,
            }
        )
        request = bounded_probe_request(plan, template)
        frames = PostgresFrameRepository(pool)
        # Reuse the real lane service/PG state/preparation worker composition, only its
        # provider is the deterministic MockTransport API used by managed unit fixtures.
        monkeypatch.setattr(lifecycle, "LANE_QUEUE", lane_queue)
        monkeypatch.setattr(
            lifecycle,
            "lane_stack",
            partial(
                lane_stack,
                lineage=CheckpointLineageService(PostgresCheckpointLineageRepository(pool)),
            ),
        )
        monkeypatch.setattr(
            lifecycle,
            "LaneTurnService",
            partial(
                lifecycle.LaneTurnService,
                placement=PlacementAdmission(
                    PostgresPlacementStore(pool),
                    {"claude_managed": PlacementLimit(max_active=1)},
                ),
            ),
        )
        port = InstalledBootstrapProbe(pool, settings, None, admitted.run_control, None)
        async with (
            Worker(
                temporal,
                task_queue=coordinator_task_queues(base_queue).stagegraph,
                workflows=[OperationWorkflow],
                workflow_runner=coordinator_workflow_runner(),
            ),
            lifecycle._lane_worker(
                temporal,
                stack.harness,
                request.operation.model_copy(update={"run_control_revision": 2}),
                pool,
                frames,
            ),
        ):
            workflow_id = await port.start(plan, request)
            assert workflow_id == "owner-bootstrap-" + bootstrap_identity(plan)
            assert await port.start(plan, request) == workflow_id
        projection = await admitted.run_control.get_run(template.request_scope, admitted.run_key)
        assert projection.phase is RunPhase.ACTIVE
        stored = await lifecycle._frames(frames, request.operation)
        assert stored
        assert sum(frame.kind.value == "run_result" for frame in stored) == 1
        assert len(stack.api.sessions) == 1
        assert len(stack.api.messages()) == 1
        assert stack.api.archived()
        assert len(stack.deletions.orders) == 1
        observations = await PostgresCheckpointLineageRepository(pool).list_attempts(
            template.request_scope,
            request.operation.runtime_unit.unit_key,
        )
        assert len(observations) == 1  # Duplicate start never schedules another lane activity.
        (attempt,) = await owner_rows(
            common_db,
            "SELECT lease_expires_at FROM mission_control.attempt WHERE attempt_key=$1",
            request.operation.runtime_unit.unit_key + ":gen:1",
        )
        assert attempt["lease_expires_at"] is None  # Hosted unit owns no cognitive namespace lease.
        (capacity,) = await owner_rows(
            common_db,
            "SELECT active FROM mission_control.placement_reservation",
        )
        assert capacity["active"] is False

    finally:
        await pool.close()
