"""The mission templates cannot drift from the compiler, and one source serves three surfaces.

Each template's slots are filled and the result is compiled by the real `ManifestCompileService`
against the seeded in-memory catalog the manifest compile tests use (no database, no network):
the compile is `ok` and a start would accept it. The same templates are the guide topic
`templates`, the `template:<id>` describe answer and the `template` facet of the search.
"""

from __future__ import annotations

import re

import pytest

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_service import (
    ManifestCompileService,
    ManifestProgramCompiler,
)
from mission_control.application.guide.mission_templates import (
    TEMPLATE_IDS,
    MissionTemplate,
    load_template,
    mission_templates,
    parse_template,
    template_markdown,
)
from mission_control.application.guide.service import GuideRefused
from mission_control.application.selection.workspace import SelectionSearchRequest
from mission_control.domain.authoring.brief import MissionBrief
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import load_manifest_yaml
from mission_control.domain.authoring.manifest_v2 import BRIEF_MISSING, MANIFEST_V2_LITERAL
from tests.architecture.test_package_boundaries import APPLICATION_NEEDLES
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.support.manifests.compile import scope, service
from tests.unit.guide.support import SANDBOXES, full_guide

# The application the fixture catalog compiles for; a template names none.
APPLICATION = "ai-engineer"
# What the owner asked for at the least, in the order a Coordinator meets them.
EXPECTED = ("smallest", "research-report", "staged-review", "system-improvement")
# The slots every template has (application id, goal text, criteria, budget, model profile).
COMMON_SLOTS = {
    "application_id",
    "mission_key",
    "title",
    "goal",
    "criterion",
    "model_profile",
    "sandbox_profile",
    "budget_usd",
}
# A template is application-neutral and installation-neutral: these values are the test's.
TEST_VALUES = {"application_id": APPLICATION, "sandbox_profile": next(iter(SANDBOXES))}
# The interview's result: the slots that fill a template's `brief` block.
BRIEF_SLOTS = {"request", "question", "answer", "done_means", "out_of_scope"}
# The purpose a template fixes where the kind of work is obvious; the others take a slot.
FIXED_PURPOSES = {"research-report": "research", "system-improvement": "system"}


def filled(template: MissionTemplate) -> str:
    """The template with its own example in every slot, for the test application."""

    return template.fill(template.examples() | TEST_VALUES)


def test_the_templates_are_the_curated_set_with_whole_headers() -> None:
    assert TEMPLATE_IDS == EXPECTED
    for template in mission_templates():
        assert template.ref == f"template:{template.id}"
        assert template.title and template.purpose and template.use_when and template.produces
        assert {slot.name for slot in template.slots} >= COMMON_SLOTS, template.id
        assert all(slot.description and slot.example for slot in template.slots)
        # A manifest of the current version, with the application as a slot.
        assert template.manifest.startswith(f"manifest: {MANIFEST_V2_LITERAL}\n")
        assert "application: {{application_id}}" in template.manifest


def test_a_template_names_no_application_and_pins_no_digest() -> None:
    for template in mission_templates():
        text = f"{template_markdown(template)} {template.examples()}"
        lowered = text.lower()
        assert not [needle for needle in APPLICATION_NEEDLES if needle in lowered], template.id
        # Written for a user of the service: no source paths, tickets or migrations.
        assert not re.search(r"\b(OVE|ADR|SPEC|FT|MP|OC)-[A-Z]?\d|\.py\b|src/", text), template.id
        # Capabilities follow the catalog: the latest admitted revision, never a digest.
        document = load_manifest_yaml(filled(template))
        environment = document["mission"]["environment"]
        entries = [*environment.get("capabilities", ()), *environment.get("plugins", ())]
        assert entries and all(entry["pin"].endswith("@latest") for entry in entries), template.id
        assert "sha256:" not in template.manifest


def test_every_template_carries_a_brief_in_the_users_words() -> None:
    for template in mission_templates():
        names = {slot.name for slot in template.slots}
        fixed = FIXED_PURPOSES.get(template.id)
        assert names >= BRIEF_SLOTS, template.id
        assert ("purpose" in names) == (fixed is None), template.id
        examples = template.examples()
        document = load_manifest_yaml(filled(template))
        brief = MissionBrief.model_validate(document["mission"]["brief"])
        assert brief.purpose.value == (fixed or examples["purpose"]), template.id
        assert brief.request == examples["request"]
        assert [(item.question, item.answer) for item in brief.answers] == [
            (examples["question"], examples["answer"])
        ]
        assert brief.done_means == examples["done_means"]
        assert brief.out_of_scope == (examples["out_of_scope"],)
        # An instruction says the task; the node's purpose card carries the rest (why the
        # mission exists, what the node owes and to whom, what it was given, when to stop).
        nodes = document["mission"]["program"].get("nodes", ())
        for node in nodes:
            if node["behavior"] == "agent_executor":
                assert "Stop after its receipt" not in node["instruction"], template.id
                assert f'"{node["key"]}.{node["outputs"][0]["name"]}"' in node["instruction"]


