from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from mission_control.adapters.capabilities.capability_bundles import bytes_digest
from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION
from mission_control.application.knowledge.toolset import LiveInvocation
from mission_control.domain.authoring.canonical import sha256_digest
from tests.fixtures.qualia_knowledge import (
    AuthoredClaim,
    KnowledgeBridgeRefused,
    QualiaKnowledgeBridge,
    QualiaKnowledgeIPC,
    build_qualia_knowledge_tools,
)
from tests.fixtures.qualia_runtime import SpendLedger
from tests.fixtures.qualia_web_tools import SEED_URLS, EvidenceCapture

REPORT = {
    "kind": "report",
    "id": "registered-report",
    "digest": "sha256:" + "a" * 64,
    "tenant": "test-tenant",
    "binding": "biotech-graph",
}
SOURCE_TEXT = (
    "Study findings. No significant changes occurred in primary outcomes. Sponsor: Qualia."
)
CLAIM = {
    "id": "primary",
    "statement": "The pilot reported no significant primary outcome changes.",
    "sourceUrl": SEED_URLS[2],
    "quote": "No significant changes occurred in primary outcomes.",
    "qualifiers": {"studyDesign": "other", "causalClaim": "unknown", "negation": True},
}
AUTHORED = {
    "id": "test-report",
    "title": "Qualia pilot primary outcomes",
    "summary": "A bounded attributed statement from retained study text.",
    "claims": [CLAIM],
    "limitations": ["Bounded source report; no generalized efficacy assessment."],
}
JUDGE_ANSWER = {
    "judgments": [
        {
            "setIndex": 0,
            "verdict": "insufficient_evidence",
            "reason": "Population qualifier is not fully supported.",
            "fragmentIndices": [0],
            "unsupportedFacets": ["population"],
            "qualification": None,
        }
    ]
}
AUDITOR_ANSWER = {
    "occurrences": [],
    "unitExplanations": [],
    "rationale": "Test response only.",
    "limitations": [],
    "recallReason": "Unmeasured; no gold inventory.",
}


def ready() -> dict[str, Any]:
    return {
        "ready": True,
        "roles": {
            role: {
                "subject": "actor-" + role,
                "invocationId": "invocation-" + role,
                "applicationId": "biotech",
            }
            for role in ("producer", "judge", "auditor")
        },
    }


def capture(directory: Path, text: str = SOURCE_TEXT, *, url: str = SEED_URLS[2]) -> dict[str, Any]:
    return EvidenceCapture(directory).save(
        "firecrawl_scrape",
        json.dumps(
            {
                "success": True,
                "data": {
                    "markdown": text,
                    "metadata": {"title": "Actual captured title", "sourceURL": url},
                },
            }
        ).encode(),
        {"requested_url": url, "complete": True, "http_status": 200},
    )


def browser_capture(directory: Path, text: str = "Troy Aikman endorses the company.") -> dict:
    return EvidenceCapture(directory).save(
        "agent_browser_page",
        json.dumps(
            {
                "text_excerpt": text,
                "title": "Actual browser title",
                "final_url": SEED_URLS[2],
            }
        ).encode(),
        {"requested_url": SEED_URLS[2], "complete": True, "http_status": 200},
    )


class HostBoundary:
    """Offline mock of the documented host IPC; not a real evaluator or admission proof."""

    def __init__(self, *, admitted: bool = False, bad_custody: bool = False) -> None:
        self.commands: list[dict[str, Any]] = []
        self.admitted, self.bad_custody = admitted, bad_custody
        self.fail_consume_once = False
        self.frozen = {"reportRevisionId": REPORT["id"], "assertions": []}
        self.assessment = {
            "schema": "qualia-assessment-preview.v1",
            "report": REPORT,
            "assessment": {
                "report": REPORT,
                "aggregate": {"complete": True},
                "census": {"status": "assessed", "holds": []},
            },
            "admitted": False,
            "qualified": False,
            "dispatched": False,
            "repairFeedback": {},
        }

    async def request(self, command: dict[str, Any]) -> dict[str, Any]:
        self.commands.append(deepcopy(command))
        action = command["action"]
        if action == "frozen":
            assert command["report"] == REPORT
            return {"frozen": deepcopy(self.frozen)}
        if action == "assessment_preview":
            assert command["report"] == REPORT
            return deepcopy(self.assessment)
        if action == "capture":
            return {
                "captureId": command["captureId"],
                "sourceUrl": command["sourceUrl"],
                "ref": {
                    "kind": "artifact",
                    "id": "source-custody",
                    "digest": bytes_digest(b"wrong")
                    if self.bad_custody
                    else bytes_digest(command["text"].encode()),
                },
            }
        if action == "prepare_report":
            return {"registration": {"task": {}, "report": {"reportId": command["input"]["id"]}}}
        if action == "call":
            assert command["request"]["operation"] == "report.register"
            assert command["request"]["nativeContract"] == {
                "name": "research-report",
                "version": "v2",
            }
            return {"result": {"nativeReceiptRef": REPORT}}
        if action == "eval_request":
            role = command["role"]
            key = "judgments" if role == "judge" else "occurrences"
            return {
                "context": {"role": role, "report": REPORT, "isolated": role},
                "body": "The actual frozen report body",
                "prompt": "Isolated " + role,
                "json_schema": {
                    "type": "object",
                    "required": [key],
                    "properties": {key: {"type": "array"}},
                },
            }
        if action == "eval_submit":
            assert json.loads(command["rawResponse"]) == command["answer"]
            assert command["usage"]["providerCalls"] == 1
            return {"result": {"observationId": command["role"] + "-actual-boundary-receipt"}}
        if action == "native_intent":
            return {
                "intent": {"actual": "host-built-intent"},
                "boundEffectDigest": "sha256:" + "b" * 64,
            }
        if action == "finalize_report":
            return {
                "report": REPORT,
                "decision": {
                    "disposition": "admitted" if self.admitted else "held",
                    "report": REPORT,
                    "subject": REPORT,
                    "reviewPending": False,
                    "admissibility": {"status": "admitted" if self.admitted else "held"},
                },
                "effectKey": "real-host-effect",
                "dispatched": self.admitted,
            }
        if action == "consume":
            if self.fail_consume_once:
                self.fail_consume_once = False
                raise KnowledgeBridgeRefused("Readback temporarily unavailable; preserve dispatch")
            assert command["effectKey"] == "real-host-effect"
            assert command["authorization"] == "owner-authorized-qualia-biotech-8032ec07"
            return {
                "native": {
                    "receipt": {
                        "outcome": "applied",
                        "receiptId": "offline-native-receipt",
                        "effect": {"effectKey": "real-host-effect"},
                        "effects": {"total": 1},
                    },
                    "proof": {"checkedEffects": 1, "requiredSubjectUids": ["offline-subject"]},
                    "acknowledgement": {"acknowledged": True},
                    "pages": [
                        {
                            "complete": True,
                            "nextCursor": None,
                            "failures": 0,
                            "checked": 1,
                            "items": [{"ok": True}],
                        }
                    ],
                }
            }
        raise AssertionError(action)


