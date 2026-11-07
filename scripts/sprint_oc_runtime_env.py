"""Sprint OC W0 (WI-24, OVE-168): compose the local W1 runtime environment of one application.

Reads the owner's existing `.env` files (MC, AI Engineer; parsed by python-dotenv, as MC's
own settings loader does), the tracked `deployments/<app>` target, Application Profile and (biotech)
graph pin, and an install receipt. Writes one IGNORED env file per process under `<out-dir>/<app>/`
(default `.scratch/sprint-oc/runtime/<app>/` in this repository):

- `install.env`         the names the root installer reads: its `seal-key` step (OVE-169 W1 D25:
                        `KS_KNOWLEDGE_SEAL_KEY_ID/_FILE/_ISSUER`, both apps) and (biotech) the
                        names `install-biotech.mjs` checks at `executor-config`
- `ks-executor.env`     KS `verification-executor serve` (K01 `/knowledge-operation/v2`)
- `bks-executor.env`    (biotech) BKS `apps/executor` (graph reads, admission dispatch consumer)
- `mission-control.env` Mission Control API, worker and Agent Server
- `minted.env`          the values this installation mints itself (stable across reruns)
- key files             the MC knowledge-issuer Ed25519 JWK + public JWKS, the KS seal key (PKCS#8)
- `manifest.json`       every name, its source and what is missing; never a value

Owner `.env` isolation: MC settings always layer `<MISSION_CONTROL_HOME or cwd>/.env` beneath the
process environment, and an environment variable that is present, even empty, wins. So
`mission-control.env` names every database (`MC_{AIENG,BIOTECH,LOCAL}_DB_*`), storage, bucket,
vault and credential setting MC reads: an explicit value, or an explicit blank (fail closed) for
the ones this topology must not inherit. A missing required name is also written blank, never
left to the `.env`.

Remote PostgreSQL DSNs are rewritten to `sslmode=verify-full&sslrootcert=<CA>` (the Supabase
public root, `--ca-file`, always parsed as an X.509 PEM). Each DSN must name the target project
exactly (`db.<ref>.supabase.co`, or a pooler login `<role>.<ref>`). The `knowledge_verification`
tenant is minted once (or `--verification-tenant-id`, one only); the W1 operator grants must use it.
Neo4j credentials are written only when `--confirm-graph` names the host pinned in
`deployments/biotech/graph.toml`. `BKS_BIOTECH_DB_VERIFICATION_DSN` is a restricted integrator
login; the
Biotech admin DSN (`MC_BIOTECH_DB_ADMIN_DSN`) is used only with `--allow-admin-verification-dsn`
(disposable W0), recorded in the manifest.

Values are never printed: stdout carries names, sources and the missing list only. Every output
path must be ignored (and untracked) by its Git repository. Secret files are created owner-only
(`0o600`; on Windows inheritance is removed and only the current user is granted, then verified).
`minted.env` is written before the key files, and an existing JWK's kid is adopted, so an
interrupted run never strands the next one. Installation ids come from an install receipt
(`--receipt`), `--component-installation-id`, or `installation-ids.json` (`--ids-file`, default
`<out-dir>/installation-ids.json` when present); without one the script refuses rather than
guessing. RUNTIME-ENVIRONMENT.md (sprint-oc/release) is the matrix this follows.

Usage (from the Mission Control repository root):
  uv run --no-sync python scripts/sprint_oc_runtime_env.py --app biotech \\
    [--component-installation-id <uuid> | --receipt <install-receipt.json> | --ids-file <json>] \\
    [--ca-file <supabase-prod-ca-2021.crt>] [--verification-tenant-id <uuid>] \\
    [--confirm-graph <pinned Aura host>] [--allow-admin-verification-dsn] \\
    [--allow-checkpoint-fallback] [--mc-root <Mission Control checkout>] \\
    [--integrator-env <ignored file>] [--deployment-file <operator deployment.json>] \\
    [--bellabs-root <dir>] [--out-dir <dir>] [--require-complete]

Exit: 0 written; 2 refused (no env file written); 3 `--require-complete` with missing names (or
a missing checkpointer DSN without `--allow-checkpoint-fallback`): the
incomplete env files are written only as `<name>.incomplete` and any runnable copy is removed.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import tomllib
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from dotenv import dotenv_values

# The Mission Control checkout this script lives in: the default `--mc-root`.
MC_ROOT = Path(__file__).resolve().parents[1]
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
BARE = re.compile(r"^[A-Za-z0-9_./:@,+=%-]*$")
PROJECT_REF = re.compile(r"^[a-z0-9]{20}$")

# Owner `.env` files, relative to the BellLabs root (H2: the names already present there).
# The Biotech graph login comes from the MC `.env` (`MC_BIOTECH_GRAPH_*`, the same Aura login
# BKS holds as `BKS_BIOTECH_GRAPH_*`); no BKS `.env` is read.
MC_ENV = "platform/mission-control/.env"
AIE_ENV = "aiengineer/.env"

# Loopback ports of the local W1 topology; distinct per application so both can run at once.
PORTS: dict[str, dict[str, int]] = {
    "ai-engineer": {"ks_executor": 4310, "mc_api": 8000, "agent_server": 2024},
    "biotech": {"ks_executor": 4311, "bks_executor": 4020, "mc_api": 8001, "agent_server": 2025},
}
TEMPORAL_ADDRESS = "127.0.0.1:7233"
LOCAL_REDIS = "redis://127.0.0.1:16379/0"  # the settings default (compose Redis)
RUNTIME_OPTIONS_FACTORY = "mission_control.bootstrap.local_operator:runtime_options"
JUDGE_KEY = "MC_JUDGE_OPENAI_API_KEY"
AUDITOR_KEY = "MC_AUDITOR_ANTHROPIC_API_KEY"

# Per application: the KS component binding entry and the DSN its `databaseUrlEnv` names.
COMPONENT_DSN = {
    "biotech": ("KS_BIOTECH_DB_COMPONENT_DSN", MC_ENV, "MC_BIOTECH_DB_ADMIN_DSN"),
    "ai-engineer": ("KS_AIENG_DB_COMPONENT_DSN", AIE_ENV, "AIENG_DB_ADMIN_DSN"),
}
RECEIPT_FORMAT = {
    "biotech": "biotech-install-receipt.v1",
    "ai-engineer": "ai-engineer-install-receipt.v1",
}
# The database plane token of each application (`Settings.db_plane`).
PLANE = {"ai-engineer": "AIENG", "biotech": "BIOTECH"}
# Every MC database variable (`MC_{AIENG,BIOTECH,LOCAL}_DB_*`, secret or not, except the local port)
# is written explicitly by the generator or blanked, so an owner `.env` cannot be inherited.
_DB_ROLES = (
    "PROJECT_REF",
    "URL",
    "PUBLISHABLE_KEY",
    "SECRET_KEY",
    "LEGACY_JWT_SECRET",
    "ADMIN_DSN",
    "RUNTIME_DSN",
    "FAMILY_WRITER_DSN",
    "BACKFILL_DSN",
    "CHECKPOINT_DSN",
)
MC_DB_BLANKED = tuple(
    f"MC_{plane}_DB_{role}"
    for plane in ("AIENG", "BIOTECH", "LOCAL")
    for role in _DB_ROLES
    if plane != "LOCAL"
    or role not in {"PROJECT_REF", "URL", "PUBLISHABLE_KEY", "SECRET_KEY", "LEGACY_JWT_SECRET"}
)


def db_name(app: str, role: str) -> str:
    """The selected plane's variable, e.g. ``MC_AIENG_DB_RUNTIME_DSN``."""

    return f"MC_{PLANE[app]}_DB_{role}"


def integrator_names(app: str) -> tuple[str, ...]:
    """Integrator-supplied names (`--integrator-env`): restricted logins no owner `.env` holds
    (the names ``mission-db login-apply`` writes for the application's plane)."""

    return (
        db_name(app, "RUNTIME_DSN"),
        db_name(app, "FAMILY_WRITER_DSN"),
        db_name(app, "CHECKPOINT_DSN"),
        "BKS_BIOTECH_DB_VERIFICATION_DSN",
    )


