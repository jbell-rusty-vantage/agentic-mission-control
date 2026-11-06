"""Production local signal composition with restricted PostgreSQL pools and real HTTP."""

from __future__ import annotations

from contextlib import AsyncExitStack
from types import SimpleNamespace

import httpx
import pytest

from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.adapters.temporal.deployment_composition import compose_hook_callbacks
from mission_control.adapters.temporal.local_signals import LocalSignalDelivery, ScopedSecretMinter
from mission_control.application.secrets.broker import SecretBroker, SecretUnavailable
from mission_control.bootstrap.signals import compose_signal_ingress, verify_signal_ingress_pool
from mission_control.bootstrap.worker import start_hook_callback_listener
from mission_control.domain.execution.bindings import EnvironmentBinding
from mission_control.interfaces.mcp.coordinator_http_client import CoordinatorStreamableHttpClient
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.integration.postgres.test_signal_ingress_postgres import Ingress, ingress  # noqa: F401

pytestmark = pytest.mark.common_db


async def test_local_delivery_reaches_the_worker_ingress_and_signal_mcp(
    ingress: Ingress,  # noqa: F811
) -> None:
    service = compose_signal_ingress(
        ingress.edge, installation_id=ingress.db.installation_id, application_id="biotech"
    )
    await verify_signal_ingress_pool(ingress.edge)
    with pytest.raises(RuntimeError, match="dedicated restricted"):
        await verify_signal_ingress_pool(ingress.runtime)
    broker = SecretBroker(
        environment=WorkerEnvironmentSource(), minter=ScopedSecretMinter(ingress.runtime)
    )
    identity = SimpleNamespace(
        request_scope=ingress.scope,
        run_key=ingress.run_key,
        activation_key=ingress.unit_key,
        attempt_no=1,
    )
    async with AsyncExitStack() as stack:
        server = await start_hook_callback_listener(
            stack, compose_hook_callbacks(ingress.runtime), port=0, ingress=(service,)
        )
        port = server.servers[0].sockets[0].getsockname()[1]
        delivery = LocalSignalDelivery(broker, ingress.runtime, port=port)
        environment = await delivery.environment(
            EnvironmentBinding(kind="local_workspace", host_profile="codex"), identity
        )
        token = environment.values["MC_SIGNAL_TOKEN"]
        assert token not in repr(environment)
        headers = {"authorization": f"Bearer {token}"}
        async with httpx.AsyncClient() as client:
            response = await client.post(
                environment.values["MC_SIGNAL_URL"],
                headers=headers,
                json={"signal_id": "local-http", "type": "milestone", "data": {}},
            )
        assert response.status_code == 202 and response.json()["accepted"] == 1
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            headers={**headers, "accept": "application/json, text/event-stream"},
        ) as http:
            mcp = CoordinatorStreamableHttpClient(http, "/v1/ingress/biotech/mcp/")
            await mcp.initialize()
            result = await mcp.call_tool(
                "signal_emit", {"type": "milestone", "signal_id": "local-mcp"}
            )
        assert result.data == {"ok": True, "signal_id": "local-mcp", "accepted": 1, "duplicates": 0}
    rows = await ingress.inbox()
    assert len(rows) == 2
    assert all(row["trust_tier"] == "run_token" for row in rows)


async def test_observation_off_delivers_no_automatic_signal_credential(
    ingress: Ingress,  # noqa: F811
) -> None:
    broker = SecretBroker(environment=WorkerEnvironmentSource())
    delivered = await LocalSignalDelivery(broker, ingress.runtime, port=1).environment(
        EnvironmentBinding(
            kind="local_workspace", host_profile="codex", in_environment_observation=False
        ),
        SimpleNamespace(
            request_scope=ingress.scope,
            run_key=ingress.run_key,
            activation_key=ingress.unit_key,
            attempt_no=1,
        ),
    )
    assert not delivered.values
    with pytest.raises(SecretUnavailable, match="must reference mint:signal_token"):
        await LocalSignalDelivery(broker, ingress.runtime, port=1).environment(
            EnvironmentBinding(
                kind="local_workspace",
                host_profile="codex",
                secret_refs=("MC_SIGNAL_TOKEN=environment:OPENAI_API_KEY;agent",),
            ),
            SimpleNamespace(),
        )
