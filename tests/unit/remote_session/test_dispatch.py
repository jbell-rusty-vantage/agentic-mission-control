"""HL-04: deterministic create ids, metadata reconciliation, dispatch keys and turn anchors."""

from __future__ import annotations

from uuid import UUID

from mission_control.adapters.remote_session.dispatch import (
    DISPATCH_METADATA_KEY,
    NEUTRAL_ANCHOR_DETAILS,
    AnchorDetails,
    DispatchKeyParts,
    TurnAnchors,
    client_session_id,
    created_by,
    dispatch_metadata,
    lookup_created,
    parse_dispatch_key,
)

NAMESPACE = UUID("00000000-0000-4000-8000-000000000001")


def test_a_create_id_is_deterministic_per_execution_and_generation() -> None:
    first = client_session_id(NAMESPACE, "heid-1", 1, prefix="s-")
    assert first == client_session_id(NAMESPACE, "heid-1", 1, prefix="s-")
    assert first.startswith("s-") and UUID(first.removeprefix("s-"))
    assert first != client_session_id(NAMESPACE, "heid-1", 2, prefix="s-")
    assert first != client_session_id(NAMESPACE, "heid-2", 1, prefix="s-")
    assert client_session_id(NAMESPACE, "heid-1", 1) == first.removeprefix("s-")


def test_dispatch_keys_name_execution_generation_kind_and_turn() -> None:
    assert parse_dispatch_key("heid:2:turn:3") == DispatchKeyParts("heid", 2, "turn", 3)
    assert parse_dispatch_key("heid:1:continuation:t-1") == DispatchKeyParts(
        "heid", 1, "continuation", None
    )
    assert parse_dispatch_key("heid:1:replace:run:with:colons") == DispatchKeyParts(
        "heid", 1, "replace", None
    )
    assert parse_dispatch_key("heid:x:turn:1") is None
    assert parse_dispatch_key("heid:1:turn") is None


def _sessions(*pairs: tuple[str, str | None]) -> list[dict[str, object]]:
    return [
        {"id": ref, "metadata": {DISPATCH_METADATA_KEY: key} if key else {}} for ref, key in pairs
    ]


def test_a_non_idempotent_create_is_found_again_by_its_metadata() -> None:
    metadata = dispatch_metadata(run_key="run-1", generation=2, dispatch_key="heid:2:turn:1")
    assert metadata == {"mc_run": "run-1", "mc_generation": "2", "mc_dispatch": "heid:2:turn:1"}
    listed = _sessions(("s-0", "heid:1:turn:1"), ("s-1", "heid:2:turn:1"), ("s-2", None))
    listed.append({"id": "s-3", "metadata": "not a mapping"})
    assert [item["id"] for item in created_by(listed, "heid:2:turn:1")] == ["s-1"]
    found = lookup_created(listed, "heid:2:turn:1")
    assert (found.outcome, found.native_ref, found.detail) == ("found", "s-1", "")


def test_duplicate_creates_adopt_the_first_listed_and_name_the_others() -> None:
    listed = _sessions(("s-1", "k"), ("s-2", "k"), ("s-3", "k"))
    found = lookup_created(listed, "k")
    assert (found.outcome, found.native_ref) == ("found", "s-1")
    assert found.detail == "duplicate creates: s-2, s-3"
    by_field = lookup_created(
        [{"session_id": "x", "metadata": {"mc_dispatch": "k"}}], "k", id_field="session_id"
    )
    assert by_field.native_ref == "x"


def test_absence_from_a_listing_is_not_authoritative_unless_the_provider_says_so() -> None:
    assert lookup_created([], "k").outcome == "unknown"
    assert lookup_created([], "k", absent="not_received").outcome == "not_received"


def test_turn_anchors_judge_a_lost_send_by_the_latest_turn() -> None:
    anchors = TurnAnchors()
    unanchored = anchors.lookup_latest("k-2", "turn-2")
    assert unanchored.outcome == "unknown"
    assert unanchored.detail == NEUTRAL_ANCHOR_DETAILS.unanchored
    anchors.acknowledge("turn-1", "k-1")
    assert anchors.sent == {"k-1": "turn-1"}
    assert anchors.lookup_latest("k-2", None).detail == NEUTRAL_ANCHOR_DETAILS.no_latest
    in_flight = anchors.lookup_latest("k-2", "turn-1")
    assert in_flight.outcome == "unknown" and "in flight" in in_flight.detail
    accepted = anchors.lookup_latest("k-2", "turn-2")
    assert (accepted.outcome, accepted.native_ref) == ("found", "turn-2")
    assert anchors.sent["k-2"] == "turn-2" and "turn-2" in anchors.known


def test_the_journal_anchor_counts_and_details_speak_the_providers_nouns() -> None:
    anchors = TurnAnchors()
    anchors.anchor("run-7")
    assert anchors.observed() == {"run-7"} and anchors.journal_anchor == "run-7"
    anchors.known.discard("run-7")
    assert anchors.observed() == {"run-7"}, "the journal anchor survives on its own"
    details = AnchorDetails(unanchored="u", no_latest="n", acknowledged="a")
    assert anchors.lookup_latest("k", "run-7", details=details).detail == "a"
    assert TurnAnchors().lookup_latest("k", "run-8", details=details).detail == "u"
