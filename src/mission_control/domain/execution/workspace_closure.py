"""`mc.workspace_closure.v1`: what the agent could see when an attempt settled (OVE-204 slice 5).

A **Workspace Closure** is the evidence of an attempt's workspace at a settled boundary: every
file the agent could reach (the folded `files` channel on the text-only backend; the exclusive
writable slots and `/workspace` of a sandbox) with its raw-byte digest, its slot and where it
lived, and, within the Application Profile's caps, its bytes in the content-addressed payload
store. It is an attribute of the unit's result checkpoint point, not a point of its own: the
result point's `workspace_checkpoint_ref` is `workspace-closure://<closure_id>#<closure_digest>`.

Capture degrades, it never fails the attempt: past the caps a body is `withheld_cap` and the
closure says `complete = false`; a sensitive slot's body is `withheld_sensitive`, a body that
contains a resolved secret value `withheld_secret`, a Context Packet input `withheld_input`
(its bytes are the packet's durable custody, already named by the materialization manifest).

Bodies are referenced as `closure-body://sha256:<hex>?bytes=<n>&type=<media>` and read through
the run-bound artifact body reader. Pure, frozen and secret-free.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import parse_qsl, quote, unquote
from uuid import NAMESPACE_URL, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.execution.cognition_points import point_id_for
from mission_control.domain.graph_runtime.identities import (
    DIGEST_PATTERN,
    UNIT_KEY_PATTERN,
    QualifiedCheckpointKey,
)

WORKSPACE_CLOSURE_SCHEMA: Final = "mc.workspace_closure.v1"
CLOSURE_REF_PREFIX: Final = "workspace-closure://"
CLOSURE_BODY_PREFIX: Final = "closure-body://"
_DIGEST_PREFIX: Final = "sha256:"
_HEX: Final = frozenset("0123456789abcdef")

ClosureBoundary = Literal["attempt_settled", "attempt_failed", "attempt_cancelled"]
ClosureBackend = Literal["state", "docker", "langsmith", "daytona"]
ClosureDestination = Literal[
    "state_channel", "sandbox_writable", "sandbox_workdir", "sandbox_upload"
]
ClosureBodyState = Literal[
    "promoted",
    "withheld_cap",
    "withheld_sensitive",
    "withheld_secret",
    "withheld_input",
    "unreadable",
]
ClosureEncoding = Literal["utf-8", "base64", "binary"]
SlotAccess = Literal["read_only", "exclusive_write"]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClosureFile(_Contract):
    """One file of the closure: raw-byte digest, slot, destination and body custody."""

    path: str = Field(min_length=2, max_length=1024, pattern=r"^/")
    size_bytes: int = Field(ge=0)
    digest: str = Field(pattern=DIGEST_PATTERN)
    slot: str | None = Field(default=None, min_length=1, max_length=256)
    slot_access: SlotAccess | None = None
    destination: ClosureDestination
    encoding: ClosureEncoding = "binary"
    media_type: str = Field(default="application/octet-stream", min_length=1, max_length=256)
    body_state: ClosureBodyState
    body_ref: str | None = Field(default=None, min_length=1, max_length=2048)
    candidate_id: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def promoted_bodies_are_referenced(self) -> ClosureFile:
        if (self.body_state == "promoted") != (self.body_ref is not None):
            raise ValueError("a closure file has a body reference exactly when it is promoted")
        if self.body_ref is not None:
            ref = parse_closure_body_ref(self.body_ref)
            if ref.digest != self.digest or ref.bytes != self.size_bytes:
                raise ValueError("a closure body reference names another body")
        return self


class ClosureLimits(_Contract):
    """The caps in force at capture and which of them cut the closure short."""

    max_files: int = Field(ge=0)
    max_bytes: int = Field(ge=0)
    applied: tuple[Literal["max_files", "max_bytes"], ...] = ()
    omitted_files: int = Field(default=0, ge=0)
    """Files past `max_files`: not listed at all (their digests are unknown to the closure)."""


class WorkspaceClosure(_Contract):
    """`mc.workspace_closure.v1`: the workspace of one attempt at one settled boundary."""

    schema_version: Literal["mc.workspace_closure.v1"] = WORKSPACE_CLOSURE_SCHEMA
    closure_id: str = Field(min_length=36, max_length=36)
    run_id: str = Field(min_length=1, max_length=512)
    unit_key: str = Field(pattern=UNIT_KEY_PATTERN)
    execution_generation: int = Field(ge=1)
    harness_execution_id: str | None = Field(default=None, min_length=1, max_length=256)
    point_id: str = Field(min_length=36, max_length=36)
    result_checkpoint: QualifiedCheckpointKey
    boundary: ClosureBoundary
    backend: ClosureBackend
    roots: tuple[str, ...] = ()
    files: tuple[ClosureFile, ...] = ()
    limits: ClosureLimits
    files_digest_channel: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    """The result point's text digest of the `files` channel (cross-check only)."""
    closure_digest: str = Field(pattern=DIGEST_PATTERN)
    recorded_at: AwareDatetime

    @property
    def complete(self) -> bool:
        return not self.limits.applied

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.files)

    @property
    def promoted_bytes(self) -> int:
        return sum(item.size_bytes for item in self.files if item.body_state == "promoted")

    @property
    def ref(self) -> str:
        return closure_ref(self.closure_id, self.closure_digest)

    @model_validator(mode="after")
    def identity_is_derived(self) -> WorkspaceClosure:
        paths = [item.path for item in self.files]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("closure files are sorted by path and unique")
        if self.closure_digest != closure_digest(self.files):
            raise ValueError("closure digest does not cover its files")
        expected = closure_id_for(
            self.run_id,
            self.unit_key,
            self.execution_generation,
            self.result_checkpoint.checkpoint_id,
            self.boundary,
        )
        if self.closure_id != expected:
            raise ValueError("closure id is not derived from its coordinate")
        if self.point_id != result_point_id(
            self.run_id, self.unit_key, self.execution_generation, self.result_checkpoint
        ):
            raise ValueError("closure point id is not the result checkpoint's point")
        return self


