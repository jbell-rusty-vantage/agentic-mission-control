"""MO-12 for every worker-hosted lane: an Environment Kit's mission layer runs in the leased
worktree at `prepare`, before the provider starts, and a kit that does not reach `prepared`
refuses the session.

One scenario parametrized by lane replaces the per-lane copies that sat in
`tests/unit/{claude,codex,cursor}/`. The mission layer runs under the host's real bash, with the
lane's allowlisted environment; the provider is each lane's FIXTURE (the Claude SDK client, the
Codex app-server launcher, the Cursor replay bridge), which `prepare` never starts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from mission_control.adapters.claude.harness import ClaudeLaneError
from mission_control.adapters.cursor.projection import LaneProjectionError
from mission_control.application.environments.mission_layer import (
    ENVIRONMENT_NOT_PREPARED,
    MissionLayerService,
)
from mission_control.application.execution.harness.lane_turns import (
    LaneExecutionIdentity,
    harness_scope,
)
from mission_control.application.execution.harness.protocol import AgentHarness
from mission_control.domain.authoring.environment_kits import (
    MISSION_SETUP_RECEIPT,
    MissionSetupReceipt,
)
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lanes import PreparedSession, PrepareRequest
from tests.fixtures.cursor_controls import started_session
from tests.fixtures.environment_kits import (
    BASH,
    kit_document,
    kit_pin,
    mission_layer_service,
    published_kit,
    setup_environ,
)
from tests.support.providers import claude, codex, cursor

pytestmark = pytest.mark.skipif(BASH is None, reason="the mission layer runs under bash")

# A worker-only variable the lane's allowlist must keep out of the setup child.
WORKER_ONLY = {"MC_WORKER_ONLY_DSN": "postgresql://worker-only"}


@dataclass
class KitLane:
    """One lane's harness over its fixture provider, with a kit pinned by its binding."""

    profile: str
    harness: AgentHarness
    operation: OperationExecutionRequest
    lease_root: Callable[[str], Path]
    provider_started: Callable[[], bool]
    refusal: type[Exception]

    def request(self) -> PrepareRequest:
        operation = self.operation
        heid = str(LaneExecutionIdentity.of(operation, self.profile, 1).harness_execution_id)
        return PrepareRequest(
            scope=harness_scope(operation.request_scope),
            lane_profile=self.profile,
            harness_execution_id=heid,
            binding_digest=operation.effective_configuration_digest,
            idempotency_key=f"{heid}:1:prepare",
            generation=1,
            run_id=operation.identity.run_id,
            operation_id=operation.identity.operation_id,
            attempt_no=1,
        )

    async def prepare(self) -> tuple[PreparedSession, Path]:
        request = self.request()
        self.harness.stage(request.harness_execution_id, self.operation)  # type: ignore[attr-defined]
        prepared = await self.harness.prepare(request)
        return prepared, self.lease_root(request.harness_execution_id)


def _claude(tmp_path: Path, pin: str, mission_layer: MissionLayerService | None) -> KitLane:
    binding = claude.claude_binding(
        materialization_digest=claude.materialization_digest_for(claude.base_operation()),
        environment={
            "kind": "local_workspace",
            "host_profile": "worker.linux.default",
            "setup_pin": pin,
        },
    )
    stack = claude.claude_stack(
        tmp_path,
        operation=claude.claude_operation(binding=binding),
        environ=setup_environ(**WORKER_ONLY),
        mission_layer=mission_layer,
    )
    return KitLane(
        profile=claude.PROFILE,
        harness=stack.harness,
        operation=stack.operation,
        lease_root=lambda _heid: Path(next(iter(stack.workspace.registry.values())).path),
        provider_started=lambda: bool(stack.factory.clients),
        refusal=ClaudeLaneError,
    )


def _codex(tmp_path: Path, pin: str, mission_layer: MissionLayerService | None) -> KitLane:
    operation = codex.codex_operation(
        codex.codex_binding(
            environment={
                "kind": "local_workspace",
                "host_profile": "worker.linux.wsl",
                "setup_pin": pin,
            }
        )
    )
    launcher = codex.FixtureLauncher()
    harness, *_ = codex.build_harness(
        tmp_path,
        launcher,
        settings=codex.fixture_settings(tmp_path, worker_environ=setup_environ(**WORKER_ONLY)),
        mission_layer=mission_layer,
    )

    def lease_root(_heid: str) -> Path:
        (root,) = (path for path in (tmp_path / "leases").iterdir() if path.is_dir())
        return root

    return KitLane(
        profile=codex.PROFILE,
        harness=harness,
        operation=operation,
        lease_root=lease_root,
        provider_started=lambda: bool(launcher.launches),
        refusal=LaneProjectionError,
    )


