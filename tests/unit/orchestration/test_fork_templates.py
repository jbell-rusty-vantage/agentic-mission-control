"""RRM-009 (RRM-006): a fork's StageGraph templates derive from the source's with the patch."""

from __future__ import annotations

from datetime import datetime

import pytest

from mission_control.application.programs.fork_templates import (
    ForkPatchNotApplicable,
    StageGraphForkTemplateDerivation,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.policies.forks import (
    ForkPatchChange,
    RunForkPatch,
    stage_objective_path,
)
from tests.unit.operations.test_operation_execution import DIGEST, operation_request


class MemoryTemplates:
    def __init__(self) -> None:
        self.stored: dict[tuple[str, str], dict[str, OperationExecutionRequest]] = {}

    async def list_templates(
        self, *, request_scope: str, semantic_input_binding_ref: str
    ) -> dict[str, OperationExecutionRequest]:
        return dict(self.stored.get((request_scope, semantic_input_binding_ref), {}))

    async def persist_templates(
        self,
        *,
        request_scope: str,
        semantic_input_binding_ref: str,
        templates: dict[str, OperationExecutionRequest],
        recorded_at: datetime,
    ) -> None:
        del recorded_at
        self.stored[(request_scope, semantic_input_binding_ref)] = dict(templates)


def _patch(*changes: tuple[str, str]) -> RunForkPatch:
    snapshot = "run-snapshot:" + "a" * 64
    return RunForkPatch.create(
        source_snapshot_id=snapshot,
        source_snapshot_digest="sha256:" + "b" * 64,
        target_admission_request_ref="run-request:tenant-1:operator:fork",
        changes=tuple(ForkPatchChange(path=path, value=value) for path, value in changes),
        invalidation_frontier=("review",),
    )


@pytest.mark.asyncio
async def test_patched_stage_gains_an_admitted_objective_and_the_rest_is_copied() -> None:
    store = MemoryTemplates()
    source = {
        "draft/execute/default": operation_request(prompt="draft"),
        "review/execute/default": operation_request(prompt="review"),
    }
    store.stored[("tenant-1", "semantic-input:source")] = source
    derivation = StageGraphForkTemplateDerivation(store)

    patched = await derivation.derive_stagegraph(
        request_scope="tenant-1",
        source_semantic_input_binding_ref="semantic-input:source",
        derived_semantic_input_binding_ref="semantic-input:fork:f1",
        patch=_patch((stage_objective_path("review"), "Review more strictly.")),
        expected_configuration_digest=DIGEST,
    )
    assert patched == ("review/execute/default",)
    derived = store.stored[("tenant-1", "semantic-input:fork:f1")]
    assert derived["draft/execute/default"] == source["draft/execute/default"]
    segment = derived["review/execute/default"].prompt_segments[-1]
    assert segment.source_ref == "fork-objective:review"
    assert segment.trust_class.value == "admitted_input"
    assert segment.content == "Review more strictly."
    assert segment.rendered_digest == sha256_digest("Review more strictly.")
    assert derived["review/execute/default"].prompt_segments[:-1] == (
        source["review/execute/default"].prompt_segments
    )
    # The source's templates are untouched.
    assert store.stored[("tenant-1", "semantic-input:source")] == source


@pytest.mark.asyncio
async def test_patch_naming_a_stage_without_a_template_is_refused() -> None:
    store = MemoryTemplates()
    store.stored[("tenant-1", "semantic-input:source")] = {
        "draft/execute/default": operation_request(prompt="draft")
    }
    derivation = StageGraphForkTemplateDerivation(store)
    with pytest.raises(ForkPatchNotApplicable, match="review"):
        await derivation.derive_stagegraph(
            request_scope="tenant-1",
            source_semantic_input_binding_ref="semantic-input:source",
            derived_semantic_input_binding_ref="semantic-input:fork:f2",
            patch=_patch((stage_objective_path("review"), "x")),
            expected_configuration_digest=DIGEST,
        )
    with pytest.raises(ForkPatchNotApplicable, match="no StageGraph"):
        await derivation.derive_stagegraph(
            request_scope="tenant-1",
            source_semantic_input_binding_ref="semantic-input:missing",
            derived_semantic_input_binding_ref="semantic-input:fork:f3",
            patch=_patch(),
            expected_configuration_digest=DIGEST,
        )
    assert ("tenant-1", "semantic-input:fork:f2") not in store.stored


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["scope", "configuration"])
async def test_fork_refuses_foreign_or_old_templates_without_partial_persistence(
    mismatch: str,
) -> None:
    store = MemoryTemplates()
    valid = operation_request()
    invalid = valid.model_copy(
        update={
            "request_scope" if mismatch == "scope" else "effective_configuration_digest": (
                "another-tenant" if mismatch == "scope" else "sha256:" + "e" * 64
            )
        }
    )
    store.stored[("tenant-1", "semantic-input:prepared")] = {
        "draft/execute/default": valid,
        "review/execute/default": invalid,
    }
    with pytest.raises(ForkPatchNotApplicable, match="review/execute/default"):
        await StageGraphForkTemplateDerivation(store).derive_stagegraph(
            request_scope="tenant-1",
            source_semantic_input_binding_ref="semantic-input:prepared",
            derived_semantic_input_binding_ref="semantic-input:fork:refused",
            patch=_patch(),
            expected_configuration_digest=DIGEST,
        )
    assert ("tenant-1", "semantic-input:fork:refused") not in store.stored


