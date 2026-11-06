---
type: Concept
category: boundaries
title: Mission Control
description: What Mission Control is, what it owns (admission, scheduling, mission state, lane control, selection, the common database component, the public surfaces), what it refuses (entity writes, a second scheduler, application content, hidden authority) and how source ownership is layered so a change lands in the right package.
tags: [mission-control, boundary, architecture, source-ownership, refusals]
aliases: [source ownership, module map, layering, service boundary]
questions:
  - What does Mission Control own and what does it refuse?
  - Which package owns this code and where does my change go?
  - Who writes entities, and who schedules work?
  - Why can the kernel not import Biotech or AI Engineer code?
updated: 2026-11-01
---

# Mission Control

Mission Control is the shared control service that brings agent platforms (Deep Agents first;
Claude Agent SDK, Codex, Cursor, hosted Claude and Codex agents as adapters) under one roof as
robust, controllable **missions**, supplied as a real service. It turns an outcome into an admitted,
durably scheduled mission for one of two applications and computes whether the result is accepted
([goal](goals.md#goal-mission-control-service)). It is not an agent framework and not a knowledge
store: it wraps each provider's native lifecycle in a Temporal workflow so it can read and write
mission state snapshots and control the run (fork, queue a message, inject context, interrupt).

## What it owns

- **Admission and identity.** Scope is installation, application, tenant and actor on every request
  and record ([lifecycle](lifecycle.md), [applications](applications.md)).
- **Scheduling.** Temporal alone schedules missions, fed by a transactional outbox (ADR-0004);
  Deep Agents is bounded operation cognition and Agent Server hosts async children but schedules
  nothing (ADR-0005, ADR-0006). Reducers own lifecycle and settlement. See
  [workflow systems](workflow-systems.md) and [temporal synthesis](temporal-synthesis.md).
- **Mission state.** Authoritative state is separate from advisory memory and from runtime
  checkpoints (ADR-0007). Accepted command, delivered signal and applied effect are distinct.
- **Lane control.** Nine lane profiles behind one harness protocol (`LANE_PROFILES`,
  `src/mission_control/domain/execution/lanes.py:78-88`; ADR-0035, ADR-0050); see
  [lanes and harness](lanes-and-harness.md).
- **Selection.** One resolution seam over declared lane, model and application registries
  (ADR-0063): [selection workspace](selection-workspace.md), [application profile](application-profile.md).
- **The common database component.** One schema release installed identically into each
  application's own PostgreSQL ([database component](database-component.md), ADR-0002, ADR-0003).
- **Public surfaces.** HTTP, `missionctl`, the MCP servers, Socket.IO; the dashboard control plane
  is a goal ([interfaces](interfaces.md), [coordinator surface](coordinator-surface.md),
  [mission stream](mission-stream.md)).

## What it refuses

| Refusal | Why | Where it is pinned |
| --- | --- | --- |
| Writing application entities | A Domain Service judges evidence and writes; the kernel only sends governed intents through Knowledge Services ([knowledge services](knowledge-services.md)) | ADR-0059; `tests/architecture/test_package_boundaries.py:475` (kernel names no application) |
| Importing Biotech or any application | Application logic runs behind an admitted interface; `integrations/biotech` is optional | `test_package_boundaries.py:178` |
| A second scheduler or compatibility kernel | One scheduler and one writer must be provable | ADR-0001, ADR-0004 |
| Sharing one checkpoint namespace or database across applications | A token for one application never acquires the other's authority | ADR-0002, ADR-0009 |
| Agents writing tables | Agents act through tools and effects, never SQL | ADR-0056 |
| Memory or a signal as authority | Advisory memory and signals are evidence, never authority | ADR-0007, ADR-0045 |
| Decoding a sealed lane binding outside the lane package | Lane packages own their writers (OC-R3) | `test_package_boundaries.py:391,411` |
| Eve as a lane | Not supported or planned | ADR-0014 |

## Applications own content

The two applications (AI Engineer, Biotech) own their entity stores, schemas and domain judgement;
Knowledge Services owns the shared knowledge contracts and operations. Mission Control carries
**what may differ per application as data** (`deployments/<app>/application.toml`), never as code
that names an application. Cross-repository navigation: [applications](applications.md).

## Layers and where a change lands

Interfaces call application handlers; application uses domain rules and ports; adapters implement
ports; bootstrap wires them. Domain imports no database, Temporal, FastAPI or provider SDK
(`test_package_boundaries.py:117`).

| Package | Reason to change it |
| --- | --- |
| `contracts` | Public request and receipt shapes, canonical bytes, resource identity |
| `domain` | Pure program interpretation, admission and lifecycle meaning, resolution types (`domain/resolution`) |
| `application` | Use cases: missions, execution, programs, recovery, resolution, selection (`application/resolution`, `application/selection`) |
| `adapters` | SQL, Temporal, Deep Agents, Agent Server, storage and every provider lane's mechanics |
| `interfaces` | Parse and authorize transport requests, return typed outcomes |
| `bootstrap` | Bind installation configuration to restricted pools and process roles |

A new workflow is not a new scheduler: Stage Graph and GoalDirected share governed operation
execution, budgets and settlement. Do not put application logic into HTTP dependencies or provider
callbacks. Definitions and compiled bindings are immutable; runtime state belongs to scoped
repositories. One distribution imports `mission_control` from `src/mission_control`
(`test_package_boundaries.py:210`); do not recreate `app/`.

## Persistence and events in one paragraph

Mission Control's schemas live in each application's Supabase PostgreSQL and relate to the
knowledge schemas (KS, AIDB, BKS). Temporal persistence and Agent Server persistence are separate
databases (ADR-0017). Granular workflow and agent events are published over Redis and Socket.IO;
Postgres is the replay source. See [persistence](persistence.md), [database component](database-component.md)
and [mission stream](mission-stream.md).

Built / specified / goal: scheduling, admission, layering and the refusals are implemented and
tested (architecture tests above); W0 is the only released qualification gate
([qualification](qualification.md)). The service as a real deployment is a proposal
([deployment](deployment.md)); one local-and-cloud session and the dashboard are goals.

## Citations

- Decisions: [ADR-0001](../adr/0001-one-python-distribution-clean-transformation.md),
  [ADR-0002](../adr/0002-one-service-two-applications-schema-per-app-database.md),
  [ADR-0004](../adr/0004-temporal-sole-scheduler-transactional-outbox.md),
  [ADR-0005](../adr/0005-deep-agents-first-extend-not-fork.md),
  [ADR-0007](../adr/0007-authoritative-state-separate-from-advisory-memory.md),
  [ADR-0014](../adr/0014-eve-excluded.md),
  [ADR-0063](../adr/0063-one-resolution-seam-over-declared-lane-model-and-application-registries.md).
- Code: [composition](../../src/mission_control/bootstrap/composition.py),
  [scoped mission service](../../src/mission_control/application/missions/service.py),
  [public contracts](../../src/mission_control/contracts/contracts.py),
  [lane profiles](../../src/mission_control/domain/execution/lanes.py),
  [runtime navigation](../../src/mission_control/AGENTS.md).
- Tests: [package boundaries](../../tests/architecture/test_package_boundaries.py).
- Owner model: [REFACTOR-PLAN §1](../specs/agentic-sdlc-2026-11/truth-pass/mission-control/REFACTOR-PLAN.md).
