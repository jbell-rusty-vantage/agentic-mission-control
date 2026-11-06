"""AI Engineer KS bridge over Mission Control's production knowledge gateway (OVE-204 slice 2).

The real :class:`KnowledgeGateway` (in-memory journal and handle store, real Ed25519 minter)
and the real :class:`KnowledgeToolset` locate/access path run against a scripted KS binding and
a scripted fixture host; every assertion about a credential reads the bearer token KS received.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION
from mission_control.application.knowledge.gateway import KnowledgeGateway
from mission_control.application.knowledge.toolset import KnowledgeToolset, LiveInvocation
from mission_control.contracts.knowledge_assessment import RESULT_VERSIONS
from mission_control.contracts.knowledge_protocol import (
    KnowledgePlanPreview,
    OperationEnvelope,
    OperationHandle,
    Ref,
    digest_bytes,
    digest_canonical,
)
from mission_control.contracts.knowledge_protocol_results import (
    ConcurrencyToken,
    CredentialClaims,
    OperationReceipt,
    OperationStatus,
    ReceiptEffect,
)
from tests.fixtures.aieng_knowledge import AiengKnowledgeBridge
from tests.fixtures.knowledge_binding import (
    InMemoryKnowledgeHandleStore,
    InMemoryKnowledgeJournal,
    Issuer,
    RecordingMinter,
    SteppingClock,
    knowledge_port,
)
from tests.fixtures.mission_control_common_db import AI_ENGINEER_INSTALLATION_ID
from tests.fixtures.qualia_knowledge import KnowledgeBridgeRefused
from tests.fixtures.qualia_runtime import SpendLedger

KS_INSTALLATION = "0192a4f0-0000-7000-8000-0000000a1e11"
TENANT = "22222222-2222-4222-8222-222222222222"
BINDING = "aiengineer-postgres"
AUDIENCE = "knowledge-services-executor"
RUN = "11111111-1111-4111-8111-111111111111"
MISSION = "33333333-3333-4333-8333-333333333333"
ACTIVATION = "44444444-4444-4444-8444-444444444444"
BOUND = "sha256:" + "b" * 64


def ref(kind: str, id_: str, version: str, seed: str) -> dict[str, str]:
    return {
        "kind": kind,
        "id": id_,
        "version": version,
        "digest": "sha256:" + seed * 64,
        "tenant": TENANT,
        "binding": BINDING,
    }


REPORT = ref("report", "aieng-r1", "research-report.v2", "a")
DECISION = ref("use_decision", "decision-1", "use-decision.v1", "d")
POLICY = ref("policy", "policy-1", "policy.v1", "e")
RUBRIC = ref("rubric", "rubric-1", "rubric.v1", "f")


def claims_of(credential: Any) -> CredentialClaims:
    token = credential() if callable(credential) else credential
    payload = token.split(".")[1]
    return CredentialClaims.model_validate_json(base64.urlsafe_b64decode(payload + "==="))


class ScriptedBinding:
    """The KS binding: answers what the aiengineer-postgres binding answers, records tokens."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, CredentialClaims, OperationEnvelope]] = []
        self.documents: dict[str, bytes] = {}
        self.results: dict[str, tuple[OperationHandle, Ref]] = {}

    def of(self, operation: str) -> list[tuple[CredentialClaims, OperationEnvelope]]:
        return [(claims, envelope) for name, claims, envelope in self.calls if name == operation]

    def _document(self, operation: str) -> dict[str, Any]:
        if operation == "report.decide":
            return {"schema": "use-decision-result.v1", "decision": DECISION}
        if operation == "decision.resolve":
            return {
                "schema": "use-decision-resolution.v1",
                "requested": DECISION,
                "current": DECISION,
                "chain": [DECISION],
                "report": REPORT,
                "subject": REPORT,
                "use": "knowledge_ingestion.ai_engineer",
                "audience": "ai_engineer",
                "useClass": "official",
                "disposition": "admitted",
                "conditions": [],
                "admissibility": {"status": "admitted", "reason": None},
                "reviewPending": False,
                "reviewer": None,
                "judgment": [],
                "revocationEpoch": 5,
                "checkedAt": "2026-10-24T20:00:00Z",
            }
        return {"schema": RESULT_VERSIONS[operation], "report": REPORT}

    async def invoke(self, envelope: OperationEnvelope, credential: Any) -> Any:
        claims = claims_of(credential)
        operation = envelope.operation
        self.calls.append((operation, claims, envelope))
        handle = OperationHandle(
            protocolVersion="ks.knowledge_operation.v2",
            tenant=envelope.tenant,
            application=envelope.application,
            binding=envelope.binding,
            operationId=f"op-{len(self.calls)}",
        )
        if operation == "knowledge.plan_preview":
            return KnowledgePlanPreview(
                planId="plan-1",
                semanticPayloadDigest="sha256:" + "1" * 64,
                boundEffectDigest=BOUND,
                normalizedValuesDigest="sha256:" + "2" * 64,
                processedEpoch=3,
                migrationHead="20261025010200",
            )
        if operation in {"report.register", "knowledge.apply"}:
            effect = envelope.effect
            assert effect is not None
            native = (
                REPORT
                if operation == "report.register"
                else ref("receipt", "rcpt-1", "receipt.v1", "c")
            )
            body: dict[str, Any] = {
                "handle": handle,
                "effect": ReceiptEffect(
                    effectKey=effect.effectKey,
                    semanticPayloadDigest=effect.semanticPayloadDigest,
                    originatingOrigin=effect.originatingOrigin,
                    boundEffectDigest=effect.boundEffectDigest,
                    canonicalization="kop-canonical-json.v1",
                    currentCallerOrigin=claims.origin,
                    dispatchId=envelope.dispatchId,
                    envelopeDigest=envelope.digest(),
                    dispatchSequence=1,
                ),
                "outcome": "applied",
                "nativeReceiptRef": Ref.model_validate(native),
                "affectedRefs": [],
                "concurrencyToken": ConcurrencyToken(before=None, after="1"),
                "processedRevocationEpoch": 0,
                "itemOutcomes": [],
                "appliedAt": "2026-10-24T20:00:00Z",
                "details": None,
            }
            return OperationReceipt(**body, digest=digest_canonical(dict(body)))
        data = json.dumps(self._document(operation)).encode()
        result = Ref(
            kind="artifact",
            id=f"result-{len(self.calls)}",
            version=RESULT_VERSIONS[operation],
            digest=digest_bytes(data),
            tenant=TENANT,
            binding=BINDING,
        )
        self.documents[result.id] = data
        self.results[handle.operationId] = (handle, result)
        return handle

    async def operation_get(self, handle: OperationHandle, credential: Any) -> OperationStatus:
        claims_of(credential)
        stored, result = self.results[handle.operationId]
        return OperationStatus(
            handle=stored,
            state="succeeded",
            revision=1,
            createdAt="2026-10-24T20:00:00Z",
            updatedAt="2026-10-24T20:00:00Z",
            progressRef=None,
            pendingReviewRef=None,
            resultRef=result,
            error=None,
            unresolvedEffects=[],
            retryAfterMs=None,
            cancelRequestId=None,
        )

    async def artifact(self, artifact_id: str, digest: str, credential: Any) -> bytes:
        claims_of(credential)
        return self.documents[artifact_id]


