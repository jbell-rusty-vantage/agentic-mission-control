"""Sprint OC W0 (WI-24): the runtime environment generator, over fixture env files only.

Every value here is fake. The tracked `deployments/<app>` files supply the target identity
(installation ids, project refs and the Biotech graph pin are public in tracked config).
"""

from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[3]
BIOTECH_REF = "bxnetwiimwhtlrjlbtab"
AIE_REF = "wkythqbofmckbuoothhn"
BIOTECH_MC_ID = "01a103c0-9a9e-7a95-961b-29dda83c842b"
COMPONENT = "0b6a2c1e-4d3f-4a5b-8c7d-112233445566"
TENANT = "7f3e2d1c-0b9a-4876-9543-210fedcba987"
GRAPH_HOST = "8032ec07.databases.neo4j.io"  # deployments/biotech/graph.toml
BIO_DSN = f"postgresql://postgres:fake-bio-pw@db.{BIOTECH_REF}.supabase.co:5432/postgres"
AIE_DSN = (
    f"postgresql://postgres.{AIE_REF}:fake-aie-pw@aws-1.pooler.supabase.com:5432/postgres"
    "?sslmode=require"
)
SECRETS = ("fake-bio-pw", "fake-aie-pw", "fake-aura", "fake-anthropic", "fake-openai")


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "sprint_oc_runtime_env", ROOT / "scripts" / "sprint_oc_runtime_env.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gen = _module()


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _certificate(path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fake test root")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, None)
    )
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _owner_files(bellabs: Path, *, mc: str | None = None, bks: str | None = None) -> None:
    files = {
        gen.MC_ENV: mc
        if mc is not None
        else (
            "# owner MC env (fake)\n"
            f"DATABASE_DIRECT={BIO_DSN}\n"
            'export ANTHROPIC_API_KEY="fake-anthropic\\tkey"\n'
            "OPENAI_API_KEY='fake-openai-key'\n"
            "SECOND_ANTHROPIC_API_KEY=fake-auditor-key\n"
            "TEMPORAL_TASK_QUEUE=wrong-queue\n"
        ),
        gen.BKS_ENV: bks
        if bks is not None
        else (
            f"NEO4J_URI=neo4j+s://{GRAPH_HOST}\n"
            "NEO4J_AURA_USERNAME=fake-aura-user # trailing comment\n"
            "NEO4J_AURA_PASSWORD=stale\n"
            "NEO4J_AURA_PASSWORD=fake-aura-pw\n"
        ),
        gen.AIE_ENV: f"POSTGRES_URL_NON_POOLING={AIE_DSN}\n",
    }
    for relative, text in files.items():
        path = bellabs / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    bellabs = tmp_path / "bellabs"
    _owner_files(bellabs)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_text("runtime/\nsecrets.env\n", encoding="utf-8")
    ca = tmp_path / "fake-root-ca.crt"
    _certificate(ca)
    # A Mission Control root of its own (`--mc-root`): the probe writes a poisoned `.env` there.
    mc = tmp_path / "mc"
    for app in ("biotech", "ai-engineer"):
        shutil.copytree(ROOT / "deployments" / app, mc / "deployments" / app)
    return {"bellabs": bellabs, "repo": repo, "out": repo / "runtime", "ca": ca, "mc": mc}


def tls(world: dict[str, Path], dsn: str) -> str:
    return gen.tls_dsn(dsn, world["ca"].resolve())


def _run(
    world: dict[str, Path],
    *extra: str,
    app: str = "biotech",
    out: Path | None = None,
    ca: bool = True,
    fallback: bool = True,
) -> tuple[int, dict]:
    tls_args = ["--ca-file", str(world["ca"])] if ca else []
    fallback_args = ["--allow-checkpoint-fallback"] if fallback else []
    return gen.run(
        [
            "--app",
            app,
            "--bellabs-root",
            str(world["bellabs"]),
            "--mc-root",
            str(world["mc"]),
            "--out-dir",
            str(out or world["out"]),
            *tls_args,
            *fallback_args,
            *extra,
        ]
    )


def _env(path: Path) -> dict[str, str]:
    return gen.read_env(path)


CONFIRMED = (
    "--component-installation-id",
    COMPONENT,
    "--confirm-graph",
    GRAPH_HOST,
    "--allow-admin-verification-dsn",
)