class WorkspaceClosureSummary(_Contract):
    """One closure of a run without its file list (`GET /runs/{run_id}/closures`)."""

    closure_id: str = Field(min_length=36, max_length=36)
    closure_ref: str = Field(min_length=1, max_length=1024)
    unit_key: str = Field(pattern=UNIT_KEY_PATTERN)
    execution_generation: int = Field(ge=1)
    point_id: str = Field(min_length=36, max_length=36)
    boundary: ClosureBoundary
    backend: ClosureBackend
    file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    promoted_bytes: int = Field(ge=0)
    complete: bool
    recorded_at: AwareDatetime
    retain_until: AwareDatetime | None = None

    @classmethod
    def of(
        cls, closure: WorkspaceClosure, *, retain_until: AwareDatetime | None = None
    ) -> WorkspaceClosureSummary:
        return cls(
            closure_id=closure.closure_id,
            closure_ref=closure.ref,
            unit_key=closure.unit_key,
            execution_generation=closure.execution_generation,
            point_id=closure.point_id,
            boundary=closure.boundary,
            backend=closure.backend,
            file_count=len(closure.files),
            total_bytes=closure.total_bytes,
            promoted_bytes=closure.promoted_bytes,
            complete=closure.complete,
            recorded_at=closure.recorded_at,
            retain_until=retain_until,
        )


class RunClosureSummary(_Contract):
    """What `run inspect` shows of a run's Workspace Closures: how many, how many are
    incomplete, and the newest (the mission end's closure)."""

    count: int = Field(ge=0)
    incomplete: int = Field(ge=0)
    promoted_bytes: int = Field(ge=0)
    latest: WorkspaceClosureSummary | None = None

    @classmethod
    def of(cls, closures: Iterable[WorkspaceClosureSummary]) -> RunClosureSummary:
        items = list(closures)
        return cls(
            count=len(items),
            incomplete=sum(1 for item in items if not item.complete),
            promoted_bytes=sum(item.promoted_bytes for item in items),
            latest=max(items, key=lambda item: item.recorded_at) if items else None,
        )


def closure_id_for(
    run_id: str,
    unit_key: str,
    execution_generation: int,
    result_checkpoint_id: str,
    boundary: str,
) -> str:
    """Deterministic closure identity: one closure per attempt result and boundary."""

    identity = (
        f"mc.workspace_closure.v1|{run_id}|{unit_key}|{execution_generation}|"
        f"{result_checkpoint_id}|{boundary}"
    )
    return str(uuid5(NAMESPACE_URL, identity))


def result_point_id(
    run_id: str, unit_key: str, execution_generation: int, key: QualifiedCheckpointKey
) -> str:
    """The point id the settlement will write for the result checkpoint (no FK: the closure is
    written in the activity before the settlement writes the point)."""

    return point_id_for(run_id, unit_key, execution_generation, "checkpoint", key.checkpoint_id)


