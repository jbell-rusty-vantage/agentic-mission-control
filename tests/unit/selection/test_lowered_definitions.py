"""Per-manifest lowered definitions are never presented as reusable types.

A submitted manifest leaves six definitions in the catalog: a Workflow Type of its own with its
blueprint and four profiles. The rows here are the real lowering of a real manifest
(`tests/unit/guide/support.lowered_rows`), so the marker is held to what the lowering writes:
the lowered Workflow Type admits only the manifest input contract, and the other five are the
rows it allows. A search and a listing leave them out, say how many, and return them on request;
the guide counts the published Workflow Types apart from them. The deployment's bound sandbox
profiles are listed by the `sandbox_profile` facet and accepted by the draft check.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args

from mission_control.adapters.deep_agents.describe import SANDBOX_BACKEND_FACTS
from mission_control.application.capabilities.capability_search import CapabilitySearchResponse
from mission_control.application.resolution.registries import (
    ApplicationRegistry,
    LaneRegistry,
    ModelCatalog,
)
from mission_control.application.resolution.resolver import RuntimeResolver
from mission_control.application.selection.workspace import (
    DEFINITION_LISTING,
    SelectionSearchRequest,
    SelectionWorkspace,
)
from mission_control.bootstrap.selection import bound_sandbox_details, bound_sandbox_profiles
from mission_control.domain.authoring.contracts import DefinitionKind, PublishedDefinition
from mission_control.domain.authoring.manifest_lowering import (
    MANIFEST_INPUT_CONTRACT,
    is_manifest_lowered,
    manifest_lowered_refs,
)
from mission_control.domain.coordinator.contracts import CapabilitySearchRequest
from mission_control.domain.execution.contracts import DeepAgentSandboxComponent
from tests.conformance.lanes.compile.stub import STUB_DECLARATION
from tests.conformance.resolution.fixtures import APPLICATIONS, MODELS
from tests.unit.guide.support import (
    SANDBOX_DETAILS,
    SANDBOXES,
    lowered_rows,
    stub_guide,
    workspace_entries,
)
from tests.unit.selection.test_selection_workspace import (
    CATALOG_SCOPE,
    NARROW_WORKFLOW,
    OPEN_WORKFLOW,
    RESEARCH,
    ROWS,
    FakeDefinitions,
    _draft,
    _hit,
    _pin,
    _registration,
)

LOWERED = lowered_rows()
LOWERED_KINDS = frozenset(row.ref.kind for row in LOWERED)


class RankingSearch:
    """A catalog search that ranks every row of the requested kinds it was given."""

    def __init__(self, rows: Sequence[PublishedDefinition]) -> None:
        self._rows = tuple(rows)

    async def search(self, request: CapabilitySearchRequest) -> CapabilitySearchResponse:
        rows = [row for row in self._rows if row.ref.kind in request.kinds]
        return CapabilitySearchResponse(
            hits=tuple(_hit(row, rank) for rank, row in enumerate(rows, start=1)),
            search_mode="lexical",
        )


def workspace(rows: Sequence[PublishedDefinition] = (*ROWS, *LOWERED)) -> SelectionWorkspace:
    lanes = LaneRegistry(allow_unqualified=True)
    lanes.register(_registration(STUB_DECLARATION))
    models = ModelCatalog(MODELS)
    applications = ApplicationRegistry(APPLICATIONS)
    return SelectionWorkspace(
        application_id="biotech",
        lanes=lanes,
        models=models,
        applications=applications,
        admission=RuntimeResolver(lanes, applications, models, allow_unqualified_lanes=True),
        catalog_scope=CATALOG_SCOPE,
        search=RankingSearch(rows),  # type: ignore[arg-type]
        definitions=FakeDefinitions(rows),
        **workspace_entries(),
    )


def test_the_marker_is_the_lowering_s_own_input_contract() -> None:
    workflow = LOWERED[0]

    assert workflow.ref.kind is DefinitionKind.WORKFLOW_TYPE
    assert workflow.definition.input_admission_contract == MANIFEST_INPUT_CONTRACT  # type: ignore[union-attr]
    assert is_manifest_lowered(workflow.definition)
    # A curated Workflow Type states its own input admission contract.
    assert not is_manifest_lowered(OPEN_WORKFLOW.definition)
    assert not is_manifest_lowered(RESEARCH.definition)
    # One submitted manifest: its Workflow Type and the five rows it allows, by field.
    assert {
        DefinitionKind.WORKFLOW_TYPE,
        DefinitionKind.BLUEPRINT,
        DefinitionKind.CONTROL_PROFILE,
        DefinitionKind.RUNTIME_PROFILE,
        DefinitionKind.WORKSPACE_TEMPLATE,
        DefinitionKind.EVALUATION_PROFILE,
    } == LOWERED_KINDS
    assert manifest_lowered_refs((*ROWS, *LOWERED)) == {
        (row.ref.kind.value, row.ref.logical_id, row.ref.digest) for row in LOWERED
    }
    assert manifest_lowered_refs(ROWS) == frozenset()


async def test_a_listing_leaves_lowered_definitions_out_and_says_so() -> None:
    types = frozenset({"workflow_type"})
    listed = await workspace().search(SelectionSearchRequest(facets=types))
    every = await workspace().search(SelectionSearchRequest(facets=types, include_lowered=True))

    assert [hit.ref for hit in listed.hits] == [_pin(NARROW_WORKFLOW), _pin(OPEN_WORKFLOW)]
    assert (listed.total, listed.lowered_hidden) == (2, 1)
    assert listed.catalog_search_mode == DEFINITION_LISTING
    assert "1 definitions lowered from submitted manifests are left out" in listed.notes[0]
    assert "`include_lowered`" in listed.notes[0]
    assert (every.total, every.lowered_hidden, every.notes) == (3, 0, ())
    assert _pin(LOWERED[0]) in [hit.ref for hit in every.hits]
    # A catalog without lowered rows answers as before: nothing hidden, nothing noted.
    plain = await workspace(ROWS).search(SelectionSearchRequest(facets=types))
    assert (plain.total, plain.lowered_hidden, plain.notes) == (2, 0, ())
    assert "lowered_hidden" not in plain.model_dump(mode="json")


async def test_every_lowered_kind_is_left_out_when_listed_by_kind() -> None:
    by_kind = await workspace().search(
        SelectionSearchRequest(kinds=LOWERED_KINDS - {DefinitionKind.WORKFLOW_TYPE})
    )
    shown = await workspace().search(
        SelectionSearchRequest(
            kinds=LOWERED_KINDS - {DefinitionKind.WORKFLOW_TYPE}, include_lowered=True
        )
    )

    assert (by_kind.total, by_kind.lowered_hidden) == (0, 5)
    assert shown.total == 5 and {hit.kind for hit in shown.hits} == {
        kind.value for kind in LOWERED_KINDS - {DefinitionKind.WORKFLOW_TYPE}
    }


async def test_a_ranked_search_leaves_lowered_hits_out_too() -> None:
    types = frozenset({"workflow_type"})
    ranked = await workspace().search(SelectionSearchRequest(query="workflow", facets=types))
    every = await workspace().search(
        SelectionSearchRequest(query="workflow", facets=types, include_lowered=True)
    )

    assert {hit.ref for hit in ranked.hits} == {_pin(OPEN_WORKFLOW), _pin(NARROW_WORKFLOW)}
    assert ranked.lowered_hidden == 1 and "left out" in ranked.notes[-1]
    assert _pin(LOWERED[0]) in {hit.ref for hit in every.hits} and every.lowered_hidden == 0


async def test_the_guide_counts_published_workflow_types_apart_from_the_lowered() -> None:
    guide = stub_guide(rows=(*ROWS, *LOWERED))
    workflows = (await guide.topic("workflows")).markdown
    capabilities = (await guide.topic("capabilities")).markdown
    index = (await guide.index()).markdown

    assert (
        "Published Workflow Types that are not lowered from a manifest: 2. Lowered from "
        "submitted manifests and left out of listings: 1." in workflows
    )
    assert "A lowered definition belongs to that one manifest and is not reusable" in workflows
    assert '`mission_search(facets=["workflow_type"], include_lowered=true)`' in workflows
    # The counts are the curated catalog; the lowered rows are named once, as not counted.
    assert "| `workflow_type` | 2 |" in capabilities
    assert "Not counted: 6 definitions lowered from submitted manifests" in capabilities
    assert "blueprint" not in capabilities and "runtime_profile" not in capabilities
    assert f"{len(ROWS)} published catalog definitions" in index

    plain = (await stub_guide().topic("capabilities")).markdown
    assert "Not counted" not in plain


async def test_the_bound_sandbox_profiles_are_listed_and_checked() -> None:
    name = next(iter(SANDBOXES))
    listed = await workspace().search(SelectionSearchRequest(facets=frozenset({"sandbox_profile"})))
    ranked = await workspace().search(SelectionSearchRequest(query="sandbox", limit=50))

    # The deployment's bound profiles first (what a manifest names), then the catalog's rows.
    assert listed.hits[0].ref == f"sandbox:{name}" and listed.hits[0].title == name
    assert listed.hits[0].summary == SANDBOXES[name] and listed.total == 2
    assert f"sandbox:{name}" in [hit.ref for hit in ranked.hits]

    by_name = await workspace().check(_draft(sandbox_profile=name))
    by_ref = await workspace().check(_draft(sandbox_profile=f"sandbox:{name}"))
    unbound = await workspace().check(_draft(sandbox_profile="sandbox:nowhere"))

    assert by_name.admissible and by_name.sandbox_profile is not None
    assert by_name.sandbox_profile.found and by_name.sandbox_profile.title == name
    assert by_ref.admissible and by_ref.sandbox_profile == by_name.sandbox_profile.model_copy(
        update={"pin": f"sandbox:{name}"}
    )
    assert not unbound.admissible
    assert [refusal.code for refusal in unbound.refusals] == ["SANDBOX_PROFILE_UNBOUND"]
    assert name in unbound.refusals[0].reason

    # The describe answer is the launch binding: what the backend gives a node, not a name.
    described = await stub_guide().describe(f"sandbox:{name}")
    assert described.kind == "sandbox_profile" and described.markdown is None
    assert described.data == {
        "profile": name,
        "summary": SANDBOXES[name],
        "manifest_field": "environment.sandbox.profile",
        **{key: value for key, value in SANDBOX_DETAILS[name].items() if key != "summary"},
    }
    assert described.data["backend"] == "docker"
    assert described.data["execution"].startswith("commands run in one local container")
    assert described.data["network"].startswith("none")


def test_the_launch_bindings_say_what_each_sandbox_profile_gives(tmp_path: Path) -> None:
    """Two profiles that bind one sandbox say so; each line says what the backend suits."""

    component = {
        "ref": {
            "schema_version": "1",
            "kind": "sandbox_profile",
            "logical_id": "sandbox.state",
            "revision": 1,
            "digest": "sha256:" + "7" * 64,
            "lifecycle_status": "published",
            "payload_ref": None,
        },
        "backend": "state",
        "runtime_digest": "sha256:" + "c" * 64,
        "snapshot_ref": None,
        "credential_refs": [],
        "idle_ttl_seconds": 300,
    }
    docker = component | {"backend": "docker", "idle_ttl_seconds": 900}
    path = tmp_path / "bindings.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "mc.manifest_launch_bindings.v2",
                "sandbox_profiles": {
                    "research.standard": component,
                    "ingestion.standard": component,
                    "build.isolated": docker,
                },
            }
        ),
        encoding="utf-8",
    )
    settings: Any = SimpleNamespace(manifest_launch_bindings_path=path)

    details = bound_sandbox_details(settings)
    lines = bound_sandbox_profiles(settings)

    assert details is not None and lines is not None
    assert list(details) == ["build.isolated", "ingestion.standard", "research.standard"]
    research = details["research.standard"]
    assert research["backend"] == "state" and research["idle_ttl_seconds"] == 300
    assert research["execution"] == SANDBOX_BACKEND_FACTS["state"]["execution"]
    assert research["definition"] == "sandbox.state@1"
    assert research["same_binding_as"] == ["ingestion.standard"]
    assert research["starts_from_snapshot"] is False and research["secret_names"] == []
    assert details["build.isolated"]["same_binding_as"] == []
    assert details["build.isolated"]["network"].startswith("none")
    # The one line a listing shows: the backend, what it suits, and its twin.
    assert lines["research.standard"].startswith("`state` backend: ")
    assert "no command has to run" in lines["research.standard"]
    assert "binds the same sandbox as `ingestion.standard`" in lines["research.standard"]
    assert "binds the same sandbox" not in lines["build.isolated"]
    # Every backend a binding may name has its facts.
    backends = get_args(DeepAgentSandboxComponent.model_fields["backend"].annotation)
    assert set(backends) == set(SANDBOX_BACKEND_FACTS)
    # A process that reads no launch bindings cannot say.
    assert bound_sandbox_details(SimpleNamespace(manifest_launch_bindings_path=None)) is None  # type: ignore[arg-type]
