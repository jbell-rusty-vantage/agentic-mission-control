"""Host Projection: the lane-neutral port and kit every lane's writer uses (ADR-0023; OC-R3).

``HostProjectors.render`` turns resolved capability rows into the native files each lane
profile's provider reads (SPEC-01 "Host projection"), plus Deep Agents in-process objects. The
provider file formats are each lane package's own writer (``adapters/<lane>/host_files.py``,
a ``LaneHostFiles``); bootstrap composes them by profile (``bootstrap/host_projection.py``), so
this module names no lane. Where each kind lands, which subagent fields a lane can carry and
the limits it enforces are rows of the per-lane layout table
(``domain/capabilities/layouts.py``). It is pure: the same inputs give the same bytes. Secrets
appear only as the lane's native reference syntax. Kernel hooks come first in every hook
array. Anything a profile cannot run is reported, never silently dropped.

Inputs are checked here before any writer runs: every row must declare host support for the
profile (``unsupported`` fails, ``unqualified`` is reported), plugin expansion rejects cycles,
repeated selections and conflicting versions, bundle bytes must match their pinned manifest
digests, and a hook's required event that the profile cannot run fails the projection. A
fail-closed hook (catalog or gating Kernel Hook) on an event the profile only observes, or
cannot fail closed on, is reported ``degraded`` (``HOOK_EVENT_MAPPING`` enforce/observe), and
so is a Kernel Hook event the lane's ``kernel_surface`` cannot deliver.

The mission instruction is an additive overlay (SPEC-02 §4, ADR-0044): no writer writes the
repository's ``AGENTS.md`` or a ``CLAUDE.md``. MCP servers in provider files carry the ``mc-``
provenance prefix so the merge into a repository's existing config can tell them apart
(``domain/agentic_components/layering.py``). Every subagent profile field a lane has no native
key for is reported ``degraded`` (the subagent inherits the parent session there). The hook
runner and the Telemetry Hook Pack script are lane-neutral; each answers through the lane's
own ``native_output.py`` (``place_native_output``).

``render_release_host_files`` is the older MCP-only renderer over Agentic Component
releases used by the materialization planner.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from mission_control.application.agentic_components.telemetry import (
    SIGNAL_HOOK_TIMEOUT_SECONDS,
    SIGNAL_SKILL,
    TELEMETRY_HOOK_ID,
    TelemetryHook,
    carries_pack,
    pack_files,
    skill_bytes,
    telemetry_hooks,
)
from mission_control.domain.agentic_components.contracts import (
    AgentHost,
    AgenticComponentRelease,
    GeneratedFile,
)
from mission_control.domain.agentic_components.layering import (
    mission_name,
)
from mission_control.domain.agentic_components.projection import (
    DEFAULT_KERNEL_HOOKS,
    KERNEL_HOOK_SCRIPT,
    HostProjection,
    InProcessProjection,
    KernelHook,
    ProjectedFile,
    ProjectionError,
    ProjectionReport,
    ResolvedCapability,
    UnsupportedHookEvent,
)
from mission_control.domain.authoring.contracts import (
    HookScriptDefinition,
    MCPServerDefinition,
    PluginDefinition,
    SkillDefinition,
    SubagentProfileDefinition,
)
from mission_control.domain.capabilities.gates import SignalGatePolicy
from mission_control.domain.capabilities.hooks import (
    CLAUDE_SDK_CALLBACK_EVENTS,
    KERNEL_GATE_HOOK_IDS,
    HookEvent,
    NativeHook,
    native_hook,
)
from mission_control.domain.capabilities.host_support import HostSupportStatus, LaneProfile
from mission_control.domain.capabilities.layouts import (
    LANE_LAYOUTS,
    LaneLayout,
    LayeringLayout,
    SubagentLayout,
)
from mission_control.domain.capabilities.subagents import SubagentProfile

HOOK_RUNNER_SCRIPT = ".mission/hooks/run.py"
KERNEL_HOOK_TIMEOUT_SECONDS = 30
_READ_ONLY_PREFIXES = ("inputs/", ".mission/inputs/", ".git/")
_HOOK_ROOT = ".mission/hooks"
EXEC_MODE = 0o755
FILE_MODE = 0o644


# Where a lane package's native hook output module lands, beside the hook runner and the
# Telemetry Hook Pack script that load it (`load_native_output` in both scripts).
NATIVE_OUTPUT_SCRIPT = ".mission/hooks/native_output.py"

# How Kernel Hooks reach a lane: its native hook surface, in-process SDK callbacks (the local
# Claude Agent SDK lane), or not at all (the lane's writer reports the loss wholesale).
KernelSurface = Literal["native_hook", "sdk_callback", "none"]


# ------------------------------------------------------------------------------------------
# The port: one writer per lane package, one dispatch by profile
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectionInputs:
    """What a lane writer receives once the shared checks and reports have run."""

    skills: tuple[ResolvedCapability, ...]
    servers: tuple[ResolvedCapability, ...]
    hooks: tuple[ResolvedCapability, ...]
    agents: tuple[ResolvedCapability, ...]
    kernel_hooks: tuple[KernelHook, ...]
    # The overlay text (the instruction plus the mission context index) and the instruction
    # as given (an in-process lane's system prompt).
    instructions: str
    instruction: str
    agent_server_bound: bool


class LaneHostFiles(Protocol):
    """One lane package's Host Projection writer (`adapters/<lane>/host_files.py`)."""

    @property
    def kernel_surface(self) -> KernelSurface: ...

    def write(
        self, inputs: ProjectionInputs, state: ProjectionState
    ) -> InProcessProjection | None: ...


