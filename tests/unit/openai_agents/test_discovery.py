"""MO-34: the `codex_agents` Discovery Proof is an API read-back of the saved agent and the
environment template a session runs.

Against the stateful fake Agents API (HL-11 shapes): after a sync, the read-back finds both
resources by id through the listings and proves the pack's inline skills and its digest; a
template that lost a skill, or an agent carrying another pack digest, fails the proof. The live
response shape is UNVERIFIED until the HL-11..HL-13 drills record it.
"""

from __future__ import annotations

from mission_control.adapters.openai_agents.discovery import (
    AGENT_DIGEST,
    discovery_expectation,
    read_back,
)
from mission_control.adapters.openai_agents.pack import load_pack
from mission_control.adapters.openai_agents.prepare import PACK_KEY, CodexAgentsPreparer
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.domain.execution.discovery import DiscoveryItem, discovery_gaps
from tests.unit.openai_agents.support import SHIPPED_PACK, FakeAgentsApi

WORKER = {"MC_GITHUB_READONLY_TOKEN": "github-readonly-test-value-7f3a"}


def _preparer(api: FakeAgentsApi) -> CodexAgentsPreparer:
    return CodexAgentsPreparer(api.client(), WorkerEnvironmentSource(WORKER))


async def test_the_read_back_of_a_synced_pack_proves_it() -> None:
    api, pack = FakeAgentsApi(), load_pack(SHIPPED_PACK)
    prepared = await _preparer(api).sync(pack)
    writes = len(api.creates())

    expectation = discovery_expectation(pack)
    report = await read_back(api.client(), prepared)

    assert DiscoveryItem(kind="skill", name="cited-findings") in expectation.items
    assert expectation.digests == {AGENT_DIGEST: pack.digest}
    assert discovery_gaps(expectation, report) == ()
    assert len(api.creates()) == writes, "a read-back writes nothing"


async def test_a_template_without_the_skill_or_an_agent_of_another_pack_fails_the_proof() -> None:
    api, pack = FakeAgentsApi(), load_pack(SHIPPED_PACK)
    prepared = await _preparer(api).sync(pack)
    api.templates[prepared.template.id]["skills"] = []
    agent = api.agents[prepared.agent.id]
    agent["metadata"] = {**agent["metadata"], PACK_KEY: "sha256:" + "1" * 64}

    report = await read_back(api.client(), prepared)

    gaps = discovery_gaps(discovery_expectation(pack), report)
    assert "skill cited-findings was not reported loaded" in gaps
    assert any(gap.startswith(f"{AGENT_DIGEST} reads sha256:111") for gap in gaps)


async def test_resources_the_listing_no_longer_holds_prove_nothing() -> None:
    api, pack = FakeAgentsApi(), load_pack(SHIPPED_PACK)
    prepared = await _preparer(api).sync(pack)
    api.agents.clear()
    api.templates.clear()

    report = await read_back(api.client(), prepared)

    assert report.items == () and report.digests == {AGENT_DIGEST: None}
    assert discovery_gaps(discovery_expectation(pack), report)
