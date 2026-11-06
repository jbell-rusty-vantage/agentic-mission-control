---
type: Concept
category: surfaces
title: Coordinator surface
description: How a coordinator agent (or the owner's own agent tool) drives Mission Control through the mission-control skill router, the missionctl CLI, the operator and coordinator MCP servers and the HTTP API; which part of the coordinator-surface proposal is built (OVE-182 focused inspection, attention and wake channels), which is specified only, and the dashboard control plane as a goal.
tags: [mission-control, coordinator, skills, cli, mcp, dashboard, surfaces]
aliases: [mission-control skill, skill router, missionctl grammar, agent skills and CLI, dashboard control plane]
questions:
  - How does a coordinator agent drive Mission Control end to end?
  - Which skill bundle do I load to author, observe or intervene?
  - What is built of the coordinator-surface proposal and what is not?
  - What does the dashboard control plane need that does not exist yet?
updated: 2026-11-01
---

# Coordinator surface

The owner's surfaces for Mission Control are an MCP server, agent skills plus the `missionctl` CLI, the HTTP
API, and later the dashboard control plane. One service sits behind all of them, so the same handler answers
HTTP, CLI and MCP in the principal's verified tenant scope (inventory: [interfaces](interfaces.md)). The aim is
that a coordinator in the agent tool of the user's choice can spawn and supervise big work, across providers,
with granular intervention ([goal](goals.md#goal-mission-control-service)).

## The skill router

`skills/mission-control` (manifest 0.5.0, `mc.skill_bundle.v1`, digest-pinned files) is a router, not a manual
(ADR-0033). It first establishes scope (application, tenant, token through the host's secret mechanism), then
routes by the coordinator's job:

| Job | Bundle | Entry command |
| --- | --- | --- |
| Write, compile, submit, start a `mission.yml` | `mission-control-author` | `missionctl mission compile FILE --json` |
| Find, inspect, pin, publish capabilities | `mission-control-catalog` | `missionctl catalog search --request-file ...` |
| Launch then wait, supervise, inspect on wake, declare watchers | `mission-control-observe` | `missionctl wait --run RUN_ID --wait 600` |
| Queue or inject, cancel, snapshot, fork, reconcile | `mission-control-intervene` | `missionctl command send RUN_ID --request-file ...` |
| Chain missions and move state between them | `mission-control-compose` | `missionctl chain inspect CHAIN_ID --json` |

Invariants every bundle carries: admission is not delivery and delivery is not an applied effect; execution
completion is not acceptance; skill prose, catalog rank and model output grant no authority; every mutation
carries a UUID `request_id`; run `missionctl preflight` before launching and relay owner prerequisite steps
([owner prerequisites](owner-prerequisites.md)). Executor-side skills are separate bundles mounted into
missions (`mc-cognition-*`, `mc-signals`, the knowledge charters; [capability seeds](capability-seeds.md)).

## What is built (OVE-182, WI-19)

The focused part of the proposal was adopted into Sprint OC (OC-D125/126/176) and built:

- **Focused inspection:** effective configuration, outputs, inputs, fulfillment and transfer plans through
  `run inspect`, `outputs show|revisions|events|plans|plan`, `run evidence|inputs` routes and the matching MCP
  tools ([output contracts](output-contracts.md)).
- **Wake channels:** `missionctl wait`, the inbox long-poll and MCP `coordinator_inbox_wait`
  ([wake channels](wake-channels.md)).
- **Attention:** six separately recorded delivery stages, a per-delivery nonce and bounded content retrieval
  ([coordinator attention](coordinator-attention.md)); implemented and tested on PostgreSQL, the real
  coordinator-host run (C14) is unrun.
- **Selection:** `missionctl search` / `workspace check` and MCP `mission_search` / `selection_check`
  ([selection workspace](selection-workspace.md)). The skill router does not mention them yet: no file under
  `skills/mission-control*` names `missionctl search` or `selection_check`, and the agent-skills seed carrying
  that guidance (1.0.4) is not the released W0 bundle (STATE D11).
- **Position on events:** `unit_key` and `point_ref` are optional fields on the `mc.event.v1` envelope
  (`domain/subscriptions/contracts.py:196-197`), so a consumer jumps from an event to a point
  ([joinability](unit-and-point-joinability.md)).

## Specified, not built

The 2026-10-22 proposal ([PROPOSAL](../specs/coordinator-surface-2026-10/PROPOSAL-COORDINATOR-SURFACE-2026-10-22.md),
program ledger [LEDGER](../specs/coordinator-surface-2026-10/LEDGER.md), status `open`) remains unadopted beyond
the focused part: the noun-verb grammar `missionctl <noun> <verb> TARGET --at <coordinate>` with one-release
aliases (CS-D1), per-family bundles (`stage-graph`, `goal-loop`, `lanes`; CS-D2), thin digest-pinned `scripts/`
(CS-D3), `node describe` over the sealed binding (CS-D4), a Deep Agents specifics sheet and a generated
staying-current reference (CS-D8/D9), retiring the legacy coordinator launch path (CS-D12), and a Socket.IO CLI
client (CS-D11). ADR-0049 (inbox wait replaces `mission_subscribe` push) is built but its status is a separate
decision ([decisions](decisions.md)). `skills/mission-control/references/protocol.md` still carries fast-track
`Availability: FT-xx` markers that the shipped commands have overtaken.

## Dashboard control plane (goal)

No dashboard exists. A dashboard subscribes on Socket.IO to a run or mission target for `mission_event`,
`provider_frame`, `lineage`, `command_receipt` and `human_task_receipt`, and resumes from cursors
([mission stream](mission-stream.md)). The proposal's section 5.2 lists what it would still lack; checked
against code on 2026-11-01:

| Gap | State |
| --- | --- |
| Unit and point on every event | partly built (`unit_key`, `point_ref`); no `location` object |
| Program-level events (`stage.released`, `stage.decided`, `iteration.decided`) | not built (no such alias in `src/`) |
| `point.recorded`, `transcript.projected`, `budget.threshold_crossed` | not built |
| A read of the compiled program graph | not built (no revision/program route) |
| Budget state on the public API | technical facade only |

The human review loop (output reaches the owner, who continues, rejects with feedback and redoes, or starts
new) is a goal on the same surface; Human Gates exist, the loop is specified in the
[review-gates supplement](../specs/proposals-2026-10/HUMAN-REVIEW-GATES-AND-STEERING-SUPPLEMENT-2026-10-22.md) and not built
([human gates](human-gates.md), [goals](goals.md#goal-human-review-loop)). A sandboxed agent's filesystem path into the
catalog, the Catalog Workspace, is a separate goal ([goals](goals.md#goal-catalog-workspace)).

Built / specified / goal: skill router, CLI groups, MCP tools, wake channels and attention are implemented and
tested; the proposal's grammar, bundles and node describe are specified; remote MCP OAuth and the dashboard
control plane are goals.

## Citations

- Dashboard control plane and human steering (proposal): [next-stage contract design](../specs/proposals-2026-10/MISSION-CONTROL-NEXT-STAGE-CONTRACT-DESIGN-2026-10-16.md) and its [evidence](../specs/proposals-2026-10/MISSION-CONTROL-NEXT-STAGE-EVIDENCE-2026-10-16.md).
- ADR: [0033](../adr/0033-mission-control-skill-is-a-router-over-specific-skill-bundles.md),
  [0049](../adr/0049-deprecate-mission-subscribe-push-in-favour-of-inbox-wait-channels.md),
  [0015](../adr/0015-remote-mcp-oauth-no-jwt-forwarding.md).
- Program: [coordinator-surface README](../specs/coordinator-surface-2026-10/README.md),
  [proposal sections 5 and 7](../specs/coordinator-surface-2026-10/PROPOSAL-COORDINATOR-SURFACE-2026-10-22.md),
  [state-of-work D11](../specs/agentic-sdlc-2026-11/STATE-mission-control-2026-11.md).
- Skill: [router](../../skills/mission-control/SKILL.md), [manifest](../../skills/mission-control/manifest.json),
  [protocol](../../skills/mission-control/references/protocol.md).
- Code: [coordinator MCP](../../src/mission_control/interfaces/mcp/coordinator_server.py),
  [operator MCP](../../src/mission_control/interfaces/mcp/operator_server.py),
  [CLI](../../src/mission_control/interfaces/cli/main.py), [wait](../../src/mission_control/interfaces/cli/wait.py),
  [event envelope](../../src/mission_control/domain/subscriptions/contracts.py),
  [attention rules](../../src/mission_control/domain/coordinator/attention.py).
- Tests: [wake channels](../../tests/acceptance/mission_control/test_wake_channels.py),
  [attention PostgreSQL](../../tests/integration/postgres/test_wi19_attention_postgres.py),
  [public interfaces](../../tests/unit/mission_control/test_public_interfaces.py).
