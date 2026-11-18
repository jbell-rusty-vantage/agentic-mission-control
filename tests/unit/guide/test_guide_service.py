"""The guide service over in-memory ports (no database, no network).

The start page and the topics: what each must say, that every fact in them comes from the
registries (a changed registry changes the page), the size each stays under, and that a page
is written in the caller's vocabulary. Describe: one lane, model, feature, tool request and
capability, and a typed refusal for anything else.
"""

from __future__ import annotations

import json
import re
from typing import get_args

import pytest
import yaml

from mission_control.application.guide.mission_templates import TEMPLATE_IDS
from mission_control.application.guide.operations import SURFACES, Surface
from mission_control.application.guide.pages import (
    INDEX,
    TOPIC_IDS,
    insert_generated,
    load_page,
    parse_page,
)
from mission_control.application.guide.service import GuideRefused
from mission_control.application.guide.tool_docs import TOOL_DOCS, tool_document
from mission_control.application.resolution.lane_listing import describe_lane
from mission_control.application.resolution.model_listing import describe_model
from mission_control.application.resolution.registries import LaneRegistry, ModelCatalog
from mission_control.domain.authoring.brief import (
    BRIEF_ANSWERS_MAX,
    BRIEF_DONE_MEANS_MAX,
    BRIEF_REQUEST_MAX,
    BriefAnswer,
    MissionBrief,
    MissionPurpose,
)
from mission_control.domain.execution.lanes import DELIVERY_COMMANDS, LANE_PROFILES
from tests.conformance.lanes.compile.stub import NARROW_DECLARATION, STUB_DECLARATION
from tests.conformance.resolution.fixtures import MODELS
from tests.support.architecture.package_boundaries import APPLICATION_NEEDLES
from tests.support.unit.selection.selection_workspace import (
    OPEN_WORKFLOW,
    RESEARCH,
    ROWS,
    _pin,
    _registration,
)
from tests.unit.guide.support import APPLICATION, full_guide, stub_guide

# The owner's budgets, in tokens (characters of the rendered page divided by four). The
# manifest page carries the required fields, the values and the acceptance table.
INDEX_TOKENS = 500
TOPIC_TOKENS = 1_250
# The control page gained three rules a live run showed were missing (resend once on a stale
# version, the sponsorship a fork names, when a fork is possible) and what this server reads.
TOPIC_BUDGETS = {"manifest": 1_500, "control": 1_350}


def _tokens(text: str) -> int:
    return len(text) // 4


# -- the start page ------------------------------------------------------------------------------


async def test_the_index_names_the_caller_the_jobs_and_their_topics() -> None:
    page = await stub_guide().index("mcp")

    assert page.topic == INDEX and page.surface == "mcp"
    assert "You are the Coordinator" in page.markdown
    # The six jobs in order, each with its topic.
    jobs = [
        ("Interview the user", "`interview`"),
        ("Select lane, model, capabilities", "`lanes`"),
        ("Author and launch", "`launch`"),
        ("Check in on the run", "`observe`"),
        ("Steer or fork", "`control`"),
        ("Accept results", "`observe`"),
    ]
    positions = [page.markdown.index(job) for job, _topic in jobs]
    assert positions == sorted(positions)
    for job, topic in jobs:
        row = next(line for line in page.markdown.splitlines() if job in line)
        assert topic in row
    # Every topic is reachable from the start page.
    assert all(f"`{topic}`" in page.markdown for topic in TOPIC_IDS)
    assert '`mission_guide("<topic>")`' in page.markdown
    assert "`mission_run_start`" in page.markdown and "approval" in page.markdown


async def test_the_index_reports_this_installation_from_the_registries() -> None:
    page = await stub_guide().index()
    without_catalog = await stub_guide(catalog=False).index()

    assert f"application `{APPLICATION}`" in page.markdown
    assert "`claude_agent_sdk`, `deep_agents`" in page.markdown
    assert f"{len(MODELS)} Model Profiles" in page.markdown
    assert f"{len(ROWS)} published catalog definitions" in page.markdown
    assert f"{len(TEMPLATE_IDS)} mission templates" in page.markdown
    assert "no catalog is composed" in without_catalog.markdown
    # The launch job starts from a template and the manifest page.
    row = next(line for line in page.markdown.splitlines() if "Author and launch" in line)
    assert "`templates`, `manifest`, `launch`" in row
    assert '`mission_describe("template:<id>")`' in row


