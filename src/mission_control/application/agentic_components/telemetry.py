"""The Telemetry Hook Pack and its native projection per lane (SPEC-04 sections 4.1 and 4.2).

The projection of every lane in ``TELEMETRY_EVENTS`` carries the pack, unless the caller turns
it off (``HostProjectors.render(..., telemetry=False)``):

- ``.mission/hooks/signal``: the stdlib spool-and-upload script (``signal_hook.py``);
- ``.mission/bin/mc-signal``: the POSIX ``sh`` command agents run, which hands off to it;
- ``.mission/signal-policy.json``: what the script forwards on this lane (Hook Event to signal
  type), which hooks flush the spool, the no-op answer each native hook expects, and which
  files ``materialization.observed`` digests (the instruction overlay and the hook config as
  the provider reads them from disk, plus the skill directory listing; SPEC-02 section 6);
- the ``mc-signals`` skill (``skills/mc-signals``), which teaches the agent when to emit.

``TELEMETRY_EVENTS`` is SPEC-04's native projection table. ``cursor_cloud`` has no session
hook, so the script opens the session from whichever hook fires first; ``cursor_local`` and
``codex`` keep their Kernel Hook loopback and add ``stop``/``subagent_stop`` for catalog
watchers; ``claude_cloud`` forwards its session, post-tool (matcher-filtered to shell and file
edits), compaction and stop events; ``codex_cloud`` runs no hooks, so it gets the command,
the skill and one advisory line in its overlay. ``claude_agent_sdk`` gets no pack: its SDK
hooks feed frames in process and no ingress is needed locally. Neither do Deep Agents (frames
in process) nor the hosted APIs (the ``mc_signal`` custom tool, SPEC-06).

Every pack hook is fail-open and comes after the Kernel and catalog hooks of its native event.
On Cursor a permission hook must print valid JSON, so the pack answers ``allow``, which never
outweighs another hook's ``deny`` or ``ask`` (Cursor merges deny over ask over allow).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from mission_control.domain.capabilities.gates import SignalGatePolicy
from mission_control.domain.capabilities.hooks import HookEvent, NativeHook, native_hook
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.capabilities.layouts import LANE_LAYOUTS

TELEMETRY_HOOK_ID: Final = "mc.telemetry"
SIGNAL_SCRIPT: Final = ".mission/hooks/signal"
SIGNAL_CLI: Final = ".mission/bin/mc-signal"
SIGNAL_POLICY: Final = ".mission/signal-policy.json"
SIGNAL_SKILL: Final = "mc-signals"
SIGNAL_POLICY_SCHEMA: Final = "mc.signal_policy.v1"
# Above the script's lock wait plus its upload budget plus one 2 s request (12 s at most).
SIGNAL_HOOK_TIMEOUT_SECONDS: Final = 15
SIGNAL_SCRIPT_SOURCE: Final = Path(__file__).with_name("signal_hook.py")
SIGNAL_SKILL_SOURCE: Final = Path(__file__).with_name("mc_signals_skill.md")
# One line in the instruction overlay where no hook reports for the agent (codex_cloud).
ADVISORY_INSTRUCTION: Final = (
    "Report milestones, blockers, needed input and ready artifacts with `.mission/bin/mc-signal` "
    "(skill mc-signals); never write status files."
)

E = HookEvent
SIGNAL_TYPES: Final[Mapping[HookEvent, str]] = MappingProxyType(
    {
        E.SESSION_START: "session.started",
        E.SESSION_END: "session.ended",
        E.BEFORE_TOOL: "tool.started",
        E.AFTER_TOOL: "tool.completed",
        E.AFTER_SHELL: "shell.completed",
        E.AFTER_FILE_EDIT: "file.edited",
        E.AFTER_MODEL: "agent.responded",
        E.BEFORE_COMPACTION: "compaction.started",
        E.SUBAGENT_START: "subagent.started",
        E.SUBAGENT_STOP: "subagent.stopped",
        E.STOP: "stop",
    }
)
# The hooks that upload the whole spool: the end of a turn and the end of the session.
FLUSH_EVENTS: Final = (E.STOP, E.SESSION_END)
# Cursor permission hooks block on output that is not JSON.
_CURSOR_PERMISSION_EVENTS: Final = frozenset(
    {E.BEFORE_TOOL, E.BEFORE_SHELL, E.BEFORE_MCP, E.SUBAGENT_START}
)
_CURSOR_LANES: Final = frozenset({LaneProfile.CURSOR_LOCAL, LaneProfile.CURSOR_CLOUD})

TELEMETRY_EVENTS: Final[Mapping[LaneProfile, tuple[HookEvent, ...]]] = MappingProxyType(
    {
        LaneProfile.CURSOR_CLOUD: (
            E.BEFORE_TOOL,
            E.AFTER_TOOL,
            E.SUBAGENT_START,
            E.SUBAGENT_STOP,
            E.AFTER_MODEL,
            E.BEFORE_COMPACTION,
            E.STOP,
        ),
        LaneProfile.CURSOR_LOCAL: (E.SUBAGENT_STOP, E.STOP),
        LaneProfile.CODEX: (E.SUBAGENT_STOP, E.STOP),
        LaneProfile.CLAUDE_CLOUD: (
            E.SESSION_START,
            E.AFTER_SHELL,
            E.AFTER_FILE_EDIT,
            E.BEFORE_COMPACTION,
            E.SUBAGENT_STOP,
            E.STOP,
            E.SESSION_END,
        ),
        LaneProfile.CODEX_CLOUD: (),
    }
)

if any(  # pragma: no cover - import-time guard
    event not in SIGNAL_TYPES or native_hook(lane, event) is None
    for lane, events in TELEMETRY_EVENTS.items()
    for event in events
):
    raise RuntimeError("every telemetry event needs a signal type and a native hook on its lane")


@dataclass(frozen=True)
class TelemetryHook:
    """One pack entry: the Hook Event it observes and where it lands natively."""

    event: HookEvent
    native: NativeHook
    gate: bool = False
    fail_closed: bool = False
    lane_profile: str = ""

    @property
    def command(self) -> list[str]:
        if self.gate:
            return ["python", SIGNAL_SCRIPT, "gate", self.lane_profile, self.event.value]
        return ["python", SIGNAL_SCRIPT, "hook", self.event.value]


def telemetry_hooks(
    lane: LaneProfile, gates: SignalGatePolicy | None = None
) -> tuple[TelemetryHook, ...]:
    """The pack's native hook entries on ``lane`` (none where the pack has no hooks)."""

    hooks = []
    for event in TELEMETRY_EVENTS.get(lane, ()):
        if gates is not None and event in gates.events:
            continue
        native = native_hook(lane, event)
        assert native is not None
        hooks.append(TelemetryHook(event=event, native=native))
    if gates is not None:
        if lane not in TELEMETRY_EVENTS:
            raise ValueError(f"{lane.value} has no telemetry gate pack")
        for event in gates.events:
            native = native_hook(lane, event)
            if native is None or native.fail_closed is None:
                raise ValueError(f"{lane.value} cannot enforce gate {event.value}")
            hooks.append(
                TelemetryHook(
                    event, native, gate=True, fail_closed=gates.fail_closed, lane_profile=lane.value
                )
            )
    return tuple(hooks)


