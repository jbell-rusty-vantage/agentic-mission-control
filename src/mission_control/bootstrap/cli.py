"""The ``mission-control`` console script: one subcommand per process role.

* ``mission-control api [--host H] [--port P] [--reload]`` serves the configured scoped API:
  the uvicorn factory ``mission_control.bootstrap.api:create_app`` on the
  ``mission_control.bootstrap.api:api_loop_factory`` loop (a selector loop on Windows, which the
  time-travel saver needs; uvicorn's own choice elsewhere).
* ``mission-control worker`` runs the installation-bound Temporal worker
  (``mission_control.bootstrap.worker.run_cli``).
* ``mission-control preflight [...]`` runs the read-only installation check
  (``mission_control.bootstrap.preflight.main``); every argument after ``preflight`` is its own.

Each role reads the same process configuration as before (``MISSION_CONTROL_DEPLOYMENT_FILE``,
the worker's application id and binding digest, the settings in docs/ENVIRONMENT.md). Parsing
imports no role: a role's module, with its settings, adapters and provider SDKs, loads only
when that role starts. ``python -m mission_control.bootstrap.cli`` is the same entrypoint.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

PROGRAM = "mission-control"
API_FACTORY = "mission_control.bootstrap.api:create_app"
API_LOOP_FACTORY = "mission_control.bootstrap.api:api_loop_factory"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
RELOAD_DIRECTORY = "src"


@dataclass(frozen=True)
class ApiCommand:
    """Serve the configured API."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    reload: bool = False


@dataclass(frozen=True)
class WorkerCommand:
    """Run the installation-bound Temporal worker."""


@dataclass(frozen=True)
class PreflightCommand:
    """Run the read-only installation check with its own arguments."""

    arguments: tuple[str, ...] = ()


Command = ApiCommand | WorkerCommand | PreflightCommand


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("a TCP port number") from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("a TCP port between 1 and 65535")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Run one Mission Control process role from the configured installation.",
    )
    roles = parser.add_subparsers(dest="role", required=True, metavar="{api,worker,preflight}")
    api = roles.add_parser("api", help="serve the configured scoped API (REST, operator MCP)")
    api.add_argument("--host", default=DEFAULT_HOST, help=f"bind address (default {DEFAULT_HOST})")
    api.add_argument(
        "--port", type=_port, default=DEFAULT_PORT, help=f"bind port (default {DEFAULT_PORT})"
    )
    api.add_argument(
        "--reload", action="store_true", help="development only: restart on a source change"
    )
    roles.add_parser("worker", help="run the installation-bound Temporal worker")
    # No options of its own (not even -h): everything after `preflight` is the check's.
    roles.add_parser(
        "preflight",
        add_help=False,
        help="read-only installation check; its arguments follow (`preflight -h` lists them)",
    )
    return parser


def parse_command(argv: Sequence[str] | None = None) -> Command:
    """The role and its arguments; an unknown role or argument exits with the usage (status 2)."""

    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    if args.role == "preflight":
        return PreflightCommand(arguments=tuple(extra))
    if extra:
        parser.error(f"unrecognized arguments: {' '.join(extra)}")
    if args.role == "api":
        return ApiCommand(host=args.host, port=args.port, reload=args.reload)
    return WorkerCommand()


def run_api(command: ApiCommand) -> None:
    import uvicorn

    uvicorn.run(
        API_FACTORY,
        factory=True,
        loop=API_LOOP_FACTORY,
        host=command.host,
        port=command.port,
        reload=command.reload,
        reload_dirs=[RELOAD_DIRECTORY] if command.reload else None,
    )


def run_worker() -> None:
    from mission_control.bootstrap.worker import run_cli

    run_cli()


def run_preflight(command: PreflightCommand) -> int:
    from mission_control.bootstrap import preflight

    return asyncio.run(preflight.main(list(command.arguments)))


def main(argv: Sequence[str] | None = None) -> int:
    command = parse_command(argv)
    if isinstance(command, ApiCommand):
        run_api(command)
        return 0
    if isinstance(command, WorkerCommand):
        run_worker()
        return 0
    return run_preflight(command)


if __name__ == "__main__":
    raise SystemExit(main())
