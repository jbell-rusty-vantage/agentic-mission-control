---
type: Concept
category: persistence
title: Workspace Closure - what the agent could see when an attempt settled
description: "The Deep Agents adapter records every agent-visible file of an attempt at its settled boundary (attempt_settled, attempt_failed, attempt_cancelled) with raw-byte digests, slot and destination, bodies within the Application Profile's caps in the payload store, as an attribute of the result checkpoint point; read by point, by run, in state-as-of and run inspect."
tags: [mission-control, deep-agents, workspace, evidence, tracing, retention, implementation]
aliases: [agent-visible files, closure digest, attempt evidence, workspace closure]
questions:
  - Which files could the agent see when the attempt settled?
  - How do I download a closure body for a point?
  - Why is a workspace closure incomplete or withheld?
updated: 2026-11-01
---

# Workspace Closure

A **Workspace Closure** (`mc.workspace_closure.v1`, `domain/execution/workspace_closure.py`) is
the evidence of an attempt's workspace when the attempt settled: every file the agent could reach,
with its raw-byte sha256, its slot and where it lived, and (within the caps) its bytes. It closes
the gap between the [workspace candidates](operations.md) an attempt registers (only its exclusive
writable slots, failing the attempt past 64 files or 4 MB) and what the agent actually saw.

## Capture

`DeepAgentRuntimeAdapter._record_closure` calls `capture_closure`
(`adapters/deep_agents/workspace_closure.py`) inside `materializer.prepare`, while the backend is
alive, at three boundaries:

- `attempt_settled`: after the candidates are captured; the closure ref becomes the result point's
  `workspace_checkpoint_ref` (`workspace-closure://<closure_id>#<closure_digest>`, replacing the
  1.4.4 `workspace-candidates://` digest).
- `attempt_failed`: at the latest durable checkpoint of the failed lineage, on the partial points.
- `attempt_cancelled`: in `observe_latest`, at the stamped leaf.

What is listed: on the text-only `StateBackend` the whole folded `files` channel (seeded
`/inputs/**` and `/.mission/**`, skills, transfer files, the agent's writes), on a sandbox the
exclusive writable slots and `/workspace`, listed and digested in the container by one
`find ... sha256sum` command; bodies are downloaded only for files that will be promoted. Digests
cover raw bytes (base64 files decoded), matching `StateFile.digest`; the result point's text
`files_digest` is kept as `files_digest_channel` for cross-checking.

Capture never fails the attempt. Past `closure_max_files` files are omitted (`omitted_files`),
past `closure_max_bytes` promoted bytes a body is `withheld_cap`; either sets `complete = false`.
A `sensitive` slot's body is `withheld_sensitive`, a body containing a resolved secret value is
`withheld_secret`, a Context Packet input is `withheld_input` (the packet's durable custody already
holds it; the [materialization manifest](provider-frames-and-transcript.md) names it). A body whose
download does not match its listed digest is `unreadable`. A capture or store failure is logged and
the result point simply carries no ref. Hosted async children record no closure.

The same change made the 64-file / 4 MB candidate bound degrade (first files by path) instead of
raising, and gave each Docker writable target its own host directory (`slot_host_path`), so two
writable slots no longer alias one directory.

## Policy

The Application Profile's `[workspace]` table (`WorkspaceClosureProfile`,
`domain/resolution/profiles.py`): `closure_enabled`, `closure_max_files` (512),
`closure_max_bytes` (64 MiB), `closure_retention` (`"mission"` or whole days, at least 30). The
worker composition loads it (`bootstrap/workspace_closures.py`) and hands it to the adapter; it is
not part of `ResolvedRuntime`, so changing a cap does not change `runtime_digest`.

## Storage and retention

Release 1.12.0 (`0070_workspace_closure.sql`): `workspace_closure` (manifest jsonb, digest, counts,
`retain_until`) and `workspace_closure_entry` (one row per file; `object_ref` exactly when
promoted), append-only, forced RLS, `SELECT, INSERT` for the runtime role. Promoted bodies are
staged in the content-addressed artifact payload store first (`PostgresWorkspaceClosures.put`),
then header and entries in one transaction, idempotent by `closure_id` (uuid5 of run, unit,
generation, result checkpoint and boundary). The point id is derived (`point_id_for`), without a
foreign key, because the activity writes the closure before the settlement writes the point.

The frames `expire` pass also calls the definer `expire_workspace_closures(now)`, which deletes
completed runs' closures past `retain_until` (entries cascade) and reports `expired_closures`
([ADR-0055](../adr/0055-retention-follows-the-mission.md) addendum). Payload bytes are shared
across runs and are not deleted; reclaiming them needs reference counting.

## Reads

- `GET .../runs/{run_id}/points/{point_id}/closure` and `missionctl run closure RUN --point ID`:
  the closure the point's ref names, else the newest recorded for the point.
- `GET .../runs/{run_id}/closures` and `missionctl run closure RUN --list`: summaries, oldest first;
  the newest is the mission end's closure. `run inspect` (`/inspection`) and run evidence carry a
  summary (count, incomplete, newest).
- A promoted body's `closure-body://sha256:<hex>?bytes=<n>&type=<media>` downloads through
  `GET .../runs/{run_id}/artifacts/{ref}` (`missionctl run artifact`), bound to the run: the digest
  must be a promoted body of the run's closures (`ClosureBodyIndex`), size and type come from the
  entry row, and the 4 000 000-byte download cap applies (larger bodies are recorded but answer
  `413`).
- `state-as-of` lists the closure's files (`source: closure`, `body_ref` when promoted) when the
  point's ref is a closure ref; `CognitionPointReadService` adds them under the tenant scope.

## Limits

Unit-tested over the state backend and a sandbox double; the release and the PostgreSQL adapter are
tested on a disposable PostgreSQL 17. Integrated (not qualified): the provenance proof run
`source-mc-origin-01`, a Deep Agents StageGraph on disposable targets, recorded eight closures that
Mission Control's own run inspection reports (count 8, incomplete 0); the failed fork run recorded one
`attempt_failed` closure
([provenance report](../specs/archive/provider-consolidation-2026-10/sprint-oc/provenance-2026-10-31/REPORT.md)
section 2, slice 5). The report records no sandbox backend for that run: Docker, LangSmith and
Daytona sandboxes are still unexercised live, and release 1.12.0 has no deployment lock or remote
install.

Built / specified / goal: capture at the three boundaries, the store, reads, downloads and expiry are implemented and tested;
integrated on a Deep Agents StageGraph run (provenance report); qualified: no. Other lanes are not wired. The Deep Agents capture
hook is described in [Deep Agents lane](deep-agents-lane.md); closure bodies are served by the artifact route
([provider frames and transcript](provider-frames-and-transcript.md)).

## Citations

- [Contract](../../src/mission_control/domain/execution/workspace_closure.py),
  [capture](../../src/mission_control/adapters/deep_agents/workspace_closure.py),
  [store](../../src/mission_control/adapters/postgres/workspace_closures.py),
  [reads](../../src/mission_control/application/execution/cognition_point_reads.py),
  [body reader](../../src/mission_control/application/frames/artifact_bodies.py),
  [migration](../../scripts/release_1120/0070_workspace_closure.sql).
- Tests: `tests/unit/deep_agents/test_workspace_closure.py`,
  `tests/unit/frames/test_deep_agents_frames.py`,
  `tests/integration/postgres/test_workspace_closures_postgres.py`,
  `tests/integration/postgres/test_sprint_oc_release_1120.py`.
