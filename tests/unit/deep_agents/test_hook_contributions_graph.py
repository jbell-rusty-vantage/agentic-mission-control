"""WI-17 / OVE-180 on the Deep Agents lane: a real compiled graph with a scripted (offline) model
and real hook subprocesses over the ``StateBackend`` the agent's own file tools use.

- an after-effect hook's deny is a finding: the shell already ran and its result is kept;
- the same hook's staged candidate installs at the next before-model boundary, the agent's
  ``read_file`` reads it, and the next boundary confirms it once (the state channel is durable
  only after its step commits); its host-state and sealed-input candidates refuse;
- its operation request reaches admission attributed to the hook, never run inline;
- a scoped reader hook receives the read of a covered path and a refusal for another path;
- a before-effect guard's deny prevents the shell, and its candidate refuses (guards stage
  nothing);
- a binding whose hook declares a stage grant without a composed service refuses to prepare.
"""

from __future__ import annotations

import json
import textwrap
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from mission_control.adapters.deep_agents.hook_contributions import DeepAgentCandidateWorkspace
from mission_control.adapters.deep_agents.hooks import (
    HookContext,
    HookDispatcher,
    HookScriptMiddleware,
    KernelHookPorts,
    RecordingFrameSink,
    ResolvedHookScript,
    SubprocessHookScriptRunner,
)
from mission_control.application.context.hook_contributions import (
    ContributionSession,
    ContributionTarget,
    HookContributionService,
    HookGrants,
    HookReadBroker,
)
from mission_control.contracts.hooks import HookScope
from mission_control.domain.capabilities.hooks import HookEvent
from mission_control.domain.context.contributions import (
    HostReadScope,
    StageGrant,
    content_digest,
)
from tests.fixtures.hook_contributions import InMemoryInstallStore, RecordingOperationRequests
from tests.fixtures.knowledge_binding import InMemoryStaging

SCOPE = "mc/11111111-1111-1111-1111-111111111111/biotech/22222222-2222-2222-2222-222222222222"
BODY = "prepared by hook\n"
EXECUTED: list[str] = []

PREPARE = textwrap.dedent(
    """
    import hashlib, json, sys
    event = json.load(sys.stdin)
    body = "prepared by hook\\n"
    digest = "sha256:" + hashlib.sha256(body.encode()).hexdigest()
    def candidate(path):
        return {"path": path, "content": body, "digest": digest}
    print(json.dumps({
        "schema_version": "mc.hook_result.v1",
        "decision": "deny",
        "reason": "post-effect review",
        "staged_candidates": [
            candidate("/prepared/notes.md"),
            candidate("/inputs/report/r7/report.md"),
            candidate("/.mission/state.json"),
        ],
        "operation_requests": [
            {"template": "mc.prepare.index@1", "purpose": "index the notes", "request_key": "i1"}
        ],
    }))
    """
)
READER = textwrap.dedent(
    """
    import json, pathlib, sys
    event = json.load(sys.stdin)
    call = event["tool"]["call_id"]
    pathlib.Path(f"reads-{call}.json").write_text(json.dumps(event.get("reads", [])))
    """
)
GUARD = textwrap.dedent(
    """
    import hashlib, json, sys
    body = "guard\\n"
    digest = "sha256:" + hashlib.sha256(body.encode()).hexdigest()
    print(json.dumps({
        "schema_version": "mc.hook_result.v1",
        "decision": "deny",
        "reason": "guarded",
        "staged_candidates": [{"path": "/prepared/guard.md", "content": body, "digest": digest}],
    }))
    """
)


FINAL = textwrap.dedent(
    """
    import hashlib, json, sys
    body = "too late\\n"
    digest = "sha256:" + hashlib.sha256(body.encode()).hexdigest()
    print(json.dumps({
        "schema_version": "mc.hook_result.v1",
        "staged_candidates": [{"path": "/prepared/final.md", "content": body, "digest": digest}],
    }))
    """
)


@tool
def shell(command: str) -> str:
    """Run a shell command (fixture: records instead of executing)."""
    EXECUTED.append(command)
    return f"ran {command}"


