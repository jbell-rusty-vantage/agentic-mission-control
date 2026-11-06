---
type: Sprint Disposition
title: "Instruction for Stage 1 of the tracing work: one session implements and minimally verifies the Mission Transcript and the precise fork over work packages WP-TR-1..5, every decision closed by the owner on 2026-10-21"
description: "What the Stage 1 session does, in order: orient on the proposal and the ledger, re-audit the starting state, cut release 1.4.4 first (0047 joinability and kinds and retention columns, 0048 transcript projection tables, 0049 frame-body scheme), build the write side (settlement transaction, reconciler, joinable events, lifecycle writers into the existing completion tables, rollover event, reused points; model-input frames from a chat-model callback, capture profiles chosen by a deployment setting, the frame-body promoter, hook ports, subagent points, environment manifest), then the read side and the fork (transcript v2 and the settlement-triggered projection, replay, artifact download, retention classes; closure, start position for both families, one fork message delivered to the seed head, the Goal Directed reuse rule, the fork CLI; saver bounds and typed outcomes), with subagents on independent streams, minimal verification on T0, a commit after each work package, a ledger entry, and the handoff to Stage 2 (real fixtures, 10 USD) and Stage 3 (review, clean code, tests, documentation)."
tags: [mission-control, providers, consolidation, deep-agents, tracing, session, P1, stage-1]
status: archived
archived: 2026-10-23
archived_from: providers/deep_agents/SESSION-STAGE-1.md
archived_reason: "Tracing Stage 1 done"
---

> **Archived 2026-10-23** (Tracing Stage 1 done). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Stage 1: implementation and minimal verification (one session)

Run under [PROCESS.md](../../../provider-consolidation-2026-10/PROCESS.md). The plan is
[TRACING-PROPOSAL.md](../proposals/TRACING-PROPOSAL.md); its §P10 holds every owner answer, dated.
Stage 1 is followed by Stage 2 (real fixtures on a 10 USD cognition budget) and Stage 3
(adversarial review, clean code, tests, documentation); do not pull their work forward.

## 1. Goal, in the owner's words

Read a literal record of every step a mission went through, written by the harness and never
by the working agent, from Mission Control's own tables, granular to "Temporal activity
attempt → Deep Agents graph step", with the exact input and output of each step and the
environment and lifecycle facts around it; and fork from Stage 2 cycle 2 at a point, inject a
message, and run it as a new workflow that reuses everything before the point.

## 2. Shape (owner, 2026-10-21)

One session, all five work packages, in the order WP-TR-1, 2, 3, 4, 5. After each package's
minimal verification, **commit on the sprint branch** (branched from `main`; release 1.4.4 is
the first commit); no push and no merge until the owner says so. Fan out subagents on the
independent streams named below after each shared contract step; run the acceptance proofs
serially (one heavy job at a time on this host, about 15 GB RAM). Spend: 0 USD; no model
runs in Stage 1. PROCESS §1 step 4 is already done for this stage: every decision is closed;
ask only if the code contradicts a recorded answer.

## 3. Read first

1. [TRACING-PROPOSAL.md](../proposals/TRACING-PROPOSAL.md): §A.2 (what the audit corrected), P1
   (every **change** and **new** row), P2 (the three migrations), P3 (the writers, module by
   module), P4 (the read model), P5 (the fork), P6 (the saver), P8 (determinism), P9 (the
   proofs), P10 (the recorded answers, both blocks), Part C.
2. [CHANGES.md](../../../provider-consolidation-2026-10/providers/deep_agents/CHANGES.md) turn 4 and turn 5 preparation; [COGNITION-POINTS.md](../specs/COGNITION-POINTS.md) §2.
3. The release pattern: `scripts/prepare_release_143.py`,
   `packages/mission-control-db-contract/releases/1.4.3/component/release-spec.json`,
   `M143/0045_cognition_points.sql` (RLS and grant style), `packages/mission-control-db-contract/README.md`.