def _cursor(tmp_path: Path, pin: str, mission_layer: MissionLayerService | None) -> KitLane:
    stack = cursor.local_stack(
        tmp_path,
        binding_changes={"setup_pin": pin},
        settings_changes={"worker_environ": setup_environ(**WORKER_ONLY)},
        mission_layer=mission_layer,
    )
    return KitLane(
        profile="cursor_local",
        harness=stack.harness,
        operation=stack.operation,
        lease_root=lambda heid: Path(stack.harness.lease_path(heid)),
        provider_started=lambda: bool(stack.launcher.launches),
        refusal=LaneProjectionError,
    )


LANES = {"claude_agent_sdk": _claude, "codex": _codex, "cursor_local": _cursor}
# The lanes whose second `prepare` in one generation returns the session already prepared;
# `cursor_local` prepares again (it was never claimed for that lane).
IDEMPOTENT_PREPARE = ("claude_agent_sdk", "codex")


@pytest.mark.parametrize("profile", sorted(LANES))
async def test_prepare_runs_the_mission_layer_before_the_provider_starts(
    profile: str, tmp_path: Path
) -> None:
    published = published_kit(
        kit_document(
            mission={
                "steps": [{"name": "marker", "run": "echo ready > marker.txt"}],
                # The setup child sees the lane's allowlist, never the worker's own variables.
                "health": [{"name": "allowlist", "run": 'test -z "${MC_WORKER_ONLY_DSN:-}"'}],
                "timeout_s": 60,
            }
        )
    )
    pin = kit_pin(published)
    lane = LANES[profile](tmp_path, pin, mission_layer_service(published))

    prepared, root = await lane.prepare()

    receipt = MissionSetupReceipt.parse((root / MISSION_SETUP_RECEIPT).read_bytes())
    assert receipt.kit_pin == pin and receipt.outcome == "prepared"
    assert [(check.name, check.passed) for check in receipt.health] == [("allowlist", True)]
    assert (root / "marker.txt").is_file()
    assert prepared.projection_digests["setup_receipt_digest"].startswith("sha256:")
    assert not lane.provider_started(), "the mission layer runs before the provider starts"
    if profile in IDEMPOTENT_PREPARE:
        assert await lane.harness.prepare(lane.request()) == prepared


@pytest.mark.parametrize("profile", sorted(LANES))
async def test_a_kit_that_is_not_prepared_refuses_the_session(profile: str, tmp_path: Path) -> None:
    failing = published_kit(
        kit_document(mission={"steps": [{"name": "broken", "run": "exit 3"}], "timeout_s": 30})
    )
    lane = LANES[profile](tmp_path, kit_pin(failing), mission_layer_service(failing))
    with pytest.raises(lane.refusal) as raised:
        await lane.prepare()
    assert raised.value.code == ENVIRONMENT_NOT_PREPARED  # type: ignore[attr-defined]
    assert "step broken ran (exit 3)" in str(raised.value)
    assert not lane.provider_started()


@pytest.mark.parametrize("profile", sorted(LANES))
async def test_a_pinned_kit_without_a_mission_layer_service_is_refused(
    profile: str, tmp_path: Path
) -> None:
    lane = LANES[profile](tmp_path, kit_pin(published_kit()), None)
    with pytest.raises(lane.refusal) as raised:
        await lane.prepare()
    assert raised.value.code == ENVIRONMENT_NOT_PREPARED  # type: ignore[attr-defined]


async def test_a_cursor_binding_without_a_kit_starts_without_a_mission_layer(
    tmp_path: Path,
) -> None:
    stack = cursor.local_stack(tmp_path)
    heid, _ = await started_session(stack)
    root = Path(stack.harness.lease_path(heid))
    assert not (root / MISSION_SETUP_RECEIPT).exists()
    assert stack.launcher.launches
