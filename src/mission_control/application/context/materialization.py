"""The one transfer materializer: selection -> sealed plan -> prompt/index/files/handles ->
attempt readiness (OUTPUT-CONTRACTS §6; ADR-0061; Sprint OC WI-02).

:meth:`TransferMaterializer.materialize` is the single host entry point. For a receiver it

1. returns the plan already sealed for that receiver boundary (a retry, restart or redelivery
   never resolves today's revision again), or resolves each admitted named binding through its
   source resolver (``produced_output``, ``exact_artifact``, ``typed_literal``,
   ``application_selector``) into exact members, stages their exact bytes content-addressed in
   custody and seals one immutable plan (:func:`~mission_control.domain.context.transfer.
   seal_plan`), persisted in the one plan table;
2. realizes the plan for this attempt on the actual receiving backend: reads every member back
   from custody by digest, writes files read-only under ``/inputs/<binding>/...`` and the index
   at ``/.mission/transfer.json``, reads each file back *through that backend*, re-checks
   current access, and measures the invocation's real overhead;
3. appends one attempt receipt (receiver attempt, generation and realized backend in its
   identity) and returns the rendered prompt section and files only when ready; otherwise it
   raises :class:`ContextDeliveryBlocked` after recording the refused receipt.

Required content, access, use, form or resource failure refuses; nothing falls back silently.
Receipts prove delivery and readability, never that the model read or understood the content.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from mission_control.application.context.pack_service import (
    ArtifactBytesPort,
    MissionFileStagingPort,
)
from mission_control.application.context.resolution import (
    ContentResolutionService,
    ResolutionRefused,
)
from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.outputs.submission_service import SelectedItem
from mission_control.application.ports.knowledge import ContentLineageStore, LineageEntry
from mission_control.application.ports.outputs import OutputContractStore
from mission_control.domain.authoring.canonical import canonical_json
from mission_control.domain.context.packet import ConservativeTokenCounter, TokenCounter
from mission_control.domain.context.transfer import (
    INDEX_PATH,
    Boundary,
    DeliveryReceipt,
    ExactMember,
    HostOverhead,
    MemberDelivery,
    Omission,
    ReceiverAttempt,
    ReceiverRef,
    ResourceUsage,
    SealedTransferPlan,
    TransferInput,
    TransferRefusal,
    TransferSelection,
    readiness,
    render_index,
    render_inline_section,
    seal_plan,
)
from mission_control.domain.knowledge.judgment import head_demoted
from mission_control.domain.knowledge.lineage import ActorKind, LineageFact, ProvenanceRole
from mission_control.domain.outputs.collections import blocked_by_members
from mission_control.domain.outputs.contracts import (
    ExactOutput,
    OutputForm,
    collection_document,
)

_PLAN_NAMESPACE = uuid5(NAMESPACE_URL, "mission-control:sealed-transfer-plan")
MC_ISSUER = "mission-control"
_ACTOR = "mission-control:context-transfer"
# A KS report member's access ref: `<exact handle>#digest=<report revision digest>`.
_DIGEST_SEPARATOR = "#digest="


def _plain_json(value: Any) -> bytes:
    """Sorted, compact UTF-8 JSON: the exact bytes of a host-rendered document."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


class ContextDeliveryBlocked(RuntimeError):
    """A receiver's required inputs are not ready: the invocation does not start.

    ``reason`` is host-generated (typed codes and exact member keys), never provider text, so
    the operation settles ``failed`` with code ``context_delivery_blocked`` and this reason.
    """

    code = "context_delivery_blocked"

    def __init__(self, reason: str, *, refusals: Sequence[TransferRefusal] = ()) -> None:
        super().__init__(f"context_delivery_blocked: {reason}")
        self.reason = reason
        self.refusals = tuple(refusals)


class SourceRefused(RuntimeError):
    def __init__(self, refusal: TransferRefusal) -> None:
        super().__init__(f"{refusal.code}: {refusal.message}")
        self.refusal = refusal


def refuse(code: str, binding: TransferInput, message: str, *, waiting: bool = False) -> None:
    raise SourceRefused(
        TransferRefusal(code=code, binding=binding.name, message=message, waiting=waiting)
    )


# ---------------------------------------------------------------- ports


@dataclass(frozen=True)
class ResolvedContent:
    """One exact member as a resolver found it, with its exact bytes (``None``: handle only)."""

    member: ExactMember
    content: bytes | None


@dataclass(frozen=True)
class ResolutionContext:
    scope: str
    run_id: str
    receiver_position: str
    access: InvocationAccess | None = None
    boundary: Boundary = Boundary.FIRST_INVOCATION
    isolation: str = "shared"
    receiver_operation_id: str | None = None


# OVE-169: re-resolve one accepted head's exact KS decision before a consumer uses it.
HeadRecheck = Callable[[InvocationAccess, ExactOutput], Awaitable[None]]


class SourceResolver(Protocol):
    async def resolve(
        self, binding: TransferInput, context: ResolutionContext
    ) -> Sequence[ResolvedContent]:
        """Exact members of one binding or :class:`SourceRefused`; never a guess."""
        ...


class ContentCustody(Protocol):
    async def retrieve(self, durable_ref: str) -> bytes: ...


@dataclass(frozen=True)
class AccessCheck:
    ok: bool
    ref: str
    code: str | None = None


