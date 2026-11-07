"""Ordinary local same-application accepted linked report transfer."""

from __future__ import annotations

import json
from typing import Any

import pytest
from tests.acceptance.mission_control.test_overnight_goal_directed import goal_manifest
from tests.acceptance.mission_control.test_overnight_stagegraph import stagegraph_manifest

from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml


def linked_manifest(pack: dict[str, Any], *, scenario: str = "positive") -> str:
    source = load_manifest_yaml(goal_manifest(pack))["mission"]
    source["key"] = "source"
    source["title"] = "Grounded report accepted by independent verifier and review"
    source["environment"]["governors"].update(iterations=1, patience=1)
    source["environment"]["budget"]["usd"] = 3
    source["environment"]["budget"]["tool_calls"] = 12
    consumer = load_manifest_yaml(stagegraph_manifest(pack))["mission"]
    consumer["key"] = "consumer"
    consumer["title"] = "Independent mission summarizes one accepted linked report"
    consumer["goals"] = [consumer["goals"][1]]
    consumer["program"]["objectives"] = [consumer["goals"][0]["key"]]
    consumer["environment"]["budget"]["usd"] = 2
    consumer["environment"]["budget"]["tool_calls"] = 12
    consume, review = consumer["program"]["nodes"][2:]
    consume["depends_on"] = []
    consume["inputs"] = [{"name": "report", "from": "source.report", "expand": "reference"}]
    consume["instruction"] = (
        "Read /.mission/transfer.json and use knowledge_read on its exact report access_ref. "
        "Submit consume.comparison as a short attributed summary of the actual source bytes."
    )
    review["task"]["packet"] = ["consume.comparison"]
    consumer["program"]["nodes"] = [consume, review]
    if scenario == "held-repair":
        from copy import deepcopy

        source["title"] = "Bounded unsupported source retained for explicit repair"
        consumer["title"] = "Repair exact held report using full source findings"
        consume["outputs"].extend(
            deepcopy(item)
            for item in source["program"]["outputs"]
            if item["name"] in {"report", "progress_note"}
        )
        consume["instruction"] = (
            "Read the exact held report and full findings from /.mission/transfer.json. "
            "These are repair subjects, not accepted evidence. Propose a grounded successor "
            "with supersedes bound to the actual source receipt; submit consume.report, "
            "consume.progress_note and consume.comparison for normal checks and review."
        )
        review["task"]["packet"].extend(["consume.report", "consume.progress_note"])
    if scenario == "adoption":
        from copy import deepcopy

        promised = deepcopy(
            next(item for item in source["program"]["outputs"] if item["name"] == "report")
        )
        promised["name"] = "adopted_report"
        consume["outputs"].append(promised)
        review["task"]["packet"].append("consume.adopted_report")
    return canonical_manifest_bytes(
        {
            "manifest": "mission/v1",
            "missions": [source, consumer],
            "links": [
                {
                    "from": "source",
                    "to": "consumer",
                    "kind": "supplies",
                    "outputs": ["report"],
                    "on": (
                        {"goal_accepted": {"goal_key": source["goals"][0]["key"]}}
                        if scenario.startswith("cancel-")
                        else "execution_complete"
                        if scenario == "held-repair"
                        else "mission_accepted"
                    ),
                    "on_upstream_cancel": (
                        "cancel_downstream" if scenario == "cancel-propagate" else "continue"
                    ),
                    "receiving_purpose": "repair"
                    if scenario == "held-repair"
                    else "dependent_input",
                    "selector": "finalized_snapshot"
                    if scenario == "held-repair"
                    else "accepted_snapshot",
                    "placement": "handle",
                    "alternatives": ["file"],
                }
            ],
        }
    ).decode()


def test_linked_manifest_keeps_acceptance_gate_and_independent_consumer() -> None:
    from mission_control.application.authoring.completion_support import completion_support_issues
    from mission_control.domain.authoring.manifest import parse_manifest, resolve_environments
    from mission_control.domain.authoring.mission_definition import manifest_to_definitions

    document = load_manifest_yaml(linked_manifest({"reportId": "fixture", "fragments": []}))
    manifest = parse_manifest(document)
    structure = resolve_environments(manifest, document)
    assert structure.blockers == (), structure.blockers
    definitions = manifest_to_definitions(manifest, document)
    assert len(definitions) == 2
    assert all(completion_support_issues(definition) == () for definition in definitions)
    assert document["links"][0]["on"] == "mission_accepted"
    assert document["links"][0]["selector"] == "accepted_snapshot"
    source, consumer = document["missions"]
    assert source["program"]["verifier"]["independent"]
    assert source["environment"]["budget"]["usd"] != consumer["environment"]["budget"]["usd"]
    assert consumer["program"]["nodes"][0]["inputs"][0]["from"] == "source.report"


