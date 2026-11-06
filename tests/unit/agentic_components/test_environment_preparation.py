"""MO-16: `mc.environment_preparation.v1`, the readiness ladder and the launch policy.

The ladder never regresses and is contiguous up to `prepared`; a worker-hosted prepare is
`prepared` without a mission layer, or with the passing setup receipt its kit's mission layer
wrote (MO-12); a cloud prepare stops at `delivered`; the
policy admits worker-hosted lanes at `prepared` and cloud lanes at `delivered`, on what this
prepare proved; the start receipt cites the declaration digest every record of the role's sealed
binding carries, and the manifest Validation Report cites what the manifest alone declares.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import ValidationError

from mission_control.application.authoring.manifest_submit import ManifestSubmitService
from mission_control.application.environments import (
    EnvironmentNotReady,
    EnvironmentPreparationService,
    InMemoryEnvironmentPreparationRepository,
    preparation_of,
    readiness_requirements,
)
from mission_control.application.environments import preparation as preparation_module
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.run_launch import RunLaunchReceipt
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.environment_preparation import (
    READINESS_LADDER,
    EnvironmentDeclaration,
    EnvironmentPreparation,
    LaunchReadinessPolicy,
    ReadinessLevel,
    ReadinessMark,
    ReadinessRefused,
    preparation_id,
)
from mission_control.domain.execution.lanes import CursorExecutionBinding, PreparedSession
from mission_control.domain.frames.contracts import FrameKind
from mission_control.domain.policies.contracts import ActorContext
from tests.fixtures.lane_turns import cursor_binding, cursor_operation
from tests.unit.authoring.test_manifest_v2_environment import (
    KIT_PIN,
    RESOLVED,
    SECRET_REFS,
    _sdk_templates,
    compile_text,
    manifest,
)

AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
RECEIPT = "sha256:" + "b" * 64
D = ReadinessLevel


def _declared(profile: str = "claude_agent_sdk") -> EnvironmentPreparation:
    declaration = EnvironmentDeclaration.of(profile)
    return EnvironmentPreparation(
        preparation_id=uuid4(),
        run_key="run-1",
        harness_execution_id=uuid4(),
        generation=1,
        lane_profile=declaration.lane_profile,
        binding_digest=DIGEST,
        declaration=declaration,
        declaration_digest=declaration.digest,
        readiness=D.DECLARED,
        marks=(ReadinessMark(level=D.DECLARED, reached_at=AT, evidence_ref="binding:x"),),
    )


def _climbed(*levels: ReadinessLevel) -> EnvironmentPreparation:
    record = _declared()
    for offset, level in enumerate(levels, start=1):
        record = record.advanced(
            level,
            at=AT + timedelta(seconds=offset),
            evidence_ref=f"evidence:{level}",
            receipt_digest=RECEIPT if level is D.PREPARED else None,
        )
    return record


def _prepared_session(
    profile: str, *, workspace: str | None = "workspace_lease:lease-1", receipt: str = RECEIPT
) -> PreparedSession:
    return PreparedSession(
        lane_profile=profile,
        harness_execution_id=str(uuid4()),
        generation=1,
        workspace_ref=workspace,
        projection_digests={"projection_digest": DIGEST, "packet_digest": DIGEST},
        materialization_ref=receipt,
    )


# --- The ladder ---------------------------------------------------------------------------------


def test_the_ladder_orders_six_levels() -> None:
    assert [level.value for level in READINESS_LADDER] == [
        "declared",
        "rendered",
        "delivered",
        "prepared",
        "discovered",
        "exercised",
    ]


def test_levels_climb_one_at_a_time_up_to_prepared_and_never_regress() -> None:
    record = _climbed(D.RENDERED, D.DELIVERED)
    with pytest.raises(ReadinessRefused, match="delivered needs rendered first"):
        _declared().advanced(D.DELIVERED, at=AT, evidence_ref="skip")
    # A level already reached is idempotent, never a regression.
    assert record.advanced(D.RENDERED, at=AT, evidence_ref="again") is record
    assert [mark.level for mark in record.marks] == [D.DECLARED, D.RENDERED, D.DELIVERED]
    with pytest.raises(ReadinessRefused, match="receipt digest"):
        record.advanced(D.PREPARED, at=AT, evidence_ref="no-receipt")
    with pytest.raises(ReadinessRefused, match="after the environment is prepared"):
        record.advanced(D.EXERCISED, at=AT, evidence_ref="hook")


def test_observations_follow_preparation_and_a_hook_may_skip_discovery() -> None:
    record = _climbed(D.RENDERED, D.DELIVERED, D.PREPARED, D.EXERCISED)
    assert record.readiness is D.EXERCISED and record.mark(D.DISCOVERED) is None
    assert record.receipt_digest == RECEIPT
    # Discovery reported after a hook fired changes nothing.
    assert record.advanced(D.DISCOVERED, at=AT, evidence_ref="init") is record
    with pytest.raises(ReadinessRefused, match="another receipt"):
        record.advanced(D.PREPARED, at=AT, evidence_ref="x", receipt_digest=DIGEST)


def test_the_record_refuses_an_inconsistent_ladder() -> None:
    base = _climbed(D.RENDERED).model_dump()
    gap = [
        base["marks"][0],
        {"level": "delivered", "reached_at": AT, "evidence_ref": "x"},
    ]
    with pytest.raises(ValidationError, match="contiguous"):
        EnvironmentPreparation.model_validate({**base, "marks": gap, "readiness": "delivered"})
    with pytest.raises(ValidationError, match="highest level"):
        EnvironmentPreparation.model_validate({**base, "readiness": "declared"})
    with pytest.raises(ValidationError, match="receipt makes"):
        EnvironmentPreparation.model_validate({**base, "receipt_digest": RECEIPT})
    with pytest.raises(ValidationError, match="declaration_digest"):
        EnvironmentPreparation.model_validate({**base, "declaration_digest": DIGEST})


def test_a_later_observation_merges_without_regressing() -> None:
    stored = _climbed(D.RENDERED, D.DELIVERED, D.PREPARED)
    earlier = _climbed(D.RENDERED).model_copy(
        update={"preparation_id": stored.preparation_id, "harness_execution_id": uuid4()}
    )
    assert stored.merged(earlier) is stored
    later = stored.advanced(D.DISCOVERED, at=AT, evidence_ref="init")
    assert stored.merged(later).readiness is D.DISCOVERED
    with pytest.raises(ReadinessRefused, match="another preparation"):
        stored.merged(_declared())


def test_a_generation_prepared_again_keeps_the_receipt_it_recorded() -> None:
    stored = _climbed(D.RENDERED, D.DELIVERED, D.PREPARED)
    again = EnvironmentPreparation.model_validate({**stored.model_dump(), "receipt_digest": DIGEST})
    assert again.receipt_digest != stored.receipt_digest
    # A re-preparation into the reused lease: the first receipt stands, nothing is rewritten.
    assert stored.merged(again) is stored
    later = again.advanced(D.DISCOVERED, at=AT, evidence_ref="init")
    merged = stored.merged(later)
    assert merged.readiness is D.DISCOVERED and merged.receipt_digest == RECEIPT
    # Advancing with a contradicting receipt directly is still refused.
    with pytest.raises(ReadinessRefused, match="another receipt"):
        stored.advanced(D.PREPARED, at=AT, evidence_ref="x", receipt_digest=DIGEST)


def test_the_launch_policy_minimum_follows_the_placement() -> None:
    policy = LaunchReadinessPolicy()
    assert {profile: policy.minimum(profile) for profile in ("codex", "cursor_cloud")} == {
        "codex": D.PREPARED,
        "cursor_cloud": D.DELIVERED,
    }
    refused = policy.decide(_climbed(D.RENDERED, D.DELIVERED))
    assert not refused.admitted and refused.minimum is D.PREPARED
    assert refused.reason is not None and "reached delivered" in refused.reason
    assert policy.decide(_climbed(D.RENDERED, D.DELIVERED, D.PREPARED)).admitted


# --- What one prepare proves ----------------------------------------------------------------------


def _without_kit(document: dict[str, Any]) -> None:
    document["mission"]["environment"].pop("kit")


def _provider_template(change: Any = None, generation: int = 1) -> Any:
    template = next(iter(_sdk_templates(change).values()))
    return template, LaneExecutionIdentity.of(template, "claude_agent_sdk", generation)


def test_a_local_prepare_without_a_mission_layer_is_prepared() -> None:
    template, identity = _provider_template(_without_kit)
    binding = ProviderExecutionBinding.carried_by(template)
    record = preparation_of(identity, binding, _prepared_session("claude_agent_sdk"), at=AT)
    assert record.readiness is D.PREPARED and not record.omissions
    assert record.preparation_id == preparation_id(
        identity.request_scope, identity.harness_execution_id, 1
    )
    assert record.binding_digest == binding.binding_digest
    assert record.observed_config_digest == DIGEST and record.receipt_digest == RECEIPT
    assert [(item.item, item.channel) for item in record.deliveries] == [
        ("host_projection", "worktree_write"),
        ("context_packet", "worktree_write"),
    ]
    # Names and channels only; the references and values never reach the record.
    assert [(item.name, item.channel) for item in record.secrets] == [
        ("FIRECRAWL_API_KEY", "process_environment"),
        ("MC_SIGNAL_TOKEN", "process_environment"),
    ]
    assert "secret:firecrawl" not in record.model_dump_json(exclude={"declaration"})
    assert record.declaration.secret_refs == SECRET_REFS


def test_a_declared_kit_stops_at_delivered_until_its_setup_receipt_arrives() -> None:
    template, identity = _provider_template()
    record = preparation_of(
        identity,
        ProviderExecutionBinding.carried_by(template),
        _prepared_session("claude_agent_sdk"),
        at=AT,
    )
    assert record.readiness is D.DELIVERED and record.declaration.setup_pin == KIT_PIN
    (omission,) = record.omissions
    assert KIT_PIN in omission and ".mission/setup/receipt.json" in omission
    decision = LaunchReadinessPolicy().decide(record)
    assert not decision.admitted and decision.minimum is D.PREPARED


def test_a_declared_kit_is_prepared_by_the_setup_receipt_its_mission_layer_wrote() -> None:
    template, identity = _provider_template()
    session = _prepared_session("claude_agent_sdk")
    setup_receipt = "sha256:" + "5" * 64
    session = session.model_copy(
        update={
            "projection_digests": {
                **session.projection_digests,
                "setup_digest": "sha256:" + "6" * 64,
                "setup_receipt_digest": setup_receipt,
            }
        }
    )
    record = preparation_of(identity, ProviderExecutionBinding.carried_by(template), session, at=AT)
    assert record.readiness is D.PREPARED and not record.omissions
    assert record.receipt_digest == setup_receipt
    assert record.marks[-1].evidence_ref == f"setup_receipt:{setup_receipt}"
    assert LaunchReadinessPolicy().decide(record).admitted


def test_a_cloud_branch_commit_is_delivered_and_admitted() -> None:
    operation = cursor_operation("cursor_cloud")
    identity = LaneExecutionIdentity.of(operation, "cursor_cloud", 1)
    prepared = _prepared_session("cursor_cloud", workspace="branch:mc/run-1@abc1234")
    record = preparation_of(identity, CursorExecutionBinding.carried_by(operation), prepared, at=AT)
    assert record.readiness is D.DELIVERED
    assert record.deliveries[0].channel == "branch_commit"
    assert record.receipt_digest is None and "receipt signal" in record.omissions[0]
    # A Cursor binding carries no environment binding: declared as its lane alone.
    assert record.declaration == EnvironmentDeclaration.of("cursor_cloud")
    assert record.degradations and "cursor_binding" in record.degradations[0]
    assert LaunchReadinessPolicy().decide(record).admitted


def test_a_cloud_provider_environment_declares_its_kit_and_delivers_both_layers() -> None:
    """MO-13: a cursor_cloud binding with a provider environment declares the kit, secrets and
    network policy it carries; its prepare delivers the mission layer on the branch and the
    base layer in the provider environment, and stays `delivered` until the receipt signal."""

    binding = cursor_binding(
        "cursor_cloud",
        network=RESOLVED,
        cloud={
            "provider_environment": {
                "strategy": "sync",
                "kit_pin": KIT_PIN,
                "secret_refs": list(SECRET_REFS),
            }
        },
    )
    operation = cursor_operation("cursor_cloud", binding=binding)
    identity = LaneExecutionIdentity.of(operation, "cursor_cloud", 1)
    prepared = _prepared_session("cursor_cloud", workspace="branch:mc/run-1@abc1234")
    base_layer = "sha256:" + "7" * 64
    prepared = prepared.model_copy(
        update={
            "projection_digests": {
                **prepared.projection_digests,
                "setup_digest": "sha256:" + "6" * 64,
                "provider_environment_digest": base_layer,
            }
        }
    )
    record = preparation_of(identity, binding, prepared, at=AT)
    assert record.declaration == EnvironmentDeclaration(
        lane_profile="cursor_cloud",
        setup_pin=KIT_PIN,
        secret_refs=SECRET_REFS,
        network_policy_ref=RESOLVED.digest,
    )
    assert [(item.item, item.channel) for item in record.deliveries] == [
        ("host_projection", "branch_commit"),
        ("context_packet", "branch_commit"),
        ("mission_layer", "branch_commit"),
        ("base_layer", "provider_environment"),
    ]
    assert record.deliveries[-1].ref == f"config:{base_layer}"
    assert [(item.name, item.channel) for item in record.secrets] == [
        ("FIRECRAWL_API_KEY", "cursor_environment_secret")
    ]
    assert record.degradations == (
        "secrets: MC_SIGNAL_TOKEN is minted per run and no cursor_cloud channel delivers it",
    )
    assert record.readiness is D.DELIVERED and "receipt signal" in record.omissions[0]


def test_a_committed_environment_file_holds_the_base_layer_but_no_secret() -> None:
    """MO-13: when an mc-owned committed file shadows the synced environment, the base layer
    is that file and no channel Mission Control wrote holds the declared secrets."""

    binding = cursor_binding(
        "cursor_cloud",
        network=RESOLVED,
        cloud={
            "provider_environment": {
                "strategy": "sync",
                "kit_pin": KIT_PIN,
                "secret_refs": list(SECRET_REFS),
            }
        },
    )
    operation = cursor_operation("cursor_cloud", binding=binding)
    identity = LaneExecutionIdentity.of(operation, "cursor_cloud", 1)
    prepared = _prepared_session("cursor_cloud", workspace="branch:mc/run-1@abc1234")
    committed = "sha256:" + "8" * 64
    prepared = prepared.model_copy(
        update={
            "projection_digests": {
                **prepared.projection_digests,
                "provider_environment_file_digest": committed,
            }
        }
    )
    record = preparation_of(identity, binding, prepared, at=AT)
    assert (record.deliveries[-1].item, record.deliveries[-1].channel) == (
        "base_layer",
        "repository_file",
    )
    assert record.deliveries[-1].ref == f"config:{committed}"
    assert [(item.name, item.channel) for item in record.secrets] == [
        ("FIRECRAWL_API_KEY", "owner_prerequisite")
    ]


def test_a_prepare_without_projection_or_workspace_names_the_gap() -> None:
    operation = cursor_operation()
    identity = LaneExecutionIdentity.of(operation, "cursor_local", 1)
    bare = PreparedSession(lane_profile="cursor_local", harness_execution_id="x", generation=1)
    record = preparation_of(identity, CursorExecutionBinding.carried_by(operation), bare, at=AT)
    assert record.readiness is D.DECLARED and record.omissions[0].startswith("rendered:")
    unplaced = _prepared_session("cursor_local", workspace=None)
    record = preparation_of(identity, CursorExecutionBinding.carried_by(operation), unplaced, at=AT)
    assert record.readiness is D.RENDERED and record.omissions[0].startswith("delivered:")


# --- The service: record, gate, observe ----------------------------------------------------------


def test_the_service_records_gates_and_raises_the_ladder_from_frames() -> None:
    with_kit, without_kit = _provider_template(), _provider_template(_without_kit, 2)

    async def scenario() -> None:
        repository = InMemoryEnvironmentPreparationRepository()
        service = EnvironmentPreparationService(repository, clock=lambda: AT)
        template, identity = with_kit
        with pytest.raises(EnvironmentNotReady) as refused:
            await service.admit_start(
                identity,
                ProviderExecutionBinding.carried_by(template),
                _prepared_session("claude_agent_sdk"),
            )
        assert refused.value.decision.readiness is D.DELIVERED
        (stored,) = await repository.for_run(identity.request_scope, identity.run_key)
        assert stored == refused.value.preparation
        # Below `prepared` no frame raises the ladder.
        assert (
            await service.observed(identity, FrameKind.HOOK_INVOKED, evidence_ref="frame:1")
        ) == stored

        template, identity = without_kit
        record = await service.admit_start(
            identity,
            ProviderExecutionBinding.carried_by(template),
            _prepared_session("claude_agent_sdk"),
        )
        assert record.readiness is D.PREPARED
        assert await service.observed(identity, FrameKind.STATUS, evidence_ref="f") is None
        # MO-34: an init frame alone proves nothing loaded; a Discovery Proof does
        # (test_discovery_proof.py).
        assert (
            await service.observed(identity, FrameKind.SESSION_INIT, evidence_ref="frame:init")
            is None
        )
        exercised = await service.observed(
            identity, FrameKind.HOOK_INVOKED, evidence_ref="frame:hook"
        )
        assert exercised is not None and exercised.readiness is D.EXERCISED
        mark = exercised.mark(D.EXERCISED)
        assert mark is not None and mark.evidence_ref == "frame:hook"
        # The same level is written once per preparation.
        assert await service.observed(identity, FrameKind.HOOK_INVOKED, evidence_ref="x") is None

    asyncio.run(scenario())


def test_a_preparation_the_record_refuses_is_not_ready() -> None:
    """Fail closed: a contradiction settles the unit instead of failing every retry."""

    async def scenario() -> None:
        repository = InMemoryEnvironmentPreparationRepository()
        service = EnvironmentPreparationService(repository, clock=lambda: AT)
        operation = cursor_operation()
        identity = LaneExecutionIdentity.of(operation, "cursor_local", 1)
        prepared = _prepared_session("cursor_local")
        first = await service.admit_start(identity, cursor_binding(), prepared)
        assert first.readiness is D.PREPARED
        again = await service.admit_start(
            identity, cursor_binding(), _prepared_session("cursor_local", receipt=DIGEST)
        )
        assert again == first, "a re-preparation is admitted on the recorded receipt"
        with pytest.raises(EnvironmentNotReady, match="refuses this preparation") as refused:
            await service.admit_start(identity, cursor_binding(model_id="other"), prepared)
        assert refused.value.preparation == first
        assert not refused.value.decision.admitted

    asyncio.run(scenario())


def test_a_generation_prepared_again_is_admitted_on_what_it_proves() -> None:
    async def scenario() -> None:
        service = EnvironmentPreparationService(
            InMemoryEnvironmentPreparationRepository(), clock=lambda: AT
        )
        operation = cursor_operation()
        identity = LaneExecutionIdentity.of(operation, "cursor_local", 1)
        first = await service.admit_start(
            identity,
            CursorExecutionBinding.carried_by(operation),
            _prepared_session("cursor_local"),
        )
        assert first.readiness is D.PREPARED
        # The same generation prepared again into no workspace: its record keeps `prepared`,
        # but this prepare proved `rendered` only, so the session does not start.
        weaker = _prepared_session("cursor_local", workspace=None)
        with pytest.raises(EnvironmentNotReady, match="reached rendered") as refused:
            await service.admit_start(
                identity, CursorExecutionBinding.carried_by(operation), weaker
            )
        assert refused.value.preparation == first
        assert refused.value.decision.readiness is D.RENDERED

    asyncio.run(scenario())


def test_observed_levels_are_remembered_within_a_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preparation_module, "OBSERVED_MEMORY", 1)

    async def scenario() -> None:
        repository = InMemoryEnvironmentPreparationRepository()
        service = EnvironmentPreparationService(repository, clock=lambda: AT)
        operation = cursor_operation()
        identity = LaneExecutionIdentity.of(operation, "cursor_local", 1)
        await service.admit_start(
            identity,
            CursorExecutionBinding.carried_by(operation),
            _prepared_session("cursor_local"),
        )
        assert await service.observed(identity, FrameKind.HOOK_INVOKED, evidence_ref="h1")
        # Remembered: the same level is not read again.
        assert await service.observed(identity, FrameKind.HOOK_INVOKED, evidence_ref="h") is None
        other = LaneExecutionIdentity.of(operation, "cursor_local", 2)
        await service.admit_start(
            other, CursorExecutionBinding.carried_by(operation), _prepared_session("cursor_local")
        )
        assert await service.observed(other, FrameKind.HOOK_INVOKED, evidence_ref="h2")
        # Forgotten past the bound: read again, and the mark stays as first recorded.
        stored = await service.observed(identity, FrameKind.HOOK_INVOKED, evidence_ref="h3")
        assert stored is not None
        mark = stored.mark(D.EXERCISED)
        assert mark is not None and mark.evidence_ref == "h1"

    asyncio.run(scenario())


def test_a_session_init_frame_never_proves_discovery_and_a_hook_still_exercises() -> None:
    async def scenario() -> None:
        repository = InMemoryEnvironmentPreparationRepository()
        service = EnvironmentPreparationService(repository, clock=lambda: AT)
        operation = cursor_operation()
        identity = LaneExecutionIdentity.of(operation, "cursor_local", 1)
        await service.admit_start(
            identity,
            CursorExecutionBinding.carried_by(operation),
            _prepared_session("cursor_local"),
        )
        assert await service.observed(identity, FrameKind.SESSION_INIT, evidence_ref="i") is None
        hooked = await service.observed(identity, FrameKind.HOOK_INVOKED, evidence_ref="h")
        assert hooked is not None and hooked.readiness is D.EXERCISED

    asyncio.run(scenario())


# --- The start receipt and the Validation Report cite the declaration ----------------------------


def _undeclared(document: dict[str, Any]) -> None:
    """A manifest that declares no kit, variables, secrets, network or git (every mission/v1
    manifest, and many v2 ones)."""

    environment = document["mission"]["environment"]
    for name in ("kit", "variables", "secrets", "network", "git"):
        environment.pop(name)


def _record_digests(templates: dict[str, Any]) -> set[str]:
    digests: set[str] = set()
    for template in templates.values():
        identity = LaneExecutionIdentity.of(template, "claude_agent_sdk", 1)
        record = preparation_of(
            identity,
            ProviderExecutionBinding.carried_by(template),
            _prepared_session("claude_agent_sdk"),
            at=AT,
        )
        digests.add(record.declaration_digest)
    return digests


def test_the_validation_report_cites_what_the_manifest_declares() -> None:
    compilation = compile_text(manifest("claude_agent_sdk"))
    assert compilation.ok
    requirements = compilation.report.environment_readiness
    (definition,) = compilation.definitions
    assert requirements == readiness_requirements(definition)
    assert {item.node_key for item in requirements} == {
        node.key for node in definition.program.nodes
    }
    assert {
        (item.lane_profile, item.minimum, item.declaration_source) for item in requirements
    } == {("claude_agent_sdk", D.PREPARED, "manifest")}
    # The network policy resolves only at launch (MO-15: the installation's hosts and the kit's
    # egress), so the manifest cites its kit and secrets alone and the start receipt, read from
    # the sealed templates, cites what every record carries.
    templates = _sdk_templates()
    records = _record_digests(templates)
    assert records.isdisjoint(item.declaration_digest for item in requirements)
    receipt = readiness_requirements(definition, templates=templates)
    assert records == {item.declaration_digest for item in receipt}


def test_the_start_receipt_cites_the_sealed_binding_the_host_extends() -> None:
    compilation = compile_text(manifest("claude_agent_sdk", _undeclared))
    assert compilation.ok
    (definition,) = compilation.definitions
    templates = _sdk_templates(_undeclared)
    # The deployment host binding adds a network policy the manifest does not declare
    # (deployments/examples/manifest-launch-bindings.multi-provider.codex-0.162.1.example.json).
    assert all(
        ProviderExecutionBinding.carried_by(t).environment.network_policy_ref
        for t in templates.values()
    )
    records = _record_digests(templates)
    report = compilation.report.environment_readiness
    assert {item.declaration_source for item in report} == {"manifest"}
    assert records.isdisjoint(item.declaration_digest for item in report)
    # The start receipt reads the run's sealed templates: every record carries its digest.
    receipt = readiness_requirements(definition, templates=templates)
    assert {item.declaration_source for item in receipt} == {"sealed_binding"}
    assert [(item.node_key, item.role) for item in receipt] == [
        (item.node_key, item.role) for item in report
    ]
    assert records == {item.declaration_digest for item in receipt}


class _Submissions:
    def __init__(self, definition: Any) -> None:
        self.info = {
            "definition": definition.model_dump(mode="json"),
            "run_uuid": uuid4(),
            "mission_id": uuid4(),
        }

    async def run_subscriptions(self, request_scope: str, run_key: str) -> dict[str, Any]:
        return self.info


class _Launches:
    async def launch(self, request: Any, actor: ActorContext) -> RunLaunchReceipt:
        return RunLaunchReceipt(
            run_id=request.run_id,
            request_scope=request.request_scope,
            family=request.family,
            workflow_id=f"wf:{request.run_id}",
            temporal_run_id=None,
            semantic_input_binding_ref=f"semantic-input:manifest:{request.run_id}",
            accepted_run_version=1,
        )


class _Author:
    """A launch input author that returns the run's sealed templates (`LaunchTemplatesPort`)."""

    def __init__(self, templates: dict[str, Any]) -> None:
        self.templates = templates

    async def family_input(self, **_: Any) -> dict[str, Any]:
        return {}

    async def bind(self, request_scope: str, run_id: str, *, family: str) -> dict[str, Any]:
        return self.templates


