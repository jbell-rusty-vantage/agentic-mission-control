"""K01 golden contracts (SPRINT-V-DESIGN §9): Python reproduces the TypeScript bytes and digests.

The fixture is a byte copy of Knowledge Services'
``packages/knowledge-operation-protocol/fixtures/knowledge-operation-protocol.v2.golden.json``,
with its published JSON Schemas beside it. No handwritten semantic renaming: wire names only.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mission_control.contracts.knowledge_protocol import (
    PROTOCOL_VERSION,
    CanonicalizationError,
    EffectBinding,
    KnowledgeReadIntentRequest,
    KnowledgeReadIntentResult,
    OperationEnvelope,
    Origin,
    bind_effect,
    bound_effect_digest,
    can_transition,
    canonical_json,
    digest_bytes,
    digest_canonical,
    read_intent_snapshot_digest,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_protocol"
GOLDEN = json.loads(
    (FIXTURES / "knowledge-operation-protocol.v2.golden.json").read_text(encoding="utf-8")
)
VECTORS = {vector["id"]: vector for vector in GOLDEN["vectors"]}


def test_golden_header() -> None:
    assert GOLDEN["protocolVersion"] == PROTOCOL_VERSION
    assert GOLDEN["canonicalization"] == "kop-canonical-json.v1"
    payload = base64.b64decode(GOLDEN["payload"]["base64"])
    assert len(payload) == GOLDEN["payload"]["payloadBytes"]
    assert digest_bytes(payload) == GOLDEN["payload"]["payloadDigest"]


def test_canonical_unicode_bytes_and_digest_match() -> None:
    vector = VECTORS["canonical-unicode"]
    assert canonical_json(vector["value"]) == vector["canonical"]
    assert digest_canonical(vector["value"]) == vector["digest"]
    # No normalization: composed and decomposed forms stay distinct, CRLF survives as escapes.
    assert canonical_json({"s": "Café"}) != canonical_json({"s": "Café"})
    assert canonical_json({"s": "a\r\nb"}) == '{"s":"a\\r\\nb"}'
    with pytest.raises(CanonicalizationError):
        canonical_json({"n": 1.5})


def test_origin_identity_digest_matches_and_rejects_template_coordinates() -> None:
    vector = VECTORS["origin-identity"]
    origin = Origin.model_validate(vector["origin"])
    assert origin.identity() == vector["identity"]
    assert canonical_json(origin.identity()) == vector["canonical"]
    assert origin.digest() == vector["digest"]
    retry = vector["origin"] | {
        "mission": vector["origin"]["mission"] | {"operationAttempt": 2},
        "invocationId": "inv-0002",
        "authenticatedAt": "2026-10-24T20:05:00Z",
    }
    assert Origin.model_validate(retry).digest() == vector["retryOriginDigest"]
    recovery = vector["origin"] | {
        "kind": "recovery",
        "subject": "mission-control-reconciler",
        "mission": None,
        "recoveryAuthorityRef": "recovery-grant-7",
        "invocationId": "inv-0009",
        "authenticatedAt": "2026-10-24T20:30:00Z",
    }
    assert Origin.model_validate(recovery).digest() == vector["recoveryOriginDigest"]
    template_mission = vector["origin"]["mission"] | {"operationId": "manifest-template/research"}
    template = vector["origin"] | {"mission": template_mission}
    with pytest.raises(ValidationError):
        Origin.model_validate(template)
    with pytest.raises(ValidationError):
        Origin.model_validate(vector["origin"] | {"extra": 1})
    with pytest.raises(ValidationError):
        Origin.model_validate(recovery | {"recoveryAuthorityRef": None})


def test_effect_binding_matches() -> None:
    vector = VECTORS["effect-binding"]
    payload = base64.b64decode(GOLDEN["payload"]["base64"])
    origin = Origin.model_validate(vector["effect"]["originatingOrigin"])
    assert digest_canonical(vector["boundEffectInput"]) == vector["effect"]["boundEffectDigest"]
    assert bound_effect_digest(payload, origin) == vector["effect"]["boundEffectDigest"]
    bound = bind_effect(vector["effect"]["effectKey"], payload, origin)
    assert bound.model_dump(mode="json") == vector["effect"]
    assert EffectBinding.model_validate(vector["effect"]) == bound
    # Per-authentication fields never move the digest; different bytes do.
    reauthenticated = Origin.model_validate(
        vector["effect"]["originatingOrigin"]
        | {"invocationId": "inv-0003", "authenticatedAt": "2026-10-24T21:00:00Z"}
    )
    assert bound_effect_digest(payload, reauthenticated) == bound.boundEffectDigest
    assert bound_effect_digest(payload + b" ", origin) != bound.boundEffectDigest


def test_apply_envelope_validates_and_digests_identically() -> None:
    vector = VECTORS["apply-envelope"]
    envelope = OperationEnvelope.model_validate(vector["envelope"])
    assert envelope.digest() == vector["envelopeDigest"]
    assert envelope.model_dump(mode="json") == vector["envelope"]
    with pytest.raises(ValidationError):
        OperationEnvelope.model_validate(
            vector["envelope"] | {"protocolVersion": "ks.knowledge_operation.v1"}
        )
    with pytest.raises(ValidationError):
        OperationEnvelope.model_validate(vector["envelope"] | {"effect": None})
    with pytest.raises(ValidationError):
        OperationEnvelope.model_validate(vector["envelope"] | {"unknown": True})


def test_state_machine_matches_protocol() -> None:
    assert can_transition("queued", "running")
    assert can_transition("running", "held")
    assert not can_transition("held", "running")
    assert not can_transition("succeeded", "failed")


@pytest.mark.parametrize(
    ("schema_name", "vector_id", "path"),
    [
        ("origin.v2", "origin-identity", ("origin",)),
        ("effect-binding.v2", "effect-binding", ("effect",)),
        ("operation-envelope.v2", "apply-envelope", ("envelope",)),
    ],
)
def test_vectors_satisfy_published_json_schema(
    schema_name: str, vector_id: str, path: tuple[str, ...]
) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    index = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))
    schema = json.loads((FIXTURES / index["schemas"][schema_name]).read_text(encoding="utf-8"))
    value = VECTORS[vector_id]
    for key in path:
        value = value[key]
    jsonschema.Draft202012Validator(schema).validate(value)


def test_read_intent_request_bytes_and_payload_digest_match() -> None:
    """OVE-204 slice 4: the inline `knowledge.read_intent` request (KS `read-intent-request`)."""

    vector = VECTORS["read-intent-request"]
    assert vector["nativeContract"] == {"name": "knowledge-read-intent", "version": "v1"}
    request = KnowledgeReadIntentRequest.model_validate(vector["request"])
    assert canonical_json(request.payload()) == vector["canonical"]
    assert digest_canonical(request.payload()) == vector["payloadDigest"]


def test_read_intent_result_digests_match_and_native_floats_are_not_canonical() -> None:
    """Per-op `contentDigest` over protocol JSON (a float travels as its decimal string), the
    snapshot digest over the op summaries and the result digest, all `digest_canonical`."""

    vector = VECTORS["read-intent-result"]
    result = KnowledgeReadIntentResult.model_validate(vector["result"])
    assert [digest_canonical(op.body) for op in result.operations] == vector["contentDigests"]
    assert digest_canonical(vector["wireRows"]) == vector["contentDigests"][0]
    assert (
        read_intent_snapshot_digest(result.atKnowledgeSeq, result.operations)
        == (vector["snapshotDigest"])
    )
    assert canonical_json(result.model_dump(mode="json")) == vector["canonical"]
    assert digest_canonical(result.model_dump(mode="json")) == vector["digest"]
    with pytest.raises(CanonicalizationError):
        canonical_json(vector["nativeRows"])
