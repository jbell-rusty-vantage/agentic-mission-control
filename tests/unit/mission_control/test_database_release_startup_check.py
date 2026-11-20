"""Startup checks the release of the bound database against the one the application declares.

VER-S1: an application that declares no release is not checked and the database is not asked;
a bound database without the contract is `not_applicable`; otherwise the shared rule decides,
`enforce` refuses and `warn` starts. Readiness reports the outcome. The read of a real database
is proven in `tests/integration/postgres/test_database_release_check_postgres.py`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from tests.support.settings import isolated_settings

from mission_control.application.installations.registry import InstallationUnavailable
from mission_control.bootstrap.application_profiles import load_application_profile
from mission_control.bootstrap.common_installation import (
    NO_DATABASE_RELEASE_CHECK,
    CommonReadiness,
    DatabaseReleaseCheck,
    DatabaseReleaseObservation,
    DatabaseReleaseStatus,
    check_database_release,
    database_release_report,
)
from mission_control.bootstrap.composition import database_release_check
from mission_control.contracts.database_release import CheckMode, DatabaseReleaseDeclaration

DEPLOYMENTS = Path(__file__).resolve().parents[3] / "deployments"
FORMAT = "ai-engineer-database-release/1"
DECLARED = DatabaseReleaseDeclaration(format=FORMAT, range="0.12.0")
LOGGER = "mission_control.bootstrap.common_installation"


def answering(
    release: str | None, state: str, *, release_format: str = FORMAT
) -> DatabaseReleaseObservation:
    return DatabaseReleaseObservation(
        contract_present=True,
        answer={"format": release_format, "release": release, "state": state},
    )


async def check(
    observation: DatabaseReleaseObservation,
    *,
    mode: CheckMode = "enforce",
    declared: DatabaseReleaseDeclaration | None = DECLARED,
) -> DatabaseReleaseStatus:
    async def observe() -> DatabaseReleaseObservation:
        return observation

    return await check_database_release(DatabaseReleaseCheck(declared, mode), observe)


async def never_asked() -> DatabaseReleaseObservation:
    pytest.fail("the database was asked for its release")


async def test_an_application_that_declares_no_release_never_asks_the_database() -> None:
    status = await check_database_release(NO_DATABASE_RELEASE_CHECK, never_asked)

    assert status.verdict == "not_declared"
    assert status.report() == {
        "declared_range": None,
        "release": None,
        "state": None,
        "verdict": "not_declared",
        "mode": "enforce",
    }


async def test_mode_off_never_asks_the_database(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        status = await check_database_release(DatabaseReleaseCheck(DECLARED, "off"), never_asked)

    assert (status.verdict, status.declared_range, status.mode) == ("not_checked", "0.12.0", "off")
    assert "database release check is off" in caplog.text


@pytest.mark.parametrize("mode", ["enforce", "warn"])
async def test_a_database_without_the_contract_is_not_applicable_and_starts(
    mode: CheckMode,
) -> None:
    status = await check(DatabaseReleaseObservation(contract_present=False), mode=mode)

    assert (status.verdict, status.release, status.state) == ("not_applicable", None, None)
    assert status.declared_range == "0.12.0"
    assert "no api schema" in status.reason


async def test_the_declared_release_as_stamped_starts() -> None:
    status = await check(answering("0.12.0", "current"))

    assert status.report() == {
        "declared_range": "0.12.0",
        "release": "0.12.0",
        "state": "current",
        "verdict": "ok",
        "mode": "enforce",
    }
    assert status.warning is False


@pytest.mark.parametrize("state", ["ahead", "component_drift", "unverifiable"])
async def test_a_release_in_range_that_is_not_current_starts_with_a_logged_warning(
    state: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        status = await check(answering("0.12.0", state))

    assert (status.verdict, status.state, status.warning) == ("ok", state, True)
    assert "the database is release 0.12.0;" in caplog.text


async def test_another_release_is_refused_in_enforce_mode() -> None:
    with pytest.raises(
        InstallationUnavailable,
        match="database release is incompatible: the database is release 0.11.0; "
        "this service works with 0.12.0",
    ):
        await check(answering("0.11.0", "current"))


async def test_another_release_starts_in_warn_mode_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        status = await check(answering("0.11.0", "current"), mode="warn")

    assert status.report() == {
        "declared_range": "0.12.0",
        "release": "0.11.0",
        "state": "current",
        "verdict": "incompatible",
        "mode": "warn",
    }
    assert "database release is incompatible" in caplog.text
    assert "starting anyway" in caplog.text


@pytest.mark.parametrize(
    ("observation", "verdict"),
    [
        (answering(None, "unstamped"), "unstamped"),
        (answering("0.12.0", "inconsistent"), "inconsistent"),
        (answering("0.12.0", "current", release_format="something-else/9"), "unknown"),
        (DatabaseReleaseObservation(contract_present=True), "unknown"),
    ],
    ids=["never stamped", "behind its stamp", "another format", "no answer"],
)
async def test_every_verdict_that_does_not_start_is_refused_in_enforce_and_reported_in_warn(
    observation: DatabaseReleaseObservation, verdict: str
) -> None:
    with pytest.raises(InstallationUnavailable, match=f"database release is {verdict}: "):
        await check(observation)

    assert (await check(observation, mode="warn")).verdict == verdict


async def test_a_database_with_the_contract_but_no_answer_says_why() -> None:
    silent = DatabaseReleaseObservation(
        contract_present=True,
        silence="the database holds the api schema but no api.database_release() function",
    )

    with pytest.raises(
        InstallationUnavailable,
        match=r"database release is unknown: the database holds the api schema but no "
        r"api\.database_release\(\) function",
    ):
        await check(silent)


async def test_an_answer_whose_release_is_not_a_version_states_no_release() -> None:
    malformed = answering("0.12", "current")

    with pytest.raises(InstallationUnavailable, match="not a release version: 0.12"):
        await check(malformed)

    assert (await check(malformed, mode="warn")).verdict == "unknown"


def readiness(release: DatabaseReleaseStatus, **overrides: Any) -> CommonReadiness:
    values: dict[str, Any] = {
        "storage_mode": "production_common",
        "database_name": "postgres",
        "component_version": "1.16.0",
        "applied_migrations": frozenset({"0001_foundation"}),
        "schema_fingerprint": "sha256:" + "0" * 64,
        "pool_role": "mcl_runtime",
        "production_ready": True,
        "database_release": release,
    }
    return CommonReadiness(**{**values, **overrides})


async def test_readiness_reports_one_database_release_per_bound_database() -> None:
    stamped = await check(answering("0.12.0", "ahead"))
    undeclared = await check_database_release(NO_DATABASE_RELEASE_CHECK, never_asked)

    report = database_release_report(
        # Two tenants of one installation share its database, then another application.
        [readiness(stamped), readiness(stamped, pool_role="other"), readiness(undeclared)]
    )

    assert report == [
        {
            "declared_range": "0.12.0",
            "release": "0.12.0",
            "state": "ahead",
            "verdict": "ok",
            "mode": "enforce",
        },
        {
            "declared_range": None,
            "release": None,
            "state": None,
            "verdict": "not_declared",
            "mode": "enforce",
        },
    ]
    assert database_release_report([]) == []


def test_the_profiles_declare_the_release_as_data() -> None:
    declared = load_application_profile(DEPLOYMENTS, "ai-engineer").database_release

    assert declared == DatabaseReleaseDeclaration(format=FORMAT, range="0.12.0")
    assert load_application_profile(DEPLOYMENTS, "biotech").database_release is None


def test_startup_takes_the_declaration_from_the_profile_and_the_mode_from_the_settings() -> None:
    settings = isolated_settings(aieng_db_release_check="warn")

    assert database_release_check(settings, "ai-engineer") == DatabaseReleaseCheck(
        DatabaseReleaseDeclaration(format=FORMAT, range="0.12.0"), "warn"
    )
    assert database_release_check(settings, "biotech") == DatabaseReleaseCheck(None, "warn")
    assert database_release_check(isolated_settings(), "biotech") == NO_DATABASE_RELEASE_CHECK


def test_a_profile_that_does_not_load_refuses_startup(tmp_path: Path) -> None:
    settings = isolated_settings(mission_control_deployments_root=tmp_path)

    with pytest.raises(InstallationUnavailable, match="declares is unreadable"):
        database_release_check(settings, "ai-engineer")


def test_a_declaration_the_rule_cannot_read_is_refused_when_the_profile_loads(
    tmp_path: Path,
) -> None:
    source = (DEPLOYMENTS / "ai-engineer" / "application.toml").read_text(encoding="utf-8")
    copied = tmp_path / "ai-engineer" / "application.toml"
    copied.parent.mkdir()
    copied.write_text(source.replace('range = "0.12.0"', 'range = "0.12"'), encoding="utf-8")
    settings = isolated_settings(mission_control_deployments_root=tmp_path)

    with pytest.raises(InstallationUnavailable, match="not a release range: 0.12"):
        database_release_check(settings, "ai-engineer")
