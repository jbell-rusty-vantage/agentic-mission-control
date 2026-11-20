"""The database release rule every consumer of an application database applies (VER-S1, D-117).

A database that holds an application's contract states which release it is:
``api.database_release()`` returns ``{format, release, state, declared, observed, stamped_at,
stamped_by}``. Each service that works with that database states the range of releases it works
with and applies one rule to the answer before it serves. The authority is the database contract
repository (``scripts/database-release.mjs``: ``inRange``, ``releaseVerdict``, ``checkMode``);
this module is the Mission Control port and never relaxes it. Its shared cases
(``release-check.cases.json``) are mirrored under ``tests/fixtures/database_release`` and run in
``tests/unit/mission_control/test_database_release_rule.py``.

Which answer format and range an application works with is data: ``[database_release]`` in
``deployments/<app>/application.toml`` (:class:`DatabaseReleaseDeclaration`). Pure: no I/O and
no settings. Reading the bound database and refusing to start are
``bootstrap/common_installation.py``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

# The environment variable every consumer reads its mode from.
CHECK_VARIABLE: Final = "AIENG_DB_RELEASE_CHECK"
CheckMode = Literal["enforce", "warn", "off"]
CHECK_MODES: Final[tuple[CheckMode, ...]] = get_args(CheckMode)
RuleVerdict = Literal["unknown", "unstamped", "incompatible", "inconsistent", "ok"]

_VERSION: Final = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)")
_RANGE: Final = re.compile(r">=([0-9]+\.[0-9]+\.[0-9]+) <([0-9]+\.[0-9]+\.[0-9]+)")
# Why a release that is in range but not `current` still starts, by state.
_WARNINGS: Final[Mapping[str, str]] = {
    "ahead": "migrations were applied after the stamp (unreleased changes)",
    "component_drift": "a guest component differs from the version the release pins",
    "unverifiable": "the migration list could not be read, so the stamp is unchecked",
}


def _parts(version: object) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(str(version))
    if match is None:
        raise ValueError(f"not a release version: {version}")
    return int(match[1]), int(match[2]), int(match[3])


def compare_versions(a: object, b: object) -> int:
    """-1, 0 or 1: numeric comparison of two X.Y.Z versions."""

    x, y = _parts(a), _parts(b)
    return (x > y) - (x < y)


def _bounds(release_range: str) -> tuple[str, str] | None:
    """The lower and upper version of a ``>=A.B.C <D.E.F`` range; ``None`` for an exact one."""

    if _VERSION.fullmatch(release_range):
        return None
    match = _RANGE.fullmatch(release_range)
    if match is None:
        raise ValueError(f'not a release range: {release_range} (write X.Y.Z or ">=A.B.C <D.E.F")')
    return match[1], match[2]


def in_range(version: object, release_range: str) -> bool:
    """Whether a release is inside a consumer's range: an exact version, or ``>=A.B.C <D.E.F``."""

    bounds = _bounds(release_range)
    if bounds is None:
        return compare_versions(version, release_range) == 0
    lower, upper = bounds
    return compare_versions(version, lower) >= 0 and compare_versions(version, upper) < 0


@dataclass(frozen=True)
class ReleaseVerdict:
    """What the rule says about one answer for one range.

    ``start`` is whether a service in enforce mode starts; ``warning`` that it starts on a
    database that is not exactly the stamped release.
    """

    verdict: RuleVerdict
    start: bool
    warning: bool
    range: str
    release: str | None
    state: str | None
    reason: str


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def release_verdict(
    observed: Mapping[str, Any] | None, release_range: str, *, release_format: str
) -> ReleaseVerdict:
    """The verdict on what ``api.database_release()`` returned (``None`` when the database gave
    no answer) for a consumer's range and the answer format it works with.

    Raises ``ValueError`` when the answer's release is not a version, as the reference throws.
    """

    answer: Mapping[str, Any] = observed if isinstance(observed, Mapping) else {}
    release, state = answer.get("release"), answer.get("state")

    def verdict(name: RuleVerdict, reason: str, *, start: bool, warning: bool) -> ReleaseVerdict:
        return ReleaseVerdict(
            verdict=name,
            start=start,
            warning=warning,
            range=release_range,
            release=_text(release),
            state=_text(state),
            reason=reason,
        )

    def refuse(name: RuleVerdict, reason: str) -> ReleaseVerdict:
        return verdict(name, reason, start=False, warning=False)

    if answer.get("format") != release_format:
        return refuse(
            "unknown",
            "the database does not state a release (api.database_release() is missing or "
            "answered in another format)",
        )
    if release is None:
        return refuse("unstamped", "the database has never been stamped with a release")
    if not in_range(release, release_range):
        return refuse(
            "incompatible",
            f"the database is release {release}; this service works with {release_range}",
        )
    if state == "inconsistent":
        return refuse(
            "inconsistent",
            f"the database is stamped {release} but its migrations are behind that release",
        )
    if state == "current":
        return verdict("ok", f"the database is release {release}", start=True, warning=False)
    why = _WARNINGS.get(state, f"state {state}") if isinstance(state, str) else f"state {state}"
    return verdict("ok", f"the database is release {release}; {why}", start=True, warning=True)


def check_mode(environment: Mapping[str, str]) -> CheckMode:
    """enforce (default), warn or off, from ``AIENG_DB_RELEASE_CHECK``."""

    raw = environment.get(CHECK_VARIABLE)
    mode = ("enforce" if raw is None else str(raw)).strip().lower()
    for known in CHECK_MODES:
        if mode == known:
            return known
    raise ValueError(f"{CHECK_VARIABLE} must be enforce, warn or off (got {raw})")


def require_range(release_range: str) -> str:
    """``release_range`` when it is a range the rule reads and at least one release is inside
    it; ``ValueError`` otherwise. A declaration is checked once, when its file loads."""

    bounds = _bounds(release_range)
    if bounds is not None and compare_versions(*bounds) >= 0:
        raise ValueError(f"the release range {release_range} admits no release")
    return release_range


class DatabaseReleaseDeclaration(BaseModel):
    """``[database_release]`` of an application's profile file: the release of its database
    this Mission Control works with. An application that declares none is not checked."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # The `format` the database's answer carries; an answer in another format is `unknown`.
    format: str = Field(min_length=1, max_length=128)
    # An exact version (`X.Y.Z`) or `>=A.B.C <D.E.F`.
    range: str = Field(min_length=1, max_length=64)

    @field_validator("range")
    @classmethod
    def _a_release_range(cls, value: str) -> str:
        return require_range(value)


__all__ = [
    "CHECK_MODES",
    "CHECK_VARIABLE",
    "CheckMode",
    "DatabaseReleaseDeclaration",
    "ReleaseVerdict",
    "RuleVerdict",
    "check_mode",
    "compare_versions",
    "in_range",
    "release_verdict",
    "require_range",
]
