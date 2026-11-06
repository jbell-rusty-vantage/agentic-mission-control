"""OVE-184 on a real local Agent Server and real PostgreSQL (T0: nothing paid).

The parent's governed service spawns a sealed child against ``langgraph dev`` serving the
canonical config: the served-graphs route reports the sealed-child host template, the parent
creates its scope's assistant of the exact binding (admitted by the deployment auth) and runs
on it; the server's sealed-child factory takes the scope from the verified claim, reads the
contract from PostgreSQL custody under that scope, re-verifies the digests, compiles the
binding with the worker's adapter and materializer and stamps the sealed digest. The parent
then admits the child's result at check time. Another scope cannot run that assistant.

Only the model is substituted (``tests/fixtures/wi23_sealed_child_hosting.py``): a
deterministic local child that echoes whether it saw the sealed prompt.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid5

import pytest
from langgraph_sdk import get_client
from langgraph_sdk.errors import APIStatusError

from mission_control.adapters.agent_server.async_subagents.auth import mint_scope_claim
from mission_control.adapters.agent_server.deployment import GRAPH_NAMESPACE
from mission_control.adapters.deep_agents.async_subagents import DeepAgentsAsyncSubagentAdapter
from mission_control.adapters.postgres.async_subagents.async_subagent_detail_repository import (
    PostgresAsyncSubagentDetailRepository,
)
from mission_control.adapters.postgres.async_subagents.async_subagents import (
    PostgresAsyncSubagentAuthority,
)
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.application.subordinates.admission import CheckTimeAdmission
from mission_control.application.subordinates.parent_completion import ASYNC_RESULT_POLICIES
from mission_control.application.subordinates.service import (
    AsyncSubagentError,
    AsyncSubagentService,
)
from mission_control.domain.execution.async_subagent_reconciliation import (
    SEALED_BINDING_DIGEST_KEY,
    SEALED_CONTRACT_DIGEST_KEY,
    sealed_child_assistant_id,
)
from mission_control.domain.execution.contracts import (
    AsyncSubagentDependencyClass,
    AsyncSubagentLifecycle,
    OperationExecutionBinding,
)
from mission_control.domain.policies.contracts import (
    CommandStatus,
    ReserveBudgetAction,
    StartAction,
)
from tests.acceptance.control_plane.test_wp_cp_040 import exact_fixture
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.fixtures.mission_control_local_agent_server import local_agent_server
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.integration.postgres.runtime_common import scoped_command, scoped_request
from tests.unit.operations.test_async_child_check_time_admission import _sealed_contract
from tests.unit.operations.test_async_child_parent_budget import spawn
from tests.unit.run_control.test_run_control import service as run_control_service

pytestmark = pytest.mark.common_db
TOKEN_ENV = "BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN"


async def _admitted_parent(db: CommonDatabase, pool: object) -> str:
    run_control, _ = run_control_service(PostgresRunControlRepository(pool))  # type: ignore[arg-type]
    admitted = await run_control.admit(scoped_request(db, request_id="wi23-server-parent"))
    assert admitted.run_id is not None
    run_id = admitted.run_id
    started = await run_control.execute(scoped_command(db, run_id, 1, "start", StartAction()))
    assert started.status == CommandStatus.ACCEPTED
    reserved = await run_control.execute(
        scoped_command(
            db,
            run_id,
            started.resulting_run_version,
            "reserve-parent",
            ReserveBudgetAction(
                reservation_id="reservation:parent-operation", amounts={"tokens.total": 20}
            ),
        )
    )
    assert reserved.status == CommandStatus.ACCEPTED
    return run_id


@pytest.mark.asyncio
async def test_a_sealed_child_is_fetched_verified_compiled_and_admitted_on_the_real_server(
    common_db: CommonDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = await common_db.pool(max_size=6)
    scope = common_db.scope()
    monkeypatch.setenv("MISSION_CONTROL_AGENT_SERVER_PORT", "0")
    try:
        run_id = await _admitted_parent(common_db, pool)
        async with local_agent_server(
            tmp_path,
            monkeypatch,
            extra_environment={
                "MISSION_CONTROL_SEALED_CHILD_FACTORY": (
                    "tests.fixtures.wi23_sealed_child_hosting:factory"
                ),
                "WI23_TEST_CUSTODY_DSN": common_db.dsn(),
            },
        ) as endpoint:
            base, _profile, _bundle = exact_fixture()
            contract = _sealed_contract(base.model, url=endpoint)
            provider = DeepAgentsAsyncSubagentAdapter(
                secrets={f"environment:{TOKEN_ENV}": os.environ[TOKEN_ENV]},
                request_scope=scope,
            )
            service = AsyncSubagentService(
                PostgresAsyncSubagentDetailRepository(pool),
                PostgresAsyncSubagentAuthority(pool),
                provider,
                allow_new_spawns=True,
            )
            request = spawn(run_id).model_copy(
                update={
                    "request_scope": scope,
                    "contract": contract,
                    "dependency_class": AsyncSubagentDependencyClass.NONBLOCKING,
                    "objective": "Reply PONG",
                }
            )
            child = await service.spawn(request)
            child_id = child.child_execution_id
            async with asyncio.timeout(90):
                while True:
                    execution = await service.reconcile(scope, child_id)
                    if execution.lifecycle == AsyncSubagentLifecycle.COMPLETED:
                        break
                    assert execution.lifecycle not in {
                        AsyncSubagentLifecycle.FAILED,
                        AsyncSubagentLifecycle.IN_DOUBT,
                    }, (execution, (tmp_path / "agent-server.log").read_text(encoding="utf-8"))
                    await asyncio.sleep(0.5)
            manifest = execution.result_manifest
            assert manifest is not None
            # The run was served from the exact sealed binding (the thread stamp).
            assert (
                manifest.provider_checkpoint.graph_binding_digest == contract.graph_binding_digest
            )
            assert manifest.provider_checkpoint.graph_id == "belllabs_async_child"
            parent = cast(
                OperationExecutionBinding,
                SimpleNamespace(request_scope=scope, run_id=run_id, binding_id="binding-1"),
            )
            admitted = await CheckTimeAdmission(service, policies=ASYNC_RESULT_POLICIES).admit(
                parent, contract, execution, current_generation=1
            )
            assert admitted.status == "admitted", admitted
            # The sealed prompt reached the child, and its content blocks are read as text.
            assert admitted.output_text == "SEALED-PROMPT-SEEN PONG for: Reply PONG"

            # Review S2: the sealed graph stamps provider usage, so it is attributed exactly.
            assert manifest.usage.attribution == "provider_attributed"
            assistant_id = sealed_child_assistant_id(scope, contract.graph_binding_digest)
            mine = get_client(
                url=endpoint,
                headers={
                    "Authorization": "Bearer " + mint_scope_claim(os.environ[TOKEN_ENV], scope)
                },
            )
            assistant = await mine.assistants.get(assistant_id)
            assert assistant["graph_id"] == "belllabs_async_child"
            assert assistant["config"]["configurable"][SEALED_BINDING_DIGEST_KEY] == (
                contract.graph_binding_digest
            )
            # Review B1: a bl1 caller still reads and runs the static technical child on its
            # deployment default assistant (system topology, no scope metadata).
            technical = await mine.assistants.get(
                str(uuid5(GRAPH_NAMESPACE, "belllabs_async_technical_child"))
            )
            assert technical["graph_id"] == "belllabs_async_technical_child"
            static_thread = await mine.threads.create(metadata={"request_scope": scope})
            static_result = await mine.runs.wait(
                static_thread["thread_id"],
                "belllabs_async_technical_child",
                input={"messages": [{"role": "user", "content": "say PONG"}]},
            )
            assert static_result["messages"][-1]["content"] == "PONG"
            # Another scope can neither create nor run this scope's sealed assistant.
            other_scope = common_db.scope("tenant-2")
            other = get_client(
                url=endpoint,
                headers={
                    "Authorization": "Bearer "
                    + mint_scope_claim(os.environ[TOKEN_ENV], other_scope)
                },
            )
            sealed_keys = {
                SEALED_BINDING_DIGEST_KEY: contract.graph_binding_digest,
                SEALED_CONTRACT_DIGEST_KEY: contract.contract_digest,
            }
            with pytest.raises(APIStatusError) as denied_create:
                await other.assistants.create(
                    "belllabs_async_child",
                    {"configurable": sealed_keys},
                    metadata=sealed_keys,
                    assistant_id=assistant_id,
                    if_exists="do_nothing",
                )
            assert denied_create.value.status_code in {403, 404, 409}
            thread = await other.threads.create(metadata={"request_scope": other_scope})
            with pytest.raises(APIStatusError) as denied_run:
                await other.runs.create(
                    thread["thread_id"],
                    assistant_id,
                    input={"messages": [{"role": "user", "content": "Reply PONG"}]},
                    metadata=sealed_keys,
                )
            assert denied_run.value.status_code in {403, 404}
            # A follow-up to a completed child is refused before any provider call (the
            # sealed update path itself is proven against a running child offline).
            with pytest.raises(AsyncSubagentError, match="accepts no message"):
                await service.send_message(
                    scope,
                    child_id,
                    payload_ref="Reply PONG again",
                    correlation_id="wi23-update",
                    created_at=datetime.now(UTC),
                )
            runs = await mine.runs.list(child_id)
            assert [run["assistant_id"] for run in runs] == [assistant_id]
    finally:
        await pool.close()