4. Live branch state: `git status`, `git log --oneline -5`, `git worktree list --porcelain`
   from `platform/mission-control`.

## 4. Decisions in force (all closed; the proposal §P10 is the record)

| Topic | In force |
| --- | --- |
| Release | one release 1.4.4, cut first, carrying 0047, 0048, 0049; nothing later touches the schema |
| Retention columns (0047) | `retain_days` governs the delta class; `step_retain_days integer` nullable (NULL = mission evidence life, CHECK ≥ 30 when set); `prune_mode text NOT NULL DEFAULT 'delete' CHECK IN ('delete','tombstone')` reserved; `provider_frame.retention_class` generated from `kind`; per application, no lane field |
| Frame bodies (0049) | `frame-body://sha256:<hex>?bytes=<n>&type=<media>` over the content-addressed payload store; `provider_frame.body_artifact_ref` holds it; read by the granted body reader under `workflow.result.read`; no `artifact_metadata_revision` row |
| Lifecycle decisions | written into the existing `completion_candidate` and `completion_decision` (`M/0003:381-432`); `decision_key = mutation_id` (Stage Graph) or `verification_id` (Goal Directed); `candidate_key = settlement_id`; unused columns NULL; grants added in 0047 if absent; improvements belong to the output-contracts session |
| Transcript projection | tables `mission_control.transcript_entry` and `mission_control.transcript_projection_state` (0048); refreshed at every settlement through the outbox and on demand; no schedule; the view serves live tails |
| Model-input record | `model_request` frame from a callback at the chat-model boundary (`_ModelRequestObserver` beside the two existing observers); per-message objects promoted once by digest plus the batch digest under the `standard` capture profile; the whole batch under `full_requests`; profile chosen by `MISSION_CONTROL_FRAME_CAPTURE_PROFILE` (deployment setting, never a manifest field) and recorded on the harness execution; `FrameCapturePolicy` and `FrameBodyPromoter` are the extension points |
| Fork request | `mc.runtime_fork.v1` gains `at`, `message` (`instruction` a deprecated alias), `frontier_policy: close \| strict` (default `close`); `--inject FILE` on the CLI; with `cognitive_seed` the message becomes the seed head's last human message, without a seed it goes to the mailbox; the receipt records `message_delivery`, `frontier_requested`, `frontier_closed`, `reused_units`, `seed_point`, `start_position` |
| Frontier | auto-close over dependants and record; `strict` refuses a narrower frontier |
| Goal Directed fork | reuse by iteration under a derived identity (run, epoch, revision id substituted); `start_position` on the run input honoured by `initial_state`; no revision-identity change |
| Points | written in the settlement transaction; a write failure is `in_doubt` with an incident; the reconciler re-derives through `TimeTravelLane.collect_points` |
| Agent-side writes | none; `progress_note` kind reserved, tool deferred |
| Code work on this lane | not forbidden (owner): nothing may assume Deep Agents never edits files; the environment manifest, `workspace_checkpoint_ref` and promoted tool results must hold for file-editing tools |
| Spend | 0 USD |

## 5. Starting state to re-audit (cite `file:line` on the current `main`)

- Settlement: `application/execution/operations/checkpoint_lineage.py::record_result`,
  `adapters/postgres/operations/checkpoint_lineage.py::record_result`,
  `adapters/postgres/operations/cognition_points.py` (`record`, `_insert`, `_ENRICHABLE`).
- Events: `adapters/postgres/run_control/canonical.py` (`append_events`, `append_mission_events`),
  `domain/policies/reducer.py::reduce_lifecycle`; the outbox release path for the projection trigger.
- Capture: `adapters/deep_agents/adapter.py` (`execute`, `_invoke`, `_frame_recorder`,
  `_ModelCallObserver`, `_SkillDisclosureObserver`), `adapters/deep_agents/frames.py`,
  `application/frames/writer.py` (`FrameBodyPromoter`, `FullBodyPolicy`),
  `application/frames/artifact_bodies.py`, `adapters/deep_agents/hooks.py` (`KernelHookPorts`,
  `HookContext`), `adapters/deep_agents/materializer.py` (`_hook_dispatcher`, seeding),
  `adapters/temporal/deployment_composition.py` (`ExactComponentRegistry`, `compose_hook_callbacks`).
