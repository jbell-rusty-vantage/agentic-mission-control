"""Restricted LOGIN roles for the Mission Control runtime pools (``login-plan`` / ``login-apply``).

``mission-db apply`` creates only NOLOGIN capability roles and ``runtime-apply`` creates the NOLOGIN
``mission_control_checkpointer``. A running Mission Control needs three logins, each a member of
EXACTLY one capability role, because its pools check ``pg_has_role(current_user, role, 'MEMBER')``
and never ``SET ROLE`` (``adapters/postgres/connections.py``, ``bootstrap/common_installation.py``,
``adapters/deep_agents/runtime_persistence_verifier.py``):

=============  ==============================  =======================
login          capability role                 integrator DSN name (plane P = AIENG | BIOTECH)
=============  ==============================  ==============================================
runtime        mission_control_runtime         ``MC_P_DB_RUNTIME_DSN``
family writer  mission_control_family_writer   ``MC_P_DB_FAMILY_WRITER_DSN``
checkpointer   mission_control_checkpointer    ``MC_P_DB_CHECKPOINT_DSN``
ingress        mission_control_ingress         ``MC_INGRESS_DSN`` (Vercel; not a plane variable)
=============  ==============================  ==============================================

The plane is the target's application (``ai-engineer`` is AIENG, ``biotech`` is BIOTECH).

Each login is ``LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION`` and holds its
one membership ``WITH INHERIT TRUE, SET FALSE`` (PostgreSQL 16+ grant options; admin option
false). Login names never start with ``mission_control_`` (the installer's collision check treats
every ``mission_control_*`` role as a NOLOGIN capability role). The work runs as the target's admin
login, which on Supabase is a non-superuser CREATEROLE principal: PostgreSQL 16+ grants it ADMIN on
the roles it created, which is all this needs.

Secrets: passwords are ``secrets.token_urlsafe(32)``; the server only ever receives a client-side
SCRAM-SHA-256 verifier, never the password. The DSNs (host/port/database from the target; the
user ``<login>.<project_ref>`` on a Supavisor pooler route, else ``<login>``;
``sslmode=verify-full`` with the ``--ca-file``) are written ONLY to the owner-only ``--out-env``
file, which must be ignored by Git. Nothing printed or written elsewhere contains a password.
A rerun reuses the passwords the file already holds (verified, no change); ``--rotate`` resets
them.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import os
import re
import secrets
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from . import RUNTIME_SCHEMA
from .errors import ContractError, sqlstate
from .integrity import Release
from .runtime import _verified_common, inspect_steps
from .target import close_quietly, connect, public_identity

RECEIPT_FORMAT = "mission-control-login-receipt/v1"
LOGIN_PREFIX = re.compile(r"[a-z][a-z0-9]{0,15}")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
SSL_MODES = ("verify-full", "disable")
# Transaction-scoped (review S3): released at commit/rollback, safe through any pooler mode.
XACT_LOCK_SQL = (
    "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended("
    "'mission_control_logins.provision', 0))"
)
SCRAM_ITERATIONS = 4096


@dataclass(frozen=True)
class LoginSpec:
    key: str
    capability: str
    # `MC_<PLANE>_DB_<dsn_suffix>`; ``None``: the fixed name in ``fixed_dsn_name``.
    dsn_suffix: str | None
    fixed_dsn_name: str | None = None

    def role(self, prefix: str) -> str:
        return f"{prefix}_{self.key}"

    def dsn_name(self, target: dict[str, str]) -> str:
        if self.fixed_dsn_name is not None:
            return self.fixed_dsn_name
        return f"MC_{_PLANE_TOKENS.get(target['application_id'], '')}_DB_{self.dsn_suffix}"


# The application a target serves selects the plane token of its generated DSN names.
_PLANE_TOKENS = {"ai-engineer": "AIENG", "biotech": "BIOTECH"}


LOGINS = (
    LoginSpec("runtime", "mission_control_runtime", "RUNTIME_DSN"),
    LoginSpec("family_writer", "mission_control_family_writer", "FAMILY_WRITER_DSN"),
    LoginSpec("checkpointer", "mission_control_checkpointer", "CHECKPOINT_DSN"),
    # Loop iter-3 (hosted lanes): the restricted signal-ingress edge login the worker needs to
    # compose `claude_managed`/`codex_agents` (`bootstrap/signals.py::verify_signal_ingress_pool`).
    LoginSpec("ingress", "mission_control_ingress", None, "MC_INGRESS_DSN"),
)


def dsn_names(target: dict[str, str]) -> tuple[str, ...]:
    return tuple(spec.dsn_name(target) for spec in LOGINS)


_FORBIDDEN_ATTRIBUTES = (
    "rolsuper",
    "rolbypassrls",
    "rolcreatedb",
    "rolcreaterole",
    "rolreplication",
)
_ROLE_STATE = """
SELECT r.rolcanlogin, r.rolsuper, r.rolbypassrls, r.rolcreatedb, r.rolcreaterole,
       r.rolreplication,
       ARRAY(SELECT g.rolname || ':' || m.admin_option::text || ':' || m.inherit_option::text
                    || ':' || m.set_option::text
               FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles g ON g.oid = m.roleid
              WHERE m.member = r.oid ORDER BY 1) AS memberships,
       pg_catalog.has_database_privilege(r.oid, pg_catalog.current_database(), 'CONNECT')
           AS can_connect
  FROM pg_catalog.pg_roles r WHERE r.rolname = $1