# -- topics --------------------------------------------------------------------------------------


@pytest.mark.parametrize("surface", SURFACES)
async def test_every_page_renders_whole_on_every_surface(surface: Surface) -> None:
    guide = stub_guide()
    for topic in (INDEX, *TOPIC_IDS):
        page = await guide.topic(topic, surface)
        assert page.markdown.startswith(f"# {page.title}\n")
        assert page.summary and page.surface == surface
        # Nothing the service was meant to fill is left in the text.
        assert "{op:" not in page.markdown and "{{" not in page.markdown
        assert "\n\n\n" not in page.markdown


async def test_pages_stay_inside_their_budget_with_every_lane_bound() -> None:
    guide = full_guide()
    index = await guide.index("mcp")
    sizes = {topic: _tokens((await guide.topic(topic, "mcp")).markdown) for topic in TOPIC_IDS}

    assert _tokens(index.markdown) <= INDEX_TOKENS, _tokens(index.markdown)
    assert all(size <= TOPIC_BUDGETS.get(topic, TOPIC_TOKENS) for topic, size in sizes.items()), (
        sizes
    )


async def test_the_interview_page_names_the_brief_and_real_manifest_fields() -> None:
    from mission_control.domain.authoring.manifest import (
        AgentExecutorNode,
        Budget,
        Environment,
        Goal,
        GoalLoopNode,
        Governors,
        HumanGateNode,
        HumanTaskSpec,
        InputBinding,
        MissionBlock,
        Objective,
        OutputDeclaration,
        SandboxSelection,
        SideEffect,
        StageGraphNode,
        SuccessCriterion,
    )

    page = await stub_guide().topic("interview")
    text = page.markdown

    assert "## 3. The brief, and where each part goes" in text
    assert "Record each answer in the user's own words" in text
    # The interview is recorded: it ends in the manifest's `brief` block, the user's words.
    assert "No interview record is persisted" not in text
    assert "The interview ends in the `brief` block under `mission`" in text
    assert "The user's words go there verbatim" in text
    # The exact block, every field a field of the model, and its limits from the model.
    fenced = re.search(r"```yaml\n(.*?)\n```", text, re.DOTALL)
    assert fenced is not None
    block = yaml.safe_load(fenced.group(1))
    brief = MissionBrief.model_validate(block["brief"])
    assert set(block["brief"]) == set(MissionBrief.model_fields) - {"requested_by"}
    assert set(block["brief"]["answers"][0]) == set(BriefAnswer.model_fields)
    assert brief.purpose is MissionPurpose.RESEARCH
    assert "`purpose` is one of " + ", ".join(f"`{item.value}`" for item in MissionPurpose) in text
    assert f"`request` {BRIEF_REQUEST_MAX:,}" in text
    assert f"`done_means` {BRIEF_DONE_MEANS_MAX:,}" in text
    assert f"{BRIEF_ANSWERS_MAX} `answers`" in text
    assert "`requested_by` defaults to the submitting principal" in text
    assert "`mission_run_inspect` returns it as `brief`" in text
    assert "compile warns `brief_missing`" in text
    for purpose in ("Research", "Building content", "Improving the system"):
        assert f"- {purpose}:" in text
    # Every manifest field the mapping names exists on the manifest models. The table names
    # what a first manifest needs: the keys, the objectives, the evidence, the instruction,
    # the sandbox profile and the action space.
    named = {
        MissionBlock: (
            "key",
            "title",
            "description",
            "goals",
            "environment",
            "program",
            "application",
        ),
        Goal: ("key", "description", "importance", "objectives", "criteria"),
        Objective: ("key", "description"),
        SuccessCriterion: ("key", "description", "evidence", "acceptance"),
        Environment: (
            "lane",
            "model",
            "sandbox",
            "capabilities",
            "agents",
            "hooks",
            "plugins",
            "budget",
            "governors",
            "side_effects",
            "workspace",
        ),
        SandboxSelection: ("profile",),
        Budget: ("usd", "tokens", "wall_clock", "tool_calls"),
        Governors: ("depth", "fan_out", "iterations", "rounds", "patience", "transfers"),
        InputBinding: ("name", "artifact", "value"),
        OutputDeclaration: ("name", "form", "requirements"),
        AgentExecutorNode: ("key", "objectives", "instruction"),
        HumanGateNode: ("key", "task"),
        HumanTaskSpec: ("kind", "prompt", "reviewers"),
        StageGraphNode: ("key", "objectives", "nodes"),
        GoalLoopNode: ("key", "objective", "action_space"),
    }
    for model, fields in named.items():
        for field in fields:
            assert field in model.model_fields, (model.__name__, field)
            assert f"`{field}" in text or f".{field}" in text, field
    assert all(f"`{effect.value}`" in text for effect in SideEffect)
    # The importance values are the model's own, in its order.
    values = get_args(Goal.model_fields["importance"].annotation)
    assert "`importance` (" + ", ".join(f"`{value}`" for value in values[:-1]) in text
    assert f"or `{values[-1]}`)" in text
    assert "schema" in OutputDeclaration.model_json_schema(by_alias=True)["properties"]
    assert "then `form` (`text` for prose) or a `schema`" in text
    assert "`evidence` (a list of output names)" in text
    assert "`acceptance` (a typed expression such as `human: review_accept`" in text
    assert "`environment.sandbox.profile` where the lane requires a sandbox" in text
    assert "both are required" in text
    assert "aliases that name a capability, agent, plugin or node" in text
    assert "Start from a template (topic `templates`)" in text
    assert f"`mission.application` is `{APPLICATION}`" in text
    assert "`manifest: mission/v2` or `manifest: mission/v1`" in text
    # The order of the last steps, and the stop before the consequential ones.
    steps = ["selection_check", "mission_manifest_compile", "mission_preflight", "approval"]
    assert [text.index(step) for step in steps] == sorted(text.index(step) for step in steps)
    assert text.index("approval") < text.index("mission_manifest_submit", text.index("approval"))


