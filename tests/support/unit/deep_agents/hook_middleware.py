"""Builders, constants and fakes that other test files import.

Moved from tests/unit/deep_agents/test_hook_middleware.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

from mission_control.adapters.capabilities.capability_bundles import bundle_digest
from mission_control.adapters.deep_agents.materializer import ResolvedHookScriptBundle
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef
from mission_control.domain.execution.contracts import DeepAgentHookScriptComponent
from tests.fixtures.lane_turns import INSTALLATION, TENANT


def _component(hook_id: str, order: int, files: tuple[tuple[str, bytes], ...]) -> Any:
    return DeepAgentHookScriptComponent(
        ref=ExactDefinitionRef(
            kind=DefinitionKind.HOOK_SCRIPT,
            logical_id=hook_id,
            revision=1,
            digest="sha256:" + "1" * 64,
        ),
        hook_id=hook_id,
        order=order,
        events=("before_shell",),
        interpreter="python",
        entrypoint="hook.py",
        manifest_digest=bundle_digest(files, require_skill_md=False),
    )


def _hook_bundles(
    *specs: tuple[int, str], callback: str = "none"
) -> tuple[dict[str, ResolvedHookScriptBundle], list[Any]]:
    bundles: dict[str, ResolvedHookScriptBundle] = {}
    components = []
    for order, hook_id in specs:
        files = (("hook.py", f"# {hook_id}\n".encode()),)
        component = _component(hook_id, order, files).model_copy(update={"callback": callback})
        bundles[component.manifest_digest] = ResolvedHookScriptBundle(
            component.manifest_digest, files
        )
        components.append(component)
    return bundles, components


def _binding(components: Sequence[Any], **values: Any) -> Any:
    defaults: dict[str, Any] = {
        "hook_scripts": tuple(components),
        "run_id": "run-1",
        "operation_id": "op-1",
        "operation_attempt": 1,
        "execution_generation": 1,
        "binding_id": "binding-1",
        "runtime_unit": None,
        "cognitive_session_namespace": None,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def _bound_binding(components: Sequence[Any]) -> Any:
    unit = SimpleNamespace(
        request_scope=f"mc/{INSTALLATION}/biotech/{TENANT}",
        belllabs_run_id="run-1",
        unit_key="stage:s1:op-1:1",
    )
    return _binding(
        components,
        runtime_unit=unit,
        cognitive_session_namespace="belllabs/stage/stage:s1:op-1:1/gen/1",
        placement="local_in_worker",
        binding_digest="sha256:" + "d" * 64,
    )
