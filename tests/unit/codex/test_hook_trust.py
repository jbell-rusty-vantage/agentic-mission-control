"""MO-03 / Q-X2: Codex hook trust records for the projected `.codex/hooks.json`.

The hash formula is pinned against what the real codex-cli 0.162.1 app-server reported through
`hooks/list` (RECORDED: `tests/fixtures/provider_frames/codex/hooks_list/trust-0.162.1.json`,
no login, no model turn): the golden codex projection and the normalization edges (short
`SessionEnd` timeouts, matchers Codex drops, `additionalContextLimit` defaults, `async`,
`statusMessage`). With Mission Control's records in the isolated home, every hook was
`trusted`.
"""

from __future__ import annotations

import copy
import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.codex.harness import trust_config_toml
from mission_control.adapters.codex.hook_trust import (
    HookTrustUnverified,
    hook_trust_records,
    hook_trust_toml,
    verify_listed_trust,
)

RECORDED = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "provider_frames"
    / "codex"
    / "hooks_list"
    / "trust-0.162.1.json"
)
GOLDEN = Path(__file__).resolve().parents[2] / "fixtures" / "projections" / "codex"


def _recorded() -> dict[str, Any]:
    document = json.loads(RECORDED.read_text(encoding="utf-8"))
    assert document["recorded"] is True and document["codex_cli_version"] == "codex-cli 0.162.1"
    return document


def _case(name: str) -> tuple[bytes, dict[str, Any], Path]:
    case = _recorded()["cases"][name]
    listed = case["hooks_list_result"]
    source = Path(listed["data"][0]["hooks"][0]["sourcePath"])
    return json.dumps(case["hooks_json"]).encode("utf-8"), listed, source


@pytest.mark.parametrize("name", ["golden_projection", "normalization_edges"])
def test_records_carry_the_keys_and_hashes_codex_reported(name: str) -> None:
    hooks_json, listed, source = _case(name)
    records = hook_trust_records(hooks_json, source)
    reported = {
        entry["key"]: (entry["currentHash"], entry["trustStatus"])
        for entry in listed["data"][0]["hooks"]
    }
    assert {record.key: (record.trusted_hash, "trusted") for record in records} == reported
    verify_listed_trust(listed, records, source)


def test_the_recorded_golden_case_is_the_committed_golden_projection() -> None:
    hooks_json, _listed, _source = _case("golden_projection")
    committed = json.loads((GOLDEN / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    assert json.loads(hooks_json) == committed


def test_the_records_are_toml_hooks_state_tables_codex_reads() -> None:
    hooks_json, _listed, source = _case("normalization_edges")
    records = hook_trust_records(hooks_json, source)
    workspace = Path("/srv/leases/lease-1")
    config = tomllib.loads(trust_config_toml(workspace, records))
    assert config["projects"][str(workspace)] == {"trust_level": "trusted"}
    assert config["hooks"]["state"] == {
        record.key: {"enabled": True, "trusted_hash": record.trusted_hash} for record in records
    }
    assert hook_trust_toml(()) == ""


def _tampered(listed: dict[str, Any], **changes: Any) -> dict[str, Any]:
    copied = copy.deepcopy(listed)
    copied["data"][0]["hooks"][0].update(changes)
    return copied


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"trustStatus": "untrusted"}, "untrusted"),
        ({"trustStatus": "modified", "currentHash": "sha256:" + "0" * 64}, "modified"),
        ({"enabled": False}, "trusted"),
    ],
)
def test_a_hook_codex_would_not_run_refuses_the_launch(
    changes: dict[str, Any], message: str
) -> None:
    hooks_json, listed, source = _case("golden_projection")
    records = hook_trust_records(hooks_json, source)
    with pytest.raises(HookTrustUnverified) as refused:
        verify_listed_trust(_tampered(listed, **changes), records, source)
    assert refused.value.code == "HOOK_TRUST_UNVERIFIED"
    assert message in str(refused.value)


def test_a_missing_hook_extra_hook_or_load_error_refuses_the_launch() -> None:
    hooks_json, listed, source = _case("golden_projection")
    records = hook_trust_records(hooks_json, source)
    count = len(records)
    missing = copy.deepcopy(listed)
    missing["data"][0]["hooks"].pop()
    with pytest.raises(HookTrustUnverified, match=f"lists {count - 1} of the {count}"):
        verify_listed_trust(missing, records, source)
    # A hook in the file Mission Control did not project (an edited file) is refused too.
    with pytest.raises(HookTrustUnverified, match=f"lists {count} of the {count - 1}"):
        verify_listed_trust(listed, records[:-1], source)
    broken = copy.deepcopy(listed)
    broken["data"][0]["errors"] = [{"path": str(source), "message": "invalid hooks.json"}]
    with pytest.raises(HookTrustUnverified, match="invalid hooks.json"):
        verify_listed_trust(broken, records, source)
    with pytest.raises(HookTrustUnverified, match=f"lists 0 of the {count}"):
        verify_listed_trust({"data": []}, records, source)


def test_only_command_hooks_are_projected() -> None:
    document = {"hooks": {"PreToolUse": [{"hooks": [{"type": "prompt", "prompt": "x"}]}]}}
    with pytest.raises(ValueError, match="command hooks only"):
        hook_trust_records(json.dumps(document).encode(), Path("/lease/.codex/hooks.json"))
