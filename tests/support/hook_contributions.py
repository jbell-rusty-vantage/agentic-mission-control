"""In-memory doubles for WI-17 hook contributions: the install store (claims unique per path,
outcomes once per claim, crash injection) and a receiver workspace that counts writes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from mission_control.application.context.hook_contributions import (
    InstallClaim,
    InstallOutcome,
    OperationRequestReceipt,
)
from mission_control.domain.context.contributions import AttributedOperationRequest


class Crash(RuntimeError):
    """An injected process death at a chosen point."""


@dataclass
class InMemoryInstallStore:
    claims: dict[tuple[str, str, str, int, int, str], InstallClaim] = field(default_factory=dict)
    outcomes: dict[str, InstallOutcome] = field(default_factory=dict)
    crash_before_outcome: int = 0
    crash_after_outcome: int = 0

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()

    async def claim(self, scope: str, claim: InstallClaim) -> InstallClaim:
        key = (
            scope,
            claim.run_id,
            claim.operation_ref,
            claim.attempt,
            claim.generation,
            claim.path,
        )
        await asyncio.sleep(0)  # let a concurrent claimant interleave before the insert
        async with self._lock:  # the unique key: one row per receiver path
            return self.claims.setdefault(key, claim)

    async def outcome(self, scope: str, install_id: str) -> InstallOutcome | None:
        return self.outcomes.get(install_id)

    async def record_outcome(self, scope: str, outcome: InstallOutcome) -> InstallOutcome:
        if self.crash_before_outcome:
            self.crash_before_outcome -= 1
            raise Crash("died after the write, before the outcome")
        stored = self.outcomes.setdefault(outcome.install_id, outcome)
        if self.crash_after_outcome:
            self.crash_after_outcome -= 1
            raise Crash("died after the outcome, before the boundary returned")
        return stored

    async def claims_for(
        self, scope: str, run_id: str, operation_ref: str, attempt: int, generation: int
    ) -> tuple[InstallClaim, ...]:
        receiver = (scope, run_id, operation_ref, attempt, generation)
        return tuple(claim for key, claim in self.claims.items() if key[:5] == receiver)


@dataclass
class MemoryWorkspace:
    """A receiver backend: ``durable`` like a sandbox, or committed only on ``commit()`` like
    the Deep Agents state channel (``durable=False``)."""

    files: dict[str, bytes] = field(default_factory=dict)
    durable: bool = True
    writes: list[str] = field(default_factory=list)
    pending: dict[str, bytes] = field(default_factory=dict)

    @property
    def realized_backend(self) -> str:
        return "memory:sandbox" if self.durable else "memory:state"

    @property
    def read_probe(self) -> str:
        return "backend_read" if self.durable else "state_files_read"

    @property
    def durable_on_write(self) -> bool:
        return self.durable

    async def read(self, path: str) -> bytes | None:
        if path in self.pending:  # read-your-writes within the step
            return self.pending[path]
        return self.files.get(path)

    async def write(self, path: str, content: bytes) -> None:
        self.writes.append(path)
        if self.durable:
            self.files[path] = content
        else:
            self.pending[path] = content

    def commit(self) -> None:
        self.files.update(self.pending)
        self.pending.clear()

    def lose_step(self) -> None:
        """A crash before the step committed: its writes are gone."""
        self.pending.clear()


@dataclass
class RecordingOperationRequests:
    admitted: list[AttributedOperationRequest] = field(default_factory=list)

    async def propose(
        self, scope: str, request: AttributedOperationRequest
    ) -> OperationRequestReceipt:
        if all(item.request_id != request.request_id for item in self.admitted):
            self.admitted.append(request)
        return OperationRequestReceipt(
            request_id=request.request_id,
            status="admitted",
            operation_ref=f"op:{request.proposal.template}:{request.request_id[:8]}",
        )