"""


# ------------------------------------------------------------------------------- secrets


def scram_verifier(password: str, *, salt: bytes | None = None) -> str:
    """A PostgreSQL SCRAM-SHA-256 verifier for ``password`` (RFC 7677; ``pg_authid`` form)."""

    salt = salt if salt is not None else os.urandom(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, SCRAM_ITERATIONS)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()

    def b64(raw: bytes) -> str:
        return base64.b64encode(raw).decode("ascii")

    return f"SCRAM-SHA-256${SCRAM_ITERATIONS}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


def login_user(target: dict[str, str], role: str) -> str:
    """The DSN user: ``<role>.<project_ref>`` on a Supavisor pooler route, else the role."""

    if target["database_user"] != target["database_session_user"]:
        # load_target admits a differing session user only for `<session>.<project_ref>`.
        return f"{role}.{target['project_ref']}"
    return role


def build_dsn(
    target: dict[str, str], user: str, password: str, *, sslmode: str, ca_file: Path | None
) -> str:
    query = "sslmode=disable"
    if sslmode == "verify-full":
        if ca_file is None:
            raise ContractError("sslmode verify-full needs --ca-file", code="CA_FILE_MISSING")
        query = f"sslmode=verify-full&sslrootcert={quote(ca_file.resolve().as_posix(), safe=':/')}"
    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@"
        f"{target['database_host']}:{target['database_port']}/"
        f"{quote(target['database_name'], safe='')}?{query}"
    )


def _dsn_password(dsn: str, target: dict[str, str], user: str) -> str | None:
    """The password of an existing DSN when it names exactly this target endpoint and user."""

    try:
        parts = urlsplit(dsn)
        if (
            parts.hostname != target["database_host"]
            or (parts.port or 5432) != int(target["database_port"])
            or unquote(parts.path.removeprefix("/")) != target["database_name"]
            or unquote(parts.username or "") != user
        ):
            return None
        return unquote(parts.password or "") or None
    except ValueError:
        return None


# ------------------------------------------------------------------------------- env file


def read_env_file(path: Path) -> dict[str, str]:
    """``NAME='value'`` / ``NAME=value`` lines (the format this module and the generator write)."""

    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name.strip()] = value
    return values


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False
    )


def assert_ignored(path: Path) -> None:
    """Refuse unless ``path`` lies in a Git work tree that ignores it and does not track it."""

    anchor = path.parent
    while not anchor.exists():
        anchor = anchor.parent
    top = _git(anchor, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        raise ContractError(
            "--out-env is in no Git work tree; its ignore status is unprovable",
            code="OUTPUT_NOT_IN_REPOSITORY",
        )
    root = Path(top.stdout.strip()).resolve()
    relative = Path(os.path.relpath(path.resolve(), root)).as_posix()
    if _git(root, "ls-files", "--error-unmatch", "--", relative).returncode == 0:
        raise ContractError("--out-env is tracked by Git", code="OUTPUT_TRACKED")
    if _git(root, "check-ignore", "-q", "--", relative).returncode != 0:
        raise ContractError("--out-env is not ignored by Git", code="OUTPUT_NOT_IGNORED")


def _harden(path: Path) -> None:
    """Owner-only: mode 0o600; on Windows only the current user's ACE, none inherited."""

    if os.name != "nt":
        path.chmod(0o600)
        if path.stat().st_mode & 0o077:
            raise ContractError("--out-env is readable by others", code="SECRET_FILE_PERMISSIONS")
        return
    user = os.environ.get("USERNAME", "")
    if not user:
        raise ContractError(
            "USERNAME is unset; cannot restrict --out-env", code="SECRET_FILE_PERMISSIONS"
        )
    granted = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
        capture_output=True,
        text=True,
        check=False,
    )
    if granted.returncode != 0:
        raise ContractError("icacls could not restrict --out-env", code="SECRET_FILE_PERMISSIONS")
    listing = subprocess.run(
        ["icacls", str(path)], capture_output=True, text=True, check=False
    ).stdout
    principals: list[tuple[str, bool]] = []
    for line in listing.splitlines():
        text = line.strip()
        if not text:
            break
        if text.lower().startswith(str(path).lower()):
            text = text[len(str(path)) :].strip()
        match = re.match(r"^(.+?):((?:\([A-Z,]+\))+)$", text)
        if match:
            principals.append((match.group(1), "(I)" in match.group(2)))
    if not principals or any(
        inherited or principal.split("\\")[-1].lower() != user.lower()
        for principal, inherited in principals
    ):
        raise ContractError("--out-env grants more than its owner", code="SECRET_FILE_PERMISSIONS")


