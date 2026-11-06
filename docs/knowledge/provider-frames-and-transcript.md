---
type: Concept
category: persistence
title: Provider frames and the transcript
description: The Native Event Store of provider frames (verbatim, per lane writers), closing-frame derivation of mission events, usage dispositions, retention that projects before it deletes, the mc.transcript_entry.v2 read model and its persisted projection, body states, full-body resolution, expired placeholders, frame-body and closure-body downloads, and run list and search over Temporal Visibility.
tags: [mission-control, frames, transcript, native-event-store, projection, retention, search, implementation]
aliases: [Native Event Store, provider frame, transcript v2, transcript projection, frame-body download]
questions:
  - Where are provider frames stored and how is a transcript read?
  - Why is a transcript body expired, excerpted or missing?
  - How does a run list or transcript search work?
  - How is a stopped turn told apart from a model answer?
updated: 2026-11-01
---

# Provider frames and the transcript

A [Provider Frame](../../GLOSSARY.md) is the lane-neutral record of what a provider said; the
[Transcript](../../GLOSSARY.md) is the read view over events and frames (ADR-0028, ADR-0054). Mission events and
subscriptions are in [events and commands](events-and-commands.md); lanes that write frames are in
[lanes and harness](lanes-and-harness.md).

## Frames: the Native Event Store

A frame is one raw event a lane observed from its provider or from a hook, redacted, digested, excerpted under a cap
and persisted verbatim before any derivation in `mission_control.provider_frame`. Frames are keyed by
`(harness_execution_id, generation, provider_key)` and ordered by a writer-assigned `arrival_ordinal`; an append is
idempotent on that key, and a frame of an older generation than the execution's current one is counted `stale` and
never stored (`adapters/postgres/frames/repository.py`, `application/frames/sink.py`). Kinds are the lane-neutral
`FrameKind` set (`session_init`, `turn_started`, `message`, `tool_call_*`, `approval_*`, `hook_invoked|result`,
`before_compaction`, `after_compaction`, `usage`, `turn_ended`, `run_result`, ...), classified per lane by tables in
`application/frames/kinds.py`; unmapped kinds classify `unknown` and are counted. Native identity records
(`harness_execution`, `agent_session`, `session_turn`) advance in the same transaction as the frames that cause them.
Writers: `adapters/{deep_agents,cursor,claude,codex,anthropic_managed,openai_agents}/frames.py` and hook callbacks.

Only Closing Frames move state. `application/frames/reducer.py::derive` is pure and reads the current generation's
closing frames in arrival order: the first of a session gives `session.started`, of a turn `session.turn_started`, a
completed or failed tool call `tool_call.completed{status}` (deduplicated by tool call ref), a denying `hook_result`
`tool_call.completed{status: denied}`, a human wait `activation.phase_changed{awaiting_human}`, `after_compaction`
`session.compaction_observed`, `usage` and `turn_ended` the turn's usage disposition (`settled`, `estimated` or
`unknown`; unknown is never zero, `domain/frames/usage.py`). Each event points back by `source.native_event_ref`.

## Retention

`frame_retention_policy` (default 30 days, keep closing frames, 8 KiB excerpt cap); `mc.frames_expire.v1` runs
`frames.expire` on a daily Temporal Schedule per application on the worker's maintenance queue
(`MISSION_CONTROL_FRAMES_EXPIRE_SCHEDULE`, default true). Mission events are never touched. Since release 1.4.4 a frame
has a generated `retention_class`: the `delta` class (`message_delta`, `thinking_delta`, `tool_call_delta`,
`heartbeat`, `status`) expires on the policy's `retain_days` clock; every other frame is kept for the mission's
evidence life unless the application sets `step_retain_days` (terminal runs only); `prune_mode = tombstone` is reserved.
Workspace closures carry their own clock (`retain_until`, `expire_workspace_closures`;
[workspace closure](workspace-closure.md)). Because the persisted projection is the record of what retention deleted,
`expire` (`adapters/postgres/frames/retention.py`) first projects every run with expiring frames whose projection is
behind; a run still not current is held back (`FrameExpiryReport.skipped_unprojected`). In the delete transaction each
covered run's `transcript_projection_state` row is deleted and one outbox intent re-projects it with placeholders
(`invalidated_projections`).

