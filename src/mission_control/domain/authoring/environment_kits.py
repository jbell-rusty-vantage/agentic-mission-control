"""Environment Kits (``mc.environment_kit.v1``) and the mission layer they render (ADR-0042).

An Environment Kit is a pinned catalog bundle with two layers (SPEC-01 sections 1-2):

- the **base layer** (toolchains, system packages, a base install script, long-lived services),
  installed rarely, by Mission Control where a provider has an API and otherwise as an owner
  prerequisite;
- the **mission layer**: ordered setup steps and health checks rendered into one script,
  ``.mission/setup/run``, that the **bootstrap entrypoint** runs before agent work. The script
  is idempotent, bounded by the kit's ``timeout_s`` and writes ``.mission/setup/receipt.json``
  (``mc.mission_setup_receipt.v1``), the evidence that lifts readiness to ``prepared``.

Rendering is pure and deterministic, so the same kit pin always yields the same script digest.
The script names variables only; it never contains a secret value.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Final, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from mission_control.domain.authoring.canonical import stable_json_dump
from mission_control.domain.authoring.mission_environment import KitRequirements
from mission_control.domain.capabilities.bundles import normalize_bundle_path, sha256_hex
from mission_control.domain.capabilities.host_support import (
    HOSTED_PROFILES,
    CapabilityHostSupport,
    HostProfileSupport,
    HostSupportStatus,
    LaneProfile,
)
from mission_control.domain.capabilities.pins import CapabilityPin

ENVIRONMENT_KIT_SCHEMA: Final = "mc.environment_kit.v1"
MISSION_SETUP_RECEIPT_SCHEMA: Final = "mc.mission_setup_receipt.v1"
KIT_MANIFEST_PATH: Final = "kit.json"

MISSION_SETUP_DIR: Final = ".mission/setup"
MISSION_SETUP_RUN: Final = f"{MISSION_SETUP_DIR}/run"
MISSION_SETUP_RECEIPT: Final = f"{MISSION_SETUP_DIR}/receipt.json"
MISSION_SETUP_KIT: Final = f"{MISSION_SETUP_DIR}/kit.json"

# The overlay key an environment kit carries on a hosted profile: who installs its base layer.
BASE_LAYER_OVERLAY: Final = "base_layer"
SetupPhase = Literal["prepare", "start"]

_NAME = r"^[a-z][a-z0-9-]{0,62}$"
_SAFE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")
_WHEN = re.compile(r"^(?P<negate>!)?exists\('(?P<path>[^']+)'\)$")

# Toolchains a kit may declare, each with the command that reports the installed version. A
# closed table: the receipt records only what Mission Control knows how to observe.
TOOLCHAIN_PROBES: Final[Mapping[str, str]] = {
    "python": "python3 --version 2>/dev/null || python --version",
    "uv": "uv --version",
    "node": "node --version",
    "npm": "npm --version",
    "postgres": "psql --version",
    "temporal": "temporal --version",
    "docker": "docker --version",
    "git": "git --version",
}

# Lanes with a bootstrap entrypoint (SPEC-01 section 1). cursor_local, claude_agent_sdk and
# codex run it in the worker's prepare step, in the leased worktree, before the session starts.
# The hosted lanes run it from their base layer at agent start: cursor_cloud from `start` in the
# Mission Control-owned .cursor/environment.json, claude_cloud from a committed
# .claude/settings.json SessionStart command hook (CLAUDE_CODE_REMOTE=true), codex_cloud from the
# environment's start skill and install script (owner pasted). Delivery to hosted lanes is MO-13.
ENTRYPOINT_PROFILES: Final[frozenset[LaneProfile]] = frozenset(
    {
        LaneProfile.CURSOR_LOCAL,
        LaneProfile.CLAUDE_AGENT_SDK,
        LaneProfile.CODEX,
        LaneProfile.CURSOR_CLOUD,
        LaneProfile.CLAUDE_CLOUD,
        LaneProfile.CODEX_CLOUD,
    }
)


class ReadinessLevel(StrEnum):
    """SPEC-01 section 8: how far a lane's environment is proven, in order."""

    DECLARED = "declared"
    RENDERED = "rendered"
    DELIVERED = "delivered"
    PREPARED = "prepared"
    DISCOVERED = "discovered"
    EXERCISED = "exercised"

    def at_least(self, other: ReadinessLevel) -> bool:
        order = list(ReadinessLevel)
        return order.index(self) >= order.index(other)


