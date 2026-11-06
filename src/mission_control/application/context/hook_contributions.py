"""Hook context contributions: scoped host reads, staged candidates, safe-boundary installation
and operation requests (OUTPUT-CONTRACTS §11; ADR-0062; Sprint OC WI-17).

:class:`HookReadBroker` resolves a hook's declared read scopes through the receiver's actual
backend (``workspace``) or the attempt's sealed transfer plan (``transfer_input``, verified
against the plan's exact digests); a target outside the scope, under host-owned state, over its
bound or not text refuses with a typed code.

:class:`HookContributionService` stages an attributed candidate's bytes content-addressed in
custody and installs candidates at a safe boundary
(:meth:`~HookContributionService.install_context_candidates`):

1. policy (:func:`~mission_control.domain.context.contributions.install_refusal`): never host
   state, a sealed input mount, a used plan path, an output slot or a host-seeded mount, and
   only inside the hook's stage grant; per-boundary collisions and budgets refuse;
2. current authority (:class:`CurrentGrantPort`, checked now, never frozen at staging);
3. a version check: an existing file with other bytes is never overwritten;
4. a durable **claim** per (receiver, path) (:class:`CandidateInstallStore`): the first
   candidate wins a same-path race; the loser refuses ``PATH_CLAIMED``;
5. the write through the backend, a read back through it and one durable **outcome** per claim.

A backend whose writes become durable only after the step commits (the Deep Agents state
channel) leaves the claim ``pending``; the next boundary confirms it by reading it back
(:meth:`~HookContributionService.settle_pending`). The same call recovers a crash: a claim
without an outcome whose bytes are present is recorded once (``recovered``), one whose bytes are
absent is written again from custody, and a claim that already has its outcome is never written
again. An installed file is not a submission, a delivery receipt or an output-slot capture, so it
cannot fulfill an obligation. Operation requests go to :class:`OperationRequestPort` (the normal
admission path); the hook never runs model work or an external write itself.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from mission_control.application.context.materialization import ContentCustody
from mission_control.application.context.pack_service import MissionFileStagingPort
from mission_control.contracts.hooks import HookResult, HostRead
from mission_control.domain.capabilities.hooks import HookEvent
from mission_control.domain.context.contributions import (
    HOST_STATE_ROOT,
    AttributedCandidate,
    AttributedOperationRequest,
    CandidateOrigin,
    ContributionRefusal,
    HostReadScope,
    ProtectedPaths,
    StageGrant,
    attribute_candidate,
    attribute_request,
    batch_refusals,
    content_digest,
    install_refusal,
    normalize_path,
)
from mission_control.domain.context.transfer import INDEX_PATH, SealedTransferPlan

_INSTALL_NAMESPACE = uuid5(NAMESPACE_URL, "mission-control:hook-candidate-install")
MAX_READS_PER_INVOCATION = 16


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------- ports


class CandidateWorkspace(Protocol):
    """The receiver's actual backend, as the host reads and installs through it."""

    @property
    def realized_backend(self) -> str: ...

    @property
    def read_probe(self) -> str:
        """``backend_read`` (a sandbox read) or ``state_files_read`` (the files channel)."""
        ...

    @property
    def durable_on_write(self) -> bool:
        """Whether a write is durable when it returns (a sandbox), or only once the step that
        made it commits (the state channel)."""
        ...

    async def read(self, path: str) -> bytes | None: ...

    async def write(self, path: str, content: bytes) -> None: ...


class CurrentGrantPort(Protocol):
    async def check(self, origin: CandidateOrigin) -> ContributionRefusal | None:
        """The current authority of the hook invocation (stop fence, revoked grant, stale
        generation): ``None`` when it may still contribute."""
        ...


class OperationRequestReceipt(_Closed):
    request_id: str
    status: Literal["admitted", "refused"]
    code: str | None = None
    operation_ref: str | None = None