def closure_digest(files: Iterable[ClosureFile]) -> str:
    """sha256 over the canonical sorted `[[path, digest], ...]` of the closure's files."""

    pairs = sorted([item.path, item.digest] for item in files)
    canonical = json.dumps(pairs, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _DIGEST_PREFIX + hashlib.sha256(canonical).hexdigest()


# --- References ------------------------------------------------------------------------------


class MalformedClosureRef(ValueError):
    """The string is not a well-formed `workspace-closure://` or `closure-body://` reference."""


def is_closure_ref(ref: str | None) -> bool:
    return ref is not None and ref.startswith(CLOSURE_REF_PREFIX)


def closure_ref(closure_id: str, digest: str) -> str:
    """`workspace-closure://<closure_id>#sha256:<hex>`: the result point's workspace ref."""

    return f"{CLOSURE_REF_PREFIX}{closure_id}#{_DIGEST_PREFIX}{_hex_digest(digest)}"


def parse_closure_ref(ref: str) -> tuple[str, str]:
    """(closure id, closure digest) of a `workspace-closure://` reference."""

    if not is_closure_ref(ref):
        raise MalformedClosureRef("not a workspace-closure reference")
    closure_id, separator, digest = ref.removeprefix(CLOSURE_REF_PREFIX).partition("#")
    if not separator or len(closure_id) != 36:
        raise MalformedClosureRef("workspace-closure reference needs an id and a digest")
    return closure_id, f"{_DIGEST_PREFIX}{_hex_digest(digest)}"


@dataclass(frozen=True)
class ClosureBodyRef:
    """A parsed `closure-body://` reference."""

    digest: str
    bytes: int
    media_type: str

    def render(self) -> str:
        return closure_body_ref(
            digest=self.digest, size_bytes=self.bytes, media_type=self.media_type
        )


def is_closure_body_ref(ref: str | None) -> bool:
    return ref is not None and ref.startswith(CLOSURE_BODY_PREFIX)


def closure_body_ref(*, digest: str, size_bytes: int, media_type: str) -> str:
    """`closure-body://sha256:<hex>?bytes=<n>&type=<media>` (URL-encoded type)."""

    if size_bytes < 0:
        raise MalformedClosureRef("closure body size cannot be negative")
    if not media_type:
        raise MalformedClosureRef("closure body media type is required")
    return (
        f"{CLOSURE_BODY_PREFIX}{_DIGEST_PREFIX}{_hex_digest(digest)}"
        f"?bytes={size_bytes}&type={quote(media_type, safe='')}"
    )


def parse_closure_body_ref(ref: str) -> ClosureBodyRef:
    if not is_closure_body_ref(ref):
        raise MalformedClosureRef("not a closure-body reference")
    address, separator, query = ref.removeprefix(CLOSURE_BODY_PREFIX).partition("?")
    if not separator or not address.startswith(_DIGEST_PREFIX):
        raise MalformedClosureRef("closure-body reference needs a sha256 digest and a query")
    params = dict(parse_qsl(query, keep_blank_values=True))
    size = params.get("bytes")
    media_type = params.get("type")
    if size is None or not size.isdigit():
        raise MalformedClosureRef("closure-body reference needs an integer `bytes`")
    if not media_type:
        raise MalformedClosureRef("closure-body reference needs a `type`")
    return ClosureBodyRef(
        digest=f"{_DIGEST_PREFIX}{_hex_digest(address)}",
        bytes=int(size),
        media_type=unquote(media_type),
    )


def _hex_digest(digest: str) -> str:
    value = digest.removeprefix(_DIGEST_PREFIX).lower()
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise MalformedClosureRef("closure digest is not a sha256 hex digest")
    return value


__all__ = [
    "CLOSURE_BODY_PREFIX",
    "CLOSURE_REF_PREFIX",
    "WORKSPACE_CLOSURE_SCHEMA",
    "ClosureBackend",
    "ClosureBodyRef",
    "ClosureBodyState",
    "ClosureBoundary",
    "ClosureDestination",
    "ClosureEncoding",
    "ClosureFile",
    "ClosureLimits",
    "MalformedClosureRef",
    "RunClosureSummary",
    "WorkspaceClosure",
    "WorkspaceClosureSummary",
    "closure_body_ref",
    "closure_digest",
    "closure_id_for",
    "closure_ref",
    "is_closure_body_ref",
    "is_closure_ref",
    "parse_closure_body_ref",
    "parse_closure_ref",
    "result_point_id",
]
