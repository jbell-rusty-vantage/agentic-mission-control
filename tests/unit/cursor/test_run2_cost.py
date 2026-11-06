from types import SimpleNamespace

import pytest

from mission_control.adapters.cursor.bridge import SdkLocalBridge
from mission_control.adapters.cursor.cost import charged_micros


@pytest.mark.parametrize(
    ("cost", "expected"),
    [
        (None, None),
        ({}, None),
        ({"chargedCents": None}, None),
        ({"chargedCents": 0}, 0),
        ({"chargedCents": 1.25}, 12500),
        ({"chargedCents": "NaN"}, None),
        ({"chargedCents": -1}, None),
    ],
)
def test_charged_cost_is_never_zero_filled(cost, expected):
    assert charged_micros(cost) == expected


async def test_local_agent_totals_and_unattributed_billing_uuid_never_become_run_usage():
    class Agent:
        async def get_usage(self):
            return SimpleNamespace(runs=[], usage=SimpleNamespace(input_tokens=99999), cost=None)

    class Client:
        async def get_run(self, run):
            return SimpleNamespace(id=run, agent_id="a", status="finished", usage=None)

    bridge = SdkLocalBridge(Client(), "fixture", agents={"a": Agent()})
    result = await bridge.usage("a", run_id="run-native")
    assert not result.known and result.cost_micros_usd is None
    assert result.total_tokens == 0


def test_absent_cache_counters_preserve_original_canonical_json():
    from mission_control.domain.execution.lanes import UsageReport

    original = (
        '{"disposition":"settled","input_tokens":11,"output_tokens":7,'
        '"total_tokens":18,"cost_micros_usd":null}'
    )
    report = UsageReport.model_validate_json(original)
    assert report.model_dump_json() == original
    assert report.cache_read_tokens is None and report.cache_write_tokens is None
    known_zero = report.model_copy(update={"cache_read_tokens": 0})
    assert known_zero.model_dump()["cache_read_tokens"] == 0
    assert "cache_write_tokens" not in known_zero.model_dump()


async def test_http_cost_reader_exact_run_late_settlement_no_session_total_fallback():
    from mission_control.adapters.cursor.cost import HttpCostReader

    class Client:
        reads = 0

        async def usage(self, agent, run):
            assert (agent, run) == ("agent", "requested")
            self.reads += 1
            cost = {} if self.reads == 1 else {"chargedCents": 1.25}
            return {
                "cost": {"chargedCents": 999},
                "runs": [
                    {"id": "wrong", "cost": {"chargedCents": 999}},
                    {"id": "requested", "cost": cost},
                ],
            }

    reader = HttpCostReader(Client())
    assert await reader("agent", "requested") is None
    assert await reader("agent", "requested") == 12500
    assert await reader("agent", "requested") == 12500


async def test_local_billing_reader_rejects_native_run_labels_without_launching():
    from mission_control.adapters.cursor.cost import LocalBillingReader

    reader = LocalBillingReader(object(), "fixture-only")
    assert await reader("agent", "run-native-label") is None


LOCAL_AGENT = "00000000-0000-0000-0000-000000000001"
BILLING_RUN = "00000000-0000-0000-0000-000000000002"


