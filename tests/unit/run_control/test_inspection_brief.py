"""A Coordinator reads a run's Mission Brief back from the run's inspection.

The brief is sealed in the committed definition of the revision the run was admitted for, so
`run inspect` reads it from there, never from a transcript or a prompt. A fork-derived run
holds a run-request definition: its brief is its source run's. No database: the reader runs
over an in-memory definitions port and the real inspection assembly.
"""

from __future__ import annotations

from typing import Any

import pytest

from mission_control.application.authoring.manifest_submit import (
    RUN_REQUEST_DEFINITION,
    ForkStartSource,
)
from mission_control.application.authoring.run_brief import ManifestRunBriefs
from mission_control.application.execution.boundary_interventions import BoundaryInterventionService
from mission_control.application.missions.inspection import InspectionSources
from mission_control.application.missions.service import MissionControlService
from mission_control.domain.authoring.brief import MissionBrief
from tests.unit.run_control.test_ft_f1_command_mailbox import SCOPE, World, operator

BRIEF: dict[str, Any] = {
    "purpose": "system",
    "request": "Show me that a first mission runs end to end here.",
    "answers": [{"question": "Who reviews it?", "answer": "I do."}],
    "done_means": "I read three clear sentences and approve them.",
    "out_of_scope": ["No web research."],
    "requested_by": "owner",
}


class Definitions:
    """Run key -> the committed definition of its revision (`run_subscriptions`)."""

    def __init__(self, definitions: dict[str, Any]) -> None:
        self._definitions = definitions
        self.asked: list[tuple[str, str]] = []

    async def run_subscriptions(self, request_scope: str, run_key: str) -> dict[str, Any] | None:
        self.asked.append((request_scope, run_key))
        if run_key not in self._definitions:
            return None
        return {"run_uuid": None, "mission_id": None, "definition": self._definitions[run_key]}


class Forks:
    def __init__(self, sources: dict[str, str]) -> None:
        self._sources = sources

    async def fork_source(self, request_scope: str, run_id: str) -> ForkStartSource | None:
        source = self._sources.get(run_id)
        return None if source is None else ForkStartSource("fork-1", source)


@pytest.mark.asyncio
async def test_a_runs_brief_is_read_from_its_committed_definition() -> None:
    definitions = Definitions(
        {
            "run-with": {"mission_key": "hello", "brief": BRIEF},
            "run-without": {"mission_key": "hello"},
            "run-unreadable": {"mission_key": "hello", "brief": {"purpose": "nonsense"}},
        }
    )
    reader = ManifestRunBriefs(definitions)

    brief = await reader.run_brief(SCOPE, "run-with")

    assert brief == MissionBrief.model_validate(BRIEF)
    assert brief is not None and brief.requested_by == "owner"
    assert definitions.asked == [(SCOPE, "run-with")]
    # A mission that records none, a run that is no manifest run and a body no brief
    # validates from all read as no brief: inspection never fails on it.
    assert await reader.run_brief(SCOPE, "run-without") is None
    assert await reader.run_brief(SCOPE, "run-unknown") is None
    assert await reader.run_brief(SCOPE, "run-unreadable") is None


@pytest.mark.asyncio
async def test_a_forks_brief_is_its_source_runs() -> None:
    definitions = Definitions(
        {
            "run-source": {"mission_key": "hello", "brief": BRIEF},
            "run-fork": {"contract": RUN_REQUEST_DEFINITION},
            "run-orphan": {"contract": RUN_REQUEST_DEFINITION},
        }
    )
    reader = ManifestRunBriefs(definitions, fork_sources=Forks({"run-fork": "run-source"}))

    assert await reader.run_brief(SCOPE, "run-fork") == MissionBrief.model_validate(BRIEF)
    # A run request that is no fork of a manifest run has no brief.
    assert await reader.run_brief(SCOPE, "run-orphan") is None
    # Without a fork source composed a run-request definition reads as no brief.
    assert await ManifestRunBriefs(definitions).run_brief(SCOPE, "run-fork") is None


@pytest.mark.asyncio
async def test_inspection_carries_the_brief_and_leaves_the_key_out_without_one() -> None:
    world = await World().start()
    definitions = Definitions({world.run_id: {"mission_key": "hello", "brief": BRIEF}})

    def facade(source: Definitions) -> MissionControlService:
        return MissionControlService(
            world.authority,
            BoundaryInterventionService(world.authority),
            request_scope=SCOPE,
            inspection=InspectionSources(brief=ManifestRunBriefs(source)),
        )

    inspection = await facade(definitions).inspect(world.run_id, operator())

    assert inspection.brief == MissionBrief.model_validate(BRIEF)
    body = inspection.model_dump(mode="json")
    assert body["brief"]["purpose"] == "system"
    assert body["brief"]["request"] == BRIEF["request"]
    assert body["brief"]["answers"] == BRIEF["answers"]
    assert body["brief"]["requested_by"] == "owner"
    # No brief: the section is left out, so existing clients keep parsing the same body.
    without = await facade(Definitions({})).inspect(world.run_id, operator())
    assert without.brief is None and "brief" not in without.model_dump(mode="json")
