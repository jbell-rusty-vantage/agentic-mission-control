from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from mission_control.application.signals.drainer import DrainItem, DrainRejected, IngressDrainer


def item(attempts=0):
    return DrainItem(
        uuid4(),
        "scope",
        uuid4(),
        "ai-engineer",
        "signal.test",
        "credential",
        "delivery",
        {},
        datetime.now(UTC),
        generation=1,
        attempts=attempts,
    )


class Store:
    def __init__(self, value):
        self.items = [value]
        self.settled = []
        self.deferred = []
        self.committed = False

    @asynccontextmanager
    async def claim_batch(self, limit):
        yield self
        self.committed = True

    async def defer(self, value, outcome):
        self.deferred.append((value, outcome))

    async def settle(self, *args):
        self.settled.append(args)


class Effects:
    def __init__(self):
        self.frames = set()
        self.fail = True

    async def persist(self, value):
        self.frames.add(value.effect_key)
        return {"frame_persisted": True}

    async def wake(self, value):
        if self.fail:
            raise RuntimeError("secret credential must never be stored")


@pytest.mark.asyncio
async def test_persist_before_wake_replay_one_frame():
    store, effects = Store(item()), Effects()
    drainer = IngressDrainer(store, effects)
    await drainer.drain_once()
    assert store.settled[-1][1:] == (
        "pending",
        {"frame_persisted": True, "reason": "delivery_failed"},
        "delivery_failed",
    )
    effects.fail = False
    await drainer.drain_once()
    assert len(effects.frames) == 1
    assert store.settled[-1][1] == "drained"


@pytest.mark.asyncio
async def test_failure_dead_after_bound_and_static_reason():
    store = Store(item(attempts=4))
    await IngressDrainer(store, Effects()).drain_once()
    assert store.settled[0][1] == "dead"
    assert "secret" not in repr(store.settled)


@pytest.mark.asyncio
async def test_typed_refusal_never_wakes():
    class Rejected(Effects):
        async def persist(self, value):
            raise DrainRejected("stale_generation")

        async def wake(self, value):
            pytest.fail("refused evidence must not wake")

    store = Store(item())
    await IngressDrainer(store, Rejected()).drain_once()
    assert store.settled[0][1:] == ("rejected", {"reason": "stale_generation"})


def test_effect_identity_preserves_database_dedupe_spaces():
    from dataclasses import replace

    value = item()
    gate = replace(value, kind="gate.decision")
    assert value.effect_key != gate.effect_key
    assert value.effect_key == replace(value, kind="signal.other").effect_key


@pytest.mark.asyncio
async def test_pending_receipt_commits_before_enqueue_and_never_wakes_or_spends_attempts():
    from mission_control.application.signals.drainer import DrainDeferred

    store = Store(item(attempts=4))
    order = []

    class Pending:
        async def persist(self, value):
            async def enqueue():
                assert store.committed
                order.append("enqueue")

            raise DrainDeferred({"receipt": "trusted"}, after_commit=enqueue)

        async def wake(self, value):
            pytest.fail("native history has not been acknowledged")

    # Returning zero makes a completely deferred batch take the normal polling pause.
    assert await IngressDrainer(store, Pending(), batch_size=1).drain_once() == 0
    assert order == ["enqueue"] and not store.settled
    assert store.deferred[0][0].attempts == 4
    assert store.deferred[0][1] == {"receipt": "trusted"}


@pytest.mark.asyncio
async def test_enqueue_crash_retains_committed_receipt_for_retry():
    from mission_control.application.signals.drainer import DrainDeferred

    store = Store(item())

    class Pending:
        async def persist(self, value):
            async def enqueue():
                assert store.committed
                raise ConnectionError("database temporarily unavailable")

            raise DrainDeferred({"receipt": "trusted"}, after_commit=enqueue)

        async def wake(self, value):
            pytest.fail("no acknowledgment")

    assert await IngressDrainer(store, Pending()).drain_once() == 0
    assert store.deferred and not store.settled


@pytest.mark.asyncio
async def test_rejected_hint_retains_original_receipt_and_never_wakes():
    from dataclasses import replace

    value = replace(item(), outcome={"reconciliation_request": {"original": "binding"}})
    store = Store(value)

    class Rejected:
        async def persist(self, value):
            raise DrainRejected("webhook_stale_generation")

        async def wake(self, value):
            pytest.fail("rejection is not successful native history")

    assert await IngressDrainer(store, Rejected()).drain_once() == 1
    assert store.settled[0][1] == "rejected"
    assert store.settled[0][2]["reconciliation_request"] == {"original": "binding"}