class Locator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    async def locate(
        self, request_scope: str, run_key: str, unit_key: str | None
    ) -> tuple[str, str | None]:
        self.calls.append((request_scope, run_key, unit_key))
        return MISSION, ACTIVATION


def lane() -> SimpleNamespace:
    clock = SteppingClock()
    binding = ScriptedBinding()

    async def no_sleep(_: float) -> None:
        return None

    gateway = KnowledgeGateway(
        client=binding,  # type: ignore[arg-type]
        journal=InMemoryKnowledgeJournal(),
        handles=InMemoryKnowledgeHandleStore(),
        minter=RecordingMinter(Issuer(clock=clock).minter()),
        knowledge=knowledge_port(BINDING),
        audience=AUDIENCE,
        clock=clock,
        sleep=no_sleep,
    )
    locator = Locator()
    toolset = KnowledgeToolset(
        gateway=gateway,
        submissions=None,  # type: ignore[arg-type]  # locate/access only
        issuer="mission-control",
        clock=clock,
        knowledge_installation_id=KS_INSTALLATION,
        locator=locator,
    )
    return SimpleNamespace(gateway=gateway, toolset=toolset, binding=binding, locator=locator)


class FakeHost:
    """Scripted host replies (a dict or a function of the command); records every command."""

    def __init__(self, replies: dict[str, Any]) -> None:
        self.replies: dict[str, Any] = replies
        self.commands: list[dict[str, Any]] = []

    async def request(self, command: dict[str, Any]) -> dict[str, Any]:
        self.commands.append(command)
        reply = self.replies[command["action"]]
        return reply(command) if callable(reply) else reply

    def sent(self, action: str) -> list[dict[str, Any]]:
        return [command for command in self.commands if command["action"] == action]


