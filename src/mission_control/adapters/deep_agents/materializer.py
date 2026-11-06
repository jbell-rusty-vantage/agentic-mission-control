from __future__ import annotations

import asyncio
import copy
import importlib.metadata
import re
import tempfile
import types
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, make_dataclass
from dataclasses import field as dataclass_field
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, ClassVar, cast

from deepagents import DeepAgentState
from deepagents.backends import LangSmithSandbox, StateBackend
from deepagents.backends.protocol import BackendProtocol
from deepagents.backends.utils import create_file_data
from deepagents.middleware.filesystem import FilesystemPermission
from langchain.agents.middleware.types import AgentMiddleware
from langchain.agents.structured_output import ProviderStrategy, ToolStrategy
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from langsmith.sandbox import SandboxClient
from pydantic import SecretStr

from mission_control.adapters.capabilities.capability_bundles import (
    BundleError,
    bundle_digest,
    bytes_digest,
    file_manifest,
    safe_relative_path,
)
from mission_control.adapters.deep_agents.budget import FenceStopMiddleware
from mission_control.adapters.deep_agents.compaction import ObservedSummarizationMiddleware
from mission_control.adapters.deep_agents.features import (
    FeatureBuildContext,
    realize_agent_configuration,
)
from mission_control.adapters.deep_agents.hook_contributions import (
    DeepAgentCandidateWorkspace,
    FenceGrantCheck,
    forget_transfer_plan,
    transfer_plan_for,
)
from mission_control.adapters.deep_agents.hooks import (
    HookContext,
    HookDispatcher,
    HookScriptMiddleware,
    HookScriptRunner,
    KernelHookPorts,
    ResolvedHookScript,
    SubprocessHookScriptRunner,
)
from mission_control.adapters.deep_agents.hooks_callback import callback_url
from mission_control.adapters.deep_agents.output_format import (
    AnthropicOutputSchemaRefused,
    anthropic_output_schema,
)
from mission_control.adapters.deep_agents.structured_response import (
    RequireStructuredResponse,
    response_schema,
    with_auto_tool_choice,
)
from mission_control.application.agentic_components.placement import TOKEN_PATH, write_secret
from mission_control.application.context.hook_contributions import (
    ContributionSession,
    ContributionTarget,
    HookContributionService,
    HookGrants,
    HookReadBroker,
)
from mission_control.application.execution.harness.hook_callbacks import (
    HookCallbackService,
    HookTokenContext,
)
from mission_control.application.frames.sink import harness_execution_id
from mission_control.contracts.hooks import HookCallbackEndpoint, HookScope
from mission_control.contracts.identities import parse_request_scope
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.capabilities.hooks import HookEvent
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.context.contributions import ProtectedPaths
from mission_control.domain.execution.contracts import (
    CognitiveChannelDefinition,
    CognitiveRuntimeContextSchema,
    CognitiveRuntimeField,
    CognitiveStateSchema,
    DeepAgentExecutionBinding,
    DeepAgentMCPServerComponent,
    DeepAgentModelComponent,
    DeepAgentSandboxComponent,
    DeepAgentSkillComponent,
)
from mission_control.domain.execution.errors import (
    DeepAgentMaterializationError,
    DeepAgentRuntimeDrift,
    DeepAgentUnsupportedPlacement,
    OutputSchemaUnsupported,
)
from mission_control.domain.frames.contracts import HarnessExecutionStart

ResolvedSecrets = Mapping[str, str]
# One mounted Skill file as the materialization manifest records it (P3.7): where it went,
# how many bytes, which content.
SkillFileRow = dict[str, Any]
ModelFactory = Callable[[DeepAgentExecutionBinding, ResolvedSecrets], BaseChatModel]
SandboxFactory = Callable[
    [DeepAgentExecutionBinding, ResolvedSecrets],
    AbstractAsyncContextManager[BackendProtocol],
]