def test_the_manifest_start_cites_the_run_s_sealed_templates() -> None:
    compilation = compile_text(manifest("claude_agent_sdk", _undeclared))
    (definition,) = compilation.definitions
    templates = _sdk_templates(_undeclared)
    service = ManifestSubmitService(
        compiler=cast(Any, None),
        programs=cast(Any, None),
        run_control=cast(Any, None),
        submissions=_Submissions(definition),
        request_scope="mc/i/a/t",
        launches=cast(Any, _Launches()),
        launch_inputs=_Author(templates),
    )
    actor = ActorContext(actor_id="owner", permissions=frozenset({"workflow_run.start"}))
    started = asyncio.run(service.start("run-1", actor))
    assert started.environment_readiness == readiness_requirements(definition, templates=templates)
    assert _record_digests(templates) == {
        item.declaration_digest for item in started.environment_readiness
    }


def test_a_cloud_role_requires_delivered() -> None:
    compilation = compile_text(manifest("cursor_cloud"))
    assert compilation.ok
    requirements = compilation.report.environment_readiness
    assert requirements and {(item.lane_profile, item.minimum) for item in requirements} == {
        ("cursor_cloud", D.DELIVERED)
    }
    # A Cursor binding declares its lane alone, exactly as the record will.
    assert {item.declaration_digest for item in requirements} == {
        EnvironmentDeclaration.of("cursor_cloud").digest
    }


def test_deep_agents_roles_are_not_cited() -> None:
    compilation = compile_text(manifest("claude_agent_sdk", deep_agents_node=True))
    (definition,) = compilation.definitions
    lanes = {node.key: str(node.environment.lane or node.lane) for node in definition.program.nodes}
    assert "deep_agents" in lanes.values()
    cited = {item.node_key for item in compilation.report.environment_readiness}
    assert cited == {key for key, lane in lanes.items() if lane != "deep_agents"}
