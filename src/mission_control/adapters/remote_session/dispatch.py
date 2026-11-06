"""Telling whether a lost create or send was accepted (ADR-0052; MP-06 dispatch journal).

Provider session APIs disagree on idempotency: Cursor takes a client-chosen agent id, Managed
Agents and the Agents API take neither an id nor an idempotency key on create. The shared rules:

- a create the lane can name in advance uses a deterministic id (`client_session_id`, uuid5 of
  the harness execution and generation), so a provider `404` under that id is the authoritative
  "not received";
- a create the lane cannot name is stamped with `dispatch_metadata` and reconciled by listing
  the provider's sessions and matching that metadata on the client (`lookup_created`); absence
  from a listing is not authoritative unless the provider adapter says so;
- a later send is reconciled against `TurnAnchors`: the native turns this lane acknowledged and
  the one the journal acknowledged. A latest turn that is none of ours was accepted; a latest
  turn that is one of ours cannot rule out a send still in flight, so it stays `unknown` and the
  unit parks `in_doubt`.

The dispatch key a lane journals is `<harness execution>:<generation>:<kind>:<detail>`
(`turn:<n>` for a create and the turn sends, `continuation:<transfer>` for a handover,
`replace:<turn>` for a replacement); `parse_dispatch_key` reads it back.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, NamedTuple
from uuid import UUID, uuid5

from mission_control.application.execution.harness.dispatch import DispatchLookup, LookupOutcome

DISPATCH_METADATA_KEY: Final = "mc_dispatch"


def client_session_id(
    namespace: UUID, harness_execution_id: str, generation: int, *, prefix: str = ""
) -> str:
    """The deterministic id a create sends, so a lost response never duplicates a session."""

    return f"{prefix}{uuid5(namespace, f'{harness_execution_id}:{generation}')}"


@dataclass(frozen=True)
class DispatchKeyParts:
    """What a Mission Control dispatch key names."""

    harness_execution_id: str
    generation: int
    kind: str
    turn_no: int | None


def parse_dispatch_key(key: str) -> DispatchKeyParts | None:
    parts = key.split(":", 3)
    if len(parts) != 4 or not parts[1].isdigit():
        return None
    turn_no = int(parts[3]) if parts[2] == "turn" and parts[3].isdigit() else None
    return DispatchKeyParts(parts[0], int(parts[1]), parts[2], turn_no)


def dispatch_metadata(*, run_key: str, generation: int, dispatch_key: str) -> dict[str, str]:
    """The metadata a non-idempotent create carries so a listing can find it again."""

    return {
        "mc_run": run_key,
        "mc_generation": str(generation),
        DISPATCH_METADATA_KEY: dispatch_key,
    }


def created_by(
    sessions: Iterable[Mapping[str, Any]], dispatch_key: str
) -> tuple[Mapping[str, Any], ...]:
    """The listed sessions whose metadata names `dispatch_key`, in listing order."""

    matches: list[Mapping[str, Any]] = []
    for session in sessions:
        metadata = session.get("metadata")
        if isinstance(metadata, Mapping) and metadata.get(DISPATCH_METADATA_KEY) == dispatch_key:
            matches.append(session)
    return tuple(matches)


def lookup_created(
    sessions: Iterable[Mapping[str, Any]],
    dispatch_key: str,
    *,
    id_field: str = "id",
    absent: LookupOutcome = "unknown",
) -> DispatchLookup:
    """Reconcile a create by metadata: one match is `found`; duplicates from an at-least-once
    create are `found` as the first listed (the others are named for cleanup); no match is
    `absent`, which is `unknown` unless the provider's listing is authoritative."""

    matches = [str(item[id_field]) for item in created_by(sessions, dispatch_key)]
    if not matches:
        return DispatchLookup(outcome=absent, detail="no listed session carries the dispatch key")
    detail = f"duplicate creates: {', '.join(matches[1:])}"[:512] if len(matches) > 1 else ""
    return DispatchLookup(outcome="found", native_ref=matches[0], detail=detail)


class AnchorDetails(NamedTuple):
    """The wording of the three `unknown` answers, in the provider's own nouns."""

    unanchored: str = (
        "no acknowledged turn anchors this session; the lost send cannot be told apart from "
        "an earlier turn"
    )
    no_latest: str = "the session reports no latest turn"
    acknowledged: str = (
        "the latest turn is already acknowledged; the lost send may still be in flight"
    )


NEUTRAL_ANCHOR_DETAILS: Final = AnchorDetails()


@dataclass
class TurnAnchors:
    """The native turns a lane can reconcile a lost send against: those it acknowledged in
    process, the last one the dispatch journal acknowledged (handed in at reattach) and the
    turn each dispatch key produced."""

    known: set[str] = field(default_factory=set)
    journal_anchor: str | None = None
    sent: dict[str, str] = field(default_factory=dict)

    def acknowledge(self, turn_ref: str, dispatch_key: str | None = None) -> None:
        self.known.add(turn_ref)
        if dispatch_key is not None:
            self.sent[dispatch_key] = turn_ref

    def anchor(self, turn_ref: str) -> None:
        """The last turn the journal acknowledged, handed in by a reattach."""

        self.journal_anchor = turn_ref
        self.known.add(turn_ref)

    def observed(self) -> set[str]:
        return self.known | ({self.journal_anchor} if self.journal_anchor is not None else set())

    def lookup_latest(
        self,
        dispatch_key: str,
        latest_ref: str | None,
        *,
        details: AnchorDetails = NEUTRAL_ANCHOR_DETAILS,
    ) -> DispatchLookup:
        """A lost send judged by the session's latest turn against the anchors."""

        anchors = self.observed()
        if not anchors:
            return DispatchLookup(outcome="unknown", detail=details.unanchored)
        if latest_ref is None:
            return DispatchLookup(outcome="unknown", detail=details.no_latest)
        if latest_ref in anchors:
            # A read can race an in-flight send whose response was lost: an unchanged latest
            # turn cannot authorize a resend.
            return DispatchLookup(outcome="unknown", detail=details.acknowledged)
        self.acknowledge(latest_ref, dispatch_key)
        return DispatchLookup(outcome="found", native_ref=latest_ref)


__all__ = [
    "DISPATCH_METADATA_KEY",
    "NEUTRAL_ANCHOR_DETAILS",
    "AnchorDetails",
    "DispatchKeyParts",
    "TurnAnchors",
    "client_session_id",
    "created_by",
    "dispatch_metadata",
    "lookup_created",
    "parse_dispatch_key",
]
