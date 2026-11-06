"""Explicit operator composition for retained evidence; no route, dispatch or deployment.

Callers supply already-authorized restricted pools and services plus trusted
capture/workflow inputs. Constructing this object performs no I/O. Invocation is
a separate consequential reconciliation, subject to the exact reviewed request.
"""

import asyncpg

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.lanes.execution_state import PostgresLaneExecutionStateStore
from mission_control.adapters.postgres.terminal_adoption_context import (
    PostgresTerminalAdoptionContextReader,
)
from mission_control.adapters.temporal.terminal_adoption_inputs import TerminalWorkflowInputs
from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadPort
from mission_control.application.execution.operations.operation_execution import (
    OperationExecutionService,
)
from mission_control.application.programs.service import StageGraphDecisionService
from mission_control.application.recovery.terminal_evidence_adoption import (
    TerminalEvidenceAdoptionService,
)
from mission_control.application.recovery.terminal_evidence_capture import TerminalCaptureReader
from mission_control.application.recovery.terminal_lane_adoption import AdoptionIdentity


def compose_terminal_evidence_adoption(
    *,
    pool: asyncpg.Pool,
    identity: AdoptionIdentity,
    inputs: TerminalWorkflowInputs,
    cancel_issuer: str,
    cancel_command_id: str,
    captures: TerminalCaptureReader,
    payloads: ArtifactPayloadPort,
    operations: OperationExecutionService,
    programs: StageGraphDecisionService,
) -> TerminalEvidenceAdoptionService:
    frames = PostgresFrameRepository(pool, actor_ref="terminal-evidence-adoption")
    return TerminalEvidenceAdoptionService(
        contexts=PostgresTerminalAdoptionContextReader(
            pool,
            identity=identity,
            inputs=inputs,
            cancel_issuer=cancel_issuer,
            cancel_command_id=cancel_command_id,
        ),
        captures=captures,
        states=PostgresLaneExecutionStateStore(pool),
        frames=frames,
        reader=frames,
        payloads=payloads,
        operations=operations,
        programs=programs,
    )
