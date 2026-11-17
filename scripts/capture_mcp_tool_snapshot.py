from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport

from mission_control.bootstrap.settings import Settings


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture a canonical tools/list snapshot from an inspected MCP server: a stdio "
            "server started with --command, or a running Streamable HTTP server at --url."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--command")
    source.add_argument("--url", help="A Streamable HTTP MCP endpoint, for example .../mcp.")
    parser.add_argument("--arg", action="append", default=[])
    parser.add_argument("--cwd", help="Working directory of a stdio server (required with it).")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--credential-setting",
        choices=("firecrawl_api_key", "tavily_api_key"),
        help="Inject one typed Settings credential into the child without printing it.",
    )
    parser.add_argument(
        "--bearer-env",
        help=(
            "With --url: the NAME of an environment variable holding the token sent as "
            "`Authorization: Bearer`. The value is read here and never printed or written."
        ),
    )
    args = parser.parse_args()
    if args.command is not None:
        if args.cwd is None:
            parser.error("--cwd is required with --command")
        args.cwd = Path(args.cwd).resolve(strict=True)
    elif args.arg or args.credential_setting:
        parser.error("--arg and --credential-setting apply to a stdio server (--command)")
    args.output = Path(args.output).resolve()
    return args


def _stdio_transport(args: argparse.Namespace) -> StdioTransport:
    environment = {
        key: os.environ[key]
        for key in ("PATH", "PATHEXT", "SYSTEMROOT", "COMSPEC")
        if key in os.environ
    }
    environment.update({"NO_COLOR": "1", "CI": "1"})
    if args.credential_setting:
        credential = getattr(Settings(), args.credential_setting)
        if credential is None:
            raise RuntimeError(f"{args.credential_setting} is unavailable")
        environment[
            "FIRECRAWL_API_KEY"
            if args.credential_setting == "firecrawl_api_key"
            else "TAVILY_API_KEY"
        ] = credential.get_secret_value()
    return StdioTransport(
        command=args.command,
        args=list(args.arg),
        env=environment,
        cwd=str(args.cwd),
    )


def _http_transport(args: argparse.Namespace) -> StreamableHttpTransport:
    headers: dict[str, str] = {}
    if args.bearer_env:
        token = os.environ.get(args.bearer_env, "").strip()
        if not token:
            raise RuntimeError(f"{args.bearer_env} is unset or empty")
        headers["Authorization"] = f"Bearer {token}"
    return StreamableHttpTransport(url=args.url, headers=headers)


async def _capture(args: argparse.Namespace) -> dict[str, Any]:
    output: Path = args.output
    transport = _stdio_transport(args) if args.command is not None else _http_transport(args)
    async with Client(transport, timeout=30) as client:
        tools = await client.list_tools()
        server = client.initialize_result.serverInfo if client.initialize_result else None
    snapshot = {
        "snapshot_format": "mcp-tools-list/1",
        "tools": [
            tool.model_dump(mode="json", exclude_none=True)
            for tool in sorted(tools, key=lambda item: item.name)
        ],
    }
    await asyncio.to_thread(_write_snapshot, output, snapshot)
    return {
        "output": str(output),
        "server": None if server is None else {"name": server.name, "version": server.version},
        "tool_count": len(tools),
        "tool_names": [tool.name for tool in sorted(tools, key=lambda item: item.name)],
    }


def _write_snapshot(output: Path, snapshot: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="",
    )


def main() -> None:
    print(json.dumps(asyncio.run(_capture(_arguments())), sort_keys=True))


if __name__ == "__main__":
    main()
