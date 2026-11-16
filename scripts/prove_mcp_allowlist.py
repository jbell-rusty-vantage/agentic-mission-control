"""Prove, against a running server, that the Deep Agents lane attaches only a catalog allowlist.

Read-only and free of model calls: it lists the tools of the Knowledge Services executor at
`--endpoint`, builds the exact MCP component a worker would be bound to for the catalog row
`mcp.knowledge-capture` (its allowlist, the `allowlist` tool filter, each tool's input-schema
digest as the lane computes it) and runs the materializer's own MCP loading path
(`ExactDeepAgentMaterializer._load_mcp_tools`) over it. It then shows the two refusals that
keep the rule honest: the same server bound `exact` is drift, and a bound tool the server does
not list is drift. No tool is called.

    uv run --no-sync python scripts/prove_mcp_allowlist.py --endpoint http://127.0.0.1:4310/mcp

`--credential-env NAME` sends that variable's value as `Authorization: Bearer`; the value is
never printed. Exit status 0 only when every check holds.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, cast

from langchain_mcp_adapters.client import MultiServerMCPClient

from mission_control.adapters.deep_agents import ExactComponentRegistry, ExactDeepAgentMaterializer
from mission_control.adapters.deep_agents.materializer import tool_schema_digest
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef, SecretRef
from mission_control.domain.execution.contracts import (
    DeepAgentMCPServerComponent,
    DeepAgentMCPToolComponent,
)
from mission_control.domain.execution.errors import DeepAgentRuntimeDrift

ROOT = Path(__file__).resolve().parents[1]
SERVER_ID = "mcp.knowledge-capture"
WITHHELD = ("ingest_apply", "db_sql_readonly")


def catalog_row() -> Any:
    spec = importlib.util.spec_from_file_location(
        "mc_proof_agent_capabilities",
        ROOT / "packages" / "mission-control-db-contract" / "seeds" / "agent_capabilities.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.server_definition(module.served_research_specs()[SERVER_ID])


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--credential-env")
    args = parser.parse_args()
    row = catalog_row()
    allowlist = sorted(row.tool_allowlist)
    secrets: dict[str, str] = {}
    refs: tuple[SecretRef, ...] = ()
    headers: dict[str, str] | None = None
    if args.credential_env:
        value = os.environ.get(args.credential_env, "")
        if not value:
            raise SystemExit(f"{args.credential_env} has no value in this environment")
        secrets[f"environment:{args.credential_env}"] = value
        refs = (SecretRef(provider="environment", key=args.credential_env),)
        headers = {"Authorization": "Bearer " + value}
    client = MultiServerMCPClient(
        cast(
            Any,
            {"probe": {"transport": row.transport, "url": args.endpoint, "headers": headers}},
        )
    )
    listed = {tool.name: tool for tool in await client.get_tools()}

    def component(names: list[str], tool_filter: str, digests: dict[str, str]) -> Any:
        return DeepAgentMCPServerComponent(
            ref=ExactDefinitionRef(
                kind=DefinitionKind.MCP_SERVER,
                logical_id=SERVER_ID,
                revision=1,
                digest=sha256_digest({"proof": names, "tool_filter": tool_filter}),
            ),
            server_name="knowledge_capture",
            transport=row.transport,
            endpoint=args.endpoint,
            credential_refs=refs,
            tools=tuple(
                DeepAgentMCPToolComponent(tool_name=name, schema_digest=digests[name])
                for name in names
            ),
            schema_digest=sha256_digest(sorted(digests.items())),
            attachment_target="agent.main",
            tool_filter=tool_filter,
        )

    digests = {name: tool_schema_digest(listed[name]) for name in allowlist if name in listed}
    materializer = ExactDeepAgentMaterializer(ExactComponentRegistry(model_factories={}))
    attached = await materializer._load_mcp_tools(
        (component(allowlist, "allowlist", digests),), secrets
    )
    names = sorted(tool.name for tool in attached)

    async def refused(bound: Any) -> str | None:
        try:
            await materializer._load_mcp_tools((bound,), secrets)
        except DeepAgentRuntimeDrift as error:
            return str(error)[:160]
        return None

    exact_refusal = await refused(component(allowlist, "exact", digests))
    missing_refusal = await refused(
        component(
            [*allowlist, "tool_the_server_does_not_list"],
            "allowlist",
            {**digests, "tool_the_server_does_not_list": sha256_digest("absent")},
        )
    )
    changed = allowlist[0]
    schema_refusal = await refused(
        component(allowlist, "allowlist", {**digests, changed: sha256_digest("another schema")})
    )
    checks = {
        "attached_equals_catalog_allowlist": names == allowlist,
        "withheld_tools_listed_by_server": all(name in listed for name in WITHHELD),
        "withheld_tools_not_attached": not set(WITHHELD) & set(names),
        "exact_binding_reports_drift": bool(exact_refusal),
        "missing_bound_tool_refused": bool(missing_refusal),
        "changed_schema_refused": bool(schema_refusal),
    }
    print(
        json.dumps(
            {
                "endpoint": args.endpoint,
                "catalog_row": f"{SERVER_ID} ({row.source_provenance.upstream_version})",
                "server_listed_count": len(listed),
                "attached_count": len(names),
                "attached": names,
                "not_attached_count": len(set(listed) - set(names)),
                "exact_binding_refusal": exact_refusal,
                "missing_bound_tool_refusal": missing_refusal,
                "changed_schema_refusal": schema_refusal,
                "checks": checks,
                "tool_calls_made": 0,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
