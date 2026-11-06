"""Authored node text survives production templates without gaining prompt authority."""

from typing import Any

import pytest

from mission_control.application.agentic_components.placement import operating_contract, turn_text
from mission_control.application.authoring.cursor_launch import (
    cursor_projection,
    cursor_projection_digests,
)
from mission_control.application.authoring.manifest_launch_inputs import ManifestLaunchBindingError
from mission_control.application.authoring.provider_launch import materialization_digest
from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
)
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import PromptTrustClass
from mission_control.domain.execution.lanes import CursorExecutionBinding
from tests.unit.authoring.test_manifest_v2_launch import (
    compiled_ok,
    edited,
    example,
    templates_of,
)

DIAGNOSTIC = (
    "This is a bounded synthetic control diagnostic. Make exactly one shell tool call "
    "that reads AGENTS.md and then sleeps for 30 seconds."
)


@pytest.mark.parametrize("profile", ["codex", "claude_agent_sdk", "cursor_local"])
def test_stage_instructions_reach_turns_and_keep_objectives_and_projection_seals(
    profile: str,
) -> None:
    def diagnostic(document: dict[str, Any]) -> None:
        document["mission"]["program"]["nodes"][0]["instruction"] = DIAGNOSTIC

    compilation = compiled_ok(edited(example(profile, "stage-graph"), diagnostic))
    definition, program = compilation.definitions[0], compilation.programs[0]
    templates = templates_of(program, definition, None)
    nodes = {node.key: node for node in definition.program.nodes}
    runtimes = set()
    for key, template in templates.items():
        node = nodes[key.split("/", 1)[0]]
        instruction = node.body["instruction"]
        segments = [
            item
            for item in template.prompt_segments
            if item.source_ref == f"input:{node.pointer}/instruction"
        ]
        assert len(segments) == 1
        segment = segments[0]
        assert segment.content == instruction
        assert segment.source_revision == 1
        assert segment.trust_class is PromptTrustClass.ADMITTED_INPUT
        assert segment.rendered_digest == sha256_digest(instruction)
        # The goal objective is retained independently, with the same input provenance.
        objective = template.prompt_segments[0]
        assert objective.source_ref == f"input:{node.pointer}"
        assert objective.trust_class is PromptTrustClass.ADMITTED_INPUT
        assert f"stage {node.key}:" in objective.content
        assert instruction in turn_text(template)
        assert instruction not in operating_contract(template)
        runtimes.add(template.execution_runtime)
        if ProviderExecutionBinding.carried_by(template) is not None:
            binding = ProviderExecutionBinding.carried_by(template)
            assert binding.materialization_digest == materialization_digest(
                (), binding.lane_profile, template.prompt_segments, projectors=HOST_PROJECTORS
            )
        if CursorExecutionBinding.carried_by(template) is not None:
            binding = CursorExecutionBinding.carried_by(template)
            digests = cursor_projection_digests(
                cursor_projection(
                    (), binding.lane_profile, template.prompt_segments, projectors=HOST_PROJECTORS
                )
            )
            for name, value in digests.items():
                assert getattr(binding.projections, name) == value
    assert "deep_agent" in runtimes


def test_changing_only_stage_instruction_changes_its_digest_and_preserves_objective() -> None:
    def authored(text: str) -> Any:
        def change(document: dict[str, Any]) -> None:
            document["mission"]["program"]["nodes"][0]["instruction"] = text

        compilation = compiled_ok(edited(example("codex", "stage-graph"), change))
        return templates_of(compilation.programs[0], compilation.definitions[0], None)

    first = authored(DIAGNOSTIC)
    second = authored(DIAGNOSTIC + " Stop after the one call.")
    key = next(iter(first))
    assert first[key].prompt_segments[0] == second[key].prompt_segments[0]
    before = first[key].prompt_segments[1]
    after = second[key].prompt_segments[1]
    assert before.source_ref == after.source_ref
    assert before.rendered_digest != after.rendered_digest
    assert before.content in turn_text(first[key])
    assert after.content in turn_text(second[key])
    first_binding = ProviderExecutionBinding.carried_by(first[key])
    second_binding = ProviderExecutionBinding.carried_by(second[key])
    assert first_binding is not None and second_binding is not None
    first_operation = bind_operation_execution_request(first[key])
    second_operation = bind_operation_execution_request(second[key])
    assert first_operation.request_fingerprint != second_operation.request_fingerprint
    assert first_operation.prompt_sources != second_operation.prompt_sources
    # Admitted input changes the frozen operation, not the privileged file overlay.
    assert first_binding.materialization_digest == second_binding.materialization_digest


