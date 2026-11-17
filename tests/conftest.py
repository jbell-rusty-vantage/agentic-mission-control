from __future__ import annotations

import asyncio
import os
import sys

import pytest

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.control_plane_repository import (
    InMemoryDefinitionRepository,
)
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.bootstrap.settings import PROJECT_ROOT
from mission_control.domain.authoring.extensions import ExtensionRegistry

# Deterministic tests must not inherit telemetry opt-in from a developer .env.
# Explicit process environment remains available to separately authorized live jobs.
os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

# Fresh checkouts and worktrees have no `.env`, but the server builds `Settings()` at
# import. Supply non-routable placeholders for the required fields only in that case;
# explicit environment values always win, and service/provider tests keep their own opt-ins.
_OFFLINE_SETTINGS_PLACEHOLDERS = {
    "MC_AIENG_DB_URL": "https://offline-placeholder.invalid",
    "MC_AIENG_DB_PUBLISHABLE_KEY": "offline-placeholder",
    "MC_AIENG_DB_SECRET_KEY": "offline-placeholder",
    "MC_BIOTECH_DB_URL": "https://offline-placeholder.invalid",
    "MC_BIOTECH_DB_PUBLISHABLE_KEY": "offline-placeholder",
    "MC_BIOTECH_DB_SECRET_KEY": "offline-placeholder",
    "OPENAI_API_KEY": "offline-placeholder",
    "MC_BIOTECH_GRAPH_URI": "neo4j://offline-placeholder.invalid:7687",
    "MC_BIOTECH_GRAPH_USERNAME": "offline-placeholder",
    "MC_BIOTECH_GRAPH_PASSWORD": "offline-placeholder",
    "MC_LOCAL_DB_ADMIN_DSN": "postgresql://offline-placeholder.invalid:5432/offline",
    "MC_LOCAL_DB_RUNTIME_DSN": "postgresql://offline-placeholder.invalid:5432/offline",
}
if not (PROJECT_ROOT / ".env").exists():
    for _name, _value in _OFFLINE_SETTINGS_PLACEHOLDERS.items():
        os.environ.setdefault(_name, _value)


def pytest_asyncio_loop_factories(config, item):  # type: ignore[no-untyped-def]
    """Keep Psycopg's Windows selector requirement local to the modules that need it."""

    del config
    if sys.platform == "win32" and item.get_closest_marker("psycopg_selector") is not None:
        return {"windows-selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}


def _required_external_test_service(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    if os.getenv("BELL_LABS_REQUIRE_STAGE3_ENTRY_SERVICES") == "1":
        pytest.fail(f"{name} is required for the Stage 3 entry evidence job")
    pytest.skip(f"{name} is not configured")


@pytest.fixture
def in_memory_control_plane_service() -> ControlPlaneService:
    return ControlPlaneService(
        InMemoryDefinitionRepository(),
        ExtensionRegistry(),
        InMemoryPayloadStore(),
    )


@pytest.fixture
def test_application_postgres_dsn() -> str:
    return _required_external_test_service("TEST_APPLICATION_POSTGRES_DSN")


# Block C live fixtures / helpers for persistent Agent Server qualification.
pytest_plugins = ["tests.fixtures.agent_server_block_c", "tests.support.db_plugin"]
