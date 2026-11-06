"""The Codex lane package's registrations (ADR-0063; OC-R3, OC-D199).

`codex` and `codex_cloud` register with the describe-only compile
(`application/resolution/describe_only.py`): the resolution seam admits a configuration against
their declarations (`describe.py`), while `manifest_launch_inputs.provider_node` and the lane's
projection writer still build the `mc.execution_binding.v2` the harness executes. The full
compile adapter comes with the provider sweep. Bootstrap composition registers `LANES`;
nothing else names them.
"""

from __future__ import annotations

from typing import Final

from mission_control.adapters.codex.describe import CODEX_CLOUD_DECLARATION, CODEX_DECLARATION
from mission_control.application.resolution.describe_only import describe_only_registration
from mission_control.application.resolution.ports import LaneRegistration

LANES: Final[tuple[LaneRegistration, ...]] = (
    describe_only_registration(CODEX_DECLARATION),
    describe_only_registration(CODEX_CLOUD_DECLARATION),
)

__all__ = ["LANES"]