async def test_local_http_billing_survives_lane_disposal_and_reads_only_exact_uuid():
    import httpx
    from pydantic import SecretStr

    from mission_control.adapters.cursor.cost import LocalHttpBillingReader

    requests = []

    def respond(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "api.cursor.com"
        assert request.url.path == f"/v1/agents/{LOCAL_AGENT}/usage"
        assert dict(request.url.params) == {"runId": BILLING_RUN}
        assert request.headers["Authorization"] == "Bearer fixture-only"
        cost = {} if len(requests) == 1 else {"chargedCents": 0}
        return httpx.Response(
            200,
            json={
                "cost": {"chargedCents": 999},
                "runs": [
                    {"id": "wrong", "cost": {"chargedCents": 999}},
                    {"id": BILLING_RUN, "cost": cost},
                ],
            },
        )

    # No lane/session/bridge or workspace is supplied or retained by this transport.
    reader = LocalHttpBillingReader(
        SecretStr("fixture-only"), transport=httpx.MockTransport(respond)
    )
    try:
        assert await reader(LOCAL_AGENT, BILLING_RUN) is None
        assert await reader(LOCAL_AGENT, BILLING_RUN) == 0
        assert len(requests) == 2
    finally:
        await reader.aclose()
    assert reader._client.is_closed


@pytest.mark.parametrize(
    ("agent", "run"),
    [
        ("bc-" + LOCAL_AGENT, BILLING_RUN),
        (LOCAL_AGENT, "run-" + BILLING_RUN),
        ("../other?token=x", BILLING_RUN),
        (LOCAL_AGENT, BILLING_RUN.replace("-", "")),
    ],
)
async def test_local_http_billing_invalid_identity_never_sends(agent, run):
    import httpx
    from pydantic import SecretStr

    from mission_control.adapters.cursor.cost import LocalHttpBillingReader

    def unexpected(request):
        pytest.fail("unattributable identity reached billing transport")

    reader = LocalHttpBillingReader(SecretStr("fixture"), transport=httpx.MockTransport(unexpected))
    try:
        assert await reader(agent, run) is None
    finally:
        await reader.aclose()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"runs": []},
        {"runs": [None]},
        {"runs": [{"id": "wrong", "cost": {"chargedCents": 10}}]},
        {"runs": [{"id": BILLING_RUN, "cost": {"chargedCents": 10}}] * 2},
        {"nextCursor": "more", "runs": [{"id": BILLING_RUN, "cost": {"chargedCents": 10}}]},
        {"runs": [{"id": BILLING_RUN, "runId": "wrong", "cost": {"chargedCents": 10}}]},
        {"runs": [{"id": BILLING_RUN, "cost": {"chargedCents": "1e9999999"}}]},
        {"runs": [{"id": BILLING_RUN, "cost": {"chargedCents": True}}]},
        {"runs": [{"id": BILLING_RUN, "cost": {"chargedCents": -1}}]},
        {"runs": [{"id": BILLING_RUN, "cost": {"chargedCents": "NaN"}}]},
        {"runs": [{"id": BILLING_RUN, "cost": {"chargedCents": 10, "charged_cents": 20}}]},
        {"runs": [{}] * 5001},
    ],
)
async def test_local_http_billing_refuses_partial_ambiguous_or_invalid_facts(payload):
    import httpx
    from pydantic import SecretStr

    from mission_control.adapters.cursor.cost import LocalHttpBillingReader

    reader = LocalHttpBillingReader(
        SecretStr("fixture"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )
    try:
        assert await reader(LOCAL_AGENT, BILLING_RUN) is None
    finally:
        await reader.aclose()


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (200, b"x" * 1_048_577),
        (200, b"{bad"),
        (200, b'{"runs":[],"runs":[]}'),
        (302, b"secret provider body"),
        (403, b"secret provider body"),
        (404, b"secret provider body"),
        (500, b"secret provider body"),
    ],
    ids=["oversize", "malformed", "duplicate-key", "redirect", "forbidden", "missing", "error"],
)
async def test_local_http_billing_bounded_response_and_no_redirect(status, body):
    import httpx
    from pydantic import SecretStr

    from mission_control.adapters.cursor.cost import LocalHttpBillingReader

    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status, content=body, headers={"Location": "https://untrusted.invalid"}
        )

    reader = LocalHttpBillingReader(SecretStr("fixture"), transport=httpx.MockTransport(respond))
    try:
        assert await reader(LOCAL_AGENT, BILLING_RUN) is None
        assert len(calls) == 1
    finally:
        await reader.aclose()


async def test_local_http_billing_total_deadline_sanitizes_stream_error(monkeypatch):
    import asyncio

    import httpx
    from pydantic import SecretStr

    from mission_control.adapters.cursor.bridge import ProviderTransient
    from mission_control.adapters.cursor.cost import LocalHttpBillingReader

    class Stream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            await asyncio.sleep(5)
            yield b"secret provider body"

        async def aclose(self):
            self.closed = True

    stream = Stream()
    reader = LocalHttpBillingReader(
        SecretStr("fixture"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream)),
    )
    monkeypatch.setattr(reader, "DEADLINE_SECONDS", 0.01)
    try:
        with pytest.raises(ProviderTransient) as failure:
            await reader(LOCAL_AGENT, BILLING_RUN)
        assert "secret" not in str(failure.value)
        assert stream.closed
    finally:
        await reader.aclose()


@pytest.mark.parametrize("location", ["response", "run"])
@pytest.mark.parametrize("key", ["agentId", "agent_id"])
async def test_local_http_billing_refuses_foreign_agent_readback(location, key):
    import httpx
    from pydantic import SecretStr

    from mission_control.adapters.cursor.cost import LocalHttpBillingReader

    payload = {"runs": [{"id": BILLING_RUN, "cost": {"chargedCents": 10}}]}
    target = payload if location == "response" else payload["runs"][0]
    target[key] = "00000000-0000-0000-0000-000000000009"
    reader = LocalHttpBillingReader(
        SecretStr("fixture"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )
    try:
        assert await reader(LOCAL_AGENT, BILLING_RUN) is None
    finally:
        await reader.aclose()
