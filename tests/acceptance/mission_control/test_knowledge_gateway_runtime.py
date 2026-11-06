"""T1-MC (Sprint V SV-16): the knowledge gateway through actual local Temporal and PostgreSQL.

The signed scoped stack (`tests/fixtures/scoped_api_stack.py`): a fresh common database with
the newest built release (1.6.0), a local Temporal dev server, the production workers and the
configured API, serving `KNOWLEDGE_TEST_APPLICATION` (default `ai-engineer`). The worker
composes the knowledge lane through the real bootstrap (`compose_knowledge_lane`: settings,
Ed25519 key files, `describe` preflight, journal, durable handles, lineage, submissions,
tools) and talks K01 over real loopback HTTP; the API composes the run-level stop
(`compose_knowledge_stop`). The Deep Agents node of every StageGraph stage and GoalDirected role
is the deterministic technical agent: it calls `report_register`, then `submit_output` with the
exact report handle the receipt named; node completion starts the independent `report.assess`.

Binding: the verifying fake served over loopback HTTP, unless `KNOWLEDGE_BINDING_URL`,
`KNOWLEDGE_ISSUER`, `KNOWLEDGE_ISSUER_KEY_FILE` and `KNOWLEDGE_BINDING_AUDIENCE` are set (plus
`MISSION_CONTROL_TECHNICAL_KNOWLEDGE_TEMPLATE`, a `research-report/v2` registration whose tenant
is substituted with the stack's): then the same runs go to that executor. Fake-only checks
(scripted review, receipt attribution through the fake's call log) are skipped against a real
executor. No model provider is called.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
import uvicorn
from tests.fixtures.knowledge_binding import (
    FakeKnowledgeBinding,
    knowledge_http_app,
    real_binding_configured,
)
from tests.fixtures.scoped_api_stack import ScopedStack, inspect, prepare_run, scoped_stack, until

from mission_control.adapters.deep_agents.knowledge_tools import (
    knowledge_tool_components,
    knowledge_tools,
)
from mission_control.adapters.knowledge.credentials import (
    CredentialVerifier,
    generate_signing_key,
    publish_jwks,
    write_private_jwk,
)
from mission_control.bootstrap.application_profiles import load_application_profile
from mission_control.bootstrap.composition import compose_knowledge_lane
from mission_control.domain.resolution.resolved import KnowledgePortBinding

pytestmark = pytest.mark.common_db
EVIDENCE = Path(__file__).resolve().parents[3] / ".scratch" / "sprint-v" / "proofs" / "SV-16"
DEPLOYMENTS = Path(__file__).resolve().parents[3] / "deployments"


def knowledge_port_for(application: str) -> KnowledgePortBinding:
    return load_application_profile(DEPLOYMENTS, application).profile.knowledge


VERDICTS = {"assessed", "held", "rejected"}


def _write(name: str, payload: dict[str, Any]) -> None:
    path = EVIDENCE / "E-MC-t1" / name / "evidence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


async def _rows(stack: ScopedStack, query: str, *args: Any) -> list[dict[str, Any]]:
    async with stack.owner_pool.acquire() as connection:
        return [dict(row) for row in await connection.fetch(query, *args)]


def _base(stack: ScopedStack) -> str:
    return f"/v1/applications/{stack.application_id}/runs"


async def _launch(stack: ScopedStack, family: str) -> str:
    run_id, body = await prepare_run(stack, family)
    launched = await stack.http.post(f"{_base(stack)}/{run_id}/launch", json=body)
    assert launched.status_code == 202, launched.text
    return run_id


async def _completed(stack: ScopedStack, run_id: str) -> bool:
    state = await inspect(stack, run_id)
    blocked = await _rows(
        stack,
        "SELECT failure_code, settlement_payload::text AS message "
        "FROM mission_control.operation_settlement WHERE status = 'failed'",
    )
    assert state["lifecycle"] not in {"failed", "cancelled"}, (state, blocked)
    assert not [row for row in blocked if row["failure_code"] == "context_delivery_blocked"], (
        blocked
    )
    return state["lifecycle"] == "completed"


async def _at_wait(stack: ScopedStack, run_id: str) -> bool:
    state = await inspect(stack, run_id)
    assert state["lifecycle"] != "completed", state
    return bool(state["projection"]["active_waits"])


async def _satisfy_wait(stack: ScopedStack, run_id: str) -> None:
    state = await inspect(stack, run_id)
    wait = state["projection"]["active_waits"][0]
    body = {
        "request_id": str(uuid4()),
        "expected_version": state["version"],
        "expected_generation": state["execution_generation"],
        "target": {"kind": "run", "id": run_id},
        "kind": "satisfy_wait",
        "payload": {
            "condition_id": wait["condition_id"],
            "verification_evidence_ref": f"evidence:knowledge-t1:{run_id}",
            "runnable_work_remains": True,
        },
        "reason": "SV-16 T1: release the declared wait",
    }
    response = await stack.http.post(f"{_base(stack)}/{run_id}/commands", json=body)
    assert response.status_code == 202, response.text


async def _cancel_immediately(stack: ScopedStack, run_id: str) -> dict[str, Any]:
    response = None
    for _attempt in range(12):
        state = await inspect(stack, run_id)
        body = {
            "request_id": str(uuid4()),
            "expected_version": state["version"],
            "expected_generation": state["execution_generation"],
            "target": {"kind": "run", "id": run_id},
            "kind": "cancel",
            "payload": {"urgency": "immediate"},
            "reason": "SV-16 T1: stop during review",
        }
        response = await stack.http.post(f"{_base(stack)}/{run_id}/commands", json=body)
        if response.status_code == 202:
            return body
        assert response.status_code == 409, response.text
    raise AssertionError(f"cancel never accepted: {response.text if response else ''}")


async def _serve(app: Any) -> tuple[uvicorn.Server, asyncio.Task[None], str]:
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="off", log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(30):
        while not server.started:
            if task.done():
                task.result()
            await asyncio.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, task, f"http://127.0.0.1:{port}"


@pytest.mark.asyncio
async def test_stage_graph_and_goal_directed_nodes_register_submit_and_assess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = os.environ.get("KNOWLEDGE_TEST_APPLICATION", "ai-engineer")
    # OC-R4: the binding is the application's profile (`deployments/<app>/application.toml`).
    binding = knowledge_port_for(application).binding_id
    real = real_binding_configured()
    fake: FakeKnowledgeBinding | None = None
    served: tuple[uvicorn.Server, asyncio.Task[None], str] | None = None
    if not real:
        active, retiring = generate_signing_key("mc-t1-k2"), generate_signing_key("mc-t1-k1")
        write_private_jwk(active, tmp_path / "issuer-active.jwk.json")
        write_private_jwk(retiring, tmp_path / "issuer-retiring.jwk.json")
        fake = FakeKnowledgeBinding(
            verifier=CredentialVerifier(
                issuer="mission-control",
                audience="ks-executor",
                jwks=publish_jwks(active, retiring),
            ),
            clock=lambda: datetime.now(UTC),
            binding=binding,
            application=application,
        )
        fake.operation_statuses["report.assess"] = deque(["succeeded"] * 500)
        fake.operation_statuses["knowledge.read"] = deque(["succeeded"] * 500)
        served = await _serve(knowledge_http_app(fake))
        for name, value in {
            "KNOWLEDGE_BINDING_URL": served[2],
            "KNOWLEDGE_BINDING_AUDIENCE": "ks-executor",
            "KNOWLEDGE_ISSUER": "mission-control",
            "KNOWLEDGE_ISSUER_KEY_FILE": str(tmp_path / "issuer-active.jwk.json"),
            "KNOWLEDGE_ISSUER_RETIRING_KEY_FILE": str(tmp_path / "issuer-retiring.jwk.json"),
        }.items():
            monkeypatch.setenv(name, value)
    monkeypatch.setenv("MISSION_CONTROL_TECHNICAL_KNOWLEDGE", "1")

    async def lane(settings: Any, pool: Any) -> Any:
        async with pool.acquire() as connection, connection.transaction(readonly=True):
            installation = await connection.fetchval(
                "SELECT installation_id::text FROM mission_control.application_installation "
                "WHERE state = 'active'"
            )
        return await compose_knowledge_lane(
            settings, pool, application_id=application, installation_id=installation
        )

    components = knowledge_tool_components(knowledge_tools(cast(Any, None)))
    try:
        async with scoped_stack(
            tmp_path,
            monkeypatch,
            knowledge_lane=lane,
            knowledge_tools=components,
            application_id=application,
        ) as stack:
            template = os.environ.get("MISSION_CONTROL_TECHNICAL_KNOWLEDGE_TEMPLATE")
            if template:
                tenant = stack.scope.rsplit("/", 1)[-1]
                document = json.loads(Path(template).read_text(encoding="utf-8"))  # noqa: ASYNC240
                text = json.dumps(document)
                for old in {item["tenant"] for item in document.get("fragments", [])}:
                    text = text.replace(old, tenant)
                text = text.replace('"aiengineer-postgres"', json.dumps(binding))
                payload = tmp_path / "registration-payload.json"
                payload.write_text(text, encoding="utf-8")
                monkeypatch.setenv("MISSION_CONTROL_TECHNICAL_KNOWLEDGE_PAYLOAD", str(payload))
            await _run_cases(stack, application, binding, real, fake)
    finally:
        if served is not None:
            served[0].should_exit = True
            await served[1]


async def _run_cases(
    stack: ScopedStack,
    application: str,
    binding: str,
    real: bool,
    fake: FakeKnowledgeBinding | None,
) -> None:
    assert stack.knowledge is not None
    receipt = stack.knowledge.startup_receipt
    assert receipt["binding"] == binding and receipt["descriptor_digest"]
    mode = "real" if real else "fake"

    stage_run = await _launch(stack, "StageGraph")
    await until(lambda: _at_wait(stack, stage_run), seconds=240)
    await _satisfy_wait(stack, stage_run)
    await until(lambda: _completed(stack, stage_run), seconds=240)
    goal_run = await _launch(stack, "GoalDirected")
    await until(lambda: _completed(stack, goal_run), seconds=300)

    for run_id, family in ((stage_run, "StageGraph"), (goal_run, "GoalDirected")):
        evidence = await _evidence(stack, run_id)
        evidence |= {
            "family": family,
            "binding": binding,
            "application": application,
            "mode": mode,
            "startup_receipt": receipt,
        }
        _write(f"{mode}-{application}-{family}-{run_id}", evidence)
        _assert_run(evidence, run_id, binding, real)
        _assert_no_run_wide_delivery(evidence, family)

    await _attribution(stack, mode, application, (stage_run, goal_run))

    # Run-level stop during review: the draft node completes with its assessment waiting for
    # review; an immediate cancel of the run (Stop Fence first) cancels that open handle
    # through the gateway, once, with the stop's request id. Against a real executor the
    # assessment waits only behind the disposable review gate (KNOWLEDGE_TEST_COMPONENT_DSN):
    # the executor itself has no product path into `waiting_review`.
    gate = os.environ.get("KNOWLEDGE_TEST_COMPONENT_DSN")
    tenant = stack.scope.rsplit("/", 1)[-1]
    if fake is not None:
        fake.operation_statuses["report.assess"] = deque(["waiting_review"] * 2000)
    elif gate:
        await _review_gate(gate, tenant, armed=True)
    else:
        return
    try:
        review_run = await _stop_during_review(stack, mode, application, fake)
    finally:
        if fake is None and gate:
            await _review_gate(gate, tenant, armed=False)
    if fake is None:
        return

    # Receipt attribution through the fake: every call carried its own single-use credential.
    invokes = [call for call in fake.calls_of("invoke") if call.envelope is not None]
    assert len({call.claims.jti for call in fake.calls}) == len(fake.calls)
    assert len({call.envelope.dispatchId for call in invokes}) == len(invokes)
    for receipt_doc in fake.committed.values():
        caller = receipt_doc.effect.currentCallerOrigin
        assert caller.mission is not None
        assert caller.mission.runId in {stage_run, goal_run, review_run}
        assert receipt_doc.effect.dispatchSequence == 1


async def _review_gate(dsn: str, tenant: str, *, armed: bool) -> None:
    import asyncpg

    connection = await asyncpg.connect(dsn)
    try:
        if armed:
            await connection.execute(
                "INSERT INTO public.emc_review_gate (tenant_id) VALUES ($1::uuid) "
                "ON CONFLICT DO NOTHING",
                tenant,
            )
        else:
            await connection.execute(
                "DELETE FROM public.emc_review_gate WHERE tenant_id = $1::uuid", tenant
            )
    finally:
        await connection.close()


async def _attribution(
    stack: ScopedStack, mode: str, application: str, runs: tuple[str, ...]
) -> None:
    """Over the wire: `receipt.get` finds every journalled effect; the receipt names the live
    attempt that dispatched it (originating origin, caller invocation), and the journal links
    that receipt to the invocation."""

    from mission_control.application.knowledge.access import RecoveryAccess
    from mission_control.contracts.identities import parse_request_scope
    from mission_control.contracts.knowledge_protocol import Origin
    from mission_control.contracts.knowledge_protocol_results import ReceiptFound

    assert stack.knowledge is not None
    scope = parse_request_scope(stack.scope)
    recovery = RecoveryAccess(
        installation_id=str(scope.installation_id),
        application_id=scope.application_id,
        tenant_id=str(scope.tenant_id),
        issuer="mission-control",
        subject="mission-control-runtime:auditor",
        authority_ref="audit:sv16-t1",
        invocation_id=f"inv-{uuid4()}",
        authenticated_at=datetime.now(UTC),
    )
    checked = []
    for run_id in runs:
        rows = await _rows(
            stack,
            "SELECT effect_key, terminal_receipt_ref, current_caller_origin, originating_origin, "
            "operation_ref FROM mission_control.knowledge_operation_journal "
            "WHERE run_id = $1::uuid",
            run_id,
        )
        assert rows, run_id
        for row in rows:
            lookup = await stack.knowledge.gateway.receipt(row["effect_key"], recovery)
            assert isinstance(lookup, ReceiptFound), lookup
            effect = lookup.receipt.effect
            originating = Origin.model_validate(json.loads(row["originating_origin"]))
            caller = json.loads(row["current_caller_origin"])
            assert effect.effectKey == row["effect_key"]
            assert effect.originatingOrigin.digest() == originating.digest()
            assert effect.currentCallerOrigin.invocationId == caller["invocationId"]
            assert effect.currentCallerOrigin.mission is not None
            assert effect.currentCallerOrigin.mission.operationId == row["operation_ref"]
            assert row["terminal_receipt_ref"] == lookup.receipt.receipt_ref()
            checked.append(
                {
                    "run_id": run_id,
                    "effect_key": row["effect_key"],
                    "receipt_ref": row["terminal_receipt_ref"],
                    "receipt_digest": lookup.receipt.digest,
                    "invocation_id": caller["invocationId"],
                    "dispatch_sequence": effect.dispatchSequence,
                }
            )
    _write(f"{mode}-{application}-ReceiptAttribution", {"checked": checked})


async def _stop_during_review(
    stack: ScopedStack, mode: str, application: str, fake: FakeKnowledgeBinding | None
) -> str:
    review_run = await _launch(stack, "StageGraph")
    await until(lambda: _at_wait(stack, review_run), seconds=240)
    before = await _rows(
        stack,
        "SELECT state FROM mission_control.knowledge_operation_handle WHERE run_id = $1::uuid "
        "AND operation = 'report.assess'",
        review_run,
    )
    command = await _cancel_immediately(stack, review_run)

    async def cancelled() -> bool:
        rows = await _rows(
            stack,
            "SELECT state FROM mission_control.knowledge_operation_handle "
            "WHERE run_id = $1::uuid AND operation = 'report.assess'",
            review_run,
        )
        return bool(rows) and all(row["state"] == "cancelled" for row in rows)

    await until(cancelled, seconds=60)
    after = await _rows(
        stack,
        "SELECT handle.state, handle.cancel_request_id, handle.pending_review_ref, "
        "handle.remote_operation_id, submission.assessment_state, finalization.outcome_basis "
        "FROM mission_control.knowledge_operation_handle handle "
        "JOIN mission_control.output_submission submission ON "
        "submission.assessment_operation_id = handle.remote_operation_id "
        "JOIN mission_control.invocation_finalization finalization ON "
        "finalization.invocation_ref = submission.invocation_ref "
        "WHERE handle.run_id = $1::uuid AND handle.operation = 'report.assess'",
        review_run,
    )
    fence = await _rows(
        stack,
        "SELECT command_id FROM mission_control.stop_fence WHERE run_key = $1",
        review_run,
    )
    remote: list[dict[str, Any]] = []
    gate = os.environ.get("KNOWLEDGE_TEST_COMPONENT_DSN")
    if fake is None and gate:
        import asyncpg

        connection = await asyncpg.connect(gate)
        try:
            # The executor side: the operation is cancelled with the stop request id and the
            # run holds no admitted use decision (the decision stays held).
            remote = [
                dict(row)
                for row in await connection.fetch(
                    "SELECT o.state, o.cancel_request_id, (SELECT count(*) FROM "
                    "knowledge_verification.use_decision d WHERE d.tenant_id = o.tenant_id "
                    "AND d.run_id = o.run_id AND d.disposition = 'admitted') AS admitted "
                    "FROM knowledge_verification.operation o "
                    "WHERE o.operation_id = ANY($1::text[])",
                    [row["remote_operation_id"] for row in after],
                )
            ]
        finally:
            await connection.close()
    _write(
        f"{mode}-{application}-StopDuringReview-{review_run}",
        {"before": before, "after": after, "fence": fence, "command": command, "remote": remote},
    )
    assert [row["state"] for row in before] == ["waiting_review"], before
    assert [
        (row["state"], row["cancel_request_id"], row["assessment_state"], row["outcome_basis"])
        for row in after
    ] == [
        (
            "cancelled",
            f"stop:{review_run}:{command['request_id']}",
            "assessing",
            "no_declared_obligations",
        )
    ], after
    assert after[0]["pending_review_ref"] is not None
    assert [row["command_id"] for row in fence] == [command["request_id"]], fence
    if fake is not None:
        cancels = fake.calls_of("operation.cancel")
        assert len(cancels) == 1 and cancels[0].claims.operations == ["operation.cancel"]
    elif gate:
        assert [(row["state"], row["cancel_request_id"], row["admitted"]) for row in remote] == [
            ("cancelled", f"stop:{review_run}:{command['request_id']}", 0)
        ], remote
    return review_run


def _assert_no_run_wide_delivery(evidence: dict[str, Any], family: str) -> None:
    """WI-02 (ADR-0061): a later invocation no longer receives every finalized upstream report.
    These launched manifests attach no transfer selection, so no plan is sealed for the run and
    the later stages still start; exact delivery is proven by the materializer and lane tests."""

    operations = sorted(evidence["journal_starts"], key=lambda row: row["first_prepared"])
    assert len(operations) >= 2, (family, evidence)
    assert evidence["deliveries"] == [], (family, evidence["deliveries"])


async def _evidence(stack: ScopedStack, run_id: str) -> dict[str, Any]:
    queries = {
        "journal": (
            "SELECT effect_key, state, operation_ref, operation_attempt, execution_generation, "
            "reconciled, terminal_receipt_ref, current_caller_origin, originating_origin, "
            "knowledge_operation_id::text AS knowledge_operation_id "
            "FROM mission_control.knowledge_operation_journal WHERE run_id = $1::uuid "
            "ORDER BY operation_ref"
        ),
        "transitions": (
            "SELECT journal.operation_ref, transition.from_state, transition.to_state "
            "FROM mission_control.knowledge_operation_transition transition "
            "JOIN mission_control.knowledge_operation_journal journal USING "
            "(installation_id, application_id, tenant_id, knowledge_operation_id) "
            "WHERE journal.run_id = $1::uuid ORDER BY journal.operation_ref, "
            "transition.transition_version"
        ),
        "submissions": (
            "SELECT operation_ref, operation_attempt, invocation_ref, submission_key, "
            "assessment_state, assessment_operation_id, assessment_binding, selection "
            "FROM mission_control.output_submission WHERE run_id = $1::uuid "
            "ORDER BY operation_ref"
        ),
        "handles": (
            "SELECT operation, operation_ref, state, remote_operation_id, request_id "
            "FROM mission_control.knowledge_operation_handle WHERE run_id = $1::uuid "
            "ORDER BY operation_ref"
        ),
        "finalizations": (
            "SELECT operation_ref, invocation_ref, outcome, outcome_basis FROM "
            "mission_control.invocation_finalization WHERE run_id = $1::uuid "
            "ORDER BY operation_ref"
        ),
        "deliveries": (
            "SELECT transfer_plan_id::text AS transfer_plan_id, receiver_operation_ref, "
            "boundary, plan_digest FROM mission_control.transfer_plan WHERE run_id = $1::uuid "
            "ORDER BY sealed_at"
        ),
        "journal_starts": (
            "SELECT operation_ref, min(prepared_at) AS first_prepared FROM "
            "mission_control.knowledge_operation_journal WHERE run_id = $1::uuid "
            "GROUP BY operation_ref"
        ),
        "lineage": (
            "SELECT subject_handle, subject_kind, role, actor_kind, actor_ref, "
            "knowledge_operation_id::text AS knowledge_operation_id, fact "
            "FROM mission_control.content_lineage WHERE run_id = $1::uuid "
            "ORDER BY subject_handle, role"
        ),
    }
    return {name: await _rows(stack, query, run_id) for name, query in queries.items()}


def _assert_run(evidence: dict[str, Any], run_id: str, binding: str, real: bool) -> None:
    journal, transitions = evidence["journal"], evidence["transitions"]
    submissions, handles = evidence["submissions"], evidence["handles"]
    finalizations, lineage = evidence["finalizations"], evidence["lineage"]
    operations = {row["operation_ref"] for row in journal}
    assert operations, evidence
    assert all(not ref.startswith("manifest-template/") for ref in operations), evidence
    for row in journal:
        assert row["state"] == "applied", evidence
        caller = json.loads(row["current_caller_origin"])
        assert caller["kind"] == "mission_invocation"
        # The origin is the live attempt of exactly this operation.
        assert caller["mission"]["runId"] == run_id
        assert caller["mission"]["operationId"] == row["operation_ref"]
        assert caller["mission"]["operationAttempt"] == row["operation_attempt"]
        assert caller["mission"]["executionGeneration"] == row["execution_generation"]
        assert json.loads(row["originating_origin"]) == caller  # first attempt
    for ref in operations:
        states = [
            (t["from_state"], t["to_state"]) for t in transitions if t["operation_ref"] == ref
        ]
        assert states == [
            (None, "prepared"),
            ("prepared", "dispatched"),
            ("dispatched", "applied"),
        ], evidence
    assert {row["operation_ref"] for row in submissions} == operations, evidence
    for row in submissions:
        assert row["assessment_state"] in VERDICTS, evidence
        if not real:
            assert row["assessment_state"] == "assessed", evidence
        assert row["assessment_binding"] == binding, evidence
        assert row["submission_key"].startswith("rrm009-submit_output-"), evidence
    assessed = {
        row["remote_operation_id"] for row in handles if row["operation"] == "report.assess"
    }
    assert assessed == {row["assessment_operation_id"] for row in submissions}, evidence
    assert {row["state"] for row in handles} <= {"succeeded", "held", "rejected"}, evidence
    assert {(row["operation_ref"], row["outcome_basis"]) for row in finalizations} == {
        (ref, "assessed") for ref in operations
    }, evidence
    # Lineage: the registering invocation is the report's one producer (with its receipt and
    # journal row); submitting its own report is not an adoption.
    by_invocation = {row["operation_ref"]: row["invocation_ref"] for row in submissions}
    reports = {
        handle
        for row in submissions
        for handle in (item["ref"] for item in json.loads(row["selection"])["items"])
    }
    for handle in reports:
        facts = [row for row in lineage if row["subject_handle"] == handle]
        producers = [row for row in facts if row["role"] == "producer"]
        assert len(producers) == 1, evidence
        assert producers[0]["actor_ref"] in by_invocation.values(), evidence
        assert producers[0]["knowledge_operation_id"] in {
            row["knowledge_operation_id"] for row in journal
        }, evidence
        # Production by the registrar; a ready transfer receipt adds consumption (consumer),
        # never a second producer or an adoption.
        assert {"producer", "receipt"} <= {row["role"] for row in facts}, evidence
        assert {row["role"] for row in facts} <= {
            "producer",
            "receipt",
            "consumer",
            "revision",
        }, evidence