MINTED_TOKENS = (
    "KS_BIOTECH_EXECUTOR_TOKEN",
    "KS_BIOTECH_EXECUTOR_READ_TOKEN",
    "BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN",
    "RUNTIME_CHECKPOINT_SIGNING_KEY",
)
# MC settings this topology must NOT inherit from an owner `.env` (`bootstrap/settings.py`): every
# database, storage, bucket, vault and credential setting the generator does not set explicitly.
# Written as explicit blanks; their consumers treat an empty value as unconfigured (fail closed).
# A unit test checks this set against every `SecretStr` field of the real `Settings`.
MC_BLANKED = (
    "S3_BUCKET",
    "S3_ENDPOINT_URL",
    "S3_REGION",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "INGRESS_QUARANTINE_BUCKET",
    "INGRESS_CUSTODY_BUCKET",
    "INGRESS_STORAGE_CREDENTIAL",
    "INGRESS_LISTEN_SECRET_REF",
    "MISSION_CONTROL_SECRET_VAULT_DSN",
    "CAPABILITY_BUNDLE_PUBLISHER_TOKEN",
    "CAPABILITY_BUNDLE_READER_TOKEN",
    "INSPECTION_CURSOR_KEY",
    "BELL_LABS_TRACE_PSEUDONYM_KEY",
    "BELL_LABS_AGENT_AUTH_PUBLIC_KEY",
    "TEMPORAL_CLOUD_API_KEY",
    "CURSOR_API_KEY",
    # `str | None` settings whose readers treat a blank as unset (truthiness or `.strip()`).
    "COORDINATOR_MCP_JWT_ISSUER",
    "LANGSMITH_WORKSPACE_ID",
    "CAPABILITY_BUNDLE_NAMESPACE",
    "TEMPORAL_BUILD_ID",
    "KNOWLEDGE_ISSUER_RETIRING_KEY_ID",
    "MISSION_CONTROL_PAYLOAD_SHARED_ID",
)
# MC settings with a non-None default, written as that default so an owner `.env` cannot override
# them (a unit test compares each to the real `Settings` default). CAPABILITY_PINS_PATH is
# `<MISSION_CONTROL_HOME>/infra/...` and is written separately.
MC_DEFAULTS = {
    "LANGSMITH_ENDPOINT": "https://api.smith.langchain.com",
    "BELL_LABS_AGENT_AUTH_AUDIENCE": "authenticated",
    "COORDINATOR_MCP_MOUNT_PATH": "/mcp/coordinator",
    "COORDINATOR_MCP_JWT_AUDIENCE": "authenticated",
    "MCP_REGISTRY_BASE_URL": "https://registry.modelcontextprotocol.io",
    "NPX_SKILLS_EXECUTABLE": "npx",
    "NPX_SKILLS_PACKAGE_VERSION": "1.5.20",
    "OPERATION_JOURNAL_CLAIMED_BY": "operation-runtime:belllabs",
    "ASYNC_SUBAGENT_SUBMITTER_IDENTITY": "belllabs-async-submitter",
    "KNOWLEDGE_SUBJECT": "mission-control-runtime",
    "AWS_REGION": "us-east-1",
    "AWS_PROFILE": "default",
    "TEMPORAL_DEPLOYMENT_NAME": "mission-control",
    "MISSION_CONTROL_FRAME_CAPTURE_PROFILE": "standard",
    "MISSION_CONTROL_CODEX_BINARY": "codex",
    "MISSION_CONTROL_SECRET_STORE": "none",
    "MISSION_CONTROL_SECRET_KEYRING_SERVICE": "mission-control",
    "SANDBOX_IMAGE": "python:3.12-slim",
    "API_HOST": "127.0.0.1",
    "SOCKETIO_CORS_ORIGINS": "http://localhost:3000,http://127.0.0.1:3000",
}
_PATH_UNSET = "a Path or length-checked setting: a blank would not read as unset"
# The allowlist: `str`/`Path` settings the generated file does NOT set, each with why that is
# harmless. None of them can be blanked (see `_PATH_UNSET`), so the generator refuses an owner MC
# `.env` that sets any of them (`OWNER_ENV_SETS_UNMANAGED`); rerun it after editing that `.env`.
MC_UNMANAGED = {
    "AGENT_SERVER_DEPLOYMENT_ENDPOINT_ID": "no reader through Settings",
    "AGENT_SERVER_DEPLOYMENT_REVISION": "no reader through Settings",
    "BELL_LABS_AGENT_AUTH_ISSUER": "the Agent Server reads its own process env, not Settings",
    "BELL_LABS_AGENT_AUTH_JWKS_URI": "the Agent Server reads its own process env, not Settings",
    "CHAIN_RELAY_LEASE_OWNER": f"read only with CHAIN_RELAY_ENABLED; {_PATH_UNSET}",
    "MISSION_CONTROL_SIGNAL_INGRESS_ORIGIN": "local signal ingress is off; checked `is not None`",
    "CURSOR_LOCAL_REPOSITORY": "the Cursor lanes are off (no CURSOR_API_KEY)",
    "MISSION_CONTROL_CODEX_REPOSITORY": "the Codex lanes are off",
    "WEB_RESEARCH_FIRECRAWL_MCP_COMMAND": "no reader through Settings",
    "WEB_RESEARCH_TAVILY_MCP_COMMAND": "no reader through Settings",
    "MANIFEST_LAUNCH_BINDINGS_PATH": (
        "W1 harness file the launcher sets; the worker requires it with CHAIN_RELAY_ENABLED; "
        f"{_PATH_UNSET}"
    ),
    "MISSION_CONTROL_OWNER_PROBES_PATH": f"operator file; unset = feature off; {_PATH_UNSET}",
    "MISSION_CONTROL_INSTALLATION_CONFIG_PATH": f"W1 harness operator file; {_PATH_UNSET}",
    "MISSION_CONTROL_AUTH_PROFILES_PATH": f"credential-route lanes are off; {_PATH_UNSET}",
    "MISSION_CONTROL_LOCAL_RUN_PROFILE": f"W1 harness operator file; {_PATH_UNSET}",
    "MISSION_CONTROL_PREFLIGHT_WORKSPACE_ROOT": "unset = MISSION_CONTROL_WORKSPACE_ROOT",
    "CAPABILITY_BUNDLE_LOCAL_ROOT": f"unset = no directory bundle reader; {_PATH_UNSET}",
    "KNOWLEDGE_ISSUER_RETIRING_KEY_FILE": f"unset = no retiring key; {_PATH_UNSET}",
    "CURSOR_LEASE_ROOT": "the Cursor lanes are off",
    "MISSION_CONTROL_CLAUDE_LEASE_ROOT": "the Claude lane is off",
    "MISSION_CONTROL_CODEX_LEASE_ROOT": "the Codex lanes are off",
    "MISSION_CONTROL_CODEX_OWNER_HOME": "the Codex lanes are off",
    "MISSION_CONTROL_SECRET_STORE_PATH": "MISSION_CONTROL_SECRET_STORE is none",
}
GRAPH_PIN = "deployments/biotech/graph.toml"


class Refused(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Entry:
    name: str
    value: str | None
    source: str  # owner:<file>:<NAME> | minted | derived:<what> | integrator:<NAME> | constant
    needs: str | None = None  # why it is missing and who supplies it
    required: bool = True


@dataclass
class Context:
    app: str
    bellabs: Path
    out: Path
    component_installation_id: str
    mc_installation_id: str
    project_ref: str
    profile: dict[str, Any]
    owner: dict[str, dict[str, str]]
    integrator: dict[str, str]
    minted: dict[str, str]
    tenants: tuple[str, ...]
    confirm_graph: str | None
    deployment_file: Path | None
    binding_digest: str | None
    # The operator deployment's Temporal namespace (one per application; OVE-169).
    temporal_namespace: str = "default"
    ca_file: Path | None = None
    allow_admin_verification_dsn: bool = False
    graph_pin: dict[str, Any] | None = None
    choices: dict[str, str] = field(default_factory=dict)
    mc_root: Path = MC_ROOT
    allow_checkpoint_fallback: bool = False
    warnings: list[str] = field(default_factory=list)
    # The publisher token goes only to the operator file (`bundle-publisher.env`).
    publisher: Entry | None = None


# ------------------------------------------------------------------------------------- inputs


def read_env(path: Path) -> dict[str, str]:
    """A dotenv file parsed by python-dotenv (quotes, escapes, interpolation); absent: empty."""

    if not path.is_file():
        return {}
    return {
        key: value
        for key, value in dotenv_values(path, encoding="utf-8-sig").items()
        if value is not None
    }


def find_bellabs_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "platform" / "mission-control").is_dir() and (
            candidate / "biotech"
        ).is_dir():
            return candidate
    raise Refused("BELLABS_ROOT_NOT_FOUND", "pass --bellabs-root <dir>")


def ids_from_receipt(path: Path, app: str) -> tuple[str, str]:
    """(component installation id, Mission Control installation id) recorded by an installer."""

    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Refused("RECEIPT_INVALID", f"{path} is not a readable JSON receipt") from error
    if receipt.get("format") != RECEIPT_FORMAT[app]:
        raise Refused("RECEIPT_FORMAT_MISMATCH", f"{path} is not a {RECEIPT_FORMAT[app]}")
    steps = {step.get("step"): step for step in receipt.get("steps", []) if isinstance(step, dict)}
    ids = []
    for name in ("component", "mission-control"):
        value = ((steps.get(name) or {}).get("details") or {}).get("installationId")
        if not isinstance(value, str) or not UUID.match(value):
            raise Refused("RECEIPT_INCOMPLETE", f"{path} records no {name} installationId")
        ids.append(value)
    return ids[0], ids[1]


