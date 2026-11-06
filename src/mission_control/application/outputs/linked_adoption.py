"""Explicit linked adoption rechecks released authority and the receiver's current use."""

from datetime import datetime

from mission_control.application.context.linked_transfer import LinkedExportResolver
from mission_control.application.context.materialization import ResolutionContext
from mission_control.application.outputs.adoption import (
    AdoptionResult,
    AdoptionSource,
    OutputAdoptionService,
)
from mission_control.domain.context.transfer import TransferInput


class LinkedOutputAdoptionService:
    """Create target drafts through the existing submission act; never promote outputs."""

    def __init__(self, resolver: LinkedExportResolver, adoption: OutputAdoptionService) -> None:
        self._resolver = resolver
        self._adoption = adoption

    async def adopt(
        self,
        binding: TransferInput,
        context: ResolutionContext,
        *,
        target_obligation: str,
        at: datetime,
    ) -> AdoptionResult:
        export = await self._resolver.authorize(binding, context)
        if export.admission != "accepted" or export.purpose != "dependent_input":
            return AdoptionResult(False, code="linked_adoption_requires_accepted_use")
        exact = [
            await self._resolver.exact_output(export, selected, binding, context)
            for selected in export.outputs
        ]
        assert context.access is not None  # authorize checked the exact live receiver
        return await self._adoption.adopt(
            context.access,
            position=context.receiver_position,
            target_obligation=target_obligation,
            sources=tuple(
                AdoptionSource(item.run_id, item.revision_id, item.content_digest) for item in exact
            ),
            act=f"linked_export:{export.export_id}@{export.digest}",
            at=at,
        )
