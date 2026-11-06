"""Exact released cross-run inputs under the receiver's own current authority.

The chain store creates export authority at release. This module never selects a source run,
accepts an output, adopts an obligation, or replaces a pinned revision with a newer head.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Protocol

from mission_control.application.context.materialization import (
    MC_ISSUER,
    AccessCheck,
    CurrentAccessPort,
    HeadRecheck,
    ProducedOutputResolver,
    ResolutionContext,
    ResolvedContent,
    SourceRefused,
    refuse,
)
from mission_control.application.knowledge.judgment import (
    EvaluatorUnavailable,
    TrustedJudgmentRefused,
)
from mission_control.application.ports.outputs import OutputContractStore
from mission_control.domain.authoring.canonical import canonical_json
from mission_control.domain.context.transfer import (
    Boundary,
    ExactMember,
    InputSource,
    LinkedExport,
    LinkedOutputRef,
    LinkedSourceIdentity,
    TransferInput,
)
from mission_control.domain.knowledge.judgment import head_demoted
from mission_control.domain.outputs.contracts import ExactOutput


class LinkedExportPort(Protocol):
    async def released_for(
        self,
        scope: str,
        receiver_run_id: str,
        receiver_position: str,
    ) -> tuple[LinkedExport, ...]:
        """Only durable released exports for this exact receiver; never legacy packets."""
        ...

    async def get_export(self, scope: str, export_id: str) -> LinkedExport | None:
        """Read an immutable export whose chain release and receiver admission are proven."""
        ...


class LinkedExportResolver:
    def __init__(
        self,
        exports: LinkedExportPort,
        outputs: OutputContractStore,
        renderer: ProducedOutputResolver,
        *,
        recheck: HeadRecheck | None = None,
    ) -> None:
        self._exports = exports
        self._outputs = outputs
        self._renderer = renderer
        self._recheck = recheck

    async def authorize(
        self,
        binding: TransferInput,
        context: ResolutionContext,
    ) -> LinkedExport:
        source = binding.source
        if (
            source.kind != "linked_export"
            or context.boundary
            not in {Boundary.LINKED_MISSION, Boundary.NEXT_ITERATION, Boundary.REPAIR}
            or context.isolation != "shared"
        ):
            refuse("LINK_BOUNDARY_MISMATCH", binding, "no admitted linked transfer boundary")
        access = context.access
        if (
            access is None
            or access.scope != context.scope
            or access.origin.run_id != context.run_id
            or access.origin.operation_id != context.receiver_operation_id
        ):
            refuse("LINK_RECEIVER_AUTHORITY", binding, "no matching live receiver authority")
        assert source.export_id is not None
        export = await self._exports.get_export(context.scope, source.export_id)
        if export is None:
            refuse("LINK_EXPORT_UNRELEASED", binding, "no durable released export", waiting=True)
        assert export is not None
        try:
            export = LinkedExport.model_validate(export.model_dump(mode="python"))
        except ValueError:
            refuse("LINK_EXPORT_INVALID", binding, "stored export authority is invalid")
        if export.export_id != source.export_id or export.digest != source.digest:
            refuse("LINK_EXPORT_DIGEST", binding, "released export identity differs from its pin")
        if (
            export.request_scope != context.scope
            or export.receiver_run_id != context.run_id
            or export.receiver_position != context.receiver_position
        ):
            refuse("LINK_RECEIVER_MISMATCH", binding, "export belongs to another receiver")
        if (
            export.input_name != binding.name
            or export.purpose != binding.purpose
            or export.required != binding.required
            or export.placement != binding.placement
            or export.alternatives != binding.alternatives
            or export.evidence_required != binding.evidence_required
            or binding.subject_attempt is not None
            or binding.producer_operation is not None
            or binding.accepted_statuses != ("accepted",)
        ):
            refuse(
                "LINK_BINDING_MISMATCH", binding, "receiver binding differs from released policy"
            )
        return export

    async def exact_output(
        self,
        export: LinkedExport,
        selected: LinkedOutputRef,
        binding: TransferInput,
        context: ResolutionContext,
    ) -> ExactOutput:
        revision = await self._outputs.output_revision(context.scope, selected.revision_id)
        if (
            revision is None
            or revision.revision_id != selected.revision_id
            or revision.run_id != export.source_run_id
            or revision.obligation_key != selected.obligation_key
            or revision.obligation_revision != selected.obligation_revision
            or revision.content_digest != selected.content_digest
        ):
            refuse("LINK_OUTPUT_MISMATCH", binding, "export does not name the exact stored output")
        assert revision is not None
        obligation = await self._outputs.obligation_revision(
            context.scope,
            export.source_run_id,
            selected.obligation_key,
            selected.obligation_revision,
        )
        if (
            obligation is None
            or obligation.owner_position != selected.owner_position
            or obligation.key != selected.obligation_key
            or obligation.revision != selected.obligation_revision
        ):
            refuse("LINK_OUTPUT_OWNER", binding, "exported output has another source owner")
        if export.admission == "accepted":
            candidate = revision.candidate
            report = candidate.get("kind") == "handle" and "/report/" in str(candidate.get("ref"))
            if report and self._recheck is None:
                refuse("LINK_CURRENT_USE_UNWIRED", binding, "current source use must be rechecked")
            if self._recheck is not None:
                assert context.access is not None
                try:
                    await self._recheck(context.access, revision)
                except (EvaluatorUnavailable, TrustedJudgmentRefused):
                    refuse(
                        "LINK_CURRENT_USE_UNAVAILABLE",
                        binding,
                        "current exact source use cannot be established",
                        waiting=True,
                    )
            assessments = await self._outputs.output_assessments(
                context.scope, export.source_run_id
            )
            if head_demoted(assessments, revision.revision_id, revision.content_digest):
                refuse("LINK_OUTPUT_REVOKED", binding, "exact exported output is no longer usable")
        return revision

    async def resolve(
        self,
        binding: TransferInput,
        context: ResolutionContext,
    ) -> Sequence[ResolvedContent]:
        export = await self.authorize(binding, context)
        resolved: list[ResolvedContent] = []
        for selected in export.outputs:
            revision = await self.exact_output(export, selected, binding, context)
            identity = LinkedSourceIdentity(
                export_id=export.export_id,
                export_digest=export.digest,
                source_run_id=export.source_run_id,
                output_revision_id=revision.revision_id,
                output_digest=revision.content_digest,
            )
            items = await self._renderer.render_revision(
                binding,
                context,
                revision,
                len(export.outputs) > 1,
            )
            for item in items:
                member = item.member.model_copy(
                    update={
                        "source_kind": "linked_export",
                        "linked_source": identity,
                        "admission": export.admission,
                        # Revision IDs distinguish same-named deliverables of different promises.
                        "member_key": f"{binding.name}/{revision.revision_id}/{item.member.part}",
                    }
                )
                resolved.append(ResolvedContent(member, item.content))
            if export.admission == "subject":
                assessments = await self._outputs.output_assessments(
                    context.scope, export.source_run_id
                )
                content = canonical_json(
                    {
                        "schema_version": "mc.linked-subject-findings.v1",
                        "export_id": export.export_id,
                        "export_digest": export.digest,
                        "source_run_id": export.source_run_id,
                        "revision_id": revision.revision_id,
                        "content_digest": revision.content_digest,
                        "admission": "subject",
                        "official_use": False,
                        "goal_findings": [
                            item.model_dump(mode="json") for item in selected.goal_findings or ()
                        ],
                        "assessments": [
                            item.model_dump(mode="json")
                            for item in assessments
                            if item.subject_kind == "output_revision"
                            and item.subject_id == revision.revision_id
                            and item.subject_digest == revision.content_digest
                        ],
                    }
                )
                resolved.append(
                    ResolvedContent(
                        ExactMember(
                            member_key=f"{binding.name}/{revision.revision_id}/findings",
                            binding=binding.name,
                            part="artifact",
                            source_kind="linked_export",
                            source_ref=revision.revision_id,
                            revision=f"{revision.deliverable_id}@{revision.revision}",
                            issuer=MC_ISSUER,
                            digest="sha256:" + hashlib.sha256(content).hexdigest(),
                            size_bytes=len(content),
                            media_type="application/json",
                            file_name=f"{revision.revision_id}-findings.json",
                            purpose=export.purpose,
                            required=export.required,
                            access_ref=revision.revision_id,
                            admission="subject",
                            linked_source=identity,
                        ),
                        content,
                    )
                )
        return tuple(resolved)


class LinkedExportAccess:
    """Revalidate the same export and exact current use on every sealed-plan realization."""

    def __init__(self, resolver: LinkedExportResolver, content_access: CurrentAccessPort) -> None:
        self._resolver = resolver
        self._content_access = content_access

    async def check(self, member: ExactMember, context: ResolutionContext) -> AccessCheck:
        identity = member.linked_source
        if identity is None or member.source_kind != "linked_export":
            return AccessCheck(ok=False, ref=member.access_ref, code="LINK_IDENTITY_MISSING")
        export = await self._resolver._exports.get_export(context.scope, identity.export_id)
        if export is None:
            return AccessCheck(ok=False, ref=identity.export_id, code="LINK_EXPORT_UNRELEASED")
        try:
            export = LinkedExport.model_validate(export.model_dump(mode="python"))
        except ValueError:
            return AccessCheck(ok=False, ref=identity.export_id, code="LINK_EXPORT_INVALID")
        binding = TransferInput(
            name=member.binding,
            source=InputSource.linked(identity.export_id, identity.export_digest),
            purpose=member.purpose,
            required=member.required,
            placement=export.placement,
            alternatives=export.alternatives,
            evidence_required=export.evidence_required,
        )
        try:
            export = await self._resolver.authorize(binding, context)
            selected = next(
                (
                    item
                    for item in export.outputs
                    if item.revision_id == identity.output_revision_id
                    and item.content_digest == identity.output_digest
                ),
                None,
            )
            if (
                selected is None
                or identity.source_run_id != export.source_run_id
                or member.source_ref != identity.output_revision_id
                or member.admission != export.admission
            ):
                return AccessCheck(ok=False, ref=identity.export_id, code="LINK_OUTPUT_MISMATCH")
            await self._resolver.exact_output(export, selected, binding, context)
        except SourceRefused as error:
            return AccessCheck(ok=False, ref=identity.export_id, code=error.refusal.code)
        return await self._content_access.check(member, context)


__all__ = ["LinkedExportAccess", "LinkedExportPort", "LinkedExportResolver"]
