"""The guide: one start page, ten topics and one describe, the same on every transport.

A Coordinator that has only the MCP server cannot read a skill file, so the server itself says
how it is used. `GuideService.index` is the start page (who the caller is, the jobs in order,
the topic and calls for each), `topic` is one page and `describe` is everything about one
thing: a lane, a Model Profile, a capability, a feature, a tool, a mission template, a sandbox
profile or the Mission Manifest.

Judgment lives in the pages (`pages/*.md`); every fact is generated at request time from the
registries the Selection Workspace already reads (the Lane Registry and each Lane Declaration,
the Model Catalog, the published catalog definitions), from the lane's feature registry, from
the manifest models (`manifest_reference.py`) and from the mission templates
(`mission_templates.py`), so a page never restates a registry and cannot drift from it. A page
names operations by id and the service renders them in the caller's vocabulary
(`operations.py`).

A page is Markdown. So is a describe answer that is prose (a tool's documentation, a template,
the manifest reference): it carries `markdown` beside its `data`. An answer that is data (a
lane, a model, a catalog definition) carries `data` only.

The definitions a submitted manifest lowered (its own Workflow Type with its blueprint and
profiles) are never counted or presented as reusable types: the counts here leave them out and
say how many there are.

Provider-neutral and application-neutral: no lane, vendor or application is named here; the
application id is the composed one.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol, get_args

from pydantic import BaseModel, ConfigDict, Field

from mission_control.application.guide.manifest_reference import (
    MANIFEST_REF,
    UnknownSection,
    manifest_reference_document,
    manifest_reference_markdown,
    manifest_topic_section,
    required_fields,
    section_markdown,
    section_names,
)
from mission_control.application.guide.mission_templates import (
    TEMPLATE_IDS,
    TEMPLATE_REF_PREFIX,
    load_template,
    mission_templates,
    template_document,
    template_markdown,
)
from mission_control.application.guide.operations import Surface, render_operations
from mission_control.application.guide.pages import INDEX, TOPIC_IDS, insert_generated, load_page
from mission_control.application.guide.tool_docs import (
    TOOL_DOCS,
    tool_document,
    tool_notes,
    untitled_schema,
)
from mission_control.application.resolution.lane_listing import describe_lane
from mission_control.application.resolution.model_listing import describe_model
from mission_control.application.resolution.registries import LaneRegistry, ModelCatalog
from mission_control.application.selection.workspace import (
    SANDBOX_REF_PREFIX,
    SelectionCatalogUnavailable,
)
from mission_control.application.subscriptions.coordinator import DEFAULT_KINDS
from mission_control.application.subscriptions.coordinator_service import MAX_WAIT_SECONDS
from mission_control.contracts.contracts import MissionCommandRequest
from mission_control.domain.authoring.contracts import DefinitionKind, PublishedDefinition
from mission_control.domain.authoring.manifest import MissionManifest
from mission_control.domain.authoring.manifest_lowering import manifest_lowered_refs
from mission_control.domain.authoring.manifest_v2 import MissionManifestV2
from mission_control.domain.capabilities.catalog_entry import capability_pin
from mission_control.domain.capabilities.features.registry import FeatureRegistry, FeatureStatus
from mission_control.domain.capabilities.host_support import CapabilityHostSupport
from mission_control.domain.capabilities.pins import CapabilityPin, is_pin
from mission_control.domain.execution.lanes import DEFAULT_LANE_PROFILE, DELIVERY_COMMANDS
from mission_control.domain.resolution.configuration import FAMILIES
from mission_control.domain.resolution.profiles import LaneDeclaration

GUIDE_SCHEMA: Final = "mc.guide.v1"
DESCRIBE_SCHEMA: Final = "mc.describe.v1"
# What `describe` reads; anything else must be a Capability Pin or a catalog ref.
REF_FORMS: Final[tuple[str, ...]] = (
    "lane:<profile>",
    "model:<profile>",
    "feature:<id>",
    "tool:<name>",
    f"{TEMPLATE_REF_PREFIX}<id>",
    f"{SANDBOX_REF_PREFIX}<profile>",
    MANIFEST_REF,
    f"{MANIFEST_REF}:<section>",
    "<capability pin>",
)
# The run-level controls a Coordinator invokes, shown beside the delivery semantics.
SHOWN_CONTROLS: Final[tuple[str, ...]] = ("pause", "snapshot", "fork")
# The delivery semantics a Coordinator can cause: a Command kind it may send, or the fork call
# (a lane also declares semantics for commands no public request carries).
SENDABLE_COMMANDS: Final[tuple[str, ...]] = tuple(
    command
    for command in DELIVERY_COMMANDS
    if command == "fork"
    or command in get_args(MissionCommandRequest.model_fields["kind"].annotation)
)
# One line per catalog kind a mission selects (the wording follows the glossary).
KIND_LINES: Final[Mapping[DefinitionKind, str]] = {
    DefinitionKind.WORKFLOW_TYPE: "A workflow's purpose, contracts and authority ceiling.",
    DefinitionKind.SKILL: "A packaged, pinned skill directory a lane can materialize.",
    DefinitionKind.MCP_SERVER: "A Model Context Protocol server: transport, endpoint or launch "
    "identity, secret references and the tools it exposes.",
    DefinitionKind.MCP_TOOL: "One tool of a published MCP server.",
    DefinitionKind.TOOL: "A host tool, an assessment or a deterministic executor.",
    DefinitionKind.HOOK_SCRIPT: "A script that runs at a declared hook event and returns a "
    "typed decision or added context.",
    DefinitionKind.PLUGIN: "A pinned composition of other capabilities bound as one unit.",
    DefinitionKind.SUBAGENT_PROFILE: "A delegable agent: purpose, instructions, tools, model.",
    DefinitionKind.ENVIRONMENT_KIT: "A pinned bundle of toolchains, base install and setup "
    "steps with the variables, secrets and egress it requires.",
    DefinitionKind.WATCHER: "A reusable watcher template: one trigger, a condition, typed "
    "actions and limits.",
    DefinitionKind.PROMPT: "A published prompt template with its variables and trust class.",
    DefinitionKind.ARTIFACT_SCHEMA: "A schema that validates captured artifact bytes.",
    DefinitionKind.SANDBOX_PROFILE: "The pinned image, limits, lifetime, egress and cleanup "
    "rules for a workspace.",
    DefinitionKind.MIDDLEWARE: "A middleware capability a lane attaches to an agent.",
    DefinitionKind.MODEL: "A model capability row.",
}

RefusalCode = Literal["unknown_topic", "unknown_ref", "not_found", "unavailable"]
DescribedKind = Literal[
    "lane", "model", "capability", "feature", "tool", "template", "sandbox_profile", "manifest"
]


class GuideRefused(Exception):
    """A typed refusal: what was asked for is not a topic or a ref, or does not exist here.
    `valid` names what would have been accepted."""

    def __init__(self, code: RefusalCode, message: str, valid: Iterable[str] = ()) -> None:
        super().__init__(message)
        self.code: RefusalCode = code
        self.valid = tuple(valid)


class GuideCatalog(Protocol):
    """The published catalog definitions as the guide reads them (the Selection Workspace)."""

    async def published_definitions(self) -> tuple[PublishedDefinition, ...]:
        """`SelectionCatalogUnavailable` when no catalog is composed."""
        ...

    async def find_published(self, pin: CapabilityPin) -> PublishedDefinition | None: ...


@dataclass(frozen=True, slots=True)
class ToolListing:
    """One tool as the transport that serves it lists it: its description and the JSON Schema
    of its arguments. `tool:<name>` answers from the listing of the server it was asked on."""

    name: str
    description: str
    input_schema: Mapping[str, Any]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GuidePage(_Frozen):
    schema_version: Literal["mc.guide.v1"] = GUIDE_SCHEMA
    topic: str
    title: str
    summary: str
    # The vocabulary the page's calls are written in.
    surface: Surface
    markdown: str


class DescribeResult(_Frozen):
    schema_version: Literal["mc.describe.v1"] = DESCRIBE_SCHEMA
    ref: str
    kind: DescribedKind
    title: str
    data: dict[str, Any]
    # The answer as Markdown, where the answer is prose (a tool, a template, the manifest).
    markdown: str | None = Field(default=None, exclude_if=lambda value: value is None)


class GuideService:
    """The guide of one application's installation (see the module doc)."""

    def __init__(
        self,
        *,
        application_id: str,
        lanes: LaneRegistry,
        models: ModelCatalog,
        catalog: GuideCatalog | None = None,
        features: Mapping[str, FeatureRegistry] | None = None,
        sandbox_profiles: Mapping[str, str] | None = None,
    ) -> None:
        self._application_id = application_id
        self._lanes = lanes
        self._models = models
        self._catalog = catalog
        # Lane profile -> the lane's selectable feature registry (lane features and the
        # vendor rows of its model routes), composed by bootstrap from the lane's package.
        self._features = dict(features or {})
        # The sandbox profiles this deployment binds, name -> one line (`None`: this process
        # reads no launch bindings, so it cannot say).
        self._sandbox_profiles = None if sandbox_profiles is None else dict(sandbox_profiles)
        self._sections: dict[str, Callable[[], Awaitable[str]]] = {
            INDEX: self._index_section,
            "interview": self._interview_section,
            "workflows": self._workflows_section,
            "templates": self._templates_section,
            "manifest": self._manifest_section,
            "lanes": self._lanes_section,
            "models": self._models_section,
            "capabilities": self._capabilities_section,
            "observe": self._observe_section,
            "control": self._control_section,
        }
        # A page's further generated sections, by the name of their marker.
        self._named_sections: dict[str, dict[str, Callable[[], Awaitable[str]]]] = {
            "workflows": {"types": self._workflow_types_section},
        }

    @property
    def application_id(self) -> str:
        return self._application_id

    # -- pages -----------------------------------------------------------------------------------

    async def index(self, surface: Surface = "mcp") -> GuidePage:
        return await self._page(INDEX, surface)

    async def topic(self, topic_id: str, surface: Surface = "mcp") -> GuidePage:
        """One topic; the start page for `index`. `GuideRefused` names the topics."""

        wanted = topic_id.strip().lower()
        if wanted != INDEX and wanted not in TOPIC_IDS:
            raise GuideRefused(
                "unknown_topic",
                f"no guide topic {topic_id!r}; topics: {', '.join(TOPIC_IDS)}",
                TOPIC_IDS,
            )
        return await self._page(wanted, surface)

    async def _page(self, page_id: str, surface: Surface) -> GuidePage:
        source = load_page("pages", page_id)
        section = self._sections.get(page_id)
        named = self._named_sections.get(page_id, {})
        body = insert_generated(
            source.body,
            await section() if section is not None else "",
            {name: await generate() for name, generate in named.items()},
        )
        return GuidePage(
            topic=page_id,
            title=source.title,
            summary=source.summary,
            surface=surface,
            markdown=f"# {source.title}\n\n{render_operations(body, surface)}",
        )

    # -- generated sections ----------------------------------------------------------------------

    async def _published(self) -> tuple[PublishedDefinition, ...] | None:
        """The published definitions, or `None` where no catalog is composed."""

        if self._catalog is None:
            return None
        try:
            return await self._catalog.published_definitions()
        except SelectionCatalogUnavailable:
            return None

    async def _curated(self) -> tuple[tuple[PublishedDefinition, ...], int] | None:
        """The published definitions no submitted manifest lowered, and how many it did lower
        (`None` where no catalog is composed)."""

        published = await self._published()
        if published is None:
            return None
        lowered = manifest_lowered_refs(published)
        curated = tuple(
            row
            for row in published
            if (row.ref.kind.value, row.ref.logical_id, row.ref.digest) not in lowered
        )
        return curated, len(published) - len(curated)

    def _declaration(self, profile: str) -> LaneDeclaration | None:
        try:
            return self._lanes.get(profile).declaration
        except KeyError:
            return None

    async def _index_section(self) -> str:
        curated = await self._curated()
        catalog = (
            "no catalog is composed"
            if curated is None
            else f"{len(curated[0])} published catalog definitions"
        )
        return (
            f"This server: application `{self._application_id}`; lanes "
            f"{_spans(self._lanes.profiles())}; {len(self._models.profiles())} Model Profiles; "
            f"{catalog}; {len(TEMPLATE_IDS)} mission templates."
        )

    async def _interview_section(self) -> str:
        versions = _spans(
            f"manifest: {version}"
            for model in (MissionManifestV2, MissionManifest)
            for version in get_args(model.model_fields["manifest"].annotation)
        )
        return (
            f"Three fields are fixed: the first line is {versions.replace(', ', ' or ')}; "
            "`mission.key` is a stable slug; `mission.application` is "
            f"`{self._application_id}`."
        )

    async def _workflows_section(self) -> str:
        rows = []
        for profile in self._lanes.profiles():
            declaration = self._declaration(profile)
            cells = (
                [declaration.families[family] for family in FAMILIES]
                if declaration is not None
                else ["undeclared"] * len(FAMILIES)
            )
            rows.append([f"`{profile}`", *cells])
        table = _table(["Lane profile", *(f"`{family}`" for family in FAMILIES)], rows)
        allowed = "allows" if self._lanes.allow_unqualified else "does not allow"
        return f"{table}\n\nThis installation {allowed} unqualified lanes."

    async def _workflow_types_section(self) -> str:
        """What a Coordinator starts from, and what the catalog holds as Workflow Types: the
        published ones no manifest lowered, and how many submitted manifests lowered."""

        templates = f"The templates to start from (topic `templates`): {_spans(TEMPLATE_IDS)}."
        curated = await self._curated()
        published = await self._published()
        if curated is None or published is None:
            return f"{templates}\n\nThe catalog is not composed: no Workflow Type can be listed."
        kept = sum(row.ref.kind is DefinitionKind.WORKFLOW_TYPE for row in curated[0])
        every = sum(row.ref.kind is DefinitionKind.WORKFLOW_TYPE for row in published)
        return (
            f"{templates}\n\nPublished Workflow Types that are not lowered from a manifest: "
            f"{kept}. Lowered from submitted manifests and left out of listings: {every - kept}."
        )

    async def _templates_section(self) -> str:
        return _table(
            ["Template", "What it is", "Use it when"],
            [
                [f"`{template.id}`", template.purpose, template.use_when]
                for template in mission_templates()
            ],
        )

    async def _manifest_section(self) -> str:
        return manifest_topic_section(
            lanes=self._lanes.profiles(),
            sandbox_profiles=self._sandbox_profiles,
            application_id=self._application_id,
        )

    async def _lanes_section(self) -> str:
        rows = []
        for profile in self._lanes.profiles():
            describe = self._lanes.describe(profile)
            declaration = self._declaration(profile)
            name = f"`{profile}`" + (" (default)" if profile == DEFAULT_LANE_PROFILE else "")
            rows.append(
                [
                    name,
                    describe.placement,
                    "yes" if describe.qualified else "no",
                    *(
                        (
                            _verdicts(declaration.families),
                            _verdicts(
                                {route.vendor: route.verdict for route in declaration.model_routes}
                            ),
                            _verdicts(declaration.items),
                        )
                        if declaration is not None
                        else ("undeclared",) * 3
                    ),
                ]
            )
        table = _table(
            ["Lane profile", "Placement", "Qualified", "Workflow systems", "Vendors", "Item kinds"],
            rows,
        )
        features = [
            _feature_lines(profile, registry)
            for profile, registry in sorted(self._features.items())
            if profile in self._lanes.profiles()
        ]
        return "\n\n".join([table, *features])

    async def _models_section(self) -> str:
        rows = []
        for profile in self._models.profiles():
            model = self._models.get(profile)
            rows.append([f"`{profile}`", model.vendor, f"`{model.model_id}`"])
        return _table(["Model Profile", "Vendor", "Model id"], rows)

    async def _capabilities_section(self) -> str:
        curated = await self._curated()
        if curated is None:
            return "No catalog is composed for this application: nothing can be listed or pinned."
        published, lowered = curated
        counts = Counter(row.ref.kind for row in published)
        rows = [
            [f"`{kind.value}`", str(counts[kind]), line]
            for kind, line in KIND_LINES.items()
            if counts[kind]
        ]
        others = sorted(
            (kind.value, count) for kind, count in counts.items() if kind not in KIND_LINES
        )
        parts = [_table(["Kind", "Published", "What it is"], rows)]
        if others:
            listed = ", ".join(f"`{kind}` {count}" for kind, count in others)
            parts.append(f"Other published kinds, not selected directly in a manifest: {listed}.")
        if lowered:
            parts.append(
                f"Not counted: {lowered} definitions lowered from submitted manifests (topic "
                "`workflows`)."
            )
        return "\n\n".join(parts)

    async def _observe_section(self) -> str:
        return (
            f"Notification kinds: {_spans(kind.value for kind in DEFAULT_KINDS)}. One wait "
            f"lasts at most {MAX_WAIT_SECONDS} seconds."
        )

    async def _control_section(self) -> str:
        """Each lane's declared delivery semantics for what a Coordinator can send, its
        run-level controls and its restore levels; lanes that declare the same share a row."""

        grouped: dict[tuple[str, ...], list[str]] = {}
        for profile in self._lanes.profiles():
            describe = self._lanes.describe(profile)
            travel = describe.time_travel
            cells = (
                *(describe.delivery_semantics[command] for command in SENDABLE_COMMANDS),
                " / ".join(describe.controls[control] for control in SHOWN_CONTROLS),
                f"{travel.read} / {travel.fork}" if travel is not None else "not declared",
            )
            grouped.setdefault(cells, []).append(profile)
        return _table(
            [
                "Lane profile",
                *(f"`{command}`" for command in SENDABLE_COMMANDS),
                f"controls: {' / '.join(SHOWN_CONTROLS)}",
                "restore: read / fork",
            ],
            [[_spans(profiles), *cells] for cells, profiles in grouped.items()],
        )

    # -- describe --------------------------------------------------------------------------------

    async def describe(
        self, ref: str, *, tools: Mapping[str, ToolListing] | None = None
    ) -> DescribeResult:
        """Everything about one thing; `GuideRefused` for a ref that is no known form
        (`unknown_ref`, naming the forms) or names nothing here (`not_found`). `tools` is the
        tool listing of the server the question was asked on, which `tool:<name>` answers
        from."""

        text = ref.strip()
        if text == MANIFEST_REF:
            return self._describe_manifest()
        if is_pin(text):
            return await self._describe_capability(text)
        prefix, separator, name = text.partition(":")
        if separator and name:
            if prefix == "lane":
                return self._describe_lane(name)
            if prefix == "model":
                return self._describe_model(name)
            if prefix == "feature":
                return self._describe_feature(name)
            if prefix == "tool":
                return self._describe_tool(name, tools)
            if f"{prefix}:" == TEMPLATE_REF_PREFIX:
                return self._describe_template(name)
            if f"{prefix}:" == SANDBOX_REF_PREFIX:
                return self._describe_sandbox(name)
            if prefix == MANIFEST_REF:
                return self._describe_manifest_section(name)
        raise GuideRefused(
            "unknown_ref",
            f"{ref!r} is not a ref; a ref is {', '.join(REF_FORMS[:-1])} or a Capability Pin "
            "(the `ref` of a search hit)",
            REF_FORMS,
        )

    def _describe_lane(self, profile: str) -> DescribeResult:
        try:
            data = describe_lane(self._lanes, profile)
        except LookupError:
            registered = self._lanes.profiles()
            raise GuideRefused(
                "not_found",
                f"lane profile {profile!r} is not registered here; registered: "
                f"{', '.join(registered)}",
                (f"lane:{name}" for name in registered),
            ) from None
        return DescribeResult(ref=f"lane:{profile}", kind="lane", title=profile, data=data)

    def _describe_model(self, profile: str) -> DescribeResult:
        try:
            description = describe_model(self._models, self._lanes, profile)
        except KeyError:
            profiles = self._models.profiles()
            raise GuideRefused(
                "not_found",
                f"model profile {profile!r} is not in the Model Catalog; profiles: "
                f"{', '.join(profiles)}",
                (f"model:{name}" for name in profiles),
            ) from None
        return DescribeResult(
            ref=f"model:{profile}",
            kind="model",
            title=profile,
            data=description.model_dump(mode="json"),
        )

    def _describe_feature(self, feature_id: str) -> DescribeResult:
        lanes = sorted(
            profile for profile, registry in self._features.items() if feature_id in registry
        )
        if not lanes:
            known = sorted({row.id for registry in self._features.values() for row in registry})
            raise GuideRefused(
                "not_found",
                f"no feature {feature_id!r}; features: {', '.join(known) or 'none'}",
                (f"feature:{name}" for name in known),
            )
        row = self._features[lanes[0]].get(feature_id)
        return DescribeResult(
            ref=f"feature:{feature_id}",
            kind="feature",
            title=feature_id,
            data={**row.describe(), "lane_profiles": lanes},
        )

    def _describe_tool(self, tool: str, tools: Mapping[str, ToolListing] | None) -> DescribeResult:
        """A tool's description and the schema of its arguments as its server lists them, with
        the extended notes, the request schema and an example where the tool has them."""

        listing = (tools or {}).get(tool)
        if listing is None and tool not in TOOL_DOCS:
            known = sorted({*(tools or {}), *TOOL_DOCS})
            raise GuideRefused(
                "not_found",
                f"no tool {tool!r} on this server; tools: {', '.join(known)}",
                (f"tool:{name}" for name in known),
            )
        data: dict[str, Any] = {"tool": tool}
        lines = [f"# `{tool}`"]
        if listing is not None:
            schema = untitled_schema(listing.input_schema)
            data |= {"description": listing.description, "input_schema": schema}
            lines += ["", listing.description, "", "## Arguments", "", _json_block(schema)]
        title = tool
        if tool in TOOL_DOCS:
            document = tool_document(tool)
            notes = tool_notes(tool)
            title = notes.title
            data |= document
            lines += ["", f"## {notes.title}", "", notes.body]
            if "schema" in document:
                lines += [
                    "",
                    f"## The request object `{document['argument'] or tool}`",
                    "",
                    _json_block(document["schema"]),
                ]
            lines += ["", "## Example", "", _json_block(document["example"])]
        return DescribeResult(
            ref=f"tool:{tool}", kind="tool", title=title, data=data, markdown="\n".join(lines)
        )

    def _describe_template(self, template_id: str) -> DescribeResult:
        if template_id not in TEMPLATE_IDS:
            raise GuideRefused(
                "not_found",
                f"no mission template {template_id!r}; templates: {', '.join(TEMPLATE_IDS)}",
                (f"{TEMPLATE_REF_PREFIX}{name}" for name in TEMPLATE_IDS),
            )
        template = load_template(template_id)
        return DescribeResult(
            ref=template.ref,
            kind="template",
            title=template.title,
            data=template_document(template),
            markdown=template_markdown(template),
        )

    def _describe_sandbox(self, profile: str) -> DescribeResult:
        bound = self._sandbox_profiles
        if bound is None:
            raise GuideRefused(
                "unavailable", "this server reads no launch bindings, so it binds no sandbox"
            )
        if profile not in bound:
            raise GuideRefused(
                "not_found",
                f"sandbox profile {profile!r} is not bound here; bound: "
                f"{', '.join(sorted(bound)) or 'none'}",
                (f"{SANDBOX_REF_PREFIX}{name}" for name in sorted(bound)),
            )
        return DescribeResult(
            ref=f"{SANDBOX_REF_PREFIX}{profile}",
            kind="sandbox_profile",
            title=profile,
            data={
                "profile": profile,
                "summary": bound[profile],
                "manifest_field": "environment.sandbox.profile",
            },
        )

    def _describe_manifest(self) -> DescribeResult:
        return DescribeResult(
            ref=MANIFEST_REF,
            kind="manifest",
            title="Mission Manifest reference",
            data=manifest_reference_document(),
            markdown=manifest_reference_markdown(),
        )

    def _describe_manifest_section(self, section: str) -> DescribeResult:
        try:
            markdown = section_markdown(section)
        except UnknownSection:
            names = section_names()
            raise GuideRefused(
                "not_found",
                f"no manifest section {section!r}; sections: {', '.join(names)}",
                (f"{MANIFEST_REF}:{name}" for name in names),
            ) from None
        return DescribeResult(
            ref=f"{MANIFEST_REF}:{section}",
            kind="manifest",
            title=section,
            data={"section": section, "required": list(required_fields(section))},
            markdown=markdown,
        )

    async def _describe_capability(self, text: str) -> DescribeResult:
        if self._catalog is None:
            raise GuideRefused("unavailable", "no catalog is composed for this application")
        pin = CapabilityPin.parse(text)
        try:
            published = await self._catalog.find_published(pin)
            if published is None:
                published = _by_exact_ref(pin, await self._catalog.published_definitions())
        except SelectionCatalogUnavailable as error:
            raise GuideRefused("unavailable", str(error)) from None
        if published is None:
            raise GuideRefused("not_found", f"no published catalog definition for {text}")
        definition = published.definition
        support = getattr(definition, "host_support", None)
        data: dict[str, Any] = {
            "pin": capability_pin(published).render(),
            "kind": published.ref.kind.value,
            "name": published.ref.logical_id,
            "revision": published.ref.revision,
            "title": definition.title,
            "description": definition.description,
            "retired": published.retired_at is not None,
            "required_capabilities": sorted(getattr(definition, "required_capabilities", ())),
            "secret_names": [
                str(getattr(item, "key", item)) for item in getattr(definition, "secret_refs", ())
            ],
        }
        if isinstance(support, CapabilityHostSupport) and support.profiles:
            data["host_support"] = {
                profile.value: entry.status.value for profile, entry in support.profiles.items()
            }
        ceiling = getattr(definition, "authority_ceiling", None)
        if ceiling is not None:
            data["authority_ceiling"] = {
                "capabilities": sorted(ceiling.capabilities),
                "max_concurrency": ceiling.max_concurrency,
            }
        for name in ("purpose", "events", "tool_name", "side_effect_class"):
            value = getattr(definition, name, None)
            if value is not None:
                data[name] = [str(item) for item in value] if isinstance(value, tuple) else value
        return DescribeResult(ref=data["pin"], kind="capability", title=definition.title, data=data)


