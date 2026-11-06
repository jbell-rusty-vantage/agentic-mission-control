"""Explicit operator registrations sampled by the existing watcher Temporal loop."""

from __future__ import annotations

import logging
import os
import socket
from datetime import datetime
from typing import Literal
from uuid import UUID

import asyncpg
import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from temporalio import activity

from mission_control.adapters.github.client import GitHubRestClient
from mission_control.adapters.github.credentials import github_credentials
from mission_control.adapters.github.repositories import GitHubError
from mission_control.adapters.github.signals import GitHubSignalPoller
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.temporal.activities.source_watches import (
    WorkerWatch,
    sample_worker_watch,
)
from mission_control.application.frames.writer import FrameWriter
from mission_control.application.watchers.sources import SourceSignal, TrustedSourceSink

logger = logging.getLogger(__name__)


class SourceWatchRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,128}$")
    request_scope: str
    run_key: str
    harness_execution_id: UUID
    generation: int = Field(ge=1)
    kind: Literal["github_checks", "github_pull", "worker"]
    repository: str | None = None
    ref: str | None = None
    pull_number: int | None = Field(default=None, ge=1)
    watch: WorkerWatch | None = None
    worker_host: str | None = None

    @model_validator(mode="after")
    def complete(self) -> SourceWatchRegistration:
        if self.kind == "worker" and self.watch is None:
            raise ValueError("worker registration requires a watch")
        if self.kind == "worker" and not self.worker_host:
            raise ValueError("worker registration requires its owning worker host")
        if self.kind != "worker" and not self.repository:
            raise ValueError("GitHub registration requires a repository")
        if self.kind == "github_checks" and not self.ref:
            raise ValueError("checks registration requires a ref")
        if self.kind == "github_pull" and self.pull_number is None:
            raise ValueError("pull registration requires a number")
        return self


class RegisteredWatchSources:
    def __init__(
        self,
        pool: asyncpg.Pool,
        http: httpx.AsyncClient,
        registrations: list[SourceWatchRegistration],
    ) -> None:
        self._frames = PostgresFrameRepository(pool)
        self._http = http
        self._registrations = registrations
        if len({item.id for item in registrations}) != len(registrations):
            raise ValueError("source registration ids must be unique")
        self._github = (
            GitHubRestClient(http, github_credentials(os.environ, http))
            if any(item.kind != "worker" for item in registrations)
            else None
        )

    async def sample(self, scope: str, run_key: str, now: datetime) -> None:
        for item in self._registrations:
            if (item.request_scope, item.run_key) != (scope, run_key):
                continue
            if item.kind == "worker" and item.worker_host != socket.gethostname():
                continue
            if activity.in_activity():
                activity.heartbeat({"source": item.id, "phase": "sampling"})
            handle = await self._frames.existing_execution(
                scope, run_key, item.harness_execution_id, item.generation
            )
            if handle is None:
                continue  # Never revive a retired generation or execution.
            try:
                signals: tuple[SourceSignal, ...]
                if item.kind == "worker":
                    assert item.watch is not None
                    signal = await sample_worker_watch(
                        item.watch, registration_id=item.id, now=now, http=self._http
                    )
                    signals = (signal,) if signal is not None else ()
                else:
                    assert self._github is not None and item.repository is not None
                    poller = GitHubSignalPoller(self._github, item.repository)
                    if item.kind == "github_checks":
                        assert item.ref is not None
                        signals = await poller.sample(ref=item.ref, now=now)
                    else:
                        assert item.pull_number is not None
                        signals = (await poller.pull_request(item.pull_number, now=now),)
                sink = TrustedSourceSink(FrameWriter(self._frames, handle))
                for signal in signals:
                    await sink.emit(signal)
            except (httpx.HTTPError, GitHubError, OSError, ValueError):
                # A failed external source must not suppress journal/absence evaluation.
                logger.warning("watch source sample failed: %s", item.id)
