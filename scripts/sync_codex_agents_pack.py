"""Sync a `codex_agents` pack into the `OPENAI_API_KEY` project, reusing by digest (HL-11).

A paid-account operation: run it only inside an authorised budget (DECISIONS R27 gates the
`codex_agents` drills). Each run prints and records ids, digests and created/reused outcomes,
never a key or a credential value. Running it twice on an unchanged pack proves reuse by digest:
the second run reports every resource `reused`. `--delete-from` removes the agent, template and
vault a recorded run created; a prewarmed environment has no delete endpoint and expires
unattached after about five minutes.

    uv run --no-sync python scripts/sync_codex_agents_pack.py \\
        --label mc_run=run1-HL-11 --record <dir>/sync-1.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from mission_control.adapters.openai_agents.client import AgentsApiClient
from mission_control.adapters.openai_agents.pack import load_pack, pack_directory
from mission_control.adapters.openai_agents.prepare import CodexAgentsPreparer
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.bootstrap.settings import PROJECT_ROOT


def _label(value: str) -> tuple[str, str]:
    key, separator, label = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError(f"--label must be key=value, got {value!r}")
    return key, label


def _client() -> AgentsApiClient:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY is not set")
    return AgentsApiClient(SecretStr(key))


async def _sync(args: argparse.Namespace) -> dict[str, Any]:
    pack = load_pack(args.pack)
    client = _client()
    try:
        preparer = CodexAgentsPreparer(
            client, WorkerEnvironmentSource(), labels=dict(args.label or [])
        )
        prepared = await preparer.sync(pack)
        record: dict[str, Any] = {
            "pack_digest": prepared.pack_digest,
            "template_name": pack.template_name,
            "resources": [asdict(resource) for resource in prepared.resources],
            "credentials_written": list(prepared.credentials_written),
            "created": list(prepared.created),
        }
        if args.prewarm:
            prewarmed = await preparer.prewarm(prepared, launch_key=args.prewarm)
            record["prewarmed_environment"] = asdict(prewarmed)
        return record
    finally:
        await client.aclose()


async def _delete(record: dict[str, Any]) -> dict[str, Any]:
    created = {
        item["kind"]: item["id"] for item in record["resources"] if item["outcome"] == "created"
    }
    client = _client()
    try:
        if "agent" in created:
            await client.delete_agent(created["agent"])
        if "environment_template" in created:
            await client.delete_environment_template(created["environment_template"])
        if "vault" in created:
            await client.delete_vault(created["vault"])
    finally:
        await client.aclose()
    return {"deleted": created}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pack", type=Path, default=pack_directory(PROJECT_ROOT / "deployments", "ai-engineer")
    )
    parser.add_argument("--label", type=_label, action="append", help="metadata key=value")
    parser.add_argument("--prewarm", metavar="LAUNCH_KEY", help="also prewarm for this launch")
    parser.add_argument("--record", type=Path, help="write the outcome JSON here")
    parser.add_argument("--delete-from", type=Path, help="delete what a recorded run created")
    args = parser.parse_args()
    if args.delete_from:
        outcome = asyncio.run(_delete(json.loads(args.delete_from.read_text(encoding="utf-8"))))
    else:
        outcome = asyncio.run(_sync(args))
    text = json.dumps(outcome, indent=2, sort_keys=True)
    if args.record:
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
