"""Captured output validation: custody integrity, strict JSON and offline schemas."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

import pytest

from mission_control.application.context.pack_service import ArtifactContent
from mission_control.application.programs.artifact_validation import (
    supported_schema,
    validate_artifact,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.programs.completion import ArtifactValidationCheck

SCOPE = "mc/install/app/tenant"
REF = f"artifact://{SCOPE}/run/report"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["count"],
    "properties": {"count": {"type": "integer", "minimum": 1}},
    "additionalProperties": False,
}


def captured(raw_text: str = '{"count": 1}', **changes: Any) -> ArtifactContent:
    raw = raw_text.encode("utf-8")
    return replace(
        ArtifactContent(
            source_ref=REF,
            durable_ref="object://report",
            content_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            media_type="application/json",
            text=raw_text,
        ),
        **changes,
    )


class Custody:
    def __init__(self, content: ArtifactContent | None) -> None:
        self.content = content
        self.calls: list[tuple[str, str, int]] = []

    async def capture(
        self, source_ref: str, *, request_scope: str, max_text_bytes: int
    ) -> ArtifactContent | None:
        self.calls.append((source_ref, request_scope, max_text_bytes))
        return self.content


async def check(custody: Custody, **changes: Any) -> ArtifactValidationCheck:
    kwargs: dict[str, Any] = {
        "request_scope": SCOPE,
        "output_slot": "report",
        "schema_ref": "schema:report@1",
        "schema_digest": sha256_digest(SCHEMA),
        "json_schema": SCHEMA,
        "artifact_ref": REF,
    }
    kwargs.update(changes)
    return await validate_artifact(custody, **kwargs)


@pytest.mark.asyncio
async def test_captured_output_has_repeatable_scoped_evidence() -> None:
    custody = Custody(captured())
    first = await check(custody)
    second = await check(custody)
    assert first == second
    assert first.status == "satisfied"
    assert first.reason_code == "artifact_schema_valid"
    assert custody.content is not None
    assert first.artifact_digest == custody.content.content_digest
    assert custody.calls == [(REF, SCOPE, 1_048_576)] * 2
    assert first.evidence_digest.startswith("sha256:")
    renamed = await check(custody, output_slot="another")
    assert renamed.evidence_digest != first.evidence_digest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ('{"count":0}', "artifact_schema_invalid"),
        ('{"count":"1"}', "artifact_schema_invalid"),
        ('{"other":1}', "artifact_schema_invalid"),
        ('{"count":1,"extra":true}', "artifact_schema_invalid"),
        ('{"count":0,"count":1}', "artifact_json_invalid"),
        ('{"count":NaN}', "artifact_json_invalid"),
        ('{"count":Infinity}', "artifact_json_invalid"),
        ('{"count":-Infinity}', "artifact_json_invalid"),
        ('{"count":1e999}', "artifact_json_invalid"),
        ('{"count":1} trailing', "artifact_json_invalid"),
        ('{"count":', "artifact_json_invalid"),
    ],
)
async def test_invalid_output_cannot_satisfy_schema(text: str, reason: str) -> None:
    result = await check(Custody(captured(text)))
    assert (result.status, result.reason_code) == ("unsatisfied", reason)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changes", "status", "reason"),
    [
        ({"source_ref": "artifact://other/run/report"}, "unsatisfied", "artifact_ref_mismatch"),
        ({"size_bytes": 2}, "unsatisfied", "artifact_size_mismatch"),
        ({"size_bytes": -1}, "unsatisfied", "artifact_size_limit"),
        ({"size_bytes": 1_048_577}, "unsatisfied", "artifact_size_limit"),
        ({"content_digest": "sha256:" + "0" * 64}, "unsatisfied", "artifact_digest_mismatch"),
        ({"text": None}, "pending", "artifact_bytes_unavailable"),
        ({"media_type": "text/plain"}, "unavailable", "artifact_media_unsupported"),
    ],
)
async def test_custody_and_byte_integrity_are_required(
    changes: dict[str, Any], status: str, reason: str
) -> None:
    result = await check(Custody(captured(**changes)))
    assert (result.status, result.reason_code) == (status, reason)


@pytest.mark.asyncio
async def test_missing_capture_is_pending_and_can_later_resolve() -> None:
    custody = Custody(None)
    pending = await check(custody)
    assert (pending.status, pending.reason_code) == ("pending", "artifact_unavailable")
    custody.content = captured()
    available = await check(custody)
    assert available.status == "satisfied"
    assert available.evidence_digest != pending.evidence_digest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ref", "reason"),
    [
        ("https://example.com/report.json", "invalid_artifact_ref"),
        ("model says done", "invalid_artifact_ref"),
        ("workspace-candidate://", "invalid_artifact_ref"),
        ("artifact://other/run/report", "artifact_scope_mismatch"),
    ],
)
async def test_invalid_or_cross_scope_reference_never_reads_custody(ref: str, reason: str) -> None:
    custody = Custody(captured())
    result = await check(custody, artifact_ref=ref)
    assert (result.status, result.reason_code) == ("unsatisfied", reason)
    assert custody.calls == []


@pytest.mark.asyncio
async def test_candidate_and_json_suffix_media_supported() -> None:
    ref = "workspace-candidate://candidate-1"
    custody = Custody(captured(source_ref=ref, media_type="application/report+json; charset=utf-8"))
    assert (await check(custody, artifact_ref=ref)).status == "satisfied"


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "not-a-type"},
        {"$ref": "https://example.com/schema.json"},
        {"$dynamicRef": "https://example.com/schema.json#node"},
        {"$id": "https://example.com/schema.json", "$ref": "#/$defs/value"},
        {"$defs": {"unused": {"$ref": "file:///private/schema.json"}}},
        {"$schema": "http://json-schema.org/draft-07/schema#"},
        {"$recursiveRef": "#"},
        {"type": "string", "pattern": "^(a+)+$"},
        {"patternProperties": {"^(a+)+$": {"type": "string"}}},
        {"properties": {"name": {"type": "string", "pattern": ".*"}}},
        {"const": float("nan")},
    ],
)
def test_unsupported_schema_is_rejected_before_capture(schema: dict[str, Any]) -> None:
    assert not supported_schema(schema)


@pytest.mark.asyncio
async def test_remote_schema_never_reads_custody() -> None:
    custody = Custody(captured())
    result = await check(custody, json_schema={"$ref": "https://example.com/schema.json"})
    assert (result.status, result.reason_code) == ("unavailable", "schema_unsupported")
    assert custody.calls == []


@pytest.mark.asyncio
async def test_changed_schema_digest_never_reads_custody() -> None:
    custody = Custody(captured())
    result = await check(custody, schema_digest="sha256:" + "0" * 64)
    assert (result.status, result.reason_code) == ("unavailable", "schema_digest_mismatch")
    assert custody.calls == []


@pytest.mark.asyncio
async def test_local_schema_references_enforce_required_shape() -> None:
    schema = {"$defs": {"report": SCHEMA}, "$ref": "#/$defs/report"}
    assert supported_schema(schema)
    valid = await check(
        Custody(captured()), json_schema=schema, schema_digest=sha256_digest(schema)
    )
    invalid = await check(
        Custody(captured('{"count":0}')), json_schema=schema, schema_digest=sha256_digest(schema)
    )
    assert valid.status == "satisfied"
    assert invalid.reason_code == "artifact_schema_invalid"


@pytest.mark.asyncio
async def test_unresolved_local_reference_is_unavailable() -> None:
    schema = {"$ref": "#/$defs/missing"}
    assert not supported_schema(schema)
    result = await check(
        Custody(captured()), json_schema=schema, schema_digest=sha256_digest(schema)
    )
    assert (result.status, result.reason_code) == ("unavailable", "schema_unsupported")


@pytest.mark.asyncio
async def test_configured_byte_bound_is_forwarded_and_enforced() -> None:
    custody = Custody(captured())
    result = await check(custody, max_bytes=3)
    assert (result.status, result.reason_code) == ("unsatisfied", "artifact_size_limit")
    assert custody.calls == [(REF, SCOPE, 3)]


@pytest.mark.asyncio
async def test_unicode_byte_length_is_not_character_length() -> None:
    text = '{"title":"café"}'
    schema = {"type": "object"}
    custody = Custody(captured(text))
    result = await check(custody, json_schema=schema, schema_digest=sha256_digest(schema))
    assert result.status == "satisfied"
    custody.content = captured(text, size_bytes=len(text))
    assert (await check(custody)).reason_code == "artifact_size_mismatch"


@pytest.mark.asyncio
async def test_capture_failure_remains_retryable() -> None:
    class InterruptedCustody(Custody):
        async def capture(
            self, source_ref: str, *, request_scope: str, max_text_bytes: int
        ) -> ArtifactContent | None:
            raise TimeoutError("payload store temporarily unavailable")

    with pytest.raises(TimeoutError):
        await check(InterruptedCustody(None))


@pytest.mark.asyncio
async def test_primitive_json_output_is_validated_by_declared_type() -> None:
    schema = {"type": "integer"}
    result = await check(
        Custody(captured("12")), json_schema=schema, schema_digest=sha256_digest(schema)
    )
    assert result.status == "satisfied"


@pytest.mark.asyncio
async def test_recursive_schema_cannot_crash_validator() -> None:
    schema = {"$ref": "#"}
    assert not supported_schema(schema)
    custody = Custody(captured())
    result = await check(custody, json_schema=schema, schema_digest=sha256_digest(schema))
    assert (result.status, result.reason_code) == ("unavailable", "schema_unsupported")
    assert custody.calls == []


def repeated_reference_schema(depth: int) -> dict[str, Any]:
    definitions: dict[str, Any] = {"level0": SCHEMA}
    for level in range(1, depth + 1):
        definitions[f"level{level}"] = {
            "anyOf": [{"$ref": f"#/$defs/level{level - 1}"} for _ in range(2)]
        }
    return {"$defs": definitions, "$ref": f"#/$defs/level{depth}"}


@pytest.mark.asyncio
async def test_small_schema_with_exponential_reference_expansion_refused_before_capture() -> None:
    schema = repeated_reference_schema(25)
    assert not supported_schema(schema)
    custody = Custody(captured('{"count":0}'))
    result = await check(custody, json_schema=schema, schema_digest=sha256_digest(schema))
    assert (result.status, result.reason_code) == ("unavailable", "schema_unsupported")
    assert custody.calls == []


@pytest.mark.asyncio
async def test_bounded_reused_reference_dag_still_validates_without_mutating_schema() -> None:
    schema = repeated_reference_schema(4)
    digest = sha256_digest(schema)
    assert supported_schema(schema)
    assert (await check(Custody(captured()), json_schema=schema, schema_digest=digest)).status == (
        "satisfied"
    )
    assert (
        await check(Custody(captured('{"count":0}')), json_schema=schema, schema_digest=digest)
    ).reason_code == "artifact_schema_invalid"
    assert sha256_digest(schema) == digest


@pytest.mark.parametrize(
    "schema",
    [
        {"$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}}, "$ref": "#/$defs/a"},
        {"$defs": {"value": {"const": 1}}, "$ref": "#/$defs/value/const"},
        {"$ref": 17},
        {"anyOf": "not-a-schema-array"},
    ],
)
def test_cyclic_or_malformed_reference_graph_is_not_supported(schema: dict[str, Any]) -> None:
    assert not supported_schema(schema)
