"""The Selection Workspace: one search and one read-only check over a draft selection.

A coordinator choosing where and how a node runs needs five answers that live in five places:
the capabilities and the catalog's sandbox profiles and Workflow Types (Capability Search), the
lanes (each registered Lane Declaration and its describe) and the models (the Model Catalog).
`SelectionWorkspace.search` asks each place through its existing port and merges the ranked
lists by reciprocal rank, so one answer carries a stable reference per hit (a Capability Pin,
`lane:<profile>` or `model:<profile>`) and why it matched. A facet that cannot answer here (no
catalog search composed, or the search store refused) is reported, never silently dropped.

Two more answers keep a search from being silently empty. An empty query **lists** the requested
facets instead of ranking them: every lane, every Model Profile and every published definition
of the facet's catalog kinds, by name, behind `offset` and `limit`. A query the catalog search
answers with nothing is checked against the published definitions: when the Search Projection
does not return a published definition searched by its own title, the workspace scans the
published definitions itself (name, kind, description) and says so: a note names the scanned
facets, and `catalog_search_mode` is `definition_scan` when the catalog ranked none.

Two facets are not catalog definitions. `template` lists the curated mission templates the
composition hands in (a hit's ref is `template:<id>`). `sandbox_profile` lists first the sandbox
profiles this deployment binds, the names a manifest writes in `environment.sandbox.profile`
(`sandbox:<name>`), then the catalog's sandbox profile definitions.

A submitted manifest lowers into one Workflow Type of its own with its blueprint and profiles
(`manifest_lowering.manifest_lowered_refs`). Those rows belong to that manifest and are not
reusable, so a search leaves them out unless the request sets `include_lowered`; the result
says how many it left out (`lowered_hidden`).

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
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
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
from mission_control.domain.authoring.manifest_lowering import manifest_lowered_refs
from mission_control.domain.capabilities.catalog_entry import capability_pin
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

Facet = Literal["capability", "lane", "model", "sandbox_profile", "workflow_type", "template"]
FACETS: Final[tuple[Facet, ...]] = (
    "capability",
    "lane",
    "model",
    "sandbox_profile",
    "workflow_type",
    "template",
)
# What a hit's `ref` starts with where it is not a Capability Pin.
SANDBOX_REF_PREFIX: Final = "sandbox:"
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
    "sandbox_profile": frozenset({"sandbox", "sandboxes"}),
    "template": frozenset({"template", "templates"}),
}
# The resolver's manifest pointers, re-pointed into the draft's fields.
DRAFT_POINTERS: Final[Mapping[str, str]] = {
    LANE_POINTER: "/lane_profile",
    APPLICATION_POINTER: "/application_id",
    MODEL_POINTER: "/model_profile",
    DATA_CLASS_POINTER: "/data_class",
    FAMILY_POINTER: "/family",
}
# `catalog_search_mode` when the workspace answered from the published definitions itself.
DEFINITION_LISTING: Final = "definition_listing"
DEFINITION_SCAN: Final = "definition_scan"
# How long the published definitions (and a Search Projection probe that found nothing) are
# reused, in seconds, and how long a probe the projection answered is trusted.
PUBLISHED_TTL_SECONDS: Final = 30.0
PROJECTION_BUILT_TTL_SECONDS: Final = 600.0
# A listed or scanned hit's summary: the first line of the description, at most this long.
SUMMARY_CHARS: Final = 60
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


def _absent(value: object) -> bool:
    return value is None


def _empty(value: object) -> bool:
    return not value


class SelectionCatalogUnavailable(RuntimeError):
    """No catalog is composed for this workspace, so nothing can be listed or read by pin."""


class WorkspaceEntry(_Frozen):
    """One entry the composition hands in beside the catalog: a mission template, or a sandbox
    profile this deployment binds. `ref` is what the guide's describe reads."""

    ref: str
    title: str
    summary: str