@pytest.mark.asyncio
@pytest.mark.parametrize("template_id", EXPECTED)
async def test_every_filled_template_compiles_and_would_start(template_id: str) -> None:
    template = load_template(template_id)
    compile_service, definitions, _ = await service()
    before = len(await definitions.list_published_definitions())

    compilation = await compile_service.compile(filled(template), scope(APPLICATION))

    report = compilation.report
    assert report.blockers == (), report.blockers
    assert compilation.ok
    # The brief is sealed in the definition and read back in the report; who asked is the
    # principal the compile ran for.
    (definition,) = compilation.definitions
    assert definition.brief is not None and definition.brief.requested_by == "owner"
    assert report.definitions[0].brief == definition.brief
    assert BRIEF_MISSING not in {item.reason for item in report.warnings}
    # A start refuses nothing the compile accepted: no acceptance without an evaluator.
    assert report.start_blockers == (), report.start_blockers
    assert report.startable is True
    # Every `@latest` pin resolved to an exact row of the seeded catalog.
    assert compilation.resolution is not None
    assert all(item.result is not None for item in compilation.resolution.resolved)
    # Compile persists nothing.
    assert len(await definitions.list_published_definitions()) == before


@pytest.mark.asyncio
async def test_the_smallest_template_is_one_agent_stage_and_a_review_gate() -> None:
    compile_service, _, _ = await service()
    compilation = await compile_service.compile(
        filled(load_template("smallest")), scope(APPLICATION)
    )

    (program,) = compilation.programs
    assert program.lowered.family == "StageGraph"
    blueprint = program.lowered.blueprint
    assert {stage.stage_id for stage in blueprint.stages} == {"write", "review"}  # type: ignore[union-attr]
    assert [wait.scope_id for wait in blueprint.waits] == ["review"]  # type: ignore[union-attr]
    document = load_manifest_yaml(filled(load_template("smallest")))
    environment = document["mission"]["environment"]
    assert environment["lane"] == "deep_agents"
    assert [node["behavior"] for node in document["mission"]["program"]["nodes"]] == [
        "agent_executor",
        "human_gate",
    ]


@pytest.mark.asyncio
async def test_the_research_report_reads_the_web_and_the_knowledge_base() -> None:
    compile_service, _, _ = await service()
    compilation = await compile_service.compile(
        filled(load_template("research-report")), scope(APPLICATION)
    )

    (program,) = compilation.programs
    assert program.lowered.family == "GoalDirected"
    assert compilation.resolution is not None
    resolved = {
        item.result.pin.split("@", 1)[0]
        for item in compilation.resolution.resolved
        if item.result is not None
    }
    assert {
        "plugin.web-research",
        "plugin.cognition-knowledge",
        "tool.knowledge-read-intent",
        "tool.knowledge-read",
        "tool.knowledge-report-register",
        "tool.knowledge-submit-output",
    } <= resolved
    # The goal carries the question, not a page of tool-call instructions.
    goal = load_manifest_yaml(filled(load_template("research-report")))["mission"]["goals"][0]
    assert len(goal["description"]) < 600 and "submit_output" not in goal["description"]


@pytest.mark.asyncio
async def test_the_research_report_mounts_the_method_skills_and_the_charter() -> None:
    """On one installation's catalog (its common and application seeds, every revision), the
    template's `plugin.cognition-knowledge@latest` is revision 4: the research mission mounts
    the imported research and evidence skills and the application's charter by exact pin, the
    charter once, none of the eight-line knowledge skills revision 1 carried, and the capture,
    GitHub and Context7 servers the method names."""

    definitions, search = await fast_track_catalog(directories=("common", APPLICATION))
    charter = f"skill.{APPLICATION}-knowledge-charter"
    compile_service = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
        charter_skills={APPLICATION: charter},
    )
    compilation = await compile_service.compile(
        filled(load_template("research-report")), scope(APPLICATION)
    )

    assert compilation.report.blockers == (), compilation.report.blockers
    assert compilation.report.startable is True
    assert compilation.resolution is not None
    resolved = [item for item in compilation.resolution.resolved if item.result is not None]
    by_id = {item.result.capability_id: item for item in resolved}
    assert by_id["plugin.cognition-knowledge"].result.version == "4"
    mounted = {"skill.knowledge-research", "skill.knowledge-verify", charter}
    assert mounted <= set(by_id)
    for logical_id in mounted:
        assert by_id[logical_id].provenance == "plugin:knowledge_cognition"
    # The method says "capture every source you rely on" and names Context7 and GitHub: the
    # same mission mounts the capture server (revision 3, supported on this lane) through the
    # knowledge plugin and both code research servers through theirs.
    capture = by_id["mcp.knowledge-capture"]
    assert capture.provenance == "plugin:knowledge_cognition"
    assert capture.result.exact_ref is not None and capture.result.exact_ref.revision == 3
    for logical_id in ("mcp.context7", "mcp.github"):
        assert by_id[logical_id].provenance == "plugin:code_research"
    # The compile-time charter mount finds the plugin's member and adds no second row.
    assert [item.result.capability_id for item in resolved].count(charter) == 1
    assert not {name for name in by_id if name.startswith("skill.mc-cognition-")}
    # Each mounted skill has the one catalog line a node's purpose card quotes.
    published = {
        item.ref.logical_id: item for item in await definitions.list_published_definitions()
    }
    for logical_id in mounted:
        description = published[logical_id].definition.description
        assert description and len(description.splitlines()) == 1