class EvaluatorBoundary:
    """Offline model boundary recording which role/model/context the bridge actually invokes."""

    def __init__(self, *, omit_usage: bool = False, token_usage: dict | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.omit_usage = omit_usage
        self.token_usage = token_usage

    def factory(self, _ledger, *, role, model_id):
        owner = self

        class Model:
            def with_structured_output(self, schema, **kwargs):
                assert kwargs == {"method": "json_schema", "strict": True, "include_raw": True}
                self.schema = schema
                assert schema["name"] == "qualia_" + role
                assert schema["schema"]["type"] == "object"
                return self

            async def ainvoke(self, messages):
                owner.calls.append({"role": role, "model": model_id, "messages": messages})
                answer = deepcopy(JUDGE_ANSWER if role == "judge" else AUDITOR_ANSWER)
                usage = (
                    None
                    if owner.omit_usage
                    else owner.token_usage
                    or {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140}
                )
                raw = AIMessage(content=json.dumps(answer), usage_metadata=usage)
                return {"raw": raw, "parsed": answer, "parsing_error": None}

        return Model()


def bridge(
    tmp_path: Path, host: HostBoundary, model: EvaluatorBoundary, *, source_text: str = SOURCE_TEXT
) -> QualiaKnowledgeBridge:
    capture(tmp_path / "web", text=source_text)
    return QualiaKnowledgeBridge(
        host,
        ready=ready(),
        evidence_dir=tmp_path / "web",
        ledger=SpendLedger(tmp_path / "spend"),
        model_factory=model.factory,
        native_context={
            "actor": {"kind": "agent", "id": "actor-producer"},
            "run": {"system": "mission-control", "runId": "offline-test-only"},
            "activityKind": "INGESTION",
        },
    )


def native_input() -> dict[str, Any]:
    return {
        "intentId": "authored-intent",
        "captures": [
            {
                "ref": "study-source",
                "canonicalUri": SEED_URLS[2],
                "title": "MODEL_TITLE_MUST_NOT_OVERRIDE_CAPTURE",
                "captureMethod": "fabricated/1",
                "hashBasis": "RAW_BYTES",
                "completeness": "COMPLETE",
                "locators": [{"ref": "primary-quote", "exact": CLAIM["quote"]}],
            }
        ],
        "subjects": [
            {"ref": "study", "mode": "new", "nodeType": "Study", "name": "Authored study"}
        ],
        "subjectEvidence": {"study": ["primary-quote"]},
        "proposals": [],
        "about": ["study"],
    }


async def test_report_reader_pages_exact_host_metadata_and_retains_feedback(tmp_path: Path) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    host.frozen["assertions"] = [
        {"id": "actual-host-assertion", "proposition": 'Quote "A". ' * 5000}
    ]
    worker = bridge(tmp_path, host, model)
    await worker.verify_evidence(**AUTHORED)
    expected = json.dumps(host.frozen["assertions"], ensure_ascii=False, indent=2)
    chunks, offset = [], 0
    while offset < len(expected):
        raw = await worker.evidence_report_read(
            REPORT["digest"], json_pointer="/assertions", offset_chars=offset, max_chars=12000
        )
        assert len(raw) <= 16000
        page = json.loads(raw)
        assert page["content_sha256"] == bytes_digest(expected.encode())
        assert page["offset_chars"] == offset
        assert page["next_offset_chars"] > offset
        chunks.append(page["content"])
        offset = page["next_offset_chars"]
    assert "".join(chunks) == expected
    assert len([c for c in host.commands if c["action"] == "frozen"]) == 1
    assert len(model.calls) == 2
    feedback = json.loads(
        await worker.evidence_report_read(REPORT["digest"], section="evaluations")
    )
    assert len(json.loads(feedback["content"])) == 2
    assert len(model.calls) == 2


async def test_report_reader_refuses_unknown_or_rebound_report(tmp_path: Path) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    refused = json.loads(await worker.evidence_report_read(REPORT["digest"]))
    assert refused["status"] == "refused" and not host.commands
    await worker.verify_evidence(**AUTHORED)
    host.frozen["reportRevisionId"] = "another-report"
    refused = json.loads(await worker.evidence_report_read(REPORT["digest"]))
    assert refused["status"] == "refused"
    assert "another report" in refused["feedback"]
    assert "frozen" not in worker._reports[REPORT["digest"]]


async def test_actual_census_hold_is_visible_without_sealing_or_dispatch(tmp_path: Path) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    host.assessment["assessment"]["aggregate"]["complete"] = False
    host.assessment["repairFeedback"] = {
        "unmatchedAuditor": [{"id": "actual-census-2", "quote": "No primary change."}],
        "screening": [{"id": "producer-1", "flag": "negation"}],
    }
    worker = bridge(tmp_path, host, model)
    result = json.loads(await worker.verify_evidence(**AUTHORED))
    assert result["status"] == "evaluated" and result["assessment_complete"] is False
    assert result["admitted"] is False and len(model.calls) == 2
    actual = json.loads(
        await worker.evidence_report_read(
            REPORT["digest"], section="assessment", json_pointer="/repairFeedback"
        )
    )
    assert json.loads(actual["content"]) == host.assessment["repairFeedback"]
    assert not {"native_intent", "finalize_report", "consume"} & {
        c["action"] for c in host.commands
    }
    assert host.commands[-1]["action"] == "assessment_preview"


@pytest.mark.parametrize(
    "corruption", ["outer_report", "inner_report", "admitted", "dispatched", "complete"]
)
async def test_assessment_preview_refuses_rebound_or_effectful_feedback(
    tmp_path: Path, corruption: str
) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    if corruption == "outer_report":
        host.assessment["report"] = {**REPORT, "id": "other-report"}
    elif corruption == "inner_report":
        host.assessment["assessment"]["report"] = {**REPORT, "digest": "sha256:" + "c" * 64}
    elif corruption == "complete":
        host.assessment["assessment"]["aggregate"]["complete"] = "true"
    else:
        host.assessment[corruption] = True
    worker = bridge(tmp_path, host, model)
    refused = json.loads(await worker.verify_evidence(**AUTHORED))
    assert refused["status"] == "refused" and refused["stage"] == "assessment_preview"
    assert not {"native_intent", "finalize_report", "consume"} & {
        c["action"] for c in host.commands
    }


@pytest.mark.parametrize(
    "qualifiers", [{}, {"negation": None}, {"negation": "false"}, {"negation": 0}]
)
def test_claim_requires_explicit_boolean_polarity(qualifiers) -> None:
    with pytest.raises(ValidationError):
        AuthoredClaim.model_validate({**CLAIM, "qualifiers": qualifiers})
    assert AuthoredClaim.model_validate(CLAIM).qualifiers.negation is True
    assert (
        AuthoredClaim.model_validate(
            {**CLAIM, "qualifiers": {"negation": False}}
        ).qualifiers.negation
        is False
    )


async def test_verification_uses_captured_bytes_and_two_isolated_actual_model_boundaries(
    tmp_path: Path,
) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    result = json.loads(await worker.verify_evidence(**AUTHORED))
    assert result["status"] == "evaluated"
    assert result["admitted"] is False
    assert result["report"] == REPORT
    assert host.commands[0]["action"] == "capture"
    assert host.commands[0]["text"] == SOURCE_TEXT
    assert host.commands[0]["completeness"] == "unknown"
    assert [(call["role"], call["model"]) for call in model.calls] == [
        ("judge", "gpt-6.1-terra"),
        ("auditor", "gpt-6.1-sol"),
    ]
    auditor_prompt = model.calls[1]["messages"][1].content
    assert "insufficient_evidence" not in auditor_prompt
    assert "Population qualifier" not in auditor_prompt
    submits = [command for command in host.commands if command["action"] == "eval_submit"]
    assert submits[0]["answer"] == JUDGE_ANSWER  # negative verdict is never promoted
    assert submits[0]["usage"] == {"providerCalls": 1, "tokens": 140, "costUsd": "0.000325"}
    assert not any(command["action"] == "consume" for command in host.commands)
    await worker.verify_evidence(**AUTHORED)
    assert len(model.calls) == 2  # identical request reuses actual receipts
    changed = json.loads(
        await worker.verify_evidence(**(AUTHORED | {"summary": "Changed report content."}))
    )
    assert changed["status"] == "refused"
    assert "fresh report id" in changed["feedback"]


def test_single_quote_default_and_additional_quote_text_remain_exact() -> None:
    original = AuthoredClaim.model_validate(CLAIM)
    assert original.additional_quotes == []
    extra = "Study findings. "
    claim = AuthoredClaim.model_validate({**CLAIM, "additional_quotes": [extra]})
    assert claim.model_dump()["additional_quotes"] == [extra]
    assert claim.quote == CLAIM["quote"]
    assert AuthoredClaim.model_json_schema()["additionalProperties"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"additional_quotes": [CLAIM["quote"]]},
        {"additional_quotes": ["Unique quote.", "Unique quote."]},
        {"additional_quotes": ["first", "second", "third", "fourth"]},
        {"additional_quotes": ["tiny"]},
        {"additional_quotes": [42]},
        {"additional_quotes": ("not a list",)},
        {"additional_quotes": None},
        {"quote": "a" * 7996, "additional_quotes": ["12345"]},
        {"additional_quotes": ["exact quote"], "additional_sourceUrl": SEED_URLS[1]},
    ],
)
def test_additional_quotes_reject_invalid_bounds_types_and_unknown_fields(changes) -> None:
    with pytest.raises(ValidationError):
        AuthoredClaim.model_validate({**CLAIM, **changes})


