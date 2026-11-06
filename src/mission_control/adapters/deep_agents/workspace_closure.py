"""Deep Agents Workspace Closure capture (OVE-204 slice 5, `mc.workspace_closure.v1`).

At an attempt's settled boundary (`attempt_settled`, `attempt_failed`, `attempt_cancelled`),
while the materialized backend is still alive, `capture_closure` lists every file the agent
could reach and digests its raw bytes:

- the text-only `StateBackend`: the whole folded `files` channel (seeded `/inputs/**` and
  `/.mission/**`, skills, transfer files and the agent's own writes), classified by slot;
- a sandbox (Docker, LangSmith, Daytona): the exclusive writable slots and `/workspace`, listed
  and digested in the container with one `find ... sha256sum` command; bodies are downloaded
  only within the caps.

Capture degrades and never raises into the attempt: past `closure_max_files` files are omitted,
past `closure_max_bytes` promoted bytes a body is `withheld_cap`; a sensitive slot's body is
`withheld_sensitive`, a body containing a resolved secret value `withheld_secret`, a Context
Packet input `withheld_input` (its bytes are the packet's durable custody, digest only here).
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import shlex
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from deepagents.backends.protocol import BackendProtocol, SandboxBackendProtocol
from deepagents.backends.state import StateBackend
from deepagents.backends.utils import file_data_to_string

from mission_control.domain.context.render import is_context_input_slot
from mission_control.domain.execution.contracts import WorkspaceContract, WorkspaceSlotBinding
from mission_control.domain.execution.workspace_closure import (
    ClosureBackend,
    ClosureBodyState,
    ClosureBoundary,
    ClosureDestination,
    ClosureEncoding,
    ClosureFile,
    ClosureLimits,
    WorkspaceClosure,
    closure_body_ref,
    closure_digest,
    closure_id_for,
    result_point_id,
)
from mission_control.domain.graph_runtime.identities import QualifiedCheckpointKey
from mission_control.domain.resolution.profiles import WorkspaceClosureProfile

SANDBOX_WORKDIR = "/workspace"
# A secret shorter than this is not searched for (the frame redactor's floor).
MIN_SECRET_LENGTH = 6
LISTING_TIMEOUT_SECONDS = 60


class WorkspaceClosurePort(Protocol):
    """Records a Workspace Closure: bodies staged first, then header and entries at once.

    Idempotent by `closure_id`; `bodies` maps a promoted file's digest to its bytes.
    """

    async def put(
        self,
        closure: WorkspaceClosure,
        bodies: Mapping[str, bytes],
        *,
        request_scope: str,
        retain_until: datetime | None,
    ) -> None: ...


@dataclass(frozen=True)
class CapturedClosure:
    closure: WorkspaceClosure
    bodies: dict[str, bytes] = field(default_factory=dict)


@dataclass
class _Listed:
    path: str
    size: int
    digest: str
    encoding: ClosureEncoding
    destination: ClosureDestination
    content: bytes | None = None


def backend_kind(backend: BackendProtocol) -> ClosureBackend | None:
    """The closure backend of a materialized backend; None for one the closure cannot read."""

    if isinstance(backend, StateBackend):
        return "state"
    name = type(backend).__name__.lower()
    for kind in ("docker", "langsmith", "daytona"):
        if kind in name:
            return kind
    return None


def retain_until(policy: WorkspaceClosureProfile, recorded_at: datetime) -> datetime | None:
    days = policy.retention_days
    return None if days is None else recorded_at + timedelta(days=days)


async def capture_closure(
    backend: BackendProtocol,
    workspace: WorkspaceContract,
    state: Mapping[str, Any],
    *,
    run_id: str,
    unit_key: str,
    execution_generation: int,
    harness_execution_id: str | None,
    result_key: QualifiedCheckpointKey,
    boundary: ClosureBoundary,
    policy: WorkspaceClosureProfile,
    secret_values: Collection[str] = (),
    candidates: Sequence[Mapping[str, object]] = (),
    files_digest_channel: str | None = None,
    now: datetime | None = None,
) -> CapturedClosure | None:
    """The closure of the attempt's workspace, or None when the backend cannot be read."""

    kind = backend_kind(backend)
    if kind is None:
        return None
    writable = tuple(workspace.exclusive_write_paths)
    if kind == "state":
        roots: tuple[str, ...] = ("/",)
        listed = _state_files(state)
    else:
        roots = (*writable, SANDBOX_WORKDIR)
        listed = await _sandbox_files(backend, roots, writable)  # type: ignore[arg-type]
    listed.sort(key=lambda item: item.path)
    applied: list[str] = []
    omitted = max(0, len(listed) - policy.closure_max_files)
    if omitted:
        listed = listed[: policy.closure_max_files]
        applied.append("max_files")
    secrets = tuple(
        value.encode("utf-8")
        for value in secret_values
        if value and len(value) >= MIN_SECRET_LENGTH
    )
    linked = {
        (str(item.get("logical_path")), str(item.get("content_digest"))): str(item["candidate_id"])
        for item in candidates
        if item.get("candidate_id")
    }
    # Pass 1: decide which bodies to promote, within the byte cap.
    budget = policy.closure_max_bytes
    states: dict[str, ClosureBodyState] = {}
    slots: dict[str, WorkspaceSlotBinding | None] = {}
    for item in listed:
        slot = _slot_for(item.path, workspace.slot_bindings)
        slots[item.path] = slot
        if slot is not None and is_context_input_slot(slot):
            states[item.path] = "withheld_input"
        elif slot is not None and slot.sensitive:
            states[item.path] = "withheld_sensitive"
        elif item.size > budget:
            states[item.path] = "withheld_cap"
            if "max_bytes" not in applied:
                applied.append("max_bytes")
        else:
            states[item.path] = "promoted"
            budget -= item.size
    # Pass 2: a sandbox body is downloaded only now, for what will be promoted.
    if kind != "state":
        await _download(
            backend,  # type: ignore[arg-type]
            [item for item in listed if states[item.path] == "promoted"],
        )
    bodies: dict[str, bytes] = {}
    files: list[ClosureFile] = []
    for item in listed:
        state_name = states[item.path]
        content = item.content
        if state_name == "promoted":
            if content is None or _digest(content) != item.digest or len(content) != item.size:
                state_name = "unreadable"
            elif any(secret in content for secret in secrets):
                state_name = "withheld_secret"
        slot = slots[item.path]
        media_type = _media_type(item.path, item.encoding)
        body_ref = None
        if state_name == "promoted":
            assert content is not None
            bodies[item.digest] = content
            body_ref = closure_body_ref(
                digest=item.digest, size_bytes=item.size, media_type=media_type
            )
        files.append(
            ClosureFile(
                path=item.path,
                size_bytes=item.size,
                digest=item.digest,
                slot=slot.slot_name if slot is not None else None,
                slot_access=slot.access if slot is not None else None,
                destination=item.destination,
                encoding=item.encoding,
                media_type=media_type,
                body_state=state_name,
                body_ref=body_ref,
                candidate_id=linked.get((item.path, item.digest)),
            )
        )
    recorded_at = now or datetime.now(UTC)
    closure = WorkspaceClosure(
        closure_id=closure_id_for(
            run_id, unit_key, execution_generation, result_key.checkpoint_id, boundary
        ),
        run_id=run_id,
        unit_key=unit_key,
        execution_generation=execution_generation,
        harness_execution_id=harness_execution_id,
        point_id=result_point_id(run_id, unit_key, execution_generation, result_key),
        result_checkpoint=result_key,
        boundary=boundary,
        backend=kind,
        roots=roots,
        files=tuple(files),
        limits=ClosureLimits(
            max_files=policy.closure_max_files,
            max_bytes=policy.closure_max_bytes,
            applied=tuple(applied),
            omitted_files=omitted,
        ),
        files_digest_channel=files_digest_channel,
        closure_digest=closure_digest(files),
        recorded_at=recorded_at,
    )
    return CapturedClosure(closure=closure, bodies=bodies)


