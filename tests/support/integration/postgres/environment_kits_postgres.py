"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_environment_kits_postgres.py.
"""

from __future__ import annotations

from mission_control_db_contract.seeds import load_bundles, order_bundles
from tests.support.db import CommonDatabase
from tests.support.db_builders import SEEDS, apply_seed_bundle


async def _seed(database: CommonDatabase) -> None:
    bundles = [
        bundle
        for bundle in order_bundles(load_bundles([SEEDS / "common", SEEDS / "biotech"]), set())
        if not any(record["kind"].startswith("storage_") for record in bundle["records"])
    ]
    for bundle in bundles:
        await apply_seed_bundle(database, bundle)
