"""Knowledge tools projected into the Deep Agents lane (Sprint V M06/M02, design §8).

The six lane-neutral tools of :mod:`mission_control.application.knowledge.toolset` become
LangChain tools here, through the existing exact-component path (no new lane branch): the
deployment registers them in ``ExactComponentRegistry.tools`` under the definition digests of
:func:`knowledge_tool_components`, a binding names them as ordinary ``DeepAgentToolComponent``
rows, the materializer resolves them by digest and schema digest like any host tool, and the
lane adapter receipts them (``kind: tool``, ``native``) in the sealed materialization receipt
and records their calls in the capability lineage.

At every call the tool reads the **current** invocation from :data:`CURRENT_INVOCATION`, which
:class:`KnowledgeLaneSupport.bind` sets around one attempt's cognition from its live execution
binding (the SV-01 rebound coordinates), so the toolset builds a fresh host access per
dispatch; the model-facing schema has no origin, tenant or credential field and unknown fields
are refused. The tool result is the toolset's structured JSON document (handles, receipts,
typed refusal codes). When the attempt completes, :meth:`KnowledgeLaneSupport.complete`
finalizes the invocation's submissions (independent assessment handoff).
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from typing import Annotated, Any, Final, cast

from langchain_core.tools import BaseTool, InjectedToolCallId, StructuredTool
from pydantic import ValidationError, create_model

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.toolset import (
    TOOL_ARGUMENTS,
    TOOL_DESCRIPTIONS,
    TOOL_NAMES,
    ArgumentCoercion,
    ArgumentCoercionRefused,
    KnowledgeToolset,
    LegacySubmitArgs,
    LiveInvocation,
    ReadScope,
    coerce_object_arguments,
    coercion_refusal,
    validation_refusal,
)
from mission_control.application.outputs.submission_service import FinalizationReport
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef
from mission_control.domain.context.transfer import SealedTransferPlan, TransferSelection
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    DeepAgentToolComponent,
    RuntimeInvocation,
)
from mission_control.domain.execution.invocation_settlement import SettlementOutcome, WaitReason
from mission_control.domain.graph_runtime.identities import GoalDirectedUnitLocation

LANE: Final = "deep_agents"
LEGACY_SUBMIT_CATALOG_DIGEST: Final = (
    "sha256:5f5bf9da0c47856467e70e4a7abfa66947b8e8edce9487092c302c082d1556f2"
)
LEGACY_SUBMIT_DESCRIPTION: Final = (
    "Submit one report alone, or non-report handles/paths, for one output obligation; "
    "a named promise also takes inline text or a structured value (kind inline) "
    "or a code change (kind code_change). Report collections and mixed report selections are "
    "unsupported. For a named promise, obligation is its full key <owner position>.<promise "
    "name> (for example root.report), never the bare name; a refusal lists the keys this "
    "invocation may submit."
)
KNOWLEDGE_TOOL_LOGICAL_PREFIX: Final = "knowledge-tool."
CURRENT_INVOCATION: ContextVar[LiveInvocation | None] = ContextVar(
    "mission_control_knowledge_invocation", default=None
)


def live_invocation(
    invocation: RuntimeInvocation, *, obligations: tuple[str, ...] = ()
) -> LiveInvocation:
    """The live attempt of a runtime invocation (never the launch template's coordinates)."""

    binding = invocation.binding
    dispatch = binding.lane_dispatch
    generation = dispatch.execution_generation if dispatch is not None else 1
    return LiveInvocation(
        request_scope=binding.request_scope,
        run_id=binding.run_id,
        operation_id=binding.operation_id,
        operation_attempt=binding.operation_attempt,
        execution_generation=generation,
        lane=LANE,
        obligations=obligations,
        # WI-01/WI-02: the owner position the host bound to this receiver (never model-set).
        position=None if binding.transfer is None else binding.transfer.receiver_position,
        # W1 D27: an independent evaluator never acts as the producer.
        evaluator=is_evaluator(binding),
        # Provenance slice 1 (OVE-204): the attempt's runtime unit key; the toolset resolves
        # the ledger mission and activation ids from it (`KnowledgeToolset.locate`).
        unit_key=getattr(getattr(binding, "runtime_unit", None), "unit_key", None),
    )


def _same_attempt(left: LiveInvocation, right: LiveInvocation) -> bool:
    return (
        left.request_scope,
        left.run_id,
        left.operation_id,
        left.operation_attempt,
        left.execution_generation,
        left.unit_key,
    ) == (
        right.request_scope,
        right.run_id,
        right.operation_id,
        right.operation_attempt,
        right.execution_generation,
        right.unit_key,
    )


def is_evaluator(binding: Any) -> bool:
    """W1 D27: whether the host bound this invocation as an independent evaluator.

    Either fact suffices (fail closed): the sealed transfer plan's ``independent_evaluator``
    isolation, or the digest-bound runtime unit's GoalDirected ``verifier`` role, which every
    GoalDirected Deep Agents invocation carries even when it has no transfer plan."""

    transfer = getattr(binding, "transfer", None)
    if transfer is not None and transfer.isolation == "independent_evaluator":
        return True
    location = getattr(getattr(binding, "runtime_unit", None), "location", None)
    return isinstance(location, GoalDirectedUnitLocation) and location.operation_role == "verifier"


# Keyword arguments the boundary passes to the tool coroutine beside the validated arguments
# (never model-facing: they are not in the args schema, so the schema digest is unchanged).
_COERCIONS: Final = "mc_argument_coercions"
_BOUNDARY_REFUSAL: Final = "mc_boundary_refusal"


class KnowledgeStructuredTool(StructuredTool):
    """W1 D17: the knowledge tool boundary parses a JSON-object string given for an
    object-typed argument exactly once (``toolset.coerce_object_arguments``) before the args
    schema validates it; a string that is not one bounded JSON object is a typed refusal
    result, never a schema error. The model-facing schema (and its digest) is unchanged."""

    def _to_args_and_kwargs(
        self, tool_input: str | dict[str, Any], tool_call_id: str | None
    ) -> tuple[tuple[str, ...], dict[str, Any]]:
        if not isinstance(tool_input, dict):
            return super()._to_args_and_kwargs(tool_input, tool_call_id)
        try:
            coerced, records = coerce_object_arguments(self.name, tool_input)
        except ArgumentCoercionRefused as error:
            return (), {
                "tool_call_id": tool_call_id or "",
                _BOUNDARY_REFUSAL: coercion_refusal(self.name, error),
            }
        try:
            args, kwargs = super()._to_args_and_kwargs(coerced, tool_call_id)
        except ValidationError as error:
            if self.name != "submit_output":
                raise
            return (), {
                "tool_call_id": tool_call_id or "",
                _BOUNDARY_REFUSAL: validation_refusal(self.name, error),
            }
        if records:
            kwargs[_COERCIONS] = records
        return args, kwargs


def _tool(toolset: KnowledgeToolset, name: str, *, legacy: bool = False) -> BaseTool:
    arguments = LegacySubmitArgs if legacy else TOOL_ARGUMENTS[name]
    schema = create_model(
        f"{name}_arguments",
        __base__=arguments,
        tool_call_id=(Annotated[str, InjectedToolCallId], ...),
    )

    async def run(tool_call_id: str, **values: Any) -> str:
        coercions = cast(tuple[ArgumentCoercion, ...], values.pop(_COERCIONS, ()))
        refused = cast(Mapping[str, Any] | None, values.pop(_BOUNDARY_REFUSAL, None))
        live = CURRENT_INVOCATION.get()
        if refused is not None:
            document: Mapping[str, Any] = refused
        elif live is None:
            document = {
                "tool": name,
                "ok": False,
                "result": None,
                "refusal": {"code": "SCOPE_DENIED", "message": "no live invocation is bound"},
            }
        else:
            document = await toolset.dispatch(
                name, values, live, tool_call_id=tool_call_id, coercions=coercions
            )
        return json.dumps(document, sort_keys=True, separators=(",", ":"))

    return KnowledgeStructuredTool(
        coroutine=run,
        name=name,
        description=LEGACY_SUBMIT_DESCRIPTION if legacy else TOOL_DESCRIPTIONS[name],
        args_schema=schema,
    )


def knowledge_tools(toolset: KnowledgeToolset) -> dict[str, BaseTool]:
    """The seven projected tools by name."""

    return {name: _tool(toolset, name) for name in TOOL_NAMES}


def knowledge_tool_components(
    tools: Mapping[str, BaseTool], *, attachment_target: str = "agent"
) -> tuple[DeepAgentToolComponent, ...]:
    """Exact tool components for a binding; the definition digest pins name and schema."""

    from mission_control.adapters.deep_agents.materializer import tool_schema_digest

    components = []
    for name in TOOL_NAMES:
        tool = tools[name]
        schema_digest = tool_schema_digest(tool)
        digest = sha256_digest(
            {"tool": name, "schema_digest": schema_digest, "kind": "knowledge-tool.v1"}
        )
        components.append(
            DeepAgentToolComponent(
                ref=ExactDefinitionRef(
                    kind=DefinitionKind.TOOL,
                    logical_id=f"{KNOWLEDGE_TOOL_LOGICAL_PREFIX}{name.replace('_', '-')}",
                    revision=2 if name == "submit_output" else 1,
                    digest=digest,
                ),
                tool_name=name,
                schema_digest=schema_digest,
                attachment_target=attachment_target,
            )
        )
    return tuple(components)


def knowledge_registry_tools(tools: Mapping[str, BaseTool]) -> dict[str, BaseTool]:
    """``ExactComponentRegistry.tools`` entries: definition digest -> tool."""

    registry = {
        component.ref.digest: tools[component.tool_name]
        for component in knowledge_tool_components(tools)
    }
    # Preserve the admitted v1 schema under its original digest. It dispatches through the
    # same service and final-mode defaults; no v2 arguments are admitted by this wrapper.
    current = tools["submit_output"]
    legacy = current.model_copy(
        update={
            "description": LEGACY_SUBMIT_DESCRIPTION,
            "args_schema": create_model(
                "submit_output_arguments",
                __base__=LegacySubmitArgs,
                tool_call_id=(Annotated[str, InjectedToolCallId], ...),
            ),
        }
    )
    from mission_control.adapters.deep_agents.materializer import tool_schema_digest

    digest = sha256_digest(
        {
            "tool": "submit_output",
            "schema_digest": tool_schema_digest(legacy),
            "kind": "knowledge-tool.v1",
        }
    )
    registry[digest] = legacy
    return registry


class _DefinitionOnly:
    """The toolset of a definition-only knowledge tool: it is never dispatched."""

    async def dispatch(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("a served knowledge tool definition is not a live toolset")


def served_knowledge_tools() -> dict[str, BaseTool]:
    """W1 D9: the one served definition of the knowledge tool components (definition digest ->
    tool) every launch author and the worker registry agree on.

    The digest pins the tool name and its model-facing schema (``knowledge_tool_components``),
    never the live toolset, so these definition-only tools carry exactly the digests the
    worker's live tools carry (``compose_knowledge_lane`` checks the equality at startup).
    The API's launch author, the worker's chain-relay author and the ingress/probe authors
    serve them through ``compose_manifest_launch_inputs``; they never dispatch.
    """

    unbound = cast(KnowledgeToolset, _DefinitionOnly())
    return knowledge_registry_tools({name: _tool(unbound, name) for name in TOOL_NAMES})


def knowledge_capability_id(tool_name: str) -> str:
    """The catalog capability id of a knowledge tool (seed ``mc.catalog.knowledge-tools``)."""

    return "tool.knowledge-" + tool_name.removeprefix("knowledge_").replace("_", "-")


def knowledge_launch_bindings(
    catalog_digests: Mapping[str, str], tools: Mapping[str, BaseTool]
) -> dict[str, Any]:
    """``mc.manifest_launch_bindings`` capability bindings for the knowledge tools.

    ``catalog_digests`` maps a catalog capability id (``tool.knowledge-read``) to the exact
    published row digest a manifest pins; each binds the exact Deep Agents tool component the
    worker registers, so a coordinator-authored manifest that names the catalog row gets the
    tool in its node binding through the ordinary launch path.
    """

    from mission_control.application.authoring.manifest_launch_inputs import (
        CapabilityComponentBinding,
    )

    components = {item.tool_name: item for item in knowledge_tool_components(tools)}
    bindings: dict[str, Any] = {}
    for name in TOOL_NAMES:
        capability = knowledge_capability_id(name)
        digest = catalog_digests.get(capability)
        if digest is None:
            continue
        component = components[name]
        if name == "submit_output" and digest == LEGACY_SUBMIT_CATALOG_DIGEST:
            legacy_tools = dict(tools)
            legacy_tools[name] = _tool(cast(KnowledgeToolset, _DefinitionOnly()), name, legacy=True)
            component = next(
                item for item in knowledge_tool_components(legacy_tools) if item.tool_name == name
            )
            component = component.model_copy(
                update={"ref": component.ref.model_copy(update={"revision": 1})}
            )
        bindings[capability] = CapabilityComponentBinding(
            catalog_digest=digest, kind="tool", tool=component
        )
    return bindings


class KnowledgeLaneSupport:
    """Binds the live invocation for the tools and finalizes it at node completion."""

    def __init__(self, toolset: KnowledgeToolset) -> None:
        self._toolset = toolset
        self.tools = knowledge_tools(toolset)

    async def begin(self, invocation: RuntimeInvocation) -> LiveInvocation:
        """Before the agent starts: host recovery grants for a retry attempt (R2-MC D2).

        Inputs are not delivered here: every receiver gets them through its sealed transfer
        plan (WI-02), whether or not it has knowledge tools."""

        return await self._toolset.begin(live_invocation(invocation))

    def scope_reads(self, plan: SealedTransferPlan) -> None:
        """Bind the attempt's ``knowledge_read`` to its sealed plan (WI-02 B1): the plan's
        purpose, and for an independent evaluator only the plan's exact reports. The outer
        :meth:`bind` resets the binding when the attempt ends."""

        live = CURRENT_INVOCATION.get()
        if live is None:
            return
        manifests = [m for m in plan.exact_sources if m.part == "manifest"]
        reports = {}
        for item in manifests:
            handle, _, digest = item.access_ref.partition("#digest=")
            reports[handle] = digest
        purpose = manifests[0].purpose if manifests else plan.purpose.split(",", 1)[0]
        CURRENT_INVOCATION.set(
            replace(
                live,
                read_scope=ReadScope(
                    purpose=purpose,
                    isolated=plan.isolation == "independent_evaluator",
                    reports=reports,
                ),
            )
        )

    def scope_role(self, selection: TransferSelection) -> None:
        """An independent evaluator with no plan (no admitted input): its reads stay isolated,
        so no report is reachable (R1); the role scopes, not the plan's presence."""

        live = CURRENT_INVOCATION.get()
        if live is None or selection.isolation != "independent_evaluator":
            return
        CURRENT_INVOCATION.set(
            replace(
                live,
                read_scope=ReadScope(purpose="evaluation_subject", isolated=True, reports={}),
            )
        )

    async def access_for(self, invocation: RuntimeInvocation) -> InvocationAccess:
        """A fresh host access of the live attempt, for the exact reads of its transfer plan.

        Inside the bound attempt the already located live invocation is reused; otherwise the
        attempt's ledger identity is resolved once (`KnowledgeToolset.locate`)."""

        live = live_invocation(invocation)
        bound = CURRENT_INVOCATION.get()
        if bound is not None and _same_attempt(bound, live) and bound.mission_id is not None:
            return self._toolset.access(bound)
        return self._toolset.access(await self._toolset.locate(live))

    @contextmanager
    def bind(
        self, invocation: RuntimeInvocation, live: LiveInvocation | None = None
    ) -> Iterator[LiveInvocation]:
        bound = live or live_invocation(invocation)
        token = CURRENT_INVOCATION.set(bound)
        try:
            yield bound
        finally:
            CURRENT_INVOCATION.reset(token)

    async def fail(self, invocation: RuntimeInvocation, live: LiveInvocation | None = None) -> None:
        """The attempt failed (R2-MC O1): reconcile its effects and record `attempt_failed`."""

        if self.uses_knowledge(invocation):
            await self._toolset.fail(
                await self._toolset.locate(live or live_invocation(invocation))
            )

    def uses_knowledge(self, invocation: RuntimeInvocation) -> bool:
        deep = DeepAgentExecutionBinding.carried_by(invocation.binding)
        if deep is None:
            return False
        names = {tool.tool_name for tool in deep.tools}
        return bool(names & set(TOOL_NAMES))

    async def complete(self, invocation: RuntimeInvocation) -> FinalizationReport | None:
        """Node completion: a bounded receipt-first poll of the open effects under read-only
        recovery authority, then settlement (independent assessment handoff and the
        finalization), which stays blocked while an effect is unresolved."""

        if not self.uses_knowledge(invocation):
            return None
        return await self._toolset.settle(await self._toolset.locate(live_invocation(invocation)))

    # --- WI-04: the settlement of a saved result (`InvocationSettler`) ------------------------

    def applies(self, invocation: RuntimeInvocation) -> bool:
        return self.uses_knowledge(invocation)

    async def settle(
        self, invocation: RuntimeInvocation, *, fenced: bool = False
    ) -> SettlementOutcome:
        """One settlement pass over the saved result, read as a typed outcome.

        The finalization outcome is consumed, never discarded: an unresolved effect is an
        effect wait, an assessment without a verdict a review wait; otherwise the pass settled
        and names the finalization it recorded. Recorded native-plan decisions may apply
        through the shared host settlement service after qualified review. No cognition runs here.
        """

        # Possibly after a worker restart: the ledger identity is re-read, never derived.
        report, open_reviews = await self._toolset.settle_saved(
            await self._toolset.locate(live_invocation(invocation)), fenced=fenced
        )
        detail: dict[str, Any] = {
            "outcome": report.outcome,
            "outcome_basis": report.outcome_basis,
        }
        # A fenced or uncomposed pass did not collect a native snapshot. Omit the key so
        # the durable projection preserves the last known receipt references.
        if not fenced and self._toolset.native is not None:
            detail["native_effects"] = list(report.native_effects)
        obligations = tuple(f"obligation:{item.obligation_id}" for item in report.obligations)
        if report.blocked:
            return SettlementOutcome(
                state="waiting",
                reason=WaitReason.EFFECT_PENDING,
                pending_effects=report.blocked_effects,
                fulfillment_refs=obligations,
                detail=detail,
            )
        finalization = (
            None if report.finalization_id is None else f"finalization:{report.finalization_id}"
        )
        if open_reviews:
            return SettlementOutcome(
                state="waiting",
                reason=WaitReason.REVIEW_PENDING,
                pending_reviews=open_reviews,
                fulfillment_refs=obligations,
                finalization_ref=finalization,
                detail=detail,
            )
        return SettlementOutcome.done(
            fulfillment_refs=obligations, finalization_ref=finalization, detail=detail
        )

    async def stop(self, invocation: RuntimeInvocation) -> None:
        """The attempt was stopped: cancel its open handles and reconcile its effects."""

        if self.uses_knowledge(invocation):
            await self._toolset.cancel(await self._toolset.locate(live_invocation(invocation)))


__all__ = [
    "CURRENT_INVOCATION",
    "KNOWLEDGE_TOOL_LOGICAL_PREFIX",
    "LANE",
    "KnowledgeLaneSupport",
    "KnowledgeStructuredTool",
    "is_evaluator",
    "knowledge_capability_id",
    "knowledge_launch_bindings",
    "knowledge_registry_tools",
    "knowledge_tool_components",
    "knowledge_tools",
    "live_invocation",
    "served_knowledge_tools",
]
