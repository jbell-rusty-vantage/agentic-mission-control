"""Mission event reads for Transcript materialization (SPEC-03, C3).

Reads the run's canonical `mission_event` rows (by `seq`) under the caller's tenant
scope; forced RLS denies every other scope. The transcript itself is never persisted.

Tracing Stage 3 (R4-F6): `PostgresFrameBodyIndex` binds a `frame-body://` digest to a run
for the download route: a frame of the run whose promoted body it is (size and media type
from that row), else a `model_request` frame of the run that names it as a message body
(size and type from the reference that frame stored).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from mission_control.adapters.postgres.run_control.canonical import SCOPE, begin
from mission_control.application.frames.artifact_bodies import FrameBodyRecord
from mission_control.application.frames.body_refs import (
    FRAME_BODY_PREFIX,
    MalformedFrameBodyRef,
    parse_frame_body_ref,
)
from mission_control.application.frames.transcript import MAX_EVENTS, MissionEventRecord
from mission_control.domain.programs.contracts import (
    StageCandidateIdentity,
    StageExecutionIdentity,
)
from mission_control.domain.programs.runtime_units import stage_runtime_unit


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if isinstance(value, dict) else {}


class PostgresMissionEventReader:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def run_identity(self, request_scope: str, run_key: str) -> UUID | None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            value = await connection.fetchval(
                f"SELECT run_id FROM mission_control.mission_run WHERE {SCOPE} AND run_key = $4",
                *args,
                run_key,
            )
        return value if isinstance(value, UUID) else None

    async def events_for_run(
        self, request_scope: str, run_key: str, *, limit: int = MAX_EVENTS
    ) -> tuple[MissionEventRecord, ...]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            rows = await connection.fetch(
                """
                SELECT e.seq, e.event_id, e.event_type, e.recorded_at, e.actor_ref, e.payload
                FROM mission_control.mission_event e
                JOIN mission_control.mission_run r
                  ON r.installation_id = e.installation_id
                 AND r.application_id = e.application_id
                 AND r.tenant_id = e.tenant_id AND r.run_id = e.run_id
                WHERE e.installation_id = $1 AND e.application_id = $2 AND e.tenant_id = $3
                  AND r.run_key = $4
                ORDER BY e.seq
                LIMIT $5
                """,
                *args,
                run_key,
                limit,
            )
        return tuple(
            MissionEventRecord(
                seq=int(row["seq"]),
                event_id=str(row["event_id"]),
                event_type=row["event_type"],
                recorded_at=row["recorded_at"],
                actor_ref=row["actor_ref"],
                payload=_payload(row["payload"]),
            )
            for row in rows
        )


# --- Frame bodies by run (Tracing Stage 3, R4-F6) -------------------------------------------

_RUN_FRAMES = """
    FROM mission_control.provider_frame f
    JOIN mission_control.mission_run r
      ON r.installation_id = f.installation_id
     AND r.application_id = f.application_id
     AND r.tenant_id = f.tenant_id AND r.run_id = f.run_id
    WHERE f.installation_id = $1 AND f.application_id = $2 AND f.tenant_id = $3
      AND r.run_key = $4
"""


class PostgresFrameBodyIndex:
    """`FrameBodyIndex` over the run's frame rows, under the caller's tenant scope."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def run_frame_body(
        self, request_scope: str, run_key: str, digest: str
    ) -> FrameBodyRecord | None:
        needle = f"{FRAME_BODY_PREFIX}{digest}?"
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            row = await connection.fetchrow(
                f"""
                SELECT f.body_bytes, f.body_media_type
                {_RUN_FRAMES}
                  AND f.body_digest = $5 AND starts_with(f.body_artifact_ref, $6)
                LIMIT 1
                """,
                *args,
                run_key,
                digest,
                FRAME_BODY_PREFIX,
            )
            if row is not None:
                return FrameBodyRecord(
                    size_bytes=int(row["body_bytes"]), media_type=str(row["body_media_type"])
                )
            # A message body a `model_request` frame of the run names by reference.
            excerpt = await connection.fetchval(
                f"""
                SELECT f.body_excerpt
                {_RUN_FRAMES}
                  AND f.kind = 'model_request' AND position($5::bytea IN f.body_excerpt) > 0
                LIMIT 1
                """,
                *args,
                run_key,
                needle.encode("utf-8"),
            )
        if excerpt is None:
            return None
        return _named_body(bytes(excerpt).decode("utf-8", errors="replace"), needle)


def _named_body(text: str, needle: str) -> FrameBodyRecord | None:
    """The reference a stored `model_request` body holds for the needle's digest."""

    match = re.search(re.escape(needle) + r'[^"\\\s]*', text)
    if match is None:
        return None
    try:
        ref = parse_frame_body_ref(match.group(0))
    except MalformedFrameBodyRef:
        return None
    return FrameBodyRecord(size_bytes=ref.bytes, media_type=ref.media_type)


# --- Family facts (1.4.4, P4.2 `--by stage`) ---------------------------------------------


