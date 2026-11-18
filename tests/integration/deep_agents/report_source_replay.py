"""Joined proof's reconstructed-service replay, retaining fixture payload custody.

Uses real PostgreSQL transfer plans, journal, lineage and saver. This does not prove
process restart or durable object custody: result payloads and staged inputs stay in memory.
"""

from dataclasses import replace

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from tests.fixtures.checkpoint_lineage import bind_unit
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.mission_control_common_db import provision_runtime
from tests.support.deep_agents import registry
from tests.support.deep_agents_runtime import (
    ConformanceAssetVerifier,
    ConformanceBudgetAuthority,
    ConformanceEventSink,
    ConformanceSandbox,
    ConformanceSecretResolver,
)
from tests.support.integration.deep_agents.checkpoint_lineage_postgres_saver import (
    SAVER_SCHEMA,
    AcceptingAuthority,
    delivery,
    root_lineage,
)
from tests.support.integration.deep_agents.report_source_context import FULL_CONTEXT_READER
from tests.support.operations import MCP_DIGEST, SKILL_DIGEST, operation_request
from tests.support.run_control import actor, command
from tests.support.run_control import request as run_request
from tests.support.run_control import service as run_control_service

from mission_control.adapters.deep_agents import DeepAgentRuntimeAdapter, ExactDeepAgentMaterializer
from mission_control.adapters.deep_agents.harness import DeepAgentsHarness
from mission_control.adapters.deep_agents.persistence import runtime_checkpoint_conninfo
from mission_control.adapters.postgres.operations.checkpoint_lineage import (
    PostgresCheckpointLineageRepository,
)
from mission_control.adapters.postgres.operations.operation_journal import (
    PostgresAtomicOperationJournalRepository,
)
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.adapters.storage.artifact_payloads import InMemoryArtifactPayloadStore
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
)
from mission_control.application.execution.operations.journaled_operation_execution import (
    JournaledOperationExecutionCoordinator,
)
from mission_control.application.execution.operations.operation_execution import (
    InMemoryOperationBindingRepository,
    OperationExecutionService,
)
from mission_control.application.execution.operations.operation_journal import (
    OperationJournalService,
)
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.domain.execution.contracts import (
    OperationAttemptIdentity,
    OperationExecutionRequest,
)
from mission_control.domain.policies.contracts import (
    CommandStatus,
    ReserveBudgetAction,
    StartAction,
)


async def admit(pool, scope):
    control, _ = run_control_service(PostgresRunControlRepository(pool))
    admitted = await control.admit(run_request(request_scope=scope, request_id="joined-reader"))
    started = await control.execute(
        command(admitted.run_id, 1, "joined-start", StartAction()).model_copy(
            update={"request_scope": scope}
        )
    )
    assert started.status == CommandStatus.ACCEPTED
    return control, admitted.run_id


async def consume_and_replay(
    database, pool, control, binding, bundle, transfer_factory, knowledge, selection
):
    scope = database.scope()
    run = await control.get_run(scope, binding.run_id)
    reservation = "joined-reader-reservation"
    reserved = await control.execute(
        command(
            binding.run_id,
            run.version,
            "joined-reserve",
            ReserveBudgetAction(reservation_id=reservation, amounts={"tokens.total": 10}),
        ).model_copy(update={"request_scope": scope})
    )
    assert reserved.status == CommandStatus.ACCEPTED
    binding = bind_unit(
        binding,
        binding.runtime_unit,
        control_revision=reserved.resulting_run_version,
        reservation_id=reservation,
    )
    request = OperationExecutionRequest.model_validate(
        {
            **operation_request().model_dump(mode="python"),
            "request_scope": scope,
            "identity": OperationAttemptIdentity(
                run_id=binding.run_id,
                operation_id=binding.operation_id,
                operation_attempt=1,
            ),
            "run_control_revision": reserved.resulting_run_version,
            "execution_runtime": "deep_agent",
            "native_placement": None,
            **lane_fields(binding),
            "runtime_unit": binding.runtime_unit,
            "budget_reservation_id": reservation,
            "budget_limits": {"tokens.total": 10},
            "idempotency_key": "joined-reader",
            "transfer": selection,
        }
    )
    dsn = runtime_checkpoint_conninfo(await provision_runtime(database), SAVER_SCHEMA)
    payloads = InMemoryArtifactPayloadStore()
    model = FULL_CONTEXT_READER.model()

    def service(saver):
        components = replace(
            registry(binding, bundle, model), checkpointers={binding.checkpointer_ref.digest: saver}
        )
        adapter = DeepAgentRuntimeAdapter(
            ExactDeepAgentMaterializer(components),
            transfer=transfer_factory(),
            knowledge=knowledge,
        )
        assets = ConformanceAssetVerifier(
            mcp_schema_digests={"fixture-mcp": MCP_DIGEST},
            asset_manifest_digests={"skill:fixture.skill:1": SKILL_DIGEST},
        )
        return OperationExecutionService(
            authority=AcceptingAuthority(),
            bindings=InMemoryOperationBindingRepository(),
            lanes=LaneRegistry([DeepAgentsHarness(adapter)]),
            sandbox=ConformanceSandbox(),
            assets=assets,
            mcp=assets,
            secrets=ConformanceSecretResolver({"environment:OPENAI_API_KEY": "unused"}),
            events=ConformanceEventSink(),
            budget=ConformanceBudgetAuthority(),
            journal=JournaledOperationExecutionCoordinator(
                journal=OperationJournalService(PostgresAtomicOperationJournalRepository(pool)),
                run_control=control,
                results=payloads,
                actor=actor(),
            ),
            journal_claimed_by="worker:joined",
            lineage=CheckpointLineageService(PostgresCheckpointLineageRepository(pool)),
        )

    namespace = binding.cognitive_session_namespace
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        result = await service(saver).execute(request, delivery(1, binding.runtime_unit))
        assert result.status == "completed", result
        chain = await root_lineage(saver, namespace)
        assert chain and len(model.calls) > 0
    calls = len(model.calls)
    lineage = PostgresCheckpointLineageRepository(pool)
    transitions = await lineage.list_transitions(scope, namespace)
    assert len(transitions) == 1
    # New saver connection, registry, adapter, transfer store and execution service.
    # The same settled unit returns its journaled payload before provider dispatch.
    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        duplicate = await service(saver).execute(request, delivery(2, binding.runtime_unit))
        assert duplicate == result
        assert len(model.calls) == calls
        assert len(await root_lineage(saver, namespace)) == len(chain)
    assert await lineage.list_transitions(scope, namespace) == transitions
    return result