class HostProjectors:
    """The Host Projection port: the lane-neutral checks and reports, then the profile's own
    writer (OC-R3; the writers live in their lane packages and bootstrap composes them)."""

    def __init__(self, writers: Mapping[str, LaneHostFiles]) -> None:
        self._writers = dict(writers)

    def profiles(self) -> tuple[str, ...]:
        return tuple(sorted(self._writers))

    def render(
        self,
        rows: Sequence[ResolvedCapability],
        profile: LaneProfile | str,
        instruction: str,
        packet_index: str | None = None,
        kernel_hooks: Sequence[KernelHook] = DEFAULT_KERNEL_HOOKS,
        *,
        agent_server_bound: bool = False,
        telemetry: bool = True,
        gates: SignalGatePolicy | None = None,
    ) -> HostProjection:
        """Project resolved capability rows into one lane profile's native configuration.

        ``telemetry`` places the Telemetry Hook Pack (SPEC-04 section 4) on the lanes that carry
        it; ``False`` is ``observation.in_environment: off``."""
        lane = LaneProfile(profile)
        writer = self._writers.get(lane.value)
        if writer is None:
            raise ProjectionError(f"no Host Projection writer is composed for {lane.value}")
        if gates is not None and not telemetry:
            raise ProjectionError("signal gates require the telemetry pack")
        state = ProjectionState(lane, telemetry=telemetry and carries_pack(lane), gates=gates)
        if gates is not None:
            telemetry_hooks(lane, gates)  # Refuse unsupported native enforcement before placing.
        expanded = _expand(rows, lane, state)
        skills = [row for row in expanded if isinstance(row.definition, SkillDefinition)]
        servers = [row for row in expanded if isinstance(row.definition, MCPServerDefinition)]
        hooks = [row for row in expanded if isinstance(row.definition, HookScriptDefinition)]
        agents = [row for row in expanded if isinstance(row.definition, SubagentProfileDefinition)]
        _check_unique_names(skills, servers, agents)
        for row in hooks:
            _report_hook_events(row, lane, state)
        _reject_lost_required_events(lane, state)
        report_kernel_gaps(lane, kernel_hooks, state, writer.kernel_surface)
        subagents = state.layout.subagents
        if subagents is not None:
            for row in agents:
                _report_subagent_fields(row, subagents, state)
        inputs = ProjectionInputs(
            skills=tuple(skills),
            servers=tuple(servers),
            hooks=tuple(hooks),
            agents=tuple(agents),
            kernel_hooks=tuple(kernel_hooks),
            instructions=_instruction_text(instruction, packet_index),
            instruction=instruction,
            agent_server_bound=agent_server_bound,
        )
        return state.result(in_process=writer.write(inputs, state))


# ------------------------------------------------------------------------------------------
# Shared state, path hygiene and expansion
# ------------------------------------------------------------------------------------------


@dataclass
class ProjectionState:
    lane: LaneProfile
    telemetry: bool = False
    gates: SignalGatePolicy | None = None
    files: dict[str, ProjectedFile] = field(default_factory=dict)
    unsupported: list[UnsupportedHookEvent] = field(default_factory=list)
    requires_trust: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    unqualified: list[str] = field(default_factory=list)
    overflow: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    expansions: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    send_options: dict[str, object] = field(default_factory=dict)
    environment_names: set[str] = field(default_factory=set)

    @property
    def layout(self) -> LaneLayout:
        return LANE_LAYOUTS[self.lane]

    @property
    def telemetry_hooks(self) -> tuple[TelemetryHook, ...]:
        return telemetry_hooks(self.lane, self.gates) if self.telemetry else ()

    @property
    def layering(self) -> LayeringLayout:
        """The native roots of a lane whose cognition lands in a repository."""
        layering = self.layout.layering
        assert layering is not None, f"{self.lane.value} has no repository layout"
        return layering

    def write(self, path: str, content: bytes | str, mode: int = FILE_MODE) -> None:
        normalized = _safe_path(path)
        if normalized in self.files:
            raise ProjectionError(f"duplicate projected path: {normalized}")
        data = content.encode("utf-8") if isinstance(content, str) else content
        self.files[normalized] = ProjectedFile(path=normalized, content=data, mode=mode)

    def result(self, *, in_process: InProcessProjection | None = None) -> HostProjection:
        return HostProjection(
            profile=self.lane,
            files=tuple(self.files[path] for path in sorted(self.files)),
            report=ProjectionReport(
                unsupported_on_lane=tuple(self.unsupported),
                requires_trust=tuple(dict.fromkeys(self.requires_trust)),
                degraded=tuple(self.degraded),
                unqualified=tuple(self.unqualified),
                overflow=tuple(self.overflow),
                skipped_members=tuple(self.skipped),
                plugin_expansions=tuple(self.expansions),
            ),
            in_process=in_process,
            send_options=dict(self.send_options),
            environment_names=tuple(sorted(self.environment_names)),
        )


