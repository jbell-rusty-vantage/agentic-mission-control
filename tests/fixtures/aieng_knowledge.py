"""AI Engineer KS bridge: shared evaluation plus AIDB read-before-write native ingestion.

Verification (capture custody, separate real judge/auditor, assessment preview, exact report
reads) is the Qualia bridge. The native half targets the AI Engineer schema through KS
`knowledge.apply` (knowledge-ingestion-intent.v1): the agent reads the current knowledge
(persisted snapshot), previews a plan, then applies only what an exact-use decision on that
previewed effect admits. No graph is written.

Provenance slice 2 (OVE-204): every producer-side K01 call goes through Mission Control's
production knowledge gateway under an MC-minted credential whose origin is the located
``mission_invocation`` of the live attempt (``await toolset.locate(live)`` then
``toolset.access``): ``report.register`` (``gateway.invoke``), ``knowledge.plan_preview``
(``gateway.plan_preview``), ``report.seal`` / ``report.decide`` / ``decision.resolve``
(``gateway.trusted`` without an evaluator grant) and ``knowledge.apply`` (``gateway.invoke``).
The host only builds bytes bound to that wire origin (``prepare_report``, ``native_intent``)
and reads rows back. The independent judge and auditor stay host-minted standalone roles.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field
from tests.fixtures.aieng_web_tools import AIENG_SOURCES, AiEngineerEvidence
from tests.fixtures.qualia_knowledge import (
    AuthoredClaim,
    KnowledgeBridgeRefused,
    QualiaKnowledgeBridge,
    QualiaKnowledgeIPC,
    QualifierText,
    ReportReadInput,
    VerifyEvidenceInput,
)
from tests.fixtures.qualia_runtime import SpendLedger, evaluator_model
from tests.fixtures.qualia_web_tools import bounded_result, tool_capability

from mission_control.adapters.capabilities.capability_bundles import bytes_digest
from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION
from mission_control.application.authoring.manifest_launch_inputs import CapabilityComponentBinding
from mission_control.application.knowledge.access import InvocationAccess, instant
from mission_control.application.knowledge.judgment import TRUSTED_CAPABILITY_PIN
from mission_control.application.knowledge.operations import (
    KnowledgeCall,
    KnowledgeRefused,
    KnowledgeResult,
)
from mission_control.contracts.knowledge_assessment import (
    Build,
    DecisionResolution,
    DecisionResolveRequest,
    ReportSealRequest,
    ReportUseRequest,
)
from mission_control.contracts.knowledge_protocol import Budget, Governors, Ref, digest_canonical
from mission_control.contracts.knowledge_protocol_results import OperationReceipt
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import CapabilityDefinition
from mission_control.domain.execution.contracts import DeepAgentToolComponent
from mission_control.domain.knowledge.effects import mint_effect_key

AIDB_WORKSPACE = (
    Path(__file__).resolve().parents[4] / "aiengineer/ai-engineer-db-contract/workspace"
)


class EngineeringClaimQualifiers(BaseModel):
    """Authorable KS engineering.v2 qualifiers; profile remains host-owned."""

    model_config = ConfigDict(extra="forbid", strict=True)
    entity: QualifierText | None = None
    population: QualifierText | None = None
    unit: QualifierText | None = None
    baseline: QualifierText | None = None
    negation: bool
    modality: Literal[
        "asserted",
        "possible",
        "probable",
        "hypothetical",
        "recommended",
        "forecast",
        "interrogative",
    ] = "asserted"
    runtime: QualifierText | None = None
    softwareVersion: QualifierText | None = None  # noqa: N815 -- exact KS engineering.v2 spelling
    configuration: QualifierText | None = None
    benchmarkEnvironment: QualifierText | None = None  # noqa: N815
    denominator: QualifierText | None = None
    repositoryCommit: (  # noqa: N815
        Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")] | None
    ) = None


class EngineeringAuthoredClaim(AuthoredClaim):
    qualifiers: EngineeringClaimQualifiers  # type: ignore[assignment]


class AiengVerifyInput(VerifyEvidenceInput):
    claims: list[EngineeringAuthoredClaim] = Field(min_length=1, max_length=24)  # type: ignore[assignment]
    use: Literal["knowledge_ingestion.ai_engineer", "research.summary"] = (  # type: ignore[assignment]
        "knowledge_ingestion.ai_engineer"
    )


READ_QUERIES = Literal[
    "knowledge.head",
    "entity.resolve",
    "entity.by_identifier",
    "entity.card",
    "entity.relationships",
    "evidence.claims_for_entity",
    "relationships.current_by_kind",
    "vocab.relationship_kind",
]


class ReadOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opId: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")  # noqa: N815 -- KS read-intent spelling
    query: READ_QUERIES
    params: dict[str, Any] = Field(default_factory=dict)


class KnowledgeReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operations: list[ReadOperation] = Field(min_length=1, max_length=12)


class ClaimSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assertionId: str = Field(min_length=1, max_length=120)  # noqa: N815
    claimType: str | None = None  # noqa: N815
    subjects: list[dict[str, str]] = Field(default_factory=list, max_length=12)


class NativeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intentId: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")  # noqa: N815
    snapshotId: str = Field(min_length=1, max_length=200)  # noqa: N815
    subjects: list[dict[str, Any]] = Field(default_factory=list, max_length=40)
    proposals: list[dict[str, Any]] = Field(min_length=1, max_length=120)
    claims: list[ClaimSelection] = Field(min_length=1, max_length=24)
    notes: str | None = Field(default=None, max_length=4000)


class AiengIngestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report: dict[str, Any]
    native_input: NativeInput
    mode: Literal["preview", "apply"] = "preview"


class AiengSchemaInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section: Literal[
        "guide", "entity_kinds", "relationship_kinds", "relation", "ingestion_rules"
    ] = "guide"
    name: str = Field(default="", max_length=80, pattern=r"^([a-z_]+/[a-z_.]+)?$")
    offset_chars: int = Field(default=0, ge=0, le=500000)
    max_chars: int = Field(default=10000, ge=1, le=12000)


GUIDE = {
    "purpose": (
        "Write verified AI Engineer knowledge: entities, identifiers, relationships and the "
        "claims an independent judge fully supported. Read first, preview, then apply."
    ),
    "procedure": [
        "1. aieng_knowledge_read: resolve each intended subject (entity.resolve {text}, "
        "entity.by_identifier {scheme,value}); keep the returned snapshot.snapshotId.",
        "2. Reuse existing entities with mode='resolved' and their entityId; create only what "
        "the read did not find (mode='new', onMatch='use_existing' or 'review').",
        "3. Read evidence_report_read(section='frozen', json_pointer='/assertions') and select "
        "only assertions whose judgments are all full_support (claims[].assertionId).",
        "4. Author subjects and domain proposals (relationship.assert, entity.identifier, "
        "entity.alias, fact.assert_state, event.assert). Cite evidence as [{claimId: "
        "<selected assertionId>}] — the host binds the verification run.",
        "5. aieng_ingest(mode='preview'): read plan.errors, failed ruleChecks and proposal "
        "outcomes; repair and preview again with the same report.",
        "6. aieng_ingest(mode='apply') with the identical previewed native_input. KS seals, "
        "decides on the exact previewed effect and applies; the host reads rows back.",
    ],
    "host_owned": [
        "claim text and verdicts (copied from the frozen report)",
        "claim.materialize, report.publish and support.admit proposals",
        "verification run, read snapshot, context, declared use and exact-use binding",
    ],
    "native_input_example": {
        "intentId": "author-a-unique-intent-id",
        "snapshotId": "COPY_FROM_aieng_knowledge_read",
        "subjects": [
            {
                "ref": "org",
                "mode": "new",
                "kind": "organization",
                "displayName": "AUTHOR_ACTUAL_ORGANIZATION_NAME",
                "identifiers": [{"scheme": "github", "value": "AUTHOR_ACTUAL_GITHUB_ORG"}],
                "onMatch": "use_existing",
                "evidence": [{"claimId": "COPY_A_FULLY_SUPPORTED_ASSERTION_ID"}],
            }
        ],
        "proposals": [
            {
                "proposalId": "org-develops-lib",
                "kind": "relationship.assert",
                "relationshipKind": "develops",
                "fromRef": "org",
                "toRef": "lib",
                "evidence": [{"claimId": "COPY_A_FULLY_SUPPORTED_ASSERTION_ID"}],
            }
        ],
        "claims": [
            {
                "assertionId": "COPY_A_FULLY_SUPPORTED_ASSERTION_ID",
                "claimType": "relationship",
                "subjects": [{"ref": "org", "role": "subject"}],
            }
        ],
    },
    "rules": [
        "Placeholders are not facts. Every value must be justified by a selected claim.",
        "Relationship kinds constrain endpoint entity kinds: read section='relationship_kinds'.",
        "Entity kinds and their typed payload columns: section='entity_kinds' and "
        "section='relation', name='corpus/<kind>'.",
        "A new subject carries its kind's NOT NULL typed columns in typedPayload, taken from "
        "evidence (for example paper.title; repository name, owner and host). Read "
        "section='relation', name='corpus/<kind>'; the host refuses a new subject without them.",
        "Never cite search/discovery listings; only judged assertions are evidence.",
        "verify_evidence is evaluation, not admission. aieng_ingest returns held/refused "
        "feedback unless exact-use admission, native apply and row readback all succeed.",
    ],
}


class AiengKnowledgeBridge(QualiaKnowledgeBridge):
    application_id = "ai-engineer"
    verify_input_model = AiengVerifyInput
    ingest_tool = "aieng_ingest"

    def __init__(
        self,
        ipc: QualiaKnowledgeIPC,
        *,
        ready: Mapping[str, Any],
        evidence_dir: Path,
        ledger: SpendLedger,
        model_factory: Callable[..., Any] = evaluator_model,
        native_context: dict[str, Any] | None = None,
        workspace: Path = AIDB_WORKSPACE,
        lane: Any | None = None,
    ) -> None:
        super().__init__(
            ipc,
            ready=ready,
            evidence_dir=evidence_dir,
            ledger=ledger,
            model_factory=model_factory,
            native_context=native_context,
        )
        self.evidence = AiEngineerEvidence(evidence_dir, AIENG_SOURCES)
        self.workspace = workspace.resolve()
        self.snapshots: dict[str, dict[str, Any]] = {}
        # MC's composed knowledge lane (toolset + gateway); attached once the stack composed it.
        self.lane = lane
        # Every producer-side K01 call this bridge made through MC's gateway (evidence only).
        self.knowledge_calls: list[dict[str, Any]] = []

    def attach_lane(self, lane: Any) -> None:
        """Bind Mission Control's composed knowledge lane (``KnowledgeLaneComposition``)."""

        self.lane = lane

    def mc_installation_id(self, producer: Mapping[str, Any]) -> str:
        # The AI Engineer KS component has its own installation; the MC run belongs to MC's.
        from tests.fixtures.mission_control_common_db import AI_ENGINEER_INSTALLATION_ID

        return str(AI_ENGINEER_INSTALLATION_ID)

    def _intent_context(self) -> dict[str, Any]:
        native = self._current_native_context()
        run = native["run"]
        # AIDB mission/attempt ids are owned by AIDB; the host derives its attribution rows.
        return {
            "correlationId": f"{run['runId']}:{run['operationId']}:{run['attempt']}"[:200],
            "actor": {"kind": "agent", "id": native["actor"]["id"][:200]},
        }

    # ------------------------------------------------ Mission Control production path

    async def _producer_access(self) -> InvocationAccess:
        """The located access of the live producer attempt (fresh invocation id, now).

        Fails closed without the composed lane, without a producer invocation, outside this KS
        installation's MC scope, or when the access is not a ``mission_invocation``."""

        if self.lane is None:
            raise KnowledgeBridgeRefused("Mission Control's knowledge lane is not composed")
        live = CURRENT_INVOCATION.get()
        if live is None or live.evaluator:
            raise KnowledgeBridgeRefused(
                "Producer-side knowledge calls require the current producer invocation"
            )
        self._current_native_context()  # the MC scope check (application, installation, tenant)
        toolset = self.lane.toolset
        located = await toolset.locate(live)  # slice 1: ledger mission/activation ids
        access: InvocationAccess = toolset.access(located)
        wire = access.wire_origin()
        producer = self.roles["producer"]
        if (
            wire.kind != "mission_invocation"
            or wire.mission is None
            or wire.applicationId != self.application_id
            or wire.installationId != producer["installationId"]
            or wire.tenantId != producer["tenantId"]
        ):
            raise KnowledgeBridgeRefused(
                "Mission Control access names no mission invocation of this KS installation"
            )
        return access

    def _note(self, operation: str, access: InvocationAccess) -> None:
        wire = access.wire_origin()
        self.knowledge_calls.append(
            {
                "operation": operation,
                "minted_by": "mission-control",
                "issuer": wire.issuer,
                "subject": wire.subject,
                "origin_kind": wire.kind,
                "mission": None if wire.mission is None else wire.mission.model_dump(mode="json"),
                "invocation_ref": access.invocation_ref,
            }
        )

    @staticmethod
    def _governors() -> Governors:
        return Governors(
            deadline=instant(datetime.now(UTC) + timedelta(minutes=30)),
            maxItems=64,
            partialResults="forbid",
            budget=Budget(calls=0, tokens=0, costUsd="0"),
        )

    def _pin(self, tool: str) -> str:
        assert self.lane is not None
        return str(self.lane.toolset.capability_pins.get(tool, f"knowledge.{tool}@1"))

    @staticmethod
    def _request_key(*parts: str) -> str:
        return "aieng-" + digest_canonical(list(parts))[7:47]

    @staticmethod
    def _receipt(result: KnowledgeResult, operation: str) -> OperationReceipt:
        receipt = result.receipt or getattr(result.lookup, "receipt", None)
        if result.refusal_code is not None or not isinstance(receipt, OperationReceipt):
            message = None if result.refusal is None else result.refusal.message
            raise KnowledgeBridgeRefused(
                f"{operation} {result.refusal_code or 'unsettled'} "
                f"(journal {None if result.state is None else result.state.value}): {message}"
            )
        return receipt

    async def _trusted(
        self, operation: Any, request: Any, access: InvocationAccess, *, key: str
    ) -> dict[str, Any]:
        """One producer-side trusted assessment operation (no evaluator grant)."""

        assert self.lane is not None
        answer = await self.lane.gateway.trusted(
            operation,
            request,
            access,
            evaluation=None,
            request_key=key,
            governors=self._governors(),
            capability_pin=TRUSTED_CAPABILITY_PIN,
        )
        self._note(operation, access)
        if answer.document is None:
            refusal = answer.refusal
            raise KnowledgeBridgeRefused(
                f"{operation} refused: {answer.reason or (refusal.code if refusal else None)}"
                f" {refusal.message if refusal else ''} "
                f"(status {None if answer.status is None else answer.status.state})"
            )
        return answer.document

    async def _prepare_registration(
        self, prepared_input: dict[str, Any]
    ) -> tuple[dict[str, Any], InvocationAccess]:
        access = await self._producer_access()
        prepared = await self.ipc.request(
            {
                "action": "prepare_report",
                "input": prepared_input,
                "origin": access.wire_origin().model_dump(mode="json"),
            }
        )
        return prepared["registration"], access

    async def _register_report(
        self, registration: dict[str, Any], report_id: str, producer: Any
    ) -> dict[str, Any]:
        """``report.register`` through MC's gateway (journal first, MC-minted credential)."""

        assert self.lane is not None and isinstance(producer, InvocationAccess)
        pin = self._pin("report_register")
        call = KnowledgeCall(
            operation="report.register",
            capability_pin=pin,
            native_contract={"name": "research-report", "version": "v2"},
            payload=registration,
            governors=self._governors(),
            effect_key=mint_effect_key(producer.origin, pin, digest_canonical(registration)),
        )
        result = await self.lane.gateway.invoke(call, producer)
        self._note("report.register", producer)
        receipt = self._receipt(result, "report.register")
        if receipt.outcome not in {"applied", "noop"}:
            raise KnowledgeBridgeRefused(f"report.register answered {receipt.outcome}")
        return receipt.nativeReceiptRef.model_dump(mode="json")

    async def _finalize(
        self, report: dict[str, Any], prepared: dict[str, Any], access: InvocationAccess
    ) -> dict[str, Any]:
        """Seal, decide on the exact previewed effect, resolve, apply, then read rows back."""

        assert self.lane is not None
        gateway = self.lane.gateway
        task = (await self.ipc.request({"action": "apply_context", "report": report}))["task"]
        intent, preview = prepared["intent"], prepared["preview"]
        exact_use = intent["exactUse"]
        effect_key, bound = str(exact_use["effectKey"]), str(preview["boundEffectDigest"])
        subject = Ref.model_validate(report)
        await self._trusted(
            "report.seal",
            ReportSealRequest(
                schema_="report-seal.v1",
                report=subject,
                build=Build(buildId="aieng-live-fixture", runtime="node24", dirty=True),
            ),
            access,
            key=self._request_key("seal", report["id"], report["digest"]),
        )
        decided = await self._trusted(
            "report.decide",
            ReportUseRequest(
                schema_="report-use.v1",
                report=subject,
                subject=subject,
                use=task["use"],
                audience=task["audience"],
                purpose="official",
                boundEffectDigest=bound,
                targetSchema="knowledge-ingestion-intent.v1",
                normalizedValues={},
                policy=Ref.model_validate(task["policy"]),
                rubric=Ref.model_validate(task["rubric"]),
                expiresAt=None,
            ),
            access,
            key=self._request_key("decide", effect_key, bound),
        )
        decision = Ref.model_validate(decided["decision"])
        resolved_document = await self._trusted(
            "decision.resolve",
            DecisionResolveRequest(schema_="decision-resolve.v1", decision=decision),
            access,
            key=self._request_key("resolve", effect_key, decision.id, decision.digest),
        )
        resolved = DecisionResolution.model_validate(resolved_document)
        use = {"use": task["use"], "audience": task["audience"]}
        if (
            resolved.disposition != "admitted"
            or resolved.admissibility.status != "admitted"
            or resolved.reviewPending
        ):
            return {
                "report": report,
                "decision": resolved_document,
                "use": use,
                "dispatched": False,
                "qualified": False,
            }
        apply_intent = {
            **intent,
            "exactUse": {
                **exact_use,
                "useDecisionId": resolved.current.id,
                "boundEffectDigest": bound,
                "processedEpoch": max(int(preview["processedEpoch"]), resolved.revocationEpoch),
                "normalizedValuesDigest": preview["normalizedValuesDigest"],
            },
        }
        port = gateway.knowledge
        call = KnowledgeCall(
            operation="knowledge.apply",
            capability_pin=self._pin("knowledge_apply"),
            native_contract={
                "name": port.apply_contract_name,
                "version": port.apply_contract_version,
            },
            payload=apply_intent,
            governors=self._governors(),
            upstream=(subject,),
            effect_key=effect_key,
            bound_effect_digest=bound,
        )
        result = await gateway.invoke(call, access)
        self._note("knowledge.apply", access)
        receipt = self._receipt(result, "knowledge.apply")
        native = None
        if receipt.outcome == "applied":
            native = (
                await self.ipc.request(
                    {
                        "action": "readback",
                        "report": report,
                        "receiptId": receipt.nativeReceiptRef.id,
                        "effectKey": effect_key,
                        "decisionId": resolved.current.id,
                    }
                )
            )["native"]
        return {
            "report": report,
            "decision": resolved_document,
            "receipt": receipt.model_dump(mode="json"),
            "native": native,
            "use": use,
            "dispatched": True,
            "qualified": False,
            "origin": access.wire_origin().model_dump(mode="json"),
        }

    async def aieng_knowledge_read(self, operations: list[dict[str, Any]]) -> str:
        async with self._lock:
            try:
                args = KnowledgeReadInput.model_validate({"operations": operations})
                result = await self.ipc.request(
                    {
                        "action": "knowledge_read",
                        "operations": [op.model_dump(mode="json") for op in args.operations],
                        "actor": self._intent_context()["actor"]["id"],
                    }
                )
                snapshot = result["snapshot"]
                self.snapshots[snapshot["snapshotId"]] = snapshot
                return bounded_result(
                    {
                        "status": "read",
                        "snapshot": snapshot,
                        "content": result["results"],
                        "note": "Cite snapshot.snapshotId in aieng_ingest native_input.",
                    }
                )
            except Exception as error:
                return self._refusal("knowledge_read", error)

    async def aieng_ingest(
        self, report: dict[str, Any], native_input: dict[str, Any], mode: str = "preview"
    ) -> str:
        async with self._lock:
            stage = "native_input"
            state: dict[str, Any] | None = None
            try:
                args = AiengIngestInput.model_validate(
                    {"report": report, "native_input": native_input, "mode": mode}
                )
                state = self._reports.get(report.get("digest", ""))
                if state is None or state["report"] != report:
                    raise KnowledgeBridgeRefused(
                        "Report must come from this bridge's actual completed evaluations"
                    )
                if state["native_result"] is not None:
                    return state["native_result"]
                authored = args.native_input.model_dump(mode="json", exclude_none=True)
                fingerprint = sha256_digest(authored)
                if args.native_input.snapshotId not in self.snapshots:
                    raise KnowledgeBridgeRefused(
                        "snapshotId must come from aieng_knowledge_read in this mission"
                    )
                context = self._intent_context()
                state["native_context"] = self._current_native_context()
                if args.mode == "apply" and state.get("native_fingerprint") != fingerprint:
                    # Never seal or apply an effect the agent has not inspected in a preview.
                    return bounded_result(
                        {
                            "status": "refused",
                            "stage": "native_apply",
                            "recoverable": True,
                            "admitted": False,
                            "dispatched": False,
                            "report": report,
                            "feedback": "apply requires the identical native_input of the latest "
                            "successful preview; call aieng_ingest(mode='preview') first.",
                        }
                    )
                if args.mode == "preview":
                    stage = "native_preview"
                    access = await self._producer_access()
                    wire = access.wire_origin().model_dump(mode="json")
                    built = await self.ipc.request(
                        {
                            "action": "native_intent",
                            "report": report,
                            "snapshotId": args.native_input.snapshotId,
                            "context": context,
                            "origin": wire,
                            "input": {
                                key: authored[key]
                                for key in ("intentId", "subjects", "proposals", "claims", "notes")
                                if key in authored
                            },
                        }
                    )
                    if built.get("refused"):
                        state.pop("native_fingerprint", None)
                        return bounded_result(
                            {
                                "status": "refused",
                                "stage": "native_preview",
                                "recoverable": True,
                                "admitted": False,
                                "dispatched": False,
                                "report": report,
                                "content": built,
                                "repair": "Repair native_input from the details and preview again.",
                            }
                        )
                    assert self.lane is not None
                    try:
                        preview = await self.lane.gateway.plan_preview(
                            built["intent"],
                            access,
                            capability_pin=self._pin("knowledge_apply"),
                            governors=self._governors(),
                            request_key=f"aieng-preview-{uuid4().hex}",
                        )
                    except KnowledgeRefused as error:
                        self._note("knowledge.plan_preview", access)
                        state.pop("native_fingerprint", None)
                        return bounded_result(
                            {
                                "status": "refused",
                                "stage": "native_preview",
                                "recoverable": True,
                                "admitted": False,
                                "dispatched": False,
                                "report": report,
                                "content": {
                                    "refused": True,
                                    "code": "PLAN_PREVIEW_REFUSED",
                                    "message": str(error),
                                    "plan": built.get("plan"),
                                    "intent": built.get("intent"),
                                },
                                "repair": "Repair native_input from the details and preview again.",
                            }
                        )
                    self._note("knowledge.plan_preview", access)
                    previewed = {
                        "intent": built["intent"],
                        "preview": preview.model_dump(mode="json"),
                        "plan": built["plan"],
                        "reportBinding": built["reportBinding"],
                        "invocation_ref": access.invocation_ref,
                        "origin": wire,
                    }
                    state.update(native_fingerprint=fingerprint, native_preview=previewed)
                    if args.mode == "preview":
                        return bounded_result(
                            {
                                "status": "previewed",
                                "report": report,
                                "admitted": False,
                                "dispatched": False,
                                "qualified": False,
                                "content": {
                                    "plan": built["plan"],
                                    "preview": previewed["preview"],
                                    "reportBinding": built["reportBinding"],
                                },
                                "next": "If plan.errors is empty and outcomes are acceptable, call "
                                "aieng_ingest(mode='apply') with this identical native_input.",
                            }
                        )
                stage = "native_apply"
                access = await self._producer_access()
                prepared = state.get("native_preview")
                if prepared is None or prepared.get("invocation_ref") != access.invocation_ref:
                    # The intent binds the preview's originating origin: another attempt
                    # previews anew.
                    state.pop("native_fingerprint", None)
                    return bounded_result(
                        {
                            "status": "refused",
                            "stage": "native_apply",
                            "recoverable": True,
                            "admitted": False,
                            "dispatched": False,
                            "report": report,
                            "feedback": "the preview belongs to another invocation attempt; call "
                            "aieng_ingest(mode='preview') again in this attempt, then apply.",
                        }
                    )
                finalized = await self._finalize(report, prepared, access)
                state["finalized"] = finalized
                decision = finalized.get("decision", {})
                native = finalized.get("native") or {}
                receipt = finalized.get("receipt") or {}
                if (
                    not finalized.get("dispatched")
                    or decision.get("disposition") != "admitted"
                    or receipt.get("outcome") != "applied"
                ):
                    held = bounded_result(
                        {
                            "status": "held",
                            "report": report,
                            "qualified": False,
                            "content": finalized,
                        }
                    )
                    state["native_result"] = held
                    return held
                if not native.get("complete") or native.get("failures"):
                    raise KnowledgeBridgeRefused("Native apply returned no complete row readback")
                result = bounded_result(
                    {
                        "status": "native_applied",
                        "report": report,
                        "qualified": False,
                        "native_proof": {
                            "receipt_id": native["receiptId"],
                            "effect_key": receipt.get("effect", {}).get("effectKey"),
                            "entities_created": len(native["entities"]),
                            "claims_materialized": len(native["claims"]),
                            "affected_checked": native["affectedChecked"],
                            "affected_total": native["affectedTotal"],
                            "readback_complete": True,
                            "readback_failures": 0,
                        },
                        "content": finalized,
                    }
                )
                state["native_result"] = result
                return result
            except Exception as error:
                if stage == "native_apply" and state is not None:
                    # The refused effect stays fenced; a corrected input is a distinct new effect.
                    state.pop("native_fingerprint", None)
                    refusal = json.loads(self._refusal(stage, error, report))
                    refusal.update(
                        recoverable=True,
                        admitted=False,
                        dispatched=False,
                        repair="This exact effect was refused before commit and stays fenced; no "
                        "row was written. Correct native_input from the feedback (for a "
                        "constraint violation, supply the named typedPayload column from "
                        "evidence or drop that subject), preview again, then apply.",
                    )
                    return bounded_result(refusal)
                return self._refusal(stage, error, report)

    def _aidb_schema(self, args: AiengSchemaInput) -> str:
        if args.section == "guide":
            text, source = json.dumps(GUIDE, ensure_ascii=False, indent=2), "fixture-guide"
            raw = text.encode()
        else:
            path = {
                "entity_kinds": self.workspace / "vocabularies/taxonomy.entity_kind.md",
                "relationship_kinds": self.workspace / "vocabularies/taxonomy.relationship_kind.md",
                "ingestion_rules": self.workspace / "rules/ingestion-rules.v1.json",
                "relation": self.workspace / "relations" / f"{args.name}.md",
            }[args.section]
            if args.section == "relation" and not args.name:
                raise KnowledgeBridgeRefused("section='relation' requires name='<schema>/<table>'")
            if path.resolve().parent.parent != self.workspace and path.resolve().parent != (
                self.workspace / "vocabularies"
            ):
                if not path.resolve().is_relative_to(self.workspace):
                    raise KnowledgeBridgeRefused("Schema path escapes the AIDB workspace")
            raw = path.read_bytes()
            text, source = raw.decode("utf-8"), str(path.relative_to(self.workspace))
        start = min(args.offset_chars, len(text))
        end = min(start + args.max_chars, len(text))
        result = {
            "schema_source": source,
            "schema_sha256": bytes_digest(raw),
            "offset_chars": start,
            "next_offset_chars": end,
            "total_chars": len(text),
            "content": text[start:end],
        }
        while len(json.dumps(result, ensure_ascii=False)) > 16000 and end > start:
            end = start + (end - start) * 3 // 4
            result.update(next_offset_chars=end, content=text[start:end])
        return json.dumps(result, ensure_ascii=False)

    async def aieng_schema(
        self, section: str = "guide", name: str = "", offset_chars: int = 0, max_chars: int = 10000
    ) -> str:
        try:
            args = AiengSchemaInput.model_validate(
                {
                    "section": section,
                    "name": name,
                    "offset_chars": offset_chars,
                    "max_chars": max_chars,
                }
            )
            return await asyncio.to_thread(self._aidb_schema, args)
        except Exception as error:
            return self._refusal("schema", error)


