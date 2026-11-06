"""The production client factory: `ClaudeSDKClient` over an explicit child environment (MP-07).

`claude_agent_sdk._internal.transport.subprocess_cli.SubprocessCLITransport.connect`
(0.2.165, lines 814-825) spawns the CLI with ``{**os.environ (minus CLAUDECODE),
CLAUDE_CODE_ENTRYPOINT, **options.env, CLAUDE_AGENT_SDK_VERSION}``: the worker's whole
environment, including every credential variable, always reaches the subprocess, and a
variable the auth admission asked to *unset* (`AuthAdmission.env_unset`, MP-05) cannot be
removed through `options.env`. `ExplicitEnvironmentCliTransport` keeps the SDK's command
line (`_build_command`), CLI resolution, stdio framing, stderr handling and shielded
`close()`, and replaces only the spawn environment: the allowlisted one the lane built through
`application.execution.child_environment.provider_child_environment` (MO-04), plus the SDK's
own markers and `options.env` (`spawn_environment`). Nothing of the worker's is inherited,
not even by the `claude -v` minimum-version probe, which the SDK spawns with `os.environ`.
It is a subclass of an SDK-internal class pinned to 0.2.165: the private names it uses are
imported by name or listed in `_RELIED_ON` and checked at import, so an SDK bump that renames
them fails loudly rather than silently spawning with the inherited environment.

What a custom transport changes in `ClaudeSDKClient` (`client.py::connect`, `_connect_inner`):

- `_connect_inner` applies `_configure_can_use_tool` to the client's own options, but that
  copy never reaches a pre-built transport. The factory builds the transport from a
  configured copy (`--permission-prompt-tool stdio` routes `can_use_tool` over the control
  protocol) and hands the client the options as given: configuring them twice raises
  (`can_use_tool` together with `permission_prompt_tool_name`).
- The transcript mirror (`session_resume.build_mirror_batcher`) resolves the projects dir from
  the client's `options.env["CLAUDE_CONFIG_DIR"]`, else from the worker's own config dir; a
  child config dir set only in the explicit environment would drop every mirror frame. The
  factory copies it into `options.env`.
- Store-backed resume is skipped (`materialize_resume_session` runs only without a custom
  transport, MO-73), so `--resume=<id>` finds no transcript on a worker whose config dir
  lacks the CLI's own copy. `restore_resume_session` writes the session from
  `options.session_store` into the CLI's config dir before the spawn, as the SDK does into a
  temporary one (`session_resume.py`), and copies no credential.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from subprocess import PIPE
from typing import Any, Final

import anyio
import anyio.to_thread
import claude_agent_sdk
from anyio.streams.text import TextReceiveStream, TextSendStream
from claude_agent_sdk import project_key_for_directory
from claude_agent_sdk._errors import CLIConnectionError, CLINotFoundError
from claude_agent_sdk._internal._task_compat import spawn_detached
from claude_agent_sdk._internal.session_resume import (
    _load_candidate,
    _materialize_subkeys,
    _write_jsonl,
)
from claude_agent_sdk._internal.session_store_validation import _store_implements
from claude_agent_sdk._internal.sessions import _validate_uuid
from claude_agent_sdk._internal.transport import subprocess_cli as _cli
from claude_agent_sdk.client import ClaudeSDKClient
from claude_agent_sdk.types import ClaudeAgentOptions, _configure_can_use_tool

from mission_control.adapters.claude.describe import BUNDLED_CLI_VERSION, SDK_VERSION
from mission_control.adapters.claude.host import HostGate, host_gate
from mission_control.adapters.claude.session import ClaudeClient

_LOGGER = logging.getLogger(__name__)
_SDK_VERSION: Final = str(claude_agent_sdk.__version__)
# SDK-internal names this module relies on (claude_agent_sdk 0.2.165).
_RELIED_ON: Final = (
    "SubprocessCLITransport",
    "_ACTIVE_CHILDREN",
    "_SDK_READS_SESSION_STATE_ENV",
    "MINIMUM_CLAUDE_CODE_VERSION",
)
for _name in _RELIED_ON:
    if not hasattr(_cli, _name):  # pragma: no cover - guards an SDK bump
        raise ImportError(f"claude_agent_sdk {_SDK_VERSION} no longer exposes {_name}")
if _SDK_VERSION != SDK_VERSION:  # pragma: no cover - guards an SDK bump
    raise ImportError(f"claude_agent_sdk {_SDK_VERSION} is installed; MP-07 pins {SDK_VERSION}")

Spawn = Callable[..., Awaitable[Any]]


async def _empty_stream() -> AsyncIterator[dict[str, Any]]:
    # Mirrors `ClaudeSDKClient.connect(None)`: never yields, keeps the connection open.
    return
    yield {}


def cli_config_dir(environment: Mapping[str, str]) -> Path:
    """The config dir the CLI reads and writes under `environment`: `CLAUDE_CONFIG_DIR`, else
    `.claude` under the child's `HOME` (`sessions.py::_get_claude_config_home_dir`)."""

    configured = environment.get("CLAUDE_CONFIG_DIR")
    if configured:
        return Path(configured)
    home = environment.get("HOME")
    return (Path(home) if home else Path.home()) / ".claude"


