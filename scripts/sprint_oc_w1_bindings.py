"""Write the Sprint OC W1 operator launch bindings (`mc.manifest_launch_bindings.v1`, OVE-169).

The W1 harness file `MANIFEST_LAUNCH_BINDINGS_PATH` names (RUNTIME-ENVIRONMENT section 1,
`MC_UNMANAGED`). Built from the reviewed Deep Agents example scaffold, with:

* `model_profiles`: the `models.toml` rows a W1 manifest selects (`producer.default`,
  `producer.fallback`), each bound to the exact model definition the capability-pin file serves
  for that row's vendor and model id (no model is named in the environment);
* `capabilities`: the seven catalog knowledge tools (seed `mc.catalog.knowledge-tools@1.2.0`, exact
  published digests) bound to the exact Deep Agents tool components the worker registers
  (`knowledge_tool_components`; their digests depend only on tool name and schema);
* the example's `OWNER-SELECT` policy references replaced by explicit W1 operator references.

Nothing here is secret. Usage (from the canonical MC checkout):

    uv run --no-sync python <worktree>/scripts/sprint_oc_w1_bindings.py --app ai-engineer \
        --out .scratch/sprint-oc/runtime/ai-engineer/w1-launch-bindings.json
"""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path
from typing import Any

from mission_control.adapters.deep_agents.knowledge_tools import (
    knowledge_capability_id,
    knowledge_tool_components,
    knowledge_tools,
)
from mission_control.application.authoring.manifest_launch_inputs import (
    CapabilityComponentBinding,
    ManifestLaunchBindings,
)
from mission_control.application.knowledge.toolset import TOOL_NAMES

W1_REFS = {
    "authority_refs": ["authority:sprint-oc-w1-operator"],
    "redaction_policy_ref": "policy:sprint-oc-w1-redaction",
    "tracing_policy_ref": "policy:sprint-oc-w1-tracing",
    "sensitive_data_policy_ref": "policy:sprint-oc-w1-internal-data",
    "snapshot_policy_ref": "policy:sprint-oc-w1-snapshot",
}
PROFILES = ("producer.default", "producer.fallback")


class _NoToolset:
    """Tool construction only needs a closure target; the components hash name and schema."""


def _model_rows(root: Path, app: str) -> dict[str, dict[str, Any]]:
    data = tomllib.loads((root / "deployments" / app / "models.toml").read_text(encoding="utf-8"))
    return {row["profile"]: row for row in data["models"]}


def _pinned_model(pins: dict[str, Any], vendor: str, model_id: str) -> dict[str, Any]:
    for item in pins["models"]:
        if item.get("provider") == vendor and item.get("model_id") == model_id:
            ref = dict(item["ref"])
            ref.setdefault("lifecycle_status", "published")
            ref.setdefault("payload_ref", None)
            ref.setdefault("schema_version", "1")
            return ref
    raise SystemExit(f"MODEL_NOT_PINNED: {vendor}/{model_id}")


def _knowledge_digests(root: Path) -> dict[str, str]:
    seed = (
        root
        / "packages/mission-control-db-contract/seeds/common/mc.catalog.knowledge-tools-1.2.0.json"
    )
    records = json.loads(seed.read_text(encoding="utf-8"))["records"]
    digests: dict[str, str] = {}
    for record in records:
        manifest = record["fields"].get("manifest", {})
        ref = manifest.get("ref") if isinstance(manifest, dict) else None
        if ref and ref.get("kind") == "tool":
            digests[ref["logical_id"]] = ref["digest"]
    return digests


def _sealed_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Recompute the profile digest after the W1 model edit (the class's own rule)."""

    from mission_control.domain.authoring.canonical import sha256_digest
    from mission_control.domain.execution.contracts import DeepAgentProfile

    draft = DeepAgentProfile.model_validate(profile, context={"allow_placeholder_digest": True})
    digest = sha256_digest(draft.model_dump(mode="python", exclude={"profile_digest"}))
    sealed = DeepAgentProfile.model_validate({**profile, "profile_digest": digest})
    return sealed.model_dump(mode="json")


def build(root: Path, app: str) -> dict[str, Any]:
    example = json.loads(
        (root / "deployments/examples/manifest-launch-bindings.deep-agents.example.json").read_text(
            encoding="utf-8"
        )
    )
    pins = json.loads(
        (root / "infra/capability-pins/research-capabilities.json").read_text(encoding="utf-8")
    )
    rows = _model_rows(root, app)
    scaffold = example["deep_agents"]
    scaffold.update(W1_REFS)
    scaffold["workspace"]["provider"] = "local-state-backend"
    # The scaffold model is replaced per node by the selected profile; keep it a served row.
    default = rows["producer.default"]
    scaffold["profile"]["model"].update(
        {
            "provider": default["vendor"],
            "model_name": default["model_id"],
            "ref": _pinned_model(pins, default["vendor"], default["model_id"]),
        }
    )
    scaffold["profile"] = _sealed_profile(scaffold["profile"])
    model_profiles: dict[str, Any] = {}
    for profile in PROFILES:
        row = rows[profile]
        model_profiles[profile] = {
            "ref": _pinned_model(pins, row["vendor"], row["model_id"]),
            "settings": {"max_tokens": 16000},
        }
    tools = knowledge_tools(_NoToolset())  # type: ignore[arg-type]
    components = {item.tool_name: item for item in knowledge_tool_components(tools)}
    digests = _knowledge_digests(root)
    capabilities: dict[str, Any] = {}
    for name in TOOL_NAMES:
        capability = knowledge_capability_id(name)
        digest = digests.get(capability)
        if digest is None:
            raise SystemExit(f"KNOWLEDGE_TOOL_NOT_SEEDED: {capability}")
        capabilities[capability] = CapabilityComponentBinding(
            catalog_digest=digest, kind="tool", tool=components[name]
        ).model_dump(mode="json", exclude_none=True)
    document = {
        "schema_version": "mc.manifest_launch_bindings.v1",
        "deep_agents": scaffold,
        "model_profiles": model_profiles,
        "sandbox_profiles": example["sandbox_profiles"],
        "capabilities": capabilities,
    }
    ManifestLaunchBindings.model_validate(document)
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, choices=("ai-engineer", "biotech"))
    parser.add_argument("--root", default=".", help="the canonical Mission Control checkout")
    parser.add_argument("--out", required=True)
    options = parser.parse_args()
    document = build(Path(options.root).resolve(), options.app)
    Path(options.out).write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": options.out,
                "model_profiles": sorted(document["model_profiles"]),
                "capabilities": sorted(document["capabilities"]),
            }
        )
    )


if __name__ == "__main__":
    main()
