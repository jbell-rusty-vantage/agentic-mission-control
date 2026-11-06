"""A present-but-empty credential setting reads as unset (Sprint OC W0 runtime environment).

An environment variable that is present, even empty, wins over the `.env` file, so the runtime
env generator blanks credentials on purpose. A blank `APPLICATION_DATABASE_URL` arrives as
`SecretStr("")`; it must not count as a configured database (the Agent Server's
`http_app.py` would otherwise try to build a DSN from it).
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from mission_control.adapters.temporal.client import (
    TemporalConnectionError,
    resolve_temporal_connection,
)
from mission_control.bootstrap.bundle_custody import compose_bundle_materializer
from mission_control.bootstrap.lanes import settings_bound_lanes
from mission_control.bootstrap.settings import configured
from tests.fixtures.isolated_settings import isolated_settings

DSN = "postgresql://runtime@db.example.invalid:5432/postgres"
BLANK = SecretStr("")


def test_configured_treats_blank_and_whitespace_as_unset() -> None:
    assert configured(None) is None
    assert configured(BLANK) is None
    assert configured(SecretStr("  ")) is None
    assert configured(SecretStr(DSN)) == SecretStr(DSN)


def test_blank_application_database_is_not_present() -> None:
    settings = isolated_settings(application_database_direct=BLANK, application_database_url=BLANK)
    assert settings.has_application_postgres is False
    with pytest.raises(ValueError, match="APPLICATION_DATABASE_DIRECT"):
        _ = settings.application_postgres_dsn


def test_a_blank_direct_dsn_falls_through_to_the_url() -> None:
    settings = isolated_settings(
        application_database_direct=BLANK, application_database_url=SecretStr(DSN)
    )
    assert settings.has_application_postgres is True
    assert settings.application_postgres_dsn == DSN


@pytest.mark.parametrize(
    ("field", "reader"),
    [
        ("application_migration_database_direct", "application_migration_postgres_dsn"),
        ("application_backfill_database_direct", "application_backfill_postgres_dsn"),
        ("application_family_writer_database_direct", "application_family_writer_postgres_dsn"),
    ],
)
def test_blank_role_dsns_are_refused_as_missing(field: str, reader: str) -> None:
    settings = isolated_settings(**{field: BLANK})
    with pytest.raises(ValueError, match="is required"):
        getattr(settings, reader)


def test_blank_family_writer_and_common_dsns() -> None:
    settings = isolated_settings(
        application_family_writer_database_direct=BLANK, database_direct=BLANK, database_url=BLANK
    )
    assert settings.has_application_family_writer_postgres is False
    with pytest.raises(ValueError, match="DATABASE_DIRECT or DATABASE_URL"):
        _ = settings.postgres_dsn


def test_blank_inspection_cursor_key_derives_from_the_signing_key() -> None:
    blank = isolated_settings(
        inspection_cursor_key=BLANK, runtime_checkpoint_signing_key=SecretStr("signing-key")
    )
    unset = isolated_settings(runtime_checkpoint_signing_key=SecretStr("signing-key"))
    assert blank.inspection_cursor_secret == unset.inspection_cursor_secret
    assert blank.inspection_cursor_secret != b""


@pytest.mark.parametrize(
    "field",
    [
        "cursor_api_key",
        "capability_bundle_reader_token",
        "capability_bundle_publisher_token",
        "temporal_cloud_api_key",
        "mission_control_secret_vault_dsn",
        "anthropic_api_key",
    ],
)
def test_every_blank_optional_secret_is_stored_as_none(field: str) -> None:
    assert getattr(isolated_settings(**{field: BLANK}), field) is None
    assert getattr(isolated_settings(**{field: SecretStr(" ")}), field) is None


def test_a_blank_cursor_key_binds_no_cursor_lane() -> None:
    bound = settings_bound_lanes(isolated_settings(cursor_api_key=SecretStr("cursor-key")))
    blank = settings_bound_lanes(isolated_settings(cursor_api_key=BLANK))
    cursor = {profile for profile in bound if profile.startswith("cursor")}
    assert cursor
    assert not cursor & blank


def test_bundle_custody_treats_a_blank_reader_token_as_absent() -> None:
    settings = isolated_settings(
        capability_bundle_backend="supabase", capability_bundle_reader_token=BLANK
    )
    assert compose_bundle_materializer(settings) is None


def test_a_blank_temporal_cloud_key_is_missing() -> None:
    settings = isolated_settings(temporal_target="cloud", temporal_cloud_api_key=BLANK)
    with pytest.raises(TemporalConnectionError, match="requires TEMPORAL_CLOUD_API_KEY"):
        resolve_temporal_connection(settings)