- Lifecycle: `domain/programs/contracts.py`, `domain/programs/interpreter.py`,
  `application/programs/service.py`, `application/programs/goal_directed.py`,
  `adapters/temporal/workflows/goal_directed.py` (the `continue_as_new` sites),
  `M/0003_execution.sql` (`completion_candidate`, `completion_decision`: nullability and grants;
  if `candidate_id` is NOT NULL, the candidate row is written in the same transaction).
- Reads: `application/frames/transcript.py`, `domain/frames/transcript.py`,
  `adapters/postgres/frames/transcript_projection.py`, `adapters/temporal/activities/transcript_projection.py`,
  `bootstrap/worker.py` (maintenance worker), `M/0027_provider_frames.sql` (retention and expiry).
- Fork: `application/recovery/run_forks.py` (`prepare`, `_record_receipt`, `ForkReuseResolver`),
  `domain/policies/forks.py` (`compute_reuse_decisions`, `derived_unit_identity`, `FamilyPosition`),
  `application/recovery/{fork_seed,cognitive_seed}.py`, `adapters/deep_agents/time_travel.py::seed_fork`,
  `application/execution/run_launch.py::_apply_fork`, `domain/programs/goal_directed.py::initial_state`,
  `contracts/runtime_contracts.py::MissionForkRequest`.
- Saver: `adapters/deep_agents/persistence.py`, `adapters/deep_agents/cognition_points.py::collect_points`,
  `bootstrap/api.py::compose_time_travel`.

## 6. Build, in order

**WP-TR-1, joinable, transactional, lifecycle-complete (general).** Shared step: the three
migrations exactly as P2 states, `scripts/prepare_release_144.py`, `release-build` on the
disposable cluster, the release proof in `tests/integration/postgres` (fresh, from 1.4.3, from
1.3.0); contract changes (`FrameKind` with `model_request`, `environment_materialized`,
`subagent_started`, `subagent_ended` closing, `progress_note` reserved; `FULL_BODY_KINDS`;
point roles `cycle_start`, `reused`, `subagent_root`; `CheckpointPoint.root_only` relaxed;
`DomainEventEnvelope.unit_key | activation_id | point_ref`; `record_result(…, points)`). Then:
the settlement transaction with the result point's `workspace_checkpoint_ref` and
`budget_snapshot`; `point_reconciliation.py` with the `TimeTravelLane.collect_points` port
(Deep Agents implementation delegates to `collect_points`), route, CLI flag, MCP tool; the two
canonical event writers and the callers passing unit key, activation and point; `released_by`
and `continues_from` on the proposals (goldens regenerated); `completion_repository.py` inside
the family transaction; `record_rollover` action, event and workflow call; `cycle_start` and
`rollover_start` parents; `mission_run.temporal_*` at launch; the `reused` point in
`_settle_reused`. **Commit.**

**WP-TR-2, capture completeness (deep_agents, with the general promoter).**
`_ModelRequestObserver` and `model_request_body`; `application/frames/capture_policy.py`
(`standard`, `full_requests`) selected by `MISSION_CONTROL_FRAME_CAPTURE_PROFILE` and recorded
on the harness execution; `adapters/storage/frame_body_promoter.py` and the `frame-body://`
scheme in the body reader; the promoter and policy passed at the adapter's `FrameWriter` site;
real `KernelHookPorts` in the composition (fence gate, intent ledger shim, stream-writer frame
sink, usage recorder) and the callback endpoint minted at prepare; `subagent_started/ended` in
the recorder and nested points in the collector; the materialization manifest frame and
`state-as-of` listing sandbox uploads; `after_point_ref` on the stream frame payload.
Streams: the observer and recorder beside the promoter and policy beside the hooks. **Commit.**

