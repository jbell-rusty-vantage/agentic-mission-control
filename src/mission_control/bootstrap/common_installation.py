"""Read-only verification of an installed common mission_control component.

Readiness requires the persisted installation identity, the complete attested
release, this build's writer compatibility and correctly restricted pool roles.
Missing or mismatched evidence fails closed; there is no transitional fallback.

The same inspection checks the release of the bound database when the application declares
the one it works with (VER-S1, D-117): the shared rule of ``contracts/database_release.py``
decides, and a database on another release refuses startup the way a differing component does.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

import asyncpg

from mission_control.application.installations.registry import (
    ApplicationBinding,
    InstallationUnavailable,
)
from mission_control.contracts.database_release import (
    CHECK_VARIABLE,
    CheckMode,
    DatabaseReleaseDeclaration,
    release_verdict,
)

_LOG = logging.getLogger(__name__)

WRITER_VERSION = "mission-control-runtime/1"
READER_VERSION = "mission-control-runtime/1"
# Migrations this build's runtime reads directly (W1 D33). A pinned release without any of them is
# refused at startup instead of composing and failing later inside activities. Maintain with the
# code that reads them; a unit test keeps every key inside the newest built release.
REQUIRED_MIGRATIONS = frozenset(
    {
        # adapters/postgres/frames/retention.py calls expire_workspace_closures (1.12.0)
        "0070_workspace_closure",
        # bootstrap/nested_programs.py records mission_control.nested_activation (1.13.0)
        "0071_nested_program_activations",
        # adapters/postgres/knowledge/use_decisions.py reads invocation_ref (1.13.0)
        "0072_native_plan_decisions",
    }
)
CAPABILITY_ROLES = (
    "mission_control_runtime",
    "mission_control_family_writer",
    "mission_control_catalog_writer",
    "mission_control_outbox_worker",
    "mission_control_readonly",
)
# Required release tables; a missing one means the component is not installed.
REQUIRED_TABLES = frozenset(
    {
        "application_installation",
        "component_release",
        "release_attestation",
        "tenant",
        "mission",
        "mission_run",
        "request_receipt",
        "outbox",
    }
)


def _semver(version: str) -> tuple[int, int, int] | None:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    return int(parts[0]), int(parts[1]), int(parts[2])


def receipts_belong_to_release(receipt_versions: set[str], required: str) -> bool:
    """Whether migration receipts describe an installation of ``required``.

    An installation upgraded in place keeps the receipts of the earlier releases it applied
    (`mission-db` admits an upgrade only from a compatible previous fingerprint and attests
    the new version after verifying the result), so receipts of the required version or of
    an earlier semantic version are its own. Non-semantic versions must match exactly.
    """

    wanted = _semver(required)
    if wanted is None:
        return receipt_versions <= {required}
    for version in receipt_versions:
        parsed = _semver(version)
        if parsed is None or parsed > wanted:
            return False
    return True


# The shared rule's verdicts, and three outcomes that are Mission Control's own: the application
# declares no release, the check is off, and the bound database does not hold the contract.
DatabaseReleaseVerdict = Literal[
    "not_declared",
    "not_checked",
    "not_applicable",
    "unknown",
    "unstamped",
    "incompatible",
    "inconsistent",
    "ok",
]


@dataclass(frozen=True)
class DatabaseReleaseCheck:
    """What startup checks the bound database against: the release the application declares
    (none: no check) and this process's mode (``AIENG_DB_RELEASE_CHECK``)."""

    declared: DatabaseReleaseDeclaration | None = None
    mode: CheckMode = "enforce"


NO_DATABASE_RELEASE_CHECK = DatabaseReleaseCheck()


@dataclass(frozen=True)
class DatabaseReleaseObservation:
    """What the bound database said when asked which release it is."""

    # Whether the database holds the application's database contract (its `api` schema) at all.
    contract_present: bool
    # What `api.database_release()` returned; None when the database gave no answer.
    answer: Mapping[str, Any] | None = None
    # Why there is no answer, in plain words.
    silence: str | None = None


@dataclass(frozen=True)
class DatabaseReleaseStatus:
    """The outcome of the check on one bound database; readiness reports it."""

    declared_range: str | None
    release: str | None
    state: str | None
    verdict: DatabaseReleaseVerdict
    mode: CheckMode
    warning: bool
    reason: str

    def report(self) -> dict[str, str | None]:
        return {
            "declared_range": self.declared_range,
            "release": self.release,
            "state": self.state,
            "verdict": self.verdict,
            "mode": self.mode,
        }


@dataclass(frozen=True)
class CommonReadiness:
    storage_mode: Literal["production_common"]
    database_name: str
    component_version: str
    applied_migrations: frozenset[str]
    schema_fingerprint: str
    pool_role: str
    production_ready: bool
    database_release: DatabaseReleaseStatus