class CurrentAccessPort(Protocol):
    async def check(self, member: ExactMember, context: ResolutionContext) -> AccessCheck:
        """Current access/use of ``member`` for this attempt (a plan never freezes it)."""
        ...


class ReceiverBackend(Protocol):
    """The actual receiving backend of one attempt (the lane adapts its own backend)."""

    @property
    def realized_backend(self) -> str: ...

    # Optional: `state_files_read` for a text-only files channel (default `backend_read`).

    async def write(self, files: Sequence[tuple[str, bytes]]) -> None: ...

    async def read(self, path: str) -> bytes | None:
        """Read through the backend the receiver uses; ``None`` when it cannot."""
        ...


class TransferPlanConflict(RuntimeError):
    """Another plan with other content is already sealed for this receiver boundary."""


class TransferPlanStore(Protocol):
    async def seal(self, plan: SealedTransferPlan) -> SealedTransferPlan:
        """Insert once per receiver key; the same digest returns the stored plan, another
        digest raises :class:`TransferPlanConflict`."""
        ...

    async def plan_for(self, scope: str, receiver_key: str) -> SealedTransferPlan | None: ...

    async def get(self, scope: str, plan_id: str) -> SealedTransferPlan | None: ...

    async def append_receipt(self, scope: str, receipt: DeliveryReceipt) -> DeliveryReceipt:
        """Append (never rewrite); the store assigns the next ``sequence``."""
        ...

    async def receipts(self, scope: str, plan_id: str) -> tuple[DeliveryReceipt, ...]: ...

    async def file_realizations(self, scope: str, source_refs: Sequence[str]) -> Mapping[str, str]:
        """``source_ref -> receipt ref`` for exact file members a receiving backend read back
        with the required digest (file-form fulfillment evidence)."""
        ...


# ---------------------------------------------------------------- the request and result


@dataclass(frozen=True)
class MaterializeRequest:
    """``MaterializeRequest@1``: who receives what, under which bounds, on which backend."""

    receiver: ReceiverRef
    attempt: ReceiverAttempt
    selection: TransferSelection
    configuration_ref: str
    host_state_ref: str | None
    overhead: HostOverhead
    retrieval_tools: tuple[str, ...] = ()
    access: InvocationAccess | None = None
    correlation_id: str | None = None
    reserved_paths: frozenset[str] = frozenset()


@dataclass(frozen=True)
class MaterializedTransfer:
    """``MaterializeResult``: the plan, the attempt receipt and what the lane presents."""

    plan: SealedTransferPlan
    receipt: DeliveryReceipt
    prompt_section: str | None
    files: tuple[tuple[str, bytes], ...]
    index: dict[str, Any] = field(default_factory=dict)

    @property
    def handles(self) -> tuple[str, ...]:
        return tuple(
            handle for _item, member in self.plan.placed("handle") for handle in member.handles
        )


class _NoAccessCheck:
    async def check(self, member: ExactMember, context: ResolutionContext) -> AccessCheck:
        return AccessCheck(ok=True, ref=f"mc-scope:{context.scope}")


