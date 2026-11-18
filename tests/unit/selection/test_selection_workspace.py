"""The Selection Workspace over in-memory ports (no database, no network).

Search: the cross-facet reciprocal-rank merge, facet filtering, the lane filter and a catalog
facet reported unavailable. Listing: an empty query lists lanes, models and the published
definitions of the requested kinds by name, behind `offset` and `limit`. Scan: a query the
catalog answers with nothing is answered from the published definitions when the Search
Projection does not hold them, and the result says so. Check: an admissible draft, the
resolver's refusals surfaced as reasons, host-support and lane item refusals, the
authority-ceiling fit and kind mismatches.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from mission_control.application.capabilities.capability_search import CapabilitySearchResponse
from mission_control.application.selection.workspace import (
    SelectionSearchRequest,
)
from mission_control.domain.authoring.contracts import (
    DefinitionKind,
)
from mission_control.domain.capabilities.host_support import (
    LaneProfile,
)
from mission_control.domain.coordinator.contracts import (
    CapabilitySearchRequest,
)
from tests.conformance.lanes.compile.stub import (
    STUB_DECLARATION,
)
from tests.conformance.resolution.fixtures import MODELS
from tests.support.unit.selection.selection_workspace import (
    MIDDLEWARE,
    NARROW_WORKFLOW,
    NOW,
    OPEN_WORKFLOW,
    RESEARCH,
    REVIEW,
    ROWS,
    SANDBOX,
    FakeDefinitions,
    FakeSearch,
    _digest,
    _draft,
    _hit,
    _pin,
    _workflow_type,
    _workspace,
)


def _codes(check: Any) -> list[str]:
    return [refusal.code for refusal in check.refusals]


# -- search --------------------------------------------------------------------------------------


async def test_search_merges_facets_by_reciprocal_rank_with_stable_refs() -> None:
    result = await _workspace().search(SelectionSearchRequest(query="anthropic research harness"))

    facets = {hit.facet for hit in result.hits}
    assert {"capability", "lane", "model", "sandbox_profile", "workflow_type"} <= facets
    # Every facet's first hit shares the top merged score; deeper ranks score lower.
    firsts = [hit for hit in result.hits if hit.facet_rank == 1]
    assert {hit.score for hit in firsts} == {round(1 / 61, 6)}
    assert all(hit.score < firsts[0].score for hit in result.hits if hit.facet_rank > 1)
    assert [hit.score for hit in result.hits] == sorted(
        (hit.score for hit in result.hits), reverse=True
    )
    refs = {hit.facet: hit.ref for hit in result.hits if hit.facet_rank == 1}
    assert refs["lane"] == "lane:deep_agents"
    assert refs["capability"] == _pin(RESEARCH)
    assert refs["workflow_type"] == _pin(OPEN_WORKFLOW)
    assert refs["model"].startswith("model:")
    assert all(hit.reasons for hit in result.hits)
    assert result.catalog_search_mode == "lexical"
    assert result.unavailable == ()


async def test_lane_hits_say_why_they_matched() -> None:
    result = await _workspace().search(
        SelectionSearchRequest(query="stagegraph openai", facets=frozenset({"lane"}))
    )

    # Only the stub routes openai; both run StageGraph.
    assert [hit.ref for hit in result.hits] == ["lane:deep_agents", "lane:claude_agent_sdk"]
    reasons = " ".join(result.hits[0].reasons)
    assert "StageGraph" in reasons and "openai" in reasons
    assert "openai" not in " ".join(result.hits[1].reasons)


async def test_facet_filter_skips_the_catalog() -> None:
    search = FakeSearch()
    result = await _workspace(search=search).search(
        SelectionSearchRequest(query="harness model", facets=frozenset({"lane", "model"}))
    )

    assert search.requests == []
    assert {hit.facet for hit in result.hits} == {"lane", "model"}
    assert result.facets == ("lane", "model")


async def test_lane_filter_narrows_capabilities_and_models() -> None:
    search = FakeSearch()
    result = await _workspace(search=search).search(
        SelectionSearchRequest(
            query="skill model",
            facets=frozenset({"capability", "model"}),
            lane_profile="claude_agent_sdk",
        )
    )

    assert search.requests[0].host_profiles == frozenset({LaneProfile.CLAUDE_AGENT_SDK})
    capability_refs = [hit.ref for hit in result.hits if hit.facet == "capability"]
    assert capability_refs == [_pin(REVIEW)]
    # The narrow lane does not route openai: only the anthropic profiles remain.
    vendors = {hit.details["vendor"] for hit in result.hits if hit.facet == "model"}
    assert vendors == {"anthropic"}


async def test_an_unavailable_catalog_is_reported_not_dropped() -> None:
    result = await _workspace(search=FakeSearch(unavailable=True)).search(
        SelectionSearchRequest(query="research lane")
    )

    assert {item.facet for item in result.unavailable} == {
        "capability",
        "sandbox_profile",
        "workflow_type",
    }
    assert "search_privileges_missing" in result.unavailable[0].reason
    assert {hit.facet for hit in result.hits} == {"lane"}


# -- listing -------------------------------------------------------------------------------------


class UnbuiltProjection:
    """A catalog search whose Search Projection holds no row: every search answers nothing."""

    def __init__(self) -> None:
        self.requests: list[CapabilitySearchRequest] = []

    async def search(self, request: CapabilitySearchRequest) -> CapabilitySearchResponse:
        self.requests.append(request)
        return CapabilitySearchResponse(hits=(), search_mode="lexical")


class QuietSearch(FakeSearch):
    """A built projection that holds the rows but matches only a query naming a row title."""

    async def search(self, request: CapabilitySearchRequest) -> CapabilitySearchResponse:
        self.requests.append(request)
        rows = [
            row
            for row in ROWS
            if row.ref.kind in request.kinds and row.definition.title == request.query
        ]
        return CapabilitySearchResponse(
            hits=tuple(_hit(row, rank) for rank, row in enumerate(rows, start=1)),
            search_mode="lexical",
        )


def _dump(result: Any) -> dict[str, Any]:
    return result.model_dump(mode="json")


async def test_an_empty_query_lists_lanes_and_models_by_name() -> None:
    search = FakeSearch()
    result = await _workspace(search=search).search(
        SelectionSearchRequest(facets=frozenset({"lane", "model"}))
    )

    assert (result.mode, result.query, result.total) == ("listing", "", 2 + len(MODELS))
    assert [hit.ref for hit in result.hits if hit.facet == "lane"] == [
        "lane:claude_agent_sdk",
        "lane:deep_agents",
    ]
    assert [hit.ref for hit in result.hits if hit.facet == "model"] == [
        f"model:{profile}" for profile in sorted(model.profile for model in MODELS)
    ]
    # Nothing was ranked and nothing was searched: a listed hit is its ref and one line.
    assert search.requests == [] and result.catalog_search_mode is None
    assert _dump(result)["hits"][0] == {
        "facet": "lane",
        "ref": "lane:claude_agent_sdk",
        "title": "claude_agent_sdk",
        "summary": "claude lane, worker_hosted placement, unqualified",
    }
    blank = await _workspace().search(SelectionSearchRequest(query="   "))
    assert blank.mode == "listing"


async def test_listing_workflow_types_needs_no_query_and_no_projection() -> None:
    search = UnbuiltProjection()
    result = await _workspace(search=search).search(
        SelectionSearchRequest(facets=frozenset({"workflow_type"}))
    )

    # Ordered by name: `workflow.offline` before `workflow.research`.
    assert [hit.ref for hit in result.hits] == [_pin(NARROW_WORKFLOW), _pin(OPEN_WORKFLOW)]
    assert result.catalog_search_mode == "definition_listing" and result.total == 2
    # The facet holds one kind, so a hit does not repeat it.
    assert _dump(result)["hits"][0] == {
        "facet": "workflow_type",
        "ref": _pin(NARROW_WORKFLOW),
        "title": "Research workflow",
        "summary": "A fixture Workflow Type",
    }
    assert search.requests == []
    assert result.unavailable == () and result.notes == ()


async def test_kinds_name_the_catalog_kinds_of_the_capability_facet() -> None:
    workspace = _workspace()
    skills = await workspace.search(SelectionSearchRequest(kinds=frozenset({DefinitionKind.SKILL})))
    default = await workspace.search(SelectionSearchRequest(facets=frozenset({"capability"})))
    # Any catalog kind may be named, also one outside the facet's node-attachable default.
    sandboxes = await workspace.search(
        SelectionSearchRequest(kinds=frozenset({DefinitionKind.SANDBOX_PROFILE}))
    )
    with_lanes = await workspace.search(
        SelectionSearchRequest(
            kinds=frozenset({DefinitionKind.SKILL}), facets=frozenset({"capability", "lane"})
        )
    )

    # Kinds without facets ask the capability facet only.
    assert skills.facets == ("capability",)
    assert [hit.ref for hit in skills.hits] == [_pin(REVIEW), _pin(RESEARCH)]
    # A facet answering with several kinds names each hit's kind.
    assert {hit.kind for hit in skills.hits} == {None}
    assert {hit.kind for hit in default.hits} == {"skill", "middleware"}
    assert [hit.ref for hit in sandboxes.hits] == [_pin(SANDBOX)]
    assert with_lanes.facets == ("capability", "lane") and with_lanes.total == 4


async def test_a_listing_pages_with_offset_and_limit() -> None:
    workspace = _workspace()
    everything = await workspace.search(SelectionSearchRequest(limit=100))
    first = await workspace.search(SelectionSearchRequest(limit=3))
    second = await workspace.search(SelectionSearchRequest(limit=3, offset=3))
    beyond = await workspace.search(SelectionSearchRequest(offset=500))

    refs = [hit.ref for hit in everything.hits]
    assert everything.total == len(refs) == len(ROWS) + 2 + len(MODELS)
    assert [hit.ref for hit in first.hits] == refs[:3]
    assert [hit.ref for hit in second.hits] == refs[3:6]
    assert (second.offset, second.total) == (3, everything.total)
    assert beyond.hits == () and beyond.total == everything.total
    assert "offset" not in _dump(first) and _dump(second)["offset"] == 3


async def test_a_listing_keeps_the_lane_filter_and_drops_retired_rows() -> None:
    retired = RESEARCH.model_copy(
        update={
            "retired_at": NOW,
            "ref": RESEARCH.ref.model_copy(update={"lifecycle_status": "retired"}),
        }
    )
    workspace = _workspace(definitions=FakeDefinitions((retired, REVIEW, MIDDLEWARE)))
    listed = await workspace.search(SelectionSearchRequest(facets=frozenset({"capability"})))
    on_lane = await workspace.search(
        SelectionSearchRequest(
            facets=frozenset({"capability", "model"}), lane_profile="claude_agent_sdk"
        )
    )

    assert [hit.ref for hit in listed.hits] == [_pin(MIDDLEWARE), _pin(REVIEW)]
    # The lane filter keeps capabilities whose host support marks it supported, and the
    # models whose vendor the lane routes.
    assert [hit.ref for hit in on_lane.hits if hit.facet == "capability"] == [_pin(REVIEW)]
    assert {hit.summary.split()[0] for hit in on_lane.hits if hit.facet == "model"} == {"anthropic"}


async def test_a_listing_without_a_catalog_says_so() -> None:
    workspace = _workspace()
    workspace._definitions = None
    result = await workspace.search(SelectionSearchRequest())

    assert {item.facet for item in result.unavailable} == {
        "capability",
        "sandbox_profile",
        "workflow_type",
    }
    assert "no catalog is composed" in result.unavailable[0].reason
    assert {hit.facet for hit in result.hits} == {"lane", "model"}


async def test_fifty_workflow_types_list_well_under_four_thousand_tokens() -> None:
    types = [
        _workflow_type(f"workflow.research-synthesis-{index:02d}", ceiling=frozenset({"sandbox"}))
        for index in range(50)
    ]
    long = (
        "Collects sources for one question, extracts claims with their evidence, has an "
        "independent reviewer assess them and publishes the accepted report."
    )
    rows = [
        row.model_copy(
            update={
                "definition": row.definition.model_copy(
                    update={"title": f"Research synthesis {index:02d}", "description": long}
                )
            }
        )
        for index, row in enumerate(types)
    ]
    result = await _workspace(definitions=FakeDefinitions(rows)).search(
        SelectionSearchRequest(facets=frozenset({"workflow_type"}), limit=50)
    )

    assert len(result.hits) == 50 and result.total == 50
    assert all(len(hit.summary) <= 60 and hit.summary.endswith("...") for hit in result.hits)
    assert len(json.dumps(_dump(result))) // 4 < 3_300


async def test_the_published_definitions_are_read_once_per_lifetime() -> None:
    now = [100.0]
    definitions = FakeDefinitions()
    workspace = _workspace(definitions=definitions, clock=lambda: now[0])

    await workspace.search(SelectionSearchRequest())
    await workspace.search(SelectionSearchRequest(facets=frozenset({"workflow_type"})))
    assert definitions.reads == 1
    now[0] += 31.0
    await workspace.search(SelectionSearchRequest())
    assert definitions.reads == 2


# -- the definition scan -------------------------------------------------------------------------


async def test_an_unbuilt_projection_is_answered_from_the_definitions_and_says_so() -> None:
    search = UnbuiltProjection()
    result = await _workspace(search=search).search(
        SelectionSearchRequest(query="skills", facets=frozenset({"capability"}))
    )

    # The plural finds the kind `skill`; the scan ranks by where the words match.
    assert [hit.ref for hit in result.hits] == [_pin(REVIEW), _pin(RESEARCH)]
    assert result.catalog_search_mode == "definition_scan" and result.mode == "search"
    assert result.hits[0].reasons == (
        "definition scan",
        "name 'skill.code-review' matches skill",
        "title 'Skill code-review' matches skill",
    )
    assert result.hits[0].kind == "skill" and result.hits[0].facet_rank == 1
    (note,) = result.notes
    assert note.startswith("capability: the catalog Search Projection did not return")
    assert "not built or is stale" in note and "(middleware.summarize)" in note
    # The search, then one probe: the facet's first published definition, by its own title.
    assert [request.query for request in search.requests] == [
        "skills",
        MIDDLEWARE.definition.title,
    ]
    assert search.requests[1].kinds == frozenset({DefinitionKind.MIDDLEWARE})


async def test_the_scan_matches_names_and_descriptions_and_stays_honest_when_empty() -> None:
    workspace = _workspace(search=UnbuiltProjection())
    research = await workspace.search(SelectionSearchRequest(query="web research"))
    nothing = await workspace.search(
        SelectionSearchRequest(query="zebra", facets=frozenset({"workflow_type"}))
    )

    by_facet = {hit.facet: hit.ref for hit in research.hits if hit.facet_rank == 1}
    assert by_facet["capability"] == _pin(RESEARCH)
    assert by_facet["workflow_type"] == _pin(OPEN_WORKFLOW)
    # One note for the whole result, naming every facet the workspace scanned itself.
    (note,) = research.notes
    assert research.catalog_search_mode == "definition_scan"
    assert note.startswith("capability, sandbox_profile, workflow_type: the catalog Search")
    # Never silently empty: no hit, and the reason the catalog search could not be trusted.
    assert nothing.hits == () and nothing.catalog_search_mode == "definition_scan"
    assert nothing.notes[0].startswith("workflow_type: the catalog Search Projection")


async def test_a_partly_built_projection_keeps_the_catalog_mode_and_names_the_rest() -> None:
    class WithoutWorkflowTypes(FakeSearch):
        async def search(self, request: CapabilitySearchRequest) -> CapabilitySearchResponse:
            if request.kinds == frozenset({DefinitionKind.WORKFLOW_TYPE}):
                self.requests.append(request)
                return CapabilitySearchResponse(hits=(), search_mode="lexical")
            return await super().search(request)

    result = await _workspace(search=WithoutWorkflowTypes()).search(
        SelectionSearchRequest(query="research", facets=frozenset({"capability", "workflow_type"}))
    )

    by_facet = {hit.facet: hit for hit in result.hits if hit.facet_rank == 1}
    # The capabilities were ranked by the catalog; only the Workflow Types were scanned.
    assert result.catalog_search_mode == "lexical"
    assert by_facet["capability"].reasons[0].startswith("catalog lexical search")
    assert by_facet["workflow_type"].ref == _pin(OPEN_WORKFLOW)
    assert by_facet["workflow_type"].reasons[0] == "definition scan"
    (note,) = result.notes
    assert note.startswith("workflow_type: the catalog Search Projection did not return")


async def test_a_built_projection_that_matches_nothing_is_not_scanned() -> None:
    search = QuietSearch()
    result = await _workspace(search=search).search(
        SelectionSearchRequest(query="research", facets=frozenset({"capability"}))
    )

    # The probe (a published title) is answered, so the empty answer is the catalog's own.
    assert result.hits == () and result.notes == ()
    assert result.catalog_search_mode == "lexical"
    probe = MIDDLEWARE.definition.title
    assert [request.query for request in search.requests] == ["research", probe]
    # The probe is remembered: a second empty search does not probe again.
    again = QuietSearch()
    workspace = _workspace(search=again)
    await workspace.search(SelectionSearchRequest(query="one", facets=frozenset({"capability"})))
    await workspace.search(SelectionSearchRequest(query="two", facets=frozenset({"capability"})))
    assert [request.query for request in again.requests] == ["one", probe, "two"]


# -- check ---------------------------------------------------------------------------------------


async def test_an_admissible_draft() -> None:
    check = await _workspace().check(
        _draft(
            capabilities=(_pin(RESEARCH), _pin(REVIEW), _pin(MIDDLEWARE)),
            sandbox_profile=_pin(SANDBOX),
            workflow_type=_pin(OPEN_WORKFLOW),
        )
    )

    assert check.admissible, check.refusals
    assert check.lane.registered and check.lane.family_support == "native"
    assert check.model.route == "native" and check.model.vendor == "anthropic"
    assert [fit.host_status for fit in check.capabilities] == [
        "supported",
        "supported",
        "undeclared",
    ]
    assert check.capabilities[0].within_authority is True
    assert check.sandbox_profile is not None and check.sandbox_profile.lane_item_support == "native"
    assert check.workflow_type is not None
    assert check.workflow_type.authority_capabilities == ("sandbox", "web.fetch")
    assert check.not_checked  # compile, serving and preflight stay with their own commands


async def test_an_undeclared_data_class_takes_the_application_ceiling() -> None:
    check = await _workspace().check(_draft(data_class=None))

    assert (check.data_class, check.data_class_source) == ("confidential", "ceiling_default")


@pytest.mark.parametrize(
    ("overrides", "code", "pointer"),
    [
        ({"lane_profile": "codex"}, "LANE_UNKNOWN", "/lane_profile"),
        ({"model_profile": "unknown.default"}, "MODEL_UNKNOWN", "/model_profile"),
        (
            {"lane_profile": "claude_agent_sdk", "model_profile": "judge.default"},
            "MODEL_ROUTE_UNSUPPORTED",
            "/model_profile",
        ),
        ({"data_class": "phi"}, "DATA_CLASS_NOT_ADMITTED", "/data_class"),
        (
            {"lane_profile": "claude_agent_sdk", "family": "EvaluatorOptimizer"},
            "BLUEPRINT_FAMILY_UNSUPPORTED",
            "/family",
        ),
        ({"application_id": "biotech"}, "APPLICATION_OUT_OF_SCOPE", "/application_id"),
    ],
)
async def test_resolver_refusals_surface_as_reasons(
    overrides: dict[str, Any], code: str, pointer: str
) -> None:
    check = await _workspace().check(_draft(**overrides))

    assert not check.admissible
    refusal = next(item for item in check.refusals if item.code == code)
    assert refusal.pointer == pointer
    assert refusal.reason and refusal.remedy


async def test_an_unqualified_lane_is_refused_unless_policy_allows() -> None:
    unqualified = STUB_DECLARATION.model_copy(
        update={"describe": STUB_DECLARATION.describe.unqualified()}
    )

    refused = await _workspace(declarations=(unqualified,), allow_unqualified=False).check(_draft())
    allowed = await _workspace(declarations=(unqualified,), allow_unqualified=True).check(_draft())

    assert _codes(refused) == ["LANE_UNQUALIFIED"]
    assert refused.refusals[0].source == "resolver"
    assert refused.lane.qualified is False
    assert allowed.admissible


async def test_a_capability_unsupported_on_the_lane_is_refused() -> None:
    check = await _workspace().check(
        _draft(lane_profile="claude_agent_sdk", capabilities=(_pin(RESEARCH), _pin(REVIEW)))
    )

    assert _codes(check) == ["CAPABILITY_LANE_UNSUPPORTED"]
    refusal = check.refusals[0]
    assert (refusal.pointer, refusal.lane_profile) == ("/capabilities/0", "claude_agent_sdk")
    assert [fit.host_status for fit in check.capabilities] == ["unsupported", "supported"]


async def test_a_lane_that_declares_the_item_kind_unsupported_is_refused() -> None:
    # The narrow lane declares middleware unsupported.
    check = await _workspace().check(
        _draft(lane_profile="claude_agent_sdk", capabilities=(_pin(MIDDLEWARE),))
    )

    assert _codes(check) == ["ITEM_UNSUPPORTED_ON_LANE"]
    assert check.refusals[0].pointer == "/capabilities/0"
    assert check.capabilities[0].lane_item_support == "unsupported"


async def test_a_capability_outside_the_authority_ceiling_is_refused() -> None:
    check = await _workspace().check(
        _draft(capabilities=(_pin(RESEARCH), _pin(REVIEW)), workflow_type=_pin(NARROW_WORKFLOW))
    )

    assert _codes(check) == ["AUTHORITY_CEILING_EXCEEDED"]
    assert "web.fetch" in check.refusals[0].reason
    assert [fit.within_authority for fit in check.capabilities] == [False, True]


async def test_pins_of_the_wrong_kind_missing_or_malformed_are_refused() -> None:
    missing = _pin(RESEARCH).rsplit("#", 1)[0] + "#" + _digest("missing")
    check = await _workspace().check(
        _draft(
            capabilities=(missing, "not-a-pin"),
            sandbox_profile=_pin(REVIEW),
            workflow_type=_pin(SANDBOX),
        )
    )

    assert sorted(_codes(check)) == [
        "CAPABILITY_KIND_MISMATCH",
        "CAPABILITY_KIND_MISMATCH",
        "CAPABILITY_NOT_FOUND",
        "CAPABILITY_PIN_INVALID",
    ]
    assert {refusal.pointer for refusal in check.refusals} == {
        "/capabilities/0",
        "/capabilities/1",
        "/sandbox_profile",
        "/workflow_type",
    }
