from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from mission_control.adapters.storage.s3 import create_aws_session, s3_client
from mission_control.bootstrap.preflight import s3_endpoint_issues
from mission_control.bootstrap.settings import Settings

SUPABASE_LOCAL = "http://127.0.0.1:54821/storage/v1/s3"


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["", None])
async def test_blank_profile_uses_environment_credentials_without_mutating_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profile: str | None
) -> None:
    monkeypatch.setenv("AWS_PROFILE", "")
    monkeypatch.setenv("AWS_DEFAULT_PROFILE", "")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "absent-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "absent-credentials"))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-environment-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-environment-secret")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    before = dict(os.environ)

    session = create_aws_session(Settings(_env_file=None, aws_profile=profile))
    credentials = await session.get_credentials()

    assert credentials is not None
    assert credentials.method == "env"
    assert (await credentials.get_frozen_credentials()).access_key == "test-environment-key"
    assert session.profile_name == "default"
    assert session._session.get_component("credential_provider").get_provider("container-role")
    assert dict(os.environ) == before


@pytest.mark.asyncio
async def test_explicit_named_profile_preserves_profile_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    credentials_file = tmp_path / "credentials"
    credentials_file.write_text(
        "[reviewed]\naws_access_key_id = test-profile-key\n"
        "aws_secret_access_key = test-profile-secret\n"
    )
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "absent-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(credentials_file))
    monkeypatch.setenv("AWS_PROFILE", "")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-environment-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-environment-secret")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    before = dict(os.environ)

    session = create_aws_session(Settings(_env_file=None, aws_profile="reviewed"))
    credentials = await session.get_credentials()

    assert credentials is not None
    assert credentials.method == "shared-credentials-file"
    assert (await credentials.get_frozen_credentials()).access_key == "test-profile-key"
    assert session.profile_name == "reviewed"
    assert dict(os.environ) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["", None])
@pytest.mark.parametrize(
    ("default_profile", "ambient_profile", "expected"),
    [("", "reviewed", "reviewed"), ("preferred", "reviewed", "preferred")],
)
async def test_blank_settings_preserve_nonempty_ambient_profile_precedence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    profile: str | None,
    default_profile: str,
    ambient_profile: str,
    expected: str,
) -> None:
    credentials_file = tmp_path / "credentials"
    credentials_file.write_text(
        "[reviewed]\naws_access_key_id = reviewed-key\naws_secret_access_key = reviewed-secret\n"
        "[preferred]\naws_access_key_id = preferred-key\naws_secret_access_key = preferred-secret\n"
    )
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "absent-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(credentials_file))
    monkeypatch.setenv("AWS_DEFAULT_PROFILE", default_profile)
    monkeypatch.setenv("AWS_PROFILE", ambient_profile)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    before = dict(os.environ)

    session = create_aws_session(Settings(_env_file=None, aws_profile=profile))
    credentials = await session.get_credentials()

    assert credentials is not None
    assert credentials.method == "shared-credentials-file"
    assert (await credentials.get_frozen_credentials()).access_key == f"{expected}-key"
    assert session.profile_name == expected
    assert dict(os.environ) == before


def _isolated_aws(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "absent-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "absent-credentials"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_PROFILE", "")
    monkeypatch.setenv("AWS_DEFAULT_PROFILE", "")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ambient-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ambient-secret")


@pytest.mark.asyncio
async def test_s3_compatible_endpoint_path_style_region_and_explicit_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """OVE-204 slice 7: the one client choke point carries the Supabase Storage endpoint,
    path-style addressing, its signing region, SigV4 and checksums only when required; the
    explicit keys win over the ambient credential chain."""

    _isolated_aws(monkeypatch, tmp_path)
    settings = Settings(
        _env_file=None,
        aws_profile=None,
        s3_endpoint_url=SUPABASE_LOCAL,
        s3_force_path_style=True,
        s3_region="local",
        s3_access_key_id="explicit-key",
        s3_secret_access_key="explicit-secret",
    )

    session = create_aws_session(settings)
    credentials = await session.get_credentials()
    assert credentials is not None and credentials.method == "explicit"
    assert (await credentials.get_frozen_credentials()).access_key == "explicit-key"
    async with s3_client(settings) as client:
        assert client.meta.endpoint_url == SUPABASE_LOCAL
        assert client.meta.region_name == "local"
        config = client.meta.config
        assert config.s3 == {"addressing_style": "path"}
        assert config.signature_version == "s3v4"
        assert config.request_checksum_calculation == "when_required"
        assert config.response_checksum_validation == "when_required"
        url = await client.generate_presigned_url(
            "get_object", Params={"Bucket": "mission-payloads", "Key": "a/b"}, ExpiresIn=60
        )
    assert url.startswith(f"{SUPABASE_LOCAL}/mission-payloads/a/b?")
    assert "X-Amz-Credential=explicit-key%2F" in url and "%2Flocal%2Fs3%2F" in url


@pytest.mark.asyncio
async def test_without_an_endpoint_the_client_stays_on_aws(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolated_aws(monkeypatch, tmp_path)
    settings = Settings(_env_file=None, aws_profile=None, aws_region="eu-west-1")

    assert settings.s3_endpoint_url is None and settings.s3_region is None
    credentials = await create_aws_session(settings).get_credentials()
    assert credentials is not None and credentials.method == "env"
    async with s3_client(settings) as client:
        assert "amazonaws.com" in client.meta.endpoint_url
        assert client.meta.region_name == "eu-west-1"
        assert client.meta.config.s3 is None


@pytest.mark.parametrize(
    "endpoint",
    ["https://abc.storage.supabase.co/storage/v1/s3", SUPABASE_LOCAL, "http://localhost:9000"],
)
def test_endpoint_is_https_or_loopback_http(endpoint: str) -> None:
    assert Settings(_env_file=None, s3_endpoint_url=endpoint).s3_endpoint_url == endpoint


@pytest.mark.parametrize(
    "endpoint", ["http://abc.storage.supabase.co/storage/v1/s3", "ftp://127.0.0.1/x", "nohost"]
)
def test_a_remote_plaintext_or_malformed_endpoint_is_refused(endpoint: str) -> None:
    with pytest.raises(ValidationError, match="S3_ENDPOINT_URL must be an https URL"):
        Settings(_env_file=None, s3_endpoint_url=endpoint)


def test_blank_endpoint_and_region_are_unset_and_keys_come_in_pairs() -> None:
    settings = Settings(_env_file=None, s3_endpoint_url=" ", s3_region="", s3_access_key_id="")
    assert settings.s3_endpoint_url is None and settings.s3_region is None
    assert settings.s3_access_key_id is None
    with pytest.raises(ValidationError, match="set together"):
        Settings(_env_file=None, s3_access_key_id="only-the-id")


def test_preflight_names_a_keyless_or_regionless_endpoint() -> None:
    bare = Settings(_env_file=None, s3_endpoint_url=SUPABASE_LOCAL)
    assert [(item.code, item.severity) for item in s3_endpoint_issues(bare)] == [
        ("S3_ENDPOINT_WITHOUT_KEYS", "blocking"),
        ("S3_ENDPOINT_REGION_DEFAULTED", "advisory"),
        ("S3_ENDPOINT_WITHOUT_BUCKET", "advisory"),
    ]
    complete = Settings(
        _env_file=None,
        s3_endpoint_url=SUPABASE_LOCAL,
        s3_region="local",
        s3_bucket="mission-payloads",
        s3_access_key_id="key",
        s3_secret_access_key="secret",
    )
    assert s3_endpoint_issues(complete) == []
