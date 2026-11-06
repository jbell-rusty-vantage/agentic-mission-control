"""The knowledge tools from the capability catalog to a mission's node bindings (SV-16 item 3).

`mc.catalog.knowledge-tools@1.1.0` publishes six catalog `tool` rows; a coordinator-authored
manifest names them as `{search: ..., kind: tool, as: ...}` (ADR-0020/0023); compile pins the
exact rows; the deployment's launch bindings map each pinned digest to the exact Deep Agents
tool component the worker registers (`knowledge_launch_bindings`); the launch path puts the
components into each node's binding, and the Deep Agents lane receipts them as `kind: tool`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from mission_control.adapters.deep_agents.knowledge_tools import (
    knowledge_capability_id,
    knowledge_launch_bindings,
    knowledge_registry_tools,
    knowledge_tool_components,
    knowledge_tools,
)
from mission_control.application.knowledge.toolset import TOOL_NAMES
from mission_control.domain.authoring.contracts import DefinitionKind
from mission_control.domain.execution.contracts import DeepAgentExecutionBinding
from tests.fixtures.mission_control_common_db import canonical_scope
from tests.unit.authoring.manifest_launch_fixture import fixture_bindings
from tests.unit.authoring.test_manifest_launch_inputs import (
    admitted,
    compile_programs,
    fixture_served,
    resolver,
)

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "tests/fixtures/manifests/knowledge-tools-stage-graph.yml"
SEED = (
    ROOT / "packages/mission-control-db-contract/seeds/common/mc.catalog.knowledge-tools-1.2.0.json"
)
SCOPE = canonical_scope("tenant-1", "ai-engineer")


def test_the_seed_publishes_seven_catalog_tool_rows() -> None:
    bundle = json.loads(SEED.read_text(encoding="utf-8"))
    rows = [
        record["fields"]["manifest"]
        for record in bundle["records"]
        if record["kind"] == "asset_version"
    ]
    assert {row["ref"]["logical_id"] for row in rows} == {
        knowledge_capability_id(name) for name in TOOL_NAMES
    }
    assert {row["ref"]["kind"] for row in rows} == {DefinitionKind.TOOL.value}
    assert {row["definition"]["capability_kind"] for row in rows} == {"tool"}
    assert all(
        record["fields"]["kind"] == "tool"
        for record in bundle["records"]
        if record["kind"] == "asset_version"
    )
    text = json.dumps(bundle)
    assert "KNOWLEDGE_" not in text and "4310" not in text  # no deployment settings in rows


@pytest.fixture(scope="module")
def compiled() -> tuple[Any, Any]:
    import asyncio

    definitions, programs = asyncio.run(
        compile_programs(MANIFEST.read_text(encoding="utf-8"), scope=SCOPE)
    )
    return definitions[0], programs[0]


def test_a_manifest_binds_the_catalog_tools_into_its_node_bindings(
    compiled: tuple[Any, Any],
) -> None:
    definition, program = compiled
    pins = {
        item.resolved.capability_id: item.resolved.digest
        for item in definition.capabilities
        if item.resolved is not None
    }
    assert set(pins) == {knowledge_capability_id(name) for name in TOOL_NAMES}

    tools = knowledge_tools(cast(Any, None))
    bindings = fixture_bindings().model_copy(
        update={"capabilities": knowledge_launch_bindings(pins, tools)}
    )
    served = fixture_served(bindings)
    from dataclasses import replace

    served = replace(served, tools=served.tools | frozenset(knowledge_registry_tools(tools)))
    templates = resolver(bindings, served=served).stage_templates(
        definition, admitted(program, scope=SCOPE)
    )
    components = {item.tool_name: item for item in knowledge_tool_components(tools)}
    by_stage = {
        name.split("/", 1)[0]: DeepAgentExecutionBinding.carried_by(template)
        for name, template in templates.items()
    }
    draft, review = by_stage["draft"], by_stage["review"]
    assert draft is not None and review is not None
    # Mission-level capabilities reach every agent node of the program.
    assert {tool.tool_name for tool in draft.tools} == set(TOOL_NAMES)
    assert {tool.tool_name for tool in review.tools} == set(TOOL_NAMES)
    for tool in (*draft.tools, *review.tools):
        assert tool == components[tool.tool_name]  # exactly the registered component
    # Receipted like every host tool in the sealed binding.
    receipt = draft.materialization_receipt
    assert receipt is not None
    assert {
        (item.kind, item.name, item.verdict) for item in receipt.items if item.kind == "tool"
    } == {("tool", tool.tool_name, "native") for tool in draft.tools}


def test_an_unbound_catalog_tool_is_a_pointed_launch_refusal(compiled: tuple[Any, Any]) -> None:
    from mission_control.application.authoring.manifest_launch_inputs import (
        ManifestLaunchBindingError,
    )

    definition, program = compiled
    with pytest.raises(ManifestLaunchBindingError, match="no deployment component binding"):
        resolver(fixture_bindings()).stage_templates(definition, admitted(program, scope=SCOPE))


def test_a_named_schema_output_contract_names_submit_output_not_custody_tools(
    compiled: tuple[Any, Any],
) -> None:
    """L1-07 (E3 `check`): a Deep Agents stage that submits its schema outputs through
    `submit_output` is told that act, with the exact obligation key and an inline structured
    value, never "artifact custody tools" (no such tool is mounted on this lane)."""

    definition, program = compiled
    pins = {
        item.resolved.capability_id: item.resolved.digest
        for item in definition.capabilities
        if item.resolved is not None
    }
    tools = knowledge_tools(cast(Any, None))
    bindings = fixture_bindings().model_copy(
        update={"capabilities": knowledge_launch_bindings(pins, tools)}
    )
    from dataclasses import replace

    served = fixture_served(bindings)
    served = replace(served, tools=served.tools | frozenset(knowledge_registry_tools(tools)))
    launch = admitted(program, scope=SCOPE)
    assert launch.blueprint.output_promises is not None
    from mission_control.domain.authoring.canonical import sha256_digest
    from mission_control.domain.programs.completion import OutputSchemaBinding

    schema: dict[str, object] = {"type": "object"}
    binding = OutputSchemaBinding(
        schema_ref="claim_table@1",
        source_digest=sha256_digest("source"),
        schema_digest=sha256_digest(schema),
        json_schema=schema,
    )
    stages = tuple(
        stage.model_copy(
            update={
                "output_slots": tuple(
                    slot.model_copy(update={"validation_schema": binding})
                    for slot in stage.output_slots
                )
            }
        )
        for stage in launch.blueprint.stages
    )
    launch = replace(launch, blueprint=launch.blueprint.model_copy(update={"stages": stages}))
    templates = resolver(bindings, served=served).stage_templates(definition, launch)
    seen = set()
    for key, template in templates.items():
        stage_id = key.split("/", 1)[0]
        segments = [
            item
            for item in template.prompt_segments
            if item.source_ref == f"input:stage-output-contract:{stage_id}"
        ]
        if not segments:
            continue
        (segment,) = segments
        slot = {"draft": "report", "review": "review"}[stage_id]
        assert "artifact custody tools" not in segment.content
        assert "submit_output" in segment.content
        assert f"obligation {stage_id}.{slot}" in segment.content
        assert '"kind": "inline"' in segment.content and "value" in segment.content
        assert "output_refs" not in segment.content.split("\n", 1)[1]
        seen.add(stage_id)
    assert seen == {"draft", "review"}
