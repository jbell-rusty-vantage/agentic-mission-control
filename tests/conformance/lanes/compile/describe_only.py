"""The lanes that register the describe-only compile (OC-R3, OC-D199; design D11).

Each lane package other than Deep Agents registers `describe_only_registration(declaration)`.
The suite still runs every check its compile can honestly pass (required-item refusal, vendor
routes, purity, the opaque port, item digests), and each lane declares one exception: describe
honesty at compile. A describe-only receipt restates the declaration, so it proves nothing about
materialization; that is proven where the lane materializes today, by its launch resolver and its
projection writer (moved into the lane package unchanged), cited per lane below.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from mission_control.application.resolution.ports import LaneAdapter, LaneRegistration
from mission_control.bootstrap.lanes import SESSION_LANES
from mission_control.domain.resolution.profiles import LaneDeclaration
from tests.conformance.lanes.compile.contract import CompileCheck
from tests.conformance.lanes.contract import DeclaredException

_REASON: Final = (
    "describe-only compile (OC-D199, design D11): its receipt restates the lane's declaration "
    "and materializes nothing; until the provider sweep gives the lane a full compile, the "
    "binding the lane executes is built by its launch resolver and rendered by its projection "
    "writer, and these suites prove what that path materializes"
)
_PROJECTION: Final = "tests/unit/agentic_components/test_host_projection.py"
_LAYOUTS: Final = "tests/unit/agentic_components/test_lane_layouts.py"
# The lane's projection writer, moved into its package unchanged (OC-R3).
_WRITERS: Final[Mapping[str, str]] = {
    "cursor_local": "src/mission_control/adapters/cursor/host_files.py",
    "cursor_cloud": "src/mission_control/adapters/cursor/host_files.py",
    "claude_agent_sdk": "src/mission_control/adapters/claude/host_files.py",
    "claude_cloud": "src/mission_control/adapters/claude/host_files.py",
    "codex": "src/mission_control/adapters/codex/host_files.py",
    "codex_cloud": "src/mission_control/adapters/codex/host_files.py",
    "claude_managed": "src/mission_control/adapters/remote_session/host_files.py",
    "codex_agents": "src/mission_control/adapters/remote_session/host_files.py",
}
_EVIDENCE: Final[Mapping[str, tuple[str, ...]]] = {
    "cursor_local": (
        _PROJECTION,
        "tests/unit/authoring/test_manifest_cursor_launch.py",
        "tests/unit/harness/test_cursor_local.py",
    ),
    "cursor_cloud": (
        _PROJECTION,
        "tests/unit/authoring/test_manifest_cursor_launch.py",
        "tests/unit/cursor/test_cloud_inline_options.py",
    ),
    "claude_agent_sdk": (
        _PROJECTION,
        "tests/unit/authoring/test_manifest_v2_launch.py",
        "tests/unit/harness/test_layered_local_lanes.py",
    ),
    "claude_cloud": (_PROJECTION, _LAYOUTS),
    "codex": (
        _PROJECTION,
        "tests/unit/authoring/test_manifest_v2_launch.py",
        "tests/unit/codex/test_kernel_hooks.py",
    ),
    "codex_cloud": (_PROJECTION, _LAYOUTS),
    "claude_managed": (
        "tests/unit/harness/test_hosted_agent_api_profiles.py",
        "tests/unit/authoring/test_hosted_launch_bindings.py",
    ),
    "codex_agents": (
        "tests/unit/harness/test_hosted_agent_api_profiles.py",
        "tests/unit/authoring/test_hosted_launch_bindings.py",
    ),
}


class DescribeOnlyCompileConformance:
    def __init__(self, registration: LaneRegistration) -> None:
        self._registration = registration

    @property
    def profile(self) -> str:
        return self._registration.profile

    def adapter(self) -> LaneAdapter:
        return self._registration.adapter

    def declaration(self) -> LaneDeclaration:
        return self._registration.declaration

    def options(self) -> Mapping[str, Any]:
        return {}

    @property
    def exceptions(self) -> Mapping[CompileCheck, DeclaredException]:
        return {
            CompileCheck.DESCRIBE_HONESTY: DeclaredException(
                reason=_REASON,
                evidence=(_WRITERS[self.profile], *_EVIDENCE[self.profile]),
            )
        }


DESCRIBE_ONLY_COMPILE_LANES: Final[tuple[DescribeOnlyCompileConformance, ...]] = tuple(
    DescribeOnlyCompileConformance(registration) for registration in SESSION_LANES.values()
)

__all__ = ["DESCRIBE_ONLY_COMPILE_LANES", "DescribeOnlyCompileConformance"]
