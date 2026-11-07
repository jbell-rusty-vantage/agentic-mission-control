"""The companion composes ordinary controls without creating duplicate execution workers."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI

from mission_control.adapters.operations.runtime_ports import FilesystemArtifactPayloadStore
from mission_control.adapters.temporal.registration.task_queues import maintenance_task_queue
from mission_control.adapters.temporal.workflows.fork_seed import ForkSeedWorkflow
from tests.fixtures import qualia_control_api as fixture
from tests.fixtures.db_env import db_env_name
from tests.fixtures.manifest_runtime import AUTHOR


@pytest.mark.asyncio
@pytest.mark.parametrize("already_served", [True, False])
async def test_companion_has_ordinary_control_grants_and_only_missing_seed_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, already_served: bool
) -> None:
    observed: dict[str, Any] = {"workers": []}
    monkeypatch.setenv("MANIFEST_LAUNCH_BINDINGS_PATH", "primary-fixture-bindings.json")
    monkeypatch.setenv("MISSION_CONTROL_SUBSCRIPTION_RELAY", "1")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        assert "MANIFEST_LAUNCH_BINDINGS_PATH" not in os.environ
        assert os.environ["MISSION_CONTROL_SUBSCRIPTION_RELAY"] == "0"
        yield

    application = FastAPI(lifespan=lifespan)

    @application.get("/health/live")
    async def health() -> dict[str, bool]:
        return {"live": True}

    def create(deployment: Any, *, runtime_options: Any) -> FastAPI:
        observed.update(deployment=deployment, options=runtime_options)
        return application

    @asynccontextmanager
    async def worker(client: Any, **kwargs: Any) -> Any:
        observed["workers"].append((client, kwargs))
        yield

    monkeypatch.setattr(fixture, "create_application", create)
    monkeypatch.setattr(fixture, "Worker", worker)
    payloads = FilesystemArtifactPayloadStore(tmp_path / "payloads")
    monkeypatch.setattr(fixture, "artifact_payload_store", lambda _settings: payloads)
    queue = maintenance_task_queue("rrm009")
    stack = SimpleNamespace(
        database=SimpleNamespace(
            application_id="biotech",
            installation_id=UUID("0192a4f0-0000-7000-8000-00000000b10e"),
            project_ref="mcdisposablebiotech",
            tenants={"tenant-1": UUID("11111111-1111-4111-8111-111111111111")},
        ),
        payload_root=tmp_path / "payloads",
        settings=SimpleNamespace(
            task_queue_base="rrm009",
            temporal_address="127.0.0.1:7233",
            temporal_namespace="default",
        ),
        worker_queues=(queue,) if already_served else (),
        composition=SimpleNamespace(time_travel=object()),
        client=object(),
    )
    async with fixture.qualia_control_api(stack) as http:
        assert (await http.get("/health/live")).json() == {"live": True}
        assert http.headers["Authorization"].startswith("Bearer ")
        assert os.environ["MANIFEST_LAUNCH_BINDINGS_PATH"] == "primary-fixture-bindings.json"
        assert os.environ["MISSION_CONTROL_SUBSCRIPTION_RELAY"] == "1"
    deployment = observed["deployment"].applications[0]
    grant = deployment.authentication.grants[0]
    assert grant.actor_id == AUTHOR.actor_id
    assert grant.subject == "qualia-fixture-operator"
    assert {
        "workflow_run.control",
        "workflow_run.snapshot",
        "workflow_run.fork",
        "workflow_run.admit",
        "workflow_run.start",
    } <= grant.permissions
    assert deployment.temporal.address == stack.settings.temporal_address
    assert deployment.family_writer_secret_ref == db_env_name(
        stack.database.application_id, "FAMILY_WRITER_DSN"
    )
    assert len(observed["workers"]) == (0 if already_served else 1)
    if not already_served:
        client, configuration = observed["workers"][0]
        assert client is stack.client and configuration["task_queue"] == queue
        assert configuration["workflows"] == [ForkSeedWorkflow]