def binding_digest_from(path: Path, app: str, installation_id: str) -> str:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Refused("DEPLOYMENT_FILE_INVALID", f"{path} is not readable JSON") from error
    for item in document.get("applications", []):
        binding = (item.get("authentication") or {}).get("binding") or {}
        if binding.get("application_id") == app:
            if binding.get("installation_id") != installation_id:
                raise Refused(
                    "DEPLOYMENT_INSTALLATION_MISMATCH",
                    f"{path} binding is not target.toml's installation",
                )
            digest = binding.get("binding_digest")
            if not isinstance(digest, str) or not re.match(r"^sha256:[0-9a-f]{64}$", digest):
                raise Refused("DEPLOYMENT_FILE_INVALID", f"{path} binding has no binding_digest")
            return digest
    raise Refused("DEPLOYMENT_APPLICATION_MISSING", f"{path} configures no {app} application")


def temporal_namespace_from(path: Path, app: str) -> str:
    """The deployment's Temporal namespace for ``app`` (``default`` when it names none)."""

    document = json.loads(path.read_text(encoding="utf-8"))
    for item in document.get("applications", []):
        binding = (item.get("authentication") or {}).get("binding") or {}
        if binding.get("application_id") == app:
            namespace = (item.get("temporal") or {}).get("namespace") or "default"
            if not isinstance(namespace, str) or not re.fullmatch(
                r"[A-Za-z0-9._-]{1,64}", namespace
            ):
                raise Refused("DEPLOYMENT_FILE_INVALID", f"{path} temporal namespace is invalid")
            return namespace
    raise Refused("DEPLOYMENT_APPLICATION_MISSING", f"{path} configures no {app} application")


def load_graph_pin(mc_root: Path = MC_ROOT) -> dict[str, Any]:
    document = tomllib.loads((mc_root / GRAPH_PIN).read_text(encoding="utf-8"))
    graph = document.get("graph") or {}
    refused = tuple((document.get("refuse") or {}).get("aura_instance_ids") or ())
    host, instance = graph.get("host"), graph.get("aura_instance_id")
    if (
        graph.get("app") != "biotech"
        or not host
        or not instance
        or not host.startswith(f"{instance}.")
    ):
        raise Refused("GRAPH_PIN_INVALID", f"{GRAPH_PIN} names no biotech host/instance pair")
    return {"host": host.lower(), "instance": instance, "refused": refused}


def validate_ca(path: Path) -> None:
    try:
        x509.load_pem_x509_certificate(path.read_bytes())
    except (OSError, ValueError) as error:
        raise Refused(
            "CA_FILE_INVALID", f"{path} is not a readable X.509 PEM certificate"
        ) from error


# ------------------------------------------------------------------------------------- git guard


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
        raise Refused(
            "OUTPUT_NOT_IN_REPOSITORY", f"{path} is in no Git work tree; ignore status unprovable"
        )
    root = Path(top.stdout.strip()).resolve()
    relative = Path(os.path.relpath(path.resolve(), root)).as_posix()
    if _git(root, "ls-files", "--error-unmatch", "--", relative).returncode == 0:
        raise Refused("OUTPUT_TRACKED", f"{relative} is tracked by {root}")
    if _git(root, "check-ignore", "-q", "--", relative).returncode != 0:
        raise Refused("OUTPUT_NOT_IGNORED", f"{relative} is not ignored by {root}")


# ------------------------------------------------------------------------------------- files