def test_combined_quote_limit_accepts_exactly_8000_characters() -> None:
    claim = AuthoredClaim.model_validate(
        {
            **CLAIM,
            "quote": "a" * 7995,
            "additional_quotes": ["12345"],
        }
    )
    assert len(claim.quote) + len(claim.additional_quotes[0]) == 8000


async def test_context_quotes_forward_unchanged_from_same_retained_source(tmp_path: Path) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    extra = ["Study findings. ", "Sponsor: Qualia."]
    claim = {**CLAIM, "additional_quotes": extra}
    result = json.loads(await worker.verify_evidence(**{**AUTHORED, "claims": [claim]}))
    assert result["status"] == "evaluated"
    prepared = next(command for command in host.commands if command["action"] == "prepare_report")
    assert prepared["input"]["claims"][0]["additional_quotes"] == extra
    assert prepared["input"]["claims"][0]["quote"] == CLAIM["quote"]
    assert prepared["input"]["claims"][0]["sourceUrl"] == CLAIM["sourceUrl"]
    assert len([command for command in host.commands if command["action"] == "capture"]) == 1


@pytest.mark.parametrize(
    "extra", [["Unavailable source context."], ["Study findings.\n"], ["Study  findings."]]
)
async def test_inexact_context_quote_is_refused_before_registration_or_models(
    tmp_path: Path, extra
) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    result = json.loads(
        await worker.verify_evidence(
            **{
                **AUTHORED,
                "claims": [{**CLAIM, "additional_quotes": extra}],
            }
        )
    )
    assert result["status"] == "refused"
    assert "does not uniquely resolve" in result["feedback"]
    assert not any(command["action"] == "prepare_report" for command in host.commands)
    assert not model.calls