async def verify_linked(
    stack: Any,
    scope: str,
    runs: dict[str, str],
    script: Any,
    *,
    explicit_adoption: bool = False,
    expected_release_gate: str = "mission_accepted",
) -> None:
    from tests.fixtures.overnight_stagegraph_evidence import observed_report_parts

    from mission_control.adapters.postgres.context.transfer_plans import PostgresTransferPlanStore
    from mission_control.adapters.postgres.knowledge.output_contracts import (
        PostgresOutputContractStore,
    )
    from mission_control.adapters.postgres.run_control import canonical as mc
    from mission_control.domain.context.transfer import SealedTransferPlan

    store = PostgresOutputContractStore(stack.worker_pool)
    source = await store.accepted_outputs(scope, runs["source"])
    report = next(item for item in source if item.obligation_key == "root.report")
    assert report.candidate["ref"] == script.source.registered[1]["handle"]
    assert report.content_digest == script.source.registered[1]["digest"]
    received, gaps = observed_report_parts(script.consumer.reads, source, scope.rsplit("/", 1)[-1])
    assert received and not gaps, gaps
    consumer = await store.accepted_outputs(scope, runs["consumer"])
    comparison = next(item for item in consumer if item.obligation_key == "consume.comparison")
    assert isinstance(comparison.candidate["text"], str)
    assert comparison.candidate["text"] in script.summaries
    assert str(report.candidate["ref"]) in comparison.candidate["text"]
    assert report.content_digest in comparison.candidate["text"]
    if not explicit_adoption:
        assert not any(item.candidate.get("ref") == report.candidate["ref"] for item in consumer), (
            "delivery is not implicit adoption into a receiving output"
        )
    async with stack.worker_pool.acquire() as connection, connection.transaction():
        args = await mc.begin(connection, scope)
        rows = await connection.fetch(
            "SELECT plan FROM mission_control.transfer_plan WHERE installation_id=$1 "
            "AND application_id=$2 AND tenant_id=$3 AND run_id=$4::uuid "
            "AND receiver_position='consume'",
            *args,
            runs["consumer"],
        )
    assert len(rows) == 1
    plan = SealedTransferPlan.model_validate(mc.load(rows[0]["plan"]))
    assert plan.boundary.value == "linked_mission"
    manifests = [member for member in plan.exact_sources if member.part == "manifest"]
    assert len(manifests) == 1
    member = manifests[0]
    assert member.source_kind == "linked_export" and member.admission == "accepted"
    assert member.access_ref == f"{report.candidate['ref']}#digest={report.content_digest}"
    assert member.linked_source is not None
    assert member.linked_source.source_run_id == runs["source"]
    assert member.linked_source.output_revision_id == report.revision_id
    assert member.linked_source.output_digest == report.content_digest
    from mission_control.adapters.postgres.chains.exports import PostgresLinkedExports

    export = await PostgresLinkedExports(stack.worker_pool).get_export(
        scope, member.linked_source.export_id
    )
    assert export is not None and export.digest == member.linked_source.export_digest
    assert export.release_gate == expected_release_gate and export.admission == "accepted"
    assert export.source_run_id == runs["source"] and export.receiver_run_id == runs["consumer"]
    assert [(item.revision_id, item.content_digest) for item in export.outputs] == [
        (report.revision_id, report.content_digest)
    ]
    receipts = await PostgresTransferPlanStore(stack.worker_pool).receipts(scope, plan.plan_id)
    assert receipts and all(receipt.result == "ready" for receipt in receipts)
    for name, keys in (
        ("source", {"root.report", "root.progress_note"}),
        ("consumer", {"consume.comparison"}),
    ):
        obligations = await store.active_obligations(scope, runs[name])
        assert keys <= {item.key for item in obligations}
        for obligation in obligations:
            if obligation.key in keys:
                decision = await store.latest_fulfillment(
                    scope, runs[name], obligation.key, obligation.revision
                )
                assert decision is not None and decision[1].disposition == "fulfilled"
    from tests.acceptance.mission_control.test_overnight_goal_directed import goal_records

    source_result = await goal_records(stack, scope, runs["source"])
    assert source_result["result"] is not None
    details = source_result["result"]["family_result"]
    assert details["goal_iterations"] == 1 and details["final_verifier_action"] == "accepted"
    assert {read["iteration"] for read in script.source.reads} == {1}


