"""Database environment contract: one plane per process, selected by MISSION_CONTROL_APPLICATION.

Fake values only; settings are built from explicit values (never `.env` or the environment).
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from mission_control.bootstrap.settings import (
    IntegrationConfigurationError,
    plane_for_application,
)
from tests.fixtures.isolated_settings import isolated_settings

REF = "abcdefghijklmnopqrst"
OTHER_REF = "zyxwvutsrqponmlkjihg"
URL = f"https://{REF}.supabase.co"
POOLER = f"postgresql://role.{REF}:fake@pooler.example.invalid:5432/postgres"
DIRECT = f"postgresql://postgres:fake@db.{REF}.supabase.co:5432/postgres"


def test_the_application_selects_the_plane() -> None:
    assert plane_for_application(None) == "LOCAL"
    assert plane_for_application("ai-engineer") == "AIENG"
    assert plane_for_application("biotech") == "BIOTECH"
    with pytest.raises(IntegrationConfigurationError, match="selects no database plane"):
        plane_for_application("elsewhere")


def test_each_plane_reads_only_its_own_variables() -> None:
    values = {
        "mc_local_db_admin_dsn": SecretStr("postgresql://local@127.0.0.1/db"),
        "mc_aieng_db_admin_dsn": SecretStr(POOLER),
        "mc_biotech_db_admin_dsn": SecretStr(DIRECT),
    }
    assert isolated_settings(**values).postgres_dsn == "postgresql://local@127.0.0.1/db"
    assert isolated_settings(mission_control_application="ai-engineer", **values).postgres_dsn == (
        POOLER
    )
    assert isolated_settings(mission_control_application="biotech", **values).postgres_dsn == (
        DIRECT
    )


def test_the_resolved_view_carries_the_selected_plane() -> None:
    settings = isolated_settings(
        mission_control_application="ai-engineer",
        mc_aieng_db_project_ref=REF,
        mc_aieng_db_url=URL,
        mc_aieng_db_runtime_dsn=SecretStr(POOLER),
        mc_aieng_db_checkpoint_dsn=SecretStr(DIRECT),
    )
    view = settings.db
    assert (view.plane, view.project_ref, view.url) == ("AIENG", REF, URL)
    assert view.env_name("runtime_dsn") == "MC_AIENG_DB_RUNTIME_DSN"
    assert settings.application_postgres_dsn == POOLER
    assert view.checkpoint_dsn is not None
    assert view.checkpoint_dsn.get_secret_value() == DIRECT
    assert settings.coordinator_jwt_issuer == f"{URL}/auth/v1"


def test_a_missing_value_names_the_selected_planes_variable() -> None:
    settings = isolated_settings(mission_control_application="biotech")
    with pytest.raises(ValueError, match="MC_BIOTECH_DB_ADMIN_DSN"):
        _ = settings.application_migration_postgres_dsn
    with pytest.raises(ValueError, match="MC_BIOTECH_DB_RUNTIME_DSN"):
        _ = settings.application_postgres_dsn


def test_the_project_ref_must_appear_in_every_sibling() -> None:
    ok = isolated_settings(
        mission_control_application="ai-engineer",
        mc_aieng_db_project_ref=REF,
        mc_aieng_db_url=URL,
        mc_aieng_db_admin_dsn=SecretStr(DIRECT),
        mc_aieng_db_runtime_dsn=SecretStr(POOLER),
    )
    assert ok.db.project_ref == REF
    with pytest.raises(ValueError, match="MC_AIENG_DB_PROJECT_REF") as raised:
        isolated_settings(
            mission_control_application="ai-engineer",
            mc_aieng_db_project_ref=OTHER_REF,
            mc_aieng_db_url=URL,
        )
    assert "MC_AIENG_DB_URL" in str(raised.value) and "fake" not in str(raised.value)
    with pytest.raises(ValueError, match="MC_BIOTECH_DB_RUNTIME_DSN"):
        isolated_settings(
            mission_control_application="biotech",
            mc_biotech_db_project_ref=REF,
            mc_biotech_db_url=URL,
            mc_biotech_db_runtime_dsn=SecretStr(f"postgresql://role.{OTHER_REF}:x@h/db"),
        )


def test_the_check_covers_only_the_selected_plane_and_never_local() -> None:
    # A mismatching AIENG block is not read while BIOTECH is selected.
    isolated_settings(
        mission_control_application="biotech",
        mc_aieng_db_project_ref=OTHER_REF,
        mc_aieng_db_url=URL,
    )
    # LOCAL has no project: an unrelated loopback DSN is accepted.
    isolated_settings(mc_local_db_runtime_dsn=SecretStr("postgresql://app@127.0.0.1:55432/db"))
    # A blank project ref is unset (no check).
    isolated_settings(
        mission_control_application="ai-engineer", mc_aieng_db_project_ref="  ", mc_aieng_db_url=URL
    )


def test_the_registry_the_settings_fields_and_the_example_list_the_same_names() -> None:
    import re
    from pathlib import Path

    import yaml

    from mission_control.bootstrap.settings import Settings

    root = Path(__file__).resolve().parents[3]
    pattern = re.compile(r"^MC_(AIENG|BIOTECH|LOCAL)_DB_[A-Z_]+$")
    registry = yaml.safe_load((root / "config" / "env.registry.yaml").read_text("utf-8"))
    names = {entry["name"] for entry in registry["variables"] if pattern.match(entry["name"])}
    fields = {name.upper() for name in Settings.model_fields if pattern.match(name.upper())}
    example = {
        match.group(1)
        for line in (root / ".env.example").read_text("utf-8").splitlines()
        if (match := re.match(r"^([A-Z][A-Z0-9_]*)=", line)) and pattern.match(match.group(1))
    }
    assert names == fields == example
    assert all(
        entry["secret"] is False
        for entry in registry["variables"]
        if entry.get("role") in {"PROJECT_REF", "URL", "PUBLISHABLE_KEY", "PORT"}
    )
    # The registry's other scopes (GitHub, Biotech graph) are listed in .env.example too.
    listed = {
        match.group(1)
        for line in (root / ".env.example").read_text("utf-8").splitlines()
        if (match := re.match(r"^([A-Z][A-Z0-9_]*)=", line))
    }
    others = {entry["name"] for entry in registry["variables"]} - names
    assert others and others <= listed
