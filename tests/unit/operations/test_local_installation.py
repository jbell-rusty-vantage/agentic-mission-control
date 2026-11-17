"""The local installation script's rules that need no database (``scripts/dev``).

A local installation is loopback only and self-contained: the admin DSN must name a loopback
host, every process it starts inherits operating-system essentials and nothing else, the env
file names every database variable (the three restricted logins, the rest explicit blanks) with
``MISSION_CONTROL_HOME`` at a directory that holds no ``.env``, the deployment file loads through
the real loader with the Sprint OC operator's permission set, and the container variant differs
only in paths and network names.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType
from urllib.parse import urlsplit

import pytest

from mission_control.adapters.auth.jwt import MissionTokenVerifier
from mission_control.bootstrap.api import load_deployment
from mission_control.bootstrap.settings import Settings
from mission_control_db_contract.logins import LOGIN_PREFIX
from mission_control_db_contract.target import load_target, target_dsn

ROOT = Path(__file__).resolve().parents[3]
INSTALLATION = "01a1e210-df57-77ba-be46-4d5e292bab24"
TENANT = "01a1e210-df57-7779-afbd-97b738fee24e"
DIGEST = "sha256:" + "ab" * 32


def _module(name: str) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "dev" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


script = _module("local_installation")
gen = script.gen
dep = script.dep


def _logins(app: str, host: str = "127.0.0.1:55434") -> dict[str, str]:
    database = script.database_name(app)
    return {
        gen.db_name(app, role): f"postgresql://{login}:pw-{login}@{host}/{database}?sslmode=disable"
        for role, login in (
            ("RUNTIME_DSN", "mcl_runtime"),
            ("FAMILY_WRITER_DSN", "mcl_family_writer"),
            ("CHECKPOINT_DSN", "mcl_checkpointer"),
        )
    }


def _entries(app: str, out: Path, *, node: str | None = "/usr/bin/node") -> list[tuple[str, str]]:
    return script.runtime_environment(
        app,
        out,
        installation_id=INSTALLATION,
        binding_digest=DIGEST,
        logins=_logins(app),
        signing_key="signing-key-for-tests",
        profile=script.load_profile(app),
        workspace_root=out / "workspace-owner",
        temporal_address="127.0.0.1:7233",
        namespace=script.temporal_namespace(app),
        node=node,
    )


# ------------------------------------------------------------------------------------- inputs


def test_the_default_admin_server_is_the_compose_postgres_17_on_loopback() -> None:
    dsn, source = script.admin_dsn(script.ADMIN_DSN_ENV, {})
    parts = urlsplit(dsn)
    assert (parts.hostname, parts.port, source) == ("127.0.0.1", 55434, "compose:default")
    moved, _ = script.admin_dsn(script.ADMIN_DSN_ENV, {script.COMPOSE_DB_PORT_ENV: "55999"})
    assert urlsplit(moved).port == 55999
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "application-postgres-17:" in compose and "pgvector/pgvector:pg17" in compose
    assert f"${{{script.COMPOSE_DB_PORT_ENV}:-55434}}:5432" in compose


@pytest.mark.parametrize("host", ["db.abcdefghijklmnopqrst.supabase.co", "10.0.0.5", "example.com"])
def test_an_admin_dsn_that_is_not_loopback_is_refused_without_its_value(host: str) -> None:
    secret = "do-not-print-this"
    with pytest.raises(script.Refused) as refused:
        script.admin_dsn("SOME_ADMIN_DSN", {"SOME_ADMIN_DSN": f"postgresql://u:{secret}@{host}/db"})
    assert refused.value.code == "ADMIN_DSN_NOT_LOOPBACK"
    assert secret not in str(refused.value) and host not in str(refused.value)


@pytest.mark.parametrize(
    "value", ["mysql://u:p@127.0.0.1/db", "postgresql://127.0.0.1/db", "not a url"]
)
def test_an_admin_dsn_that_is_not_a_postgres_login_is_refused(value: str) -> None:
    with pytest.raises(script.Refused) as refused:
        script.admin_dsn("SOME_ADMIN_DSN", {"SOME_ADMIN_DSN": value})
    assert refused.value.code == "ADMIN_DSN_INVALID"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_a_named_loopback_admin_dsn_is_used(host: str) -> None:
    value = f"postgresql://admin:pw@{host}:55433/postgres"
    dsn, source = script.admin_dsn("SOME_ADMIN_DSN", {"SOME_ADMIN_DSN": value})
    assert (dsn, source) == (value, "environment:SOME_ADMIN_DSN")
    scoped = script.with_database(dsn, "mc_local_ai_engineer")
    assert scoped == "postgresql://admin:pw@127.0.0.1:55433/mc_local_ai_engineer"


@pytest.mark.parametrize("app", script.APPLICATIONS)
def test_names_fit_the_installer_and_the_drop_guards(
    app: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert LOGIN_PREFIX.fullmatch(script.login_prefix(app))
    assert not script.login_prefix(app).startswith("mission")
    assert re.fullmatch(r"mc_local_[a-z0-9_]{1,48}", script.database_name(app))
    for role in script.login_roles(app):
        assert re.fullmatch(r"mcl[a-z0-9]{1,13}_[a-z_]{1,16}", role)
    # The generated target manifest is one `mission-db` accepts, and it names the local DSN.
    path = tmp_path / "target.toml"
    path.write_text(
        script.target_manifest(
            app,
            installation_id=INSTALLATION,
            host="127.0.0.1",
            port=55434,
            database=script.database_name(app),
            user="belllabs",
        ),
        encoding="utf-8",
    )
    target = load_target(path)
    assert (target["environment"], target["project_ref"]) == ("disposable", f"mc-local-{app}")
    dsn = script.with_database(script.compose_admin_dsn({}), script.database_name(app))
    monkeypatch.setenv(script.INSTALL_DSN_ENV, dsn)
    assert target_dsn(target) == dsn


def test_started_processes_inherit_operating_system_essentials_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leaked = {
        "OPENAI_API_KEY": "sk-leak",
        "MC_AIENG_DB_ADMIN_DSN": "postgresql://leak",
        "MISSION_CONTROL_HOME": "/somewhere/else",
        "TEMPORAL_TARGET": "cloud",
        "TEMPORAL_CLOUD_API_KEY": "leak",
        "LANGSMITH_TRACING": "true",
        "CAPABILITY_EMBEDDING_PROFILE": "embedding.openai.text-embedding-3-small",
    }
    for name, value in leaked.items():
        monkeypatch.setenv(name, value)
    environment = script.base_environment({"EXTRA": "kept"})
    assert not set(leaked) & set(environment)
    assert environment["EXTRA"] == "kept"
    assert any(name.upper() == "PATH" for name in environment)
    assert {name.upper() for name in environment} <= {*script.PASSTHROUGH, "EXTRA"}


# ------------------------------------------------------------------------------------- env file


@pytest.mark.parametrize("app", script.APPLICATIONS)
def test_every_database_variable_and_secret_is_set_or_explicitly_blank(
    app: str, tmp_path: Path
) -> None:
    values = dict(_entries(app, tmp_path))
    logins = _logins(app)
    assert {name: values[name] for name in logins} == logins
    database = {
        name.upper()
        for name in Settings.model_fields
        if name.startswith(("mc_", "MC_")) and "_db_" in name
    } - {"MC_LOCAL_DB_PORT"}
    assert database <= set(values)
    # Only the three restricted logins carry a value; the admin login is never in the runtime.
    assert {name for name in database if values[name]} == set(logins)
    assert values[gen.db_name(app, "ADMIN_DSN")] == ""
    secrets_ = {
        name.upper()
        for name, info in Settings.model_fields.items()
        if "SecretStr" in str(info.annotation)
    }
    assert secrets_ <= set(values)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "TEMPORAL_CLOUD_API_KEY", "S3_BUCKET"):
        assert values[name] == ""
    assert values["MISSION_CONTROL_HOME"] == tmp_path.as_posix()
    assert values["TEMPORAL_TARGET"] == "local" and values["LANGSMITH_TRACING"] == "false"
    assert values["MISSION_CONTROL_WORKER_BINDING_DIGEST"] == DIGEST
    assert values["LANGGRAPH_CHECKPOINT_SETUP"] == "false"
    # Rendered and read back unchanged (DSNs are quoted: `?` and `&` are not bare).
    path = tmp_path / "mission-control.env"
    path.write_text(script.render_env(list(values.items()), ["header"]), encoding="utf-8")
    assert script.read_env_file(path) == values


def test_a_missing_restricted_login_refuses_the_env_file(tmp_path: Path) -> None:
    app = "ai-engineer"
    logins = _logins(app)
    del logins[gen.db_name(app, "CHECKPOINT_DSN")]
    with pytest.raises(script.Refused) as refused:
        script.runtime_environment(
            app,
            tmp_path,
            installation_id=INSTALLATION,
            binding_digest=DIGEST,
            logins=logins,
            signing_key="k",
            profile=script.load_profile(app),
            workspace_root=tmp_path,
            temporal_address="127.0.0.1:7233",
            namespace="mc-local-ai-engineer",
            node=None,
        )
    assert refused.value.code == "LOGINS_MISSING"


SETTINGS_PROBE = textwrap.dedent(
    """
    import json, os
    from pathlib import Path
    from pydantic import SecretStr
    from mission_control.bootstrap import settings as module

    home = Path(os.environ["MISSION_CONTROL_HOME"]).resolve()
    assert module.PROJECT_ROOT == home and not (home / ".env").exists()
    loaded = module.Settings()
    poisoned = [
        name.upper()
        for name in module.Settings.model_fields
        if "poison" in str(
            value.get_secret_value()
            if isinstance(value := getattr(loaded, name), SecretStr)
            else value
        )
    ]
    print(json.dumps({
        "poisoned": poisoned,
        "application": loaded.mission_control_application,
        "plane": loaded.db_plane,
        "has_runtime": loaded.has_application_postgres,
        "admin": loaded.db.admin_dsn is None,
        "openai": loaded.openai_api_key is None,
        "embedding_profile": loaded.capability_embedding_profile,
        "temporal_target": loaded.temporal_target,
        "tracing": loaded.langsmith_tracing,
        "deployments_root": str(loaded.deployments_root),
    }))
    """
)


def test_the_real_settings_loader_reads_no_env_file_under_the_generated_environment(
    tmp_path: Path,
) -> None:
    app = "ai-engineer"
    out = tmp_path / "installation"
    shutil.copytree(ROOT / "deployments" / app, out / "deployments" / app)
    # A checkout-like working directory whose `.env` names every setting: none may be read.
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".env").write_text(
        "".join(f"{name.upper()}=poison\n" for name in Settings.model_fields)
        + "TEMPORAL_TARGET=cloud\nLANGSMITH_TRACING=true\n",
        encoding="utf-8",
    )
    generated = dict(_entries(app, out))
    environment = script.base_environment(
        {**generated, "PYTHONPATH": str(ROOT / "src"), "PYTHONUTF8": "1"}
    )
    probe = subprocess.run(
        [sys.executable, "-c", SETTINGS_PROBE],
        env=environment,
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert probe.returncode == 0, probe.stderr[-2000:]
    result = json.loads(probe.stdout.strip().splitlines()[-1])
    assert result == {
        "poisoned": [],
        "application": app,
        "plane": "AIENG",
        "has_runtime": True,
        "admin": True,
        "openai": True,
        "embedding_profile": None,
        "temporal_target": "local",
        "tracing": False,
        "deployments_root": str((out / "deployments").resolve()),
    }


# ------------------------------------------------------------------------------------- deployment


@pytest.fixture
def ignored(tmp_path: Path) -> Path:
    """An output directory inside a Git work tree that ignores it."""

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / ".gitignore").write_text("local-stack/\n", encoding="utf-8")
    out = repo / "local-stack" / "ai-engineer"
    out.mkdir(parents=True)
    return out


def test_the_deployment_loads_and_the_operator_holds_the_sprint_oc_permissions(
    ignored: Path, tmp_path: Path
) -> None:
    app = "ai-engineer"
    document = script.deployment_document(
        app,
        installation_id=INSTALLATION,
        tenant=TENANT,
        component_version=script.COMPONENT_VERSION,
        queue_base=script.load_profile(app)["installation"]["temporal_task_queue"],
        temporal_address="127.0.0.1:7233",
        namespace=script.temporal_namespace(app),
    )
    _kid, jwks = dep.ensure_operator_key(ignored)
    (ignored / dep.OPERATOR_JWKS).write_text(json.dumps(jwks), encoding="utf-8")
    (ignored / dep.DEPLOYMENT).write_text(json.dumps(document), encoding="utf-8")
    (item,) = load_deployment(ignored / dep.DEPLOYMENT).applications
    binding = item.authentication.binding
    assert binding.required_component_version == script.COMPONENT_VERSION
    assert binding.supabase_project_ref == "mc-local-ai-engineer"
    assert binding.database_secret_ref == "MC_AIENG_DB_RUNTIME_DSN"
    assert item.family_writer_secret_ref == "MC_AIENG_DB_FAMILY_WRITER_DSN"
    assert item.signal_ingress_secret_ref is None
    assert item.temporal is not None and item.temporal.namespace == "mc-local-ai-engineer"
    assert item.temporal.queue_base == "biotech-research-ingestion"

    bearer = dep.mint_token(
        ignored, app, tenant=TENANT, ttl_minutes=5, subject=script.OPERATOR_SUBJECT
    )
    actor = MissionTokenVerifier((item.authentication,)).authenticate(app, bearer)
    assert str(actor.identity.tenant_id) == TENANT
    assert actor.actor.actor_id == script.OPERATOR_ACTOR

    # The same permission set as the Sprint OC operator's grant, read from its own generator.
    mc = tmp_path / "mc"
    shutil.copytree(ROOT / "deployments" / app, mc / "deployments" / app)
    sprint = dep.deployment_document(
        mc, app, component_version="1.14.0", namespace="mc-ai-engineer", tenant=TENANT
    )
    (operator,) = [
        grant
        for grant in sprint["applications"][0]["authentication"]["grants"]
        if grant["subject"] == dep.OPERATOR_SUBJECT
    ]
    assert sorted(actor.actor.permissions) == operator["permissions"]


def test_the_newest_release_with_a_release_integration_test_is_installed() -> None:
    version = script.COMPONENT_VERSION
    _component, manifest = script.release_manifest(version)
    assert manifest["component_version"] == version and manifest["postgres_major"] == 17
    compact = version.replace(".", "")
    tests = ROOT / "tests" / "integration" / "postgres"
    assert list(tests.glob(f"test_*release_{compact}.py"))
    # The runtime's required migrations are inside it (bootstrap/common_installation.py).
    from mission_control.bootstrap.common_installation import REQUIRED_MIGRATIONS

    keys = {item["key"] for item in manifest["ordered_migrations"]}
    assert keys >= REQUIRED_MIGRATIONS


def test_an_output_directory_that_git_does_not_ignore_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `run` points this process's settings home at the output directory; restore it afterwards.
    monkeypatch.setenv("MISSION_CONTROL_HOME", str(tmp_path))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    code, document = script.run(["install", "--out", str(repo / "tracked" / "ai-engineer")])
    assert (code, document["code"]) == (2, "OUTPUT_NOT_IGNORED")
    assert document["steps"] == []  # refused before any database or Temporal contact
    outside = tmp_path / "no-repository" / "ai-engineer"
    code, document = script.run(["install", "--out", str(outside)])
    assert (code, document["code"]) == (2, "OUTPUT_NOT_IN_REPOSITORY")


# ------------------------------------------------------------------------------------- container


def test_the_container_variant_changes_only_paths_and_network_names(tmp_path: Path) -> None:
    app = "ai-engineer"
    host = _entries(app, tmp_path)
    derived = dict(
        script.container_environment(
            host,
            out=tmp_path,
            database_host="application-postgres-17",
            database_port=5432,
            temporal_address="host.docker.internal:7233",
            redis_url="redis://redis:6379/0",
        )
    )
    values = dict(host)
    # The one added name: the container names the saver's server as the host processes do.
    assert set(derived) == set(values) | {"LANGGRAPH_CHECKPOINT_LOCATOR"}
    checkpoint = next(name for name in values if name.endswith("_DB_CHECKPOINT_DSN"))
    written = urlsplit(values[checkpoint])
    assert derived["LANGGRAPH_CHECKPOINT_LOCATOR"] == f"{written.hostname}:{written.port}"
    from mission_control.adapters.deep_agents.persistence import saver_locator_digest

    assert saver_locator_digest(
        derived[checkpoint], address=derived["LANGGRAPH_CHECKPOINT_LOCATOR"]
    ) == saver_locator_digest(values[checkpoint])
    assert saver_locator_digest(derived[checkpoint]) != saver_locator_digest(values[checkpoint])
    assert derived["MISSION_CONTROL_HOME"] == script.CONTAINER_HOME
    assert derived["MISSION_CONTROL_DEPLOYMENT_FILE"] == (
        f"{script.CONTAINER_HOME}/{script.CONTAINER_DEPLOYMENT}"
    )
    assert derived["MISSION_CONTROL_DEPLOYMENTS_ROOT"] == f"{script.CONTAINER_HOME}/deployments"
    assert derived["CAPABILITY_BUNDLE_LOCAL_ROOT"] == f"{script.CONTAINER_HOME}/bundles"
    assert derived["MISSION_CONTROL_WORKSPACE_ROOT"] == script.CONTAINER_WORKSPACE
    assert derived["WEB_RESEARCH_AGENT_BROWSER_NODE"] == script.CONTAINER_NODE
    assert derived["TEMPORAL_ADDRESS"] == "host.docker.internal:7233"
    for name, original in _logins(app).items():
        before, after = urlsplit(original), urlsplit(derived[name])
        assert (after.hostname, after.port, after.query) == (
            "application-postgres-17",
            5432,
            "sslmode=require",  # a non-loopback endpoint without TLS is refused by the runtime
        )
        assert (after.username, after.password, after.path) == (
            before.username,
            before.password,
            before.path,
        )
    changed = {name for name in values if derived[name] != values[name]}
    assert changed == {
        "MISSION_CONTROL_HOME",
        "MISSION_CONTROL_DEPLOYMENT_FILE",
        "MISSION_CONTROL_DEPLOYMENTS_ROOT",
        "MISSION_CONTROL_WORKSPACE_ROOT",
        "CAPABILITY_PINS_PATH",
        "CAPABILITY_BUNDLE_LOCAL_ROOT",
        "ARTIFACT_PAYLOAD_ROOT",
        "DEEP_AGENT_SANDBOX_WORKSPACE_ROOT",
        "WEB_RESEARCH_AGENT_BROWSER_NODE",
        "TEMPORAL_ADDRESS",
        "REDIS_URL",
        *_logins(app),
    }
    # A host without Node still gets the worker image's Node in the container file.
    without = dict(
        script.container_environment(
            _entries(app, tmp_path, node=None),
            out=tmp_path,
            database_host="db",
            database_port=5432,
            temporal_address="temporal:7233",
            redis_url="redis://redis:6379/0",
        )
    )
    assert without["WEB_RESEARCH_AGENT_BROWSER_NODE"] == script.CONTAINER_NODE