class OperationRequestPort(Protocol):
    async def propose(
        self, scope: str, request: AttributedOperationRequest
    ) -> OperationRequestReceipt:
        """Submit a separate ordinary operation through normal admission (idempotent on
        ``request.request_id``); never executes it inline."""
        ...


class InstallClaim(_Closed):
    """The durable claim of one receiver path by one attributed candidate."""

    install_id: str
    run_id: str
    operation_ref: str
    path: str
    candidate: AttributedCandidate
    custody_ref: str
    attempt: int = Field(ge=1)
    generation: int = Field(ge=1)
    boundary: str
    claimed_at: datetime


class InstallOutcome(_Closed):
    """The one installation of a claim, observed through the receiving backend."""

    install_id: str
    candidate_id: str
    digest: str
    realized_backend: str
    probe: str
    recovered: bool
    installed_at: datetime


class CandidateInstallStore(Protocol):
    async def claim(self, scope: str, claim: InstallClaim) -> InstallClaim:
        """Insert once per (run, operation, attempt, generation, path); return the stored claim,
        which may belong to another candidate (a lost same-path race)."""
        ...

    async def outcome(self, scope: str, install_id: str) -> InstallOutcome | None: ...

    async def record_outcome(self, scope: str, outcome: InstallOutcome) -> InstallOutcome:
        """Insert once per claim; a repeat returns the stored outcome."""
        ...

    async def claims_for(
        self, scope: str, run_id: str, operation_ref: str, attempt: int, generation: int
    ) -> tuple[InstallClaim, ...]:
        """The claims of one receiver attempt and generation (never an earlier attempt's)."""
        ...


# ---------------------------------------------------------------- requests and receipts


@dataclass(frozen=True)
class ContributionTarget:
    """The receiver a boundary installs into: one operation attempt's workspace in one
    execution generation. A retry attempt is another receiver: its fresh workspace is installed
    into, never told that an earlier attempt's install already happened."""

    scope: str
    run_id: str
    operation_ref: str
    attempt: int = 1
    generation: int = 1


@dataclass(frozen=True)
class StagedEntry:
    candidate: AttributedCandidate
    custody_ref: str


@dataclass(frozen=True)
class CandidateInstallation:
    """``install_context_candidates`` input: what to install where, under which grants."""

    target: ContributionTarget
    boundary: str
    candidates: tuple[StagedEntry, ...]
    grants: Mapping[str, StageGrant]
    protected: ProtectedPaths = field(default_factory=ProtectedPaths)
    # The attempt's own current-authority check (its stop fence), beside the service's.
    current: CurrentGrantPort | None = None


class InstallRecord(_Closed):
    install_id: str
    candidate_id: str
    hook_id: str
    path: str
    digest: str
    state: Literal["installed", "pending"]
    recovered: bool = False
    realized_backend: str
    probe: str


class InstallationReceipt(_Closed):
    boundary: str
    generation: int
    records: tuple[InstallRecord, ...] = ()
    refusals: tuple[ContributionRefusal, ...] = ()

    @property
    def installed(self) -> tuple[InstallRecord, ...]:
        return tuple(item for item in self.records if item.state == "installed")


# ---------------------------------------------------------------- scoped reads


def _read(
    scope: HostReadScope, target: str, *, refused: str | None = None, content: bytes | None = None
) -> HostRead:
    if refused is not None:
        return HostRead(scope=scope.name, target=target, refused=refused)
    assert content is not None
    if len(content) > scope.max_bytes:
        return HostRead(scope=scope.name, target=target, refused="READ_TOO_LARGE")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return HostRead(scope=scope.name, target=target, refused="READ_NOT_TEXT")
    return HostRead(
        scope=scope.name,
        target=target,
        digest=content_digest(content),
        size_bytes=len(content),
        content=text,
    )