# -- helpers -------------------------------------------------------------------------------------


def _by_exact_ref(
    pin: CapabilityPin, published: Iterable[PublishedDefinition]
) -> PublishedDefinition | None:
    """The row a search hit without a pin names: `<kind>:<logical id>@<revision>#<digest>`."""

    kind, separator, logical_id = pin.capability_id.partition(":")
    if not separator:
        return None
    return next(
        (
            row
            for row in published
            if row.ref.kind.value == kind
            and row.ref.logical_id == logical_id
            and row.ref.digest == pin.digest
        ),
        None,
    )


def _spans(names: Iterable[str]) -> str:
    return ", ".join(f"`{name}`" for name in names)


def _json_block(value: object) -> str:
    return f"```json\n{json.dumps(value, indent=2, ensure_ascii=False)}\n```"


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = [f"| {' | '.join(header)} |", f"|{' --- |' * len(header)}"]
    lines += [f"| {' | '.join(row)} |" for row in rows]
    return "\n".join(lines)


def _verdicts(support: Mapping[Any, str]) -> str:
    """What is supported, the full verdict (`native`) bare and the weaker ones prefixed."""

    groups: dict[str, list[str]] = {}
    for name, verdict in support.items():
        if verdict != "unsupported":
            groups.setdefault(verdict, []).append(str(name))
    parts = [", ".join(groups.pop("native", []))]
    parts += [f"{verdict}: {', '.join(names)}" for verdict, names in sorted(groups.items())]
    return "; ".join(part for part in parts if part) or "none"


def _feature_lines(profile: str, registry: FeatureRegistry) -> str:
    """One lane's selectable features by namespace, the unavailable ones apart."""

    available: dict[str, list[str]] = {}
    waiting: list[str] = []
    for row in registry:
        namespace, _, name = row.id.partition(".")
        if row.status is FeatureStatus.AVAILABLE:
            available.setdefault(namespace, []).append(name)
        else:
            waiting.append(f"`{row.id}` ({row.status.value})")
    lines = [f"Features of `{profile}`, by namespace (`feature:<namespace>.<name>`):"]
    lines += [f"- `{namespace}`: {', '.join(names)}" for namespace, names in available.items()]
    if waiting:
        lines.append(f"- not available: {', '.join(waiting)}")
    return "\n".join(lines)


__all__ = [
    "DESCRIBE_SCHEMA",
    "GUIDE_SCHEMA",
    "KIND_LINES",
    "REF_FORMS",
    "DescribeResult",
    "DescribedKind",
    "GuideCatalog",
    "GuidePage",
    "GuideRefused",
    "GuideService",
    "RefusalCode",
    "ToolListing",
]
