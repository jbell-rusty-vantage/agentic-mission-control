"""Every launch template carries its node's Purpose Card, on every lane.

The launch author builds one card per node role from the committed definition and freezes it
in the template as the host's instruction segment. The Deep Agents lane puts it at the top of
the system prompt; the file lanes and the hosted lanes read it through the same instruction
channel (the Instruction Overlay's operating contract). A fork keeps it. No database, no
network: the real compile and the real launch resolver over the fixture catalog.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from mission_control.adapters.deep_agents.adapter import _prompts
from mission_control.application.agentic_components.placement import (
    MISSION_CONTEXT_POINTER,
    operating_contract,
    turn_text,
)
from mission_control.application.authoring.capability_summaries import CatalogCapabilitySummaries
from mission_control.application.authoring.manifest_launch_inputs import (
    node_purpose_card,
    purpose_card_pins,
)
from mission_control.application.authoring.provider_launch import materialization_digest
from mission_control.application.execution.operations.operation_execution import (
    bind_operation_execution_request,
)
from mission_control.application.guide.mission_templates import load_template
from mission_control.application.programs.fork_templates import StageGraphForkTemplateDerivation
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import (
    PURPOSE_CARD_SOURCE_REF,
    PromptTrustClass,
    is_purpose_card,
    purpose_card_problem,
    purpose_card_segment,
)
from mission_control.domain.policies.forks import stage_objective_path
from tests.support.operations import DIGEST, operation_request
from tests.unit.authoring.test_manifest_compile import scope, service
from tests.unit.authoring.test_manifest_v2_launch import (
    compiled_ok,
    edited,
    example,
    templates_of,
)
from tests.unit.authoring.test_mission_brief import BRIEF
from tests.unit.guide.support import SANDBOXES
from tests.unit.orchestration.test_fork_templates import MemoryTemplates, _patch

HOST_LINE = (
    "BellLabs authority, budgets, lifecycle, and artifact admission remain host-owned. "
    "Use only the exact attached tools, Skills, MCP surface, and writable workspace slots."
)


def cards(template: Any) -> list[Any]:
    return [segment for segment in template.prompt_segments if is_purpose_card(segment)]


def with_brief(document: dict[str, Any]) -> None:
    document["mission"]["brief"] = dict(BRIEF)


# -- the template segment, lane by lane ----------------------------------------------------------


@pytest.mark.parametrize("profile", ["codex", "claude_agent_sdk", "cursor_local"])
def test_every_stage_template_carries_its_nodes_card_in_the_instruction_channel(
    profile: str,
) -> None:
    compilation = compiled_ok(edited(example(profile, "stage-graph"), with_brief))
    definition, program = compilation.definitions[0], compilation.programs[0]
    root = definition.program
    nodes = {node.key: node for node in root.nodes}

    templates = templates_of(program, definition, None)

    runtimes = set()
    for key, template in templates.items():
        node = nodes[key.split("/", 1)[0]]
        (card,) = cards(template)
        # The one pure function, the node's sealed facts: the same segment.
        assert card == node_purpose_card(definition, (root, node), verifier=False)
        assert card.source_ref == PURPOSE_CARD_SOURCE_REF
        assert card.trust_class is PromptTrustClass.AUTHORED_INSTRUCTION
        assert purpose_card_problem(template.prompt_segments) is None
        text = card.content
        assert f"- Node `{node.key}`, behaviour `agent_executor`, in the `stage_graph` `root`." in (
            text
        )
        assert "- Purpose: system (improving the system itself)\n" in text
        assert f"```data source=brief.request trust=admitted_input\n{BRIEF['request']}\n```" in text
        # The objective and the node's own instruction stay admitted input, in their places.
        assert template.prompt_segments[0].source_ref == f"input:{node.pointer}"
        assert all(
            segment.trust_class is PromptTrustClass.ADMITTED_INPUT
            for segment in template.prompt_segments
            if segment is not card
        )
        # The lanes' instruction channel: the card, then the pointer at the packet on disk.
        assert operating_contract(template) == f"{text}\n\n{MISSION_CONTEXT_POINTER}"
        assert text not in turn_text(template) and node.body["instruction"] in turn_text(template)
        # Recorded with the node's sealed facts: the frozen operation's prompt sources.
        assert (
            PURPOSE_CARD_SOURCE_REF,
            1,
            PromptTrustClass.AUTHORED_INSTRUCTION,
            card.rendered_digest,
        ) in bind_operation_execution_request(template).prompt_sources
        binding = ProviderExecutionBinding.carried_by(template)
        if binding is not None:
            # The sealed file-lane projection renders the overlay with the card in it.
            assert binding.materialization_digest == materialization_digest(
                (), binding.lane_profile, template.prompt_segments, projectors=HOST_PROJECTORS
            )
        runtimes.add(template.execution_runtime)
    # One card per agent stage, on whichever lane the stage runs.
    assert {key.split("/", 1)[0] for key in templates} == set(nodes) and runtimes


def test_deep_agents_puts_the_card_at_the_top_of_the_system_prompt() -> None:
    compilation = compiled_ok(edited(example("codex", "stage-graph"), with_brief))
    definition, program = compilation.definitions[0], compilation.programs[0]
    templates = templates_of(program, definition, None)
    (template,) = [item for item in templates.values() if item.execution_runtime == "deep_agent"]
    (card,) = cards(template)

    system, user = _prompts(SimpleNamespace(prompt_segments=template.prompt_segments))  # type: ignore[arg-type]

    # The card first, the fixed host-authority line last; nothing admitted in between.
    assert system == f"{card.content}\n\n{HOST_LINE}"
    assert system.startswith("# Purpose card\n")
    assert card.content not in user
    assert user.startswith(template.prompt_segments[0].content)
    # A published instruction segment keeps its place after the card.
    published = operation_request().prompt_segments[0]
    mixed = SimpleNamespace(prompt_segments=(published, *template.prompt_segments))
    system, _user = _prompts(mixed)  # type: ignore[arg-type]
    assert system == f"{card.content}\n\n{published.content}\n\n{HOST_LINE}"


def test_a_goal_loop_gets_one_card_per_role() -> None:
    compilation = compiled_ok(edited(example("codex", "goal-loop"), with_brief))
    definition, program = compilation.definitions[0], compilation.programs[0]

    templates = templates_of(program, definition, None)

    (executor,) = cards(templates["executor"])
    (verifier,) = cards(templates["verifier"])
    root = definition.program
    assert executor == node_purpose_card(definition, (root,), verifier=False)
    assert verifier == node_purpose_card(definition, (root,), verifier=True)
    assert "role executor: you do the work of each iteration." in executor.content
    assert "role verifier: you judge the executor's work and do not do it." in verifier.content
    assert executor.rendered_digest != verifier.rendered_digest


def test_a_mission_without_a_brief_still_gets_a_card() -> None:
    compilation = compiled_ok(example("codex", "stage-graph").read_text(encoding="utf-8"))
    definition, program = compilation.definitions[0], compilation.programs[0]

    templates = templates_of(program, definition, None)

    for template in templates.values():
        (card,) = cards(template)
        assert f'- Mission: "{definition.title}"\n\n## Your part\n' in card.content
        assert "Purpose:" not in card.content


# -- what the node was given ---------------------------------------------------------------------


async def _compiled(template_id: str) -> tuple[Any, Any]:
    template = load_template(template_id)
    values = template.examples() | {
        "application_id": "ai-engineer",
        "sandbox_profile": next(iter(SANDBOXES)),
    }
    compile_service, definitions, _ = await service()
    compilation = await compile_service.compile(template.fill(values), scope("ai-engineer"))
    assert compilation.ok, compilation.report.blockers
    return compilation.definitions[0], definitions


@pytest.mark.asyncio
async def test_the_card_lists_each_bound_capability_with_its_catalog_line() -> None:
    definition, definitions = await _compiled("smallest")
    root = definition.program
    pins = purpose_card_pins(definition)

    summaries = await CatalogCapabilitySummaries(definitions)(pins)
    card = node_purpose_card(definition, (root, root.nodes[0]), verifier=False, summaries=summaries)

    (pin,) = pins
    assert pin.startswith("tool.knowledge-submit-output@") and "#sha256:" in pin
    (published,) = [
        row
        for row in await definitions.list_published_definitions()
        if row.ref.logical_id == "tool.knowledge-submit-output" and pin.endswith(row.ref.digest)
    ]
    # The description of the exact pinned revision: a sealed fact, read by pin.
    assert summaries == {pin: published.definition.description}
    line = next(item for item in card.content.splitlines() if item.startswith("- tool "))
    name, _, quoted = line.partition(": ")
    assert name == "- tool `submit_output`"
    described = " ".join(summaries[pin].split())
    assert described.startswith(json.loads(quoted).removesuffix("..."))
    # Without the catalog the capability is listed by name alone.
    bare = node_purpose_card(definition, (root, root.nodes[0]), verifier=False)
    assert "- tool `submit_output`\n" in bare.content
    # A pin the catalog does not hold, or text that is no exact pin, is left out.
    assert (
        await CatalogCapabilitySummaries(definitions)(
            ["tool.nowhere@1.0.0#sha256:" + "0" * 64, "not a pin"]
        )
        == {}
    )


@pytest.mark.asyncio
async def test_an_independent_verifier_is_not_told_it_has_the_producer_tools() -> None:
    definition, _definitions = await _compiled("research-report")
    root = definition.program

    executor = node_purpose_card(definition, (root,), verifier=False).content
    verifier = node_purpose_card(definition, (root,), verifier=True).content

    for alias in ("knowledge_search", "knowledge_read", "report_register", "submit_output"):
        assert f"- tool `{alias}`\n" in executor
    assert "- plugin `web_research`\n" in executor
    assert "- plugin `knowledge_cognition`\n" in executor
    assert "- plugin `code_research`\n" in executor
    # What the verifier is never given is not on its card.
    assert "- tool `knowledge_read`\n" in verifier
    assert "`report_register`" not in verifier and "`submit_output`" not in verifier
    assert "- Purpose: research (researching for the application)\n" in verifier
    # A plugin is one line: the members compile expanded from it are not listed again.
    given = executor.split("## What you were given\n", 1)[1].split("- Budget:", 1)[0]
    assert len(given.strip().splitlines()) == 7


# -- a fork keeps the card -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_fork_derives_the_same_card_from_the_same_sealed_facts() -> None:
    card = purpose_card_segment("# Purpose card\n\nWhy the mission exists.")
    source = {
        key: template.model_copy(update={"prompt_segments": (*template.prompt_segments, card)})
        for key, template in {
            "draft/execute/default": operation_request(prompt="draft"),
            "review/execute/default": operation_request(prompt="review"),
        }.items()
    }
    store = MemoryTemplates()
    store.stored[("tenant-1", "semantic-input:source")] = source

    await StageGraphForkTemplateDerivation(store).derive_stagegraph(
        request_scope="tenant-1",
        source_semantic_input_binding_ref="semantic-input:source",
        derived_semantic_input_binding_ref="semantic-input:fork:f1",
        patch=_patch((stage_objective_path("review"), "Review more strictly.")),
        expected_configuration_digest=DIGEST,
    )

    derived = store.stored[("tenant-1", "semantic-input:fork:f1")]
    for template in derived.values():
        assert cards(template) == [card]
        assert purpose_card_problem(template.prompt_segments) is None
    # The fork's own objective is admitted input after it; the card's digest is unchanged.
    patched = derived["review/execute/default"].prompt_segments
    assert patched[-1].source_ref == "fork-objective:review"
    assert patched[-2] == card
