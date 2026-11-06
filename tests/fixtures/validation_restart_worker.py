"""Owned crash-test worker: real family service, deterministic custody, no provider processes."""

import asyncio
import faulthandler
import json
import os
from datetime import timedelta
from pathlib import Path

import asyncpg
from pydantic import TypeAdapter
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.worker import UnsandboxedWorkflowRunner, Worker
from tests.integration.postgres.test_completion_validation_postgres import recompose
from tests.unit.orchestration.test_artifact_schema_validation import Custody, captured
from tests.unit.orchestration.test_completion_validation_service import OUTPUT

from mission_control.domain.programs.contracts import StageGraphResultActivityRequest


@workflow.defn
class ValidationRestartWorkflow:
    @workflow.run
    async def run(self, request_json: str) -> dict:
        return await workflow.execute_activity(
            "restart.validate",
            request_json,
            start_to_close_timeout=timedelta(seconds=60),
            heartbeat_timeout=timedelta(seconds=3),
            retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=5),
        )


async def main():
    faulthandler.dump_traceback_later(30, repeat=False)
    print("owned-worker: building pools", flush=True)
    root = Path(os.environ["MC_RESTART_ROOT"])
    runtime = await asyncpg.create_pool(
        os.environ["MC_RESTART_RUNTIME_DSN"], min_size=1, max_size=3
    )
    writer = await asyncpg.create_pool(os.environ["MC_RESTART_WRITER_DSN"], min_size=1, max_size=3)
    custody = Custody(captured(source_ref=OUTPUT))
    _, service = recompose(runtime, writer, custody)
    print("owned-worker: pools ready", flush=True)

    @activity.defn(name="restart.validate")
    async def validate(request_json: str) -> dict:
        request = TypeAdapter(StageGraphResultActivityRequest).validate_json(request_json)
        result = await service.decide_result(request)
        observed = {
            "run_id": request.run_id,
            "decision": result.proposal.decision.value,
            "attempt": activity.info().attempt,
            "captures": len(custody.calls),
            "pid": os.getpid(),
        }
        marker = root / (request.run_id + ".committed.json")
        if os.environ.get("MC_RESTART_BLOCK") == "1" and not marker.exists():
            with marker.open("w", encoding="utf-8") as stream:
                json.dump(observed, stream)
                stream.flush()
                os.fsync(stream.fileno())
            while True:
                activity.heartbeat("durably committed; awaiting owned process interruption")
                await asyncio.sleep(0.25)
        return observed

    client = await Client.connect(os.environ["MC_RESTART_TEMPORAL"])
    print("owned-worker: Temporal connected", flush=True)
    try:
        async with Worker(
            client,
            task_queue=os.environ["MC_RESTART_QUEUE"],
            workflows=[ValidationRestartWorkflow],
            activities=[validate],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            (root / os.environ["MC_RESTART_READY"]).write_text(str(os.getpid()), encoding="utf-8")
            faulthandler.cancel_dump_traceback_later()
            await asyncio.Event().wait()
    finally:
        await runtime.close()
        await writer.close()


if __name__ == "__main__":
    with asyncio.Runner(
        loop_factory=asyncio.SelectorEventLoop if os.name == "nt" else None
    ) as runner:
        runner.run(main())