async def test_workflow_and_lane_tables_follow_the_lane_declarations() -> None:
    guide = stub_guide()
    workflows = (await guide.topic("workflows")).markdown
    lanes = (await guide.topic("lanes")).markdown

    assert "| `deep_agents` | native | native | unqualified | unqualified |" in workflows
    assert "| `claude_agent_sdk` | native | unqualified | unqualified | unsupported |" in workflows
    assert "This installation allows unqualified lanes" in workflows
    assert (
        "Published Workflow Types that are not lowered from a manifest: 2. Lowered from "
        "submitted manifests and left out of listings: 0." in workflows
    )
    assert (
        "The templates to start from (topic `templates`): `smallest`, `research-report`, "
        "`staged-review`, `system-improvement`." in workflows
    )
    # The systems, then the templates, then what a Workflow Type is.
    order = [
        "| Stage Graph |",
        "## What to start from",
        "The templates to start from",
        "A Workflow Type is",
    ]
    assert [workflows.index(part) for part in order] == sorted(
        workflows.index(part) for part in order
    )
    without_catalog = (await stub_guide(catalog=False).topic("workflows")).markdown
    assert "The catalog is not composed: no Workflow Type can be listed." in without_catalog
    assert "{{" not in workflows
    row = next(line for line in lanes.splitlines() if line.startswith("| `claude_agent_sdk`"))
    # Placement, qualification, families, routed vendors and supported item kinds, each from
    # the declaration: openai, middleware and subagent profiles are unsupported there.
    assert "| worker_hosted | no |" in row
    assert "StageGraph; unqualified: GoalDirected, ParallelSwarm" in row
    assert "| anthropic |" in row and "openai" not in row
    assert "middleware" not in row and "subagent_profile" not in row
    assert "`deep_agents` (default)" in lanes
    # The lane's feature registry, the unavailable rows apart.
    assert "- `deep_agents`: filesystem, bash, todo_list" in lanes
    assert "- `anthropic`: prompt_caching" in lanes
    assert "`deep_agents.memory` (planned)" in lanes

    one_lane = stub_guide(declarations=(STUB_DECLARATION,), allow_unqualified=False)
    assert "claude_agent_sdk" not in (await one_lane.topic("lanes")).markdown
    assert "does not allow unqualified lanes" in (await one_lane.topic("workflows")).markdown


