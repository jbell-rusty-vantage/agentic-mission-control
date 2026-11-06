"""The `codex_agents` lane package's registration (ADR-0063; OC-R3, OC-D199).

Registered with the describe-only compile (`application/resolution/describe_only.py`): the
resolution seam admits a configuration against the declaration (`describe.py`), while
`manifest_launch_inputs.provider_node` (hosted placement) and the hosted projection writer still
build the `mc.execution_binding.v2` the harness executes. The full compile adapter comes with
the provider sweep. Bootstrap composition registers `LANES`; nothing else names it.
"""

from __future__ import annotations

from typing import Final

from mission_control.adapters.openai_agents.describe import CODEX_AGENTS_DECLARATION
from mission_control.application.resolution.describe_only import describe_only_registration
from mission_control.application.resolution.ports import LaneRegistration

LANES: Final[tuple[LaneRegistration, ...]] = (describe_only_registration(CODEX_AGENTS_DECLARATION),)

__all__ = ["LANES"]
