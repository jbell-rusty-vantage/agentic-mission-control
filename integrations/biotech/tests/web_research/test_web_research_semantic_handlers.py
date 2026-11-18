from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import ValidationError
from tests.fixtures.lane_bindings import LANE_REBINDERS
from tests.support.unit.web_research.web_research_semantic_handlers import (
    BLUEPRINT_DIGEST,
    BROWSER_RUNTIME,
    CONFIGURATION_DIGEST,
    FIRECRAWL_RUNTIME,
    OPENAI_SENTINEL,
    RUN_ID,
    SCOPE,
    TAVILY_RUNTIME,
    FakeBrowser,
    FakeSearch,
    binding,
    binding_authority,
    exact_ref,
    request,
    runtime,
)

from biotech_mission_adapters.application.web_research.web_research_repository import (
    InMemoryWebResearchRecordRepository,
)
from biotech_mission_adapters.application.web_research.web_research_semantic_handlers import (
    WebResearchHandlerDependencies,
    build_web_research_run_binding,
    register_web_research_stagegraph_handlers,
)
from biotech_mission_adapters.domain.coordinator.web_research_runtime import (
    BrowserExecutionGrantBinding,
    VerifiedWebResearchResult,
    WebResearchGoal,
    WebResearchRecordEnvelope,
)
from mission_control.adapters.temporal.coordinator_runtime import (
    GoalDirectedCoordinatorDependencies,
    StageGraphCoordinatorDependencies,
    create_routed_coordinator_activities,
)
from mission_control.application.programs.goal_directed import (
    InMemoryGoalOperationTemplateRepository,
)
from mission_control.application.programs.orchestration_binding_repository import (
    InMemoryRunSemanticInputBindingRepository,
)
from mission_control.application.programs.orchestration_routing import (
    BoundStageOperationExecutor,
    SemanticHandlerRegistry,
    SemanticRoutingError,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.programs.bindings import StageHandlerBinding
from mission_control.domain.programs.contracts import (
    WorkflowEvaluationRequest,
)


class FakeLifecycle:
    async def execute(self, request: object) -> object:
        raise AssertionError(f"not used: {request!r}")


@pytest.mark.asyncio
async def test_full_governed_web_research_handler_workflow() -> None:
    (
        operations,
        evaluator,
        records,
        firecrawl,
        tavily,
        browser,
        frozen,
    ) = await runtime()

    admission = await operations.execute(request("admit_public_goal"))
    firecrawl_result = await operations.execute(
        request("search_firecrawl", input_refs=admission.output_refs)
    )
    tavily_result = await operations.execute(
        request("search_tavily", input_refs=admission.output_refs)
    )
    synthesis = await operations.execute(
        request(
            "synthesize_citations",
            input_refs=firecrawl_result.output_refs + tavily_result.output_refs,
        )
    )
    browser_result = await operations.execute(
        request("browser_verify", input_refs=synthesis.output_refs)
    )
    promoted = await operations.execute(
        request("promote_verified_result", input_refs=browser_result.output_refs)
    )
    evaluated = await evaluator.evaluate(
        WorkflowEvaluationRequest(
            run_id=RUN_ID,
            workflow_cycle=1,
            objective="produce verified research",
            current_output_refs={"promote_verified_result": promoted.output_refs},
            execution_lineage=(
                admission,
                firecrawl_result,
                tavily_result,
                synthesis,
                browser_result,
                promoted,
            ),
            request_scope=SCOPE,
            semantic_input_binding_ref=frozen.binding_id,
            effective_configuration_digest=CONFIGURATION_DIGEST,
            blueprint_digest=BLUEPRINT_DIGEST,
            evaluation_contract_ref=("evaluation:web-research-browser-verification:v1"),
            objective_contract_ref="objective:web-research:v1",
        )
    )

    assert evaluated.action == "accept"
    assert promoted.output_contract_ref == ("schema:web-research-browser-verification-result:v1")
    assert len(firecrawl.requests) == 1
    assert len(tavily.requests) == 1
    assert len(browser.requests) == 1
    assert all("?" not in url for url in browser.requests[0].urls)

    final_record = await records.get(SCOPE, RUN_ID, promoted.output_refs[0])
    persisted = json.dumps(final_record.payload)
    assert "do-not-persist" not in persisted
    assert OPENAI_SENTINEL not in persisted
    assert "provider-secret-request-id" not in persisted

    # Attribution survives the same JSON envelope boundary used by PostgreSQL records.
    restored = WebResearchRecordEnvelope.model_validate_json(final_record.model_dump_json())
    report = VerifiedWebResearchResult.model_validate(restored.payload)
    provenance = report.provenance
    assert provenance is not None
    promotion_request = request("promote_verified_result", input_refs=browser_result.output_refs)
    assert provenance.run_id == RUN_ID
    assert provenance.request_scope == SCOPE
    assert provenance.operation_id == promotion_request.identity.operation_id
    assert provenance.semantic_key == promotion_request.identity.semantic_key
    assert provenance.handler_ref == "web-research.promote-verified-result@1"
    assert provenance.producer_kind == "deterministic_semantic_handler"
    assert "mission_id" not in provenance.model_dump()
    assert "provider_execution_id" not in provenance.model_dump()

    # A recovery generation replay returns the committed report and original attribution.
    replay = replace(
        promotion_request,
        identity=replace(promotion_request.identity, execution_generation=2),
    )
    replay_result = await operations.execute(replay)
    assert replay_result.output_refs == promoted.output_refs
    replay_record = await records.get(SCOPE, RUN_ID, replay_result.output_refs[0])
    assert replay_record == final_record
    assert provenance.execution_generation == 1

    # Provenance is inside the content digest and cannot be moved between scopes/runs.
    changed = json.loads(final_record.model_dump_json())
    changed["payload"]["provenance"]["run_id"] = "another-run"
    with pytest.raises(ValidationError, match="payload digest mismatch"):
        WebResearchRecordEnvelope.model_validate(changed)
    changed["content_digest"] = sha256_digest(changed["payload"])
    with pytest.raises(ValidationError, match="provenance differs from record scope or run"):
        WebResearchRecordEnvelope.model_validate(changed)
    changed["payload"]["provenance"]["run_id"] = RUN_ID
    changed["payload"]["provenance"]["request_scope"] = "another-scope"
    changed["content_digest"] = sha256_digest(changed["payload"])
    with pytest.raises(ValidationError, match="provenance differs from record scope or run"):
        WebResearchRecordEnvelope.model_validate(changed)

    legacy_payload = dict(final_record.payload)
    del legacy_payload["provenance"]
    assert VerifiedWebResearchResult.model_validate(legacy_payload).provenance is None


@pytest.mark.asyncio
async def test_provider_search_is_retry_idempotent_after_record_commit() -> None:
    operations, _evaluator, _records, firecrawl, _tavily, _browser, _frozen = await runtime()
    admission = await operations.execute(request("admit_public_goal"))
    provider_request = request(
        "search_firecrawl",
        input_refs=admission.output_refs,
    )

    first = await operations.execute(provider_request)
    second = await operations.execute(provider_request)

    assert first == second
    assert len(firecrawl.requests) == 1


@pytest.mark.asyncio
async def test_public_goal_admission_fails_closed_for_secret_or_active_authority() -> None:
    for question in (
        "Log in to a private account and inspect Upgrade Labs",
        "Research public pages using api_key=secret-material-value",
    ):
        bindings = InMemoryRunSemanticInputBindingRepository()
        records = InMemoryWebResearchRecordRepository()
        registry = SemanticHandlerRegistry()
        register_web_research_stagegraph_handlers(
            registry,
            WebResearchHandlerDependencies(
                firecrawl=FakeSearch("firecrawl"),
                tavily=FakeSearch("tavily"),
                browser=FakeBrowser(),
                records=records,
            ),
        )
        frozen = binding(WebResearchGoal(question=question))
        await bindings.create(frozen)

        with pytest.raises(SemanticRoutingError):
            await BoundStageOperationExecutor(bindings, registry).execute(
                request("admit_public_goal")
            )


def test_binding_uses_all_exact_published_handler_revisions() -> None:
    frozen = binding()

    assert {(item.stage_id, item.handler.exact_handler_ref) for item in frozen.stage_handlers} == {
        ("admit_public_goal", "web-research.admit-public-goal@1"),
        ("search_firecrawl", "web-research.search-firecrawl@1"),
        ("search_tavily", "web-research.search-tavily@1"),
        ("synthesize_citations", "web-research.synthesize-citations@1"),
        ("browser_verify", "web-research.verify-in-browser@1"),
        ("promote_verified_result", "web-research.promote-verified-result@1"),
    }
    assert frozen.workflow_evaluator is not None
    assert frozen.workflow_evaluator.exact_handler_ref == "web-research.evaluate@1"


def test_routed_activity_composition_registers_web_research_handlers() -> None:
    registry = SemanticHandlerRegistry()
    dependencies = WebResearchHandlerDependencies(
        firecrawl=FakeSearch("firecrawl"),
        tavily=FakeSearch("tavily"),
        browser=FakeBrowser(),
        records=InMemoryWebResearchRecordRepository(),
    )

    register_web_research_stagegraph_handlers(registry, dependencies)
    activities = create_routed_coordinator_activities(
        bindings=InMemoryRunSemanticInputBindingRepository(),
        handlers=registry,
        lifecycle=FakeLifecycle(),  # type: ignore[arg-type]
        goal_directed=GoalDirectedCoordinatorDependencies(
            lane_bindings=LANE_REBINDERS,
            run_control=cast(Any, object()),
            operation_bindings=cast(Any, object()),
            templates=InMemoryGoalOperationTemplateRepository(),
            documents=cast(Any, object()),
            actor=ActorContext(
                actor_id="web-research-test",
                permissions=frozenset({"workflow_run.goal_directed"}),
            ),
        ),
        stagegraph=StageGraphCoordinatorDependencies(
            lane_bindings=LANE_REBINDERS,
            run_control=cast(Any, object()),
            repository=cast(Any, object()),
            operation_bindings=cast(Any, object()),
            templates=cast(Any, object()),
        ),
    )

    exact = next(
        item.handler for item in binding().stage_handlers if item.stage_id == "search_firecrawl"
    )
    assert registry.stage(exact).__class__.__name__ == "ProviderSearchHandler"
    assert activities.stagegraph is not None


def test_handler_ref_change_is_not_silently_routable() -> None:
    registry = SemanticHandlerRegistry()
    exact = next(
        item.handler for item in binding().stage_handlers if item.stage_id == "search_firecrawl"
    )
    changed = exact.model_copy(update={"handler_revision": 2})

    with pytest.raises(SemanticRoutingError, match="unknown semantic handler"):
        registry.stage(changed)


def test_stage_binding_is_immutable_and_schema_bound() -> None:
    frozen = binding()
    item = frozen.stage_handlers[0]

    assert isinstance(item, StageHandlerBinding)
    assert item.handler.input.schema_ref == "schema:web-research-stage-input:v1"
    assert item.handler.input.payload_digest.startswith("sha256:")
    route_refs = {
        route.stage_id: route.handler.operation_execution_binding_ref
        for route in frozen.stage_handlers
    }
    assert route_refs == {
        "admit_public_goal": None,
        "search_firecrawl": ("operation-binding:web-research-test:search_firecrawl"),
        "search_tavily": ("operation-binding:web-research-test:search_tavily"),
        "synthesize_citations": None,
        "browser_verify": ("operation-binding:web-research-test:browser_verify"),
        "promote_verified_result": None,
    }
    assert frozen.workflow_evaluator is not None
    assert frozen.workflow_evaluator.operation_execution_binding_ref is None
    assert frozen.operation_execution_binding_refs == tuple(
        sorted(ref for ref in route_refs.values() if ref is not None)
    )


def test_binding_rejects_unrelated_server_tools_missing_skills_and_browser_grants() -> None:
    firecrawl_ref = exact_ref(
        DefinitionKind.MCP_TOOL,
        "mcp.firecrawl:firecrawl_search",
        "3",
    )
    tavily_ref = exact_ref(
        DefinitionKind.MCP_TOOL,
        "mcp.tavily:tavily_search",
        "4",
    )
    browser_ref = exact_ref(
        DefinitionKind.SKILL,
        "skill.agent-browser",
        "5",
    )
    authority = binding_authority(firecrawl_ref, tavily_ref, browser_ref)
    servers = authority["mcp_servers"]
    assert isinstance(servers, tuple)
    authority["mcp_servers"] = (
        servers[0].model_copy(
            update={"allowed_tools": frozenset({"firecrawl_search", "firecrawl_scrape"})}
        ),
        servers[1],
    )
    with pytest.raises(ValueError, match="search-tool allowlist"):
        build_web_research_run_binding(
            request_scope=SCOPE,
            run_id=RUN_ID,
            goal=WebResearchGoal(question="Research public evidence"),
            firecrawl_tool_ref=firecrawl_ref,
            tavily_tool_ref=tavily_ref,
            browser_skill_ref=browser_ref,
            firecrawl_runtime=FIRECRAWL_RUNTIME,
            tavily_runtime=TAVILY_RUNTIME,
            browser_runtime=BROWSER_RUNTIME,
            effective_configuration_digest=CONFIGURATION_DIGEST,
            blueprint_digest=BLUEPRINT_DIGEST,
            created_at=datetime(2026, 7, 26, tzinfo=UTC),
            **authority,
        )

    authority = binding_authority(firecrawl_ref, tavily_ref, browser_ref)
    skills = authority["skills"]
    assert isinstance(skills, tuple)
    authority["skills"] = skills[:2]
    with pytest.raises(ValueError, match="at least 3 items"):
        build_web_research_run_binding(
            request_scope=SCOPE,
            run_id=RUN_ID,
            goal=WebResearchGoal(question="Research public evidence"),
            firecrawl_tool_ref=firecrawl_ref,
            tavily_tool_ref=tavily_ref,
            browser_skill_ref=browser_ref,
            firecrawl_runtime=FIRECRAWL_RUNTIME,
            tavily_runtime=TAVILY_RUNTIME,
            browser_runtime=BROWSER_RUNTIME,
            effective_configuration_digest=CONFIGURATION_DIGEST,
            blueprint_digest=BLUEPRINT_DIGEST,
            created_at=datetime(2026, 7, 26, tzinfo=UTC),
            **authority,
        )

    authority = binding_authority(firecrawl_ref, tavily_ref, browser_ref)
    grant = authority["browser_grant"]
    assert isinstance(grant, BrowserExecutionGrantBinding)
    authority["browser_grant"] = grant.model_copy(
        update={"capabilities": frozenset({"browser.navigation"})}
    )
    with pytest.raises(ValueError, match="execution authority"):
        build_web_research_run_binding(
            request_scope=SCOPE,
            run_id=RUN_ID,
            goal=WebResearchGoal(question="Research public evidence"),
            firecrawl_tool_ref=firecrawl_ref,
            tavily_tool_ref=tavily_ref,
            browser_skill_ref=browser_ref,
            firecrawl_runtime=FIRECRAWL_RUNTIME,
            tavily_runtime=TAVILY_RUNTIME,
            browser_runtime=BROWSER_RUNTIME,
            effective_configuration_digest=CONFIGURATION_DIGEST,
            blueprint_digest=BLUEPRINT_DIGEST,
            created_at=datetime(2026, 7, 26, tzinfo=UTC),
            **authority,
        )
