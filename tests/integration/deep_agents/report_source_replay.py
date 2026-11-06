"""Joined proof's reconstructed-service replay, retaining fixture payload custody.

Uses real PostgreSQL transfer plans, journal, lineage and saver. This does not prove
process restart or durable object custody: result payloads and staged inputs stay in memory.
"""

from dataclasses import replace

from tests.fixtures.checkpoint_lineage import bind_unit
from tests.fixtures.lane_bindings import lane_fields
from tests.integration.deep_agents import test_checkpoint_lineage_postgres_saver as cp
from tests.integration.deep_agents.test_report_source_context import FullContextReader
from tests.integration.deep_agents.test_wi02_transfer_plan_lane import registry


class CountingReader(FullContextReader):
    calls: int = 0

    def _generate(self, *args, **kwargs):
        self.calls += 1
        return super()._generate(*args, **kwargs)


async def admit(pool, scope):
    control, _ = cp.run_control_service(cp.PostgresRunControlRepository(pool))
    admitted = await control.admit(cp.run_request(request_scope=scope, request_id="joined-reader"))
    started = await control.execute(
        cp.command(admitted.run_id, 1, "joined-start", cp.StartAction()).model_copy(
            update={"request_scope": scope}
        )
    )
    assert started.status == cp.CommandStatus.ACCEPTED
    return control, admitted.run_id


async def consume_and_replay(
    database, pool, control, binding, bundle, transfer_factory, knowledge, selection
):
    scope = database.scope()
    run = await control.get_run(scope, binding.run_id)
    reservation = "joined-reader-reservation"
    reserved = await control.execute(
        cp.command(
            binding.run_id,
            run.version,
            "joined-reserve",
            cp.ReserveBudgetAction(reservation_id=reservation, amounts={"tokens.total": 10}),
        ).model_copy(update={"request_scope": scope})
    )
    assert reserved.status == cp.CommandStatus.ACCEPTED
    binding = bind_unit(
        binding,
        binding.runtime_unit,
        control_revision=reserved.resulting_run_version,
        reservation_id=reservation,
    )
    request = cp.OperationExecutionRequest.model_validate(
        {
            **cp.operation_request().model_dump(mode="python"),
            "request_scope": scope,
            "identity": cp.OperationAttemptIdentity(
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
    dsn = cp.runtime_checkpoint_conninfo(await cp.provision_runtime(database), cp.SAVER_SCHEMA)
    payloads = cp.InMemoryArtifactPayloadStore()
    model = CountingReader()

    def service(saver):
        components = replace(
            registry(binding, bundle, model), checkpointers={binding.checkpointer_ref.digest: saver}
        )
        adapter = cp.DeepAgentRuntimeAdapter(
            cp.ExactDeepAgentMaterializer(components),
            transfer=transfer_factory(),
            knowledge=knowledge,
        )
        assets = cp.ConformanceAssetVerifier(
            mcp_schema_digests={"fixture-mcp": cp.MCP_DIGEST},
            asset_manifest_digests={"skill:fixture.skill:1": cp.SKILL_DIGEST},
        )
        return cp.OperationExecutionService(
            authority=cp.AcceptingAuthority(),
            bindings=cp.InMemoryOperationBindingRepository(),
            lanes=cp.LaneRegistry([cp.DeepAgentsHarness(adapter)]),
            sandbox=cp.ConformanceSandbox(),
            assets=assets,
            mcp=assets,
            secrets=cp.ConformanceSecretResolver({"environment:OPENAI_API_KEY": "unused"}),
            events=cp.ConformanceEventSink(),
            budget=cp.ConformanceBudgetAuthority(),
            journal=cp.JournaledOperationExecutionCoordinator(
                journal=cp.OperationJournalService(
                    cp.PostgresAtomicOperationJournalRepository(pool)
                ),
                run_control=control,
                results=payloads,
                actor=cp.actor(),
            ),
            journal_claimed_by="worker:joined",
            lineage=cp.CheckpointLineageService(cp.PostgresCheckpointLineageRepository(pool)),
        )

    namespace = binding.cognitive_session_namespace
    async with cp.AsyncPostgresSaver.from_conn_string(dsn) as saver:
        result = await service(saver).execute(request, cp.delivery(1, binding.runtime_unit))
        assert result.status == "completed", result
        chain = await cp.root_lineage(saver, namespace)
        assert chain and model.calls > 0
    calls = model.calls
    lineage = cp.PostgresCheckpointLineageRepository(pool)
    transitions = await lineage.list_transitions(scope, namespace)
    assert len(transitions) == 1
    # New saver connection, registry, adapter, transfer store and execution service.
    # The same settled unit returns its journaled payload before provider dispatch.
    async with cp.AsyncPostgresSaver.from_conn_string(dsn) as saver:
        duplicate = await service(saver).execute(request, cp.delivery(2, binding.runtime_unit))
        assert duplicate == result
        assert model.calls == calls
        assert len(await cp.root_lineage(saver, namespace)) == len(chain)
    assert await lineage.list_transitions(scope, namespace) == transitions
    return result
