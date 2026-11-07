"""Joined MC tools -> real KS HTTP/PG -> exact dependent Deep Agents read.

Both services use disposable PostgreSQL. The test controller supplies scripted independent
judgments and promotion; this is not a Temporal mission or live evaluator qualification.
Transfer, checkpoint, submission and journal stores are PostgreSQL;
fixture payload custody is retained in memory.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.fixtures.checkpoint_lineage import bind_unit, stage_unit
from tests.fixtures.knowledge_binding import (
    InMemoryStaging,
    model_content,
)
from tests.fixtures.lane_bindings import lane_fields
from tests.fixtures.mission_control_common_db import create_common_database, drop_common_database
from tests.integration.deep_agents.report_source_replay import admit, consume_and_replay
from tests.integration.deep_agents.test_report_source_context import FullContextReader
from tests.integration.deep_agents.test_wi02_transfer_plan_lane import (
    _invocation,
    _selection,
)
from tests.unit.outputs.scenario import build_stack, obligation

from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION, knowledge_tools
from mission_control.adapters.knowledge.credentials import Ed25519CredentialMinter, load_signing_key
from mission_control.adapters.knowledge.http_client import (
    HttpExactContentReader,
    HttpKnowledgeBindingClient,
)
from mission_control.adapters.postgres.context.transfer_plans import PostgresTransferPlanStore
from mission_control.adapters.postgres.knowledge.handles import PostgresKnowledgeHandleStore
from mission_control.adapters.postgres.knowledge.invocation_locator import (
    PostgresInvocationLocator,
)
from mission_control.adapters.postgres.knowledge.operations import PostgresKnowledgeJournal
from mission_control.adapters.postgres.knowledge.output_contracts import PostgresOutputContractStore
from mission_control.application.context.materialization import (
    KnowledgeReadAccess,
    ProducedOutputResolver,
    TransferMaterializer,
)
from mission_control.application.context.resolution import ContentResolutionService
from mission_control.application.knowledge.gateway import KnowledgeGateway
from mission_control.application.knowledge.toolset import KnowledgeToolset, LiveInvocation
from mission_control.application.outputs.fulfillment import PromoteOutput
from mission_control.application.outputs.submission_service import (
    SelectedItem,
    SubmissionService,
    report_ref,
)
from mission_control.bootstrap.application_profiles import load_application_profile
from mission_control.domain.context import transfer_builders
from mission_control.domain.outputs.contracts import OutputForm

ROOT = Path(__file__).resolve().parents[3]
KS = ROOT.parent / "knowledge-services"
HOST = "src/knowledge-operation/tests/report-source-fixture-host.ts"


async def response(process):
    line = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 90)
    if not line:
        raise AssertionError(f"fixture host exited: {process.returncode}")
    return json.loads(line)


async def command(process, payload):
    process.stdin.write((json.dumps(payload) + "\n").encode())
    process.stdin.flush()
    return await response(process)


@pytest.mark.asyncio
@pytest.mark.common_db
@pytest.mark.parametrize("application", ["ai-engineer", "biotech"])
async def test_mc_registration_repair_real_service_and_exact_consumer(tmp_path, application):
    await _run_report_source_fixture(tmp_path, application)


@pytest.mark.asyncio
@pytest.mark.common_db
async def test_phase0_real_capture_custody_registration_submission(tmp_path):
    """Fail without real local storage; submission is deliberately not workflow qualification."""
    root = Path(os.environ.get("MISSION_CONTROL_PHASE0_EVIDENCE", str(tmp_path)))
    await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
    await _run_report_source_fixture(root, "ai-engineer", capture_mode=True)


async def _run_report_source_fixture(tmp_path, application, *, capture_mode=False):
    database = await create_common_database(application_id=application)
    pool = await database.pool()
    process = None
    client = None
    log = (tmp_path / "host.log").open("wb")
    try:

        def now():
            return datetime.now(UTC)

        invocation, binding, bundle = _invocation()
        control, run_id = await admit(pool, database.scope())
        binding = bind_unit(
            binding.model_copy(update={"run_id": run_id, "operation_id": "review"}),
            stage_unit(request_scope=database.scope(), run_id=run_id, operation_id="review"),
        )
        invocation = invocation.model_copy(
            update={
                "binding": invocation.binding.model_copy(
                    update={
                        "run_id": run_id,
                        "operation_id": "review",
                        "runtime_unit": binding.runtime_unit,
                        **lane_fields(binding),
                    }
                )
            }
        )
        live = LiveInvocation(
            request_scope=database.scope(),
            run_id=invocation.binding.run_id,
            operation_id="draft",
            operation_attempt=1,
            execution_generation=1,
            lane="deep_agents",
            position="draft",
            obligations=("draft.report",),
        )
        store = PostgresOutputContractStore(pool)
        # Access derives entirely from the host invocation, before any producer content exists.
        preliminary = KnowledgeToolset(
            gateway=None,
            submissions=SubmissionService(store),
            issuer="mission-control",
            clock=now,
            locator=PostgresInvocationLocator(pool),
        )
        # Provenance slice 1: the origin names the admitted run's ledger mission.
        live = await preliminary.locate(live)
        access = preliminary.access(live)
        key_path = tmp_path / "fixture.private.jwk.json"
        config = tmp_path / "host.json"
        config.write_text(
            json.dumps(
                {
                    "origin": access.wire_origin().model_dump(mode="json"),
                    "keyPath": str(key_path),
                    "captureMode": capture_mode,
                    "evidenceRoot": str(tmp_path / "06-evidence"),
                }
            ),
            encoding="utf-8",
        )
        env = dict(os.environ)
        env["KS_AIENG_DB_ADMIN_DSN"] = env["MISSION_CONTROL_TEST_ADMIN_DSN"]
        process = await asyncio.to_thread(
            subprocess.Popen,
            ["node", "--import", "tsx", HOST, str(config)],
            cwd=KS / "apps/verification-executor",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
            env=env,
        )
        ready = await response(process)
        assert ready["ready"]
        if capture_mode:
            assert ready["captureEvidence"]["reconstructed"]
            assert ready["captureEvidence"]["providerCalls"] == 1
            (tmp_path / "02-observed-service-config.json").write_text(
                json.dumps(
                    {key: value for key, value in ready.items() if key != "reports"}, indent=2
                ),
                encoding="utf-8",
            )
        client = HttpKnowledgeBindingClient(ready["url"])
        gateway = KnowledgeGateway(
            client=client,
            content=HttpExactContentReader(client),
            journal=PostgresKnowledgeJournal(pool),
            handles=PostgresKnowledgeHandleStore(pool),
            minter=Ed25519CredentialMinter(
                issuer=ready["issuer"], active=load_signing_key(key_path)
            ),
            knowledge=load_application_profile(ROOT / "deployments", application).profile.knowledge,
            audience=ready["audience"],
            clock=now,
        )
        stack = await build_stack(
            store, store, access, obligation("draft.report", OutputForm.REFERENCE), clock=now
        )
        toolset = replace(preliminary, gateway=gateway, submissions=stack.submissions)
        tools = knowledge_tools(toolset)
        if capture_mode:
            (tmp_path / "02-effective-run-config.json").write_text(
                json.dumps(
                    {
                        "source": "observed binding and Deep Agents tool schemas",
                        "origin": access.wire_origin().model_dump(mode="json"),
                        "provider_execution": "direct tools; no model or DeepAgent cognition",
                        "application": application,
                        "binding": ready["binding"],
                        "tools": {
                            name: tool.args_schema.model_json_schema()
                            for name, tool in tools.items()
                        },
                        "obligations": list(live.obligations),
                        "discovery_provider": "scripted Tavily; real source HTTP and custody",
                        "budgets": {
                            "observed_discovery_calls": 1,
                            "observed_captures": 2,
                            "paid_calls": 0,
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        async def call(name, args, key):
            token = CURRENT_INVOCATION.set(live)
            try:
                message = await tools[name].ainvoke(
                    {"name": name, "type": "tool_call", "id": key, "args": args}
                )
                result = json.loads(message.content)
                if capture_mode:
                    with (tmp_path / "04-tool-events.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(
                            json.dumps(
                                {
                                    "at": now().isoformat(),
                                    "id": key,
                                    "tool": name,
                                    "arguments": args,
                                    "result": result,
                                }
                            )
                            + "\n"
                        )
                assert result["ok"], result
                return result["result"]
            finally:
                CURRENT_INVOCATION.reset(token)

        prior = None
        prior_public = None
        for revision, payload in enumerate(ready["reports"], 1):
            payload["report"]["supersedes"] = prior_public
            registered = await call(
                "report_register", {"report": model_content(payload)}, f"register-{revision}"
            )
            item = next(item for item in registered["affected"] if "/report/" in item["handle"])
            prior_public = {"handle": item["handle"], "digest": item["digest"]}
            selected = {"kind": "handle", "ref": item["handle"], "digest": item["digest"]}
            exact = report_ref(
                SelectedItem.model_validate(selected), tenant=access.origin.tenant_id
            )
            assert exact is not None
            prior = exact.model_dump(mode="json")
            submitted = await call(
                "submit_output",
                {"obligation": "draft.report", "items": [selected]},
                f"submit-{revision}",
            )
            assert await store.accepted_outputs(access.scope, live.run_id) == ()
            if capture_mode:
                stored = await command(
                    process, {"action": "read", "report": prior, "revision": revision}
                )
                (tmp_path / f"stored-report-{revision}.json").write_text(
                    json.dumps(stored, indent=2), encoding="utf-8"
                )
                (tmp_path / f"registration-submission-{revision}.json").write_text(
                    json.dumps(
                        {"registered": registered, "submitted": submitted, "payload": payload},
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                # Phase 0 proves custody through submission; it never promotes accepted outputs.
                if revision == len(ready["reports"]):
                    return
                continue
            judged = await command(
                process, {"action": "assess", "report": prior, "revision": revision}
            )
            (tmp_path / f"assessment-{revision}.json").write_text(
                json.dumps(judged, indent=2), encoding="utf-8"
            )
            output = submitted["revisions"][0]
            if revision == 1:
                assert judged["state"] == "held" and not judged["admitted"]
                continue
            assert judged["admitted"] and judged["report"] == prior, judged
            # Explicit test-controller promotion only after the independently judged exact ref.
            promoted = await stack.outputs.promote_output(
                stack.host,
                PromoteOutput(
                    run_id=live.run_id,
                    revision_id=output["revision_id"],
                    expected_head=None,
                    generation=1,
                ),
            )
            assert promoted.status == "promoted"

        receiver_access = toolset.access(replace(live, operation_id="review", position="review"))

        class Receiver:
            def uses_knowledge(self, invocation):
                return False

            def applies(self, invocation):
                # Reader has no submissions or knowledge-tool settlement to perform.
                return False

            def scope_reads(self, plan):
                self.plan = plan

            async def access_for(self, invocation):
                return receiver_access

        reports = ContentResolutionService(gateway)
        staging = InMemoryStaging()
        transfers = PostgresTransferPlanStore(pool)

        def materializer():
            return TransferMaterializer(
                store=PostgresTransferPlanStore(pool),
                staging=staging,
                custody=staging,
                resolvers={"produced_output": ProducedOutputResolver(store, reports=reports)},
                access={"produced_output": KnowledgeReadAccess(reports)},
            )

        selection = transfer_builders.dependent_stage(
            transfer_builders.first_invocation("review", _selection().bounds, _selection().backend),
            [("draft", "draft", "draft.report")],
        )
        invocation = invocation.model_copy(
            update={
                "binding": invocation.binding.model_copy(
                    update={
                        "request_scope": database.scope(),
                        "transfer": selection,
                    }
                )
            }
        )
        FullContextReader.expected = judged["body"].encode()
        FullContextReader.observed = {}
        FullContextReader.file_path = f"/inputs/draft/{exact.id}_{exact.version}/body.md"
        receiver = Receiver()
        result = await consume_and_replay(
            database,
            pool,
            control,
            binding,
            bundle,
            materializer,
            receiver,
            selection,
        )
        assert result.output_text == "entire context read"
        received = (
            "\n".join(FullContextReader.observed[i] for i in sorted(FullContextReader.observed))
            + "\n"
        )
        assert received == judged["body"]
        plan = await transfers.get(database.scope(), receiver.plan.plan_id)
        assert plan is not None
        body = next(item for item in plan.exact_sources if item.part == "body")
        assert body.digest == judged["bodyDigest"]
        assert body.source_ref == output["revision_id"]
        (receipt,) = await transfers.receipts(plan.receiver.scope, plan.plan_id)
        assert receipt.result == "ready" and receipt.realized_backend == "deep_agents:state"
    finally:
        if client is not None:
            await client.aclose()
        if process is not None and process.poll() is None:
            process.stdin.close()
            try:
                await asyncio.to_thread(process.wait, timeout=30)
            except subprocess.TimeoutExpired:
                process.terminate()
                await asyncio.to_thread(process.wait, timeout=10)
        log.close()
        await pool.close()
        await drop_common_database(database)
