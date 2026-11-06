"""Schema-only dependent inputs retain exact validation and fail closed for richer promises."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mission_control.application.authoring.manifest_launch_inputs import ManifestLaunchInputAuthor
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import StageGraphBlueprint
from mission_control.domain.outputs.contracts import Enforcement, OutputForm, Requirement, SchemaPin
from mission_control.domain.programs.contracts import StageAuthoredInput
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog, publish_output_schemas
from tests.unit.authoring import test_manifest_launch_inputs as fixtures
from tests.unit.authoring.test_manifest_launch_inputs import MINIMAL, compile_programs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant", ["valid", "reference", "assessment", "unbound", "missing", "schema_mismatch"]
)
async def test_only_exact_bound_schema_values_pass_without_trusted_settlement(
    variant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def bound_catalog() -> Any:
        definitions, search = await fast_track_catalog()
        await publish_output_schemas(
            definitions,
            {"source_manifest@1": {"type": "object"}, "claim_table@1": {"type": "object"}},
        )
        return definitions, search

    monkeypatch.setattr(fixtures, "fast_track_catalog", bound_catalog)
    _, programs = await compile_programs(MINIMAL.read_text(encoding="utf-8"))
    configuration = programs[0].configuration
    blueprint = configuration.selected_blueprint
    promises = blueprint.output_promises
    assert promises is not None
    original = promises.obligation("collect.sources")
    assert original is not None and original.contract.schema_pin is not None
    contract = original.contract
    if variant == "reference":
        contract = contract.model_copy(update={"form": OutputForm.REFERENCE, "schema_pin": None})
    elif variant == "assessment":
        contract = contract.model_copy(
            update={
                "requirements": (
                    Requirement(key="assessed", validator="knowledge.report.assess@1"),
                )
            }
        )
    elif variant == "unbound":
        contract = contract.model_copy(
            update={"schema_pin": SchemaPin(ref=contract.schema_pin.ref)}
        )
    elif variant == "schema_mismatch":
        contract = contract.model_copy(
            update={
                "schema_pin": SchemaPin(
                    ref="different@1",
                    body={},
                    digest=sha256_digest({}),
                )
            }
        )
    updated = original.model_copy(update={"contract": contract})
    altered = promises.model_copy(
        update={
            "obligations": tuple(
                updated if item.key == original.key else item for item in promises.obligations
            )
        }
    )
    configuration = configuration.model_copy(
        update={"selected_blueprint": blueprint.model_copy(update={"output_promises": altered})}
    )

    class Runs:
        async def get_run(self, scope: str, run_id: str) -> Any:
            assert (scope, run_id) == ("scope", "run")
            return SimpleNamespace(effective_configuration_digest=configuration.digest)

    class Configurations:
        async def retrieve_for_admission(self, digest: str) -> Any:
            assert digest == configuration.digest
            return configuration

    author = ManifestLaunchInputAuthor(
        resolver=None,  # type: ignore[arg-type]
        run_control=Runs(),  # type: ignore[arg-type]
        control_plane=Configurations(),  # type: ignore[arg-type]
        definitions=None,  # type: ignore[arg-type]
        stage_templates=None,  # type: ignore[arg-type]
        goal_templates=None,  # type: ignore[arg-type]
        dependent_inputs_admitted=False,
    )
    selected = StageAuthoredInput("synthesize", "collect", "sources", "sources")
    if variant == "missing":
        selected = replace(selected, producer_output_slot_id="missing")
    assert await author._schema_only_dependent_inputs("scope", "run", (selected,)) is (
        variant == "valid"
    )
    # A second unknown input cannot be hidden by a valid first selection.
    assert not await author._schema_only_dependent_inputs(
        "scope", "run", (selected, replace(selected, producer_stage_id="unknown"))
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "variant",
    [
        "valid",
        "required_input",
        "required_promise",
        "required_slot",
        "text_assessment",
        "reference",
    ],
)
async def test_full_qualia_graph_optional_plain_text_keeps_narrow_launch_eligibility(
    tmp_path: Path,
    variant: str,
) -> None:
    from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
    from mission_control.application.authoring.manifest_service import (
        ManifestCompileService,
        ManifestProgramCompiler,
        ManifestScope,
    )
    from mission_control.application.programs.stage_inputs import stagegraph_authored_inputs
    from mission_control.domain.authoring.extensions import ExtensionRegistry
    from tests.fixtures.mission_control_common_db import canonical_scope
    from tests.fixtures.qualia_full_manifest import full_manifest
    from tests.fixtures.qualia_stagegraph import RECORD_SCHEMA
    from tests.fixtures.qualia_web_tools import build_qualia_web_tools

    definitions, search = await fast_track_catalog()
    web = build_qualia_web_tools(tmp_path / "web", environment={})
    for definition in web.definitions.values():
        await definitions.publish(definition, "fixture", datetime.now(UTC), 0)
    await publish_output_schemas(definitions, {"qualia_record@1": RECORD_SCHEMA})
    compiler = ManifestCompileService(
        definitions=definitions,
        search=search,
        programs=ManifestProgramCompiler(definitions, ExtensionRegistry(), InMemoryPayloadStore()),
    )
    compiled = await compiler.compile(
        full_manifest(web, [], vendor="firecrawl", interventions=False),
        ManifestScope(request_scope=canonical_scope(), actor_id="owner", at=datetime.now(UTC)),
    )
    assert compiled.ok, compiled.report.blockers
    (program,), (definition,) = compiled.programs, compiled.definitions
    configuration = program.configuration
    blueprint = configuration.selected_blueprint
    assert isinstance(blueprint, StageGraphBlueprint)
    promises = blueprint.output_promises
    assert promises is not None
    original = promises.obligation("discover.optional_background")
    assert original is not None
    if variant == "required_promise":
        changed = original.model_copy(update={"enforcement": Enforcement.REQUIRED})
    elif variant == "text_assessment":
        changed = original.model_copy(
            update={
                "contract": original.contract.model_copy(
                    update={
                        "requirements": (
                            Requirement(key="assessed", validator="knowledge.report.assess@1"),
                        ),
                    }
                )
            }
        )
    elif variant == "reference":
        changed = original.model_copy(
            update={"contract": original.contract.model_copy(update={"form": OutputForm.REFERENCE})}
        )
    else:
        changed = original
    stages = blueprint.stages
    if variant == "required_slot":
        stages = tuple(
            stage.model_copy(
                update={
                    "output_slots": tuple(
                        slot.model_copy(update={"required": True})
                        if slot.output_slot_id == "optional_background"
                        else slot
                        for slot in stage.output_slots
                    )
                }
            )
            if stage.stage_id == "discover"
            else stage
            for stage in stages
        )
    configuration = configuration.model_copy(
        update={
            "selected_blueprint": blueprint.model_copy(
                update={
                    "stages": stages,
                    "output_promises": promises.model_copy(
                        update={
                            "obligations": tuple(
                                changed if promise.key == original.key else promise
                                for promise in promises.obligations
                            )
                        }
                    ),
                }
            )
        }
    )
    inputs = stagegraph_authored_inputs(definition)
    if variant == "required_input":
        inputs = tuple(
            replace(item, required=True) if item.name == "background" else item for item in inputs
        )

    class Runs:
        async def get_run(self, *_args: Any) -> Any:
            return SimpleNamespace(effective_configuration_digest=configuration.digest)

    class Plane:
        async def retrieve_for_admission(self, _digest: str) -> Any:
            return configuration

    class Definitions:
        async def run_subscriptions(self, *_args: Any) -> Any:
            return {"definition": definition.model_dump(mode="json")}

    author = ManifestLaunchInputAuthor(
        resolver=None,  # type: ignore[arg-type]
        run_control=Runs(),  # type: ignore[arg-type]
        control_plane=Plane(),  # type: ignore[arg-type]
        definitions=Definitions(),
        stage_templates=None,  # type: ignore[arg-type]
        goal_templates=None,  # type: ignore[arg-type]
        dependent_inputs_admitted=False,
    )
    assert await author._schema_only_dependent_inputs(canonical_scope(), "run", inputs) is (
        variant == "valid"
    )
    if variant != "valid":
        return

    @dataclass
    class Prepared:
        stage_inputs: tuple[StageAuthoredInput, ...]

    class Dispatcher:
        async def prepare(self, *_args: Any, **kwargs: Any) -> Prepared:
            return Prepared(kwargs["stage_inputs"])

    async def bind(*_args: Any, **_kwargs: Any) -> Any:
        return {}

    author.bind = bind  # type: ignore[method-assign]
    author._dispatcher = Dispatcher()  # type: ignore[assignment]
    launched = await author.family_input(
        request_scope=canonical_scope(), run_id="run", family="StageGraph", initial_goal=None
    )
    assert {item["consumer_stage_id"] for item in launched["stage_inputs"]} == {
        "formulations",
        "studies",
        "synthesize",
        "verify",
        "ingest",
        "finalize",
    }
