"""MO-44: watcher conditions are the closed ADR-0010 AST: parsed once, evaluated totally,
never executed as code."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from mission_control.domain.programs.watcher_conditions import (
    ConditionSyntaxError,
    WatcherCondition,
    evaluate_condition,
    parse_condition,
)

CONTEXT: dict[str, Any] = {
    "event": {
        "conclusion": "failure",
        "head_branch": "mc/run-1/fix",
        "attempt": 3,
        "ratio": 0.25,
        "labels": ["ci", "red"],
        "flag": True,
        "nested": {"name": "inner"},
        "nothing": None,
    },
    "run": {"phase": "active", "branch_prefix": "mc/run-1/", "version": 7},
    "unit": {"key": "build"},
    "watcher": {"id": "ci-red-fix", "fires": 1},
}


def holds(text: str, context: dict[str, Any] = CONTEXT) -> bool:
    return evaluate_condition(parse_condition(text), context)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("event.conclusion == 'failure'", True),
        ('event.conclusion != "failure"', False),
        (
            "event.conclusion == 'failure' and startswith(event.head_branch, run.branch_prefix)",
            True,
        ),
        ("event.conclusion == 'success' or run.phase == 'active'", True),
        ("not (event.conclusion == 'failure')", False),
        ("event.attempt >= 3 and event.attempt < 4", True),
        ("event.ratio == 0.25 and event.ratio > 0.2", True),
        ("event.attempt == 3.0", True),  # numbers compare as exact decimals
        ("event.flag == true and event.nothing == null", True),
        ("event.flag == 1", False),  # a boolean is never a number
        ("event.conclusion in ['failure', 'cancelled']", True),
        ("event.conclusion not in ['failure']", False),
        ("'red' in event.labels", True),
        ("event.nested.name == 'inner' and unit.key == 'build'", True),
        ("exists(event.nested.name) and not exists(event.missing)", True),
        ("exists(event.nothing)", False),
        ("watcher.fires < 3 and run.version > 6", True),
    ],
)
def test_conditions_evaluate_over_event_run_unit_and_watcher(text: str, expected: bool) -> None:
    assert holds(text) is expected


def test_evaluation_is_total_missing_paths_read_null_and_mismatches_are_false() -> None:
    assert holds("event.missing == null")
    assert not holds("event.missing == 'x'")
    assert not holds("event.missing > 1")  # ordering needs two numbers or two strings
    assert not holds("event.conclusion > 1")
    assert not holds("event.attempt in event.conclusion")  # `in` needs a list
    assert not holds("event.attempt not in event.conclusion")
    assert not holds("startswith(event.attempt, 'x')")
    assert holds("event.conclusion > 'a'")  # strings order lexically
    assert not holds("event.nested.name.deeper == 'x'")


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os').system('rm -rf /')",
        "event.conclusion.upper() == 'FAILURE'",
        "len(event.labels) > 1",
        "os.environ == 'x'",
        "event.conclusion",  # a bare value is not a condition
        "event['conclusion'] == 'x'",
        "event.conclusion == 'failure' and",
        "event.conclusion = 'failure'",
        "lambda: True",
        "exists('literal')",
        "event.a in [event.b]",
        "1e5 == event.attempt",
        "'a\\nb' == event.x",
        "",
    ],
)
def test_anything_outside_the_closed_grammar_is_a_pointed_syntax_error(text: str) -> None:
    with pytest.raises(ConditionSyntaxError):
        parse_condition(text)


def test_the_parsed_tree_is_typed_closed_and_round_trips() -> None:
    condition = parse_condition(
        "event.conclusion == 'failure' and (event.attempt > 2 or event.flag == true)"
    )
    assert condition.op == "all"
    assert [item.op for item in condition.operands] == ["eq", "any"]
    assert condition.paths() == ("event.conclusion", "event.attempt", "event.flag")
    restored = WatcherCondition.model_validate_json(condition.model_dump_json())
    assert restored == condition
    number = parse_condition("event.ratio == 0.25").values[1]
    assert (number.kind, number.text) == ("number", "0.25")
    assert evaluate_condition(restored, CONTEXT)
    assert evaluate_condition(
        parse_condition("event.amount == 12.50"), {"event": {"amount": Decimal("12.5")}}
    )


def test_bounds_on_size_and_nesting() -> None:
    deep = "(" * 20 + "event.a == 1" + ")" * 20
    with pytest.raises(ConditionSyntaxError, match="nests at most"):
        parse_condition(deep)
    wide = " or ".join(f"event.a == {index}" for index in range(70))
    with pytest.raises(ConditionSyntaxError, match="at most 64 nodes"):
        parse_condition(wide)
    with pytest.raises(ConditionSyntaxError, match="at most 2048 characters"):
        parse_condition("event.a == '" + "x" * 2100 + "'")
    # Depth is refused before descending: a text far past the bound (yet under 2048
    # characters) is a syntax error, never a RecursionError.
    for levels in (300, 1000):
        with pytest.raises(ConditionSyntaxError, match="nests at most"):
            parse_condition("(" * levels + "event.a == 1" + ")" * levels)
    with pytest.raises(ConditionSyntaxError, match="nests at most"):
        parse_condition("not " * 400 + "event.a == 1")


def test_malformed_trees_are_refused_at_validation() -> None:
    with pytest.raises(ValueError, match="combines conditions only"):
        WatcherCondition.model_validate({"op": "all", "values": [{"kind": "null"}]})
    with pytest.raises(ValueError, match="not rooted"):
        WatcherCondition.model_validate(
            {"op": "exists", "values": [{"kind": "path", "text": "os.environ"}]}
        )
    with pytest.raises(ValueError, match="eq takes 2"):
        WatcherCondition.model_validate({"op": "eq", "values": [{"kind": "null"}]})
