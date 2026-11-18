"""Builders, constants and fakes that other test files import.

Moved from tests/unit/orchestration/test_budget_admission_failure.py.
"""

from dataclasses import replace

from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    build_stagegraph_v2,
)
from mission_control.domain.execution.contracts import OperationAttemptIdentity
from mission_control.domain.programs.contracts import ExecutionIdentity
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from tests.support.unit.orchestration.human_gate_budget_admission import fixture


def graph():
    return build_stagegraph_v2(
        logical_id="test.admission-failure",
        title="Admission failure",
        description="No cognition ran",
        stages=(StageGraphStageSpec("work", reservation={"tokens.total": 1}),),
        max_concurrency=1,
    )


async def prepared(*, conclude=True, repository=None, run_request=None, make_command=None):
    from mission_control.domain.policies.contracts import BudgetApplicability
    from tests.support.run_control import request

    run_request = run_request or request()
    run_request = run_request.model_copy(
        update={
            "budget_envelope": run_request.budget_envelope.model_copy(
                update={
                    "dimensions": tuple(
                        item.model_copy(update={"applicability": BudgetApplicability.UNBOUNDED})
                        if item.dimension == "operation.attempts"
                        else item
                        for item in run_request.budget_envelope.dimensions
                    )
                }
            )
        }
    )
    kwargs = {"repository": repository, "run_request": run_request}
    if make_command is not None:
        kwargs["make_command"] = make_command
    control, repository, gate = await fixture(**kwargs)
    interpreter = StageGraphInterpreter(graph(), effective_max_concurrency=1)
    projection = interpreter.initial_projection(ExecutionIdentity(gate.run_id), run_version=3)
    proposal = interpreter.frontier(projection, available_concurrency=1)[0]
    operation = gate.operation.model_copy(
        update={
            "semantic_attempt_id": proposal.identity.semantic_key,
            "operation": gate.operation.operation.model_copy(
                update={
                    "identity": OperationAttemptIdentity(
                        run_id=gate.run_id,
                        operation_id=proposal.identity.operation_id,
                        operation_attempt=1,
                    ),
                    "budget_reservation_id": proposal.reservation_id,
                    "run_control_revision": 4,
                    "budget_limits": proposal.reservation,
                }
            ),
        }
    )
    candidate = replace(
        gate,
        projection=projection,
        proposal=proposal,
        operation=operation,
        blueprint=graph().model_dump(mode="json"),
        human_gate=None,
        control_gate_keys=(),
        conclude_budget_rejection=conclude,
    )
    return control, repository, candidate, interpreter