def ready(**subjects: str) -> dict[str, Any]:
    return {
        "ready": True,
        "roles": {
            role: {
                "subject": subjects.get(role, "actor-" + role),
                "invocationId": "invocation-" + role,
                "applicationId": "ai-engineer",
                "installationId": KS_INSTALLATION,
                "tenantId": TENANT,
            }
            for role in ("producer", "judge", "auditor")
        },
    }


def bridge(tmp_path: Path, host: FakeHost, composed: Any = None) -> AiengKnowledgeBridge:
    return AiengKnowledgeBridge(
        host,  # type: ignore[arg-type]
        ready=ready(),
        evidence_dir=tmp_path / "web",
        ledger=SpendLedger(tmp_path / "budget"),
        lane=composed,
    )


def live(
    application: str = "ai-engineer",
    installation: str | None = None,
    *,
    attempt: int = 2,
    evaluator: bool = False,
) -> LiveInvocation:
    return LiveInvocation(
        request_scope=f"mc/{installation or AI_ENGINEER_INSTALLATION_ID}/{application}/{TENANT}",
        run_id=RUN,
        operation_id="ingest-operation",
        operation_attempt=attempt,
        execution_generation=1,
        lane="deep_agents",
        evaluator=evaluator,
        unit_key="unit-ingest-2",
    )


class bound:  # noqa: N801 -- a context manager over the live invocation
    def __init__(self, invocation: LiveInvocation) -> None:
        self.invocation = invocation

    def __enter__(self) -> LiveInvocation:
        self.token = CURRENT_INVOCATION.set(self.invocation)
        return self.invocation

    def __exit__(self, *_: object) -> None:
        CURRENT_INVOCATION.reset(self.token)


def intent_reply(command: dict[str, Any]) -> dict[str, Any]:
    """The host builds the intent over the wire origin it was given (aieng-intent.ts)."""

    return {
        "intent": {
            "schemaVersion": "knowledge-ingestion-intent.v1",
            "intentId": command["input"]["intentId"],
            "context": {"tenantId": TENANT},
            "proposals": command["input"]["proposals"],
            "exactUse": {
                "effectKey": f"aieng-r1:native:{command['input']['intentId']}",
                "originatingOrigin": command["origin"],
            },
        },
        "effectKey": f"aieng-r1:native:{command['input']['intentId']}",
        "plan": {"errors": []},
        "reportBinding": {"claimIds": ["a-1"]},
    }


def host_replies() -> dict[str, Any]:
    return {
        "knowledge_read": {"snapshot": {"snapshotId": "snap-1"}, "results": []},
        "prepare_report": lambda command: {
            "registration": {"schema": "research-report.v2", "producer": command["origin"]}
        },
        "native_intent": intent_reply,
        "apply_context": {
            "task": {
                "use": "knowledge_ingestion.ai_engineer",
                "audience": "ai_engineer",
                "policy": POLICY,
                "rubric": RUBRIC,
            },
            "supported": 1,
        },
        "readback": {
            "native": {
                "receiptId": "rcpt-1",
                "entities": [{}],
                "claims": [{}],
                "affectedChecked": 3,
                "affectedTotal": 3,
                "failures": [],
                "complete": True,
            }
        },
    }


NATIVE = {
    "intentId": "i-1",
    "snapshotId": "snap-1",
    "subjects": [],
    "proposals": [{"proposalId": "p", "kind": "entity.alias"}],
    "claims": [{"assertionId": "a-1"}],
}


def evaluated(worker: AiengKnowledgeBridge) -> None:
    worker._reports[REPORT["digest"]] = {
        "report": REPORT,
        "response": json.dumps({"report": REPORT}),
        "native_result": None,
    }


def test_mc_scope_uses_mc_installation_not_the_ks_component(tmp_path: Path) -> None:
    worker = bridge(tmp_path, FakeHost({}))
    with bound(live()):
        context = worker._current_native_context()
        assert context["run"]["operationId"] == "ingest-operation"
        assert context["run"]["attempt"] == 2
    for wrong in (live(installation=KS_INSTALLATION), live(application="biotech")):
        with bound(wrong), pytest.raises(KnowledgeBridgeRefused):
            worker._current_native_context()