def _state_files(state: Mapping[str, Any]) -> list[_Listed]:
    """Every entry of the folded `files` channel with its raw bytes (a deleted entry is None)."""

    files = state.get("files")
    if not isinstance(files, Mapping):
        return []
    listed: list[_Listed] = []
    for path, data in files.items():
        if data is None or not isinstance(path, str) or not path.startswith("/"):
            continue
        content, encoding = _file_bytes(data)
        listed.append(
            _Listed(
                path=path,
                size=len(content),
                digest=_digest(content),
                encoding=encoding,
                destination="state_channel",
                content=content,
            )
        )
    return listed


def _file_bytes(data: Any) -> tuple[bytes, ClosureEncoding]:
    """Raw bytes of a `FileData` (the same bytes `StateFile.digest` covers)."""

    if not isinstance(data, Mapping):
        return str(data).encode("utf-8", errors="replace"), "utf-8"
    encoding = str(data.get("encoding", "utf-8"))
    text = file_data_to_string(dict(data))  # type: ignore[arg-type]
    if encoding == "utf-8":
        return text.encode("utf-8", errors="replace"), "utf-8"
    try:
        return base64.standard_b64decode(text), "base64"
    except ValueError:
        return text.encode("utf-8", errors="replace"), "base64"


def listing_command(roots: Sequence[str]) -> str:
    """One shell command: `<size>\\t<sha256>  <path>` per regular file under the roots."""

    quoted = " ".join(shlex.quote(root) for root in roots)
    return (
        f"find {quoted} -type f -exec sh -c "
        '\'for f do printf "%s\\t" "$(wc -c < "$f" | tr -d " ")"; sha256sum "$f"; done\' '
        "sh {} + 2>/dev/null"
    )


