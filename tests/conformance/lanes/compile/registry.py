"""Every lane the compile suite runs. R1 registered the real Deep Agents compile; R3 registers
every other lane package with its describe-only compile and a declared exception (OC-D199).

`SUITE_PROBES` are not lanes: the narrow stub keeps every branch of the suite running (an
emulated vendor route, a degraded cell, kinds unsupported on a second declaration) until real
lanes exercise them. It borrows the `claude_agent_sdk` describe, so it is parametrized under a
probe id and kept out of the registered-lane checks.
"""

from __future__ import annotations

from typing import Any, Final

import pytest

from tests.conformance.lanes.compile.contract import CompileCheck, CompileConformance
from tests.conformance.lanes.compile.deep_agents import DeepAgentsCompileConformance
from tests.conformance.lanes.compile.describe_only import DESCRIBE_ONLY_COMPILE_LANES
from tests.conformance.lanes.compile.stub import NarrowStubCompileConformance

COMPILE_LANES: Final[tuple[CompileConformance, ...]] = (
    DeepAgentsCompileConformance(),
    *DESCRIBE_ONLY_COMPILE_LANES,
)
SUITE_PROBES: Final[tuple[CompileConformance, ...]] = (NarrowStubCompileConformance(),)


def compile_lanes(check: CompileCheck) -> list[Any]:
    return [
        *(
            pytest.param(lane, id=lane.profile)
            for lane in COMPILE_LANES
            if check not in lane.exceptions
        ),
        *(
            pytest.param(probe, id=f"probe-{probe.profile}")
            for probe in SUITE_PROBES
            if check not in probe.exceptions
        ),
    ]


__all__ = ["COMPILE_LANES", "SUITE_PROBES", "compile_lanes"]
