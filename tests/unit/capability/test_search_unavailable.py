"""W1 D7: a ranked search branch the store refuses is a typed error, never an untyped 500.

The PostgreSQL adapter maps ``insufficient_privilege`` (no USAGE on schema ``extensions``) and
``undefined_function``/``undefined_object`` (a missing ``vector``/``pg_trgm`` object) to
``CapabilitySearchUnavailable``; manifest compile turns it into a ``CAPABILITY_UNAVAILABLE``
blocker naming the reason, and the catalog HTTP routes answer a typed 503.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mission_control.adapters.postgres.capability.capability_search_repository import _ranked
from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_service import (
    ManifestCompileService,
    ManifestProgramCompiler,
    ManifestScope,
)
from mission_control.application.capabilities.capability_search import CapabilitySearchService
from mission_control.application.capabilities.capability_search_repository import (
    CapabilitySearchUnavailable,
)
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import ManifestErrorCode
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.fixtures.mission_control_common_db import canonical_scope, catalog_scope

ROOT = Path(__file__).resolve().parents[3]
MINIMAL = ROOT / "tests/fixtures/manifests/minimal-stage-graph.yml"


class Refusing:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def fetch(self, query: str, *args: object) -> Any:
        raise self.error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (
            asyncpg.InsufficientPrivilegeError("permission denied for schema extensions"),
            "search_privileges_missing",
        ),
        (
            asyncpg.UndefinedFunctionError("function word_similarity does not exist"),
            "search_extension_missing",
        ),
        (
            asyncpg.UndefinedObjectError("type extensions.vector does not exist"),
            "search_extension_missing",
        ),
    ],
)
async def test_store_refusals_become_typed(error: Exception, reason: str) -> None:
    with pytest.raises(CapabilitySearchUnavailable) as refused:
        await _ranked(Refusing(error), "SELECT 1", (), branch="trigram")  # type: ignore[arg-type]
    assert refused.value.reason == reason and refused.value.branch == "trigram"
    assert refused.value.code == "capability_search_unavailable"


@pytest.mark.asyncio
async def test_other_database_errors_are_not_reclassified() -> None:
    with pytest.raises(asyncpg.UniqueViolationError):
        await _ranked(
            Refusing(asyncpg.UniqueViolationError("x")),  # type: ignore[arg-type]
            "SELECT 1",
            (),
            branch="lexical",
        )


class UnavailableSearch:
    """A search service whose ranked branch the store refused (D7)."""

    def __init__(self, inner: CapabilitySearchService) -> None:
        self._inner = inner

    async def search(self, request: Any) -> Any:
        raise CapabilitySearchUnavailable("search_privileges_missing", "trigram")

    def max_fused_score(self, mode: Any) -> float:
        return self._inner.max_fused_score(mode)


@pytest.mark.asyncio
async def test_compile_reports_a_typed_blocker_instead_of_raising() -> None:
    definitions, search = await fast_track_catalog()
    service = ManifestCompileService(
        definitions=definitions,
        search=UnavailableSearch(search),  # type: ignore[arg-type]
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
    )
    compilation = await service.compile(
        MINIMAL.read_text(encoding="utf-8"),
        ManifestScope(
            request_scope=canonical_scope("tenant-1", "biotech"),
            actor_id="owner",
            at=datetime(2026, 10, 28, tzinfo=UTC),
        ),
    )
    assert not compilation.ok
    blockers = [b for b in compilation.report.blockers if b.reason == "search_privileges_missing"]
    assert blockers, compilation.report.blockers
    assert all(b.code is ManifestErrorCode.CAPABILITY_UNAVAILABLE for b in blockers)
    assert "trigram branch is unavailable" in blockers[0].message
    assert "schema extensions or a relation" in blockers[0].message


def test_catalog_search_route_answers_a_typed_503(monkeypatch: pytest.MonkeyPatch) -> None:
    from mission_control.interfaces.http import catalog as routes

    app = FastAPI()
    app.include_router(routes.router)

    class Service:
        catalog_scope = catalog_scope("biotech")
        search = UnavailableSearch(None)  # type: ignore[arg-type]

    app.dependency_overrides[routes.get_mission_principal] = object
    app.dependency_overrides[routes.catalog_service] = Service
    monkeypatch.setattr(routes, "permitted", lambda *_args: None)
    response = TestClient(app).post(
        "/v1/applications/biotech/catalog/search", json={"query": "agent browser"}
    )
    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "catalog_search_unavailable"
    assert detail["reason"] == "search_privileges_missing"
    assert detail["branch"] == "trigram"
