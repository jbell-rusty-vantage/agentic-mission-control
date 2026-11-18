"""Readable fixture configuration from authored inputs and observed exact bindings.

No intended skill bundle or regenerated provider manifest is materialization evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from mission_control.domain.execution.contracts import DeepAgentExecutionBinding
from mission_control.domain.frames.body import redact_text
from mission_control.domain.resolution.sealed import SealedLaneBinding


def cell(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return redact_text(text)[0].replace("|", "\\|").replace("\n", " ").replace("`", "'")


def render_configuration(
    destination: Path,
    configuration: dict[str, Any],
    bindings: list[dict[str, Any]],
    materializations: list[dict[str, Any]],
) -> None:
    """Join frame observations by canonical unit identity; leave missing links explicit."""
    authored_path = destination / "01-authored-mission.yml"
    authored = yaml.safe_load(authored_path.read_text()) if authored_path.exists() else {}
    mission = (authored or {}).get("mission", {})
    environment = mission.get("environment", {})
    transcript_path = destination / "04-workflow-transcript.jsonl"
    entries = (
        [
            json.loads(line)
            for line in transcript_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        if transcript_path.exists()
        else []
    )
    frames = {
        entry.get("refs", {}).get("frame_id"): entry
        for entry in entries
        if entry.get("kind") == "environment_materialized"
    }
    heading = [
        "# Effective run configuration",
        "",
        "[Full observed configuration](02-effective-run-config.json); "
        "[actual binding/frame records](06-evidence/persisted-runtime.json).",
        "",
        f"Authored mission: {cell(mission.get('key', 'unavailable'))}; "
        f"effective digest: `{cell(configuration.get('digest', 'unavailable'))}`.",
        "",
        "| Authored control | Value |",
        "| --- | --- |",
    ]
    for key in ("lane", "model", "sandbox", "budget", "governors"):
        heading.append(f"| {key} | {cell(environment.get(key, 'not declared'))} |")
    heading.extend(
        [
            "",
            "## Output obligations (effective contract)",
            "",
            "| Slot | Form | Enforcement |",
            "| --- | --- | --- |",
        ]
    )
    promises = configuration.get("output_promises") or {}
    for obligation in promises.get("obligations", []):
        heading.append(
            f"| {cell(obligation['key'])} | "
            f"{cell(obligation.get('contract', {}).get('form'))} | "
            f"{cell(obligation.get('enforcement'))} |"
        )
    heading.extend(
        ["", "These are obligations, not proof of acceptance; see outputs and validation.", ""]
    )
    material = [
        "# Actual provider configuration and materialization",
        "",
        "[Raw observed manifests/receipts](observations.json); "
        "[binding/frame records](../06-evidence/persisted-runtime.json).",
        "",
        "Bound configuration and provider materialization are distinct evidence. "
        "The six Phase 0 sandbox bundles are separate proof and are not assumed mounted here.",
        "",
    ]
    if not bindings:
        material.append("No observed operation binding; provider materialization is unproved.")
    for number, record in enumerate(bindings):
        try:
            bound = DeepAgentExecutionBinding.unseal(
                SealedLaneBinding.model_validate(record["lane_binding"])
            )
        except (KeyError, ValueError) as error:
            material.append(f"Binding {number}: unavailable/invalid ({type(error).__name__}).")
            continue
        unit_key = bound.runtime_unit.unit_key if bound.runtime_unit else None
        unit_frames = {
            frame_id
            for frame_id, entry in frames.items()
            if unit_key is not None and entry.get("unit_key") == unit_key
        }
        observed = [item for item in materializations if item.get("frame_id") in unit_frames]
        location = (
            bound.runtime_unit.model_dump(mode="json")["location"] if bound.runtime_unit else {}
        )
        title = cell(location.get("stage_id", location.get("operation_role", bound.operation_id)))
        subtitle = f"## Unit {number + 1}: {title} (attempt {bound.operation_attempt})"
        details = [
            subtitle,
            "",
            f"Operation: `{cell(bound.operation_id)}`; "
            f"session: `{cell(record.get('session_id'))}`; unit: `{cell(unit_key)}`.",
            "",
            f"Binding envelope digest: `{record['lane_binding']['digest']}`; "
            "validated through the lane's sealed-binding contract.",
            "",
        ]
        material.extend(details)
        heading.extend(details[:3])
        node: dict[str, Any] = next(
            (
                node
                for node in mission.get("program", {}).get("nodes", [])
                if node.get("key") == location.get("stage_id")
            ),
            {},
        )
        authored_environment = {**environment, **node.get("environment", {})}
        authored_capabilities = authored_environment.get("capabilities", [])
        authored_tools = [
            item.get("as", item.get("pin"))
            for item in authored_capabilities
            if item.get("kind") == "tool"
        ]
        authored_skills = [
            item.get("pin") for item in authored_capabilities if item.get("kind") == "skill"
        ]
        receipt_items = bound.materialization_receipt.items if bound.materialization_receipt else ()
        manifests = [item.get("manifest", item.get("receipt", {})) for item in observed]
        model_digests = [manifest.get("model", {}).get("digest") for manifest in manifests]
        model_observed = (
            "No unit-linked environment frame"
            if not manifests
            else f"environment frame model digest(s): {model_digests}; "
            f"matches bound model={all(value == bound.model.ref.digest for value in model_digests)}"
        )
        rows = [
            (
                "Model",
                authored_environment.get("model", "not declared"),
                f"{bound.model.provider}:{bound.model.model_name}; {bound.model.ref.digest}",
                model_observed,
            ),
            (
                "Tools",
                authored_tools,
                [
                    {"name": tool.tool_name, "schema_digest": tool.schema_digest}
                    for tool in bound.tools
                ],
                [
                    {
                        "name": item.name,
                        "schema_digest": item.digest,
                        "locator": item.native_locator,
                    }
                    for item in receipt_items
                    if item.kind == "tool"
                ],
            ),
            (
                "Skills",
                authored_skills or "No authored skill pins",
                [skill.model_dump(mode="json") for skill in bound.skills]
                if bound.skills
                else "0 bound skills",
                "0 mounted skills; environment manifest skills=[]"
                if manifests and all(manifest.get("skills") == [] for manifest in manifests)
                else [manifest.get("skills", "not recorded") for manifest in manifests]
                if manifests
                else "not observed",
            ),
            (
                "Sandbox/backend",
                authored_environment.get("sandbox", "not declared"),
                {
                    "sandbox_backend": bound.sandbox.backend,
                    "backend_ref": bound.backend_ref.logical_id,
                    "backend_digest": bound.backend_ref.digest,
                },
                [
                    {"name": item.name, "locator": item.native_locator, "digest": item.digest}
                    for item in receipt_items
                    if item.kind == "sandbox"
                ],
            ),
            (
                "Checkpointer",
                "deployment supplied",
                {"ref": bound.checkpointer_ref.logical_id, "digest": bound.checkpointer_ref.digest},
                "No independent implementation/DB identity in environment manifest; bound pin only",
            ),
        ]
        table = [
            "| Concern | Authored | Bound effective configuration | Observed materialization |",
            "| --- | --- | --- | --- |",
        ]
        table.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
        material.extend(
            [
                *table,
                "",
                "### Actual environment files",
                "",
                "| Path | Destination | Bytes | Digest |",
                "| --- | --- | --- | --- |",
            ]
        )
        heading.extend(
            [
                *table,
                "",
                "See the [materialization index](03-materialized/INDEX.md) "
                "for actual file paths and evidence limits.",
                "",
            ]
        )
        for manifest in manifests:
            for file in manifest.get("files", []):
                material.append(
                    "| "
                    + " | ".join(
                        cell(file.get(key)) for key in ("path", "destination", "bytes", "digest")
                    )
                    + " |"
                )
        if not manifests:
            material.append("No unit-linked materialization files observed.")
        material.extend(
            [
                "",
                "File metadata proves recorded path/digest/length, not that contents "
                "were read. Actual tool/backend reads belong in transcript/output evidence.",
                "",
            ]
        )
    (destination / "02-effective-run-config.md").write_text("\n".join(heading), encoding="utf-8")
    (destination / "03-materialized/INDEX.md").write_text("\n".join(material), encoding="utf-8")