def test_empty_agent_executor_instruction_fails_at_its_manifest_pointer() -> None:
    compilation = compiled_ok(example("codex", "stage-graph").read_text(encoding="utf-8"))
    definition, program = compilation.definitions[0], compilation.programs[0]
    node = definition.program.nodes[0]
    stripped = node.model_copy(update={"body": {**node.body, "instruction": ""}})
    definition = definition.model_copy(
        update={
            "program": definition.program.model_copy(
                update={"nodes": (stripped, *definition.program.nodes[1:])}
            )
        }
    )
    with pytest.raises(ManifestLaunchBindingError) as error:
        templates_of(program, definition, None)
    assert error.value.pointer == f"{node.pointer}/instruction"


def test_legacy_stage_without_instruction_keeps_the_original_prompt_bytes() -> None:
    compilation = compiled_ok(example("codex", "stage-graph").read_text(encoding="utf-8"))
    definition, program = compilation.definitions[0], compilation.programs[0]
    node = definition.program.nodes[0]
    stripped = node.model_copy(
        update={"body": {name: value for name, value in node.body.items() if name != "instruction"}}
    )
    definition = definition.model_copy(
        update={
            "program": definition.program.model_copy(
                update={"nodes": (stripped, *definition.program.nodes[1:])}
            )
        }
    )
    templates = templates_of(program, definition, None)
    template = next(value for key, value in templates.items() if key.startswith(node.key + "/"))
    assert len(template.prompt_segments) == 1
    objective = template.prompt_segments[0]
    assert objective.source_ref == f"input:{node.pointer}"
    assert objective.trust_class is PromptTrustClass.ADMITTED_INPUT
    assert objective.rendered_digest == sha256_digest(objective.content)
    assert turn_text(template).endswith(objective.content)


@pytest.mark.parametrize("profile", ["codex", "claude_agent_sdk", "cursor_local"])
def test_a_session_lane_output_contract_names_its_outputs_file_not_a_custody_tool(
    profile: str,
) -> None:
    """P5c: a Session Lane has no artifact custody tool; its stage output contract names the
    lease-relative `outputs/<slot>.json` its lane registers. Deep Agents keeps its text."""

    from dataclasses import replace

    from mission_control.application.authoring.manifest_launch_inputs import AdmittedLaunch
    from mission_control.domain.execution.contracts import SESSION_LANE_RUNTIMES
    from mission_control.domain.programs.completion import OutputSchemaBinding
    from tests.unit.authoring.test_manifest_v2_launch import SCOPE, resolver

    schema: dict[str, object] = {"type": "object"}
    binding = OutputSchemaBinding(
        schema_ref="schema.sdlc-diagnosis-report@1",
        source_digest=sha256_digest("source"),
        schema_digest=sha256_digest(schema),
        json_schema=schema,
    )
    compilation = compiled_ok(example(profile, "stage-graph").read_text(encoding="utf-8"))
    definition, program = compilation.definitions[0], compilation.programs[0]
    admitted = AdmittedLaunch.from_configuration(SCOPE, "run-v2", program.configuration)
    blueprint = admitted.blueprint
    stages = tuple(
        stage.model_copy(
            update={
                "output_slots": tuple(
                    slot.model_copy(update={"validation_schema": binding})
                    for slot in stage.output_slots
                )
            }
        )
        for stage in blueprint.stages
    )
    admitted = replace(admitted, blueprint=blueprint.model_copy(update={"stages": stages}))
    templates = resolver().stage_templates(definition, admitted)
    runtimes = set()
    for key, template in templates.items():
        stage = next(item for item in stages if item.stage_id == key.split("/", 1)[0])
        (segment,) = [
            item
            for item in template.prompt_segments
            if item.source_ref == f"input:stage-output-contract:{stage.stage_id}"
        ]
        assert segment.trust_class is PromptTrustClass.ADMITTED_INPUT
        assert segment.rendered_digest == sha256_digest(segment.content)
        assert segment.content.startswith("Declared output contract: ")
        runtimes.add(template.execution_runtime)
        if template.execution_runtime in SESSION_LANE_RUNTIMES:
            for slot in stage.output_slots:
                assert f"{slot.output_slot_id} -> outputs/{slot.output_slot_id}.json" in (
                    segment.content
                )
            assert '"output_refs": [] and no output_bindings' in segment.content
            assert "artifact custody tools" not in segment.content
            assert segment.content in turn_text(template)
        else:
            assert (
                "Publish the JSON artifact bytes using the available artifact custody tools."
                in (segment.content)
            )
            assert "outputs/" not in segment.content
    assert "deep_agent" in runtimes and runtimes & SESSION_LANE_RUNTIMES
