"""The public Deep Agents read tool returns only verified, bounded selected content."""

from collections import deque
from dataclasses import replace

import pytest

from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION
from tests.fixtures.knowledge_binding import report_package
from tests.unit.knowledge.test_gateway import TENANT
from tests.unit.knowledge.test_knowledge_tools import lane


@pytest.mark.parametrize("failure", [None, "digest", "size", "encoding"])
async def test_selected_read_through_deep_adapter(failure: str | None) -> None:
    h = lane()
    body = b"Model X has 7B parameters."
    if failure == "size":
        body = b"x" * 262_145
    if failure == "encoding":
        body = b"\xff"
    package = report_package("exact-read", "1", tenant=TENANT, body=body)
    if failure == "digest":
        package = replace(package, served_body=b"Model X has 9B parameters.")
    h.fake.register_package(package)
    h.fake.operation_statuses["knowledge.read"] = deque(["succeeded"])
    token = CURRENT_INVOCATION.set(h.live())
    try:
        result = await h.call(
            "knowledge_read",
            {
                "handle": f"kh:{package.report.binding}/report/exact-read@research-report.v2",
                "digest": package.report.digest,
            },
            "read-1",
        )
    finally:
        CURRENT_INVOCATION.reset(token)
    if failure:
        assert not result["ok"]
        assert (
            result["refusal"]["code"]
            == {
                "digest": "DIGEST_MISMATCH",
                "size": "CONTENT_LIMIT_EXCEEDED",
                "encoding": "SCHEMA_UNSUPPORTED",
            }[failure]
        )
        assert "content" not in (result.get("result") or {})
    else:
        assert result["ok"], result
        answer = result["result"]
        assert answer["status"] == "succeeded" and answer["result_ref"]["digest"]
        assert answer["content"]["body"] == body.decode()
        assert answer["content"]["manifest"]["report"]["digest"] == package.report.digest
    assert len(h.fake.calls_of("invoke")) == 1


@pytest.mark.parametrize("extra", [None, "body", "ledger"])
async def test_member_read_exposes_only_selected_records_without_body_or_ledger(
    extra: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = lane()
    package = h.fake.register_package(
        report_package("members", "1", tenant=TENANT, assertions=("a-1", "a-2"))
    )
    member, _ = package.member_handles("assertion")[0]
    h.fake.operation_statuses["knowledge.read"] = deque(["succeeded"])
    original_fetch = h.fake.fetch

    async def fetch(result_ref, credentials):
        result = await original_fetch(result_ref, credentials)
        return replace(result, **{extra: b"unselected secret"}) if extra else result

    monkeypatch.setattr(h.fake, "fetch", fetch)
    token = CURRENT_INVOCATION.set(h.live())
    try:
        result = await h.call(
            "knowledge_read",
            {
                "handle": f"kh:{package.report.binding}/report/members@research-report.v2",
                "digest": package.report.digest,
                "members": [member.model_dump(mode="json", exclude={"tenant", "binding"})],
            },
            "member-read",
        )
    finally:
        CURRENT_INVOCATION.reset(token)
    if extra:
        assert not result["ok"] and result["refusal"]["code"] == "PARTIAL_PACKAGE"
        assert "unselected secret" not in str(result)
        return
    assert result["ok"], result
    content = result["result"]["content"]
    assert content["body"] == content["ledger"] == ""
    assert [item["handle"]["id"] for item in content["manifest"]["assertions"]] == ["a-1"]