class KitHostSupport(StrEnum):
    """The kit manifest's per-host vocabulary (SPEC-01 section 2)."""

    FULL = "full"
    BASE_VIA_OWNER = "base_via_owner"
    UNSUPPORTED = "unsupported"


# `local` in a kit manifest covers the worker-hosted lanes, each of which runs the bootstrap
# entrypoint in its prepare step; Deep Agents is governed by its sandbox profile and never
# takes a kit.
LOCAL_PROFILES: Final = (LaneProfile.CURSOR_LOCAL, LaneProfile.CLAUDE_AGENT_SDK, LaneProfile.CODEX)
_HOST_KEYS: Final = frozenset({"local", *(profile.value for profile in HOSTED_PROFILES)})
# Hosts whose base layer Mission Control itself installs: the worker, and cursor_cloud through
# its environments API (SPEC-01 section 7 `sync`). Other hosted profiles are `generate` only.
_FULL_HOST_KEYS: Final = frozenset({"local", LaneProfile.CURSOR_CLOUD.value})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _safe_relative(path: str) -> str:
    normalized = normalize_bundle_path(path)
    if not _SAFE_PATH.fullmatch(normalized):
        raise ValueError(f"kit paths use [A-Za-z0-9._/-] only: {path!r}")
    return normalized


class _KitShellLine(_Strict):
    name: str = Field(pattern=_NAME)
    run: str = Field(min_length=1, max_length=4_096)

    @field_validator("run")
    @classmethod
    def _one_line(cls, value: str) -> str:
        if "\n" in value or "\r" in value or "\x00" in value:
            raise ValueError("a kit command is one shell line")
        return value


class KitCommand(_KitShellLine):
    """One mission-layer health check."""


# A sibling of KitCommand rather than a subclass, so a field declared as a health check never
# holds a step and its dump and digest follow the declared type.
class KitStep(_KitShellLine):
    """One mission-layer step; ``when`` is ``exists('<path>')`` or ``!exists('<path>')``."""

    when: str | None = None

    @field_validator("when")
    @classmethod
    def _closed_condition(cls, value: str | None) -> str | None:
        if value is None:
            return None
        match = _WHEN.fullmatch(value.strip())
        if match is None:
            raise ValueError("a step condition is exists('<path>') or !exists('<path>')")
        _safe_relative(match["path"])
        return value.strip()


class KitService(_Strict):
    name: str = Field(pattern=_NAME)
    start: str = Field(min_length=1)
    health: str = Field(min_length=1)

    @field_validator("start", "health")
    @classmethod
    def _bundle_path(cls, value: str) -> str:
        return _safe_relative(value)


class KitBase(_Strict):
    """The base layer: a base install script and long-lived services, as bundle paths."""

    install: str | None = None
    services: tuple[KitService, ...] = ()

    @field_validator("install")
    @classmethod
    def _bundle_path(cls, value: str | None) -> str | None:
        return None if value is None else _safe_relative(value)


class KitMission(_Strict):
    steps: tuple[KitStep, ...] = ()
    health: tuple[KitCommand, ...] = ()
    timeout_s: int = Field(default=480, ge=1, le=3_600)

    @model_validator(mode="after")
    def _unique_names(self) -> KitMission:
        for label, items in (("step", self.steps), ("health check", self.health)):
            names = [item.name for item in items]
            if len(names) != len(set(names)):
                raise ValueError(f"kit {label} names must be unique")
        return self


