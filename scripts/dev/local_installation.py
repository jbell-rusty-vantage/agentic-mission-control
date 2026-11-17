"""Prepare a fresh, fully local, production-shaped Mission Control installation of one application.

``install`` builds, against LOCAL infrastructure only, everything the two process roles
(``mission-control api`` and ``mission-control worker``) need, and writes it under one ignored
directory (default ``.scratch/local-stack/<app>/``):

1. a database ``mc_local_<app>`` on the loopback PostgreSQL 17 + pgvector cluster named by an
   admin DSN environment variable (``--admin-dsn-env``, default ``MC_LOCAL_STACK_ADMIN_DSN``;
   unset: the compose ``application-postgres-17`` service on ``127.0.0.1:55434``,
   ``make local-infra``). A DSN whose host is not loopback is refused: nothing here reaches a
   remote database or service.
2. the common component through ``mission-db`` (lock, plan, apply, verify), the runtime phase
   (the LangGraph saver and store), the seed bundles ``seeds/common`` and ``seeds/<app>``, the
   restricted logins (``login-apply``: runtime, family writer, checkpointer, ingress, each a
   member of exactly one capability role) and the deployment's tenant (``tenant-apply``);
3. the capability search projection, lexical only (no embedding call), and the seed skill
   bundles in a local custody root (``bundles/``);
4. a sealed Application Binding, the operator deployment file (``deployment.json``) with a
   generated Ed25519 signing key, its pinned public JWKS and one operator grant holding the
   Sprint OC operator's permission set, and a bearer in ``operator-token.txt`` (file only);
5. ``mission-control.env``: every name the API and the worker read. ``MISSION_CONTROL_HOME`` is
   the installation directory, which holds no ``.env``, so the settings loader layers nothing
   beneath the process environment; every database variable of every plane is written (the
   three restricted logins, every other one an explicit blank) and every provider credential
   is an explicit blank. A variable that is present, even empty, wins.
6. the Temporal namespace on the loopback server (default ``127.0.0.1:7233``, namespace
   ``mc-local-<app>``, created when absent) with the Search Attributes registered.

A second run on the same directory verifies and reuses (every installer step is idempotent);
``--recreate`` drops the local database and its logins and builds a new installation. ``token``
re-mints the operator bearer. ``container`` derives, from the installed files, the env file and
deployment file ``deployments/docker/compose.yml`` reads (container paths, ``sslmode=require``
DSNs on the compose network, the Temporal address); it changes no database. Output is names,
paths and digests only: no DSN, key or token is ever printed. Exit 0 = ready, 2 = refused.

What the worker needs beyond this repository is checked and reported, never invented: the
capability resource owner's pinned modules (``workspace://.tools/...``), the pinned skill
bundles of the checkout's offline store and a Node executable. ``installation.json`` records
``worker.ready``; ``make local-up`` starts the worker only when it is true.

    make local-infra
    uv run --no-sync python scripts/dev/local_installation.py install --app ai-engineer
    uv run --no-sync python scripts/dev/local_installation.py token --app ai-engineer
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
PACKAGE = ROOT / "packages" / "mission-control-db-contract"
APPLICATIONS = ("ai-engineer", "biotech")
DEFAULT_APPLICATION = "ai-engineer"
# The newest release with a release integration test (releases/README.md, 2026-11-16:
# tests/integration/postgres/test_capability_search_release_1160.py). Releases before 1.16.0
# cannot activate the capability search projection on a locale database (`en_US.utf8`) once
# the 1.1.0 capability seed is applied (0075).
COMPONENT_VERSION = "1.16.0"
RUNTIME_VERSIONS = (
    "--reader-version",
    "mission-control-runtime/1",
    "--writer-version",
    "mission-control-runtime/1",
)
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
ADMIN_DSN_ENV = "MC_LOCAL_STACK_ADMIN_DSN"
# The compose `application-postgres-17` service (docker-compose.yml): a tracked development
# placeholder, not a credential of any real installation.
COMPOSE_DB_PORT_ENV = "MC_LOCAL_STACK_DB_PORT"
COMPOSE_DB = {"user": "belllabs", "word": "belllabs-local", "database": "belllabs", "port": 55434}
# The variable the generated target manifest names for `mission-db` (set for its process only).
INSTALL_DSN_ENV = "MC_LOCAL_STACK_INSTALL_DSN"
TEMPORAL_ADDRESS = "127.0.0.1:7233"
RUNTIME_OPTIONS_FACTORY = "mission_control.bootstrap.local_operator:runtime_options"
OPERATOR_SUBJECT = "local-operator"
OPERATOR_ACTOR = "operator:local"
# The worker's loopback Kernel Hook listener: away from the default 47555, which another stack's
# worker on this host may hold, and one port per application (`hook_callback_port`).
HOOK_CALLBACK_PORT = 47565
TOKEN_TTL_MINUTES = 720
STATE = "installation.json"
ENV_FILE = "mission-control.env"
LOGINS_ENV = "logins.env"
MINTED_ENV = "minted.env"
PINS = "capability-pins/research-capabilities.json"
# The container variant of an installation (`container`): where deployments/docker/compose.yml
# mounts the deployment directory and the capability resource owner, and the worker image's Node.
CONTAINER_HOME = "/var/lib/mission-control"
CONTAINER_WORKSPACE = "/var/lib/mission-control-workspace"
CONTAINER_NODE = "/usr/local/bin/node"
CONTAINER_ENV_FILE = "mission-control.container.env"
CONTAINER_DEPLOYMENT = "deployment.container.json"
# What `--recreate` removes besides the database (never anything else in the directory).
GENERATED = (
    STATE,
    ENV_FILE,
    LOGINS_ENV,
    f"{LOGINS_ENV}.prev",
    f"{LOGINS_ENV}.pending",
    MINTED_ENV,
    CONTAINER_ENV_FILE,
    CONTAINER_DEPLOYMENT,
    "deployment.json",
    "operator-issuer.jwk.json",
    "operator-jwks.json",
    "operator-token.txt",
    "deployments",
    "receipts",
    "capability-pins",
    "payloads",
    "workspaces",
)
# The only variables a process started for this installation inherits from its parent; every
# Mission Control name comes from the generated env file (see `base_environment`).
PASSTHROUGH = frozenset(
    {
        *("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "OS"),
        *("TEMP", "TMP", "TMPDIR", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "HOME"),
        *("USERNAME", "USER", "LOGNAME", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA"),
        *("PROGRAMFILES", "PROGRAMFILES(X86)", "COMMONPROGRAMFILES"),
        *("NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE"),
        *("LANG", "LC_ALL", "LC_CTYPE", "TZ"),
    }
)
# Provider and service credentials: explicit blanks (a blank optional secret reads as unset).
# Add a key to the generated file by hand to run paid cognition; nothing is inherited.
CREDENTIAL_BLANKS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "MC_JUDGE_OPENAI_API_KEY",
    "MC_AUDITOR_ANTHROPIC_API_KEY",
    "FIRECRAWL_API_KEY",
    "TAVILY_API_KEY",
    "LANGSMITH_API_KEY",
    "RUNTIME_CHECKPOINT_SIGNING_KEY",
    "MC_INGRESS_DSN",
)


def _script(name: str) -> ModuleType:
    """A sibling script under ``scripts/`` as a module (the repository's own loading idiom)."""

    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# The Sprint OC generators own the shared refusals, the ignore guard, the owner-only writer, the
# operator key and bearer minting, and the lists of names an owner `.env` must never supply.
dep = _script("sprint_oc_deployment_file")
gen = dep.gen
Refused = gen.Refused


# ------------------------------------------------------------------------------------- inputs


def default_out(app: str) -> Path:
    return ROOT / ".scratch" / "local-stack" / app


def database_name(app: str) -> str:
    return "mc_local_" + re.sub(r"[^a-z0-9]", "_", app)


def login_prefix(app: str) -> str:
    """The `mission-db login-apply` prefix (at most 16 lowercase characters, never `mission*`)."""

    return ("mcl" + re.sub(r"[^a-z0-9]", "", app))[:16]


def login_roles(app: str) -> tuple[str, ...]:
    prefix = login_prefix(app)
    return tuple(
        f"{prefix}_{key}" for key in ("runtime", "family_writer", "checkpointer", "ingress")
    )


def project_ref(app: str) -> str:
    return f"mc-local-{app}"


def temporal_namespace(app: str) -> str:
    return f"mc-local-{app}"


def hook_callback_port(app: str) -> int:
    """A distinct default listener port per application, so two local stacks can run at once."""

    return HOOK_CALLBACK_PORT + APPLICATIONS.index(app)


def compose_admin_dsn(environment: dict[str, str] | None = None) -> str:
    """The admin DSN of the compose ``application-postgres-17`` service on loopback."""

    source = os.environ if environment is None else environment
    port = source.get(COMPOSE_DB_PORT_ENV) or str(COMPOSE_DB["port"])
    credentials = f"{COMPOSE_DB['user']}:{COMPOSE_DB['word']}"
    return f"postgresql://{credentials}@127.0.0.1:{port}/{COMPOSE_DB['database']}"


def loopback_dsn(dsn: str, name: str) -> str:
    """``dsn`` when it is a PostgreSQL URL on a loopback host; refused otherwise (no value in
    the message)."""

    try:
        parts = urlsplit(dsn)
        host, login = parts.hostname, parts.username
        parts.port  # noqa: B018 - a malformed port raises here, not at connect time
    except ValueError:
        raise Refused("ADMIN_DSN_INVALID", f"{name} is not a PostgreSQL URL") from None
    if parts.scheme not in {"postgres", "postgresql"} or not host:
        raise Refused("ADMIN_DSN_INVALID", f"{name} is not a PostgreSQL URL")
    if host not in LOOPBACK_HOSTS:
        raise Refused(
            "ADMIN_DSN_NOT_LOOPBACK",
            f"{name} names a host that is not loopback; a local installation never uses a "
            "remote database",
        )
    if not login:
        raise Refused("ADMIN_DSN_INVALID", f"{name} names no login")
    return dsn


def admin_dsn(env_name: str, environment: dict[str, str] | None = None) -> tuple[str, str]:
    """(DSN, source) of the loopback admin server: the named variable, else the compose one."""

    source = os.environ if environment is None else environment
    value = source.get(env_name)
    if value:
        return loopback_dsn(value, env_name), f"environment:{env_name}"
    return loopback_dsn(compose_admin_dsn(source), "the compose default"), "compose:default"


def with_database(dsn: str, database: str) -> str:
    """``dsn`` on ``127.0.0.1`` naming ``database`` and no query (the installer's exact target)."""

    parts = urlsplit(dsn)
    host = "127.0.0.1" if parts.hostname == "localhost" else (parts.hostname or "127.0.0.1")
    host = f"[{host}]" if ":" in host else host
    credentials = quote(parts.username or "", safe="")
    if parts.password is not None:
        credentials += ":" + quote(parts.password, safe="")
    netloc = f"{credentials}@{host}:{parts.port or 5432}"
    return urlunsplit((parts.scheme, netloc, "/" + database, "", ""))


def base_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment of every process this installation starts: operating-system essentials
    only, then ``extra``. No Mission Control setting, database name or credential of the caller's
    shell reaches it."""

    environment = {key: value for key, value in os.environ.items() if key.upper() in PASSTHROUGH}
    environment.update(extra or {})
    return environment


def read_env_file(path: Path) -> dict[str, str]:
    """``NAME=value`` / ``NAME='value'`` lines, as this script and ``mission-db`` write them."""

    values: dict[str, str] = {}
    if not path.is_file():
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


def render_env(entries: list[tuple[str, str]], header: list[str]) -> str:
    """dotenv text: bare when safe, else single-quoted (literal for compose, uv and node)."""

    lines = [f"# {line}" if line else "#" for line in header] + [""]
    seen: set[str] = set()
    for name, value in entries:
        if name in seen:
            raise Refused("ENV_DUPLICATE", name)
        seen.add(name)
        if "\n" in value or "\r" in value:
            raise Refused("VALUE_MULTILINE", name)
        if gen.BARE.match(value):
            lines.append(f"{name}={value}")
        elif "'" not in value and not value.endswith("\\"):
            lines.append(f"{name}='{value}'")
        else:
            raise Refused("VALUE_UNQUOTABLE", name)
    return "\n".join(lines) + "\n"


def load_profile(app: str) -> dict[str, Any]:
    path = ROOT / "deployments" / app / "application.toml"
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Refused("PROFILE_INVALID", f"{path} is not readable TOML") from error


def release_manifest(version: str) -> tuple[Path, dict[str, Any]]:
    component = PACKAGE / "releases" / version / "component"
    try:
        manifest = json.loads((component / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Refused("RELEASE_NOT_BUILT", f"release {version} has no built manifest") from error
    return component, manifest


def load_state(out: Path) -> dict[str, Any] | None:
    path = out / STATE
    if not path.is_file():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise Refused("STATE_INVALID", f"{path} is not JSON; rerun with --recreate") from error
    if not isinstance(state, dict):
        raise Refused("STATE_INVALID", f"{path} is not an object; rerun with --recreate")
    return state


def running_pid_files(out: Path) -> list[str]:
    return sorted(path.name for path in (out / "run").glob("*.pid")) if out.is_dir() else []


# ------------------------------------------------------------------------------------- documents


def target_manifest(
    app: str, *, installation_id: str, host: str, port: int, database: str, user: str
) -> str:
    return (
        "# Generated by scripts/dev/local_installation.py: a loopback disposable target.\n"
        "format_version = 1\n\n[target]\n"
        f'app = "{app}"\napplication_id = "{app}"\n'
        f'project_label = "local-stack-{app}"\nproject_ref = "{project_ref(app)}"\n'
        f'installation_id = "{installation_id}"\nenvironment = "disposable"\n'
        f'database_host = "{host}"\ndatabase_port = {port}\n'
        f'database_name = "{database}"\ndatabase_user = "{user}"\n'
        f'database_url_env = "{INSTALL_DSN_ENV}"\n\n[approval]\n'
        'approved_by = "scripts/dev/local_installation.py"\n'
        'identity_evidence = "loopback disposable database created by the local installation"\n'
    )


def operator_permissions() -> list[str]:
    """The Sprint OC operator's permission set (``scripts/sprint_oc_deployment_file.py``)."""

    from mission_control.interfaces.http.run_control import ROLE_PERMISSIONS

    return sorted(
        ROLE_PERMISSIONS["operator"] | ROLE_PERMISSIONS["state_inspector"] | dep.EXTRA_PERMISSIONS
    )


def deployment_document(
    app: str,
    *,
    installation_id: str,
    tenant: str,
    component_version: str,
    queue_base: str,
    temporal_address: str,
    namespace: str,
    max_request_bytes: int = 1_000_000,
) -> dict[str, Any]:
    """The operator ``MissionDeployment`` of one application: a sealed binding on the restricted
    logins' variable names, the operator issuer and one operator grant, and the Temporal target."""

    from mission_control.adapters.temporal.coordinator_runtime import coordinator_task_queues
    from mission_control.application.installations.registry import ApplicationBinding

    binding = ApplicationBinding.seal(
        application_id=app,
        installation_id=installation_id,
        binding_version=f"local-stack/{component_version}",
        supabase_project_ref=project_ref(app),
        database_secret_ref=gen.db_name(app, "RUNTIME_DSN"),
        accepted_issuers={dep.issuer(app)},
        accepted_audiences={dep.audience(app)},
        required_component_version=component_version,
    )
    queues = coordinator_task_queues(queue_base)
    return {
        "storage_mode": "production_common",
        "max_request_bytes": max_request_bytes,
        "applications": [
            {
                "authentication": {
                    "binding": binding.model_dump(mode="json"),
                    "issuer": dep.issuer(app),
                    "audience": dep.audience(app),
                    "public_jwks_file": dep.OPERATOR_JWKS,
                    "algorithms": ["EdDSA"],
                    "grants": [
                        {
                            "subject": OPERATOR_SUBJECT,
                            "actor_id": OPERATOR_ACTOR,
                            "tenant_ids": [tenant],
                            "permissions": operator_permissions(),
                            "authority_refs": ["authority:lifecycle"],
                            "sponsorship_refs": ["sponsorship:local-stack"],
                            "approval_refs": ["approval:local-stack"],
                        }
                    ],
                },
                "family_writer_secret_ref": gen.db_name(app, "FAMILY_WRITER_DSN"),
                "temporal": {
                    "address": temporal_address,
                    "namespace": namespace,
                    "root_task_queue": queues.stagegraph,
                    "stagegraph_task_queue": queues.stagegraph,
                    "goal_directed_task_queue": queues.goal_directed,
                },
            }
        ],
    }


def runtime_environment(
    app: str,
    out: Path,
    *,
    installation_id: str,
    binding_digest: str,
    logins: dict[str, str],
    signing_key: str,
    profile: dict[str, Any],
    workspace_root: Path,
    temporal_address: str,
    namespace: str,
    node: str | None,
    hook_callback_port: int = HOOK_CALLBACK_PORT,
) -> list[tuple[str, str]]:
    """Every name the API and the worker read, in file order: explicit values, then explicit
    blanks for every other database variable and every credential."""

    installation = profile["installation"]
    names = {role: gen.db_name(app, role) for role in ("RUNTIME_DSN", "FAMILY_WRITER_DSN")}
    names["CHECKPOINT_DSN"] = gen.db_name(app, "CHECKPOINT_DSN")
    missing = [name for name in names.values() if not logins.get(name)]
    if missing:
        raise Refused("LOGINS_MISSING", f"{LOGINS_ENV} holds no {', '.join(missing)}")
    entries: list[tuple[str, str]] = [
        # Operator assets resolve from here, and `<MISSION_CONTROL_HOME>/.env` does not exist.
        ("MISSION_CONTROL_HOME", out.as_posix()),
        ("MISSION_CONTROL_APPLICATION", app),
        ("MISSION_CONTROL_DEPLOYMENT_FILE", (out / dep.DEPLOYMENT).as_posix()),
        ("MISSION_CONTROL_DEPLOYMENTS_ROOT", (out / "deployments").as_posix()),
        ("MISSION_CONTROL_WORKER_APPLICATION_ID", app),
        ("MISSION_CONTROL_WORKER_BINDING_DIGEST", binding_digest),
        ("MISSION_CONTROL_WORKER_ROLE", "base"),
        ("MISSION_CONTROL_RUNTIME_OPTIONS_FACTORY", RUNTIME_OPTIONS_FACTORY),
        ("MISSION_CONTROL_CATALOG_SCOPE", f"mc/{installation_id}/{app}/catalog"),
        ("MISSION_CONTROL_WORKSPACE_ROOT", workspace_root.as_posix()),
        ("MISSION_CONTROL_HOOK_CALLBACK_PORT", str(hook_callback_port)),
        ("CAPABILITY_PINS_PATH", (out / PINS).as_posix()),
        ("CAPABILITY_BUNDLE_BACKEND", "local"),
        ("CAPABILITY_BUNDLE_LOCAL_ROOT", (out / "bundles").as_posix()),
        ("ARTIFACT_PAYLOAD_ROOT", (out / "payloads").as_posix()),
        ("DEEP_AGENT_SANDBOX_WORKSPACE_ROOT", (out / "workspaces").as_posix()),
        *((name, logins[name]) for name in names.values()),
        ("LANGGRAPH_CHECKPOINT_SCHEMA", "mission_control_runtime"),
        ("LANGGRAPH_CHECKPOINT_SETUP", "false"),
        ("TEMPORAL_TARGET", "local"),
        ("TEMPORAL_ADDRESS", temporal_address),
        ("TEMPORAL_NAMESPACE", namespace),
        ("TEMPORAL_TASK_QUEUE", installation["temporal_task_queue"]),
        ("LANGSMITH_PROJECT", installation["langsmith_project"]),
        ("AGENT_SERVER_LANGSMITH_PROJECT", installation["agent_server_langsmith_project"]),
        ("LANGSMITH_TRACING", "false"),
        ("LANGCHAIN_TRACING_V2", "false"),
        ("BELL_LABS_ENVIRONMENT", "development"),
        ("RUN_CONTROL_TEMPORAL_ENABLED", "true"),
        ("COORDINATOR_LAUNCH_ENABLED", "true"),
        ("COORDINATOR_MCP_ENABLED", "false"),
        ("CHAIN_RELAY_ENABLED", "false"),
        ("LANGGRAPH_RUNTIME_ENABLED", "false"),
        ("ASYNC_SUBAGENT_SPAWNING_ENABLED", "false"),
        ("KNOWLEDGE_GATEWAY_REQUIRED", "false"),
        ("REDIS_URL", gen.LOCAL_REDIS),
        ("RUNTIME_CHECKPOINT_SIGNING_KEY", signing_key),
        *gen.MC_DEFAULTS.items(),
    ]
    if node:
        entries.append(("WEB_RESEARCH_AGENT_BROWSER_NODE", Path(node).as_posix()))
    named = {name for name, _value in entries}
    blanks = (*gen.MC_DB_BLANKED, *gen.MC_BLANKED, *CREDENTIAL_BLANKS)
    return entries + [(name, "") for name in dict.fromkeys(blanks) if name not in named]


def container_dsn(dsn: str, host: str, port: int) -> str:
    """The same login and database through ``host:port`` with ``sslmode=require``: Mission
    Control refuses a non-loopback PostgreSQL endpoint without TLS."""

    parts = urlsplit(dsn)
    credentials = parts.netloc.rsplit("@", 1)[0]
    return urlunsplit(
        (parts.scheme, f"{credentials}@{host}:{port}", parts.path, "sslmode=require", "")
    )


def container_environment(
    entries: list[tuple[str, str]],
    *,
    out: Path,
    database_host: str,
    database_port: int,
    temporal_address: str,
    redis_url: str,
) -> list[tuple[str, str]]:
    """The host env file's entries as a container reads them: the deployment directory at
    ``CONTAINER_HOME``, the capability resource owner at ``CONTAINER_WORKSPACE``, the worker
    image's Node, and PostgreSQL, Temporal and Redis by their network names."""

    home = out.as_posix()
    fixed = {
        "MISSION_CONTROL_DEPLOYMENT_FILE": f"{CONTAINER_HOME}/{CONTAINER_DEPLOYMENT}",
        "MISSION_CONTROL_WORKSPACE_ROOT": CONTAINER_WORKSPACE,
        "WEB_RESEARCH_AGENT_BROWSER_NODE": CONTAINER_NODE,
        "TEMPORAL_ADDRESS": temporal_address,
        "REDIS_URL": redis_url,
    }
    result: list[tuple[str, str]] = []
    for name, value in entries:
        if name in fixed:
            value = fixed[name]
        elif name.endswith("_DSN") and value:
            value = container_dsn(value, database_host, database_port)
        elif value == home or value.startswith(home + "/"):
            value = CONTAINER_HOME + value[len(home) :]
        result.append((name, value))
    named = {name for name, _value in result}
    return result + [(name, value) for name, value in fixed.items() if name not in named]


# ------------------------------------------------------------------------------------- database


async def _connect(dsn: str) -> Any:
    import asyncpg

    try:
        return await asyncpg.connect(dsn, timeout=10)
    except Exception as error:  # the driver's message may carry the endpoint; name only its type
        parts = urlsplit(dsn)
        raise Refused(
            "ADMIN_CONNECTION",
            f"cannot connect to the loopback PostgreSQL server at {parts.hostname}:"
            f"{parts.port or 5432} ({type(error).__name__}); start it with `make local-infra`",
        ) from None


async def ensure_database(admin: str, name: str, *, postgres_major: int) -> dict[str, Any]:
    """Create ``name`` (when absent) with the release's required extensions; refuse a server of
    another major version."""

    connection = await _connect(admin)
    try:
        version = int(await connection.fetchval("SHOW server_version_num"))
        if version // 10000 != postgres_major:
            raise Refused(
                "POSTGRES_VERSION",
                f"the common component needs PostgreSQL {postgres_major}; the server is "
                f"{version // 10000} (the compose `application-postgres` is 16: use "
                "`application-postgres-17`, `make local-infra`)",
            )
        exists = await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if not exists:
            await connection.execute(f'CREATE DATABASE "{name}"')
    finally:
        await connection.close()
    connection = await _connect(with_database(admin, name))
    try:
        await connection.execute("CREATE SCHEMA IF NOT EXISTS extensions")
        await connection.execute("CREATE EXTENSION IF NOT EXISTS vector SCHEMA extensions")
        await connection.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA extensions")
        await connection.execute("GRANT USAGE ON SCHEMA extensions TO PUBLIC")
        storage = await ensure_storage(connection)
    finally:
        await connection.close()
    return {
        "disposition": "reused" if exists else "created",
        "server_version_num": version,
        "storage": storage,
    }


# `seeds/common` carries two Supabase Storage bundles (the `capability-bundles` and
# `mission-payloads` buckets and their `storage.objects` policies), and the application's
# cognition profiles depend on the first: on a plain PostgreSQL they report `blocked` and
# `seed-apply` stops at the dependant. This is a SYNTHETIC stand-in shaped like Supabase Storage
# (as in tests/integration/postgres/test_capability_bundles_publish.py) so that every bundle
# applies; it is not Supabase and stores nothing. Local custody is the filesystem (`bundles/`).
SYNTHETIC_STORAGE = """
DO $$ BEGIN CREATE ROLE authenticated NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE SCHEMA storage;
COMMENT ON SCHEMA storage IS
    'SYNTHETIC stand-in created by scripts/dev/local_installation.py; not Supabase Storage';
CREATE TABLE storage.buckets (
    id text PRIMARY KEY, name text NOT NULL, public boolean NOT NULL DEFAULT false,
    file_size_limit bigint, allowed_mime_types text[]);
CREATE TABLE storage.objects (
    id bigserial PRIMARY KEY, bucket_id text NOT NULL REFERENCES storage.buckets (id),
    name text NOT NULL, content bytea, UNIQUE (bucket_id, name));
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;
CREATE FUNCTION storage.foldername(name text) RETURNS text[]
    LANGUAGE sql IMMUTABLE AS $f$
    SELECT (string_to_array(name, '/'))[1:array_length(string_to_array(name, '/'), 1) - 1]
    $f$;
GRANT USAGE ON SCHEMA storage TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON storage.objects TO authenticated;
GRANT USAGE, SELECT ON SEQUENCE storage.objects_id_seq TO authenticated;
"""


async def ensure_storage(connection: Any) -> str:
    """``present`` when the database already has a ``storage`` schema (a Supabase stack's own, or
    this stand-in from an earlier run); else create the synthetic stand-in in one transaction."""

    if await connection.fetchval("SELECT to_regnamespace('storage') IS NOT NULL"):
        return "present"
    async with connection.transaction():
        await connection.execute(SYNTHETIC_STORAGE)
    return "synthetic-created"


async def drop_database(admin: str, name: str, roles: tuple[str, ...]) -> dict[str, Any]:
    """Drop the local database and the restricted logins this installation created."""

    if not re.fullmatch(r"mc_local_[a-z0-9_]{1,48}", name):
        raise Refused("DATABASE_NAME", "only a mc_local_* database is ever dropped")
    connection = await _connect(admin)
    try:
        existed = await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        await connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        dropped = []
        for role in roles:
            if not re.fullmatch(r"mcl[a-z0-9]{1,13}_[a-z_]{1,16}", role):
                raise Refused("LOGIN_NAME", "only this installation's logins are ever dropped")
            if await connection.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role):
                await connection.execute(f'DROP ROLE "{role}"')
                dropped.append(role)
    finally:
        await connection.close()
    return {"database_dropped": bool(existed), "logins_dropped": dropped}


