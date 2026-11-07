"""Composition of the bundle custody every capability rows resolver materializes through.

MO-01 (SPEC-02 §2, ADR-0024): the launch author and every lane's worker-side rows resolver
receive the same deployment-owned :class:`BundleMaterializer`, so a skill bundle or hook script
fetches through short-lived signed URLs, verifies against its manifest and is cached by digest.

``CAPABILITY_BUNDLE_BACKEND=supabase`` reads the private ``capability-bundles`` bucket with the
reader credential (never the service key); ``local`` reads the digest-path store under
``CAPABILITY_BUNDLE_LOCAL_ROOT`` that ``scripts/seeds_publish_bundles.py --storage local:DIR``
writes. Without either there is no custody: a launch that selects bundle bytes is refused with
``bundle_custody_unavailable`` instead of failing in a worker at materialization.
"""

from __future__ import annotations

import httpx

from mission_control.adapters.capabilities.local_bundle_store import (
    FilesystemBundleFetcher,
    FilesystemBundleObjectStore,
)
from mission_control.adapters.supabase_storage.bundles import (
    SignedUrlBundleFetcher,
    configured_supabase_bundle_custody,
)
from mission_control.application.capabilities.bundle_custody import BundleMaterializer
from mission_control.bootstrap.settings import Settings

STORAGE_TIMEOUT_SECONDS = 30


def compose_bundle_materializer(settings: Settings) -> BundleMaterializer | None:
    """The deployment's bundle materializer, or ``None`` when no custody is configured.

    The Supabase reader holds one process-lived HTTP client with redirects disabled; a
    configured but malformed Supabase origin fails here, at startup.
    """

    if settings.capability_bundle_backend == "supabase":
        if settings.capability_bundle_reader_token is None:
            return None
        http = httpx.Client(timeout=STORAGE_TIMEOUT_SECONDS, follow_redirects=False)
        store = configured_supabase_bundle_custody(settings, http_client=http, credential="reader")
        origin = settings.db.url or ""
        return BundleMaterializer(store, SignedUrlBundleFetcher(http, origin=origin))
    if settings.capability_bundle_local_root is None:
        return None
    local = FilesystemBundleObjectStore(settings.capability_bundle_local_root)
    return BundleMaterializer(local, FilesystemBundleFetcher(local))


__all__ = ["compose_bundle_materializer"]
