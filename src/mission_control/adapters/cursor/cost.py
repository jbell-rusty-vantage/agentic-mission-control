"""Attributable Cursor billed cost. Temporal owns delayed rereads, never this reader.

Missing charged_cents stays None; explicit provider zero is a settled zero.
Local billing UUIDs cannot be inferred from client-minted run labels.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, DecimalException, InvalidOperation
from typing import Any

import httpx
from pydantic import SecretStr

# Application composition schedules these delays as Temporal timers, not worker sleeps.
SETTLEMENT_DELAYS_SECONDS = (300, 900)


def charged_micros(cost: Any) -> int | None:
    if cost is None:
        return None
    value = (
        cost.get("charged_cents", cost.get("chargedCents"))
        if isinstance(cost, dict)
        else getattr(cost, "charged_cents", None)
    )
    if value is None or isinstance(value, bool):
        return None
    try:
        cents = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not cents.is_finite() or cents < 0:
        return None
    return int((cents * 10_000).quantize(Decimal(1), rounding=ROUND_HALF_UP))


class SdkCostReader:
    """Connected SDK client: exact per-run record only, no agent-total fallback."""

    def __init__(self, client: Any, api_key: str) -> None:
        self._client = client
        self._api_key = api_key

    async def __call__(self, agent_id: str, run_id: str) -> int | None:
        from cursor_sdk.asyncio import AsyncAgent

        agent = AsyncAgent(
            agent_id=agent_id, client=self._client, model=None, api_key=self._api_key
        )
        usage = await agent.get_usage(run_id=run_id)
        entry = next((item for item in usage.runs if item.run_id == run_id), None)
        return charged_micros(entry.cost) if entry is not None else None


class HttpCostReader:
    """Cloud usage REST cost, proven per-run in research/cursor.md MO-13 receipt.

    No SDK/bridge is required on the cloud worker. Session totals and wrong-run entries
    cannot settle the requested run, even when the HTTP request supplied runId.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    async def __call__(self, agent_id: str, run_id: str) -> int | None:
        from mission_control.adapters.cursor.bridge import FeatureUnavailable, RunNotFound
        from mission_control.adapters.cursor.cloud_api import AgentNotFound

        try:
            response = await self._client.usage(agent_id, run_id)
        except (FeatureUnavailable, RunNotFound, AgentNotFound):
            return None
        for entry in response.get("runs") or ():
            if not isinstance(entry, dict):
                continue
            if (entry.get("id") or entry.get("runId") or entry.get("run_id")) == run_id:
                return charged_micros(entry.get("cost"))
        return None


class LocalBillingReader(SdkCostReader):
    """Existing connected bridge only; caller supplies an attributable native billing UUID.

    No process/agent is launched and no conversation resumed. This connected-client reader
    is limited to the sidecar lifetime; LocalHttpBillingReader owns the post-cleanup read
    transport. Native run labels are not billing UUIDs and are rejected rather than
    heuristically matched to agent totals.
    """

    async def __call__(self, agent_id: str, run_id: str) -> int | None:
        from uuid import UUID

        try:
            UUID(run_id)
        except ValueError:
            return None
        return await super().__call__(agent_id, run_id)


class LocalHttpBillingReader:
    """Read local billing after bridge/workspace shutdown, with no agent lifecycle calls.

    cursor-sdk 1.0.37's bundled static Agent.getUsage uses this same HTTP endpoint for
    local agents. The scoped cost repository must first prove complete native history;
    this reader accepts only exact native agent/billing UUIDs, never run-<uuid> labels.
    It owns only its HTTP connection, independently of the local lane's lifetime.
    """

    MAX_RESPONSE_BYTES = 1_048_576
    MAX_RUNS = 5_000
    DEADLINE_SECONDS = 15

    def __init__(
        self, api_key: SecretStr, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        from mission_control.adapters.cursor.cloud_api import api_client

        self._client = api_client(api_key, transport=transport, timeout=self.DEADLINE_SECONDS)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __call__(self, agent_id: str, run_id: str) -> int | None:
        import asyncio
        import json
        from urllib.parse import quote
        from uuid import UUID

        from mission_control.adapters.cursor.bridge import ProviderTransient

        # Canonical UUID spelling prevents a local identity from becoming a URL route.
        try:
            if any(str(UUID(value)) != value.lower() for value in (agent_id, run_id)):
                return None
        except (ValueError, AttributeError, TypeError):
            return None
        try:
            async with asyncio.timeout(self.DEADLINE_SECONDS):
                async with self._client.stream(
                    "GET",
                    f"/v1/agents/{quote(agent_id, safe='')}/usage",
                    params={"runId": run_id},
                    headers={"Accept-Encoding": "identity"},
                ) as response:
                    # No error body is needed to retain unknown liability. Redirects are
                    # never followed, and no provider text enters the observation journal.
                    if (
                        response.status_code != 200
                        or response.headers.get("Content-Encoding", "identity") != "identity"
                    ):
                        return None
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65_536):
                        if len(body) + len(chunk) > self.MAX_RESPONSE_BYTES:
                            return None
                        body.extend(chunk)
        except (TimeoutError, httpx.TransportError):
            raise ProviderTransient("Cursor billing read timed out or failed") from None
        try:
            payload = json.loads(body, object_pairs_hook=_unique_billing_fields)
        except (ValueError, RecursionError):
            return None
        if not isinstance(payload, dict) or any(
            payload.get(key) for key in ("nextCursor", "next_cursor", "hasMore", "has_more")
        ):
            return None
        if any(key in payload and payload[key] != agent_id for key in ("agentId", "agent_id")):
            return None
        runs = payload.get("runs")
        if not isinstance(runs, list) or len(runs) > self.MAX_RUNS:
            return None
        if any(not isinstance(entry, dict) for entry in runs):
            return None
        matching = [entry for entry in runs if entry.get("id") == run_id]
        if len(matching) != 1:
            return None
        entry = matching[0]
        if any(key in entry and entry[key] != run_id for key in ("runId", "run_id")):
            return None
        if any(key in entry and entry[key] != agent_id for key in ("agentId", "agent_id")):
            return None
        cost = entry.get("cost")
        if not isinstance(cost, dict):
            return None
        # Conflicting spellings and unbounded decimal exponents are not billing facts.
        if "charged_cents" in cost and cost.get("chargedCents") != cost["charged_cents"]:
            return None
        value = cost.get("chargedCents")
        if not isinstance(value, (int, float, str)) or isinstance(value, bool):
            return None
        if len(str(value)) > 64:
            return None
        try:
            return charged_micros(cost)
        except (DecimalException, ValueError, OverflowError):
            return None


def _unique_billing_fields(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate billing response field")
        result[key] = value
    return result
