"""Placing a Host Projection and the Context Packet into a lane's workspace (FT-G3, C14).

Every file lane (cursor_local, cursor_cloud, claude_agent_sdk, codex) *places* what the Host
Projection renders (SPEC-07 section 5.1); the helpers they share live here rather than in one
lane's adapter. ``RenderedProjectionSource`` yields the ``HostProjection`` of a binding's exact
catalog rows for a lane profile. The packet's verified bytes are materialized under
``.mission/`` and ``inputs/``, ``.mission/operating-contract.md`` carries the operating
contract, and an empty ``outputs/`` receives declared outputs. A refused preparation raises
:class:`LaneProjectionError` with ``CAPABILITY_DRIFT`` or ``UNSUPPORTED_BEHAVIOR``.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Iterable, Sequence
from pathlib import Path, PurePosixPath
from typing import Final, Protocol

from mission_control.application.agentic_components.projections import HostProjectors
from mission_control.domain.agentic_components.layering import OPERATING_CONTRACT_PATH
from mission_control.domain.agentic_components.projection import (
    DEFAULT_KERNEL_HOOKS,
    HostProjection,
    KernelHook,
    ProjectedFile,
    ResolvedCapability,
)
from mission_control.domain.context.render import (
    CONTEXT_INDEX_PATH,
    bytes_digest,
    is_context_input_slot,
)
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    PromptSegment,
    PromptTrustClass,
)
from mission_control.domain.execution.lanes import CursorExecutionBinding
from mission_control.domain.programs.runtime_units import goal_unit_workspace_root

CAPABILITY_DRIFT: Final = "CAPABILITY_DRIFT"
UNSUPPORTED_BEHAVIOR: Final = "UNSUPPORTED_BEHAVIOR"
KERNEL_HOOK_PATH: Final = ".mission/hooks/kernel.py"
HOOK_CONTEXT_PATH: Final = ".mission/hooks/context.json"
TOKEN_PATH: Final = ".mission/bin/.token"  # noqa: S105 - a file path, not a secret
STATE_ROOT: Final = ".mission/state"
OUTPUTS_DIR: Final = "outputs"
TURN_TEXT_LIMIT: Final = 32_000
MISSION_CONTEXT_POINTER: Final = (
    "Mission context: read .mission/context.md (the context index) and .mission/inputs.json "
    "before acting; inputs are under inputs/ (read-only); write declared outputs under outputs/."
)
_INSTRUCTION_CLASSES: Final = frozenset(
    {PromptTrustClass.SYSTEM_AUTHORITY, PromptTrustClass.AUTHORED_INSTRUCTION}
)


class LaneProjectionError(ValueError):
    """Preparation refused: `code` is `CAPABILITY_DRIFT` or `UNSUPPORTED_BEHAVIOR`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class ProjectionSource(Protocol):
    async def project(
        self, operation: OperationExecutionRequest, *, profile: str, packet_index: str | None
    ) -> HostProjection: ...


class DurableInputReader(Protocol):
    async def retrieve(self, durable_ref: str) -> bytes: ...


RowsResolver = Callable[[OperationExecutionRequest], Awaitable[Sequence[ResolvedCapability]]]


def operating_contract_text(segments: Sequence[PromptSegment]) -> str:
    """The authority and authored instructions of ``segments``: the lanes' instruction
    channel. Launch authors render it from a template's segments to pin the same digest."""

    parts = [
        segment.content.strip()
        for segment in segments
        if segment.trust_class in _INSTRUCTION_CLASSES and segment.content.strip()
    ]
    # The packet index changes per turn; the pinned projection points at it on disk instead of
    # inlining it, so the rule digest stays the binding's.
    parts.append(MISSION_CONTEXT_POINTER)
    return "\n\n".join(parts)


def operating_contract(operation: OperationExecutionRequest) -> str:
    """The operation's authority and authored instructions: the lane's instruction channel."""

    return operating_contract_text(operation.prompt_segments)


