"""The database release rule is the one every consumer of the database applies (VER-S1).

The cases are the database contract repository's `release-check.cases.json`, mirrored under
`tests/fixtures/database_release`; each consumer runs them against its own port of
`scripts/database-release.mjs`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from tests.support.settings import isolated_settings
from tests.support.sibling_checkouts import AIDB_CHECKOUT_ENV, sibling_checkout

from mission_control.contracts.database_release import (
    CHECK_MODES,
    CHECK_VARIABLE,
    DatabaseReleaseDeclaration,
    check_mode,
    in_range,
    release_verdict,
)

ROOT = Path(__file__).resolve().parents[3]
CASES_FILE = "release-check.cases.json"
CASES_PATH = ROOT / "tests" / "fixtures" / "database_release" / CASES_FILE
CASES: dict[str, Any] = json.loads(CASES_PATH.read_text(encoding="utf-8"))
# The answer format the shared verdict cases are written for.
FORMAT = "ai-engineer-database-release/1"


def test_the_mirrored_cases_are_the_contract_repositorys_bytes() -> None:
    checkout = sibling_checkout(AIDB_CHECKOUT_ENV, "aiengineer/ai-engineer-db-contract")

    assert CASES_PATH.read_bytes() == (checkout / CASES_FILE).read_bytes()


def test_the_mirrored_cases_are_the_format_this_port_reads() -> None:
    assert CASES["format"] == "ai-engineer-release-check-cases/1"
    assert CASES["range"] and CASES["verdict"]


@pytest.mark.parametrize(
    "case", CASES["range"], ids=[f"{c['version']} in {c['range']}" for c in CASES["range"]]
)
def test_a_release_is_inside_or_outside_a_range(case: dict[str, Any]) -> None:
    assert in_range(case["version"], case["range"]) is case["in"]


@pytest.mark.parametrize("case", CASES["verdict"], ids=[c["name"] for c in CASES["verdict"]])
def test_the_verdict_on_what_the_database_answered(case: dict[str, Any]) -> None:
    verdict = release_verdict(case["observed"], case["range"], release_format=FORMAT)

    assert (verdict.verdict, verdict.start, verdict.warning) == (
        case["verdict"],
        case["start"],
        case["warning"],
    )
    assert verdict.range == case["range"]
    assert verdict.reason


def test_the_verdict_carries_the_release_and_state_it_judged() -> None:
    verdict = release_verdict(
        {"format": FORMAT, "release": "0.11.0", "state": "current"}, "0.12.0", release_format=FORMAT
    )

    assert (verdict.release, verdict.state) == ("0.11.0", "current")
    assert verdict.reason == "the database is release 0.11.0; this service works with 0.12.0"


def test_an_answer_that_is_not_an_object_is_no_answer() -> None:
    answers: list[Any] = ["0.12.0", ["0.12.0"], 12, {}]
    for answer in answers:
        verdict = release_verdict(answer, "0.12.0", release_format=FORMAT)

        assert (verdict.verdict, verdict.start) == ("unknown", False)


def test_a_release_or_range_that_is_not_one_is_an_error_not_a_verdict() -> None:
    with pytest.raises(ValueError, match="not a release version: 0.12"):
        release_verdict(
            {"format": FORMAT, "release": "0.12", "state": "current"},
            "0.12.0",
            release_format=FORMAT,
        )
    with pytest.raises(ValueError, match="not a release range"):
        in_range("0.12.0", "^0.12.0")
    with pytest.raises(ValueError, match="not a release range"):
        in_range("0.12.0", "0.12.0\n")


def test_the_mode_variable_and_its_values_are_the_shared_ones() -> None:
    assert CASES["mode"]["variable"] == CHECK_VARIABLE
    assert set(CASES["mode"]["values"]) == set(CHECK_MODES)
    assert check_mode({}) == "enforce"
    for mode in CHECK_MODES:
        assert check_mode({CHECK_VARIABLE: f" {mode.upper()} "}) == mode
    with pytest.raises(ValueError, match=f"{CHECK_VARIABLE} must be enforce, warn or off"):
        check_mode({CHECK_VARIABLE: "strict"})
    with pytest.raises(ValueError, match=f"{CHECK_VARIABLE} must be enforce, warn or off"):
        check_mode({CHECK_VARIABLE: ""})


def test_the_settings_read_the_mode_and_treat_a_blank_variable_as_unset() -> None:
    assert isolated_settings().aieng_db_release_check == "enforce"
    assert isolated_settings(aieng_db_release_check=" Warn ").aieng_db_release_check == "warn"
    assert isolated_settings(aieng_db_release_check="off").aieng_db_release_check == "off"
    # This repository's rule for a variable that is present but empty.
    assert isolated_settings(aieng_db_release_check="  ").aieng_db_release_check == "enforce"
    with pytest.raises(ValidationError, match=f"{CHECK_VARIABLE} must be enforce, warn or off"):
        isolated_settings(aieng_db_release_check="strict")


def test_the_settings_field_is_the_shared_variable_name() -> None:
    assert CHECK_VARIABLE.lower() in type(isolated_settings()).model_fields


@pytest.mark.parametrize("declared", ["0.12.0", ">=1.2.0 <2.0.0"])
def test_a_declaration_names_a_range_the_rule_reads(declared: str) -> None:
    assert DatabaseReleaseDeclaration(format=FORMAT, range=declared).range == declared


@pytest.mark.parametrize(
    ("declared", "problem"),
    [
        ("0.12", "not a release range"),
        ("^0.12.0", "not a release range"),
        (">=0.12.0", "not a release range"),
        (">=2.0.0 <1.0.0", "admits no release"),
        (">=1.0.0 <1.0.0", "admits no release"),
    ],
)
def test_a_declaration_with_another_range_is_refused(declared: str, problem: str) -> None:
    with pytest.raises(ValidationError, match=problem):
        DatabaseReleaseDeclaration(format=FORMAT, range=declared)
