"""Exact catalog schemas survive compilation and qualify the fresh launch guard."""

import pytest

from mission_control.application.authoring.completion_support import completion_support_issues
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import MCPToolDefinition, StageGraphBlueprint
from mission_control.domain.authoring.manifest import Behavior, parse_manifest
from mission_control.domain.authoring.manifest_lowering import lower_mission
from mission_control.domain.authoring.mission_definition import (
    AcceptanceExpression,
    manifest_to_definitions,
)
from tests.unit.authoring.test_manifest_compile import AT, minimal, scope, service, text
from tests.unit.authoring.test_manifest_launch_inputs import admitted, pubmed_resolver

SCHEMA = {"type": "object", "required": ["count"], "properties": {"count": {"type": "integer"}}}


async def catalog_schema(definitions, *, schema=SCHEMA):
    source = next(
        row.definition
        for row in await definitions.list_published_definitions()
        if isinstance(row.definition, MCPToolDefinition)
    )
    tool = source.model_copy(
        update={"logical_id": "tool.validated_report", "output_schema": schema}
    )
    await definitions.publish(tool, "fixture", AT, 0)


def authored():
    document = minimal()
    for node in document["mission"]["program"]["nodes"]:
        node["outputs"][0]["schema"] = "tool.validated_report@1"
    document["mission"]["goals"][0]["criteria"][0]["acceptance"] = {
        "schema": "tool.validated_report@1"
    }
    return document


@pytest.mark.asyncio
async def test_exact_catalog_schema_is_frozen_and_qualifies_launch():
    compiler, definitions, _ = await service(catalog_schema)
    document = authored()
    definition = manifest_to_definitions(parse_manifest(document), document)[0]
    schemas = await compiler._output_schemas(definition)
    lowered = lower_mission(definition, output_schemas=schemas)
    assert isinstance(lowered.blueprint, StageGraphBlueprint)
    assert completion_support_issues(definition, lowered.blueprint) == ()
    pinned = lowered.blueprint.stages[-1].output_slots[0].validation_schema
    assert pinned is not None and pinned.json_schema == SCHEMA
    assert pinned.schema_digest == sha256_digest(SCHEMA)
    assert lowered.blueprint.stages[-1].schema_criteria[0].obligation_ref == "evidence_map"
    result = await compiler.compile(text(document), scope())
    assert result.ok, result.report.blockers
    templates = pubmed_resolver(result.definitions[0]).stage_templates(
        result.definitions[0], admitted(result.programs[0])
    )
    for template in templates.values():
        segment = template.prompt_segments[-1]
        assert "tool.validated_report@1" in segment.content
        assert "output_bindings" in segment.content
        assert segment.rendered_digest == sha256_digest(segment.content)
    # A later tool revision cannot alter the explicitly referenced revision or its compiler id.
    source = next(
        row.definition
        for row in await definitions.list_published_definitions()
        if row.ref.logical_id == "tool.validated_report"
    )
    await definitions.publish(
        source.model_copy(update={"output_schema": {"type": "array"}}), "fixture", AT, 1
    )
    again = lower_mission(definition, output_schemas=await compiler._output_schemas(definition))
    assert again.blueprint_digest == lowered.blueprint_digest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "schema", [{"$ref": "https://example.com/schema"}, {"type": "string", "pattern": ".*"}]
)
async def test_unqualified_catalog_schema_never_unlocks_launch(schema):
    async def publish(definitions):
        await catalog_schema(definitions, schema=schema)

    compiler, _, _ = await service(publish)
    document = authored()
    definition = manifest_to_definitions(parse_manifest(document), document)[0]
    schemas = await compiler._output_schemas(definition)
    assert schemas == {}
    lowered = lower_mission(definition, output_schemas=schemas)
    assert completion_support_issues(definition, lowered.blueprint)


@pytest.mark.asyncio
async def test_unknown_domain_schema_is_not_inferred_from_unrelated_tool():
    compiler, _, _ = await service(catalog_schema)
    document = minimal()
    definition = manifest_to_definitions(parse_manifest(document), document)[0]
    assert await compiler._output_schemas(definition) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("output_count", [1, 2])
async def test_goal_loop_freezes_declared_outputs_and_criteria(output_count):
    compiler, _, _ = await service(catalog_schema)
    document = authored()
    definition = manifest_to_definitions(parse_manifest(document), document)[0]
    output = definition.program.nodes[-1].outputs[0]
    root = definition.program.model_copy(
        update={
            "behavior": Behavior.GOAL_LOOP,
            "nodes": (),
            "outputs": (output,)
            if output_count == 1
            else (output, output.model_copy(update={"name": "secondary_report"})),
            "completion": AcceptanceExpression(op="schema", schema_ref=output.schema_ref),
        }
    )
    definition = definition.model_copy(update={"program": root})
    lowered = lower_mission(definition, output_schemas=await compiler._output_schemas(definition))
    assert completion_support_issues(definition, lowered.blueprint) == ()
    assert lowered.blueprint.output_slots[0].validation_schema.json_schema == SCHEMA
    assert len(lowered.blueprint.schema_criteria) == 2
    assert len(lowered.blueprint.output_slots) == output_count