async def test_overlapping_duplicate_quote_occurrences_are_not_unique(tmp_path: Path) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model, source_text=SOURCE_TEXT + " aaaaaa")
    result = json.loads(
        await worker.verify_evidence(
            **{
                **AUTHORED,
                "claims": [{**CLAIM, "additional_quotes": ["aaaaa"]}],
            }
        )
    )
    assert result["status"] == "refused"
    assert "does not uniquely resolve" in result["feedback"]
    assert not model.calls


async def test_two_claims_select_distinct_verified_snapshots_of_same_url(tmp_path: Path) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    scrape = worker._source(CLAIM["sourceUrl"])
    browser = browser_capture(tmp_path / "web")
    claims = [
        {**CLAIM, "capture_id": scrape.record["capture_id"]},
        {
            **CLAIM,
            "id": "endorsement",
            "capture_id": browser["capture_id"],
            "statement": "The captured page reports Troy Aikman's endorsement.",
            "quote": "Troy Aikman endorses the company.",
        },
    ]
    result = json.loads(await worker.verify_evidence(**{**AUTHORED, "claims": claims}))
    assert result["status"] == "evaluated"
    ids = {scrape.record["capture_id"], browser["capture_id"]}
    assert {item["capture_id"] for item in result["source_captures"]} == ids
    custody = [command for command in host.commands if command["action"] == "capture"]
    assert {command["captureId"] for command in custody} == ids
    assert {command["text"] for command in custody} == {
        SOURCE_TEXT,
        "Troy Aikman endorses the company.",
    }
    prepared = next(command for command in host.commands if command["action"] == "prepare_report")
    assert [claim["capture_id"] for claim in prepared["input"]["claims"]] == [
        scrape.record["capture_id"],
        browser["capture_id"],
    ]


async def test_url_only_claim_refuses_ambiguity_before_any_host_or_model_call(
    tmp_path: Path,
) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    scrape_id = worker._source(CLAIM["sourceUrl"]).record["capture_id"]
    browser = browser_capture(tmp_path / "web")
    result = json.loads(await worker.verify_evidence(**AUTHORED))
    assert result["status"] == "refused"
    assert result["content"]["issues"][0]["error"] == "capture_id_required"
    assert result["content"]["issues"][0]["sourceUrl"] == CLAIM["sourceUrl"]
    assert all(
        row["sourceUrl"] == CLAIM["sourceUrl"] for row in result["content"]["available_captures"]
    )
    assert {row["capture_id"] for row in result["content"]["available_captures"]} == {
        scrape_id,
        browser["capture_id"],
    }
    assert not host.commands and not model.calls


async def test_url_only_legacy_ignores_corrupt_capture_and_pins_sole_verified_id(
    tmp_path: Path,
) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    original = worker._source(CLAIM["sourceUrl"]).record["capture_id"]
    corrupt = browser_capture(tmp_path / "web")
    (tmp_path / "web" / f"{corrupt['capture_id']}.response.bin").write_bytes(b"corrupt")
    result = json.loads(await worker.verify_evidence(**AUTHORED))
    assert result["status"] == "evaluated"
    prepared = next(command for command in host.commands if command["action"] == "prepare_report")
    assert prepared["input"]["claims"][0]["capture_id"] == original
    assert [row["capture_id"] for row in result["source_captures"]] == [original]