@pytest.mark.asyncio
async def test_changed_configuration_uses_prepared_exact_capabilities_and_retains_sources() -> None:
    """A prepared successor supplies the capabilities; the fork never rewrites their pins."""
    from mission_control.domain.authoring.contracts import DefinitionKind
    from mission_control.domain.execution.contracts import ImmutableAssetBinding
    from tests.unit.operations.test_operation_execution import exact

    store = MemoryTemplates()
    original = operation_request()
    successor_digest = "sha256:" + "e" * 64
    tavily = ImmutableAssetBinding(
        ref=exact(DefinitionKind.SKILL, "skill.tavily-search", successor_digest),
        manifest_digest=successor_digest,
        mount_path="/skills/tavily-search/SKILL.md",
    )
    prepared = original.model_copy(
        update={"effective_configuration_digest": successor_digest, "skills": (tavily,)}
    )
    store.stored[("tenant-1", "semantic-input:original")] = {"review/execute/default": original}
    store.stored[("tenant-1", "semantic-input:prepared")] = {"review/execute/default": prepared}
    patch = RunForkPatch.create(
        source_snapshot_id="run-snapshot:" + "a" * 64,
        source_snapshot_digest="sha256:" + "b" * 64,
        target_admission_request_ref="run-request:tenant-1:operator:fork",
        changes=(ForkPatchChange(path="effective_configuration_digest", value=successor_digest),),
        invalidation_frontier=("*",),
    )
    await StageGraphForkTemplateDerivation(store).derive_stagegraph(
        request_scope="tenant-1",
        source_semantic_input_binding_ref="semantic-input:prepared",
        derived_semantic_input_binding_ref="semantic-input:fork:successor",
        patch=patch,
        expected_configuration_digest=successor_digest,
    )
    copied = store.stored[("tenant-1", "semantic-input:fork:successor")]["review/execute/default"]
    assert copied == prepared
    assert copied.skills == (tavily,)
    assert copied.mcp_servers == prepared.mcp_servers
    assert copied.lane_binding == prepared.lane_binding
    assert (
        store.stored[("tenant-1", "semantic-input:original")]["review/execute/default"] == original
    )
    assert (
        store.stored[("tenant-1", "semantic-input:prepared")]["review/execute/default"] == prepared
    )