async def test_models_and_capabilities_are_generated() -> None:
    guide = stub_guide()
    models = (await guide.topic("models")).markdown
    capabilities = (await guide.topic("capabilities")).markdown

    for model in MODELS:
        assert f"| `{model.profile}` | {model.vendor} | `{model.model_id}` |" in models
    assert "never a raw model id" in models
    assert "| `skill` | 2 |" in capabilities and "| `workflow_type` | 2 |" in capabilities
    assert "| `sandbox_profile` | 1 |" in capabilities
    assert "Discovered is not runnable" in capabilities
    # A kind the catalog does not hold is not listed.
    assert "`watcher`" not in capabilities

    empty = (await stub_guide(catalog=False).topic("capabilities")).markdown
    assert "No catalog is composed" in empty


async def test_the_control_table_is_each_lane_s_own_matrix() -> None:
    guide = full_guide()
    text = (await guide.topic("control")).markdown
    lines = text.splitlines()

    header = next(line for line in lines if line.startswith("| Lane profile |"))
    # Only what a Coordinator can send: no column for a command no public request carries.
    assert "`hard_pause`" not in header
    assert [name for name in DELIVERY_COMMANDS if f"`{name}`" in header] == [
        "queue_instruction",
        "interrupt_and_inject",
        "pause",
        "resume",
        "cancel",
        "fork",
        "request_continuation",
    ]
    deep_agents = next(line for line in lines if line.startswith("| `deep_agents` |"))
    assert "cooperative_inject" in deep_agents and "R3 / R3" in deep_agents
    # Lanes that declare the same share one row; every bound lane is in the table once.
    assert "| `claude_managed`, `codex_agents` |" in text
    first_cells = " ".join(line.split("|")[1] for line in lines if line.startswith("| `"))
    assert sorted(re.findall(r"`([a-z_]+)`", first_cells)) == sorted(LANE_PROFILES)
    for word in ("cancel_and_replace", "wait_then_send", "Stop Fence", "in_doubt"):
        assert word in text


async def test_launch_and_observe_carry_the_rules() -> None:
    guide = stub_guide()
    launch = (await guide.topic("launch")).markdown
    observe = (await guide.topic("observe")).markdown

    assert "the only step that runs agents" in launch
    assert "`ok: false`" in launch and "`blockers`" in launch and "`start_blockers`" in launch
    assert "wait for their yes" in launch
    assert "Wait; never poll" in observe
    assert "One wait lasts at most 300 seconds" in observe
    assert "`terminal_result`" in observe and "Execution is not acceptance" in observe


async def test_who_may_resolve_a_review_is_the_gate_s_own_rule() -> None:
    """The page and the templates say who resolves a Human Task as `is_reviewer` decides it:
    a listed actor id, or the holder of `reviewer:<name>`; anyone else is `not_reviewer`."""

    from mission_control.application.guide.mission_templates import mission_templates
    from mission_control.domain.programs.human_gate import (
        REVIEWER_PERMISSION_PREFIX,
        HumanGateSpec,
        ResolutionRejection,
        is_reviewer,
    )

    observe = (await stub_guide().topic("observe")).markdown
    assert (
        f"that actor id, or a principal holding the permission `{REVIEWER_PERMISSION_PREFIX}"
        "<name>`; anyone else is refused `not_reviewer`" in observe
    )
    spec = HumanGateSpec.model_validate(
        {
            "gate_key": "review",
            "task_kind": "REVIEW",
            "prompt": "Review.",
            "reviewers": ["owner", "operator:probe"],
        }
    )
    assert is_reviewer(spec, "operator:probe", frozenset())
    assert is_reviewer(spec, "someone", frozenset({f"{REVIEWER_PERMISSION_PREFIX}owner"}))
    assert not is_reviewer(spec, "someone", frozenset({"workflow_run.control"}))
    assert "not_reviewer" in get_args(ResolutionRejection)
    # Every template with a human gate has the reviewer as a slot and says who can resolve.
    for template in mission_templates():
        slot = next((slot for slot in template.slots if slot.name == "reviewer"), None)
        if "behavior: human_gate" in template.manifest:
            assert slot is not None and "reviewers: [{{reviewer}}]" in template.manifest
            assert "actor id" in slot.description and "reviewer role" in slot.description


