"""Bounded, offline validation of captured output bytes against frozen schemas."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from mission_control.application.context.pack_service import ArtifactBytesPort
from mission_control.domain.authoring.canonical import canonical_json, sha256_digest
from mission_control.domain.context.refs import parse_artifact_ref, parse_workspace_candidate_ref
from mission_control.domain.outputs.contracts import ExactOutput, OutputForm
from mission_control.domain.programs.completion import ArtifactValidationCheck

_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_MAX_SCHEMA_BYTES = 1_048_576
_MAX_SCHEMA_EXPANSION = 10_000


def _bounded_schema_expansion(
    schema: dict[str, Any], targets: dict[str, dict[str, Any] | bool]
) -> bool:
    """Conservatively count local-reference/combinator expansion without expanding it.

    Memoization makes a shared reference DAG cheap to inspect, while summing its
    cost at every use detects exponential evaluation. Cycles are unsupported.
    Counting all containers (including unused definitions/annotations) deliberately
    overestimates work. This is a static expansion cap, not a validator time limit.
    """
    costs: dict[int, int] = {}
    active: set[int] = set()

    def cost(value: Any) -> int:
        if not isinstance(value, dict | list):
            return 1
        identity = id(value)
        if identity in active:
            raise ValueError("recursive artifact schema is unsupported")
        if identity in costs:
            return costs[identity]
        active.add(identity)
        children = list(value.values()) if isinstance(value, dict) else value
        if isinstance(value, dict):
            children += [targets[value[key]] for key in ("$ref", "$dynamicRef") if key in value]
        total = 1
        for child in children:
            total += cost(child)
            if total > _MAX_SCHEMA_EXPANSION:
                total = _MAX_SCHEMA_EXPANSION + 1
                break
        active.remove(identity)
        costs[identity] = total
        return total

    return cost(schema) <= _MAX_SCHEMA_EXPANSION


def supported_schema(json_schema: dict[str, Any]) -> bool:
    """Qualify the bounded Draft 2020-12 subset without resolving external resources.

    Resource identifiers and non-fragment references are rejected, including inside
    nested schemas. This intentionally conservative subset cannot change resolution
    scope or trigger the validator's remote reference retrieval. Regex keywords are
    unqualified until a bounded regex engine is available. Draft 2020-12 ``format``
    remains an annotation, not a validation assertion. Local-reference cycles and
    excessive static reference/combinator expansion are refused before capture.
    """
    try:
        encoded = json.dumps(json_schema, allow_nan=False).encode("utf-8")
        if len(encoded) > _MAX_SCHEMA_BYTES:
            return False
        pending: list[Any] = [json_schema]
        references: list[str] = []
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                unsupported = ("$id", "$recursiveRef", "pattern", "patternProperties")
                if any(key in item for key in unsupported):
                    return False
                if "$schema" in item and item["$schema"] != _DIALECT:
                    return False
                for key in ("$ref", "$dynamicRef"):
                    if key in item and (
                        not isinstance(item[key], str) or not item[key].startswith("#")
                    ):
                        return False
                    if key in item:
                        references.append(item[key])
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        Draft202012Validator.check_schema(json_schema)
        registry: Registry[Any] = Registry()  # ty: ignore[invalid-type-form]
        resolver = registry.resolver_with_root(
            Resource.from_contents(json_schema, default_specification=DRAFT202012)
        )
        targets: dict[str, dict[str, Any] | bool] = {}
        for reference in set(references):
            target = resolver.lookup(reference).contents
            if not isinstance(target, dict | bool):
                return False
            targets[reference] = target
        if not _bounded_schema_expansion(json_schema, targets):
            return False
    except (SchemaError, Unresolvable, TypeError, ValueError, RecursionError, UnicodeError):
        return False
    return True


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("nonfinite JSON number")
    return parsed


def _reject_constant(value: str) -> Any:
    raise ValueError("nonfinite JSON constant")


def strict_json_loads(text: str) -> Any:
    """Strict JSON (no duplicate keys, no nonfinite numbers); raises ValueError/RecursionError."""

    return json.loads(
        text,
        object_pairs_hook=_object,
        parse_constant=_reject_constant,
        parse_float=_finite_float,
    )


async def validate_artifact(
    artifacts: ArtifactBytesPort,
    *,
    request_scope: str,
    output_slot: str,
    schema_ref: str,
    schema_digest: str,
    json_schema: dict[str, Any],
    artifact_ref: str,
    max_bytes: int = 1_048_576,
) -> ArtifactValidationCheck:
    """Validate custody, exact bytes and JSON shape; never accept provider prose.

    Capture exceptions propagate for activity retry. Missing custody can arrive
    later and is pending. Evidence records contain digests, never artifact bodies.
    """
    artifact_digest: str | None = None

    def result(
        status: Literal["satisfied", "unsatisfied", "pending", "unavailable"], reason: str
    ) -> ArtifactValidationCheck:
        material = {
            "validator_version": "artifact-json/1",
            "request_scope": request_scope,
            "output_slot": output_slot,
            "schema_ref": schema_ref,
            "schema_digest": schema_digest,
            "artifact_ref": artifact_ref,
            "artifact_digest": artifact_digest,
            "max_bytes": max_bytes,
            "status": status,
            "reason_code": reason,
        }
        return ArtifactValidationCheck(
            output_slot=output_slot,
            schema_ref=schema_ref,
            schema_digest=schema_digest,
            artifact_ref=artifact_ref,
            artifact_digest=artifact_digest,
            status=status,
            reason_code=reason,
            evidence_digest=sha256_digest(material),
        )

    if max_bytes <= 0:
        return result("unavailable", "invalid_capture_limit")
    parsed = parse_artifact_ref(artifact_ref)
    if parsed is None and parse_workspace_candidate_ref(artifact_ref) is None:
        return result("unsatisfied", "invalid_artifact_ref")
    if parsed is not None and parsed[0] != request_scope:
        return result("unsatisfied", "artifact_scope_mismatch")
    if not supported_schema(json_schema):
        return result("unavailable", "schema_unsupported")
    if sha256_digest(json_schema) != schema_digest:
        return result("unavailable", "schema_digest_mismatch")
    content = await artifacts.capture(
        artifact_ref, request_scope=request_scope, max_text_bytes=max_bytes
    )
    if content is None:
        return result("pending", "artifact_unavailable")
    artifact_digest = content.content_digest
    if content.source_ref != artifact_ref:
        return result("unsatisfied", "artifact_ref_mismatch")
    if content.size_bytes < 0 or content.size_bytes > max_bytes:
        return result("unsatisfied", "artifact_size_limit")
    media = content.media_type.split(";", 1)[0].strip().lower()
    if media != "application/json" and not (
        media.startswith("application/") and media.endswith("+json")
    ):
        return result("unavailable", "artifact_media_unsupported")
    if content.text is None:
        return result("pending", "artifact_bytes_unavailable")
    try:
        raw = content.text.encode("utf-8")
    except UnicodeError:
        return result("unsatisfied", "artifact_encoding_invalid")
    if len(raw) > max_bytes or len(raw) != content.size_bytes:
        return result("unsatisfied", "artifact_size_mismatch")
    if "sha256:" + hashlib.sha256(raw).hexdigest() != content.content_digest:
        return result("unsatisfied", "artifact_digest_mismatch")
    try:
        instance = json.loads(
            content.text,
            object_pairs_hook=_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (ValueError, RecursionError):
        return result("unsatisfied", "artifact_json_invalid")
    try:
        invalid = next(
            Draft202012Validator(json_schema, registry=Registry()).iter_errors(instance), None
        )
    except (Unresolvable, RecursionError, ValueError, TypeError):
        return result("unavailable", "schema_unsupported")
    if invalid is not None:
        return result("unsatisfied", "artifact_schema_invalid")
    return result("satisfied", "artifact_schema_valid")


def validate_output_revision(
    revision: ExactOutput,
    *,
    request_scope: str,
    run_id: str,
    obligation_key: str,
    output_slot: str,
    schema_ref: str,
    schema_digest: str,
    json_schema: dict[str, Any],
    max_bytes: int = 1_048_576,
) -> ArtifactValidationCheck:
    """Validate a host-selected immutable named value, never a model-emitted revision ref.

    Output content digests cover canonical-json/1 bytes, unlike artifact raw-byte hashes.
    The scoped store selects the exact finalized operation/attempt/generation before this
    function is called. The criteria still validate the actual canonical value against
    their own frozen schema, independently of the submission's shape check.
    """
    reference = f"output-revision:{revision.revision_id}#digest={revision.content_digest}"
    observed_digest: str | None = None

    def result(
        status: Literal["satisfied", "unsatisfied", "unavailable"], reason: str
    ) -> ArtifactValidationCheck:
        return ArtifactValidationCheck(
            output_slot=output_slot,
            schema_ref=schema_ref,
            schema_digest=schema_digest,
            artifact_ref=reference,
            artifact_digest=observed_digest,
            status=status,
            reason_code=reason,
            evidence_digest=sha256_digest(
                {
                    "validator_version": "named-output-json/1",
                    "request_scope": request_scope,
                    "run_id": run_id,
                    "obligation_key": obligation_key,
                    "revision_id": revision.revision_id,
                    "declared_digest": revision.content_digest,
                    "observed_digest": observed_digest,
                    "schema_ref": schema_ref,
                    "schema_digest": schema_digest,
                    "status": status,
                    "reason": reason,
                }
            ),
        )

    candidate = revision.candidate
    if revision.run_id != run_id or revision.obligation_key != obligation_key:
        return result("unsatisfied", "output_revision_owner_mismatch")
    if (
        revision.form not in {OutputForm.STRUCTURED, OutputForm.CONTROL_RECORD}
        or candidate.get("kind") != "inline"
        or "value" not in candidate
        or candidate.get("form") != revision.form.value
    ):
        return result("unsatisfied", "output_revision_form_invalid")
    if candidate.get("schema_ref") != schema_ref:
        return result("unsatisfied", "output_revision_schema_pin_mismatch")
    try:
        raw = canonical_json(candidate["value"])
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return result("unsatisfied", "output_revision_json_invalid")
    observed_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if observed_digest != revision.content_digest or candidate.get("digest") != observed_digest:
        return result("unsatisfied", "output_revision_digest_mismatch")
    if max_bytes <= 0 or len(raw) > max_bytes:
        return result("unsatisfied", "output_revision_size_limit")
    if not supported_schema(json_schema):
        return result("unavailable", "schema_unsupported")
    if sha256_digest(json_schema) != schema_digest:
        return result("unavailable", "schema_digest_mismatch")
    try:
        invalid = next(
            Draft202012Validator(json_schema, registry=Registry()).iter_errors(candidate["value"]),
            None,
        )
    except (Unresolvable, RecursionError, ValueError, TypeError):
        return result("unavailable", "schema_unsupported")
    if invalid is not None:
        return result("unsatisfied", "output_revision_schema_invalid")
    return result("satisfied", "output_revision_schema_valid")