def _harden(path: Path) -> None:
    """Owner-only access: mode 0o600 (0o700 for a directory); on Windows no inherited ACEs and
    only the current user (a directory's grant is inherited by what is created inside it)."""

    directory = path.is_dir()
    if os.name != "nt":
        path.chmod(0o700 if directory else 0o600)
        if path.stat().st_mode & 0o077:
            raise Refused("SECRET_FILE_PERMISSIONS", f"{path} is readable by others")
        return
    user = os.environ.get("USERNAME", "")
    if not user:
        raise Refused("SECRET_FILE_PERMISSIONS", "USERNAME is not set; cannot restrict the ACL")
    granted = subprocess.run(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"{user}:{'(OI)(CI)F' if directory else 'F'}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if granted.returncode != 0:
        raise Refused("SECRET_FILE_PERMISSIONS", f"icacls could not restrict {path}")
    principals = acl_principals(path)
    if not principals or any(
        inherited or principal.split("\\")[-1].lower() != user.lower()
        for principal, inherited in principals
    ):
        raise Refused("SECRET_FILE_PERMISSIONS", f"{path} grants more than {user}")


def acl_principals(path: Path) -> list[tuple[str, bool]]:
    """(principal, inherited) for each ACE of ``path`` as `icacls` lists them (Windows)."""

    listing = subprocess.run(
        ["icacls", str(path)], capture_output=True, text=True, check=False
    ).stdout
    found: list[tuple[str, bool]] = []
    for line in listing.splitlines():
        text = line.strip()
        if not text:
            break
        if text.lower().startswith(str(path).lower()):
            text = text[len(str(path)) :].strip()
        match = re.match(r"^(.+?):((?:\([A-Z,]+\))+)$", text)
        if match:
            found.append((match.group(1), "(I)" in match.group(2)))
    return found


def write_text(path: Path, text: str, *, secret: bool) -> None:
    """Write via a temporary sibling; a secret's sibling is restricted before any byte lands."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    with contextlib.suppress(FileNotFoundError):
        temporary.unlink()
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    try:
        if secret:
            _harden(temporary)
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        temporary.replace(path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
    if secret:
        _harden(path)


# ------------------------------------------------------------------------------------- minting


def mint_values(out: Path) -> tuple[dict[str, str], list[str]]:
    """Reuse `minted.env` (and an existing JWK's kid); mint only absent values."""

    existing = read_env(out / "minted.env")
    values: dict[str, str] = {}
    fresh: list[str] = []
    for name in MINTED_TOKENS:
        values[name] = existing.get(name) or secrets.token_urlsafe(32)
        if not existing.get(name):
            fresh.append(name)
    jwk_kid = None
    jwk = out / "knowledge-issuer.jwk.json"
    if jwk.is_file():
        try:
            jwk_kid = json.loads(jwk.read_text(encoding="utf-8")).get("kid")
        except ValueError as error:
            raise Refused("ISSUER_KEY_INVALID", f"{jwk} is not JSON") from error
    recorded = existing.get("KNOWLEDGE_ISSUER_KEY_ID")
    if recorded and jwk_kid and recorded != jwk_kid:
        raise Refused("ISSUER_KEY_INVALID", f"{jwk} kid differs from minted.env")
    values["KNOWLEDGE_ISSUER_KEY_ID"] = (
        recorded or jwk_kid or f"mc-knowledge-{secrets.token_hex(4)}"
    )
    if not recorded:
        fresh.append("KNOWLEDGE_ISSUER_KEY_ID")
    values["KS_KNOWLEDGE_SEAL_KEY_ID"] = (
        existing.get("KS_KNOWLEDGE_SEAL_KEY_ID") or f"ks-seal-{secrets.token_hex(4)}"
    )
    if not existing.get("KS_KNOWLEDGE_SEAL_KEY_ID"):
        fresh.append("KS_KNOWLEDGE_SEAL_KEY_ID")
    tenant = existing.get("KNOWLEDGE_VERIFICATION_TENANT_ID") or ""
    if not UUID.match(tenant):
        tenant = str(uuid.uuid4())
        fresh.append("KNOWLEDGE_VERIFICATION_TENANT_ID")
    values["KNOWLEDGE_VERIFICATION_TENANT_ID"] = tenant
    return values, fresh


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def check_keys(out: Path, issuer_kid: str) -> None:
    private_jwk = out / "knowledge-issuer.jwk.json"
    if private_jwk.is_file():
        document = json.loads(private_jwk.read_text(encoding="utf-8"))
        if (
            document.get("crv") != "Ed25519"
            or not document.get("d")
            or document.get("kid") != issuer_kid
        ):
            raise Refused(
                "ISSUER_KEY_INVALID", f"{private_jwk} is not the Ed25519 key {issuer_kid}"
            )


def ensure_keys(out: Path, issuer_kid: str) -> list[str]:
    """Write the MC issuer JWK/JWKS and the KS seal key once; reuse them afterwards."""

    fresh: list[str] = []
    private_jwk, public_jwks = out / "knowledge-issuer.jwk.json", out / "knowledge-issuer.jwks.json"
    if private_jwk.is_file():
        document = json.loads(private_jwk.read_text(encoding="utf-8"))
        public = {key: document[key] for key in ("kty", "crv", "x")}
        _harden(private_jwk)
    else:
        key = Ed25519PrivateKey.generate()
        raw_private = key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        raw_public = key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        public = {"kty": "OKP", "crv": "Ed25519", "x": _b64url(raw_public)}
        document = {**public, "d": _b64url(raw_private), "kid": issuer_kid, "alg": "EdDSA"}
        write_text(private_jwk, json.dumps(document), secret=True)
        fresh.append(private_jwk.name)
    jwks = {"keys": [{**public, "kid": issuer_kid, "alg": "EdDSA", "use": "sig"}]}
    write_text(public_jwks, json.dumps(jwks, indent=2) + "\n", secret=False)
    seal = out / "ks-seal.pem"
    if seal.is_file():
        _harden(seal)
    else:
        pem = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        write_text(seal, pem.decode("ascii"), secret=True)
        fresh.append(seal.name)
    return fresh


# ------------------------------------------------------------------------------------- DSNs


def tls_dsn(dsn: str, ca_file: Path) -> str:
    """``dsn`` with exactly ``sslmode=verify-full`` and ``sslrootcert=<ca_file>``; others kept."""

    parts = urlsplit(dsn)
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in {"sslmode", "sslrootcert"}
    ]
    query += [("sslmode", "verify-full"), ("sslrootcert", ca_file.as_posix())]
    return urlunsplit(parts._replace(query=urlencode(query, quote_via=quote, safe=":/")))


def is_dsn(name: str) -> bool:
    return name.endswith("_DSN")


def dsn_project_ref(dsn: str) -> str | None:
    """The Supabase project a DSN names: the direct host `db.<ref>.supabase.co`, or the pooler
    login `<role>.<ref>` on `*.pooler.supabase.com`. Anything else names no project."""

    parts = urlsplit(dsn)
    host, user = (parts.hostname or "").lower(), parts.username or ""
    direct = re.fullmatch(r"db\.([a-z0-9]{20})\.supabase\.co", host)
    if direct:
        return direct.group(1)
    if host.endswith(".pooler.supabase.com"):
        login = re.fullmatch(r"[A-Za-z0-9_]+\.([a-z0-9]{20})", user)
        return login.group(1) if login else None
    return None


def secure_dsns(files: dict[str, list[Entry]], ca_file: Path | None) -> dict[str, list[Entry]]:
    """Every non-loopback DSN gets TLS verification against the CA; refuse when the CA is absent."""

    result: dict[str, list[Entry]] = {}
    for file, entries in files.items():
        secured = []
        for entry in entries:
            if entry.value and is_dsn(entry.name):
                host = urlsplit(entry.value).hostname or ""
                if host not in {"127.0.0.1", "localhost", "::1"}:
                    if ca_file is None or not ca_file.is_file():
                        raise Refused(
                            "CA_FILE_MISSING",
                            f"{entry.name} is remote; pass --ca-file <Supabase root CA>",
                        )
                    validate_ca(ca_file)
                    entry = replace(entry, value=tls_dsn(entry.value, ca_file))
            secured.append(entry)
        result[file] = secured
    return result


def check_identity(ctx: Context, files: dict[str, list[Entry]]) -> None:
    """H3: every DSN must name the target's project exactly (host or pooler login)."""

    for entries in files.values():
        for entry in entries:
            if (
                entry.value
                and is_dsn(entry.name)
                and dsn_project_ref(entry.value) != ctx.project_ref
            ):
                raise Refused(
                    "TARGET_IDENTITY_MISMATCH",
                    f"{entry.name} ({entry.source}) does not name target {ctx.project_ref}",
                )


# ------------------------------------------------------------------------------------- composition


def owner(
    ctx: Context, file: str, source_name: str, name: str | None = None, *, required: bool = True
) -> Entry:
    value = ctx.owner.get(file, {}).get(source_name) or None
    needs = None if value else f"owner (ESCALATION H2): {source_name} in {file}"
    return Entry(name or source_name, value, f"owner:{file}:{source_name}", needs, required)


def derived(name: str, value: str | None, what: str, needs: str | None = None) -> Entry:
    return Entry(name, value, f"derived:{what}", None if value else needs)


def constant(name: str, value: str) -> Entry:
    return Entry(name, value, "constant")


def blank(name: str) -> Entry:
    return Entry(name, "", "blank:owner .env isolation")


def minted(ctx: Context, name: str, as_name: str | None = None) -> Entry:
    return Entry(as_name or name, ctx.minted[name], "minted")


def integrator(ctx: Context, source_name: str, name: str, what: str) -> Entry:
    value = ctx.integrator.get(source_name) or None
    return Entry(
        name,
        value,
        f"integrator:{source_name}",
        None if value else f"integrator: {source_name} ({what})",
    )


# W1 D5: both values travel as K01 `Name`s (`^[a-z][a-z0-9_.-]{0,119}$`: MC `Origin.issuer`,
# `CredentialClaims.iss`/`aud`, KS `NameSchema`), so the application is joined with `.`, never `/`.
def issuer(app: str) -> str:
    return f"mission-control.{app}"


def audience(app: str) -> str:
    return f"knowledge-services-executor.{app}"


# OVE-169 W1 D25: the KS executor signs run seals as this issuer (its descriptor `signingIssuer`);
# the root installers' `seal-key` step pins the key's public half under the same id and issuer.
SEAL_ISSUER = "knowledge-services"
SEAL_INSTALL_NAMES = (
    "KS_KNOWLEDGE_SEAL_KEY_ID",
    "KS_KNOWLEDGE_SEAL_KEY_FILE",
    "KS_KNOWLEDGE_SEAL_ISSUER",
)


def ks_executor(ctx: Context) -> list[Entry]:
    app, ports = ctx.app, PORTS[ctx.app]
    dsn_env, dsn_file, dsn_source = COMPONENT_DSN[app]
    binding: dict[str, Any] = {
        "application": app,
        "binding": ctx.profile["knowledge"]["binding_id"],
        "installationId": ctx.component_installation_id,
        "databaseUrlEnv": dsn_env,
    }
    if app == "biotech":
        binding["tenants"] = list(ctx.tenants)
    entries = [
        constant("VERIFY_HOST", "127.0.0.1"),
        constant("VERIFY_PORT", str(ports["ks_executor"])),
        constant("KS_KNOWLEDGE_ISSUER", issuer(app)),
        constant("KS_KNOWLEDGE_AUDIENCE", audience(app)),
        derived(
            "KS_KNOWLEDGE_JWKS_FILE",
            (ctx.out / "knowledge-issuer.jwks.json").as_posix(),
            "minted issuer public JWKS",
        ),
        derived(
            "KS_KNOWLEDGE_BINDINGS_JSON",
            json.dumps([binding], separators=(",", ":")),
            "install receipt + profile",
        ),
        owner(ctx, dsn_file, dsn_source, dsn_env),
        minted(ctx, "KS_KNOWLEDGE_SEAL_KEY_ID"),
        derived(
            "KS_KNOWLEDGE_SEAL_KEY_FILE", (ctx.out / "ks-seal.pem").as_posix(), "minted seal key"
        ),
        constant("KS_KNOWLEDGE_SEAL_ISSUER", SEAL_ISSUER),
    ]
    if app == "ai-engineer":
        # The co-hosted knowledge database the AIDB native apply port uses (KS reads it as
        # `KS_AIENG_DB_RUNTIME_DSN`, its only knowledge-pool name).
        entries.append(owner(ctx, AIE_ENV, "AIENG_DB_ADMIN_DSN", "KS_AIENG_DB_RUNTIME_DSN"))
    else:
        entries += [
            constant("KS_BIOTECH_EXECUTOR_URL", f"http://127.0.0.1:{ports['bks_executor']}"),
            # OVE-169: the KS executor drains pending Biotech dispatches (bounded, idempotent).
            constant("KS_BIOTECH_DISPATCH_DRAIN_INTERVAL_MS", "5000"),
            constant("KS_BIOTECH_DISPATCH_DRAIN_LIMIT", "10"),
            minted(ctx, "KS_BIOTECH_EXECUTOR_TOKEN"),
            minted(ctx, "KS_BIOTECH_EXECUTOR_READ_TOKEN"),
        ]
    return entries


def bks_tokens(ctx: Context) -> str:
    """One writer and one reader service principal for the single verification tenant (a BKS
    token authenticates to exactly one principal, so one token cannot serve two tenants)."""

    scope = {
        "installationId": ctx.component_installation_id,
        "applicationId": "biotech",
        "tenantId": ctx.tenants[0],
    }

    def sha(name: str) -> str:
        return hashlib.sha256(ctx.minted[name].encode("utf-8")).hexdigest()

    return json.dumps(
        [
            {
                "tokenSha256": sha("KS_BIOTECH_EXECUTOR_TOKEN"),
                "role": "writer",
                "class": "service",
                "principalId": "ks-biotech-graph",
                **scope,
                "grants": ["admission.dispatch"],
            },
            {
                "tokenSha256": sha("KS_BIOTECH_EXECUTOR_READ_TOKEN"),
                "role": "reader",
                "class": "service",
                "principalId": "ks-biotech-graph-reader",
                **scope,
                "grants": [],
            },
        ],
        separators=(",", ":"),
    )


def graph_entries(ctx: Context) -> list[Entry]:
    """Neo4j names only for the pinned, confirmed Aura host; any other host refuses. The login is
    read from the MC `.env` (`MC_BIOTECH_GRAPH_*`) and written under the names BKS reads."""

    pin = ctx.graph_pin or load_graph_pin(ctx.mc_root)
    uri = ctx.owner.get(MC_ENV, {}).get("MC_BIOTECH_GRAPH_URI") or ""
    host = (urlsplit(uri).hostname or "").lower() if uri else ""
    for candidate in (host, (ctx.confirm_graph or "").lower()):
        if candidate and candidate.split(".")[0] in pin["refused"]:
            raise Refused("GRAPH_HOST_REFUSED", f"{candidate} is a refused Aura instance")
    if host and host != pin["host"]:
        raise Refused(
            "GRAPH_HOST_MISMATCH", f"MC .env MC_BIOTECH_GRAPH_URI is not the {GRAPH_PIN} host"
        )
    if ctx.confirm_graph and ctx.confirm_graph.lower() != pin["host"]:
        raise Refused("GRAPH_CONFIRMATION_MISMATCH", f"--confirm-graph is not the {GRAPH_PIN} host")
    confirmed = bool(ctx.confirm_graph) and host == pin["host"]
    ctx.choices["graph"] = "confirmed" if confirmed else "unconfirmed"
    needs = f"integrator: --confirm-graph {pin['host']} (pinned in {GRAPH_PIN})"
    entries = [
        owner(ctx, MC_ENV, "MC_BIOTECH_GRAPH_URI", "BKS_BIOTECH_GRAPH_URI"),
        owner(ctx, MC_ENV, "MC_BIOTECH_GRAPH_USERNAME", "BKS_BIOTECH_GRAPH_USERNAME"),
        owner(ctx, MC_ENV, "MC_BIOTECH_GRAPH_PASSWORD", "BKS_BIOTECH_GRAPH_PASSWORD"),
        constant("BKS_TARGET", "production"),
    ]
    if confirmed:
        return entries
    return [Entry(entry.name, None, entry.source, needs) for entry in entries]


def verification_dsn(ctx: Context) -> Entry:
    if ctx.integrator.get("BKS_BIOTECH_DB_VERIFICATION_DSN"):
        ctx.choices["verificationDsn"] = "integrator"
        return integrator(
            ctx,
            "BKS_BIOTECH_DB_VERIFICATION_DSN",
            "BKS_BIOTECH_DB_VERIFICATION_DSN",
            "outbox worker",
        )
    if ctx.allow_admin_verification_dsn:
        ctx.choices["verificationDsn"] = "admin-allowed (disposable W0)"
        entry = owner(ctx, MC_ENV, "MC_BIOTECH_DB_ADMIN_DSN", "BKS_BIOTECH_DB_VERIFICATION_DSN")
        return replace(entry, source=f"{entry.source} (--allow-admin-verification-dsn)")
    ctx.choices["verificationDsn"] = "missing"
    return Entry(
        "BKS_BIOTECH_DB_VERIFICATION_DSN",
        None,
        "integrator:BKS_BIOTECH_DB_VERIFICATION_DSN",
        "integrator: BKS_BIOTECH_DB_VERIFICATION_DSN (a restricted login holding "
        "knowledge_verification_outbox_worker), or --allow-admin-verification-dsn "
        "for disposable W0",
    )


def bks_executor(ctx: Context) -> list[Entry]:
    return [
        constant("BKS_NO_ENV_FILE", "1"),
        constant("EXECUTOR_PORT", str(PORTS["biotech"]["bks_executor"])),
        *graph_entries(ctx),
        derived(
            "BKS_EXECUTOR_TOKENS",
            bks_tokens(ctx),
            "minted KS tokens (sha256) + verification tenant",
        ),
        verification_dsn(ctx),
        derived("BKS_VERIFICATION_TENANTS", ctx.tenants[0], "verification tenant"),
    ]


def checkpoint_dsn(ctx: Context) -> Entry:
    """The saver login. Blank, MC falls back to the application (runtime) DSN, which is not the
    checkpointer role; that is allowed only with `--allow-checkpoint-fallback`."""

    name = db_name(ctx.app, "CHECKPOINT_DSN")
    entry = integrator(
        ctx,
        name,
        name,
        "restricted login holding mission_control_checkpointer",
    )
    if entry.value is not None:
        ctx.choices["checkpointDsn"] = "integrator"
        return entry
    if ctx.allow_checkpoint_fallback:
        ctx.choices["checkpointDsn"] = "application-dsn-fallback (--allow-checkpoint-fallback)"
        ctx.warnings.append(
            f"{name} is blank: the saver uses the application "
            "(runtime) DSN, not the mission_control_checkpointer role"
        )
        return replace(entry, required=False)
    ctx.choices["checkpointDsn"] = "missing"
    ctx.warnings.append(
        f"{name} is missing: mission-control.env is held as "
        f".incomplete (a blank would fall back to the application DSN); pass {name} "
        "in --integrator-env or --allow-checkpoint-fallback"
    )
    return entry


def mission_control(ctx: Context) -> list[Entry]:
    app, installation = ctx.app, ctx.mc_installation_id
    profile = ctx.profile["installation"]
    workspace = (
        ctx.bellabs / "platform" / "mission-control" / profile["capability_workspace_root"]
    ).resolve()
    runtime = "restricted login holding mission_control_runtime"
    writer = "restricted login holding mission_control_family_writer"
    deployment_needs = "integrator: --deployment-file <operator deployment.json> (W1 harness)"
    application_toml = f"deployments/{app}/application.toml"
    home = ctx.mc_root
    tools = workspace / ".tools"
    node = shutil.which("node")
    if not node:
        raise Refused("NODE_NOT_FOUND", "WEB_RESEARCH_AGENT_BROWSER_NODE needs node on PATH")
    entries = [
        # The `.env` MC layers beneath this file is `<MISSION_CONTROL_HOME>/.env`: pin it to the
        # owner MC `.env` the generator inspected (OWNER_ENV_SETS_UNMANAGED).
        derived("MISSION_CONTROL_HOME", home.as_posix(), "canonical Mission Control checkout"),
        derived(
            "CAPABILITY_PINS_PATH",
            (home / "infra" / "capability-pins" / "research-capabilities.json").as_posix(),
            "settings default under MISSION_CONTROL_HOME",
        ),
        derived(
            "WEB_RESEARCH_FIRECRAWL_MCP_MODULE",
            (
                tools
                / "reviewed"
                / "firecrawl-mcp-7232b6d1cdd80335107d53a33b80c902b515a334"
                / "dist"
                / "index.js"
            ).as_posix(),
            "settings derivation from MISSION_CONTROL_WORKSPACE_ROOT",
        ),
        derived(
            "WEB_RESEARCH_TAVILY_MCP_MODULE",
            (tools / "node_modules" / "tavily-mcp" / "build" / "index.js").as_posix(),
            "settings derivation from MISSION_CONTROL_WORKSPACE_ROOT",
        ),
        derived(
            "WEB_RESEARCH_AGENT_BROWSER_ENTRYPOINT",
            (tools / "node_modules" / "agent-browser" / "bin" / "agent-browser.js").as_posix(),
            "settings derivation from MISSION_CONTROL_WORKSPACE_ROOT",
        ),
        derived("WEB_RESEARCH_AGENT_BROWSER_NODE", Path(node).as_posix(), "node on PATH"),
        *(Entry(name, value, "constant:settings default") for name, value in MC_DEFAULTS.items()),
        constant("MISSION_CONTROL_APPLICATION", app),
        constant("MISSION_CONTROL_WORKER_APPLICATION_ID", app),
        derived(
            "MISSION_CONTROL_DEPLOYMENTS_ROOT",
            (ctx.mc_root / "deployments").as_posix(),
            "this checkout",
        ),
        derived(
            "MISSION_CONTROL_WORKSPACE_ROOT",
            workspace.as_posix(),
            "profile capability_workspace_root",
        ),
        derived(
            "MISSION_CONTROL_DEPLOYMENT_FILE",
            ctx.deployment_file.as_posix() if ctx.deployment_file else None,
            "--deployment-file",
            deployment_needs,
        ),
        derived(
            "MISSION_CONTROL_WORKER_BINDING_DIGEST",
            ctx.binding_digest,
            "--deployment-file binding",
            deployment_needs,
        ),
        # The reviewed local-operator runtime options (family admissions, artifact bodies).
        derived(
            "MISSION_CONTROL_RUNTIME_OPTIONS_FACTORY",
            RUNTIME_OPTIONS_FACTORY if ctx.deployment_file else None,
            "with --deployment-file",
            deployment_needs,
        ),
        derived(
            "MISSION_CONTROL_CATALOG_SCOPE",
            f"mc/{installation}/{app}/catalog",
            "target.toml installation_id",
        ),
        constant("TEMPORAL_TARGET", "local"),
        constant("TEMPORAL_ADDRESS", TEMPORAL_ADDRESS),
        derived(
            "TEMPORAL_NAMESPACE",
            ctx.temporal_namespace,
            "--deployment-file temporal.namespace (else default)",
        ),
        derived("TEMPORAL_TASK_QUEUE", profile["temporal_task_queue"], application_toml),
        derived("LANGSMITH_PROJECT", profile["langsmith_project"], application_toml),
        derived(
            "AGENT_SERVER_LANGSMITH_PROJECT",
            profile["agent_server_langsmith_project"],
            application_toml,
        ),
        constant("RUN_CONTROL_TEMPORAL_ENABLED", "true"),
        constant("COORDINATOR_LAUNCH_ENABLED", "true"),
        # Pinned off: with COORDINATOR_MCP_JWT_ISSUER blank, `Settings.coordinator_jwt_issuer`
        # falls back to the plane URL (MC_<PLANE>_DB_URL), which bundle custody writes. The
        # coordinator MCP surface
        # (and its Supabase JWT verifier) must not switch on because custody did.
        constant("COORDINATOR_MCP_ENABLED", "false"),
        # Loop iter-1 L1-04: the worker relays released chain links (`mc.chain.start_run`);
        # without it a released consumer stays `pending` forever. The worker then requires
        # MANIFEST_LAUNCH_BINDINGS_PATH, which the W1 launcher sets (MC_UNMANAGED).
        constant("CHAIN_RELAY_ENABLED", "1"),
        # One name each: the runtime and family-writer variables are also the operator
        # deployment's `database_secret_ref` / `family_writer_secret_ref`.
        derived(db_name(app, "PROJECT_REF"), ctx.project_ref, "target.toml project_ref"),
        integrator(
            ctx,
            db_name(app, "RUNTIME_DSN"),
            db_name(app, "RUNTIME_DSN"),
            f"{runtime}; database_secret_ref",
        ),
        integrator(
            ctx,
            db_name(app, "FAMILY_WRITER_DSN"),
            db_name(app, "FAMILY_WRITER_DSN"),
            f"{writer}; family_writer_secret_ref",
        ),
        checkpoint_dsn(ctx),
        constant("LANGGRAPH_CHECKPOINT_SCHEMA", "mission_control_runtime"),
        constant("LANGGRAPH_CHECKPOINT_SETUP", "false"),
        derived("ARTIFACT_PAYLOAD_ROOT", (ctx.out / "payloads").as_posix(), "runtime directory"),
        derived(
            "DEEP_AGENT_SANDBOX_WORKSPACE_ROOT",
            (ctx.out / "workspaces").as_posix(),
            "runtime directory",
        ),
        constant("REDIS_URL", LOCAL_REDIS),
        constant("KNOWLEDGE_GATEWAY_REQUIRED", "true"),
        constant("KNOWLEDGE_DISPOSABLE_INSTALLATION", "true"),
        constant("KNOWLEDGE_BINDING_URL", f"http://127.0.0.1:{PORTS[app]['ks_executor']}"),
        constant("KNOWLEDGE_BINDING_AUDIENCE", audience(app)),
        constant("KNOWLEDGE_ISSUER", issuer(app)),
        derived(
            "KNOWLEDGE_ISSUER_KEY_FILE",
            (ctx.out / "knowledge-issuer.jwk.json").as_posix(),
            "minted issuer key",
        ),
        minted(ctx, "KNOWLEDGE_ISSUER_KEY_ID"),
        derived("KNOWLEDGE_DESCRIBE_TENANT", ctx.tenants[0], "verification tenant"),
        # W1 D6: the KS component installation the executor serves (`KS_KNOWLEDGE_BINDINGS_JSON`
        # installationId): MC sends it as the K01 origin installation, never its own id.
        derived(
            "KNOWLEDGE_COMPONENT_INSTALLATION_ID",
            ctx.component_installation_id,
            "install receipt / --component-installation-id",
        ),
        minted(ctx, "RUNTIME_CHECKPOINT_SIGNING_KEY"),
        minted(ctx, "BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN"),
        constant("MISSION_CONTROL_AGENT_SERVER_PROFILE", "runtime"),
        owner(ctx, MC_ENV, "ANTHROPIC_API_KEY"),
        owner(ctx, MC_ENV, "OPENAI_API_KEY"),
        # OVE-169: the independent evaluators' own credential names (the judge on OpenAI, the
        # auditor on a SECOND Anthropic key; never the producer's).
        owner(ctx, MC_ENV, "OPENAI_API_KEY", JUDGE_KEY),
        owner(ctx, MC_ENV, "SECOND_ANTHROPIC_API_KEY", AUDITOR_KEY),
        owner(ctx, MC_ENV, "LANGSMITH_API_KEY", required=False),
        owner(ctx, MC_ENV, "FIRECRAWL_API_KEY", required=False),
        owner(ctx, MC_ENV, "TAVILY_API_KEY", required=False),
    ]
    entries += bundle_custody(ctx)
    named = {entry.name for entry in entries}
    return entries + [blank(name) for name in (*MC_DB_BLANKED, *MC_BLANKED) if name not in named]


# The application's own Supabase project (never the MC `.env` for ai-engineer: it names biotech).
APP_SUPABASE = {"biotech": MC_ENV, "ai-engineer": AIE_ENV}
# The names those owner files hold (MC `.env`: plane-prefixed; `aiengineer/.env`: `AIENG_DB_*`).
OWNER_URL = {
    "biotech": ("MC_BIOTECH_DB_URL", "MC_BIOTECH_DB_PUBLISHABLE_KEY"),
    "ai-engineer": ("AIENG_DB_URL", "AIENG_DB_PUBLISHABLE_KEY"),
}
CUSTODY_TOKENS = {
    "CAPABILITY_BUNDLE_PUBLISHER_TOKEN": "publisher",
    "CAPABILITY_BUNDLE_READER_TOKEN": "reader",
}


def _unverified_claims(token: str) -> dict[str, Any]:
    """The payload of a compact JWS, decoded without verification (shape checks only)."""

    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError) as error:
        raise Refused("BUNDLE_CUSTODY_INVALID", "a custody token is not a compact JWT") from error
    if not isinstance(claims, dict):
        raise Refused("BUNDLE_CUSTODY_INVALID", "a custody token carries no claims object")
    return claims