async def test_one_page_speaks_each_transport_s_vocabulary() -> None:
    guide = stub_guide()
    mcp = (await guide.topic("launch", "mcp")).markdown
    cli = (await guide.topic("launch", "cli")).markdown
    http = (await guide.topic("launch", "http")).markdown

    assert "`mission_manifest_compile`" in mcp and "missionctl" not in mcp
    assert "`missionctl mission compile`" in cli and "mission_manifest_compile" not in cli
    assert "`POST missions:compile`" in http
    # An operation one transport lacks names the nearest transport that has it.
    index = (await guide.index("cli")).markdown
    assert (
        "`POST human-tasks/{human_task_id}/resolutions` (HTTP route; no missionctl command)"
        in index
    )
    # The judgment is the same text on every transport.
    strip = re.compile(r"`[^`]*`( \([^)]*; no [^)]*\))?")
    assert strip.sub("", mcp) == strip.sub("", cli) == strip.sub("", http)


async def test_an_unknown_topic_is_refused_with_the_topics() -> None:
    with pytest.raises(GuideRefused) as refused:
        await stub_guide().topic("pricing")

    assert refused.value.code == "unknown_topic"
    assert refused.value.valid == TOPIC_IDS and "interview" in str(refused.value)


# -- the page sources ----------------------------------------------------------------------------


def test_pages_have_their_frontmatter_and_name_no_application() -> None:
    for directory, names in (("pages", (INDEX, *TOPIC_IDS)), ("tools", tuple(TOOL_DOCS))):
        for name in names:
            page = load_page(directory, name)
            assert page.id == name and page.title and page.summary and page.body
            lowered = f"{page.title} {page.summary} {page.body}".lower()
            assert not [needle for needle in APPLICATION_NEEDLES if needle in lowered], name
            # Written for a user of the service: no source paths, tickets or migrations.
            assert not re.search(r"\b(OVE|ADR|SPEC|FT|MP|OC)-[A-Z]?\d|\.py\b|src/", page.body), name


def test_a_malformed_page_is_refused() -> None:
    with pytest.raises(ValueError, match="frontmatter"):
        parse_page("no frontmatter", expected_id="x")
    with pytest.raises(ValueError, match="declares id"):
        parse_page("---\nid: y\ntitle: T\nsummary: S\n---\nbody", expected_id="x")
    assert insert_generated("a\n\n{{generated}}\n\nb", "") == "a\n\nb"
    assert insert_generated("a", "g") == "a\n\ng"


# -- describe ------------------------------------------------------------------------------------


def _lanes() -> LaneRegistry:
    lanes = LaneRegistry(allow_unqualified=True)
    for declaration in (STUB_DECLARATION, NARROW_DECLARATION):
        lanes.register(_registration(declaration))
    return lanes


async def test_describe_a_lane_is_the_lane_route_s_document() -> None:
    result = await stub_guide().describe("lane:deep_agents")

    assert (result.kind, result.ref) == ("lane", "lane:deep_agents")
    assert result.data == describe_lane(_lanes(), "deep_agents")
    assert {"controls", "delivery_semantics", "time_travel", "model_routes"} <= set(result.data)
    assert result.data["time_travel"] == {"read": "R3", "fork": "R3"}


async def test_describe_a_model_is_the_model_route_s_document() -> None:
    result = await stub_guide().describe("model:judge.default")

    expected = describe_model(ModelCatalog(MODELS), _lanes(), "judge.default")
    assert result.kind == "model" and result.data == expected.model_dump(mode="json")
    assert result.data["routes"]["claude_agent_sdk"] == "unsupported"


async def test_describe_a_capability_is_one_definition_s_summary() -> None:
    guide = stub_guide()
    by_pin = await guide.describe(_pin(RESEARCH))
    ref = RESEARCH.ref
    by_exact_ref = await guide.describe(
        f"{ref.kind.value}:{ref.logical_id}@{ref.revision}#{ref.digest}"
    )
    workflow = await guide.describe(_pin(OPEN_WORKFLOW))

    assert by_pin.kind == "capability" and by_pin.ref == _pin(RESEARCH)
    assert by_pin.data == {
        "pin": _pin(RESEARCH),
        "kind": "skill",
        "name": "skill.web-research",
        "revision": 1,
        "title": "Skill web-research",
        "description": "The web-research procedure",
        "retired": False,
        "required_capabilities": ["web.fetch"],
        "secret_names": [],
        "host_support": {"deep_agents": "supported", "claude_agent_sdk": "unsupported"},
    }
    assert by_exact_ref.data == by_pin.data
    assert workflow.data["authority_ceiling"] == {
        "capabilities": ["sandbox", "web.fetch"],
        "max_concurrency": 2,
    }
    assert workflow.data["purpose"] == "Exercise the authority-ceiling fit"


