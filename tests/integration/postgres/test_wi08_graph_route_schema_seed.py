"""OVE-171 / WI-08: the W2 graph-variant schema seed `mc.catalog.artifact-schemas@1.0.1` on a real
disposable installation: pending until applied, applied once as a pure addition after 1.0.0 (whose
row stays byte-identical), then an idempotent replay; changed bytes under 1.0.1 conflict."""

from __future__ import annotations

import copy

import pytest

from mission_control_db_contract.errors import ContractError
from mission_control_db_contract.seeds import load_bundles, validate_bundle
from tests.integration.postgres.test_ai_engineer_report_schema_seed import (
    RELEASE_142,
    SEEDS,
    apply,
    catalog_counts,
    ident,
    plan,
    published,
    receipts,
    s0_row,
)
from tests.integration.postgres.test_capability_bundles_publish import SYNTHETIC_STORAGE
from tests.integration.postgres.test_run2_release_141 import disposable, install, release_at

NEW_KEY = ("mc.catalog.artifact-schemas", "1.0.1")
pytestmark = pytest.mark.common_db


@pytest.mark.asyncio
async def test_the_successor_schema_seed_applies_additively_and_replays(tmp_path):
    release = release_at(RELEASE_142, tmp_path / "lock-142", "ai-engineer")
    everything = load_bundles([SEEDS / "common", SEEDS / "ai-engineer"])
    (new,) = [bundle for bundle in everything if ident(bundle) == NEW_KEY]
    prior = [bundle for bundle in everything if ident(bundle) != NEW_KEY]
    assert set(published(new)) == {
        "schema.w2-triage-verdict",
        "schema.w2-scan-flag",
        "schema.w2-critique-verdict",
    }
    async with disposable(tmp_path, "ai-engineer") as (target, connection):
        await install(target, release)
        await connection.execute(SYNTHETIC_STORAGE)
        assert set((await apply(target, release, prior)).values()) == {"applied"}
        before_counts, before_receipts = (
            await catalog_counts(connection),
            await receipts(connection),
        )
        before_s0 = await s0_row(connection)

        assert (await plan(target, release, [new]))[NEW_KEY] == "pending"
        assert (await apply(target, release, [new]))[NEW_KEY] == "applied"
        delta = {k: v - before_counts[k] for k, v in (await catalog_counts(connection)).items()}
        assert delta == {
            "asset_version": 3,
            "asset_decision": 3,
            "seed_identity": 6,
            "installation_seed_receipt": 1,
        }
        after = await receipts(connection)
        receipt = after.pop(NEW_KEY)
        assert after == before_receipts and receipt[0] == new["seed_digest"]
        assert await s0_row(connection) == before_s0  # 1.0.0 untouched

        settled = await catalog_counts(connection)
        assert (await apply(target, release, [new]))[NEW_KEY] == "replay"
        assert await catalog_counts(connection) == settled

        drifted = copy.deepcopy({k: v for k, v in new.items() if k != "seed_digest"})
        drifted["records"][0]["fields"]["manifest"]["definition"]["description"] += " (edited)"
        drifted = validate_bundle(drifted)
        assert (await plan(target, release, [drifted]))[NEW_KEY] == "conflict"
        with pytest.raises(ContractError, match="different digest"):
            await apply(target, release, [drifted])
        assert await catalog_counts(connection) == settled