def test_biotech_files_carry_owner_minted_and_derived_values(world: dict[str, Path]) -> None:
    code, summary = _run(world, *CONFIRMED, "--verification-tenant-id", TENANT)
    assert code == 0, summary
    out = world["out"] / "biotech"
    ks = _env(out / "ks-executor.env")
    bks = _env(out / "bks-executor.env")
    mc = _env(out / "mission-control.env")

    binding = json.loads(ks["KS_KNOWLEDGE_BINDINGS_JSON"])
    assert binding == [
        {
            "application": "biotech",
            "binding": "biotech-graph",
            "installationId": COMPONENT,
            "databaseUrlEnv": "KS_BIOTECH_COMPONENT_DSN",
            "tenants": [TENANT],
        }
    ]
    assert ks["KS_BIOTECH_COMPONENT_DSN"] == tls(world, BIO_DSN)
    assert "sslmode=verify-full&sslrootcert=" in ks["KS_BIOTECH_COMPONENT_DSN"]
    assert ks["KS_KNOWLEDGE_ISSUER"] == mc["KNOWLEDGE_ISSUER"] == "mission-control.biotech"
    assert ks["KS_KNOWLEDGE_AUDIENCE"] == mc["KNOWLEDGE_BINDING_AUDIENCE"]
    assert mc["KNOWLEDGE_BINDING_AUDIENCE"] == "knowledge-services-executor.biotech"
    # W1 D6: MC names the component installation the executor installs, not its own id.
    assert mc["KNOWLEDGE_COMPONENT_INSTALLATION_ID"] == COMPONENT == binding[0]["installationId"]
    assert mc["KNOWLEDGE_COMPONENT_INSTALLATION_ID"] != BIOTECH_MC_ID
    assert mc["KNOWLEDGE_BINDING_URL"] == f"http://127.0.0.1:{ks['VERIFY_PORT']}"
    assert ks["KS_BIOTECH_EXECUTOR_URL"] == f"http://127.0.0.1:{bks['EXECUTOR_PORT']}"

    assert (bks["NEO4J_URI"], bks["NEO4J_USERNAME"], bks["NEO4J_PASSWORD"]) == (
        f"neo4j+s://{GRAPH_HOST}",
        "fake-aura-user",
        "fake-aura-pw",
    )
    assert bks["BKS_TARGET"] == "production"
    assert bks["BKS_NO_ENV_FILE"] == "1"
    assert bks["BKS_VERIFICATION_DSN"] == tls(world, BIO_DSN)
    assert bks["BKS_VERIFICATION_TENANTS"] == TENANT
    by_role = {entry["role"]: entry for entry in json.loads(bks["BKS_EXECUTOR_TOKENS"])}
    for role, name in (
        ("writer", "KS_BIOTECH_EXECUTOR_TOKEN"),
        ("reader", "KS_BIOTECH_EXECUTOR_READ_TOKEN"),
    ):
        assert by_role[role]["tokenSha256"] == hashlib.sha256(ks[name].encode()).hexdigest()
        assert by_role[role]["class"] == "service"
        assert by_role[role]["tenantId"] == TENANT
        assert "token" not in by_role[role]
    assert by_role["writer"]["grants"] == ["admission.dispatch"]

    assert mc["MISSION_CONTROL_APPLICATION"] == "biotech"
    assert mc["TEMPORAL_TASK_QUEUE"] == "biotech-research-ingestion"  # profile, not owner .env
    assert mc["MISSION_CONTROL_CATALOG_SCOPE"] == f"mc/{BIOTECH_MC_ID}/biotech/catalog"
    # python-dotenv semantics for the owner file: double-quoted escapes are decoded.
    assert mc["ANTHROPIC_API_KEY"] == "fake-anthropic\tkey"
    assert mc["OPENAI_API_KEY"] == "fake-openai-key"
    assert len(mc["BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN"]) >= 43
    # OVE-169: the evaluators' own names; the auditor maps the owner's SECOND key.
    assert mc["MC_JUDGE_OPENAI_API_KEY"] == "fake-openai-key"
    assert mc["MC_AUDITOR_ANTHROPIC_API_KEY"] == "fake-auditor-key"
    ks_env = _env(out / "ks-executor.env")
    assert ks_env["KS_BIOTECH_DISPATCH_DRAIN_INTERVAL_MS"] == "5000"

    install = _env(out / "install.env")
    for name in (
        "KS_KNOWLEDGE_BINDINGS_JSON",
        "KS_BIOTECH_EXECUTOR_URL",
        "KS_BIOTECH_EXECUTOR_TOKEN",
        "KS_BIOTECH_EXECUTOR_READ_TOKEN",
        "NEO4J_URI",
        "NEO4J_USERNAME",
        "NEO4J_PASSWORD",
        "BKS_EXECUTOR_TOKENS",
        "BKS_VERIFICATION_DSN",
        "BKS_VERIFICATION_TENANTS",
        "KS_BIOTECH_COMPONENT_DSN",
        # OVE-169 W1 D25: the installer's seal-key step.
        "KS_KNOWLEDGE_SEAL_KEY_ID",
        "KS_KNOWLEDGE_SEAL_KEY_FILE",
        "KS_KNOWLEDGE_SEAL_ISSUER",
    ):
        assert install.get(name), name
    assert ks_env["KS_KNOWLEDGE_SEAL_ISSUER"] == "knowledge-services"
    assert install["KS_KNOWLEDGE_SEAL_KEY_ID"] == ks_env["KS_KNOWLEDGE_SEAL_KEY_ID"]
    assert install["KS_KNOWLEDGE_SEAL_KEY_FILE"] == (out / "ks-seal.pem").as_posix()

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["choices"] == {
        "graph": "confirmed",
        "verificationDsn": "admin-allowed (disposable W0)",
        "checkpointDsn": "application-dsn-fallback (--allow-checkpoint-fallback)",
        "bundleCustody": "local (no bundle-custody.env)",
    }
    missing = {item["name"] for item in summary["missing"]}
    assert {
        "APPLICATION_DATABASE_DIRECT",
        "MISSION_CONTROL_DEPLOYMENT_FILE",
    } <= missing
    # Names and sources only: no value reaches the summary or the manifest.
    printed = json.dumps(summary) + (out / "manifest.json").read_text(encoding="utf-8")
    for secret in [*SECRETS, ks["KS_BIOTECH_EXECUTOR_TOKEN"], mc["RUNTIME_CHECKPOINT_SIGNING_KEY"]]:
        assert secret not in printed


def test_mission_control_file_blanks_every_inheritable_setting(world: dict[str, Path]) -> None:
    assert _run(world, "--component-installation-id", COMPONENT)[0] == 0
    text = (world["out"] / "biotech" / "mission-control.env").read_text(encoding="utf-8")
    written = {line.split("=", 1)[0] for line in text.splitlines() if line and line[0] != "#"}
    assert set(gen.MC_BLANKED) <= written
    mc = _env(world["out"] / "biotech" / "mission-control.env")
    assert all(mc[name] == "" for name in gen.MC_BLANKED)
    # A missing required name is an explicit blank too, never left to the owner `.env`.
    assert mc["APPLICATION_DATABASE_DIRECT"] == ""
    assert mc["REDIS_URL"] == gen.LOCAL_REDIS


def test_the_w1_worker_runs_the_chain_relay(world: dict[str, Path]) -> None:
    """Loop iter-1 L1-04: a released chain consumer starts only when the worker runs the relay
    (E4b consumer 2a6bc6a7 sat `pending` until a manual restart with CHAIN_RELAY_ENABLED=1)."""

    from pydantic import TypeAdapter

    from mission_control.bootstrap.settings import Settings

    assert _run(world, "--component-installation-id", COMPONENT)[0] == 0
    mc = _env(world["out"] / "biotech" / "mission-control.env")
    assert mc["CHAIN_RELAY_ENABLED"] == "1"
    assert Settings.model_fields["chain_relay_enabled"].annotation is bool
    assert TypeAdapter(bool).validate_python(mc["CHAIN_RELAY_ENABLED"]) is True
    # The relay's launch input author is the W1 harness file the launcher names.
    assert "CHAIN_RELAY_ENABLED" in gen.MC_UNMANAGED["MANIFEST_LAUNCH_BINDINGS_PATH"]


