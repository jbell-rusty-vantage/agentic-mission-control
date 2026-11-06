"""ITER-3 F1-G2/G4/G5 on a disposable PostgreSQL 17 (common component, restricted roles).

1. F1-G4: the reused ``collect_a`` of a fork-derived run carries the source run's accepted
   ``collect_a.notes_a`` into the derived run (one host invocation of the derived unit, adopted,
   finalized without assessment, promoted): the family's named-output settlement binds it to the
   reused stage, and the consumer ``synthesize`` receives exactly those bytes through its sealed
   transfer plan (``notes_a`` materialized as a file, ``notes_b`` by the profile default) beside
   the re-run ``collect_b``'s own output. The source run is untouched.
2. F1-G2: ``ManifestSubmitService.start`` on a fork-derived run of a submitted manifest Stage
   Graph (admitted through the real manifest fork provenance) derives the family input from the
   source's submission with the production launch input author and launches through the
   governed ``RunLaunchService``, which derives the templates from the source's binding; a
   run-request run that is no fork is refused typed. (Recording submitter: no Temporal.)
3. F1-G5: the derived run's recorded family decisions of a dependency-starved conclusion read
   back through ``PostgresUnitFailureReader`` under the runtime role as typed unit failures.
   The journal rows are written by the owner here (the family writer is not exercised).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from mission_control.adapters.postgres.context.transfer_plans import PostgresTransferPlanStore
from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.postgres.control_plane.manifest_submission import (
    PostgresManifestSubmissionRepository,
)
from mission_control.adapters.postgres.knowledge.output_contracts import (
    PostgresOutputContractStore,
)
from mission_control.adapters.postgres.run_control.inspection_repository import (
    PostgresUnitFailureReader,
)
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_fork_admission import (
    ManifestForkAdmissionProvenance,
)
from mission_control.application.authoring.manifest_launch_inputs import (
    ManifestLaunchInputAuthor,
    binding_ref,
)
from mission_control.application.authoring.manifest_service import (
    ManifestCompileService,
    ManifestProgramCompiler,
)
from mission_control.application.authoring.manifest_submit import (
    ForkStartSource,
    ManifestStartRefused,
    ManifestSubmitService,
    StoredForkSources,
    register_manifest_admission_policies,
)
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.context.materialization import (
    MaterializeRequest,
    ProducedOutputResolver,
    TransferMaterializer,
)
from mission_control.application.execution.run_launch import (
    RunLaunchService,
    fork_semantic_input_binding_ref,
)
from mission_control.application.execution.service import (
    AdmissionPolicyRegistry,
    F1RunConfigurationVerifier,
    RunControlService,
)
from mission_control.application.knowledge.toolset import LiveInvocation
from mission_control.application.outputs.adoption import OutputAdoptionService
from mission_control.application.outputs.fulfillment import OutputFulfillmentService
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.application.programs.named_outputs import NamedStageOutputs
from mission_control.application.recovery.fork_outputs import ForkOutputCarry
from mission_control.application.recovery.run_forks import ForkCommand, compile_fork_admission
from mission_control.bootstrap.launch_promises import compose_launch_promises
from mission_control.domain.authoring.contracts import StageNode, StageOutputSlot
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.context import transfer_builders
from mission_control.domain.context.transfer import ReceiverAttempt, ReceiverRef
from mission_control.domain.execution.contracts import ReusedResultRef
from mission_control.domain.graph_runtime.identities import StageGraphUnitLocation
from mission_control.domain.outputs.contracts import OutputForm, SubmitOutput
from mission_control.domain.outputs.rules import text_digest
from mission_control.domain.policies.contracts import DecisionStatus
from mission_control.domain.policies.forks import RunSnapshotManifest, snapshot_id_for
from mission_control.domain.programs.contracts import (
    StageCandidateIdentity,
    StageExecutionIdentity,
    StageGraphRunInput,
)
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.fixtures.knowledge_binding import InMemoryStaging
from tests.fixtures.mission_control_common_db import CommonDatabase, catalog_scope
from tests.fixtures.run_forks import technical_snapshot
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.integration.postgres.test_manifest_submit import (
    MINIMAL,
    OWNER,
    RecordingSubmitter,
)
from tests.integration.postgres.test_manifest_submit import request as submit_request
from tests.unit.context.test_wi07_current_set_transfer import OVERHEAD, SANDBOX, Backend, bounds
from tests.unit.knowledge.test_knowledge_tools import MISSION, lane
from tests.unit.orchestration.test_stagegraph_v2 import operation_slot
from tests.unit.outputs.scenario import host_access, obligation, promises, text

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]

NOTE_A = "source: arxiv-2310.06825-abstract\nmistral-7b: 7-billion-parameter"
NOTE_B = "source: hf-meta-llama-llama-3.1-model-card\nllama-3-1: 8B, 70B and 405B"


@pytest_asyncio.fixture
async def pool(common_db: CommonDatabase) -> AsyncIterator[asyncpg.Pool]:  # noqa: F811
    created = await common_db.pool("mission_control_runtime")
    try:
        yield created
    finally:
        await created.close()


def e2_promises() -> Any:
    return promises(
        obligation("collect_a.notes_a", OutputForm.TEXT, position="collect_a"),
        obligation("collect_b.notes_b", OutputForm.TEXT, position="collect_b"),
        obligation("synthesize.synthesis", OutputForm.TEXT, position="synthesize"),
    )


def stage_identity(run_id: str, stage: str) -> StageExecutionIdentity:
    return StageExecutionIdentity(
        run_id, 1, StageCandidateIdentity(stage, 0, "NO_MAPPED_INSTANCE", 0, 0, "execute"), 1, 1
    )


def stage_node(stage: str, slot: str) -> StageNode:
    return StageNode(
        stage_id=stage,
        operation_slots=(operation_slot(),),
        output_slots=(StageOutputSlot(output_slot_id=slot, output_contract_ref="text"),),
    )


async def produce(toolset: Any, submissions: Any, scope: str, run: str, stage: str, key: str,
                  body: str) -> str:  # fmt: skip
    """One producer invocation submits and finalizes its note; returns the revision id."""

    live = await toolset.begin(
        LiveInvocation(
            request_scope=scope,
            run_id=run,
            operation_id=stage_identity(run, stage).operation_id,
            operation_attempt=1,
            execution_generation=1,
            lane="deep_agents",
            position=stage,
        )
    )
    access = toolset.access(live)
    ack = await submissions.submit_output(
        access,
        SubmitOutput(submission_key=f"{stage}-1", obligation_key=key, items=(text("note", body),)),
        position=stage,
    )
    assert ack.status == "accepted", ack.error
    await submissions.finalize(access.identity(live.obligations))
    return ack.revisions[0].revision_id


async def test_reused_stage_output_reaches_the_derived_consumer(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    scope = common_db.scope()
    source, derived = str(uuid4()), str(uuid4())
    store = PostgresOutputContractStore(pool)
    h = lane()
    submissions = SubmissionService(store, contracts=store, clock=h.clock)
    toolset = replace(h.toolset, submissions=submissions)
    h.locator.missions.update({source: MISSION, derived: MISSION})
    fulfillment = OutputFulfillmentService(store, submissions)
    host = host_access(scope)
    named = NamedStageOutputs(store, fulfillment)
    for run in (source, derived):
        assert isinstance(await fulfillment.register_promises(host, run, e2_promises()), tuple)
    # The source run: collect_a submitted and its stage settlement accepted it.
    await produce(toolset, submissions, scope, source, "collect_a", "collect_a.notes_a", NOTE_A)
    settled = await named.reconcile(
        scope, stage_identity(source, "collect_a"), stage_node("collect_a", "notes_a"), {}
    )
    (source_ref,) = settled["output_bindings"]["notes_a"]
    (source_head,) = await store.accepted_outputs(scope, source)

    # The derived run reuses collect_a: the operation boundary carries its accepted output.
    carry = ForkOutputCarry(
        invocations=toolset,
        finalization=submissions,
        adoption=OutputAdoptionService(
            outputs=store, submissions=submissions, lineage=toolset.lineage
        ),
        fulfillment=fulfillment,
        outputs=store,
        live_factory=LiveInvocation,
    )
    reused_identity = stage_identity(derived, "collect_a")
    binding = SimpleNamespace(
        request_scope=scope,
        run_id=derived,
        operation_id=reused_identity.operation_id,
        operation_attempt=1,
        lane_dispatch=SimpleNamespace(execution_generation=1),
        runtime_unit=SimpleNamespace(
            unit_key="bl-unit-v1:" + "b" * 64,
            location=StageGraphUnitLocation(
                stage_id="collect_a",
                mapped_instance_id="NO_MAPPED_INSTANCE",
                workflow_cycle_ordinal=0,
                stage_cycle_ordinal=0,
                operation_slot_id="execute",
            ),
        ),
    )
    ref = ReusedResultRef(
        fork_request_id="fork-request-iter3",
        source_run_id=source,
        source_unit_key="bl-unit-v1:" + "a" * 64,
        source_settlement_id="settlement-collect-a",
        source_result_manifest_ref="result-manifest:collect-a",
        source_result_manifest_digest="sha256:" + "c" * 64,
    )
    carried = await carry.carry(binding, ref)  # type: ignore[arg-type]
    assert len(carried.revisions) == 1
    assert (await carry.carry(binding, ref)).revisions == carried.revisions  # retry: same rows
    # The family's named-output settlement of the reused stage binds the carried revision.
    reused = await named.reconcile(
        scope, reused_identity, stage_node("collect_a", "notes_a"), {"output_refs": []}
    )
    (bound,) = reused["output_bindings"]["notes_a"]
    assert bound != source_ref and bound.endswith(f"#digest={source_head.content_digest}")
    # collect_b re-ran in the derived run (the invalidation frontier).
    await produce(toolset, submissions, scope, derived, "collect_b", "collect_b.notes_b", NOTE_B)
    fresh = await named.reconcile(
        scope, stage_identity(derived, "collect_b"), stage_node("collect_b", "notes_b"), {}
    )
    assert fresh["output_bindings"]["notes_b"]

    # The consumer's sealed transfer plan resolves both inputs in the derived run.
    selection = transfer_builders.dependent_stage(
        transfer_builders.first_invocation("synthesize", bounds(), SANDBOX),
        [
            ("notes_a", "collect_a", "collect_a.notes_a"),
            ("notes_b", "collect_b", "collect_b.notes_b"),
        ],
        placements={"notes_a": "file"},
    )
    staging = InMemoryStaging()
    materializer = TransferMaterializer(
        store=PostgresTransferPlanStore(pool),
        staging=staging,
        custody=staging,
        resolvers={"produced_output": ProducedOutputResolver(store)},
    )
    consumer = stage_identity(derived, "synthesize").operation_id
    sealed = await materializer.materialize(
        MaterializeRequest(
            receiver=ReceiverRef(scope=scope, run_id=derived, operation_id=consumer),
            attempt=ReceiverAttempt(
                operation_attempt=1, execution_generation=1, invocation_ref="inv-synthesize-1"
            ),
            selection=selection,
            configuration_ref="erc:sha256:" + "0" * 64,
            host_state_ref="context-packet:p1@sha256:" + "1" * 64,
            overhead=OVERHEAD,
            access=toolset.access(
                LiveInvocation(
                    request_scope=scope,
                    run_id=derived,
                    operation_id=consumer,
                    operation_attempt=1,
                    execution_generation=1,
                    lane="deep_agents",
                    mission_id=MISSION,
                )
            ),
        ),
        Backend(),
    )
    sources = {member.binding: member for member in sealed.plan.exact_sources}
    carried_id = carried.revisions[0].removeprefix("output:").partition("@")[0]
    assert sources["notes-a"].source_ref == carried_id
    assert sources["notes-a"].admission == "accepted"
    # Exactly the source's accepted bytes, materialized as a read-only file (expand: materialize).
    assert sources["notes-a"].digest == text_digest(NOTE_A) == source_head.content_digest
    placed = {item.member_key: item for item in sealed.plan.placements}
    assert placed[sources["notes-a"].member_key].placement == "file"
    assert placed[sources["notes-a"].member_key].path.startswith("/inputs/notes-a/")
    assert sources["notes-b"].admission == "accepted"
    assert sources["notes-b"].digest == text_digest(NOTE_B)
    # The source run is untouched: its one accepted head is its own revision.
    assert [item.revision_id for item in await store.accepted_outputs(scope, source)] == [
        source_head.revision_id
    ]


class Materializations:
    def __init__(self, derived: str, fork_request_id: str) -> None:
        self.derived, self.fork_request_id = derived, fork_request_id

    async def fork_of_run(self, request_scope: str, run_id: str) -> Any:
        if run_id != self.derived:
            return None
        return SimpleNamespace(fork_request_id=self.fork_request_id, materialized=True)


class Forks:
    def __init__(self, request: Any, receipt: Any) -> None:
        self.request, self.receipt = request, receipt

    async def get_request(self, request_scope: str, request_id: str) -> Any:
        return self.request if request_id == self.request.request_id else None

    async def get(self, request_scope: str, request_id: str) -> Any:
        return self.receipt if request_id == self.request.request_id else None


class Derivation:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def derive_stagegraph(self, **kwargs: Any) -> tuple[str, ...]:
        self.calls.append(kwargs)
        return ()


class SourceTemplates:
    """The source run's frozen templates exist (it launched); the fork derives from them."""

    def __init__(self, source_ref: str) -> None:
        self.source_ref = source_ref

    async def list_templates(self, *, request_scope: str, semantic_input_binding_ref: str) -> Any:
        return {"collect": object()} if semantic_input_binding_ref == self.source_ref else {}

    async def persist_templates(self, **kwargs: Any) -> None:
        raise AssertionError("a fork-derived start freezes no templates of its own")