@pytest.mark.asyncio
async def test_production_artifact_schema_compiles_and_pins_exact_revision():
    from tests.unit.capability.test_artifact_schema_seeds import production_record

    record = production_record()

    # The ordinary catalog fixture loads the real committed production seed.
    compiler, definitions, _ = await service()
    document = authored()
    for node in document["mission"]["program"]["nodes"]:
        node["outputs"][0]["schema"] = "schema.s0-probe-report@1"
        node["outputs"][0]["enforcement"] = "required"
    document["mission"]["goals"][0]["criteria"][0]["acceptance"] = {
        "schema": "schema.s0-probe-report@1"
    }
    result = await compiler.compile(text(document), scope())
    assert result.ok, result.report.blockers
    definition = manifest_to_definitions(parse_manifest(document), document)[0]
    schemas = await compiler._output_schemas(definition)
    binding = schemas["schema.s0-probe-report@1"]
    assert binding.source_digest == record.ref.digest
    assert binding.schema_digest == sha256_digest(record.definition.json_schema)
    lowered = lower_mission(definition, output_schemas=schemas)
    await definitions.publish(
        record.definition.model_copy(update={"json_schema": {"type": "array"}}),
        record.published_by,
        record.published_at,
        1,
    )
    again = lower_mission(definition, output_schemas=await compiler._output_schemas(definition))
    assert again.blueprint_digest == lowered.blueprint_digest
    document["mission"]["program"]["nodes"][0]["outputs"][0]["schema"] = "schema.absent@1"
    refused = await compiler.compile(text(document), scope())
    # Compilation preserves unresolved authority; the fresh-start materialization
    # boundary calls this same check before creating a provider session.
    issues = completion_support_issues(
        refused.definitions[0], admitted(refused.programs[0]).blueprint
    )
    assert any(issue.reason == "output_schema_validator_unavailable" for issue in issues)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["retired", "digest_mismatch", "wrong_kind"])
async def test_artifact_schema_authority_refuses_invalid_catalog_rows(case):
    from unittest.mock import AsyncMock

    from tests.unit.capability.test_artifact_schema_seeds import production_record

    compiler, _, _ = await service()
    record = production_record()
    document = authored()
    for node in document["mission"]["program"]["nodes"]:
        node["outputs"][0]["schema"] = "schema.s0-probe-report@1"
        node["outputs"][0]["enforcement"] = "required"
    definition = manifest_to_definitions(parse_manifest(document), document)[0]
    if case == "retired":
        record = record.model_copy(update={"retired_at": AT})
    elif case == "digest_mismatch":
        record = record.model_copy(
            update={"ref": record.ref.model_copy(update={"digest": "sha256:" + "0" * 64})}
        )
    else:
        record = record.model_copy(
            update={
                "definition": next(
                    row.definition
                    for row in await compiler._definitions.list_published_definitions()
                    if isinstance(row.definition, StageGraphBlueprint)
                )
            }
        )
    compiler._definitions = AsyncMock(list_published_definitions=AsyncMock(return_value=(record,)))
    if case == "digest_mismatch":
        with pytest.raises(ValueError, match="invalid digest"):
            await compiler._output_schemas(definition)
    else:
        assert await compiler._output_schemas(definition) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse", [False, True])
async def test_same_schema_reference_from_two_kinds_is_ambiguous_in_both_orders(reverse):
    from unittest.mock import AsyncMock

    from mission_control.domain.authoring.contracts import DefinitionKind
    from tests.unit.capability.test_artifact_schema_seeds import production_record

    compiler, _, _ = await service()
    artifact = production_record()
    source = next(
        row
        for row in await compiler._definitions.list_published_definitions()
        if isinstance(row.definition, MCPToolDefinition)
    )
    tool = source.definition.model_copy(
        update={
            "logical_id": artifact.ref.logical_id,
            "output_schema": artifact.definition.json_schema,
        }
    )
    other = source.model_copy(
        update={
            "definition": tool,
            "ref": artifact.ref.model_copy(
                update={
                    "kind": DefinitionKind.MCP_TOOL,
                    "digest": sha256_digest(tool),
                }
            ),
        }
    )
    rows = (artifact, other) if not reverse else (other, artifact)
    compiler._definitions = AsyncMock(list_published_definitions=AsyncMock(return_value=rows))
    document = authored()
    for node in document["mission"]["program"]["nodes"]:
        node["outputs"][0]["schema"] = "schema.s0-probe-report@1"
    definition = manifest_to_definitions(parse_manifest(document), document)[0]
    with pytest.raises(ValueError, match="ambiguous authority"):
        await compiler._output_schemas(definition)
