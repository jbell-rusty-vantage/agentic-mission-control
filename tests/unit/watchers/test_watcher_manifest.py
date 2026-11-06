"""MO-44: `controls.watchers` and `controls.notifications` in mission/v2, `event_wait` stages,
and their compilation into watcher descriptors (SPEC-04 §5.1-5.2)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, get_args

import pytest

from mission_control.application.watchers.service import run_facts
from mission_control.contracts.contracts import MissionInspection
from mission_control.domain.authoring.contracts import StageGraphBlueprint
from mission_control.domain.authoring.manifest import (
    ManifestRejected,
    load_manifest_yaml,
)
from mission_control.domain.authoring.manifest_lowering import lower_mission
from mission_control.domain.authoring.manifest_v2 import parse_manifest_any
from mission_control.domain.authoring.mission_definition import (
    MissionDefinition,
    manifest_to_definitions,
)
from mission_control.domain.authoring.mission_watchers import compile_mission_watchers
from mission_control.domain.policies.contracts import RunOutcome, RunPhase
from mission_control.domain.programs.watchers import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_FIRES,
    DEFAULT_RATE,
    RUN_FACTS,
    RUN_LIFECYCLES,
    RUN_OUTCOMES,
    RUN_PHASES,
    WAIT_CONDITION_PREFIX,
    WatcherLimits,
    WatcherSpec,
    compile_watcher,
)
from tests.unit.watchers.fakes import RunView

ROOT = Path(__file__).resolve().parents[3]
MINIMAL = ROOT / "tests/fixtures/manifests/minimal-stage-graph.yml"

CI_RED_FIX = {
    "id": "ci-red-fix",
    "on": {
        "signal": "github.check_suite.completed",
        "where": "event.conclusion == 'failure' and "
        "startswith(event.head_branch, run.branch_prefix)",
    },
    "then": [{"instruct": {"text": "CI is red; fix it.", "include": ["event.summary"]}}],
    "limits": {"max_fires": 3, "min_interval": "10m"},
}
STALLED = {
    "id": "stalled",
    "on": {"absence": {"of": ["frame", "signal"], "for": "20m"}, "while": "run.phase == 'active'"},
    "then": [{"notify": {"kind": "blocked", "text": "No progress for 20 minutes"}}, {"probe": {}}],
    "limits": {"max_fires": 2},
}


def v1() -> dict[str, Any]:
    return load_manifest_yaml(MINIMAL.read_text(encoding="utf-8"))


def v2(**controls: Any) -> dict[str, Any]:
    document = copy.deepcopy(v1())
    document["manifest"] = "mission/v2"
    document["mission"]["controls"].update(controls)
    return document


def definition(document: dict[str, Any]) -> MissionDefinition:
    (item,) = manifest_to_definitions(parse_manifest_any(document), document)
    return item


def issues(document: dict[str, Any]) -> tuple[set[str], set[str]]:
    manifest = parse_manifest_any(document)
    ((pointer, block),) = manifest.mission_blocks()
    compiled = compile_mission_watchers(block, pointer)
    return (
        {item.reason or "" for item in compiled.blockers},
        {item.reason or "" for item in compiled.warnings},
    )


def rejected(document: dict[str, Any]) -> str:
    with pytest.raises(ManifestRejected) as error:
        parse_manifest_any(document)
    return " ".join(f"{item.pointer} {item.message}" for item in error.value.issues)


def test_inline_watchers_compile_to_descriptors_with_every_boundary_resolved() -> None:
    document = v2(
        commands_allowed=["pause", "resume", "cancel", "queue_instruction"],
        watchers=[CI_RED_FIX, STALLED],
    )
    watchers = definition(document).policies.watchers
    ci, stalled = watchers
    assert (ci.watcher_id, ci.origin, ci.trigger.kind) == ("ci-red-fix", "manifest", "signal")
    assert ci.pointer == "/mission/controls/watchers/0"
    assert ci.where is not None and ci.where.op == "all"
    bounds = ci.boundaries
    assert (bounds.max_fires, bounds.min_interval_seconds) == (3, 600)
    assert (bounds.rate_count, bounds.rate_window_seconds) == DEFAULT_RATE
    assert bounds.max_depth == DEFAULT_MAX_DEPTH
    assert bounds.min_trust == "provider_signed"  # instruct drives the run
    assert stalled.trigger.absence_of == ("frame", "signal") and stalled.trigger.seconds == 1200
    assert stalled.boundaries.min_trust == "environment_key"
    assert stalled.active_while is not None
    assert issues(document) == (set(), set())


@pytest.mark.parametrize(
    ("watcher", "message"),
    [
        ({**CI_RED_FIX, "on": {"signal": "x.y", "event": "run.completed"}}, "exactly one of"),
        (
            {**STALLED, "on": {"absence": {"of": ["frame"], "for": "1m"}, "where": "event.a == 1"}},
            "use while",
        ),
        ({**CI_RED_FIX, "on": {"signal": "x.y", "where": "event.x()"}}, "condition"),
        ({**CI_RED_FIX, "then": [{"launch": {"mission_ref": "missions/ks-ingest@2"}}]}, "launch"),
        ({**CI_RED_FIX, "then": [{"notify": {"kind": "blocked"}, "probe": {}}]}, "exactly one of"),
        (
            {**CI_RED_FIX, "then": [{"instruct": {"text": "x", "text_ref": "prompts/x.md"}}]},
            "text_ref",
        ),
        ({**CI_RED_FIX, "limits": {"rate": "ten per hour"}}, "rate"),
        ({**CI_RED_FIX, "limits": {"min_trust": "environment_key"}}, "min_trust"),
        ({"id": "pinned", "pin": "stall-detector@1"}, "sha256"),
        ({"id": "both", "pin": "stall-detector@latest", "then": [{"probe": {}}]}, "template"),
        ({"id": "neither"}, "declares on and then"),
    ],
)
def test_malformed_watchers_are_pointed_schema_errors(
    watcher: dict[str, Any], message: str
) -> None:
    assert message in rejected(v2(watchers=[watcher]))


def test_grants_waits_budget_and_ids_are_checked_against_the_mission() -> None:
    document = v2(
        commands_allowed=["pause", "resume"],
        watchers=[
            CI_RED_FIX,  # queue_instruction is not granted
            {**STALLED, "then": [{"satisfy_wait": {"node": "synthesize"}}]},  # not an event_wait
            {**STALLED, "id": "stalled-2", "limits": {"budget": {"tokens": 5_000_000}}},
            {**STALLED, "id": "stalled-2"},
        ],
    )
    blockers, _ = issues(document)
    assert blockers == {
        "action_not_granted",
        "unknown_wait",
        "widens_authority",
        "duplicate_watcher",
    }


def test_notifications_are_sugar_for_notify_watchers_and_mcp_is_rejected_in_v2() -> None:
    document = v2(notifications={"on": ["run.completed", "blocked"], "channel": "inbox"})
    watchers = definition(document).policies.watchers
    assert [(item.watcher_id, item.trigger.name) for item in watchers] == [
        ("notifications:0:0", "run.completed"),
        ("notifications:1:0", "command.in_doubt"),
        ("notifications:1:1", "human_task.expired"),
        ("notifications:1:2", "subscription.dead_lettered"),
    ]
    assert {item.actions[0].notify.kind for item in watchers if item.actions[0].notify} == {
        "terminal_result",
        "blocked",
    }
    assert definition(document).policies.notifications is None  # consumed, not stored
    assert "channel" in rejected(v2(notifications={"on": ["run.completed"], "channel": "mcp"}))
    assert "neither an event type" in rejected(v2(notifications={"on": ["completion"]}))
    assert "channel" in rejected(
        v2(subscriptions=[{"events": ["run.completed"], "channel": "mcp"}])
    )


def test_notifications_naming_output_attention_events_compile_as_before_wi19() -> None:
    """WI-19 journals output/transfer attention events and the inbox notifies them, but authored
    `notifications` sugar compiles exactly as at base eae4194e: the definition digest computed
    there (`progress` notify kinds) is pinned here."""

    document = v2(
        notifications={"on": ["output.fulfilled", "transfer.delivery_refused"], "channel": "inbox"}
    )
    item = definition(document)
    assert [(w.watcher_id, w.actions[0].notify.kind) for w in item.policies.watchers] == [
        ("notifications:0:0", "progress"),
        ("notifications:1:0", "progress"),
    ]
    assert item.digest == (
        "sha256:6862c48a2a1aee7a2dff459a317f9feba08267d7b6b5217dddc9287d7158ad40"
    )


def test_v1_parses_unchanged_and_compile_warns_about_its_unconsumed_fields() -> None:
    document = v1()
    document["mission"]["controls"]["notifications"] = {
        "on": ["human_task", "completion"],
        "channel": "inbox",
    }
    document["mission"]["controls"]["subscriptions"].append(
        {"events": ["run.completed"], "channel": "mcp"}
    )
    item = definition(document)
    assert item.policies.watchers == ()
    assert item.policies.notifications is not None
    assert issues(document) == (set(), {"notifications_unconsumed", "mcp_channel_undelivered"})
    # A definition without watchers keeps its exact digest (the field is additive).
    assert "watchers" not in item.policies.model_dump(mode="json")


def event_wait_document(**node: Any) -> dict[str, Any]:
    document = v2()
    nodes = document["mission"]["program"]["nodes"]
    nodes.insert(
        1,
        {
            "key": "await-merge",
            "behavior": "event_wait",
            "event_type": "github.pull_request.merged",
            "match": {"base": "main", "merged": True},
            **node,
        },
    )
    nodes[2]["depends_on"] = ["collect", "await-merge"]
    return document


def test_an_event_wait_stage_holds_on_a_declared_wait_released_by_its_implied_watcher() -> None:
    item = definition(event_wait_document())
    (implied,) = item.policies.watchers
    assert (implied.watcher_id, implied.origin) == ("event_wait:await-merge", "event_wait")
    assert implied.trigger.name == "github.pull_request.merged"
    assert implied.where is not None and [value.op for value in implied.where.operands] == [
        "eq",
        "eq",
    ]
    (action,) = implied.actions
    assert action.satisfy_wait is not None and action.satisfy_wait.node == "await-merge"
    assert implied.boundaries.max_fires == 1
    blueprint = lower_mission(item).blueprint
    assert isinstance(blueprint, StageGraphBlueprint)
    assert {(wait.scope_id, wait.wait_id) for wait in blueprint.waits} == {
        ("await-merge", "await-merge")
    }
    assert WAIT_CONDITION_PREFIX == "stagegraph-wait:"
    # A satisfy_wait action may name it; rearm and nested matches are refused, timeouts warned.
    assert issues(event_wait_document()) == (set(), set())
    granted = event_wait_document()
    granted["mission"]["controls"]["commands_allowed"].append("satisfy_wait")
    granted["mission"]["controls"]["watchers"] = [
        {**STALLED, "then": [{"satisfy_wait": {"node": "await-merge"}}]}
    ]
    assert issues(granted) == (set(), set())
    assert issues(event_wait_document(mode={"rearm": {}}))[0] == {"event_wait_rearm"}
    assert issues(event_wait_document(match={"pr": {"number": 1}}))[0] == {"event_wait_match"}
    assert issues(event_wait_document(timeout="1h"))[1] == {"event_wait_timeout_unenforced"}


def test_a_pinning_entry_may_only_narrow_its_template() -> None:
    template = WatcherSpec.model_validate(
        {
            "on": {"absence": {"of": ["frame"], "for": "20m"}},
            "then": [{"notify": {"kind": "blocked"}}],
            "limits": {"max_fires": 5, "rate": "6/h", "min_interval": "5m"},
        }
    )

    def pinned(**limits: Any) -> Any:
        return compile_watcher(
            template,
            watcher_id="stall",
            origin="catalog",
            pointer="/mission/controls/watchers/0",
            template="stall-detector@1#sha256:" + "a" * 64,
            overrides=WatcherLimits.model_validate(limits),
        )

    narrowed = pinned(max_fires=2, rate="2/h", min_interval="10m")
    assert narrowed.boundaries.max_fires == 2 and narrowed.boundaries.rate_count == 2
    assert narrowed.template is not None and narrowed.origin == "catalog"
    for widening, message in (
        ({"max_fires": 9}, "widens"),
        ({"rate": "100/h"}, "widens"),
        ({"min_interval": "1m"}, "shortens"),
    ):
        with pytest.raises(ValueError, match=message):
            pinned(**widening)
    assert pinned().boundaries.max_fires == 5
    defaults = compile_watcher(
        WatcherSpec.model_validate(
            {"on": {"event": "run.completed"}, "then": [{"notify": {"kind": "terminal_result"}}]}
        ),
        watcher_id="done",
        origin="manifest",
        pointer="/p",
    )
    assert defaults.boundaries.max_fires == DEFAULT_MAX_FIRES


@pytest.mark.parametrize(
    ("condition", "message"),
    [
        ("run.phase == 'executing'", "run.phase is never 'executing'"),
        ("run.lifecycle in ['running', 'done']", "run.lifecycle is never 'done'"),
        ("'stopped' != run.outcome", "run.outcome is never 'stopped'"),
        ("startswith(event.head_branch, run.branch)", "run.branch is not a run fact"),
        ("watcher.count < 2", "watcher.count is not a watcher fact"),
    ],
)
def test_conditions_name_only_facts_and_values_the_evaluator_provides(
    condition: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        WatcherSpec.model_validate(
            {"on": {"event": "run.completed", "where": condition}, "then": [{"probe": {}}]}
        )


def test_the_fact_vocabulary_is_the_run_control_and_inspection_vocabulary() -> None:
    assert {item.value for item in RunPhase} == RUN_PHASES
    assert {item.value for item in RunOutcome} == RUN_OUTCOMES
    assert set(get_args(MissionInspection.model_fields["lifecycle"].annotation)) == RUN_LIFECYCLES
    assert set(run_facts("run-1", RunView())) == set(RUN_FACTS)