def turn_text(
    operation: OperationExecutionRequest,
    *,
    limit: int = TURN_TEXT_LIMIT,
    packet_on_disk: bool = True,
) -> str:
    """The first send: the admitted inputs plus the pointer to the packet index on disk.

    Instructions travel through the lane's instruction channel, never inline secrets. A lane
    that materializes no packet files (`packet_on_disk=False`, a provider-hosted sandbox the
    packet does not reach) sends the inputs alone, with no pointer to files that are not there.
    """

    inputs = [
        segment.content.strip()
        for segment in operation.prompt_segments
        if segment.trust_class not in _INSTRUCTION_CLASSES and segment.content.strip()
    ]
    body = "\n\n".join(inputs)
    if not packet_on_disk:
        return body[:limit] + ("\n\n[truncated]" if len(body) > limit else "")
    pointer = (
        "Read .mission/context.md (the mission's context index) and "
        f"{OPERATING_CONTRACT_PATH} before acting; write declared outputs under outputs/."
    )
    if len(body) > limit:
        body = body[:limit] + "\n\n[truncated: the full inputs are listed in .mission/context.md]"
    return f"{pointer}\n\n{body}".strip()


class RenderedProjectionSource:
    """Renders the FT-A4 Host Projection of resolved rows for a lane profile."""

    def __init__(
        self,
        rows: RowsResolver,
        *,
        kernel_hooks: Sequence[KernelHook] = DEFAULT_KERNEL_HOOKS,
        projectors: HostProjectors,
    ) -> None:
        self._rows = rows
        self._kernel_hooks = tuple(kernel_hooks)
        self._projectors = projectors

    async def project(
        self, operation: OperationExecutionRequest, *, profile: str, packet_index: str | None
    ) -> HostProjection:
        rows = await self._rows(operation)
        binding = ProviderExecutionBinding.carried_by(operation)
        cursor = CursorExecutionBinding.carried_by(operation)
        telemetry = (
            binding.environment.in_environment_observation is not False
            if binding is not None
            else cursor.in_environment_observation is not False
            if cursor is not None
            else True
        )
        gates = (
            binding.environment.signal_gates
            if binding is not None
            else cursor.signal_gates
            if cursor is not None
            else None
        )
        return self._projectors.render(
            rows,
            profile,
            operating_contract(operation),
            packet_index,
            self._kernel_hooks,
            telemetry=telemetry,
            gates=gates,
        )


def static_rows(rows: Sequence[ResolvedCapability]) -> RowsResolver:
    async def resolve(_operation: OperationExecutionRequest) -> Sequence[ResolvedCapability]:
        return tuple(rows)

    return resolve


def safe_relative(path: str) -> PurePosixPath:
    normalized = PurePosixPath(path.replace("\\", "/").lstrip("/"))
    if not normalized.parts or ".." in normalized.parts:
        raise LaneProjectionError(CAPABILITY_DRIFT, f"unsafe workspace path: {path}")
    return normalized


def _write(root: Path, relative: PurePosixPath, content: bytes, mode: int) -> None:
    target = root.joinpath(*relative.parts)
    resolved_root = root.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if resolved_root not in target.parent.resolve().parents and target.parent.resolve() != (
        resolved_root
    ):
        raise LaneProjectionError(CAPABILITY_DRIFT, f"path escapes the workspace: {relative}")
    # A lease reused within a run already holds the read-only (0444) file, and an agent may
    # have planted a symlink there: replace the entry instead of writing through it.
    target.unlink(missing_ok=True)
    target.write_bytes(content)
    if os.name != "nt":
        target.chmod(mode)


def write_files(root: Path, files: Iterable[ProjectedFile]) -> tuple[str, ...]:
    written: list[str] = []
    for item in files:
        relative = safe_relative(item.path)
        _write(root, relative, item.content, item.mode)
        written.append(relative.as_posix())
    return tuple(written)


