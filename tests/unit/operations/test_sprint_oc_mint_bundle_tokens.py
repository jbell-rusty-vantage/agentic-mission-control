"""Sprint OC W0: offline capability-bundle custody tokens, and their pass-through (fake secrets)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from joserfc import jwt
from joserfc.errors import BadSignatureError
from joserfc.jwk import ECKey, OctKey

ROOT = Path(__file__).resolve().parents[3]
AIE_REF = "wkythqbofmckbuoothhn"
BIOTECH_REF = "bxnetwiimwhtlrjlbtab"
SECRET = "fake-jwt-secret-for-tests-0123456789abcdef"


def _load(name: str) -> ModuleType:
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mint = _load("sprint_oc_mint_bundle_tokens")
seeds = _load("seeds_publish_bundles")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    (root / ".gitignore").write_text("runtime/\n", encoding="utf-8")
    return root


def _env_file(tmp_path: Path, *, ref: str = AIE_REF, secret: str = SECRET) -> Path:
    path = tmp_path / "aie.env"
    path.write_text(
        f"AIENG_DB_URL=https://{ref}.supabase.co\nAIENG_DB_LEGACY_JWT_SECRET={secret}\n",
        encoding="utf-8",
    )
    return path


def _run(repo: Path, *extra: str, app: str = "ai-engineer") -> tuple[int, dict]:
    return mint.run(
        ["--app", app, "--mc-root", str(ROOT), "--out-dir", str(repo / "runtime"), *extra]
    )


def _tokens(repo: Path, app: str = "ai-engineer") -> dict[str, str]:
    return mint.runtime.read_env(repo / "runtime" / app / "bundle-custody.env")


def test_hs256_tokens_carry_the_policy_claims(repo: Path, tmp_path: Path) -> None:
    env = _env_file(tmp_path)
    code, summary = _run(
        repo, "--secret-env-file", str(env), "--secret-env", "AIENG_DB_LEGACY_JWT_SECRET"
    )
    assert code == 0, summary
    tokens = _tokens(repo)
    key = OctKey.import_key(SECRET)
    for role, name in mint.TOKENS.items():
        claims = jwt.decode(tokens[name], key).claims
        assert claims["mc_capability_role"] == role
        assert claims["role"] == claims["aud"] == "authenticated"
        assert claims["iss"] == f"https://{AIE_REF}.supabase.co/auth/v1"
        assert claims["exp"] > claims["iat"]
    publisher = jwt.decode(tokens["CAPABILITY_BUNDLE_PUBLISHER_TOKEN"], key).claims
    reader = jwt.decode(tokens["CAPABILITY_BUNDLE_READER_TOKEN"], key).claims
    assert publisher["exp"] - publisher["iat"] == 24 * 3600
    assert reader["exp"] - reader["iat"] == 7 * 86400
    assert publisher["sub"] != reader["sub"]
    # Stable: uuid5(NAMESPACE_URL, "sprint-oc:<app>:<role>").
    assert publisher["sub"] == str(
        uuid.uuid5(uuid.NAMESPACE_URL, "sprint-oc:ai-engineer:publisher")
    )
    assert reader["sub"] == str(uuid.uuid5(uuid.NAMESPACE_URL, "sprint-oc:ai-engineer:reader"))
    printed = json.dumps(summary)
    assert SECRET not in printed
    assert all(token not in printed for token in tokens.values())
    assert summary["tokens"]["CAPABILITY_BUNDLE_READER_TOKEN"]["claims"]["mc_capability_role"] == (
        "reader"
    )


def test_es256_standby_key_signs_with_its_kid(repo: Path, tmp_path: Path) -> None:
    key = ECKey.generate_key("P-256")
    pem = tmp_path / "standby.pem"
    pem.write_bytes(key.as_pem(private=True))
    env = tmp_path / "bio.env"
    env.write_text(f"MC_BIOTECH_DB_URL=https://{BIOTECH_REF}.supabase.co\n", encoding="utf-8")
    code, summary = _run(
        repo,
        "--es256-key-file",
        str(pem),
        "--kid",
        "standby-1",
        "--url-env-file",
        str(env),
        "--reader-ttl",
        "2d",
        app="biotech",
    )
    assert code == 0, summary
    token = _tokens(repo, "biotech")["CAPABILITY_BUNDLE_READER_TOKEN"]
    decoded = jwt.decode(token, ECKey.import_key(key.as_pem(private=False)))
    assert decoded.header["kid"] == "standby-1"
    assert decoded.header["alg"] == "ES256"
    assert decoded.claims["exp"] - decoded.claims["iat"] == 2 * 86400


def _rsa_pem() -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


@pytest.mark.parametrize(
    "pem",
    [
        # PEM armour around garbage (the label is split so no secret scanner reads a key here).
        b"-----BEGIN %s-----\ngarbage\n-----END %s-----\n"
        % (b"PRIVATE " + b"KEY", b"PRIVATE " + b"KEY"),
        b"not a key at all",
        # A well-formed key of another type: joserfc raises InvalidKeyTypeError (a JoseError).
        _rsa_pem(),
    ],
    ids=["garbage-pem", "garbage", "rsa-pem"],
)
def test_an_unusable_es256_key_file_refuses_cleanly(repo: Path, tmp_path: Path, pem: bytes) -> None:
    key_file = tmp_path / "standby.pem"
    key_file.write_bytes(pem)
    env = tmp_path / "bio.env"
    env.write_text(f"MC_BIOTECH_DB_URL=https://{BIOTECH_REF}.supabase.co\n", encoding="utf-8")
    code, summary = _run(
        repo,
        "--es256-key-file",
        str(key_file),
        "--kid",
        "standby-1",
        "--url-env-file",
        str(env),
        app="biotech",
    )
    assert (code, summary["code"]) == (2, "KEY_INVALID")
    assert not (repo / "runtime" / "biotech" / "bundle-custody.env").exists()


def test_the_secret_is_read_literally_without_interpolation(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `${X}` inside a secret is part of it; python-dotenv would otherwise substitute it.
    secret = "fake-${X}-jwt-secret-0123456789abcdef-0123"
    monkeypatch.setenv("X", "substituted")
    env = tmp_path / "aie.env"
    env.write_text(
        f"AIENG_DB_URL=https://{AIE_REF}.supabase.co\nAIENG_DB_LEGACY_JWT_SECRET={secret}\n",
        encoding="utf-8",
    )
    code, summary = _run(
        repo, "--secret-env-file", str(env), "--secret-env", "AIENG_DB_LEGACY_JWT_SECRET"
    )
    assert code == 0, summary
    token = _tokens(repo)["CAPABILITY_BUNDLE_READER_TOKEN"]
    assert jwt.decode(token, OctKey.import_key(secret)).claims["mc_capability_role"] == "reader"
    with pytest.raises(BadSignatureError):
        jwt.decode(token, OctKey.import_key(secret.replace("${X}", "substituted")))


def test_a_project_other_than_the_target_refuses(repo: Path, tmp_path: Path) -> None:
    env = _env_file(tmp_path, ref=BIOTECH_REF)
    code, summary = _run(
        repo, "--secret-env-file", str(env), "--secret-env", "AIENG_DB_LEGACY_JWT_SECRET"
    )
    assert (code, summary["code"]) == (2, "PROJECT_REF_MISMATCH")
    assert not (repo / "runtime").exists()


@pytest.mark.parametrize(
    ("extra", "code"),
    [
        ((), "SIGNING_MATERIAL_REQUIRED"),
        (("--secret-env", "AIENG_DB_LEGACY_JWT_SECRET", "--kid", "x"), "SIGNING_MATERIAL_REQUIRED"),
        (("--secret-env", "MISSING_NAME"), "SECRET_MISSING"),
        (("--secret-env", "AIENG_DB_LEGACY_JWT_SECRET", "--reader-ttl", "90d"), "TTL_TOO_LONG"),
        (("--secret-env", "AIENG_DB_LEGACY_JWT_SECRET", "--publisher-ttl", "soon"), "TTL_INVALID"),
    ],
)
def test_refusals(repo: Path, tmp_path: Path, extra: tuple[str, ...], code: str) -> None:
    env = _env_file(tmp_path)
    result = _run(repo, "--secret-env-file", str(env), *extra)
    assert result == (2, result[1])
    assert result[1]["code"] == code


def test_output_must_be_ignored(repo: Path, tmp_path: Path) -> None:
    env = _env_file(tmp_path)
    code, summary = mint.run(
        [
            "--app",
            "ai-engineer",
            "--mc-root",
            str(ROOT),
            "--out-dir",
            str(repo / "visible"),
            "--secret-env-file",
            str(env),
            "--secret-env",
            "AIENG_DB_LEGACY_JWT_SECRET",
        ]
    )
    assert (code, summary["code"]) == (2, "OUTPUT_NOT_IGNORED")


def test_custody_file_is_owner_only(repo: Path, tmp_path: Path) -> None:
    env = _env_file(tmp_path)
    assert (
        _run(repo, "--secret-env-file", str(env), "--secret-env", "AIENG_DB_LEGACY_JWT_SECRET")[0]
        == 0
    )
    path = repo / "runtime" / "ai-engineer" / "bundle-custody.env"
    if os.name == "nt":
        principals = mint.runtime.acl_principals(path)
        assert principals
        assert all(not inherited for _, inherited in principals)
        assert {p.split("\\")[-1].lower() for p, _ in principals} == {
            os.environ["USERNAME"].lower()
        }
    else:
        assert path.stat().st_mode & 0o077 == 0


# ------------------------------------------------------------------------- seeds publisher


@pytest.fixture
def restore_environ() -> Iterator[None]:
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def test_seed_publisher_requires_an_env_file(restore_environ: None) -> None:
    with pytest.raises(SystemExit, match="--env-file"):
        seeds.target_settings("ai-engineer", None)


def test_seed_publisher_refuses_another_project(tmp_path: Path, restore_environ: None) -> None:
    env = tmp_path / "mission-control.env"
    env.write_text(f"MC_AIENG_DB_URL=https://{BIOTECH_REF}.supabase.co\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="does not name the ai-engineer project"):
        seeds.target_settings("ai-engineer", env)


def test_seed_publisher_takes_the_target_project_from_the_env_file(
    tmp_path: Path, restore_environ: None
) -> None:
    env = tmp_path / "mission-control.env"
    env.write_text(
        f"MC_AIENG_DB_URL=https://{AIE_REF}.supabase.co\nCAPABILITY_BUNDLE_PUBLISHER_TOKEN=fake\n",
        encoding="utf-8",
    )
    settings = seeds.target_settings("ai-engineer", env)
    assert settings.db.url == f"https://{AIE_REF}.supabase.co"
    assert settings.capability_bundle_publisher_token.get_secret_value() == "fake"


# ------------------------------------------------------------------------- skill registration


register = _load("register_supabase_skill_bundle")


def test_skill_registration_refuses_a_file_without_an_application(
    tmp_path: Path, restore_environ: None
) -> None:
    env = tmp_path / "bundle-publisher.env"
    env.write_text(f"MC_AIENG_DB_URL=https://{AIE_REF}.supabase.co\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="MISSION_CONTROL_APPLICATION"):
        register.operator_settings(env)


def test_skill_registration_refuses_another_project(tmp_path: Path, restore_environ: None) -> None:
    env = tmp_path / "bundle-publisher.env"
    env.write_text(
        f"MISSION_CONTROL_APPLICATION=ai-engineer\nMC_AIENG_DB_URL=https://{BIOTECH_REF}.supabase.co\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="does not name the ai-engineer project"):
        register.operator_settings(env)