class HookReadBroker:
    """Resolves declared read scopes; nothing outside them is ever read for a hook."""

    def __init__(self, *, plan: Callable[[], SealedTransferPlan | None] | None = None) -> None:
        self._plan = plan or (lambda: None)

    async def resolve(
        self, scope: HostReadScope, target: str, workspace: CandidateWorkspace | None
    ) -> HostRead:
        """One read of ``target`` under ``scope``: a workspace path or a transfer binding."""

        if scope.kind == "transfer_input":
            return await self._transfer(scope, target, workspace)
        path = normalize_path(target)
        if path is None:
            return _read(scope, target, refused="READ_OUT_OF_SCOPE")
        folded = path.casefold()
        if folded in (INDEX_PATH, HOST_STATE_ROOT) or folded.startswith(HOST_STATE_ROOT + "/"):
            return _read(scope, path, refused="READ_HOST_PRIVATE")
        if not scope.covers(path):
            return _read(scope, path, refused="READ_OUT_OF_SCOPE")
        if workspace is None:
            return _read(scope, path, refused="READ_UNAVAILABLE")
        try:
            content = await workspace.read(path)
        except (OSError, ValueError, RuntimeError):
            content = None
        if content is None:
            return _read(scope, path, refused="READ_UNAVAILABLE")
        return _read(scope, path, content=content)

    async def _transfer(
        self, scope: HostReadScope, binding: str, workspace: CandidateWorkspace | None
    ) -> HostRead:
        if binding not in scope.bindings:
            return _read(scope, binding, refused="READ_OUT_OF_SCOPE")
        plan = self._plan()
        if plan is None or workspace is None:
            return _read(scope, binding, refused="READ_UNAVAILABLE")
        placed = [
            (item, plan.member(item.member_key))
            for item in plan.placements
            if plan.member(item.member_key).binding == binding
        ]
        files = [(item, member) for item, member in placed if item.placement == "file"]
        if not files:
            return _read(scope, binding, refused="READ_NOT_FILE")
        item, member = files[0]
        assert item.path is not None
        try:
            content = await workspace.read(item.path)
        except (OSError, ValueError, RuntimeError):
            content = None
        if content is None:
            return _read(scope, item.path, refused="READ_UNAVAILABLE")
        if content_digest(content) != member.digest:
            return _read(scope, item.path, refused="READ_DIGEST_MISMATCH")
        return _read(scope, item.path, content=content)

    async def reads_for(
        self,
        event: HookEvent,
        scopes: Sequence[HostReadScope],
        workspace: CandidateWorkspace | None,
        *,
        event_paths: Sequence[str] = (),
    ) -> tuple[HostRead, ...]:
        """The reads one invocation receives: every literal path or binding a scope declares
        for this event, plus each path the event itself names (a file a tool edited), which is
        read under a covering scope or refused ``READ_OUT_OF_SCOPE``."""

        applicable = [scope for scope in scopes if scope.applies_to(event)]
        if not applicable:
            return ()
        requests: list[tuple[HostReadScope, str]] = []
        for scope in applicable:
            if scope.kind == "transfer_input":
                requests.extend((scope, binding) for binding in scope.bindings)
            else:
                requests.extend((scope, path) for path in scope.paths if "*" not in path)
        workspace_scopes = [scope for scope in applicable if scope.kind == "workspace"]
        for raw in event_paths:
            path = normalize_path(raw) or raw
            covering = next((scope for scope in workspace_scopes if scope.covers(path)), None)
            chosen = covering or (workspace_scopes[0] if workspace_scopes else None)
            if chosen is not None and (chosen, path) not in requests:
                requests.append((chosen, path))
        reads = [
            await self.resolve(scope, target, workspace)
            for scope, target in requests[:MAX_READS_PER_INVOCATION]
        ]
        return tuple(reads)


# ---------------------------------------------------------------- staging and installation


