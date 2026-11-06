"""WI-03 trusted assessment contracts: Python reproduces the KS bytes and refuses what KS refuses.

The vectors are byte copies of Knowledge Services' golden file (KS 7d12c0f / eff4c8e,
``packages/knowledge-operation-protocol/src/assessment.ts``).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from mission_control.contracts.knowledge_assessment import (
    DecisionResolveRequest,
    ReportObservationRequest,
    ReportReviewRequest,
    ReportUseRequest,
    assessment_request_digest,
)
from mission_control.contracts.knowledge_protocol import canonical_json, digest_canonical
from mission_control.contracts.knowledge_protocol_results import CredentialClaims

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_protocol"
GOLDEN = json.loads(
    (FIXTURES / "knowledge-operation-protocol.v2.golden.json").read_text(encoding="utf-8")
)
VECTORS = {vector["id"]: vector for vector in GOLDEN["vectors"]}


def schema(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / f"{name}.schema.json").read_text(encoding="utf-8"))


def test_judge_credential_bytes_and_digest_match() -> None:
    vector = VECTORS["evaluator-credential-judge"]
    claims = CredentialClaims.model_validate(vector["claims"])
    dumped = claims.model_dump(mode="json")
    assert canonical_json(dumped) == vector["canonical"]
    assert digest_canonical(dumped) == vector["digest"]
    jsonschema.Draft202012Validator(schema("credential-claims.v2")).validate(dumped)


def test_a_credential_without_a_grant_omits_evaluation_on_the_wire() -> None:
    claims = dict(VECTORS["evaluator-credential-judge"]["claims"])
    claims.pop("evaluation")
    claims["operations"] = ["decision.resolve"]
    dumped = CredentialClaims.model_validate(claims).model_dump(mode="json")
    assert "evaluation" not in dumped
    jsonschema.Draft202012Validator(schema("credential-claims.v2")).validate(dumped)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"evaluation": None}, "evaluator grant"),
        ({"operations": ["report.observe", "report.register"]}, "assessment and read"),
        ({"operations": ["report.review"]}, "reviewer"),
    ],
)
def test_evaluator_credentials_refuse_like_ks(change: dict[str, object], message: str) -> None:
    claims = dict(VECTORS["evaluator-credential-judge"]["claims"]) | change
    if "report.register" in str(change):
        claims["effect"] = {"effectKey": "e-1", "boundEffectDigest": "sha256:" + "a" * 64}
    with pytest.raises(ValidationError, match=message):
        CredentialClaims.model_validate(claims)


@pytest.mark.parametrize(
    ("vector_id", "model", "name"),
    [
        ("report-use-official", ReportUseRequest, "report-use.v1"),
        ("report-review-approve", ReportReviewRequest, "report-review.v1"),
        ("decision-resolve", DecisionResolveRequest, "decision-resolve.v1"),
    ],
)
def test_request_bytes_and_digests_match(vector_id: str, model: type, name: str) -> None:
    vector = VECTORS[vector_id]
    request = model.model_validate(vector["request"])
    dumped = request.model_dump(mode="json", by_alias=True)
    assert canonical_json(dumped) == vector["canonical"]
    assert assessment_request_digest(request) == vector["digest"]
    jsonschema.Draft202012Validator(schema(name)).validate(dumped)


def test_a_report_decision_names_its_own_report_and_never_floats() -> None:
    request = VECTORS["report-use-official"]["request"]
    other = dict(request) | {"subject": dict(request["subject"]) | {"digest": "sha256:" + "b" * 64}}
    with pytest.raises(ValidationError):
        ReportUseRequest.model_validate(other)
    with pytest.raises(ValidationError):
        ReportUseRequest.model_validate(dict(request) | {"purpose": "publish"})
    with pytest.raises(ValidationError):
        ReportUseRequest.model_validate(dict(request) | {"normalizedValues": {"x": 1.5}})


def test_an_observation_request_observes_something() -> None:
    report = VECTORS["report-use-official"]["request"]["report"]
    with pytest.raises(ValidationError):
        ReportObservationRequest.model_validate(
            {
                "schema": "report-observation.v1",
                "report": report,
                "observations": [],
                "census": None,
            }
        )
