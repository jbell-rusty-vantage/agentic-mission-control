"""MO-41: `signal_emit` on the Mission Control signals MCP server (SPEC-04 section 4.1).

The tool is served over Streamable HTTP on the ingress app and authenticates with the request's
own bearer, exactly as `POST signals` does; an in-memory store records what the service would
write. The real store is exercised in
tests/integration/postgres/test_telemetry_pack_ingress_postgres.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from mission_control.application.secrets.minting import token_digest
from mission_control.application.signals.contracts import TrustTier
from mission_control.interfaces.http.ingress import create_ingress_app
from mission_control.interfaces.mcp.coordinator_http_client import CoordinatorStreamableHttpClient
from mission_control.interfaces.mcp.signal_tools import SIGNAL_EMIT_TOOL, mount_signal_tools
from tests.unit.signals.test_ingress_service import TOKEN, FakeStore, service

PATH = "/v1/ingress/biotech/mcp/"


@asynccontextmanager
async def signals_client(
    store: FakeStore, token: str | None = TOKEN, path: str = PATH
) -> AsyncIterator[CoordinatorStreamableHttpClient]:
    ingress = service(store)
    app = create_ingress_app([ingress])
    mcp = mount_signal_tools(app, [ingress])
    headers = {"accept": "application/json, text/event-stream"}
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    async with (
        mcp.router.lifespan_context(mcp),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1", headers=headers
        ) as http,
    ):
        client = CoordinatorStreamableHttpClient(http, path)
        await client.initialize()
        yield client


async def test_signal_emit_records_one_signal_with_the_callers_run_token() -> None:
    store = FakeStore()
    async with signals_client(store) as client:
        assert [tool.name for tool in await client.list_tools()] == [SIGNAL_EMIT_TOOL]
        result = await client.call_tool(
            SIGNAL_EMIT_TOOL,
            {
                "type": "milestone",
                "message": "tests green",
                "data": {"passed": 412},
                "signal_id": "retry-1",
            },
        )

    assert result.data == {"ok": True, "signal_id": "retry-1", "accepted": 1, "duplicates": 0}
    ((call, principal, (item,)),) = store.calls
    assert call == "accept"
    assert (principal.tier, principal.credential) == (TrustTier.RUN_TOKEN, token_digest(TOKEN))
    assert (item.kind, item.dedupe_key, item.seq) == ("signal.milestone", "retry-1", None)
    assert item.payload["data"] == {"passed": 412, "message": "tests green", "source": "mcp"}


async def test_signal_emit_mints_a_signal_id_when_none_is_given() -> None:
    store = FakeStore()
    async with signals_client(store) as client:
        result = await client.call_tool(SIGNAL_EMIT_TOOL, {"type": "blocked"})
    assert isinstance(result.data, dict) and result.data["ok"] is True
    assert str(result.data["signal_id"]).startswith("mcp-")
    ((_call, _principal, (item,)),) = store.calls
    assert item.dedupe_key == result.data["signal_id"] and item.kind == "signal.blocked"


async def test_signal_emit_answers_refusals_as_typed_receipts() -> None:
    store = FakeStore()
    async with signals_client(store, token=None) as client:
        refused = await client.call_tool(SIGNAL_EMIT_TOOL, {"type": "milestone"})
    assert refused.data == {"ok": False, "error": {"code": "missing_credential", "status": 401}}

    async with signals_client(store) as client:
        invalid = await client.call_tool(SIGNAL_EMIT_TOOL, {"type": "Not A Type"})
    assert invalid.data == {"ok": False, "error": {"code": "invalid_item", "status": 422}}

    async with signals_client(store, path="/v1/ingress/other/mcp/") as client:
        unknown = await client.call_tool(SIGNAL_EMIT_TOOL, {"type": "milestone"})
    assert unknown.data == {"ok": False, "error": {"code": "unknown_application", "status": 404}}

    revoked = FakeStore(outcome="revoked")
    async with signals_client(revoked) as client:
        result = await client.call_tool(SIGNAL_EMIT_TOOL, {"type": "milestone"})
    assert result.data == {"ok": False, "error": {"code": "revoked", "status": 401}}
    assert store.calls == [], "nothing reached the store without a valid signal and credential"
