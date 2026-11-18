"""An explicit two-variant fixture Workflow Type, authored before either run is admitted.

``two_variant_manifests`` returns two variants of the minimal Stage Graph that differ only in
which catalog MCP server backs the ``search`` capability (PubMed, then Tavily), so each
variant's runtime profile binds a different server. ``TwoVariantForkPrograms.prepare`` compiles
both through the ordinary publish/compile APIs, checks that they agree on every protected
Workflow Type field and on their output promises, and publishes one shared Workflow Type whose
allowed component sets are the union of the two. Later compiles of either prepared variant use
that shared type, so a run of one variant can be forked into the other's configuration through
real admission; the common fork's exact Workflow Type and configuration authority checks stay
unchanged, and neither variant's runtime bindings gain the other's server.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from mission_control.application.authoring.manifest_service import (
    ManifestProgramCompiler,
    ManifestScope,
    OverlayDefinitionRepository,
)
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    CompilationContext,
    CompileInvocation,
    DefinitionSelector,
    EnvironmentAvailability,
    ExactDefinitionRef,
    PublishRequest,
)
from mission_control.domain.authoring.errors import DefinitionNotFound
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.domain.authoring.manifest_lowering import (
    MANIFEST_RUN_CAPABILITIES,
    MANIFEST_RUNTIME_BINDING,
)

MINIMAL = Path(__file__).resolve().parents[3] / "tests/fixtures/manifests/minimal-stage-graph.yml"
SELECTORS = (
    "blueprint",
    "control_profile",
    "runtime_profile",
    "workspace_template",
    "evaluation_profile",
)
SEARCH_SERVERS: dict[str, dict[str, Any]] = {
    "pubmed": {"search": "pubmed literature retrieval", "tools": ["search_articles"]},
    "tavily": {"search": "tavily web search extract"},
}


def search_variant(server: Literal["pubmed", "tavily"]) -> str:
    """The minimal Stage Graph with its one ``search`` capability backed by ``server``."""
    document = load_manifest_yaml(MINIMAL.read_text(encoding="utf-8"))
    mission = document["mission"]
    mission["environment"]["sandbox"]["egress"] = [server]
    mission["environment"]["capabilities"] = [
        {"kind": "mcp_server", "as": "search", **SEARCH_SERVERS[server]}
    ]
    mission["program"]["nodes"][0]["action_space"] = ["search"]
    return canonical_manifest_bytes(document).decode("utf-8")


def two_variant_manifests() -> tuple[str, str]:
    """The source variant (PubMed) and the fork target variant (Tavily)."""
    return search_variant("pubmed"), search_variant("tavily")


class TwoVariantForkPrograms(ManifestProgramCompiler):
    def __init__(self, repository: Any, extensions: Any, payloads: Any) -> None:
        super().__init__(repository, extensions, payloads)
        self.repository, self.extensions, self.payloads = repository, extensions, payloads
        self.variants: dict[str, Any] = {}
        self.workflow_ref: Any = None
        self.preparation: dict[str, Any] = {}

    async def prepare(
        self,
        compiler: Any,
        manifests: tuple[str, str],
        *,
        request_scope: str,
        actor_id: str,
        at: datetime,
    ) -> dict[str, Any]:
        assert self.workflow_ref is None, "fork contract already prepared"
        variants = []
        for text in manifests:
            compilation = await compiler.compile(
                text, ManifestScope(request_scope=request_scope, actor_id=actor_id, at=at)
            )
            assert compilation.ok and len(compilation.programs) == 1, compilation.report.blockers
            lowered = compilation.programs[0].lowered
            configuration, _ = await super().compile(
                lowered,
                request_scope=request_scope,
                actor_id=actor_id,
                at=at,
                persist=True,
                compilation_suffix=f"two-variant-preparation.{uuid4().hex}",
            )
            variants.append((lowered, configuration))
        first, second = (entry[1] for entry in variants)
        protected = set(type(first.workflow_type).model_fields) - {
            "logical_id",
            "title",
            "description",
            "purpose",
            "allowed_blueprints",
            "allowed_control_profiles",
            "allowed_runtime_profiles",
            "allowed_workspace_templates",
            "allowed_evaluation_profiles",
        }
        for field in protected:
            assert getattr(first.workflow_type, field) == getattr(second.workflow_type, field), (
                "variant changes protected Workflow Type contract",
                field,
            )
        assert first.output_promises == second.output_promises, "variant changes output promises"
        assert type(first.selected_blueprint) is type(second.selected_blueprint)
        refs = {
            kind: frozenset(
                ref
                for _, config in variants
                for ref in config.source_refs
                if ref.kind.value == kind
            )
            for kind in SELECTORS
        }
        assert all(1 <= len(value) <= 2 for value in refs.values())
        allowed = {
            "allowed_blueprints": refs["blueprint"],
            "allowed_control_profiles": refs["control_profile"],
            "allowed_runtime_profiles": refs["runtime_profile"],
            "allowed_workspace_templates": refs["workspace_template"],
            "allowed_evaluation_profiles": refs["evaluation_profile"],
        }
        identity = sha256_digest(
            {key: sorted(ref.digest for ref in value) for key, value in allowed.items()}
        )[7:31]
        definition = first.workflow_type.model_copy(
            update={
                "logical_id": f"fixture.two-variant-fork.{identity}.workflow",
                "title": "Two-variant fork fixture",
                "description": "Exactly two variants; selected runtime capabilities stay narrow.",
                "purpose": "Run the source variant and fork it into the target variant.",
                **allowed,
            }
        )
        # Both ordinary component configurations are published before the shared contract.
        # No run has been admitted by this preparation.
        control = ControlPlaneService(self.repository, self.extensions, self.payloads)
        exact = ExactDefinitionRef(
            kind=definition.kind,
            logical_id=definition.logical_id,
            revision=1,
            digest=sha256_digest(definition),
        )
        try:
            published = await self.repository.get(exact)
        except DefinitionNotFound:
            published = await control.publish(
                PublishRequest(
                    definition=definition,
                    actor_id=actor_id,
                    published_at=at,
                    expected_head_revision=0,
                )
            )
        self.workflow_ref = published.ref
        self.variants = {sha256_digest(asdict(lowered)): config for lowered, config in variants}
        self.preparation = {
            "workflow_type_ref": published.ref.model_dump(mode="json"),
            "protected_fields": sorted(protected),
            "allowed_refs": {
                key: [ref.model_dump(mode="json") for ref in sorted(value, key=lambda r: r.digest)]
                for key, value in allowed.items()
            },
            "variant_components": [
                {
                    kind: next(
                        ref for ref in config.source_refs if ref.kind.value == kind
                    ).model_dump(mode="json")
                    for kind in SELECTORS
                }
                for _, config in variants
            ],
        }
        return self.preparation

    async def compile(
        self,
        lowered: Any,
        *,
        request_scope: str,
        actor_id: str,
        at: datetime,
        persist: bool,
        compilation_suffix: str | None = None,
    ) -> Any:
        if self.workflow_ref is None:
            return await super().compile(
                lowered,
                request_scope=request_scope,
                actor_id=actor_id,
                at=at,
                persist=persist,
                compilation_suffix=compilation_suffix,
            )
        template = self.variants.get(sha256_digest(asdict(lowered)))
        assert template is not None, (
            "unprepared fixture variant cannot use the shared Workflow Type"
        )
        assert template.context.authority_scope == request_scope
        assert template.context.authority_subject_id == actor_id
        refs = {
            kind: next(ref for ref in template.source_refs if ref.kind.value == kind)
            for kind in SELECTORS
        }
        repository = self.repository if persist else OverlayDefinitionRepository(self.repository)
        control = ControlPlaneService(repository, self.extensions, self.payloads)
        configuration = await control.compile(
            CompileInvocation(
                workflow_type=DefinitionSelector(exact=self.workflow_ref),
                **{key: DefinitionSelector(exact=value) for key, value in refs.items()},
                input_manifest=lowered.input_manifest,
                caller_authority=lowered.authority,
                environment=EnvironmentAvailability(
                    capabilities=MANIFEST_RUN_CAPABILITIES,
                    runtime_bindings=frozenset({MANIFEST_RUNTIME_BINDING}),
                ),
                context=CompilationContext(
                    compilation_id=f"{lowered.base_id}.shared-fork-contract.compile"
                    + (f".{compilation_suffix}" if compilation_suffix else ""),
                    compiled_at=at,
                    actor_id=actor_id,
                    authority_subject_id=actor_id,
                    authority_scope=request_scope,
                ),
            )
        )
        assert self.workflow_ref in configuration.source_refs
        assert (
            configuration.runtime_profile.operation_binding_refs
            == template.runtime_profile.operation_binding_refs
        )
        return configuration, self.workflow_ref