async def test_all_claim_quote_mismatches_are_aggregated_before_custody(tmp_path: Path) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    claims = [
        {
            **CLAIM,
            "id": "first",
            "quote": "Missing primary quote.",
            "additional_quotes": ["Missing context quote.", "Sponsor: Qualia."],
        },
        {**CLAIM, "id": "second", "additional_quotes": ["Also missing context."]},
    ]
    result = json.loads(await worker.verify_evidence(**{**AUTHORED, "claims": claims}))
    assert result["status"] == "refused"
    issues = result["content"]["issues"]
    assert [(issue["claim_id"], issue["quote_indices"]) for issue in issues] == [
        ("first", [0, 1]),
        ("second", [1]),
    ]
    assert not host.commands and not model.calls


@pytest.mark.parametrize("kind", ["foreign_url", "missing", "corrupt"])
async def test_explicit_capture_never_falls_back_to_another_source(tmp_path: Path, kind) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    if kind == "foreign_url":
        record = capture(tmp_path / "web", url=SEED_URLS[1])
    elif kind == "corrupt":
        record = capture(tmp_path / "web")
        (tmp_path / "web" / f"{record['capture_id']}.response.bin").write_bytes(b"corrupt")
    else:
        record = {"capture_id": "0" * 32}
    result = json.loads(
        await worker.verify_evidence(
            **{
                **AUTHORED,
                "claims": [{**CLAIM, "capture_id": record["capture_id"]}],
            }
        )
    )
    assert result["status"] == "refused"
    assert result["content"]["issues"][0]["error"] == "capture_id_unavailable_for_url"
    assert not host.commands and not model.calls


@pytest.mark.parametrize("value", ["../arbitrary", "A" * 32, "a" * 31, 123, True])
def test_capture_selector_schema_is_strict_registered_identity(value) -> None:
    with pytest.raises(ValidationError):
        AuthoredClaim.model_validate({**CLAIM, "capture_id": value})


@pytest.mark.parametrize("field", ["captureId", "sourceUrl"])
async def test_custody_receipt_must_echo_exact_selected_identity(tmp_path: Path, field) -> None:
    class WrongEcho(HostBoundary):
        async def request(self, command):
            answer = await super().request(command)
            if command["action"] == "capture":
                answer[field] = "wrong-identity"
            return answer

    host, model = WrongEcho(), EvaluatorBoundary()
    result = json.loads(await bridge(tmp_path, host, model).verify_evidence(**AUTHORED))
    assert result["status"] == "refused"
    assert "different capture identity" in result["feedback"]
    assert not any(command["action"] == "prepare_report" for command in host.commands)
    assert not model.calls


async def test_native_capture_selects_only_evaluated_snapshot_and_strips_fixture_selector(
    tmp_path: Path,
) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    browser = browser_capture(tmp_path / "web", SOURCE_TEXT)
    browser_id = browser["capture_id"]
    assert (
        json.loads(
            await worker.verify_evidence(
                **{
                    **AUTHORED,
                    "claims": [{**CLAIM, "capture_id": browser_id}],
                }
            )
        )["status"]
        == "evaluated"
    )
    authored = native_input()
    authored["captures"][0]["capture_id"] = browser_id
    result = json.loads(await worker.biotech_ingest(REPORT, authored))
    assert result["status"] == "held"
    native = next(command for command in host.commands if command["action"] == "native_intent")
    selected = native["input"]["captures"][0]
    assert selected["captureId"] == browser_id
    assert "capture_id" not in selected
    assert selected["hashBasis"] == "STORED_EXCERPT_TEXT"
    assert selected["completeness"] == "PARTIAL_EXCERPT"
    assert selected["title"] == "Actual browser title"


async def test_native_capture_rejects_registered_but_unevaluated_snapshot(tmp_path: Path) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    assert json.loads(await worker.verify_evidence(**AUTHORED))["status"] == "evaluated"
    browser = browser_capture(tmp_path / "web", SOURCE_TEXT)
    authored = native_input()
    authored["captures"][0]["capture_id"] = browser["capture_id"]
    result = json.loads(await worker.biotech_ingest(REPORT, authored))
    assert result["status"] == "refused"
    assert "capture_id evaluated for this URL" in result["feedback"]
    assert not any(command["action"] == "native_intent" for command in host.commands)


