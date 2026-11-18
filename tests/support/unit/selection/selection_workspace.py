"""Builders, constants and fakes that other test files import.

Moved from tests/unit/selection/test_selection_workspace.py.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from mission_control.application.capabilities.capability_search import CapabilitySearchResponse
from mission_control.application.capabilities.capability_search_repository import (
    CapabilitySearchUnavailable,
)
from mission_control.application.resolution.ports import LaneRegistration
from mission_control.application.resolution.registries import (
    ApplicationRegistry,
    DescribeOnlyLane,
    LaneRegistry,
    ModelCatalog,
)
from mission_control.application.resolution.resolver import RuntimeResolver
from mission_control.application.selection.workspace import SelectionDraft, SelectionWorkspace
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    AuthorityCeiling,
    CapabilityDefinition,
    CapabilityKind,
    CatalogPayloadRef,
    DefinitionKind,
    ExactDefinitionRef,
    PublishedDefinition,
    SkillDefinition,
    SkillFileManifestEntry,
    SourceProvenance,
    WorkflowTypeDefinition,
    WorkflowWorkspaceContract,
)
from mission_control.domain.capabilities.catalog_entry import capability_pin
from mission_control.domain.capabilities.host_support import (
    CapabilityHostSupport,
    HostProfileSupport,
    HostSupportStatus,
    LaneProfile,
)
from mission_control.domain.coordinator.contracts import (
    AuthorizationState,
    CapabilitySearchHit,
    CapabilitySearchRequest,
    PolicyReason,
    PolicyReasonCode,
)
from mission_control.domain.resolution.profiles import LaneDeclaration
from tests.conformance.lanes.compile.stub import (
    NARROW_DECLARATION,
    STUB_DECLARATION,
    StubLaneAdapter,
)
from tests.conformance.resolution.fixtures import APPLICATIONS, MODELS

NOW = datetime(2026, 10, 31, tzinfo=UTC)
CATALOG_SCOPE = "mc/installation/ai-engineer/catalog"


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ref(kind: DefinitionKind, logical_id: str) -> ExactDefinitionRef:
    return ExactDefinitionRef(
        kind=kind, logical_id=logical_id, revision=1, digest=_digest(logical_id)
    )


def _published(definition: Any) -> PublishedDefinition:
    return PublishedDefinition(
        ref=ExactDefinitionRef(
            kind=definition.kind,
            logical_id=definition.logical_id,
            revision=1,
            digest=sha256_digest(definition),
        ),
        definition=definition,
        published_at=NOW,
        published_by="fixture",
    )


def _skill(
    logical_id: str, *, lanes: Iterable[LaneProfile], requires: frozenset[str] = frozenset()
) -> PublishedDefinition:
    name = logical_id.split(".", 1)[1]
    manifest = _digest(logical_id)
    supported = frozenset(lanes)
    return _published(
        SkillDefinition(
            logical_id=logical_id,
            title=f"Skill {name}",
            description=f"The {name} procedure",
            skill_name=name,
            frontmatter={"name": name, "description": name},
            body_summary=name,
            bundle_ref=CatalogPayloadRef(
                uri=f"repo://tests/{logical_id}",
                digest=manifest,
                media_type="application/vnd.belllabs.skill-manifest+json",
                size_bytes=128,
            ),
            manifest_digest=manifest,
            file_manifest=(
                SkillFileManifestEntry(path="SKILL.md", digest=_digest("SKILL.md"), size_bytes=8),
            ),
            source_provenance=SourceProvenance(
                source="belllabs",
                locator=f"repo://tests/{logical_id}",
                upstream_identity=logical_id,
                upstream_version="1.0.0",
            ),
            review_status="approved",
            required_capabilities=requires,
            host_support=CapabilityHostSupport(
                profiles={
                    lane: HostProfileSupport(
                        status=HostSupportStatus.SUPPORTED
                        if lane in supported
                        else HostSupportStatus.UNSUPPORTED
                    )
                    for lane in (LaneProfile.DEEP_AGENTS, LaneProfile.CLAUDE_AGENT_SDK)
                }
            ),
        )
    )


def _capability(kind: DefinitionKind, logical_id: str) -> PublishedDefinition:
    family = {
        DefinitionKind.MIDDLEWARE: CapabilityKind.MIDDLEWARE,
        DefinitionKind.SANDBOX_PROFILE: CapabilityKind.SANDBOX,
    }[kind]
    return _published(
        CapabilityDefinition(
            logical_id=logical_id,
            kind=kind,
            title=logical_id,
            description=f"{logical_id} capability",
            capability_kind=family,
            maturity="qualified",
            attachment_targets=frozenset({"agent.main"}),
        )
    )


def _workflow_type(logical_id: str, *, ceiling: frozenset[str]) -> PublishedDefinition:
    return _published(
        WorkflowTypeDefinition(
            logical_id=logical_id,
            title="Research workflow",
            description="A fixture Workflow Type",
            purpose="Exercise the authority-ceiling fit",
            input_admission_contract="contract:input@1",
            invariants=frozenset({"contract:invariant@1"}),
            allowed_blueprints=frozenset({_ref(DefinitionKind.BLUEPRINT, "bp")}),
            allowed_control_profiles=frozenset({_ref(DefinitionKind.CONTROL_PROFILE, "cp")}),
            allowed_runtime_profiles=frozenset({_ref(DefinitionKind.RUNTIME_PROFILE, "rp")}),
            allowed_workspace_templates=frozenset({_ref(DefinitionKind.WORKSPACE_TEMPLATE, "wt")}),
            allowed_evaluation_profiles=frozenset({_ref(DefinitionKind.EVALUATION_PROFILE, "ep")}),
            authority_ceiling=AuthorityCeiling(capabilities=ceiling, max_concurrency=2),
            workspace_contract=WorkflowWorkspaceContract(),
        )
    )


RESEARCH = _skill(
    "skill.web-research", lanes=(LaneProfile.DEEP_AGENTS,), requires=frozenset({"web.fetch"})
)
REVIEW = _skill(
    "skill.code-review",
    lanes=(LaneProfile.DEEP_AGENTS, LaneProfile.CLAUDE_AGENT_SDK),
)
MIDDLEWARE = _capability(DefinitionKind.MIDDLEWARE, "middleware.summarize")
SANDBOX = _capability(DefinitionKind.SANDBOX_PROFILE, "sandbox.local-docker")
OPEN_WORKFLOW = _workflow_type("workflow.research", ceiling=frozenset({"web.fetch", "sandbox"}))
NARROW_WORKFLOW = _workflow_type("workflow.offline", ceiling=frozenset({"sandbox"}))
ROWS = (RESEARCH, REVIEW, MIDDLEWARE, SANDBOX, OPEN_WORKFLOW, NARROW_WORKFLOW)


def _pin(row: PublishedDefinition) -> str:
    return capability_pin(row).render()


class FakeDefinitions:
    """The published definitions (fixture rows by default), counting each read."""

    def __init__(self, rows: Sequence[PublishedDefinition] = ROWS) -> None:
        self.rows = tuple(rows)
        self.reads = 0

    async def list_published_definitions(self) -> tuple[PublishedDefinition, ...]:
        self.reads += 1
        return self.rows


class FakeSearch:
    """Returns the rows of the requested kinds in fixture order, recording each request."""

    def __init__(self, *, unavailable: bool = False) -> None:
        self.requests: list[CapabilitySearchRequest] = []
        self._unavailable = unavailable

    async def search(self, request: CapabilitySearchRequest) -> CapabilitySearchResponse:
        self.requests.append(request)
        if self._unavailable:
            raise CapabilitySearchUnavailable("search_privileges_missing", "lexical")
        rows = [row for row in ROWS if row.ref.kind in request.kinds]
        if request.host_profiles:
            rows = [
                row
                for row in rows
                if isinstance(getattr(row.definition, "host_support", None), CapabilityHostSupport)
                and all(row.definition.host_support.supports(p) for p in request.host_profiles)  # type: ignore[union-attr]
            ]
        return CapabilitySearchResponse(
            hits=tuple(_hit(row, rank) for rank, row in enumerate(rows, start=1)),
            search_mode="lexical",
        )


def _hit(row: PublishedDefinition, rank: int) -> CapabilitySearchHit:
    return CapabilitySearchHit(
        exact_ref=row.ref,
        kind=row.ref.kind,
        title=row.definition.title,
        summary=row.definition.description,
        lexical_rank=rank,
        fused_rank=1.0 / (60 + rank),
        compatibility_summary="compatible",
        authorization_state=AuthorizationState.SELECTABLE,
        reasons=(PolicyReason(code=PolicyReasonCode.SELECTABLE, message="Selectable."),),
        source_digest=row.ref.digest,
        indexed_at=NOW,
        projection_generation="generation-1",
        pin=_pin(row),
    )


def _registration(declaration: LaneDeclaration) -> LaneRegistration:
    return LaneRegistration(
        profile=declaration.lane_profile,
        declaration=declaration,
        adapter=StubLaneAdapter(declaration),
        harness_factory=lambda _deps: DescribeOnlyLane(declaration.describe),
    )


def _workspace(
    *,
    declarations: Iterable[LaneDeclaration] = (STUB_DECLARATION, NARROW_DECLARATION),
    allow_unqualified: bool = True,
    search: Any = None,
    application_id: str = "ai-engineer",
    definitions: FakeDefinitions | None = None,
    clock: Any = None,
) -> SelectionWorkspace:
    lanes = LaneRegistry(allow_unqualified=allow_unqualified)
    for declaration in declarations:
        lanes.register(_registration(declaration))
    applications = ApplicationRegistry(APPLICATIONS)
    models = ModelCatalog(MODELS)
    return SelectionWorkspace(
        application_id=application_id,
        lanes=lanes,
        models=models,
        applications=applications,
        admission=RuntimeResolver(
            lanes, applications, models, allow_unqualified_lanes=allow_unqualified
        ),
        catalog_scope=CATALOG_SCOPE,
        search=search if search is not None else FakeSearch(),
        definitions=definitions if definitions is not None else FakeDefinitions(),
        **({"clock": clock} if clock is not None else {}),
    )


def _draft(**overrides: Any) -> SelectionDraft:
    values: dict[str, Any] = {
        "lane_profile": "deep_agents",
        "model_profile": "producer.default",
        "family": "StageGraph",
        "data_class": "internal",
    }
    return SelectionDraft.model_validate({**values, **overrides})
