"""Offline spend-boundary regressions; synthetic usage is confined to these tests."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from tests.fixtures.qualia_runtime import SpendLedger


def test_reservation_survives_restart_and_blocks_dispatch(tmp_path):
    first = SpendLedger(tmp_path, limit=3)
    first.reserve("unresolved", {"messages": "source"}, {"model": "gpt-6.1-sol"})
    resumed = SpendLedger(tmp_path, limit=3)
    with pytest.raises(ValueError, match="dollar budget exhausted"):
        resumed.reserve("another", "request", {"model": "gpt-6.1-sol"})
    assert resumed.reservations == {"unresolved": 2.0}


def test_large_bounded_source_context_and_true_usage_settlement(tmp_path):
    ledger = SpendLedger(tmp_path)
    coordinates = {"model": "gpt-6.1-sol"}
    ledger.reserve("actual-observer-shape", "x" * 200_000, coordinates)
    message = AIMessage(
        content="offline test",
        usage_metadata={
            "input_tokens": 100000,
            "output_tokens": 1000,
            "total_tokens": 101000,
        },
    )
    ledger.complete(
        "actual-observer-shape",
        SimpleNamespace(
            generations=[[SimpleNamespace(message=message)]],
        ),
        coordinates,
    )
    assert ledger.spent == pytest.approx(0.26)
    assert not ledger.reservations
    assert SpendLedger(tmp_path).spent == pytest.approx(0.26)
    with pytest.raises(ValueError, match="request byte budget"):
        ledger.reserve("too-large", "x" * 700000, coordinates)
    assert "too-large" not in ledger.reservations


def test_fork_context_bound_remains_covered_by_the_existing_reservation(tmp_path):
    ledger = SpendLedger(tmp_path, limit=2)
    ledger.reserve("seeded-fork", "x" * 699998, {"model": "gpt-6.1-sol"})
    assert ledger.reservations == {"seeded-fork": 2.0}
    # A pessimistic token per serialized byte, no cache discount, and the entire
    # actual 16k output allowance fit the USD2 pre-dispatch reservation (USD1.91).
    assert ledger.reservations["seeded-fork"] > (700000 * 2.5 + 16000 * 10) / 1_000_000
    with pytest.raises(ValueError, match="dollar budget exhausted"):
        ledger.reserve("concurrent", "bounded", {"model": "gpt-6.1-sol"})
