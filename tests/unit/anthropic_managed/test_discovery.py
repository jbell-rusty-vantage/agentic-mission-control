"""MO-34: the `claude_managed` Discovery Proof is an API read-back of the agent a session runs.

Against the fake Managed Agents API (HL-07 shapes): after a sync, the read-back of the prepared
agent proves every pack skill at its prepared version and the pack's materialization digest; an
agent that drifted after the sync (another writer moved a skill version or the digest) fails the
proof and names what drifted. The live read-back belongs to the hosted drills (HL-08/HL-09).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Final

import pytest

from mission_control.adapters.anthropic_managed.discovery import (
    AGENT_DIGEST,
    discovery_expectation,
    read_back,
)
from mission_control.adapters.anthropic_managed.pack import RenderedPack, load_pack, render_pack
from mission_control.adapters.anthropic_managed.prepare import (
    METADATA_DIGEST,
    ClaudeManagedPrepare,
    PreparedPack,
)
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.application.secrets.broker import SecretBroker
from mission_control.domain.execution.discovery import DiscoveryItem, discovery_gaps
from tests.fixtures.managed_agents import FakeManagedAgentsApi

PACK: Final = Path(__file__).resolve().parents[3] / "deployments/hosted-packs/ai-engineer"


@pytest.fixture
def rendered(tmp_path: Path) -> RenderedPack:
    pack_dir = tmp_path / "pack"
    shutil.copytree(PACK / "claude_managed", pack_dir)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("# Repo rules\n")
    return render_pack(
        load_pack(pack_dir), installation_id="local", repo_root=repo, ingress_host="ingress.test"
    )


async def _synced(api: FakeManagedAgentsApi, rendered: RenderedPack) -> PreparedPack:
    broker = SecretBroker(
        environment=WorkerEnvironmentSource({"FIRECRAWL_API_KEY": "fc-test-value-0123456789"})
    )
    return await ClaudeManagedPrepare(api.client(), broker, installation_id="local").sync(rendered)


async def test_the_read_back_of_a_synced_agent_proves_the_pack(rendered: RenderedPack) -> None:
    api = FakeManagedAgentsApi()
    prepared = await _synced(api, rendered)

    expectation = discovery_expectation(rendered)
    report = await read_back(api.client(), prepared)

    assert expectation.mechanism == report.mechanism == "api_readback"
    assert DiscoveryItem(kind="skill", name="mission-control-signals") in expectation.items
    assert expectation.digests == {AGENT_DIGEST: rendered.materialization_digest}
    assert discovery_gaps(expectation, report) == ()
    assert report.source == f"api:agents/{prepared.agent.agent_id}@{prepared.agent.version}"
    # A read-back: one retrieve, nothing written.
    assert api.requests[-1].method == "GET"


async def test_an_agent_that_drifted_after_the_sync_fails_the_proof(
    rendered: RenderedPack,
) -> None:
    api = FakeManagedAgentsApi()
    prepared = await _synced(api, rendered)
    agent = api.agents[prepared.agent.agent_id]
    agent["skills"] = [{**agent["skills"][0], "version": "skillver_other"}]
    agent["metadata"] = {**agent["metadata"], METADATA_DIGEST: "sha256:" + "0" * 64}

    report = await read_back(api.client(), prepared)

    gaps = discovery_gaps(discovery_expectation(rendered), report)
    assert "skill mission-control-signals was not reported loaded" in gaps
    assert any(gap.startswith(f"{AGENT_DIGEST} reads sha256:000") for gap in gaps)


async def test_an_agent_without_the_digest_metadata_reads_it_as_absent(
    rendered: RenderedPack,
) -> None:
    api = FakeManagedAgentsApi()
    prepared = await _synced(api, rendered)
    agent = api.agents[prepared.agent.agent_id]
    agent["metadata"] = {**agent["metadata"], METADATA_DIGEST: "not-a-digest"}

    report = await read_back(api.client(), prepared)

    assert report.digests == {AGENT_DIGEST: None}
    assert f"{AGENT_DIGEST} is absent where the provider reads it" in discovery_gaps(
        discovery_expectation(rendered), report
    )