def write_env_file(path: Path, values: dict[str, str]) -> None:
    """Rewrite ``path`` owner-only; the temporary sibling is restricted before any byte lands."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    with contextlib.suppress(FileNotFoundError):
        temporary.unlink()
    os.close(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    try:
        _harden(temporary)
        lines = ["# mission-db login-apply: restricted Mission Control logins (owner-only)"]
        for name in sorted(values):
            value = values[name]
            if "'" in value or "\n" in value:
                raise ContractError(f"{name} cannot be quoted", code="VALUE_UNQUOTABLE")
            lines.append(f"{name}='{value}'")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
        temporary.replace(path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
    _harden(path)


# ------------------------------------------------------------------------------- inspection


def _expected_membership(capability: str) -> list[str]:
    return [f"{capability}:false:true:false"]


async def _role_state(connection: Any, role: str) -> dict[str, Any] | None:
    row = await connection.fetchrow(_ROLE_STATE, role)
    return None if row is None else dict(row)


def _drift(state: dict[str, Any], capability: str) -> list[str]:
    reasons = []
    if not state["rolcanlogin"]:
        reasons.append("not LOGIN")
    reasons += [
        f"has {name.removeprefix('rol').upper()}" for name in _FORBIDDEN_ATTRIBUTES if state[name]
    ]
    if list(state["memberships"]) != _expected_membership(capability):
        reasons.append(
            "memberships differ from exactly "
            f"{capability} (INHERIT TRUE, SET FALSE, no ADMIN): {list(state['memberships'])}"
        )
    if not state["can_connect"]:
        reasons.append("lacks CONNECT on the database")
    return reasons


async def _inspect(
    connection: Any, descriptor: dict[str, Any], prefix: str, target: dict[str, str]
) -> dict[str, Any]:
    await connection.execute(
        "SELECT set_config('search_path', $1, false)", descriptor["session"]["search_path"]
    )
    runtime = await inspect_steps(connection, descriptor)
    capabilities = {
        row["rolname"]: dict(row)
        for row in await connection.fetch(
            "SELECT r.rolname, r.rolcanlogin, EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m "
            "WHERE m.member = r.oid) AS has_memberships FROM pg_catalog.pg_roles r "
            "WHERE r.rolname = ANY($1::text[])",
            [spec.capability for spec in LOGINS],
        )
    }
    logins = []
    holds = []
    for spec in LOGINS:
        role = spec.role(prefix)
        entry: dict[str, Any] = {
            "login": role,
            "capability": spec.capability,
            "dsn_name": spec.dsn_name(target),
        }
        capability = capabilities.get(spec.capability)
        if capability is None or capability["rolcanlogin"]:
            entry["status"] = "capability_missing"
            holds.append(
                f"capability role {spec.capability} is missing or not NOLOGIN"
                + (" (run mission-db runtime-apply first)" if spec.key == "checkpointer" else "")
            )
        elif capability["has_memberships"]:
            # A login inherits through its capability role: that role must hold nothing itself.
            entry["status"] = "capability_missing"
            holds.append(f"capability role {spec.capability} is itself a member of another role")
        elif spec.key == "checkpointer" and not runtime["complete"]:
            entry["status"] = "capability_missing"
            holds.append(
                f"{RUNTIME_SCHEMA} is not complete; run mission-db runtime-apply before the "
                "checkpointer login"
            )
        else:
            state = await _role_state(connection, role)
            if state is None:
                entry["status"] = "absent"
            else:
                drift = _drift(state, spec.capability)
                entry["status"] = "drift" if drift else "present"
                if drift:
                    entry["drift"] = drift
                    holds.append(f"login {role} drifted: {'; '.join(drift)}")
        logins.append(entry)
    return {"logins": logins, "holds": holds, "runtime_complete": runtime["complete"]}


def _validate_prefix(prefix: str) -> None:
    if not LOGIN_PREFIX.fullmatch(prefix) or prefix.startswith("mission"):
        raise ContractError(
            "--login-prefix must be a short lowercase identifier not starting with 'mission'",
            code="LOGIN_PREFIX_INVALID",
        )


def _validate_tls(target: dict[str, str], sslmode: str, ca_file: Path | None) -> None:
    if sslmode not in SSL_MODES:
        raise ContractError(f"--sslmode must be one of {', '.join(SSL_MODES)}")
    if sslmode == "disable" and target["database_host"] not in LOOPBACK:
        raise ContractError(
            "sslmode disable is admitted only for a loopback disposable target",
            code="TLS_REQUIRED",
        )
    if sslmode == "verify-full":
        if ca_file is None or not ca_file.is_file():
            raise ContractError("verify-full needs a readable --ca-file", code="CA_FILE_MISSING")
        if b"-----BEGIN CERTIFICATE-----" not in ca_file.read_bytes():
            raise ContractError("--ca-file is not a PEM certificate", code="CA_FILE_INVALID")


# ------------------------------------------------------------------------------- commands


async def login_plan(
    target: dict[str, str],
    release: Release,
    descriptor: dict[str, Any],
    *,
    reader_version: str,
    writer_version: str,
    prefix: str = "mcl",
) -> dict[str, Any]:
    """Read-only: which logins are absent, present (verified) or drifted, and why."""

    _validate_prefix(prefix)
    connection = await connect(target, readonly=True)
    try:
        await _verified_common(connection, target, release, reader_version, writer_version)
        inspection = await _inspect(connection, descriptor, prefix, target)
    except ContractError:
        raise
    except Exception as exc:
        raise ContractError(f"Login planning failed (SQLSTATE {sqlstate(exc)})") from None
    finally:
        await close_quietly(connection)
    present = all(e["status"] == "present" for e in inspection["logins"])
    status = "hold" if inspection["holds"] else ("complete" if present else "pending")
    return {
        "status": status,
        "target": public_identity(target),
        "logins": inspection["logins"],
        "holds": inspection["holds"],
        "mutations": [
            f"create LOGIN {e['login']} member of {e['capability']}"
            for e in inspection["logins"]
            if e["status"] == "absent"
        ],
    }


TRANSACTION_POOLER_PORT = "6543"


def _pending(out_env: Path) -> Path:
    return out_env.with_name(out_env.name + ".pending")


async def login_apply(
    target: dict[str, str],
    release: Release,
    descriptor: dict[str, Any],
    *,
    confirmation: str,
    out_env: Path,
    reader_version: str,
    writer_version: str,
    sslmode: str = "verify-full",
    ca_file: Path | None = None,
    rotate: bool = False,
    probe: bool = False,
    prefix: str = "mcl",
    require_ignored: bool = True,
) -> dict[str, Any]:
    """Create or verify the restricted logins; their DSNs go only to ``out_env``.

    Order (review S1/S3): decide the actions, write the new DSNs to an owner-only
    ``<out-env>.pending`` sibling, then ONE transaction takes a transaction-scoped advisory lock,
    re-inspects (a concurrent change refuses), runs the DDL and verifies; only after it commits is
    ``out_env`` replaced atomically (the previous file kept as ``.prev``). A crash in between leaves
    the pending file, which the next run adopts only when its credentials authenticate. Logins
    reported ``verified`` are proven by connecting with the file's credentials.
    """

    if confirmation != f"{target['project_ref']}:{target['installation_id']}":
        raise ContractError("Login apply requires exact project-ref:installation-UUID confirmation")
    if target["database_port"] == TRANSACTION_POOLER_PORT:
        raise ContractError(
            "login-apply needs a session connection, not the transaction pooler (port 6543)",
            code="SESSION_CONNECTION_REQUIRED",
        )
    _validate_prefix(prefix)
    _validate_tls(target, sslmode, ca_file)
    out_env = out_env.resolve()
    pending = _pending(out_env)
    if require_ignored:
        assert_ignored(out_env)
        assert_ignored(pending)
    existing_env = read_env_file(out_env)
    if pending.exists():
        candidate = read_env_file(pending)
        try:
            await _probe(candidate, target)
        except ContractError:
            pending.unlink()  # never adopted: the DDL it was written for did not commit
        else:
            _replace(out_env, candidate, keep_previous=True)
            pending.unlink()  # adopted: out_env now holds the committed credentials
            existing_env = candidate
    connection = await connect(target, readonly=False, statement_timeout_ms=60000)
    entries: list[dict[str, Any]] = []
    committed = False
    try:
        await _verified_common(connection, target, release, reader_version, writer_version)
        before = await _inspect(connection, descriptor, prefix, target)
        if before["holds"]:
            raise ContractError("; ".join(before["holds"]), code="LOGIN_HOLD")
        passwords: dict[str, str] = {}
        actions: dict[str, str] = {}
        for item in before["logins"]:
            spec = next(s for s in LOGINS if s.dsn_name(target) == item["dsn_name"])
            role = spec.role(prefix)
            user = login_user(target, role)
            known = existing_env.get(spec.dsn_name(target))
            password = None if rotate or known is None else _dsn_password(known, target, user)
            if item["status"] == "absent":
                actions[role] = "created"
            elif rotate:
                actions[role] = "rotated"
            elif password is None:
                raise ContractError(
                    f"login {role} exists but --out-env holds no DSN for it; rerun with --rotate",
                    code="LOGIN_SECRET_UNKNOWN",
                )
            else:
                actions[role] = "verified"
            passwords[role] = password or secrets.token_urlsafe(32)
        values = dict(existing_env)
        for spec in LOGINS:
            role = spec.role(prefix)
            values[spec.dsn_name(target)] = build_dsn(
                target, login_user(target, role), passwords[role], sslmode=sslmode, ca_file=ca_file
            )
        changed = any(action != "verified" for action in actions.values())
        if changed:
            write_env_file(pending, values)
        async with connection.transaction():
            await connection.execute(XACT_LOCK_SQL)
            again = await _inspect(connection, descriptor, prefix, target)
            if [e["status"] for e in again["logins"]] != [e["status"] for e in before["logins"]]:
                raise ContractError("logins changed concurrently; rerun", code="LOGIN_CONCURRENT")
            for spec in LOGINS:
                role = spec.role(prefix)
                action = actions[role]
                if action == "verified":
                    continue
                verifier = scram_verifier(passwords[role])
                if action == "created":
                    statement = await connection.fetchval(
                        "SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB "
                        "NOCREATEROLE NOREPLICATION INHERIT PASSWORD %L', $1::text, $2::text)",
                        role,
                        verifier,
                    )
                    await connection.execute(statement)
                    await connection.execute(
                        await connection.fetchval(
                            "SELECT format('GRANT %I TO %I WITH INHERIT TRUE, SET FALSE', "
                            "$1::text, $2::text)",
                            spec.capability,
                            role,
                        )
                    )
                else:
                    await connection.execute(
                        await connection.fetchval(
                            "SELECT format('ALTER ROLE %I PASSWORD %L', $1::text, $2::text)",
                            role,
                            verifier,
                        )
                    )
            after = await _inspect(connection, descriptor, prefix, target)
            if after["holds"] or any(e["status"] != "present" for e in after["logins"]):
                raise ContractError(
                    "; ".join(after["holds"]) or "a login does not verify after apply",
                    code="LOGIN_UNVERIFIED",
                )
        committed = True
        if changed:
            _replace(out_env, values, keep_previous=True)
            pending.unlink(missing_ok=True)
        for spec in LOGINS:
            role = spec.role(prefix)
            entries.append(
                {
                    "login": role,
                    "user": login_user(target, role),
                    "capability": spec.capability,
                    "dsn_name": spec.dsn_name(target),
                    "action": actions[role],
                }
            )
    except ContractError:
        if not committed:  # after the commit the pending file holds the only new credentials
            pending.unlink(missing_ok=True)
        raise
    except Exception as exc:
        if not committed:
            pending.unlink(missing_ok=True)
        raise ContractError(f"Login apply failed (SQLSTATE {sqlstate(exc)})") from None
    finally:
        await close_quietly(connection)
    # A `verified` login is proven by its credentials, never by the file alone (review S1).
    verify_only = all(entry["action"] == "verified" for entry in entries)
    probes = await _probe(values, target) if probe or verify_only else None
    return {
        "format": RECEIPT_FORMAT,
        "status": "complete",
        "target": public_identity(target),
        "logins": entries,
        "changed": not verify_only,
        "out_env": out_env.as_posix(),
        "sslmode": sslmode,
        "probes": probes,
        "finished_at": datetime.now(UTC).isoformat(),
    }


def _replace(out_env: Path, values: dict[str, str], *, keep_previous: bool = False) -> None:
    """Atomically replace ``out_env`` (owner-only), keeping the previous file as ``.prev``."""

    if keep_previous and out_env.exists():
        previous = out_env.with_name(out_env.name + ".prev")
        write_env_file(previous, read_env_file(out_env))
    write_env_file(out_env, values)


async def _probe(values: dict[str, str], target: dict[str, str]) -> list[dict[str, Any]]:
    """Connect as each login through its own DSN; prove the session user and database."""

    import asyncpg

    results = []
    for spec in LOGINS:
        try:
            connection = await asyncpg.connect(values[spec.dsn_name(target)], timeout=10)
        except Exception as exc:
            raise ContractError(
                f"Login probe of {spec.dsn_name(target)} could not connect "
                f"(SQLSTATE {sqlstate(exc)})",
                code="LOGIN_PROBE_FAILED",
            ) from None
        try:
            row = await connection.fetchrow(
                "SELECT session_user AS session_user, current_database() AS database, "
                "pg_has_role(session_user, $1, 'MEMBER') AS member, "
                "pg_has_role(session_user, $1, 'SET') AS can_set",
                spec.capability,
            )
        finally:
            await connection.close()
        if row is None or row["database"] != target["database_name"] or not row["member"]:
            raise ContractError(
                f"Login probe of {spec.dsn_name(target)} is not a member of {spec.capability}",
                code="LOGIN_PROBE_FAILED",
            )
        results.append(
            {
                "dsn_name": spec.dsn_name(target),
                "session_user": row["session_user"],
                "member": True,
                "can_set_role": bool(row["can_set"]),
            }
        )
    return results


__all__ = [
    "dsn_names",
    "LOGINS",
    "build_dsn",
    "login_apply",
    "login_plan",
    "login_user",
    "read_env_file",
    "scram_verifier",
]