def bundle_custody(ctx: Context) -> list[Entry]:
    """`bundle-custody.env` (`sprint_oc_mint_bundle_tokens.py`) switches custody to Supabase: the
    two tokens, the application namespace and the application's own project URL and key."""

    path = ctx.out / "bundle-custody.env"
    if not path.is_file():
        ctx.choices["bundleCustody"] = "local (no bundle-custody.env)"
        return [constant("CAPABILITY_BUNDLE_BACKEND", "local")]
    tokens = read_env(path)
    issuer = f"https://{ctx.project_ref}.supabase.co/auth/v1"
    for name, role in CUSTODY_TOKENS.items():
        token = tokens.get(name, "")
        if not token:
            raise Refused("BUNDLE_CUSTODY_INVALID", f"{path.name} has no {name}")
        claims = _unverified_claims(token)
        if claims.get("iss") != issuer or claims.get("mc_capability_role") != role:
            raise Refused("BUNDLE_CUSTODY_INVALID", f"{name} is not a {role} token for the target")
        expires = claims.get("exp")
        if isinstance(expires, bool) or not isinstance(expires, int | float):
            raise Refused("BUNDLE_CUSTODY_INVALID", f"{name} has no numeric exp")
        if expires <= int(time.time()) + 300:
            raise Refused("BUNDLE_CUSTODY_EXPIRED", f"{name} expires within 5 minutes; re-mint")
    source = APP_SUPABASE[ctx.app]
    url_name, key_name = OWNER_URL[ctx.app]
    url = ctx.owner.get(source, {}).get(url_name, "")
    host = (urlsplit(url).hostname or "").lower() if url else ""
    if host != f"{ctx.project_ref}.supabase.co":
        raise Refused("DB_URL_MISMATCH", f"{source} {url_name} is not the {ctx.app} project")
    ctx.choices["bundleCustody"] = "supabase (bundle-custody.env)"
    # The runtime (API, worker) reads with the reader token only; the publisher token is an
    # operator credential (`bundle-publisher.env`, seed upload and skill registration).
    ctx.publisher = Entry(
        "CAPABILITY_BUNDLE_PUBLISHER_TOKEN",
        tokens["CAPABILITY_BUNDLE_PUBLISHER_TOKEN"],
        f"minted:{path.name}",
    )
    return [
        constant("CAPABILITY_BUNDLE_BACKEND", "supabase"),
        # The storage policies scope every object to the application id as its first folder.
        derived("CAPABILITY_BUNDLE_NAMESPACE", ctx.app, "application id (storage policy prefix)"),
        Entry(
            "CAPABILITY_BUNDLE_READER_TOKEN",
            tokens["CAPABILITY_BUNDLE_READER_TOKEN"],
            f"minted:{path.name}",
        ),
        owner(ctx, source, url_name, db_name(ctx.app, "URL")),
        owner(ctx, source, key_name, db_name(ctx.app, "PUBLISHABLE_KEY")),
    ]


