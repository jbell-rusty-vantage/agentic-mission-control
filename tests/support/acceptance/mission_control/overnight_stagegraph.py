"""Builders, constants and fakes that other test files import.

Moved from tests/acceptance/mission_control/test_overnight_stagegraph.py.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from mission_control.application.authoring.manifest_submit import SubmitRequest
from mission_control.contracts.identities import mission_root_id
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from tests.fixtures.manifest_runtime import AUTHOR
from tests.fixtures.rrm009_production_harness import ProductionStack

ROOT = Path(__file__).resolve().parents[4]
TEMPLATE = ROOT / "tests/fixtures/manifests/sprint-oc-w2/ai-engineer.producer-consumer.mission.yml"


def overnight_launch_bindings(technical: Any) -> Any:
    from mission_control.adapters.deep_agents.knowledge_tools import (
        knowledge_launch_bindings,
        knowledge_tools,
    )
    from tests.fixtures.models import model_binding
    from tests.fixtures.rrm009_production_stack import AGENT_COGNITIVE_QUEUE
    from tests.unit.authoring.manifest_launch_fixture import fixture_bindings

    authored = load_manifest_yaml(TEMPLATE.read_text(encoding="utf-8"))
    pins = {
        item["pin"].split("@", 1)[0]: item["pin"].split("#", 1)[1]
        for item in authored["mission"]["environment"]["capabilities"]
    }
    bindings = fixture_bindings(task_queue=AGENT_COGNITIVE_QUEUE).model_copy(
        update={
            "model_profiles": {"frontier.default": model_binding(technical.binding.model)},
            "sandbox_profiles": {"research.standard": technical.binding.sandbox},
            "capabilities": knowledge_launch_bindings(pins, knowledge_tools(cast(Any, None))),
        }
    )
    assert set(pins) <= set(bindings.capabilities)
    return type(bindings).model_validate(bindings.model_dump(mode="python"))


async def production_lifecycle(
    stack: ProductionStack, components: Any, *, models: Any = None
) -> Any:
    """Use the actual manifest launch author, including ERC obligations and transfer pins."""
    assert stack.database is not None
    from mission_control.adapters.postgres.control_plane.definition_repository import (
        PostgresDefinitionRepository,
    )
    from mission_control.adapters.postgres.control_plane.manifest_submission import (
        PostgresManifestSubmissionRepository,
    )
    from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
    from mission_control.application.authoring.manifest_service import (
        ManifestCompileService,
        ManifestProgramCompiler,
    )
    from mission_control.application.authoring.manifest_submit import (
        ManifestSubmitService,
        register_manifest_admission_policies,
    )
    from mission_control.bootstrap.manifests import compose_manifest_launch_inputs
    from mission_control.bootstrap.technical_api import api
    from mission_control.domain.authoring.extensions import ExtensionRegistry
    from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
    from tests.fixtures.models import catalog_for

    run_control = api.state.run_control_service
    register_manifest_admission_policies(api.state.admission_policy_registry)
    author = compose_manifest_launch_inputs(
        stack.worker_pool,
        settings=stack.settings,
        application_id=stack.database.application_id,
        run_control=run_control,
        control_plane=stack.control_plane,
        additional=components,
        models=models
        if models is not None
        else catalog_for({"frontier.default": stack.technical.binding.model}),
        trusted_settlement_ready=lambda: stack.factory.knowledge.trusted is not None,
    )
    assert author is not None, "fixture needs an explicit MANIFEST_LAUNCH_BINDINGS_PATH"
    definitions, search = await fast_track_catalog()
    catalog = PostgresDefinitionRepository(
        stack.worker_pool, catalog_scope=stack.settings.mission_control_catalog_scope or ""
    )
    programs = ManifestProgramCompiler(catalog, ExtensionRegistry(), InMemoryPayloadStore())
    return ManifestSubmitService(
        compiler=ManifestCompileService(definitions=definitions, search=search, programs=programs),
        programs=programs,
        run_control=run_control,
        submissions=PostgresManifestSubmissionRepository(stack.worker_pool),
        request_scope=stack.database.scope("tenant-1"),
        launches=api.state.run_launch_service,
        launch_inputs=author,
    )


def stagegraph_manifest(pack: dict[str, Any]) -> str:
    """Reuse accepted W2 authoring with one optional omission and small local bounds."""
    text = TEMPLATE.read_text(encoding="utf-8")
    text = text.replace("__PACK__", json.dumps(pack, sort_keys=True))
    text = text.replace("__PRODUCER__", "frontier.default")
    text = text.replace("__CONSUMER__", "frontier.default")
    document = load_manifest_yaml(text)
    mission = document["mission"]
    mission["key"] = "overnight-stagegraph-exact-report"
    mission["title"] = "Small exact report transfer with observed consumer read"
    # The fixture's own final review gate is replaced by the two review nodes below.
    producer, consumer = mission["program"]["nodes"][:2]
    producer["outputs"].append(
        {"name": "caveats", "form": "text", "enforcement": "optional", "media_type": "text/plain"}
    )
    # The inherited W2 human criteria were attached to cognition with no qualified
    # human evaluator. Preserve those criteria and author explicit ordinary REVIEW nodes.
    producer_objectives = producer["objectives"]
    consumer_objectives = consumer["objectives"]
    consumer["depends_on"] = ["review-producer"]
    consumer["instruction"] = consumer["instruction"].replace(
        "/.mission/inputs.json", "/.mission/transfer.json"
    )
    mission["program"]["nodes"] = [
        producer,
        {
            "key": "review-producer",
            "behavior": "human_gate",
            "objectives": producer_objectives,
            "depends_on": ["produce"],
            "task": {
                "kind": "REVIEW",
                "prompt": "Review this exact report and progress note.",
                "reviewers": ["owner"],
                "packet": ["produce.report", "produce.progress_note"],
                "on_timeout": "keep_waiting",
            },
        },
        consumer,
        {
            "key": "review-consumer",
            "behavior": "human_gate",
            "objectives": consumer_objectives,
            "depends_on": ["consume"],
            "task": {
                "kind": "REVIEW",
                "prompt": "Review the summary of the exact accepted report.",
                "reviewers": ["owner"],
                "packet": ["produce.report", "consume.comparison"],
                "on_timeout": "keep_waiting",
            },
        },
    ]
    # The optional slot is intentionally unsubmitted; required progress/report remain intact.
    return canonical_manifest_bytes(document).decode("utf-8")


async def run_stagegraph_fixture(
    stack: ProductionStack,
    lifecycle: Any,
    manifest: str,
    destination: Path,
    *,
    collect: Callable[[str, Path], Awaitable[None]],
    verify: Callable[[str], Awaitable[None]],
    progress: Callable[[str], Awaitable[None]] | None = None,
    expected_terminal_outcomes: frozenset[str] = frozenset({"completed"}),
    timeout_seconds: float = 180,
) -> str:
    """Submit/start through ordinary handlers, retain failed attempts, require exact proof.

    ``verify`` must check actual output-store/transfer/read receipts, not model prose.
    ``collect`` runs while PostgreSQL, Temporal, provider backends and KS remain available.
    The caller owns teardown and cancellation if a timed-out workflow is still active.
    """
    assert stack.database is not None
    await asyncio.to_thread(destination.mkdir, parents=True, exist_ok=True)
    (destination / "01-authored-mission.yml").write_text(manifest, encoding="utf-8")
    run_id: str | None = None
    outcome: dict[str, Any] = {"qualified": False, "result": "failed-before-admission"}
    try:
        receipt, replayed = await lifecycle.submit(
            SubmitRequest(
                manifest_yaml=manifest,
                request_id=uuid4(),
                actor=AUTHOR,
                sponsorship_refs=frozenset({"sponsorship:test"}),
            )
        )
        assert not replayed
        (mission,) = receipt.missions
        assert mission.family == "StageGraph" and mission.run_id is not None
        run_id = mission.run_id
        outcome["result"] = "admitted"
        (destination / "06-evidence").mkdir(exist_ok=True)
        (destination / "06-evidence/admission.json").write_text(
            receipt.model_dump_json(indent=2), encoding="utf-8"
        )
        await lifecycle.start(run_id, AUTHOR)
        outcome["result"] = "running"
        scope = stack.database.scope("tenant-1")
        async with asyncio.timeout(timeout_seconds):
            while True:
                if progress is not None:
                    await progress(run_id)
                response = await stack.http.get(
                    f"/run-control/v1/runs/{run_id}", params={"request_scope": scope}
                )
                assert response.status_code == 200, response.text
                observed = response.json()
                if observed["phase"] == "terminal":
                    break
                await asyncio.sleep(0.25)
            outcome["terminal"] = observed
            root = stack.client.get_workflow_handle(mission_root_id(scope, run_id))
            assert (await root.describe()).workflow_type == "mc.mission_run.v1"
            await root.result()
        outcome["terminal"] = observed
        assert observed["terminal_outcome"] in expected_terminal_outcomes, observed
        await verify(run_id)
        outcome["result"] = "passed-engineering-fixture"
        return run_id
    except BaseException as error:
        outcome["last_execution_state"] = outcome["result"]
        outcome["result"] = (
            "timed_out"
            if isinstance(error, TimeoutError)
            else "cancelled"
            if isinstance(error, asyncio.CancelledError)
            else "failed"
        )
        outcome["error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        try:
            if run_id is not None:
                await collect(run_id, destination)
        finally:
            (destination / "07-validation.json").write_text(
                json.dumps(outcome, indent=2, default=str), encoding="utf-8"
            )