class TransferMaterializer:
    def __init__(
        self,
        *,
        store: TransferPlanStore,
        staging: MissionFileStagingPort,
        custody: ContentCustody,
        resolvers: Mapping[str, SourceResolver],
        access: Mapping[str, CurrentAccessPort] | None = None,
        counter: TokenCounter | None = None,
        uuid_factory: Callable[[str], str] | None = None,
        lineage: ContentLineageStore | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._lineage = lineage
        self._clock = clock
        self._store = store
        self._staging = staging
        self._custody = custody
        self._resolvers = dict(resolvers)
        self._access = dict(access or {})
        self._counter = counter or ConservativeTokenCounter()
        self._ids = uuid_factory or (lambda basis: str(uuid5(_PLAN_NAMESPACE, basis)))

    # -- sealing ---------------------------------------------------------------------

    async def seal(self, request: MaterializeRequest) -> SealedTransferPlan:
        """The receiver's sealed plan: the stored one when it exists, else resolve and seal."""

        selection = request.selection
        scope = request.receiver.scope
        key = request.receiver.key(selection.boundary)
        stored = await self._store.plan_for(scope, key)
        if stored is not None:
            if stored.selection_authority_ref != selection.digest:
                raise ContextDeliveryBlocked(
                    f"PLAN_CONFLICT:{stored.plan_id}",
                    refusals=(
                        TransferRefusal(
                            code="PLAN_CONFLICT",
                            message="the receiver's sealed plan pins another selection",
                        ),
                    ),
                )
            return stored
        context = ResolutionContext(
            scope=scope,
            run_id=request.receiver.run_id,
            receiver_position=selection.receiver_position,
            access=request.access,
            boundary=selection.boundary,
            isolation=selection.isolation,
            receiver_operation_id=request.receiver.operation_id,
        )
        members: list[ExactMember] = []
        texts: dict[str, str] = {}
        omissions: list[Omission] = []
        for binding in selection.inputs:
            resolver = self._resolvers.get(binding.source.kind)
            try:
                if resolver is None:
                    refuse(
                        "SOURCE_KIND_UNWIRED",
                        binding,
                        f"no resolver is composed for {binding.source.kind} sources",
                    )
                    raise AssertionError  # pragma: no cover - refuse always raises
                resolved = await resolver.resolve(binding, context)
            except SourceRefused as refused:
                if binding.required:
                    raise ContextDeliveryBlocked(
                        f"{refused.refusal.code}:{binding.name}", refusals=(refused.refusal,)
                    ) from None
                omissions.append(
                    Omission(
                        binding=binding.name,
                        code=refused.refusal.code,
                        reason=refused.refusal.message,
                    )
                )
                continue
            for item in resolved:
                member = item.member
                if item.content is not None:
                    if _digest(item.content) != member.digest or len(item.content) != (
                        member.size_bytes
                    ):
                        raise ContextDeliveryBlocked(
                            f"DIGEST_MISMATCH:{member.member_key}",
                            refusals=(
                                TransferRefusal(
                                    code="DIGEST_MISMATCH",
                                    member_key=member.member_key,
                                    message="resolved bytes differ from their exact identity",
                                ),
                            ),
                        )
                    custody_ref = await self._staging.stage(
                        request_scope=scope,
                        name=f"transfer/{member.digest[7:]}",
                        content=item.content,
                        media_type=member.media_type,
                    )
                    member = member.model_copy(update={"custody_ref": custody_ref})
                    if member.textual:
                        try:
                            texts[member.member_key] = item.content.decode("utf-8")
                        except UnicodeDecodeError:
                            raise ContextDeliveryBlocked(
                                f"ENCODING_INVALID:{member.member_key}"
                            ) from None
                members.append(member)
        sealed = seal_plan(
            plan_id=self._ids(f"{scope}/{key}/{selection.digest}"),
            receiver=request.receiver,
            selection=selection,
            configuration_ref=request.configuration_ref,
            host_state_ref=request.host_state_ref,
            members=members,
            unresolved_optional=omissions,
            overhead=request.overhead,
            retrieval_tools=request.retrieval_tools,
            inline_texts=texts,
            counter=self._counter,
        )
        if isinstance(sealed, TransferRefusal):
            raise ContextDeliveryBlocked(
                f"{sealed.code}:{sealed.member_key or sealed.binding or 'plan'}",
                refusals=(sealed,),
            )
        collisions = {item.path for item in sealed.placements if item.path} & set(
            request.reserved_paths
        )
        if collisions:
            raise ContextDeliveryBlocked(f"PATH_COLLISION:{sorted(collisions)[0]}")
        try:
            return await self._store.seal(sealed)
        except TransferPlanConflict:
            # A concurrent first attempt sealed first: the stored plan is the authority.
            stored = await self._store.plan_for(scope, key)
            if stored is None or stored.selection_authority_ref != selection.digest:
                raise ContextDeliveryBlocked(f"PLAN_CONFLICT:{key}") from None
            return stored

    # -- delivery ----------------------------------------------------------------------

    async def deliver(
        self,
        plan: SealedTransferPlan,
        request: MaterializeRequest,
        backend: ReceiverBackend,
    ) -> MaterializedTransfer:
        """Realize ``plan`` for this attempt on ``backend`` and append its receipt."""

        scope = plan.receiver.scope
        context = ResolutionContext(
            scope=scope,
            run_id=plan.receiver.run_id,
            receiver_position=plan.receiver_position,
            access=request.access,
            boundary=plan.boundary,
            isolation=plan.isolation,
            receiver_operation_id=plan.receiver.operation_id,
        )
        texts: dict[str, str] = {}
        files: list[tuple[str, bytes]] = []
        deliveries: list[MemberDelivery] = []
        checks: dict[str, AccessCheck] = {}
        contents: dict[str, bytes] = {}
        for placed in plan.placements:
            member = plan.member(placed.member_key)
            checker = self._access.get(member.source_kind, _NoAccessCheck())
            check = await checker.check(member, context)
            checks[member.member_key] = check
            if placed.placement == "handle":
                capable = bool(set(plan.retrieval_tools) & set(request.retrieval_tools))
                deliveries.append(
                    MemberDelivery(
                        member_key=member.member_key,
                        placement="handle",
                        path_or_handle=",".join(member.handles),
                        required_digest=member.digest,
                        probe="retrieval_capability",
                        readable=capable,
                        access_ref=check.ref,
                        access_ok=check.ok,
                        code=None if capable else "NO_RETRIEVAL_CAPABILITY",
                    )
                )
                continue
            assert member.custody_ref is not None
            try:
                content = await self._custody.retrieve(member.custody_ref)
            except (OSError, KeyError, ValueError):
                content = None
            if content is None or _digest(content) != member.digest:
                deliveries.append(
                    MemberDelivery(
                        member_key=member.member_key,
                        placement=placed.placement,
                        path_or_handle=placed.path or "prompt",
                        required_digest=member.digest,
                        observed_digest=None if content is None else _digest(content),
                        probe="prompt" if placed.placement == "inline" else "backend_read",
                        readable=False,
                        access_ref=check.ref,
                        access_ok=check.ok,
                        code="CUSTODY_UNAVAILABLE" if content is None else "DIGEST_MISMATCH",
                    )
                )
                continue
            contents[member.member_key] = content
            if placed.placement == "inline":
                texts[member.member_key] = content.decode("utf-8")
                deliveries.append(
                    MemberDelivery(
                        member_key=member.member_key,
                        placement="inline",
                        path_or_handle="prompt",
                        required_digest=member.digest,
                        observed_digest=_digest(content),
                        size_bytes=len(content),
                        probe="prompt",
                        readable=True,
                        access_ref=check.ref,
                        access_ok=check.ok,
                        code=None if check.ok else check.code,
                    )
                )
            else:
                assert placed.path is not None
                files.append((placed.path, content))
        index = render_index(plan)
        index_bytes = _plain_json(index) + b"\n"
        files.append((INDEX_PATH, index_bytes))
        # A failed write leaves every file unreadable below: fail closed, never assume.
        with contextlib.suppress(OSError, ValueError, RuntimeError):
            await backend.write(files)
        for placed in plan.placements:
            if placed.placement != "file" or placed.member_key not in contents:
                continue
            member = plan.member(placed.member_key)
            assert placed.path is not None
            try:
                observed = await backend.read(placed.path)
            except (OSError, ValueError, RuntimeError):
                observed = None
            check = checks[member.member_key]
            deliveries.append(
                MemberDelivery(
                    member_key=member.member_key,
                    placement="file",
                    path_or_handle=placed.path,
                    required_digest=member.digest,
                    observed_digest=None if observed is None else _digest(observed),
                    size_bytes=None if observed is None else len(observed),
                    probe=getattr(backend, "read_probe", "backend_read"),
                    readable=observed is not None,
                    access_ref=check.ref,
                    access_ok=check.ok,
                    code=check.code
                    if not check.ok
                    else (None if observed is not None else "BACKEND_UNREADABLE"),
                )
            )
        complete = len(texts) == len(plan.placed("inline"))
        # Omissions are always visible, even when nothing was placed.
        section = (
            render_inline_section(plan, texts)
            if complete and (plan.placements or plan.omissions)
            else None
        )
        usage = _usage(plan, request.overhead, section, self._counter)
        result, findings = readiness(plan, deliveries, usage)
        receipt = await self._store.append_receipt(
            scope,
            DeliveryReceipt(
                receipt_id=str(uuid4()),
                plan_id=plan.plan_id,
                plan_digest=plan.digest,
                receiver_attempt=request.attempt,
                realized_backend=backend.realized_backend,
                sequence=1,
                delivered=tuple(deliveries),
                current_access_refs=tuple(dict.fromkeys(item.ref for item in checks.values())),
                resource_usage=usage,
                result=result,
                findings=findings,
                correlation_id=request.correlation_id or request.attempt.invocation_ref,
            ),
        )
        if result != "ready":
            first = findings[0]
            raise ContextDeliveryBlocked(
                f"{first.code}:{first.member_key or 'plan'}", refusals=findings
            )
        await self._record_consumption(plan, receipt, request)
        return MaterializedTransfer(
            plan=plan,
            receipt=receipt,
            prompt_section=section,
            files=tuple(files),
            index=index,
        )

    async def _record_consumption(
        self, plan: SealedTransferPlan, receipt: DeliveryReceipt, request: MaterializeRequest
    ) -> None:
        """Ready and readable: the receiving attempt is the consumer of each exact KS revision
        (SP-10). Recorded only for a ready receipt; never a producer or adoption fact."""

        access = request.access
        if self._lineage is None or access is None:
            return
        entries = [
            LineageEntry(
                fact=LineageFact(
                    subject_handle=member.access_ref.partition(_DIGEST_SEPARATOR)[0],
                    role=ProvenanceRole.CONSUMER,
                    actor_kind=ActorKind.ORIGIN,
                    actor_ref=access.invocation_ref,
                    actor_origin=access.origin,
                    fact={"transfer_plan": plan.ref, "delivery_receipt": receipt.receipt_id},
                ),
                subject_kind="report",
                subject_digest=member.access_ref.partition(_DIGEST_SEPARATOR)[2] or None,
                run_id=plan.receiver.run_id,
            )
            for member in {
                item.access_ref: item for item in plan.exact_sources if item.issuer != MC_ISSUER
            }.values()
        ]
        if entries:
            await self._lineage.record(
                plan.receiver.scope, entries, actor_ref=_ACTOR, at=self._clock()
            )

    async def materialize(
        self, request: MaterializeRequest, backend: ReceiverBackend
    ) -> MaterializedTransfer:
        """The single entry point: seal (or reuse) the receiver's plan, then deliver it."""

        plan = await self.seal(request)
        return await self.deliver(plan, request, backend)

    async def file_realizations(
        self, scope: str, revisions: Sequence[ExactOutput]
    ) -> Mapping[str, str]:
        return await self._store.file_realizations(
            scope, [revision.revision_id for revision in revisions]
        )


def _usage(
    plan: SealedTransferPlan,
    overhead: HostOverhead,
    section: str | None,
    counter: TokenCounter,
) -> ResourceUsage:
    """The attempt's measured total: the sealed plan's file/reserve accounting with the
    attempt's own measured host/tool/skill overhead and the actually rendered section."""

    resources = plan.resource_plan
    rendered = counter.count(section) if section else 0
    total = (
        overhead.host_state_tokens
        + overhead.tool_schema_tokens
        + overhead.skill_tokens
        + resources.index_tokens
        + max(rendered, resources.inline_tokens)
        + resources.file_read_tokens
        + resources.bounds.generation_reserve_tokens
        + resources.bounds.tool_result_reserve_tokens
    )
    return ResourceUsage(
        overhead=overhead,
        total_tokens=total,
        headroom_tokens=resources.bounds.window_tokens - total,
    )


# ---------------------------------------------------------------- source resolvers


def _file_name(stem: str, media_type: str) -> str:
    extension = {
        "text/markdown": ".md",
        "application/json": ".json",
        "text/plain": ".txt",
    }.get(media_type, ".bin")
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in stem)[:96] or "value"
    return safe if "." in safe[1:] else safe + extension


