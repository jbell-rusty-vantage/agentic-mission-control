from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mission_control.application.execution.run_launch import RunLaunchRejected
from mission_control.application.signals.drainer import DrainRejected
from mission_control.application.signals.launch import RemoteMissionLauncher, ResolvedLaunch
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.policies.contracts import ActorContext
from tests.unit.signals.test_drainer import item


class Lifecycle:
    request_scope = "scope"

    def __init__(self):
        self.calls, self.ids = [], set()
        self.mission_id = uuid4()

    async def submit(self, request):
        self.calls.append("submit")
        self.ids.add(request.request_id)
        return SimpleNamespace(
            missions=[SimpleNamespace(run_id="run", mission_id=self.mission_id)]
        ), False

    async def start(self, run_id, actor):
        self.calls.append("start")
        if self.calls.count("start") > 1:
            raise RunLaunchRejected("run_not_pending", "already running")


class Resolver:
    def __init__(self):
        self.lifecycle = Lifecycle()

    async def resolve(self, value):
        return ResolvedLaunch(
            self.lifecycle,
            ActorContext(actor_id="operator", permissions=frozenset()),
            "manifest",
            frozenset({"sponsor"}),
        )

    async def preflight(self, launch):
        self.lifecycle.calls.append("preflight")


@pytest.mark.asyncio
async def test_launch_replay_preserves_id_and_preflight_before_submit():
    resolver = Resolver()
    launcher = RemoteMissionLauncher(resolver)
    value = replace(
        item(), kind="mission_request", payload={"inputs": {}, "inputs_digest": sha256_digest({})}
    )
    expected = {"mission_id": str(resolver.lifecycle.mission_id)}
    assert await launcher.admit(value) == expected
    assert await launcher.admit(value) == expected
    assert resolver.lifecycle.ids == {value.ingress_id}
    assert resolver.lifecycle.calls == ["preflight", "submit", "start"] * 2


@pytest.mark.asyncio
async def test_bad_inputs_refused_before_resolution():
    resolver = Resolver()
    with pytest.raises(DrainRejected, match="inputs_digest_mismatch"):
        await RemoteMissionLauncher(resolver).admit(
            replace(item(), kind="mission_request", payload={"inputs": {}, "inputs_digest": "bad"})
        )
    assert resolver.lifecycle.calls == []


@pytest.mark.asyncio
async def test_permanent_unbound_selection_is_terminal_without_dispatch_or_fallback():
    from mission_control.application.authoring.manifest_launch_inputs import (
        ManifestLaunchBindingError,
    )

    class Unbound(Lifecycle):
        async def start(self, run_id, actor):
            self.calls.append("start")
            raise ManifestLaunchBindingError("/environment/model", "private deployment detail")

    resolver = Resolver()
    resolver.lifecycle = Unbound()
    value = replace(
        item(), kind="mission_request", payload={"inputs": {}, "inputs_digest": sha256_digest({})}
    )
    with pytest.raises(DrainRejected) as refused:
        await RemoteMissionLauncher(resolver).admit(value)
    assert refused.value.code == "launch_binding_unavailable"
    assert "private" not in str(refused.value)
    assert resolver.lifecycle.calls == ["preflight", "submit", "start"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["infrastructure", "retryable", "unconfigured"])
async def test_unbound_refusal_does_not_capture_other_failures(failure):
    from mission_control.application.authoring.manifest_submit import ManifestStartUnavailable

    error = {
        "infrastructure": OSError("unavailable"),
        "retryable": RunLaunchRejected("temporary", "retry later", retryable=True),
        "unconfigured": ManifestStartUnavailable("no configured launcher"),
    }[failure]

    class Unavailable(Lifecycle):
        async def start(self, run_id, actor):
            raise error

    resolver = Resolver()
    resolver.lifecycle = Unavailable()
    value = replace(
        item(), kind="mission_request", payload={"inputs": {}, "inputs_digest": sha256_digest({})}
    )
    with pytest.raises(type(error)) as raised:
        await RemoteMissionLauncher(resolver).admit(value)
    assert raised.value is error
