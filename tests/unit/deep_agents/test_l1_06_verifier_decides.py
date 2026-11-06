"""OVE-169 L1-06: a verifier that follows its objective decides in a few model calls.

The E4 consumer verifier (2a6bc6a7) spent 16 of 16 tool calls re-reading and searching and the
family failed on the budget stop (``goal_directed.py`` NON_JUDGED_VERIFIER_FAILURES). This turn
runs the production E4 verifier template's prompt through a real ``create_agent`` loop held to
the run's in-turn budget (``BudgetStopMiddleware`` over the template's ``budget_limits``). The
fake verifier knows nothing but the prompt: it reads the subject binding the objective names,
then answers with the verdict the objective's contract dictates. It settles in at most three
model calls, before any budget stop, with an observation the reconciler admits
(``output_contract_ref`` among the frozen contracts) and convergence counts as a verified
completion (every required obligation accepted).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from mission_control.adapters.deep_agents.adapter import (
    _budget_stop_of,
    _ModelCallObserver,
    _turn_limits,
    _TurnSpend,
)
from mission_control.adapters.deep_agents.budget import BudgetStopMiddleware
from mission_control.domain.programs.goal_directed_runtime import GoalVerifierObservation
from tests.unit.authoring.test_l1_06_goal_verifier_objective import E4, loop_templates, text_of

USAGE = {"input_tokens": 900, "output_tokens": 100, "total_tokens": 1000}
RUN_DIMENSIONS = ("model.turns", "tokens.total", "tool.calls.total")
read: list[str] = []


@tool
def read_file(file_path: str) -> str:
    """Read a file from the workspace."""

    read.append(file_path)
    return "Mistral 7B | 7-billion-parameter | arxiv-2310.06825-abstract"


class PromptDrivenVerifier(BaseChatModel):
    """Reads the subject the objective names, then returns the verdict its contract dictates."""

    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "prompt-driven-verifier"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> PromptDrivenVerifier:
        del tools, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        self.calls += 1
        prompt = str(next(item for item in messages if item.type == "human").content)
        if self.calls == 1:
            subject = re.search(r"binding (subject-[a-z0-9-]+)", prompt)
            assert subject is not None, "the objective names no subject binding"
            call = {"name": "read_file", "args": {"file_path": f"inputs/{subject.group(1)}/"}}
        else:
            obligations = re.search(
                r"accepted_obligation_refs: on accepted exactly (\[.*?\])", prompt
            )
            contract = re.search(
                r"output_contract_ref: exactly one of .*?else (output:\S+?)\)", prompt
            )
            assert obligations is not None and contract is not None, "no verdict contract"
            verdict = {
                "decision": "accepted",
                "progress_made": True,
                "accepted_obligation_refs": json.loads(obligations.group(1)),
                "findings": ["brief_submitted: met - the brief restates the map"],
                "evidence_refs": read[-1:],
                "unmet_obligations": [],
                "output_contract_ref": contract.group(1),
            }
            call = {"name": "GoalVerifierObservation", "args": verdict}
        message = AIMessage(
            content="",
            id=f"a-{self.calls}",
            tool_calls=[{**call, "id": f"t{self.calls}", "type": "tool_call"}],
            usage_metadata=dict(USAGE),
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.asyncio
async def test_a_verifier_that_reads_the_subject_then_returns_the_verdict_settles_fast() -> None:
    read.clear()
    _definition, blueprint, templates = await loop_templates(E4, index=1)
    template = templates["verifier"]
    remaining = {
        key: value for key, value in template.budget_limits.items() if key in RUN_DIMENSIONS
    }
    invocation: Any = SimpleNamespace(
        binding=SimpleNamespace(budget_limits={"goal.iterations": 1}),
        run_budget_dimensions=RUN_DIMENSIONS,
        run_budget_remaining=remaining,
    )
    calls = _ModelCallObserver()
    spend = _TurnSpend(calls)
    budget = BudgetStopMiddleware(_turn_limits(invocation), spend, admit_tool_call=spend.admit)
    model = PromptDrivenVerifier()
    agent = create_agent(
        model,
        tools=[read_file],
        middleware=[budget],
        response_format=ToolStrategy(GoalVerifierObservation, handle_errors=False),
    )

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=text_of(template))]}, config={"callbacks": [calls]}
    )

    assert model.calls <= 3
    assert read == ["inputs/subject-root-brief/"]
    assert _budget_stop_of(result["messages"]) == {}
    observation = GoalVerifierObservation.model_validate(result["structured_response"])
    # `GoalDirectedService._parsed` admits only the frozen required output contracts.
    assert observation.output_contract_ref in blueprint.required_output_contracts
    # `GoalDirectedExecution` counts a verified completion only with every required obligation.
    assert observation.decision == "accepted" and not observation.unmet_obligations
    assert set(blueprint.required_obligation_refs) <= set(observation.accepted_obligation_refs)