def _safe_path(path: str) -> str:
    raw = path.replace("\\", "/")
    pure = PurePosixPath(raw)
    if pure.is_absolute() or ".." in pure.parts or raw.startswith("~"):
        raise ProjectionError(f"projected path escapes the workspace: {path}")
    normalized = pure.as_posix()
    if normalized in {"", "."}:
        raise ProjectionError("projected path is empty")
    if any(normalized.startswith(prefix) for prefix in _READ_ONLY_PREFIXES):
        raise ProjectionError(f"projected path writes into a read-only seed: {normalized}")
    return normalized


def _expand(
    rows: Iterable[ResolvedCapability], lane: LaneProfile, state: ProjectionState
) -> list[ResolvedCapability]:
    """Flatten plugins into their members in position order; skip unsupported optionals.

    Deterministic: the output is the depth-first manifest order. A capability may be selected
    once per projection; a plugin that (transitively) contains itself, the same pin reached
    twice, or two versions of one capability are rejected with the selection path.
    """
    out: list[ResolvedCapability] = []
    selected: dict[str, tuple[str, str]] = {}

    def visit(row: ResolvedCapability, parents: tuple[str, ...]) -> None:
        rendered = row.pin.render()
        trail = " > ".join((*parents, rendered))
        if rendered in parents:
            raise ProjectionError(f"plugin dependency cycle: {trail}")
        _check_host_support(row, lane, state, trail)
        capability = row.pin.capability_id
        previous = selected.get(capability)
        if previous is not None:
            version, where = previous
            if version == row.pin.version:
                raise ProjectionError(f"capability selected more than once: {where} and {trail}")
            raise ProjectionError(f"conflicting versions of {capability}: {where} and {trail}")
        selected[capability] = (row.pin.version, trail)
        definition = row.definition
        if isinstance(definition, PluginDefinition):
            optional = {m.pin for m in definition.manifest.members if m.optional}
            taken: list[str] = []
            for member in row.members:
                if member.pin in optional and not _runs_on(member, lane):
                    state.skipped.append(member.pin.render())
                    continue
                visit(member, (*parents, rendered))
                taken.append(member.pin.render())
            state.expansions.append((rendered, tuple(taken)))
            return
        out.append(row)

    for row in rows:
        visit(row, ())
    return out


def _host_status(row: ResolvedCapability, lane: LaneProfile) -> HostSupportStatus:
    host_support = getattr(row.definition, "host_support", None)
    return HostSupportStatus.UNSUPPORTED if host_support is None else host_support.status(lane)


def _runs_on(row: ResolvedCapability, lane: LaneProfile) -> bool:
    return _host_status(row, lane) is HostSupportStatus.SUPPORTED


def _check_host_support(
    row: ResolvedCapability, lane: LaneProfile, state: ProjectionState, trail: str
) -> None:
    status = _host_status(row, lane)
    if status is HostSupportStatus.UNSUPPORTED:
        raise ProjectionError(f"{trail} declares no support for lane profile {lane.value}")
    if status is HostSupportStatus.UNQUALIFIED:
        state.unqualified.append(
            f"{row.pin.render()}: host support on {lane.value} is unqualified; projected "
            "without materialization proof"
        )


def _check_unique_names(
    skills: Sequence[ResolvedCapability],
    servers: Sequence[ResolvedCapability],
    agents: Sequence[ResolvedCapability],
) -> None:
    for label, names in (
        ("skill", [skill_name(row) for row in skills]),
        ("MCP server", [server_name(row) for row in servers]),
        ("subagent", [subagent(row).profile.name for row in agents]),
    ):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ProjectionError(f"duplicate {label} name(s): {', '.join(duplicates)}")


def host_overlay(row: ResolvedCapability, lane: LaneProfile) -> dict[str, object]:
    host_support = getattr(row.definition, "host_support", None)
    return {} if host_support is None else host_support.overlay(lane)


def _instruction_text(instruction: str, packet_index: str | None) -> str:
    text = instruction.rstrip() + "\n"
    if packet_index:
        text += "\n## Mission context\n\n" + packet_index.rstrip() + "\n"
    return text