# The Agent Server keeps today's local W1 auth: the worker reaches it with `bl1.` scope claims
# (BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN, `deployment_auth.py`). A plane URL (MC_<PLANE>_DB_URL, or an
# explicit BELL_LABS_AGENT_AUTH_ISSUER) would make `agent_server/auth.py` derive an issuer and
# verify every
# other bearer as an RS256 Supabase JWT; it has no use for the custody names either.
AGENT_SERVER_WITHHELD = (
    # The evaluators run in the worker only (least privilege for the Agent Server).
    "MC_JUDGE_OPENAI_API_KEY",
    "MC_AUDITOR_ANTHROPIC_API_KEY",
    *(f"MC_{plane}_DB_{role}" for plane in PLANE.values() for role in ("URL", "PUBLISHABLE_KEY")),
    "CAPABILITY_BUNDLE_READER_TOKEN",
    "CAPABILITY_BUNDLE_PUBLISHER_TOKEN",
    "BELL_LABS_AGENT_AUTH_ISSUER",
    "BELL_LABS_AGENT_AUTH_JWKS_URI",
)
# The operator file for seed upload and skill registration: identity, custody and the database
# the registration writes, with every inheritable setting blanked as in `mission-control.env`.
PUBLISHER_NAMES = {
    "MISSION_CONTROL_HOME",
    "MISSION_CONTROL_APPLICATION",
    "MISSION_CONTROL_DEPLOYMENTS_ROOT",
    "MISSION_CONTROL_WORKSPACE_ROOT",
    "MISSION_CONTROL_CATALOG_SCOPE",
    *(
        f"MC_{plane}_DB_{role}"
        for plane in PLANE.values()
        for role in ("PROJECT_REF", "RUNTIME_DSN", "URL", "PUBLISHABLE_KEY")
    ),
    "CAPABILITY_BUNDLE_BACKEND",
    "CAPABILITY_BUNDLE_NAMESPACE",
    "REDIS_URL",
    *MC_BLANKED,
    *MC_DEFAULTS,
}