class LiteralResolver:
    """``typed_literal(schema_pin, value)``: exact canonical bytes; the pin is its identity."""

    async def resolve(
        self, binding: TransferInput, context: ResolutionContext
    ) -> Sequence[ResolvedContent]:
        source = binding.source
        assert source.schema_pin is not None
        if isinstance(source.value, str) and source.schema_pin.startswith("text/"):
            content, media = source.value.encode("utf-8"), source.schema_pin.split("@", 1)[0]
        else:
            content, media = _plain_json(source.value), "application/json"
        digest = _digest(content)
        return (
            ResolvedContent(
                ExactMember(
                    member_key=f"{binding.name}/value",
                    binding=binding.name,
                    part="value",
                    source_kind="typed_literal",
                    source_ref=f"literal:{source.schema_pin}",
                    revision=digest[7:23],
                    issuer=MC_ISSUER,
                    digest=digest,
                    size_bytes=len(content),
                    media_type=media,
                    file_name=_file_name(binding.name, media),
                    purpose=binding.purpose,
                    required=binding.required,
                    access_ref=f"mc-scope:{context.scope}",
                ),
                content,
            ),
        )


class DurableReader(Protocol):
    async def retrieve(self, durable_ref: str) -> bytes: ...


class ArtifactResolver:
    """``exact_artifact(ArtifactRef)``: the scoped artifact whose bytes match the pinned digest."""

    def __init__(self, artifacts: ArtifactBytesPort, reader: DurableReader) -> None:
        self._artifacts = artifacts
        self._reader = reader

    async def resolve(
        self, binding: TransferInput, context: ResolutionContext
    ) -> Sequence[ResolvedContent]:
        source = binding.source
        assert source.artifact_ref is not None and source.digest is not None
        return (await self.exact(binding, context, source.artifact_ref, source.digest, "artifact"),)

    async def exact(
        self,
        binding: TransferInput,
        context: ResolutionContext,
        ref: str,
        digest: str,
        part: str,
        *,
        source_kind: str = "exact_artifact",
        revision: str | None = None,
    ) -> ResolvedContent:
        captured = await self._artifacts.capture(ref, request_scope=context.scope, max_text_bytes=0)
        if captured is None:
            refuse("SOURCE_UNRESOLVED", binding, f"{ref} does not resolve in this scope")
            raise AssertionError  # pragma: no cover
        if captured.content_digest != digest:
            refuse("DIGEST_MISMATCH", binding, f"{ref} is not the pinned revision {digest}")
        try:
            content = await self._reader.retrieve(captured.durable_ref)
        except (OSError, KeyError, ValueError):
            refuse("CUSTODY_UNAVAILABLE", binding, f"{ref} bytes are not retrievable")
            raise AssertionError from None  # pragma: no cover
        if _digest(content) != digest:
            refuse("DIGEST_MISMATCH", binding, f"{ref} custody bytes differ from {digest}")
        return ResolvedContent(
            ExactMember.model_validate(
                {
                    "member_key": f"{binding.name}/{part}",
                    "binding": binding.name,
                    "part": part,
                    "source_kind": source_kind,
                    "source_ref": ref,
                    "revision": revision or digest[7:23],
                    "issuer": MC_ISSUER,
                    "digest": digest,
                    "size_bytes": len(content),
                    "media_type": captured.media_type,
                    "file_name": _file_name(
                        captured.file_name or ref.rsplit("/", 1)[-1], captured.media_type
                    ),
                    "purpose": binding.purpose,
                    "required": binding.required,
                    "access_ref": ref,
                }
            ),
            content,
        )


