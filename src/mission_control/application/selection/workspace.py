"""The Selection Workspace: one search and one read-only check over a draft selection.

A coordinator choosing where and how a node runs needs five answers that live in five places:
the capabilities and the catalog's sandbox profiles and Workflow Types (Capability Search), the
lanes (each registered Lane Declaration and its describe) and the models (the Model Catalog).
`SelectionWorkspace.search` asks each place through its existing port and merges the ranked
lists by reciprocal rank, so one answer carries a stable reference per hit (a Capability Pin,
`lane:<profile>` or `model:<profile>`) and why it matched. A facet that cannot answer here (no
catalog search composed, or the search store refused) is reported, never silently dropped.

`SelectionWorkspace.check` takes a draft (application, lane, model profile, family, data class,
capability pins, sandbox profile pin, Workflow Type pin) and returns a structured decision:
the resolution seam's admission (`RuntimeResolver.admit`: lane, application, model route, data
class, family), the lane's qualification as `RuntimeResolver.resolve` would refuse it, the
model's Data Class ceiling, each pin's host support on the lane (the compiler's rule for the
host-filtered kinds), the lane's declared support for the pin's configuration item kind, and
the fit of each pin's required capabilities under the Workflow Type's authority ceiling. It is
read-only, launches nothing, and names what it did not check (`not_checked`): the lane's
compile and seal need the compiled node configuration and the launch process's deployment
facts, so `mission compile` and `preflight` remain the authority before submit.

Provider-neutral: no lane, vendor or application is named here; every fact comes from a
registry, a declaration or a catalog row.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from mission_control.application.authoring.manifest_service import HOST_FILTERED_KINDS
from mission_control.application.capabilities.capability_search import CapabilitySearchResponse
from mission_control.application.capabilities.capability_search_repository import (
    CapabilitySearchUnavailable,
)
from mission_control.application.capabilities.catalog import find_published_by_pin
from mission_control.application.resolution.ports import (
    ApplicationRegistry,
    LaneRegistration,
    ModelCatalog,
)
from mission_control.application.resolution.resolver import (
    APPLICATION_POINTER,
    DATA_CLASS_POINTER,
    FAMILY_POINTER,
    LANE_POINTER,
    MODEL_POINTER,
)
from mission_control.domain.authoring.contracts import (
    DefinitionKind,
    PublishedDefinition,
    WorkflowTypeDefinition,
)
from mission_control.domain.capabilities.host_support import (
    CapabilityHostSupport,
    HostSupportStatus,
    LaneProfile,
)
from mission_control.domain.capabilities.pins import CapabilityPin, CapabilityPinError
from mission_control.domain.coordinator.contracts import (
    CapabilitySearchHit,
    CapabilitySearchRequest,
)
from mission_control.domain.execution.data_class import DATA_CLASSES, DataClass, DataClassSource
from mission_control.domain.execution.lanes import DEFAULT_LANE_PROFILE, LaneDescribe
from mission_control.domain.resolution.configuration import ConfigurationItemKind, Family
from mission_control.domain.resolution.profiles import LaneDeclaration, ModelProfile
from mission_control.domain.resolution.resolved import ResolutionRefused
from mission_control.domain.resolution.selection import LaneAdmission

SELECTION_SEARCH_SCHEMA: Final = "mc.selection_search.v1"
SELECTION_CHECK_SCHEMA: Final = "mc.selection_check.v1"
# The constant of the reciprocal-rank merge across facets (the catalog's own fusion uses 60).
MERGE_RRF_K: Final = 60

Facet = Literal["capability", "lane", "model", "sandbox_profile", "workflow_type"]
FACETS: Final[tuple[Facet, ...]] = (
    "capability",
    "lane",
    "model",
    "sandbox_profile",
    "workflow_type",
)
# The catalog kinds each catalog-backed facet searches.
FACET_KINDS: Final[Mapping[Facet, frozenset[DefinitionKind]]] = {
    "capability": frozenset(
        {
            DefinitionKind.SKILL,
            DefinitionKind.MCP_SERVER,
            DefinitionKind.MCP_TOOL,
            DefinitionKind.TOOL,
            DefinitionKind.PLUGIN,
            DefinitionKind.HOOK_SCRIPT,
            DefinitionKind.SUBAGENT_PROFILE,
            DefinitionKind.MIDDLEWARE,
            DefinitionKind.ENVIRONMENT_KIT,
        }
    ),
    "sandbox_profile": frozenset({DefinitionKind.SANDBOX_PROFILE}),
    "workflow_type": frozenset({DefinitionKind.WORKFLOW_TYPE}),
}
# The neutral configuration item kind a catalog kind becomes on a node (`ConfigurationItem`),
# where a lane declares its support. A plugin expands into its members; it has no item kind.
ITEM_KIND_OF: Final[Mapping[DefinitionKind, ConfigurationItemKind]] = {
    DefinitionKind.SKILL: "skill_bundle",
    DefinitionKind.MCP_SERVER: "mcp_server",
    DefinitionKind.MCP_TOOL: "mcp_server",
    DefinitionKind.TOOL: "tool",
    DefinitionKind.HOOK_SCRIPT: "hook_script",
    DefinitionKind.SUBAGENT_PROFILE: "subagent_profile",
    DefinitionKind.MIDDLEWARE: "middleware",
    DefinitionKind.ENVIRONMENT_KIT: "environment_kit",
    DefinitionKind.SANDBOX_PROFILE: "sandbox_profile",
}
# Query words that name a whole facet ("which harness ...") and so match every entry in it.
FACET_WORDS: Final[Mapping[Facet, frozenset[str]]] = {
    "lane": frozenset({"lane", "lanes", "harness", "harnesses"}),
    "model": frozenset({"model", "models"}),
}
# The resolver's manifest pointers, re-pointed into the draft's fields.
DRAFT_POINTERS: Final[Mapping[str, str]] = {
    LANE_POINTER: "/lane_profile",
    APPLICATION_POINTER: "/application_id",
    MODEL_POINTER: "/model_profile",
    DATA_CLASS_POINTER: "/data_class",
    FAMILY_POINTER: "/family",
}
NOT_CHECKED: Final[tuple[str, ...]] = (
    "lane compile and seal (RuntimeResolver.resolve steps 3-6): they need the compiled node "
    "configuration and the launch process's deployment facts; run `missionctl mission compile`",
    "whether this installation's workers serve each pinned digest (launch bindings)",
    "owner prerequisites, secrets and placement; run `missionctl preflight`",
    "the application's Knowledge Services apply-contract alignment",
)


# -- ports ---------------------------------------------------------------------------------------


class CapabilitySearchPort(Protocol):
    """`CapabilitySearchService.search` (hybrid RRF over the catalog Search Projection)."""

    async def search(self, request: CapabilitySearchRequest) -> CapabilitySearchResponse: ...


class LaneDescribes(Protocol):
    """What the workspace reads from the Lane Registry (`registries.LaneRegistry`)."""

    @property
    def allow_unqualified(self) -> bool: ...

    def profiles(self) -> tuple[str, ...]: ...

    def describe(self, lane_profile: str) -> LaneDescribe:
        """`LookupError` for a profile the registry does not hold."""
        ...

    def get(self, profile: str) -> LaneRegistration:
        """`KeyError` for a profile without a package registration."""
        ...


class SelectionAdmission(Protocol):
    """Steps 1 and 2 of the resolution seam (`RuntimeResolver.admit`)."""

    def admit(self, admission: LaneAdmission) -> ResolutionRefused | None: ...


# -- contracts -----------------------------------------------------------------------------------


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SelectionSearchRequest(_Frozen):
    query: str = Field(min_length=1, max_length=2_000)
    facets: frozenset[Facet] = frozenset(FACETS)
    # Narrows capabilities to those whose host support marks this lane `supported`, and models
    # to those whose vendor the lane routes (`native` or `emulated`).
    lane_profile: str | None = Field(default=None, min_length=1, max_length=64)
    limit: int = Field(default=20, ge=1, le=100)
    # Per catalog-backed facet.
    catalog_limit: int = Field(default=10, ge=1, le=50)


class SelectionHit(_Frozen):
    facet: Facet
    # What a draft names: a Capability Pin, `lane:<profile>` or `model:<profile>`.
    ref: str
    title: str
    summary: str
    # Reciprocal-rank merge score across facets, then the rank inside the facet.
    score: float
    facet_rank: int = Field(ge=1)
    reasons: tuple[str, ...] = Field(min_length=1)
    # Facet-specific facts: supported lanes, qualification, routes, kind.
    details: dict[str, object] = Field(default_factory=dict)


class FacetUnavailable(_Frozen):
    facet: Facet
    reason: str


class SelectionSearchResult(_Frozen):
    schema_version: Literal["mc.selection_search.v1"] = SELECTION_SEARCH_SCHEMA
    query: str
    facets: tuple[Facet, ...]
    hits: tuple[SelectionHit, ...]
    unavailable: tuple[FacetUnavailable, ...] = ()
    # The catalog's own mode (`hybrid` or `lexical`) when a catalog facet answered.
    catalog_search_mode: str | None = None


class SelectionDraft(_Frozen):
    """What a coordinator intends one node to run with, before it writes the manifest."""

    application_id: str | None = Field(default=None, min_length=1, max_length=64)
    lane_profile: str = Field(min_length=1, max_length=64)
    model_profile: str = Field(min_length=1, max_length=192)
    family: Family
    # Undeclared: the application's Data Class ceiling, as the seam treats an undeclared mission.
    data_class: DataClass | None = None
    capabilities: tuple[str, ...] = Field(default=(), max_length=64)
    sandbox_profile: str | None = None
    workflow_type: str | None = None


class SelectionRefusal(_Frozen):
    code: str
    # A JSON pointer into the draft.
    pointer: str
    reason: str
    remedy: str
    lane_profile: str | None = None
    # `resolver`: the resolution seam's own refusal; `workspace`: a catalog or ceiling check.
    source: Literal["resolver", "workspace"]


HostStatus = Literal["supported", "unqualified", "unsupported", "undeclared"]
_HOST_STATUS: Final[Mapping[HostSupportStatus, HostStatus]] = {
    HostSupportStatus.SUPPORTED: "supported",
    HostSupportStatus.UNQUALIFIED: "unqualified",
    HostSupportStatus.UNSUPPORTED: "unsupported",
}


class PinFit(_Frozen):
    pointer: str
    pin: str
    found: bool
    kind: DefinitionKind | None = None
    title: str | None = None
    # The pin's host support on the draft's lane (`undeclared`: its kind carries no matrix).
    host_status: HostStatus | None = None
    # The lane's declared support for the pin's configuration item kind.
    lane_item_support: str | None = None
    required_capabilities: tuple[str, ...] = ()
    # Under the Workflow Type's authority ceiling; `None` when the draft names no Workflow Type.
    within_authority: bool | None = None


class WorkflowTypeFit(_Frozen):
    pin: str
    found: bool
    title: str | None = None
    authority_capabilities: tuple[str, ...] = ()
    max_concurrency: int | None = None


class LaneFit(_Frozen):
    lane_profile: str
    registered: bool
    qualified: bool | None = None
    allow_unqualified: bool
    family_support: str | None = None


class ModelFit(_Frozen):
    model_profile: str
    found: bool
    vendor: str | None = None
    model_id: str | None = None
    route: str | None = None
    data_class_ceiling: DataClass | None = None


class SelectionCheck(_Frozen):
    schema_version: Literal["mc.selection_check.v1"] = SELECTION_CHECK_SCHEMA
    admissible: bool
    application_id: str
    data_class: DataClass
    data_class_source: DataClassSource
    lane: LaneFit
    model: ModelFit
    workflow_type: WorkflowTypeFit | None = None
    sandbox_profile: PinFit | None = None
    capabilities: tuple[PinFit, ...] = ()
    refusals: tuple[SelectionRefusal, ...] = ()
    not_checked: tuple[str, ...] = NOT_CHECKED


# -- the workspace -------------------------------------------------------------------------------


class SelectionWorkspace:
    """Search and check for one application's installation (see the module doc)."""

    def __init__(
        self,
        *,
        application_id: str,
        lanes: LaneDescribes,
        models: ModelCatalog,
        applications: ApplicationRegistry,
        admission: SelectionAdmission,
        catalog_scope: str | None = None,
        search: CapabilitySearchPort | None = None,
        definitions: object | None = None,
    ) -> None:
        self._application_id = application_id
        self._lanes = lanes
        self._models = models
        self._applications = applications
        self._admission = admission
        self._catalog_scope = catalog_scope
        self._search = search
        # `CatalogDefinitions` (`find_by_pin` or `list_published_definitions`).
        self._definitions = definitions

    @property
    def application_id(self) -> str:
        return self._application_id

    # -- search ----------------------------------------------------------------------------------

    async def search(self, request: SelectionSearchRequest) -> SelectionSearchResult:
        tokens = _tokens(request.query)
        ranked: dict[Facet, list[tuple[float, SelectionHit]]] = {}
        unavailable: list[FacetUnavailable] = []
        mode: str | None = None
        for facet in FACETS:
            if facet not in request.facets:
                continue
            if facet == "lane":
                ranked[facet] = self._lane_hits(tokens)
            elif facet == "model":
                ranked[facet] = self._model_hits(tokens, request.lane_profile)
            else:
                outcome = await self._catalog_hits(facet, request)
                if isinstance(outcome, FacetUnavailable):
                    unavailable.append(outcome)
                else:
                    ranked[facet], facet_mode = outcome
                    mode = mode or facet_mode
        return SelectionSearchResult(
            query=request.query,
            facets=tuple(facet for facet in FACETS if facet in request.facets),
            hits=_merge(ranked, request.limit),
            unavailable=tuple(unavailable),
            catalog_search_mode=mode,
        )

    def _lane_hits(self, tokens: frozenset[str]) -> list[tuple[float, SelectionHit]]:
        hits: list[tuple[float, SelectionHit]] = []
        for profile in self._lanes.profiles():
            describe = self._lanes.describe(profile)
            declaration = _declaration(self._lanes, profile)
            fields: list[tuple[str, str, float]] = [
                ("lane profile", profile, 3.0),
                ("lane", describe.lane, 3.0),
                ("placement", describe.placement, 1.0),
                ("qualification", "qualified" if describe.qualified else "unqualified", 1.0),
            ]
            details: dict[str, object] = {
                "lane": describe.lane,
                "placement": describe.placement,
                "qualified": describe.qualified,
                "describe_digest": describe.digest,
                "default": profile == DEFAULT_LANE_PROFILE,
            }
            if declaration is not None:
                families = {
                    family: support
                    for family, support in declaration.families.items()
                    if support != "unsupported"
                }
                routes = {
                    route.vendor: route.verdict
                    for route in declaration.model_routes
                    if route.verdict != "unsupported"
                }
                items = {
                    kind: support
                    for kind, support in declaration.items.items()
                    if support != "unsupported"
                }
                fields += [("runs family", family, 2.0) for family in families]
                fields += [("routes vendor", vendor, 2.0) for vendor in routes]
                fields += [
                    ("route mechanism", route.mechanism, 1.0)
                    for route in declaration.model_routes
                    if route.verdict != "unsupported"
                ]
                fields += [("supports item kind", kind, 1.0) for kind in items]
                details.update(families=families, model_routes=routes, items=items)
            score, reasons = _score(tokens, fields, FACET_WORDS["lane"], "lane")
            if score > 0:
                summary = (
                    f"{describe.lane} lane, {describe.placement} placement, "
                    f"{'qualified' if describe.qualified else 'unqualified'}"
                )
                hits.append(
                    (
                        score,
                        _hit("lane", f"lane:{profile}", profile, summary, reasons, details),
                    )
                )
        # Ties keep the default lane first, then the profile order.
        hits.sort(key=lambda item: (-item[0], item[1].ref != f"lane:{DEFAULT_LANE_PROFILE}"))
        return hits

    def _model_hits(
        self, tokens: frozenset[str], lane_profile: str | None
    ) -> list[tuple[float, SelectionHit]]:
        hits: list[tuple[float, SelectionHit]] = []
        for profile in self._models.profiles():
            model = self._models.get(profile)
            routes = self._routes(model)
            if lane_profile is not None and routes.get(lane_profile) not in {"native", "emulated"}:
                continue
            fields: list[tuple[str, str, float]] = [
                ("model profile", model.profile, 3.0),
                ("model id", model.model_id, 2.0),
                ("vendor", model.vendor, 2.0),
                ("data class ceiling", model.data_class_ceiling, 1.0),
                *(("supports", capability, 1.0) for capability in model.supports),
                *(
                    ("routed by lane", lane, 1.0)
                    for lane, verdict in routes.items()
                    if verdict in {"native", "emulated"}
                ),
            ]
            score, reasons = _score(tokens, fields, FACET_WORDS["model"], "model")
            if score > 0:
                details: dict[str, object] = {
                    "vendor": model.vendor,
                    "model_id": model.model_id,
                    "max_input_tokens": model.max_input_tokens,
                    "cost_per_million_input": model.cost_per_million_input,
                    "cost_per_million_output": model.cost_per_million_output,
                    "data_class_ceiling": model.data_class_ceiling,
                    "routes": routes,
                }
                summary = f"{model.vendor} {model.model_id}"
                hits.append(
                    (
                        score,
                        _hit("model", f"model:{profile}", profile, summary, reasons, details),
                    )
                )
        hits.sort(key=lambda item: -item[0])
        return hits

    def _routes(self, model: ModelProfile) -> dict[str, str]:
        """Each registered lane's verdict for the model's vendor (`unregistered`: no package
        registration in this process, so no declared route)."""

        routes: dict[str, str] = {}
        for profile in self._lanes.profiles():
            declaration = _declaration(self._lanes, profile)
            if declaration is None:
                routes[profile] = "unregistered"
                continue
            route = declaration.route(model.vendor)
            routes[profile] = route.verdict if route is not None else "unsupported"
        return routes

    async def _catalog_hits(
        self, facet: Facet, request: SelectionSearchRequest
    ) -> tuple[list[tuple[float, SelectionHit]], str] | FacetUnavailable:
        if self._search is None or self._catalog_scope is None:
            return FacetUnavailable(
                facet=facet, reason="no capability search is composed for this application"
            )
        host_profiles: frozenset[LaneProfile] = frozenset()
        if facet == "capability" and request.lane_profile is not None:
            try:
                host_profiles = frozenset({LaneProfile(request.lane_profile)})
            except ValueError:
                return FacetUnavailable(
                    facet=facet, reason=f"lane profile {request.lane_profile} is not a lane"
                )
        try:
            response = await self._search.search(
                CapabilitySearchRequest(
                    query=request.query,
                    kinds=FACET_KINDS[facet],
                    tenant_scope=self._catalog_scope,
                    host_profiles=host_profiles,
                    limit=request.catalog_limit,
                )
            )
        except CapabilitySearchUnavailable as error:
            return FacetUnavailable(facet=facet, reason=str(error))
        hits: list[tuple[float, SelectionHit]] = []
        for hit in response.hits:
            ref = _catalog_ref(hit)
            if ref is None:
                continue
            hits.append((hit.fused_rank, _catalog_hit(facet, ref, hit, response.search_mode)))
        return hits, response.search_mode

    # -- check -----------------------------------------------------------------------------------

    async def check(self, draft: SelectionDraft) -> SelectionCheck:
        refusals: list[SelectionRefusal] = []
        application_id = draft.application_id or self._application_id
        if application_id != self._application_id:
            refusals.append(
                _workspace_refusal(
                    "APPLICATION_OUT_OF_SCOPE",
                    "/application_id",
                    f"this workspace serves application {self._application_id}",
                    f"check the draft against application {application_id}'s own service",
                )
            )
        lane = self._lane_fit(draft)
        if lane.registered and lane.qualified is False and not lane.allow_unqualified:
            # What `RuntimeResolver.resolve` refuses first (`admit` leaves it to the worker).
            refusals.append(
                _resolver_refusal(
                    ResolutionRefused(
                        code="LANE_UNQUALIFIED",
                        pointer=LANE_POINTER,
                        lane_profile=draft.lane_profile,
                        reason=f"lane profile {draft.lane_profile} has no recorded qualification",
                        remedy="record a lane qualification, or enable unqualified lanes for a "
                        "local proof",
                    )
                )
            )
        model = self._model(draft.model_profile)
        if model is None:
            refusals.append(
                _resolver_refusal(
                    ResolutionRefused(
                        code="MODEL_UNKNOWN",
                        pointer=MODEL_POINTER,
                        reason=f"model profile {draft.model_profile} is not in the model catalog",
                        remedy=f"choose one of {', '.join(self._models.profiles()) or 'none'}",
                    )
                )
            )
        data_class, source = self._data_class(draft, application_id)
        admitted = self._admission.admit(
            LaneAdmission(
                lane_profile=draft.lane_profile,
                application_id=application_id,
                family=draft.family,
                data_class=data_class,
                vendor=model.vendor if model is not None else None,
            )
        )
        if admitted is not None:
            refusals.append(_resolver_refusal(admitted))
        if model is not None and not _within(data_class, model.data_class_ceiling):
            refusals.append(
                _resolver_refusal(
                    ResolutionRefused(
                        code="DATA_CLASS_NOT_ADMITTED",
                        pointer=DATA_CLASS_POINTER,
                        lane_profile=draft.lane_profile,
                        reason=f"model profile {model.profile} admits data up to "
                        f"{model.data_class_ceiling}; the draft's data class is {data_class}",
                        remedy="declare or lower the data class, or choose another model",
                    )
                )
            )
        workflow, ceiling = await self._workflow_type(draft.workflow_type, refusals)
        sandbox = (
            await self._pin_fit(
                "/sandbox_profile",
                draft.sandbox_profile,
                draft.lane_profile,
                frozenset({DefinitionKind.SANDBOX_PROFILE}),
                ceiling,
                refusals,
            )
            if draft.sandbox_profile is not None
            else None
        )
        capabilities = [
            await self._pin_fit(
                f"/capabilities/{index}",
                pin,
                draft.lane_profile,
                FACET_KINDS["capability"],
                ceiling,
                refusals,
            )
            for index, pin in enumerate(draft.capabilities)
        ]
        return SelectionCheck(
            admissible=not refusals,
            application_id=application_id,
            data_class=data_class,
            data_class_source=source,
            lane=lane,
            model=self._model_fit(draft, model),
            workflow_type=workflow,
            sandbox_profile=sandbox,
            capabilities=tuple(capabilities),
            refusals=tuple(refusals),
        )

    def _lane_fit(self, draft: SelectionDraft) -> LaneFit:
        try:
            describe = self._lanes.describe(draft.lane_profile)
        except LookupError:
            return LaneFit(
                lane_profile=draft.lane_profile,
                registered=False,
                allow_unqualified=self._lanes.allow_unqualified,
            )
        declaration = _declaration(self._lanes, draft.lane_profile)
        return LaneFit(
            lane_profile=draft.lane_profile,
            registered=True,
            qualified=describe.qualified,
            allow_unqualified=self._lanes.allow_unqualified,
            family_support=(
                declaration.families[draft.family] if declaration is not None else None
            ),
        )

    def _model(self, profile: str) -> ModelProfile | None:
        try:
            return self._models.get(profile)
        except KeyError:
            return None

    def _model_fit(self, draft: SelectionDraft, model: ModelProfile | None) -> ModelFit:
        if model is None:
            return ModelFit(model_profile=draft.model_profile, found=False)
        declaration = _declaration(self._lanes, draft.lane_profile)
        route = declaration.route(model.vendor) if declaration is not None else None
        return ModelFit(
            model_profile=model.profile,
            found=True,
            vendor=model.vendor,
            model_id=model.model_id,
            route=route.verdict if route is not None else None,
            data_class_ceiling=model.data_class_ceiling,
        )

    def _data_class(
        self, draft: SelectionDraft, application_id: str
    ) -> tuple[DataClass, DataClassSource]:
        if draft.data_class is not None:
            return draft.data_class, "declared"
        try:
            return self._applications.get(application_id).data_class_ceiling, "ceiling_default"
        except KeyError:
            # The admission refuses the unknown application; the most sensitive class keeps
            # every other check fail-closed meanwhile.
            return DATA_CLASSES[-1], "ceiling_default"

    async def _published(
        self, pointer: str, pin_text: str, refusals: list[SelectionRefusal]
    ) -> PublishedDefinition | None:
        try:
            pin = CapabilityPin.parse(pin_text)
        except CapabilityPinError as error:
            refusals.append(
                _workspace_refusal(
                    "CAPABILITY_PIN_INVALID", pointer, str(error), "copy the ref a search hit gave"
                )
            )
            return None
        if self._definitions is None:
            refusals.append(
                _workspace_refusal(
                    "CATALOG_UNAVAILABLE",
                    pointer,
                    "no catalog is composed for this application",
                    "check the draft where the application's catalog is served",
                )
            )
            return None
        published = await find_published_by_pin(self._definitions, pin)
        if published is None:
            refusals.append(
                _workspace_refusal(
                    "CAPABILITY_NOT_FOUND",
                    pointer,
                    f"no published catalog row for {pin.render()}",
                    "search again and pin a published row",
                )
            )
            return None
        if published.retired_at is not None:
            refusals.append(
                _workspace_refusal(
                    "CAPABILITY_RETIRED",
                    pointer,
                    f"{pin.render()} was retired",
                    "search again and pin its successor",
                )
            )
        return published

    async def _workflow_type(
        self, pin: str | None, refusals: list[SelectionRefusal]
    ) -> tuple[WorkflowTypeFit | None, frozenset[str] | None]:
        if pin is None:
            return None, None
        published = await self._published("/workflow_type", pin, refusals)
        if published is None:
            return WorkflowTypeFit(pin=pin, found=False), None
        definition = published.definition
        if not isinstance(definition, WorkflowTypeDefinition):
            refusals.append(
                _workspace_refusal(
                    "CAPABILITY_KIND_MISMATCH",
                    "/workflow_type",
                    f"{pin} is a {published.ref.kind}, not a workflow_type",
                    "pin a hit from the workflow_type facet",
                )
            )
            return WorkflowTypeFit(pin=pin, found=True, title=definition.title), None
        ceiling = definition.authority_ceiling
        return (
            WorkflowTypeFit(
                pin=pin,
                found=True,
                title=definition.title,
                authority_capabilities=tuple(sorted(ceiling.capabilities)),
                max_concurrency=ceiling.max_concurrency,
            ),
            ceiling.capabilities,
        )

    async def _pin_fit(
        self,
        pointer: str,
        pin: str,
        lane_profile: str,
        kinds: frozenset[DefinitionKind],
        ceiling: frozenset[str] | None,
        refusals: list[SelectionRefusal],
    ) -> PinFit:
        published = await self._published(pointer, pin, refusals)
        if published is None:
            return PinFit(pointer=pointer, pin=pin, found=False)
        kind = published.ref.kind
        definition = published.definition
        if kind not in kinds:
            refusals.append(
                _workspace_refusal(
                    "CAPABILITY_KIND_MISMATCH",
                    pointer,
                    f"{pin} is a {kind}; this slot takes {', '.join(sorted(kinds))}",
                    "pin a hit from the matching facet",
                )
            )
        host_status = _host_status(getattr(definition, "host_support", None), lane_profile)
        if kind in HOST_FILTERED_KINDS and host_status in {"unsupported", "unqualified"}:
            # The compiler's rule (`pin_lane_unsupported`): a host-filtered kind runs only on a
            # lane its host support marks `supported`.
            refusals.append(
                _workspace_refusal(
                    "CAPABILITY_LANE_UNSUPPORTED",
                    pointer,
                    f"{pin} is {host_status} on lane {lane_profile}",
                    "choose a lane the capability supports, or another capability",
                    lane_profile,
                )
            )
        item_kind = ITEM_KIND_OF.get(kind)
        declaration = _declaration(self._lanes, lane_profile)
        item_support = (
            declaration.items[item_kind]
            if declaration is not None and item_kind is not None
            else None
        )
        if item_support == "unsupported":
            refusals.append(
                _resolver_refusal(
                    ResolutionRefused(
                        code="ITEM_UNSUPPORTED_ON_LANE",
                        pointer=pointer,
                        lane_profile=lane_profile,
                        reason=f"lane {lane_profile} declares {item_kind} unsupported",
                        remedy=f"run {pin} on a lane that supports {item_kind}",
                    )
                )
            )
        required = frozenset(getattr(definition, "required_capabilities", frozenset()))
        within: bool | None = None
        if ceiling is not None:
            outside = sorted(required - ceiling)
            within = not outside
            if outside:
                refusals.append(
                    _workspace_refusal(
                        "AUTHORITY_CEILING_EXCEEDED",
                        pointer,
                        f"{pin} requires {', '.join(outside)}, outside the Workflow Type's "
                        "authority ceiling",
                        "choose another capability or a Workflow Type whose ceiling grants it",
                    )
                )
        return PinFit(
            pointer=pointer,
            pin=pin,
            found=True,
            kind=kind,
            title=definition.title,
            host_status=host_status,
            lane_item_support=item_support,
            required_capabilities=tuple(sorted(required)),
            within_authority=within,
        )


