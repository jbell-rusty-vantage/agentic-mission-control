"""Reading a run's Mission Brief back: the brief its revision's definition seals.

The brief is part of the committed ``MissionDefinition@1`` (``domain/authoring/brief.py``), so
a run's brief is read from the definition of the revision the run was admitted for, never
from a transcript or a prompt. A fork-derived run holds a run-request definition; its brief
is its source run's, as its manifest is. A run that was not submitted from a manifest, or
whose mission records no brief, has none.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import ValidationError

from mission_control.application.authoring.manifest_submit import (
    RUN_REQUEST_DEFINITION,
    ForkSourcePort,
)
from mission_control.domain.authoring.brief import MissionBrief


class RunDefinitionReader(Protocol):
    async def run_subscriptions(self, request_scope: str, run_key: str) -> dict[str, Any] | None:
        """The run's mission and its revision's committed ``definition``."""


class ManifestRunBriefs:
    """The brief of a manifest run, read from its committed definition."""

    def __init__(
        self, definitions: RunDefinitionReader, *, fork_sources: ForkSourcePort | None = None
    ) -> None:
        self._definitions = definitions
        self._fork_sources = fork_sources

    async def run_brief(self, request_scope: str, run_id: str) -> MissionBrief | None:
        body = await self._definition(request_scope, run_id)
        if _run_request(body) and self._fork_sources is not None:
            fork = await self._fork_sources.fork_source(request_scope, run_id)
            body = (
                await self._definition(request_scope, fork.source_run_id)
                if fork is not None
                else None
            )
        brief = body.get("brief") if isinstance(body, dict) else None
        if not isinstance(brief, dict):
            return None
        try:
            return MissionBrief.model_validate(brief)
        except ValidationError:
            return None

    async def _definition(self, request_scope: str, run_id: str) -> Any:
        info = await self._definitions.run_subscriptions(request_scope, run_id)
        return info.get("definition") if info is not None else None


def _run_request(body: Any) -> bool:
    return isinstance(body, dict) and body.get("contract") == RUN_REQUEST_DEFINITION


__all__ = ["ManifestRunBriefs", "RunDefinitionReader"]