class ProducedOutputResolver:
    """``produced_output(position, output_key)``: the exact accepted revision(s) of the
    producer's named promise; a report handle is read exactly from KS with purpose."""

    def __init__(
        self,
        contracts: OutputContractStore,
        *,
        reports: ContentResolutionService | None = None,
        artifacts: ArtifactResolver | None = None,
        recheck: HeadRecheck | None = None,
    ) -> None:
        self._contracts = contracts
        self._reports = reports
        self._artifacts = artifacts
        self._recheck = recheck

    async def resolve(
        self, binding: TransferInput, context: ResolutionContext
    ) -> Sequence[ResolvedContent]:
        source = binding.source
        obligations = await self._contracts.active_obligations(context.scope, context.run_id)
        promise = next(
            (
                item
                for item in obligations
                if item.key == source.output_key and item.owner_position == source.position
            ),
            None,
        )
        if promise is None:
            refuse(
                "SOURCE_UNRESOLVED",
                binding,
                f"{source.position} promises no output {source.output_key} in this run",
            )
        assert promise is not None
        accepted = [
            item
            for item in await self._contracts.accepted_outputs(context.scope, context.run_id)
            if item.obligation_key == source.output_key
        ]
        demoted: list[str] = []
        if accepted:
            accepted, demoted = await self._current_heads(accepted, context)
        admissions = dict.fromkeys((item.revision_id for item in accepted), "accepted")
        if binding.subject_attempt is not None:
            attempt = binding.subject_attempt
            allowed = (
                context.boundary == Boundary.EVALUATOR
                and context.isolation == "independent_evaluator"
                and binding.purpose == "evaluation_subject"
            ) or (context.boundary == Boundary.REPAIR and binding.purpose == "repair")
            if not allowed:
                refuse("SUBJECT_NOT_AUTHORIZED", binding, "receiver has no subject authority")
            subjects = await self._contracts.finalized_subject_outputs(
                context.scope,
                context.run_id,
                str(source.output_key),
                operation_ref=attempt.operation_ref,
                operation_attempt=attempt.operation_attempt,
                execution_generation=attempt.execution_generation,
            )
            subjects = tuple(
                item
                for item in subjects
                if item.run_id == context.run_id
                and item.obligation_key == promise.key
                and item.obligation_revision == promise.revision
            )
            if not subjects:
                refuse(
                    "SOURCE_NOT_FINALIZED",
                    binding,
                    "exact producer attempt has no subject",
                    waiting=True,
                )
            current = {item.deliverable_id: item for item in accepted}
            for item in subjects:
                current[item.deliverable_id] = item
                admissions[item.revision_id] = "subject"
            accepted = list(current.values())
        elif "submitted" in binding.accepted_statuses and binding.producer_operation is not None:
            # WI-07: the whole current set, not only the latest executor refs. Every accepted head
            # of the promise stays (earlier successes are retained); the exact producing
            # operation's newer finalized, unrejected revision of a deliverable is the subject in
            # its place, and a deliverable it adds joins the set. Held or rejected revisions are
            # never admitted here (the current-set index labels them).
            current = {item.deliverable_id: item for item in accepted}
            judged: Sequence[Any] | None = None
            for item in await self._contracts.submitted_outputs(
                context.scope,
                context.run_id,
                str(source.output_key),
                operation_ref=binding.producer_operation,
            ):
                head = current.get(item.deliverable_id)
                if head is not None and head.revision >= item.revision:
                    continue
                if item.form is OutputForm.COLLECTION:
                    # Review S1: a collection whose held or rejected members keep its aggregate
                    # rule unmet is never a delivered subject (the index labels it instead).
                    if judged is None:
                        judged = await self._contracts.output_assessments(
                            context.scope, context.run_id
                        )
                    # Exclusion is the conservative direction: any held or rejected verdict
                    # counts here (nothing treated as trusted), it never admits more.
                    if blocked_by_members(promise, item, judged, trusted_validators=frozenset()):
                        continue
                current[item.deliverable_id] = item
                admissions[item.revision_id] = "submitted"
            accepted = list(current.values())
        if not accepted:
            refuse(
                "SOURCE_NOT_ACCEPTED",
                binding,
                f"{source.position}.{source.output_key} has no accepted exact revision yet"
                + (f" (demoted after revocation: {', '.join(demoted)})" if demoted else ""),
                waiting=True,
            )
        resolved: list[ResolvedContent] = []
        for revision in sorted(accepted, key=lambda item: item.deliverable_id):
            admission = admissions[revision.revision_id]
            resolved.extend(
                ResolvedContent(
                    item.member.model_copy(update={"admission": admission}), item.content
                )
                for item in await self.render_revision(
                    binding, context, revision, len(accepted) > 1
                )
            )
            if admission == "subject":
                assessments = await self._contracts.output_assessments(
                    context.scope, context.run_id
                )
                matched = [
                    item.model_dump(mode="json")
                    for item in assessments
                    if item.subject_kind == "output_revision"
                    and item.subject_id == revision.revision_id
                    and item.subject_digest == revision.content_digest
                ]
                content = _plain_json(
                    {
                        "schema_version": "mc.subject-findings.v1",
                        "revision_id": revision.revision_id,
                        "content_digest": revision.content_digest,
                        "admission": "subject",
                        "official_use": False,
                        "assessments": matched,
                    }
                )
                resolved.append(
                    ResolvedContent(
                        ExactMember(
                            member_key=f"{binding.name}/{revision.deliverable_id}/findings",
                            binding=binding.name,
                            part="artifact",
                            source_kind="produced_output",
                            source_ref=revision.revision_id,
                            revision=f"{revision.deliverable_id}@{revision.revision}",
                            issuer=MC_ISSUER,
                            digest=_digest(content),
                            size_bytes=len(content),
                            media_type="application/json",
                            file_name=f"{revision.deliverable_id}-findings.json",
                            purpose=binding.purpose,
                            required=binding.required,
                            access_ref=revision.revision_id,
                            admission="subject",
                        ),
                        content,
                    )
                )
        return tuple(resolved)

    async def _current_heads(
        self, accepted: list[ExactOutput], context: ResolutionContext
    ) -> tuple[list[ExactOutput], list[str]]:
        """OVE-169: a consumer re-check before use. When composed, ``recheck`` re-resolves each
        head's exact KS decision (a revocation records a superseding assessment); a head whose
        standing trusted assessment is no longer ``pass`` is demoted and not admitted."""

        if self._recheck is not None and context.access is not None:
            for revision in accepted:
                await self._recheck(context.access, revision)
        assessments = await self._contracts.output_assessments(context.scope, context.run_id)
        current: list[ExactOutput] = []
        demoted: list[str] = []
        for revision in accepted:
            if head_demoted(assessments, revision.revision_id, revision.content_digest):
                demoted.append(revision.revision_id)
            else:
                current.append(revision)
        return current, demoted

    async def render_revision(
        self,
        binding: TransferInput,
        context: ResolutionContext,
        revision: ExactOutput,
        several: bool,
    ) -> Sequence[ResolvedContent]:
        """Render one already-authorized exact revision using the receiver's own access."""
        candidate = revision.candidate
        prefix = f"{binding.name}/{revision.deliverable_id}" if several else binding.name
        kind = candidate.get("kind")
        ref = candidate.get("ref")
        base = {
            "binding": binding.name,
            "source_kind": "produced_output",
            "source_ref": revision.revision_id,
            "revision": f"{revision.deliverable_id}@{revision.revision}",
            "purpose": binding.purpose,
            "required": binding.required,
        }
        if kind == "inline":
            text = candidate.get("text")
            if isinstance(text, str):
                content = text.encode("utf-8")
                media = str(candidate.get("media_type") or "text/plain")
            elif revision.form is OutputForm.COLLECTION:
                # WI-07: an inline manifest's exact bytes are its canonical member-set document.
                members = candidate.get("members")
                content = canonical_json(
                    collection_document(
                        members if isinstance(members, list) else [], candidate.get("value")
                    )
                )
                media = "application/json"
            else:
                content = canonical_json(candidate.get("value"))
                media = "application/json"
            if _digest(content) != revision.content_digest:
                refuse("DIGEST_MISMATCH", binding, f"{revision.revision_id} inline bytes differ")
            return (
                ResolvedContent(
                    ExactMember.model_validate(
                        base
                        | {
                            "member_key": f"{prefix}/value",
                            "part": "value",
                            "issuer": MC_ISSUER,
                            "digest": revision.content_digest,
                            "size_bytes": len(content),
                            "media_type": media,
                            "file_name": _file_name(revision.deliverable_id, media),
                            "access_ref": revision.revision_id,
                        }
                    ),
                    content,
                ),
            )
        if kind == "handle" and isinstance(ref, str) and "/report/" in ref:
            return await self._report(binding, context, revision, ref, prefix, base)
        if kind in {"handle", "native_id"} and revision.form.value == "reference":
            # An exact reference: issuer, scope and native revision, never a bare URL.
            issuer = candidate.get("issuer") or (
                ref.split("/", 1)[0] if isinstance(ref, str) else None
            )
            native_revision = candidate.get("native_revision")
            if not isinstance(issuer, str) or not isinstance(ref, str) or not native_revision:
                refuse(
                    "REFERENCE_NOT_EXACT",
                    binding,
                    f"{revision.revision_id} names no exact issuer/revision",
                )
            document = {
                "issuer": issuer,
                "scope": context.scope,
                "ref": ref,
                "native_revision": native_revision,
                "digest": revision.content_digest,
            }
            content = _plain_json(document)
            return (
                ResolvedContent(
                    ExactMember.model_validate(
                        base
                        | {
                            "member_key": f"{prefix}/reference",
                            "part": "reference",
                            "issuer": str(issuer),
                            "digest": _digest(content),
                            "size_bytes": len(content),
                            "media_type": "application/json",
                            "file_name": _file_name(revision.deliverable_id, "application/json"),
                            "access_ref": ref,
                        }
                    ),
                    content,
                ),
            )
        if (
            kind == "path"
            and isinstance(ref, str)
            and ref.startswith("artifact://")
            and self._artifacts is not None
        ):
            item = await self._artifacts.exact(
                binding,
                context,
                ref,
                revision.content_digest,
                "artifact",
                source_kind="produced_output",
                revision=f"{revision.deliverable_id}@{revision.revision}",
            )
            member = item.member.model_copy(
                update={
                    "member_key": f"{prefix}/artifact",
                    "source_ref": revision.revision_id,
                }
            )
            return (ResolvedContent(member, item.content),)
        refuse(
            "SOURCE_FORM_UNSUPPORTED",
            binding,
            f"{revision.revision_id} ({revision.form.value}, {kind}) has no exact custody route",
        )
        raise AssertionError  # pragma: no cover

    async def _report(
        self,
        binding: TransferInput,
        context: ResolutionContext,
        revision: ExactOutput,
        handle: str,
        prefix: str,
        base: Mapping[str, Any],
    ) -> Sequence[ResolvedContent]:
        if self._reports is None or context.access is None:
            refuse("KNOWLEDGE_READ_UNWIRED", binding, "no exact knowledge read is composed")
        assert self._reports is not None and context.access is not None
        try:
            resolved = await self._reports.resolve(
                SelectedItem(kind="handle", ref=handle, digest=revision.content_digest),
                context.access,
                purpose=binding.purpose,
            )
        except ResolutionRefused as refused:
            refuse(refused.code, binding, str(refused))
            raise AssertionError from None  # pragma: no cover
        package = resolved.package
        issuer = resolved.report.binding
        # Qualified on-demand handles: the exact assertion and fragment refs the package names.
        evidence = tuple(
            f"{handle}#fragment:{item.handle.id}@{item.handle.digest}" for item in package.evidence
        )
        assertions = tuple(
            f"{handle}#assertion:{item.handle.id}@{item.handle.digest}"
            for item in package.assertions
        )
        # The exact report handle and its revision digest: what each attempt re-reads.
        common = dict(base) | {
            "issuer": issuer,
            "access_ref": f"{handle}{_DIGEST_SEPARATOR}{revision.content_digest}",
        }
        parts: list[ResolvedContent] = []
        for part, content, media, name in (
            ("body", resolved.body, "text/markdown", "body.md"),
            ("ledger", resolved.ledger, "application/json", "ledger.json"),
            ("manifest", resolved.manifest_bytes, "application/json", "manifest.json"),
        ):
            parts.append(
                ResolvedContent(
                    ExactMember.model_validate(
                        common
                        | {
                            "member_key": f"{prefix}/{part}",
                            "part": part,
                            "revision": f"{resolved.report.id}@{resolved.report.version}",
                            "digest": _digest(content),
                            "size_bytes": len(content),
                            "media_type": media,
                            "file_name": name,
                            "handles": assertions if part == "manifest" else (),
                        }
                    ),
                    content,
                )
            )
        if evidence:
            listing = json.dumps(list(evidence)).encode("utf-8")
            parts.append(
                ResolvedContent(
                    ExactMember.model_validate(
                        common
                        | {
                            "member_key": f"{prefix}/evidence",
                            "part": "evidence",
                            "revision": f"{resolved.report.id}@{resolved.report.version}",
                            "digest": _digest(listing),
                            "size_bytes": len(listing),
                            "media_type": "application/json",
                            "file_name": "evidence.json",
                            "handles": evidence,
                        }
                    ),
                    None,
                )
            )
        return tuple(parts)