def carries_pack(lane: LaneProfile) -> bool:
    return lane in TELEMETRY_EVENTS


def signal_policy(lane: LaneProfile, gates: SignalGatePolicy | None = None) -> dict[str, object]:
    """``.mission/signal-policy.json`` for ``lane``."""

    events = tuple(dict.fromkeys((*TELEMETRY_EVENTS[lane], *(gates.events if gates else ()))))
    layout = LANE_LAYOUTS[lane]
    layering = layout.layering
    assert layering is not None
    files = [] if layering.overlay_inline else [layering.overlay]
    if layout.hooks_file is not None and events:
        files.append(layout.hooks_file)
    stdout: dict[str, dict[str, str]] = {}
    if lane in _CURSOR_LANES:
        stdout = {
            event.value: {"permission": "allow"} if event in _CURSOR_PERMISSION_EVENTS else {}
            for event in events
        }
    policy: dict[str, object] = {
        "schema_version": SIGNAL_POLICY_SCHEMA,
        "lane_profile": lane.value,
        "signals": {event.value: SIGNAL_TYPES[event] for event in events},
        "flush": [event.value for event in FLUSH_EVENTS if event in events],
        "stdout": stdout,
        "materialization": {"files": sorted(files), "skills": layering.skills},
        "batch": {"max_signals": 20, "max_delay_seconds": 30},
    }
    if gates is not None:
        policy["gates"] = {
            event.value: {"fail_closed": gates.fail_closed} for event in gates.events
        }
    return policy


def signal_cli() -> str:
    """``.mission/bin/mc-signal``: the agents' command, a POSIX ``sh`` hand-off."""

    return (
        "#!/bin/sh\n"
        "# mc-signal: report to Mission Control (SPEC-04 section 4.1; skill mc-signals).\n"
        "#   mc-signal <type> [message] [--data '<json object>']\n"
        'here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        "for python in python3 python; do\n"
        # Probe by running it: a Windows Store alias is on PATH but runs nothing.
        '  if "$python" -c "" >/dev/null 2>&1; then\n'
        '    exec "$python" "$here/../hooks/signal" emit "$@"\n'
        "  fi\n"
        "done\n"
        'echo "mc-signal: no python3 or python on PATH; nothing was recorded" >&2\n'
        "exit 3\n"
    )


def _lf(path: Path) -> bytes:
    # Normalized to LF so the projection is byte-identical on every checkout.
    return path.read_bytes().replace(b"\r\n", b"\n")


def pack_files(
    lane: LaneProfile, gates: SignalGatePolicy | None = None
) -> tuple[tuple[str, bytes, int], ...]:
    """The script, the command and the policy: ``(path, content, mode)``."""

    policy = json.dumps(signal_policy(lane, gates), indent=2, sort_keys=True) + "\n"
    return (
        (SIGNAL_SCRIPT, _lf(SIGNAL_SCRIPT_SOURCE), 0o755),
        (SIGNAL_CLI, signal_cli().encode("utf-8"), 0o755),
        (SIGNAL_POLICY, policy.encode("utf-8"), 0o644),
    )


def skill_bytes() -> bytes:
    """The ``mc-signals`` skill as the pack places it (the ``skills/mc-signals`` bundle)."""

    return _lf(SIGNAL_SKILL_SOURCE)


__all__ = [
    "ADVISORY_INSTRUCTION",
    "FLUSH_EVENTS",
    "SIGNAL_CLI",
    "SIGNAL_POLICY",
    "SIGNAL_SCRIPT",
    "SIGNAL_SKILL",
    "SIGNAL_TYPES",
    "TELEMETRY_EVENTS",
    "TELEMETRY_HOOK_ID",
    "TelemetryHook",
    "carries_pack",
    "pack_files",
    "signal_cli",
    "signal_policy",
    "skill_bytes",
    "telemetry_hooks",
]
