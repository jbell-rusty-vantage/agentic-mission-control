"""MO45: normalized source evidence reaches the closed watcher planner."""

import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from mission_control.adapters.github.client import GitHubRestClient
from mission_control.adapters.github.signals import GitHubSignalPoller
from mission_control.adapters.temporal.activities.source_watches import (
    WorkerWatch,
    sample_worker_watch,
)
from mission_control.application.effects.ports import GitCredential
from mission_control.application.watchers.sources import cursor_status_signal, github_signal
from tests.unit.watchers.fakes import T0
from tests.unit.watchers.test_watcher_planner import plan, watcher


def fires(signal):
    descriptor = watcher(
        "source",
        {
            "on": {"signal": signal.signal_type},
            "then": [{"notify": {"kind": "progress", "text": "source"}}],
            "limits": {"max_fires": 1},
        },
    )
    assert plan([descriptor], [signal.observation()]).firings
    assert signal.frame().kind.value == "status"


@pytest.mark.parametrize(
    ("event", "payload"),
    [
        ("check_suite", {"action": "completed", "check_suite": {"conclusion": "failure"}}),
        ("pull_request", {"action": "closed", "pull_request": {"merged": True, "number": 4}}),
        ("push", {"ref": "refs/heads/main", "after": "abc"}),
    ],
)
def test_github_sources(event, payload):
    fires(github_signal(event, payload, delivery_id="verified", observed_at=T0))


@pytest.mark.parametrize("status", ["FINISHED", "ERROR"])
def test_cursor_status_is_evidence(status):
    fires(
        cursor_status_signal(
            {"event": "statusChange", "status": status, "id": "bc_1"},
            delivery_id="verified",
            observed_at=T0,
        )
    )


@pytest.mark.parametrize("kind", ["file", "log", "url"])
async def test_worker_samples(kind, tmp_path: Path):
    path = tmp_path / "result.log"
    path.write_text("SECRET material\ncomplete\n")
    watch = WorkerWatch(
        kind=kind,
        resource="https://example.test/health" if kind == "url" else str(path),
        pattern="complete" if kind == "log" else None,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    ) as http:
        signal = await sample_worker_watch(watch, registration_id="watch", now=T0, http=http)
    assert signal is not None
    assert "SECRET" not in signal.model_dump_json()
    fires(signal)


async def test_live_process_is_never_killed_or_reported_exited():
    async with httpx.AsyncClient() as http:
        assert (
            await sample_worker_watch(
                WorkerWatch(kind="process", resource=str(os.getpid())),
                registration_id="pid",
                now=T0,
                http=http,
            )
            is None
        )


async def test_exited_process_produces_watcher_evidence():
    process = await asyncio.create_subprocess_exec(sys.executable, "-c", "pass")
    await process.wait()
    async with httpx.AsyncClient() as http:
        signal = await sample_worker_watch(
            WorkerWatch(kind="process", resource=str(process.pid)),
            registration_id="exited",
            now=T0,
            http=http,
        )
    assert signal is not None
    fires(signal)


def test_url_credentials_and_relative_paths_rejected():
    with pytest.raises(ValueError):
        WorkerWatch(kind="url", resource="https://secret@example.test")
    with pytest.raises(ValueError):
        WorkerWatch(kind="file", resource="../../private")


async def test_github_poll_fallback_is_bounded_read_only_and_stable():
    repository = "https://github.com/example/repo"

    class Credentials:
        async def credential(self, target):
            assert target == repository
            return GitCredential(
                repository=target,
                username="x-access-token",
                secret=SecretStr("fixture-secret"),
                source="github_app_installation",
            )

    def respond(request):
        assert request.method == "GET"
        assert request.headers["authorization"] == "Bearer fixture-secret"
        if "/check-suites" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "check_suites": [
                        {
                            "id": 1,
                            "status": "completed",
                            "conclusion": "failure",
                            "head_branch": "main",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"number": 4, "state": "closed", "merged": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        poller = GitHubSignalPoller(GitHubRestClient(http, Credentials()), repository)
        (first,) = await poller.sample(ref="main", now=T0)
        (second,) = await poller.sample(ref="main", now=T0)
        assert first.delivery_id == second.delivery_id
        fires(first)
        fires(await poller.pull_request(4, now=T0))
        assert "fixture-secret" not in first.model_dump_json()


async def test_url_health_does_not_read_body_or_follow_redirects():
    class Unreadable(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("status probes must never materialize response bodies")
            yield b""  # pragma: no cover

    requests = []

    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(
            302, headers={"location": "https://other.test/secret"}, stream=Unreadable()
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        signal = await sample_worker_watch(
            WorkerWatch(kind="url", resource="https://health.test"),
            registration_id="health",
            now=T0,
            http=http,
        )
    assert signal.data == {"healthy": False, "status": 302}
    assert requests == ["https://health.test"]