**WP-TR-3, read model and retention (general).** `mc.transcript_entry.v2`; `--by` and
`--point` on the transcript; frames-by-point; the artifact download route and `run artifact`;
`replay --dry-run`; the projection activity registered on the maintenance worker, triggered
from settlement through the outbox and by `transcript/refresh`, writing `transcript_entries.py`;
the retention classes and the narrowed expiry; `state-as-of` with `withheld`. **Commit.**

**WP-TR-4, the precise fork (general, one deep_agents part).** `domain/programs/dependencies.py::stage_descendants`;
closure in `SemanticForkService.prepare` with the receipt fields; `StageGraphRunInput.start_position`
honoured by `interpreter.initial_projection`; `GoalDirectedRunInput.start_position` honoured by
`initial_state`; the Goal Directed reuse rule and the derived identity substitution;
`run_launch._apply_fork` filling both; `message` with the `instruction` alias and the delivery
decided by the seed; the seed head with the message in `time_travel.py::seed_fork`
(deep_agents); `run fork --at --point --inject`. **Commit.**

**WP-TR-5, the remote saver (deep_agents, general outcomes).** The locator digest on pins and
keys; bounded `alist` in `_classify` and `_own_result_config`; the points walk budget and
`points_incomplete`; the copy on a worker activity; `503 state_unavailable`;
`cognitive_seed_unavailable`; the topology note for the ADR candidate. **Commit.**

## 7. Minimal verification (per package, reported passed, failed, blocked, unrun)

Ruff and mypy on changed modules; `tests/architecture`; the unit suites of the touched
packages; the release proof; then the acceptance proofs on the production offline stack as
P9 specifies: after WP-TR-1 FX-TR-RECONCILE and the lifecycle half of FX-TR-STEP plus the four
FX-DA proofs on 1.4.4; after WP-TR-2 FX-TR-STEP in full, FX-TR-SUB, FX-TR-HOOK; after WP-TR-3
FX-TR-RETAIN, FX-TR-REPLAY; after WP-TR-4 FX-TR-FORK-CYCLE, FX-TR-FORK-GD, FX-DA-FORK; after
WP-TR-5 FX-TR-REMOTE. The FX-TR fixture needs the four-stage blueprint with a cycle policy on
S2 and the scripted `evaluation: cycle` twice (P9); build it in WP-TR-1. The RF-20 set is
pre-existing.

## 8. Non-goals

Real-model runs (Stage 2); the review, simplification, test-gap and documentation pass
(Stage 3); output contracts, K04, K05, K11, the `progress_note` tool, pruning (TR-D17), the
Agent Server's move to the Postgres edition and the child-state read through its API. Nothing
changes the reducers' authority, the Temporal-only scheduling rule, or the separation of
application PostgreSQL from Temporal persistence. No push, no merge, no deployment, no paid run.

## 9. End with

The ledger entry in [CHANGES.md](../../../provider-consolidation-2026-10/providers/deep_agents/CHANGES.md) (one row per change, general or deep_agents,
finished part, proof; checks run; the honest list of what is not materialized); one finished
part to read in reading order (`application/execution/operations/checkpoint_lineage.py` →
`adapters/postgres/operations/checkpoint_lineage.py` → `adapters/deep_agents/adapter.py::_ModelRequestObserver`
→ `application/frames/transcript.py` → `application/recovery/run_forks.py::prepare`); the
sequence it sits in (the proposal's closing diagram); the two commands with what the owner
sees: `missionctl run transcript RUN --by step --point ID --full`, then
`missionctl run fork RUN --at stage:S2,cycle:2 --point ID --inject msg.json` and
`missionctl run transcript DERIVED --by stage`; and the handoff `SESSION-STAGE-2.md` (the live
fixture plan, the models the owner names, the budget split under 10 USD, the F-T3-1 fix as
the first item).
