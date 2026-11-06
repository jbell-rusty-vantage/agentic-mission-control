---
type: Concept
category: execution
title: "The precise fork"
description: How a fork names a position, a cognition point and a message, how the invalidation frontier is closed, where the derived run starts, how the seed head is built inside the fork saga, what the Goal Directed family refuses and which typed outcomes an operator sees.
tags: [mission-control, implementation, fork, tracing]
aliases: [cognition-point fork, invalidation frontier, seed head, fork --at --point --inject]
questions:
  - How do I fork at a cognition point and inject a message?
  - Which typed outcome did my fork or launch return?
  - How is the invalidation frontier closed?
  - What does a Goal Directed fork refuse?
  - Who may admit a derived run's fork configuration?
updated: 2026-11-06
---

# The precise fork

The precise fork (tracing Stages 1 to 3) extends the semantic fork described in
[recovery](recovery.md): the operator names where the derived run resumes (`--at`), which
recorded cognition point its cognition continues from (`--point`), a message to inject
(`--inject`) and which stages to re-run (`--frontier`). Every refusal is a typed
`ForkRejected` code, mapped to HTTP in `interfaces/http/run_forks.py`.

## Position, point and message

- `--at stage:S2,cycle:2` or `--at iteration:3[,session:1]` becomes the request's `at`
  (`parse_fork_at` in the CLI). `--point ID` looks the point up and fills the
  `cognitive_seed` (unit key and checkpoint key) and, when `--at` is absent, `at` from the point's
  location (`_fork_position`). A position of the other family, or one that is not the seed
  point's unit, is `invalid_patch`.
- `--inject FILE` is the request's `message`. With a `cognitive_seed` and inline text the message
  becomes the seed head's last human message (`message_delivery: seed_head`); otherwise it is
  queued to the derived run's mailbox (`mailbox`) as the older `--instruction-file` was
  (`_message_delivery`).
- The kernel route `POST /run-control/v1/runs/{id}/forks` composes no seed and no mailbox, so it
  refuses a `message` with 422 `invalid_patch` (reason `message_not_deliverable`); the mission fork
  route delivers it.

## Frontier closure

`SemanticForkService._close_frontier` closes the requested frontier (the `at` stage plus every
`--frontier`) over the source blueprint: `closed_frontier` is `frontier | descendants(frontier)`
(`domain/programs/dependencies.py`). `--frontier-policy close` (default) records and uses the
closed set; `strict` refuses a narrower frontier with `frontier_not_closed`, naming the missing
stages. A stage the blueprint does not know is `invalid_patch`. Without a blueprint reader
nothing is closed: the receipt's `frontier_closed` is then empty (honest, not its own
closure) and `strict` refuses `frontier_closure_unavailable` (503). A Goal Directed run, an empty
frontier or the invalidate-all marker is its own closure.

## Where the derived run starts

`_start_position` builds the `start_position` the launch carries into the family input.

- Stage Graph: the `at` stage must have been reached (else `fork_position_unavailable`). Every
  stage outside the frontier starts at the cycle the source holds it at, with that cycle's
  objective, so a reused upstream stage that cycled is not re-run from cycle 0. The snapshot
  records only the current cycle's objective of each stage, so a fork at an older cycle above 0
  is refused `fork_position_unavailable`.
- Goal Directed: every iteration below `at.iteration` must be reused (executor and verifier),
  else `fork_position_unavailable` (a whole-run patch such as a new goal objective re-runs them
  all). An iteration the source never reached is refused, and so is a source whose Goal Revision
  changed below the fork iteration (`_check_goal_position`). The derived run's agent-run count
  follows the last reused unit; its session generation comes from the seed point
  (`at.session_generation` defaults to it and may not name another).

## Starting a derived manifest run, and its reused named outputs

A fork admits the derived run with a run-request definition, not a `MissionDefinition@1`.
`missions:start {"run_id": <derived>}` resolves the fork (`StoredForkSources`) and starts from the
**source** run's submission (F1-G2): `ManifestLaunchInputAuthor.fork_family_input` prepares the
Stage Graph input for the derived admission (source's human gates and authored inputs, the fork's
binding) and the governed launch derives the templates from the source's binding. Typed 409
`ManifestStartRefused` codes, never a 500: `fork_start_unavailable`, `not_a_manifest_run`,
`fork_source_not_manifest`, `fork_family_input_derived`, `fork_start_unsupported` (Goal Directed:
use `/runs/{id}/launch`), `definition_unreadable`.
A reused unit carries the source's **accepted** revisions of its stage's promises before it settles
(F1-G4, `application/recovery/fork_outputs.py`): one host invocation of the derived unit (lane
`fork_reuse`) adopts them (adopter lineage `fork_reuse:<fork request>`), finalizes without an
assessment handoff and promotes them, so they are never judged again; the consumer's plan then
resolves them like any accepted head. A terminal refusal settles `fork_outputs_not_carried`.
Stage Graph only; assessments of requirement-bearing promises are not carried (they then wait).

## The seed head

`CognitiveSeedService.resolve` admits a seed only for a recorded, `seedable` checkpoint point of
the named unit whose lane declares `time_travel.fork: R3`; the checkpoint key is compared without
the saver locator. A Goal Directed verifier point is refused `cognitive_seed_not_supported`
(no derived unit continues a verifier thread). `seed` then asks the lane's `seed_fork` to copy the
source thread's root lineage up to the point into the derived unit's own namespace (the source is
never written; on a deployment with a maintenance worker the copy is the `mc.fork_seed.v1`
workflow, `adapters/temporal/activities/fork_seed.py`), sets the namespace head, and records a
`fork_seed` point on the derived run.

