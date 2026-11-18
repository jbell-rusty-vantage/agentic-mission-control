"""Builders, constants and fakes that other test files import.

Moved from tests/unit/authoring/test_manifest_v2_launch.py.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_launch_inputs import (
    AdmittedLaunch,
    ManifestLaunchBindings,
    ManifestLaunchInputAuthor,
    ManifestLaunchResolver,
    ServedComponents,
)
from mission_control.application.authoring.manifest_service import (
    CompiledMission,
    ManifestCompilation,
    ManifestCompileService,
    ManifestProgramCompiler,
    ManifestScope,
)
from mission_control.bootstrap.resolution import compose_manifest_launch_resolver
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.execution.data_class import DEFAULT_DATA_CLASS_POLICY, DataClassPolicy
from tests.fixtures.applications import installed_applications
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.fixtures.models import bindings_catalog
from tests.support.ids import canonical_scope

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "tests/fixtures/manifests/multi-provider"
BINDINGS = (
    ROOT
    / "deployments/examples"
    / ("manifest-launch-bindings.multi-provider.codex-0.162.1.example.json")
)
V1_BINDINGS = ROOT / "deployments/examples/manifest-launch-bindings.deep-agents.example.json"


SCOPE = canonical_scope("tenant-1", "ai-engineer")
AT = datetime(2026, 10, 9, tzinfo=UTC)


def example(profile: str, form: str) -> Path:
    return EXAMPLES / f"{profile.replace('_', '-')}.{form}.mission.yml"


async def _compile(
    manifest_yaml: str, scope: str, data_class_policy: DataClassPolicy
) -> ManifestCompilation:
    definitions, search = await fast_track_catalog()
    service = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
        data_class_policy=data_class_policy,
    )
    return await service.compile(
        manifest_yaml, ManifestScope(request_scope=scope, actor_id="owner", at=AT)
    )


def compile_yaml(
    manifest_yaml: str,
    scope: str = SCOPE,
    data_class_policy: DataClassPolicy = DEFAULT_DATA_CLASS_POLICY,
) -> ManifestCompilation:
    return asyncio.run(_compile(manifest_yaml, scope, data_class_policy))


def compiled_ok(manifest_yaml: str) -> ManifestCompilation:
    compilation = compile_yaml(manifest_yaml)
    assert compilation.ok, [(item.pointer, item.message) for item in compilation.report.blockers]
    return compilation


def bindings() -> ManifestLaunchBindings:
    return ManifestLaunchBindings.load(BINDINGS)


def served(bound: ManifestLaunchBindings) -> ServedComponents:
    """FIXTURE: the example file's Deep Agent components as a test deployment serves them."""

    profile = bound.deep_agents.profile
    return ServedComponents(
        models=frozenset(item.ref.digest for item in bound.model_profiles.values()),
        sandboxes=frozenset(item.ref.digest for item in bound.sandbox_profiles.values()),
        checkpointers=frozenset({profile.checkpointer_ref.digest}),
        stores=frozenset({profile.store_ref.digest}),
        qualification=True,  # OC-R6: an explicit test composition (fixture models)
    )


def resolver(bound: ManifestLaunchBindings | None = None) -> ManifestLaunchResolver:
    bound = bound or bindings()
    return compose_manifest_launch_resolver(
        bound,
        served(bound),
        applications=installed_applications(),
        models=bindings_catalog(bound),
        provider_secret_env={"openai": "OPENAI_API_KEY"},
    )


def templates_of(
    program: CompiledMission, definition: MissionDefinition, bound: ManifestLaunchBindings | None
) -> dict[str, Any]:
    admitted = AdmittedLaunch.from_configuration(SCOPE, "run-v2", program.configuration)
    target = resolver(bound)
    if program.lowered.family == "StageGraph":
        return dict(target.stage_templates(definition, admitted))
    return dict(target.goal_templates(definition, admitted))


def edited(path: Path, change: Any) -> str:
    document = load_manifest_yaml(path.read_text(encoding="utf-8"))
    change(document)
    return canonical_manifest_bytes(document).decode("utf-8")


def blockers(compilation: ManifestCompilation) -> dict[str, str]:
    return {item.pointer: str(item.reason) for item in compilation.report.blockers}


def bundle_selection(skill: str, hook: str | None) -> Any:
    """Pin a skill bundle (and a hook script) mission-wide. Goal Loop criteria are accepted by
    human review and outputs are optional, so a launch reaches its capability rows; the Deep
    Agents node of a Stage Graph example is dropped (it has no component binding here)."""

    def change(document: dict[str, Any]) -> None:
        mission = document["mission"]
        environment = mission["environment"]
        environment["workspace"]["skills"] = [{"pin": skill, "as": "observe"}]
        if hook is not None:
            environment["hooks"] = [{"pin": hook, "events": ["before_tool"], "fail_closed": True}]
        program = mission["program"]
        if program["behavior"] == "stage_graph":
            program["nodes"] = [node for node in program["nodes"] if node["key"] != "summarize"]
            return
        for goal in mission["goals"]:
            for criterion in goal["criteria"]:
                criterion["acceptance"] = {"human": "review_accept"}
        for output in program["outputs"]:
            output["enforcement"] = "optional"

    return change


def stub_author(
    definition: MissionDefinition,
    program: CompiledMission,
    *,
    projection_rows: Any,
    persisted: list[dict[str, Any]],
    target: ManifestLaunchResolver | None = None,
    kits: Any = None,
) -> ManifestLaunchInputAuthor:
    """The launch author over one compiled run, recording every template it would freeze."""

    class Runs:
        async def get_run(self, _scope: str, _run: str) -> Any:
            return SimpleNamespace(effective_configuration_digest=program.configuration.digest)

    class Plane:
        async def retrieve_for_admission(self, _digest: str) -> Any:
            return program.configuration

    class Submissions:
        async def run_subscriptions(self, _scope: str, _run: str) -> dict[str, Any]:
            return {"definition": definition.model_dump(mode="json")}

    class Templates:
        async def persist_templates(self, **values: Any) -> None:
            persisted.append(values)

        async def get_template(self, **_: Any) -> Any:
            raise ValueError("no frozen template")

        async def list_templates(self, **_: Any) -> dict[str, Any]:
            return {}

    return ManifestLaunchInputAuthor(
        resolver=target or resolver(),
        run_control=Runs(),  # type: ignore[arg-type]
        control_plane=Plane(),  # type: ignore[arg-type]
        definitions=Submissions(),
        stage_templates=Templates(),  # type: ignore[arg-type]
        goal_templates=Templates(),  # type: ignore[arg-type]
        projection_rows=projection_rows,
        kits=kits,
    )