class PostgresFamilyFactsReader:
    """`FamilyFactsReader` over the family admission journal and the completion rows.

    Stage Graph units: the `operation_admitted` proposal's `released_by` and `continues_from`,
    the `result_decided` proposal's decision, the `cycle_decided` proposal the unit's cycle
    took part in, and the `completion_decision` row the family wrote for the unit. Goal
    Directed mutations are not mapped here yet (their unit key needs the revision identity
    the journal row does not carry verbatim); their groups keep the event facts only.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def unit_facts(self, request_scope: str, run_key: str) -> dict[str, dict[str, Any]]:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            journal = await connection.fetch(
                f"""
                SELECT mutation FROM mission_control.family_admission_journal
                WHERE {SCOPE} AND run_key = $4
                ORDER BY family_version
                """,
                *args,
                run_key,
            )
            decisions = await connection.fetch(
                f"""
                SELECT a.activation_key, d.decision_key, d.result_disposition, d.reason_codes,
                       d.decided_at, d.candidate_id::text AS candidate_id
                FROM mission_control.completion_decision AS d
                JOIN mission_control.activation AS a
                  ON a.installation_id = d.installation_id
                 AND a.application_id = d.application_id
                 AND a.tenant_id = d.tenant_id
                 AND a.activation_id = d.activation_id
                WHERE d.installation_id = $1 AND d.application_id = $2 AND d.tenant_id = $3
                  AND d.run_id = (
                      SELECT run_id FROM mission_control.mission_run
                      WHERE {SCOPE} AND run_key = $4
                  )
                ORDER BY d.decided_at
                """,
                *args,
                run_key,
            )
        return family_unit_facts(
            request_scope,
            [_payload(row["mutation"]) for row in journal],
            [dict(row) for row in decisions],
        )


def family_unit_facts(
    request_scope: str,
    mutations: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Pure: the journal mutations and completion rows of one run, keyed by unit key."""

    facts: dict[str, dict[str, Any]] = {}
    admitted: dict[tuple[str, int], str] = {}
    for mutation in mutations:
        kind = mutation.get("decision_kind")
        payload = mutation.get("decision_payload")
        proposal = payload.get("proposal") if isinstance(payload, dict) else None
        if not isinstance(proposal, dict):
            continue
        if kind in {"operation_admitted", "result_decided"}:
            unit_key = _stage_unit_key(request_scope, proposal.get("identity"))
            if unit_key is None:
                continue
            unit = facts.setdefault(unit_key, {})
            if kind == "operation_admitted":
                candidate = proposal["identity"]["candidate"]
                admitted[(str(candidate["stage_id"]), int(candidate["stage_cycle_ordinal"]))] = (
                    unit_key
                )
                unit["released_by"] = list(proposal.get("released_by") or ())
                unit["continues_from"] = proposal.get("continues_from")
                unit["admission_mutation_id"] = mutation.get("mutation_id")
            else:
                validation = (
                    payload.get("completion_validation") if isinstance(payload, dict) else None
                )
                unit["result"] = {
                    "decision": proposal.get("decision"),
                    "mutation_id": mutation.get("mutation_id"),
                    "execution_disposition": (
                        validation.get("execution_disposition")
                        if isinstance(validation, dict)
                        else None
                    ),
                    "reason_codes": (
                        list(validation.get("reason_codes") or ())
                        if isinstance(validation, dict)
                        else []
                    ),
                }
        elif kind == "cycle_decided":
            stage_id = proposal.get("stage_id")
            prior = proposal.get("prior_stage_cycle_ordinal")
            if isinstance(stage_id, str) and isinstance(prior, int):
                unit_key = admitted.get((stage_id, prior))
                if unit_key is not None:
                    facts.setdefault(unit_key, {})["cycle"] = {
                        "mutation_id": mutation.get("mutation_id"),
                        "next_stage_cycle_ordinal": proposal.get("next_stage_cycle_ordinal"),
                        "invalidated_stage_ids": list(proposal.get("invalidated_stage_ids") or ()),
                        "next_objective": proposal.get("next_objective"),
                    }
    for row in decisions:
        unit_key = row.get("activation_key")
        if not isinstance(unit_key, str):
            continue
        decided_at = row.get("decided_at")
        facts.setdefault(unit_key, {})["decision"] = {
            "decision_key": row.get("decision_key"),
            "result_disposition": row.get("result_disposition"),
            "reason_codes": list(row.get("reason_codes") or ()),
            "decided_at": decided_at.isoformat() if isinstance(decided_at, datetime) else None,
            "candidate_id": row.get("candidate_id"),
        }
    return facts


def _stage_unit_key(request_scope: str, identity: Any) -> str | None:
    """The unit key of a Stage Graph proposal identity (as `asdict` serialized it)."""

    if not isinstance(identity, dict) or not isinstance(identity.get("candidate"), dict):
        return None
    try:
        candidate = StageCandidateIdentity(**identity["candidate"])
        stage = StageExecutionIdentity(
            run_id=str(identity["run_id"]),
            execution_epoch=int(identity["execution_epoch"]),
            candidate=candidate,
            semantic_attempt=int(identity["semantic_attempt"]),
            execution_generation=int(identity.get("execution_generation", 1)),
        )
    except (KeyError, TypeError, ValueError):
        return None
    return stage_runtime_unit(request_scope, stage).unit_key
