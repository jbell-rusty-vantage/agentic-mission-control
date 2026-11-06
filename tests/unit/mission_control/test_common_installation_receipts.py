"""Readiness accepts an installation upgraded in place (receipts of earlier releases)."""

from __future__ import annotations

import pytest

from mission_control.bootstrap.common_installation import receipts_belong_to_release


@pytest.mark.parametrize(
    ("receipts", "required", "accepted"),
    [
        ({"1.1.0"}, "1.1.0", True),
        # 1.0.0 applied 0001..0024, the 1.1.0 upgrade applied 0025..0030.
        ({"1.0.0", "1.1.0"}, "1.1.0", True),
        # A release without new migrations is attested without receipts of its own.
        ({"1.0.0"}, "1.0.1", True),
        # Receipts of a newer release than the binding pins are not this release.
        ({"1.0.0", "1.1.0"}, "1.0.0", False),
        ({"2.0.0"}, "1.1.0", False),
        ({"1.1.0", "unlabelled"}, "1.1.0", False),
        # Non-semantic (fixture) versions match exactly.
        ({"parity-1"}, "parity-1", True),
        ({"parity-1", "parity-0"}, "parity-1", False),
    ],
)
def test_receipts_belong_to_the_pinned_release(
    receipts: set[str], required: str, accepted: bool
) -> None:
    assert receipts_belong_to_release(receipts, required) is accepted


def test_a_release_missing_a_migration_this_build_reads_is_named() -> None:
    # W1 D33: the worker composed against 1.9.0 and failed only inside activities.
    from mission_control.bootstrap.common_installation import (
        REQUIRED_MIGRATIONS,
        missing_required_migrations,
    )

    assert missing_required_migrations(REQUIRED_MIGRATIONS) == ()
    keys = set(REQUIRED_MIGRATIONS) - {"0072_native_plan_decisions"}
    assert missing_required_migrations(keys) == ("0072_native_plan_decisions",)


def test_every_required_migration_ships_in_the_newest_built_release() -> None:
    import json
    from pathlib import Path

    from mission_control.bootstrap.common_installation import REQUIRED_MIGRATIONS

    releases = Path(__file__).resolve().parents[3] / "packages/mission-control-db-contract/releases"
    built = sorted(
        (p for p in releases.iterdir() if (p / "component/manifest.json").is_file()),
        key=lambda p: tuple(int(x) for x in p.name.split(".")),
    )
    manifest = json.loads((built[-1] / "component/manifest.json").read_bytes())
    shipped = {Path(item["path"]).stem for item in manifest["ordered_migrations"]}
    assert shipped >= REQUIRED_MIGRATIONS