async def test_producer_access_is_the_located_mission_invocation(tmp_path: Path) -> None:
    composed = lane()
    worker = bridge(tmp_path, FakeHost({}), composed)
    with bound(live()):
        access = await worker._producer_access()
    wire = access.wire_origin()
    assert wire.kind == "mission_invocation"
    assert wire.installationId == KS_INSTALLATION and wire.tenantId == TENANT
    assert wire.mission is not None
    assert (wire.mission.missionId, wire.mission.runId) == (MISSION, RUN)
    assert wire.mission.missionId != wire.mission.runId
    assert wire.mission.activationId == ACTIVATION
    assert (wire.mission.operationAttempt, wire.mission.lane) == (2, "deep_agents")
    assert composed.locator.calls == [
        (f"mc/{AI_ENGINEER_INSTALLATION_ID}/ai-engineer/{TENANT}", RUN, "unit-ingest-2")
    ]
    with bound(live(evaluator=True)), pytest.raises(KnowledgeBridgeRefused):
        await worker._producer_access()
    with bound(live(application="biotech")), pytest.raises(KnowledgeBridgeRefused):
        await worker._producer_access()
    unattached = bridge(tmp_path, FakeHost({}))
    with bound(live()), pytest.raises(KnowledgeBridgeRefused, match="not composed"):
        await unattached._producer_access()


async def test_report_register_goes_through_the_gateway_under_an_mc_credential(
    tmp_path: Path,
) -> None:
    composed = lane()
    host = FakeHost(host_replies())
    worker = bridge(tmp_path, host, composed)
    with bound(live()):
        registration, access = await worker._prepare_registration({"id": "aieng-r1"})
        report = await worker._register_report(registration, "aieng-r1", access)
    assert report == REPORT
    # The registration's producer is exactly the wire origin the credential carries.
    (prepare,) = host.sent("prepare_report")
    ((claims, envelope),) = composed.binding.of("report.register")
    assert prepare["origin"] == claims.origin.model_dump(mode="json")
    assert claims.origin.kind == "mission_invocation" and claims.origin.mission is not None
    assert claims.origin.mission.missionId == MISSION
    assert claims.iss == "mission-control" and claims.evaluation is None
    assert envelope.effect is not None and claims.effect is not None
    assert claims.effect.effectKey == envelope.effect.effectKey
    # Nothing producer-side is minted by the host any more.
    assert not host.sent("call")
    assert [call["operation"] for call in worker.knowledge_calls] == ["report.register"]


async def test_apply_runs_on_the_located_origin_and_the_intent_binds_it(tmp_path: Path) -> None:
    composed = lane()
    host = FakeHost(host_replies())
    worker = bridge(tmp_path, host, composed)
    evaluated(worker)
    with bound(live()):
        missing = json.loads(await worker.aieng_ingest(REPORT, NATIVE, "preview"))
        assert missing["status"] == "refused" and "snapshotId" in missing["feedback"]
        await worker.aieng_knowledge_read([{"opId": "head", "query": "knowledge.head"}])
        previewed = json.loads(await worker.aieng_ingest(REPORT, NATIVE, "preview"))
        assert previewed["status"] == "previewed", previewed
        assert previewed["content"]["preview"]["boundEffectDigest"] == BOUND
        changed = {**NATIVE, "intentId": "i-2"}
        refused = json.loads(await worker.aieng_ingest(REPORT, changed, "apply"))
        # A changed input is never sealed, decided or applied without its own preview.
        assert refused["status"] == "refused" and refused["stage"] == "native_apply"
        assert not composed.binding.of("report.seal") and not composed.binding.of("knowledge.apply")
        await worker.aieng_ingest(REPORT, changed, "preview")
        applied = json.loads(await worker.aieng_ingest(REPORT, changed, "apply"))
    assert applied["status"] == "native_applied", applied
    assert applied["native_proof"]["readback_failures"] == 0

    wire = host.sent("native_intent")[-1]["origin"]
    assert wire["kind"] == "mission_invocation" and wire["mission"]["missionId"] == MISSION
    ((apply_claims, apply_envelope),) = composed.binding.of("knowledge.apply")
    assert apply_claims.origin.kind == "mission_invocation"
    assert apply_claims.origin.mission is not None
    assert apply_claims.origin.mission.missionId == MISSION
    assert apply_claims.origin.mission.activationId == ACTIVATION
    assert apply_claims.effect is not None and apply_claims.effect.boundEffectDigest == BOUND
    payload = apply_envelope.input.inlinePayload if apply_envelope.input else None
    assert isinstance(payload, dict)
    exact_use = payload["exactUse"]
    # The intent's originating origin is the wire origin the host was given, same attempt.
    assert exact_use["originatingOrigin"] == wire
    assert exact_use["originatingOrigin"]["mission"] == apply_claims.origin.mission.model_dump(
        mode="json"
    )
    assert exact_use["useDecisionId"] == DECISION["id"]
    assert exact_use["processedEpoch"] == 5 and exact_use["boundEffectDigest"] == BOUND
    # Every producer-side operation was MC-minted under the same mission invocation.
    for operation in (
        "knowledge.plan_preview",
        "report.seal",
        "report.decide",
        "decision.resolve",
        "knowledge.apply",
    ):
        calls = composed.binding.of(operation)
        assert calls, operation
        for claims, _ in calls:
            assert claims.origin.kind == "mission_invocation", operation
            assert claims.origin.mission is not None
            assert claims.origin.mission.missionId == MISSION, operation
            assert claims.evaluation is None, operation
    (readback,) = host.sent("readback")
    assert readback["receiptId"] == "rcpt-1" and readback["decisionId"] == DECISION["id"]
    assert not host.sent("finalize_report") and not host.sent("call")


