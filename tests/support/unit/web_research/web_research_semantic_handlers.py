"""Builders, constants and fakes that other test files import.

Moved from tests/unit/web_research/test_web_research_semantic_handlers.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

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
    BrowserPageVerification,
    ExactOperationExecutionBinding,
    GovernedBrowserVerificationRequest,
    GovernedBrowserVerificationResponse,
    GovernedMCPServerBinding,
    GovernedSearchRequest,
    GovernedSearchResponse,
    NormalizedSearchResult,
    OperationExecutionBindingAuthority,
    ReviewedRuntimeArtifactBinding,
    ReviewedSkillMountBinding,
    WebResearchGoal,
)
from mission_control.application.programs.orchestration_binding_repository import (
    InMemoryRunSemanticInputBindingRepository,
)
from mission_control.application.programs.orchestration_routing import (
    BoundStageOperationExecutor,
    BoundWorkflowEvaluator,
    SemanticHandlerRegistry,
)
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef
from mission_control.domain.programs.contracts import (
    StageCandidateIdentity,
    StageExecutionIdentity,
    StageOperationRequest,
)

CONFIGURATION_DIGEST = "sha256:" + "1" * 64
BLUEPRINT_DIGEST = "sha256:" + "2" * 64
SCOPE = "tenant:web-research-test"
RUN_ID = "web-research-run-1"
OPENAI_SENTINEL = "sk-proj-SENTINEL_OPENAI_KEY_1234567890"

FIRECRAWL_RUNTIME = ReviewedRuntimeArtifactBinding(
    package_name="firecrawl-mcp",
    package_version="3.22.4",
    module_locator="workspace://.tools/reviewed/firecrawl/dist/index.js",
    module_digest="sha256:69e305ec3cf14ddbfe62a7c509e218a9ec4b44c82604bffa023159130769498b",
    tools_snapshot_digest="sha256:b00747ddea6305fc08efcdd9fcaddcd69f62f0c3a59e2901d045475600c53bf2",
)
TAVILY_RUNTIME = ReviewedRuntimeArtifactBinding(
    package_name="tavily-mcp",
    package_version="0.2.21",
    module_locator="workspace://.tools/node_modules/tavily-mcp/build/index.js",
    module_digest="sha256:60d2f3d0553f4879225990fd42e43265244ef5ac6d02799f6bafa5aef2d2d05e",
    tools_snapshot_digest="sha256:65d256e03f0e82bb425b089cecf372f91f4c33b0c32fd2a94421475f2a9c922d",
)
BROWSER_RUNTIME = ReviewedRuntimeArtifactBinding(
    package_name="agent-browser",
    package_version="0.33.0",
    module_locator="workspace://.tools/node_modules/agent-browser/bin/agent-browser.js",
    module_digest="sha256:8e382f4a5ba22f45e1e0339abfe5a55ed95a19540b16a69ee3faf31c8dc8216a",
)


def exact_ref(kind: DefinitionKind, logical_id: str, digit: str) -> ExactDefinitionRef:
    return ExactDefinitionRef(
        kind=kind,
        logical_id=logical_id,
        revision=2,
        digest="sha256:" + digit * 64,
    )


def binding_authority(
    firecrawl_tool_ref: ExactDefinitionRef,
    tavily_tool_ref: ExactDefinitionRef,
    browser_skill_ref: ExactDefinitionRef,
    *,
    configuration_digest: str = CONFIGURATION_DIGEST,
) -> dict[str, object]:
    firecrawl_server = exact_ref(DefinitionKind.MCP_SERVER, "mcp.firecrawl", "6")
    tavily_server = exact_ref(DefinitionKind.MCP_SERVER, "mcp.tavily", "7")
    firecrawl_skill = exact_ref(DefinitionKind.SKILL, "skill.firecrawl-search", "8")
    tavily_skill = exact_ref(DefinitionKind.SKILL, "skill.tavily-search", "9")
    profile = exact_ref(
        DefinitionKind.AGENT_PROFILE,
        "agent-profile.web-research-browser-verification",
        "a",
    )
    runtime = exact_ref(
        DefinitionKind.RUNTIME_PROFILE,
        "web-research-browser-verification-runtime-v1",
        "b",
    )
    workspace = exact_ref(
        DefinitionKind.WORKSPACE_TEMPLATE,
        "web-research-browser-verification-workspace-v1",
        "c",
    )
    return {
        "mcp_servers": (
            GovernedMCPServerBinding(
                server_ref=firecrawl_server,
                tool_ref=firecrawl_tool_ref,
                allowed_tools=frozenset({"firecrawl_search"}),
                server_schema_digest="sha256:" + "d" * 64,
            ),
            GovernedMCPServerBinding(
                server_ref=tavily_server,
                tool_ref=tavily_tool_ref,
                allowed_tools=frozenset({"tavily_search"}),
                server_schema_digest="sha256:" + "e" * 64,
            ),
        ),
        "skills": (
            ReviewedSkillMountBinding(
                skill_ref=firecrawl_skill,
                bundle_ref="belllabs://skills/firecrawl-search",
                bundle_digest="sha256:" + "1" * 64,
                manifest_digest="sha256:" + "2" * 64,
                mount_path="/skills/firecrawl-search/SKILL.md",
            ),
            ReviewedSkillMountBinding(
                skill_ref=tavily_skill,
                bundle_ref="belllabs://skills/tavily-search",
                bundle_digest="sha256:" + "3" * 64,
                manifest_digest="sha256:" + "4" * 64,
                mount_path="/skills/tavily-search/SKILL.md",
            ),
            ReviewedSkillMountBinding(
                skill_ref=browser_skill_ref,
                bundle_ref="belllabs://skills/agent-browser",
                bundle_digest="sha256:" + "5" * 64,
                manifest_digest="sha256:" + "6" * 64,
                mount_path="/skills/agent-browser/SKILL.md",
            ),
        ),
        "browser_grant": BrowserExecutionGrantBinding(
            agent_profile_ref=profile,
            runtime_profile_ref=runtime,
            workspace_template_ref=workspace,
            executable="agent-browser",
            capabilities=frozenset(
                {
                    "browser.process",
                    "browser.navigation",
                    "browser.screenshot",
                    "network.web",
                    "workspace.browser.read",
                    "workspace.browser.write",
                    "artifact.browser-evidence.write",
                }
            ),
            network_hosts=frozenset({"example.com"}),
            workspace_paths=frozenset({"/workspace/browser", "/artifacts/browser-evidence"}),
            grant_digest="sha256:" + "7" * 64,
        ),
        "operation_execution": OperationExecutionBindingAuthority(
            bindings={
                stage_id: ExactOperationExecutionBinding(
                    binding_id=f"operation-binding:web-research-test:{stage_id}",
                    binding_digest="sha256:" + digit * 64,
                )
                for stage_id, digit in (
                    ("search_firecrawl", "8"),
                    ("search_tavily", "9"),
                    ("browser_verify", "a"),
                )
            },
            effective_configuration_digest=configuration_digest,
        ),
    }


class FakeOperationBindingReader:
    def __init__(
        self,
        *,
        request_scope: str,
        run_id: str,
        configuration_digest: str,
    ) -> None:
        self._values = {
            f"operation-binding:web-research-test:{stage_id}": SimpleNamespace(
                binding_id=f"operation-binding:web-research-test:{stage_id}",
                request_scope=request_scope,
                run_id=run_id,
                effective_configuration_digest=configuration_digest,
                operation_id=stage_id,
            )
            for stage_id in (
                "search_firecrawl",
                "search_tavily",
                "browser_verify",
            )
        }

    async def get_binding_by_id(
        self,
        binding_id: str,
        *,
        request_scope: str,
    ) -> object | None:
        binding = self._values.get(binding_id)
        if binding is None or binding.request_scope != request_scope:
            return None
        return binding


class FakeSearch:
    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.requests: list[GovernedSearchRequest] = []

    async def search(self, request: GovernedSearchRequest) -> GovernedSearchResponse:
        self.requests.append(request)
        return GovernedSearchResponse(
            results=(
                NormalizedSearchResult(
                    title=f"{self.provider} result",
                    url=f"https://{self.provider}.example/source?access_token=discard-me",
                    snippet=(f"{self.provider} reports public evidence; api_key={OPENAI_SENTINEL}"),
                ),
            ),
            provider_request_id="provider-secret-request-id",
        )


class FakeBrowser:
    def __init__(self) -> None:
        self.requests: list[GovernedBrowserVerificationRequest] = []

    async def verify(
        self,
        request: GovernedBrowserVerificationRequest,
    ) -> GovernedBrowserVerificationResponse:
        self.requests.append(request)
        return GovernedBrowserVerificationResponse(
            pages=tuple(
                BrowserPageVerification(
                    requested_url=url,
                    final_url=url,
                    status_code=200,
                    title="Verified public page",
                    text_excerpt="Page says Bearer do-not-persist-this-token-value",
                    screenshot_ref=("belllabs://browser-evidence/screenshots/" + str(index)),
                    verified=True,
                )
                for index, url in enumerate(request.urls)
            )
        )


def binding(goal: WebResearchGoal | None = None):
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
    return build_web_research_run_binding(
        request_scope=SCOPE,
        run_id=RUN_ID,
        goal=goal
        or WebResearchGoal(
            question="Find public technologies used by Upgrade Labs",
        ),
        firecrawl_tool_ref=firecrawl_ref,
        tavily_tool_ref=tavily_ref,
        browser_skill_ref=browser_ref,
        firecrawl_runtime=FIRECRAWL_RUNTIME,
        tavily_runtime=TAVILY_RUNTIME,
        browser_runtime=BROWSER_RUNTIME,
        **binding_authority(firecrawl_ref, tavily_ref, browser_ref),
        effective_configuration_digest=CONFIGURATION_DIGEST,
        blueprint_digest=BLUEPRINT_DIGEST,
        created_at=datetime(2026, 7, 26, tzinfo=UTC),
        maximum_results=5,
        browser_verification_limit=2,
    )


def request(
    stage_id: str,
    *,
    input_refs: tuple[str, ...] = (),
    operation_attempt: int = 1,
) -> StageOperationRequest:
    return StageOperationRequest(
        identity=StageExecutionIdentity(
            run_id=RUN_ID,
            execution_epoch=1,
            candidate=StageCandidateIdentity(
                stage_id=stage_id,
                mapped_instance_presence=0,
                mapped_instance_id="NO_MAPPED_INSTANCE",
                workflow_cycle_ordinal=1,
                stage_cycle_ordinal=1,
                operation_slot_id="execute",
            ),
            semantic_attempt=operation_attempt,
        ),
        idempotency_key=f"{RUN_ID}:{stage_id}:cycle-1",
        objective="execute the exact governed web-research stage",
        input_refs=input_refs,
        reservation_id=f"reservation:{stage_id}",
        reservation={"tool.calls.total": 5},
        workspace_namespace="workspace:web-research",
        request_scope=SCOPE,
        semantic_input_binding_ref=binding().binding_id,
        effective_configuration_digest=CONFIGURATION_DIGEST,
        blueprint_digest=BLUEPRINT_DIGEST,
        cycle_evaluation_contract_ref=("evaluation:web-research-browser-verification:v1"),
        cycle_objective_contract_ref="objective:web-research:v1",
    )


async def runtime():
    bindings = InMemoryRunSemanticInputBindingRepository()
    records = InMemoryWebResearchRecordRepository()
    firecrawl = FakeSearch("firecrawl")
    tavily = FakeSearch("tavily")
    browser = FakeBrowser()
    registry = SemanticHandlerRegistry()
    register_web_research_stagegraph_handlers(
        registry,
        WebResearchHandlerDependencies(
            firecrawl=firecrawl,
            tavily=tavily,
            browser=browser,
            records=records,
        ),
    )
    frozen = binding()
    await bindings.create(frozen)
    operation_bindings = FakeOperationBindingReader(
        request_scope=SCOPE,
        run_id=RUN_ID,
        configuration_digest=CONFIGURATION_DIGEST,
    )
    return (
        BoundStageOperationExecutor(bindings, registry, operation_bindings),
        BoundWorkflowEvaluator(bindings, registry, operation_bindings),
        records,
        firecrawl,
        tavily,
        browser,
        frozen,
    )