def dumps_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def frontmatter(fields: Sequence[tuple[str, object]], body: str) -> str:
    lines = ["---"]
    for key, value in fields:
        if value is None:
            continue
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, int):
            rendered = str(value)
        elif isinstance(value, list | tuple):
            rendered = json.dumps(list(value), ensure_ascii=False)
        else:
            rendered = json.dumps(str(value), ensure_ascii=False)
        lines.append(f"{key}: {rendered}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.rstrip() + "\n"


# ------------------------------------------------------------------------------------------
# Skills and hook script directories
# ------------------------------------------------------------------------------------------


def skill_name(row: ResolvedCapability) -> str:
    definition = row.definition
    assert isinstance(definition, SkillDefinition)
    return definition.skill_name


def _verify_pinned_bytes(row: ResolvedCapability, label: str) -> None:
    """Every resolved file must be exactly the manifest entry it claims to be."""
    definition = row.definition
    assert isinstance(definition, SkillDefinition | HookScriptDefinition)
    entries = {entry.path: entry for entry in definition.file_manifest}
    if {item.path for item in row.files} != set(entries):
        raise ProjectionError(f"{label} {row.pin.render()} files differ from its manifest")
    for item in row.files:
        entry = entries[item.path]
        digest = "sha256:" + sha256(item.content).hexdigest()
        if digest != entry.digest or len(item.content) != entry.size_bytes:
            raise ProjectionError(
                f"{label} {row.pin.render()} file {item.path} does not match its pinned digest"
            )


def _skill_frontmatter(content: bytes) -> dict[str, str]:
    """Top-level scalar keys of a SKILL.md YAML frontmatter block (the fields providers read)."""
    text = content.decode("utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    fields: dict[str, str] = {}
    for line in text[4:end].split("\n"):
        if not line or line[0] in " \t#" or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def skill_files(row: ResolvedCapability, state: ProjectionState) -> list[tuple[str, bytes, int]]:
    definition = row.definition
    assert isinstance(definition, SkillDefinition)
    label = "skill bundle"
    if not row.files:
        raise ProjectionError(f"{label} {row.pin.render()} has no resolved files")
    by_path = {item.path: item for item in row.files}
    if "SKILL.md" not in by_path:
        raise ProjectionError(f"{label} {row.pin.render()} has no SKILL.md")
    _verify_pinned_bytes(row, label)
    name = definition.skill_name
    limit = state.layout.skill_name_limit
    if len(name) > limit:
        raise ProjectionError(f"skill name {name!r} exceeds {limit} characters")
    # Claude Code and Codex discover a skill by its SKILL.md frontmatter, not by the directory.
    frontmatter = _skill_frontmatter(by_path["SKILL.md"].content)
    if frontmatter.get("name") != name:
        raise ProjectionError(
            f"{label} {row.pin.render()} SKILL.md frontmatter name "
            f"{frontmatter.get('name')!r} does not match skill_name {name!r}"
        )
    if not frontmatter.get("description"):
        raise ProjectionError(f"{label} {row.pin.render()} SKILL.md has no description")
    return [
        (item.path, item.content, EXEC_MODE if item.executable else FILE_MODE)
        for item in sorted(row.files, key=lambda item: item.path)
    ]


def write_skills(skills: Sequence[ResolvedCapability], root: str, state: ProjectionState) -> None:
    for row in skills:
        name = skill_name(row)
        for path, content, mode in skill_files(row, state):
            state.write(f"{root}/{name}/{path}", content, mode)


def hook_dir(row: ResolvedCapability) -> str:
    return f"{_HOOK_ROOT}/{_hook_slug(row.definition.logical_id)}"


def _hook_slug(logical_id: str) -> str:
    return re.sub(r"[^a-z0-9._-]", "-", logical_id)


HOOK_RUNNER_SOURCE = Path(__file__).with_name("hook_runner.py")


def write_hook_scripts(
    hooks: Sequence[ResolvedCapability], state: ProjectionState, *, runner: bool = True
) -> None:
    """Hook directories, their ``hook.json`` descriptors and (file lanes) the hook runner."""
    if hooks and runner:
        # Normalized to LF so the projection is byte-identical on every checkout.
        source = HOOK_RUNNER_SOURCE.read_bytes().replace(b"\r\n", b"\n")
        state.write(HOOK_RUNNER_SCRIPT, source, EXEC_MODE)
    for row in hooks:
        definition = row.definition
        assert isinstance(definition, HookScriptDefinition)
        _verify_pinned_bytes(row, "hook script")
        for item in sorted(row.files, key=lambda item: item.path):
            executable = item.executable or item.path == definition.entrypoint
            state.write(
                f"{hook_dir(row)}/{item.path}", item.content, EXEC_MODE if executable else FILE_MODE
            )
        if runner:
            descriptor = {
                "schema_version": "mc.hook_descriptor.v1",
                "hook_id": definition.logical_id,
                "pin": row.pin.render(),
                "lane_profile": state.lane.value,
                "events": [event.value for event in definition.events],
                "interpreter": definition.interpreter.value,
                "entrypoint": definition.entrypoint,
                "timeout_seconds": definition.timeout_seconds,
                "fail_closed": definition.fail_closed,
                "callback": definition.callback.value,
            }
            state.write(f"{hook_dir(row)}/hook.json", dumps_json(descriptor))


def place_native_output(
    hooks: Sequence[ResolvedCapability], state: ProjectionState, source: Path
) -> None:
    """The lane package's native hook output module (``source``), beside the hook runner and
    the Telemetry Hook Pack gate that load it: placed when the runner is (a catalog hook) or a
    signal gate is, LF-normalized so the projection is byte-identical on every checkout."""
    if hooks or (state.telemetry and state.gates is not None):
        state.write(NATIVE_OUTPUT_SCRIPT, source.read_bytes().replace(b"\r\n", b"\n"))


def write_telemetry_pack(skills: Sequence[ResolvedCapability], state: ProjectionState) -> None:
    """The Telemetry Hook Pack's script, command and policy, and the ``mc-signals`` skill
    unless a selected catalog row already places it."""
    for path, content, mode in pack_files(state.lane, state.gates):
        state.write(path, content, mode)
    if all(skill_name(row) != SIGNAL_SKILL for row in skills):
        state.write(f"{state.layering.skills}/{SIGNAL_SKILL}/SKILL.md", skill_bytes())


def _report_hook_events(row: ResolvedCapability, lane: LaneProfile, state: ProjectionState) -> None:
    definition = row.definition
    assert isinstance(definition, HookScriptDefinition)
    for event in definition.events:
        native = native_hook(lane, event)
        if native is None:
            state.unsupported.append(
                UnsupportedHookEvent(
                    hook_id=definition.logical_id,
                    event=event,
                    required=event in definition.required_events,
                )
            )
        elif definition.fail_closed:
            _report_unenforced(definition.logical_id, lane, event, native, state)


def _report_unenforced(
    hook_id: str, lane: LaneProfile, event: HookEvent, native: NativeHook, state: ProjectionState
) -> None:
    """A fail-closed hook whose native event cannot block (or cannot fail closed) on the lane."""
    if not native.enforceable:
        state.degraded.append(
            f"{hook_id}: {native.native_event} cannot hold {event.value} fail-closed on "
            f"{lane.value} ({native.mode.value})"
        )


def _reject_lost_required_events(lane: LaneProfile, state: ProjectionState) -> None:
    lost = [item for item in state.unsupported if item.required]
    if lost:
        named = ", ".join(f"{item.hook_id} {item.event.value}" for item in lost)
        raise ProjectionError(
            f"required hook event(s) have no native hook on lane profile {lane.value}: {named}"
        )


def kernel_delivers(
    lane: LaneProfile, event: HookEvent, *, in_process: bool = False
) -> NativeHook | None:
    """The native hook a Kernel Hook event rides on; in-process Kernel Hooks (SDK callbacks,
    outside agent-writable files) reach only the events the Python SDK calls back."""
    native = native_hook(lane, event)
    if native is not None and in_process and event not in CLAUDE_SDK_CALLBACK_EVENTS:
        return None
    return native


def report_kernel_gaps(
    lane: LaneProfile,
    kernel_hooks: Sequence[KernelHook],
    state: ProjectionState,
    surface: KernelSurface = "native_hook",
) -> None:
    """Name every Kernel Hook event the profile cannot deliver (a lane without a Kernel Hook
    surface reports the loss wholesale in its own writer)."""
    if surface == "none":
        return
    in_process = surface == "sdk_callback"
    label = "Python SDK callback" if in_process else "native hook"
    for kernel in kernel_hooks:
        missing = [
            event.value
            for event in kernel.events
            if kernel_delivers(lane, event, in_process=in_process) is None
        ]
        if missing:
            state.degraded.append(
                f"{kernel.hook_id}: no {label} on {lane.value} for {', '.join(missing)}"
            )
        if kernel.hook_id in KERNEL_GATE_HOOK_IDS:
            for event in kernel.events:
                native = kernel_delivers(lane, event, in_process=in_process)
                if native is not None:
                    _report_unenforced(kernel.hook_id, lane, event, native, state)


def _catalog_hook_command(row: ResolvedCapability, event: HookEvent) -> list[str]:
    """Exec form: the lane's hook runner adapts native stdin to ``mc.hook_input.v1``."""
    return ["python", HOOK_RUNNER_SCRIPT, _hook_slug(row.definition.logical_id), event.value]


def _kernel_hook_command(hook: KernelHook, event: HookEvent) -> list[str]:
    return ["python", KERNEL_HOOK_SCRIPT, event.value, hook.hook_id]


@dataclass(frozen=True)
class HookEntry:
    hook_id: str
    event: HookEvent
    native: NativeHook
    command: list[str]
    timeout: int
    fail_closed: bool
    matcher: str | None
    overlay: dict[str, object]
    kernel: bool


def hook_entries(
    lane: LaneProfile,
    kernel_hooks: Sequence[KernelHook],
    hooks: Sequence[ResolvedCapability],
    telemetry: Sequence[TelemetryHook] = (),
) -> list[HookEntry]:
    """Kernel hooks first in their fixed order, then catalog hooks in row order, then the
    Telemetry Hook Pack (fail-open, asynchronous where the lane allows)."""
    entries: list[HookEntry] = []
    for kernel in kernel_hooks:
        for event in kernel.events:
            native = kernel_delivers(lane, event)
            if native is None:
                continue
            entries.append(
                HookEntry(
                    hook_id=kernel.hook_id,
                    event=event,
                    native=native,
                    command=_kernel_hook_command(kernel, event),
                    timeout=KERNEL_HOOK_TIMEOUT_SECONDS,
                    fail_closed=True,
                    matcher=native.matcher,
                    overlay={},
                    kernel=True,
                )
            )
    for row in hooks:
        definition = row.definition
        assert isinstance(definition, HookScriptDefinition)
        overlay = host_overlay(row, lane)
        for event in definition.events:
            native = native_hook(lane, event)
            if native is None:
                continue
            matcher = overlay.get("matcher", native.matcher or definition.matcher)
            entries.append(
                HookEntry(
                    hook_id=definition.logical_id,
                    event=event,
                    native=native,
                    command=_catalog_hook_command(row, event),
                    timeout=definition.timeout_seconds,
                    fail_closed=definition.fail_closed,
                    matcher=None if matcher is None else str(matcher),
                    overlay=overlay,
                    kernel=False,
                )
            )
    entries.extend(
        HookEntry(
            hook_id=TELEMETRY_HOOK_ID,
            event=hook.event,
            native=hook.native,
            command=hook.command,
            timeout=SIGNAL_HOOK_TIMEOUT_SECONDS,
            fail_closed=hook.fail_closed,
            matcher=hook.native.matcher,
            overlay={} if hook.gate else {"async": True},
            kernel=False,
        )
        for hook in telemetry
    )
    return entries


def shell_join(parts: Sequence[str]) -> str:
    return " ".join(
        part if re.fullmatch(r"[A-Za-z0-9_./:@=-]+", part) else json.dumps(part) for part in parts
    )


# ------------------------------------------------------------------------------------------
# MCP servers
# ------------------------------------------------------------------------------------------


def server_name(row: ResolvedCapability) -> str:
    logical = row.definition.logical_id
    name = logical.removeprefix("mcp.")
    return re.sub(r"[^A-Za-z0-9_-]", "-", name)


def file_server_name(row: ResolvedCapability) -> str:
    """The server's name in a provider config file, with the ``mc-`` provenance prefix."""

    return mission_name(server_name(row))


@dataclass(frozen=True)
class McpLaunch:
    transport: str
    command: str | None
    args: tuple[str, ...]
    url: str | None
    env: dict[str, str]
    env_refs: dict[str, str]
    header_refs: dict[str, str]
    tools: tuple[str, ...]


def mcp_launch(row: ResolvedCapability, lane: LaneProfile) -> McpLaunch:
    definition = row.definition
    assert isinstance(definition, MCPServerDefinition)
    overlay = host_overlay(row, lane)
    transport = str(overlay.get("transport", definition.transport))
    header_refs = dict(definition.header_refs)
    overlay_headers = overlay.get("header_refs")
    if isinstance(overlay_headers, dict):
        header_refs.update({str(k): str(v) for k, v in overlay_headers.items()})
    if transport == "stdio":
        template = definition.launch_template
        if not template:
            raise ProjectionError(f"{row.pin.render()} has no stdio launch template")
        command, args, url = template[0], tuple(template[1:]), None
    else:
        candidate = overlay.get("url", definition.endpoint)
        if not isinstance(candidate, str) or not candidate:
            raise ProjectionError(f"{row.pin.render()} has no endpoint for {lane.value}")
        command, args, url = None, (), candidate
    exposed = definition.exposed_tools()
    tools = tuple(sorted(tool.name for tool in exposed)) or tuple(sorted(definition.allowed_tools))
    return McpLaunch(
        transport=transport,
        command=command,
        args=args,
        url=url,
        env=dict(definition.env),
        env_refs=dict(definition.env_refs),
        header_refs=header_refs,
        tools=tools,
    )


def _header_value(header: str, ref: str, template: str) -> str:
    reference = template.format(name=ref)
    return f"Bearer {reference}" if header.lower() == "authorization" else reference


def json_mcp_entry(
    row: ResolvedCapability, lane: LaneProfile, *, cursor: bool
) -> dict[str, object]:
    launch = mcp_launch(row, lane)
    template = "${{env:{name}}}" if cursor else "${{{name}}}"
    entry: dict[str, object]
    if launch.transport == "stdio":
        entry = {"type": "stdio", "command": launch.command, "args": list(launch.args)}
        env = dict(launch.env)
        env.update({key: template.format(name=ref) for key, ref in launch.env_refs.items()})
        if env:
            entry["env"] = env
    else:
        entry = {
            "type": "http" if launch.transport == "streamable_http" else "sse",
            "url": launch.url,
        }
        if launch.header_refs:
            entry["headers"] = {
                header: _header_value(header, ref, template)
                for header, ref in launch.header_refs.items()
            }
    definition = row.definition
    assert isinstance(definition, MCPServerDefinition)
    if cursor and definition.oauth is not None:
        auth: dict[str, object] = {
            "CLIENT_ID": template.format(name=definition.oauth.client_id_ref)
        }
        if definition.oauth.client_secret_ref:
            auth["CLIENT_SECRET"] = template.format(name=definition.oauth.client_secret_ref)
        if definition.oauth.scopes:
            auth["scopes"] = list(definition.oauth.scopes)
        entry["auth"] = auth
    return entry


def mcp_environment_names(
    servers: Sequence[ResolvedCapability],
    lane: LaneProfile,
    *,
    by_name: bool = False,
    oauth_refs: bool = False,
) -> set[str]:
    """The variables the projected MCP configuration reads from the provider process
    environment, names only: the `${NAME}` / `${env:NAME}` references `json_mcp_entry` writes
    (stdio env, headers and, with ``oauth_refs``, an OAuth block) and, with ``by_name``, the
    `env_vars` names a lane forwarding variables by name writes beside its `env_http_headers`
    and `bearer_token_env_var` names."""

    names: set[str] = set()
    for row in servers:
        launch = mcp_launch(row, lane)
        if launch.transport == "stdio":
            names.update(launch.env_refs.values())
            if by_name:
                names.update(launch.env_refs)
        else:
            names.update(launch.header_refs.values())
        definition = row.definition
        assert isinstance(definition, MCPServerDefinition)
        oauth = definition.oauth
        if oauth_refs and oauth is not None:
            names.add(oauth.client_id_ref)
            if oauth.client_secret_ref:
                names.add(oauth.client_secret_ref)
    return names


# ------------------------------------------------------------------------------------------
# Subagents
# ------------------------------------------------------------------------------------------


def subagent(row: ResolvedCapability) -> SubagentProfileDefinition:
    definition = row.definition
    assert isinstance(definition, SubagentProfileDefinition)
    return definition


# What a subagent loses on a lane whose subagent definition has no key for a field it sets.
_SUBAGENT_FIELD_LOSS = {
    "model": "model choice; it runs on the parent session's model",
    "tools": "tool allowlist; it inherits the parent session's tools",
    "skills": "skill restriction; it sees every skill of the session",
    "mcp_servers": "MCP server restriction; it inherits the parent session's servers",
    "readonly": "read-only setting; it can write",
    "background": "background setting; it runs as a foreground agent",
    "max_turns": "max_turns limit",
    "interrupt_on": "interrupt_on approvals",
    "context_mode": "forked context; it starts from an isolated context",
}


def _set_fields(profile: SubagentProfile) -> tuple[str, ...]:
    """The profile fields that ask for more than the lane's default subagent."""
    requested = {
        "model": profile.model != "inherit",
        "tools": bool(profile.tools),
        "skills": bool(profile.skills),
        "mcp_servers": bool(profile.mcp_servers),
        "readonly": profile.readonly,
        "background": profile.background,
        "max_turns": profile.max_turns is not None,
        "interrupt_on": bool(profile.interrupt_on),
        "context_mode": profile.context_mode != "isolated",
    }
    return tuple(name for name, is_set in requested.items() if is_set)


def _report_subagent_fields(
    row: ResolvedCapability, subagents: SubagentLayout, state: ProjectionState
) -> None:
    profile = subagent(row).profile
    for name in _set_fields(profile):
        if name not in subagents.fields:
            state.degraded.append(
                f"subagent {profile.name}: {state.lane.value} subagents have no per-agent "
                f"{_SUBAGENT_FIELD_LOSS[name]}"
            )


def subagent_file_only(
    row: ResolvedCapability, subagents: SubagentLayout, lane: LaneProfile
) -> bool:
    """Whether the subagent asks for a field its file carries but an inline launch definition
    does not (Cursor: ``readonly``, ``is_background``); a host-support overlay value, keyed by
    the native field, wins over the profile's."""
    requested = set(_set_fields(subagent(row).profile))
    overlay = host_overlay(row, lane)
    return any(
        bool(overlay[native]) if native in overlay else field in requested
        for field, native in subagents.fields.items()
        if field not in subagents.inline_fields
    )


def subagent_path(layering: LayeringLayout, name: str) -> str:
    assert layering.agents is not None
    return f"{layering.agents}/{name}{layering.agent_suffix}"


def subagent_prompt(row: ResolvedCapability) -> str:
    profile = subagent(row).profile
    if profile.prompt is not None:
        return profile.prompt
    for item in row.files:
        if item.path in {"prompt.md", "PROMPT.md"}:
            return item.content.decode("utf-8")
    raise ProjectionError(f"subagent {row.pin.render()} prompt bundle is not resolved")


def subagent_model(row: ResolvedCapability, lane: LaneProfile) -> str:
    overlay = host_overlay(row, lane)
    return str(overlay.get("model", subagent(row).profile.model))


# ------------------------------------------------------------------------------------------
# Profiles
# ------------------------------------------------------------------------------------------


def matcher_hooks(
    lane: LaneProfile,
    kernel_hooks: Sequence[KernelHook],
    hooks: Sequence[ResolvedCapability],
    telemetry: Sequence[TelemetryHook],
    *,
    exec_form: bool,
) -> dict[str, list[dict[str, object]]]:
    """Claude Code and Codex shape: ``{Event: [{matcher, hooks: [{type, command, ...}]}]}``."""
    out: dict[str, list[dict[str, object]]] = {}
    for entry in hook_entries(lane, kernel_hooks, hooks, telemetry):
        handler: dict[str, object] = {"type": "command"}
        if exec_form:
            handler["command"] = entry.command[0]
            handler["args"] = entry.command[1:]
            handler["timeout"] = entry.timeout
            if entry.overlay.get("async") is True:
                handler["async"] = True
            if entry.hook_id == TELEMETRY_HOOK_ID and entry.fail_closed:
                handler["onFailure"] = "block"
        else:
            handler["command"] = shell_join(entry.command)
            handler["timeout"] = entry.timeout
            limit = entry.overlay.get("additional_context_limit")
            if isinstance(limit, int) and not isinstance(limit, bool):
                handler["additionalContextLimit"] = limit
        group: dict[str, object] = {"hooks": [handler]}
        if entry.matcher:
            group["matcher"] = entry.matcher
        out.setdefault(entry.native.native_event, []).append(group)
    return out


# ------------------------------------------------------------------------------------------
# Agentic Component releases (MCP-only renderer used by the materialization planner)
# ------------------------------------------------------------------------------------------


def render_release_host_files(
    host: AgentHost,
    releases: tuple[AgenticComponentRelease, ...],
) -> tuple[GeneratedFile, ...]:
    mcp_releases = tuple(release for release in releases if release.mcp is not None)
    if not mcp_releases:
        return ()
    if host == AgentHost.CODEX:
        return (_generated(".codex/config.toml", "application/toml", _render_codex(mcp_releases)),)
    if host == AgentHost.CURSOR:
        return (
            _generated(
                ".cursor/mcp.json",
                "application/json",
                _render_json_host(mcp_releases, cursor=True),
            ),
        )
    if host == AgentHost.CLAUDE_CODE:
        return (
            _generated(
                ".mcp.json",
                "application/json",
                _render_json_host(mcp_releases, cursor=False),
            ),
        )
    return ()


def skill_target_path(host: AgentHost, skill_name: str) -> str:
    roots = {
        AgentHost.CODEX: ".agents/skills",
        AgentHost.CURSOR: ".cursor/skills",
        AgentHost.CLAUDE_CODE: ".claude/skills",
        AgentHost.AGENT_FRAMEWORK: ".agents/skills",
    }
    return f"{roots[host]}/{skill_name}"


def _render_json_host(
    releases: tuple[AgenticComponentRelease, ...],
    *,
    cursor: bool,
) -> str:
    servers: dict[str, object] = {}
    for release in releases:
        binding = release.mcp
        assert binding is not None
        if binding.transport == "stdio":
            entry: dict[str, object] = {
                "command": binding.command,
                "args": list(binding.arguments),
            }
            if not cursor:
                entry["type"] = "stdio"
            if binding.secret_environment:
                entry["env"] = {
                    item.environment_name: f"${{{item.environment_name}}}"
                    for item in binding.secret_environment
                }
        else:
            entry = {"url": binding.url}
            if not cursor:
                entry["type"] = "http" if binding.transport == "streamable_http" else "sse"
        servers[binding.server_name] = entry
    return json.dumps({"mcpServers": servers}, indent=2, sort_keys=True) + "\n"


def _render_codex(releases: tuple[AgenticComponentRelease, ...]) -> str:
    lines = ["# Generated by the BellLabs Agentic Components harness."]
    for release in sorted(releases, key=lambda item: item.mcp.server_name if item.mcp else ""):
        binding = release.mcp
        assert binding is not None
        name = binding.server_name.replace('"', '\\"')
        lines.extend(("", f'[mcp_servers."{name}"]'))
        if binding.transport == "stdio":
            lines.append(f"command = {json.dumps(binding.command)}")
            if binding.arguments:
                args = ", ".join(json.dumps(item) for item in binding.arguments)
                lines.append(f"args = [{args}]")
            if binding.working_directory:
                lines.append(f"cwd = {json.dumps(binding.working_directory)}")
            if binding.secret_environment:
                values = ", ".join(
                    json.dumps(item.environment_name) for item in binding.secret_environment
                )
                lines.append(f"env_vars = [{values}]")
        else:
            lines.append(f"url = {json.dumps(binding.url)}")
        lines.append("enabled = true")
        allowed = ", ".join(json.dumps(item) for item in sorted(binding.allowed_tools))
        lines.append(f"enabled_tools = [{allowed}]")
    return "\n".join(lines) + "\n"


def _generated(path: str, media_type: str, content: str) -> GeneratedFile:
    return GeneratedFile(
        path=path,
        media_type=media_type,
        content=content,
        digest=f"sha256:{sha256(content.encode()).hexdigest()}",
    )