async def test_describe_a_tool_returns_its_request_shape_notes_and_example() -> None:
    result = await stub_guide().describe("tool:mission_command_send")

    assert result.kind == "tool" and result.data["argument"] == "request"
    properties = result.data["schema"]["properties"]
    assert {"request_id", "expected_version", "expected_generation", "target", "kind"} <= set(
        properties
    )
    assert "queue_instruction" in properties["kind"]["enum"]
    assert "8 KiB" in result.data["notes"] and "satisfy_wait" in result.data["notes"]
    assert result.data["example"]["kind"] == "queue_instruction"


def test_every_documented_example_is_a_valid_request() -> None:
    for name, doc in TOOL_DOCS.items():
        document = tool_document(name)
        assert document["notes"].strip(), name
        if doc.model is None:
            assert "schema" not in document
            continue
        doc.model.model_validate(doc.example)
        # The model's own schema, less the generated titles that repeat each field's name.
        full = doc.model.model_json_schema()
        assert set(document["schema"]["properties"]) == set(full["properties"])
        assert document["schema"].get("required") == full.get("required")
        assert set(document["schema"].get("$defs", {})) == set(full.get("$defs", {}))
        assert '"title": "' not in json.dumps(document["schema"])
        assert len(json.dumps(document["schema"])) < len(json.dumps(full))


def test_the_moved_tool_documentation_lost_no_fact() -> None:
    """What the four tool descriptions said before they were shortened is in the notes."""

    facts = {
        "mission_command_send": (
            "repeating it returns the first receipt",
            "1 to 4096 characters",
            "first fences the run against any further effect",
            "next_iteration",
            '"deadline"',
            '"node_key"',
            '"materialize"',
            "activation_id",
            "most recently active",
            "authority_ref",
            "pause_decision_id",
            "runnable_work_remains",
            "verification_evidence_ref",
            "at most 8 KiB",
            "sha256:<64 hex>",
            "accepted, rejected or stale",
        ),
        "coordinator_inbox_command": (
            "recursion depth",
            "retryable later",
            "recorded as caused by it",
            "request_continuation",
            "`admission`, `delivery`",
        ),
        "mission_run_fork": (
            "a repeat returns the same fork",
            "it pays for the new run",
            "1 to 2000 characters",
            "from_snapshot_id",
            "snapshot_digest",
            "`instruction` is the older name",
            "coordinate.point.key",
            "session_generation",
            "declares patchable",
            '"strict"',
            "baseline_reservations",
            "approval_refs",
            "reused_units",
            "frontier_closed",
            "message_delivery",
            "receipt.target_run_id",
            "in-flight Commands and active children are never copied",
        ),
        "mission_governed_prepare": (
            "an unknown name is refused",
            "mc/<run>/<unit>",
            "`lane` section of mission_run_inspect",
            "input_digest",
            "review_digest",
            "mission_approval_resolve",
            "returns the same intent",
        ),
        # The descriptions shortened to bring the listing under its token ceiling.
        "mission_approval_resolve": (
            "does not serve Human Gate tasks",
            "which must differ from the pending",
            "`answer` or `selected`",
            "`elicitation_content`, or deny to decline",
            "accepted or duplicate",
        ),
        "knowledge_review": (
            "knowledge.review permission",
            "launched or revised the run, its producer or an evaluator",
            '"use_decision"',
            "`qualifiers_digest`",
            "records it once",
        ),
        "coordinator_inbox_observe": (
            "`delivery_nonce`",
            "background_task_exit, monitor_event",
            "connected_poll when the host was not idle",
            "tool_result, task_output or",
            "Idempotent by `observation_key`",
            "never acknowledgment",
        ),
        "mission_run_points": (
            "`session_generation`",
            "replacement_start, fork_seed, rollover_start, cycle_start, reused",
            "at most 500",
            "`next_cursor` to pass back as `cursor`",
        ),
        "mission_human_task_resolve": (
            "mission_approval_resolve covers edited arguments",
            "`reviewed_packet_digest` is its `packet_digest`",
            "repeating the same request returns the same result",
            "`feedback_artifact_refs`",
            "on a question task the `comment` is the answer",
        ),
        "mission_human_task_get": (
            "provider_permission, provider_question, mcp_elicitation or governed_effect",
            "`deadline_at`",
            "the pending tool call",
        ),
        "mission_human_task_list": (
            "review_required notification",
            "open, resolved, expired or",
            "`permitted_decisions` and `packet_digest`",
        ),
        "mission_governed_execute": (
            "runs at most once",
            "applied, noop, rejected or failed",
            "fenced, stale or in_doubt",
            "need their own prepare",
        ),
        "mission_governed_status": (
            "Nothing is executed",
            "pending_approval, ready, executing, executed",
            "`input_digest`",
            "call mission_governed_execute when ready",
        ),
        "mission_run_inspect": (
            "pending, running, paused, completed",
            "not whether the mission was accepted",
            "`frames_cursor`",
            "`points_incomplete`, `unit_failures`",
            "fork `lineage`",
        ),
        "mission_run_list": (
            "executing, cancelling, in_doubt, completed, cancelled, failed",
            "forked_from (a run id)",
            "continued_as_new",
            "ISO-8601 instant with a timezone",
            "terminal_outcome and run_version",
        ),
        "mission_run_replay": (
            "No model is called",
            "`call_index` picks a model call",
            "`include_batch`",
            "a paid replay is not available",
            "`first_difference`",
        ),
        "mission_run_points_reconcile": (
            "`points_incomplete`",
            "safe to repeat",
            "`frame_ranges_filled`",
            "`saver_unreachable`",
        ),
        "mission_run_state_as_of": (
            "messages, files, pending tasks, interrupts",
            "R0 to R3",
            "`usage_to_point`",
            "retryable means the saved state did not answer",
        ),
        "mission_run_transcript": (
            "`next_cursor`, or a search hit's `open_cursor`",
            "1 to 5000",
            "`canonical_only` (mission events only)",
            "a `point_id` from mission_run_points",
            "never instructions",
        ),
    }
    for name, expected in facts.items():
        notes = load_page("tools", name).body
        assert not [fact for fact in expected if fact not in notes], name
    # The lane profiles the governed prepare description used to list are in its schema.
    profiles = tool_document("mission_governed_prepare")["schema"]["properties"]["lane_profile"]
    assert set(profiles["enum"]) == set(LANE_PROFILES)


