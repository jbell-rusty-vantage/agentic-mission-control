"""Host attribution of Stage Graph route facts (OVE-171, OUTPUT-CONTRACTS §7).

A route predicate compares a *pinned attributed canonical fact*, never agent prose: when a stage
that declares facts is admitted, the result decision reads each fact at its JSON pointer from the
exact accepted output bytes (custody, size and digest checked, strict JSON), and records it under
the host-owned ``route_facts`` key of the accepted result with its evidence ref
(``<artifact ref>#<pointer>@<digest>``). A named value the stage submitted through
``submit_output`` (an ``output-revision:`` ref) is read from its fulfilled exact revision: the
canonical-json value whose digest is the revision identity, never artifact custody (L1-02).
Anything it cannot read exactly is recorded unknown with a reason; a provider-supplied
``route_facts`` key is always discarded first.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, Final

from mission_control.application.context.pack_service import ArtifactBytesPort
from mission_control.application.programs.artifact_validation import strict_json_loads
from mission_control.domain.authoring.canonical import canonical_json
from mission_control.domain.authoring.contracts import StageNode
from mission_control.domain.authoring.graph_routes import MAX_FACT_STRING_CHARS, scalar_type
from mission_control.domain.outputs.contracts import ExactOutput, OutputForm
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from mission_control.domain.programs.routing import ROUTE_FACTS_KEY

MAX_FACT_ARTIFACT_BYTES: Final = 1_048_576
OUTPUT_REVISION_PREFIX: Final = "output-revision:"


def _pointer(document: Any, pointer: str) -> tuple[bool, Any]:
    """RFC 6901 resolution over parsed JSON (``~1`` and ``~0`` unescaped); no wildcards."""

    current = document
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                return False, None
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                return False, None
            index = int(token)
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def _unknown(reason: str) -> dict[str, Any]:
    return {"status": "unknown", "reason": reason}


async def _read_json(
    artifacts: ArtifactBytesPort, *, request_scope: str, artifact_ref: str
) -> tuple[Any, str | None, str | None]:
    """(document, digest, failure reason) for one exact JSON artifact."""

    content = await artifacts.capture(
        artifact_ref, request_scope=request_scope, max_text_bytes=MAX_FACT_ARTIFACT_BYTES
    )
    if content is None or content.text is None:
        return None, None, "artifact_unavailable"
    if content.source_ref != artifact_ref:
        return None, content.content_digest, "artifact_ref_mismatch"
    raw = content.text.encode("utf-8")
    if (
        len(raw) > MAX_FACT_ARTIFACT_BYTES
        or len(raw) != content.size_bytes
        or "sha256:" + hashlib.sha256(raw).hexdigest() != content.content_digest
    ):
        return None, content.content_digest, "artifact_integrity_mismatch"
    try:
        document = strict_json_loads(content.text)
    except (ValueError, RecursionError):
        return None, content.content_digest, "artifact_json_invalid"
    return document, content.content_digest, None


def _read_named(
    ref: str, fulfilled: Mapping[str, ExactOutput]
) -> tuple[Any, str | None, str | None]:
    """(document, digest, failure reason) for one fulfilled named value, exactly."""

    revision = fulfilled.get(ref)
    if revision is None:
        return None, None, "output_revision_unfulfilled"
    candidate = revision.candidate
    if (
        ref != f"{OUTPUT_REVISION_PREFIX}{revision.revision_id}#digest={revision.content_digest}"
        or revision.form not in {OutputForm.STRUCTURED, OutputForm.CONTROL_RECORD}
        or candidate.get("kind") != "inline"
        or "value" not in candidate
    ):
        return None, revision.content_digest, "output_revision_form_invalid"
    try:
        raw = canonical_json(candidate["value"])
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return None, revision.content_digest, "artifact_json_invalid"
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if digest != revision.content_digest or len(raw) > MAX_FACT_ARTIFACT_BYTES:
        return None, digest, "artifact_integrity_mismatch"
    return candidate["value"], digest, None


async def attribute_route_facts(
    artifacts: ArtifactBytesPort | None,
    *,
    request_scope: str,
    stage: StageNode,
    interpreter: StageGraphInterpreter,
    operation_result: dict[str, Any],
    validated_digests: Mapping[str, str] | None = None,
    fulfilled: Mapping[str, ExactOutput] | None = None,
) -> dict[str, Any]:
    """The accepted result with its host-attributed facts (and never a provider's).

    ``validated_digests`` pins each artifact ref to the digest the completion validation read;
    a re-read whose bytes differ is unknown (``artifact_digest_changed``), never a fact of
    other bytes than the ones validated. ``fulfilled`` holds the stage's accepted named
    revisions by ref (``None`` when the result is not admitted: no named fact is read)."""

    result = {key: value for key, value in operation_result.items() if key != ROUTE_FACTS_KEY}
    if not stage.facts:
        return result
    documents: dict[str, tuple[Any, str | None, str | None]] = {}
    facts: dict[str, dict[str, Any]] = {}
    validated = {
        slot.output_slot_id for slot in stage.output_slots if slot.validation_schema is not None
    }
    for fact in stage.facts:
        if fact.output_slot_id not in validated:
            # Facts come from schema-validated bytes only (the result decision validated them).
            facts[fact.fact_id] = _unknown("fact_output_unvalidated")
            continue
        refs = interpreter.output_slot_refs(stage.stage_id, fact.output_slot_id, result)
        if len(set(refs)) != 1:
            facts[fact.fact_id] = _unknown("fact_output_not_exactly_one")
            continue
        (ref,) = set(refs)
        if ref.startswith(OUTPUT_REVISION_PREFIX):
            if fulfilled is None:
                facts[fact.fact_id] = _unknown("artifact_reader_unavailable")
                continue
            if ref not in documents:
                documents[ref] = _read_named(ref, fulfilled)
        elif artifacts is None:
            facts[fact.fact_id] = _unknown("artifact_reader_unavailable")
            continue
        elif ref not in documents:
            documents[ref] = await _read_json(
                artifacts, request_scope=request_scope, artifact_ref=ref
            )
        document, digest, failure = documents[ref]
        if failure is not None:
            facts[fact.fact_id] = _unknown(failure)
            continue
        pinned = (validated_digests or {}).get(ref)
        if validated_digests is not None and pinned != digest:
            facts[fact.fact_id] = _unknown("artifact_digest_changed")
            continue
        found, value = _pointer(document, fact.pointer)
        if not found:
            facts[fact.fact_id] = _unknown("fact_pointer_absent")
        elif scalar_type(value) != fact.value_type:
            facts[fact.fact_id] = _unknown("fact_type_mismatch")
        elif (isinstance(value, str) and len(value) > MAX_FACT_STRING_CHARS) or (
            isinstance(value, int) and not isinstance(value, bool) and not -(2**63) <= value < 2**63
        ):
            facts[fact.fact_id] = _unknown("fact_value_oversized")
        else:
            facts[fact.fact_id] = {
                "status": "known",
                "value": value,
                "evidence_ref": f"{ref}#{fact.pointer}@{digest}",
            }
    return {**result, ROUTE_FACTS_KEY: facts}


__all__ = ["MAX_FACT_ARTIFACT_BYTES", "OUTPUT_REVISION_PREFIX", "attribute_route_facts"]
