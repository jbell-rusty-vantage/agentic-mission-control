"""MO-01: the materialization step every capability rows resolver shares (ADR-0024).

A definition's bytes come through short-lived signed URLs, are verified against its manifest
and cached by manifest digest; the rows resolvers and render previews materialize skill bundles
and hook scripts through it and refuse with a typed error when no custody is composed. The
Supabase reader fetches signed URLs on the configured origin only, with no bearer credential.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from mission_control.adapters.capabilities.capability_bundles import BundleError
from mission_control.adapters.capabilities.local_bundle_store import (
    FilesystemBundleFetcher,
    FilesystemBundleObjectStore,
)
from mission_control.adapters.supabase_storage import bundles as supabase_bundles
from mission_control.adapters.supabase_storage.bundles import SignedUrlBundleFetcher
from mission_control.application.authoring.control_plane_repository import (
    InMemoryDefinitionRepository,
)
from mission_control.application.authoring.provider_launch import CatalogProjectionRows
from mission_control.application.capabilities.bundle_custody import (
    BundleCustodyService,
    BundleCustodyUnavailable,
    BundleMaterializer,
    bundle_definition,
    definition_object_prefix,
)
from mission_control.domain.authoring.contracts import HookScriptDefinition, SkillDefinition
from mission_control.domain.capabilities.bundles import (
    BundleKind,
    CapabilityDrift,
    build_bundle_manifest,
)
from mission_control.domain.capabilities.catalog_entry import capability_pin
from tests.fixtures.catalog_http import catalog_harness

SKILL_FILES = (
    ("SKILL.md", b"---\nname: observe\ndescription: Observe a mission.\n---\n\nBody.\n"),
    ("scripts/tail.sh", b"#!/bin/sh\ntail -f transcript.jsonl\n"),
)
HOOK_FILES = (("policy.py", b"import json\nprint(json.dumps({'allow': True}))\n"),)
ORIGIN = "https://ref.supabase.co"


@dataclass
class CountingFetcher:
    """The local signed-URL fetcher, counting every download."""

    inner: FilesystemBundleFetcher
    urls: list[str] = field(default_factory=list)

    async def fetch(self, url: str) -> bytes:
        self.urls.append(url)
        return await self.inner.fetch(url)


async def _published(
    store: FilesystemBundleObjectStore,
    files: Sequence[tuple[str, bytes]],
    *,
    kind: BundleKind,
    capability_id: str,
    **fields: object,
) -> SkillDefinition | HookScriptDefinition:
    manifest = build_bundle_manifest(
        files,
        application_id="biotech",
        kind=kind,
        capability_id=capability_id,
        version="1.0.0",
        executable=frozenset(path for path, _ in files if path.endswith(".sh")),
    )
    await BundleCustodyService(store=store).upload(manifest, files)
    definition = bundle_definition(manifest, files, fields)
    assert isinstance(definition, SkillDefinition | HookScriptDefinition)
    return definition


def _materializer(
    root: Path, **values: int
) -> tuple[BundleMaterializer, FilesystemBundleObjectStore, CountingFetcher]:
    store = FilesystemBundleObjectStore(root)
    fetcher = CountingFetcher(FilesystemBundleFetcher(store))
    return BundleMaterializer(store, fetcher, **values), store, fetcher


# --- BundleMaterializer ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bytes_come_through_signed_urls_once_per_manifest_digest(tmp_path: Path) -> None:
    bundles, store, fetcher = _materializer(tmp_path)
    skill = await _published(store, SKILL_FILES, kind="skill_bundle", capability_id="skill.observe")
    first = await bundles.files(skill)
    assert dict(first) == dict(SKILL_FILES)
    assert len(fetcher.urls) == len(SKILL_FILES)
    assert all(url.startswith("file:") and "expires=" in url for url in fetcher.urls)
    assert await bundles.files(skill) == first
    assert len(fetcher.urls) == len(SKILL_FILES), "a cached digest is never fetched again"


@pytest.mark.asyncio
async def test_the_cache_keeps_the_most_recent_digests(tmp_path: Path) -> None:
    bundles, store, fetcher = _materializer(tmp_path, max_cached=1)
    skill = await _published(store, SKILL_FILES, kind="skill_bundle", capability_id="skill.a")
    hook = await _published(
        store,
        HOOK_FILES,
        kind="hook_script",
        capability_id="hook.a",
        events=["before_shell"],
        entrypoint="policy.py",
        interpreter="python",
    )
    await bundles.files(skill)
    await bundles.files(hook)
    await bundles.files(hook)
    assert len(fetcher.urls) == len(SKILL_FILES) + len(HOOK_FILES)
    await bundles.files(skill)  # evicted by the hook: fetched again
    assert len(fetcher.urls) == 2 * len(SKILL_FILES) + len(HOOK_FILES)


@pytest.mark.asyncio
async def test_drifted_bytes_never_materialize_or_cache(tmp_path: Path) -> None:
    bundles, store, _fetcher = _materializer(tmp_path)
    skill = await _published(store, SKILL_FILES, kind="skill_bundle", capability_id="skill.b")
    target = store.path_for(f"{definition_object_prefix(skill)}/SKILL.md")
    original = target.read_bytes()
    target.write_bytes(original.replace(b"Observe", b"0bserve"))
    with pytest.raises(CapabilityDrift):
        await bundles.files(skill)
    target.write_bytes(original)
    assert dict(await bundles.files(skill)) == dict(SKILL_FILES)


# --- The rows resolvers ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rows_carry_verified_bundle_bytes_or_refuse_without_custody(tmp_path: Path) -> None:
    bundles, store, _fetcher = _materializer(tmp_path)
    skill = await _published(store, SKILL_FILES, kind="skill_bundle", capability_id="skill.c")
    hook = await _published(
        store,
        HOOK_FILES,
        kind="hook_script",
        capability_id="hook.c",
        events=["before_shell"],
        entrypoint="policy.py",
        interpreter="python",
    )
    definitions = InMemoryDefinitionRepository()
    now = datetime.now(UTC)
    pins = [
        capability_pin(await definitions.publish(item, "test", now, 0)).render()
        for item in (skill, hook)
    ]

    rows = await CatalogProjectionRows(definitions, bundles=bundles)(pins)
    skill_row, hook_row = (rows[pin] for pin in pins)
    assert {item.path: item.content for item in skill_row.files} == dict(SKILL_FILES)
    assert {item.path for item in skill_row.files if item.executable} == {"scripts/tail.sh"}
    assert {item.path: item.content for item in hook_row.files} == dict(HOOK_FILES)

    with pytest.raises(BundleCustodyUnavailable) as refused:
        await CatalogProjectionRows(definitions, bundles=None)(pins)
    assert refused.value.logical_id == "skill.c"
    assert refused.value.code == "BUNDLE_CUSTODY_UNAVAILABLE"


@pytest.mark.asyncio
async def test_render_previews_materialize_through_custody_or_answer_503(tmp_path: Path) -> None:
    bundles, store, _fetcher = _materializer(tmp_path)
    skill = await _published(store, SKILL_FILES, kind="skill_bundle", capability_id="skill.d")
    definitions = InMemoryDefinitionRepository()
    pin = capability_pin(await definitions.publish(skill, "test", datetime.now(UTC), 0)).render()
    harness = catalog_harness(definitions, None)
    body = {"pin": pin, "host": "claude_agent_sdk"}

    refused = harness.client.post(harness.url("render"), json=body)
    assert refused.status_code == 503
    assert refused.json()["detail"]["code"] == "BUNDLE_CUSTODY_UNAVAILABLE"

    service = replace(harness.service, bundles=bundles)
    harness.app.state.mission_control_catalog_services = dict.fromkeys(
        harness.app.state.mission_control_catalog_services, service
    )
    rendered = harness.client.post(harness.url("render"), json=body)
    assert rendered.status_code == 200, rendered.text
    files = {item["path"]: item["content"] for item in rendered.json()["files"]}
    assert files[".claude/skills/observe/SKILL.md"] == SKILL_FILES[0][1].decode()


# --- The Supabase signed-URL fetcher --------------------------------------------------------


def _fetcher(handler: httpx.MockTransport) -> SignedUrlBundleFetcher:
    return SignedUrlBundleFetcher(
        httpx.Client(transport=handler, follow_redirects=False), origin=ORIGIN
    )


def test_a_signed_url_on_the_origin_is_fetched_without_a_bearer_credential() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"bytes")

    url = f"{ORIGIN}/storage/v1/object/sign/capability-bundles/biotech/x/SKILL.md?token=t"
    assert _fetcher(httpx.MockTransport(handler)).fetch_sync(url) == b"bytes"
    (request,) = seen
    assert "authorization" not in request.headers and "apikey" not in request.headers


def test_signed_urls_off_origin_failed_or_oversized_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/moved"):
            return httpx.Response(302, headers={"location": "https://elsewhere.test/x"})
        if request.url.path.endswith("/big"):
            return httpx.Response(200, content=b"x" * 32)
        return httpx.Response(404)

    fetcher = _fetcher(httpx.MockTransport(handler))
    with pytest.raises(BundleError, match="outside the configured Supabase origin"):
        fetcher.fetch_sync("https://elsewhere.test/storage/v1/object/sign/x?token=t")
    with pytest.raises(BundleError, match="HTTP 302"):
        fetcher.fetch_sync(f"{ORIGIN}/moved?token=t")
    with pytest.raises(BundleError, match="HTTP 404"):
        fetcher.fetch_sync(f"{ORIGIN}/missing?token=t")
    monkeypatch.setattr(supabase_bundles, "MAX_BUNDLE_FILE_BYTES", 16)
    with pytest.raises(BundleError, match="per-file quota"):
        fetcher.fetch_sync(f"{ORIGIN}/big?token=t")


def test_the_fetcher_needs_a_redirect_free_transport_and_an_origin() -> None:
    with pytest.raises(BundleError, match="redirects"):
        SignedUrlBundleFetcher(httpx.Client(follow_redirects=True), origin=ORIGIN)
    with pytest.raises(BundleError, match="scheme and host"):
        SignedUrlBundleFetcher(httpx.Client(follow_redirects=False), origin="ref.supabase.co")