SETTINGS_PROBE = textwrap.dedent(
    """
    import json, os, re, sys
    from pathlib import Path
    from pydantic import SecretStr
    from mission_control.bootstrap import settings as module

    generated = json.loads(sys.argv[1])
    home = Path(os.environ["MISSION_CONTROL_HOME"]).resolve()
    assert module.PROJECT_ROOT == home
    kinds = re.compile(r"(str|Path|SecretStr)( [|] None)?")
    poisoned = {}
    for name, info in module.Settings.model_fields.items():
        annotation = re.sub(r"<class '([^']+)'>", r"\\1", str(info.annotation))
        annotation = annotation.replace("pydantic.types.", "").replace("pathlib.", "")
        if kinds.fullmatch(annotation):
            poisoned[name] = f"poison{len(poisoned)}"

    def value(instance, name):
        found = getattr(instance, name)
        return found.get_secret_value() if isinstance(found, SecretStr) else found

    # Control: without the generated environment the owner `.env` really is read.
    for key in generated:
        if key != "MISSION_CONTROL_HOME":
            os.environ.pop(key, None)
    (home / ".env").write_text("DATABASE_DIRECT=poison-control\\n", encoding="utf-8")
    control = value(module.Settings(), "database_direct") == "poison-control"

    (home / ".env").write_text(
        "".join(f"{n.upper()}={p}\\n" for n, p in poisoned.items()), encoding="utf-8"
    )
    os.environ.update(generated)
    loaded = module.Settings()
    leaks = sorted(n.upper() for n, p in poisoned.items() if str(value(loaded, n)) == p)
    # W1 D5: the loaded issuer and audience are K01 Names (Origin.issuer, claims iss/aud).
    from pydantic import TypeAdapter
    from mission_control.contracts.knowledge_protocol import Name
    names = TypeAdapter(Name)
    knowledge = {
        "issuer": names.validate_python(loaded.knowledge_issuer),
        "audience": names.validate_python(loaded.knowledge_binding_audience),
        "component": loaded.knowledge_component_installation_id,
    }
    defaults = {n.upper(): str(f.default) for n, f in module.Settings.model_fields.items()}
    print(json.dumps({
        "poisoned": sorted(n.upper() for n in poisoned),
        "secret": sorted(n.upper() for n, f in module.Settings.model_fields.items()
                         if "SecretStr" in str(f.annotation)),
        "control": control,
        "leaks": leaks,
        "defaults": defaults,
        "has_application_postgres": loaded.has_application_postgres,
        "knowledge": knowledge,
    }))
    """
)


