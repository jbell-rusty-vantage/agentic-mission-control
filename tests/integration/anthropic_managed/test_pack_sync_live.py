"""HL-07 opt-in live sync of the AI Engineer `claude_managed` pack (skipped by default).

Runs only with `MC_CLAUDE_MANAGED_LIVE=1`, an `ANTHROPIC_API_KEY` and a finite
`MC_PAID_BUDGET_USD` the owner authorized. It syncs the checked-in pack twice through the real
Managed Agents API: the first sync must create the skill, environment, vault and agent, the
second must create nothing and reuse every id. Prepare starts no session, so no model tokens
or session runtime are billed.

Every resource is labelled `mc_run=$MC_RUN_LABEL` (the skill, which takes no metadata, carries
it in its name), so the drill never touches another installation's resources. The vault holds a
fixed non-secret placeholder instead of the worker's real credential, and the Signal Ingress
host is `MC_CLAUDE_MANAGED_INGRESS_HOST` (default `example.com`, the host HL-23 used, while the
ingress is not deployed). Created resources are archived or deleted at the end unless
`MC_CLAUDE_MANAGED_KEEP=1`. With `MC_CLAUDE_MANAGED_EVIDENCE=<path>` both receipts and the
cleanup outcomes (ids, actions and digests only) are written there as JSON.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Final

import pytest
from pydantic import SecretStr

from mission_control.adapters.anthropic_managed.client import ManagedAgentsClient
from mission_control.adapters.anthropic_managed.pack import load_pack, render_pack
from mission_control.adapters.anthropic_managed.prepare import ClaudeManagedPrepare, PreparedPack
from mission_control.application.secrets.broker import SecretBroker

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
PACK: Final = REPO_ROOT / "deployments/hosted-packs/ai-engineer/claude_managed"
PLACEHOLDER: Final = "mc-drill-placeholder-not-a-secret"

LIVE = (
    os.environ.get("MC_CLAUDE_MANAGED_LIVE") == "1"
    and bool(os.environ.get("ANTHROPIC_API_KEY"))
    and float(os.environ.get("MC_PAID_BUDGET_USD", "0") or 0) > 0
)

pytestmark = pytest.mark.skipif(
    not LIVE,
    reason="paid live drill: set MC_CLAUDE_MANAGED_LIVE=1, ANTHROPIC_API_KEY, MC_PAID_BUDGET_USD",
)


class PlaceholderEnvironment:
    """The broker's worker environment for the drill: every declared credential gets the
    same non-secret placeholder value."""

    async def read(self, key: str) -> str | None:
        return PLACEHOLDER


async def test_a_live_sync_creates_once_and_reuses_on_the_second_run() -> None:
    evidence = os.environ.get("MC_CLAUDE_MANAGED_EVIDENCE")
    if evidence and not Path(evidence).parent.is_dir():
        pytest.fail("MC_CLAUDE_MANAGED_EVIDENCE names a missing directory; nothing was created")
    client = ManagedAgentsClient(SecretStr(os.environ["ANTHROPIC_API_KEY"]))
    label = os.environ.get("MC_RUN_LABEL", "run1-HL-07")
    rendered = render_pack(
        load_pack(PACK),
        installation_id=os.environ.get("MC_INSTALLATION_ID", "local"),
        repo_root=REPO_ROOT,
        ingress_host=os.environ.get("MC_CLAUDE_MANAGED_INGRESS_HOST", "example.com"),
    )
    prepare = ClaudeManagedPrepare(
        client,
        SecretBroker(environment=PlaceholderEnvironment()),
        installation_id=os.environ.get("MC_INSTALLATION_ID", "local"),
        labels={"mc_run": label},
    )
    receipts: list[PreparedPack] = []
    cleanup: dict[str, str] = {}
    try:
        receipts.append(await prepare.sync(rendered))
        receipts.append(await prepare.sync(rendered))
        first, second = receipts

        assert len(first.created()) == 4
        assert second.created() == ()
        assert second.session_fields() == first.session_fields()
        assert second.agent.readback_digest == first.agent.readback_digest
    finally:
        if receipts and os.environ.get("MC_CLAUDE_MANAGED_KEEP") != "1":
            cleanup = await _cleanup(client, receipts[0])
        await client.aclose()
        _record(receipts, cleanup)


async def _cleanup(client: ManagedAgentsClient, prepared: PreparedPack) -> dict[str, str]:
    """Archive the agent, then delete what it referenced; each outcome is recorded."""

    steps: list[tuple[str, Callable[[], Awaitable[Any]]]] = [
        (prepared.agent.agent_id, lambda: client.archive_agent(prepared.agent.agent_id)),
        (
            prepared.environment.environment_id,
            lambda: client.delete_environment(prepared.environment.environment_id),
        ),
    ]
    if prepared.vault is not None:
        vault_id = prepared.vault.vault_id
        steps.extend(
            (
                credential.credential_id,
                _bind(client.delete_credential, vault_id, credential.credential_id),
            )
            for credential in prepared.vault.credentials
        )
        steps.append((vault_id, lambda: client.delete_vault(vault_id)))
    steps.extend(
        (skill.skill_id, _bind(client.delete_skill, skill.skill_id)) for skill in prepared.skills
    )
    outcomes: dict[str, str] = {}
    for resource_id, step in steps:
        try:
            await step()
            outcomes[resource_id] = "archived" if resource_id.startswith("agent_") else "deleted"
        except Exception as error:  # every outcome is recorded, none is fatal
            outcomes[resource_id] = f"failed: {type(error).__name__}"
    return outcomes


def _bind(call: Callable[..., Awaitable[Any]], *args: str) -> Callable[[], Awaitable[Any]]:
    return lambda: call(*args)


def _record(receipts: list[PreparedPack], cleanup: dict[str, str]) -> None:
    target = os.environ.get("MC_CLAUDE_MANAGED_EVIDENCE")
    if not target:
        return
    Path(target).write_text(
        json.dumps(
            {
                "receipts": [receipt.model_dump(mode="json") for receipt in receipts],
                "cleanup": cleanup,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