class EnvironmentKitManifest(_Strict):
    """``mc.environment_kit.v1``: the ``kit.json`` of an Environment Kit bundle."""

    schema_version: Literal["mc.environment_kit.v1"] = ENVIRONMENT_KIT_SCHEMA
    id: str = Field(pattern=r"^envkit\.[a-z0-9][a-z0-9-]*$")
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
    title: str = Field(min_length=1)
    description: str = Field(min_length=1, max_length=1_024)
    toolchains: dict[str, str] = Field(default_factory=dict)
    system_packages: tuple[str, ...] = ()
    base: KitBase = Field(default_factory=KitBase)
    mission: KitMission = Field(default_factory=KitMission)
    requires: KitRequirements = Field(default_factory=KitRequirements)
    host_support: dict[str, KitHostSupport] = Field(default_factory=dict)

    @field_validator("requires", mode="before")
    @classmethod
    def _requires_block(cls, value: object) -> object:
        # The authored block spells optional secrets `NAME?` (SPEC-01 section 2).
        if isinstance(value, Mapping) and any(
            isinstance(item, str) for item in value.get("secrets", ())
        ):
            return KitRequirements.from_requires(value)
        return value

    @field_validator("toolchains")
    @classmethod
    def _known_toolchains(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = sorted(set(value) - set(TOOLCHAIN_PROBES))
        if unknown:
            raise ValueError(f"unknown toolchain(s): {', '.join(unknown)}")
        for name, version in value.items():
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", version):
                raise ValueError(f"invalid {name} version: {version!r}")
        return value

    @field_validator("system_packages")
    @classmethod
    def _package_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for name in value:
            if not re.fullmatch(r"[a-z0-9][a-z0-9.+-]*", name):
                raise ValueError(f"invalid system package name: {name!r}")
        return value

    @field_validator("host_support")
    @classmethod
    def _host_keys(cls, value: dict[str, KitHostSupport]) -> dict[str, KitHostSupport]:
        unknown = sorted(set(value) - _HOST_KEYS)
        if unknown:
            raise ValueError(f"unknown kit host(s): {', '.join(unknown)}")
        if value.get("local") == KitHostSupport.BASE_VIA_OWNER:
            raise ValueError("local lanes install the base layer in the worker, never via owner")
        synced = sorted(
            key
            for key, support in value.items()
            if support == KitHostSupport.FULL and key not in _FULL_HOST_KEYS
        )
        if synced:
            raise ValueError(
                f"Mission Control installs no base layer on {', '.join(synced)} "
                "(SPEC-01 section 7: sync is cursor_cloud only); use base_via_owner"
            )
        return value

    @property
    def secret_names(self) -> tuple[str, ...]:
        return tuple(secret.name for secret in self.requires.secrets)

    def capability_host_support(self) -> CapabilityHostSupport:
        """The catalog matrix. Local ``full`` is ``supported`` on every ``LOCAL_PROFILES`` lane,
        whose prepare step runs the entrypoint; a hosted host is ``unqualified`` until its route
        is proven (Q-C1, Q-L1, Q-X1 for the hosted base layers) and names who installs the base
        layer in its overlay."""

        profiles: dict[LaneProfile, HostProfileSupport] = {}
        if self.host_support.get("local") == KitHostSupport.FULL:
            for profile in LOCAL_PROFILES:
                profiles[profile] = HostProfileSupport(status=HostSupportStatus.SUPPORTED)
        for key, support in self.host_support.items():
            if key == "local" or support == KitHostSupport.UNSUPPORTED:
                continue
            installer = "mission_control" if support == KitHostSupport.FULL else "owner"
            profiles[LaneProfile(key)] = HostProfileSupport(
                status=HostSupportStatus.UNQUALIFIED,
                overlay={BASE_LAYER_OVERLAY: installer},
            )
        return CapabilityHostSupport(profiles=profiles)

    def canonical_json(self) -> bytes:
        return json.dumps(
            stable_json_dump(self), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")


# --- rendering ------------------------------------------------------------------------------


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _condition(when: str | None) -> str:
    if when is None:
        return "true"
    match = _WHEN.fullmatch(when)
    assert match is not None  # validated by KitStep
    test = f"[ -e {_quote(match['path'])} ]"
    return f"! {test}" if match["negate"] else test


_PREAMBLE: Final = """\
#!/usr/bin/env bash
# Mission layer rendered by Mission Control from {pin} ({schema}).
# Bootstrap entrypoint: bash .mission/setup/run [--phase prepare|start]
# Idempotent and bounded ({timeout_s} s); writes .mission/setup/receipt.json ({receipt_schema}).
# It names variables only and never contains a secret value. Do not edit: re-rendered per run.
set -u
phase=prepare
if [ "${{1:-}}" = "--phase" ] && [ -n "${{2:-}}" ]; then phase="$2"; fi
case "$phase" in prepare|start) ;; *) echo "unknown phase: $phase" >&2; exit 2 ;; esac
cd "$(dirname "$0")/../.." || exit 2
started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
deadline=$(( $(date +%s) + {timeout_s} ))
outcome=prepared
steps=""
health=""
toolchains=""

mc_remaining() {{ echo $(( deadline - $(date +%s) )); }}

mc_exec() {{
    left=$(mc_remaining)
    if [ "$left" -le 0 ]; then return 124; fi
    if command -v timeout >/dev/null 2>&1; then
        timeout "$left" bash -c "$1"
    else
        bash -c "$1"
    fi
}}

mc_step() {{
    status=ran
    code=0
    if [ "$outcome" = timed_out ]; then
        status=timed_out
    elif [ "$2" = skip ]; then
        status=skipped
    else
        mc_exec "$3"
        code=$?
        if [ "$code" -eq 124 ]; then status=timed_out; outcome=timed_out
        elif [ "$code" -ne 0 ] && [ "$outcome" = prepared ]; then outcome=failed
        fi
    fi
    steps="$steps${{steps:+,}}{{\\"name\\":\\"$1\\",\\"status\\":\\"$status\\",\\"exit_code\\":$code}}"
}}

mc_health() {{
    code=124
    if [ "$outcome" != timed_out ]; then mc_exec "$2"; code=$?; fi
    if [ "$code" -ne 0 ] && [ "$outcome" = prepared ]; then outcome=failed; fi
    health="$health${{health:+,}}{{\\"name\\":\\"$1\\",\\"exit_code\\":$code}}"
}}

mc_toolchain() {{
    observed=$(bash -c "$3" 2>/dev/null | head -n 1 | tr -cd 'A-Za-z0-9 ._+-')
    entry="\\"name\\":\\"$1\\",\\"declared\\":\\"$2\\",\\"observed\\":\\"$observed\\""
    toolchains="$toolchains${{toolchains:+,}}{{$entry}}"
}}
"""

_EPILOGUE: Final = """
finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
receipt=.mission/setup/receipt.json
head='"schema_version":"{receipt_schema}","kit_pin":"{pin}"'
run='"phase":"%s","outcome":"%s","started_at":"%s","finished_at":"%s"'
results='"steps":[%s],"health":[%s],"toolchains":[%s]'
printf "{{$head,$run,$results}}\\n" "$phase" "$outcome" "$started_at" "$finished_at" \\
    "$steps" "$health" "$toolchains" > "$receipt.tmp" && mv "$receipt.tmp" "$receipt"
[ "$outcome" = prepared ]
"""


class RenderedMissionLayer(_Strict):
    """The mission-layer files a kit pin renders, and the digest of the entrypoint script."""

    kit_pin: str
    files: dict[str, str]
    setup_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @property
    def run_script(self) -> str:
        return self.files[MISSION_SETUP_RUN]


def render_mission_layer(kit: EnvironmentKitManifest, *, pin: str) -> RenderedMissionLayer:
    """``.mission/setup/run`` and ``.mission/setup/kit.json`` for one exact kit pin."""

    pin = CapabilityPin.parse(pin).render()
    lines = [
        _PREAMBLE.format(
            pin=pin,
            schema=ENVIRONMENT_KIT_SCHEMA,
            timeout_s=kit.mission.timeout_s,
            receipt_schema=MISSION_SETUP_RECEIPT_SCHEMA,
        )
    ]
    for step in kit.mission.steps:
        lines.append(
            f"if {_condition(step.when)}; then mc_step {step.name} run {_quote(step.run)}; "
            f"else mc_step {step.name} skip ''; fi"
        )
    for check in kit.mission.health:
        lines.append(f"mc_health {check.name} {_quote(check.run)}")
    for name, version in sorted(kit.toolchains.items()):
        lines.append(f"mc_toolchain {name} {_quote(version)} {_quote(TOOLCHAIN_PROBES[name])}")
    lines.append(_EPILOGUE.format(receipt_schema=MISSION_SETUP_RECEIPT_SCHEMA, pin=pin))
    script = "\n".join(lines)
    record = json.dumps(
        {"kit_pin": pin, "kit": stable_json_dump(kit)},
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
    )
    return RenderedMissionLayer(
        kit_pin=pin,
        files={MISSION_SETUP_RUN: script, MISSION_SETUP_KIT: record + "\n"},
        setup_digest="sha256:" + sha256_hex(script.encode("utf-8")),
    )


def entrypoint_command(profile: LaneProfile, *, phase: SetupPhase = "start") -> str:
    """The guarded shell line a lane's base layer runs (SPEC-01 section 1).

    It runs the mission layer only when the mission branch carries one, so a base layer that
    serves every mission stays valid for missions without a kit.
    """

    if profile not in ENTRYPOINT_PROFILES:
        raise ValueError(f"{profile.value} has no bootstrap entrypoint")
    command = f"if [ -f {MISSION_SETUP_RUN} ]; then bash {MISSION_SETUP_RUN} --phase {phase}; fi"
    if profile == LaneProfile.CLAUDE_CLOUD:
        return f'[ "$CLAUDE_CODE_REMOTE" = "true" ] || exit 0; {command}'
    return command


# --- receipt --------------------------------------------------------------------------------


class SetupStepResult(_Strict):
    name: str = Field(pattern=_NAME)
    status: Literal["ran", "skipped", "timed_out"]
    exit_code: int


class SetupHealthResult(_Strict):
    name: str = Field(pattern=_NAME)
    exit_code: int

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


class ToolchainObservation(_Strict):
    name: str
    declared: str
    observed: str


class MissionSetupReceipt(_Strict):
    """``mc.mission_setup_receipt.v1``: what ``.mission/setup/run`` did, written by the script."""

    schema_version: Literal["mc.mission_setup_receipt.v1"] = MISSION_SETUP_RECEIPT_SCHEMA
    kit_pin: str
    phase: SetupPhase
    outcome: Literal["prepared", "failed", "timed_out"]
    started_at: AwareDatetime
    finished_at: AwareDatetime
    steps: tuple[SetupStepResult, ...] = ()
    health: tuple[SetupHealthResult, ...] = ()
    toolchains: tuple[ToolchainObservation, ...] = ()

    @classmethod
    def parse(cls, content: bytes) -> MissionSetupReceipt:
        return cls.model_validate(json.loads(content.decode("utf-8")))

    @property
    def failures(self) -> tuple[str, ...]:
        failed = [
            f"step {step.name} {step.status} (exit {step.exit_code})"
            for step in self.steps
            if step.status == "timed_out" or (step.status == "ran" and step.exit_code != 0)
        ]
        failed += [
            f"health {item.name} (exit {item.exit_code})" for item in self.health if not item.passed
        ]
        return tuple(failed)


def receipt_readiness(
    receipt: MissionSetupReceipt | None, *, kit_pin: str
) -> tuple[ReadinessLevel, tuple[str, ...]]:
    """Readiness a receipt proves for ``kit_pin`` and the reasons it proves no more.

    Delivered files without a receipt stay ``delivered``; a receipt for another kit, or one
    whose steps or health checks failed, never reaches ``prepared``.
    """

    if receipt is None:
        return ReadinessLevel.DELIVERED, ("no .mission/setup/receipt.json was written",)
    if receipt.kit_pin != kit_pin:
        return ReadinessLevel.DELIVERED, (f"the receipt is for {receipt.kit_pin}, not {kit_pin}",)
    failures = receipt.failures
    if receipt.outcome != "prepared" or failures:
        return ReadinessLevel.DELIVERED, (f"setup {receipt.outcome}", *failures)
    return ReadinessLevel.PREPARED, ()


__all__ = [
    "BASE_LAYER_OVERLAY",
    "ENTRYPOINT_PROFILES",
    "ENVIRONMENT_KIT_SCHEMA",
    "KIT_MANIFEST_PATH",
    "LOCAL_PROFILES",
    "MISSION_SETUP_KIT",
    "MISSION_SETUP_RECEIPT",
    "MISSION_SETUP_RECEIPT_SCHEMA",
    "MISSION_SETUP_RUN",
    "TOOLCHAIN_PROBES",
    "EnvironmentKitManifest",
    "KitBase",
    "KitCommand",
    "KitHostSupport",
    "KitMission",
    "KitService",
    "KitStep",
    "MissionSetupReceipt",
    "ReadinessLevel",
    "RenderedMissionLayer",
    "SetupHealthResult",
    "SetupPhase",
    "SetupStepResult",
    "ToolchainObservation",
    "entrypoint_command",
    "receipt_readiness",
    "render_mission_layer",
]
