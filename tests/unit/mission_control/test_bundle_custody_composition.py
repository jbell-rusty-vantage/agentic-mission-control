"""MO-01 composition: settings -> the bundle custody every rows resolver materializes through.

The local backend reads the digest-path store under ``CAPABILITY_BUNDLE_LOCAL_ROOT``; the
Supabase backend reads with the reader credential and fetches signed URLs on its own origin.
Without either there is no custody (the launch refuses), and a configured but incomplete
Supabase origin fails at composition. Offline: no storage request is made.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mission_control.adapters.capabilities.local_bundle_store import (
    FilesystemBundleFetcher,
    FilesystemBundleObjectStore,
)
from mission_control.adapters.supabase_storage.bundles import (
    SignedUrlBundleFetcher,
    SupabaseBundleObjectStore,
)
from mission_control.bootstrap.bundle_custody import compose_bundle_materializer
from mission_control.bootstrap.settings import IntegrationConfigurationError, Settings


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "capability_bundle_local_root": None,
        "capability_bundle_reader_token": None,
        "supabase_url": None,
    }
    return Settings(_env_file=None, **(values | overrides))  # type: ignore[call-arg]


def test_the_local_backend_reads_the_digest_path_store_under_the_local_root(
    tmp_path: Path,
) -> None:
    bundles = compose_bundle_materializer(settings(capability_bundle_local_root=tmp_path))
    assert bundles is not None
    assert isinstance(bundles.store, FilesystemBundleObjectStore)
    assert bundles.store.root == (tmp_path / "capability-bundles").resolve()
    assert isinstance(bundles.fetcher, FilesystemBundleFetcher)


def test_supabase_custody_reads_with_the_reader_credential_and_signed_urls() -> None:
    bundles = compose_bundle_materializer(
        settings(
            capability_bundle_backend="supabase",
            supabase_url="https://ref.supabase.co",
            capability_bundle_reader_token="reader-jwt",
        )
    )
    assert bundles is not None
    assert isinstance(bundles.store, SupabaseBundleObjectStore)
    assert bundles.store.credential == "reader"
    assert isinstance(bundles.fetcher, SignedUrlBundleFetcher)


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"capability_bundle_backend": "supabase", "supabase_url": "https://ref.supabase.co"},
    ],
    ids=["local-without-root", "supabase-without-reader"],
)
def test_without_a_custody_source_there_is_no_custody(overrides: dict[str, object]) -> None:
    assert compose_bundle_materializer(settings(**overrides)) is None


def test_a_reader_credential_without_its_supabase_origin_fails_at_composition() -> None:
    with pytest.raises(IntegrationConfigurationError, match="SUPABASE_URL"):
        compose_bundle_materializer(
            settings(capability_bundle_backend="supabase", capability_bundle_reader_token="jwt")
        )
