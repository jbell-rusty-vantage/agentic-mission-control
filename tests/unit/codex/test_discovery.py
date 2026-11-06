"""MO-34: the `codex` Discovery Proof is the app-server's own `skills/list`, `hooks/list` and
`config/read` after `thread/start`.

- RECORDED (`tests/fixtures/projections/discovery/codex.recorded.json`, codex-cli 0.162.1,
  no login, no model turn): over a repository that owns an `AGENTS.md`, a skill and an MCP
  server, the real app-server lists the mission's skill, trusted `SessionStart` hook and MCP
  server beside the repository's own, so the report proves the expectation the prepare records.
  Re-record with ``uv run --frozen python -m tests.fixtures.projections.discovery.codex_cli``
  (no provider call); the recording is bound to the projection digest.
- FIXTURE app-server: the harness reads back after `thread/start`, and `lane.turn` persists the
  report as a frame and raises the environment to `discovered`.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from mission_control.adapters.codex.discovery import app_server_report
from mission_control.application.agentic_components.layering import LayeringReceipt
from mission_control.application.agentic_components.materialization import projection_digest
from mission_control.application.environments import (
    EnvironmentPreparationService,
    InMemoryEnvironmentPreparationRepository,
)
from mission_control.application.environments.discovery import (
    DISCOVERY_RAW_KIND,
    discovery_expectation,
)
from mission_control.application.execution.harness.lane_turns import harness_scope
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.discovery import DiscoveryItem, discovery_gaps
from mission_control.domain.execution.environment_preparation import (
    ReadinessLevel,
    preparation_id,
)
from mission_control.domain.execution.lanes import PrepareRequest, StartRequest
from mission_control.domain.frames.contracts import FrameKind
from tests.fixtures.lane_turns import RecordingSignals, lane_stack
from tests.fixtures.projections.discovery import codex_cli
from tests.unit.codex.support import codex_operation, codex_stack

RECORDING = json.loads(codex_cli.RECORDING.read_text(encoding="utf-8"))
BOUNDS = {"heartbeat_timeout_s": 60, "max_frames": 100}


def _expectation() -> Any:
    return discovery_expectation(
        LaneProfile.CODEX,
        LayeringReceipt.model_validate(RECORDING["layering"]),
        RECORDING["placed"],
    )


def _report(answers: dict[str, Any]) -> Any:
    return app_server_report(
        answers["skills_list"],
        answers["hooks_list"],
        answers["config_read"],
        source="app_server:recording",
    )


# --- the recording ------------------------------------------------------------------------------


def test_recording_is_labelled_and_made_without_a_provider_call() -> None:
    assert RECORDING["schema_version"] == "mc.discovery_recording.v1"
    assert RECORDING["fixture"] is True and RECORDING["lane_profile"] == "codex"
    assert RECORDING["cli"]["version"].startswith("codex-cli 0.162")
    assert "127.0.0.1:9" in RECORDING["provider_call"]
    assert RECORDING["requests"][-3:] == [
        "skills/list {cwds}",
        "hooks/list {cwds}",
        "config/read {cwd}",
    ]


def test_recording_matches_the_current_projection() -> None:
    projection = codex_cli.project()
    assert RECORDING["projection_digest"] == projection_digest(projection), (
        "codex projection changed: re-record "
        "`uv run --frozen python -m tests.fixtures.projections.discovery.codex_cli`"
    )
    assert RECORDING["projected_paths"] == list(projection.paths())


def test_the_recorded_lists_prove_what_the_mission_placed_beside_the_repository() -> None:
    expectation = _expectation()
    assert expectation is not None and expectation.mechanism == "app_server"
    assert set(expectation.items) == {
        DiscoveryItem(kind="skill", name="agent-browser"),
        DiscoveryItem(kind="hook", name="SessionStart"),
        DiscoveryItem(kind="hook", name="Stop"),
        DiscoveryItem(kind="hook", name="SubagentStop"),
        DiscoveryItem(kind="mcp_server", name="mc-discovery-stub"),
    }
    report = _report(RECORDING["answers"])
    assert discovery_gaps(expectation, report) == ()
    # The repository's own cognition loads too, and the layered files were put back.
    assert {
        DiscoveryItem(kind="skill", name="repo-notes"),
        DiscoveryItem(kind="mcp_server", name="repo-docs"),
    } <= set(report.items)
    assert RECORDING["repository"]["byte_identical_after_restore"] is True


def test_an_untrusted_mission_hook_or_a_disabled_item_is_not_discovered() -> None:
    answers = deepcopy(RECORDING["answers"])
    for item in answers["hooks_list"]["data"]:
        for hook in item["hooks"]:
            hook["trustStatus"] = "untrusted"
    for item in answers["skills_list"]["data"]:
        for skill in item["skills"]:
            skill["enabled"] = False
    answers["config_read"]["config"]["mcp_servers"]["mc-discovery-stub"]["enabled"] = False
    assert set(discovery_gaps(_expectation(), _report(answers))) == {
        "skill agent-browser was not reported loaded",
        "hook SessionStart was not reported loaded",
        "hook Stop was not reported loaded",
        "hook SubagentStop was not reported loaded",
        "mcp_server mc-discovery-stub was not reported loaded",
    }


def test_recording_is_path_and_user_free() -> None:
    text = codex_cli.RECORDING.read_text(encoding="utf-8")
    assert "\r\n" not in text
    for needle in ("Users\\\\", "/Users/", "/home/", "AppData", "sk-"):
        assert needle not in text
    scopes = {
        skill["scope"]
        for item in RECORDING["answers"]["skills_list"]["data"]
        for skill in item["skills"]
    }
    assert scopes <= {"repo", "system"}


# --- the harness over the FIXTURE app-server ----------------------------------------------------


async def test_the_harness_reads_back_what_the_app_server_loaded(tmp_path: Path) -> None:
    stack = codex_stack(tmp_path)
    harness = stack.harness
    harness.stage(stack.heid, stack.operation)
    fields = {
        "scope": harness_scope(stack.operation.request_scope),
        "lane_profile": "codex",
        "harness_execution_id": stack.heid,
        "binding_digest": stack.operation.effective_configuration_digest,
        "idempotency_key": f"{stack.heid}:1:test",
        "generation": 1,
    }
    prepared = await harness.prepare(
        PrepareRequest(
            **fields,
            run_id=stack.operation.identity.run_id,
            operation_id=stack.operation.identity.operation_id,
            attempt_no=1,
        )
    )
    session = await harness.start(StartRequest(**fields, prepared=prepared))
    try:
        assert prepared.discovery is not None
        assert prepared.discovery.items == (DiscoveryItem(kind="mcp_server", name="mc-fixture"),)
        report = await harness.discover(session)
        assert report is not None and report.source == f"app_server:{session.native_session_ref}"
        assert discovery_gaps(prepared.discovery, report) == ()
        requested = [method for method, _params in stack.launcher.server.records]
        assert {"skills/list", "hooks/list", "config/read"} <= set(requested)
    finally:
        await stack.launcher.shutdown()


async def test_a_lane_turn_persists_the_proof_and_the_environment_is_discovered(
    tmp_path: Path,
) -> None:
    repository = InMemoryEnvironmentPreparationRepository()
    stack = codex_stack(tmp_path, "turn_full")
    operation = codex_operation()
    lanes = lane_stack(
        stack.harness,
        operation=operation,
        preparations=EnvironmentPreparationService(repository),
    )
    result = await lanes.service.turn(stack.turn(segment=BOUNDS), RecordingSignals(lanes.frames))
    assert result.done
    identity = stack.identity
    stored = await repository.get(
        identity.request_scope,
        preparation_id(identity.request_scope, identity.harness_execution_id, 1),
    )
    assert stored is not None and stored.readiness is ReadinessLevel.DISCOVERED
    mark = stored.mark(ReadinessLevel.DISCOVERED)
    assert mark is not None and mark.evidence_ref.startswith("frame:discovery:thr-")
    execution = lanes.frames._executions[identity.harness_execution_id]
    (frame,) = [item for item in execution.frames.values() if item.raw_kind == DISCOVERY_RAW_KIND]
    assert frame.kind is FrameKind.STATUS