class ApplicationSelectorResolver:
    """``application_selector(binding_pin, selector)``: only a registered application port that
    answers an exact native revision or a retained observation; a live query is not replay."""

    def __init__(self, selectors: Mapping[str, SourceResolver]) -> None:
        self._selectors = dict(selectors)

    async def resolve(
        self, binding: TransferInput, context: ResolutionContext
    ) -> Sequence[ResolvedContent]:
        pin = binding.source.binding_pin
        assert pin is not None
        selector = self._selectors.get(pin)
        if selector is None:
            refuse(
                "APPLICATION_SELECTOR_UNRESOLVED",
                binding,
                f"no admitted application binding {pin} resolves selectors exactly",
            )
            raise AssertionError  # pragma: no cover
        resolved = tuple(await selector.resolve(binding, context))
        for item in resolved:
            member = item.member
            if (
                member.source_kind != "application_selector"
                or not member.revision
                or (item.content is None and not member.handles)
            ):
                refuse(
                    "APPLICATION_SELECTOR_NOT_EXACT",
                    binding,
                    f"{member.member_key} is not an exact native revision or retained observation",
                )
        return resolved


class KnowledgeReadAccess:
    """Current access to a KS report member: the exact read must still succeed for this attempt
    and answer the sealed package (a revoked, erased or changed revision stops readiness)."""

    def __init__(self, reports: ContentResolutionService) -> None:
        self._reports = reports

    async def check(self, member: ExactMember, context: ResolutionContext) -> AccessCheck:
        """Every KS member (manifest, body, ledger, evidence) re-reads its exact revision for this
        realization and must still match: the part's bytes digest, or its qualified handles."""

        if member.issuer == MC_ISSUER:
            return AccessCheck(ok=True, ref=f"mc-scope:{context.scope}")
        if context.access is None:
            return AccessCheck(
                ok=False, ref=f"ks:{member.access_ref}", code="KNOWLEDGE_ACCESS_UNAVAILABLE"
            )
        handle, _, report_digest = member.access_ref.partition(_DIGEST_SEPARATOR)
        try:
            resolved = await self._reports.resolve(
                SelectedItem(kind="handle", ref=handle, digest=report_digest),
                context.access,
                purpose=member.purpose,
                # Every realization re-reads (a restart of the same attempt included): a revoked
                # or erased revision is never answered from an earlier read.
                attempt_key=f"{context.access.invocation_ref[:40]}:{uuid4().hex[:16]}",
            )
        except ResolutionRefused as refused:
            return AccessCheck(ok=False, ref=f"ks:{member.access_ref}", code=refused.code)
        current = {
            "manifest": _digest(resolved.manifest_bytes),
            "body": _digest(resolved.body),
            "ledger": _digest(resolved.ledger),
        }
        if member.part == "evidence":
            served = {
                f"{handle}#fragment:{item.handle.id}@{item.handle.digest}"
                for item in resolved.package.evidence
            }
            unchanged = set(member.handles) <= served
        else:
            unchanged = current.get(member.part) == member.digest
        if not unchanged:
            return AccessCheck(ok=False, ref=f"ks:{member.access_ref}", code="REVISION_CHANGED")
        return AccessCheck(ok=True, ref=f"ks:{resolved.result_ref.id}@{resolved.result_ref.digest}")


__all__ = [
    "AccessCheck",
    "ApplicationSelectorResolver",
    "ArtifactResolver",
    "ContentCustody",
    "ContextDeliveryBlocked",
    "CurrentAccessPort",
    "KnowledgeReadAccess",
    "LiteralResolver",
    "MaterializeRequest",
    "MaterializedTransfer",
    "ProducedOutputResolver",
    "ReceiverBackend",
    "ResolutionContext",
    "ResolvedContent",
    "SourceRefused",
    "SourceResolver",
    "TransferMaterializer",
    "TransferPlanConflict",
    "TransferPlanStore",
]