async def test_describe_a_feature_carries_its_configuration_schema() -> None:
    result = await stub_guide().describe("feature:anthropic.web_search")

    assert result.kind == "feature" and result.data["lane_profiles"] == ["deep_agents"]
    assert result.data["model_provider"] == "anthropic" and result.data["status"] == "available"
    assert "max_uses" in result.data["config_schema"]["properties"]


@pytest.mark.parametrize(
    ("ref", "code", "names"),
    [
        ("everything", "unknown_ref", "lane:<profile>"),
        ("", "unknown_ref", "tool:<name>"),
        ("run:123", "unknown_ref", "feature:<id>"),
        ("lane:nowhere", "not_found", "lane:deep_agents"),
        ("model:nobody.default", "not_found", "model:judge.default"),
        ("tool:mission_run_outputs", "not_found", "tool:mission_command_send"),
        ("feature:deep_agents.nothing", "not_found", "feature:deep_agents.bash"),
    ],
)
async def test_an_unknown_ref_is_refused_with_what_is_valid(
    ref: str, code: str, names: str
) -> None:
    with pytest.raises(GuideRefused) as refused:
        await stub_guide().describe(ref)

    assert refused.value.code == code
    assert names in refused.value.valid


async def test_an_unpublished_pin_and_a_missing_catalog_are_refused() -> None:
    missing = _pin(RESEARCH).rsplit("#", 1)[0] + "#sha256:" + "0" * 64
    with pytest.raises(GuideRefused) as not_found:
        await stub_guide().describe(missing)
    with pytest.raises(GuideRefused) as unavailable:
        await stub_guide(catalog=False).describe(_pin(RESEARCH))

    assert not_found.value.code == "not_found"
    assert unavailable.value.code == "unavailable"


def test_the_surface_vocabulary_is_closed() -> None:
    assert get_args(Surface) == SURFACES == ("mcp", "cli", "http")
