---
type: Decision Record
title: The precise fork - closure, family position and the seed head
description: Accepted - a fork names a position, a cognition point and a message; the invalidation frontier is closed over the blueprint, the derived run starts at the family position the source held, and the seed head is built inside the fork saga before the receipt.
tags: [mission-control, adr, accepted, fork, recovery, tracing]
status: accepted
source: docs/specs/archive/provider-consolidation-2026-10/proposals/TRACING-PROPOSAL.md (P5, TR-D12, TR-D13, TR-D14); src/mission_control/application/recovery/run_forks.py; src/mission_control/application/recovery/cognitive_seed.py
---

# The precise fork - closure, family position and the seed head

**Status: accepted 2026-11-01; implemented by tracing Stages 1-3 (`6b3f172f`, `05d92929`, `4a281b36`; Stage 3 finish `34d968ee`, merged 2026-10-22).** Previously proposed.  Extends
[ADR-0032](0032-interventions-real-queue-inject-cancel-fork-and-subscriptions.md).

## Context

A semantic fork re-ran what a patch invalidated, but a stage that consumes an invalidated
stage was reused with a stale input, a reused upstream stage that had cycled restarted at
cycle 0, and a "continue from this step" fork could not carry the cognition itself. A seed
installed after the receipt could leave a launchable run without its seed.

## Decision

1. Position, point, message. A fork may carry `at` (stage and cycle, or iteration and session
   generation), a `cognitive_seed` (a seedable point of a settled unit on a lane that forks at
   R3) and one `message`. With a seed the message is the seed head's last human message;
   without one it is queued to the mailbox.
2. Closure. The invalidation frontier is closed over the source blueprint: `frontier | descendants`.
   `frontier_policy: close` (default) uses and records the closed set; `strict` refuses a narrower
   frontier. Without a blueprint nothing is closed and the receipt says so.
3. Family position. The derived run carries a `start_position`. Stages outside the frontier start
   at the cycle the source held them at; a fork at an older cycle above 0 is refused because the
   snapshot holds only the current cycle's objective. Goal Directed reuses by iteration
   (TR-D14, option B): the iterations below `at` must all be reused, the revision must not have
   changed below it, and a verifier point cannot be a seed.
4. Seed head. The state at the point plus the injected message; the point's own pending delta
   writes are not copied when a message is injected. The seed runs inside the fork saga before
   the receipt, so a launch refuses a seeded fork without it (`fork_seed_pending`), a saver
   failure is `503 cognitive_seed_unavailable` and the fork stays replayable, and replaying a
   fork that has its receipt never copies twice.
5. A fork without `--baseline-reservation` holds the source run's admitted baseline.

## Consequences

- A fork is exact about what it re-runs, where it resumes and what the unit's thread holds.
- Refusals are typed (`frontier_not_closed`, `fork_position_unavailable`,
  `cognitive_seed_not_supported`) instead of starting a derived run that cannot honour the request.
- Known limits: a Goal Directed fork where a revision changed below the fork iteration is refused;
  Cursor Cloud fork restore is not built; forks at an older cycle above 0 need a richer snapshot.

# Citations

- [Fork service, closure and start position](../../src/mission_control/application/recovery/run_forks.py),
  [cognitive seed](../../src/mission_control/application/recovery/cognitive_seed.py),
  [fork policy](../../src/mission_control/domain/policies/forks.py),
  [closure](../../src/mission_control/domain/programs/dependencies.py),
  [launch guard](../../src/mission_control/application/execution/run_launch.py),
  [Deep Agents time travel](../../src/mission_control/adapters/deep_agents/time_travel.py).
- Concept: [The precise fork](../knowledge/precise-fork.md).