class SelectionSearchRequest(_Frozen):
    # Empty (or blank): list the requested facets by name instead of ranking them.
    query: str = Field(default="", max_length=2_000)
    facets: frozenset[Facet] = frozenset(FACETS)
    # The catalog kinds the capability facet answers with, instead of its node-attachable
    # default (`FACET_KINDS`); any catalog kind may be named (`watcher`, `prompt`, ...).
    # Naming kinds without facets asks the capability facet only.
    kinds: frozenset[DefinitionKind] = frozenset()
    # Narrows capabilities to those whose host support marks this lane `supported`, and models
    # to those whose vendor the lane routes (`native` or `emulated`).
    lane_profile: str | None = Field(default=None, min_length=1, max_length=64)
    limit: int = Field(default=20, ge=1, le=100)
    # A listing's first row (ranked searches ignore it).
    offset: int = Field(default=0, ge=0, le=100_000)
    # Per catalog-backed facet.
    catalog_limit: int = Field(default=10, ge=1, le=50)
    # Also answer with the definitions a submitted manifest lowered (its own Workflow Type,
    # blueprint and profiles); left out by default because none of them is reusable.
    include_lowered: bool = False


class SelectionHit(_Frozen):
    """One hit. A listed hit is small on purpose: `score`, `facet_rank`, `reasons` and
    `details` are left out of its dump (nothing was ranked), and `kind` where the facet holds
    one kind; the guide's describe reads the rest by `ref`."""

    facet: Facet
    # What a draft names: a Capability Pin, `lane:<profile>` or `model:<profile>`; what a
    # manifest starts from or names: `template:<id>`, `sandbox:<profile>`.
    ref: str
    title: str
    summary: str
    # A catalog hit's kind (`skill`, `mcp_server`, `workflow_type`, ...).
    kind: str | None = Field(default=None, exclude_if=_absent)
    # Reciprocal-rank merge score across facets, then the rank inside the facet (from 1).
    score: float = Field(default=0.0, exclude_if=lambda value: value == 0.0)
    facet_rank: int = Field(default=0, ge=0, exclude_if=lambda value: value == 0)
    reasons: tuple[str, ...] = Field(default=(), exclude_if=_empty)
    # Facet-specific facts: supported lanes, qualification, routes, kind.
    details: dict[str, object] = Field(default_factory=dict, exclude_if=_empty)


class FacetUnavailable(_Frozen):
    facet: Facet
    reason: str


class SelectionSearchResult(_Frozen):
    schema_version: Literal["mc.selection_search.v1"] = SELECTION_SEARCH_SCHEMA
    query: str
    facets: tuple[Facet, ...]
    hits: tuple[SelectionHit, ...]
    unavailable: tuple[FacetUnavailable, ...] = ()
    # Who answered the catalog facets: the catalog's own mode (`hybrid` or `lexical`), or the
    # workspace over the published definitions (`definition_listing`; `definition_scan` when
    # it scanned every facet that answered; `notes` names the scanned facets either way).
    catalog_search_mode: str | None = None
    mode: Literal["search", "listing"] = "search"
    # A listing: how many rows the requested facets hold in all, and where this page starts.
    total: int | None = Field(default=None, exclude_if=_absent)
    offset: int = Field(default=0, exclude_if=lambda value: value == 0)
    # How many definitions lowered from submitted manifests the requested facets hold and this
    # answer left out (`include_lowered` adds them).
    lowered_hidden: int = Field(default=0, exclude_if=lambda value: value == 0)
    # What the caller must know to read the hits honestly (an unbuilt Search Projection).
    notes: tuple[str, ...] = Field(default=(), exclude_if=_empty)


