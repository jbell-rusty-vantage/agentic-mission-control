"""Real JSON-lines KS bridge for the owner-authorized Qualia experiment.

The producer authors claims and graph entities. The host supplies captured source bytes,
custody, exact frozen report fields, separate evaluator credentials, admission and dispatch.
No report is declared admitted by this adapter and no synthetic evaluator is installed.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

from jsonschema import Draft202012Validator
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field, model_validator
from scripts.overnight_evidence import redact
from tests.fixtures.qualia_runtime import SpendLedger, evaluator_model
from tests.fixtures.qualia_web_tools import (
    EvidenceCapture,
    SourceReadInput,
    WebToolRefused,
    bounded_result,
)

from mission_control.adapters.capabilities.capability_bundles import bytes_digest
from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION
from mission_control.adapters.deep_agents.materializer import tool_schema_digest
from mission_control.application.authoring.manifest_launch_inputs import CapabilityComponentBinding
from mission_control.contracts.identities import parse_request_scope
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    CapabilityDefinition,
    CapabilityKind,
    DefinitionKind,
    ExactDefinitionRef,
)
from mission_control.domain.execution.contracts import DeepAgentToolComponent

DEFAULT_BKS_ROOT = Path(__file__).resolve().parents[4] / "biotech/biotech-knowledge-services"
NATIVE_AUTHORIZATION = "owner-authorized-qualia-biotech-8032ec07"


class KnowledgeBridgeRefused(RuntimeError):
    """Failed real host boundary; never an accepting replacement receipt."""


class EvidenceSelectionRefused(KnowledgeBridgeRefused):
    def __init__(self, issues: list[dict[str, Any]], captures: list[dict[str, Any]]) -> None:
        super().__init__(
            "Capture selection or quote does not uniquely resolve; "
            "inspect all issues before retrying"
        )
        self.details = {"issues": issues, "available_captures": captures}


class NativeCaptureSelectionRefused(KnowledgeBridgeRefused):
    """Recoverable authored-input error before any native intent/finalization or dispatch."""

    def __init__(
        self,
        capture: dict[str, Any],
        authored: dict[str, Any],
        sources: list[RetainedSource],
    ) -> None:
        url = capture["canonicalUri"]
        eligible = [source for source in sources if source.url == url]
        super().__init__(
            "Native capture requires an exact capture_id evaluated for this URL; "
            "available IDs: " + ", ".join(source.record["capture_id"] for source in eligible)
        )
        references = {capture["ref"], *(locator["ref"] for locator in capture.get("locators", []))}
        referenced_paths: list[dict[str, str]] = []

        def visit(value: Any, path: str) -> None:
            if isinstance(value, str) and value in references:
                referenced_paths.append({"path": path, "ref": value})
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    visit(item, f"{path}/{index}")
            elif isinstance(value, dict):
                for key, item in value.items():
                    escaped = key.replace("~", "~0").replace("/", "~1")
                    visit(item, f"{path}/{escaped}")

        for key, value in authored.items():
            if key != "captures":
                visit(value, f"/{key}")
        self.details = {
            "issue": "native_capture_not_evaluated_or_ambiguous",
            "capture_ref": capture["ref"],
            "source_url": url,
            "requested_capture_id": capture.get("capture_id"),
            "allowed_capture_ids_for_url": [source.record["capture_id"] for source in eligible],
            "available_captures": [
                {
                    "capture_id": source.record["capture_id"],
                    "source_url": source.url,
                    "engine": source.record["capture_engine"],
                    "raw_sha256": source.record["raw_sha256"],
                    "text_sha256": bytes_digest(source.text.encode()),
                }
                for source in sources
            ],
            "referenced_paths": referenced_paths,
            "repair": (
                "Read the allowed evaluated snapshot with source_read before changing any "
                "locator. Never substitute a capture ID while retaining an unverified quote. "
                "An unused extra capture may be removed only when no references remain; "
                "otherwise repair every listed reference with a unique exact quote from an "
                "allowed evaluated snapshot. Include a distinct browser capture only when "
                "that exact browser ID is in this report's frozen evidence. Historical browser "
                "provenance remains retained, but does not confer native admission. Retry "
                "biotech_ingest with the same report and repaired native_input. If the facts "
                "cannot be supported within the evaluated snapshots, preserve the refusal."
            ),
        }


class QualiaKnowledgeIPC:
    """One request/response in flight; timeout permanently poisons this uncorrelated stream."""

    def __init__(self, process: subprocess.Popen[bytes], *, timeout_seconds: float = 60) -> None:
        self.process, self.timeout_seconds = process, timeout_seconds
        self._lock = asyncio.Lock()
        self._poisoned = False

    def _exchange(self, command: dict[str, Any]) -> dict[str, Any]:
        if self.process.stdin is None or self.process.stdout is None:
            raise KnowledgeBridgeRefused("Knowledge host pipes are unavailable")
        serialized = (json.dumps(command, ensure_ascii=False) + "\n").encode()
        if len(serialized) > 25_000_000:
            raise KnowledgeBridgeRefused("Knowledge IPC request exceeds capture quota")
        self.process.stdin.write(serialized)
        self.process.stdin.flush()
        raw = self.process.stdout.readline(8_000_001)
        if not raw.endswith(b"\n") or len(raw) > 8_000_000:
            raise KnowledgeBridgeRefused("Knowledge host closed or exceeded response quota")
        answer = json.loads(raw)
        if not isinstance(answer, dict):
            raise KnowledgeBridgeRefused("Knowledge host returned a non-object response")
        return answer

    async def request(self, command: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            if self._poisoned:
                raise KnowledgeBridgeRefused("Knowledge IPC is uncertain; host recovery required")
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(self._exchange, command),
                    self.timeout_seconds,
                )
            except BaseException:
                self._poisoned = True
                raise
            if "error" in result:
                raise KnowledgeBridgeRefused(str(redact(result["error"]))[:4000])
            return result


QualifierText = Annotated[str, Field(min_length=1, max_length=500)]


class ScientificClaimQualifiers(BaseModel):
    """Authorable subset of KS scientific.v2; profile/claimClass remain host-owned."""

    model_config = ConfigDict(extra="forbid", strict=True)
    entity: QualifierText | None = None
    population: QualifierText | None = None
    unit: QualifierText | None = None
    jurisdiction: QualifierText | None = None
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
    studyDesign: (  # noqa: N815 -- exact KS scientific.v2 spelling
        Literal[
            "randomized_controlled_trial",
            "cohort",
            "case_control",
            "cross_sectional",
            "case_report",
            "in_vitro",
            "animal",
            "analytical_validation",
            "systematic_review",
            "modeling",
            "other",
        ]
        | None
    ) = None
    species: QualifierText | None = None
    intervention: QualifierText | None = None
    comparator: QualifierText | None = None
    endpoint: QualifierText | None = None
    sampleSize: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991)  # noqa: N815
    effectMeasure: QualifierText | None = None  # noqa: N815
    followUp: QualifierText | None = None  # noqa: N815
    causalClaim: Literal["association", "causal", "none", "unknown"] = "unknown"  # noqa: N815


class AuthoredClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    statement: str = Field(min_length=5, max_length=4000)
    sourceUrl: str = Field(min_length=8, max_length=2048)  # noqa: N815 -- exact KS IPC spelling
    capture_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$", strict=True)] | None = None
    quote: str = Field(min_length=5, max_length=8000)
    additional_quotes: list[Annotated[str, Field(min_length=5, max_length=8000, strict=True)]] = (
        Field(default_factory=list, max_length=3, strict=True)
    )
    qualifiers: ScientificClaimQualifiers

    @model_validator(mode="after")
    def bounded_distinct_quotes(self) -> AuthoredClaim:
        quotes = [self.quote, *self.additional_quotes]
        if len(set(quotes)) != len(quotes):
            raise ValueError("Primary and additional quotes must be distinct")
        if sum(len(quote) for quote in quotes) > 8000:
            raise ValueError("Primary and additional quotes exceed 8000 total characters")
        return self


class VerifyEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    title: str = Field(min_length=5, max_length=500)
    summary: str = Field(min_length=10, max_length=4000)
    claims: list[AuthoredClaim] = Field(min_length=1, max_length=24)
    limitations: list[str] = Field(max_length=24)
    use: Literal["label_reference.ingredients", "research.summary"] = "research.summary"
    native_input: dict[str, Any] | None = None


class IngestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report: dict[str, Any]
    native_input: dict[str, Any] | None = None


class SchemaInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section: Literal["guide", "partial_schema", "canonical_schema", "native_vocabulary"] = "guide"
    json_pointer: str = Field(default="", max_length=500)
    offset_chars: int = Field(default=0, ge=0, le=500000)
    max_chars: int = Field(default=10000, ge=1, le=12000)


class ReportReadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    section: Literal["frozen", "evaluations", "assessment"] = "frozen"
    json_pointer: str = Field(default="", max_length=400)
    offset_chars: int = Field(default=0, ge=0, le=8_000_000)
    max_chars: int = Field(default=10000, ge=1, le=12000)


@dataclass(frozen=True)
class RetainedSource:
    url: str
    title: str
    text: str
    record: dict[str, Any]

    @property
    def native_fields(self) -> dict[str, str]:
        browser = self.record["capture_engine"] == "agent_browser_page"
        return {
            "captureMethod": "http-capture/agent-browser-retained-v1"
            if browser
            else "http-capture/qualia-rest-retained-v1",
            "hashBasis": "STORED_EXCERPT_TEXT" if browser else "TOOL_RENDITION",
            "completeness": "PARTIAL_EXCERPT" if browser else "UNKNOWN",
        }


class QualiaKnowledgeBridge:
    # Domain hooks: the AI Engineer bridge subclasses these; Qualia's values are unchanged.
    application_id = "biotech"
    verify_input_model: type[BaseModel] = VerifyEvidenceInput
    ingest_tool = "biotech_ingest"

    def __init__(
        self,
        ipc: QualiaKnowledgeIPC,
        *,
        ready: Mapping[str, Any],
        evidence_dir: Path,
        ledger: SpendLedger,
        bks_root: Path = DEFAULT_BKS_ROOT,
        model_factory: Callable[..., Any] = evaluator_model,
        native_context: dict[str, Any] | None = None,
    ) -> None:
        self.ipc, self.ledger, self.model_factory = ipc, ledger, model_factory
        self.evidence = EvidenceCapture(evidence_dir)
        self.bks_root = bks_root.resolve()
        self.roles = dict(ready["roles"])
        actors = [self.roles[role] for role in ("producer", "judge", "auditor")]
        if (
            not ready.get("ready")
            or len({actor["subject"] for actor in actors}) != 3
            or len({actor["invocationId"] for actor in actors}) != 3
            or any(actor["applicationId"] != self.application_id for actor in actors)
        ):
            raise KnowledgeBridgeRefused(
                f"Separate authenticated {self.application_id} evaluator roles required"
            )
        self.native_context = native_context
        self._reports: dict[str, dict[str, Any]] = {}
        self._report_ids: dict[str, str] = {}
        self._lock = asyncio.Lock()

    @property
    def results(self) -> tuple[dict[str, Any], ...]:
        """Actual driver observations, excluding retained source text and credentials."""
        return tuple(
            {
                "report": dict(state["report"]),
                "verification": json.loads(state["response"]),
                "assessment": state.get("assessment"),
                "native": None
                if state["native_result"] is None
                else json.loads(state["native_result"]),
                "dispatch": state.get("finalized"),
                "native_context": state.get("native_context"),
            }
            for state in self._reports.values()
        )

    def mc_installation_id(self, producer: Mapping[str, Any]) -> str:
        """The MC installation an invocation must belong to; Qualia's KS shares it."""
        return str(producer["installationId"])

    def _current_native_context(self) -> dict[str, Any]:
        if self.native_context is not None:  # Explicit trusted offline/test override only.
            return self.native_context
        live = CURRENT_INVOCATION.get()
        if live is None or live.evaluator:
            raise KnowledgeBridgeRefused(
                "Native ingestion requires the current producer invocation"
            )
        scope, producer = parse_request_scope(live.request_scope), self.roles["producer"]
        if (
            scope.application_id != self.application_id
            or str(scope.installation_id) != self.mc_installation_id(producer)
            or str(scope.tenant_id) != producer["tenantId"]
        ):
            raise KnowledgeBridgeRefused("Native invocation scope differs from the actual KS host")
        return {
            "actor": {
                "kind": "agent",
                "id": f"{live.run_id}:{live.operation_id}",
                "model": "gpt-6.1-sol",
            },
            "run": {
                "system": "mission-control",
                "runId": live.run_id,
                "operationId": live.operation_id,
                "attempt": live.operation_attempt,
            },
            "activityKind": "INGESTION",
            "operationKind": "knowledge.ingestion_apply",
        }

    def _sources(self, url: str) -> list[RetainedSource]:
        self.evidence.policy.allowed_url(url)
        candidates = []
        for path in self.evidence.directory.glob("*.json"):
            if len(path.stem) != 32 or path.stat().st_size > 32000:
                continue
            try:
                record = json.loads(path.read_bytes())
                request = record.get("requested_url")
                if request == url or (isinstance(request, list) and url in request):
                    candidates.append(record)
            except (ValueError, TypeError, OSError):
                continue
        candidates.sort(key=lambda row: row.get("capture_id", ""))
        sources = []
        for record in candidates:
            try:
                checked = json.loads(
                    self.evidence.read_source(
                        SourceReadInput(capture_id=record["capture_id"], max_chars=1),
                    )
                )
                raw = (
                    self.evidence.directory / f"{record['capture_id']}.response.bin"
                ).read_bytes()
                if bytes_digest(raw) != checked["evidence"]["raw_sha256"]:
                    raise KnowledgeBridgeRefused("Source changed during custody transfer")
                text, title = self.evidence.page(record, json.loads(raw))
                if bytes_digest(text.encode()) != checked["source_document_sha256"]:
                    raise KnowledgeBridgeRefused("Parsed source changed during custody transfer")
                sources.append(RetainedSource(url, str(title)[:500], text, checked["evidence"]))
            except (WebToolRefused, ValueError, KeyError, TypeError, OSError):
                continue
        return sources

    def _source(self, url: str, capture_id: str | None = None) -> RetainedSource:
        sources = self._sources(url)
        selected = [s for s in sources if s.record["capture_id"] == capture_id]
        if capture_id is not None and len(selected) == 1:
            return selected[0]
        if capture_id is None and len(sources) == 1:
            return sources[0]
        raise KnowledgeBridgeRefused(
            "Select an exact verified registered capture_id for this URL; available IDs: "
            + ", ".join(source.record["capture_id"] for source in sources)
        )

    def _claim_sources(
        self, claims: list[AuthoredClaim]
    ) -> tuple[dict[str, RetainedSource], dict[str, str]]:
        by_url = {url: self._sources(url) for url in sorted({c.sourceUrl for c in claims})}
        selected: dict[str, RetainedSource] = {}
        claim_sources: dict[str, str] = {}
        issues: list[dict[str, Any]] = []
        for claim in claims:
            candidates = by_url[claim.sourceUrl]
            matching = (
                [s for s in candidates if s.record["capture_id"] == claim.capture_id]
                if claim.capture_id is not None
                else candidates
            )
            if len(matching) != 1:
                issues.append(
                    {
                        "claim_id": claim.id,
                        "capture_id": claim.capture_id,
                        "sourceUrl": claim.sourceUrl,
                        "error": "capture_id_unavailable_for_url"
                        if claim.capture_id is not None
                        else "capture_id_required"
                        if matching
                        else "no_verified_capture",
                    }
                )
                continue
            source = matching[0]
            chosen_id = source.record["capture_id"]
            mismatches = []
            for index, quote in enumerate([claim.quote, *claim.additional_quotes]):
                start = source.text.find(quote)
                if start < 0 or start != source.text.rfind(quote):
                    mismatches.append(index)
            if mismatches:
                issues.append(
                    {
                        "claim_id": claim.id,
                        "capture_id": chosen_id,
                        "sourceUrl": claim.sourceUrl,
                        "error": "quote_does_not_uniquely_resolve",
                        "quote_indices": mismatches,
                    }
                )
            selected[chosen_id], claim_sources[claim.id] = source, chosen_id
        if issues:
            available = [
                {
                    "capture_id": source.record["capture_id"],
                    "engine": source.record["capture_engine"],
                    "sourceUrl": url,
                }
                for url, sources in by_url.items()
                for source in sources
            ]
            raise EvidenceSelectionRefused(issues, available)
        return selected, claim_sources

    async def _put_source(self, source: RetainedSource) -> RetainedSource:
        result = await self.ipc.request(
            {
                "action": "capture",
                "captureId": source.record["capture_id"],
                "sourceUrl": source.url,
                "text": source.text,
                "title": source.title,
                "mediaType": "text/markdown",
                "completeness": "partial"
                if source.record["capture_engine"] == "agent_browser_page"
                else "unknown",
            }
        )
        if (
            result.get("ref", {}).get("digest") != bytes_digest(source.text.encode())
            or result.get("captureId") != source.record["capture_id"]
            or result.get("sourceUrl") != source.url
        ):
            raise KnowledgeBridgeRefused(
                "KS custody returned a different capture identity or digest"
            )
        return source

    @staticmethod
    def _response_text(message: Any) -> str:
        content = message.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                part if isinstance(part, str) else part.get("text", "")
                for part in content
                if isinstance(part, str) or (isinstance(part, dict) and part.get("type") == "text")
            )
        raise KnowledgeBridgeRefused("Evaluator returned no actual JSON text")

    async def _evaluate(self, role: str, report: dict[str, Any]) -> dict[str, Any]:
        request = await self.ipc.request({"action": "eval_request", "role": role, "report": report})
        context = request["context"]
        if context["role"] != role or context["report"] != report:
            raise KnowledgeBridgeRefused(
                "Isolated evaluator context names another role or revision"
            )
        model_id = "gpt-6.1-terra" if role == "judge" else "gpt-6.1-sol"
        model = self.model_factory(self.ledger, role=role, model_id=model_id)
        evaluator = model.with_structured_output(
            {"name": f"qualia_{role}", "schema": request["json_schema"], "strict": True},
            method="json_schema",
            strict=True,
            include_raw=True,
        )
        # Never add producer history, a prior judgment, or a fabricated factual inventory.
        result = await evaluator.ainvoke(
            [
                SystemMessage(content=request["prompt"]),
                HumanMessage(content=json.dumps({"context": context, "body": request["body"]})),
            ]
        )
        if result.get("parsing_error") is not None or result.get("raw") is None:
            raise KnowledgeBridgeRefused("Actual evaluator JSON could not be parsed")
        message = result["raw"]
        raw_text = self._response_text(message)
        answer = json.loads(raw_text)
        Draft202012Validator(request["json_schema"]).validate(answer)
        if result.get("parsed") != answer:
            raise KnowledgeBridgeRefused("Parsed evaluation differs from actual model JSON")
        usage = message.usage_metadata
        if (
            not usage
            or not all(
                isinstance(usage.get(k), int) and usage[k] >= 0
                for k in ("input_tokens", "output_tokens")
            )
            or usage["input_tokens"] + usage["output_tokens"] < 1
        ):
            raise KnowledgeBridgeRefused("Actual evaluator token usage is required")
        factor = Decimal("0.5") if role == "judge" else Decimal(1)
        cost = (
            factor
            * (
                Decimal(usage["input_tokens"]) * Decimal("2.5")
                + Decimal(usage["output_tokens"]) * 10
            )
            / 1_000_000
        )
        # KS accepts six fractional USD digits. Round upward only at that wire
        # boundary; the observer ledger and exact estimate retain their precision.
        ks_cost = cost.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
        observed = await self.ipc.request(
            {
                "action": "eval_submit",
                "role": role,
                "report": report,
                "model": model_id,
                "answer": answer,
                "rawResponse": raw_text,
                "usage": {
                    "providerCalls": 1,
                    "tokens": usage["input_tokens"] + usage["output_tokens"],
                    "costUsd": format(ks_cost, "f"),
                },
            }
        )
        if "result" not in observed:
            raise KnowledgeBridgeRefused("KS returned no observation receipt")
        return {
            "role": role,
            "model": model_id,
            "answer": answer,
            "receipt": observed["result"],
            "usage": usage,
            "cost_usd_upper_estimate": format(cost, "f"),
            "ks_cost_usd_upper_estimate": format(ks_cost, "f"),
        }

    async def _prepare_registration(
        self, prepared_input: dict[str, Any]
    ) -> tuple[dict[str, Any], Any]:
        """The host-prepared ``research-report/v2`` registration and its producer context.

        Qualia: the host's own producer role (``None``). The AI Engineer bridge overrides this
        with Mission Control's located invocation access (provenance slice 2)."""

        prepared = await self.ipc.request({"action": "prepare_report", "input": prepared_input})
        return prepared["registration"], None

    async def _register_report(
        self, registration: dict[str, Any], report_id: str, producer: Any
    ) -> dict[str, Any]:
        """Register the prepared report; answers its immutable report reference."""

        registered = await self.ipc.request(
            {
                "action": "call",
                "request": {
                    "actor": "producer",
                    "operation": "report.register",
                    "nativeContract": {"name": "research-report", "version": "v2"},
                    "payload": registration,
                    "requestId": f"{report_id}:register",
                },
            }
        )
        return registered["result"]["nativeReceiptRef"]

    @staticmethod
    def _refusal(stage: str, error: Exception, report: dict[str, Any] | None = None) -> str:
        native_capture = isinstance(error, NativeCaptureSelectionRefused)
        return bounded_result(
            {
                "status": "refused",
                "stage": stage,
                "report": report,
                "qualified": False,
                "error_type": type(error).__name__,
                "feedback": str(redact(str(error)))[:4000],
                "content": error.details
                if isinstance(error, (EvidenceSelectionRefused, NativeCaptureSelectionRefused))
                else {},
                **(
                    {
                        "recoverable": True,
                        "retry_tool": "biotech_ingest",
                        "required_action": "repair_native_input_and_retry",
                        "admitted": False,
                        "dispatched": False,
                        "native_input_frozen": False,
                    }
                    if native_capture
                    else {}
                ),
                "repair": (
                    "Repair the native capture/reference selection using "
                    "content.available_captures "
                    "and retry biotech_ingest; this is not an applied ingestion result."
                    if native_capture
                    else "Correct source capture, quote, qualifiers, report or native schema; do "
                    "not invent receipts."
                ),
            }
        )

    async def verify_evidence(
        self,
        id: str,  # noqa: A002 -- exact KS AuthoredReport contract spelling
        title: str,
        summary: str,
        claims: list[dict[str, Any]],
        limitations: list[str],
        use: str = "research.summary",
        native_input: dict[str, Any] | None = None,
    ) -> str:
        async with self._lock:
            stage, report = "capture", None
            try:
                authored = self.verify_input_model.model_validate(
                    {
                        "id": id,
                        "title": title,
                        "summary": summary,
                        "claims": claims,
                        "limitations": limitations,
                        "use": use,
                        "native_input": native_input,
                    }
                )
                fingerprint = sha256_digest(authored.model_dump(mode="json"))
                if id in self._report_ids:
                    previous = self._reports[self._report_ids[id]]
                    if previous["fingerprint"] != fingerprint:
                        raise KnowledgeBridgeRefused(
                            "Changed report content requires a fresh report id"
                        )
                    return previous["response"]
                if len({claim.id for claim in authored.claims}) != len(authored.claims):
                    raise KnowledgeBridgeRefused("Report claim ids must be unique")
                sources, claim_sources = await asyncio.to_thread(
                    self._claim_sources, authored.claims
                )
                for source in sources.values():
                    await self._put_source(source)
                prepared_input = authored.model_dump(mode="json", exclude={"native_input"})
                for claim in prepared_input["claims"]:
                    # Pin even a legacy unambiguous URL to the actual selected snapshot.
                    claim["capture_id"] = claim_sources[claim["id"]]
                stage = "prepare_report"
                registration, producer = await self._prepare_registration(prepared_input)
                stage = "report.register"
                report = await self._register_report(registration, id, producer)
                if report.get("kind") != "report" or not report.get("digest", "").startswith(
                    "sha256:"
                ):
                    raise KnowledgeBridgeRefused("KS returned no actual immutable report reference")
                evaluations = []
                for role in ("judge", "auditor"):
                    stage = f"{role}_evaluation"
                    evaluations.append(await self._evaluate(role, report))
                stage = "assessment_preview"
                assessment = await self.ipc.request(
                    {"action": "assessment_preview", "report": report}
                )
                if (
                    assessment.get("schema") != "qualia-assessment-preview.v1"
                    or assessment.get("report") != report
                    or assessment.get("assessment", {}).get("report") != report
                    or assessment.get("admitted") is not False
                    or assessment.get("qualified") is not False
                    or assessment.get("dispatched") is not False
                    or type(assessment.get("assessment", {}).get("aggregate", {}).get("complete"))
                    is not bool
                ):
                    raise KnowledgeBridgeRefused(
                        "Assessment preview is not exact read-only report feedback"
                    )
                response = bounded_result(
                    {
                        "status": "evaluated",
                        "report": report,
                        "admitted": False,
                        "qualified": False,
                        "assessment_complete": assessment["assessment"]["aggregate"]["complete"],
                        "assessment_feedback_section": "assessment",
                        "source_captures": [
                            {
                                "capture_id": key,
                                "source_url": source.url,
                                "raw_sha256": source.record["raw_sha256"],
                                "text_sha256": bytes_digest(source.text.encode()),
                                "engine": source.record["capture_engine"],
                            }
                            for key, source in sources.items()
                        ],
                        "content": {
                            "evaluations": evaluations,
                            "assessment": assessment,
                            "next": (
                                "Read section='assessment' with evidence_report_read for exact "
                                "canonical holds and census differences. Repair every held "
                                "claim/occurrence with a fresh report id before ingestion. "
                                "This preview neither seals nor admits; exact-use admission "
                                f"occurs in {self.ingest_tool}."
                            ),
                        },
                    }
                )
                self._reports[report["digest"]] = {
                    "report": report,
                    "fingerprint": fingerprint,
                    "response": response,
                    "native_input": native_input,
                    "source_urls": {c.sourceUrl for c in authored.claims},
                    "sources": sources,
                    "claim_sources": claim_sources,
                    "evaluations": evaluations,
                    "assessment": assessment,
                    "native_result": None,
                }
                self._report_ids[id] = report["digest"]
                return response
            except Exception as error:
                return self._refusal(stage, error, report)

    async def _native_admission(
        self,
        state: dict[str, Any],
        report: dict[str, Any],
        authored: dict[str, Any],
    ) -> dict[str, Any]:
        allowed = {
            "intentId",
            "context",
            "captures",
            "subjects",
            "subjectEvidence",
            "proposals",
            "about",
            "reportProjection",
        }
        if set(authored) - allowed:
            raise KnowledgeBridgeRefused("native_input contains host-owned or unknown fields")
        transformed = {**authored, "context": self._current_native_context()}
        state["native_context"] = transformed["context"]
        captures = []
        for capture in authored["captures"]:
            if set(capture) - {
                "ref",
                "canonicalUri",
                "title",
                "captureMethod",
                "hashBasis",
                "completeness",
                "locators",
                "capture_id",
            }:
                raise KnowledgeBridgeRefused(
                    "Native capture bytes, custody and times are host-owned"
                )
            url = self.evidence.policy.allowed_url(capture["canonicalUri"])
            candidates = [source for source in state["sources"].values() if source.url == url]
            if not candidates:
                raise NativeCaptureSelectionRefused(
                    capture, authored, list(state["sources"].values())
                )
            selected_id = capture.get("capture_id")
            if selected_id is not None:
                SourceReadInput(capture_id=selected_id, max_chars=1)
                candidates = [s for s in candidates if s.record["capture_id"] == selected_id]
            if len(candidates) != 1:
                raise NativeCaptureSelectionRefused(
                    capture, authored, list(state["sources"].values())
                )
            source = candidates[0]
            checked = json.loads(
                await asyncio.to_thread(
                    self.evidence.read_source,
                    SourceReadInput(capture_id=source.record["capture_id"], max_chars=1),
                )
            )
            if (
                checked["source_document_sha256"] != bytes_digest(source.text.encode())
                or checked["evidence"]["raw_sha256"] != source.record["raw_sha256"]
            ):
                raise KnowledgeBridgeRefused("Native evidence differs from evaluated source bytes")
            await self._put_source(source)
            captures.append(
                {
                    **{key: value for key, value in capture.items() if key != "capture_id"},
                    "captureId": source.record["capture_id"],
                    "title": source.title,
                    **source.native_fields,
                }
            )
        transformed["captures"] = captures
        built = await self.ipc.request(
            {"action": "native_intent", "report": report, "input": transformed}
        )
        if "intent" not in built or "boundEffectDigest" not in built:
            raise KnowledgeBridgeRefused("KS returned no exact bound native intent")
        return await self.ipc.request(
            {
                "action": "finalize_report",
                "report": report,
                "intent": built["intent"],
            }
        )

    async def biotech_ingest(
        self, report: dict[str, Any], native_input: dict[str, Any] | None = None
    ) -> str:
        async with self._lock:
            stage = "native_input"
            try:
                state = self._reports.get(report.get("digest", ""))
                if state is None or state["report"] != report:
                    raise KnowledgeBridgeRefused(
                        "Report must come from this bridge's actual completed evaluations"
                    )
                current = self._current_native_context()
                if state.get("native_context") is not None:
                    original = state["native_context"]["run"]
                    if any(
                        original.get(key) != current["run"].get(key)
                        for key in ("runId", "operationId")
                    ):
                        raise KnowledgeBridgeRefused(
                            "Native receipt belongs to another run/operation; "
                            "evaluate a fresh report"
                        )
                authored = native_input if native_input is not None else state["native_input"]
                if not isinstance(authored, dict):
                    raise KnowledgeBridgeRefused(
                        "Agent-authored native_input is required; use biotech_schema"
                    )
                fingerprint = sha256_digest(authored)
                if state.get("native_fingerprint") not in (None, fingerprint):
                    raise KnowledgeBridgeRefused(
                        "Native input changed after finalization; use a new report"
                    )
                if state["native_result"] is not None:
                    return state["native_result"]
                stage = "native_admission"
                finalized = state.get("finalized")
                if finalized is None:
                    finalized = await self._native_admission(state, report, authored)
                    state.update(finalized=finalized, native_fingerprint=fingerprint)
                decision = finalized.get("decision", {})
                if (
                    not finalized.get("dispatched")
                    or decision.get("disposition") != "admitted"
                    or decision.get("admissibility", {}).get("status") != "admitted"
                    or decision.get("reviewPending") is not False
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
                if decision.get("report") != report or decision.get("subject") != report:
                    raise KnowledgeBridgeRefused("Admission names another frozen report")
                stage = "consume"
                consumed = await self.ipc.request(
                    {
                        "action": "consume",
                        "effectKey": finalized["effectKey"],
                        "authorization": NATIVE_AUTHORIZATION,
                    }
                )
                native = consumed.get("native", {})
                pages = native.get("pages", [])
                if (
                    native.get("receipt", {}).get("outcome") not in {"applied", "duplicate", "noop"}
                    or not pages
                    or pages[-1].get("complete") is not True
                    or pages[-1].get("nextCursor") is not None
                    or any(
                        page.get("failures")
                        or any(not item.get("ok") for item in page.get("items", []))
                        for page in pages
                    )
                ):
                    raise KnowledgeBridgeRefused("Native consume returned no receipt/readback")
                receipt, proof = native["receipt"], native["proof"]
                checked = sum(page["checked"] for page in pages)
                if (
                    native["acknowledgement"].get("acknowledged") is not True
                    or receipt["effect"]["effectKey"] != finalized["effectKey"]
                    or checked != receipt["effects"]["total"]
                    or checked != proof["checkedEffects"]
                    or not proof["requiredSubjectUids"]
                ):
                    raise KnowledgeBridgeRefused(
                        "Native proof summary differs from acknowledged readback"
                    )
                result = bounded_result(
                    {
                        "status": "native_applied",
                        "report": report,
                        "qualified": False,
                        "native_proof": {
                            "receipt_id": receipt["receiptId"],
                            "effect_key": receipt["effect"]["effectKey"],
                            "acknowledged": True,
                            "total_effects": receipt["effects"]["total"],
                            "checked_effects": checked,
                            "readback_complete": True,
                            "readback_failures": 0,
                            "verified_subject_uids": proof["requiredSubjectUids"],
                        },
                        "content": {"admission": finalized, **consumed},
                    }
                )
                state.update(native_result=result, native_fingerprint=fingerprint)
                return result
            except Exception as error:
                return self._refusal(stage, error, report)

    def _schema(self, args: SchemaInput) -> str:
        paths = {
            "partial_schema": self.bks_root / "scripts/fixtures/qualia/partial-schema.json",
            "native_vocabulary": self.bks_root / "scripts/fixtures/qualia/native-vocabulary.json",
            "canonical_schema": self.bks_root
            / "packages/contracts/json-schema/biotech-knowledge-intent.v2.json",
        }
        if args.section == "guide":
            canonical = json.loads(paths["canonical_schema"].read_bytes())
            guide = {
                "purpose": (
                    "Agent authors actual entities, sourced fields, locators and proposals. "
                    "Host supplies capture bytes/time/custody, context and frozen report; KS "
                    "policy decides admission."
                ),
                "canonical_top_level_fields": list(canonical["properties"]),
                "canonical_required": canonical["required"],
                "minimal_property_examples_from_pinned_release": {
                    "Product": {"productKind": "DIETARY_SUPPLEMENT"},
                    "ChemicalSubstance": {"substanceClass": "CHEMICAL"},
                    "IngredientMaterial": {"materialKind": "BOTANICAL_PREPARATION"},
                    "Organization": {},
                    "Person": {
                        "privacyClass": "PUBLIC",
                        "publicActorBasis": ["AUTHOR_OR_INVESTIGATOR"],
                    },
                },
                "property_example_scope": (
                    "These are schema vocabulary examples from D1/D6/D7, not classifications of "
                    "any particular entity. Choose only values justified by source evidence. "
                    "BOTANICAL_PREPARATION is for a botanical material; CHEMICALLY_DEFINED, "
                    "MICROBIAL_PREPARATION, MATERIAL_MIXTURE, PROTEIN_OR_ENZYME, UNRESOLVED "
                    "and OTHER are other MaterialKind values. A named public study author's "
                    "publicActorBasis can be AUTHOR_OR_INVESTIGATOR only when actually sourced."
                ),
                "schema_navigation": (
                    "biotech_schema(section='canonical_schema',json_pointer='/properties/subjects')"
                    " returns exact canonical fields; paginate offset_chars or use a more "
                    "specific JSON pointer. Native registered predicates, node properties and "
                    "enum values are in section='native_vocabulary', with pointers such as "
                    "'/nodes/StudyResult', '/predicates/LEGAL_NAME' and "
                    "'/relationships/DECLARES_COMPONENT'. Never invent a predicate."
                ),
                "verified_report_projection": (
                    "Read evidence_report_read(report_digest=<actual report digest>, "
                    "section='frozen', json_pointer='/assertions') for actual immutable assertion "
                    "IDs, propositions, qualifiers and evidence. Include reportProjection: "
                    "{primaryAssertionId:<a chosen benefit/study assertion ID>, claims:["
                    "{assertionId:<actual ID>,claimRef:<unique local ref>,claimType:<registered "
                    "ClaimType enum>},...]} covering every frozen assertion once. The trusted "
                    "builder copies actual propositions into Claims and actual KS judgments into "
                    "PROPOSED VETTING Assessments. One graph evidence report assesses the selected "
                    "primary Claim and cites the assessments, retaining the full frozen KS bundle "
                    "as context. This makes no clinical-certainty or world-truth promotion. "
                    "Do not author replacement judgments, synthetic predicates or report.publish. "
                    "Include every frozen evidence captureId as a native capture with capture_id "
                    "and its exact canonicalUri. Do not add other snapshots just because they "
                    "were acquired or mentioned upstream: distinct browser capture is included "
                    "only if that exact browser ID occurs in this frozen report's evidence. "
                    "The trusted builder creates support locators "
                    "from actual frozen evidence; do not copy those quotes into invented records. "
                    "Supply your own exact source locators for authored entity fields and other "
                    "domain proposals. Choose ClaimType from the registered enum; use OTHER "
                    "when no more specific classification is justified."
                ),
                "native_capture_repair": (
                    "Use only exact evaluated IDs from verify_evidence.source_captures and "
                    "evidence_report_read(section='frozen',json_pointer='/assertions'). "
                    "A native_admission capture-selection refusal is recoverable before "
                    "finalization. Read its report-bound allowed IDs and referenced_paths. "
                    "Remove an unused extra capture only after resolving all references; for "
                    "a referenced locator, source_read an allowed snapshot and author a unique "
                    "exact quote supporting the same fact. Never auto-rebind IDs or quote bytes. "
                    "Retry biotech_ingest with the same report and corrected native_input. "
                    "Do not treat this refusal as an applied graph write or successful ingress."
                ),
                "native_input_example": {
                    "intentId": "author-a-unique-intent-id",
                    "captures": [
                        {
                            "ref": "label",
                            "canonicalUri": "https://www.qualialife.com/shop/qualia-nad",
                            "capture_id": "COPY_ACTUAL_EVALUATED_CAPTURE_ID",
                            "title": "HOST_OVERRIDES_FROM_CAPTURE",
                            "locators": [
                                {
                                    "ref": "product-name-quote",
                                    "exact": "AUTHOR_UNIQUE_EXACT_CAPTURE_QUOTE",
                                    "reportsFields": ["Product.name", "Product.marketedName"],
                                }
                            ],
                        }
                    ],
                    "subjects": [
                        {
                            "ref": "product",
                            "mode": "new",
                            "nodeType": "Product",
                            "name": "AUTHOR_ACTUAL_CAPTURED_PRODUCT_NAME",
                            "properties": {
                                "productKind": "DIETARY_SUPPLEMENT",
                                "marketedName": "AUTHOR_ACTUAL_CAPTURED_PRODUCT_NAME",
                            },
                            "onMatch": "use_existing",
                        }
                    ],
                    "subjectEvidence": {"product": ["product-name-quote"]},
                    "proposals": [],
                    "about": ["product"],
                },
                "rules": [
                    "Example strings are placeholders, never evidence or facts.",
                    (
                        "Every new subject needs subjectEvidence pointing to unique exact "
                        "captured quotes."
                    ),
                    (
                        "Every factual proposal needs captured locator evidence. Use "
                        "canonical proposal fields, not invented predicates."
                    ),
                    (
                        "Captures may only use snapshots evaluated by verify_evidence. Set "
                        "fixture selector capture_id to the exact evaluated registered ID; "
                        "it is stripped before the canonical Biotech builder. URL-only legacy "
                        "selection requires one evaluated snapshot. Capture method/hash "
                        "basis/completeness are host-derived."
                    ),
                    (
                        "native_input excludes report, pins, sources, bytes, storageUri and "
                        "retrievedAt; the real builder supplies them."
                    ),
                    (
                        "Person requires PUBLIC privacyClass and publicActorBasis. Keep "
                        "funding/limits and formulation versions explicit."
                    ),
                    (
                        "verify_evidence is evaluation, not admission. biotech_ingest returns"
                        " held/refused feedback unless actual exact-use admission and graph "
                        "readback succeed."
                    ),
                ],
                "partial_schema": json.loads(paths["partial_schema"].read_bytes()),
            }
            raw, value = json.dumps(guide, ensure_ascii=False).encode(), guide
            source = "fixture-guide-derived-from-native-intent.test.ts-and-canonical-schema"
        else:
            raw = paths[args.section].read_bytes()
            value, source = json.loads(raw), str(paths[args.section])
        if args.json_pointer:
            if not args.json_pointer.startswith("/"):
                raise KnowledgeBridgeRefused("Schema pointer must be an RFC6901 JSON pointer")
            for part in args.json_pointer[1:].split("/"):
                key = part.replace("~1", "/").replace("~0", "~")
                value = value[int(key)] if isinstance(value, list) else value[key]
        text = json.dumps(value, ensure_ascii=False, indent=2)
        start, end = (
            min(args.offset_chars, len(text)),
            min(args.offset_chars + args.max_chars, len(text)),
        )
        result = {
            "schema_source": source,
            "schema_sha256": bytes_digest(raw),
            "json_pointer": args.json_pointer,
            "offset_chars": start,
            "next_offset_chars": end,
            "total_chars": len(text),
            "content": text[start:end],
        }
        while len(json.dumps(result, ensure_ascii=False)) > 16000 and end > start:
            end = start + (end - start) * 3 // 4
            result.update(next_offset_chars=end, content=text[start:end])
        return json.dumps(result, ensure_ascii=False)

    async def biotech_schema(
        self,
        section: str = "guide",
        json_pointer: str = "",
        offset_chars: int = 0,
        max_chars: int = 10000,
    ) -> str:
        try:
            args = SchemaInput.model_validate(
                {
                    "section": section,
                    "json_pointer": json_pointer,
                    "offset_chars": offset_chars,
                    "max_chars": max_chars,
                }
            )
            return await asyncio.to_thread(self._schema, args)
        except Exception as error:
            return self._refusal("schema", error)

    async def evidence_report_read(
        self,
        report_digest: str,
        section: str = "frozen",
        json_pointer: str = "",
        offset_chars: int = 0,
        max_chars: int = 10000,
    ) -> str:
        """Read exact host records without squeezing the full evidence into a preview."""
        async with self._lock:
            try:
                args = ReportReadInput.model_validate(
                    {
                        "report_digest": report_digest,
                        "section": section,
                        "json_pointer": json_pointer,
                        "offset_chars": offset_chars,
                        "max_chars": max_chars,
                    }
                )
                state = self._reports.get(args.report_digest)
                if state is None:
                    raise KnowledgeBridgeRefused("Report was not evaluated by this bridge")
                if args.section == "frozen" and "frozen" not in state:
                    result = await self.ipc.request({"action": "frozen", "report": state["report"]})
                    frozen = result["frozen"]
                    if frozen.get("reportRevisionId") != state["report"]["id"]:
                        raise KnowledgeBridgeRefused(
                            "Frozen metadata names another report revision"
                        )
                    state["frozen"] = frozen
                value = state[args.section]
                if args.json_pointer:
                    if not args.json_pointer.startswith("/"):
                        raise KnowledgeBridgeRefused(
                            "Report pointer must be an RFC6901 JSON pointer"
                        )
                    for part in args.json_pointer[1:].split("/"):
                        key = part.replace("~1", "/").replace("~0", "~")
                        value = value[int(key)] if isinstance(value, list) else value[key]
                serialized = json.dumps(value, ensure_ascii=False, indent=2)
                start = min(args.offset_chars, len(serialized))
                end = min(start + args.max_chars, len(serialized))
                response = {
                    "report": state["report"],
                    "section": args.section,
                    "json_pointer": args.json_pointer,
                    "content_sha256": bytes_digest(serialized.encode()),
                    "offset_chars": start,
                    "next_offset_chars": end,
                    "total_chars": len(serialized),
                    "content": serialized[start:end],
                }
                while len(json.dumps(response, ensure_ascii=False)) > 16000 and end > start:
                    end = start + (end - start) * 3 // 4
                    response.update(next_offset_chars=end, content=serialized[start:end])
                return json.dumps(response, ensure_ascii=False)
            except Exception as error:
                return self._refusal("report_read", error)


@dataclass(frozen=True)
class QualiaKnowledgeTools:
    bridge: QualiaKnowledgeBridge
    tools: dict[str, BaseTool]
    definitions: dict[str, CapabilityDefinition]
    components: tuple[DeepAgentToolComponent, ...]
    bindings: dict[str, CapabilityComponentBinding]

    @property
    def worker(self) -> QualiaKnowledgeBridge:
        return self.bridge

    @property
    def registry_tools(self) -> dict[str, BaseTool]:
        return {item.ref.digest: self.tools[item.tool_name] for item in self.components}


def build_qualia_knowledge_tools(
    process: subprocess.Popen[bytes],
    *,
    ready: Mapping[str, Any],
    evidence_dir: Path,
    ledger: SpendLedger,
    bks_root: Path = DEFAULT_BKS_ROOT,
    model_factory: Callable[..., Any] = evaluator_model,
    native_context: dict[str, Any] | None = None,
    attachment_target: str = "agent.main",
    timeout_seconds: float = 60,
) -> QualiaKnowledgeTools:
    bridge = QualiaKnowledgeBridge(
        QualiaKnowledgeIPC(process, timeout_seconds=timeout_seconds),
        ready=ready,
        evidence_dir=evidence_dir,
        ledger=ledger,
        bks_root=bks_root,
        model_factory=model_factory,
        native_context=native_context,
    )
    tools: dict[str, BaseTool] = {}
    definitions: dict[str, CapabilityDefinition] = {}
    bindings: dict[str, CapabilityComponentBinding] = {}
    components: list[DeepAgentToolComponent] = []
    entries = (
        (
            "evidence_report_read",
            ReportReadInput,
            "Read exact frozen assertion/evidence/judgment metadata, full evaluation feedback "
            "or canonical assessment/census repair feedback (section='assessment') "
            "for a report actually evaluated by this bridge. Use RFC6901 pointers and character "
            "pagination; no new model, web or graph call. Preserve IDs and exact source quotes.",
        ),
        (
            "verify_evidence",
            VerifyEvidenceInput,
            (
                "Submit 1..24 agent-authored attributed claims with unique exact quotes from "
                "existing registered web captures. Set capture_id from source_read/scrape/browser. "
                "Pin capture_id "
                "when multiple snapshots share sourceUrl; the host never chooses an engine. "
                "Each claim may include up to 3 additional_quotes from that same snapshot, "
                "with primary+additional quotes totaling at most 8000 "
                "characters. Supply exact context quotes supporting every scientific qualifier "
                "(entity, serving basis, population, specimen, duration, sample size); never "
                "assume missing context or generalize label/trial evidence. Runs actual KS "
                "registration and separate "
                "Terra judge/Sol auditor model evaluations. Returns immutable report "
                "reference and factual repair feedback; does not admit graph use. Use a fresh"
                " report id after any content change."
            ),
        ),
        (
            "biotech_ingest",
            IngestInput,
            (
                "Apply agent-authored native graph input for an actually evaluated report "
                "through KS native intent, sealed exact-use admission and authorized Biotech "
                "dispatch/readback. Held/refused decisions never consume graph effects. "
                "Each native capture may select capture_id, restricted to evaluated snapshots "
                "for canonicalUri; selectors are stripped before the canonical graph builder. "
                "Inspect biotech_schema first."
            ),
        ),
        (
            "biotech_schema",
            SchemaInput,
            (
                "Read the real bounded Biotech native-input guide, partial schema or complete"
                " canonical JSON schema via RFC6901 pointers and character pagination. Guide "
                "placeholders are not facts. No graph access or model call."
            ),
        ),
    )
    for name, schema, description in entries:
        tool = StructuredTool.from_function(
            coroutine=getattr(bridge, name), name=name, description=description, args_schema=schema
        )
        schema_digest = tool_schema_digest(tool)
        definition = CapabilityDefinition(
            logical_id=f"tool.qualia.{name}",
            title=name,
            description=f"{description} Input schema digest: {schema_digest}.",
            kind=DefinitionKind.TOOL,
            capability_kind=CapabilityKind.TOOL,
            maturity="experimental",
            attachment_targets=frozenset({attachment_target}),
        )
        ref = ExactDefinitionRef(
            kind=definition.kind,
            logical_id=definition.logical_id,
            revision=1,
            digest=sha256_digest(definition),
        )
        component = DeepAgentToolComponent(
            ref=ref,
            tool_name=name,
            schema_digest=schema_digest,
            attachment_target=attachment_target,
        )
        tools[name], definitions[definition.logical_id] = tool, definition
        components.append(component)
        bindings[definition.logical_id] = CapabilityComponentBinding(
            kind="tool", catalog_digest=ref.digest, tool=component
        )
    return QualiaKnowledgeTools(bridge, tools, definitions, tuple(components), bindings)