async def review_linked(
    stack: Any,
    scope: str,
    run_id: str,
    *,
    service: Any,
    actor: Any,
    records: list[dict[str, Any]],
) -> None:
    from tests.acceptance.mission_control.test_overnight_goal_directed import goal_records

    from mission_control.adapters.postgres.knowledge.output_contracts import (
        PostgresOutputContractStore,
    )
    from mission_control.domain.programs.human_gate import HumanResolutionRequest, packet_item

    for task in await service.list(actor, run_id=run_id, lifecycle="open"):
        assert hasattr(task, "activation") and task.activation.packet
        accepted = {
            item.obligation_key: item
            for item in await PostgresOutputContractStore(stack.worker_pool).accepted_outputs(
                scope, run_id
            )
        }
        for item in task.activation.packet:
            if item.source == "goal.verification":
                retained = await goal_records(stack, scope, run_id)
                matches = [
                    row["payload"]["verification"]
                    for row in retained["documents"]
                    if row["contract"] == "goal.verification/1"
                    and row["payload"]["verification"]["verification_ref"] == item.ref
                ]
                assert len(matches) == 1 and matches[0]["decision"] == "accepted"
                assert item == packet_item(item.source, item.ref)
            else:
                output = accepted[item.source]
                assert (
                    item.ref
                    == f"output-revision:{output.revision_id}#digest={output.content_digest}"
                )
                assert item.digest == output.content_digest
        resolution = await service.resolve(
            task.human_task_id,
            HumanResolutionRequest(
                request_id=f"overnight-linked:{task.human_task_id}",
                expected_task_version=task.version,
                decision="approve",
                reviewed_packet_digest=task.activation.packet_digest,
                comment="Scripted exact identity/digest approval; semantic human review unproved.",
            ),
            actor,
        )
        records.append(
            {
                "run_id": run_id,
                "semantic_human_review": False,
                "packet": [item.model_dump(mode="json") for item in task.activation.packet],
                "observed_outputs": [
                    output.model_dump(mode="json") for output in accepted.values()
                ],
                "task": resolution.task.public(),
            }
        )


