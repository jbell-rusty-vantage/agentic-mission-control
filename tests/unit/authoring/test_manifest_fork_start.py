"""F1-G2: ``missions:start`` on a fork-derived run never answers 500.

A fork admits its derived run with a run-request definition (``mc.run-request-definition/1``),
never a ``MissionDefinition@1``. ``ManifestSubmitService.start`` resolves the fork to its
source run's manifest submission, or refuses with a typed ``ManifestStartRefused`` (HTTP 409).
The successful derivation on PostgreSQL is ``tests/integration/postgres/
test_fork_completion_postgres.py``.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from mission_control.application.authoring.manifest_submit import (
    RUN_REQUEST_DEFINITION,
    ForkStartSource,
    ManifestStartRefused,
    ManifestSubmitService,
)
from mission_control.domain.policies.contracts import ActorContext

pytestmark = pytest.mark.asyncio

OWNER = ActorContext(
    actor_id="owner",
    authority_refs=frozenset({"authority:owner"}),
    permissions=frozenset({"workflow_run.start", "workflow_run.read"}),
)
RUN_REQUEST = {"contract": RUN_REQUEST_DEFINITION, "request_scope": "scope"}


class Submissions:
    def __init__(self, definitions: dict[str, Any]) -> None:
        self.definitions = definitions

    async def run_subscriptions(self, request_scope: str, run_key: str) -> Any:
        if run_key not in self.definitions:
            return None
        return {
            "run_uuid": uuid4(),
            "mission_id": uuid4(),
            "revision_id": uuid4(),
            "definition": self.definitions[run_key],
        }


class Forks:
    def __init__(self, source: ForkStartSource | None) -> None:
        self.source = source

    async def fork_source(self, request_scope: str, run_id: str) -> ForkStartSource | None:
        return self.source


def service(definitions: dict[str, Any], forks: Forks | None) -> ManifestSubmitService:
    return ManifestSubmitService(
        compiler=None,  # type: ignore[arg-type]
        programs=None,  # type: ignore[arg-type]
        run_control=None,  # type: ignore[arg-type]
        submissions=Submissions(definitions),  # type: ignore[arg-type]
        request_scope="scope",
        launches=object(),  # type: ignore[arg-type]
        fork_sources=forks,
    )


async def refused(svc: ManifestSubmitService, run_id: str = "derived") -> ManifestStartRefused:
    with pytest.raises(ManifestStartRefused) as raised:
        await svc.start(run_id, OWNER)
    return raised.value


async def test_a_run_request_run_without_fork_sources_is_refused_typed() -> None:
    error = await refused(service({"derived": RUN_REQUEST}, None))
    assert error.code == "fork_start_unavailable"


async def test_a_run_request_run_that_is_no_fork_is_refused_typed() -> None:
    error = await refused(service({"derived": RUN_REQUEST}, Forks(None)))
    assert error.code == "not_a_manifest_run"


async def test_a_fork_of_a_run_request_run_is_refused_typed() -> None:
    forks = Forks(ForkStartSource(fork_request_id="fork-1", source_run_id="source"))
    error = await refused(service({"derived": RUN_REQUEST, "source": RUN_REQUEST}, forks))
    assert error.code == "fork_source_not_manifest"
    error = await refused(service({"derived": RUN_REQUEST}, forks))
    assert error.code == "fork_source_not_manifest"


async def test_an_unreadable_definition_is_refused_typed_not_a_500() -> None:
    error = await refused(service({"derived": {"contract": "something-else"}}, None))
    assert error.code == "definition_unreadable"