class ScriptedModel(BaseChatModel):
    """Turn 1 runs ``shell``; turn 2 reads two files; turn 3 answers. No provider call."""

    @property
    def _llm_type(self) -> str:
        return "scripted-wi17-fixture"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        done = sum(isinstance(message, ToolMessage) for message in messages)
        if done == 0:
            calls = [{"name": "shell", "args": {"command": "pytest -q"}, "id": "call-1"}]
        elif done == 1:
            calls = [
                {"name": "read_file", "args": {"file_path": "/prepared/notes.md"}, "id": "call-2"},
                {"name": "read_file", "args": {"file_path": "/other/secret.md"}, "id": "call-3"},
            ]
        else:
            calls = []
        reply = AIMessage(id=f"msg-{done}", content="" if calls else "finished", tool_calls=calls)
        return ChatResult(generations=[ChatGeneration(message=reply)])


def _script(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / f"{name}.py"
    path.write_text(body, encoding="utf-8")
    return path


def _agent(
    tmp_path: Path, *, guard: bool = False, final: bool = False
) -> tuple[Any, ContributionSession, Any]:
    staging = InMemoryStaging()
    store = InMemoryInstallStore()
    admission = RecordingOperationRequests()
    service = HookContributionService(
        store=store,
        staging=staging,  # type: ignore[arg-type]
        custody=staging,  # type: ignore[arg-type]
        requests=admission,
    )
    session = ContributionSession(
        service=service,
        target=ContributionTarget(scope=SCOPE, run_id="run-1", operation_ref="op-1"),
        grants={
            "hook.prepare": HookGrants(
                stage=StageGrant(
                    paths=("/prepared/**",), operation_templates=("mc.prepare.index@1",)
                )
            ),
            "hook.reader": HookGrants(
                reads=(HostReadScope(name="prepared", kind="workspace", paths=("/prepared/**",)),)
            ),
            "hook.guard": HookGrants(stage=StageGrant(paths=("/prepared/**",))),
            "hook.final": HookGrants(stage=StageGrant(paths=("/prepared/**",))),
        },
    )
    scripts = [
        ResolvedHookScript(
            hook_id="hook.prepare",
            events=frozenset({HookEvent.AFTER_TOOL}),
            interpreter="python",
            entrypoint=_script(tmp_path, "prepare", PREPARE),
            matcher="^shell$",
        ),
        ResolvedHookScript(
            hook_id="hook.reader",
            events=frozenset({HookEvent.AFTER_TOOL, HookEvent.AFTER_TOOL_FAILURE}),
            interpreter="python",
            entrypoint=_script(tmp_path, "reader", READER),
            matcher="^read_file$",
        ),
    ]
    if guard:
        scripts.append(
            ResolvedHookScript(
                hook_id="hook.guard",
                events=frozenset({HookEvent.BEFORE_SHELL}),
                interpreter="python",
                entrypoint=_script(tmp_path, "guard", GUARD),
                fail_closed=True,
            )
        )
    if final:
        scripts.append(
            ResolvedHookScript(
                hook_id="hook.final",
                events=frozenset({HookEvent.STOP}),
                interpreter="python",
                entrypoint=_script(tmp_path, "final", FINAL),
            )
        )
    backend = StateBackend()
    ports = KernelHookPorts(frames=RecordingFrameSink())
    dispatcher = HookDispatcher(
        context=HookContext(
            scope=HookScope(installation_id="i", application_id="biotech"),
            run_id="run-1",
            activation_id="op-1",
            attempt_no=1,
            generation=1,
            harness_execution_id="exec-1",
        ),
        kernel_hooks=ports.build(),
        scripts=tuple(scripts),
        runner=SubprocessHookScriptRunner(),
        frames=ports.frames,
        cwd=tmp_path,
        contributions=session,
        workspace=DeepAgentCandidateWorkspace(backend),
    )
    agent = create_deep_agent(
        model=ScriptedModel(),
        tools=[shell],
        middleware=[HookScriptMiddleware(dispatcher)],
        backend=backend,
    )
    return agent, session, SimpleNamespace(store=store, admission=admission)


async def test_after_effect_candidates_install_at_the_next_boundary_and_reach_the_agent(
    tmp_path: Path,
) -> None:
    EXECUTED.clear()
    agent, session, doubles = _agent(tmp_path)
    result = await agent.ainvoke({"messages": [HumanMessage(content="prepare and read")]})
    tools = {m.tool_call_id: m for m in result["messages"] if isinstance(m, ToolMessage)}

    # The post-effect deny cannot undo the committed shell call: it ran, its result is kept.
    assert EXECUTED == ["pytest -q"]
    assert tools["call-1"].status != "error"
    assert "ran pytest -q" in str(tools["call-1"].content)
    assert "[Mission Control hook] post-effect review" in str(tools["call-1"].content)

    # Installed through the agent's own backend: its read_file tool returns the bytes.
    assert BODY.strip() in str(tools["call-2"].content)
    assert "/prepared/notes.md" in result["files"]
    first, second = session.receipts
    assert [item.state for item in first.records] == ["pending"]
    assert sorted(item.code for item in first.refusals) == [
        "HOST_STATE_OVERWRITE",
        "SEALED_INPUT_REWRITE",
    ]
    assert [(item.state, item.recovered) for item in second.records] == [("installed", False)]
    (outcome,) = doubles.store.outcomes.values()
    assert outcome.digest == content_digest(BODY.encode())
    assert outcome.realized_backend == "deep_agents:state"
    (claim,) = doubles.store.claims.values()
    assert claim.candidate.origin.hook_id == "hook.prepare"
    assert claim.candidate.origin.event is HookEvent.AFTER_TOOL

    # The operation request went to admission, attributed; nothing ran it inline.
    (request,) = doubles.admission.admitted
    assert request.origin.hook_id == "hook.prepare"
    assert request.proposal.template == "mc.prepare.index@1"

    # The scoped reader saw the covered file and a refusal for the other path.
    covered = json.loads((tmp_path / "reads-call-2.json").read_text())
    assert [(item["target"], item.get("content")) for item in covered] == [
        ("/prepared/notes.md", BODY)
    ]
    other = json.loads((tmp_path / "reads-call-3.json").read_text())
    assert [(item["target"], item["refused"]) for item in other] == [
        ("/other/secret.md", "READ_OUT_OF_SCOPE")
    ]


async def test_a_before_effect_deny_prevents_the_effect_and_stages_nothing(tmp_path: Path) -> None:
    EXECUTED.clear()
    agent, session, doubles = _agent(tmp_path, guard=True)
    result = await agent.ainvoke({"messages": [HumanMessage(content="prepare and read")]})
    tools = {m.tool_call_id: m for m in result["messages"] if isinstance(m, ToolMessage)}
    assert EXECUTED == []
    assert tools["call-1"].status == "error" and "guarded" in str(tools["call-1"].content)
    assert [item.code for item in session.refusals] == ["RESULT_NOT_PERMITTED"]
    assert "/prepared/guard.md" not in result.get("files", {})
    assert doubles.store.claims == {}


async def test_transfer_input_reads_verify_the_sealed_plan_digest() -> None:
    member = SimpleNamespace(binding="report", digest=content_digest(b"R7 bytes"))
    plan = SimpleNamespace(
        placements=(
            SimpleNamespace(member_key="m1", placement="file", path="/inputs/report/r7.md"),
        ),
        member=lambda key: member,
    )

    class Files:
        def __init__(self, content: bytes) -> None:
            self.content = content

        async def read(self, path: str) -> bytes | None:
            return self.content if path == "/inputs/report/r7.md" else None

    scope = HostReadScope(name="inputs", kind="transfer_input", bindings=("report",))
    broker = HookReadBroker(plan=lambda: plan)  # type: ignore[arg-type,return-value]
    exact = await broker.resolve(scope, "report", Files(b"R7 bytes"))  # type: ignore[arg-type]
    assert exact.content == "R7 bytes" and exact.target == "/inputs/report/r7.md"
    tampered = await broker.resolve(scope, "report", Files(b"today's file"))  # type: ignore[arg-type]
    assert tampered.refused == "READ_DIGEST_MISMATCH"
    assert (await broker.resolve(scope, "notes", Files(b""))).refused == "READ_OUT_OF_SCOPE"  # type: ignore[arg-type]


def _declaring(declared: str, *, bound: bool) -> Any:
    from tests.unit.deep_agents.test_hook_middleware import _binding, _bound_binding, _hook_bundles

    bundles, (component,) = _hook_bundles((0, "hook.a"))
    update = (
        {"stage": StageGrant(paths=("/prepared/**",))}
        if declared == "stage"
        else {"host_reads": (HostReadScope(name="n", kind="workspace", paths=("/n/a.md",)),)}
    )
    component = component.model_copy(update=update)
    binding = _bound_binding([component]) if bound else _binding([component])
    binding.workspace = SimpleNamespace(
        exclusive_write_paths=("/workspace/out",),
        slot_bindings=(
            SimpleNamespace(logical_path="/context/packet.md", access="read_only"),
            SimpleNamespace(logical_path="/workspace/report.md", access="exclusive_write"),
        ),
        read_mounts=(SimpleNamespace(logical_path="/mounts/kit"),),
    )
    binding.skills = (SimpleNamespace(mount_root="/skills/research"),)
    return bundles, binding


@pytest.mark.parametrize("declared", ["stage", "reads"])
async def test_declared_contributions_without_a_composed_service_refuse_to_prepare(
    declared: str,
) -> None:
    from contextlib import AsyncExitStack

    from mission_control.adapters.deep_agents.materializer import (
        ExactComponentRegistry,
        ExactDeepAgentMaterializer,
    )
    from mission_control.domain.execution.errors import DeepAgentMaterializationError

    bundles, binding = _declaring(declared, bound=True)
    registry = ExactComponentRegistry(model_factories={}, hook_scripts=bundles)
    with pytest.raises(DeepAgentMaterializationError, match="contribution service"):
        async with AsyncExitStack() as stack:
            await ExactDeepAgentMaterializer(registry)._hook_dispatcher(
                binding, stack, StateBackend()
            )


async def test_the_materializer_composes_the_session_with_the_receivers_protected_paths() -> None:
    from contextlib import AsyncExitStack

    from mission_control.adapters.deep_agents.materializer import (
        ExactComponentRegistry,
        ExactDeepAgentMaterializer,
    )

    bundles, binding = _declaring("stage", bound=True)
    staging = InMemoryStaging()
    service = HookContributionService(
        store=InMemoryInstallStore(),
        staging=staging,  # type: ignore[arg-type]
        custody=staging,  # type: ignore[arg-type]
    )
    registry = ExactComponentRegistry(
        model_factories={}, hook_scripts=bundles, hook_contributions=service
    )
    async with AsyncExitStack() as stack:
        dispatcher = await ExactDeepAgentMaterializer(registry)._hook_dispatcher(
            binding, stack, StateBackend()
        )
    session = dispatcher.contributions
    assert session is not None and isinstance(dispatcher.workspace, DeepAgentCandidateWorkspace)
    assert session.target.scope == binding.runtime_unit.request_scope
    assert session.target.operation_ref == "op-1"
    assert session.protected.output_paths == ("/workspace/out", "/workspace/report.md")
    assert session.protected.reserved_paths == (
        "/context/packet.md",
        "/mounts/kit",
        "/skills/research",
    )
    assert set(session.grants) == {"hook.a"}


async def test_collect_refusals_requests_and_final_leftovers_reach_the_stream(
    tmp_path: Path,
) -> None:
    EXECUTED.clear()
    agent, session, _doubles = _agent(tmp_path, guard=True, final=True)
    events = [
        chunk
        async for chunk in agent.astream(
            {"messages": [HumanMessage(content="prepare and read")]}, stream_mode="custom"
        )
        if isinstance(chunk, dict) and str(chunk.get("type", "")).startswith("mc.hook_contribution")
    ]
    collected = [item for item in events if item["type"] == "mc.hook_contribution_collected"]
    sequences = [item["sequence"] for item in events if "sequence" in item]
    assert sequences == sorted(set(sequences)) and len({item["id"] for item in events}) == len(
        events
    )
    guard = next(item for item in collected if item["hook_id"] == "hook.guard")
    assert [item["code"] for item in guard["refused"]] == ["RESULT_NOT_PERMITTED"]
    final = next(item for item in collected if item["hook_id"] == "hook.final")
    assert [item["path"] for item in final["staged"]] == ["/prepared/final.md"]
    (closed,) = [item for item in events if item["type"] == "mc.hook_contribution_closed"]
    assert [(item["code"], item["path"]) for item in closed["refused"]] == [
        ("CANDIDATE_NOT_INSTALLED", "/prepared/final.md")
    ]
    assert session.staged == []
    assert {item.code for item in session.refusals} == {
        "RESULT_NOT_PERMITTED",
        "CANDIDATE_NOT_INSTALLED",
    }


async def test_after_effect_operation_requests_are_visible_at_collect(tmp_path: Path) -> None:
    EXECUTED.clear()
    agent, _session, _doubles = _agent(tmp_path)
    events = [
        chunk
        async for chunk in agent.astream(
            {"messages": [HumanMessage(content="prepare and read")]}, stream_mode="custom"
        )
        if isinstance(chunk, dict) and chunk.get("type") == "mc.hook_contribution_collected"
    ]
    prepare = next(item for item in events if item["hook_id"] == "hook.prepare")
    assert [item["status"] for item in prepare["requests"]] == ["admitted"]
    assert len(prepare["staged"]) == 3 and prepare["event"] == "after_tool"


async def test_an_attempt_ending_in_an_error_still_refuses_its_leftovers(caplog) -> None:  # type: ignore[no-untyped-def]
    """Teardown closes the session even when no final answer (no STOP) ever came."""

    import logging
    from contextlib import AsyncExitStack

    from mission_control.adapters.deep_agents.materializer import (
        ExactComponentRegistry,
        ExactDeepAgentMaterializer,
    )
    from mission_control.contracts.hooks import HookResult
    from mission_control.domain.context.contributions import CandidateOrigin, StagedCandidate

    bundles, binding = _declaring("stage", bound=True)
    staging = InMemoryStaging()
    service = HookContributionService(
        store=InMemoryInstallStore(),
        staging=staging,  # type: ignore[arg-type]
        custody=staging,  # type: ignore[arg-type]
    )
    registry = ExactComponentRegistry(
        model_factories={}, hook_scripts=bundles, hook_contributions=service
    )
    body = "staged then stranded\n"
    caplog.set_level(logging.WARNING, logger="mission_control.adapters.deep_agents.hooks")
    with pytest.raises(RuntimeError, match="recursion limit"):
        async with AsyncExitStack() as stack:
            dispatcher = await ExactDeepAgentMaterializer(registry)._hook_dispatcher(
                binding, stack, StateBackend()
            )
            session = dispatcher.contributions
            assert session is not None
            await session.collect(
                CandidateOrigin(
                    hook_id="hook.a",
                    event=HookEvent.AFTER_TOOL,
                    input_digest=content_digest(b"input"),
                ),
                HookResult(
                    staged_candidates=(
                        StagedCandidate(
                            path="/prepared/x.md",
                            content=body,
                            digest=content_digest(body.encode()),
                        ),
                    )
                ),
            )
            raise RuntimeError("recursion limit reached")
    assert [(item.code, item.path) for item in session.refusals] == [
        ("CANDIDATE_NOT_INSTALLED", "/prepared/x.md")
    ]
    assert session.staged == []
    assert "CANDIDATE_NOT_INSTALLED" in caplog.text
    assert dispatcher.close_contributions() == ()  # idempotent with the final-answer close


def test_the_plan_registry_keys_by_identity_and_reports_unattachable_backends(caplog) -> None:  # type: ignore[no-untyped-def]
    import logging

    from mission_control.adapters.deep_agents.hook_contributions import (
        forget_transfer_plan,
        remember_transfer_plan,
        transfer_plan_for,
    )

    class Equal:
        """Equal-valued and unhashable backends never share a plan."""

        def __eq__(self, other: object) -> bool:
            return isinstance(other, Equal)

        __hash__ = None  # type: ignore[assignment]

    class Slotted:
        __slots__ = ()

    first, second = Equal(), Equal()
    plan_a, plan_b = SimpleNamespace(plan_id="plan-a"), SimpleNamespace(plan_id="plan-b")
    assert remember_transfer_plan(first, plan_a)  # type: ignore[arg-type]
    assert remember_transfer_plan(second, plan_b)  # type: ignore[arg-type]
    assert transfer_plan_for(first) is plan_a  # type: ignore[arg-type]
    assert transfer_plan_for(second) is plan_b  # type: ignore[arg-type]
    forget_transfer_plan(first)  # type: ignore[arg-type]
    assert transfer_plan_for(first) is None and transfer_plan_for(second) is plan_b  # type: ignore[arg-type]
    forget_transfer_plan(second)  # type: ignore[arg-type]

    caplog.set_level(logging.WARNING)
    slotted = Slotted()
    assert remember_transfer_plan(slotted, SimpleNamespace(plan_id="plan-c")) is False  # type: ignore[arg-type]
    assert transfer_plan_for(slotted) is None  # type: ignore[arg-type]
    assert "plan-c" in caplog.text and "cannot be weakly referenced" in caplog.text


def test_refusal_events_carry_a_digest_and_a_bounded_sanitized_path() -> None:
    from mission_control.adapters.deep_agents.hooks import safe_path

    raw = "/x/" + (chr(0x202E) + "\n<script>") * 20
    shown = safe_path(raw)
    assert shown["path_digest"] == content_digest(raw.encode())
    assert shown["path"] is not None and len(shown["path"]) <= 64
    assert set(shown["path"]) <= set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-"
    )