class HookContributionService:
    def __init__(
        self,
        *,
        store: CandidateInstallStore,
        staging: MissionFileStagingPort,
        custody: ContentCustody,
        grants: CurrentGrantPort | None = None,
        requests: OperationRequestPort | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._store = store
        self._staging = staging
        self._custody = custody
        self._grants = grants
        self._requests = requests
        self._clock = clock
        # Claims this instance wrote whose outcome waits for the step to commit.
        self._written: set[str] = set()

    async def stage(
        self, scope: str, candidate: AttributedCandidate, content: bytes
    ) -> StagedEntry:
        """Stage the attributed candidate's exact bytes content-addressed in custody."""

        if content_digest(content) != candidate.digest:
            raise ValueError("staged bytes differ from the attributed candidate")
        ref = await self._staging.stage(
            request_scope=scope,
            name=f"hook-candidates/{candidate.digest[7:]}",
            content=content,
            media_type=candidate.media_type,
        )
        return StagedEntry(candidate=candidate, custody_ref=ref)

    async def request_operation(
        self, scope: str, request: AttributedOperationRequest
    ) -> OperationRequestReceipt:
        if self._requests is None:
            return OperationRequestReceipt(
                request_id=request.request_id, status="refused", code="OPERATION_REQUEST_UNWIRED"
            )
        return await self._requests.propose(scope, request)

    async def install_context_candidates(
        self, request: CandidateInstallation, workspace: CandidateWorkspace
    ) -> InstallationReceipt:
        target = request.target
        candidates = [entry.candidate for entry in request.candidates]
        batch = batch_refusals(candidates, dict(request.grants))
        records: list[InstallRecord] = []
        refusals: list[ContributionRefusal] = list(batch.values())  # one per refused candidate
        seen: set[str] = set()
        for entry in request.candidates:
            candidate = entry.candidate
            if candidate.candidate_id in batch or candidate.candidate_id in seen:
                continue
            seen.add(candidate.candidate_id)
            refused = await self._authority(
                candidate, request.grants, request.protected, request.current
            )
            if refused is not None:
                refusals.append(refused)
                continue
            outcome = await self._install(target, request.boundary, entry, workspace)
            if isinstance(outcome, ContributionRefusal):
                refusals.append(outcome)
            else:
                records.append(outcome)
        return InstallationReceipt(
            boundary=request.boundary,
            generation=target.generation,
            records=tuple(records),
            refusals=tuple(refusals),
        )

    async def settle_pending(
        self,
        target: ContributionTarget,
        workspace: CandidateWorkspace,
        *,
        grants: Mapping[str, StageGrant] | None = None,
        protected: ProtectedPaths | None = None,
        current: CurrentGrantPort | None = None,
    ) -> tuple[tuple[InstallRecord, ...], tuple[ContributionRefusal, ...]]:
        """Confirm this attempt's claims that have no outcome: present bytes are recorded once;
        absent bytes are written again from custody (a crash before the write landed). Only the
        current attempt and generation are settled, and only under current authority: a fenced
        run, a revoked grant or a now-protected path settles nothing."""

        settled: list[InstallRecord] = []
        refused: list[ContributionRefusal] = []
        claims = await self._store.claims_for(
            target.scope, target.run_id, target.operation_ref, target.attempt, target.generation
        )
        for claim in claims:
            if await self._store.outcome(target.scope, claim.install_id) is not None:
                continue
            refusal = await self._authority(
                claim.candidate, grants, protected or ProtectedPaths(), current
            )
            if refusal is not None:
                refused.append(refusal)
                continue
            entry = StagedEntry(candidate=claim.candidate, custody_ref=claim.custody_ref)
            result = await self._complete(target, claim, entry, workspace)
            if isinstance(result, InstallRecord):
                settled.append(result)
            else:
                refused.append(result)
        return tuple(settled), tuple(refused)

    async def _authority(
        self,
        candidate: AttributedCandidate,
        grants: Mapping[str, StageGrant] | None,
        protected: ProtectedPaths,
        current: CurrentGrantPort | None,
    ) -> ContributionRefusal | None:
        """Policy (when the stage grants are given) and current authority, checked now."""

        refused = (
            None
            if grants is None
            else install_refusal(candidate, grants.get(candidate.origin.hook_id), protected)
        )
        for check in (current, self._grants):
            if refused is None and check is not None:
                refused = await check.check(candidate.origin)
        return refused

    async def _install(
        self,
        target: ContributionTarget,
        boundary: str,
        entry: StagedEntry,
        workspace: CandidateWorkspace,
    ) -> InstallRecord | ContributionRefusal:
        candidate = entry.candidate
        install_id = str(
            uuid5(
                _INSTALL_NAMESPACE,
                f"{target.scope}|{target.run_id}|{target.operation_ref}|{target.attempt}|"
                f"{target.generation}|{candidate.path}",
            )
        )
        current = await self._current(workspace, candidate.path)
        if current is not None and content_digest(current) != candidate.digest:
            existing = await self._store.outcome(target.scope, install_id)
            if existing is None or existing.candidate_id != candidate.candidate_id:
                return self._refusal(candidate, "VERSION_CONFLICT", "another file is at the path")
        claim = await self._store.claim(
            target.scope,
            InstallClaim(
                install_id=install_id,
                run_id=target.run_id,
                operation_ref=target.operation_ref,
                path=candidate.path,
                candidate=candidate,
                custody_ref=entry.custody_ref,
                attempt=target.attempt,
                generation=target.generation,
                boundary=boundary,
                claimed_at=self._clock(),
            ),
        )
        if claim.candidate.candidate_id != candidate.candidate_id:
            return self._refusal(
                candidate, "PATH_CLAIMED", "another candidate already claimed the path"
            )
        stored = await self._store.outcome(target.scope, install_id)
        if stored is not None:
            # Installed earlier in this attempt; say so only while the bytes are still there.
            if await self._current(workspace, candidate.path) is None:
                return self._refusal(
                    candidate, "INSTALLED_FILE_ABSENT", "the installed file is no longer present"
                )
            return self._record(claim, stored, "installed", recovered=True)
        return await self._complete(target, claim, entry, workspace)

    async def _complete(
        self,
        target: ContributionTarget,
        claim: InstallClaim,
        entry: StagedEntry,
        workspace: CandidateWorkspace,
    ) -> InstallRecord | ContributionRefusal:
        candidate = claim.candidate
        current = await self._current(workspace, candidate.path)
        if current is not None:
            if content_digest(current) != candidate.digest:
                return self._refusal(candidate, "VERSION_CONFLICT", "another file is at the path")
            # Present with the candidate's bytes: a write this instance made has committed, or
            # an earlier attempt's write survived a crash before its outcome was recorded.
            recovered = claim.install_id not in self._written
            self._written.discard(claim.install_id)
            return await self._outcome(target, claim, workspace, recovered=recovered)
        try:
            content = await self._custody.retrieve(entry.custody_ref)
        except (OSError, KeyError, ValueError):
            content = None
        if content is None or content_digest(content) != candidate.digest:
            return self._refusal(candidate, "CUSTODY_UNAVAILABLE", "staged bytes are unavailable")
        try:
            await workspace.write(candidate.path, content)
        except (OSError, ValueError, RuntimeError):
            return self._refusal(candidate, "WRITE_FAILED", "the backend refused the write")
        if not workspace.durable_on_write:
            self._written.add(claim.install_id)
            observed = await self._current(workspace, candidate.path)
            if observed is None or content_digest(observed) != candidate.digest:
                return self._refusal(
                    candidate, "READBACK_MISMATCH", "the backend did not return the bytes"
                )
            return InstallRecord(
                install_id=claim.install_id,
                candidate_id=candidate.candidate_id,
                hook_id=candidate.origin.hook_id,
                path=candidate.path,
                digest=candidate.digest,
                state="pending",
                realized_backend=workspace.realized_backend,
                probe=workspace.read_probe,
            )
        observed = await self._current(workspace, candidate.path)
        if observed is None or content_digest(observed) != candidate.digest:
            return self._refusal(
                candidate, "READBACK_MISMATCH", "the backend did not return the bytes"
            )
        return await self._outcome(target, claim, workspace, recovered=False)

    async def _outcome(
        self,
        target: ContributionTarget,
        claim: InstallClaim,
        workspace: CandidateWorkspace,
        *,
        recovered: bool,
    ) -> InstallRecord:
        stored = await self._store.record_outcome(
            target.scope,
            InstallOutcome(
                install_id=claim.install_id,
                candidate_id=claim.candidate.candidate_id,
                digest=claim.candidate.digest,
                realized_backend=workspace.realized_backend,
                probe=workspace.read_probe,
                recovered=recovered,
                installed_at=self._clock(),
            ),
        )
        return self._record(claim, stored, "installed", recovered=stored.recovered)

    @staticmethod
    def _record(
        claim: InstallClaim,
        outcome: InstallOutcome,
        state: Literal["installed", "pending"],
        *,
        recovered: bool,
    ) -> InstallRecord:
        return InstallRecord(
            install_id=claim.install_id,
            candidate_id=claim.candidate.candidate_id,
            hook_id=claim.candidate.origin.hook_id,
            path=claim.path,
            digest=claim.candidate.digest,
            state=state,
            recovered=recovered,
            realized_backend=outcome.realized_backend,
            probe=outcome.probe,
        )

    @staticmethod
    async def _current(workspace: CandidateWorkspace, path: str) -> bytes | None:
        try:
            return await workspace.read(path)
        except (OSError, ValueError, RuntimeError):
            return None

    @staticmethod
    def _refusal(candidate: AttributedCandidate, code: str, message: str) -> ContributionRefusal:
        return ContributionRefusal(
            code=code, hook_id=candidate.origin.hook_id, path=candidate.path, message=message
        )


# ---------------------------------------------------------------- one attempt's session


@dataclass(frozen=True)
class HookGrants:
    """One hook's admitted read scopes and stage grant (pinned in the execution binding)."""

    reads: tuple[HostReadScope, ...] = ()
    stage: StageGrant | None = None


class ContributionSession:
    """The contributions of one operation attempt: reads served at dispatch, candidates and
    requests collected per invocation, installation at each safe boundary (serialized)."""

    def __init__(
        self,
        *,
        service: HookContributionService,
        target: ContributionTarget,
        grants: Mapping[str, HookGrants],
        protected: ProtectedPaths | None = None,
        broker: HookReadBroker | None = None,
        current: CurrentGrantPort | None = None,
    ) -> None:
        self.service = service
        self.target = target
        self.grants = dict(grants)
        self.protected = protected or ProtectedPaths()
        self.broker = broker or HookReadBroker()
        self.current = current
        self.staged: list[StagedEntry] = []
        self.refusals: list[ContributionRefusal] = []
        self.receipts: list[InstallationReceipt] = []
        self.requests: list[OperationRequestReceipt] = []
        self._lock = asyncio.Lock()

    def reads_declared(self, hook_id: str) -> tuple[HostReadScope, ...]:
        grant = self.grants.get(hook_id)
        return () if grant is None else grant.reads

    async def reads(
        self,
        hook_id: str,
        event: HookEvent,
        workspace: CandidateWorkspace | None,
        *,
        event_paths: Sequence[str] = (),
    ) -> tuple[HostRead, ...]:
        scopes = self.reads_declared(hook_id)
        if not scopes:
            return ()
        return await self.broker.reads_for(event, scopes, workspace, event_paths=event_paths)

    async def collect(self, origin: CandidateOrigin, result: HookResult) -> CollectOutcome:
        """Attribute and stage what one invocation proposed; nothing is applied here. The
        outcome (staged, refused, requested) is returned for the lane to make visible."""

        grant = self.grants.get(origin.hook_id)
        stage = None if grant is None else grant.stage
        staged: list[StagedEntry] = []
        refusals: list[ContributionRefusal] = []
        requests: list[OperationRequestReceipt] = []
        for candidate in result.staged_candidates:
            attributed = attribute_candidate(origin, candidate)
            if isinstance(attributed, ContributionRefusal):
                refusals.append(attributed)
                continue
            if stage is None:
                refusals.append(
                    ContributionRefusal(
                        code="PATH_OUT_OF_GRANT",
                        hook_id=origin.hook_id,
                        path=attributed.path,
                        message="the hook declares no stage grant",
                    )
                )
                continue
            staged.append(await self.service.stage(self.target.scope, attributed, candidate.body))
        for proposal in result.operation_requests:
            request = attribute_request(origin, proposal, stage)
            if isinstance(request, ContributionRefusal):
                refusals.append(request)
                continue
            requests.append(await self.service.request_operation(self.target.scope, request))
        self.staged.extend(staged)
        self.refusals.extend(refusals)
        self.requests.extend(requests)
        return CollectOutcome(
            origin=origin, staged=tuple(staged), refusals=tuple(refusals), requests=tuple(requests)
        )

    def _stage_grants(self) -> dict[str, StageGrant]:
        return {hook: grant.stage for hook, grant in self.grants.items() if grant.stage is not None}

    async def boundary(self, workspace: CandidateWorkspace, name: str) -> InstallationReceipt:
        """A safe boundary (no tool in flight): confirm this attempt's pending/crashed claims
        under current authority, then install the staged candidates; the staging list is
        consumed either way."""

        async with self._lock:
            settled, unsettled = await self.service.settle_pending(
                self.target,
                workspace,
                grants=self._stage_grants(),
                protected=self.protected,
                current=self.current,
            )
            staged, self.staged = self.staged, []
            receipt = await self.service.install_context_candidates(
                CandidateInstallation(
                    target=self.target,
                    boundary=name,
                    candidates=tuple(staged),
                    grants=self._stage_grants(),
                    protected=self.protected,
                    current=self.current,
                ),
                workspace,
            )
            if settled or unsettled:
                # A re-staged candidate whose claim was just settled is one installation.
                records = {item.install_id: item for item in (*receipt.records, *settled)}
                receipt = receipt.model_copy(
                    update={
                        "records": tuple(records.values()),
                        "refusals": (*unsettled, *receipt.refusals),
                    }
                )
            if receipt.records or receipt.refusals:
                self.receipts.append(receipt)
            return receipt

    def close(self) -> tuple[ContributionRefusal, ...]:
        """The attempt has no later boundary (its final answer): every still-staged candidate
        is refused ``CANDIDATE_NOT_INSTALLED``, visibly, instead of being silently dropped."""

        leftovers, self.staged = self.staged, []
        refusals = tuple(
            ContributionRefusal(
                code="CANDIDATE_NOT_INSTALLED",
                hook_id=entry.candidate.origin.hook_id,
                path=entry.candidate.path,
                message="the attempt ended before a safe boundary could install the candidate",
            )
            for entry in leftovers
        )
        self.refusals.extend(refusals)
        return refusals


@dataclass(frozen=True)
class CollectOutcome:
    """What one hook invocation's contributions became: staged, refused or requested."""

    origin: CandidateOrigin
    staged: tuple[StagedEntry, ...] = ()
    refusals: tuple[ContributionRefusal, ...] = ()
    requests: tuple[OperationRequestReceipt, ...] = ()


__all__ = [
    "CandidateInstallStore",
    "CandidateInstallation",
    "CandidateWorkspace",
    "CollectOutcome",
    "ContributionSession",
    "ContributionTarget",
    "CurrentGrantPort",
    "HookContributionService",
    "HookGrants",
    "HookReadBroker",
    "InstallClaim",
    "InstallOutcome",
    "InstallRecord",
    "InstallationReceipt",
    "OperationRequestPort",
    "OperationRequestReceipt",
    "StagedEntry",
]
