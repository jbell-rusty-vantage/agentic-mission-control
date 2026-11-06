"""Observation selection survives lowering and agrees with pinned projection rendering."""

from __future__ import annotations

import pytest

from mission_control.application.agentic_components.materialization import projection_digest
from mission_control.application.agentic_components.placement import (
    RenderedProjectionSource,
    static_rows,
)
from mission_control.application.agentic_components.telemetry import SIGNAL_SCRIPT
from mission_control.application.authoring.provider_launch import materialization_digest
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.domain.authoring.manifest_v2 import EnvironmentV2
from mission_control.domain.authoring.mission_definition import EnvironmentSelections
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from tests.unit.authoring.test_manifest_v2_launch import (
    DEFAULT_DATA_CLASS_POLICY,
    SCOPE,
    _compile,
    example,
    templates_of,
)
from tests.unit.codex.support import codex_binding, codex_operation


@pytest.mark.parametrize("enabled", [True, False])
async def test_observation_policy_pins_and_renders_the_same_pack(enabled: bool) -> None:
    selections = EnvironmentSelections.of(
        EnvironmentV2(observation={"in_environment": "on" if enabled else "off"})
    )
    assert selections is not None
    assert selections.binding_fields()["in_environment_observation"] is enabled
    original = codex_binding()
    binding = codex_binding(
        environment=original.environment.model_copy(update={"in_environment_observation": enabled})
    )
    operation = codex_operation(binding)
    projection = await RenderedProjectionSource(
        static_rows(()), projectors=HOST_PROJECTORS
    ).project(operation, profile="codex", packet_index=None)
    assert (SIGNAL_SCRIPT in {item.path for item in projection.files}) is enabled
    assert projection_digest(projection) == materialization_digest(
        (), "codex", operation.prompt_segments, projectors=HOST_PROJECTORS, telemetry=enabled
    )


async def test_manifest_off_is_inherited_lowered_and_sealed_into_launch_templates() -> None:
    document = load_manifest_yaml(example("codex", "goal-loop").read_text("utf-8"))
    document["mission"]["environment"]["observation"] = {"in_environment": "off"}
    compilation = await _compile(
        canonical_manifest_bytes(document).decode(), SCOPE, DEFAULT_DATA_CLASS_POLICY
    )
    assert compilation.ok
    (definition,) = compilation.definitions
    (program,) = compilation.programs
    templates = templates_of(program, definition, None)
    assert templates
    for operation in templates.values():
        binding = ProviderExecutionBinding.carried_by(operation)
        assert binding is not None and binding.environment.in_environment_observation is False
        projection = await RenderedProjectionSource(
            static_rows(()), projectors=HOST_PROJECTORS
        ).project(operation, profile="codex", packet_index=None)
        assert SIGNAL_SCRIPT not in {item.path for item in projection.files}
        assert projection_digest(projection) == binding.materialization_digest


async def test_manifest_gate_policy_is_pinned_in_the_launch_projection() -> None:
    document = load_manifest_yaml(example("codex", "goal-loop").read_text("utf-8"))
    document["mission"]["environment"]["observation"] = {"gates": {"fail_closed": True}}
    compilation = await _compile(
        canonical_manifest_bytes(document).decode(), SCOPE, DEFAULT_DATA_CLASS_POLICY
    )
    assert compilation.ok
    (definition,) = compilation.definitions
    (program,) = compilation.programs
    for operation in templates_of(program, definition, None).values():
        binding = ProviderExecutionBinding.carried_by(operation)
        assert binding is not None and binding.environment.signal_gates is not None
        projection = await RenderedProjectionSource(
            static_rows(()), projectors=HOST_PROJECTORS
        ).project(operation, profile="codex", packet_index=None)
        assert projection_digest(projection) == binding.materialization_digest
        hooks = next(item for item in projection.files if item.path == ".codex/hooks.json")
        assert b"gate codex before_tool" in hooks.content
