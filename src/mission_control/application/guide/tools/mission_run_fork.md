---
id: mission_run_fork
title: mission_run_fork: fork a run
summary: Admit a new run that starts from a Snapshot of this one, optionally with changes, a first instruction or an agent state to continue from.
---
Fork a run: admit a new run that starts from a Snapshot of this one, optionally with changes, a first instruction or an agent state to continue from.

Use it to retry or explore from a safe boundary without touching the source run; in-flight Commands and active children are never copied.

`request` fields:

- Required: `request_id` (a new UUID; a repeat returns the same fork), `sponsorship_ref` (a sponsorship your principal holds; it pays for the new run) and `reason` (1 to 2000 characters). mission_whoami lists your `sponsorship_refs`; a ref you do not hold is refused `unauthorized`, naming the ref required and the refs you hold.
- `snapshot_id` (also accepted as `from_snapshot_id`): omit it to use the latest safe Snapshot; `snapshot_digest` may pin it. Where the run has no Snapshot yet, one is taken now, which is possible only at a safe boundary (see below).
- `message`: `{"text": "..."}` or `{"artifact_ref", "content_digest"}`, given to the new run as its first instruction (`instruction` is the older name of the same field).
- `cognitive_seed`: start an agent from a cognition point listed by mission_run_points. For a checkpoint point: `{"unit_key": coordinate.unit_key, "checkpoint": coordinate.point.key}`; for any other kind: `{"unit_key": coordinate.unit_key, "point": coordinate.point}`.
- `at`: where the new run resumes: `{"stage", "cycle"}` for a Stage Graph run, or `{"iteration", optional "session_generation"}` for a Goal Loop run. Derived from the seed point when omitted.
- `changes`: `[{"path", "value"}]`, edits to fields the run's Workflow Type declares patchable.
- `invalidation_frontier`: stage ids, or `"*"`, whose work must run again.
- `frontier_policy`: `"close"` (default: also re-run every stage that depends on them) or `"strict"` (refuse a frontier that leaves a dependent stage out).
- `baseline_reservations`: `{dimension: amount}`, budget held for the new run (default: the source run's).
- `approval_refs`: approvals your principal holds.

When a fork is possible. Every fork starts from a Snapshot, a fork from a cognition point included. A Snapshot is taken only at a safe boundary: the run has started, at least one stage settlement is accepted, and nothing is in flight (no active stage, open stage liability, unsettled unit, effect or usage, unapplied Command, pending continuation, active child or linked run). A Human Gate keeps its stage active until its Human Task is resolved, so a run that waits at a gate has no safe boundary: with no earlier Snapshot the fork is refused `CHECKPOINT_INVALID`, the message says what holds the boundary open and `reasons` lists it (`stage_active:<stage>` ...). Fork once that work settles or the run ends; from then every point mission_run_points lists with `seedable` can seed it. A finished run is always at a safe boundary.

Returns `receipt` (`target_run_id`, `snapshot_id`, `reused_units`, `frontier_closed`, `message_delivery`) and `seed`. The new run is admitted, not started: call mission_run_start with `receipt.target_run_id`.
