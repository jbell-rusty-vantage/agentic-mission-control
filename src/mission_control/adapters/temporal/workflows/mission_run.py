"""Fresh Mission Control root registration over the qualified execution protocol."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    CancelledError,
    ChildWorkflowError,
    TerminatedError,
)
from temporalio.exceptions import TimeoutError as TemporalTimeoutError

with workflow.unsafe.imports_passed_through():
    from mission_control.adapters.temporal.family_failure_activity import (
        FAMILY_FAILURE_ACTIVITY,
        FAMILY_FAILURE_UNAVAILABLE,
    )
    from mission_control.adapters.temporal.workflows.belllabs_run import BellLabsRunWorkflow
    from mission_control.domain.authoring.canonical import sha256_digest
    from mission_control.domain.coordinator.launch import WorkflowResultRecord
    from mission_control.domain.coordinator.workflow_completion import terminal_family_completion
    from mission_control.domain.programs.contracts import BellLabsRunInput
    from mission_control.domain.programs.family_failure import (
        MAX_FAMILY_FAILURE_CAUSE_CHARS,
        FamilyFailureTerminalizationRequest,
        FamilyFailureTerminalizationResult,
    )

# W1 D15: a family that failed, timed out, was cancelled or was terminated never proposes
# terminalization, so the run stayed `active`/`cancelling`. New roots ask run control to
# terminalize it with the typed cause before failing themselves; histories recorded before
# the patch fail at once, as they did.
FAMILY_FAILURE_PATCH = "w1-d15-root-terminalizes-failed-family"
# W1 D39: the typed cause is the innermost failure through nested child workflows (a family
# that failed on its failed operation child), not `unknown`. Only new histories carry it.
FAMILY_FAILURE_NESTED_CAUSE_PATCH = "w1-d39-family-failure-nested-cause"
# A unit still settling after the family closed keeps the run open: the activity retries for
# about half an hour, then the root fails anyway (the run is left to the operator).
FAMILY_FAILURE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=32,
    non_retryable_error_types=["NotFoundError", FAMILY_FAILURE_UNAVAILABLE],
)


@workflow.defn(name="mc.mission_run.v1")
class MissionRunWorkflow(BellLabsRunWorkflow):
    @workflow.run
    async def run(self, run_input: BellLabsRunInput) -> Any:
        try:
            run_input.validate_mission_binding()
            if workflow.info().workflow_id != run_input.workflow_id:
                raise ValueError("Mission Control root identity differs from its admitted binding")
        except ValueError as error:
            raise ApplicationError(
                str(error), type="InvalidMissionBinding", non_retryable=True
            ) from error
        try:
            result = await super().run(run_input)
        except ChildWorkflowError as error:
            if workflow.patched(FAMILY_FAILURE_PATCH):
                await _terminalize_failed_family(run_input, error)
            raise
        # Old histories returned immediately after the family. New roots stay open until
        # the durable record is saved; ambiguous activity responses retry the same payload.
        if workflow.patched("mc-root-materialize-terminal-result-v1"):
            await workflow.execute_activity(
                "coordinator.materialize_workflow_result",
                terminal_family_completion(run_input, result, completed_at=workflow.now()),
                result_type=WorkflowResultRecord,
                task_queue=run_input.family_task_queue,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_interval=timedelta(seconds=30)),
            )
        return result


async def _terminalize_failed_family(
    run_input: BellLabsRunInput, error: ChildWorkflowError
) -> None:
    """Terminalize the run with the family's typed cause; never masks the family failure."""

    cause, message = family_failure_cause(
        error, nested=workflow.patched(FAMILY_FAILURE_NESTED_CAUSE_PATCH)
    )
    handle = workflow.start_activity(
        FAMILY_FAILURE_ACTIVITY,
        FamilyFailureTerminalizationRequest(
            request_scope=run_input.request_scope,
            run_id=run_input.run_id,
            execution_epoch=run_input.continuity.execution_epoch,
            family=run_input.family,
            family_workflow_id=run_input.family_workflow_id,
            cause=cause,
            cause_digest=sha256_digest({"family_failure_message": message}),
            occurred_at=workflow.now(),
        ),
        result_type=FamilyFailureTerminalizationResult,
        task_queue=run_input.family_task_queue,
        start_to_close_timeout=timedelta(seconds=60),
        retry_policy=FAMILY_FAILURE_RETRY,
    )
    try:
        try:
            outcome = await asyncio.shield(handle)
        except asyncio.CancelledError:
            # The root was cancelled while terminalizing: the shielded activity keeps running
            # (cancelling it could leave the run open), the root waits for it once, then honours
            # the cancellation.
            with contextlib.suppress(ActivityError):
                await handle
            raise
    except ActivityError:
        workflow.logger.warning("the failed family's run could not be terminalized: %s", cause)
        return
    if not outcome.accepted:
        workflow.logger.warning(
            "run control refused the failed family's terminalization: %s", outcome.reason_code
        )


def family_failure_cause(error: ChildWorkflowError, *, nested: bool = True) -> tuple[str, str]:
    """The typed cause code of a family's end and its message (only digested, never stored).

    An application failure names its innermost typed `ApplicationError` (an exhausted
    activity's own type when the family did not handle it); termination, timeout and
    cancellation name themselves. `nested` (W1 D39) first walks through child workflow
    failures the family did not handle (its operation child's own end).
    """

    cause: BaseException | None = error.cause
    while nested and isinstance(cause, ChildWorkflowError):
        cause = cause.cause
    prefix = "application_error"
    if isinstance(cause, ActivityError):
        prefix, cause = "activity_error", cause.cause
    if isinstance(cause, TerminatedError):
        code = "terminated"
    elif isinstance(cause, TemporalTimeoutError):
        code = "timed_out"
    elif isinstance(cause, CancelledError):
        code = "cancelled"
    elif isinstance(cause, ApplicationError):
        code = f"{prefix}:{cause.type or 'unspecified'}"
    else:
        code = "unknown"
    message = cause.message if isinstance(cause, ApplicationError) else str(cause or error)
    return code[:MAX_FAMILY_FAILURE_CAUSE_CHARS], message