async def read_database_release(connection: asyncpg.Connection) -> DatabaseReleaseObservation:
    """Ask the bound database which release it is. Read-only; a missing schema, function or
    privilege is an observation, never an error."""

    probe = await connection.fetchrow(
        """
        SELECT contract.schema_oid IS NOT NULL AS contract_present,
               reader.oid IS NOT NULL AS function_present,
               COALESCE(
                   has_schema_privilege(contract.schema_oid, 'USAGE')
                   AND has_function_privilege(reader.oid, 'EXECUTE'),
                   false
               ) AS permitted
        FROM (SELECT to_regnamespace('api')::oid AS schema_oid) AS contract
        LEFT JOIN pg_catalog.pg_proc AS reader
          ON reader.pronamespace = contract.schema_oid
         AND reader.proname = 'database_release'
         AND reader.pronargs = 0
         AND reader.prokind = 'f'
        """
    )
    if probe is None or not probe["contract_present"]:
        return DatabaseReleaseObservation(contract_present=False)
    if not probe["function_present"]:
        return DatabaseReleaseObservation(
            contract_present=True,
            silence="the database holds the api schema but no api.database_release() function",
        )
    if not probe["permitted"]:
        return DatabaseReleaseObservation(
            contract_present=True,
            silence="this login may not call api.database_release() (it needs USAGE on schema "
            "api and EXECUTE on the function)",
        )
    raw = await connection.fetchval("SELECT api.database_release()::text")
    try:
        answer = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        return DatabaseReleaseObservation(
            contract_present=True,
            silence="api.database_release() did not return a JSON object",
        )
    return DatabaseReleaseObservation(contract_present=True, answer=answer)


def _unruled(
    verdict: DatabaseReleaseVerdict,
    declared: DatabaseReleaseDeclaration | None,
    mode: CheckMode,
    reason: str,
) -> DatabaseReleaseStatus:
    """An outcome the shared rule did not decide: no release or state was judged."""

    return DatabaseReleaseStatus(
        declared_range=None if declared is None else declared.range,
        release=None,
        state=None,
        verdict=verdict,
        mode=mode,
        warning=False,
        reason=reason,
    )


def _ruled(
    declared: DatabaseReleaseDeclaration, mode: CheckMode, observation: DatabaseReleaseObservation
) -> DatabaseReleaseStatus:
    try:
        ruled = release_verdict(observation.answer, declared.range, release_format=declared.format)
    except ValueError as error:
        # The answer names a release that is not a version: it states no release the rule reads.
        return _unruled(
            "unknown", declared, mode, f"the answer of the database is unreadable ({error})"
        )
    silence = observation.silence if observation.answer is None else None
    return DatabaseReleaseStatus(
        declared_range=declared.range,
        release=ruled.release,
        state=ruled.state,
        verdict=ruled.verdict,
        mode=mode,
        warning=ruled.warning,
        reason=silence or ruled.reason,
    )


async def check_database_release(
    check: DatabaseReleaseCheck,
    observe: Callable[[], Awaitable[DatabaseReleaseObservation]],
) -> DatabaseReleaseStatus:
    """Whether this process may serve on the release of its bound database.

    An application that declares no release, and mode ``off``, never ask the database. A bound
    database that does not hold the contract (the Mission Control component alone in its own
    database, as on the local stack) is ``not_applicable`` and starts. Otherwise the shared rule
    decides: in ``enforce`` mode a verdict that does not start raises
    :class:`InstallationUnavailable`; ``warn`` always starts and logs the verdict.
    """

    declared, mode = check.declared, check.mode
    if declared is None:
        return _unruled("not_declared", None, mode, "the application declares no database release")
    if mode == "off":
        _LOG.warning(
            "database release check is off (%s=off): the database is not asked", CHECK_VARIABLE
        )
        return _unruled(
            "not_checked", declared, mode, f"{CHECK_VARIABLE}=off: the database was not asked"
        )
    observation = await observe()
    if not observation.contract_present:
        status = _unruled(
            "not_applicable",
            declared,
            mode,
            "the bound database does not hold the database contract of the application "
            "(no api schema)",
        )
        _LOG.info("database release check not applicable: %s", status.reason)
        return status
    status = _ruled(declared, mode, observation)
    if status.verdict == "ok":
        log = _LOG.warning if status.warning else _LOG.info
        log("database release check: %s (declared range %s)", status.reason, declared.range)
    elif mode == "warn":
        _LOG.warning(
            "database release is %s: %s (%s=warn: starting anyway)",
            status.verdict,
            status.reason,
            CHECK_VARIABLE,
        )
    else:
        raise InstallationUnavailable(f"database release is {status.verdict}: {status.reason}")
    return status


def database_release_report(
    installations: Iterable[CommonReadiness],
) -> list[dict[str, str | None]]:
    """The distinct database release outcomes of the composed installations, first seen first
    (the tenants of one installation share one): what readiness states."""

    report: list[dict[str, str | None]] = []
    for installation in installations:
        entry = installation.database_release.report()
        if entry not in report:
            report.append(entry)
    return report