def agent_server(entries: list[Entry]) -> list[Entry]:
    kept = [entry for entry in entries if entry.name not in AGENT_SERVER_WITHHELD]
    return kept + [blank(name) for name in AGENT_SERVER_WITHHELD]


# The runtime reader token is not an operator credential: an explicit blank in the operator file.
PUBLISHER_WITHHELD = ("CAPABILITY_BUNDLE_READER_TOKEN",)


def bundle_publisher(ctx: Context, entries: list[Entry]) -> list[Entry] | None:
    if ctx.publisher is None:
        return None
    withheld = {ctx.publisher.name, *PUBLISHER_WITHHELD}
    kept = [entry for entry in entries if entry.name in PUBLISHER_NAMES - withheld]
    held = {entry.name for entry in kept}
    # Every other database variable is an explicit blank (least privilege: no admin, family
    # writer or checkpoint login in the operator file).
    blanks = [blank(name) for name in MC_DB_BLANKED if name not in held]
    return [*kept, *blanks, *(blank(name) for name in PUBLISHER_WITHHELD), ctx.publisher]


def compose(ctx: Context) -> dict[str, list[Entry]]:
    runtime = mission_control(ctx)
    files = {
        "ks-executor.env": ks_executor(ctx),
        "mission-control.env": runtime,
        "agent-server.env": agent_server(runtime),
    }
    publisher = bundle_publisher(ctx, runtime)
    if publisher is not None:
        files["bundle-publisher.env"] = publisher
    if ctx.app == "biotech":
        files["bks-executor.env"] = bks_executor(ctx)
        # The installer's executor-config step reads both executors' names from one process.
        seen: dict[str, Entry] = {}
        for entry in files["ks-executor.env"] + files["bks-executor.env"]:
            seen.setdefault(entry.name, entry)
        files["install.env"] = list(seen.values())
    else:
        # The root installer's seal-key step: the executor's seal key id, private key path, issuer.
        files["install.env"] = [
            entry for entry in files["ks-executor.env"] if entry.name in SEAL_INSTALL_NAMES
        ]
    return files


# ------------------------------------------------------------------------------------- output


def render(entries: list[Entry], header: str) -> str:
    """dotenv text: a missing name is an explicit blank (never left to an owner `.env`)."""

    lines = [
        f"# {header}",
        "# Generated by scripts/sprint_oc_runtime_env.py; ignored; never commit or print.",
        "",
    ]
    for entry in entries:
        if entry.value is None:
            lines.append(f"# MISSING {entry.name}: {entry.needs}")
            lines.append(f"{entry.name}=")
            continue
        value = entry.value
        if "\n" in value or "\r" in value:
            raise Refused("VALUE_MULTILINE", entry.name)
        if BARE.match(value):
            lines.append(f"{entry.name}={value}")
        elif "'" not in value and "\\\\" not in value and not value.endswith("\\"):
            # Single quotes are literal for node --env-file and uv (dotenvy).
            lines.append(f"{entry.name}='{value}'")
        else:
            raise Refused("VALUE_UNQUOTABLE", entry.name)
    return "\n".join(lines) + "\n"


def build_context(args: argparse.Namespace) -> Context:
    app = args.app
    if app != "biotech" and args.confirm_graph:
        raise Refused("CONFIRM_GRAPH_NOT_APPLICABLE", f"{app} runs no graph executor")
    if app != "biotech" and args.allow_admin_verification_dsn:
        raise Refused("ADMIN_VERIFICATION_DSN_NOT_APPLICABLE", f"{app} runs no BKS executor")
    mc_root = (args.mc_root or MC_ROOT).resolve()
    if not (mc_root / "deployments" / app / "target.toml").is_file():
        raise Refused("MC_ROOT_INVALID", f"{mc_root} is not a Mission Control checkout")
    bellabs = (args.bellabs_root or find_bellabs_root(mc_root)).resolve()
    out = (args.out_dir or mc_root / ".scratch" / "sprint-oc" / "runtime").resolve() / app
    deployments = mc_root / "deployments" / app
    target = tomllib.loads((deployments / "target.toml").read_text(encoding="utf-8"))["target"]
    profile = tomllib.loads((deployments / "application.toml").read_text(encoding="utf-8"))
    if not PROJECT_REF.match(target["project_ref"]):
        raise Refused("TARGET_INVALID", f"deployments/{app}/target.toml project_ref")

    component = args.component_installation_id
    mc_id = target["installation_id"]
    if component is not None and not UUID.match(component):
        raise Refused(
            "INSTALLATION_ID_INVALID", "--component-installation-id must be a lowercase uuid"
        )
    if args.receipt is not None:
        receipt_component, receipt_mc = ids_from_receipt(args.receipt, app)
        if component is not None and component != receipt_component:
            raise Refused(
                "INSTALLATION_ID_MISMATCH", "--component-installation-id differs from the receipt"
            )
        if receipt_mc != mc_id:
            raise Refused(
                "MC_INSTALLATION_MISMATCH",
                f"receipt Mission Control id differs from deployments/{app}/target.toml",
            )
        component = receipt_component
    ids_file = args.ids_file or (out.parent / "installation-ids.json")
    if args.ids_file is not None and not ids_file.is_file():
        raise Refused("IDS_FILE_MISSING", str(ids_file))
    if ids_file.is_file():
        assert_ignored(ids_file.resolve())
        try:
            recorded = json.loads(ids_file.read_text(encoding="utf-8")).get(app)
        except (OSError, ValueError, AttributeError) as error:
            raise Refused(
                "IDS_FILE_INVALID", f"{ids_file} is not a JSON object of app -> uuid"
            ) from error
        if recorded is not None:
            if not isinstance(recorded, str) or not UUID.match(recorded):
                raise Refused("IDS_FILE_INVALID", f"{ids_file} {app} is not a lowercase uuid")
            if component is not None and component != recorded:
                raise Refused(
                    "INSTALLATION_ID_MISMATCH",
                    f"the component installation id differs from {ids_file}",
                )
            component = recorded
    if component is None:
        raise Refused(
            "INSTALLATION_ID_REQUIRED",
            "--receipt <install receipt>, --component-installation-id <uuid> or --ids-file <json>",
        )
    tenants = tuple(args.verification_tenant_id or ())
    if len(tenants) > 1:
        # A BKS token authenticates to one principal with one tenantId (apps/executor/src/auth.ts).
        raise Refused(
            "TENANT_MULTIPLE_UNSUPPORTED", "one --verification-tenant-id per installation"
        )
    if any(not UUID.match(tenant) for tenant in tenants):
        raise Refused("TENANT_ID_INVALID", "--verification-tenant-id must be a lowercase uuid")

    integrator_values: dict[str, str] = {}
    if args.integrator_env is not None:
        path = args.integrator_env.resolve()
        if not path.is_file():
            raise Refused("INTEGRATOR_ENV_MISSING", str(path))
        assert_ignored(path)
        raw = read_env(path)
        unknown = sorted(set(raw) - set(integrator_names(app)))
        if unknown:
            raise Refused("INTEGRATOR_ENV_UNKNOWN_NAMES", ",".join(unknown))
        integrator_values = {key: value for key, value in raw.items() if value}

    deployment_file = args.deployment_file.resolve() if args.deployment_file else None
    digest = binding_digest_from(deployment_file, app, mc_id) if deployment_file else None
    namespace = temporal_namespace_from(deployment_file, app) if deployment_file else "default"
    owner_files = {name: read_env(bellabs / name) for name in (MC_ENV, AIE_ENV)}
    producer_key = owner_files[MC_ENV].get("ANTHROPIC_API_KEY")
    if producer_key and owner_files[MC_ENV].get("SECOND_ANTHROPIC_API_KEY") == producer_key:
        # A second name over the same key is not an independent auditor credential.
        raise Refused(
            "AUDITOR_CREDENTIAL_SHARED",
            f"{MC_ENV} SECOND_ANTHROPIC_API_KEY equals ANTHROPIC_API_KEY",
        )
    layered = read_env(mc_root / ".env")
    for label, values in ((MC_ENV, owner_files[MC_ENV]), (f"{mc_root.as_posix()}/.env", layered)):
        unmanaged = sorted({key.upper() for key in values} & set(MC_UNMANAGED))
        if unmanaged:
            raise Refused("OWNER_ENV_SETS_UNMANAGED", f"{label} sets {','.join(unmanaged)}")
    if args.ca_file is not None:
        validate_ca(args.ca_file.resolve())
    default_ca = (
        bellabs
        / "platform"
        / "mission-control"
        / ".scratch"
        / "sprint-oc"
        / "runtime"
        / "supabase-prod-ca-2021.crt"
    )
    return Context(
        app=app,
        bellabs=bellabs,
        out=out,
        component_installation_id=component,
        mc_installation_id=mc_id,
        project_ref=target["project_ref"],
        profile=profile,
        owner=owner_files,
        integrator=integrator_values,
        minted={},
        tenants=tenants,
        confirm_graph=args.confirm_graph,
        deployment_file=deployment_file,
        binding_digest=digest,
        temporal_namespace=namespace,
        ca_file=(args.ca_file or default_ca).resolve(),
        allow_admin_verification_dsn=args.allow_admin_verification_dsn,
        graph_pin=load_graph_pin(mc_root) if app == "biotech" else None,
        mc_root=mc_root,
        allow_checkpoint_fallback=args.allow_checkpoint_fallback,
    )