class SelectionDraft(_Frozen):
    """What a coordinator intends one node to run with, before it writes the manifest."""

    application_id: str | None = Field(default=None, min_length=1, max_length=64)
    lane_profile: str = Field(min_length=1, max_length=64)
    model_profile: str = Field(min_length=1, max_length=192)
    family: Family
    # Undeclared: the application's Data Class ceiling, as the seam treats an undeclared mission.
    data_class: DataClass | None = None
    capabilities: tuple[str, ...] = Field(default=(), max_length=64)
    # A sandbox profile this deployment binds (its name or `sandbox:<name>`), or a catalog pin.
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
        clock: Callable[[], float] = time.monotonic,
        templates: Sequence[WorkspaceEntry] = (),
        sandbox_profiles: Sequence[WorkspaceEntry] = (),
    ) -> None:
        self._application_id = application_id
        # The curated mission templates and the sandbox profiles this deployment binds.
        self._entries: dict[Facet, tuple[WorkspaceEntry, ...]] = {
            "template": tuple(templates),
            "sandbox_profile": tuple(sandbox_profiles),
        }
        self._lanes = lanes
        self._models = models
        self._applications = applications
        self._admission = admission
        self._catalog_scope = catalog_scope
        self._search = search
        # `CatalogDefinitions` (`find_by_pin` or `list_published_definitions`).
        self._definitions = definitions
        self._clock = clock
        # (read at, rows): the published definitions, reused for `PUBLISHED_TTL_SECONDS`.
        self._definition_cache: tuple[float, tuple[PublishedDefinition, ...]] | None = None
        # Per catalog kind: (probed at, whether the Search Projection answered the probe).
        self._projection_probes: dict[DefinitionKind, tuple[float, bool]] = {}

    @property
    def application_id(self) -> str:
        return self._application_id

    # -- the published definitions ---------------------------------------------------------------

    async def published_definitions(self) -> tuple[PublishedDefinition, ...]:
        """Every published catalog definition of this scope, retired ones excluded, read once
        per `PUBLISHED_TTL_SECONDS`. `SelectionCatalogUnavailable` when no catalog is composed."""

        lister = getattr(self._definitions, "list_published_definitions", None)
        if not callable(lister):
            raise SelectionCatalogUnavailable("no catalog is composed for this application")
        now = self._clock()
        cached = self._definition_cache
        if cached is not None and now - cached[0] < PUBLISHED_TTL_SECONDS:
            return cached[1]
        rows = tuple(row for row in await lister() if row.retired_at is None)
        self._definition_cache = (now, rows)
        return rows

    async def find_published(self, pin: CapabilityPin) -> PublishedDefinition | None:
        """The published row a Capability Pin names (`SelectionCatalogUnavailable` without a
        catalog)."""

        if self._definitions is None:
            raise SelectionCatalogUnavailable("no catalog is composed for this application")
        return await find_published_by_pin(self._definitions, pin)

    async def _lowered(self) -> frozenset[tuple[str, str, str]]:
        """The published definitions submitted manifests lowered (empty without a catalog)."""

        try:
            return manifest_lowered_refs(await self.published_definitions())
        except SelectionCatalogUnavailable:
            return frozenset()

    # -- search ----------------------------------------------------------------------------------

    async def search(self, request: SelectionSearchRequest) -> SelectionSearchResult:
        query = " ".join(request.query.split())
        facets = _requested_facets(request)
        if not query:
            return await self._listing(request, facets)
        tokens = _tokens(query)
        ranked: dict[Facet, list[tuple[float, SelectionHit]]] = {}
        unavailable: list[FacetUnavailable] = []
        # Facet -> the published definition the Search Projection did not return.
        scanned: dict[Facet, str] = {}
        modes: list[str] = []
        lowered = frozenset() if request.include_lowered else await self._lowered()
        hidden = 0
        for facet in facets:
            if facet == "lane":
                ranked[facet] = self._lane_hits(tokens)
                continue
            if facet == "model":
                ranked[facet] = self._model_hits(tokens, request.lane_profile)
                continue
            entries = self._entry_hits(tokens, facet)
            if facet not in FACET_KINDS:
                ranked[facet] = entries
                continue
            outcome = await self._catalog_hits(facet, request, query, lowered)
            if isinstance(outcome, FacetUnavailable):
                # What the deployment binds is still an answer where no catalog search is.
                ranked[facet] = entries
                if not entries:
                    unavailable.append(outcome)
                continue
            catalog_hits, facet_mode, probe, left_out = outcome
            ranked[facet] = [*entries, *catalog_hits]
            hidden += left_out
            modes.append(facet_mode)
            if probe is not None:
                scanned[facet] = probe
        # The catalog's own mode where its search answered a facet; `definition_scan` only when
        # the workspace scanned every facet that answered. The note names the scanned facets.
        ranked_modes = [mode for mode in modes if mode != DEFINITION_SCAN]
        notes = [_scan_note(scanned)] if scanned else []
        if hidden:
            notes.append(_lowered_note(hidden))
        return SelectionSearchResult(
            query=query,
            facets=facets,
            hits=_merge(ranked, request.limit),
            unavailable=tuple(unavailable),
            catalog_search_mode=(ranked_modes or modes or [None])[0],
            lowered_hidden=hidden,
            notes=tuple(notes),
        )

    async def _listing(
        self, request: SelectionSearchRequest, facets: tuple[Facet, ...]
    ) -> SelectionSearchResult:
        """Every row of the requested facets by name; `offset` and `limit` window the whole."""

        rows: list[SelectionHit] = []
        unavailable: list[FacetUnavailable] = []
        mode: str | None = None
        hidden = 0
        for facet in facets:
            if facet == "lane":
                rows += self._lane_listing()
                continue
            if facet == "model":
                rows += self._model_listing(request.lane_profile)
                continue
            entries = [
                _listed(facet, entry.ref, entry.title, entry.summary)
                for entry in self._entries.get(facet, ())
            ]
            rows += entries
            if facet not in FACET_KINDS:
                continue
            try:
                listed, left_out = await self._catalog_listing(facet, request)
            except SelectionCatalogUnavailable as error:
                if not entries:
                    unavailable.append(FacetUnavailable(facet=facet, reason=str(error)))
                continue
            mode = DEFINITION_LISTING
            hidden += left_out
            rows += listed
        return SelectionSearchResult(
            query="",
            facets=facets,
            hits=tuple(rows[request.offset : request.offset + request.limit]),
            unavailable=tuple(unavailable),
            catalog_search_mode=mode,
            mode="listing",
            total=len(rows),
            offset=request.offset,
            lowered_hidden=hidden,
            notes=(_lowered_note(hidden),) if hidden else (),
        )

    def _lane_listing(self) -> list[SelectionHit]:
        hits: list[SelectionHit] = []
        for profile in self._lanes.profiles():
            describe = self._lanes.describe(profile)
            hits.append(_listed("lane", f"lane:{profile}", profile, _lane_summary(describe)))
        return hits

    def _model_listing(self, lane_profile: str | None) -> list[SelectionHit]:
        hits: list[SelectionHit] = []
        for profile in self._models.profiles():
            model = self._models.get(profile)
            if lane_profile is not None and self._routes(model).get(lane_profile) not in {
                "native",
                "emulated",
            }:
                continue
            hits.append(
                _listed("model", f"model:{profile}", profile, f"{model.vendor} {model.model_id}")
            )
        return hits

    async def _catalog_listing(
        self, facet: Facet, request: SelectionSearchRequest
    ) -> tuple[list[SelectionHit], int]:
        """The facet's listed rows and how many lowered definitions were left out."""

        rows, hidden = await self._facet_rows(facet, request)
        # A facet that answers with one kind names it once, as the facet.
        mixed = len(_facet_kinds(facet, request)) > 1
        return [
            _listed(
                facet,
                capability_pin(row).render(),
                row.definition.title,
                _one_line(row.definition.description),
                kind=row.ref.kind.value if mixed else None,
            )
            for row in rows
        ], hidden

    async def _facet_rows(
        self, facet: Facet, request: SelectionSearchRequest
    ) -> tuple[list[PublishedDefinition], int]:
        """The facet's published definitions by name, under the request's kind and lane
        filters (the lane filter keeps rows whose host support marks the lane `supported`),
        and how many definitions lowered from submitted manifests were left out of them."""

        kinds = _facet_kinds(facet, request)
        lane = request.lane_profile if facet == "capability" else None
        published = await self.published_definitions()
        lowered = frozenset() if request.include_lowered else manifest_lowered_refs(published)
        rows = [
            row
            for row in published
            if row.ref.kind in kinds
            and (
                lane is None
                or _host_status(getattr(row.definition, "host_support", None), lane) == "supported"
            )
        ]
        kept = [row for row in rows if _definition_key(row) not in lowered]
        kept.sort(key=lambda row: (row.ref.logical_id, row.ref.revision))
        return kept, len(rows) - len(kept)

    def _entry_hits(self, tokens: frozenset[str], facet: Facet) -> list[tuple[float, SelectionHit]]:
        """The facet's handed-in entries (templates, bound sandbox profiles) a query matches."""

        hits: list[tuple[float, SelectionHit]] = []
        for entry in self._entries.get(facet, ()):
            fields = [("name", entry.title, 3.0), ("summary", entry.summary, 1.0)]
            score, reasons = _score(
                tokens, fields, FACET_WORDS.get(facet, frozenset()), facet, stem=True
            )
            if score > 0:
                hits.append(
                    (score, _hit(facet, entry.ref, entry.title, entry.summary, reasons, {}))
                )
        hits.sort(key=lambda item: -item[0])
        return hits

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
                hits.append(
                    (
                        score,
                        _hit(
                            "lane",
                            f"lane:{profile}",
                            profile,
                            _lane_summary(describe),
                            reasons,
                            details,
                        ),
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
        self,
        facet: Facet,
        request: SelectionSearchRequest,
        query: str,
        lowered: frozenset[tuple[str, str, str]],
    ) -> tuple[list[tuple[float, SelectionHit]], str, str | None, int] | FacetUnavailable:
        """The facet's ranked hits, who ranked them, when that was the definition scan the
        published definition the Search Projection did not return, and how many hits lowered
        from submitted manifests (`lowered`) were left out."""

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
                    query=query,
                    kinds=_facet_kinds(facet, request),
                    tenant_scope=self._catalog_scope,
                    host_profiles=host_profiles,
                    limit=request.catalog_limit,
                )
            )
            hits: list[tuple[float, SelectionHit]] = []
            hidden = 0
            for hit in response.hits:
                ref = _catalog_ref(hit)
                if ref is None:
                    continue
                if _hit_key(hit) in lowered:
                    hidden += 1
                    continue
                hits.append((hit.fused_rank, _catalog_hit(facet, ref, hit, response.search_mode)))
            if hits or hidden:
                return hits, response.search_mode, None, hidden
            scanned = await self._definition_scan(facet, request, query)
        except CapabilitySearchUnavailable as error:
            return FacetUnavailable(facet=facet, reason=str(error))
        if scanned is None:
            # The Search Projection answers for this scope: the query matched nothing.
            return [], response.search_mode, None, 0
        return scanned

    async def _definition_scan(
        self, facet: Facet, request: SelectionSearchRequest, query: str
    ) -> tuple[list[tuple[float, SelectionHit]], str, str, int] | None:
        """The fallback behind an empty catalog answer: `None` when the facet holds no
        published definition or the Search Projection answers a probe, else a lexical scan of
        the published definitions with the name of the definition the probe searched for and
        the number of lowered definitions the scan left out."""

        try:
            rows, hidden = await self._facet_rows(facet, request)
        except SelectionCatalogUnavailable:
            return None
        if not rows or await self._projection_answers(rows[0]):
            return None
        tokens = frozenset(_stem(token) for token in _tokens(query))
        scored: list[tuple[float, PublishedDefinition, tuple[str, ...]]] = []
        for row in rows:
            fields = [
                ("name", row.ref.logical_id, 3.0),
                ("title", row.definition.title, 3.0),
                ("kind", row.ref.kind.value, 2.0),
                ("description", row.definition.description, 1.0),
            ]
            score, reasons = _score(tokens, fields, frozenset(), facet, stem=True)
            if score > 0:
                scored.append((score, row, reasons))
        scored.sort(key=lambda item: (-item[0], item[1].ref.logical_id, item[1].ref.revision))
        hits = [
            (
                score,
                _hit(
                    facet,
                    capability_pin(row).render(),
                    row.definition.title,
                    _one_line(row.definition.description),
                    ("definition scan", *reasons[:2]),
                    {"kind": row.ref.kind.value},
                    kind=row.ref.kind.value,
                ),
            )
            for score, row, reasons in scored[: request.catalog_limit]
        ]
        return hits, DEFINITION_SCAN, rows[0].ref.logical_id, hidden

    async def _projection_answers(self, probe: PublishedDefinition) -> bool:
        """Whether the Search Projection returns a published definition searched by its own
        title. Remembered per catalog kind: a projection that answered stays built for
        `PROJECTION_BUILT_TTL_SECONDS`; one that did not is asked again after
        `PUBLISHED_TTL_SECONDS`, so a rebuild is noticed soon."""

        now = self._clock()
        cached = self._projection_probes.get(probe.ref.kind)
        if cached is not None and now - cached[0] < (
            PROJECTION_BUILT_TTL_SECONDS if cached[1] else PUBLISHED_TTL_SECONDS
        ):
            return cached[1]
        answered = False
        if self._search is not None and self._catalog_scope is not None:
            response = await self._search.search(
                CapabilitySearchRequest(
                    query=probe.definition.title,
                    kinds=frozenset({probe.ref.kind}),
                    tenant_scope=self._catalog_scope,
                    limit=1,
                )
            )
            answered = bool(response.hits)
        self._projection_probes[probe.ref.kind] = (now, answered)
        return answered

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
            self._bound_sandbox(draft.sandbox_profile, refusals)
            or await self._pin_fit(
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

    def _bound_sandbox(self, text: str, refusals: list[SelectionRefusal]) -> PinFit | None:
        """A draft's sandbox profile where it names what a manifest names: a sandbox profile
        this deployment binds, by name or as a search hit's `sandbox:<name>`. `None`: it is
        neither, so it is read as a catalog pin."""

        bound = {entry.title for entry in self._entries["sandbox_profile"]}
        name = text.removeprefix(SANDBOX_REF_PREFIX)
        if name in bound:
            return PinFit(
                pointer="/sandbox_profile",
                pin=text,
                found=True,
                kind=DefinitionKind.SANDBOX_PROFILE,
                title=name,
            )
        if not text.startswith(SANDBOX_REF_PREFIX):
            return None
        refusals.append(
            _workspace_refusal(
                "SANDBOX_PROFILE_UNBOUND",
                "/sandbox_profile",
                f"sandbox profile {name} is not bound by this deployment; bound: "
                f"{', '.join(sorted(bound)) or 'none'}",
                "name a bound sandbox profile",
            )
        )
        return PinFit(pointer="/sandbox_profile", pin=text, found=False)

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


def _stem(token: str) -> str:
    """A plural folded onto its singular (`skills` finds the kind `skill`); nothing more."""

    return token[:-1] if len(token) > 3 and token.endswith("s") else token


def _requested_facets(request: SelectionSearchRequest) -> tuple[Facet, ...]:
    """The facets in their fixed order; kinds named without facets ask capabilities only."""

    if request.kinds and "facets" not in request.model_fields_set:
        return ("capability",)
    return tuple(facet for facet in FACETS if facet in request.facets)


def _facet_kinds(facet: Facet, request: SelectionSearchRequest) -> frozenset[DefinitionKind]:
    if facet == "capability" and request.kinds:
        return request.kinds
    return FACET_KINDS[facet]


def _one_line(text: str) -> str:
    line = " ".join(text.split("\n", 1)[0].split())
    return line if len(line) <= SUMMARY_CHARS else line[: SUMMARY_CHARS - 3].rstrip() + "..."


def _definition_key(row: PublishedDefinition) -> tuple[str, str, str]:
    """A published row as `manifest_lowered_refs` names it."""

    return (row.ref.kind.value, row.ref.logical_id, row.ref.digest)


def _hit_key(hit: CapabilitySearchHit) -> tuple[str, str, str] | None:
    """A catalog search hit as `manifest_lowered_refs` names it (`None`: it carries no digest)."""

    if hit.exact_ref is not None:
        return (hit.kind.value, hit.exact_ref.logical_id, hit.exact_ref.digest)
    if hit.pin is None:
        return None
    try:
        pin = CapabilityPin.parse(hit.pin)
    except CapabilityPinError:
        return None
    return (hit.kind.value, pin.capability_id, pin.digest) if pin.digest is not None else None


def _lowered_note(hidden: int) -> str:
    return (
        f"{hidden} definitions lowered from submitted manifests are left out: each belongs to "
        "the one manifest it was lowered from and is not a reusable type; `include_lowered` "
        "lists them"
    )


def _scan_note(scanned: Mapping[Facet, str]) -> str:
    """What a caller must know about hits the workspace scanned for itself: which facets,
    the evidence that the Search Projection does not hold them, and what a scan lacks."""

    probe = next(iter(scanned.values()))
    return (
        f"{', '.join(scanned)}: the catalog Search Projection did not return a published "
        f"definition searched by its own title ({probe}), so it is not built or is stale for "
        "this catalog scope; these hits come from a lexical scan of the published definitions "
        "(name, kind, description), without semantic ranking or the catalog's selection policy"
    )


def _lane_summary(describe: LaneDescribe) -> str:
    return (
        f"{describe.lane} lane, {describe.placement} placement, "
        f"{'qualified' if describe.qualified else 'unqualified'}"
    )


def _listed(
    facet: Facet, ref: str, title: str, summary: str, *, kind: str | None = None
) -> SelectionHit:
    """A listed row: nothing was ranked, so it carries no score, rank, reasons or details."""

    return SelectionHit(facet=facet, ref=ref, title=title, summary=summary, kind=kind)


def _score(
    tokens: frozenset[str],
    fields: Iterable[tuple[str, str, float]],
    facet_words: frozenset[str],
    facet: str,
    *,
    stem: bool = False,
) -> tuple[float, tuple[str, ...]]:
    """Weighted token overlap: each field adds its weight once per query token it contains."""

    score = 0.0
    reasons: list[str] = []
    for label, value, weight in fields:
        words = _tokens(value)
        matched = sorted(tokens & (frozenset(_stem(word) for word in words) if stem else words))
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
    *,
    kind: str | None = None,
) -> SelectionHit:
    # Score and rank are placeholders until the merge assigns them.
    return SelectionHit(
        facet=facet,
        ref=ref,
        title=title,
        summary=summary,
        kind=kind,
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
        kind=hit.kind.value,
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
    "DEFINITION_LISTING",
    "DEFINITION_SCAN",
    "FACETS",
    "FACET_KINDS",
    "SANDBOX_REF_PREFIX",
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
    "SelectionCatalogUnavailable",
    "SelectionCheck",
    "SelectionDraft",
    "SelectionHit",
    "SelectionRefusal",
    "SelectionSearchRequest",
    "SelectionSearchResult",
    "SelectionWorkspace",
    "WorkflowTypeFit",
    "WorkspaceEntry",
]