async def _run_linked_case(tmp_path: Any, monkeypatch: Any, scenario: str) -> None:
    import asyncio
    import os
    import subprocess
    from datetime import UTC, datetime
    from pathlib import Path
    from uuid import uuid4

    from tests.acceptance.mission_control.test_overnight_goal_directed import goal_launch_bindings
    from tests.acceptance.mission_control.test_overnight_stagegraph import (
        ROOT,
        production_lifecycle,
    )
    from tests.fixtures.knowledge_binding import model_content
    from tests.fixtures.manifest_runtime import AUTHOR
    from tests.fixtures.mission_control_common_db import canonical_scope
    from tests.fixtures.mission_control_production_stack import open_postgres_production_stack
    from tests.fixtures.overnight_linked_evidence import export_linked
    from tests.fixtures.overnight_linked_model import linked_components, linked_script
    from tests.fixtures.overnight_linked_probes import LinkedProbe
    from tests.fixtures.overnight_trusted import install_scripted_trusted
    from tests.fixtures.rrm009_production_stack import technical_binding
    from tests.integration.deep_agents.test_report_source_real_service import command, response
    from tests.integration.temporal.test_manifest_launch_production import host_pins

    from mission_control.adapters.postgres.chains.exports import PostgresChainStartGate
    from mission_control.adapters.postgres.chains.store import (
        HOOK_NAME,
        ChainReleaseHook,
        PostgresChainIntentStore,
        PostgresChainReader,
    )
    from mission_control.adapters.postgres.human_tasks.repository import PostgresHumanTaskRepository
    from mission_control.adapters.postgres.run_control.canonical import register_post_append_hook
    from mission_control.adapters.temporal.human_gate_wake import TemporalHumanGateWake
    from mission_control.application.authoring.manifest_launch_inputs import (
        ManifestChainLaunchInputs,
    )
    from mission_control.application.authoring.manifest_submit import SubmitRequest
    from mission_control.application.chains.relay import ChainIntentRelay, LaunchServiceChainStarter
    from mission_control.application.human_tasks.service import HumanTaskService
    from mission_control.application.knowledge.access import instant
    from mission_control.bootstrap.composition import compose_knowledge_lane
    from mission_control.bootstrap.settings import get_settings
    from mission_control.bootstrap.technical_api import api
    from mission_control.contracts.identities import mission_root_id
    from mission_control.contracts.knowledge_protocol import Origin
    from mission_control.domain.policies.contracts import ActorContext

    application_name = "biotech" if scenario == "biotech" else "ai-engineer"
    monkeypatch.setenv("MISSION_CONTROL_APPLICATION", application_name)
    get_settings.cache_clear()
    scope = canonical_scope(application_id=application_name)
    _, installation, application, tenant = scope.split("/")
    destination = (
        Path(os.environ.get("MISSION_CONTROL_OVERNIGHT_EVIDENCE", str(tmp_path)))
        / "linked"
        / os.environ.get("MISSION_CONTROL_FIXTURE_ATTEMPT", "run-1")
    )
    if scenario != "positive":
        destination /= scenario
    destination.mkdir(parents=True, exist_ok=True)
    probe = LinkedProbe(scenario if scenario in {"gate", "duplicate", "restart"} else "positive")
    cancellation: Any = None
    if scenario.startswith("cancel-"):
        from tests.fixtures.overnight_linked_cancellation import LinkedCancellationProbe

        cancellation = LinkedCancellationProbe(mode=scenario.removeprefix("cancel-"))
    repair: Any = None
    if scenario == "held-repair":
        from tests.fixtures.overnight_linked_repair_probe import LinkedRepairProbe

        repair = LinkedRepairProbe()
    revocation: Any = None
    adoption: Any = None
    if scenario == "revocation":
        from tests.fixtures.overnight_linked_revocation import LinkedSourceRevocation

        revocation = LinkedSourceRevocation()
    if scenario == "adoption":
        from tests.fixtures.overnight_linked_adoption import LinkedAdoptionProbe

        adoption = LinkedAdoptionProbe()
    outcome: dict[str, Any] = {"result": "failed-before-admission", "qualified": False}
    (destination / "README.md").write_text(
        "Local linked engineering fixture: real PostgreSQL/Temporal/KS, scripted cognition; "
        "Qualification unrun. Startup pending; sibling pytest log preserves setup errors.\n",
        encoding="utf-8",
    )
    key = tmp_path / "knowledge-private.jwk.json"
    configuration = tmp_path / "knowledge-host.json"
    origin = Origin(
        kind="standalone",
        installationId=installation,
        applicationId=application,
        tenantId=tenant,
        issuer="mission-control",
        subject="mission-control-runtime",
        mission=None,
        recoveryAuthorityRef=None,
        invocationId="overnight-linked-startup",
        authenticatedAt=instant(datetime.now(UTC)),
    )
    configuration.write_text(
        json.dumps({"origin": origin.model_dump(mode="json"), "keyPath": str(key)}),
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["KS_AIENG_DB_ADMIN_DSN"] = environment["MISSION_CONTROL_TEST_ADMIN_DSN"]
    host_log = (destination / "knowledge-host.log").open("wb")
    process = await asyncio.to_thread(
        subprocess.Popen,
        [
            "node",
            "--import",
            "tsx",
            "src/knowledge-operation/tests/report-source-fixture-host.ts",
            str(configuration),
        ],
        cwd=ROOT.parent / "knowledge-services/apps/verification-executor",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=host_log,
        env=environment,
    )
    try:
        ready = await response(process)
        assert ready["ready"], ready
        report = model_content(ready["reports"][-1])
        script = linked_script(report)
        technical = technical_binding()
        models: Any = None
        biotech_profile: Any = None
        if scenario == "biotech":
            from tests.fixtures.overnight_linked_biotech import (
                biotech_model_profile,
                biotech_technical_binding,
                validate_biotech_ready,
            )

            from mission_control.application.resolution.registries import ModelCatalog

            validate_biotech_ready(ready, tenant=tenant)
            biotech_profile = biotech_model_profile()
            technical = biotech_technical_binding(technical, biotech_profile)
            models = ModelCatalog((biotech_profile,))
        model_log: list[dict[str, Any]] = []
        if repair is not None:
            from tests.fixtures.overnight_linked_repair_model import (
                linked_repair_components,
                linked_repair_script,
            )

            script = linked_repair_script(
                model_content(ready["reports"][0]),
                report,
                feedback="The first candidate claims 9B, but captured evidence states 7B. "
                "Repair the report to the captured parameter count and cite the exact fragment.",
            )
            components = linked_repair_components(technical, script, model_log)
        elif scenario == "biotech":
            from tests.fixtures.overnight_linked_biotech import biotech_components

            components = biotech_components(technical, script, model_log, tenant)
        else:
            components = linked_components(technical, script, model_log)
        bindings_path = tmp_path / "manifest-launch-bindings.json"
        launch_bindings = goal_launch_bindings(technical)
        if biotech_profile is not None:
            from tests.fixtures.models import model_binding

            launch_bindings = launch_bindings.model_copy(
                update={
                    "model_profiles": {
                        biotech_profile.profile: model_binding(technical.binding.model)
                    }
                }
            )
        bindings_path.write_text(launch_bindings.model_dump_json(indent=2), encoding="utf-8")
        holder: dict[str, Any] = {}

        async def lane(settings: Any, pool: Any) -> Any:
            settings.knowledge_binding_url = ready["url"]
            settings.knowledge_binding_audience = ready["audience"]
            settings.knowledge_issuer = ready["issuer"]
            settings.knowledge_issuer_key_file = key
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
            if scenario == "biotech":
                from tests.fixtures.overnight_linked_biotech import BiotechDecisionCapture

                capture = BiotechDecisionCapture(
                    destination / "06-evidence/native-decision-resolutions.json"
                )
                capture.install(composed, monkeypatch)
                holder["decision_capture"] = capture
            probe.install(composed)
            if cancellation is not None:
                cancellation.install(composed, monkeypatch, script)
            if adoption is not None:
                adoption.install(monkeypatch, composed, pool)
            holder["lane"] = composed
            return composed

        capability_pins_path = host_pins(tmp_path / "capability-pins.json")
        if biotech_profile is not None:
            from tests.fixtures.overnight_linked_biotech import biotech_host_pins

            capability_pins_path = biotech_host_pins(capability_pins_path, biotech_profile)

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
                "CAPABILITY_PINS_PATH": str(capability_pins_path),
                # Actual Anthropic profile still uses the ordinary broker; cognition is scripted.
                **(
                    {"ANTHROPIC_API_KEY": "deterministic-local-model-no-provider-access"}
                    if scenario == "biotech"
                    else {}
                ),
            },
        ) as stack:
            unregister = register_post_append_hook(HOOK_NAME, ChainReleaseHook())
            lifecycle = await production_lifecycle(stack, components, models=models)
            if revocation is not None:
                revocation.install(monkeypatch, process, stack.worker_pool)
            runs: dict[str, str] = {}
            chain_id: Any = None
            records: list[dict[str, Any]] = []
            relay_reports: list[Any] = []
            timeline: list[dict[str, Any]] = []
            try:
                pack = {
                    "reportId": report["report"]["reportId"],
                    "task": report["task"],
                    "fragments": report["fragments"],
                }
                authored = linked_manifest(pack, scenario=scenario)
                if scenario == "biotech":
                    from tests.fixtures.overnight_linked_biotech import biotech_linked_manifest

                    authored = biotech_linked_manifest(authored, ready, tenant=tenant)
                (destination / "01-authored-mission.yml").write_text(authored, encoding="utf-8")
                receipt, replayed = await lifecycle.submit(
                    SubmitRequest(
                        manifest_yaml=authored,
                        request_id=uuid4(),
                        actor=AUTHOR,
                        sponsorship_refs=frozenset({"sponsorship:test"}),
                    )
                )
                assert not replayed and receipt.chain_id is not None
                chain_id = receipt.chain_id
                (destination / "06-evidence").mkdir(exist_ok=True)
                (destination / "06-evidence/admission.json").write_text(
                    receipt.model_dump_json(indent=2), encoding="utf-8"
                )
                source = next(
                    mission for mission in receipt.missions if mission.mission_key == "source"
                )
                assert source.run_id is not None
                runs["source"] = source.run_id
                script.source_run = source.run_id
                inspection = await PostgresChainReader(stack.worker_pool).inspect(scope, chain_id)
                assert inspection is not None
                assert (
                    next(
                        member for member in inspection.members if member.mission_key == "consumer"
                    ).run_key
                    is None
                )
                projection = await api.state.run_control_service.get_run(scope, source.run_id)
                effective = await stack.control_plane.retrieve_for_admission(
                    projection.effective_configuration_digest
                )
                script.source.output_contract_ref = sorted(
                    effective.workflow_type.output_contracts
                )[0]
                script.source.obligation_refs = tuple(sorted(projection.required_obligation_refs))
                relay = ChainIntentRelay(
                    store=probe.store(PostgresChainIntentStore(stack.worker_pool)),
                    starter=probe.starter(
                        LaunchServiceChainStarter(
                            inputs=ManifestChainLaunchInputs(lifecycle._launch_inputs),
                            launches=api.state.run_launch_service,
                            start_gate=PostgresChainStartGate(stack.worker_pool),
                        ),
                        stack,
                    ),
                    lease_seconds=1 if scenario == "duplicate" else 60,
                    canceller=None if cancellation is None else cancellation.canceller(stack),
                    lease_owner="overnight-linked",
                    base_backoff_seconds=0.25,
                )
                reviews = HumanTaskService(
                    PostgresHumanTaskRepository(stack.worker_pool),
                    request_scope=scope,
                    wake=TemporalHumanGateWake(stack.client),
                )
                reviewer = ActorContext(actor_id="owner")
                await lifecycle.start(source.run_id, AUTHOR)
                outcome["result"] = "running"
                async with asyncio.timeout(240):
                    while True:
                        inspection = await PostgresChainReader(stack.worker_pool).inspect(
                            scope, chain_id
                        )
                        assert inspection is not None
                        for member in inspection.members:
                            if member.run_key is not None:
                                runs[member.mission_key] = member.run_key
                                if member.mission_key == "consumer":
                                    script.consumer_run = member.run_key
                        if (
                            scenario
                            in {"positive", "biotech", "gate", "duplicate", "restart", "adoption"}
                            and "consumer" not in runs
                        ):
                            failed_source = next(
                                (
                                    member
                                    for member in inspection.members
                                    if member.mission_key == "source"
                                    and member.phase == "terminal"
                                    and member.terminal_outcome in {"failed", "cancelled"}
                                ),
                                None,
                            )
                            if failed_source is not None:
                                outcome["source_failed_before_consumer_admission"] = (
                                    failed_source.model_dump(mode="json")
                                )
                                raise AssertionError(
                                    "Source terminated before its acceptance gate "
                                    "could admit a consumer: "
                                    + json.dumps(
                                        failed_source.model_dump(mode="json"), sort_keys=True
                                    )
                                )
                        await probe.progress(stack, scope, runs, script)
                        if cancellation is not None:
                            await cancellation.progress(stack, scope, runs, script)
                        for run_id in tuple(runs.values()):
                            if not await probe.allow_review(
                                stack,
                                scope,
                                run_id,
                                source_run=runs["source"],
                                chain=inspection,
                                service=reviews,
                                actor=reviewer,
                            ):
                                continue
                            if cancellation is not None and not await cancellation.allow_review(
                                stack,
                                scope,
                                run_id,
                                source_run=runs["source"],
                                chain=inspection,
                                service=reviews,
                                actor=reviewer,
                            ):
                                continue
                            await review_linked(
                                stack,
                                scope,
                                run_id,
                                service=reviews,
                                actor=reviewer,
                                records=records,
                            )
                        relayed = await (cancellation or probe).relay_once(
                            relay, scope, now=datetime.now(UTC)
                        )
                        if relayed.delivered or relayed.failed or relayed.dead:
                            relay_reports.append(relayed)
                        snapshot = {
                            "at": instant(datetime.now(UTC)),
                            "members": [
                                member.model_dump(mode="json") for member in inspection.members
                            ],
                            "chain": inspection.chain.lifecycle.value,
                        }
                        if not timeline or snapshot["members"] != timeline[-1]["members"]:
                            timeline.append(snapshot)
                        if (
                            set(runs) == {"source", "consumer"}
                            and all(member.phase == "terminal" for member in inspection.members)
                            and (scenario != "duplicate" or len(probe.starts) == 2)
                        ):
                            expected = {
                                "source": (
                                    "cancelled"
                                    if cancellation is not None
                                    else "failed"
                                    if repair is not None
                                    else "completed"
                                ),
                                "consumer": (
                                    "cancelled"
                                    if cancellation is not None and cancellation.mode != "continue"
                                    else "failed"
                                    if revocation is not None
                                    else "completed"
                                ),
                            }
                            assert all(
                                member.terminal_outcome == expected[member.mission_key]
                                for member in inspection.members
                            ), inspection
                            break
                        await asyncio.sleep(0.25)
                    for name, run_id in runs.items():
                        if (
                            cancellation is not None
                            and cancellation.mode == "pending"
                            and name == "consumer"
                        ):
                            never_started = await api.state.run_control_service.get_run(
                                scope, run_id
                            )
                            assert never_started.terminal_outcome == "cancelled"
                            assert never_started.execution_target is None
                            continue
                        root = stack.client.get_workflow_handle(mission_root_id(scope, run_id))
                        assert (await root.describe()).workflow_type == "mc.mission_run.v1"
                        await root.result()
                final_chain = await PostgresChainReader(stack.worker_pool).inspect(scope, chain_id)
                assert final_chain is not None
                assert final_chain.chain.lifecycle.value == "completed"
                assert final_chain.chain.terminal_outcome is not None
                assert final_chain.chain.terminal_outcome.value == (
                    "cancelled"
                    if cancellation is not None
                    else "execution_failed"
                    if revocation is not None or repair is not None
                    else "accepted"
                )
                if cancellation is None:
                    assert not any(report.failed or report.dead for report in relay_reports), (
                        relay_reports
                    )
                    assert len([key for report in relay_reports for key in report.delivered]) == 1
                if cancellation is not None:
                    await cancellation.verify(stack, scope, runs, script)
                    if cancellation.mode == "continue":
                        await verify_linked(
                            stack, scope, runs, script, expected_release_gate="goal_accepted"
                        )
                        assert {record["run_id"] for record in records} == set(runs.values())
                    else:
                        assert {record["run_id"] for record in records} == {runs["source"]}
                elif repair is not None:
                    await repair.verify(stack, scope, runs, script, holder["lane"])
                    assert {record["run_id"] for record in records} == {runs["consumer"]}
                elif revocation is not None:
                    revocation.verify(script)
                    assert not [row for row in stack.model_log if row["run_id"] == runs["consumer"]]
                    from mission_control.adapters.postgres.knowledge.output_contracts import (
                        PostgresOutputContractStore,
                    )

                    assert not await PostgresOutputContractStore(
                        stack.worker_pool
                    ).accepted_outputs(scope, runs["consumer"])
                    assert {record["run_id"] for record in records} == {runs["source"]}
                else:
                    await verify_linked(
                        stack, scope, runs, script, explicit_adoption=adoption is not None
                    )
                    if adoption is not None:
                        await adoption.verify(stack, scope, runs, holder["lane"])
                    assert {record["run_id"] for record in records} == set(runs.values())
                if scenario == "biotech":
                    from tests.fixtures.overnight_linked_biotech import verify_biotech

                    biotech_proof = await verify_biotech(
                        stack, scope, runs, script, holder["lane"], technical, biotech_profile
                    )
                    (destination / "06-evidence/biotech.json").write_text(
                        json.dumps(biotech_proof, indent=2, default=str), encoding="utf-8"
                    )
                await probe.verify(stack, scope, runs, script)
                outcome["result"] = "passed-engineering-fixture"
            except BaseException as error:
                outcome["result"] = "timed_out" if isinstance(error, TimeoutError) else "failed"
                outcome["error"] = {"type": type(error).__name__, "message": str(error)}
                raise
            finally:
                try:
                    if chain_id is not None:
                        if cancellation is not None:
                            (destination / "06-evidence/cancellation.json").write_text(
                                json.dumps(cancellation.evidence(), indent=2, default=str),
                                encoding="utf-8",
                            )
                        if revocation is not None:
                            (destination / "06-evidence/revocation.json").write_text(
                                json.dumps(revocation.proof, indent=2, default=str),
                                encoding="utf-8",
                            )
                        if repair is not None:
                            (destination / "06-evidence/repair.json").write_text(
                                json.dumps(repair.evidence(), indent=2, default=str),
                                encoding="utf-8",
                            )
                        if adoption is not None:
                            (destination / "06-evidence/adoption.json").write_text(
                                json.dumps(adoption.proof, indent=2, default=str), encoding="utf-8"
                            )
                        (destination / "06-evidence/probe.json").write_text(
                            json.dumps(probe.evidence(), indent=2, default=str), encoding="utf-8"
                        )
                        if scenario == "biotech" and script.source.registered:
                            from mission_control.contracts.knowledge_protocol import Ref

                            native = []
                            for exact in script.source.registered.values():
                                handle = exact["handle"].split("/report/", 1)[1]
                                report_id, version = handle.rsplit("@", 1)
                                ref = Ref(
                                    kind="report",
                                    id=report_id,
                                    version=version,
                                    binding=ready["binding"],
                                    tenant=tenant,
                                    digest=exact["digest"],
                                )
                                native.append(
                                    await command(
                                        process,
                                        {
                                            "action": "inspect",
                                            "report": ref.model_dump(mode="json"),
                                        },
                                    )
                                )
                            (destination / "06-evidence/native-report-contexts.json").write_text(
                                json.dumps(native, indent=2, default=str), encoding="utf-8"
                            )
                        gaps = await export_linked(
                            stack,
                            scope,
                            destination,
                            chain_id=chain_id,
                            runs=runs,
                            script=script,
                            lane=holder["lane"],
                            reviews=records,
                            relay_reports=relay_reports,
                            timeline=timeline,
                        )
                        outcome["missing_evidence"] = gaps
                        if outcome["result"] == "passed-engineering-fixture":
                            assert not gaps, gaps
                finally:
                    (destination / "07-validation.json").write_text(
                        json.dumps(outcome, indent=2, default=str), encoding="utf-8"
                    )
                    unregister()
    except BaseException as error:
        outcome["result"] = "timed_out" if isinstance(error, TimeoutError) else "failed"
        outcome["error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        (destination / "07-validation.json").write_text(
            json.dumps(outcome, indent=2, default=str), encoding="utf-8"
        )
        if process.poll() is None:
            if process.stdin is not None:
                process.stdin.close()
            try:
                await asyncio.to_thread(process.wait, 30)
            except subprocess.TimeoutExpired:
                process.terminate()
                await asyncio.to_thread(process.wait, 30)
        host_log.close()


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_ordinary_linked_accepted_report_reaches_independent_consumer(
    tmp_path: Any, monkeypatch: Any
) -> None:
    await _run_linked_case(tmp_path, monkeypatch, "positive")


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_linked_consumer_waits_for_source_human_acceptance(
    tmp_path: Any, monkeypatch: Any
) -> None:
    await _run_linked_case(tmp_path, monkeypatch, "gate")


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_linked_lost_ack_relay_redelivery_starts_one_consumer(
    tmp_path: Any, monkeypatch: Any
) -> None:
    await _run_linked_case(tmp_path, monkeypatch, "duplicate")


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_linked_saved_consumer_survives_worker_restart_without_duplicate_cognition(
    tmp_path: Any, monkeypatch: Any
) -> None:
    await _run_linked_case(tmp_path, monkeypatch, "restart")


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_linked_source_correction_after_seal_refuses_first_delivery(
    tmp_path: Any, monkeypatch: Any
) -> None:
    await _run_linked_case(tmp_path, monkeypatch, "revocation")


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_linked_explicit_adoption_is_a_draft_until_normal_trusted_settlement(
    tmp_path: Any, monkeypatch: Any
) -> None:
    await _run_linked_case(tmp_path, monkeypatch, "adoption")


