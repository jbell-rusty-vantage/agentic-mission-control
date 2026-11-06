"""MO-11 acceptance: a minted token expires and is bound; wrong-run use is rejected.

`mint:signal_token` issues a random `mct_` token bound to one scope, run, unit and generation
with the `signal:write` scope only; the store keeps its digest, never its value.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from mission_control.adapters.secrets.minted import InMemoryMintedCredentialStore
from mission_control.application.secrets.minting import (
    MINT_PURPOSES,
    MISSION_REQUEST,
    SIGNAL_TOKEN,
    TOKEN_PATTERN,
    CredentialBinding,
    CredentialMinter,
    CredentialRejected,
    LaunchBinding,
    MintPurpose,
    token_digest,
)

BINDING = CredentialBinding(
    request_scope="mc/installation/biotech/tenant", run_id="run-1", unit_id="unit-a", generation=1
)
START = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


def minter() -> tuple[CredentialMinter, InMemoryMintedCredentialStore, Clock]:
    store = InMemoryMintedCredentialStore()
    clock = Clock()
    return CredentialMinter(store, clock=clock), store, clock


async def test_a_signal_token_is_bound_scoped_and_stored_as_a_digest_only() -> None:
    credentials, store, _clock = minter()
    token = await credentials.mint("signal_token", BINDING)

    assert TOKEN_PATTERN.fullmatch(token.value)
    assert token.value not in repr(token)
    record = await store.by_digest(token_digest(token.value))
    assert record is not None and record == token.record
    assert record.binding == BINDING and record.scopes == ("signal:write",)
    assert record.expires_at == START + timedelta(hours=24)
    assert token.value not in repr(record) and token.value not in str(store._records)

    verified = await credentials.verify(
        token.value, purpose="signal_token", binding=BINDING, scope="signal:write"
    )
    assert verified.credential_id == record.credential_id


@pytest.mark.parametrize(
    "other",
    [
        replace(BINDING, run_id="run-2"),
        replace(BINDING, unit_id="unit-b"),
        replace(BINDING, generation=2),
        replace(BINDING, request_scope="mc/installation/biotech/other-tenant"),
    ],
    ids=["run", "unit", "generation", "scope"],
)
async def test_use_for_another_run_unit_generation_or_scope_is_rejected(
    other: CredentialBinding,
) -> None:
    credentials, _store, _clock = minter()
    token = await credentials.mint("signal_token", BINDING)
    with pytest.raises(CredentialRejected) as rejected:
        await credentials.verify(token.value, purpose="signal_token", binding=other)
    assert rejected.value.reason == "wrong_binding"
    assert token.value not in str(rejected.value)


async def test_the_token_expires_at_its_lifetime_or_the_mission_deadline() -> None:
    credentials, _store, clock = minter()
    token = await credentials.mint("signal_token", BINDING)
    clock.now = START + timedelta(hours=24) - timedelta(seconds=1)
    await credentials.verify(token.value, purpose="signal_token", binding=BINDING)
    clock.now = START + timedelta(hours=24)
    with pytest.raises(CredentialRejected) as expired:
        await credentials.verify(token.value, purpose="signal_token", binding=BINDING)
    assert expired.value.reason == "expired"

    clock.now = START
    deadline = START + timedelta(hours=2)
    early = await credentials.mint("signal_token", BINDING, deadline=deadline)
    assert early.record.expires_at == deadline
    clock.now = deadline
    with pytest.raises(CredentialRejected, match="expired"):
        await credentials.verify(early.value, purpose="signal_token", binding=BINDING)
    with pytest.raises(ValueError, match="deadline has passed"):
        await credentials.mint("signal_token", BINDING, deadline=START)


async def test_unknown_purpose_and_scope_mismatches_are_rejected() -> None:
    credentials, _store, _clock = minter()
    token = await credentials.mint("signal_token", BINDING)
    with pytest.raises(CredentialRejected, match="unknown"):
        await credentials.verify("mct_" + "x" * 43, purpose="signal_token", binding=BINDING)
    with pytest.raises(CredentialRejected, match="wrong_purpose"):
        await credentials.verify(token.value, purpose="mission_request", binding=BINDING)
    with pytest.raises(CredentialRejected, match="insufficient_scope"):
        await credentials.verify(
            token.value, purpose="signal_token", binding=BINDING, scope="mission:request"
        )
    with pytest.raises(ValueError, match="not a purpose"):
        await credentials.mint("org_api_key", BINDING)


async def test_a_new_generation_and_a_terminal_run_revoke_earlier_tokens() -> None:
    credentials, _store, _clock = minter()
    first = await credentials.mint("signal_token", BINDING)
    other_unit = await credentials.mint("signal_token", replace(BINDING, unit_id="unit-b"))
    second_binding = replace(BINDING, generation=2)
    second = await credentials.mint("signal_token", second_binding)

    assert await credentials.revoke_superseded(second_binding) == 1
    with pytest.raises(CredentialRejected, match="revoked"):
        await credentials.verify(first.value, purpose="signal_token", binding=BINDING)
    await credentials.verify(second.value, purpose="signal_token", binding=second_binding)

    assert await credentials.revoke_run(BINDING.request_scope, BINDING.run_id) == 2
    for token, binding in ((second, second_binding), (other_unit, other_unit.record.binding)):
        with pytest.raises(CredentialRejected, match="revoked"):
            await credentials.verify(token.value, purpose="signal_token", binding=binding)


async def test_the_purpose_table_is_extended_by_one_entry() -> None:
    model_gateway = MintPurpose(
        "model_gateway", ("model:invoke",), timedelta(hours=1), rate_limit_per_minute=60
    )
    store = InMemoryMintedCredentialStore()
    credentials = CredentialMinter(
        store, purposes={**MINT_PURPOSES, model_gateway.name: model_gateway}
    )
    token = await credentials.mint("model_gateway", BINDING)
    assert token.record.scopes == ("model:invoke",)
    assert token.record.rate_limit_per_minute == 60
    assert MINT_PURPOSES == {"signal_token": SIGNAL_TOKEN, "mission_request": MISSION_REQUEST}


async def test_a_launch_credential_is_bound_to_a_tenant_scope_never_a_run() -> None:
    # MO-40: the operator launch credential of the Signal Ingress launch route (R29).
    credentials, store, _clock = minter()
    scope = LaunchBinding(BINDING.request_scope)
    token = await credentials.mint(
        "mission_request", scope, context={"manifest_refs": ["mission:report@1"]}
    )
    record = await store.by_digest(token_digest(token.value))
    assert record is not None and record.binding == scope
    assert record.scopes == ("mission:request",) and record.rate_limit_per_minute == 30
    assert record.context == {"manifest_refs": ["mission:report@1"]}
    assert record.expires_at == START + timedelta(days=7)
    await credentials.verify(
        token.value, purpose="mission_request", binding=scope, scope="mission:request"
    )

    with pytest.raises(ValueError, match="tenant scope only"):
        await credentials.mint("mission_request", BINDING)
    with pytest.raises(ValueError, match="bound to a run"):
        await credentials.mint("signal_token", scope)
    with pytest.raises(ValueError, match="never carries a secret"):
        await credentials.mint("signal_token", BINDING, context={"token": "value"})
    # A run's revocation never touches a launch credential.
    assert await credentials.revoke_run(BINDING.request_scope, BINDING.run_id) == 0
