"""Candidate checks against one pinned obligation (OUTPUT-CONTRACTS §§2-3).

A submission is refused, never repaired, when it names an undeclared promise, the wrong form,
the wrong schema version or shape, bytes that differ from the declared digest, a bare id no
single admitted binding completes, or a control record that claims authority. Expected and
optional enforcement never make invalid material valid. JSON Schema validation is injected
(``SchemaValidator``) so the domain stays free of I/O and third-party validators.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.outputs.contracts import (
    AdmittedBinding,
    CandidateRef,
    Finding,
    OutputError,
    OutputErrorCode,
    OutputForm,
    OutputObligation,
    RecoveryOwner,
    SubmitOutput,
    collection_digest,
    tagged_digest,
)

SchemaValidator = Callable[[dict[str, Any], Any], Sequence[str]]
HANDLE: Final = re.compile(
    r"^kh:(?P<binding>[a-z][a-z0-9_.-]{0,119})/(?P<kind>[a-z_]+)/"
    r"(?P<id>[A-Za-z0-9][A-Za-z0-9._:-]{0,199})@(?P<version>[a-z][a-z0-9_.-]*\.v[0-9]+)$"
)
BARE_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
# A control record is attributed content under an admitted schema; it never grants command,
# review or acceptance authority, whatever it says.
AUTHORITY_KEYS: Final = frozenset(
    {
        "accept",
        "acceptance",
        "approve",
        "approval",
        "authority",
        "command",
        "commands",
        "grant",
        "grants",
        "review_authority",
        "reviewer",
        "waive",
        "waiver",
    }
)


def text_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def value_digest(value: Any) -> str:
    return sha256_digest(value)


def code_change_digest(candidate: CandidateRef) -> str:
    """The identity of a proposed change: repository, base, head/patch and changed scope."""

    return tagged_digest(
        "mc.code_change.v1",
        {
            "repository": candidate.repository,
            "base": candidate.base,
            "head": candidate.head,
            "patch_digest": candidate.patch_digest,
            "changed_paths": sorted(candidate.changed_paths),
        },
    )


def pointer_get(value: Any, pointer: str) -> tuple[bool, Any]:
    current = value
    for raw in pointer.split("/")[1:]:
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


@dataclass(frozen=True)
class CandidateDecision:
    candidate: CandidateRef
    findings: tuple[Finding, ...] = ()
    resolution: dict[str, str] | None = None


@dataclass(frozen=True)
class SubmissionCheck:
    """Accepted decisions per item, or the first refusal."""

    decisions: tuple[CandidateDecision, ...] = ()
    error: OutputError | None = None
    findings: tuple[Finding, ...] = field(default_factory=tuple)


class CandidateRefused(ValueError):
    def __init__(self, error: OutputError) -> None:
        super().__init__(error.safe_message)
        self.error = error


def _refuse(
    code: OutputErrorCode,
    message: str,
    *,
    pointer: str | None = None,
    retry: Literal["retryable", "repairable", "terminal"] = "repairable",
    owner: RecoveryOwner = "producer",
) -> CandidateRefused:
    return CandidateRefused(
        OutputError(
            code=code,
            field_pointer=pointer,
            safe_message=message[:500],
            retry_state=retry,
            recovery_owner=owner,
            available_actions=("submit_output",) if retry == "repairable" else (),
        )
    )


def check_candidate(
    obligation: OutputObligation,
    candidate: CandidateRef,
    *,
    bindings: Sequence[AdmittedBinding] = (),
    validate_schema: SchemaValidator | None = None,
    pointer: str = "/items/0",
) -> CandidateDecision:
    """Check one candidate; raise :class:`CandidateRefused` with the typed refusal."""

    contract = obligation.contract
    if candidate.form is not contract.form:
        raise _refuse(
            OutputErrorCode.FORM_MISMATCH,
            f"obligation {obligation.key} promises {contract.form}, not {candidate.form}",
            pointer=f"{pointer}/form",
        )
    if contract.media_type is not None and candidate.media_type not in {
        None,
        contract.media_type,
    }:
        raise _refuse(
            OutputErrorCode.MEDIA_TYPE_MISMATCH,
            f"media type {candidate.media_type} is not the contracted {contract.media_type}",
            pointer=f"{pointer}/media_type",
        )
    form = contract.form
    if form is OutputForm.TEXT:
        return _text(obligation, candidate, pointer)
    if form in {OutputForm.STRUCTURED, OutputForm.CONTROL_RECORD}:
        return _structured(obligation, candidate, validate_schema, pointer)
    if form is OutputForm.CODE_CHANGE:
        return _code_change(obligation, candidate, pointer)
    if form is OutputForm.REFERENCE:
        return _reference(candidate, bindings, pointer)
    if form is OutputForm.FILE:
        if candidate.kind not in {"path", "handle"}:
            raise _refuse(OutputErrorCode.MISSING_FIELD, "a file names its path or handle")
        if candidate.size_bytes is None or candidate.media_type is None:
            raise _refuse(
                OutputErrorCode.MISSING_FIELD,
                "a file declares its exact size and media type",
                pointer=pointer,
            )
        return CandidateDecision(candidate)
    if form is OutputForm.COLLECTION:
        return _collection(obligation, candidate, pointer)
    # effect_receipt: a pending dispatch has no receipt yet; it is recorded, never fulfilling.
    if candidate.effect_key is None:
        raise _refuse(OutputErrorCode.MISSING_FIELD, "an effect receipt names its effect key")
    findings: tuple[Finding, ...] = ()
    if candidate.receipt_ref is None:
        findings = (Finding(code="receipt_pending", message="no native receipt yet"),)
    return CandidateDecision(candidate, findings)


def _collection(
    obligation: OutputObligation, candidate: CandidateRef, pointer: str
) -> CandidateDecision:
    """An exact manifest (WI-07): distinct exact members; an inline manifest's digest is its
    member set plus its value (order-free); coverage entries name listed members only."""

    if not candidate.members:
        raise _refuse(OutputErrorCode.MISSING_FIELD, "a collection names exact members")
    if len({member.ref for member in candidate.members}) != len(candidate.members):
        raise _refuse(OutputErrorCode.DUPLICATE_DELIVERABLE, "collection members are distinct")
    if candidate.kind == "inline":
        if candidate.text is not None:
            raise _refuse(OutputErrorCode.FORM_MISMATCH, "a collection manifest carries no text")
        if collection_digest(candidate.members, candidate.value) != candidate.digest:
            raise _refuse(
                OutputErrorCode.DIGEST_MISMATCH,
                "the manifest differs from its declared member-set digest",
                pointer=f"{pointer}/digest",
            )
    coverage = obligation.contract.coverage
    findings: tuple[Finding, ...] = ()
    if coverage is not None:
        found, entries = pointer_get(candidate.value, coverage.pointer)
        if not found or not isinstance(entries, list):
            findings = (
                Finding(code="coverage_absent", message="the manifest names no covered subjects"),
            )
        else:
            listed = {(member.ref, member.digest) for member in candidate.members}
            for index, entry in enumerate(entries):
                if not (
                    isinstance(entry, dict) and (entry.get("ref"), entry.get("digest")) in listed
                ):
                    raise _refuse(
                        OutputErrorCode.MEMBER_NOT_LISTED,
                        f"coverage entry {index} names no exact listed member",
                        pointer=f"{pointer}/value{coverage.pointer}/{index}",
                    )
    return CandidateDecision(candidate, findings)


def _text(obligation: OutputObligation, candidate: CandidateRef, pointer: str) -> CandidateDecision:
    contract = obligation.contract
    if candidate.kind != "inline" or candidate.text is None:
        raise _refuse(
            OutputErrorCode.MISSING_FIELD,
            "a text output carries its exact bytes inline",
            pointer=f"{pointer}/text",
        )
    if candidate.value is not None:
        raise _refuse(OutputErrorCode.FORM_MISMATCH, "a text output carries no JSON value")
    if contract.encoding is not None and candidate.encoding not in {None, contract.encoding}:
        raise _refuse(OutputErrorCode.ENCODING_INVALID, "text encoding differs from the contract")
    if text_digest(candidate.text) != candidate.digest:
        raise _refuse(
            OutputErrorCode.DIGEST_MISMATCH,
            "the text bytes differ from the declared digest",
            pointer=f"{pointer}/digest",
        )
    size = len(candidate.text.encode("utf-8"))
    if contract.max_bytes is not None and size > contract.max_bytes:
        raise _refuse(OutputErrorCode.SIZE_EXCEEDED, f"text is {size} bytes, over the limit")
    if candidate.size_bytes is not None and candidate.size_bytes != size:
        raise _refuse(OutputErrorCode.DIGEST_MISMATCH, "declared size differs from the bytes")
    return CandidateDecision(candidate)


def _structured(
    obligation: OutputObligation,
    candidate: CandidateRef,
    validate_schema: SchemaValidator | None,
    pointer: str,
) -> CandidateDecision:
    contract = obligation.contract
    schema = contract.schema_pin
    assert schema is not None  # the contract validator requires it
    if candidate.kind != "inline" or candidate.value is None:
        raise _refuse(
            OutputErrorCode.MISSING_FIELD,
            "a structured output carries its exact canonical value inline",
            pointer=f"{pointer}/value",
        )
    if candidate.schema_ref != schema.ref:
        raise _refuse(
            OutputErrorCode.SCHEMA_PIN_MISMATCH,
            f"value is declared under {candidate.schema_ref!r}, the contract pins {schema.ref!r}",
            pointer=f"{pointer}/schema_ref",
        )
    if value_digest(candidate.value) != candidate.digest:
        raise _refuse(
            OutputErrorCode.DIGEST_MISMATCH,
            "the canonical value differs from the declared digest",
            pointer=f"{pointer}/digest",
        )
    findings: list[Finding] = []
    if schema.body is None:
        findings.append(
            Finding(code="schema_unbound", message=f"no validator is bound for {schema.ref}")
        )
    elif validate_schema is None:
        # A bound schema with no validator never passes silently (fail closed).
        raise _refuse(
            OutputErrorCode.SCHEMA_UNVALIDATED,
            f"{schema.ref} is bound but no schema validator is composed",
            pointer=f"{pointer}/value",
            retry="terminal",
            owner="host",
        )
    else:
        errors = list(validate_schema(dict(schema.body), candidate.value))
        if errors:
            raise _refuse(
                OutputErrorCode.SCHEMA_INVALID,
                f"value does not satisfy {schema.ref}: {errors[0]}",
                pointer=f"{pointer}/value",
            )
    if contract.form is OutputForm.CONTROL_RECORD and isinstance(candidate.value, dict):
        claimed = sorted(AUTHORITY_KEYS & set(candidate.value))
        if claimed:
            raise _refuse(
                OutputErrorCode.SELF_GRANTED_AUTHORITY,
                f"a control record cannot grant authority: {', '.join(claimed)}",
                pointer=f"{pointer}/value",
                retry="terminal",
            )
    if contract.member_contract is not None:
        found, members = pointer_get(candidate.value, contract.member_contract.pointer)
        if not found or not isinstance(members, list) or not members:
            raise _refuse(
                OutputErrorCode.MEMBER_REF_NOT_EXACT,
                "an index lists its exact members (ref and digest)",
                pointer=f"{pointer}/value{contract.member_contract.pointer}",
            )
        for index, member in enumerate(members):
            if not (
                isinstance(member, dict)
                and isinstance(member.get("ref"), str)
                and isinstance(member.get("digest"), str)
                and re.fullmatch(r"sha256:[0-9a-f]{64}", member["digest"])
            ):
                raise _refuse(
                    OutputErrorCode.MEMBER_REF_NOT_EXACT,
                    f"index member {index} is not an exact ref and digest",
                    pointer=f"{pointer}/value{contract.member_contract.pointer}/{index}",
                )
    if contract.coverage is not None:
        found, _ = pointer_get(candidate.value, contract.coverage.pointer)
        if not found:
            findings.append(
                Finding(code="coverage_absent", message="the value names no covered subjects")
            )
    return CandidateDecision(candidate, tuple(findings))


def _code_change(
    obligation: OutputObligation, candidate: CandidateRef, pointer: str
) -> CandidateDecision:
    contract = obligation.contract
    if candidate.repository is None or candidate.base is None:
        raise _refuse(
            OutputErrorCode.MISSING_FIELD,
            "a code change names its exact repository and base",
            pointer=pointer,
        )
    if candidate.head is None and candidate.patch_digest is None:
        raise _refuse(
            OutputErrorCode.MISSING_FIELD,
            "a code change names its exact head or patch digest",
            pointer=pointer,
        )
    if not candidate.changed_paths:
        raise _refuse(OutputErrorCode.MISSING_FIELD, "a code change declares its changed scope")
    if contract.repository is not None and candidate.repository != contract.repository:
        raise _refuse(
            OutputErrorCode.REPOSITORY_MISMATCH,
            f"repository {candidate.repository} is not the contracted {contract.repository}",
            pointer=f"{pointer}/repository",
        )
    if code_change_digest(candidate) != candidate.digest:
        raise _refuse(
            OutputErrorCode.DIGEST_MISMATCH,
            "the change identity differs from the declared digest",
            pointer=f"{pointer}/digest",
        )
    return CandidateDecision(candidate)


def _reference(
    candidate: CandidateRef, bindings: Sequence[AdmittedBinding], pointer: str
) -> CandidateDecision:
    if candidate.kind == "handle":
        if candidate.ref is None or HANDLE.match(candidate.ref) is None:
            raise _refuse(
                OutputErrorCode.AMBIGUOUS_REFERENCE,
                "a reference names an exact handle (binding, kind, id and revision)",
                pointer=f"{pointer}/ref",
            )
        return CandidateDecision(candidate)
    if candidate.kind != "native_id":
        raise _refuse(OutputErrorCode.FORM_MISMATCH, "a reference is a handle or a native id")
    if candidate.ref is None or BARE_ID.match(candidate.ref) is None:
        raise _refuse(OutputErrorCode.UNRESOLVED_REFERENCE, "the bare id is not a native id")
    if candidate.native_kind is None:
        raise _refuse(
            OutputErrorCode.MISSING_FIELD,
            "a bare id names its native kind",
            pointer=f"{pointer}/native_kind",
        )
    matches = [
        binding
        for binding in bindings
        if candidate.native_kind in binding.native_kinds
        and (candidate.issuer is None or candidate.issuer == binding.issuer)
        and (candidate.native_revision is None or candidate.native_revision == binding.revision)
    ]
    if not matches:
        raise _refuse(
            OutputErrorCode.UNRESOLVED_REFERENCE,
            f"no admitted binding of this invocation completes bare id {candidate.ref}",
            pointer=f"{pointer}/ref",
        )
    if len(matches) > 1:
        raise _refuse(
            OutputErrorCode.AMBIGUOUS_REFERENCE,
            f"bare id {candidate.ref} matches {len(matches)} admitted bindings; name the handle",
            pointer=f"{pointer}/ref",
        )
    binding = matches[0]
    handle = f"kh:{binding.binding_id}/{candidate.native_kind}/{candidate.ref}@{binding.revision}"
    resolved = candidate.model_copy(
        update={"kind": "handle", "ref": handle, "issuer": binding.issuer}
    )
    resolution = {
        "bare_id": candidate.ref,
        "binding_id": binding.binding_id,
        "rule": "single_admitted_binding",
        "handle": handle,
    }
    return CandidateDecision(
        resolved,
        (Finding(code="bare_id_resolved", message=f"resolved through {binding.binding_id}"),),
        resolution,
    )


def check_submission(
    obligation: OutputObligation | None,
    request: SubmitOutput,
    *,
    position: str | None,
    bindings: Sequence[AdmittedBinding] = (),
    validate_schema: SchemaValidator | None = None,
) -> SubmissionCheck:
    """All-or-nothing: every item is checked against the one pinned obligation."""

    if obligation is None:
        return SubmissionCheck(
            error=OutputError(
                code=OutputErrorCode.OBLIGATION_UNDECLARED,
                field_pointer="/obligation_key",
                safe_message=f"no admitted promise {request.obligation_key} for this run",
                retry_state="terminal",
            )
        )
    if not position:
        return SubmissionCheck(
            error=OutputError(
                code=OutputErrorCode.POSITION_UNBOUND,
                safe_message="the host bound no owner position to this invocation",
                retry_state="terminal",
                recovery_owner="host",
            )
        )
    if obligation.owner_position != position:
        return SubmissionCheck(
            error=OutputError(
                code=OutputErrorCode.POSITION_MISMATCH,
                position=position,
                field_pointer="/obligation_key",
                safe_message=f"{obligation.key} belongs to {obligation.owner_position}",
                retry_state="terminal",
            )
        )
    deliverables = [item.deliverable_id for item in request.items]
    if len(set(deliverables)) != len(deliverables):
        return SubmissionCheck(
            error=OutputError(
                code=OutputErrorCode.DUPLICATE_DELIVERABLE,
                field_pointer="/items",
                safe_message="one act offers one revision of each deliverable",
            )
        )
    if len(deliverables) > obligation.cardinality.max:
        return SubmissionCheck(
            error=OutputError(
                code=OutputErrorCode.CARDINALITY_EXCEEDED,
                field_pointer="/items",
                safe_message=(
                    f"{len(deliverables)} deliverables exceed the promised maximum "
                    f"{obligation.cardinality.max}"
                ),
            )
        )
    decisions: list[CandidateDecision] = []
    for index, item in enumerate(request.items):
        try:
            decisions.append(
                check_candidate(
                    obligation,
                    item,
                    bindings=bindings,
                    validate_schema=validate_schema,
                    pointer=f"/items/{index}",
                )
            )
        except CandidateRefused as refused:
            return SubmissionCheck(error=refused.error)
    return SubmissionCheck(decisions=tuple(decisions))


__all__ = [
    "AUTHORITY_KEYS",
    "CandidateDecision",
    "CandidateRefused",
    "SchemaValidator",
    "SubmissionCheck",
    "check_candidate",
    "check_submission",
    "code_change_digest",
    "pointer_get",
    "text_digest",
    "value_digest",
]