async def test_fork_derived_manifest_run_starts_and_names_its_failure_causes(
    common_db: CommonDatabase,  # noqa: F811
    pool: asyncpg.Pool,
) -> None:
    scope = common_db.scope()
    definitions, search = await fast_track_catalog()
    catalog = PostgresDefinitionRepository(pool, catalog_scope=catalog_scope("biotech"))
    programs = ManifestProgramCompiler(catalog, ExtensionRegistry(), InMemoryPayloadStore())
    control_plane = ControlPlaneService(catalog, ExtensionRegistry(), InMemoryPayloadStore())
    policies = AdmissionPolicyRegistry()
    register_manifest_admission_policies(policies)
    run_control = RunControlService(
        PostgresRunControlRepository(pool), F1RunConfigurationVerifier(control_plane), policies
    )
    submissions = PostgresManifestSubmissionRepository(pool)
    compiler = ManifestCompileService(definitions=definitions, search=search, programs=programs)
    plain = ManifestSubmitService(
        compiler=compiler,
        programs=programs,
        run_control=run_control,
        submissions=submissions,
        request_scope=scope,
    )
    receipt, _ = await plain.submit(submit_request(MINIMAL.read_text(encoding="utf-8")))
    (mission,) = receipt.missions
    assert mission.family == "StageGraph" and mission.run_id is not None
    source = await run_control.get_run(scope, mission.run_id)

    # The fork admits the derived run through the real manifest provenance (as the saga does).
    template = technical_snapshot(source.run_id, request_scope=scope)
    values = template.model_dump(mode="python", exclude={"snapshot_digest"})
    budget = await run_control.get_budget(scope, source.run_id)
    values.update(
        budget_frontier=template.budget_frontier.model_copy(
            update={"limits": budget.limits, "account_id": budget.account_id}
        ),
        request_scope=scope,
        source_run_id=source.run_id,
        projection_version=source.version,
        snapshot_id=snapshot_id_for(scope, source.run_id, source.version, template.boundary_ref),
        effective_configuration_digest=source.effective_configuration_digest,
        workflow_type_ref=source.workflow_type_ref,
        input_manifest=source.input_manifest,
        reuse_candidates=(),
    )
    snapshot = RunSnapshotManifest.create(**values)
    fork_request_id = str(uuid4())
    target = compile_fork_admission(
        snapshot,
        ForkCommand(
            request_scope=scope,
            source_run_id=source.run_id,
            request_id=fork_request_id,
            idempotency_key=str(uuid4()),
            snapshot_id=snapshot.snapshot_id,
            snapshot_digest=snapshot.snapshot_digest,
            sponsorship_ref="sponsorship:test",
            actor=OWNER,
            reason="ITER-3 F1-G2 fork-derived manifest start",
            requested_at=datetime.now(UTC),
        ),
        patch_digest="sha256:" + "a" * 64,
        effective_configuration_digest=source.effective_configuration_digest,
        input_manifest=source.input_manifest,
    )
    evidence = await ManifestForkAdmissionProvenance(
        submissions, run_control, control_plane
    ).evidence(target)
    admitted = await run_control.admit(
        target.model_copy(
            update={"admission_evidence_refs": (*target.admission_evidence_refs, *evidence)}
        )
    )
    assert admitted.status == DecisionStatus.ACCEPTED and admitted.run_id is not None
    derived = admitted.run_id
    stored = await submissions.run_subscriptions(scope, derived)
    assert stored is not None and stored["definition"]["contract"] == "mc.run-request-definition/1"

    fork_request = SimpleNamespace(
        request_id=fork_request_id,
        source_run_id=source.run_id,
        patch=SimpleNamespace(cognitive_seed=None),
    )
    fork_receipt = SimpleNamespace(
        target_run_id=derived, source_run_id=source.run_id, start_position=None
    )
    materializations = Materializations(derived, fork_request_id)
    forks = Forks(fork_request, fork_receipt)
    derivation = Derivation()
    submitter = RecordingSubmitter()
    author = ManifestLaunchInputAuthor(
        resolver=None,  # type: ignore[arg-type]  # the fork path resolves no templates
        run_control=run_control,
        control_plane=control_plane,
        definitions=submissions,
        stage_templates=SourceTemplates(binding_ref(source.run_id)),  # type: ignore[arg-type]
        goal_templates=None,  # type: ignore[arg-type]
    )
    service = ManifestSubmitService(
        compiler=compiler,
        programs=programs,
        run_control=run_control,
        submissions=submissions,
        request_scope=scope,
        launches=RunLaunchService(
            run_control=run_control,
            submitter=submitter,
            promises=compose_launch_promises(pool),
            forks=forks,  # type: ignore[arg-type]
            materializations=materializations,  # type: ignore[arg-type]
            fork_templates=derivation,
        ),
        launch_inputs=author,
        fork_sources=StoredForkSources(materializations, forks),
    )

    started = await service.start(derived, OWNER)

    assert started.family == "StageGraph"
    assert (started.forked_from_run_id, started.fork_request_id) == (
        source.run_id,
        fork_request_id,
    )
    expected_ref = fork_semantic_input_binding_ref(fork_request_id)
    assert started.semantic_input_binding_ref == expected_ref
    (call,) = submitter.calls
    launched = call["input"]
    assert isinstance(launched, StageGraphRunInput)
    assert launched.run_id == derived and launched.request_scope == scope
    assert launched.correlation_id == f"orchestration:{derived}:epoch:1"
    assert launched.semantic_input_binding_ref == expected_ref
    # The source's authored input (synthesize <- collect.sources, materialize) travels as is.
    assert [(item.consumer_stage_id, item.name) for item in launched.authored_inputs] == [
        ("synthesize", "sources")
    ]
    (derive,) = derivation.calls
    assert derive["source_semantic_input_binding_ref"] == binding_ref(source.run_id)
    assert derive["derived_semantic_input_binding_ref"] == expected_ref
    # The ledger mission of the root is the derived run's own.
    assert call["mission_id"] == str(stored["mission_id"])

    # A run-request run that no fork admitted is refused typed (never a 500).
    lonely = ManifestSubmitService(
        compiler=compiler,
        programs=programs,
        run_control=run_control,
        submissions=submissions,
        request_scope=scope,
        launches=service._launches,
        launch_inputs=author,
        fork_sources=StoredForkSources(Materializations("other", fork_request_id), forks),
    )
    with pytest.raises(ManifestStartRefused) as refused:
        await lonely.start(derived, OWNER)
    assert refused.value.code == "not_a_manifest_run"
    assert ForkStartSource  # the port's value type is public

    # F1-G5: a dependency-starved conclusion of the derived run is typed in inspection.
    await _journal(
        common_db,
        derived,
        [
            _decided("collect", "reject", "required_dependency_output_missing", "failed"),
            {
                "decision_kind": "completion_proposed",
                "decision_payload": {
                    "completion": {"failed": True, "skipped_stage_ids": ["synthesize"]}
                },
            },
        ],
    )
    failures = await PostgresUnitFailureReader(pool).unit_failures(scope, derived)
    assert [(item.unit, item.reason, item.failure_ref) for item in failures] == [
        (
            "stage/collect",
            "required_dependency_output_missing",
            "stage_rejected:collect:required_dependency_output_missing:outputs_missing:sources",
        ),
        (
            "stage/synthesize",
            "dependency_unresolved",
            "dependency_unresolved:synthesize:collect:to:synthesize=failed",
        ),
    ]
    # Another tenant sees none of it.
    assert (
        await PostgresUnitFailureReader(pool).unit_failures(common_db.scope("tenant-2"), derived)
        == ()
    )