async def restore_resume_session(options: ClaudeAgentOptions, config_dir: Path) -> Path | None:
    """Write the session `options.resume` names from `options.session_store` into the CLI's
    config dir, where `--resume=<id>` reads it; the restored transcript path, or `None`.

    Mirrors `session_resume.materialize_resume_session` (0.2.165, lines 130-195): the main
    transcript at `projects/<project_key_for_directory(cwd)>/<id>.jsonl`, subagent transcripts
    and their metadata under `<id>/` when the store lists subkeys. Nothing is written without
    a store, a resume, a UUID session id or stored entries, nor over the CLI's own transcript:
    the CLI writes it before mirroring it, so it is never behind the store. The main
    transcript is written last, so its presence means a complete restore. A store failure or
    timeout raises `RuntimeError` (`session_resume._with_timeout`).
    """

    store, session_id = options.session_store, options.resume
    if store is None or session_id is None or _validate_uuid(session_id) is None:
        return None
    project_key = project_key_for_directory(options.cwd)
    project_dir = config_dir / "projects" / project_key
    transcript = project_dir / f"{session_id}.jsonl"
    if await anyio.to_thread.run_sync(transcript.is_file):
        return None
    timeout_s = options.load_timeout_ms / 1000
    loaded = await _load_candidate(store, project_key, session_id, timeout_s)
    if loaded is None:
        return None
    if _store_implements(store, "list_subkeys"):
        await _materialize_subkeys(
            store, config_dir, project_dir, project_key, session_id, timeout_s
        )
    await anyio.to_thread.run_sync(_write_jsonl, transcript, loaded[1])
    return transcript