## Transcript v2 and the persisted projection

An entry is `mc.transcript_entry.v2` (`domain/frames/transcript.py`): `entry_seq`, the unit, node, cycle, iteration and
session generation, `point_id`, `body` (`state`, `bytes`, `media_type`, `artifact_ref`) and `execution`. `merge` places
an entry by the run's cognition point index when composed, by time otherwise; cursors are strictly increasing and
opaque (`tc1:...`); `GET .../transcript?by=step|stage|iteration&point=&unit=` groups them. The settlement transaction
writes one `transcript_projection` outbox intent; the relay on the maintenance worker starts `mc.transcript_project.v1`,
whose `transcript.project` activity replaces the run's `transcript_entry` rows and `transcript_projection_state` marks.
A read serves stored rows only while the marks equal the live sources, and materializes the view otherwise. The
activity heartbeats between phases, a pass whose sources moved queues its own catch-up intent, a failed run queues one
retry (at most one per run per hour, five minutes later) and the starter restarts a failed workflow under its id
(`application/frames/projection_trigger.py`, `search.py`).

- **`body.state`:** `inline` only when the excerpt holds the whole body, `excerpt` when cut, `artifact` when the frame
  promoted its body to a reference, `expired` (and `pruned`, reserved) for a placeholder.
- **Full bodies:** `--full` / `full=true` resolves a page's promoted bodies, each reference once per page, bounded by
  `FULL_PAGE_BODY_BUDGET_BYTES` (16 MiB); past it an entry keeps the bare reference and sets `body.truncated`. It answers
  `501 full_body_unavailable` only when no body reader is composed. A `model_request` also gets the body of its system
  prompt and messages. An expired or pruned entry is never resolved.
- **Expired placeholders:** `keep_expired(projected, fresh)` turns every frame entry the earlier projection held and the
  store no longer has into a `frame_expired` placeholder at its own cursor, with no artifact reference.
- **Markdown:** `domain/frames/render.py` quotes each message and, per model request, the model, step, tools and every
  prompt part once, and collapses consecutive kernel hook pairs into one line per tool call; JSONL is unchanged.

Surfaces: `GET /runs/{id}/transcript` (JSONL, JSON or Markdown), `frames/tail` (non-canonical SSE tail), `missionctl run
transcript [--follow] [--since]`, `run frames --tail`, MCP `mission_run_transcript` and the
`mc://applications/{application_id}/runs/{run_id}/transcript` resource.

## Frame and closure bodies

A promoted body is a `frame-body://sha256:<hex>?bytes=<n>&type=<media>` reference (`application/frames/body_refs.py`;
the `&ref=` parameter was removed). Workspace closures add `closure-body://` references served by the same route
(`application/frames/artifact_bodies.py`). `GET /v1/applications/{app}/runs/{run_id}/artifacts/{ref}` binds the read to
the path's run: a frame-body digest must be referenced by a frame of that run in the caller's scope
(`PostgresFrameBodyIndex.run_frame_body`), an `artifact://` reference must be the run's, and byte count and media type are
the row's, never the reference's. Anything else is `404`; the response is `Content-Disposition: attachment` with
`X-Content-Type-Options: nosniff`.

## Run list, search and Deep Agents stop markers

`GET /runs?query=` runs over Temporal Visibility with a bounded grammar (`lane`, `phase`, `mission_id`, `forked_from`,
`status`, `started_after`), bound to the installation workflow prefix and scope hash and enriched from the ledger
(`domain/frames/run_query.py`); `GET /runs/{id}/transcript/search` uses `mission_control_search.transcript_document`, a
rebuildable `websearch_to_tsquery` index, never an authorization store; CLI `run list`, `run search`; MCP
`mission_run_list`, `mission_run_search`. The search attributes `mc_mission_id`, `mc_run_id`, `mc_lane`, `mc_phase` and
`ForkedFromRunId` are registered by `make temporal-search-attributes`.