async def test_native_capture_refusal_exposes_exact_repair_and_does_not_freeze_retry(
    tmp_path: Path,
) -> None:
    host, model = HostBoundary(admitted=True), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    verified = json.loads(await worker.verify_evidence(**AUTHORED))
    allowed = verified["source_captures"][0]
    browser = browser_capture(tmp_path / "web", SOURCE_TEXT)
    authored = native_input()
    authored["captures"][0]["capture_id"] = browser["capture_id"]
    original = deepcopy(authored)
    refused = json.loads(await worker.biotech_ingest(REPORT, authored))
    assert authored == original
    assert refused["status"] == "refused" and refused["recoverable"] is True
    assert refused["retry_tool"] == "biotech_ingest"
    assert refused["required_action"] == "repair_native_input_and_retry"
    assert refused["admitted"] is False and refused["dispatched"] is False
    assert refused["native_input_frozen"] is False
    feedback = refused["content"]
    assert feedback["capture_ref"] == "study-source"
    assert feedback["requested_capture_id"] == browser["capture_id"]
    assert feedback["source_url"] == CLAIM["sourceUrl"]
    assert feedback["allowed_capture_ids_for_url"] == [allowed["capture_id"]]
    assert feedback["available_captures"] == [allowed]
    assert feedback["referenced_paths"] == [
        {"path": "/subjectEvidence/study/0", "ref": "primary-quote"}
    ]
    assert "Never substitute a capture ID" in feedback["repair"]
    state = worker._reports[REPORT["digest"]]
    assert state.get("native_fingerprint") is None
    assert state.get("finalized") is None and state["native_result"] is None
    assert not any(
        command["action"] in {"native_intent", "finalize_report", "consume"}
        for command in host.commands
    )
    # The producer explicitly repairs its selector; the bridge neither rewrites nor infers it.
    corrected = deepcopy(authored)
    corrected["captures"][0]["capture_id"] = allowed["capture_id"]
    applied = json.loads(await worker.biotech_ingest(REPORT, corrected))
    assert applied["status"] == "native_applied"  # Offline HostBoundary only.
    assert state["native_fingerprint"] == sha256_digest(corrected)
    assert sum(command["action"] == "finalize_report" for command in host.commands) == 1
    assert sum(command["action"] == "consume" for command in host.commands) == 1
    assert len(model.calls) == 2  # No automatic paid evaluation/retry is introduced.


async def test_unused_unevaluated_capture_can_be_removed_without_rebinding_existing_refs(
    tmp_path: Path,
) -> None:
    host, model = HostBoundary(admitted=True), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    await worker.verify_evidence(**AUTHORED)
    browser = browser_capture(tmp_path / "web", "A separate unused browser note.")
    authored = native_input()
    authored["captures"].append(
        {
            "ref": "unused-browser",
            "canonicalUri": CLAIM["sourceUrl"],
            "capture_id": browser["capture_id"],
            "locators": [{"ref": "unused-note", "exact": "A separate unused browser note."}],
        }
    )
    refused = json.loads(await worker.biotech_ingest(REPORT, authored))
    assert refused["content"]["referenced_paths"] == []
    assert worker._reports[REPORT["digest"]].get("native_fingerprint") is None
    authored["captures"].pop()
    applied = json.loads(await worker.biotech_ingest(REPORT, authored))
    assert applied["status"] == "native_applied"  # Offline HostBoundary only.
    selected = next(command for command in host.commands if command["action"] == "native_intent")
    assert selected["input"]["captures"][0]["captureId"] != browser["capture_id"]


async def test_schema_guide_distinguishes_frozen_native_captures_from_browser_history(
    tmp_path: Path,
) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    response = json.loads(await worker.biotech_schema(section="guide", max_chars=12000))
    # Guide content is paginated output, never a tool-definition/schema or a WorkflowType change.
    text = response["content"]
    assert "distinct browser capture is included" in text
    assert "only if that exact browser ID" in text
    assert "native_capture_repair" in text
    assert "Never auto-rebind IDs or quote bytes" in text
    assert not host.commands and not model.calls


async def test_native_url_ambiguity_requires_explicit_evaluated_capture(tmp_path: Path) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    scrape_id = worker._source(CLAIM["sourceUrl"]).record["capture_id"]
    browser = browser_capture(tmp_path / "web", SOURCE_TEXT)
    browser_id = browser["capture_id"]
    claims = [
        {**CLAIM, "capture_id": scrape_id},
        {**CLAIM, "id": "browser-primary", "capture_id": browser_id},
    ]
    assert (
        json.loads(
            await worker.verify_evidence(
                **{
                    **AUTHORED,
                    "claims": claims,
                }
            )
        )["status"]
        == "evaluated"
    )
    result = json.loads(await worker.biotech_ingest(REPORT, native_input()))
    assert result["status"] == "refused"
    assert scrape_id in result["feedback"] and browser_id in result["feedback"]
    assert not any(command["action"] == "native_intent" for command in host.commands)


async def test_native_snapshot_guard_checks_original_raw_capture_digest(tmp_path: Path) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    source = worker._source(CLAIM["sourceUrl"])
    assert json.loads(await worker.verify_evidence(**AUTHORED))["status"] == "evaluated"
    raw_path = tmp_path / "web" / f"{source.record['capture_id']}.response.bin"
    record_path = raw_path.with_name(f"{source.record['capture_id']}.json")
    payload = json.loads(raw_path.read_bytes())
    payload["data"]["metadata"]["title"] = "Changed raw source, identical parsed text"
    changed = json.dumps(payload).encode()
    raw_path.write_bytes(changed)
    record = json.loads(record_path.read_bytes())
    record.update(raw_sha256=bytes_digest(changed), raw_size_bytes=len(changed))
    record_path.write_text(json.dumps(record), encoding="utf-8")
    result = json.loads(await worker.biotech_ingest(REPORT, native_input()))
    assert result["status"] == "refused"
    assert "differs from evaluated source bytes" in result["feedback"]
    assert not any(command["action"] == "native_intent" for command in host.commands)


