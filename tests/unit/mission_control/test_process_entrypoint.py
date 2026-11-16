"""The ``mission-control`` console script: one subcommand per process role.

``api`` serves the uvicorn factory on the API loop factory, ``worker`` runs the worker entry and
``preflight`` hands every later argument to the read-only check. Parsing imports no role, and an
unknown role or argument exits with the usage (status 2) before anything starts.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from mission_control.bootstrap import cli

ROOT = Path(__file__).resolve().parents[3]


def test_api_defaults_to_loopback_port_8000_without_reload() -> None:
    assert cli.parse_command(["api"]) == cli.ApiCommand(host="127.0.0.1", port=8000, reload=False)


def test_api_takes_host_port_and_reload() -> None:
    command = cli.parse_command(["api", "--host", "0.0.0.0", "--port", "8020", "--reload"])
    assert command == cli.ApiCommand(host="0.0.0.0", port=8020, reload=True)


@pytest.mark.parametrize("port", ["0", "65536", "-1", "eighty"])
def test_api_refuses_a_port_that_is_not_a_tcp_port(port: str) -> None:
    with pytest.raises(SystemExit) as refused:
        cli.parse_command(["api", "--port", port])
    assert refused.value.code == 2


def test_worker_takes_no_arguments() -> None:
    assert cli.parse_command(["worker"]) == cli.WorkerCommand()
    with pytest.raises(SystemExit) as refused:
        cli.parse_command(["worker", "--application", "any"])
    assert refused.value.code == 2


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["readiness"],
        ["-h"],
        ["--profile", "run-profile.json", "--db-dsn-env", "SOME_DSN", "readiness"],
        ["host", "--lane", "codex", "--auth-profile", "codex=profile-1"],
    ],
)
def test_preflight_hands_every_later_argument_to_the_check(arguments: list[str]) -> None:
    assert cli.parse_command(["preflight", *arguments]) == cli.PreflightCommand(
        arguments=tuple(arguments)
    )


@pytest.mark.parametrize("argv", [[], ["serve"], ["api", "extra"], ["--port", "8000"]])
def test_an_unknown_role_or_argument_exits_with_the_usage(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as refused:
        cli.parse_command(argv)
    assert refused.value.code == 2


def test_parsing_and_help_import_no_role_module() -> None:
    probe = (
        "import sys\n"
        "from mission_control.bootstrap import cli\n"
        "cli.parse_command(['api', '--port', '8020'])\n"
        "cli.parse_command(['worker'])\n"
        "cli.parse_command(['preflight', 'readiness'])\n"
        "heavy = [name for name in ('uvicorn', 'mission_control.bootstrap.api',\n"
        "    'mission_control.bootstrap.worker', 'mission_control.bootstrap.preflight',\n"
        "    'mission_control.bootstrap.settings') if name in sys.modules]\n"
        "print(heavy)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip() == "[]"


def test_api_runs_the_factory_on_the_api_loop_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    assert cli.main(["api", "--host", "0.0.0.0", "--port", "8020"]) == 0
    ((args, options),) = calls
    assert args == ("mission_control.bootstrap.api:create_app",)
    assert options == {
        "factory": True,
        "loop": "mission_control.bootstrap.api:api_loop_factory",
        "host": "0.0.0.0",
        "port": 8020,
        "reload": False,
        "reload_dirs": None,
    }
    calls.clear()
    assert cli.main(["api", "--reload"]) == 0
    assert calls[0][1]["reload"] is True and calls[0][1]["reload_dirs"] == ["src"]


def test_the_named_factory_and_loop_factory_exist() -> None:
    for reference in (cli.API_FACTORY, cli.API_LOOP_FACTORY):
        module, _, attribute = reference.partition(":")
        assert callable(getattr(import_module(module), attribute))


def test_main_dispatches_each_role(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []
    monkeypatch.setattr(cli, "run_api", seen.append)
    monkeypatch.setattr(cli, "run_worker", lambda: seen.append("worker"))
    monkeypatch.setattr(cli, "run_preflight", lambda command: seen.append(command) or 2)
    assert cli.main(["api", "--port", "8100"]) == 0
    assert cli.main(["worker"]) == 0
    # The check's own status is the process status (2 = a blocked gate).
    assert cli.main(["preflight", "readiness"]) == 2
    assert seen == [
        cli.ApiCommand(port=8100),
        "worker",
        cli.PreflightCommand(arguments=("readiness",)),
    ]


def test_worker_and_preflight_run_the_existing_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    from mission_control.bootstrap import preflight, worker

    ran: list[object] = []
    monkeypatch.setattr(worker, "run_cli", lambda: ran.append("worker"))

    async def check(argv: list[str]) -> int:
        ran.append(argv)
        return 0

    monkeypatch.setattr(preflight, "main", check)
    cli.run_worker()
    assert cli.run_preflight(cli.PreflightCommand(arguments=("readiness",))) == 0
    assert ran == ["worker", ["readiness"]]


def test_the_distribution_declares_the_console_script_and_make_calls_it() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["scripts"]["mission-control"] == "mission_control.bootstrap.cli:main"
    module, _, attribute = project["scripts"]["mission-control"].partition(":")
    assert getattr(import_module(module), attribute) is cli.main
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "MISSION_CONTROL ?= $(RUN) python -m mission_control.bootstrap.cli" in makefile
    for role in ("api $(API_FLAGS)", "worker", "preflight $(ARGS)"):
        assert f"\t$(MISSION_CONTROL) {role}\n" in makefile