The head is the state at the point, plus the injected human message when there is one
(`adapters/deep_agents/time_travel.py`). The point's own pending delta-channel writes are the
outputs of the source's next step, so they are not copied when a message is injected; without a
message the copy continues from the point itself. The head's message count is the one the saver
folds, and an unreported count stays unknown.

Ordering (`SemanticForkService.fork`): the seed runs inside the fork saga as `before_receipt`,
so the receipt exists only once the seed is in place. A fork that has its receipt is never
copied again, which makes replaying the same seeded fork idempotent. Until the receipt exists,
`RunLaunchService` refuses the derived run's launch `fork_seed_pending` (retryable): retry the
fork, then the launch.

## Typed outcomes

| Outcome | Surface |
| --- | --- |
| Saver unreachable, not served or copy incomplete | 503 `cognitive_seed_unavailable`, retryable |
| Derived stage templates do not match the source patch at launch | `fork_templates_mismatch` (`RunLaunchRejected`, `application/execution/run_launch.py:509`); `fork_templates_unavailable` when derivation is not composed |
| Point not seedable, lane not R3, verifier seed | 422 `cognitive_seed_not_supported` |
| Position unreachable or not honourable | 422 `fork_position_unavailable` |
| Strict frontier too narrow | 422 `frontier_not_closed` |
| No blueprint for a strict frontier | 503 `frontier_closure_unavailable` |
| `state-as-of` for a point whose saver state is gone | 404 `point_state_missing` (`interfaces/http/cognition_points.py`) |
| `missions:start` of a derived run it cannot derive | 409 with the `ManifestStartRefused` code (above) |
| A Stage Graph concluded failed (a rejected producer, dependency-starved stages) | `run inspect` `unit_failures`: `stage_rejected:<stage>:<veto>[:<reason codes>]`, `dependency_unresolved:<stage>:<dependency>=<disposition>` (or `producer_skipped`), read from the family journal (`PostgresUnitFailureReader`, F1-G5) |

The saver locator digest (`saver_locator_digest` in `adapters/deep_agents/persistence.py`) names
where a saver lives: host (loopback aliases are one host), port, database and schema, never the
credentials, so the API and the workers compute the same digest from their own DSNs.

## Trusted admission provenance

A caller-authored fork patch cannot supply admission facts. `SemanticForkService` takes a `ForkAdmissionProvenance` (`application/recovery/run_forks.py:1031`), composed in
`bootstrap/composition.py:313` as `ManifestForkAdmissionProvenance` (`application/authoring/manifest_fork_admission.py`): for a manifest-compiled run it requires exactly one submitted
configuration whose actor, program digest, contract (`mc.manifest-compiled-program/1`) and workflow type match the target, else the fork is refused. Qualia recorded-point forks were admitted this way (`0eccfa2d`).

## Baseline reservation

A fork without `--baseline-reservation DIMENSION=AMOUNT` holds the source run's admitted
baseline; each flag overrides one dimension (`_baseline_reservations`). A replay of a fork
reserved earlier keeps the baseline that fork recorded.

Built / specified / goal: built; integrated and live paid (Qualia fork05 and AI Engineer forks, `NEXT-SESSION.md:32-98`); a `cognitive_seed` may name any lane's point (`CognitivePointSeed`) and is admitted at the lane's declared fork level R1 to R3 since 2026-11-05 ([cross-provider control](cross-provider-control.md), tested, not live); `--at` and `--frontier` tested only; the fork-derived `missions:start`, the reused-output carry and the typed concluded-failure causes (2026-11-06, ITER-3 F1-G2/G4/G5) tested on PostgreSQL and in unit tests, not yet live; Stage Graph and Goal Directed positions
only. Forking across lane placements (local to cloud) and forking a *workflow* mid-run by policy are goals ([lanes and harness](lanes-and-harness.md), [revisions](revisions.md)).

## Citations

- [Fork service, closure, start position, seed ordering](../../src/mission_control/application/recovery/run_forks.py),
  [cognitive seed](../../src/mission_control/application/recovery/cognitive_seed.py),
  [fork policy and contracts](../../src/mission_control/domain/policies/forks.py),
  [closure](../../src/mission_control/domain/programs/dependencies.py).
- [Fork-derived start](../../src/mission_control/application/authoring/manifest_submit.py),
  [reused-output carry](../../src/mission_control/application/recovery/fork_outputs.py),
  [proof on PostgreSQL](../../tests/integration/postgres/test_fork_completion_postgres.py).
- [Launch guard](../../src/mission_control/application/execution/run_launch.py),
  [Deep Agents time travel](../../src/mission_control/adapters/deep_agents/time_travel.py),
  [seed activity](../../src/mission_control/adapters/temporal/activities/fork_seed.py).
- [Kernel fork route](../../src/mission_control/interfaces/http/run_forks.py),
  [CLI `run fork`](../../src/mission_control/interfaces/cli/main.py).
- Decision: [ADR-0057](../adr/0057-the-precise-fork-closure-family-position-and-the-seed-head.md).