@dataclass(frozen=True)
class AiengKnowledgeTools:
    bridge: AiengKnowledgeBridge
    tools: dict[str, BaseTool]
    definitions: dict[str, CapabilityDefinition]
    components: tuple[DeepAgentToolComponent, ...]
    bindings: dict[str, CapabilityComponentBinding]

    @property
    def worker(self) -> AiengKnowledgeBridge:
        return self.bridge

    @property
    def registry_tools(self) -> dict[str, BaseTool]:
        return {item.ref.digest: self.tools[item.tool_name] for item in self.components}


def build_aieng_knowledge_tools(
    process: subprocess.Popen[bytes],
    *,
    ready: Mapping[str, Any],
    evidence_dir: Path,
    ledger: SpendLedger,
    model_factory: Callable[..., Any] = evaluator_model,
    native_context: dict[str, Any] | None = None,
    attachment_target: str = "agent.main",
    timeout_seconds: float = 300,
    lane: Any | None = None,
) -> AiengKnowledgeTools:
    bridge = AiengKnowledgeBridge(
        QualiaKnowledgeIPC(process, timeout_seconds=timeout_seconds),
        ready=ready,
        evidence_dir=evidence_dir,
        ledger=ledger,
        model_factory=model_factory,
        native_context=native_context,
        lane=lane,
    )
    entries: tuple[tuple[str, type[BaseModel], str], ...] = (
        (
            "evidence_report_read",
            ReportReadInput,
            "Read exact frozen assertion/evidence/judgment metadata, full evaluation feedback or "
            "canonical assessment/census repair feedback (section='assessment') for a report "
            "actually evaluated by this bridge. RFC6901 pointers and character pagination; no new "
            "model, web or database write.",
        ),
        (
            "verify_evidence",
            AiengVerifyInput,
            "Submit 1..24 attributed engineering claims with unique exact quotes from registered "
            "page captures (capture_id from "
            "github_file/arxiv_abs/context7_docs/scrape/source_read). Each claim may add up to 3 "
            "additional_quotes from the same capture (8000 characters total). Qualifiers follow KS"
            " engineering.v2: set repositoryCommit (40-hex) for repository evidence, "
            "softwareVersion for releases and benchmarkEnvironment/denominator for reported "
            "results; leave unreported qualifiers null. Runs actual KS registration and separate "
            "Terra judge/Sol auditor evaluations. Returns an immutable report reference and repair"
            " feedback; does not admit any write. Use a fresh report id after any change.",
        ),
        (
            "aieng_knowledge_read",
            KnowledgeReadInput,
            "Bounded AI Engineer knowledge read (entity.resolve, entity.by_identifier, "
            "entity.card, entity.relationships, evidence.claims_for_entity, "
            "relationships.current_by_kind, vocab.relationship_kind, knowledge.head). Persists a "
            "read snapshot; its snapshotId is required by aieng_ingest.",
        ),
        (
            "aieng_ingest",
            AiengIngestInput,
            "Write verified AI Engineer knowledge for an evaluated report. mode='preview' returns "
            "the executor's plan (errors, rule checks, proposal outcomes) and exact effect digests "
            "with no write; mode='apply' requires the identical previewed native_input, then KS "
            "seals, decides on that exact effect, applies and the host reads rows back. Held or "
            "refused decisions write nothing. Read aieng_schema(section='guide') first.",
        ),
        (
            "aieng_schema",
            AiengSchemaInput,
            "Read the AI Engineer native-input guide, entity kinds, relationship kinds (with "
            "endpoint kinds), ingestion rules or one relation's columns (section='relation', "
            "name='corpus/library'). Character pagination; no database access or model call.",
        ),
    )
    tools: dict[str, BaseTool] = {}
    definitions: dict[str, CapabilityDefinition] = {}
    bindings: dict[str, CapabilityComponentBinding] = {}
    components: list[DeepAgentToolComponent] = []
    for name, schema, description in entries:
        tool = StructuredTool.from_function(
            coroutine=getattr(bridge, name), name=name, description=description, args_schema=schema
        )
        definition, component, binding = tool_capability(
            tool, f"tool.aieng.{name}", description, attachment_target
        )
        tools[name], definitions[definition.logical_id] = tool, definition
        components.append(component)
        bindings[definition.logical_id] = binding
    return AiengKnowledgeTools(bridge, tools, definitions, tuple(components), bindings)