def test_real_settings_loader_takes_nothing_unlisted_from_an_owner_env(
    world: dict[str, Path],
) -> None:
    assert _run(world, "--component-installation-id", COMPONENT, app="ai-engineer")[0] == 0
    generated = _env(world["out"] / "ai-engineer" / "mission-control.env")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "HOME", "WINDIR"}
    }
    environment.update(generated)
    environment.update({"PYTHONPATH": str(ROOT / "src"), "PYTHONUTF8": "1"})
    probe = subprocess.run(
        [sys.executable, "-c", SETTINGS_PROBE, json.dumps(generated)],
        env=environment,
        cwd=world["bellabs"],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert probe.returncode == 0, probe.stderr[-2000:]
    result = json.loads(probe.stdout.strip().splitlines()[-1])
    assert Path(generated["MISSION_CONTROL_HOME"]) == world["mc"].resolve()
    assert result["control"] is True  # the owner `.env` really is read without the file
    # Every str/Path/SecretStr setting is either set by the generated file or on the allowlist;
    # exactly the allowlisted ones still read the poisoned `.env` (no stale allowlist entry).
    poisoned = set(result["poisoned"])
    assert poisoned <= set(generated) | set(gen.MC_UNMANAGED)
    assert set(gen.MC_UNMANAGED) <= poisoned
    assert set(result["leaks"]) == set(gen.MC_UNMANAGED)
    assert all(gen.MC_UNMANAGED.values())
    assert set(result["secret"]) <= set(generated)
    # The explicit defaults are the real Settings defaults.
    for name, default in gen.MC_DEFAULTS.items():
        assert generated[name] == default == result["defaults"][name], name
    # A blank APPLICATION_DATABASE_URL is not a configured database (http_app.py).
    assert result["has_application_postgres"] is False
    assert result["knowledge"] == {
        "issuer": "mission-control.ai-engineer",
        "audience": "knowledge-services-executor.ai-engineer",
        "component": COMPONENT,
    }


def test_owner_env_setting_an_unmanaged_name_refuses(world: dict[str, Path]) -> None:
    _owner_files(
        world["bellabs"],
        mc=f"DATABASE_DIRECT={BIO_DSN}\nmanifest_launch_bindings_path=C:/owner/bindings.json\n",
    )
    code, summary = _run(world, "--component-installation-id", COMPONENT)
    assert (code, summary["code"]) == (2, "OWNER_ENV_SETS_UNMANAGED")
    assert "MANIFEST_LAUNCH_BINDINGS_PATH" in summary["detail"]
    assert "owner/bindings" not in json.dumps(summary)


def test_runtime_directories_are_owner_only(world: dict[str, Path]) -> None:
    assert _run(world, "--component-installation-id", COMPONENT)[0] == 0
    for name in ("payloads", "workspaces"):
        path = world["out"] / "biotech" / name
        if os.name == "nt":
            principals = gen.acl_principals(path)
            assert principals, name
            assert all(not inherited for _, inherited in principals), name
            assert {p.split("\\")[-1].lower() for p, _ in principals} == {
                os.environ["USERNAME"].lower()
            }, name
        else:
            assert path.stat().st_mode & 0o077 == 0, name


def test_graph_credentials_need_the_pinned_confirmed_host(world: dict[str, Path]) -> None:
    code, summary = _run(world, "--component-installation-id", COMPONENT)
    assert code == 0
    bks = _env(world["out"] / "biotech" / "bks-executor.env")
    assert bks["NEO4J_USERNAME"] == bks["NEO4J_PASSWORD"] == bks["NEO4J_URI"] == ""
    assert {"NEO4J_PASSWORD", "BKS_TARGET"} <= {item["name"] for item in summary["missing"]}
    assert "fake-aura" not in (world["out"] / "biotech" / "install.env").read_text(encoding="utf-8")

    wrong = _run(
        world, "--component-installation-id", COMPONENT, "--confirm-graph", "x.databases.neo4j.io"
    )
    assert wrong[1]["code"] == "GRAPH_CONFIRMATION_MISMATCH"
    refused = _run(
        world,
        "--component-installation-id",
        COMPONENT,
        "--confirm-graph",
        "4773dc72.databases.neo4j.io",
    )
    assert refused[1]["code"] == "GRAPH_HOST_REFUSED"


def test_owner_graph_other_than_the_pin_refuses(world: dict[str, Path]) -> None:
    _owner_files(world["bellabs"], bks="NEO4J_URI=neo4j+s://4773dc72.databases.neo4j.io\n")
    assert _run(world, "--component-installation-id", COMPONENT)[1]["code"] == "GRAPH_HOST_REFUSED"
    _owner_files(world["bellabs"], bks="NEO4J_URI=neo4j+s://other1.databases.neo4j.io\n")
    assert _run(world, "--component-installation-id", COMPONENT)[1]["code"] == "GRAPH_HOST_MISMATCH"


def test_confirm_graph_is_refused_for_ai_engineer(world: dict[str, Path]) -> None:
    code, summary = _run(
        world,
        "--component-installation-id",
        COMPONENT,
        "--confirm-graph",
        GRAPH_HOST,
        app="ai-engineer",
    )
    assert (code, summary["code"]) == (2, "CONFIRM_GRAPH_NOT_APPLICABLE")


def test_verification_dsn_is_missing_without_an_explicit_choice(world: dict[str, Path]) -> None:
    code, summary = _run(
        world, "--component-installation-id", COMPONENT, "--confirm-graph", GRAPH_HOST
    )
    assert code == 0
    bks = _env(world["out"] / "biotech" / "bks-executor.env")
    assert bks["BKS_VERIFICATION_DSN"] == ""
    assert "BKS_VERIFICATION_DSN" in {item["name"] for item in summary["missing"]}
    assert summary["choices"]["verificationDsn"] == "missing"


def test_more_than_one_tenant_refuses(world: dict[str, Path]) -> None:
    other = "11111111-2222-4333-8444-555555555555"
    code, summary = _run(
        world,
        "--component-installation-id",
        COMPONENT,
        "--verification-tenant-id",
        TENANT,
        "--verification-tenant-id",
        other,
    )
    assert (code, summary["code"]) == (2, "TENANT_MULTIPLE_UNSUPPORTED")


def test_reruns_reuse_minted_values_and_keys(world: dict[str, Path]) -> None:
    assert _run(world, "--component-installation-id", COMPONENT)[0] == 0
    out = world["out"] / "biotech"
    first = _env(out / "minted.env")
    jwk = (out / "knowledge-issuer.jwk.json").read_bytes()
    code, summary = _run(world, "--component-installation-id", COMPONENT)
    assert code == 0
    assert summary["mintedNow"] == []
    assert _env(out / "minted.env") == first
    assert (out / "knowledge-issuer.jwk.json").read_bytes() == jwk


def test_a_lost_minted_env_adopts_the_existing_key_id(world: dict[str, Path]) -> None:
    assert _run(world, "--component-installation-id", COMPONENT)[0] == 0
    out = world["out"] / "biotech"
    kid = json.loads((out / "knowledge-issuer.jwk.json").read_text(encoding="utf-8"))["kid"]
    (out / "minted.env").unlink()  # an interruption between the two writes
    code, summary = _run(world, "--component-installation-id", COMPONENT)
    assert code == 0, summary
    assert _env(out / "minted.env")["KNOWLEDGE_ISSUER_KEY_ID"] == kid
    assert _env(out / "mission-control.env")["KNOWLEDGE_ISSUER_KEY_ID"] == kid


def test_issuer_jwks_and_seal_key_are_usable(world: dict[str, Path]) -> None:
    assert _run(world, "--component-installation-id", COMPONENT)[0] == 0
    out = world["out"] / "biotech"
    private = json.loads((out / "knowledge-issuer.jwk.json").read_text(encoding="utf-8"))
    public = json.loads((out / "knowledge-issuer.jwks.json").read_text(encoding="utf-8"))["keys"]
    kid = _env(out / "mission-control.env")["KNOWLEDGE_ISSUER_KEY_ID"]
    assert private["kid"] == kid
    assert private["crv"] == "Ed25519"
    assert private["d"]
    assert public == [
        {
            "kty": "OKP",
            "crv": "Ed25519",
            "x": private["x"],
            "kid": kid,
            "alg": "EdDSA",
            "use": "sig",
        }
    ]
    seal = serialization.load_pem_private_key((out / "ks-seal.pem").read_bytes(), password=None)
    assert type(seal).__name__.startswith("Ed25519")


def test_secret_files_are_owner_only(world: dict[str, Path]) -> None:
    assert _run(world, *CONFIRMED)[0] == 0
    out = world["out"] / "biotech"
    secret = [
        "minted.env",
        "knowledge-issuer.jwk.json",
        "ks-seal.pem",
        "ks-executor.env",
        "bks-executor.env",
        "install.env",
        "mission-control.env",
    ]
    for name in secret:
        path = out / name
        if os.name == "nt":
            principals = gen.acl_principals(path)
            user = os.environ["USERNAME"].lower()
            assert principals, name
            assert all(not inherited for _, inherited in principals), name
            assert {p.split("\\")[-1].lower() for p, _ in principals} == {user}, name
        else:
            assert path.stat().st_mode & 0o077 == 0, name
    assert not list(out.glob("*.tmp-*"))


def test_require_complete_writes_no_runnable_file_while_names_are_missing(
    world: dict[str, Path],
) -> None:
    assert _run(world, *CONFIRMED)[0] == 0
    out = world["out"] / "biotech"
    assert (out / "mission-control.env").is_file()
    code, summary = _run(world, *CONFIRMED, "--require-complete")
    assert code == 3
    assert summary["status"] == "incomplete"
    assert not (out / "mission-control.env").exists()  # the stale runnable copy is removed
    assert (out / "mission-control.env.incomplete").is_file()
    # The complete files stay runnable.
    assert (out / "install.env").is_file()
    assert not (out / "install.env.incomplete").exists()


def test_installation_id_is_required_and_nothing_is_written(world: dict[str, Path]) -> None:
    code, summary = _run(world)
    assert (code, summary["code"]) == (2, "INSTALLATION_ID_REQUIRED")
    assert not world["out"].exists()


def test_receipt_supplies_ids_and_mismatches_refuse(world: dict[str, Path], tmp_path: Path) -> None:
    def receipt(component: str, mc: str) -> Path:
        path = tmp_path / f"receipt-{component[:4]}-{mc[:4]}.json"
        steps = [
            {"step": "component", "details": {"installationId": component}},
            {"step": "mission-control", "details": {"installationId": mc}},
        ]
        path.write_text(
            json.dumps({"format": "biotech-install-receipt.v1", "steps": steps}), encoding="utf-8"
        )
        return path

    good = receipt(COMPONENT, BIOTECH_MC_ID)
    assert _run(world, "--receipt", str(good))[0] == 0
    binding = json.loads(
        _env(world["out"] / "biotech" / "ks-executor.env")["KS_KNOWLEDGE_BINDINGS_JSON"]
    )
    assert binding[0]["installationId"] == COMPONENT
    other = "11111111-2222-4333-8444-555555555555"
    mismatch = _run(world, "--receipt", str(good), "--component-installation-id", other)
    assert mismatch[1]["code"] == "INSTALLATION_ID_MISMATCH"
    assert _run(world, "--receipt", str(receipt(COMPONENT, other)))[1]["code"] == (
        "MC_INSTALLATION_MISMATCH"
    )


def test_ids_file_supplies_and_records_installation_ids(world: dict[str, Path]) -> None:
    ids = world["out"] / "installation-ids.json"
    ids.parent.mkdir(parents=True)
    ids.write_text(json.dumps({"biotech": COMPONENT}), encoding="utf-8")
    assert _run(world)[0] == 0
    other = "11111111-2222-4333-8444-555555555555"
    assert _run(world, "--component-installation-id", other)[1]["code"] == (
        "INSTALLATION_ID_MISMATCH"
    )
    assert _run(world, "--component-installation-id", other, app="ai-engineer")[0] == 0
    assert json.loads(ids.read_text(encoding="utf-8")) == {
        "ai-engineer": other,
        "biotech": COMPONENT,
    }


def test_output_must_be_ignored_and_untracked(world: dict[str, Path]) -> None:
    code, summary = _run(
        world, "--component-installation-id", COMPONENT, out=world["repo"] / "visible"
    )
    assert (code, summary["code"]) == (2, "OUTPUT_NOT_IGNORED")
    tracked = world["out"] / "biotech" / "minted.env"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("", encoding="utf-8")
    _git(world["repo"], "add", "-f", str(tracked))
    assert _run(world, "--component-installation-id", COMPONENT)[1]["code"] == "OUTPUT_TRACKED"


@pytest.mark.parametrize(
    "host",
    [
        "db.someotherprojectxxxx.supabase.co",
        f"db.{BIOTECH_REF}.supabase.co.evil.example",
        f"x{BIOTECH_REF}.supabase.co",
    ],
)
def test_dsn_must_name_the_target_project_exactly(world: dict[str, Path], host: str) -> None:
    _owner_files(
        world["bellabs"], mc=f"DATABASE_DIRECT=postgresql://postgres:fake@{host}:5432/postgres\n"
    )
    code, summary = _run(world, "--component-installation-id", COMPONENT)
    assert (code, summary["code"]) == (2, "TARGET_IDENTITY_MISMATCH")
    assert "fake@" not in json.dumps(summary)


def test_pooler_login_must_carry_the_ref(world: dict[str, Path]) -> None:
    assert gen.dsn_project_ref(AIE_DSN) == AIE_REF
    assert gen.dsn_project_ref("postgresql://postgres:x@aws-1.pooler.supabase.com:5432/p") is None
    assert gen.dsn_project_ref(f"postgresql://u:x@db.{BIOTECH_REF}.supabase.co/p") == BIOTECH_REF


def test_ca_file_is_always_validated(world: dict[str, Path], tmp_path: Path) -> None:
    junk = tmp_path / "not-a-cert.crt"
    junk.write_text("not a certificate", encoding="utf-8")
    code, summary = gen.run(
        [
            "--app",
            "biotech",
            "--bellabs-root",
            str(world["bellabs"]),
            "--out-dir",
            str(world["out"]),
            "--ca-file",
            str(junk),
            "--component-installation-id",
            COMPONENT,
        ]
    )
    assert (code, summary["code"]) == (2, "CA_FILE_INVALID")
    assert _run(world, "--component-installation-id", COMPONENT, ca=False)[1]["code"] == (
        "CA_FILE_MISSING"
    )


def test_integrator_env_fills_restricted_logins(world: dict[str, Path]) -> None:
    secrets_file = world["repo"] / "secrets.env"
    runtime = (
        f"postgresql://mc_runtime_login.{AIE_REF}:fake-rt@aws-1.pooler.supabase.com:5432/postgres"
    )
    secrets_file.write_text(f"MC_RUNTIME_DSN={runtime}\n", encoding="utf-8")
    args = ("--component-installation-id", COMPONENT, "--integrator-env", str(secrets_file))
    assert _run(world, *args, app="ai-engineer")[0] == 0
    mc = _env(world["out"] / "ai-engineer" / "mission-control.env")
    assert mc["APPLICATION_DATABASE_DIRECT"] == tls(world, runtime)
    assert mc["MC_AI_ENGINEER_RUNTIME_DSN"] == tls(world, runtime)
    secrets_file.write_text("SOMETHING_ELSE=x\n", encoding="utf-8")
    assert _run(world, *args, app="ai-engineer")[1]["code"] == "INTEGRATOR_ENV_UNKNOWN_NAMES"


def test_ai_engineer_has_no_graph_executor(world: dict[str, Path]) -> None:
    code, _ = _run(world, "--component-installation-id", COMPONENT, app="ai-engineer")
    assert code == 0
    out = world["out"] / "ai-engineer"
    assert not (out / "bks-executor.env").exists()
    ks = _env(out / "ks-executor.env")
    # OVE-169 W1 D25: install.env carries exactly the seal-key step's names, the executor's values.
    install = _env(out / "install.env")
    assert set(install) == {
        "KS_KNOWLEDGE_SEAL_KEY_ID",
        "KS_KNOWLEDGE_SEAL_KEY_FILE",
        "KS_KNOWLEDGE_SEAL_ISSUER",
    }
    assert install == {name: ks[name] for name in install}
    assert install["KS_KNOWLEDGE_SEAL_KEY_FILE"] == (out / "ks-seal.pem").as_posix()
    assert ks["KS_AI_ENGINEER_COMPONENT_DSN"] == tls(world, AIE_DSN)
    assert ks["KNOWLEDGE_DB_URL"] == tls(world, AIE_DSN)
    assert "sslmode=require" not in ks["KNOWLEDGE_DB_URL"]
    binding = json.loads(ks["KS_KNOWLEDGE_BINDINGS_JSON"])[0]
    assert binding["binding"] == "aiengineer-postgres"
    assert "tenants" not in binding
    assert "KS_BIOTECH_EXECUTOR_TOKEN" not in ks
    assert _env(out / "mission-control.env")["MISSION_CONTROL_APPLICATION"] == "ai-engineer"
    assert ks["VERIFY_PORT"] == "4310"


def test_one_mission_control_root_for_home_deployments_and_pins(world: dict[str, Path]) -> None:
    assert _run(world, "--component-installation-id", COMPONENT)[0] == 0
    mc = _env(world["out"] / "biotech" / "mission-control.env")
    home = world["mc"].resolve().as_posix()
    assert mc["MISSION_CONTROL_HOME"] == home
    assert mc["MISSION_CONTROL_DEPLOYMENTS_ROOT"] == f"{home}/deployments"
    assert mc["CAPABILITY_PINS_PATH"].startswith(f"{home}/infra/")
    manifest = json.loads((world["out"] / "biotech" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mcRoot"] == home
    assert any("canonical checkout" in warning for warning in manifest["warnings"])


def test_the_layered_env_of_the_mc_root_is_checked_too(world: dict[str, Path]) -> None:
    (world["mc"] / ".env").write_text("CURSOR_LEASE_ROOT=C:/elsewhere\n", encoding="utf-8")
    code, summary = _run(world, "--component-installation-id", COMPONENT)
    assert (code, summary["code"]) == (2, "OWNER_ENV_SETS_UNMANAGED")
    assert "CURSOR_LEASE_ROOT" in summary["detail"]


def test_a_missing_checkpoint_dsn_is_never_a_silent_fallback(world: dict[str, Path]) -> None:
    out = world["out"] / "ai-engineer"
    code, summary = _run(
        world, "--component-installation-id", COMPONENT, app="ai-engineer", fallback=False
    )
    assert code == 3
    assert summary["choices"]["checkpointDsn"] == "missing"
    assert not (out / "mission-control.env").exists()
    assert (out / "mission-control.env.incomplete").is_file()

    code, summary = _run(world, "--component-installation-id", COMPONENT, app="ai-engineer")
    assert code == 0
    assert summary["choices"]["checkpointDsn"].startswith("application-dsn-fallback")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert any("mission_control_checkpointer" in warning for warning in manifest["warnings"])
    assert (out / "mission-control.env").is_file()
    assert not (out / "mission-control.env.incomplete").exists()


def test_an_integrator_checkpoint_dsn_needs_no_fallback(world: dict[str, Path]) -> None:
    secrets_file = world["repo"] / "secrets.env"
    saver = f"postgresql://mc_saver_login.{AIE_REF}:fake-cp@aws-1.pooler.supabase.com:5432/postgres"
    secrets_file.write_text(f"MC_CHECKPOINTER_DSN={saver}\n", encoding="utf-8")
    code, summary = _run(
        world,
        "--component-installation-id",
        COMPONENT,
        "--integrator-env",
        str(secrets_file),
        app="ai-engineer",
        fallback=False,
    )
    assert code == 0, summary
    assert summary["choices"]["checkpointDsn"] == "integrator"
    mc = _env(world["out"] / "ai-engineer" / "mission-control.env")
    assert mc["LANGGRAPH_CHECKPOINT_DATABASE_DIRECT"] == tls(world, saver)


# ------------------------------------------------------------------------- bundle custody


def _custody(world: dict[str, Path], app: str, **claims: object) -> None:
    """A fake bundle-custody.env with unsigned-shape tokens (the generator checks shape only)."""

    import base64
    import time

    ref = {"ai-engineer": AIE_REF, "biotech": BIOTECH_REF}[app]
    lines = []
    for name, role in (
        ("CAPABILITY_BUNDLE_PUBLISHER_TOKEN", "publisher"),
        ("CAPABILITY_BUNDLE_READER_TOKEN", "reader"),
    ):
        body = {
            "iss": f"https://{ref}.supabase.co/auth/v1",
            "mc_capability_role": role,
            "exp": int(time.time()) + 3600,
            **claims,
        }
        payload = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
        lines.append(f"{name}=eyJhbGciOiJIUzI1NiJ9.{payload}.fake-signature-{role}")
    path = world["out"] / app / "bundle-custody.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_bundle_custody_tokens_pass_into_mission_control_env(world: dict[str, Path]) -> None:
    _owner_files(
        world["bellabs"],
        mc=f"DATABASE_DIRECT={BIO_DSN}\nSUPABASE_URL=https://{BIOTECH_REF}.supabase.co\n"
        "SUPABASE_PUBLISHABLE_KEY=fake-biotech-publishable\n",
    )
    aie = world["bellabs"] / gen.AIE_ENV
    aie.write_text(
        f"POSTGRES_URL_NON_POOLING={AIE_DSN}\nSUPABASE_URL=https://{AIE_REF}.supabase.co\n"
        "SUPABASE_PUBLISHABLE_KEY=fake-aie-publishable\n",
        encoding="utf-8",
    )
    _custody(world, "ai-engineer")
    code, summary = _run(world, "--component-installation-id", COMPONENT, app="ai-engineer")
    assert code == 0, summary
    mc = _env(world["out"] / "ai-engineer" / "mission-control.env")
    custody = _env(world["out"] / "ai-engineer" / "bundle-custody.env")
    assert mc["CAPABILITY_BUNDLE_BACKEND"] == "supabase"
    assert mc["CAPABILITY_BUNDLE_NAMESPACE"] == "ai-engineer"
    assert mc["CAPABILITY_BUNDLE_READER_TOKEN"] == custody["CAPABILITY_BUNDLE_READER_TOKEN"]
    # The application's own project, never the MC `.env` (which names biotech).
    assert mc["SUPABASE_URL"] == f"https://{AIE_REF}.supabase.co"
    assert mc["SUPABASE_PUBLISHABLE_KEY"] == "fake-aie-publishable"
    assert summary["choices"]["bundleCustody"].startswith("supabase")
    assert "fake-signature" not in json.dumps(summary)


def test_the_publisher_token_never_reaches_a_runtime_env(world: dict[str, Path]) -> None:
    aie = world["bellabs"] / gen.AIE_ENV
    aie.write_text(
        f"POSTGRES_URL_NON_POOLING={AIE_DSN}\nSUPABASE_URL=https://{AIE_REF}.supabase.co\n"
        "SUPABASE_PUBLISHABLE_KEY=fake-aie-publishable\n",
        encoding="utf-8",
    )
    _custody(world, "ai-engineer")
    assert _run(world, "--component-installation-id", COMPONENT, app="ai-engineer")[0] == 0
    out = world["out"] / "ai-engineer"
    publisher_token = _env(out / "bundle-custody.env")["CAPABILITY_BUNDLE_PUBLISHER_TOKEN"]
    for runtime in ("mission-control.env", "agent-server.env", "ks-executor.env"):
        text = (out / runtime).read_text(encoding="utf-8")
        assert publisher_token not in text, runtime
        assert _env(out / runtime).get("CAPABILITY_BUNDLE_PUBLISHER_TOKEN", "") == "", runtime
    publisher = _env(out / "bundle-publisher.env")
    assert publisher["CAPABILITY_BUNDLE_PUBLISHER_TOKEN"] == publisher_token
    assert publisher["SUPABASE_URL"] == f"https://{AIE_REF}.supabase.co"
    assert publisher["SUPABASE_PUBLISHABLE_KEY"] == "fake-aie-publishable"
    assert publisher["CAPABILITY_BUNDLE_NAMESPACE"] == "ai-engineer"
    assert publisher["MISSION_CONTROL_APPLICATION"] == "ai-engineer"
    assert all(publisher[name] == "" for name in ("DATABASE_DIRECT", "SUPABASE_SECRET_KEY"))
    assert "ANTHROPIC_API_KEY" not in publisher
    # The runtime reader token is not an operator credential either.
    reader_token = _env(out / "bundle-custody.env")["CAPABILITY_BUNDLE_READER_TOKEN"]
    assert publisher["CAPABILITY_BUNDLE_READER_TOKEN"] == ""
    assert reader_token not in (out / "bundle-publisher.env").read_text(encoding="utf-8")
    # Owner-only like every other secret file.
    if os.name == "nt":
        principals = gen.acl_principals(out / "bundle-publisher.env")
        assert principals
        assert all(not inherited for _, inherited in principals)


def test_agent_server_env_keeps_supabase_auth_off(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real `agent_server/auth.py` loader: the generated Agent Server env derives no issuer,
    so the worker's `bl1.` scope claims stay the only Agent Server credential (today's local W1);
    `mission-control.env` (API, worker) does carry SUPABASE_URL for the custody reader."""

    from mission_control.adapters.agent_server import auth

    aie = world["bellabs"] / gen.AIE_ENV
    aie.write_text(
        f"POSTGRES_URL_NON_POOLING={AIE_DSN}\nSUPABASE_URL=https://{AIE_REF}.supabase.co\n"
        "SUPABASE_PUBLISHABLE_KEY=fake-aie-publishable\n",
        encoding="utf-8",
    )
    _custody(world, "ai-engineer")
    assert _run(world, "--component-installation-id", COMPONENT, app="ai-engineer")[0] == 0
    out = world["out"] / "ai-engineer"

    def configured(env_file: str) -> bool:
        for name, value in _env(out / env_file).items():
            monkeypatch.setenv(name, value)
        return auth.authentication_is_configured()

    agent = _env(out / "agent-server.env")
    assert agent["SUPABASE_URL"] == agent["BELL_LABS_AGENT_AUTH_ISSUER"] == ""
    assert agent["BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN"]
    assert configured("agent-server.env") is False
    assert configured("mission-control.env") is True
    assert configured("agent-server.env") is False


def test_without_custody_the_backend_is_local_and_tokens_blank(world: dict[str, Path]) -> None:
    assert _run(world, "--component-installation-id", COMPONENT)[0] == 0
    mc = _env(world["out"] / "biotech" / "mission-control.env")
    assert mc["CAPABILITY_BUNDLE_BACKEND"] == "local"
    assert mc["CAPABILITY_BUNDLE_READER_TOKEN"] == mc["SUPABASE_URL"] == ""


@pytest.mark.parametrize(
    ("claims", "code"),
    [
        ({"iss": f"https://{BIOTECH_REF}.supabase.co/auth/v1"}, "BUNDLE_CUSTODY_INVALID"),
        ({"exp": 1}, "BUNDLE_CUSTODY_EXPIRED"),
        ({"exp": "soon"}, "BUNDLE_CUSTODY_INVALID"),
        ({"exp": None}, "BUNDLE_CUSTODY_INVALID"),
        ({"exp": [1]}, "BUNDLE_CUSTODY_INVALID"),
    ],
)
def test_custody_tokens_for_another_project_or_expired_refuse(
    world: dict[str, Path], claims: dict[str, object], code: str
) -> None:
    _custody(world, "ai-engineer", **claims)
    result = _run(world, "--component-installation-id", COMPONENT, app="ai-engineer")
    assert (result[0], result[1]["code"]) == (2, code)


def test_custody_needs_the_application_project_url(world: dict[str, Path]) -> None:
    # aiengineer/.env names no SUPABASE_URL; the MC `.env` (biotech) must not stand in.
    _owner_files(
        world["bellabs"],
        mc=f"DATABASE_DIRECT={BIO_DSN}\nSUPABASE_URL=https://{BIOTECH_REF}.supabase.co\n",
    )
    _custody(world, "ai-engineer")
    result = _run(world, "--component-installation-id", COMPONENT, app="ai-engineer")
    assert (result[0], result[1]["code"]) == (2, "SUPABASE_URL_MISMATCH")


def _aie_project_env(world: dict[str, Path]) -> None:
    (world["bellabs"] / gen.AIE_ENV).write_text(
        f"POSTGRES_URL_NON_POOLING={AIE_DSN}\nSUPABASE_URL=https://{AIE_REF}.supabase.co\n"
        "SUPABASE_PUBLISHABLE_KEY=fake-aie-publishable\n",
        encoding="utf-8",
    )


def test_files_a_run_does_not_produce_are_removed(world: dict[str, Path]) -> None:
    """Custody back to local: the earlier operator file (a live publisher token) must not stay."""

    _aie_project_env(world)
    _custody(world, "ai-engineer")
    out = world["out"] / "ai-engineer"
    assert _run(world, "--component-installation-id", COMPONENT, app="ai-engineer")[0] == 0
    assert (out / "bundle-publisher.env").is_file()
    (out / "bundle-publisher.env.incomplete").write_text("stale\n", encoding="utf-8")
    (out / "bundle-custody.env").unlink()
    code, summary = _run(world, "--component-installation-id", COMPONENT, app="ai-engineer")
    assert code == 0, summary
    assert summary["choices"]["bundleCustody"].startswith("local")
    assert not (out / "bundle-publisher.env").exists()
    assert not (out / "bundle-publisher.env.incomplete").exists()
    assert {p.name for p in out.glob("*.env*")} == {
        "minted.env",
        "ks-executor.env",
        "mission-control.env",
        "agent-server.env",
        "install.env",
    }


def test_a_held_mission_control_env_holds_the_agent_server_env(world: dict[str, Path]) -> None:
    out = world["out"] / "ai-engineer"
    assert _run(world, "--component-installation-id", COMPONENT, app="ai-engineer")[0] == 0
    assert (out / "agent-server.env").is_file()
    code, _ = _run(
        world, "--component-installation-id", COMPONENT, app="ai-engineer", fallback=False
    )
    assert code == 3
    for name in ("mission-control.env", "agent-server.env"):
        assert not (out / name).exists(), name
        assert (out / f"{name}.incomplete").is_file(), name
    assert (out / "ks-executor.env").is_file()


def test_custody_leaves_coordinator_auth_unchanged(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Custody writes SUPABASE_URL; `Settings.coordinator_jwt_issuer` falls back to it when
    COORDINATOR_MCP_JWT_ISSUER is blank. The generated file pins the coordinator MCP surface off
    in both modes, so custody cannot switch Supabase JWT auth on for it."""

    from mission_control.bootstrap.settings import Settings

    _aie_project_env(world)
    out = world["out"] / "ai-engineer"
    assert _run(world, "--component-installation-id", COMPONENT, app="ai-engineer")[0] == 0
    local = _env(out / "mission-control.env")
    _custody(world, "ai-engineer")
    assert _run(world, "--component-installation-id", COMPONENT, app="ai-engineer")[0] == 0
    custody = _env(out / "mission-control.env")
    assert local["SUPABASE_URL"] == "" and custody["SUPABASE_URL"]
    coordinator = sorted(name for name in local if name.startswith("COORDINATOR_"))
    assert [custody[name] for name in coordinator] == [local[name] for name in coordinator]
    assert custody["COORDINATOR_MCP_ENABLED"] == "false"
    assert custody["COORDINATOR_MCP_JWT_ISSUER"] == ""
    # An inherited `COORDINATOR_MCP_ENABLED=true` (shell or owner `.env`) loses to the file.
    monkeypatch.setenv("COORDINATOR_MCP_ENABLED", "true")
    for name, value in custody.items():
        monkeypatch.setenv(name, value)
    assert Settings(_env_file=None).coordinator_mcp_enabled is False


def test_a_shared_auditor_key_and_the_deployment_namespace(world: dict[str, Path]) -> None:
    """OVE-169: an auditor key equal to the producer's refuses; the deployment file's Temporal
    namespace and the local-operator options factory reach mission-control.env."""

    _owner_files(
        world["bellabs"],
        mc=(
            f"DATABASE_DIRECT={BIO_DSN}\n"
            "ANTHROPIC_API_KEY=fake-anthropic-same\n"
            "SECOND_ANTHROPIC_API_KEY=fake-anthropic-same\n"
            "OPENAI_API_KEY=fake-openai-key\n"
        ),
    )
    code, summary = _run(world, *CONFIRMED)
    assert code == 2 and summary["code"] == "AUDITOR_CREDENTIAL_SHARED"
    _owner_files(world["bellabs"])
    deployment = world["repo"] / "runtime" / "deployment.json"
    deployment.parent.mkdir(parents=True, exist_ok=True)
    binding = {"application_id": "biotech", "installation_id": BIOTECH_MC_ID}
    binding["binding_digest"] = "sha256:" + "c" * 64
    deployment.write_text(
        json.dumps(
            {
                "applications": [
                    {
                        "authentication": {"binding": binding},
                        "temporal": {"namespace": "mc-biotech"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    code, summary = _run(world, *CONFIRMED, "--deployment-file", str(deployment))
    assert code in {0, 3}, summary
    mc = _env(world["out"] / "biotech" / "mission-control.env.incomplete")
    if not mc:
        mc = _env(world["out"] / "biotech" / "mission-control.env")
    assert mc["TEMPORAL_NAMESPACE"] == "mc-biotech"
    assert mc["MISSION_CONTROL_RUNTIME_OPTIONS_FACTORY"] == gen.RUNTIME_OPTIONS_FACTORY
    agent = _env(world["out"] / "biotech" / "agent-server.env.incomplete") or _env(
        world["out"] / "biotech" / "agent-server.env"
    )
    assert agent["MC_AUDITOR_ANTHROPIC_API_KEY"] == ""
