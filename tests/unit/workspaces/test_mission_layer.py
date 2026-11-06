"""MO-12: the mission layer: rendering, the bootstrap entrypoint, the receipt and readiness.

Every run here executes the rendered ``.mission/setup/run`` with the host's real bash.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.workspaces.mission_setup import resolve_bash
from mission_control.application.environments.kits import EnvironmentKitCatalog
from mission_control.application.environments.mission_layer import (
    EnvironmentNotPrepared,
    MissionLayerService,
    prepare_lane_environment,
)
from mission_control.application.execution.child_environment import provider_child_environment
from mission_control.domain.authoring.environment_kits import (
    MISSION_SETUP_KIT,
    MISSION_SETUP_RECEIPT,
    MISSION_SETUP_RUN,
    EnvironmentKitManifest,
    MissionSetupReceipt,
    ReadinessLevel,
    entrypoint_command,
    receipt_readiness,
    render_mission_layer,
)
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.bindings import EnvironmentBinding
from tests.fixtures.environment_kits import (
    BASH,
    StaticDefinitions,
    kit_document,
    kit_pin,
    mission_layer_service,
    published_kit,
    setup_environ,
)

pytestmark = pytest.mark.skipif(BASH is None, reason="the mission layer runs under bash")

PIN = "envkit.fixture@1#sha256:" + "a" * 64
SENTINEL = "sentinel-setup-secret"


def _kit(**changes: Any) -> EnvironmentKitManifest:
    return EnvironmentKitManifest.model_validate(kit_document(**changes))


def _mission(*steps: dict[str, Any], health: tuple[dict[str, Any], ...] = (), timeout_s: int = 60):
    return {"steps": list(steps), "health": list(health), "timeout_s": timeout_s}


def _binding(**changes: Any) -> EnvironmentBinding:
    return EnvironmentBinding(
        kind="local_workspace", host_profile="worker.linux.default", **changes
    )


class _Identity:
    request_scope = "mc/test/biotech/global"
    run_key = "run-mo12"
    activation_key = "unit-1"
    attempt_no = 1


def test_rendering_is_deterministic_names_no_value_and_records_the_kit() -> None:
    kit = _kit()
    first, second = render_mission_layer(kit, pin=PIN), render_mission_layer(kit, pin=PIN)
    assert first == second
    assert first.setup_digest.startswith("sha256:")
    assert set(first.files) == {MISSION_SETUP_RUN, MISSION_SETUP_KIT}
    script = first.run_script
    assert script.startswith("#!/usr/bin/env bash\n")
    assert PIN in script and "bounded (60 s)" in script
    assert "mc_step marker run 'echo ready > marker.txt'" in script
    assert "[ -e 'never.lock' ]" in script and "! [ -e 'marker.txt' ]" in script
    # Secret requirements are names the broker delivers at run time, never rendered.
    assert "FIXTURE_SETUP_TOKEN" not in script
    assert json.loads(first.files[MISSION_SETUP_KIT])["kit_pin"] == PIN
    assert render_mission_layer(_kit(), pin=PIN.replace("a" * 64, "b" * 64)) != first


def test_entrypoint_commands_run_the_mission_layer_only_when_present() -> None:
    cursor = entrypoint_command(LaneProfile.CURSOR_CLOUD)
    assert cursor == (
        "if [ -f .mission/setup/run ]; then bash .mission/setup/run --phase start; fi"
    )
    claude = entrypoint_command(LaneProfile.CLAUDE_CLOUD)
    assert claude.startswith('[ "$CLAUDE_CODE_REMOTE" = "true" ] || exit 0; ')
    assert entrypoint_command(LaneProfile.CODEX, phase="prepare").endswith("--phase prepare; fi")
    with pytest.raises(ValueError, match="no bootstrap entrypoint"):
        entrypoint_command(LaneProfile.DEEP_AGENTS)


async def test_a_local_prepare_reaches_prepared_with_a_receipt_and_is_idempotent(
    tmp_path: Path,
) -> None:
    published = published_kit(kit_document(toolchains={"git": "2"}))
    pin = kit_pin(published)
    service = mission_layer_service(published)

    outcome = await service.prepare(tmp_path, kit_pin=pin, environment=setup_environ())
    assert outcome.readiness == ReadinessLevel.PREPARED
    assert outcome.exit_code == 0 and outcome.reasons == ()
    receipt = outcome.receipt
    assert receipt is not None and receipt.kit_pin == pin and receipt.phase == "prepare"
    assert [(step.name, step.status, step.exit_code) for step in receipt.steps] == [
        ("marker", "ran", 0),
        ("lockfile", "skipped", 0),
    ]
    assert [(item.name, item.passed) for item in receipt.health] == [("marker", True)]
    (toolchain,) = receipt.toolchains
    assert (toolchain.name, toolchain.declared) == ("git", "2")
    assert outcome.digests() == {
        "setup_digest": outcome.setup_digest,
        "setup_receipt_digest": outcome.receipt_digest,
    }
    assert (tmp_path / "marker.txt").read_text().strip() == "ready"

    again = await service.prepare(tmp_path, kit_pin=pin, environment=setup_environ())
    assert again.readiness == ReadinessLevel.PREPARED
    assert again.setup_digest == outcome.setup_digest
    assert again.receipt is not None
    assert [step.status for step in again.receipt.steps] == ["skipped", "skipped"]


async def test_a_failing_step_or_health_check_stays_delivered(tmp_path: Path) -> None:
    published = published_kit(
        kit_document(
            mission=_mission(
                {"name": "broken", "run": "exit 3"},
                health=({"name": "absent", "run": "test -f nothing.txt"},),
            )
        )
    )
    outcome = await mission_layer_service(published).prepare(
        tmp_path, kit_pin=kit_pin(published), environment=setup_environ()
    )
    assert outcome.readiness == ReadinessLevel.DELIVERED
    assert outcome.exit_code != 0
    assert outcome.reasons == (
        "setup failed",
        "step broken ran (exit 3)",
        "health absent (exit 1)",
    )


async def test_the_kit_bound_stops_a_hanging_step(tmp_path: Path) -> None:
    published = published_kit(
        kit_document(
            mission=_mission(
                {"name": "hang", "run": "sleep 30"},
                {"name": "after", "run": "true"},
                timeout_s=1,
            )
        )
    )
    outcome = await mission_layer_service(published).prepare(
        tmp_path, kit_pin=kit_pin(published), environment=setup_environ()
    )
    assert outcome.readiness == ReadinessLevel.DELIVERED
    receipt = outcome.receipt
    assert receipt is not None and receipt.outcome == "timed_out"
    assert [step.status for step in receipt.steps] == ["timed_out", "timed_out"]


async def test_a_stale_or_foreign_receipt_never_proves_prepared(tmp_path: Path) -> None:
    published = published_kit()
    pin = kit_pin(published)
    await mission_layer_service(published).prepare(
        tmp_path, kit_pin=pin, environment=setup_environ()
    )
    receipt = MissionSetupReceipt.parse((tmp_path / MISSION_SETUP_RECEIPT).read_bytes())
    level, reasons = receipt_readiness(receipt, kit_pin="envkit.other@1#sha256:" + "c" * 64)
    assert level == ReadinessLevel.DELIVERED and "not envkit.other" in reasons[0]
    assert receipt_readiness(None, kit_pin=pin)[0] == ReadinessLevel.DELIVERED

    # A run that writes no receipt never inherits the previous run's.
    silent = published_kit(kit_document(id="envkit.silent", mission=_mission()))
    (tmp_path / MISSION_SETUP_RECEIPT).write_text(json.dumps(receipt.model_dump(mode="json")))

    class _NoRun:
        async def run(self, root: Path, **_: Any) -> int:
            return 0

    service = MissionLayerService(EnvironmentKitCatalog(StaticDefinitions(silent)), _NoRun())
    outcome = await service.prepare(tmp_path, kit_pin=kit_pin(silent), environment={})
    assert outcome.readiness == ReadinessLevel.DELIVERED
    assert outcome.receipt is None and outcome.reasons[0].startswith("no ")


async def test_a_lane_whose_binding_pins_a_kit_must_reach_prepared(tmp_path: Path) -> None:
    published = published_kit()
    pin = kit_pin(published)
    pinned = _binding(setup_pin=pin)

    async def prepare(service: Any, binding: EnvironmentBinding) -> Any:
        return await prepare_lane_environment(
            service,
            binding,
            tmp_path,
            identity=_Identity(),
            environ=setup_environ(OPENAI_API_KEY="sk-worker-only"),
            child_environment=provider_child_environment,
            secrets=None,
        )

    # No pin: nothing runs. A pin without a composed service is refused, never skipped.
    assert await prepare(None, _binding()) is None
    with pytest.raises(EnvironmentNotPrepared, match="no mission layer service"):
        await prepare(None, pinned)
    with pytest.raises(EnvironmentNotPrepared, match="is not published"):
        await prepare(mission_layer_service(), pinned)

    outcome = await prepare(mission_layer_service(published), pinned)
    assert outcome is not None and outcome.readiness == ReadinessLevel.PREPARED

    failing = published_kit(
        kit_document(id="envkit.failing", mission=_mission({"name": "x", "run": "false"}))
    )
    with pytest.raises(EnvironmentNotPrepared, match="reached delivered: setup failed"):
        await prepare(
            mission_layer_service(failing),
            _binding(setup_pin=kit_pin(failing)),
        )


async def test_the_setup_child_sees_the_allowlist_and_setup_secrets_only(tmp_path: Path) -> None:
    probe = (
        'if [ -n "${OPENAI_API_KEY:-}" ]; then exit 9; fi; test "${#FIXTURE_SETUP_TOKEN}" -eq 21'
    )
    published = published_kit(kit_document(mission=_mission({"name": "probe", "run": probe})))
    pin = kit_pin(published)

    class _Secrets:
        phases: list[str] = []

        async def environment(self, environment: Any, identity: Any, *, phase: str = "agent"):
            self.phases.append(phase)
            return type("Delivered", (), {"values": {"FIXTURE_SETUP_TOKEN": SENTINEL}})()

    secrets = _Secrets()
    outcome = await prepare_lane_environment(
        mission_layer_service(published),
        _binding(setup_pin=pin),
        tmp_path,
        identity=_Identity(),
        environ=setup_environ(OPENAI_API_KEY="sk-worker-only"),
        child_environment=provider_child_environment,
        secrets=secrets,  # type: ignore[arg-type]
    )
    assert outcome is not None and outcome.readiness == ReadinessLevel.PREPARED
    assert secrets.phases == ["setup"]
    # The value reached the step, never a delivered file.
    for relative in (MISSION_SETUP_RUN, MISSION_SETUP_KIT, MISSION_SETUP_RECEIPT):
        assert SENTINEL not in (tmp_path / relative).read_text(encoding="utf-8")


def test_bash_resolution_skips_the_windows_wsl_launcher(tmp_path: Path) -> None:
    git_bash = tmp_path / "Git" / "bin" / "bash.exe"
    git_bash.parent.mkdir(parents=True)
    git_bash.touch()
    paths = {
        "bash": r"C:\Windows\System32\bash.exe",
        "git": str(tmp_path / "Git" / "cmd" / "git.exe"),
    }
    assert resolve_bash(paths.get, windows=True) == str(git_bash)
    assert resolve_bash(paths.get, windows=False) == paths["bash"]
    assert resolve_bash({"bash": paths["bash"]}.get, windows=True) is None
    assert resolve_bash({"bash": str(git_bash)}.get, windows=True) == str(git_bash)
