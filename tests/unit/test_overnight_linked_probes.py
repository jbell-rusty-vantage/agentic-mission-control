"""The injected lost ACK never substitutes for a real governed launch receipt."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.fixtures.overnight_linked_probes import (
    DeliveryAcknowledgementLost,
    LinkedProbe,
    LostAcknowledgementStore,
)


@pytest.mark.asyncio
async def test_ack_loss_requires_real_start_then_redelivery_uses_normal_ack():
    ordinary = SimpleNamespace(mark_delivered=AsyncMock())
    probe = LinkedProbe("duplicate")
    store = LostAcknowledgementStore(ordinary, probe)
    with pytest.raises(AssertionError, match="real start receipt"):
        await store.mark_delivered("scope", "actual-key", lease_owner="relay", delivered_at=None)
    assert not probe.acknowledgement_lost
    probe.starts.append({"receipt": {"already_started": False}})
    with pytest.raises(DeliveryAcknowledgementLost):
        await store.mark_delivered("scope", "actual-key", lease_owner="relay", delivered_at=None)
    ordinary.mark_delivered.assert_not_awaited()
    await store.mark_delivered("scope", "actual-key", lease_owner="relay", delivered_at=None)
    ordinary.mark_delivered.assert_awaited_once()
    assert probe.lost_delivery_key == "actual-key"


@pytest.mark.asyncio
async def test_relay_probe_does_not_swallow_unrelated_delivery_failure():
    probe = LinkedProbe("duplicate")
    relay = SimpleNamespace(relay_once=AsyncMock(side_effect=RuntimeError("real boundary failure")))
    with pytest.raises(RuntimeError, match="real boundary failure"):
        await probe.relay_once(relay, "scope", now=None)