A turn Mission Control stopped is told apart from a model answer: the stop message keeps `mc_stop` (`{marker, detail}`;
`mc_budget_stop`, `mc_fence_stop`, `mc_hook_stop`, `adapters/deep_agents/budget.py`) and the turn's
`graph.invocation_ended` frame records the marker as `stop_reason`. Hook frame ids are deterministic
(`hook:{event}:{hook_id}:{invocation_ref}:invoked|result`, `adapters/deep_agents/hooks.py`), so a retried activity
writes duplicates, not new rows.

Built / specified / goal: frames, derivation, projection, retention ordering and downloads are implemented and tested
on PostgreSQL and Temporal; stream envelopes name unit and point ([joinability](unit-and-point-joinability.md)); a
narrative or as-of read over history is an idea, not built.

## Citations

- ADR: [0028](../adr/0028-native-event-store-provider-frames-and-materialized-transcript.md),
  [0054](../adr/0054-the-mission-transcript-is-the-replayable-record.md),
  [0055](../adr/0055-retention-follows-the-mission.md).
- History: [SPEC-03](../specs/archive/fast-track-2026-10/SPEC-03-mission-state-and-transcript.md),
  [TRACING-PROPOSAL](../specs/archive/provider-consolidation-2026-10/proposals/TRACING-PROPOSAL.md).
- Code: [frame contracts](../../src/mission_control/domain/frames/contracts.py),
  [usage dispositions](../../src/mission_control/domain/frames/usage.py),
  [run query grammar](../../src/mission_control/domain/frames/run_query.py),
  [transcript entries](../../src/mission_control/domain/frames/transcript.py),
  [Markdown renderer](../../src/mission_control/domain/frames/render.py),
  [frame sink](../../src/mission_control/application/frames/sink.py),
  [kind tables](../../src/mission_control/application/frames/kinds.py),
  [frame reducer](../../src/mission_control/application/frames/reducer.py),
  [transcript service](../../src/mission_control/application/frames/transcript.py),
  [projector and search](../../src/mission_control/application/frames/search.py),
  [projection relay](../../src/mission_control/application/frames/projection_trigger.py),
  [body references](../../src/mission_control/application/frames/body_refs.py),
  [body reader](../../src/mission_control/application/frames/artifact_bodies.py),
  [frame store](../../src/mission_control/adapters/postgres/frames/repository.py),
  [retention](../../src/mission_control/adapters/postgres/frames/retention.py),
  [frame body index](../../src/mission_control/adapters/postgres/frames/transcript_reads.py),
  [projection activity](../../src/mission_control/adapters/temporal/activities/transcript_projection.py),
  [transcript routes](../../src/mission_control/interfaces/http/transcript.py),
  [artifact route](../../src/mission_control/interfaces/http/artifacts.py),
  [Deep Agents frames](../../src/mission_control/adapters/deep_agents/frames.py).
- Tests: [contracts and body](../../tests/unit/frames/test_frame_contracts_and_body.py),
  [transcript](../../tests/unit/frames/test_transcript.py),
  [full reads](../../tests/unit/frames/test_transcript_full_reads.py),
  [expired placeholders](../../tests/unit/frames/test_keep_expired.py),
  [projection trigger](../../tests/unit/frames/test_transcript_projection_trigger.py),
  [artifact download](../../tests/unit/frames/test_artifact_download.py),
  [run list and search](../../tests/unit/frames/test_run_list_and_search.py),
  [frames in PostgreSQL](../../tests/integration/postgres/test_provider_frames_postgres.py),
  [transcript entries and retention](../../tests/integration/postgres/test_transcript_entries.py),
  [expiry workflow](../../tests/integration/temporal/test_frames_expire_workflow.py),
  [Deep Agents frames](../../tests/integration/deep_agents/test_provider_frames_deep_agents.py).
