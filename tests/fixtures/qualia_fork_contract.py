"""Explicit two-variant fixture Workflow Type, authored before either run admission.

Uses ordinary publish/compile APIs. The common fork's protected exact Workflow Type and
configuration authority checks stay unchanged; selected ERCs never gain the union's tools.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any
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
from mission_control.domain.authoring.manifest_lowering import (
    MANIFEST_RUN_CAPABILITIES,
    MANIFEST_RUNTIME_BINDING,
)

SELECTORS = (
    "blueprint",
    "control_profile",
    "runtime_profile",
    "workspace_template",
    "evaluation_profile",
)


class QualiaForkPrograms(ManifestProgramCompiler):
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
                compilation_suffix=f"qualia-contract-preparation.{uuid4().hex}",
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
                "logical_id": f"fixture.qualia.firecrawl-tavily.{identity}.workflow",
                "title": "Qualia Firecrawl source and Tavily fork",
                "description": "Exactly two variants; selected runtime capabilities stay narrow.",
                "purpose": "Run the source and independently reassess through the Tavily fork.",
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