def record_ids(path: Path, app: str, component: str) -> None:
    """Keep the integrator's app -> component installation id map (ids only; not secret)."""

    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except ValueError:
        current = {}
    if current.get(app) != component:
        current[app] = component
        write_text(path, json.dumps(dict(sorted(current.items())), indent=2) + "\n", secret=False)


ENV_FILES = (
    "ks-executor.env",
    "mission-control.env",
    "agent-server.env",
    "bundle-publisher.env",
    "bks-executor.env",
    "install.env",
)


def run(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--app", required=True, choices=sorted(PORTS))
    parser.add_argument("--component-installation-id")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--ids-file", type=Path)
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--verification-tenant-id", action="append")
    parser.add_argument("--confirm-graph")
    parser.add_argument("--allow-admin-verification-dsn", action="store_true")
    parser.add_argument("--allow-checkpoint-fallback", action="store_true")
    parser.add_argument("--mc-root", type=Path)
    parser.add_argument("--integrator-env", type=Path)
    parser.add_argument("--deployment-file", type=Path)
    parser.add_argument("--bellabs-root", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    try:
        ctx = build_context(args)
        biotech_only = {"bks-executor.env"}
        env_files = [n for n in ENV_FILES if ctx.app == "biotech" or n not in biotech_only]
        checked = [
            "minted.env",
            "manifest.json",
            "knowledge-issuer.jwk.json",
            "knowledge-issuer.jwks.json",
            "ks-seal.pem",
            "bundle-custody.env",
            "payloads/.keep",
            "workspaces/.keep",
            "../installation-ids.json",
            *env_files,
            *(f"{name}.incomplete" for name in env_files),
        ]
        for name in checked:
            assert_ignored(ctx.out / name)
        ctx.minted, fresh = mint_values(ctx.out)
        if ctx.tenants:
            ctx.minted["KNOWLEDGE_VERIFICATION_TENANT_ID"] = ctx.tenants[0]
        else:
            ctx.tenants = (ctx.minted["KNOWLEDGE_VERIFICATION_TENANT_ID"],)
        check_keys(ctx.out, ctx.minted["KNOWLEDGE_ISSUER_KEY_ID"])
        files = secure_dsns(compose(ctx), ctx.ca_file)
        check_identity(ctx, files)
        rendered = {name: render(entries, f"{ctx.app} {name}") for name, entries in files.items()}
        minted_text = render(
            [Entry(name, value, "minted") for name, value in sorted(ctx.minted.items())],
            f"{ctx.app} minted.env",
        )
        # minted.env (the kid) lands before the key files: an interruption never strands a key.
        write_text(ctx.out / "minted.env", minted_text, secret=True)
        fresh += ensure_keys(ctx.out, ctx.minted["KNOWLEDGE_ISSUER_KEY_ID"])
    except Refused as refusal:
        return 2, {"status": "refused", "code": refusal.code, "detail": refusal.detail}

    missing = [
        {"file": file, "name": entry.name, "needs": entry.needs}
        for file, entries in files.items()
        for entry in entries
        if entry.value is None and entry.required
    ]
    incomplete: set[str] = set()
    if args.require_complete:
        incomplete = {str(item["file"]) for item in missing}
    if ctx.choices.get("checkpointDsn") == "missing":
        # Not fail-closed like the other blanks: never runnable without the explicit opt-in.
        incomplete.add("mission-control.env")
    if "mission-control.env" in incomplete and "agent-server.env" in files:
        # agent-server.env is mission-control.env minus withheld names: held with it.
        incomplete.add("agent-server.env")
    canonical = (ctx.bellabs / "platform" / "mission-control").resolve()
    if ctx.mc_root != canonical:
        ctx.warnings.append(
            f"--mc-root is not the canonical checkout ({canonical.as_posix()}); W1 runs from it"
        )
    try:
        # A file this run does not produce (e.g. bundle-publisher.env once custody is local)
        # must not survive from an earlier run, runnable or held.
        for name in env_files:
            if name not in rendered:
                (ctx.out / name).unlink(missing_ok=True)
                (ctx.out / f"{name}.incomplete").unlink(missing_ok=True)
        for name, text in rendered.items():
            runnable, held = ctx.out / name, ctx.out / f"{name}.incomplete"
            if name in incomplete:
                write_text(held, text, secret=True)
                runnable.unlink(missing_ok=True)
            else:
                write_text(runnable, text, secret=True)
                held.unlink(missing_ok=True)
    except Refused as refusal:
        return 2, {"status": "refused", "code": refusal.code, "detail": refusal.detail}
    try:
        for directory in ("payloads", "workspaces"):
            (ctx.out / directory).mkdir(parents=True, exist_ok=True)
            _harden(ctx.out / directory)
    except Refused as refusal:
        return 2, {"status": "refused", "code": refusal.code, "detail": refusal.detail}
    manifest = {
        "format": "sprint-oc-runtime-env.v2",
        "app": ctx.app,
        "componentInstallationId": ctx.component_installation_id,
        "missionControlInstallationId": ctx.mc_installation_id,
        "projectRef": ctx.project_ref,
        "ports": {**PORTS[ctx.app], "temporal": TEMPORAL_ADDRESS},
        "choices": ctx.choices,
        "warnings": ctx.warnings,
        "mcRoot": ctx.mc_root.as_posix(),
        "files": {
            file: [
                {"name": e.name, "source": e.source, "present": e.value is not None}
                for e in entries
            ]
            for file, entries in files.items()
        },
        "missing": missing,
        "incompleteFiles": sorted(incomplete),
        "mintedNow": sorted(fresh),
    }
    write_text(ctx.out / "manifest.json", json.dumps(manifest, indent=2) + "\n", secret=False)
    record_ids(ctx.out.parent / "installation-ids.json", ctx.app, ctx.component_installation_id)
    summary = {
        "status": "incomplete" if incomplete else "written",
        "app": ctx.app,
        "outDir": str(ctx.out),
        "files": {
            (f"{file}.incomplete" if file in incomplete else file): [
                e.name for e in entries if e.value
            ]
            for file, entries in files.items()
        },
        "choices": ctx.choices,
        "warnings": ctx.warnings,
        "mcRoot": ctx.mc_root.as_posix(),
        "mintedNow": sorted(fresh),
        "missing": missing,
    }
    return (3 if incomplete else 0), summary


def main() -> None:
    code, summary = run()
    print(json.dumps(summary, indent=2))
    sys.exit(code)


if __name__ == "__main__":
    main()
