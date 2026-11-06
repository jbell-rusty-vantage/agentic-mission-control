"""Ordinary local GoalDirected repair fixture. Run only after the StageGraph gate."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from tests.acceptance.mission_control.test_overnight_stagegraph import (
    ROOT,
    overnight_launch_bindings,
    production_lifecycle,
    stagegraph_manifest,
)
from tests.fixtures.manifest_runtime import AUTHOR
from tests.fixtures.rrm009_production_harness import ProductionStack

from mission_control.application.authoring.manifest_submit import SubmitRequest
from mission_control.contracts.identities import mission_root_id
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.domain.execution.contracts import StructuredOutputBinding
from mission_control.domain.programs.goal_directed_runtime import (
    GoalNamedExecutorObservation,
    GoalVerifierObservation,
)


def goal_manifest(pack: dict[str, Any]) -> str:
    template = ROOT / "tests/fixtures/manifests/sprint-oc-w1/ai-engineer.report.mission.yml"
    document = load_manifest_yaml(
        template.read_text()
        .replace("__PACK__", json.dumps(pack))
        .replace("__PRODUCER__", "frontier.default")
    )
    mission = document["mission"]
    mission["key"] = "overnight-goal-exact-repair"
    mission["title"] = "Two-iteration grounded report repair"
    mission["program"]["verifier"]["environment"]["model"]["profile"] = "frontier.default"
    mission["environment"]["capabilities"] = load_manifest_yaml(stagegraph_manifest(pack))[
        "mission"
    ]["environment"]["capabilities"]
    mission["environment"]["governors"].update(iterations=2, patience=2)
    mission["environment"]["budget"]["tool_calls"] = 40
    return canonical_manifest_bytes(document).decode()


def goal_launch_bindings(technical: Any) -> Any:
    bindings = overnight_launch_bindings(technical)
    schemas = {
        role: StructuredOutputBinding(
            schema_id=f"overnight-goal-{role}",
            revision=1,
            schema_digest=sha256_digest(model.model_json_schema()),
        )
        for role, model in (
            ("executor", GoalNamedExecutorObservation),
            ("verifier", GoalVerifierObservation),
        )
    }
    return bindings.model_copy(
        update={
            "deep_agents": bindings.deep_agents.model_copy(update={"goal_output_schemas": schemas})
        }
    )


def goal_components(technical: Any, script: Any, log: list[dict[str, Any]]) -> Any:
    from tests.fixtures.overnight_goal_model import GoalModel

    base = technical.components(log)

    def factory(bound: Any, _secrets: Any) -> Any:
        return GoalModel(
            run_id=bound.run_id,
            operation_id=bound.operation_id,
            log=log,
            script=script,
            output_contract_ref=script.output_contract_ref,
            obligation_refs=script.obligation_refs,
        )

    return replace(
        base, model_factories={**base.model_factories, technical.binding.model.ref.digest: factory}
    )


def test_goal_manifest_preserves_independent_review_and_repair_bounds() -> None:
    from mission_control.application.authoring.completion_support import completion_support_issues
    from mission_control.domain.authoring.manifest import parse_manifest
    from mission_control.domain.authoring.mission_definition import manifest_to_definitions

    document = load_manifest_yaml(goal_manifest({"reportId": "fixture", "fragments": []}))
    (definition,) = manifest_to_definitions(parse_manifest(document), document)
    assert completion_support_issues(definition) == ()
    program = document["mission"]["program"]
    assert program["behavior"] == "goal_loop" and program["verifier"]["independent"]
    assert document["mission"]["environment"]["governors"]["iterations"] == 2
    assert document["mission"]["goals"][0]["criteria"][0]["acceptance"] == {
        "human": "review_accept"
    }


def test_goal_model_factory_accepts_actual_lane_binding() -> None:
    from langchain_core.messages import HumanMessage
    from tests.fixtures.overnight_goal_model import GoalScript
    from tests.fixtures.rrm009_production_stack import technical_binding

    candidates: list[dict[str, Any]] = [
        {
            "report": {"reportId": "fixture", "revision": revision},
            "assertions": [{"id": f"a{revision}"}],
            "supportSets": [{"id": f"s{revision}"}],
        }
        for revision in (1, 2)
    ]
    script = GoalScript(
        candidates=(candidates[0], candidates[1]), feedback="Exact actionable feedback."
    )
    script.output_contract_ref = "actual-compiled-contract"
    script.obligation_refs = ("actual-compiled-obligation",)
    technical = technical_binding()
    components = goal_components(technical, script, [])
    model = components.model_factories[technical.binding.model.ref.digest](technical.binding, {})
    reply = model.invoke(
        [HumanMessage(content=str({"operation_role": "executor", "goal_iteration": 1}))]
    )
    assert reply.tool_calls[0]["name"] == "report_register"


async def verify_goal(
    stack: Any, scope: str, run_id: str, script: Any, lane: Any, reviews: list[Any]
) -> None:
    from mission_control.adapters.postgres.knowledge.output_contracts import (
        PostgresOutputContractStore,
    )

    store = PostgresOutputContractStore(stack.worker_pool)
    outputs = await store.accepted_outputs(scope, run_id)
    report = next(item for item in outputs if item.obligation_key == "root.report")
    assert report.candidate["ref"] == script.registered[2]["handle"]
    assert report.content_digest == script.registered[2]["digest"]
    assert script.registered[1] != script.registered[2]
    assert {item["iteration"] for item in script.reads} == {1, 2}
    assert any(
        item["iteration"] == 2
        and item["role"] == "executor"
        and script.feedback in item["received"]
        for item in script.contexts
    )
    identities = {
        (item["role"], item["iteration"]): item["operation_id"] for item in script.contexts
    }
    assert len(set(identities.values())) == 4
    evaluator_calls = lane.startup_receipt["fixture_evaluators"]["calls"]
    assert {item["role"] for item in evaluator_calls} >= {"judge", "auditor"}
    assert len({item["credential"] for item in evaluator_calls}) >= 2
    assert reviews, "authored human acceptance must complete through ordinary service"
    for obligation in await store.active_obligations(scope, run_id):
        if obligation.key not in {"root.report", "root.progress_note"}:
            continue
        decision = await store.latest_fulfillment(
            scope, run_id, obligation.key, obligation.revision
        )
        assert decision is not None and decision[1].disposition == "fulfilled"
    retained = await goal_records(stack, scope, run_id)
    assert retained["result"] is not None, "persisted terminal family result missing"
    details = retained["result"]["family_result"]
    assert details["family"] == "GoalDirected"
    assert details["goal_iterations"] == 2 and details["final_verifier_action"] == "accepted"
    assert details["stop_reason"] not in {"not_observed", "cancelled", "iteration_limit"}
    verifications = details["verification_results"]
    assert len(verifications) == 2
    assert verifications[0]["decision"] in {"repair_required", "rejected"}
    assert script.feedback in verifications[0]["findings"]
    assert verifications[1]["decision"] == "accepted"
    executions = details["execution_results"]
    assert len(executions) == 2
    assert {item["session_id"] for item in executions}.isdisjoint(
        {item["verifier_session_id"] for item in verifications}
    )
    assert {item["workspace_id"] for item in executions}.isdisjoint(
        {item["verifier_workspace_id"] for item in verifications}
    )


async def verify_persistent_failure(
    stack: Any, scope: str, run_id: str, script: Any, reviews: list[Any], destination: Path
) -> None:
    from mission_control.adapters.postgres.knowledge.output_contracts import (
        PostgresOutputContractStore,
    )

    assert not reviews, "unsupported reports must not reach authored human acceptance"
    assert not script.errors
    assert {item["iteration"] for item in script.reads} == {1, 2}
    retained = await goal_records(stack, scope, run_id)
    assert retained["result"] is not None
    details = retained["result"]["family_result"]
    assert details["goal_iterations"] == 2
    assert [item["decision"] for item in details["verification_results"]] == [
        "repair_required",
        "repair_required",
    ]
    assert details["stop_reason"] == "iteration_limit", details
    store = PostgresOutputContractStore(stack.worker_pool)
    finalized = await store.finalized_outputs(scope, run_id)
    assessments = await store.output_assessments(scope, run_id)
    superseded = {item.supersedes for item in assessments if item.supersedes is not None}
    held = []
    for iteration in (1, 2):
        exact = script.registered[iteration]
        outputs = [
            output
            for output in finalized
            if output.obligation_key == "root.report"
            and output.candidate.get("ref") == exact["handle"]
            and output.content_digest == exact["digest"]
        ]
        assert len(outputs) == 1, (iteration, exact, outputs)
        output = outputs[0]
        exact_assessments = [
            item
            for item in assessments
            if item.subject_kind == "output_revision"
            and item.subject_id == output.revision_id
            and item.subject_digest == exact["digest"]
            and item.method_pin == "knowledge.report.assess@1"
        ]
        heads = [item for item in exact_assessments if item.assessment_id not in superseded]
        assert heads and all(item.result in {"fail", "review"} for item in heads), heads
        held.append(
            {
                "iteration": iteration,
                "report": exact,
                "output_revision_id": output.revision_id,
                "assessments": [item.model_dump(mode="json") for item in exact_assessments],
                "active_assessment_ids": [item.assessment_id for item in heads],
            }
        )
    (destination / "06-evidence/held-assessment-verification.json").write_text(
        json.dumps(held, indent=2), encoding="utf-8"
    )
    assert not any(
        item.obligation_key == "root.report" for item in await store.accepted_outputs(scope, run_id)
    )
    for obligation in await store.active_obligations(scope, run_id):
        if obligation.key != "root.report":
            continue
        decision = await store.latest_fulfillment(
            scope, run_id, obligation.key, obligation.revision
        )
        assert decision is not None and decision[1].disposition != "fulfilled"


async def verify_stale_feedback_replay(
    stack: Any, scope: str, run_id: str, destination: Path
) -> None:
    """Replay actual old feedback at the host resolver; do not dispatch a stale operation."""
    import base64

    from pydantic import TypeAdapter

    from mission_control.adapters.postgres.operations.operation_binding_repository import (
        PostgresOperationBindingRepository,
    )
    from mission_control.adapters.postgres.orchestration.goal_directed_repository import (
        PostgresGoalDirectedDocumentRepository,
    )
    from mission_control.application.programs.goal_context import resolve_goal_context
    from mission_control.domain.programs.contracts import GoalVerificationResult
    from mission_control.domain.programs.goal_directed_runtime import (
        GoalOperationPreparationRequest,
    )

    response = await stack.http.get(
        f"/run-control/v1/runs/{run_id}", params={"request_scope": scope}
    )
    assert response.status_code == 200, response.text
    family_id = response.json()["execution_target"]["family_workflow_id"]
    history = await stack.client.get_workflow_handle(family_id).fetch_history()
    (destination / "06-evidence/family-history.json").write_text(
        history.to_json(), encoding="utf-8"
    )
    selected = []
    for event in json.loads(history.to_json())["events"]:
        scheduled = event.get("activityTaskScheduledEventAttributes", {})
        if scheduled.get("activityType", {}).get("name") != "goaldirected.prepare_verifier":
            continue
        for payload in scheduled["input"]["payloads"]:
            request = GoalOperationPreparationRequest.model_validate(
                json.loads(base64.b64decode(payload["data"]))
            )
            if request.operation_role == "verifier" and request.goal_iteration == 2:
                selected.append(request)
    assert len(selected) == 1, "need exact current verifier2 preparation request"
    current = selected[0]
    documents = PostgresGoalDirectedDocumentRepository(stack.worker_pool)
    bindings = PostgresOperationBindingRepository(stack.worker_pool)
    context = await resolve_goal_context(current, documents, bindings)
    assert context.subject is not None
    assert current.subject_execution is not None
    retained = await goal_records(stack, scope, run_id)
    old = [
        document["payload"]["verification"]
        for document in retained["documents"]
        if document["contract"] == "goal.verification/1"
        and document["payload"]["verification"]["executor_identity"]["iteration"]["goal_iteration"]
        == 1
    ]
    assert len(old) == 1
    stale = TypeAdapter(GoalVerificationResult).validate_python(old[0])
    # This diagnostic deliberately exercises the resolver's independent identity check.
    # No modified request is admitted, dispatched, persisted, or accepted.
    with pytest.raises(ValueError, match="Goal feedback differs") as refused:
        await resolve_goal_context(
            current.model_copy(update={"verification_feedback": stale}), documents, bindings
        )
    (destination / "06-evidence/stale-feedback-replay.json").write_text(
        json.dumps(
            {
                "mode": "pure host resolver replay over actual immutable source records",
                "live_stale_dispatch": False,
                "current_subject": current.subject_execution.to_payload(),
                "stale_verification_ref": stale.verification_ref,
                "stale_executor_identity": old[0]["executor_identity"],
                "refusal": str(refused.value),
                "normal_current_subject_resolution": "passed",
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


async def goal_records(stack: Any, scope: str, run_id: str) -> dict[str, Any]:
    from mission_control.adapters.postgres.run_control import canonical as mc

    async with stack.worker_pool.acquire() as connection, connection.transaction():
        args = await mc.begin(connection, scope)
        documents = await connection.fetch(
            "SELECT contract,payload FROM mission_control.runtime_document WHERE "
            "installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
            "AND contract LIKE 'goal.%' AND identity::jsonb->>0=$4",
            *args,
            run_id,
        )
        result = await connection.fetchrow(
            "SELECT result_digest,result_payload FROM mission_control.coordinator_workflow_result "
            "WHERE installation_id=$1 AND application_id=$2 AND tenant_id=$3 AND run_key=$4",
            *args,
            run_id,
        )
    payload = mc.load(result["result_payload"]) if result else None
    if result:
        assert sha256_digest(payload) == result["result_digest"]
    return {
        "result": payload,
        "documents": [
            {"contract": row["contract"], "payload": mc.load(row["payload"])} for row in documents
        ],
    }


async def run_goal_fixture(
    stack: ProductionStack,
    lifecycle: Any,
    manifest: str,
    destination: Path,
    *,
    script: Any,
    collect: Callable[[str, Path], Awaitable[None]],
    verify: Callable[[str], Awaitable[None]],
    progress: Callable[[str], Awaitable[None]] | None = None,
    timeout_seconds: float = 180,
    expected_terminal_outcomes: frozenset[str] = frozenset({"completed"}),
) -> str:
    """Submit/start through ordinary handlers, retain failed attempts, require exact proof.

    ``verify`` must check actual output-store/transfer/read receipts, not model prose.
    ``collect`` runs while PostgreSQL, Temporal, provider backends and KS remain available.
    The caller owns teardown and cancellation if a timed-out workflow is still active.
    """
    assert stack.database is not None
    await asyncio.to_thread(destination.mkdir, parents=True, exist_ok=True)
    (destination / "01-authored-mission.yml").write_text(manifest, encoding="utf-8")
    run_id: str | None = None
    outcome: dict[str, Any] = {"qualified": False, "result": "failed-before-admission"}
    try:
        receipt, replayed = await lifecycle.submit(
            SubmitRequest(
                manifest_yaml=manifest,
                request_id=uuid4(),
                actor=AUTHOR,
                sponsorship_refs=frozenset({"sponsorship:test"}),
            )
        )
        assert not replayed
        (mission,) = receipt.missions
        assert mission.family == "GoalDirected" and mission.run_id is not None
        run_id = mission.run_id
        outcome["result"] = "admitted"
        (destination / "06-evidence").mkdir(exist_ok=True)
        (destination / "06-evidence/admission.json").write_text(
            receipt.model_dump_json(indent=2), encoding="utf-8"
        )
        scope = stack.database.scope("tenant-1")
        from mission_control.bootstrap.technical_api import api

        projection = await api.state.run_control_service.get_run(scope, run_id)
        configuration = await stack.control_plane.retrieve_for_admission(
            projection.effective_configuration_digest
        )
        from mission_control.domain.authoring.contracts import GoalDirectedBlueprint

        assert isinstance(configuration.selected_blueprint, GoalDirectedBlueprint)
        assert not configuration.selected_blueprint.output_slots, (
            "reference/text-only fixture must not silently become legacy schema completion"
        )
        script.output_contract_ref = sorted(configuration.workflow_type.output_contracts)[0]
        script.obligation_refs = tuple(sorted(projection.required_obligation_refs))
        await lifecycle.start(run_id, AUTHOR)
        outcome["result"] = "running"
        scope = stack.database.scope("tenant-1")
        async with asyncio.timeout(timeout_seconds):
            while True:
                if progress is not None:
                    await progress(run_id)
                response = await stack.http.get(
                    f"/run-control/v1/runs/{run_id}", params={"request_scope": scope}
                )
                assert response.status_code == 200, response.text
                observed = response.json()
                if observed["phase"] == "terminal":
                    break
                await asyncio.sleep(0.25)
            # Projection terminalization precedes the root's durable result activity.
            # Keep ordinary workers alive until that host completion has finished.
            outcome["terminal"] = observed
            root = stack.client.get_workflow_handle(mission_root_id(scope, run_id))
            assert (await root.describe()).workflow_type == "mc.mission_run.v1"
            await root.result()
        outcome["terminal"] = observed
        assert observed["terminal_outcome"] in expected_terminal_outcomes, observed
        await verify(run_id)
        outcome["result"] = "passed-engineering-fixture"
        return run_id
    except BaseException as error:
        outcome["last_execution_state"] = outcome["result"]
        outcome["result"] = "timed_out" if isinstance(error, TimeoutError) else "failed"
        outcome["error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        try:
            if run_id is not None:
                await collect(run_id, destination)
        finally:
            (destination / "07-validation.json").write_text(
                json.dumps(outcome, indent=2, default=str), encoding="utf-8"
            )


async def _run_goal_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str) -> None:
    """Real PostgreSQL/Temporal/KS HTTP; only producer/evaluator cognition is scripted."""
    from datetime import UTC, datetime

    from tests.fixtures.knowledge_binding import model_content
    from tests.fixtures.mission_control_common_db import canonical_scope
    from tests.fixtures.mission_control_production_stack import open_postgres_production_stack
    from tests.fixtures.overnight_goal_model import GoalScript
    from tests.fixtures.overnight_trusted import install_scripted_trusted
    from tests.fixtures.rrm009_production_stack import technical_binding
    from tests.integration.deep_agents.test_report_source_real_service import response
    from tests.integration.temporal.test_manifest_launch_production import host_pins

    from mission_control.adapters.postgres.human_tasks.repository import PostgresHumanTaskRepository
    from mission_control.adapters.temporal.human_gate_wake import TemporalHumanGateWake
    from mission_control.application.human_tasks.service import HumanTaskService
    from mission_control.application.knowledge.access import instant
    from mission_control.bootstrap.composition import compose_knowledge_lane
    from mission_control.bootstrap.settings import get_settings
    from mission_control.contracts.knowledge_protocol import Origin
    from mission_control.domain.policies.contracts import ActorContext
    from mission_control.domain.programs.human_gate import HumanResolutionRequest

    assert scenario in {"repair", "persistent-failure", "unavailable", "restart"}
    application = "ai-engineer"
    monkeypatch.setenv("MISSION_CONTROL_APPLICATION", application)
    get_settings.cache_clear()
    scope = canonical_scope(application_id=application)
    _, installation, _, tenant = scope.split("/")
    evidence = Path(
        os.environ.get("MISSION_CONTROL_OVERNIGHT_EVIDENCE", str(tmp_path / "evidence"))
    )
    await asyncio.to_thread(evidence.mkdir, parents=True, exist_ok=True)
    evidence = (
        evidence / "goal-directed" / os.environ.get("MISSION_CONTROL_FIXTURE_ATTEMPT", "run-1")
    )
    if scenario != "repair":
        evidence /= scenario
    await asyncio.to_thread(evidence.mkdir, parents=True, exist_ok=True)
    (evidence / "README.md").write_text(
        "GoalDirected engineering attempt: real local PostgreSQL, Temporal and KS HTTP; "
        "scripted producer/evaluator cognition. Setup/execution pending; see sibling run log "
        "for setup failure. No qualification claim. Capture proof is separate Phase 0.\n",
        encoding="utf-8",
    )
    key_path = tmp_path / "knowledge-private.jwk.json"
    config_path = tmp_path / "knowledge-host.json"
    origin = Origin(
        kind="standalone",
        installationId=installation,
        applicationId=application,
        tenantId=tenant,
        issuer="mission-control",
        subject="mission-control-runtime",
        mission=None,
        recoveryAuthorityRef=None,
        invocationId="overnight-goal-startup",
        authenticatedAt=instant(datetime.now(UTC)),
    )
    config_path.write_text(
        json.dumps({"origin": origin.model_dump(mode="json"), "keyPath": str(key_path)}),
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["KNOWLEDGE_DB_CONTRACT_ADMIN_DSN"] = environment["MISSION_CONTROL_TEST_ADMIN_DSN"]
    log = (evidence / "knowledge-host.log").open("wb")
    process = await asyncio.to_thread(
        subprocess.Popen,
        [
            "node",
            "--import",
            "tsx",
            "src/knowledge-operation/tests/report-source-fixture-host.ts",
            str(config_path),
        ],
        cwd=ROOT.parent / "knowledge-services/apps/verification-executor",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log,
        env=environment,
    )
    try:
        ready = await response(process)
        assert ready["ready"], ready
        payload = model_content(ready["reports"][-1])
        payload["report"]["revision"] = 1
        payload["report"]["supersedes"] = None
        first = model_content(ready["reports"][0])
        second = model_content(ready["reports"][-1])
        if scenario == "persistent-failure":
            second = model_content(ready["reports"][0])
            second["report"]["revision"] = 2
            for collection in ("assertions", "supportSets"):
                for record in first[collection]:
                    original = record["id"]
                    second = json.loads(
                        json.dumps(second).replace(
                            json.dumps(original), json.dumps(original + "-persistent-r2")
                        )
                    )
        script = GoalScript(
            candidates=(first, second),
            accept_final=scenario != "persistent-failure",
            feedback="The first candidate claims 9B, but captured evidence states 7B. "
            "Repair the report to the captured parameter count and cite the exact fragment.",
        )
        model_log: list[dict[str, Any]] = []
        technical = technical_binding()
        components = goal_components(technical, script, model_log)
        bindings_path = tmp_path / "manifest-launch-bindings.json"
        bindings_path.write_text(
            goal_launch_bindings(technical).model_dump_json(indent=2), encoding="utf-8"
        )
        holder: dict[str, Any] = {}
        recovery: Any = None
        if scenario in {"unavailable", "restart"}:
            from tests.fixtures.overnight_goal_recovery import GoalSettlementRecovery

            recovery = GoalSettlementRecovery(
                mode="unavailable" if scenario == "unavailable" else "restart"
            )

        async def lane(settings: Any, pool: Any) -> Any:
            # The service endpoint and key are observed from the actual disposable host.
            settings.knowledge_binding_url = ready["url"]
            settings.knowledge_binding_audience = ready["audience"]
            settings.knowledge_issuer = ready["issuer"]
            settings.knowledge_issuer_key_file = key_path
            settings.knowledge_describe_tenant = tenant
            settings.knowledge_disposable_installation = True
            settings.mc_judge_openai_api_key = None
            settings.mc_auditor_anthropic_api_key = None
            composed = await compose_knowledge_lane(
                settings, pool, application_id=application, installation_id=installation
            )
            assert composed is not None
            composed = install_scripted_trusted(
                composed, pool, application, producer_vendor=technical.binding.model.provider
            )
            if recovery is not None:
                recovery.install(composed)
            holder["lane"] = composed
            return composed

        async with open_postgres_production_stack(
            root=tmp_path,
            monkeypatch=monkeypatch,
            application_id=application,
            technical_override=technical,
            components=components,
            model_log=model_log,
            knowledge_lane=lane,
            fixture_owner_prerequisites=True,
            scoped_mission_root=True,
            extra_environment={
                "MANIFEST_LAUNCH_BINDINGS_PATH": str(bindings_path),
                "CAPABILITY_PINS_PATH": str(host_pins(tmp_path / "capability-pins.json")),
            },
        ) as stack:
            lifecycle = await production_lifecycle(stack, components)
            reviews = HumanTaskService(
                PostgresHumanTaskRepository(stack.worker_pool),
                request_scope=scope,
                wake=TemporalHumanGateWake(stack.client),
            )
            reviewer = ActorContext(actor_id="owner")
            review_records: list[dict[str, Any]] = []
            pack = {
                "reportId": payload["report"]["reportId"],
                "task": payload["task"],
                "fragments": payload["fragments"],
            }

            async def collect(run_id: str, destination: Path) -> None:
                from tests.fixtures.overnight_stagegraph_evidence import export_stagegraph

                gaps = await export_stagegraph(
                    stack,
                    scope,
                    run_id,
                    destination,
                    observed_reads=script.reads,
                    observed_evaluators=holder["lane"].startup_receipt["fixture_evaluators"][
                        "calls"
                    ],
                )
                try:
                    root_history = await stack.client.get_workflow_handle(
                        mission_root_id(scope, run_id)
                    ).fetch_history()
                    (destination / "06-evidence/root-history.json").write_text(
                        root_history.to_json(), encoding="utf-8"
                    )
                except Exception as error:
                    (destination / "06-evidence/root-history-unavailable.json").write_text(
                        json.dumps({"type": type(error).__name__, "message": str(error)}),
                        encoding="utf-8",
                    )
                (destination / "06-evidence/goal-journal.json").write_text(
                    json.dumps(await goal_records(stack, scope, run_id), indent=2, default=str),
                    encoding="utf-8",
                )
                observed = {
                    "run_id": run_id,
                    "scenario": scenario,
                    "recovery": None if recovery is None else recovery.evidence(),
                    "cognition": "scripted",
                    "capture_prerequisite": "separate-phase0",
                    "model_calls": model_log,
                    "tool_calls": script.calls,
                    "script_errors": script.errors,
                    "verifier_backend_reads": script.reads,
                    "received_goal_contexts": script.contexts,
                    "observed_registration_refs": script.registered,
                    "operator_reviews": review_records,
                    "knowledge_startup": holder["lane"].startup_receipt,
                    "missing_evidence": gaps,
                }
                (destination / "06-evidence/observations.json").write_text(
                    json.dumps(observed, indent=2, default=str), encoding="utf-8"
                )

            async def verify(run_id: str) -> None:
                if scenario == "persistent-failure":
                    await verify_persistent_failure(
                        stack, scope, run_id, script, review_records, evidence
                    )
                else:
                    await verify_goal(stack, scope, run_id, script, holder["lane"], review_records)
                await verify_stale_feedback_replay(stack, scope, run_id, evidence)
                if recovery is not None:
                    await recovery.verify(stack, scope, run_id, script)

            async def progress(run_id: str) -> None:
                if recovery is not None:
                    await recovery.progress(stack, scope, run_id, script)
                for task in await reviews.list(reviewer, run_id=run_id, lifecycle="open"):
                    assert hasattr(task, "activation"), (
                        "fixture only accepts authored workflow gates"
                    )
                    packet = task.activation.packet
                    assert packet, (
                        "ordinary goal human review must include exact candidate evidence"
                    )
                    from mission_control.adapters.postgres.knowledge.output_contracts import (
                        PostgresOutputContractStore,
                    )

                    accepted = {
                        output.obligation_key: output
                        for output in await PostgresOutputContractStore(
                            stack.worker_pool
                        ).accepted_outputs(scope, run_id)
                    }
                    assert {item.source for item in packet} >= {"root.report"}, packet
                    named_packet = [item for item in packet if item.source != "goal.verification"]
                    for item in named_packet:
                        output = accepted[item.source]
                        assert item.digest == output.content_digest, (item, output)
                        assert item.ref == (
                            f"output-revision:{output.revision_id}#digest={output.content_digest}"
                        ), (item, output)
                    report = accepted["root.report"]
                    assert report.candidate["ref"] == script.registered[2]["handle"]
                    assert report.content_digest == script.registered[2]["digest"]
                    retained = await goal_records(stack, scope, run_id)
                    from mission_control.domain.programs.human_gate import packet_item

                    decisions = [item for item in packet if item.source == "goal.verification"]
                    assert len(decisions) == 1, packet
                    decision = decisions[0]
                    assert decision == packet_item("goal.verification", decision.ref)
                    matching = [
                        document["payload"]["verification"]
                        for document in retained["documents"]
                        if document["contract"] == "goal.verification/1"
                        and document["payload"]["verification"]["verification_ref"] == decision.ref
                    ]
                    assert len(matching) == 1, (decision, retained)
                    assert matching[0]["decision"] == "accepted", matching
                    resolution = await reviews.resolve(
                        task.human_task_id,
                        HumanResolutionRequest(
                            request_id=f"overnight-review:{task.human_task_id}",
                            expected_task_version=task.version,
                            decision="approve",
                            reviewed_packet_digest=task.activation.packet_digest,
                            comment="Scripted identity/digest approval; semantic review unproved.",
                        ),
                        reviewer,
                    )
                    review_records.append(
                        {
                            "mode": "scripted exact identity/digest approval",
                            "semantic_human_review": False,
                            "observed_candidates": [
                                accepted[item.source].model_dump(mode="json")
                                for item in named_packet
                            ],
                            "observed_goal_records": retained,
                            "task": resolution.task.public(),
                        }
                    )

            await run_goal_fixture(
                stack,
                lifecycle,
                goal_manifest(pack),
                evidence,
                script=script,
                collect=collect,
                verify=verify,
                progress=progress,
                expected_terminal_outcomes=(
                    frozenset({"failed"})
                    if scenario == "persistent-failure"
                    else frozenset({"completed"})
                ),
            )
    finally:
        if process.poll() is None:
            if process.stdin is not None:
                process.stdin.close()
            try:
                await asyncio.to_thread(process.wait, 30)
            except subprocess.TimeoutExpired:
                process.terminate()
                await asyncio.to_thread(process.wait, 30)
        log.close()


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_ordinary_goal_directed_repair_and_exact_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _run_goal_case(tmp_path, monkeypatch, "repair")


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_persistent_unsupported_goal_candidates_exhaust_authored_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _run_goal_case(tmp_path, monkeypatch, "persistent-failure")


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_goal_evaluator_unavailable_waits_then_resumes_exact_saved_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _run_goal_case(tmp_path, monkeypatch, "unavailable")


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_goal_saved_executor_survives_real_worker_restart_without_duplicate_cognition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _run_goal_case(tmp_path, monkeypatch, "restart")