@dataclass(frozen=True)
class ResolvedSkillBundle:
    bundle_digest: str
    files: tuple[tuple[str, bytes], ...]
    digest_format: str = "legacy_text_v1"

    def verify(self, *, skill_md_digest: str) -> None:
        try:
            file_manifest(self.files)
        except ValueError as error:
            raise DeepAgentRuntimeDrift(str(error)) from error
        if self.digest_format == "bytes_v1":
            if bundle_digest(self.files) != self.bundle_digest:
                raise DeepAgentRuntimeDrift("Skill bundle manifest drifted from the exact binding")
            if bytes_digest(dict(self.files)["SKILL.md"]) != skill_md_digest:
                raise DeepAgentRuntimeDrift("SKILL.md content drifted from the exact binding")
            return
        if self.digest_format != "legacy_text_v1":
            raise DeepAgentRuntimeDrift("unknown skill bundle digest format")
        normalized: list[dict[str, object]] = []
        skill_md: bytes | None = None
        seen: set[str] = set()
        for raw_path, content in self.files:
            path = PurePosixPath(raw_path.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or str(path) in seen:
                raise DeepAgentRuntimeDrift("Skill bundle contains an unsafe or duplicate path")
            seen.add(str(path))
            normalized.append(
                {
                    "path": str(path),
                    "digest": sha256_digest(content.decode("utf-8")),
                    "size_bytes": len(content),
                }
            )
            if str(path) == "SKILL.md":
                skill_md = content
        if skill_md is None:
            raise DeepAgentRuntimeDrift("exact Skill bundle does not contain SKILL.md")
        if sha256_digest(skill_md.decode("utf-8")) != skill_md_digest:
            raise DeepAgentRuntimeDrift("SKILL.md content drifted from the exact binding")
        if sha256_digest(sorted(normalized, key=lambda item: str(item["path"]))) != (
            self.bundle_digest
        ):
            raise DeepAgentRuntimeDrift("Skill bundle manifest drifted from the exact binding")


@dataclass(frozen=True)
class ResolvedHookScriptBundle:
    """Verified bytes of one catalog hook script directory, keyed by its manifest digest."""

    manifest_digest: str
    files: tuple[tuple[str, bytes], ...]

    def verify(self) -> None:
        try:
            if bundle_digest(self.files, require_skill_md=False) != self.manifest_digest:
                raise DeepAgentRuntimeDrift("Hook script bundle drifted from the exact binding")
        except BundleError as error:
            raise DeepAgentRuntimeDrift(str(error)) from error


@dataclass(frozen=True)
class ExactComponentRegistry:
    """Run-local exact revisions; keys are immutable definition digests, never aliases."""

    model_factories: Mapping[str, ModelFactory]
    prompts: Mapping[str, str] = dataclass_field(default_factory=dict)
    tools: Mapping[str, BaseTool] = dataclass_field(default_factory=dict)
    middleware: Mapping[str, AgentMiddleware[Any, Any, Any]] = dataclass_field(default_factory=dict)
    skill_bundles: Mapping[str, ResolvedSkillBundle] = dataclass_field(default_factory=dict)
    sandbox_factories: Mapping[str, SandboxFactory] = dataclass_field(default_factory=dict)
    checkpointers: Mapping[str, BaseCheckpointSaver[Any]] = dataclass_field(default_factory=dict)
    stores: Mapping[str, BaseStore] = dataclass_field(default_factory=dict)
    structured_output_schemas: Mapping[str, type[Any] | dict[str, Any]] = dataclass_field(
        default_factory=dict
    )
    # FT-A5: catalog hook script bytes (manifest digest -> files), the kernel hook ports and
    # the subprocess runner. Kernel hooks are always composed; the ports default to no-ops.
    hook_scripts: Mapping[str, ResolvedHookScriptBundle] = dataclass_field(default_factory=dict)
    kernel_hooks: KernelHookPorts = dataclass_field(default_factory=KernelHookPorts)
    hook_runner: HookScriptRunner = dataclass_field(default_factory=SubprocessHookScriptRunner)
    # P3.5: the worker's Kernel Hook callback service and its loopback base URL. When both are
    # present and a catalog hook script of the binding declares `callback: service`, `prepare`
    # mints the task token that script uses to write a frame or an intent through the service.
    hook_callbacks: HookCallbackService | None = None
    hook_callback_base_url: str | None = None
    hook_token_ttl: timedelta = timedelta(hours=4)
    # WI-17: the host service that stages and installs hook candidates and admits their
    # operation requests. A binding whose hooks declare reads or a stage grant without it is
    # refused at prepare (no contribution path ever fails open).
    hook_contributions: HookContributionService | None = None
    # Sprint B: where `deep_agents.bash` / `anthropic.bash` host or Docker shell sessions keep
    # their working directory (None: a temporary directory per agent).
    shell_workspace_root: Path | None = None


@dataclass(frozen=True)
class MaterializedDeepAgentArguments:
    model: BaseChatModel
    tools: tuple[BaseTool, ...]
    middleware: tuple[AgentMiddleware[Any, Any, Any], ...]
    subagents: tuple[dict[str, object], ...]
    skills: tuple[str, ...]
    backend: BackendProtocol
    state_schema: type[DeepAgentState]
    context_schema: type[Any]
    context: object
    # None only for a hosted graph, whose checkpointer and store the Agent Server manages.
    checkpointer: BaseCheckpointSaver[Any] | None
    store: BaseStore | None
    initial_state: dict[str, object]
    resolved_attachments: tuple[dict[str, str], ...]
    # W1 D16: the node's output schema wrapped in the strategy its model row declares (never a
    # raw schema, which LangChain would auto-detect into a forced tool choice).
    response_format: ToolStrategy[Any] | ProviderStrategy[Any] | None
    # P3.7: what the materializer knows about the environment it built (Skills mounted, MCP
    # servers connected, the resolved model, every Skill file with its bytes and digest). The
    # adapter records it as the `environment_materialized` frame; stable across prepares of
    # the same binding.
    manifest_facts: dict[str, Any] = dataclass_field(default_factory=dict)
    # Sprint B: provider-executed dict tools (OpenAI Responses built-ins, Anthropic server
    # tools) bound beside `tools`; `create_deep_agent` keeps them out of the tool node.
    provider_tools: tuple[dict[str, Any], ...] = ()


def response_format_for(
    schema: type[Any] | dict[str, Any], model: DeepAgentModelComponent
) -> ToolStrategy[Any] | ProviderStrategy[Any]:
    """W1 D16: the structured-response strategy the model's catalog row declares.

    ``tool_forced`` binds the schema as a tool the model must call (LangChain ``ToolStrategy``:
    ``tool_choice`` any); ``provider_native`` asks the vendor's own response-format constraint
    (``ProviderStrategy``: Anthropic ``output_config.format``, OpenAI ``response_format``) with
    ``tool_choice`` auto. A model without a declared strategy binds no structured response
    (fail closed): framework auto-detection forced tool choice on Claude Sonnet 5.5, which
    the API refuses with a 400.
    """

    if model.structured_output in ("tool_forced", "tool_auto"):
        # `tool_auto` binds the same tool with tool choice auto (`prepare` wraps the client and
        # adds the host enforcement, `structured_response.py`); no grammar is compiled. Both
        # parse a JSON string given for an object-typed field once (W1 D17 rules).
        return ToolStrategy(response_schema(schema))
    if model.structured_output == "provider_native":
        if model.provider == "anthropic":
            # The exact schema langchain-anthropic sends must be in Anthropic's supported
            # subset; refuse before any model call instead of a provider 400.
            try:
                anthropic_output_schema(schema)
            except AnthropicOutputSchemaRefused as refused:
                raise OutputSchemaUnsupported(
                    f"the output schema cannot bind provider_native on {model.model_name}: "
                    f"{refused}"
                ) from None
        return ProviderStrategy(schema)
    raise OutputSchemaUnsupported(
        f"model {model.model_name} declares no structured_output strategy; a node output "
        "schema cannot bind (declare tool_forced or provider_native in models.toml)"
    )


class StateSandboxFactory:
    def __call__(
        self,
        binding: DeepAgentExecutionBinding,
        _secrets: ResolvedSecrets,
    ) -> AbstractAsyncContextManager[BackendProtocol]:
        component = binding.sandbox
        if component.backend != "state":
            raise DeepAgentUnsupportedPlacement("state backend factory cannot change placement")

        @asynccontextmanager
        async def context() -> AsyncIterator[BackendProtocol]:
            yield StateBackend()

        return context()


class OpenAIExactModelFactory:
    """Construct ChatOpenAI only from an exact component and resolved credential ref."""

    _allowed_settings: ClassVar[set[str]] = {
        "reasoning_effort",
        "verbosity",
        "max_completion_tokens",
        "temperature",
        "service_tier",
        "use_responses_api",
        # A hosted graph is streamed by the Agent Server; usage reaches the persisted message
        # only when the client streams usage (REQ-CP-DA-011 provider-attributed usage).
        "stream_usage",
        # Tracing Stage 2: a streamed parent emits `messages`-mode chunks, which the frame
        # recorder coalesces into the delta retention class (`message_delta`).
        "streaming",
        # Sprint B: `openai.compaction` (server-side compaction) is a model setting.
        "context_management",
    }

    def __init__(self, *, secret_key: str = "environment:OPENAI_API_KEY") -> None:
        self._secret_key = secret_key

    def __call__(
        self,
        binding: DeepAgentExecutionBinding,
        secrets: ResolvedSecrets,
    ) -> BaseChatModel:
        unsupported = set(binding.model.settings) - self._allowed_settings
        if unsupported:
            raise DeepAgentMaterializationError(
                "unsupported exact OpenAI model settings: " + ", ".join(sorted(unsupported))
            )
        try:
            api_key = secrets[self._secret_key]
        except KeyError as error:
            raise DeepAgentMaterializationError(
                "OpenAI model credential reference was not resolved"
            ) from error
        return ChatOpenAI(
            model=binding.model.model_name,
            api_key=SecretStr(api_key),
            max_retries=0,
            **binding.model.settings,
        )


class AnthropicExactModelFactory:
    """Construct ChatAnthropic only from an exact component and resolved credential ref.

    The neutral manifest settings the launch author emits are OpenAI-shaped
    (`max_completion_tokens`, `reasoning_effort` with `minimal`); this factory translates
    them to the Anthropic constructor (`max_tokens`, `reasoning_effort` without `minimal`)
    and refuses what has no Anthropic meaning (`verbosity`, `service_tier`,
    `use_responses_api`) instead of dropping it. `thinking` is left to the model's default
    (adaptive on the 4.6+ family); `reasoning_effort` is the depth control.
    """

    _allowed_settings: ClassVar[set[str]] = {
        "max_tokens",
        "max_completion_tokens",
        "reasoning_effort",
        "thinking",
        "output_config",
        "temperature",
        "streaming",
        "stream_usage",
        "betas",
        # Sprint B: `anthropic.clear_tool_uses` and `anthropic.compaction` are model settings.
        "context_management",
    }
    # Anthropic output cap when the mission names none; ChatAnthropic's own default is lower
    # than an agent turn with tool calls needs.
    default_max_tokens: ClassVar[int] = 8_192

    def __init__(self, *, secret_key: str = "environment:ANTHROPIC_API_KEY") -> None:
        self._secret_key = secret_key

    def __call__(
        self,
        binding: DeepAgentExecutionBinding,
        secrets: ResolvedSecrets,
    ) -> BaseChatModel:
        settings = dict(binding.model.settings)
        unsupported = set(settings) - self._allowed_settings
        if unsupported:
            raise DeepAgentMaterializationError(
                "unsupported exact Anthropic model settings: " + ", ".join(sorted(unsupported))
            )
        if "max_completion_tokens" in settings:
            if "max_tokens" in settings:
                raise DeepAgentMaterializationError(
                    "Anthropic model settings name both max_tokens and max_completion_tokens"
                )
            settings["max_tokens"] = settings.pop("max_completion_tokens")
        settings.setdefault("max_tokens", self.default_max_tokens)
        if settings.get("reasoning_effort") == "minimal":
            settings["reasoning_effort"] = "low"
        try:
            api_key = secrets[self._secret_key]
        except KeyError as error:
            raise DeepAgentMaterializationError(
                "Anthropic model credential reference was not resolved"
            ) from error
        return ChatAnthropic(
            model_name=binding.model.model_name,
            api_key=SecretStr(api_key),
            max_retries=0,
            **settings,
        )


MODEL_FACTORIES: Mapping[str, Callable[[], ModelFactory]] = {
    "openai": OpenAIExactModelFactory,
    "anthropic": AnthropicExactModelFactory,
}


def model_factory_for(provider: str) -> ModelFactory:
    """The exact factory of a model provider (`DeepAgentModelComponent.provider`)."""

    try:
        return MODEL_FACTORIES[provider]()
    except KeyError as error:
        raise DeepAgentMaterializationError(
            f"no exact model factory for provider {provider!r}; known: "
            + ", ".join(sorted(MODEL_FACTORIES))
        ) from error


class ExactModelFactory:
    """The factory a served model definition is registered under (OC-R6).

    The vendor and model id are the sealed binding's (`binding.model.provider` and
    `model_name`), which the launch compiled from the resolved Model Catalog pin. A pinned
    definition registers with the vendor and model id its capability pin declares, which are
    compared, never trusted over the binding: a binding sealed for another vendor or model id
    is a materialization error (`MODEL_PIN_VENDOR_MISMATCH`, `MODEL_PIN_MODEL_MISMATCH`), as at
    composition and preflight.
    """

    def __init__(
        self, served_vendor: str | None = None, served_model_id: str | None = None
    ) -> None:
        self._served_vendor = served_vendor
        self._served_model_id = served_model_id

    def __call__(
        self,
        binding: DeepAgentExecutionBinding,
        secrets: ResolvedSecrets,
    ) -> BaseChatModel:
        vendor = binding.model.provider
        if self._served_vendor is not None and self._served_vendor != vendor:
            raise DeepAgentMaterializationError(
                f"MODEL_PIN_VENDOR_MISMATCH: the binding calls a {vendor} model on served "
                f"definition {binding.model.ref.logical_id}, pinned as {self._served_vendor}"
            )
        check_served_model_id(binding, self._served_model_id)
        return model_factory_for(vendor)(binding, secrets)


def check_served_model_id(binding: DeepAgentExecutionBinding, served_model_id: str | None) -> None:
    if served_model_id is not None and served_model_id != binding.model.model_name:
        raise DeepAgentMaterializationError(
            f"MODEL_PIN_MODEL_MISMATCH: the binding calls {binding.model.model_name} on served "
            f"definition {binding.model.ref.logical_id}, pinned as {served_model_id}"
        )


class IdentityCheckedModelFactory:
    """A registered (non-pin) model factory behind the identity it declares (OC-R6)."""

    def __init__(self, factory: ModelFactory, *, vendor: str, model_id: str) -> None:
        self._factory = factory
        self._vendor = vendor
        self._model_id = model_id

    def __call__(
        self,
        binding: DeepAgentExecutionBinding,
        secrets: ResolvedSecrets,
    ) -> BaseChatModel:
        if binding.model.provider != self._vendor:
            raise DeepAgentMaterializationError(
                f"MODEL_PIN_VENDOR_MISMATCH: the binding calls a {binding.model.provider} model "
                f"on a component registered as {self._vendor}"
            )
        check_served_model_id(binding, self._model_id)
        return self._factory(binding, secrets)


class LangSmithSandboxFactory:
    def __call__(
        self,
        binding: DeepAgentExecutionBinding,
        secrets: ResolvedSecrets,
    ) -> AbstractAsyncContextManager[BackendProtocol]:
        component = binding.sandbox
        if component.backend != "langsmith":
            raise DeepAgentUnsupportedPlacement("LangSmith factory cannot change placement")
        api_key = _single_secret(component, secrets)

        @asynccontextmanager
        async def context() -> AsyncIterator[BackendProtocol]:
            client = SandboxClient(api_key=api_key)
            sandbox = await asyncio.to_thread(
                client.create_sandbox,
                snapshot_name=component.snapshot_ref,
                idle_ttl_seconds=component.idle_ttl_seconds,
            )
            backend = LangSmithSandbox(sandbox=sandbox)
            try:
                yield backend
            finally:
                await backend.aclose()
                await asyncio.to_thread(client.delete_sandbox, sandbox.name)

        return context()


class ExactDeepAgentMaterializer:
    """Resolves a frozen binding to framework inputs and owns provider lifecycles."""

    def __init__(self, registry: ExactComponentRegistry) -> None:
        self._registry = registry

    @asynccontextmanager
    async def prepare(
        self,
        binding: DeepAgentExecutionBinding,
        secrets: ResolvedSecrets,
        *,
        output_schema_digest: str | None = None,
        hosted: bool = False,
    ) -> AsyncIterator[MaterializedDeepAgentArguments]:
        """Resolve the exact binding; `hosted` materializes a graph an Agent Server serves.

        REQ-CP-DA-019: a hosted binding has a remote placement whose checkpointer and store the
        Agent Server manages, so no local checkpointer or store is resolved for it. Everything
        else (model, tools, Skills, MCP, middleware, schemas) is resolved exactly as for a
        local-in-worker invocation.
        """

        self._verify_runtime(binding, hosted=hosted)
        async with AsyncExitStack() as stack:
            backend_factory = _exact(
                self._registry.sandbox_factories,
                binding.sandbox.ref.digest,
                "sandbox",
            )
            backend = await stack.enter_async_context(backend_factory(binding, secrets))
            # WI-17: the sealed plan delivered to this backend is forgotten with the attempt.
            stack.callback(forget_transfer_plan, backend)
            # Sprint B: the sealed lane features and model tools. Model-setting rows are
            # merged into the exact model component before the factory constructs the
            # client; middleware rows join the stack after Mission Control's own; provider
            # tools are bound beside the agent's tools.
            realized = realize_agent_configuration(
                binding.agent_configuration,
                FeatureBuildContext(
                    backend=backend,
                    model_provider=binding.model.provider,
                    secrets=secrets,
                    shell_workspace_root=self._registry.shell_workspace_root,
                ),
            )
            model_factory = _exact(
                self._registry.model_factories,
                binding.model.ref.digest,
                "model",
            )
            model = model_factory(_with_model_settings(binding, realized.model_settings), secrets)
            skill_sources, state_skill_files, skill_files = await self._mount_skills(
                binding.skills, backend
            )
            tools = [
                self._resolve_tool(item.ref.digest, item.schema_digest, item.tool_name)
                for item in binding.tools
            ]
            mcp_tools = await self._load_mcp_tools(binding.mcp_servers, secrets)
            tools.extend(mcp_tools)
            catalog_middleware = tuple(
                _exact(self._registry.middleware, item.ref.digest, "middleware")
                for item in binding.middleware
            )
            dispatcher = await self._hook_dispatcher(binding, stack, backend)
            # Mission Control's hook middleware (kernel hooks first, then catalog hooks) and
            # the compaction wrapper lead every attempt; no binding field can remove them.
            # P1-S2: a node-level summarization trigger from `provider_options.deep_agents`
            # overrides the worker default; everything else about compaction is unchanged.
            summarization_trigger, summarization_keep = _summarization_overrides(binding)
            ports = self._registry.kernel_hooks
            hook_context = dispatcher.context
            middleware = (
                # Tracing Stage 2 (F-S2-9): a fenced run calls the model no more.
                FenceStopMiddleware(lambda: ports.stop_fence.run_fenced(hook_context)),
                HookScriptMiddleware(
                    dispatcher, mcp_tools=frozenset(tool.name for tool in mcp_tools)
                ),
                ObservedSummarizationMiddleware.observed(
                    model,
                    backend,
                    dispatcher,
                    trigger=summarization_trigger,
                    keep=summarization_keep,
                ),
                *catalog_middleware,
                *realized.middleware,
            )
            # P1 subagents: children get the parent's loaded tools (narrowed or whole) plus
            # their own seeded MCP tools and Skill roots, mounted beside the parent's.
            subagents, child_skill_files, child_files = await self._materialize_subagents(
                binding,
                secrets,
                skill_sources,
                backend,
                mcp_tools=mcp_tools,
                parent_tools=tuple(tools),
            )
            state_skill_files = {**state_skill_files, **child_skill_files}
            skill_files = (*skill_files, *child_files)
            # A hosted graph's checkpointer and store are the Agent Server's (REQ-CP-DA-019).
            checkpointer: BaseCheckpointSaver[Any] | None = (
                None
                if hosted
                else _exact(
                    self._registry.checkpointers,
                    binding.checkpointer_ref.digest,
                    "checkpointer",
                )
            )
            store: BaseStore | None = (
                None if hosted else _exact(self._registry.stores, binding.store_ref.digest, "store")
            )
            state_schema = _state_type(binding.cognitive_state_schema)
            # A hosted graph is invoked by the Agent Server without a runtime context, so its
            # frozen context values become the dataclass defaults (exact: they are part of
            # the binding digest). Local cognition passes the instance explicitly.
            context_schema = _context_type(
                binding.cognitive_context_schema,
                defaults=binding.cognitive_context_values if hosted else None,
            )
            context = _context_instance(
                context_schema,
                binding.cognitive_context_schema,
                binding.cognitive_context_values,
            )
            initial_state: dict[str, object] = {
                "artifact_index": dict(binding.initial_artifact_index),
                "context_manifest": dict(binding.initial_context_manifest),
                "child_result_index": list(binding.initial_child_result_index),
            }
            if state_skill_files:
                initial_state["files"] = state_skill_files
            schema = (
                _exact(
                    self._registry.structured_output_schemas,
                    output_schema_digest,
                    "structured output schema",
                )
                if output_schema_digest is not None
                and output_schema_digest in self._registry.structured_output_schemas
                else None
            )
            response_format = None if schema is None else response_format_for(schema, binding.model)
            if (
                isinstance(response_format, ToolStrategy)
                and binding.model.structured_output == "tool_auto"
            ):
                # W1 D18: never force the response tool; the host requires exactly one call.
                model = with_auto_tool_choice(model)
                middleware = (
                    *middleware,
                    RequireStructuredResponse([spec.name for spec in response_format.schema_specs]),
                )
            yield MaterializedDeepAgentArguments(
                model=model,
                tools=tuple(tools),
                middleware=middleware,
                subagents=subagents,
                skills=skill_sources,
                backend=backend,
                state_schema=state_schema,
                context_schema=context_schema,
                context=context,
                checkpointer=checkpointer,
                store=store,
                initial_state=initial_state,
                resolved_attachments=tuple(
                    item.model_copy(update={"status": "resolved"}).model_dump(mode="json")
                    for item in binding.intended_attachments
                ),
                response_format=response_format,
                manifest_facts=_manifest_facts(binding, skill_files),
                provider_tools=realized.provider_tools,
            )

    async def _hook_dispatcher(
        self,
        binding: DeepAgentExecutionBinding,
        stack: AsyncExitStack,
        backend: BackendProtocol | None = None,
    ) -> HookDispatcher:
        """The attempt's hook dispatcher: kernel ports from the registry, the catalog scripts
        verified onto a private root, and the `HookContext` every script reads (P3.5): the
        cognitive namespace as the native session, the scripts' root as the workspace, and
        the callback endpoint minted through the worker's service when a script declares it."""

        scripts: list[ResolvedHookScript] = []
        root: Path | None = None
        for component in sorted(binding.hook_scripts, key=lambda item: item.order):
            bundle = _exact(self._registry.hook_scripts, component.manifest_digest, "hook script")
            if bundle.manifest_digest != component.manifest_digest:
                raise DeepAgentRuntimeDrift("resolved hook script identity drift")
            bundle.verify()
            if root is None:
                root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="mc-hooks-")))
            directory = root / re.sub(r"[^a-z0-9._-]", "-", component.hook_id)
            for relative, content in bundle.files:
                target = directory / safe_relative_path(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            entrypoint = directory / safe_relative_path(component.entrypoint)
            if not entrypoint.is_file():
                raise DeepAgentRuntimeDrift("hook script entrypoint is not in its bundle")
            scripts.append(
                ResolvedHookScript(
                    hook_id=component.hook_id,
                    events=frozenset(HookEvent(event) for event in component.events),
                    interpreter=component.interpreter,
                    entrypoint=entrypoint,
                    timeout_seconds=component.timeout_seconds,
                    fail_closed=component.fail_closed,
                    matcher=component.matcher,
                    callback=component.callback == "service",
                )
            )
        ports = self._registry.kernel_hooks
        unit = binding.runtime_unit
        # The same deterministic execution identity the frame recorder opens, so the persisted
        # ports (intents, fence admissions) and the callback's frames join this attempt.
        execution_id = (
            str(
                harness_execution_id(
                    request_scope=unit.request_scope,
                    run_key=unit.belllabs_run_id,
                    activation_key=unit.unit_key,
                    attempt_no=binding.execution_generation,
                    lane=LaneProfile.DEEP_AGENTS.value,
                )
            )
            if unit is not None
            else binding.binding_id
        )
        callback = (
            await self._mint_hook_callback(binding, root, execution_id)
            if root is not None and any(script.callback for script in scripts)
            else None
        )
        context = HookContext(
            scope=_hook_scope(binding),
            lane_profile=LaneProfile.DEEP_AGENTS,
            run_id=binding.run_id,
            activation_id=binding.operation_id,
            attempt_no=binding.operation_attempt,
            generation=binding.execution_generation,
            harness_execution_id=execution_id,
            native_session_ref=binding.cognitive_session_namespace,
            workspace_root=None if root is None else str(root),
            callback=callback,
        )
        session, workspace = self._contribution_session(binding, stack, backend, context)
        dispatcher = HookDispatcher(
            context=context,
            kernel_hooks=ports.build(LaneProfile.DEEP_AGENTS),
            scripts=tuple(scripts),
            runner=self._registry.hook_runner,
            frames=ports.frames,
            cwd=root,
            contributions=session,
            workspace=workspace,
        )
        if session is not None:
            # WI-17: however the attempt ends (an error, a cancel, the recursion limit, a final
            # answer without STOP), still-staged candidates are refused visibly at teardown;
            # idempotent with the final-answer close.
            stack.callback(dispatcher.close_contributions)
        return dispatcher

    def _contribution_session(
        self,
        binding: DeepAgentExecutionBinding,
        stack: AsyncExitStack,
        backend: BackendProtocol | None,
        context: HookContext,
    ) -> tuple[ContributionSession | None, DeepAgentCandidateWorkspace | None]:
        """WI-17: the attempt's contribution session when a hook declares host reads or a
        stage grant: reads and installs go through the agent's own backend; the stop fence is
        the current authority; sealed inputs, host state, output slots and seeded mounts are
        protected."""

        grants = {
            component.hook_id: HookGrants(reads=component.host_reads, stage=component.stage)
            for component in binding.hook_scripts
            if component.host_reads or component.stage is not None
        }
        if not grants:
            return None, None
        service = self._registry.hook_contributions
        unit = binding.runtime_unit
        if service is None or backend is None or unit is None:
            raise DeepAgentMaterializationError(
                "hook scripts declare host reads or a stage grant but no contribution service, "
                "backend or runtime unit is composed"
            )
        ports = self._registry.kernel_hooks
        session = ContributionSession(
            service=service,
            target=ContributionTarget(
                scope=unit.request_scope,
                run_id=binding.run_id,
                operation_ref=binding.operation_id,
                attempt=binding.operation_attempt,
                generation=binding.execution_generation,
            ),
            grants=grants,
            protected=protected_paths(binding),
            broker=HookReadBroker(plan=lambda: transfer_plan_for(backend)),
            current=FenceGrantCheck(lambda: ports.stop_fence.run_fenced(context)),
        )
        return session, DeepAgentCandidateWorkspace(backend)

    async def _mint_hook_callback(
        self, binding: DeepAgentExecutionBinding, root: Path, execution_id: str
    ) -> HookCallbackEndpoint | None:
        """Mint the task token for this attempt the way the command-hook lanes do
        (`HookCallbackService.issue`), write it under the scripts' root (mode 0600) and
        return the endpoint the scripts read on stdin. None when the worker serves no
        callback or the binding has no runtime unit to bind the token to."""

        service = self._registry.hook_callbacks
        base_url = self._registry.hook_callback_base_url
        unit = binding.runtime_unit
        if service is None or base_url is None or unit is None:
            return None
        lane = LaneProfile.DEEP_AGENTS
        context = HookTokenContext(
            request_scope=unit.request_scope,
            run_id=binding.run_id,
            attempt_no=binding.operation_attempt,
            generation=binding.execution_generation,
            harness_execution_id=execution_id,
            lane_profile=lane.value,
            execution_start=HarnessExecutionStart(
                harness_execution_id=execution_id,
                request_scope=unit.request_scope,
                run_key=unit.belllabs_run_id,
                activation_key=unit.unit_key,
                attempt_no=binding.execution_generation,
                generation=binding.execution_generation,
                lane_profile=lane,
                native_session_ref=cast(str, binding.cognitive_session_namespace),
                runtime_kind="deep_agent",
                provider_kind="langgraph",
                placement_kind=binding.placement,
                intended_binding_digest=binding.binding_digest,
                native_identity={
                    "operation_id": binding.operation_id,
                    "binding_id": binding.binding_id,
                },
            ),
            workspace_root=str(root),
        )
        token = await service.issue(context, ttl=self._registry.hook_token_ttl)
        await asyncio.to_thread(write_secret, root, TOKEN_PATH, token)
        return HookCallbackEndpoint(
            url=callback_url(base_url, unit.request_scope),
            token_path=str(root.joinpath(*PurePosixPath(TOKEN_PATH).parts)),
        )

    async def _materialize_subagents(
        self,
        binding: DeepAgentExecutionBinding,
        secrets: ResolvedSecrets,
        skill_sources: tuple[str, ...],
        backend: BackendProtocol,
        *,
        mcp_tools: Sequence[BaseTool] = (),
        parent_tools: Sequence[BaseTool] = (),
    ) -> tuple[tuple[dict[str, object], ...], dict[str, object], tuple[SkillFileRow, ...]]:
        """Sync children as `SubAgent` dicts in the two child shapes the binding sealed.

        An inheriting child (`inherits_parent`) receives every parent tool and MCP tool and
        every parent Skill root: the explicit, receipted form of the framework's
        `general-purpose` child. A seeded child receives the parent components it narrowed
        (tools, Skills, MCP servers by exact ref) plus its own `seeded_*` components: its MCP
        servers are connected here for the child alone, and its Skill bundles are mounted
        beside the parent's. A child's prompt is the inline text the binding carries
        (digest-checked by the contract) or the registry prompt under the pinned digest.

        Returns the specs, the state-backend files the children's Skills added and the
        manifest rows of every seeded Skill file.
        """

        tools_by_ref = {item.ref: item for item in binding.tools}
        skills_by_ref = {item.ref: item for item in binding.skills}
        mcp_by_ref = {item.ref: item for item in binding.mcp_servers}
        mcp_tools_by_name = {tool.name: tool for tool in mcp_tools}
        result: list[dict[str, object]] = []
        state_files: dict[str, object] = {}
        seeded_rows: list[SkillFileRow] = []
        for child in binding.sync_subagents:
            model_factory = _exact(
                self._registry.model_factories,
                child.model.ref.digest,
                "subagent model",
            )
            child_binding = binding.model_copy(update={"model": child.model})
            child_tools: list[BaseTool]
            child_skill_roots: set[str]
            if child.inherits_parent:
                child_tools = [*parent_tools, *mcp_tools]
                child_skill_roots = set(skill_sources)
            else:
                child_tools = [
                    self._resolve_tool(
                        tools_by_ref[ref].ref.digest,
                        tools_by_ref[ref].schema_digest,
                        tools_by_ref[ref].tool_name,
                    )
                    for ref in child.tool_refs
                ]
                for ref in child.mcp_server_refs:
                    server = mcp_by_ref.get(ref)
                    if server is None:
                        raise DeepAgentRuntimeDrift(
                            "subagent MCP server is not bound on the parent"
                        )
                    for expected in server.tools:
                        loaded = mcp_tools_by_name.get(expected.tool_name)
                        if loaded is None:
                            raise DeepAgentRuntimeDrift("subagent MCP tool was not loaded")
                        child_tools.append(loaded)
                child_tools.extend(
                    self._resolve_tool(item.ref.digest, item.schema_digest, item.tool_name)
                    for item in child.seeded_tools
                )
                child_tools.extend(await self._load_mcp_tools(child.seeded_mcp_servers, secrets))
                child_skill_roots = {
                    str(PurePosixPath(skills_by_ref[ref].mount_root).parent)
                    for ref in child.skill_refs
                }
                if not child_skill_roots <= set(skill_sources):
                    raise DeepAgentRuntimeDrift("subagent Skill projection is unavailable")
                if child.seeded_skills:
                    seeded_sources, seeded_files, seeded_file_rows = await self._mount_skills(
                        child.seeded_skills, backend, already_mounted=binding.skills
                    )
                    child_skill_roots.update(seeded_sources)
                    state_files.update(seeded_files)
                    seeded_rows.extend(seeded_file_rows)
            system_prompt = (
                child.system_prompt
                if child.system_prompt is not None
                else _exact(
                    self._registry.prompts,
                    child.system_prompt_ref.digest,
                    "subagent prompt",
                )
            )
            result.append(
                {
                    "name": child.name,
                    "description": child.description,
                    "system_prompt": system_prompt,
                    "model": model_factory(child_binding, secrets),
                    "tools": child_tools,
                    "skills": sorted(child_skill_roots),
                    # deepagents 0.7.5 reads typed rules (`rule.mode`); a plain mapping
                    # fails `create_deep_agent` for every sync subagent (RRM-009).
                    "permissions": [
                        FilesystemPermission(
                            operations=["read", "write"],
                            paths=list(child.writable_paths),
                            mode="allow",
                        ),
                        FilesystemPermission(
                            operations=["read", "write"], paths=["/"], mode="deny"
                        ),
                    ],
                }
            )
        return tuple(result), state_files, tuple(seeded_rows)

    @staticmethod
    def _verify_runtime(binding: DeepAgentExecutionBinding, *, hosted: bool = False) -> None:
        if binding.silent_fallback:
            raise DeepAgentUnsupportedPlacement("silent Deep Agent fallback is forbidden")
        if hosted:
            if (
                binding.placement != "remote_langsmith_deployment"
                or binding.checkpoint_behavior != "remote_managed"
            ):
                raise DeepAgentUnsupportedPlacement(
                    "a hosted async subagent graph requires a remote-managed placement"
                )
        elif binding.placement != "local_in_worker":
            raise DeepAgentUnsupportedPlacement(
                "this adapter materializes only local-in-worker Deep Agent placement"
            )
        for package, expected in binding.package_versions.items():
            try:
                actual = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError as error:
                raise DeepAgentRuntimeDrift(
                    f"required runtime package is absent: {package}"
                ) from error
            if actual != expected:
                raise DeepAgentRuntimeDrift(
                    f"runtime package drift for {package}: expected {expected}, observed {actual}"
                )
        if binding.cognitive_state_schema.deepagents_version != "0.7.5":
            raise DeepAgentRuntimeDrift("cognitive schema baseline is not Deep Agents 0.7.5")

    async def _mount_skills(
        self,
        components: Sequence[DeepAgentSkillComponent],
        backend: BackendProtocol,
        *,
        already_mounted: Sequence[DeepAgentSkillComponent] = (),
    ) -> tuple[tuple[str, ...], dict[str, object], tuple[SkillFileRow, ...]]:
        """Mount exact Skill bundles below `/skills/` and return their source roots, the
        state-backend files, and one manifest row per mounted file (path, bytes, digest and
        its destination: the `files` state channel or a sandbox upload).

        `already_mounted` names bundles another call put on this backend (the parent's, when
        a child seeds the same Skill): their root is returned, nothing is uploaded twice.
        """

        uploads: list[tuple[str, bytes]] = []
        sources: set[str] = set()
        mounted = {item.mount_root for item in already_mounted}
        for component in components:
            if component.mount_root in mounted:
                sources.add(str(PurePosixPath(component.mount_root).parent))
                continue
            bundle = _exact(
                self._registry.skill_bundles,
                component.bundle_digest,
                "Skill bundle",
            )
            if bundle.bundle_digest != component.bundle_digest:
                raise DeepAgentRuntimeDrift("resolved Skill bundle identity drift")
            bundle.verify(skill_md_digest=component.skill_md_digest)
            try:
                if not component.mount_root.startswith("/skills/"):
                    raise BundleError("skills must mount below /skills")
                safe_relative_path(component.mount_root[1:])
            except BundleError as error:
                raise DeepAgentRuntimeDrift(str(error)) from error
            root = PurePosixPath(component.mount_root)
            sources.add(str(root.parent))
            uploads.extend((str(root / path), content) for path, content in bundle.files)
        mounted_paths = [path.casefold() for path, _ in uploads]
        if len(mounted_paths) != len(set(mounted_paths)):
            raise DeepAgentRuntimeDrift("Skill bundle mount paths overlap")
        state_files: dict[str, object] = {}
        destination = "state_channel" if isinstance(backend, StateBackend) else "sandbox_upload"
        if isinstance(backend, StateBackend):
            try:
                state_files = {
                    path: create_file_data(content.decode("utf-8")) for path, content in uploads
                }
            except UnicodeDecodeError as error:
                raise DeepAgentUnsupportedPlacement(
                    "binary skill bundles require a byte-capable sandbox backend"
                ) from error
        elif uploads:
            responses = await backend.aupload_files(uploads)
            failures = [item for item in responses if item.error]
            if failures:
                raise DeepAgentMaterializationError("exact Skill bundle failed sandbox attachment")
        rows = tuple(
            {
                "path": path,
                "bytes": len(content),
                "digest": bytes_digest(content),
                "destination": destination,
            }
            for path, content in uploads
        )
        return tuple(sorted(sources)), state_files, rows

    def _resolve_tool(self, digest: str, schema_digest: str, name: str) -> BaseTool:
        tool = _exact(self._registry.tools, digest, "tool")
        if tool.name != name:
            raise DeepAgentRuntimeDrift("resolved tool name drift")
        observed = _tool_schema_digest(tool)
        if observed != schema_digest:
            raise DeepAgentRuntimeDrift("resolved tool schema drift")
        return tool

    async def _load_mcp_tools(
        self,
        servers: tuple[DeepAgentMCPServerComponent, ...],
        secrets: ResolvedSecrets,
    ) -> tuple[BaseTool, ...]:
        if not servers:
            return ()
        connections: dict[str, dict[str, object]] = {}
        expected = {}
        for server in servers:
            if server.transport == "stdio":
                environment = {
                    ref.key: _secret_value(ref.provider, ref.key, secrets)
                    for ref in server.credential_refs
                }
                connections[server.server_name] = {
                    "transport": "stdio",
                    "command": cast(str, server.command),
                    "args": list(server.arguments),
                    "env": environment or None,
                }
            else:
                headers = {}
                if server.credential_refs:
                    headers["Authorization"] = "Bearer " + _secret_value(
                        server.credential_refs[0].provider,
                        server.credential_refs[0].key,
                        secrets,
                    )
                connections[server.server_name] = {
                    "transport": server.transport,
                    "url": cast(str, server.endpoint),
                    "headers": headers or None,
                }
            for expected_tool in server.tools:
                if expected_tool.tool_name in expected:
                    raise DeepAgentMaterializationError("MCP tool namespace collision")
                expected[expected_tool.tool_name] = expected_tool.schema_digest
        # langchain-mcp-adapters 0.3.1 deliberately rejects client-level async
        # context management. get_tools() returns tools that open scoped sessions.
        client = MultiServerMCPClient(cast(Any, connections))
        tools = await client.get_tools()
        observed_names = {tool.name for tool in tools}
        if observed_names != set(expected):
            raise DeepAgentRuntimeDrift("MCP server tool filter drift")
        for loaded_tool in tools:
            observed = _tool_schema_digest(loaded_tool)
            if observed != expected[loaded_tool.name]:
                raise DeepAgentRuntimeDrift(f"MCP tool schema drift: {loaded_tool.name}")
        return tuple(tools)


def _summarization_overrides(
    binding: DeepAgentExecutionBinding,
) -> tuple[tuple[str, int] | None, tuple[str, int] | None]:
    """`provider_options.deep_agents.summarization` (or the `summarization` lane feature)
    as the middleware's trigger and keep."""

    options = binding.provider_options
    policy = options.effective_summarization if options is not None else None
    if policy is None:
        return None, None
    trigger: tuple[str, int] = (
        ("messages", policy.trigger_messages)
        if policy.trigger_messages is not None
        else ("tokens", cast(int, policy.trigger_tokens))
    )
    return trigger, ("messages", policy.keep_messages)


def _with_model_settings(
    binding: DeepAgentExecutionBinding, settings: Mapping[str, Any]
) -> DeepAgentExecutionBinding:
    """The binding whose exact model component also carries the feature-derived settings
    (a run-local view for the factory; the sealed binding and its digest are unchanged)."""

    if not settings:
        return binding
    overlap = set(settings) & set(binding.model.settings)
    if overlap:
        raise DeepAgentMaterializationError(
            "agent capabilities and the exact model pin both set: " + ", ".join(sorted(overlap))
        )
    model = binding.model.model_copy(update={"settings": {**binding.model.settings, **settings}})
    return binding.model_copy(update={"model": model})


def _exact(registry: Mapping[str, Any], digest: str, kind: str) -> Any:
    try:
        return registry[digest]
    except KeyError as error:
        raise DeepAgentMaterializationError(
            f"exact {kind} revision is unavailable; runtime lookup/fallback is forbidden"
        ) from error


def tool_schema_digest(tool: BaseTool) -> str:
    """The digest an exact binding pins for a tool's model-facing input schema."""

    return _tool_schema_digest(tool)


def _tool_schema_digest(tool: BaseTool) -> str:
    schema_type = tool.get_input_schema()
    schema = (
        schema_type.model_json_schema()
        if hasattr(schema_type, "model_json_schema")
        else schema_type.schema()
    )
    return sha256_digest(schema)


def _single_secret(component: DeepAgentSandboxComponent, secrets: ResolvedSecrets) -> str:
    if len(component.credential_refs) != 1:
        raise DeepAgentMaterializationError("sandbox requires one exact credential reference")
    ref = component.credential_refs[0]
    return _secret_value(ref.provider, ref.key, secrets)


def _secret_value(provider: str, key: str, secrets: ResolvedSecrets) -> str:
    try:
        return secrets[f"{provider}:{key}"]
    except KeyError as error:
        raise DeepAgentMaterializationError(
            "required credential reference was not resolved"
        ) from error


def _merge_by_key(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {**left, **right}


def _replace(_left: Any, right: Any) -> Any:
    return right


def _append_unique_by_id(
    left: list[dict[str, Any]], right: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    result = list(left)
    identities = {str(item.get("id", item.get("ref", item))) for item in result}
    for item in right:
        identity = str(item.get("id", item.get("ref", item)))
        if identity not in identities:
            result.append(item)
            identities.add(identity)
    return result


def _channel_type(channel: CognitiveChannelDefinition) -> object:
    if channel.value_kind in {"object", "map"}:
        base: object = dict[str, Any]
    elif channel.value_kind == "string_list":
        base = list[str]
    else:
        base = list[dict[str, Any]]
    reducer = {
        "replace": _replace,
        "merge_by_key": _merge_by_key,
        "append_unique_by_id": _append_unique_by_id,
    }[channel.reducer.value]
    return Annotated[base, reducer]


def _state_type(schema: CognitiveStateSchema) -> type[DeepAgentState]:
    # Framework-owned middleware schemas are composed into the graph by
    # create_deep_agent itself. Redeclaring these channels here would erase
    # PrivateStateAttr and cause an empty reducer default to suppress loading.
    annotations = {
        channel.name: _channel_type(channel)
        for channel in schema.channels
        if channel.name not in {"skills_metadata", "skills_load_errors"}
    }

    def body(namespace: dict[str, object]) -> None:
        namespace["__annotations__"] = annotations
        namespace["__module__"] = __name__

    return cast(
        type[DeepAgentState],
        types.new_class(
            f"BellLabsState_{schema.schema_digest.removeprefix('sha256:')[:12]}",
            (DeepAgentState,),
            {"total": False},
            body,
        ),
    )


def _runtime_python_type(field: CognitiveRuntimeField) -> type[Any]:
    return {
        "string": str,
        "integer": int,
        "boolean": bool,
        "string_list": tuple[str, ...],
        "string_map": dict[str, str],
    }[field.value_kind]


def _context_type(
    schema: CognitiveRuntimeContextSchema, *, defaults: Mapping[str, object] | None = None
) -> type[Any]:
    required: list[tuple[str, type[Any]]] = []
    defaulted: list[tuple[str, type[Any], Any]] = []
    for item in schema.fields:
        python_type = _runtime_python_type(item)
        if defaults is not None and item.name in defaults:
            value = defaults[item.name]
            # A factory copies the frozen value per instance, so a mutable default (a
            # string map) is never shared; defaulted fields follow the required ones, as a
            # dataclass requires, and instances are built by keyword only.
            defaulted.append(
                (item.name, python_type, dataclass_field(default_factory=_copy_of(value)))
            )
        else:
            required.append((item.name, python_type))
    return make_dataclass(
        f"BellLabsContext_{schema.schema_digest.removeprefix('sha256:')[:12]}",
        [*required, *defaulted],
        frozen=True,
        slots=True,
    )


def _copy_of(value: object) -> Callable[[], object]:
    return lambda: copy.deepcopy(value)


def _context_instance(
    context_type: type[Any],
    schema: CognitiveRuntimeContextSchema,
    values: Mapping[str, object],
) -> object:
    for context_field in schema.fields:
        expected = _runtime_python_type(context_field)
        value = values[context_field.name]
        if not isinstance(value, expected):
            raise DeepAgentMaterializationError(
                f"runtime context field {context_field.name!r} does not match its frozen value kind"
            )
    return context_type(**values)


def _manifest_facts(
    binding: DeepAgentExecutionBinding, skill_files: Sequence[SkillFileRow]
) -> dict[str, Any]:
    """P3.7: the facts the `environment_materialized` frame records, in a stable order.

    `state_files` lists every Skill file the materializer put into `initial_state["files"]`
    (the text-only `StateBackend`); `sandbox_files` lists the ones it uploaded to a sandbox
    backend instead. Both carry the path, the byte count and the content digest, never the
    content.
    """

    skills = [
        *binding.skills,
        *(skill for child in binding.sync_subagents for skill in child.seeded_skills),
    ]
    servers = [
        *binding.mcp_servers,
        *(server for child in binding.sync_subagents for server in child.seeded_mcp_servers),
    ]
    seen: set[str] = set()
    skill_rows: list[dict[str, Any]] = []
    for skill in skills:
        if skill.mount_root in seen:
            continue
        seen.add(skill.mount_root)
        skill_rows.append(
            {
                "name": skill.skill_name,
                "mount_root": skill.mount_root,
                "bundle_digest": skill.bundle_digest,
            }
        )
    by_path = {str(row["path"]): row for row in skill_files}
    rows = [by_path[path] for path in sorted(by_path)]
    return {
        "skills": sorted(skill_rows, key=lambda row: str(row["mount_root"])),
        "mcp_servers": sorted({server.server_name for server in servers}),
        "model": {
            "logical_id": binding.model.ref.logical_id,
            "revision": binding.model.ref.revision,
            "digest": binding.model.ref.digest,
            "provider": binding.model.provider,
        },
        # Sprint B: the sealed lane features and model tools, by id with their config digest.
        "agent_configuration": (
            {
                "digest": binding.agent_configuration.configuration_digest,
                "items": [
                    {
                        "id": item.id,
                        "mechanism": item.mechanism.value,
                        "by_default": item.by_default,
                        "config_digest": item.config_digest,
                    }
                    for item in binding.agent_configuration.items
                ],
            }
            if binding.agent_configuration is not None
            else None
        ),
        "state_files": [
            {"path": row["path"], "bytes": row["bytes"], "digest": row["digest"]}
            for row in rows
            if row["destination"] == "state_channel"
        ],
        "sandbox_files": [
            {"path": row["path"], "bytes": row["bytes"], "digest": row["digest"]}
            for row in rows
            if row["destination"] == "sandbox_upload"
        ],
    }


def protected_paths(binding: DeepAgentExecutionBinding) -> ProtectedPaths:
    """What no hook candidate may land on in this attempt's workspace (WI-17): its output slots
    (a file there is captured as the agent's output, so a candidate would self-fulfill), the
    host-seeded read-only slots and mounts, and the Skill roots; the sealed input mounts and
    host state are refused for every receiver by the domain policy itself."""

    workspace = binding.workspace
    outputs = {
        *workspace.exclusive_write_paths,
        *(slot.logical_path for slot in workspace.slot_bindings if slot.access != "read_only"),
    }
    reserved = {
        *(slot.logical_path for slot in workspace.slot_bindings if slot.access == "read_only"),
        *(mount.logical_path for mount in workspace.read_mounts),
        *(component.mount_root for component in binding.skills),
    }
    return ProtectedPaths(
        output_paths=tuple(sorted(outputs)), reserved_paths=tuple(sorted(reserved))
    )


def _hook_scope(binding: DeepAgentExecutionBinding) -> HookScope:
    """The installation/application/tenant scope hooks see; never credentials."""
    unit = binding.runtime_unit
    if unit is not None:
        try:
            scope = parse_request_scope(unit.request_scope)
        except ValueError:
            pass
        else:
            return HookScope(
                installation_id=str(scope.installation_id),
                application_id=scope.application_id,
                tenant_id=str(scope.tenant_id),
            )
    return HookScope(installation_id="unbound", application_id="unbound")


async def seed_backend_files(
    backend: BackendProtocol, files: Sequence[tuple[str, bytes]]
) -> dict[str, object]:
    """FT-B2 (SPEC-02 lane seeding): put Context Packet files where the agent reads them.

    A sandbox or filesystem backend receives them through ``upload_files`` before the first
    model call; the text-only ``StateBackend`` receives them as invocation-input ``files``
    (returned here for the caller to merge). Binary content on ``StateBackend`` is refused;
    the packer already downgrades binary items to references for text-only lanes.
    """

    if not files:
        return {}
    if isinstance(backend, StateBackend):
        try:
            return {path: create_file_data(content.decode("utf-8")) for path, content in files}
        except UnicodeDecodeError as error:
            raise DeepAgentUnsupportedPlacement(
                "binary context inputs require a byte-capable sandbox backend"
            ) from error
    responses = await backend.aupload_files(list(files))
    if any(item.error for item in responses):
        raise DeepAgentMaterializationError("context packet inputs failed sandbox attachment")
    return {}
