"""FT-G1: `mc.lane_describe.v1`, harness contracts and `mc.cursor_binding.v1` (v2 since
MO-31); MP-01: the `mc.lane_describe.v2` stubs of the hosted profiles; MP-07/08/09: the
implemented v2 matrices."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mission_control.adapters.cursor.describe import (
    CURSOR_CLOUD_DESCRIBE,
    CURSOR_CLOUD_DESCRIBE_V1,
    CURSOR_LOCAL_DESCRIBE,
    CURSOR_LOCAL_DESCRIBE_V1,
)
from mission_control.adapters.deep_agents.describe import DEEP_AGENTS_DESCRIBE
from mission_control.application.execution.harness.describe import (
    DECLARED_LANE_MATRICES,
    V1_LANE_PROFILES,
    V2_IMPLEMENTED_LANE_PROFILES,
    V2_STUB_LANE_PROFILES,
    declared_matrix,
)
from mission_control.domain.authoring.canonical import stable_json_dump
from mission_control.domain.execution.bindings import WorkspacePolicyPin as BindingPolicyPin
from mission_control.domain.execution.lanes import (
    DELIVERY_COMMANDS,
    LANE_CONTRACTS,
    LANE_CONTROLS,
    LANE_FEATURES,
    LANE_PROFILES,
    PLACEMENT_OF_PROFILE,
    CursorExecutionBinding,
    LaneDescribe,
    UsageReport,
    WorkspacePolicyPin,
    lane_contract_schemas,
)

DIGEST = "sha256:" + "a" * 64

# 00-ARCHITECTURE section 6 (lane matrix), row by row.
ARCHITECTURE_MATRIX: dict[str, dict[str, str]] = {
    "deep_agents": {
        "prepare": "native",
        "start": "native",
        "reattach": "native",
        "send_turn": "native",
        "cancel_turn": "native",
        "observe": "native",
        "fork": "emulated",
        "snapshot": "emulated",
    },
    "cursor_local": {
        "prepare": "native",
        "start": "native",
        "reattach": "emulated",
        "cancel_turn": "native",
        "observe": "native",
        "pause": "unsupported",
        "fork": "emulated",
        "snapshot": "emulated",
    },
    "cursor_cloud": {
        "prepare": "native",
        "start": "native",
        "reattach": "native",
        "cancel_turn": "native",
        "observe": "native",
        "pause": "unsupported",
        "fork": "emulated",
        "snapshot": "emulated",
    },
}
ARCHITECTURE_DELIVERY: dict[str, dict[str, str]] = {
    "deep_agents": {
        "queue_instruction": "turn_boundary_guaranteed",
        # Owner 2026-11-06 (steer with context): the running turn is steered in-process.
        "interrupt_and_inject": "cooperative_inject",
        "pause": "pause_at_tool_gate",
    },
    "cursor_local": {
        "queue_instruction": "wait_then_send",
        "interrupt_and_inject": "cancel_and_replace",
        "pause": "unsupported",
    },
    "cursor_cloud": {
        "queue_instruction": "wait_then_send",
        "interrupt_and_inject": "cancel_and_replace",
        "pause": "unsupported",
    },
}


@pytest.mark.parametrize("profile", sorted(ARCHITECTURE_MATRIX))
def test_declared_matrices_match_the_architecture_lane_matrix(profile: str) -> None:
    describe = declared_matrix(profile)
    assert LaneDescribe.model_validate_json(describe.model_dump_json()) == describe
    if profile in V1_LANE_PROFILES:
        # Round trip through the wire contract: the fixture validates as mc.lane_describe.v1.
        assert describe.schema_version == "mc.lane_describe.v1"
        assert not describe.is_v2 and "features" not in describe.model_dump(mode="json")
    else:
        assert describe.is_v2 and set(describe.features) == set(LANE_FEATURES)
    for control, support in ARCHITECTURE_MATRIX[profile].items():
        assert describe.controls[control] == support, control
    for command, semantics in ARCHITECTURE_DELIVERY[profile].items():
        assert describe.delivery_semantics[command] == semantics, command


def test_the_nine_profiles_are_declared_and_partitioned() -> None:
    assert set(DECLARED_LANE_MATRICES) == set(LANE_PROFILES)
    groups = (V1_LANE_PROFILES, V2_IMPLEMENTED_LANE_PROFILES, V2_STUB_LANE_PROFILES)
    assert set(LANE_PROFILES) == frozenset().union(*groups)
    assert sum(len(group) for group in groups) == len(LANE_PROFILES)


def test_the_cursor_v1_shapes_stay_readable_beside_their_v2_matrices() -> None:
    """MP-09: v2 adds per-feature evidence; controls, delivery and identity are unchanged."""

    for v1, v2 in (
        (CURSOR_LOCAL_DESCRIBE_V1, CURSOR_LOCAL_DESCRIBE),
        (CURSOR_CLOUD_DESCRIBE_V1, CURSOR_CLOUD_DESCRIBE),
    ):
        assert v1.schema_version == "mc.lane_describe.v1" and not v1.is_v2
        assert LaneDescribe.model_validate_json(v1.model_dump_json()) == v1
        assert v2.is_v2 and v2.qualified is False and v1.digest != v2.digest
        assert (v2.controls, v2.delivery_semantics, v2.identity) == (
            v1.controls,
            v1.delivery_semantics,
            v1.identity,
        )
        assert not any(evidence.qualified for evidence in v2.features.values())


@pytest.mark.parametrize("profile", sorted(V2_IMPLEMENTED_LANE_PROFILES))
def test_implemented_v2_matrices_carry_evidence_and_nothing_is_qualified(profile: str) -> None:
    describe = declared_matrix(profile)
    assert LaneDescribe.model_validate_json(describe.model_dump_json()) == describe
    assert describe.is_v2 and describe.qualified is False
    assert set(describe.features) == set(LANE_FEATURES)
    assert not any(evidence.qualified for evidence in describe.features.values())
    assert "workflow_gate" in describe.approval_modes
    assert describe.placement == PLACEMENT_OF_PROFILE[profile]


@pytest.mark.parametrize("profile", sorted(V2_STUB_LANE_PROFILES))
def test_mp01_profiles_are_v2_stubs_with_every_cell_unqualified(profile: str) -> None:
    """A stub states design intent, not proof: nothing native/emulated, nothing qualified."""

    describe = declared_matrix(profile)
    assert LaneDescribe.model_validate_json(describe.model_dump_json()) == describe
    assert describe.schema_version == "mc.lane_describe.v2" and describe.is_v2
    assert describe.qualified is False
    assert set(describe.controls.values()) == {"unqualified"}
    assert set(describe.features) == set(LANE_FEATURES)
    for name, evidence in describe.features.items():
        assert evidence.status in {"unqualified", "unsupported"}, name
        assert not evidence.implemented and not evidence.qualified, name
        assert not describe.feature_implemented(name), name
    assert describe.compaction_control in {"unqualified", "unsupported"}
    assert describe.subordinate_visibility in {"unqualified", "unavailable"}
    assert "workflow_gate" in describe.approval_modes
    # `unqualified()` is idempotent on a stub (the registry publishes stubs through it).
    assert describe.unqualified() == describe


def test_hosted_stubs_state_the_feasibility_findings() -> None:
    claude_cloud = declared_matrix("claude_cloud")
    codex_cloud = declared_matrix("codex_cloud")
    assert claude_cloud.placement == codex_cloud.placement == "cloud"
    assert not claude_cloud.hooks.fail_closed and not codex_cloud.hooks.fail_closed
    assert codex_cloud.hooks.mechanism == "none" and codex_cloud.hooks.events_supported == ()
    # Neither hosted product exposes a public cancel/interrupt: the Stop Fence cannot reach
    # them, which is why admission refuses any workflow that requires `cancel` there.
    for describe in (claude_cloud, codex_cloud):
        assert describe.feature("cancel").status == "unsupported"
        assert describe.delivery_semantics["cancel"] == "unsupported"
        assert describe.feature("approval_suspension").status == "unsupported"
    assert codex_cloud.feature("follow_up").status == "unsupported"
    assert codex_cloud.feature("observe").status == "unsupported"
    assert codex_cloud.feature("continuation").status == "unsupported"
    assert claude_cloud.feature("status").status == "unsupported"
    assert claude_cloud.feature("follow_up").status == "unqualified"
    assert claude_cloud.approval_modes == ("workflow_gate",)
    assert codex_cloud.approval_modes == ("workflow_gate",)


def test_v2_describe_rules() -> None:
    stub = declared_matrix("codex").model_dump(mode="json")
    # v1 cannot carry v2 fields.
    with pytest.raises(ValidationError, match="mc.lane_describe.v2"):
        LaneDescribe.model_validate({**stub, "schema_version": "mc.lane_describe.v1"})
    # v2 carries evidence for every feature.
    features = dict(stub["features"])
    features.pop("launch")
    with pytest.raises(ValidationError, match="exactly"):
        LaneDescribe.model_validate({**stub, "features": features})
    # A qualified v2 lane cannot carry unqualified features.
    native = {
        **stub,
        "controls": dict.fromkeys(LANE_CONTROLS, "native"),
        "qualified": True,
    }
    with pytest.raises(ValidationError, match="unqualified features"):
        LaneDescribe.model_validate(native)
    # A qualified feature cites its evidence.
    with pytest.raises(ValidationError, match="evidence_ref"):
        LaneDescribe.model_validate(
            {
                **stub,
                "features": {
                    **stub["features"],
                    "launch": {"status": "native", "implemented": True, "qualified": True},
                },
            }
        )
    with pytest.raises(ValidationError, match="cannot be implemented"):
        LaneDescribe.model_validate(
            {
                **stub,
                "features": {
                    **stub["features"],
                    "launch": {"status": "unsupported", "implemented": True},
                },
            }
        )


def test_cursor_profiles_are_unqualified_and_differ_where_the_spec_says() -> None:
    assert not CURSOR_LOCAL_DESCRIBE.qualified and not CURSOR_CLOUD_DESCRIBE.qualified
    assert DEEP_AGENTS_DESCRIBE.qualified
    assert CURSOR_LOCAL_DESCRIBE.identity.cursor == "bridge_offset"
    assert CURSOR_CLOUD_DESCRIBE.identity.cursor == "sse_event_id"
    assert CURSOR_CLOUD_DESCRIBE.placement == "cloud"
    assert CURSOR_LOCAL_DESCRIBE.placement == "worker_hosted"
    assert "session_start" in CURSOR_LOCAL_DESCRIBE.hooks.events_supported
    assert "session_start" not in CURSOR_CLOUD_DESCRIBE.hooks.events_supported
    assert "session_end" not in CURSOR_CLOUD_DESCRIBE.hooks.events_supported
    assert "prompt_prefix" not in CURSOR_CLOUD_DESCRIBE.instruction_channel
    # Kernel Hooks are fail-closed on the worker; the cloud VM runs catalog command hooks
    # only (it cannot reach the loopback callback), so cloud does not claim fail-closed
    # (FT-G6 describe honesty).
    assert CURSOR_LOCAL_DESCRIBE.hooks.fail_closed
    assert not CURSOR_CLOUD_DESCRIBE.hooks.fail_closed


def _payload(**changes: Any) -> dict[str, Any]:
    return {**CURSOR_LOCAL_DESCRIBE.model_dump(mode="json"), **changes}


def test_describe_rejects_incomplete_or_dishonest_matrices() -> None:
    controls = dict(CURSOR_LOCAL_DESCRIBE.controls)
    controls.pop("fork")
    with pytest.raises(ValidationError, match="controls"):
        LaneDescribe.model_validate(_payload(controls=controls))
    with pytest.raises(ValidationError, match="delivery_semantics"):
        LaneDescribe.model_validate(_payload(delivery_semantics={"cancel": "wait_then_send"}))
    with pytest.raises(ValidationError):
        LaneDescribe.model_validate(_payload(controls={**controls, "fork": "magic"}))
    with pytest.raises(ValidationError, match="belong"):
        LaneDescribe.model_validate(_payload(lane="deep_agents"))
    hooks = {**CURSOR_LOCAL_DESCRIBE.hooks.model_dump(), "events_supported": ["on_anything"]}
    with pytest.raises(ValidationError, match="hook events"):
        LaneDescribe.model_validate(_payload(hooks=hooks))
    stub = CURSOR_LOCAL_DESCRIBE.unqualified()
    assert set(stub.controls.values()) == {"unqualified"}
    with pytest.raises(ValidationError, match="qualified"):
        LaneDescribe.model_validate({**stub.model_dump(mode="json"), "qualified": True})
    assert set(LANE_CONTROLS) == set(stub.controls)
    assert set(DELIVERY_COMMANDS) == set(stub.delivery_semantics)


def test_describe_digest_is_stable_and_content_bound() -> None:
    assert DEEP_AGENTS_DESCRIBE.digest == declared_matrix("deep_agents").digest
    assert CURSOR_LOCAL_DESCRIBE.digest != CURSOR_LOCAL_DESCRIBE.unqualified().digest
    with pytest.raises(ValueError, match="undeclared"):
        declared_matrix("gemini_cli")


def test_every_lane_contract_exports_a_json_schema() -> None:
    schemas = lane_contract_schemas()
    assert set(schemas) == set(LANE_CONTRACTS)
    for name, schema in schemas.items():
        assert schema["type"] == "object", name
        assert schema.get("additionalProperties") is False, name
    describe = schemas["lane_describe"]
    assert describe["properties"]["schema_version"]["enum"] == [
        "mc.lane_describe.v1",
        "mc.lane_describe.v2",
    ]
    assert describe["properties"]["schema_version"]["default"] == "mc.lane_describe.v1"


def _local_binding(**changes: Any) -> dict[str, Any]:
    return {
        "lane_profile": "cursor_local",
        "pins": {
            "cursor_sdk": "1.0.37",
            "bridge": "1.0.37",
            "protocol": "sdk.v1",
            "cloud_api": "v1",
        },
        "model_id": "composer-2",
        "workspace": {"base_ref": "main"},
        "projections": {"rules_digest": DIGEST, "agents_digest": DIGEST, "hooks_digest": DIGEST},
        "hook_callback": {"listen": "127.0.0.1:47555", "token_ttl_s": 3600},
        "budgets": {"max_turns": 4, "max_segments": 8, "wall_clock_s": 3600},
        **changes,
    }


def test_cursor_binding_is_sealed_by_its_digest_and_shaped_by_profile() -> None:
    binding = CursorExecutionBinding.sealed(**_local_binding())
    assert binding.schema_version == "mc.cursor_binding.v2"
    assert binding.binding_digest == binding.computed_digest()
    tampered = {**binding.model_dump(mode="json"), "model_id": "other-model"}
    with pytest.raises(ValidationError, match="binding_digest"):
        CursorExecutionBinding.model_validate(tampered)
    with pytest.raises(ValidationError, match="hook callback"):
        CursorExecutionBinding.sealed(**_local_binding(hook_callback=None))
    with pytest.raises(ValidationError, match="listen"):
        CursorExecutionBinding.sealed(
            **_local_binding(hook_callback={"listen": "0.0.0.0:1", "token_ttl_s": 60})
        )
    with pytest.raises(ValidationError, match="repository"):
        CursorExecutionBinding.sealed(**_local_binding(lane_profile="cursor_cloud"))
    cloud = CursorExecutionBinding.sealed(
        **_local_binding(
            lane_profile="cursor_cloud",
            workspace={"repo_url": "https://github.com/acme/repo", "base_ref": "main"},
            cloud={"auto_create_pr": False},
        )
    )
    assert cloud.cloud is not None and cloud.cloud.environment == "cloud"


# `_local_binding()` sealed by the pre-MO-31 `lanes.py` (a1db195), dumped in JSON mode.
PRE_MO31_V1_BINDING: dict[str, Any] = {
    "schema_version": "mc.cursor_binding.v1",
    "lane_profile": "cursor_local",
    "pins": {"cursor_sdk": "1.0.37", "bridge": "1.0.37", "protocol": "sdk.v1", "cloud_api": "v1"},
    "model_id": "composer-2",
    "mode": "agent",
    "workspace": {"repo_url": None, "base_ref": "main", "lease_root": None, "branch_prefix": "mc/"},
    "projections": {
        "rules_digest": DIGEST,
        "agents_digest": DIGEST,
        "skills": [],
        "mcp_servers": [],
        "hooks_digest": DIGEST,
    },
    "inline_subagents": [],
    "disallowed_tools": [],
    "sandbox_enabled": False,
    "cloud": None,
    "hook_callback": {"listen": "127.0.0.1:47555", "token_ttl_s": 3600},
    "budgets": {"max_turns": 4, "max_segments": 8, "wall_clock_s": 3600},
    "binding_digest": "sha256:5f326b3d8e0532eaa6a0d588fd31df84b2e66e0db4e1b84e717bde4dd0a24943",
}


def test_cursor_binding_v2_pins_hook_scripts_and_plugins_and_v1_still_reads() -> None:
    """MO-31: v2 adds hook-script and plugin pins (plugins with their expansion digest), left
    out of the dump and digest when empty; a sealed v1 binding reads unchanged and cannot carry
    them."""

    hook = "hook.mc-policy-template@1.0.0#" + DIGEST
    plugin = "plugin.web-research@1.0.0#" + DIGEST
    plain = CursorExecutionBinding.sealed(**_local_binding())
    projections = plain.model_dump(mode="json")["projections"]
    assert not {"hook_script_pins", "plugin_pins", "plugin_expansion_digest"} & set(projections)
    full = CursorExecutionBinding.sealed(
        **_local_binding(
            projections={
                **projections,
                "skills": ["skill.a@1#" + DIGEST],
                "hook_script_pins": [hook],
                "plugin_pins": [plugin],
                "plugin_expansion_digest": DIGEST,
            },
            inline_subagents=["subagent.v@1#" + DIGEST],
        )
    )
    assert full.binding_digest != plain.binding_digest
    assert full.projected_pins() == ("skill.a@1#" + DIGEST, "subagent.v@1#" + DIGEST, hook, plugin)
    assert CursorExecutionBinding.model_validate(full.model_dump(mode="json")) == full
    with pytest.raises(ValidationError, match="plugin_expansion_digest"):
        CursorExecutionBinding.sealed(
            **_local_binding(projections={**projections, "plugin_pins": [plugin]})
        )
    # A v1 binding sealed before MO-31 keeps its bytes and digest; it has no v2 slots.
    v1 = CursorExecutionBinding.model_validate(PRE_MO31_V1_BINDING)
    assert v1.model_dump(mode="json") == PRE_MO31_V1_BINDING
    assert v1.binding_digest == v1.computed_digest() == PRE_MO31_V1_BINDING["binding_digest"]
    resealed = CursorExecutionBinding.sealed(
        **_local_binding(schema_version="mc.cursor_binding.v1")
    )
    assert resealed == v1
    with pytest.raises(ValidationError, match="no hook-script or plugin pins"):
        CursorExecutionBinding.sealed(
            **_local_binding(
                schema_version="mc.cursor_binding.v1",
                projections={**projections, "hook_script_pins": [hook]},
            )
        )


def test_a_cursor_workspace_policy_is_pinned_only_when_the_manifest_admitted_one() -> None:
    """MO-05: absent, the policy stays out of the dump and the digest (bindings sealed before
    it keep theirs); present, it is part of the sealed content."""

    legacy = CursorExecutionBinding.sealed(**_local_binding())
    assert legacy.workspace.policy is None
    assert "policy" not in legacy.model_dump(mode="json")["workspace"]
    assert "policy" not in stable_json_dump(legacy)["workspace"]
    policy = {
        "mode": "managed_worktree",
        "reuse": "within_run",
        "dirty_input": "reject",
        "cleanup": "retain_until_artifacts_registered",
    }
    pinned = CursorExecutionBinding.sealed(
        **_local_binding(workspace={**legacy.workspace.model_dump(), "policy": policy})
    )
    assert pinned.workspace.policy == WorkspacePolicyPin.model_validate(policy)
    assert pinned.binding_digest != legacy.binding_digest
    assert WorkspacePolicyPin is BindingPolicyPin


def test_usage_report_never_counts_unknown_as_tokens() -> None:
    with pytest.raises(ValidationError, match="unknown"):
        UsageReport(disposition="unknown", total_tokens=3)
    assert UsageReport(disposition="estimated", total_tokens=3).total_tokens == 3


_DB_CONTRACT = Path(__file__).resolve().parents[3] / "packages/mission-control-db-contract"
_MIGRATIONS = _DB_CONTRACT / "releases/1.15.0/component/migrations"
# Cross-provider control (OVE-224, ADR-0069): the 1.14.0 describe refresh of every session lane.
_CROSS_PROVIDER_MIGRATION = "0073_cross_provider_lane_describes.sql"
# Owner 2026-11-06 (steer with context): 1.15.0 revises the Deep Agents row only.
_STEER_MIGRATION = "0074_deep_agents_cooperative_inject_describe.sql"
_SUBAGENT_FIELDS_MIGRATION = "0046_lane_describe_subagent_fields.sql"
_LANE_DESCRIBE_MIGRATION = "0033_approvals_coordinator_inbox_lane_describes.sql"
_HOSTED_AGENT_API_MIGRATION = "0036_hosted_agent_api_lane_profiles.sql"
_CURRENT_LANE_DESCRIBE_MIGRATION = "0040_implemented_lane_describes.sql"
# Released (locked 1.1.0, 0030) and unreleased-but-built (0031) bytes: never edited.
_IMMUTABLE_LANE_MIGRATIONS = {
    "0033_approvals_coordinator_inbox_lane_describes.sql": (
        "d72734e84e11c6e11475f60793d3b31899b7847bc75d4c1fc01e84a68f134cd0"
    ),
    "0036_hosted_agent_api_lane_profiles.sql": (
        "af7b4ccddfbfd47f5f8fafdd4406dda78e95c330a09ee665ef46c2c4b878cb9d"
    ),
    "0030_lane_bindings.sql": "c057bc275ab7162f1109646323a0aba82fd8c8b89bc9240df48ebc44501027cf",
    "0031_multi_provider_lanes.sql": (
        "21ac0c9ae225d322f6fa44a9f49187d3f5d9018f663558a999ff42f5b80d2df1"
    ),
}


def _seeded_describes(migration: str) -> dict[str, Any]:
    """The describe documents a migration INSERTs into `lane_profile`, by profile."""

    sql = (_MIGRATIONS / migration).read_text("utf-8")
    return {
        match.group(1): json.loads(match.group(2))
        for match in re.finditer(r"\('([a-z_]+)', '[a-z_]+', '[a-z_]+',\s*'(\{.*?\})'::jsonb", sql)
    }


def _revised_describes(migration: str) -> dict[str, Any]:
    """The describe documents a migration UPDATEs on `lane_profile`, by profile."""

    sql = (_MIGRATIONS / migration).read_text("utf-8")
    pattern = (
        r"UPDATE mission_control\.lane_profile\s+SET describe = '((?:[^']|'')*)'::jsonb\s+"
        r"WHERE lane_profile = '([a-z_]+)' AND (?:NOT )?qualified"
        r"(?: AND describe = '(?:[^']|'')*'::jsonb)?;"
    )
    revised: dict[str, Any] = {}
    for match in re.finditer(pattern, sql):
        assert match.group(2) not in revised, f"{match.group(2)} revised twice in {migration}"
        revised[match.group(2)] = json.loads(match.group(1).replace("''", "'"))
    return revised


def test_lane_profile_migrations_end_at_exactly_the_declared_describes() -> None:
    """Historical seeds stay immutable; 0042 advances only the Codex CLI pin."""

    for name, digest in _IMMUTABLE_LANE_MIGRATIONS.items():
        assert hashlib.sha256((_MIGRATIONS / name).read_bytes()).hexdigest() == digest, name
    seeded_0030 = _seeded_describes("0030_lane_bindings.sql")
    seeded_0031 = _seeded_describes("0031_multi_provider_lanes.sql")
    revised_0033 = _revised_describes(_LANE_DESCRIBE_MIGRATION)
    seeded_0036 = _seeded_describes(_HOSTED_AGENT_API_MIGRATION)
    revised_0040 = _revised_describes(_CURRENT_LANE_DESCRIBE_MIGRATION)
    revised_0042 = _revised_describes("0042_codex_01621_lane_describe.sql")
    revised_0046 = _revised_describes(_SUBAGENT_FIELDS_MIGRATION)
    revised_0073 = _revised_describes(_CROSS_PROVIDER_MIGRATION)
    revised_0074 = _revised_describes(_STEER_MIGRATION)
    assert set(revised_0042) == {"codex"}
    assert set(seeded_0030) == {"deep_agents", "cursor_local", "cursor_cloud"}
    assert set(seeded_0031) == {"claude_agent_sdk", "codex", "claude_cloud", "codex_cloud"}
    assert set(revised_0040) == V2_IMPLEMENTED_LANE_PROFILES
    assert set(seeded_0036) == {"claude_managed", "codex_agents"}
    # 1.4.3: every lane's describe gains `subagents.fields`; only Deep Agents is qualified.
    assert set(revised_0046) == set(DECLARED_LANE_MATRICES)
    before_0046 = {
        **seeded_0030,
        **seeded_0031,
        **revised_0033,
        **seeded_0036,
        **revised_0040,
        **revised_0042,
    }
    for profile, document in revised_0046.items():
        previous = dict(before_0046[profile])
        assert document["subagents"]["fields"]
        assert document["qualified"] == previous["qualified"]
        stripped = json.loads(json.dumps(document))
        stripped["subagents"].pop("fields")
        stripped.pop("time_travel", None)
        assert stripped == previous, profile
    # 1.14.0 (cross-provider control): every session lane's describe moved (`time_travel`, fork
    # cells); the Deep Agents row and the two hosted stubs did not.
    assert set(revised_0073) == V2_IMPLEMENTED_LANE_PROFILES
    for document in revised_0073.values():
        assert document["qualified"] is False
        assert document["time_travel"]["read"] in {"R1", "R2", "R3"}
    # 1.15.0: only the Deep Agents row moves (cooperative_inject); it stays qualified.
    assert set(revised_0074) == {"deep_agents"}
    assert revised_0074["deep_agents"]["qualified"] is True
    assert revised_0074["deep_agents"]["delivery_semantics"]["interrupt_and_inject"] == (
        "cooperative_inject"
    )
    assert {**before_0046, **revised_0046, **revised_0073, **revised_0074} == {
        profile: describe.model_dump(mode="json")
        for profile, describe in DECLARED_LANE_MATRICES.items()
    }
    assert set(seeded_0030) - set(revised_0033) == V1_LANE_PROFILES
    assert (set(seeded_0031) | set(seeded_0036)) - V2_IMPLEMENTED_LANE_PROFILES == (
        V2_STUB_LANE_PROFILES
    )
    for document in (
        *seeded_0031.values(),
        *revised_0033.values(),
        *seeded_0036.values(),
        *revised_0040.values(),
        *revised_0042.values(),
    ):
        assert document["qualified"] is False
        assert document["schema_version"] == "mc.lane_describe.v2"


def test_frozen_0040_and_additive_0042_are_exact_generated_text() -> None:
    """Reproduce 0040's frozen declaration and the narrow version successor independently."""

    spec = importlib.util.spec_from_file_location(
        "lane_describe_refresh", _DB_CONTRACT / "scripts/lane_describe_refresh.py"
    )
    assert spec is not None and spec.loader is not None
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    sql = (_MIGRATIONS / _CURRENT_LANE_DESCRIBE_MIGRATION).read_bytes().decode("utf-8")
    # 1.14.0: the declared matrices moved past 0040 (0073), so 0040 is reproduced from the
    # documents persisted through 1.13.0 (0042's pin and 0046's fields reverted below).
    documents = generator.persisted_documents(_DB_CONTRACT / "releases/1.13.0/component/migrations")
    documents["codex"] = json.loads(
        json.dumps(documents["codex"]).replace("codex-cli 0.162.1", "codex-cli 0.162.0")
    )
    documents["codex"]["versions"]["codex_cli"] = "0.162.0"
    # 0040 predates the 1.4.3 describe fields: reproduce it without them.
    for document in documents.values():
        document["subagents"].pop("fields", None)
        document.pop("time_travel", None)
    assert generator.current_section(sql) == generator.render_section(documents)
    # 1.4.3: the successor section is exactly what the generator renders from the persisted
    # 1.4.2 documents to the declared matrices (qualified Deep Agents named explicitly).
    prior = generator.persisted_documents(_DB_CONTRACT / "releases/1.4.2/component/migrations")
    expected = generator.render_successor_section(
        label="release 1.4.3: subagent fields and time travel on every lane describe",
        # 1.14.0: 0046's end state is what 1.13.0 persisted (0073 moved the declared matrices on).
        documents=generator.persisted_documents(
            _DB_CONTRACT / "releases/1.13.0/component/migrations"
        ),
        prior=prior,
        profiles=tuple(DECLARED_LANE_MATRICES),
        qualified_profiles=("deep_agents",),
    )
    assert (_MIGRATIONS / _SUBAGENT_FIELDS_MIGRATION).read_bytes().decode("utf-8") == expected
    # 1.14.0: 0073 is exactly the successor section from the persisted 1.13.0 documents to the
    # declared matrices for the profiles that moved (`scripts/prepare_release_1140.py`).
    prior_1130 = generator.persisted_documents(
        _DB_CONTRACT / "releases/1.13.0/component/migrations"
    )
    # 1.15.0: 0073's end state is what 1.14.0 persisted (0074 moved the declared matrices on).
    persisted_1140 = generator.persisted_documents(
        _DB_CONTRACT / "releases/1.14.0/component/migrations"
    )
    moved = tuple(p for p in persisted_1140 if persisted_1140[p] != prior_1130.get(p))
    expected_0073 = generator.render_successor_section(
        label="release 1.14.0: cross-provider control time-travel and intervention cells (OVE-224)",
        documents=persisted_1140,
        prior=prior_1130,
        profiles=moved,
        qualified_profiles=tuple(p for p in ("deep_agents",) if p in moved),
    )
    assert (_MIGRATIONS / _CROSS_PROVIDER_MIGRATION).read_bytes().decode("utf-8") == expected_0073
    # 1.15.0: 0074 is exactly the successor from the persisted 1.14.0 documents to the declared
    # matrices for the profiles that moved (`scripts/prepare_release_1150.py`).
    declared = generator.declared_documents()
    moved_1150 = tuple(p for p in declared if declared[p] != persisted_1140.get(p))
    expected_0074 = generator.render_successor_section(
        label="release 1.15.0: Deep Agents steer with context (cooperative_inject)",
        documents=declared,
        prior=persisted_1140,
        profiles=moved_1150,
        qualified_profiles=tuple(p for p in ("deep_agents",) if p in moved_1150),
    )
    assert (_MIGRATIONS / _STEER_MIGRATION).read_bytes().decode("utf-8") == expected_0074
    successor_spec = importlib.util.spec_from_file_location(
        "codex_describe_successor",
        _DB_CONTRACT.parents[1] / "scripts/prepare_codex_describe_successor.py",
    )
    assert successor_spec is not None and successor_spec.loader is not None
    successor = importlib.util.module_from_spec(successor_spec)
    successor_spec.loader.exec_module(successor)
    assert (_MIGRATIONS / successor.MIGRATION).read_text("utf-8") == successor.candidate_sql()
    # The same serialization reproduces an applied 0031 seed literal exactly (0031 predates
    # the 1.4.3 describe fields, which 0046 adds on top of it).
    claude_cloud_document = DECLARED_LANE_MATRICES["claude_cloud"].model_dump(mode="json")
    claude_cloud_document["subagents"].pop("fields", None)
    claude_cloud_document.pop("time_travel", None)
    claude_cloud = generator.describe_literal(claude_cloud_document)
    assert f"'{claude_cloud}'::jsonb" in (_MIGRATIONS / "0031_multi_provider_lanes.sql").read_text(
        "utf-8"
    )
