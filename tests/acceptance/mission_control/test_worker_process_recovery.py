"""Forced process loss after a real PostgreSQL family commit, before Temporal acknowledgement.

Only child Popen handles owned by this fixture are killed. The private Temporal server
and fresh mct database are fixture-owned; shared database/container services stay running.
This qualifies the production decision service's recovery, not paid-provider restoration.
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import TypeAdapter
from tests.fixtures.mission_control_production_stack import start_local
from tests.fixtures.owned_process import OwnedProcess
from tests.fixtures.validation_restart_worker import ValidationRestartWorkflow
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.unit.orchestration.test_completion_validation_service import prepared
from tests.unit.run_control.test_run_control import command

from mission_control.adapters.postgres.orchestration.completion_evidence import (
    PostgresCompletionEvidenceReader,
)
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.domain.policies.contracts import CancelAction, CommandStatus
from mission_control.domain.programs.contracts import StageGraphResultActivityRequest

pytestmark = pytest.mark.common_db
ROOT = Path(__file__).resolve().parents[3]


async def exists(path, process):
    async with asyncio.timeout(60):
        while not path.exists():
            assert process.poll() is None, (
                "owned worker exited before its barrier; inspect fixture log"
            )
            await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_forced_worker_loss_replays_commit_and_honors_offline_cancel(common_db, tmp_path):
    with socket.socket() as address:
        address.bind(("127.0.0.1", 0))
        port = address.getsockname()[1]
    env = await start_local(tmp_path / "temporal.sqlite", port=port)
    pool = await common_db.pool()
    writer = await common_db.pool("mission_control_family_writer")
    processes = []
    logs = []
    queue = "owned-restart-" + uuid4().hex
    child_env = {
        **os.environ,
        "MC_RESTART_ROOT": str(tmp_path),
        "MC_RESTART_RUNTIME_DSN": common_db.dsn("mission_control_runtime"),
        "MC_RESTART_WRITER_DSN": common_db.dsn("mission_control_family_writer"),
        "MC_RESTART_TEMPORAL": f"127.0.0.1:{port}",
        "MC_RESTART_QUEUE": queue,
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
    }

    async def start(block):
        log = (tmp_path / f"worker-{len(processes)}.log").open("w", encoding="utf-8")
        logs.append(log)
        ready = "ready-" + uuid4().hex
        proc = await asyncio.to_thread(
            OwnedProcess,
            [sys.executable, "-m", "tests.fixtures.validation_restart_worker"],
            cwd=ROOT,
            env={**child_env, "MC_RESTART_BLOCK": str(int(block)), "MC_RESTART_READY": ready},
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        processes.append(proc)
        await exists(tmp_path / ready, proc)
        return proc

    def kill(proc):
        # The job contains only this fixture's launcher/interpreter descendants.
        proc.kill()

    try:
        first = await start(True)
        fixture = await prepared(
            PostgresRunControlRepository(pool, family_writer_pool=writer), common_db.scope()
        )
        request = fixture.result
        encoded = TypeAdapter(StageGraphResultActivityRequest).dump_json(request).decode()
        handle = await env.client.start_workflow(
            ValidationRestartWorkflow.run, encoded, id="restart-" + uuid4().hex, task_queue=queue
        )
        original_run = handle.first_execution_run_id
        await exists(tmp_path / (request.run_id + ".committed.json"), first)
        original_pid = json.loads((tmp_path / (request.run_id + ".committed.json")).read_text())[
            "pid"
        ]
        before = await fixture.run_control.get_run(common_db.scope(), request.run_id)
        evidence = await PostgresCompletionEvidenceReader(pool).list(
            common_db.scope(), request.run_id
        )
        assert evidence.decisions[0].validation.status == "satisfied"
        assert len(before.accepted_output_evidence) == 1
        kill(first)
        second = await start(False)
        recovered = await asyncio.wait_for(handle.result(), timeout=60)
        assert recovered["attempt"] >= 2 and recovered["pid"] != original_pid
        assert recovered["captures"] == 0  # receipt replay never reopens artifact custody
        assert handle.first_execution_run_id == original_run
        assert await fixture.run_control.get_run(common_db.scope(), request.run_id) == before
        assert (
            await PostgresCompletionEvidenceReader(pool).list(common_db.scope(), request.run_id)
            == evidence
        )

        # Cancel a second admitted run while there is no worker to receive its result.
        kill(second)
        cancelled = await prepared(
            PostgresRunControlRepository(pool, family_writer_pool=writer),
            common_db.scope("tenant-2"),
        )
        run = await cancelled.run_control.get_run(cancelled.scope, cancelled.result.run_id)
        cancel = command(run.run_id, run.version, "offline-cancel", CancelAction()).model_copy(
            update={"request_scope": cancelled.scope}
        )
        receipt = await cancelled.run_control.execute(cancel)
        assert receipt.status == CommandStatus.ACCEPTED
        assert await cancelled.run_control.execute(cancel) == receipt
        encoded = TypeAdapter(StageGraphResultActivityRequest).dump_json(cancelled.result).decode()
        cancel_handle = await env.client.start_workflow(
            ValidationRestartWorkflow.run,
            encoded,
            id="cancel-restart-" + uuid4().hex,
            task_queue=queue,
        )
        await start(False)
        cancelled_result = await asyncio.wait_for(cancel_handle.result(), timeout=60)
        assert cancelled_result["decision"] == "quarantine"
        after = await cancelled.run_control.get_run(cancelled.scope, run.run_id)
        assert after.phase.value == "cancelling"
        assert not after.accepted_output_evidence and not after.accepted_obligation_evidence
        (tmp_path / "recovery-proof.json").write_text(
            json.dumps(
                {
                    "committed_validation_status": "satisfied",
                    "retry_attempt": recovered["attempt"],
                    "duplicate_output_evidence": False,
                    "replay_artifact_reads": recovered["captures"],
                    "offline_cancel_result": cancelled_result["decision"],
                    "provider_restore": "unverified",
                }
            ),
            encoding="utf-8",
        )
    finally:
        for proc in processes:
            kill(proc)
        for log in logs:
            log.close()
        await pool.close()
        await writer.close()
        await env.shutdown()
