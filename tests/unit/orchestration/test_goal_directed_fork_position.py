"""1.4.4 (TR-D14, WP-TR-4): the Goal Directed fork start position is a pin, not a skip.

A fork-derived Goal Directed run starts at iteration 1 like any other (its earlier
iterations settle by reference through the fork's reuse decisions); the family carries the
receipt's `start_position` and, when it first claims the executor of that iteration, the
session generation and the agent run must be the ones the fork seeded. Anything else is a
typed `fork start position drift` failure, never fresh cognition elsewhere.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from mission_control.adapters.temporal.workflows.goal_directed import _continuation
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.programs.contracts import (
    GoalContinuationState,
    GoalDirectedStartPosition,
)
from mission_control.domain.programs.goal_directed import (
    GoalDirectedExecutionError,
    GoalDirectedInterpreter,
)
from tests.unit.orchestration.test_wp_bp_020_goal_directed import (
    _blueprint,
    _execution,
    _revision,
    _run_input,
    _verification,
)

PIN = GoalDirectedStartPosition(goal_iteration=2, session_generation=1, agent_run=2)


def _continuation_state(
    *, fork_start_position: GoalDirectedStartPosition | None
) -> GoalContinuationState:
    revision = _revision()
    return GoalContinuationState(
        active_revision=revision,
        accepted_revisions=(revision,),
        next_goal_iteration=2,
        next_agent_run=2,
        session_generation=1,
        session_token_usage=0,
        workspace_generation=1,
        handoffs=(),
        output_refs=("artifact:prior",),
        no_progress_iterations=0,
        repeated_blocker_count=0,
        last_blocker_class="",
        rollover_count=0,
        next_session_mode="reuse",
        completed_goal_iterations=1,
        completed_agent_runs=1,
        lineage_digest=sha256_digest("prior-lineage"),
        fork_start_position=fork_start_position,
    )


def test_fresh_state_carries_the_fork_start_position() -> None:
    configured = _blueprint(max_iterations=3)
    state = GoalDirectedInterpreter(configured).initial_state(
        replace(_run_input(configured), start_position=PIN)
    )
    assert state.fork_start_position == PIN
    # A pin is not a skip: the derived run still starts at iteration 1, agent run 1.
    assert (state.next_goal_iteration, state.next_agent_run, state.session_generation) == (1, 1, 1)
    # Without a fork the state carries no pin.
    assert (
        GoalDirectedInterpreter(configured)
        .initial_state(_run_input(configured))
        .fork_start_position
        is None
    )


def test_executor_claim_at_the_pinned_iteration_with_matching_counters_succeeds() -> None:
    configured = _blueprint(max_iterations=3)
    interpreter = GoalDirectedInterpreter(configured)
    state = interpreter.initial_state(replace(_run_input(configured), start_position=PIN))
    # Iteration 1 is claimed as usual (below the pin), executed and verified; the family
    # then reaches iteration 2 on session 1 as agent run 2, exactly the fork's position.
    state, claim_one = interpreter.claim_execution(state)
    assert claim_one.identity.iteration.goal_iteration == 1
    state = interpreter.apply_execution_result(state, _execution(claim_one))
    state = interpreter.apply_verification(state, _verification(claim_one))
    assert (state.next_goal_iteration, state.next_agent_run, state.session_generation) == (2, 2, 1)
    state, claim_two = interpreter.claim_execution(state)
    assert claim_two.identity.iteration.goal_iteration == PIN.goal_iteration
    assert claim_two.identity.agent_run == PIN.agent_run
    assert claim_two.identity.session_generation == PIN.session_generation
    assert state.fork_start_position == PIN


@pytest.mark.parametrize(
    ("agent_run", "session_generation"),
    [(3, 1), (2, 2), (1, 2)],
)
def test_executor_claim_at_the_pinned_iteration_with_other_counters_is_refused(
    agent_run: int, session_generation: int
) -> None:
    configured = _blueprint(max_iterations=3)
    interpreter = GoalDirectedInterpreter(configured)
    state = interpreter.initial_state(replace(_run_input(configured), start_position=PIN))
    drifted = replace(
        state,
        next_goal_iteration=PIN.goal_iteration,
        next_agent_run=agent_run,
        session_generation=session_generation,
    )
    with pytest.raises(GoalDirectedExecutionError) as refused:
        interpreter.claim_execution(drifted)
    assert str(refused.value).startswith("fork start position drift:")
    # The same counters at another iteration are not pinned.
    elsewhere = replace(drifted, next_goal_iteration=3)
    _state, claim = interpreter.claim_execution(elsewhere)
    assert claim.identity.iteration.goal_iteration == 3


def test_a_pin_beyond_the_frozen_iteration_limit_is_refused() -> None:
    configured = _blueprint(max_iterations=2)
    beyond = GoalDirectedStartPosition(goal_iteration=3, session_generation=1, agent_run=3)
    with pytest.raises(GoalDirectedExecutionError, match="exceeds the frozen GoalDirected limit"):
        GoalDirectedInterpreter(configured).initial_state(
            replace(_run_input(configured), start_position=beyond)
        )


def test_continuation_state_round_trips_the_pin() -> None:
    configured = _blueprint(max_iterations=3)
    interpreter = GoalDirectedInterpreter(configured)
    # The workflow's Continue-As-New builder carries the pin from the state.
    fresh = interpreter.initial_state(replace(_run_input(configured), start_position=PIN))
    assert _continuation(fresh).fork_start_position == PIN
    assert _continuation(replace(fresh, fork_start_position=None)).fork_start_position is None
    # A continued segment takes the pin from the continuation state...
    continued = interpreter.initial_state(
        _run_input(configured, continuation=_continuation_state(fork_start_position=PIN))
    )
    assert continued.fork_start_position == PIN
    assert continued.next_goal_iteration == 2
    _state, claim = interpreter.claim_execution(continued)
    assert claim.identity.agent_run == PIN.agent_run
    # ...and falls back to the run input's when the continuation predates the field.
    fallback = interpreter.initial_state(
        replace(
            _run_input(configured, continuation=_continuation_state(fork_start_position=None)),
            start_position=PIN,
        )
    )
    assert fallback.fork_start_position == PIN
    # A continued segment that reaches the pinned iteration with other counters is refused.
    drifted = replace(_continuation_state(fork_start_position=PIN), next_agent_run=3)
    with pytest.raises(GoalDirectedExecutionError, match="^fork start position drift:"):
        interpreter.claim_execution(
            interpreter.initial_state(_run_input(configured, continuation=drifted))
        )