# -- helpers -------------------------------------------------------------------------------------


def _tokens(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", text.lower()))


def _score(
    tokens: frozenset[str],
    fields: Iterable[tuple[str, str, float]],
    facet_words: frozenset[str],
    facet: str,
) -> tuple[float, tuple[str, ...]]:
    """Weighted token overlap: each field adds its weight once per query token it contains."""

    score = 0.0
    reasons: list[str] = []
    for label, value, weight in fields:
        matched = sorted(tokens & _tokens(value))
        if matched:
            score += weight * len(matched)
            reasons.append(f"{label} {value!r} matches {', '.join(matched)}")
    named = sorted(tokens & facet_words)
    if named:
        score += 0.5
        reasons.append(f"the query names the {facet} facet ({', '.join(named)})")
    return score, tuple(reasons)


def _hit(
    facet: Facet,
    ref: str,
    title: str,
    summary: str,
    reasons: tuple[str, ...],
    details: dict[str, object],
) -> SelectionHit:
    # Score and rank are placeholders until the merge assigns them.
    return SelectionHit(
        facet=facet,
        ref=ref,
        title=title,
        summary=summary,
        score=0.0,
        facet_rank=1,
        reasons=reasons,
        details=details,
    )


def _catalog_ref(hit: CapabilitySearchHit) -> str | None:
    if hit.pin is not None:
        return hit.pin
    if hit.exact_ref is not None:
        ref = hit.exact_ref
        return f"{ref.kind}:{ref.logical_id}@{ref.revision}#{ref.digest}"
    return None


def _catalog_hit(facet: Facet, ref: str, hit: CapabilitySearchHit, mode: str) -> SelectionHit:
    reasons = [f"catalog {mode} search, fused score {hit.fused_rank:.4f}"]
    if hit.lexical_rank is not None:
        reasons.append(f"full-text rank {hit.lexical_rank}")
    if hit.semantic_rank is not None:
        reasons.append(f"semantic rank {hit.semantic_rank}")
    reasons.append(hit.compatibility_summary)
    return _hit(
        facet,
        ref,
        hit.title,
        hit.summary,
        tuple(reasons),
        {
            "kind": hit.kind.value,
            "supported_profiles": [profile.value for profile in hit.supported_profiles],
            "authorization_state": str(hit.authorization_state),
        },
    )


def _merge(
    ranked: Mapping[Facet, Sequence[tuple[float, SelectionHit]]], limit: int
) -> tuple[SelectionHit, ...]:
    """Reciprocal rank across facets (`1 / (k + rank)`): facets score on different scales, so
    only their order is fused. Ties break on the score relative to the facet's best, then on
    the facet order."""

    merged: list[tuple[float, float, int, SelectionHit]] = []
    for facet_index, facet in enumerate(FACETS):
        entries = ranked.get(facet, ())
        best = max((score for score, _ in entries), default=0.0)
        for rank, (score, hit) in enumerate(entries, start=1):
            fused = 1.0 / (MERGE_RRF_K + rank)
            relative = score / best if best > 0 else 0.0
            merged.append(
                (
                    fused,
                    relative,
                    facet_index,
                    hit.model_copy(update={"score": round(fused, 6), "facet_rank": rank}),
                )
            )
    merged.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return tuple(item[3] for item in merged[:limit])


def _declaration(lanes: LaneDescribes, profile: str) -> LaneDeclaration | None:
    try:
        return lanes.get(profile).declaration
    except KeyError:
        return None


def _host_status(support: object, lane_profile: str) -> HostStatus:
    if not isinstance(support, CapabilityHostSupport):
        return "undeclared"
    try:
        return _HOST_STATUS[support.status(lane_profile)]
    except ValueError:
        # Not a Lane Profile the host-support vocabulary knows.
        return "unsupported"


def _within(data_class: DataClass, ceiling: DataClass) -> bool:
    return DATA_CLASSES.index(data_class) <= DATA_CLASSES.index(ceiling)


def _resolver_refusal(refusal: ResolutionRefused) -> SelectionRefusal:
    return SelectionRefusal(
        code=refusal.code,
        pointer=DRAFT_POINTERS.get(refusal.pointer, refusal.pointer),
        reason=refusal.reason,
        remedy=refusal.remedy,
        lane_profile=refusal.lane_profile,
        source="resolver",
    )


def _workspace_refusal(
    code: str, pointer: str, reason: str, remedy: str, lane_profile: str | None = None
) -> SelectionRefusal:
    return SelectionRefusal(
        code=code,
        pointer=pointer,
        reason=reason,
        remedy=remedy,
        lane_profile=lane_profile,
        source="workspace",
    )


__all__ = [
    "FACETS",
    "FACET_KINDS",
    "SELECTION_CHECK_SCHEMA",
    "SELECTION_SEARCH_SCHEMA",
    "CapabilitySearchPort",
    "Facet",
    "FacetUnavailable",
    "LaneDescribes",
    "LaneFit",
    "ModelFit",
    "PinFit",
    "SelectionAdmission",
    "SelectionCheck",
    "SelectionDraft",
    "SelectionHit",
    "SelectionRefusal",
    "SelectionSearchRequest",
    "SelectionSearchResult",
    "SelectionWorkspace",
    "WorkflowTypeFit",
]