@pytest.mark.parametrize(
    ("role", "input_tokens", "output_tokens", "exact", "serialized"),
    [
        ("judge", 1, 0, "0.00000125", "0.000002"),
        ("auditor", 1, 0, "0.0000025", "0.000003"),
        ("judge", 3, 1, "0.00000875", "0.000009"),
        ("judge", 100, 40, "0.000325", "0.000325"),
        ("auditor", 0, 1, "0.00001", "0.000010"),
    ],
)
async def test_evaluator_cost_rounds_up_only_at_ks_boundary(
    tmp_path: Path, role, input_tokens, output_tokens, exact, serialized
) -> None:
    host = HostBoundary()
    model = EvaluatorBoundary(
        token_usage={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
    )
    worker = bridge(tmp_path, host, model)
    result = await worker._evaluate(role, REPORT)
    submitted = next(command for command in host.commands if command["action"] == "eval_submit")
    assert submitted["usage"]["costUsd"] == serialized
    assert result["ks_cost_usd_upper_estimate"] == serialized
    assert Decimal(result["cost_usd_upper_estimate"]) == Decimal(exact)
    assert Decimal(serialized) >= Decimal(exact)
    assert Decimal(serialized) - Decimal(exact) < Decimal("0.000001")
    assert len(serialized.split(".")[1]) == 6


@pytest.mark.parametrize(("bad_custody", "omit_usage"), [(True, False), (False, True)])
async def test_missing_real_custody_or_evaluator_usage_never_finalizes(
    tmp_path: Path, bad_custody, omit_usage
) -> None:
    host, model = HostBoundary(bad_custody=bad_custody), EvaluatorBoundary(omit_usage=omit_usage)
    worker = bridge(tmp_path, host, model)
    result = json.loads(await worker.verify_evidence(**AUTHORED))
    assert result["status"] == "refused"
    assert not any(
        command["action"] in {"native_intent", "finalize_report", "consume"}
        for command in host.commands
    )
    assert not any(command["action"] == "eval_submit" for command in host.commands)


async def test_held_decision_never_consumes_and_preserves_evaluated_source_version(
    tmp_path: Path,
) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    await worker.verify_evidence(**AUTHORED)
    capture(tmp_path / "web", "Changed later source text must not replace evaluated bytes.")
    result = json.loads(await worker.biotech_ingest(REPORT, native_input()))
    assert result["status"] == "held"
    assert [command for command in host.commands if command["action"] == "capture"][-1][
        "text"
    ] == SOURCE_TEXT
    native = next(command for command in host.commands if command["action"] == "native_intent")[
        "input"
    ]
    assert native["captures"][0]["title"] == "Actual captured title"
    assert native["captures"][0]["hashBasis"] == "TOOL_RENDITION"
    assert native["captures"][0]["completeness"] == "UNKNOWN"
    assert native["context"]["actor"]["id"] == "actor-producer"
    assert not any(command["action"] == "consume" for command in host.commands)
    await worker.biotech_ingest(REPORT, native_input())
    assert sum(command["action"] == "finalize_report" for command in host.commands) == 1


async def test_native_consume_recovery_reuses_admitted_dispatch_and_requires_readback(
    tmp_path: Path,
) -> None:
    host, model = HostBoundary(admitted=True), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    await worker.verify_evidence(**AUTHORED)
    host.fail_consume_once = True
    failed = json.loads(await worker.biotech_ingest(REPORT, native_input()))
    assert failed["status"] == "refused" and failed["stage"] == "consume"
    resumed = json.loads(await worker.biotech_ingest(REPORT, native_input()))
    assert resumed["status"] == "native_applied"
    assert resumed["qualified"] is False
    assert sum(command["action"] == "finalize_report" for command in host.commands) == 1
    assert sum(command["action"] == "consume" for command in host.commands) == 2
    before = len(host.commands)
    assert json.loads(await worker.biotech_ingest(REPORT, native_input())) == resumed
    assert len(host.commands) == before


@pytest.mark.parametrize("corrupt", [False, True])
async def test_verified_native_summary_survives_large_receipt_and_refuses_count_mismatch(
    tmp_path: Path, corrupt: bool
) -> None:
    class LargeReceiptHost(HostBoundary):
        async def request(self, command):
            result = await super().request(command)
            if command["action"] == "consume":
                result["native"]["receipt"]["retained_detail"] = "exact retained data " * 5000
                if corrupt:
                    result["native"]["proof"]["checkedEffects"] = 2
            return result

    worker = bridge(tmp_path, LargeReceiptHost(admitted=True), EvaluatorBoundary())
    await worker.verify_evidence(**AUTHORED)
    raw = await worker.biotech_ingest(REPORT, native_input())
    result = json.loads(raw)
    if corrupt:
        assert result["status"] == "refused" and "summary differs" in result["feedback"]
    else:
        assert len(raw) <= 16000 and result["status"] == "native_applied"
        assert result["native_proof"] == {
            "receipt_id": "offline-native-receipt",
            "effect_key": "real-host-effect",
            "acknowledged": True,
            "total_effects": 1,
            "checked_effects": 1,
            "readback_complete": True,
            "readback_failures": 0,
            "verified_subject_uids": ["offline-subject"],
        }


async def test_agent_cannot_supply_source_bytes_or_foreign_report(tmp_path: Path) -> None:
    host, model = HostBoundary(admitted=True), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    foreign = json.loads(await worker.biotech_ingest(REPORT, native_input()))
    assert foreign["status"] == "refused"
    await worker.verify_evidence(**AUTHORED)
    authored = native_input()
    authored["captures"][0]["contentUtf8"] = "Model invented evidence"
    refused = json.loads(await worker.biotech_ingest(REPORT, authored))
    assert refused["status"] == "refused"
    assert "host-owned" in refused["feedback"]
    assert not any(command["action"] == "native_intent" for command in host.commands)


async def test_schema_guide_and_exact_capability_registration_are_local_only(
    tmp_path: Path,
) -> None:
    bundle = build_qualia_knowledge_tools(
        None,
        ready=ready(),
        evidence_dir=tmp_path / "web",
        ledger=SpendLedger(tmp_path / "spend"),
    )
    for component in bundle.components:
        assert sha256_digest(bundle.definitions[component.ref.logical_id]) == component.ref.digest
        assert component.schema_digest == sha256_digest(
            bundle.tools[component.tool_name].get_input_schema().model_json_schema()
        )
    guide = json.loads(await bundle.tools["biotech_schema"].ainvoke({}))
    assert "subjectEvidence" in guide["content"]
    schema = json.loads(
        await bundle.tools["biotech_schema"].ainvoke(
            {
                "section": "canonical_schema",
                "json_pointer": "/properties/context",
            }
        )
    )
    assert "activityKind" in schema["content"]
    assert schema["schema_sha256"].startswith("sha256:")


async def test_real_jsonline_ipc_lock_keeps_concurrent_requests_paired() -> None:
    code = (
        "import sys,json,time\nfor line in sys.stdin:\n "
        "x=json.loads(line);time.sleep(.01);print(json.dumps({'echo':x}),flush=True)"
    )
    process = await asyncio.to_thread(
        subprocess.Popen,
        [sys.executable, "-u", "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        ipc = QualiaKnowledgeIPC(process)
        answers = await asyncio.gather(*(ipc.request({"n": n}) for n in range(8)))
        assert [answer["echo"]["n"] for answer in answers] == list(range(8))
    finally:
        process.terminate()
        await asyncio.to_thread(process.wait, 5)


async def test_ipc_timeout_poison_prevents_stale_response_reuse() -> None:
    process = await asyncio.to_thread(
        subprocess.Popen,
        [sys.executable, "-u", "-c", "import time;time.sleep(5)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        ipc = QualiaKnowledgeIPC(process, timeout_seconds=0.03)
        with pytest.raises(TimeoutError):
            await ipc.request({"action": "wait"})
        with pytest.raises(KnowledgeBridgeRefused, match="uncertain"):
            await ipc.request({"action": "next"})
    finally:
        process.terminate()
        await asyncio.to_thread(process.wait, 5)


async def test_native_provenance_uses_current_scoped_invocation(tmp_path: Path) -> None:
    host, model = HostBoundary(), EvaluatorBoundary()
    worker = bridge(tmp_path, host, model)
    worker.native_context = None
    worker.roles["producer"].update(
        installationId="11111111-1111-4111-8111-111111111111",
        tenantId="22222222-2222-4222-8222-222222222222",
    )
    await worker.verify_evidence(**AUTHORED)
    refused = json.loads(await worker.biotech_ingest(REPORT, native_input()))
    assert refused["status"] == "refused"
    assert "current producer invocation" in refused["feedback"]
    live = LiveInvocation(
        request_scope=(
            "mc/11111111-1111-4111-8111-111111111111/biotech/22222222-2222-4222-8222-222222222222"
        ),
        run_id="actual-run",
        operation_id="actual-ingestion-operation",
        operation_attempt=3,
        execution_generation=2,
        lane="deep_agents",
    )
    token = CURRENT_INVOCATION.set(live)
    try:
        result = json.loads(await worker.biotech_ingest(REPORT, native_input()))
    finally:
        CURRENT_INVOCATION.reset(token)
    assert result["status"] == "held"
    context = next(command for command in host.commands if command["action"] == "native_intent")[
        "input"
    ]["context"]
    assert context["run"] == {
        "system": "mission-control",
        "runId": "actual-run",
        "operationId": "actual-ingestion-operation",
        "attempt": 3,
    }
    assert context["actor"]["id"] == "actual-run:actual-ingestion-operation"
    assert worker.results[0]["native"]["status"] == "held"


def test_real_openai_client_accepts_named_host_schema_without_request() -> None:
    from langchain_openai import ChatOpenAI
    from pydantic import SecretStr

    model = ChatOpenAI(
        model="gpt-6.1-terra", api_key=SecretStr("offline-unused"), use_responses_api=True
    )
    model.with_structured_output(
        {
            "name": "qualia_judge",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["judgments"],
                "properties": {"judgments": {"type": "array", "items": {"type": "string"}}},
            },
        },
        method="json_schema",
        strict=True,
        include_raw=True,
    )  # Construction only: no invoke or network request.


@pytest.mark.parametrize(
    "qualifiers",
    [
        {"studyDesign": "single-arm pilot"},
        {"sampleSize": "53"},
        {"sampleSize": True},
        {"causalClaim": "proven"},
        {"unknown_field": "invented"},
        {"profile": "scientific.v2"},
    ],
)
def test_qualifier_schema_refuses_unsupported_values_without_normalization(qualifiers) -> None:
    with pytest.raises(ValidationError):
        AuthoredClaim.model_validate({**CLAIM, "qualifiers": {"negation": False, **qualifiers}})