def parse_listing(output: str) -> list[tuple[str, int, str]]:
    """(path, size, `sha256:<hex>`) per well-formed line of `listing_command` output."""

    rows: list[tuple[str, int, str]] = []
    for line in output.splitlines():
        size, tab, rest = line.partition("\t")
        hex_digest, sep, path = rest.partition("  ")
        if not tab or not sep or not size.isdigit() or not path.startswith("/"):
            continue
        hex_digest = hex_digest.strip().lower()
        if len(hex_digest) != 64 or any(c not in "0123456789abcdef" for c in hex_digest):
            continue
        rows.append((path, int(size), "sha256:" + hex_digest))
    return rows


async def _sandbox_files(
    backend: SandboxBackendProtocol, roots: Sequence[str], writable: Sequence[str]
) -> list[_Listed]:
    command = listing_command(roots)
    response = (
        await backend.aexecute(command)
        if hasattr(backend, "aexecute")
        else backend.execute(command)
    )
    seen: dict[str, _Listed] = {}
    for path, size, digest in parse_listing(response.output or ""):
        destination: ClosureDestination = (
            "sandbox_writable"
            if any(_within(path, root) for root in writable)
            else "sandbox_workdir"
        )
        seen[path] = _Listed(
            path=path, size=size, digest=digest, encoding="binary", destination=destination
        )
    return list(seen.values())


async def _download(backend: SandboxBackendProtocol, items: Sequence[_Listed]) -> None:
    if not items:
        return
    paths = [item.path for item in items]
    downloaded = (
        await backend.adownload_files(paths)
        if hasattr(backend, "adownload_files")
        else backend.download_files(paths)
    )
    by_path = {item.path: item for item in items}
    for response in downloaded:
        target = by_path.get(response.path)
        if target is not None and response.error is None and response.content is not None:
            target.content = bytes(response.content)


def _slot_for(path: str, slots: Sequence[WorkspaceSlotBinding]) -> WorkspaceSlotBinding | None:
    matches = [slot for slot in slots if _within(path, slot.logical_path)]
    return max(matches, key=lambda slot: len(slot.logical_path)) if matches else None


def _within(path: str, root: str) -> bool:
    normalized = root.rstrip("/")
    return path == normalized or path.startswith(normalized + "/")


def _media_type(path: str, encoding: ClosureEncoding) -> str:
    guessed = mimetypes.guess_type(path)[0]
    if guessed:
        return guessed
    return "text/plain" if encoding == "utf-8" else "application/octet-stream"


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


__all__ = [
    "SANDBOX_WORKDIR",
    "CapturedClosure",
    "WorkspaceClosurePort",
    "backend_kind",
    "capture_closure",
    "listing_command",
    "parse_listing",
    "retain_until",
]