# ------------------------------------------------------------------------------------- steps


class Installer:
    def __init__(self, args: argparse.Namespace) -> None:
        self.app: str = args.app
        self.out: Path = (args.out or default_out(self.app)).resolve()
        self.args = args
        self.steps: list[dict[str, Any]] = []
        self.deployment_dir = self.out / "deployments" / self.app

    def record(self, step: str, **facts: Any) -> None:
        self.steps.append({"step": step, **facts})
        shown = ", ".join(f"{key}={value}" for key, value in facts.items() if key != "detail")
        print(f"[local-install] {step}: {shown}", flush=True)

    def run(self, command: list[str], env: dict[str, str], timeout: int = 900) -> tuple[int, str]:
        done = subprocess.run(
            command,
            cwd=ROOT,
            env=base_environment(env),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return done.returncode, done.stdout

    @staticmethod
    def _json(stdout: str) -> dict[str, Any]:
        text = stdout[stdout.find("{") :] if "{" in stdout else "{}"
        try:
            value = json.loads(text)
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def mission_db(self, step: str, *arguments: str, dsn: str) -> dict[str, Any]:
        """One `mission-db` command (its JSON is redacted by contract); a blocked gate refuses."""

        code, stdout = self.run(
            [sys.executable, "-m", "mission_control_db_contract.cli", *arguments],
            {INSTALL_DSN_ENV: dsn},
        )
        body = self._json(stdout)
        self.record(step, exit=code, status=body.get("status"))
        if code != 0:
            holds = body.get("holds") or (body.get("plan") or {}).get("holds") or []
            detail = "; ".join(
                str(item) for item in (body.get("code"), body.get("error"), *holds) if item
            )
            raise Refused(f"MISSION_DB_{step.upper().replace('-', '_')}", detail or f"exit {code}")
        return body

    # -- stages --------------------------------------------------------------------------------

    def guard(self) -> None:
        for name in (STATE, ENV_FILE, LOGINS_ENV, "operator-token.txt", "run/api.pid"):
            gen.assert_ignored(self.out / name)

    def identity(self, admin: str) -> dict[str, Any]:
        """The installation's identity: reused from ``installation.json``, else allocated."""

        from mission_control.contracts.identities import uuid7

        state = load_state(self.out)
        parts = urlsplit(admin)
        endpoint = {
            "host": "127.0.0.1" if parts.hostname == "localhost" else parts.hostname,
            "port": parts.port or 5432,
            "name": database_name(self.app),
        }
        if state is not None:
            if state.get("application") != self.app:
                raise Refused("STATE_MISMATCH", f"{self.out} holds another application")
            if state.get("database") != endpoint:
                raise Refused(
                    "STATE_MISMATCH",
                    f"{self.out} was installed on another server; rerun with --recreate",
                )
            return state
        return {
            "schema": "mc.local_installation.v1",
            "application": self.app,
            "installation_id": str(uuid7()),
            "tenant_id": str(uuid7()),
            "project_ref": project_ref(self.app),
            "database": endpoint,
            "login_prefix": login_prefix(self.app),
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }

    def recreate(self, admin: str) -> None:
        running = running_pid_files(self.out)
        if running:
            raise Refused(
                "STACK_RUNNING",
                f"{', '.join(running)} exist under {self.out / 'run'}; run `make local-down` first",
            )
        dropped = asyncio.run(drop_database(admin, database_name(self.app), login_roles(self.app)))
        for name in GENERATED:
            path = self.out / name
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        self.record("recreate", **dropped)

    def write_inputs(self, state: dict[str, Any], admin: str) -> None:
        """The self-contained deployments root (target manifest, the application's tracked
        profile and Model Catalog) and the capability pins the processes read."""

        self.deployment_dir.mkdir(parents=True, exist_ok=True)
        parts = urlsplit(admin)
        database = state["database"]
        gen.write_text(
            self.deployment_dir / "target.toml",
            target_manifest(
                self.app,
                installation_id=state["installation_id"],
                host=database["host"],
                port=database["port"],
                database=database["name"],
                user=parts.username or "",
            ),
            secret=False,
        )
        for source in sorted((ROOT / "deployments" / self.app).glob("*.toml")):
            if source.name != "target.toml":
                shutil.copyfile(source, self.deployment_dir / source.name)
        pins = self.out / PINS
        pins.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "infra" / "capability-pins" / "research-capabilities.json", pins)

    def install_component(self, state: dict[str, Any], dsn: str, component: Path) -> None:
        common = ["--deployment-dir", str(self.deployment_dir), *RUNTIME_VERSIONS]
        confirm = f"{state['project_ref']}:{state['installation_id']}"
        receipts = self.out / "receipts"
        receipts.mkdir(parents=True, exist_ok=True)
        self.mission_db(
            "lock",
            "lock",
            "--app",
            self.app,
            "--component-root",
            str(component),
            "--deployments-root",
            str(self.out / "deployments"),
            dsn=dsn,
        )
        plan = self.mission_db("plan", "plan", *common, dsn=dsn)
        self.mission_db(
            "apply",
            "apply",
            *common,
            "--confirm-target",
            confirm,
            "--expected-plan-digest",
            str(plan.get("plan_digest", "")),
            dsn=dsn,
        )
        self.mission_db("verify", "verify", *common, dsn=dsn)
        descriptor = str(PACKAGE / "runtime" / "descriptor.json")
        self.mission_db(
            "runtime-apply",
            "runtime-apply",
            *common,
            "--descriptor",
            descriptor,
            "--confirm-target",
            confirm,
            "--receipt-out",
            str(receipts / "runtime-receipts.json"),
            dsn=dsn,
        )
        bundles: list[str] = []
        for directory in ("common", self.app):
            bundles += ["--bundle", str(PACKAGE / "seeds" / directory)]
        self.mission_db(
            "seed-apply", "seed-apply", *common, *bundles, "--confirm-target", confirm, dsn=dsn
        )
        logins_env = self.out / LOGINS_ENV
        self.mission_db(
            "login-apply",
            "login-apply",
            *common,
            "--descriptor",
            descriptor,
            "--login-prefix",
            state["login_prefix"],
            "--confirm-target",
            confirm,
            "--out-env",
            str(logins_env),
            "--sslmode",
            "disable",
            "--probe",
            # A login that exists without its DSN on file (a removed logins.env) gets a new
            # password; on a first install nothing exists yet and this changes nothing.
            *([] if logins_env.is_file() else ["--rotate"]),
            "--receipt-out",
            str(receipts / "login-receipt.json"),
            dsn=dsn,
        )

    def write_deployment(self, state: dict[str, Any], queue_base: str) -> dict[str, Any]:
        for name in (dep.OPERATOR_KEY, dep.OPERATOR_JWKS, dep.DEPLOYMENT):
            gen.assert_ignored(self.out / name)
        kid, jwks = dep.ensure_operator_key(self.out)
        gen.write_text(
            self.out / dep.OPERATOR_JWKS, json.dumps(jwks, indent=2) + "\n", secret=False
        )
        document = deployment_document(
            self.app,
            installation_id=state["installation_id"],
            tenant=state["tenant_id"],
            component_version=state["component_version"],
            queue_base=queue_base,
            temporal_address=state["temporal"]["address"],
            namespace=state["temporal"]["namespace"],
        )
        gen.write_text(
            self.out / dep.DEPLOYMENT, json.dumps(document, indent=2) + "\n", secret=False
        )
        binding = document["applications"][0]["authentication"]["binding"]
        self.record("deployment-file", binding_digest=binding["binding_digest"], operator_kid=kid)
        return document

    def apply_tenant(self, state: dict[str, Any], dsn: str) -> None:
        self.mission_db(
            "tenant-apply",
            "tenant-apply",
            "--deployment-dir",
            str(self.deployment_dir),
            *RUNTIME_VERSIONS,
            "--deployment-file",
            str(self.out / dep.DEPLOYMENT),
            "--confirm-target",
            f"{state['project_ref']}:{state['installation_id']}",
            "--receipt-out",
            str(self.out / "receipts" / "tenant-receipt.json"),
            dsn=dsn,
        )

    def rebuild_projection(self, state: dict[str, Any], dsn: str, workspace_root: Path) -> None:
        """The lexical-only capability search projection. It runs on the plane's admin variable;
        acceptable here only because the target is this local disposable database."""

        scope = f"mc/{state['installation_id']}/{self.app}/catalog"
        code, stdout = self.run(
            [
                sys.executable,
                "scripts/rebuild_capability_search_projection.py",
                "--tenant",
                scope,
                "--lexical-only",
            ],
            {
                "MISSION_CONTROL_HOME": self.out.as_posix(),
                "MISSION_CONTROL_APPLICATION": self.app,
                "MISSION_CONTROL_DEPLOYMENTS_ROOT": (self.out / "deployments").as_posix(),
                "MISSION_CONTROL_WORKSPACE_ROOT": workspace_root.as_posix(),
                "MISSION_CONTROL_CATALOG_SCOPE": scope,
                gen.db_name(self.app, "ADMIN_DSN"): dsn,
            },
        )
        body = self._json(stdout)
        verification = body.get("verification") or {}
        self.record(
            "projection-rebuild-lexical",
            exit=code,
            documents=(body.get("rebuild") or {}).get("selected_count"),
            verified=verification.get("valid"),
        )
        if code != 0 or verification.get("valid") is not True:
            raise Refused(
                "PROJECTION_REBUILD", f"the lexical projection did not verify (exit {code})"
            )

    def publish_bundles(self) -> None:
        code, stdout = self.run(
            [
                sys.executable,
                "scripts/seeds_publish_bundles.py",
                "--target",
                self.app,
                "--storage",
                f"local:{(self.out / 'bundles').as_posix()}",
            ],
            {"MISSION_CONTROL_HOME": self.out.as_posix()},
        )
        body = self._json(stdout)
        self.record(
            "seed-bundles",
            exit=code,
            bundles=len(body.get("bundles") or []),
            uploaded=body.get("uploaded_objects"),
            verified=body.get("verified_objects"),
            drift=len(body.get("seed_drift") or []),
        )
        if code != 0:
            raise Refused("SEED_BUNDLES", f"seed bundle publication failed (exit {code})")

    def copy_pinned_skill_bundles(self) -> list[str]:
        """Copy each `capability-bundles://` pinned skill from the checkout's offline store
        (`.runtime/capability-bundles`, `scripts/publish_skill_bundle.py`) into the custody root
        the worker reads; returns the digests that are not available."""

        from mission_control.adapters.capabilities.capability_bundles import (
            BundleError,
            DirectoryBundleStore,
        )
        from mission_control.adapters.capabilities.capability_pins import CapabilityPins

        source = ROOT / ".runtime" / "capability-bundles"
        target = self.out / "bundles"
        missing: list[str] = []
        scheme = "capability-bundles://"
        for skill in CapabilityPins.load(self.out / PINS).skills:
            if not skill.source_locator.startswith(scheme):
                continue
            digest = skill.source_locator.removeprefix(scheme)
            try:
                try:
                    DirectoryBundleStore(target).load(digest)
                    continue
                except (OSError, ValueError):  # absent, or not this bundle: publish it below
                    pass
                manifest, files = DirectoryBundleStore(source).load(digest)
                # Republish the verified bytes through the store's own publication path.
                with tempfile.TemporaryDirectory() as scratch:
                    for relative, content in files:
                        path = Path(scratch) / relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(content)
                    published = DirectoryBundleStore(target).publish(
                        Path(scratch), asset_id=manifest.asset_id, version=manifest.version
                    )
                if published.digest != digest:
                    raise BundleError("republished bundle differs from its pin")
            except (OSError, ValueError):  # BundleError and a malformed manifest are ValueErrors
                missing.append(digest)
        return missing

    def worker_prerequisites(self, workspace_root: Path, node: str | None) -> dict[str, Any]:
        """What the worker needs beyond this repository (reported, never invented): the capability
        resource owner's pinned modules, the pinned skill bundles and a Node executable."""

        from mission_control.adapters.capabilities.capability_pins import CapabilityPins
        from mission_control.bootstrap.preflight import check_pins

        missing: list[str] = []
        if node is None:
            missing.append("node: no Node executable on PATH (WEB_RESEARCH_AGENT_BROWSER_NODE)")
        pins = CapabilityPins.load(self.out / PINS)
        for issue in check_pins(pins, workspace_root, PINS):
            if issue.severity == "blocking":
                missing.append(f"{issue.code}: {issue.pointer}")
        for digest in self.copy_pinned_skill_bundles():
            missing.append(f"PINNED_SKILL_BUNDLE_UNAVAILABLE: {digest}")
        result = {
            "ready": not missing,
            "missing": missing,
            "capability_workspace_root": workspace_root.as_posix(),
        }
        self.record("worker-prerequisites", ready=result["ready"], missing=len(missing))
        return result

    def minted(self) -> str:
        """The checkpoint signing key: minted once, stable across reruns."""

        path = self.out / MINTED_ENV
        gen.assert_ignored(path)
        name = "RUNTIME_CHECKPOINT_SIGNING_KEY"
        value = read_env_file(path).get(name) or secrets.token_urlsafe(32)
        gen.write_text(
            path,
            render_env(
                [(name, value)], ["Minted by scripts/dev/local_installation.py; never commit."]
            ),
            secret=True,
        )
        return value

    def setup_temporal(self, address: str, namespace: str) -> None:
        host = address.rsplit(":", 1)[0].strip("[]")
        if host not in LOOPBACK_HOSTS:
            raise Refused(
                "TEMPORAL_NOT_LOOPBACK", "the local installation sets up a loopback Temporal only"
            )
        created = asyncio.run(ensure_namespace(address, namespace))
        self.record("temporal-namespace", namespace=namespace, created=created)
        code, _stdout = self.run(
            [
                sys.executable,
                "scripts/dev/temporal_search_attributes.py",
                "--address",
                address,
                "--namespace",
                namespace,
            ],
            {"MISSION_CONTROL_HOME": self.out.as_posix()},
            timeout=300,
        )
        self.record("temporal-search-attributes", exit=code)
        if code != 0:
            raise Refused("TEMPORAL_SEARCH_ATTRIBUTES", f"registration failed (exit {code})")

    def mint_token(self, state: dict[str, Any], ttl_minutes: int) -> Path:
        if not 1 <= ttl_minutes <= 24 * 60:
            raise Refused("TTL_INVALID", "--token-ttl-minutes must be between 1 and 1440")
        path = self.out / dep.TOKEN
        gen.assert_ignored(path)
        bearer = dep.mint_token(
            self.out,
            self.app,
            tenant=state["tenant_id"],
            ttl_minutes=ttl_minutes,
            subject=OPERATOR_SUBJECT,
        )
        gen.write_text(path, bearer + "\n", secret=True)
        self.record("operator-token", file=path.name, ttl_minutes=ttl_minutes)
        return path

    # -- commands ------------------------------------------------------------------------------

    def install(self) -> dict[str, Any]:
        self.guard()
        admin, source = admin_dsn(self.args.admin_dsn_env)
        if self.args.recreate:
            self.recreate(admin)
        component, manifest = release_manifest(self.args.component_version)
        profile = load_profile(self.app)
        installation = profile["installation"]
        workspace_root = (
            self.args.workspace_root or ROOT / installation["capability_workspace_root"]
        ).resolve()
        state = self.identity(admin)
        state["component_version"] = manifest["component_version"]
        state["temporal"] = {
            "address": self.args.temporal_address,
            "namespace": self.args.temporal_namespace or temporal_namespace(self.app),
            "queue_base": installation["temporal_task_queue"],
        }
        self.out.mkdir(parents=True, exist_ok=True)
        gen.write_text(self.out / STATE, json.dumps(state, indent=2) + "\n", secret=False)
        database = state["database"]
        created = asyncio.run(
            ensure_database(admin, database["name"], postgres_major=manifest["postgres_major"])
        )
        self.record("database", admin=source, name=database["name"], **created)
        dsn = with_database(admin, database["name"])
        self.write_inputs(state, admin)
        self.install_component(state, dsn, component)
        document = self.write_deployment(state, installation["temporal_task_queue"])
        self.apply_tenant(state, dsn)
        self.rebuild_projection(state, dsn, workspace_root)
        self.publish_bundles()
        node = shutil.which("node")
        worker = self.worker_prerequisites(workspace_root, node)
        binding = document["applications"][0]["authentication"]["binding"]
        entries = runtime_environment(
            self.app,
            self.out,
            installation_id=state["installation_id"],
            binding_digest=binding["binding_digest"],
            logins=read_env_file(self.out / LOGINS_ENV),
            signing_key=self.minted(),
            profile=profile,
            workspace_root=workspace_root,
            temporal_address=state["temporal"]["address"],
            namespace=state["temporal"]["namespace"],
            node=node,
            hook_callback_port=self.args.hook_callback_port or hook_callback_port(self.app),
        )
        gen.write_text(
            self.out / ENV_FILE,
            render_env(
                entries,
                [
                    f"Mission Control API and worker: local installation of {self.app}.",
                    "Generated by scripts/dev/local_installation.py; ignored.",
                    "Never commit or print: it holds the restricted logins and a signing key.",
                    "Every database variable is set or blank and no .env is layered beneath it.",
                ],
            ),
            secret=True,
        )
        self.record("env-file", file=ENV_FILE, names=len(entries))
        if self.args.skip_temporal_setup:
            self.record("temporal", skipped=True)
        else:
            self.setup_temporal(state["temporal"]["address"], state["temporal"]["namespace"])
        token = self.mint_token(state, self.args.token_ttl_minutes)
        state.update(
            {
                "binding_digest": binding["binding_digest"],
                "worker": worker,
                "installed_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )
        gen.write_text(self.out / STATE, json.dumps(state, indent=2) + "\n", secret=False)
        return {
            "status": "ready",
            "application": self.app,
            "directory": self.out.as_posix(),
            "installation_id": state["installation_id"],
            "tenant_id": state["tenant_id"],
            "component_version": state["component_version"],
            "binding_digest": binding["binding_digest"],
            "database": {**database, **created},
            "temporal": state["temporal"],
            "files": {
                "env": (self.out / ENV_FILE).as_posix(),
                "deployment": (self.out / dep.DEPLOYMENT).as_posix(),
                "operator_token": token.as_posix(),
            },
            "worker": worker,
            "steps": self.steps,
        }

    def token(self) -> dict[str, Any]:
        self.guard()
        state = load_state(self.out)
        if state is None:
            raise Refused("NOT_INSTALLED", f"{self.out} holds no installation; run install first")
        path = self.mint_token(state, self.args.token_ttl_minutes)
        return {"status": "written", "token_file": path.as_posix(), "subject": OPERATOR_SUBJECT}

    def container(self) -> dict[str, Any]:
        """Derive what deployments/docker/compose.yml reads from the installed host files: the
        same binding, logins and keys; only paths and network names differ. No database change."""

        self.guard()
        state = load_state(self.out)
        entries = list(read_env_file(self.out / ENV_FILE).items())
        if state is None or not entries:
            raise Refused("NOT_INSTALLED", f"{self.out} holds no installation; run install first")
        for name in (CONTAINER_ENV_FILE, CONTAINER_DEPLOYMENT):
            gen.assert_ignored(self.out / name)
        document = json.loads((self.out / dep.DEPLOYMENT).read_text(encoding="utf-8"))
        temporal_address = self.args.container_temporal_address
        document["applications"][0]["temporal"]["address"] = temporal_address
        gen.write_text(
            self.out / CONTAINER_DEPLOYMENT, json.dumps(document, indent=2) + "\n", secret=False
        )
        derived = container_environment(
            entries,
            out=self.out,
            database_host=self.args.container_db_host,
            database_port=self.args.container_db_port,
            temporal_address=temporal_address,
            redis_url=self.args.container_redis_url,
        )
        gen.write_text(
            self.out / CONTAINER_ENV_FILE,
            render_env(
                derived,
                [
                    f"Mission Control API and worker containers: local installation of {self.app}.",
                    "Derived by scripts/dev/local_installation.py container; ignored.",
                    "Never commit or print: it holds the restricted logins and a signing key.",
                ],
            ),
            secret=True,
        )
        self.record("container-env", file=CONTAINER_ENV_FILE, names=len(derived))
        return {
            "status": "written",
            "env_file": (self.out / CONTAINER_ENV_FILE).as_posix(),
            "deployment_file": (self.out / CONTAINER_DEPLOYMENT).as_posix(),
            "mounts": {
                "deployment_directory": CONTAINER_HOME,
                "capability_workspace_root": CONTAINER_WORKSPACE,
            },
            "database": f"{self.args.container_db_host}:{self.args.container_db_port}",
            "temporal_address": temporal_address,
        }


async def ensure_namespace(address: str, namespace: str) -> bool:
    """Create ``namespace`` on the loopback Temporal server when it is absent; True if created."""

    from google.protobuf.duration_pb2 import Duration
    from temporalio.api.workflowservice.v1 import (
        DescribeNamespaceRequest,
        RegisterNamespaceRequest,
    )
    from temporalio.service import RPCError, RPCStatusCode

    from mission_control.adapters.temporal.client import TemporalConnection, connect_temporal

    try:
        async with asyncio.timeout(30):
            client = await connect_temporal(
                TemporalConnection(target="local", address=address, namespace=namespace)
            )
            try:
                await client.workflow_service.describe_namespace(
                    DescribeNamespaceRequest(namespace=namespace)
                )
                return False
            except RPCError as error:
                if error.status != RPCStatusCode.NOT_FOUND:
                    raise
            await client.workflow_service.register_namespace(
                RegisterNamespaceRequest(
                    namespace=namespace,
                    workflow_execution_retention_period=Duration(seconds=7 * 86400),
                )
            )
            return True
    except (TimeoutError, RuntimeError, RPCError, OSError) as error:
        raise Refused(
            "TEMPORAL_UNAVAILABLE",
            f"no Temporal server answered at {address} ({type(error).__name__}); start one "
            "(`make temporal-up`, or `temporal server start-dev`) or pass --skip-temporal-setup",
        ) from None


# ------------------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "command", nargs="?", choices=("install", "token", "container"), default="install"
    )
    parser.add_argument("--app", choices=APPLICATIONS, default=DEFAULT_APPLICATION)
    parser.add_argument(
        "--out", type=Path, help="default .scratch/local-stack/<app> (must be ignored)"
    )
    parser.add_argument(
        "--admin-dsn-env",
        default=ADMIN_DSN_ENV,
        help=f"NAME of the variable holding the loopback admin DSN (default {ADMIN_DSN_ENV}; "
        "unset: the compose application-postgres-17 service)",
    )
    parser.add_argument(
        "--recreate", action="store_true", help="drop the local database and rebuild"
    )
    parser.add_argument("--component-version", default=COMPONENT_VERSION)
    parser.add_argument("--workspace-root", type=Path, help="the capability resource owner")
    parser.add_argument("--temporal-address", default=TEMPORAL_ADDRESS)
    parser.add_argument("--temporal-namespace", help="default mc-local-<app>")
    parser.add_argument("--skip-temporal-setup", action="store_true")
    parser.add_argument(
        "--hook-callback-port", type=int, help=f"default {HOOK_CALLBACK_PORT} + application index"
    )
    parser.add_argument("--token-ttl-minutes", type=int, default=TOKEN_TTL_MINUTES)
    container = parser.add_argument_group("container (deployments/docker/compose.yml)")
    container.add_argument("--container-db-host", default="application-postgres-17")
    container.add_argument("--container-db-port", type=int, default=5432)
    container.add_argument("--container-temporal-address", default="host.docker.internal:7233")
    container.add_argument("--container-redis-url", default="redis://redis:6379/0")
    return parser


def run(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    args = build_parser().parse_args(argv)
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", args.admin_dsn_env):
        return 2, {"status": "refused", "code": "ADMIN_DSN_ENV", "error": "name a variable"}
    installer = Installer(args)
    # Settings computed in this process layer `<MISSION_CONTROL_HOME>/.env`: point them at the
    # installation directory before any Mission Control module loads, so no `.env` is ever read.
    os.environ["MISSION_CONTROL_HOME"] = str(installer.out)
    commands = {
        "install": installer.install,
        "token": installer.token,
        "container": installer.container,
    }
    try:
        document = commands[args.command]()
    except Refused as refused:
        return 2, {
            "status": "refused",
            "code": refused.code,
            "error": str(refused),
            "steps": installer.steps,
        }
    return 0, document


def main() -> None:
    code, document = run()
    sys.stdout.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