def test_explicit_adoption_authors_a_separate_required_receiver_promise() -> None:
    from mission_control.domain.authoring.manifest import parse_manifest, resolve_environments

    document = load_manifest_yaml(
        linked_manifest({"reportId": "fixture", "fragments": []}, scenario="adoption")
    )
    assert not resolve_environments(parse_manifest(document), document).blockers
    source, consumer = document["missions"]
    consume, review = consumer["program"]["nodes"]
    report = next(output for output in consume["outputs"] if output["name"] == "adopted_report")
    original = next(output for output in source["program"]["outputs"] if output["name"] == "report")
    assert {**report, "name": "report"} == original
    assert report["enforcement"] == "required" and report["form"] == "reference"
    assert "consume.adopted_report" in review["task"]["packet"]


@pytest.mark.asyncio
@pytest.mark.common_db
@pytest.mark.parametrize("mode", ["pending", "continue", "propagate"])
async def test_linked_governed_source_cancellation_respects_independent_consumer_policy(
    tmp_path: Any, monkeypatch: Any, mode: str
) -> None:
    await _run_linked_case(tmp_path, monkeypatch, "cancel-" + mode)


def test_cancellation_authoring_preserves_default_and_explicit_policies() -> None:
    from mission_control.domain.authoring.manifest import parse_manifest, resolve_environments

    for mode in ("pending", "continue", "propagate"):
        document = load_manifest_yaml(
            linked_manifest({"reportId": "fixture", "fragments": []}, scenario="cancel-" + mode)
        )
        assert not resolve_environments(parse_manifest(document), document).blockers
        (link,) = document["links"]
        assert link["on"] == {"goal_accepted": {"goal_key": "model_facts_report"}}
        assert link["on_upstream_cancel"] == (
            "cancel_downstream" if mode == "propagate" else "continue"
        )


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_linked_held_report_repair_preserves_findings_and_requires_own_acceptance(
    tmp_path: Any, monkeypatch: Any
) -> None:
    await _run_linked_case(tmp_path, monkeypatch, "held-repair")


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_biotech_report_only_linked_transfer_uses_actual_application_catalog(
    tmp_path: Any, monkeypatch: Any
) -> None:
    await _run_linked_case(tmp_path, monkeypatch, "biotech")
