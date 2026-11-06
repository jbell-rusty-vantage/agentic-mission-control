"""Codex home/auth compatibility and read-only selected-home login readiness (MO-65)."""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from mission_control.application.agentic_components.placement import LaneProjectionError

CODEX_OWNER_HOME_REQUIRED = "CODEX_OWNER_HOME_REQUIRED"
CODEX_OWNER_LOGIN_UNAVAILABLE = "CODEX_OWNER_LOGIN_UNAVAILABLE"


def require_auth_home(route: str, mode: str, owner_home: Path | None) -> None:
    """Topology guard only; a selected-home status probe supplies actual login evidence."""
    if route == "owner_cli_login" and (mode != "owner" or owner_home is None):
        raise LaneProjectionError(
            CODEX_OWNER_HOME_REQUIRED,
            "Codex ChatGPT login requires owner CODEX_HOME mode and an explicit owner home; "
            "isolated homes never copy owner credentials. Select an admitted API-key route "
            "for an isolated home.",
        )


@dataclass(frozen=True)
class CodexLoginReadiness:
    ready: bool
    code: str | None
    home: str
    route: str = "owner_cli_login"


async def owner_login_preflight(
    binary: str, owner_home: Path, *, environ: Mapping[str, str] | None = None
) -> CodexLoginReadiness:
    """No login, credential reads/copies or raw status output; API keys scrubbed first."""
    source = os.environ if environ is None else environ
    keep = {
        "PATH",
        "HOME",
        "USERPROFILE",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "APPDATA",
        "LOCALAPPDATA",
        "PATHEXT",
    }
    env = {key: value for key, value in source.items() if key.upper() in keep}
    env["CODEX_HOME"] = str(owner_home)
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [binary, "login", "status"],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        ready = False
        if isinstance(result.stdout, str) and isinstance(result.stderr, str):
            text = (result.stdout + result.stderr).lower()
            ready = result.returncode == 0 and "chatgpt" in text and "api key" not in text
    except (OSError, subprocess.SubprocessError):
        ready = False
    return CodexLoginReadiness(
        ready, None if ready else CODEX_OWNER_LOGIN_UNAVAILABLE, str(owner_home)
    )