def write_secret(root: Path, path: str, value: str) -> None:
    """Write a task token readable by the workspace owner only (mode 0600 where supported)."""

    relative = safe_relative(path)
    target = root.joinpath(*relative.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(value)


async def packet_files(
    operation: OperationExecutionRequest,
    reader: DurableInputReader | None,
    *,
    mount_root: str = "",
) -> list[tuple[str, bytes]]:
    """The packet's verified read-only files (`.mission/`, `inputs/`) and the operating
    contract, as workspace-relative paths and bytes (digests checked against the slots)."""

    files: list[tuple[str, bytes]] = []
    # A GoalDirected unit's slots live under its role root (`/goal/<n>/<role>`, RRM-020); the
    # lane's lease root is that unit's workspace, so both prefixes map to the lease root.
    unit_root = (goal_unit_workspace_root(operation.runtime_unit) or "").rstrip("/")
    prefixes = tuple(prefix for prefix in (unit_root, mount_root.rstrip("/")) if prefix)
    for slot in operation.workspace.slot_bindings:
        if not is_context_input_slot(slot):
            continue
        if reader is None:
            raise LaneProjectionError(
                UNSUPPORTED_BEHAVIOR, "context inputs are bound but no durable reader is composed"
            )
        assert slot.durable_ref is not None and slot.content_digest is not None
        content = await reader.retrieve(slot.durable_ref)
        if bytes_digest(content) != slot.content_digest:
            raise LaneProjectionError(
                CAPABILITY_DRIFT, f"context input digest mismatch for {slot.logical_path}"
            )
        logical = slot.logical_path
        for prefix in prefixes:
            if logical.startswith(prefix + "/"):
                logical = logical[len(prefix) :]
                break
        files.append((safe_relative(logical).as_posix(), content))
    files.append((OPERATING_CONTRACT_PATH, operating_contract(operation).encode("utf-8")))
    return files


async def materialize_packet(
    root: Path,
    operation: OperationExecutionRequest,
    reader: DurableInputReader | None,
    *,
    mount_root: str = "",
) -> dict[str, str]:
    """Write the packet's verified read-only files (`.mission/`, `inputs/`), the operating
    contract and an empty `outputs/`; return path -> digest of what was written."""

    written: dict[str, str] = {}
    for path, content in await packet_files(operation, reader, mount_root=mount_root):
        await asyncio.to_thread(_write, root, safe_relative(path), content, 0o444)
        written[path] = bytes_digest(content)
    await asyncio.to_thread((root / OUTPUTS_DIR).mkdir, parents=True, exist_ok=True)
    return written


def read_packet_index(root: Path) -> str | None:
    target = root / CONTEXT_INDEX_PATH
    return target.read_text(encoding="utf-8") if target.is_file() else None


def hook_context_index(context: object) -> str | None:
    """`sessionStart` additional context: the lease's packet index (bounded by the caller)."""

    root = getattr(context, "workspace_root", None)
    return read_packet_index(Path(root)) if root else None


__all__ = [
    "CAPABILITY_DRIFT",
    "HOOK_CONTEXT_PATH",
    "KERNEL_HOOK_PATH",
    "MISSION_CONTEXT_POINTER",
    "OUTPUTS_DIR",
    "STATE_ROOT",
    "TOKEN_PATH",
    "TURN_TEXT_LIMIT",
    "UNSUPPORTED_BEHAVIOR",
    "DurableInputReader",
    "LaneProjectionError",
    "ProjectionSource",
    "RenderedProjectionSource",
    "RowsResolver",
    "hook_context_index",
    "materialize_packet",
    "operating_contract",
    "operating_contract_text",
    "packet_files",
    "read_packet_index",
    "safe_relative",
    "static_rows",
    "turn_text",
    "write_files",
    "write_secret",
]