async def test_a_preview_of_another_attempt_is_never_applied(tmp_path: Path) -> None:
    composed = lane()
    host = FakeHost(host_replies())
    worker = bridge(tmp_path, host, composed)
    evaluated(worker)
    with bound(live(attempt=1)):
        await worker.aieng_knowledge_read([{"opId": "head", "query": "knowledge.head"}])
        previewed = json.loads(await worker.aieng_ingest(REPORT, NATIVE, "preview"))
        assert previewed["status"] == "previewed"
    with bound(live(attempt=2)):
        refused = json.loads(await worker.aieng_ingest(REPORT, NATIVE, "apply"))
    assert refused["status"] == "refused" and "another invocation attempt" in refused["feedback"]
    assert not composed.binding.of("report.seal")


def test_evaluator_roles_need_distinct_subjects_from_each_other_and_the_producer(
    tmp_path: Path,
) -> None:
    for subjects in ({"judge": "same", "auditor": "same"}, {"judge": "actor-producer"}):
        with pytest.raises(KnowledgeBridgeRefused, match="Separate"):
            AiengKnowledgeBridge(
                FakeHost({}),  # type: ignore[arg-type]
                ready=ready(**subjects),
                evidence_dir=tmp_path / "web",
                ledger=SpendLedger(tmp_path / "budget"),
            )


async def test_evaluator_calls_stay_host_minted_with_distinct_subjects(tmp_path: Path) -> None:
    """Judge/auditor requests go to the host (its own key and standalone subjects); MC's
    gateway mints none of them, and its producer subject differs from both evaluators."""

    composed = lane()
    host = FakeHost(
        {
            "eval_request": lambda command: {
                "context": {"role": command["role"], "report": command["report"]},
                "json_schema": {"type": "object"},
                "prompt": "p",
                "body": {},
            },
        }
    )
    worker = bridge(tmp_path, host, composed)

    class Refuse(RuntimeError):
        pass

    def model(*_: Any, **__: Any) -> Any:
        raise Refuse

    worker.model_factory = model
    for role in ("judge", "auditor"):
        with pytest.raises(Refuse):
            await worker._evaluate(role, REPORT)
    assert [command["role"] for command in host.sent("eval_request")] == ["judge", "auditor"]
    assert composed.binding.calls == []
    subjects = {worker.roles[role]["subject"] for role in ("judge", "auditor")}
    assert len(subjects) == 2 and "mission-control-runtime" not in subjects


async def test_schema_guide_and_relation_paths_stay_in_the_workspace(tmp_path: Path) -> None:
    worker = bridge(tmp_path, FakeHost({}))
    guide = json.loads(await worker.aieng_schema())
    assert guide["total_chars"] > 0
    relation = json.loads(await worker.aieng_schema(section="relation", name="corpus/library"))
    assert "corpus.library" in relation["content"]
    refused = json.loads(await worker.aieng_schema(section="relation", name=""))
    assert refused["status"] == "refused"