async def _role_memberships(connection: asyncpg.Connection) -> tuple[asyncpg.Record, set[str]]:
    role = await connection.fetchrow(
        """
        SELECT current_user AS name, current_database() AS database_name,
               rolsuper, rolbypassrls
        FROM pg_catalog.pg_roles WHERE rolname = current_user
        """
    )
    if role is None:
        raise InstallationUnavailable("pool role is not visible")
    members = {
        row["rolname"]
        for row in await connection.fetch(
            """
            SELECT rolname FROM pg_catalog.pg_roles
            WHERE rolname = ANY($1::text[]) AND pg_has_role(current_user, oid, 'MEMBER')
            """,
            list(CAPABILITY_ROLES),
        )
    }
    return role, members


async def verify_pool_role(connection: asyncpg.Connection, capability_role: str) -> asyncpg.Record:
    """The pool must hold exactly one capability role and no owner/bypass authority."""
    role, members = await _role_memberships(connection)
    owns_objects = await connection.fetchval(
        """
        SELECT EXISTS (
            SELECT 1 FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname IN ('mission_control', 'mission_control_search')
              AND pg_has_role(current_user, c.relowner, 'MEMBER')
            UNION ALL
            SELECT 1 FROM pg_catalog.pg_namespace n
            WHERE n.nspname IN ('mission_control', 'mission_control_search')
              AND pg_has_role(current_user, n.nspowner, 'MEMBER')
        )
        """
    )
    if role["rolsuper"] or role["rolbypassrls"] or owns_objects or members != {capability_role}:
        raise InstallationUnavailable(
            f"pool must hold only {capability_role} without owner or RLS bypass authority"
        )
    return role


async def inspect_common_installation(
    pool: asyncpg.Pool,
    binding: ApplicationBinding,
    *,
    capability_role: str = "mission_control_runtime",
    database_release: DatabaseReleaseCheck = NO_DATABASE_RELEASE_CHECK,
) -> CommonReadiness:
    async with (
        pool.acquire() as connection,
        connection.transaction(isolation="repeatable_read", readonly=True),
    ):
        role = await verify_pool_role(connection, capability_role)
        present = {
            row["relname"]
            for row in await connection.fetch(
                """
                SELECT c.relname FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'mission_control' AND c.relkind IN ('r', 'p')
                """
            )
        }
        if not present >= REQUIRED_TABLES:
            raise InstallationUnavailable("common mission_control component is not installed")
        try:
            installations = await connection.fetch(
                """
                SELECT installation_id, application_id, supabase_project_ref,
                       schema_component_version
                FROM mission_control.application_installation
                WHERE state = 'active'
                """
            )
            receipts = await connection.fetch(
                "SELECT component_version, migration_key FROM mission_control.component_release"
            )
            attestation = await connection.fetchrow(
                """
                SELECT component_version, schema_fingerprint, fingerprint_algorithm,
                       supported_reader_versions, supported_writer_versions
                FROM mission_control.release_attestation
                WHERE component_version = $1
                """,
                binding.required_component_version,
            )
        except asyncpg.InsufficientPrivilegeError as error:
            raise InstallationUnavailable("installation evidence is not readable") from error
        if len(installations) != 1:
            raise InstallationUnavailable("exactly one active application installation is required")
        actual = installations[0]
        if (
            actual["installation_id"] != binding.installation_id
            or actual["application_id"] != binding.application_id
            or actual["supabase_project_ref"] != binding.supabase_project_ref
            or actual["schema_component_version"] != binding.required_component_version
        ):
            raise InstallationUnavailable("persisted installation identity differs from binding")
        if attestation is None:
            raise InstallationUnavailable("installed component release is not attested")
        if (
            WRITER_VERSION not in attestation["supported_writer_versions"]
            or READER_VERSION not in attestation["supported_reader_versions"]
        ):
            raise InstallationUnavailable("this build is not an admitted reader/writer")
        if not receipts or not receipts_belong_to_release(
            {row["component_version"] for row in receipts}, binding.required_component_version
        ):
            raise InstallationUnavailable("component receipts do not match the pinned release")
        missing = missing_required_migrations(row["migration_key"] for row in receipts)
        if missing:
            raise InstallationUnavailable(
                "installed release predates this build; missing migrations: " + ", ".join(missing)
            )
        release = await check_database_release(
            database_release, lambda: read_database_release(connection)
        )
        return CommonReadiness(
            storage_mode="production_common",
            database_name=role["database_name"],
            component_version=attestation["component_version"],
            applied_migrations=frozenset(row["migration_key"] for row in receipts),
            schema_fingerprint=attestation["schema_fingerprint"],
            pool_role=role["name"],
            production_ready=attestation["fingerprint_algorithm"] != "fixture-unqualified",
            database_release=release,
        )


def missing_required_migrations(applied: Iterable[str]) -> tuple[str, ...]:
    """The migrations this build reads that the installation has no receipt for, sorted."""

    return tuple(sorted(REQUIRED_MIGRATIONS - set(applied)))
