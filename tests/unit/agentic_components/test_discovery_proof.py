"""MO-34: a Discovery Proof raises an environment to `discovered` (SPEC-02 section 6, G14).

- The contract: a report proves its expectation when it names every expected item and reads
  every expected digest; it may name more (repository, user, bundled cognition), and anything
  short of the expectation is named as a gap.
- Expectations: each lane expects what its mechanism can report, from the layering receipt's
  mission items; file-reading mechanisms also expect the overlay and hook config as placed.
- The `materialization.observed` signal (MO-41's data) reads as a report; bad data only fails it.
- The service: a complete report raises a prepared environment to `discovered`; on a cloud lane
  with no mission layer a provider-side proof also lifts `prepared` (the report digest is the
  receipt), which is how cursor_cloud and both hosted API lanes reach `discovered`; a mission
  layer still waits for its receipt; nothing short of the expectation changes the record.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from mission_control.application.agentic_components.layering import (
    DiscoveredItem,
    LayeringReceipt,
)
from mission_control.application.environments import (
    EnvironmentPreparationService,
    InMemoryEnvironmentPreparationRepository,
    preparation_of,
)
from mission_control.application.environments.discovery import (
    DISCOVERY_RAW_KIND,
    MECHANISM_OF_PROFILE,
    discovery_expectation,
    discovery_observation,
    discovery_report_of,
    materialization_signal_report,
    proof_gaps,
)
from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.frames.kinds import classify
from mission_control.application.signals.contracts import Signal
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.discovery import (
    DiscoveryExpectation,
    DiscoveryItem,
    DiscoveryReport,
    as_digest,
    discovery_gaps,
)
from mission_control.domain.execution.environment_preparation import (
    EnvironmentDeclaration,
    EnvironmentPreparation,
    ReadinessLevel,
    ReadinessMark,
    preparation_id,
    readiness_rank,
)
from mission_control.domain.execution.lanes import PreparedSession
from mission_control.domain.frames.contracts import FrameKind
from tests.fixtures.discovery_lanes import DISCOVERING_LANES, scenario
from tests.fixtures.discovery_lanes import Attempt as LaneAttempt
from tests.fixtures.lane_turns import cursor_binding, cursor_operation

AT = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
D = ReadinessLevel
OVERLAY = ".cursor/rules/mc-mission.mdc"
HOOKS = ".cursor/hooks.json"
OVERLAY_DIGEST = "sha256:" + "1" * 64
HOOKS_DIGEST = "sha256:" + "2" * 64
RECEIPT = "sha256:" + "3" * 64
HARNESS_EXECUTION = UUID("55555555-5555-4555-8555-555555555555")
SKILL = DiscoveryItem(kind="skill", name="agent-browser")
SERVER = DiscoveryItem(kind="mcp_server", name="mc-tavily")


def _expectation(mechanism: Any = "session_init", **changes: Any) -> DiscoveryExpectation:
    return DiscoveryExpectation.model_validate(
        {"mechanism": mechanism, "items": [SKILL, SERVER], **changes}
    )


def _report(
    lane: LaneProfile = LaneProfile.CLAUDE_AGENT_SDK,
    mechanism: Any = "session_init",
    **changes: Any,
) -> DiscoveryReport:
    return DiscoveryReport.model_validate(
        {
            "lane_profile": lane,
            "mechanism": mechanism,
            "items": [SKILL, SERVER, DiscoveryItem(kind="skill", name="repo-notes")],
            "source": "test",
            **changes,
        }
    )


# --- the contract --------------------------------------------------------------------------------


def test_a_report_proves_its_expectation_and_may_name_more() -> None:
    assert discovery_gaps(_expectation(), _report()) == ()


def test_a_report_short_of_its_expectation_names_every_gap() -> None:
    expectation = _expectation(
        "materialization_signal",
        digests={OVERLAY: OVERLAY_DIGEST, HOOKS: HOOKS_DIGEST, "AGENTS.md": RECEIPT},
    )
    report = _report(
        LaneProfile.CURSOR_CLOUD,
        "materialization_signal",
        items=[SKILL],
        digests={OVERLAY: None, HOOKS: RECEIPT},
    )
    assert discovery_gaps(expectation, report) == (
        "mcp_server mc-tavily was not reported loaded",
        f"{HOOKS} reads {RECEIPT}, not the placed {HOOKS_DIGEST}",
        f"{OVERLAY} is absent where the provider reads it",
        "AGENTS.md was not read",
    )
    assert discovery_gaps(_expectation(), _report(mechanism="app_server")) == (
        "the lane discovers through session_init, not app_server",
    )


def test_only_a_sha256_digest_reads_as_a_digest() -> None:
    assert as_digest(OVERLAY_DIGEST) == OVERLAY_DIGEST
    for value in (None, 7, "sha256:short", "md5:" + "1" * 64, OVERLAY_DIGEST.upper()):
        assert as_digest(value) is None


# --- expectations per lane -----------------------------------------------------------------------


def _receipt(lane: LaneProfile) -> LayeringReceipt:
    def item(kind: Any, name: str, origin: Any) -> DiscoveredItem:
        return DiscoveredItem(kind=kind, name=name, path=f"{kind}/{name}", origin=origin)

    return LayeringReceipt(
        lane_profile=lane,
        discovery=(
            item("instructions", "AGENTS.md", "repo"),
            item("instructions", "mission overlay", "mission"),
            item("skill", "repo-notes", "repo"),
            item("skill", "agent-browser", "mission"),
            item("subagent", "reviewer", "mission"),
            item("hook", "PreToolUse", "mission"),
            item("mcp_server", "mc-tavily", "mission"),
        ),
    )


@pytest.mark.parametrize(
    ("lane", "kinds"),
    [
        (LaneProfile.CLAUDE_AGENT_SDK, {"skill", "subagent", "mcp_server"}),
        (LaneProfile.CODEX, {"skill", "hook", "mcp_server"}),
        (LaneProfile.CURSOR_LOCAL, {"skill"}),
        (LaneProfile.CURSOR_CLOUD, {"skill"}),
    ],
)
def test_each_lane_expects_the_mission_items_its_mechanism_reports(
    lane: LaneProfile, kinds: set[str]
) -> None:
    placed = {OVERLAY: OVERLAY_DIGEST, HOOKS: HOOKS_DIGEST, ".mission/run.json": RECEIPT}
    expectation = discovery_expectation(lane, _receipt(lane), placed)
    assert expectation is not None and expectation.mechanism == MECHANISM_OF_PROFILE[lane]
    assert {item.kind for item in expectation.items} == kinds
    assert all(item.name != "repo-notes" for item in expectation.items), "repository items"
    files = {OVERLAY: OVERLAY_DIGEST, HOOKS: HOOKS_DIGEST}
    assert expectation.digests == (files if lane.value.startswith("cursor") else {})


def test_a_lane_without_a_mechanism_expects_nothing() -> None:
    for lane in (LaneProfile.CODEX_CLOUD, LaneProfile.DEEP_AGENTS):
        assert discovery_expectation(lane, _receipt(LaneProfile.CODEX), {}) is None


# --- the cursor_cloud signal and the frame -------------------------------------------------------


def _signal(data: dict[str, Any], kind: str = "materialization.observed") -> Signal:
    return Signal(signal_id="spool-2", type=kind, seq=2, data=data)


def test_the_materialization_signal_reads_as_a_report_and_bad_data_only_fails_it() -> None:
    report = materialization_signal_report(
        "cursor_cloud",
        _signal(
            {
                "files": {OVERLAY: OVERLAY_DIGEST, HOOKS: "not-a-digest", "x": None},
                "skills": ["agent-browser", 3, "", "x" * 300],
            }
        ),
    )
    assert report is not None and report.source == "signal:spool-2"
    assert report.items == (SKILL,)
    assert report.digests == {OVERLAY: OVERLAY_DIGEST, HOOKS: None, "x": None}
    assert materialization_signal_report("cursor_cloud", _signal({}, "session.started")) is None
    empty = materialization_signal_report("cursor_cloud", _signal({"files": [1], "skills": "a"}))
    assert empty is not None and empty.items == () and empty.digests == {}


@pytest.mark.parametrize("lane", list(LaneProfile))
def test_a_report_travels_as_a_status_frame_on_every_lane(lane: LaneProfile) -> None:
    report = _report()
    observation = discovery_observation(report, provider_key="discovery:s", native_session_ref="s")
    assert classify(lane, DISCOVERY_RAW_KIND, observation.body).kind is FrameKind.STATUS
    assert observation.kind is FrameKind.STATUS
    assert discovery_report_of(observation.raw_kind, observation.body) == report
    assert discovery_report_of("system.init", observation.body) is None
    assert discovery_report_of(DISCOVERY_RAW_KIND, {"schema_version": "other"}) is None


# --- the service ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Attempt:
    lane_profile: str
    request_scope: str = "mc/scope"
    run_key: str = "run-1"
    attempt_no: int = 1
    harness_execution_id: UUID = HARNESS_EXECUTION


def _stored(
    attempt: Attempt,
    reached: ReadinessLevel,
    expectation: DiscoveryExpectation | None,
    *,
    setup_pin: str | None = None,
) -> EnvironmentPreparation:
    declaration = EnvironmentDeclaration.of(attempt.lane_profile, {"setup_pin": setup_pin})
    record = EnvironmentPreparation(
        preparation_id=preparation_id(
            attempt.request_scope, attempt.harness_execution_id, attempt.attempt_no
        ),
        run_key=attempt.run_key,
        harness_execution_id=attempt.harness_execution_id,
        generation=attempt.attempt_no,
        lane_profile=declaration.lane_profile,
        binding_digest=RECEIPT,
        declaration=declaration,
        declaration_digest=declaration.digest,
        readiness=D.DECLARED,
        marks=(ReadinessMark(level=D.DECLARED, reached_at=AT, evidence_ref="binding"),),
        discovery=expectation,
    )
    for level in (D.RENDERED, D.DELIVERED, D.PREPARED):
        if readiness_rank(level) > readiness_rank(reached):
            break
        record = record.advanced(
            level,
            at=AT,
            evidence_ref=f"evidence:{level}",
            receipt_digest=RECEIPT if level is D.PREPARED else None,
        )
    return record


async def _service(
    record: EnvironmentPreparation, attempt: Attempt
) -> tuple[EnvironmentPreparationService, InMemoryEnvironmentPreparationRepository]:
    repository = InMemoryEnvironmentPreparationRepository()
    await repository.record(attempt.request_scope, record)
    return EnvironmentPreparationService(repository, clock=lambda: AT), repository


LOCAL_LANES = [
    ("claude_agent_sdk", "session_init"),
    ("codex", "app_server"),
    ("cursor_local", "setting_readback"),
]


@pytest.mark.parametrize(("lane", "mechanism"), LOCAL_LANES)
def test_a_prepared_local_lane_is_discovered_by_a_complete_report(
    lane: str, mechanism: str
) -> None:
    async def scenario() -> None:
        attempt = Attempt(lane)
        expectation = _expectation(mechanism)
        service, repository = await _service(_stored(attempt, D.PREPARED, expectation), attempt)
        report = _report(LaneProfile(lane), mechanism)
        outcome = await service.discovered(attempt, report, evidence_ref="frame:discovery:1")
        assert outcome.gaps == ()
        assert outcome.preparation is not None
        assert outcome.preparation.readiness is D.DISCOVERED
        mark = outcome.preparation.mark(D.DISCOVERED)
        assert mark is not None and mark.evidence_ref == "frame:discovery:1"
        assert outcome.preparation.receipt_digest == RECEIPT, "the prepare receipt stands"
        # The same proof again changes nothing; a hook frame still raises it to exercised.
        again = await service.discovered(attempt, report, evidence_ref="frame:discovery:2")
        assert again.preparation == outcome.preparation
        exercised = await service.observed(attempt, FrameKind.HOOK_INVOKED, evidence_ref="h")
        assert exercised is not None and exercised.readiness is D.EXERCISED
        (stored,) = repository.records.values()
        assert stored.mark(D.DISCOVERED) == mark

    asyncio.run(scenario())


def test_a_short_or_foreign_report_changes_nothing_and_says_why() -> None:
    async def scenario() -> None:
        attempt = Attempt("claude_agent_sdk")
        record = _stored(attempt, D.PREPARED, _expectation())
        service, _repository = await _service(record, attempt)
        short = await service.discovered(attempt, _report(items=[SKILL]), evidence_ref="f")
        assert short.preparation == record
        assert short.gaps == ("mcp_server mc-tavily was not reported loaded",)
        foreign = await service.discovered(
            attempt, _report(LaneProfile.CODEX, "app_server"), evidence_ref="f"
        )
        assert foreign.gaps == ("the report is about codex, not claude_agent_sdk",)
        unrecorded = Attempt("claude_agent_sdk", harness_execution_id=uuid4())
        missing = await service.discovered(unrecorded, _report(), evidence_ref="f")
        assert missing.preparation is None and missing.gaps

    asyncio.run(scenario())


def test_without_an_expectation_or_below_prepared_a_local_lane_is_not_discovered() -> None:
    attempt = Attempt("cursor_local")
    report = _report(LaneProfile.CURSOR_LOCAL, "setting_readback")
    unexpected = _stored(attempt, D.PREPARED, None)
    assert proof_gaps(unexpected, report) == ("the preparation records no discovery expectation",)
    delivered = _stored(attempt, D.DELIVERED, _expectation("setting_readback"))
    assert proof_gaps(delivered, report) == (
        "the environment is delivered; discovery follows preparation",
    )


@pytest.mark.parametrize(
    ("lane", "mechanism"),
    [
        ("cursor_cloud", "materialization_signal"),
        ("claude_managed", "api_readback"),
        ("codex_agents", "api_readback"),
    ],
)
def test_a_cloud_lane_is_prepared_and_discovered_by_one_provider_side_proof(
    lane: str, mechanism: str
) -> None:
    async def scenario() -> None:
        attempt = Attempt(lane)
        service, _repository = await _service(
            _stored(attempt, D.DELIVERED, _expectation(mechanism)), attempt
        )
        report = _report(LaneProfile(lane), mechanism)
        outcome = await service.discovered(attempt, report, evidence_ref="signal:spool-2")
        assert outcome.gaps == () and outcome.preparation is not None
        record = outcome.preparation
        assert record.readiness is D.DISCOVERED
        assert record.receipt_digest == report.digest
        prepared, discovered = record.mark(D.PREPARED), record.mark(D.DISCOVERED)
        assert prepared is not None and discovered is not None
        assert prepared.evidence_ref == discovered.evidence_ref == "signal:spool-2"

    asyncio.run(scenario())


def test_a_cloud_mission_layer_still_waits_for_its_receipt_signal() -> None:
    attempt = Attempt("cursor_cloud")
    record = _stored(
        attempt, D.DELIVERED, _expectation("materialization_signal"), setup_pin="kit/dev@1"
    )
    report = _report(LaneProfile.CURSOR_CLOUD, "materialization_signal")
    assert proof_gaps(record, report) == (
        "prepared: Environment Kit kit/dev@1 declares a mission layer whose receipt signal has "
        "not arrived",
    )
    # Once the mission layer's receipt prepared it, the same proof raises it to discovered.
    prepared = record.advanced(D.PREPARED, at=AT, evidence_ref="receipt", receipt_digest=RECEIPT)
    assert proof_gaps(prepared, report) == ()


def test_a_worker_side_mechanism_never_prepares_a_cloud_lane() -> None:
    attempt = Attempt("cursor_cloud")
    record = _stored(attempt, D.DELIVERED, _expectation("setting_readback"))
    report = _report(LaneProfile.CURSOR_CLOUD, "setting_readback")
    assert proof_gaps(record, report) == (
        "the environment is delivered; discovery follows preparation",
    )


def test_a_lost_write_is_lost_evidence_never_an_error() -> None:
    class Failing(InMemoryEnvironmentPreparationRepository):
        async def record(self, request_scope: str, preparation: Any) -> Any:
            raise ConnectionError("database unavailable")

    async def scenario() -> None:
        attempt = Attempt("claude_agent_sdk")
        repository = Failing()
        record = _stored(attempt, D.PREPARED, _expectation())
        repository.records[(attempt.request_scope, record.preparation_id)] = record
        service = EnvironmentPreparationService(repository, clock=lambda: AT)
        outcome = await service.discovered(attempt, _report(), evidence_ref="f")
        assert outcome.preparation is None
        assert outcome.gaps == ("the discovery proof was not recorded",)

    asyncio.run(scenario())


def test_prepare_records_the_expectation_the_proof_is_compared_with() -> None:
    operation = cursor_operation("cursor_cloud")
    expectation = _expectation("materialization_signal", digests={OVERLAY: OVERLAY_DIGEST})
    prepared = PreparedSession(
        lane_profile="cursor_cloud",
        harness_execution_id=str(uuid4()),
        generation=1,
        workspace_ref="branch:mc/run-1@" + "a" * 40,
        projection_digests={"rules_digest": OVERLAY_DIGEST},
        materialization_ref="a" * 40,
        discovery=expectation,
    )
    identity = LaneExecutionIdentity.of(operation, "cursor_cloud", 1)
    record = preparation_of(identity, cursor_binding("cursor_cloud"), prepared, at=AT)
    assert record.readiness is D.DELIVERED and record.discovery == expectation
    # A re-observation keeps the first expectation.
    assert record.merged(record).discovery == expectation


# --- acceptance: every lane with a mechanism reaches `discovered` --------------------------------


@pytest.mark.parametrize("lane", DISCOVERING_LANES)
async def test_every_discovering_lane_reaches_discovered_through_its_mechanism(
    lane: str, tmp_path: Path
) -> None:
    """The local lanes from `prepared`, cursor_cloud and both API lanes from `delivered`; the
    PostgreSQL proof is `tests/integration/postgres/test_environment_preparation.py`."""

    case = await scenario(lane, tmp_path)
    attempt = LaneAttempt(request_scope="mc/scope", lane_profile=lane)
    service = EnvironmentPreparationService(InMemoryEnvironmentPreparationRepository())
    started = await service.admit_start(attempt, case.binding, case.prepared)
    local = lane in {"claude_agent_sdk", "codex", "cursor_local"}
    assert started.readiness is (D.PREPARED if local else D.DELIVERED)

    outcome = await service.discovered(attempt, case.report, evidence_ref=f"proof:{lane}")

    assert outcome.gaps == ()
    assert outcome.preparation is not None
    assert outcome.preparation.readiness is D.DISCOVERED
