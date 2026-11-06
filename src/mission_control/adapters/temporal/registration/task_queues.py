from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BellLabsTaskQueues:
    """Five stable logical isolation classes; process topology remains deployment-owned."""

    coordinator_family: str
    agent_cognitive: str
    ingestion_io: str
    sandbox_external_job: str
    verification_reconciliation: str

    def __post_init__(self) -> None:
        values = tuple(self.__dict__.values())
        if any(not value for value in values) or len(set(values)) != len(values):
            raise ValueError("BellLabs logical task queues must be non-empty and unique")

    @classmethod
    def from_base(cls, base: str) -> BellLabsTaskQueues:
        if not base:
            raise ValueError("base Temporal task queue must be non-empty")
        return cls(
            coordinator_family=f"{base}-coordinator-family",
            agent_cognitive=f"{base}-agent-cognitive",
            ingestion_io=f"{base}-ingestion-io",
            sandbox_external_job=f"{base}-sandbox-external-job",
            verification_reconciliation=f"{base}-verification-reconciliation",
        )


def generic_artifact_task_queue(base: str) -> str:
    """The queue of `GenericArtifactWorkflow` and its `artifact.promote` activity (RRM-009).

    The workflow runs `operation.execute` on its own queue, so the worker serving it
    registers both activities; the API's generic artifact submitter targets the same name.
    """

    if not base:
        raise ValueError("base Temporal task queue must be non-empty")
    return f"{base}-generic-artifact"


def watchers_task_queue(base: str) -> str:
    """The queue of `mc.watchers.v1` and its `watchers.evaluate` activity (SPEC-04 §5.3).

    Derived from the deployment's root task queue, so the API that starts the evaluator and
    the worker that hosts it name the same queue.
    """

    if not base:
        raise ValueError("base Temporal task queue must be non-empty")
    return f"{base}-watchers"


def maintenance_task_queue(base: str) -> str:
    """The worker's maintenance queue (FT-C1 `mc.frames_expire.v1` retention runs, HL-18
    `mc.hosted_session_retention.v1` session deletions, `mc.transcript_project.v1`, the fork
    seed copy).

    The one derivation: the API that starts these workflows and the worker that hosts them
    both call it on the deployment's base task queue (`settings.temporal_task_queue`).
    """

    if not base:
        raise ValueError("base Temporal task queue must be non-empty")
    return f"{base}-maintenance"