class ExplicitEnvironmentCliTransport(_cli.SubprocessCLITransport):
    """The SDK subprocess transport spawned with an explicit environment, nothing inherited."""

    def __init__(
        self,
        options: ClaudeAgentOptions,
        *,
        environment: Mapping[str, str],
        prompt: AsyncIterable[dict[str, Any]] | None = None,
        spawn: Spawn = anyio.open_process,
        check_version: bool = True,
    ) -> None:
        super().__init__(prompt=prompt if prompt is not None else _empty_stream(), options=options)
        self._environment = dict(environment)
        self._spawn = spawn
        self._check_version = check_version

    def spawn_environment(self) -> dict[str, str]:
        """Exactly what the CLI receives: the explicit environment plus the SDK's markers."""

        process_env: dict[str, str] = {
            **self._environment,
            "CLAUDE_CODE_ENTRYPOINT": "sdk-py",
            **self._options.env,
            "CLAUDE_AGENT_SDK_VERSION": _SDK_VERSION,
        }
        process_env.pop("CLAUDECODE", None)
        reads_state = _cli._SDK_READS_SESSION_STATE_ENV
        if not any(key.upper() == reads_state for key in process_env):
            process_env[reads_state] = "1"
        if self._options.enable_file_checkpointing:
            process_env["CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING"] = "true"
        if self._cwd:
            process_env["PWD"] = self._cwd
        return process_env

    async def _check_claude_version(self) -> None:
        """The SDK's minimum-version warning, probed with the explicit environment (the SDK's
        own probe spawns `claude -v` with the worker's whole environment)."""

        if self._cli_path is None:
            raise CLINotFoundError("CLI path not resolved. Call connect() first.")
        process = None
        output = ""
        try:
            with anyio.fail_after(2):
                process = await self._spawn(
                    [self._cli_path, "-v"], stdout=PIPE, stderr=PIPE, env=self.spawn_environment()
                )
                if process.stdout:
                    output = (await process.stdout.receive()).decode().strip()
        except Exception:
            return
        finally:
            if process is not None:
                with suppress(Exception):
                    process.terminate()
                with suppress(Exception):
                    await process.wait()
        observed = re.match(r"(\d+)\.(\d+)\.(\d+)", output)
        minimum = _cli.MINIMUM_CLAUDE_CODE_VERSION
        if observed and tuple(map(int, observed.groups())) < tuple(map(int, minimum.split("."))):
            _LOGGER.warning(
                "Claude Code %s at %s is below the Agent SDK minimum %s",
                observed.group(0),
                self._cli_path,
                minimum,
            )

    async def connect(self) -> None:
        if self._process:
            return
        if self._cli_path is None:
            self._cli_path = await anyio.to_thread.run_sync(self._find_cli)
        self._reject_windows_batch_cli(self._cli_path)
        if self._check_version and not self._environment.get("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK"):
            await self._check_claude_version()
        cmd = self._build_command()
        process_env = self.spawn_environment()
        await self._restore_resume_session(cli_config_dir(process_env))
        stderr_dest = PIPE if self._options.stderr is not None else None
        try:
            self._process = await self._spawn(
                cmd,
                stdin=PIPE,
                stdout=PIPE,
                stderr=stderr_dest,
                cwd=self._cwd,
                env=process_env,
                user=self._options.user,
            )
        except FileNotFoundError as error:
            failure: CLIConnectionError = CLINotFoundError(
                f"Claude Code not found at: {self._cli_path}"
            )
            self._exit_error = failure
            raise failure from error
        except Exception as error:
            failure = CLIConnectionError(f"Failed to start Claude Code: {error}")
            self._exit_error = failure
            raise failure from error
        assert self._process is not None
        _cli._ACTIVE_CHILDREN.add(self._process)
        if self._process.stdout:
            self._stdout_stream = TextReceiveStream(self._process.stdout)
        if stderr_dest is PIPE and self._process.stderr:
            self._stderr_stream = TextReceiveStream(self._process.stderr)
            self._stderr_task = spawn_detached(self._handle_stderr())
        if self._process.stdin:
            self._stdin_stream = TextSendStream(self._process.stdin)
        self._ready = True

    async def _restore_resume_session(self, config_dir: Path) -> None:
        try:
            restored = await restore_resume_session(self._options, config_dir)
        except (RuntimeError, OSError) as error:
            failure = CLIConnectionError(
                f"Failed to restore session {self._options.resume} from the session store: {error}"
            )
            self._exit_error = failure
            raise failure from error
        if restored is not None:
            _LOGGER.info("restored session %s from the session store", self._options.resume)


class SdkClientFactory:
    """`ClaudeClientFactory` over the pinned SDK: one explicit-environment subprocess per
    session. `spawn` and `check_version` exist for tests of the environment only; a real
    session spawns the bundled (or `cli_path`) Claude Code. `gate` is the host gate consulted
    before every client is built (`host.HostUnsupported` on Windows); tests inject one."""

    def __init__(
        self,
        *,
        spawn: Spawn = anyio.open_process,
        check_version: bool = True,
        gate: Callable[[], HostGate] = host_gate,
    ) -> None:
        self._spawn = spawn
        self._check_version = check_version
        self._gate = gate

    @property
    def versions(self) -> Mapping[str, str]:
        return {"claude_agent_sdk": _SDK_VERSION, "claude_code_bundled": BUNDLED_CLI_VERSION}

    def create(
        self, options: ClaudeAgentOptions, *, environment: Mapping[str, str]
    ) -> ClaudeClient:
        # Enforced where the lane spawns: never build a client on an unsupported host.
        self._gate().require()
        config_dir = environment.get("CLAUDE_CONFIG_DIR")
        if config_dir and "CLAUDE_CONFIG_DIR" not in options.env:
            options = replace(options, env={**options.env, "CLAUDE_CONFIG_DIR": config_dir})
        transport = ExplicitEnvironmentCliTransport(
            _configure_can_use_tool(options),
            environment=environment,
            spawn=self._spawn,
            check_version=self._check_version,
        )
        return ClaudeSDKClient(options, transport=transport)


__all__ = [
    "ExplicitEnvironmentCliTransport",
    "SdkClientFactory",
    "cli_config_dir",
    "restore_resume_session",
]
