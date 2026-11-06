"""W1 D30 (OVE-169): no evaluator credentials never fails a run silently.

Probe run 76ddfa88: with MC_JUDGE_OPENAI_API_KEY and MC_AUDITOR_ANTHROPIC_API_KEY blank the worker
composed no trusted settlement; the report revision got no assessment and no wait, the promise
stayed MISSING and the run failed. Now (1) a launch whose promises need the trusted assessment pin,
in any family, refuses with `trusted_assessment_unavailable` where no trusted settlement composes,
and (2) a worker that composes none keeps such a revision's saved result waiting
(`settlement_unavailable`, reason `evaluator_unavailable`) with the actionable cause, instead of
finalizing it unjudged.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from mission_control.application.authoring import manifest_launch_inputs as launch
from mission_control.application.knowledge.judgment import EvaluatorUnavailable
from mission_control.application.knowledge.trusted_settlement import (
    UncomposedTrustedSettlement,
    pending_or_raise,
)
from mission_control.domain.execution.invocation_settlement import SettlementOutcome, WaitReason
from mission_control.domain.outputs.contracts import EvaluationScope, OutputForm, Requirement
from tests.unit.knowledge.test_wi07_report_collections import PIN, run_iteration, stack_with
from tests.unit.outputs.scenario import obligation


def promises(*requirements: Requirement) -> Any:
    return SimpleNamespace(
        obligations=(
            obligation("root.report", OutputForm.REFERENCE, requirements=requirements),
            obligation("root.summary", OutputForm.TEXT),
        )
    )


def author(admitted: bool, admitted_promises: Any) -> Any:
    value = launch.ManifestLaunchInputAuthor(
        resolver=None,  # type: ignore[arg-type]
        run_control=None,  # type: ignore[arg-type]
        control_plane=None,  # type: ignore[arg-type]
        definitions=None,  # type: ignore[arg-type]
        stage_templates=None,  # type: ignore[arg-type]
        goal_templates=None,  # type: ignore[arg-type]
        dependent_inputs_admitted=admitted,
        trusted_assessment_pin=PIN,
    )
    prepared: list[str] = []

    async def bind(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def human_control(*_args: Any) -> tuple[Any, Any]:
        return (), None

    async def admitted_promises_of(*_args: Any) -> Any:
        return admitted_promises

    class Dispatcher:
        async def prepare(self, *_args: Any, **_kwargs: Any) -> Any:
            prepared.append("prepared")
            raise RuntimeError("prepared")  # the launch went past the refusal

    value.bind = bind
    value._human_control = human_control
    value._admitted_promises = admitted_promises_of
    value._dispatcher = Dispatcher()
    return value


def start(value: Any, family: str = "GoalDirected") -> Any:
    return asyncio.run(
        value.family_input(request_scope="scope", run_id="run-1", family=family, initial_goal="g")
    )


@pytest.mark.parametrize("family", ["GoalDirected", "StageGraph"])
def test_a_trusted_requirement_refuses_at_launch_without_a_trusted_settlement(
    family: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Definitions:
        async def run_subscriptions(self, *_args: Any) -> None:
            return None  # a Stage Graph without authored dependent inputs

    trusted = promises(Requirement(key="assessed", validator=PIN))
    value = author(False, trusted)
    value._definitions = Definitions()
    with pytest.raises(launch.ManifestTrustedAssessmentUnavailable) as refused:
        start(value, family)
    assert refused.value.code == "trusted_assessment_unavailable"
    assert refused.value.pointer == "/outputs/root.report/requirements/assessed"
    assert "MC_JUDGE_OPENAI_API_KEY" in str(refused.value)
    # The same family's typed refusal family (dependent inputs) catches it too.
    assert isinstance(refused.value, launch.ManifestDependentInputsUnavailable)


def test_composable_or_untrusted_launches_are_not_refused() -> None:
    with pytest.raises(RuntimeError, match="prepared"):
        start(author(True, promises(Requirement(key="assessed", validator=PIN))))
    with pytest.raises(RuntimeError, match="prepared"):
        start(author(False, promises(Requirement(key="schema", validator="mc.schema@1"))))
    with pytest.raises(RuntimeError, match="prepared"):
        start(author(False, None))


pytestmark_async = pytest.mark.asyncio


@pytestmark_async
async def test_an_uncomposed_worker_keeps_a_trusted_revision_waiting_with_the_cause() -> None:
    stack = await stack_with(EvaluationScope.INVOCATION)
    access = await run_iteration(stack, 1, "a")
    guard = UncomposedTrustedSettlement(store=stack.store, assessment_pin=PIN)
    passed = await guard.settle(access, attempt=0)
    assert len(passed.unavailable) == 1 and passed.causes
    with pytest.raises(EvaluatorUnavailable) as waiting:
        pending_or_raise(passed)
    outcome = SettlementOutcome.unavailable(waiting.value)
    assert outcome.state == "waiting" and outcome.reason is WaitReason.SETTLEMENT_UNAVAILABLE
    assert outcome.detail["reason"] == "evaluator_unavailable"
    assert "MC_JUDGE_OPENAI_API_KEY" in outcome.detail["issues"][0]
    # Another pin (no trusted requirement) never waits.
    other = UncomposedTrustedSettlement(store=stack.store, assessment_pin="mc.schema@1")
    assert pending_or_raise(await other.settle(access, attempt=0)) == ()


@pytestmark_async
async def test_the_toolset_settlement_raises_the_wait_instead_of_finalizing_unjudged() -> None:
    """The saved-result pass of a worker without a trusted settlement: the finalization is
    recorded once, then the uncomposed guard keeps the result waiting (the settlement boundary
    records `settlement_unavailable` with the cause and retries); never a silent success."""

    from dataclasses import replace

    from mission_control.application.knowledge.trusted_settlement import TrustedSettlementPass
    from tests.unit.knowledge.test_knowledge_tools import lane

    class Guard:
        calls = 0

        async def settle(self, access: Any, *, attempt: int) -> TrustedSettlementPass:
            Guard.calls += 1
            return TrustedSettlementPass(
                unavailable=("rev-1",), causes=("rev-1: no trusted settlement is composed",)
            )

    h = lane()
    toolset = replace(h.toolset, trusted=None, uncomposed_trusted=Guard())  # type: ignore[arg-type]
    with pytest.raises(EvaluatorUnavailable, match="trusted evaluator unavailable for rev-1"):
        await toolset.settle_saved(h.live())
    assert Guard.calls == 1
    # A worker with no guard (no trusted pin) settles as before.
    plain = replace(h.toolset, trusted=None, uncomposed_trusted=None)
    _report, pending = await plain.settle_saved(h.live())
    assert pending == ()


# ---------------------------------------------------------------------- review follow-ups


def _compiled_configuration() -> Any:
    """A real admitted configuration: the Sprint OC W3 report collection (GoalDirected; its
    `root.reports` requirement names the trusted pin), compiled offline."""

    from pathlib import Path

    from tests.unit.authoring.test_manifest_v2_launch import compiled_ok

    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures/manifests/sprint-oc-w3/ai-engineer.report-collection.mission.yml"
    )
    text = fixture.read_text(encoding="utf-8").replace("__PRODUCER__", "producer.default")
    (program,) = compiled_ok(text).programs
    return program.configuration


def _real_admission_author(configuration: Any) -> Any:
    value = author(False, None)
    del value._admitted_promises  # the real admission read, not the stub

    class RunControl:
        async def get_run(self, *_args: Any) -> Any:
            return SimpleNamespace(effective_configuration_digest=configuration.digest)

    class ControlPlane:
        async def retrieve_for_admission(self, digest: str) -> Any:
            assert digest == configuration.digest
            return configuration

    value._run_control = RunControl()
    value._control_plane = ControlPlane()
    return value


def test_the_refusal_reads_the_real_admitted_configuration() -> None:
    configuration = _compiled_configuration()
    with pytest.raises(launch.ManifestTrustedAssessmentUnavailable) as refused:
        start(_real_admission_author(configuration))
    assert refused.value.pointer == "/outputs/root.reports/requirements/assessed"


def test_a_configuration_without_a_workspace_template_adds_no_new_failure() -> None:
    """The check reads the selected blueprint only: without a workspace template (which the
    launch's own `bind` requires) it still answers the typed refusal, never a ValueError; and
    the real `AdmittedLaunch.from_configuration` failure stays where it was."""

    from mission_control.domain.authoring.contracts import DefinitionKind

    configuration = _compiled_configuration()
    bare = configuration.model_copy(
        update={
            "source_refs": tuple(
                ref
                for ref in configuration.source_refs
                if ref.kind != DefinitionKind.WORKSPACE_TEMPLATE
            )
        }
    )
    with pytest.raises(launch.ManifestTrustedAssessmentUnavailable):
        start(_real_admission_author(bare))
    with pytest.raises(ValueError, match="workspace template"):
        launch.AdmittedLaunch.from_configuration("scope", "run-1", bare)
    # Without the trusted requirement the same bare configuration passes the check.
    untrusted = bare.model_copy(
        update={
            "selected_blueprint": bare.selected_blueprint.model_copy(
                update={"output_promises": None}
            )
        }
    )
    with pytest.raises(RuntimeError, match="prepared"):
        start(_real_admission_author(untrusted))


@pytestmark_async
async def test_a_finally_judged_revision_is_never_held_again() -> None:
    """Review item 2: a credential-less worker resuming a run does not re-hold a revision a
    credentialed worker already judged (pass or fail); a pending review still holds."""

    from tests.unit.knowledge.test_wi07_report_collections import ScriptedBridge, settlement

    for verdict, held in (("pass", False), ("fail", False), ("review", True)):
        stack = await stack_with(EvaluationScope.INVOCATION)
        access = await run_iteration(stack, 1, "a")
        await settlement(stack, ScriptedBridge(stack, {"a": verdict})).settle(access, attempt=1)
        passed = await UncomposedTrustedSettlement(store=stack.store, assessment_pin=PIN).settle(
            access, attempt=0
        )
        assert bool(passed.unavailable) is held, verdict


@pytestmark_async
async def test_the_wait_releases_once_a_composed_settlement_runs() -> None:
    """Review item 3c: the same saved result waits under a worker without credentials, then a
    worker with a composed trusted settlement judges and promotes it on its next pass."""

    from tests.unit.knowledge.test_wi07_report_collections import ScriptedBridge, settlement

    stack = await stack_with(EvaluationScope.INVOCATION)
    access = await run_iteration(stack, 1, "a")
    guard = UncomposedTrustedSettlement(store=stack.store, assessment_pin=PIN)
    with pytest.raises(EvaluatorUnavailable):
        pending_or_raise(await guard.settle(access, attempt=0))
    bridge = ScriptedBridge(stack, {"a": "pass"})
    passed = await settlement(stack, bridge).settle(access, attempt=2)
    assert bridge.assessed == ["a"] and len(passed.promoted) == 1
    assert pending_or_raise(passed) == ()
    # And a credential-less pass after that no longer holds it.
    assert pending_or_raise(await guard.settle(access, attempt=3)) == ()
