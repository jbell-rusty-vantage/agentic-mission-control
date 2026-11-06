"""Host-validated hook context contributions (OUTPUT-CONTRACTS §11; ADR-0062; Sprint OC WI-17).

A hook script observes a bounded event snapshot. This module holds the pure rules for what it
may additionally *see* and *propose*:

- **Scoped host reads** (:class:`HostReadScope`): a declared, admitted, least-privilege read
  capability over named workspace paths or the attempt's sealed transfer inputs. The host
  resolves the read; a target outside the declared scope, under host-owned state or over its
  byte bound refuses. There is no implicit whole-workspace, Knowledge Services, credential or
  private-middleware read: those kinds do not exist.
- **Staged candidates** (:class:`StagedCandidate`): a file a hook *proposes* with its own digest
  and a path intent. The host attributes it (:class:`AttributedCandidate`, origin = the hook
  invocation) and installs it only at a supported safe boundary after validating it against the
  hook's :class:`StageGrant` and the receiver's :class:`ProtectedPaths`. A candidate never
  touches the live workspace by itself, never rewrites a sealed input mount, the transfer index
  or host-owned state, and never lands on an output slot (so it cannot self-fulfill a promise).
- **Operation requests** (:class:`OperationRequestProposal`): model work, semantic preparation
  or an external write a hook wants is a *separate ordinary operation*, proposed with a typed
  template and admitted through the normal admission path; scripts are not an effect executor.

What a result may carry depends on the event (:func:`event_role`): a before-effect guard
answers allow/deny; an observation/post-effect event may add findings, candidates and
operation requests but cannot undo an already committed effect; a before-compaction event's
preservation proposal belongs to the compaction consumer (WI-18), not to this module.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mission_control.domain.capabilities.hooks import HookEvent
from mission_control.domain.context.transfer import INDEX_PATH, INPUTS_ROOT

HOST_STATE_ROOT: Final = "/.mission"
MAX_READ_BYTES: Final = 65_536
MAX_CANDIDATE_BYTES: Final = 65_536
MAX_STAGE_TOTAL_BYTES: Final = 262_144
MAX_CANDIDATES: Final = 32
MAX_OPERATION_REQUESTS: Final = 4
_PATH_LIMIT: Final = 512
_NAME = r"^[a-z0-9][a-z0-9._-]{0,63}$"
_DIGEST = r"^sha256:[0-9a-f]{64}$"
_CANDIDATE_NAMESPACE = "mission-control:hook-candidate"
_REQUEST_NAMESPACE = "mission-control:hook-operation-request"


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def content_digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def stable_uuid(namespace: str, basis: str) -> str:
    """A deterministic RFC 4122 shaped identifier (version 5 layout) of `basis` in
    `namespace`: the same contribution always gets the same identity, with no randomness."""

    value = hashlib.sha256(f"{namespace}\x00{basis}".encode()).hexdigest()[:32]
    variant = "89ab"[int(value[16], 16) % 4]
    return f"{value[:8]}-{value[8:12]}-5{value[13:16]}-{variant}{value[17:20]}-{value[20:32]}"


# ---------------------------------------------------------------- the event matrix


class HookEventRole(StrEnum):
    """What a hook result may do at an event (OUTPUT-CONTRACTS §11 event capability table)."""

    # Allow/deny with a typed reason; kernel/admission checks run first; a deny prevents the
    # not-yet-executed action.
    GUARD = "before_effect_guard"
    # Findings, staged candidates and operation requests; a deny cannot undo or retroactively
    # deny what already happened.
    OBSERVATION = "observation"
    # A bounded preservation proposal consumed by the compaction wrapper (WI-18).
    COMPACTION = "before_compaction"


_ROLES: Final[dict[HookEvent, HookEventRole]] = {
    HookEvent.SESSION_START: HookEventRole.GUARD,
    HookEvent.BEFORE_PROMPT: HookEventRole.GUARD,
    HookEvent.BEFORE_MODEL: HookEventRole.GUARD,
    HookEvent.BEFORE_TOOL: HookEventRole.GUARD,
    HookEvent.BEFORE_SHELL: HookEventRole.GUARD,
    HookEvent.BEFORE_MCP: HookEventRole.GUARD,
    HookEvent.SUBAGENT_START: HookEventRole.GUARD,
    HookEvent.AFTER_MODEL: HookEventRole.OBSERVATION,
    HookEvent.AFTER_TOOL: HookEventRole.OBSERVATION,
    HookEvent.AFTER_TOOL_FAILURE: HookEventRole.OBSERVATION,
    HookEvent.AFTER_SHELL: HookEventRole.OBSERVATION,
    HookEvent.AFTER_FILE_EDIT: HookEventRole.OBSERVATION,
    HookEvent.AFTER_COMPACTION: HookEventRole.OBSERVATION,
    HookEvent.SUBAGENT_STOP: HookEventRole.OBSERVATION,
    HookEvent.STOP: HookEventRole.OBSERVATION,
    HookEvent.SESSION_END: HookEventRole.OBSERVATION,
    HookEvent.BEFORE_COMPACTION: HookEventRole.COMPACTION,
}
if set(_ROLES) != set(HookEvent):  # pragma: no cover - import-time guard
    raise RuntimeError("every Hook Event needs a contribution role")

# The events that fire after an effect already ran: a deny there is a finding, never an undo.
COMMITTED_EFFECT_EVENTS: Final = frozenset(
    {
        HookEvent.AFTER_TOOL,
        HookEvent.AFTER_TOOL_FAILURE,
        HookEvent.AFTER_SHELL,
        HookEvent.AFTER_FILE_EDIT,
        HookEvent.SUBAGENT_STOP,
    }
)


def event_role(event: HookEvent | str) -> HookEventRole:
    return _ROLES[HookEvent(event)]


def permits_contributions(event: HookEvent | str) -> bool:
    """Staged candidates and operation requests are observation results only."""

    return event_role(event) is HookEventRole.OBSERVATION


# ---------------------------------------------------------------- paths


def normalize_path(path: str) -> str | None:
    """An absolute, normalized POSIX workspace path, or ``None`` when it is not one.

    No backslash, NUL, ``.``/``..`` segment, empty segment or trailing slash survives."""

    if not path or len(path) > _PATH_LIMIT or "\\" in path or "\x00" in path:
        return None
    if not path.startswith("/") or path.endswith("/"):
        return None
    parts = path.split("/")[1:]
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return path


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    out = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif pattern[index] == "*":
            out.append("[^/]*")
            index += 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return re.compile("^" + "".join(out) + "$")


def path_matches(pattern: str, path: str) -> bool:
    """``*`` matches within one segment, ``**`` across segments; everything else is literal."""

    return _pattern_regex(pattern).match(path) is not None


def _under(path: str, root: str) -> bool:
    """`path` is `root` or below it, compared case-folded: on a case-insensitive backend
    `/.Mission/x` and `/Inputs/x` are the protected paths themselves."""

    path, root = path.casefold(), root.casefold()
    return path == root or path.startswith(root.rstrip("/") + "/")


def _check_pattern(pattern: str) -> str:
    """A declared path pattern: absolute, no traversal, not the whole workspace, not host state."""

    literal = pattern.replace("**", "x").replace("*", "x")
    if normalize_path(literal) is None:
        raise ValueError(f"path pattern {pattern!r} is not an absolute workspace path")
    head = pattern.split("*", 1)[0]
    if head.rstrip("/") == "":
        raise ValueError(f"path pattern {pattern!r} names the whole workspace")
    if _under(head.rstrip("/") or "/", HOST_STATE_ROOT) or path_matches(
        pattern.casefold(), INDEX_PATH
    ):
        raise ValueError(f"path pattern {pattern!r} names host-owned state")
    return pattern


# ---------------------------------------------------------------- declared capabilities


class HostReadScope(_Closed):
    """One declared, admitted host-mediated read capability of a hook (least privilege).

    ``workspace`` reads named paths (patterns) through the receiver's actual backend;
    ``transfer_input`` reads named bindings of the attempt's sealed transfer plan, verified
    against the plan's exact digests. ``events`` narrows when the read is resolved (empty: every
    event the hook runs at). A read over ``max_bytes`` refuses; nothing is truncated."""

    name: str = Field(pattern=_NAME)
    kind: Literal["workspace", "transfer_input"]
    paths: tuple[str, ...] = ()
    bindings: tuple[str, ...] = ()
    events: frozenset[HookEvent] = frozenset()
    max_bytes: int = Field(default=16_384, ge=1, le=MAX_READ_BYTES)

    @model_validator(mode="after")
    def least_privilege(self) -> HostReadScope:
        if self.kind == "workspace":
            if not self.paths or self.bindings:
                raise ValueError("a workspace read scope names paths and no bindings")
            for pattern in self.paths:
                _check_pattern(pattern)
        else:
            if not self.bindings or self.paths:
                raise ValueError("a transfer_input read scope names bindings and no paths")
            for binding in self.bindings:
                if not re.fullmatch(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", binding):
                    raise ValueError(f"binding name {binding!r} is invalid")
        if len(set(self.paths)) != len(self.paths) or len(set(self.bindings)) != len(self.bindings):
            raise ValueError("read scope entries must be unique")
        return self

    def applies_to(self, event: HookEvent) -> bool:
        return not self.events or event in self.events

    def covers(self, path: str) -> bool:
        return self.kind == "workspace" and any(path_matches(item, path) for item in self.paths)


class StageGrant(_Closed):
    """What a hook may *propose*: candidate paths (patterns), bounds and the operation templates
    it may request. A grant is never permission to write: the host installs or refuses."""

    paths: tuple[str, ...] = Field(default=(), max_length=16)
    max_candidates: int = Field(default=8, ge=1, le=MAX_CANDIDATES)
    max_total_bytes: int = Field(default=65_536, ge=1, le=MAX_STAGE_TOTAL_BYTES)
    operation_templates: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def bounded(self) -> StageGrant:
        for pattern in self.paths:
            _check_pattern(pattern)
            head = pattern.split("*", 1)[0]
            if _under(head.rstrip("/") or "/", INPUTS_ROOT) or path_matches(
                pattern.casefold(), f"{INPUTS_ROOT}/x"
            ):
                raise ValueError(f"stage path {pattern!r} names the sealed input mounts")
        if not self.paths and not self.operation_templates:
            raise ValueError("a stage grant names candidate paths or operation templates")
        if len(set(self.operation_templates)) != len(self.operation_templates):
            raise ValueError("operation templates must be unique")
        return self

    def covers(self, path: str) -> bool:
        return any(path_matches(item, path) for item in self.paths)


# ---------------------------------------------------------------- what a script proposes


class StagedCandidate(_Closed):
    """A file a hook proposes (``mc.hook_result.v1`` ``staged_candidates``). It carries no
    origin: the host attributes it to the invocation that returned it."""

    path: str = Field(min_length=1, max_length=_PATH_LIMIT)
    content: str = Field(max_length=MAX_CANDIDATE_BYTES)
    digest: str = Field(pattern=_DIGEST)
    media_type: Literal["text/plain", "text/markdown", "application/json"] = "text/plain"
    note: str | None = Field(default=None, min_length=1, max_length=500)

    @property
    def body(self) -> bytes:
        return self.content.encode("utf-8")


class OperationRequestProposal(_Closed):
    """A request for a separate ordinary operation (model work, semantic preparation or an
    external write). The host admits it through the normal path or refuses; the hook never
    executes it."""

    template: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=500)
    request_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    input_refs: tuple[str, ...] = Field(default=(), max_length=16)


class CandidateOrigin(_Closed):
    """The hook invocation a contribution came from; host-filled, never script-supplied."""

    hook_id: str = Field(min_length=1)
    event: HookEvent
    run_id: str | None = None
    operation_id: str | None = None
    attempt_no: int | None = Field(default=None, ge=1)
    generation: int | None = Field(default=None, ge=1)
    harness_execution_id: str | None = None
    input_digest: str = Field(pattern=_DIGEST)


class AttributedCandidate(_Closed):
    candidate_id: str
    origin: CandidateOrigin
    path: str
    digest: str = Field(pattern=_DIGEST)
    size_bytes: int = Field(ge=0)
    media_type: str
    note: str | None = None


class AttributedOperationRequest(_Closed):
    request_id: str
    origin: CandidateOrigin
    proposal: OperationRequestProposal


class ContributionRefusal(_Closed):
    """A typed, host-generated refusal (never provider text)."""

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    hook_id: str | None = None
    path: str | None = None
    message: str = Field(min_length=1, max_length=500)


def attribute_candidate(
    origin: CandidateOrigin, candidate: StagedCandidate
) -> AttributedCandidate | ContributionRefusal:
    """Attribute one proposal or refuse it: the event must permit contributions, the path must
    be a normalized absolute path and the bytes must carry the digest the hook declared."""

    def refusal(code: str, message: str) -> ContributionRefusal:
        return ContributionRefusal(
            code=code, hook_id=origin.hook_id, path=candidate.path, message=message
        )

    if not permits_contributions(origin.event):
        return refusal(
            "RESULT_NOT_PERMITTED",
            f"{origin.event.value} is a {event_role(origin.event).value} event; "
            "staged candidates are observation results",
        )
    path = normalize_path(candidate.path)
    if path is None:
        return refusal("PATH_INVALID", "candidate path is not a normalized absolute path")
    body = candidate.body
    if len(body) > MAX_CANDIDATE_BYTES:
        return refusal("CANDIDATE_TOO_LARGE", "candidate exceeds the per-file bound")
    if content_digest(body) != candidate.digest:
        return refusal("CANDIDATE_DIGEST_MISMATCH", "candidate bytes differ from their digest")
    basis = "|".join(
        (
            origin.hook_id,
            origin.run_id or "-",
            origin.operation_id or "-",
            str(origin.attempt_no or "-"),
            str(origin.generation or "-"),
            origin.harness_execution_id or "-",
            path,
            candidate.digest,
        )
    )
    return AttributedCandidate(
        candidate_id=stable_uuid(_CANDIDATE_NAMESPACE, basis),
        origin=origin,
        path=path,
        digest=candidate.digest,
        size_bytes=len(body),
        media_type=candidate.media_type,
        note=candidate.note,
    )


def attribute_request(
    origin: CandidateOrigin, proposal: OperationRequestProposal, grant: StageGrant | None
) -> AttributedOperationRequest | ContributionRefusal:
    """Attribute an operation request; only an observation event of a hook whose grant names
    the template may propose it."""

    def refusal(code: str, message: str) -> ContributionRefusal:
        return ContributionRefusal(code=code, hook_id=origin.hook_id, message=message)

    if not permits_contributions(origin.event):
        return refusal(
            "RESULT_NOT_PERMITTED",
            f"{origin.event.value} cannot request operations; requests are observation results",
        )
    if grant is None or proposal.template not in grant.operation_templates:
        return refusal(
            "OPERATION_TEMPLATE_NOT_ADMITTED",
            f"operation template {proposal.template!r} is not in the hook's grant",
        )
    basis = "|".join(
        (origin.hook_id, origin.run_id or "-", origin.operation_id or "-", proposal.request_key)
    )
    return AttributedOperationRequest(
        request_id=stable_uuid(_REQUEST_NAMESPACE, basis), origin=origin, proposal=proposal
    )


# ---------------------------------------------------------------- installation policy


class ProtectedPaths(_Closed):
    """The receiver's paths no candidate may land on: the sealed input mounts and transfer
    index, host-owned state, the plan's own placement paths, context input slots and Skill
    roots, and the output slots (a file there would be captured as the agent's output and could
    self-fulfill a promise)."""

    sealed_paths: frozenset[str] = frozenset()
    output_paths: tuple[str, ...] = ()
    reserved_paths: tuple[str, ...] = ()

    @field_validator("output_paths", "reserved_paths")
    @classmethod
    def absolute(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(item.rstrip("/") or "/" for item in value)


def install_refusal(
    candidate: AttributedCandidate, grant: StageGrant | None, protected: ProtectedPaths
) -> ContributionRefusal | None:
    """The policy refusal of installing ``candidate`` now, or ``None`` when it may proceed to
    the collision/version checks the store and the backend perform."""

    def refusal(code: str, message: str) -> ContributionRefusal:
        return ContributionRefusal(
            code=code, hook_id=candidate.origin.hook_id, path=candidate.path, message=message
        )

    path = candidate.path
    if _under(path, HOST_STATE_ROOT) or _under(path, INDEX_PATH):
        return refusal("HOST_STATE_OVERWRITE", "host-owned state is never a candidate target")
    if _under(path, INPUTS_ROOT) or any(_under(path, item) for item in protected.sealed_paths):
        return refusal("SEALED_INPUT_REWRITE", "a sealed input or used plan path is read-only")
    if any(_under(path, root) or _under(root, path) for root in protected.output_paths):
        return refusal(
            "OUTPUT_SLOT_PATH",
            "a candidate cannot land on an output slot (it would self-fulfill a promise)",
        )
    if any(_under(path, root) or _under(root, path) for root in protected.reserved_paths):
        return refusal("PROTECTED_PATH", "the path belongs to a host-seeded mount")
    if grant is None or not grant.covers(path):
        return refusal("PATH_OUT_OF_GRANT", "the hook's stage grant does not cover the path")
    return None


def batch_refusals(
    candidates: Sequence[AttributedCandidate], grants: dict[str, StageGrant]
) -> dict[str, ContributionRefusal]:
    """Per-installation bounds: one candidate per path (a second one is a collision, both of
    the same path refuse), and each hook's count/byte budget."""

    refused: dict[str, ContributionRefusal] = {}
    by_path: dict[str, list[AttributedCandidate]] = {}
    for item in candidates:
        by_path.setdefault(item.path, []).append(item)
    for path, items in by_path.items():
        if len({item.candidate_id for item in items}) > 1:
            for item in items:
                refused[item.candidate_id] = ContributionRefusal(
                    code="PATH_COLLISION",
                    hook_id=item.origin.hook_id,
                    path=path,
                    message="two candidates target the same path at one boundary",
                )
    usage: dict[str, tuple[int, int]] = {}
    for item in _unique(candidates):
        if item.candidate_id in refused:
            continue
        grant = grants.get(item.origin.hook_id)
        count, size = usage.get(item.origin.hook_id, (0, 0))
        count, size = count + 1, size + item.size_bytes
        usage[item.origin.hook_id] = (count, size)
        if grant is not None and (count > grant.max_candidates or size > grant.max_total_bytes):
            refused[item.candidate_id] = ContributionRefusal(
                code="CANDIDATE_BUDGET",
                hook_id=item.origin.hook_id,
                path=item.path,
                message="the hook's candidate count or byte budget is exhausted",
            )
    return refused


def _unique(candidates: Iterable[AttributedCandidate]) -> list[AttributedCandidate]:
    return list({item.candidate_id: item for item in candidates}.values())


__all__ = [
    "COMMITTED_EFFECT_EVENTS",
    "HOST_STATE_ROOT",
    "AttributedCandidate",
    "AttributedOperationRequest",
    "CandidateOrigin",
    "ContributionRefusal",
    "HookEventRole",
    "HostReadScope",
    "OperationRequestProposal",
    "ProtectedPaths",
    "StageGrant",
    "StagedCandidate",
    "attribute_candidate",
    "attribute_request",
    "batch_refusals",
    "content_digest",
    "event_role",
    "install_refusal",
    "normalize_path",
    "path_matches",
    "permits_contributions",
]