def test_fill_names_what_is_missing_and_what_is_unknown() -> None:
    template = load_template("smallest")
    values = template.examples()

    with pytest.raises(ValueError, match=r"slots without a value \['goal'\]"):
        template.fill({name: value for name, value in values.items() if name != "goal"})
    with pytest.raises(ValueError, match=r"values without a slot \['colour'\]"):
        template.fill(values | {"colour": "blue"})
    assert "{{" not in template.fill(values)


def test_a_malformed_template_is_refused() -> None:
    header = "id: x\ntitle: T\npurpose: P\nuse_when: U\nproduces: R\n"
    slot = "slots:\n  goal:\n    description: D\n    example: E\n"
    assert (
        parse_template(f"---\n{header}{slot}---\nmission: {{{{goal}}}}\n", expected_id="x").id
        == "x"
    )
    with pytest.raises(ValueError, match="no header"):
        parse_template("mission: {}", expected_id="x")
    with pytest.raises(ValueError, match="declares id"):
        parse_template(f"---\n{header}{slot}---\nmission: {{{{goal}}}}\n", expected_id="y")
    # The declared slots are exactly the slots the manifest uses.
    with pytest.raises(ValueError, match="its manifest uses"):
        parse_template(f"---\n{header}{slot}---\nmission: {{{{other}}}}\n", expected_id="x")
    with pytest.raises(ValueError, match="description and example"):
        parse_template(
            f"---\n{header}slots:\n  goal: D\n---\nmission: {{{{goal}}}}\n", expected_id="x"
        )
    with pytest.raises(KeyError):
        load_template("nowhere")


async def test_one_source_serves_the_topic_describe_and_search() -> None:
    guide = full_guide()
    topic = (await guide.topic("templates", "mcp")).markdown
    workflows = (await guide.topic("workflows", "mcp")).markdown

    for template in mission_templates():
        # The topic: one row per template with its purpose and when to use it.
        assert f"| `{template.id}` | {template.purpose} | {template.use_when} |" in topic
        assert f"`{template.id}`" in workflows
        # Describe: the Markdown an agent fills, and the same manifest as data.
        described = await guide.describe(template.ref)
        assert described.kind == "template" and described.title == template.title
        assert described.markdown == template_markdown(template)
        assert described.markdown is not None and described.markdown.startswith(
            f"# Template `{template.id}`"
        )
        assert f"```yaml\n{template.manifest.rstrip()}\n```" in described.markdown
        assert described.data["manifest_yaml"] == template.manifest
        assert [slot["name"] for slot in described.data["slots"]] == [
            slot.name for slot in template.slots
        ]
        for slot in template.slots:
            assert (
                f"| `{slot.name}` | {slot.description} | `{slot.example}` |" in described.markdown
            )
    assert '`mission_describe("template:<id>")`' in topic
    assert '`mission_search(facets=["template"])`' in topic

    with pytest.raises(GuideRefused) as refused:
        await guide.describe("template:nowhere")
    assert refused.value.code == "not_found"
    assert refused.value.valid == tuple(f"template:{name}" for name in EXPECTED)


async def test_search_lists_and_ranks_the_templates() -> None:
    from mission_control.application.resolution.registries import LaneRegistry, ModelCatalog
    from tests.conformance.lanes.compile.stub import STUB_DECLARATION
    from tests.conformance.resolution.fixtures import MODELS
    from tests.support.unit.selection.selection_workspace import _registration
    from tests.unit.guide.support import _workspace

    lanes = LaneRegistry(allow_unqualified=True)
    lanes.register(_registration(STUB_DECLARATION))
    workspace = _workspace(lanes, ModelCatalog(MODELS), catalog=True)

    listed = await workspace.search(SelectionSearchRequest(facets=frozenset({"template"})))
    ranked = await workspace.search(
        SelectionSearchRequest(query="sourced research report", facets=frozenset({"template"}))
    )

    assert listed.mode == "listing" and listed.total == len(EXPECTED)
    assert [hit.ref for hit in listed.hits] == [f"template:{name}" for name in EXPECTED]
    assert listed.hits[0].summary == load_template("smallest").purpose
    # Nothing was read from the catalog for a facet that is not a catalog facet.
    assert listed.catalog_search_mode is None and listed.unavailable == ()
    assert ranked.hits[0].ref == "template:research-report"
    assert ranked.hits[0].facet == "template" and ranked.hits[0].reasons
