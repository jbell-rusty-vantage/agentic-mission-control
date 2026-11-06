"""K01 negative conformance and schema parity (Checkpoint A addendum, SV-02 item 2).

Three checks, all data-driven from ``tests/fixtures/knowledge_protocol`` (a byte copy of the
KS ``schemas/`` and ``fixtures/``), so a new drop from Knowledge Services needs no code here:

1. **Schema parity**: every published schema's top-level properties and required set equal the
   fields of the Python model that validates it (no field is missing, renamed or extra).
2. **TS-invalid documents**: documents the TypeScript schemas or their ``superRefine`` rules
   refuse are refused by the Python models too (the error classification, terminal/retry
   rules, review/cancel/failure rules, native contract, pinned schema and capability
   patterns, floats in inline payloads, unknown operations and ref kinds, lone surrogates).
3. **Vector sweep**: every golden vector is replayed by shape (canonical value, envelope,
   origin, effect, credential claims, invalid value); a vector of an unknown shape is reported
   as skipped by id, never silently passed.

The effect-scoped recovery vector and schema are being added to K01 by helper E-KS (SV-16).
Until they are copied in, the checks that need them skip with that reason: the dependency.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pydantic import BaseModel, ValidationError

from mission_control.application.knowledge.operations import (
    pending_delivery,
    settlement_from_delivery,
    settlement_from_receipt,
)
from mission_control.contracts.knowledge_assessment import (
    CredentialEvaluation,
    DecisionResolution,
    DecisionResolveRequest,
    ReportObservationRequest,
    ReportReviewRequest,
    ReportSealRequest,
    ReportUseRequest,
)
from mission_control.contracts.knowledge_protocol import (
    CanonicalizationError,
    EffectBinding,
    KnowledgePlanPreview,
    KnowledgeReadIntentRequest,
    KnowledgeReadIntentResult,
    NativeInput,
    OperationEnvelope,
    OperationHandle,
    Origin,
    Ref,
    ResearchReportPackage,
    SelectedReportRead,
    canonical_json,
    digest_canonical,
)
from mission_control.contracts.knowledge_protocol_results import (
    RECEIPT_LOOKUP,
    BindingDescriptor,
    CredentialClaims,
    CredentialRecovery,
    OperationReceipt,
    OperationStatus,
    ProtocolError,
    ReceiptEffect,
    ReceiptFound,
)
from mission_control.domain.knowledge.effects import JournalState

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_protocol"
INDEX = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))
GOLDEN = json.loads(
    (FIXTURES / "knowledge-operation-protocol.v2.golden.json").read_text(encoding="utf-8")
)
VECTORS = {vector["id"]: vector for vector in GOLDEN["vectors"]}
MODELS: dict[str, type[BaseModel]] = {
    "ref.v2": Ref,
    "origin.v2": Origin,
    "effect-binding.v2": EffectBinding,
    "effect-identity.v2": ReceiptEffect,
    "protocol-error.v2": ProtocolError,
    "operation-handle.v2": OperationHandle,
    "operation-status.v2": OperationStatus,
    "operation-receipt.v2": OperationReceipt,
    "operation-envelope.v2": OperationEnvelope,
    "binding-descriptor.v2": BindingDescriptor,
    "credential-claims.v2": CredentialClaims,
    # WI-02 readSelected (KS b046088).
    "selected-report-read.v2": SelectedReportRead,
    "research-report-package.v2": ResearchReportPackage,
    # WI-03 trusted assessment (KS 7d12c0f, eff4c8e).
    "credential-evaluation.v1": CredentialEvaluation,
    "report-observation.v1": ReportObservationRequest,
    "report-seal.v1": ReportSealRequest,
    "report-use.v1": ReportUseRequest,
    "report-review.v1": ReportReviewRequest,
    "decision-resolve.v1": DecisionResolveRequest,
    "use-decision-resolution.v1": DecisionResolution,
    # Sprint OC W1 native write: the read-only plan preview.
    "knowledge-plan-preview.v1": KnowledgePlanPreview,
    # OVE-204 slice 4: the recorded read `knowledge.read_intent` (KS 6a4dd30).
    "knowledge-read-intent-request.v1": KnowledgeReadIntentRequest,
    "knowledge-read-intent-result.v1": KnowledgeReadIntentResult,
}
STAMP = "2026-10-25T10:00:00Z"
DIGEST = "sha256:" + "a" * 64


def schema(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / INDEX["schemas"][name]).read_text(encoding="utf-8"))


def schema_accepts(name: str, document: object) -> bool:
    try:
        jsonschema.Draft202012Validator(schema(name)).validate(document)
    except jsonschema.ValidationError:
        return False
    return True


def object_schema(node: dict[str, Any]) -> dict[str, Any]:
    if "properties" in node:
        return node
    for option in node.get("anyOf", []):
        if option.get("type") == "object":
            return option
    raise AssertionError("no object schema")


# ---------------------------------------------------------------- 1. schema parity


@pytest.mark.parametrize("name", sorted(MODELS))
def test_python_model_fields_equal_the_published_schema(name: str) -> None:
    published = object_schema(schema(name))
    model = MODELS[name]
    names = {info.alias or field: info for field, info in model.model_fields.items()}
    assert set(names) == set(published["properties"]), name
    required = {field for field, info in names.items() if info.is_required()}
    assert required == set(published.get("required", [])), name


def test_every_published_schema_has_a_python_model_or_a_recorded_reason() -> None:
    unmodelled = {
        # A union of three dispositions; validated by `RECEIPT_LOOKUP` (discriminated union).
        "receipt-lookup.v2",
        # Evaluator identities are KS research-core records; MC never parses one.
        "evaluator-identity.v2",
    }
    assert set(INDEX["schemas"]) == set(MODELS) | unmodelled


def test_recovery_claim_matches_the_effect_scoped_k01_shape() -> None:
    recovery = object_schema(schema("credential-claims.v2")["properties"]["recovery"])
    if "scope" not in recovery["properties"]:
        pytest.skip(
            "awaiting E-KS: credential-claims.v2 still publishes the read-only recovery "
            "claim; MC implements the agreed effect-scoped shape (dependency recorded)"
        )
    assert set(CredentialRecovery.model_fields) == set(recovery["properties"])


# ---------------------------------------------------------------- 2. TS-invalid documents


def error_document(code: str = "SCOPE_DENIED", **updates: object) -> dict[str, Any]:
    document: dict[str, Any] = {
        "protocolVersion": "ks.knowledge_operation.v2",
        "code": code,
        "message": "refused",
        "retryable": False,
        "domainOutcome": False,
        "correlation": {"dispatchId": None, "operationId": None, "effectKey": None},
        "details": None,
        "occurredAt": STAMP,
    }
    return document | updates


def handle_document() -> dict[str, Any]:
    return {
        "protocolVersion": "ks.knowledge_operation.v2",
        "tenant": "tenant-1",
        "application": "ai-engineer",
        "binding": "aiengineer-postgres",
        "operationId": "op-1",
    }


def ref_document(kind: str = "artifact") -> dict[str, Any]:
    return {
        "kind": kind,
        "id": "r-1",
        "version": "research-core.thing.v1",
        "digest": DIGEST,
        "tenant": "tenant-1",
        "binding": "aiengineer-postgres",
    }


def status_document(state: str = "running", **updates: object) -> dict[str, Any]:
    document: dict[str, Any] = {
        "handle": handle_document(),
        "state": state,
        "revision": 2,
        "createdAt": STAMP,
        "updatedAt": STAMP,
        "progressRef": None,
        "pendingReviewRef": None,
        "resultRef": None,
        "error": None,
        "unresolvedEffects": [],
        "retryAfterMs": 100,
        "cancelRequestId": None,
    }
    return document | updates


def envelope_document() -> dict[str, Any]:
    return copy.deepcopy(VECTORS["apply-envelope"]["envelope"])


def mutate(document: dict[str, Any], path: tuple[str, ...], value: object) -> dict[str, Any]:
    result = copy.deepcopy(document)
    node = result
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return result


# (case id, schema name, document, schema expected to refuse it too)
NEGATIVE: list[tuple[str, str, dict[str, Any], bool]] = [
    ("error-misclassified-retryable", "protocol-error.v2", error_document(retryable=True), False),
    (
        "error-domain-outcome-flipped",
        "protocol-error.v2",
        error_document("EXACT_REVISION_UNAVAILABLE", domainOutcome=False),
        False,
    ),
    ("error-float-details", "protocol-error.v2", error_document(details={"x": 1.5}), True),
    (
        "status-terminal-with-retry-hint",
        "operation-status.v2",
        status_document("succeeded", retryAfterMs=100),
        False,
    ),
    (
        "status-live-without-retry-hint",
        "operation-status.v2",
        status_document("running", retryAfterMs=None),
        False,
    ),
    (
        "status-failed-without-error",
        "operation-status.v2",
        status_document("failed", retryAfterMs=None),
        False,
    ),
    (
        "status-waiting-review-without-review",
        "operation-status.v2",
        status_document("waiting_review"),
        False,
    ),
    (
        "status-cancelling-without-request-id",
        "operation-status.v2",
        status_document("cancelling"),
        False,
    ),
    (
        "status-progress-ref-not-an-artifact",
        "operation-status.v2",
        status_document(progressRef=ref_document("report")),
        True,
    ),
    (
        "status-retry-hint-out-of-bounds",
        "operation-status.v2",
        status_document(retryAfterMs=50),
        True,
    ),
    (
        "envelope-native-contract-bad-version",
        "operation-envelope.v2",
        mutate(envelope_document(), ("input", "nativeContract", "version"), "1"),
        True,
    ),
    (
        "envelope-native-contract-extra-key",
        "operation-envelope.v2",
        mutate(
            envelope_document(),
            ("input", "nativeContract"),
            {"name": "knowledge-ingestion-intent", "version": "v1", "extra": "x"},
        ),
        True,
    ),
    (
        "envelope-pinned-schema-without-digest",
        "operation-envelope.v2",
        mutate(
            envelope_document(),
            ("pinnedSchema",),
            {"name": "aiengineer-database-contract", "version": "aiengineer-database-contract.v1"},
        ),
        True,
    ),
    (
        "envelope-capability-name-pattern",
        "operation-envelope.v2",
        mutate(envelope_document(), ("requiredCapabilities",), ["knowledge apply!"]),
        True,
    ),
    (
        "envelope-unknown-operation",
        "operation-envelope.v2",
        mutate(envelope_document(), ("operation",), "report.publish"),
        True,
    ),
    (
        "envelope-cancel-id-on-apply",
        "operation-envelope.v2",
        mutate(envelope_document(), ("cancelRequestId",), "cancel-1"),
        False,
    ),
    ("ref-unknown-kind", "ref.v2", ref_document("widget"), True),
    # K01 round 4: a declared use names its audience too (both or neither).
    (
        "envelope-use-without-audience",
        "operation-envelope.v2",
        envelope_document() | {"use": "internal_report"},
        False,
    ),
    (
        "envelope-use-bad-pattern",
        "operation-envelope.v2",
        envelope_document() | {"use": "Official Use", "audience": "official"},
        True,
    ),
]


@pytest.mark.parametrize(
    ("schema_name", "document", "schema_refuses"),
    [case[1:] for case in NEGATIVE],
    ids=[case[0] for case in NEGATIVE],
)
def test_python_refuses_documents_typescript_refuses(
    schema_name: str, document: dict[str, Any], schema_refuses: bool
) -> None:
    with pytest.raises(ValidationError):
        MODELS[schema_name].model_validate(document)
    # Rules only `superRefine` states are schema-valid; pattern/shape rules are not.
    assert schema_accepts(schema_name, document) is not schema_refuses


def test_python_refuses_a_float_inline_payload() -> None:
    with pytest.raises(ValidationError):
        NativeInput.model_validate(
            {
                "nativeContract": {"name": "knowledge-ingestion-intent", "version": "v1"},
                "payloadDigest": DIGEST,
                "payloadBytes": 3,
                "payloadRef": None,
                "inlinePayload": {"amount": 1.5},
                "upstream": [],
            }
        )


def test_lone_surrogates_are_refused_and_utf16_key_order_is_javascripts() -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json({"s": "\ud800"})
    with pytest.raises(CanonicalizationError):
        canonical_json({"\udc00": 1})
    # U+1F600 is the surrogate pair D83D DE00, which sorts before U+FF61 in UTF-16 code
    # units although its code point is larger (JavaScript's Array.prototype.sort order).
    assert canonical_json({"｡": 1, "\U0001f600": 2}) == '{"\U0001f600":2,"｡":1}'
    assert canonical_json({"b": 1, "a": 2, "é": 3}) == '{"a":2,"b":1,"é":3}'


def test_effectful_grant_without_an_effect_is_refused() -> None:
    origin = VECTORS["origin-identity"]["origin"]
    claims = {
        "typ": "ks-knowledge-operation+jwt",
        "iss": "mission-control",
        "aud": "ks-executor",
        "sub": origin["subject"],
        "jti": "jti-1",
        "iat": 1000,
        "nbf": 1000,
        "exp": 1300,
        "tenant": origin["tenantId"],
        "application": origin["applicationId"],
        "binding": "aiengineer-postgres",
        "origin": origin,
        "operations": ["knowledge.apply"],
        "effect": None,
        "dispatchId": "d-1",
        "recovery": None,
    }
    with pytest.raises(ValidationError, match="effect"):
        CredentialClaims.model_validate(claims)
    assert schema_accepts("credential-claims.v2", claims)


# ---------------------------------------------------------------- 3. vector sweep


def _replay(vector: dict[str, Any]) -> str | None:
    """Replay one vector by its shape; return a skip reason for an unknown shape."""

    handled = False
    if "value" in vector and "canonical" in vector:
        assert canonical_json(vector["value"]) == vector["canonical"]
        if "digest" in vector:
            assert digest_canonical(vector["value"]) == vector["digest"]
        handled = True
    if "value" in vector and any(key in vector for key in ("refusal", "error", "invalid")):
        with pytest.raises(CanonicalizationError):
            canonical_json(vector["value"])
        handled = True
    if "envelope" in vector:
        envelope = OperationEnvelope.model_validate(vector["envelope"])
        if "envelopeDigest" in vector:
            assert envelope.digest() == vector["envelopeDigest"]
        handled = True
    if "origin" in vector:
        Origin.model_validate(vector["origin"])
        handled = True
    if "effect" in vector and isinstance(vector["effect"], dict):
        EffectBinding.model_validate(vector["effect"])
        handled = True
    for key in ("credentialClaims", "claims", "credential"):
        if isinstance(vector.get(key), dict):
            claims = CredentialClaims.model_validate(vector[key])
            assert schema_accepts("credential-claims.v2", vector[key])
            if "currentCallerOriginDigest" in vector:
                # The new attempt is the credential origin (current_caller_origin).
                assert claims.origin.digest() == vector["currentCallerOriginDigest"]
            if "originatingOriginDigest" in vector and "envelope" in vector:
                effect = vector["envelope"]["effect"]
                assert (
                    Origin.model_validate(effect["originatingOrigin"]).digest()
                    == (vector["originatingOriginDigest"])
                )
                assert claims.effect is not None and claims.recovery is not None
                assert claims.effect.effectKey == claims.recovery.effectKey == effect["effectKey"]
            handled = True
    if isinstance(vector.get("request"), dict) and vector["request"].get("schemaVersion") == (
        "knowledge-read-intent-request.v1"
    ):
        request = KnowledgeReadIntentRequest.model_validate(vector["request"])
        assert schema_accepts("knowledge-read-intent-request.v1", vector["request"])
        assert canonical_json(request.payload()) == vector["canonical"]
        assert digest_canonical(request.payload()) == vector["payloadDigest"]
        handled = True
    if isinstance(vector.get("result"), dict) and vector["result"].get("schemaVersion") == (
        "knowledge-read-intent-result.v1"
    ):
        result = KnowledgeReadIntentResult.model_validate(vector["result"])
        assert schema_accepts("knowledge-read-intent-result.v1", vector["result"])
        assert canonical_json(result.model_dump(mode="json")) == vector["canonical"]
        assert digest_canonical(vector["result"]) == vector["digest"]
        handled = True
    if isinstance(vector.get("receiptLookup"), dict):
        document = vector["receiptLookup"]
        lookup = RECEIPT_LOOKUP.validate_python(document)
        assert schema_accepts("receipt-lookup.v2", document)
        assert lookup.model_dump(mode="json") == document
        if "receiptLookupDigest" in vector:
            assert digest_canonical(document) == vector["receiptLookupDigest"]
        if isinstance(lookup, ReceiptFound) and lookup.receipt.outcome == "pending_dispatch":
            # Host rule: a queued effect settles only from the composed delivery state.
            settled = settlement_from_delivery(lookup.receipt, lookup.delivery)
            if lookup.delivery is not None and lookup.delivery.state == "applied":
                assert settled is not None and settled.state is JournalState.APPLIED
                assert not pending_delivery(None, lookup)
            elif lookup.delivery is not None and lookup.delivery.state == "revoked":
                assert settled is not None and settled.state is JournalState.REJECTED
            else:
                assert settled is None
            with pytest.raises(ValueError, match="not a settlement"):
                settlement_from_receipt(lookup.receipt, reconciled=True)
        handled = True
    return None if handled else f"unhandled vector shape: {vector['id']}"


@pytest.mark.parametrize("vector_id", sorted(VECTORS))
def test_every_golden_vector_replays_by_shape(vector_id: str) -> None:
    reason = _replay(VECTORS[vector_id])
    if reason is not None:
        pytest.skip(reason)


def test_effect_scoped_recovery_vector_is_present() -> None:
    recovery_vectors = [
        vector
        for vector in GOLDEN["vectors"]
        if "recovery" in vector["id"]
        and any(key in vector for key in ("credentialClaims", "claims"))
    ]
    if not recovery_vectors:
        pytest.skip("awaiting E-KS: effect-scoped recovery dispatch golden vector (dependency)")
    for vector in recovery_vectors:
        claims = CredentialClaims.model_validate(vector.get("credentialClaims") or vector["claims"])
        assert claims.recovery is not None