def _decided(stage: str, decision: str, veto: str, disposition: str) -> dict[str, Any]:
    return {
        "decision_kind": "result_decided",
        "decision_payload": {
            "proposal": {
                "identity": {"candidate": {"stage_id": stage}},
                "decision": decision,
                "matched_veto": veto,
                "dependency_dispositions": {f"{stage}:to:synthesize": disposition},
            },
            "completion_validation": {"reason_codes": ["outputs_missing:sources"]},
        },
    }


async def _journal(db: CommonDatabase, run_key: str, mutations: list[dict[str, Any]]) -> None:
    _mc, installation, application, tenant = db.scope().split("/")
    connection = await asyncpg.connect(db.owner_dsn)
    try:
        for version, mutation in enumerate(mutations, start=1):
            now = datetime.now(UTC)
            await connection.execute(
                """
                INSERT INTO mission_control.family_admission_journal (
                    installation_id, application_id, tenant_id, family_admission_journal_id,
                    run_key, family_kind, family_version, mutation_kind, mutation_key,
                    mutation_fingerprint, mutation_contract, mutation, decided_at, created_at,
                    created_by_actor_ref
                ) VALUES ($1::uuid, $2, $3::uuid, $4, $5, 'stagegraph', $6, 'decision_committed',
                          $7, $8, 'mc.family-mutation/1', $9::jsonb, $10, $10, 'test:owner')
                """,
                installation,
                application,
                tenant,
                uuid4(),
                run_key,
                version,
                f"mutation-{version}",
                "sha256:" + f"{version:064x}",
                json.dumps(mutation),
                now,
            )
    finally:
        await connection.close()
