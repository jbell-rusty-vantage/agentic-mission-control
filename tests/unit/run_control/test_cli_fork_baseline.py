"""Tracing Stage 2 (F-S2-10): `missionctl run fork --baseline-reservation DIM=AMOUNT`.

The derived run's launch input must carry the baseline its admission reserved
(`run_launch` refuses `budget_mismatch`), and the owner's fork command could not name one.
Tracing Stage 3 (owner decision 2026-10-22, "default to source"): without the flag the body
names no baseline and the fork service holds the source run's admitted baseline
(`tests/unit/recovery/test_precise_fork.py`); each flag overrides one dimension.
"""

from __future__ import annotations

import argparse
from typing import Any

import pytest

from mission_control.interfaces.cli.main import fork_body


def args(**values: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "fork_request_id": "fork-1",
        "from_snapshot": "run-snapshot:1",
        "instruction_file": None,
        "inject_file": None,
        "at": "stage:S2,cycle:2",
        "frontier": None,
        "frontier_policy": None,
        "sponsorship_ref": "sponsorship:test",
        "approval_refs": None,
        "reason": None,
        "baseline_reservations": None,
    }
    return argparse.Namespace(**{**defaults, **values})


def test_the_fork_flags_carry_the_baseline_reservation() -> None:
    body = fork_body(args(baseline_reservations=["tokens.total=40", "model.turns=2"]), None)
    assert body["baseline_reservations"] == {"tokens.total": 40, "model.turns": 2}
    assert body["at"] == {"stage": "S2", "cycle": 2}
    # Without the flag the server defaults to the source baseline: the body names none.
    assert "baseline_reservations" not in fork_body(args(), None)
    # A request file's baseline is kept, and a flag overrides its dimension.
    filed = fork_body(
        args(baseline_reservations=["tokens.total=5"]),
        {"baseline_reservations": {"tokens.total": 40, "model.turns": 2}},
    )
    assert filed["baseline_reservations"] == {"tokens.total": 5, "model.turns": 2}


def test_a_malformed_baseline_is_refused() -> None:
    with pytest.raises(ValueError, match="DIMENSION=AMOUNT"):
        fork_body(args(baseline_reservations=["tokens.total"]), None)
