"""Small ordinary StageGraph fixture helpers; no controller promotion or invented reads.

The integration entry point accepts the production manifest lifecycle and live stack so
the service fixture can own its actual KS host and independent scripted evaluator transport.
Every attempt retains authored inputs and observed terminal state before service teardown.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.support.acceptance.mission_control.overnight_stagegraph import (
    ROOT,
    overnight_launch_bindings,
    production_lifecycle,
    run_stagegraph_fixture,
    stagegraph_manifest,
)

from mission_control.contracts.identities import mission_root_id
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml

pytestmark = pytest.mark.psycopg_selector


def test_overnight_manifest_keeps_required_transfer_and_optional_omission() -> None:
    from mission_control.application.authoring.completion_support import completion_support_issues
    from mission_control.domain.authoring.manifest import parse_manifest
    from mission_control.domain.authoring.mission_definition import manifest_to_definitions

    document = load_manifest_yaml(stagegraph_manifest({"reportId": "fixture", "fragments": []}))
    manifest = parse_manifest(document)
    (definition,) = manifest_to_definitions(manifest, document)
    assert completion_support_issues(definition) == ()
    from tests.fixtures.rrm009_production_stack import AGENT_COGNITIVE_QUEUE, technical_binding

    bindings = overnight_launch_bindings(technical_binding())
    assert bindings.deep_agents.placement.task_queue == AGENT_COGNITIVE_QUEUE
    assert len(bindings.capabilities) == 3
    producer, review_producer, consumer, review_consumer = document["mission"]["program"]["nodes"]
    assert [
        node["behavior"] for node in (producer, review_producer, consumer, review_consumer)
    ] == ["agent_executor", "human_gate", "agent_executor", "human_gate"]
    assert review_producer["objectives"] == ["register_report"]
    assert review_consumer["objectives"] == ["compare_report"]
    assert all(
        goal["criteria"][0]["acceptance"] == {"human": "review_accept"}
        for goal in document["mission"]["goals"]
    )
    outputs = {output["name"]: output for output in producer["outputs"]}
    assert outputs["report"]["enforcement"] == "required"
    assert outputs["progress_note"]["enforcement"] == "required"
    assert outputs["caveats"]["enforcement"] == "optional"
    assert consumer["inputs"] == [
        {"name": "report", "from": "produce.report", "expand": "reference"}
    ]


def test_scripted_model_factory_accepts_the_actual_lane_binding_type() -> None:
    from langchain_core.messages import HumanMessage
    from tests.fixtures.overnight_stagegraph_model import StageGraphScript, stagegraph_components
    from tests.fixtures.rrm009_production_stack import technical_binding

    technical = technical_binding()
    binding = technical.binding.model_copy(
        update={
            "operation_id": (
                "run:operation:execution-epoch:1:stage:produce:mapped:none:slot:execute:attempt:1"
            )
        }
    )
    components = stagegraph_components(technical, StageGraphScript(report={}), [])
    model = components.model_factories[binding.model.ref.digest](binding, {})
    reply = model.invoke([HumanMessage(content="Produce the authored report.")])
    assert reply.tool_calls[0]["name"] == "report_register"


def test_negative_script_preserves_index_digest_after_typed_refusal() -> None:
    from langchain_core.messages import HumanMessage, ToolMessage
    from tests.fixtures.overnight_stagegraph_model import StageGraphCognition, StageGraphScript

    digest = "sha256:" + "a" * 64
    handle = "kh:aiengineer-postgres/report/exact@research-report.v2"
    model = StageGraphCognition(
        run_id="run",
        operation_id="execution-epoch:1:stage:consume:slot:execute",
        log=[],
        position="consume",
        script=StageGraphScript(report={}, wrong_digest_probe=True),
    ).model()
    messages = [
        HumanMessage(content="Read the selected exact report."),
        ToolMessage(
            content=json.dumps({"inputs": [{"access_ref": f"{handle}#digest={digest}"}]}),
            tool_call_id="index",
            name="read_file",
        ),
    ]
    wrong = model.invoke(messages)
    assert wrong.tool_calls[0]["args"]["digest"] != digest
    refusal = ToolMessage(
        content=json.dumps({"ok": False, "result": None, "refusal": {"code": "DIGEST_MISMATCH"}}),
        tool_call_id=wrong.tool_calls[0]["id"],
        name="knowledge_read",
    )
    corrected = model.invoke([*messages, refusal])
    assert corrected.tool_calls[0]["args"] == {"handle": handle, "digest": digest}


def test_isolation_registration_uses_exact_returned_predecessor_receipt() -> None:
    from langchain_core.messages import HumanMessage, ToolMessage
    from tests.fixtures.overnight_stagegraph_model import StageGraphScript, stagegraph_components
    from tests.fixtures.rrm009_production_stack import technical_binding

    technical = technical_binding()
    binding = technical.binding.model_copy(
        update={"operation_id": "run:stage:produce:slot:execute"}
    )
    script = StageGraphScript(
        report={"report": {"revision": 2}},
        prior_report={"older": True},
        sibling_report={"sibling": True},
    )
    components = stagegraph_components(technical, script, [])
    model = components.model_factories[binding.model.ref.digest](binding, {})
    messages: list[Any] = [
        HumanMessage(content="Register isolated prior, sibling and exact successor.")
    ]
    old = {
        "handle": "kh:aiengineer-postgres/report/older@research-report.v2",
        "digest": "sha256:" + "a" * 64,
    }
    sibling = {
        "handle": "kh:aiengineer-postgres/report/sibling@research-report.v2",
        "digest": "sha256:" + "b" * 64,
    }
    first = model.invoke(messages)
    messages.append(
        ToolMessage(
            content=json.dumps({"ok": True, "result": {"affected": [old]}}),
            tool_call_id=first.tool_calls[0]["id"],
            name="report_register",
        )
    )
    second = model.invoke(messages)
    messages.append(
        ToolMessage(
            content=json.dumps({"ok": True, "result": {"affected": [sibling]}}),
            tool_call_id=second.tool_calls[0]["id"],
            name="report_register",
        )
    )
    successor = model.invoke(messages)
    assert successor.tool_calls[0]["name"] == "report_register"
    assert successor.tool_calls[0]["args"]["report"]["report"]["supersedes"] == old
    assert script.registrations == {"prior": old, "sibling": sibling}


async def _run_stagegraph_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, scenario: str
) -> None:
    """Real PostgreSQL/Temporal/KS HTTP; only producer/evaluator cognition is scripted."""
    from datetime import UTC, datetime

    from tests.fixtures.mission_control_production_stack import open_postgres_production_stack
    from tests.fixtures.overnight_stagegraph_model import StageGraphScript, stagegraph_components
    from tests.fixtures.overnight_stagegraph_recovery import SavedConsumerRestart
    from tests.fixtures.overnight_trusted import install_scripted_trusted
    from tests.fixtures.rrm009_production_stack import technical_binding
    from tests.support.ids import canonical_scope
    from tests.support.integration.deep_agents.report_source_real_service import response
    from tests.support.knowledge.content import model_content
    from tests.support.manifest_runtime import host_pins

    from mission_control.adapters.postgres.human_tasks.repository import PostgresHumanTaskRepository
    from mission_control.adapters.postgres.knowledge.output_contracts import (
        PostgresOutputContractStore,
    )
    from mission_control.adapters.temporal.human_gate_wake import TemporalHumanGateWake
    from mission_control.application.human_tasks.service import HumanTaskService
    from mission_control.application.knowledge.access import instant
    from mission_control.bootstrap.composition import compose_knowledge_lane
    from mission_control.bootstrap.settings import get_settings
    from mission_control.contracts.knowledge_protocol import Origin
    from mission_control.domain.policies.contracts import ActorContext
    from mission_control.domain.programs.human_gate import HumanResolutionRequest

    application = "ai-engineer"
    assert scenario in {"accepted", "held", "restart", "wrong-digest", "isolation"}
    recovery = SavedConsumerRestart() if scenario == "restart" else None
    monkeypatch.setenv("MISSION_CONTROL_APPLICATION", application)
    get_settings.cache_clear()
    scope = canonical_scope(application_id=application)
    _, installation, _, tenant = scope.split("/")
    evidence = Path(
        os.environ.get("MISSION_CONTROL_OVERNIGHT_EVIDENCE", str(tmp_path / "evidence"))
    )
    await asyncio.to_thread(evidence.mkdir, parents=True, exist_ok=True)
    evidence = evidence / "stagegraph" / os.environ.get("MISSION_CONTROL_FIXTURE_ATTEMPT", "run-1")
    if scenario != "accepted":
        evidence = evidence / scenario
    await asyncio.to_thread(evidence.mkdir, parents=True, exist_ok=True)
    (evidence / "README.md").write_text(
        "StageGraph engineering attempt: real local PostgreSQL, Temporal and KS HTTP; "
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
        invocationId="overnight-stagegraph-startup",
        authenticatedAt=instant(datetime.now(UTC)),
    )
    config_path.write_text(
        json.dumps({"origin": origin.model_dump(mode="json"), "keyPath": str(key_path)}),
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["KS_AIENG_DB_ADMIN_DSN"] = environment["MISSION_CONTROL_TEST_ADMIN_DSN"]
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
        payload = model_content(ready["reports"][0 if scenario == "held" else -1])
        payload["report"]["revision"] = 1
        payload["report"]["supersedes"] = None
        script = StageGraphScript(report=payload, wrong_digest_probe=scenario == "wrong-digest")
        if scenario == "isolation":
            from copy import deepcopy

            prior = model_content(ready["reports"][0])
            prior["report"]["revision"] = 1
            prior["report"]["supersedes"] = None
            payload["report"]["revision"] = 2
            sibling = deepcopy(payload)
            replacements = {
                item["id"]: item["id"] + "-sibling"
                for name in ("assertions", "supportSets")
                for item in sibling[name]
            }

            def rename(value: Any) -> Any:
                if isinstance(value, dict):
                    return {key: rename(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [rename(item) for item in value]
                return replacements.get(value, value) if isinstance(value, str) else value

            sibling = rename(sibling)
            sibling["report"]["reportId"] += "-sibling"
            sibling["report"]["revision"] = 1
            sibling["report"]["supersedes"] = None
            sibling["report"]["structuredBody"]["sections"][0]["blocks"][0]["inlines"][0][
                "text"
            ] = "SIBLING-ONLY registered report; not selected for the consumer."
            script.prior_report, script.sibling_report = prior, sibling
        model_log: list[dict[str, Any]] = []
        technical = technical_binding()
        components = stagegraph_components(technical, script, model_log)
        bindings_path = tmp_path / "manifest-launch-bindings.json"
        bindings_path.write_text(
            overnight_launch_bindings(technical).model_dump_json(indent=2), encoding="utf-8"
        )
        holder: dict[str, Any] = {}

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
                recovery.install(composed.toolset)
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
            authored_manifest = stagegraph_manifest(pack)
            if scenario == "isolation":
                isolated_document = load_manifest_yaml(authored_manifest)
                isolated_document["mission"]["program"]["nodes"][0]["instruction"] = (
                    "Scripted isolation task: register older, then the distinct sibling, "
                    "then the current report. Set current.supersedes to the exact older report "
                    "handle/digest returned by report_register; never invent a reference. "
                    "Submit only current to produce.report; submit required progress_note and "
                    "expected summary. Older and sibling remain registered but unsubmitted. "
                    "Payloads: "
                    + json.dumps(
                        {
                            "older": script.prior_report,
                            "sibling": script.sibling_report,
                            "current": script.report,
                        },
                        sort_keys=True,
                    )
                )
                authored_manifest = canonical_manifest_bytes(isolated_document).decode("utf-8")

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
                holder["run_id"] = run_id
                observed = {
                    "run_id": run_id,
                    "cognition": "scripted",
                    "capture_prerequisite": "separate-phase0",
                    "model_calls": model_log,
                    "tool_calls": script.calls,
                    "consumer_backend_reads": script.reads,
                    "operator_reviews": review_records,
                    "knowledge_startup": holder["lane"].startup_receipt,
                    "missing_evidence": gaps,
                    "scenario": scenario,
                    "registrations": script.registrations,
                    "recovery": None
                    if recovery is None
                    else {
                        "before": recovery.before,
                        "after": recovery.after,
                        "restarted": recovery.restarted,
                    },
                }
                (destination / "06-evidence/observations.json").write_text(
                    json.dumps(observed, indent=2, default=str), encoding="utf-8"
                )

            async def verify(run_id: str) -> None:
                from tests.fixtures.overnight_stagegraph_evidence import verify_exact_stagegraph

                if scenario == "held":
                    store = PostgresOutputContractStore(stack.worker_pool)
                    assert not any(call["position"] == "consume" for call in script.calls)
                    assert not script.reads and not review_records
                    accepted = await store.accepted_outputs(scope, run_id)
                    assert "produce.report" not in {row.obligation_key for row in accepted}
                    decisions = {}
                    for obligation in await store.active_obligations(scope, run_id):
                        decision = await store.latest_fulfillment(
                            scope, run_id, obligation.key, obligation.revision
                        )
                        if decision is not None:
                            decisions[obligation.key] = decision[1]
                    assert decisions["produce.report"].disposition != "fulfilled"
                    assert decisions["produce.caveats"].enforcement.value == "optional"
                    assert not decisions["produce.caveats"].submitted
                    return
                await verify_exact_stagegraph(stack, scope, run_id, script.reads)
                outputs = await PostgresOutputContractStore(stack.worker_pool).accepted_outputs(
                    scope, run_id
                )
                keys = {output.obligation_key for output in outputs}
                assert {"produce.report", "produce.progress_note", "consume.comparison"} <= keys, (
                    keys
                )
                assert "produce.caveats" not in keys
                assert any("read" in item for item in script.reads), script.reads
                calls = holder["lane"].startup_receipt["fixture_evaluators"]["calls"]
                assert {item["role"] for item in calls} >= {"judge", "auditor"}, calls
                assert len({item["credential"] for item in calls}) >= 2
                if recovery is not None:
                    await recovery.verify(stack, scope, run_id, script)
                if scenario == "wrong-digest":
                    refusals = [
                        item["wrong_digest_refusal"]
                        for item in script.reads
                        if "wrong_digest_refusal" in item
                    ]
                    assert len(refusals) == 1 and not refusals[0]["ok"]
                    assert refusals[0]["refusal"]["code"] in {
                        "SCOPE_DENIED",
                        "EXACT_REVISION_UNAVAILABLE",
                        "DIGEST_MISMATCH",
                    }
                if scenario == "isolation":
                    assert set(script.registrations) == {"prior", "sibling", "current"}
                    excluded = [script.registrations[name] for name in ("prior", "sibling")]
                    indexes = "\n".join(item["index"] for item in script.reads if "index" in item)
                    reads = "\n".join(
                        json.dumps(item["read"], sort_keys=True)
                        for item in script.reads
                        if "read" in item
                    )
                    for report in excluded:
                        assert report["handle"] not in indexes and report["digest"] not in indexes
                        assert report["handle"] not in reads and report["digest"] not in reads
                    assert "9B parameters" not in reads and "SIBLING-ONLY" not in reads
                    registered = script.registrations["current"]
                    accepted_report = next(
                        output for output in outputs if output.obligation_key == "produce.report"
                    )
                    assert accepted_report.candidate["ref"] == registered["handle"]
                    assert accepted_report.content_digest == registered["digest"]
                    from mission_control.adapters.postgres.run_control import canonical as mc

                    async with stack.worker_pool.acquire() as connection, connection.transaction():
                        args = await mc.begin(connection, scope)
                        count = await connection.fetchval(
                            "SELECT count(*) FROM mission_control.output_revision WHERE "
                            "installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
                            "AND run_id=$4::uuid AND content_digest=ANY($5::text[])",
                            *args,
                            run_id,
                            [report["digest"] for report in excluded],
                        )
                    assert count == 0, "older/sibling registrations must remain unsubmitted"

            async def progress(run_id: str) -> None:
                if recovery is not None:
                    await recovery.progress(stack, scope, run_id, script)
                for task in await reviews.list(reviewer, run_id=run_id, lifecycle="open"):
                    assert hasattr(task, "activation"), (
                        "fixture only accepts authored workflow gates"
                    )
                    expected_sources = {
                        "review-producer": {"produce.report", "produce.progress_note"},
                        "review-consumer": {"produce.report", "consume.comparison"},
                    }[task.activation.spec.gate_key]
                    packet = task.activation.packet
                    assert {item.source for item in packet} == expected_sources, packet
                    accepted = {
                        output.obligation_key: output
                        for output in await PostgresOutputContractStore(
                            stack.worker_pool
                        ).accepted_outputs(scope, run_id)
                    }
                    for item in packet:
                        output = accepted[item.source]
                        assert item.digest == output.content_digest, (item, output)
                        assert output.revision_id in item.ref or item.ref == output.candidate.get(
                            "ref"
                        ), (item, output)
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
                                accepted[item.source].model_dump(mode="json") for item in packet
                            ],
                            "task": resolution.task.public(),
                        }
                    )

            try:
                await run_stagegraph_fixture(
                    stack,
                    lifecycle,
                    authored_manifest,
                    evidence,
                    collect=collect,
                    verify=verify,
                    progress=progress,
                    timeout_seconds=60 if scenario == "held" else 180,
                    expected_terminal_outcomes=(
                        frozenset({"failed"}) if scenario == "held" else frozenset({"completed"})
                    ),
                )
            except TimeoutError:
                if scenario != "held":
                    raise
                await verify(holder["run_id"])
                (evidence / "held-negative-proof.json").write_text(
                    json.dumps({"result": "expected-held-without-consumer", "qualified": False}),
                    encoding="utf-8",
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
async def test_held_required_report_blocks_stagegraph_consumer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _run_stagegraph_case(tmp_path, monkeypatch, scenario="held")


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_saved_consumer_survives_real_worker_restart_without_duplicate_cognition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _run_stagegraph_case(tmp_path, monkeypatch, scenario="restart")


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_ordinary_stagegraph_report_settlement_and_exact_consumer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _run_stagegraph_case(tmp_path, monkeypatch, scenario="accepted")


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_wrong_digest_read_refused_before_correct_stagegraph_consumer_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _run_stagegraph_case(tmp_path, monkeypatch, scenario="wrong-digest")


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_stale_and_sibling_registered_reports_excluded_from_exact_stagegraph_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _run_stagegraph_case(tmp_path, monkeypatch, scenario="isolation")
