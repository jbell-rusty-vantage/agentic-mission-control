---
type: Working Draft
title: "Phase A reports: what the three concept-refactor agents changed and found"
description: "The coordinator's record of the Mission Control truth-pass Phase A agents' reports (A1 workflows, A2 runtime, A3 platform): files, renames, harvested spec-pack items, code defects for OVE issues, cross-agent follow-ups for Phase B, and the commits that carry each agent's work."
tags: [mission-control, truth-pass, sdlc, refactor]
date: 2026-11-01
status: draft
---

# Phase A reports

`BEFORE_COMMIT` (documentation before the refactor): `66185d2e`.

## A1 workflows (finished 2026-11-01)

- Rewritten: `workflow-systems` (106 lines, one system × level table), `parallel-swarm` (106),
  `evaluator-optimizer` (93), `mission-chains` (134; Child Mission Invocation "not built"),
  `output-contracts` (155), `context-and-continuation` (138), `completion` (121), `revisions` (88;
  per-policy mutation goal), `human-gates` (120; review-loop goal).
- New: `stage-graph` (131), `goal-loop` (139; target model beside the built GoalDirected subset).
- Edited: `recursive-composition` (158), `lifecycle` (99), `interventions` (160),
  `durable-controls` (138), `mission-manifest` (113).
- Deleted: `continuation-checkpoint.md` (RENAMES.md line).
- ADR draft: `ADR-0068-DRAFT.md`; its link `../adr/0068-…md` resolves once Phase B creates the ADR.
- Spec-pack items placed: Goal Loop governance → `goal-loop`; Child Mission Invocation, Portals,
  Spawn Grants → `mission-chains`; fan-out and deterministic executor kinds → `workflow-systems`;
  state handoff and memory contracts → `context-and-continuation`; evolution rules →
  `output-contracts`; review packet design → `human-gates`. Left out: agent binding levels
  (superseded by ADR-0063), annex 08 §15 open questions.
- Code defects (OVE issues): (1) `parallel_swarm` or `evaluator_optimizer` roots compile on Deep
  Agents with no blocker or warning and lower to a one-stage Stage Graph
  (`manifest_lowering.py:709-712`; reproduced with the `test_lane_support_matrix` manifest);
  (2) four-family vocabulary vs three decided behaviours (OC-D204/D205); (3) migration key 0071
  claimed by nested activations and `sprint-oc-wi15`; (4) mission lifecycle values differ between
  spec and schema (`draft/admitted/active/paused/closing/closed` vs
  `drafting/ready/running/dormant/closed`); (5) `missing_output_policy` follow-up exists on Cursor
  lanes, missing-output facts on Claude/Codex, nothing found for Deep Agents.
- Unverified: NEXT-SESSION line ranges approximate; linked-run details from prose.
- Follow-ups: A3 to fold `authoring.md` (mission-manifest links `coordinator-surface.md`); Phase B
  rewrites inbound links to `continuation-checkpoint.md` in `index.md`, `log.md`,
  `provider-lanes.md`; A2 to confirm `provider-lanes`/`cursor-lane` carry launch-binding detail.

## A2 runtime (finished 2026-11-01)

- Deleted: `async-children.md`, `deep-agents-turn-stops.md`, `execution.md` (RENAMES.md lines).
- New: `deep-agents-children` (116), `temporal-synthesis` (122), `provider-batch` (87).
- Rewritten: `deep-agents-lane` (160), `agent-configuration` (122), `lanes-and-harness` (144),
  `provider-lanes` (158), `cursor-lane` (160), `hosted-api-lanes` (57),
  `session-ownership-and-dispatch` (144), `recovery` (144), `precise-fork` (132),
  `durable-reactions` (156), `watchers` (158), `coordinator-attention` (141),
  `placement-admission` (74), `hook-contributions` (150), `instruction-layering` (89),
  `model-catalog` (129), `capabilities` (157), `capability-seeds` (111).
- Research: `docs/research/deep-agents/sandbox-providers.md`, `deep-agents/surface-0.7.5.md`,
  `daytona/sandbox-tiers.md`, `cursor/sdk-facts.md` (sheet is 1.0.31; pin is `cursor-sdk==1.0.37`,
  noted), `eve/facts.md`, `provider-batch/batch-apis.md`.
- Spec-pack items placed: `mc.extension_profile.v1` and required middleware order (not built) →
  `deep-agents-lane`; parent/child message protocol → `deep-agents-children`; Agent Host
  generation → `capabilities`.
- Code defects (OVE issues): Daytona admitted by the contract but no factory;
  `deployment_composition.py:523` routes any backend other than `state`/`docker` to the LangSmith
  factory, which refuses it at run time; `provider_options.py:83` omits `daytona`;
  `describe.py:80,113` unshipped cancel/cost cells; `project_sandbox_egress` tested but never called
  in production (no SandboxHost port, no Daytona adapter); `adapters/deep_agents/AGENTS.md` says
  Docker lives in `materializer.py` (it is `docker_sandbox.py`); `src/mission_control/domain/AGENTS.md:13`
  points at `execution.md`.
- Unverified: owner's Daytona tier (Tier 4 header vs "Tier 1/2"); `langchain-daytona` 0.0.8 vs
  deepagents 0.7.5; 0.7.30 facts from a wheel read; whether the paid `test_agent_configuration_live.py` ran.
- Follow-ups for Phase B: inbound links to the renamed concepts in `AGENTS.md`, `index.md`, `log.md`,
  `mission-control.md`, `saved-result-settlement.md`. Category note: A2 put `capabilities`,
  `capability-seeds`, `coordinator-attention` in `execution` (REFACTOR-PLAN); CONCEPT-LISTS had them in
  `surfaces`. Phase B keeps REFACTOR-PLAN's placement.

## Loose Mission Control documents found outside any repository (Phase B intake)

`platform/` is not a git repository; these files are tracked nowhere. Phase B **copies** them into
Mission Control (originals stay until the owner confirms removal) and links them from the concepts:

| File in `platform/` | Destination in MC | Linked from |
| --- | --- | --- |
| `PROVIDER-BATCH-INFERENCE-PROPOSAL-2026-10-18.md`, `PROVIDER-BATCH-INFERENCE-EVIDENCE-2026-10-18.md` | `docs/specs/proposals-2026-10/` | `provider-batch`, `goals` |
| `HUMAN-REVIEW-GATES-AND-STEERING-SUPPLEMENT-2026-10-22.md` (the human review loop design: verdict plus typed riders, Review Assistant, persistence, worked example, an owner-approved review round) | `docs/specs/proposals-2026-10/` | `human-gates` (Phase B updates A1's review-loop section to state what this supplement specifies vs what is built), `goals` |
| `MISSION-CONTROL-NEXT-STAGE-CONTRACT-DESIGN-2026-10-16.md`, `MISSION-CONTROL-NEXT-STAGE-EVIDENCE-2026-10-16.md` | `docs/specs/proposals-2026-10/` (dashboard control plane, HITL, batches, capability evolution backlog) | `goals`, `decisions`, `coordinator-surface` |
| `MISSION-CONTROL-CAPABILITY-EVOLUTION-RESEARCH-2026-10-14.md` | `docs/research/mission-control/capability-evolution-2026-10-14.md` (Research frontmatter) | `capabilities`, `model-catalog` |

`docs/specs/proposals-2026-10/LEDGER.md`: one row per proposal, status `open` (proposal, not built),
next step "owner interview before building". Rewrite relative links inside the copied files that
pointed at `platform/` siblings. Not moved: `platform/AGENTS.md` (workspace guide),
`sonnet_conversation_research_and_education.md` and `supabase_agent_prompt.md` (owner's material).

## A3 platform (finished 2026-11-01)

- New: `mission-control`, `applications`, `coordinator-surface`, `database-component`,
  `documentation-retrieval-fixtures`, `deployment`, `decisions`, `goals` (stable anchors such as
  `#goal-mission-control-service`, `#goal-local-cloud-one-session`).
- Rewritten or fixed: `knowledge-services`, `application-profile`, `interfaces`, `mission-stream`,
  `selection-workspace`, `signal-ingress`, `wake-channels`, `persistence` (invariants only),
  `provider-frames-and-transcript`, `saved-result-settlement`, `collections-and-current-sets`,
  `workspace-closure`, `unit-and-point-joinability`, `qualification`, `trusted-judgment`,
  `evaluator-attempts`, `operations`, `environments` (156), `environment-preparation` (154),
  `secret-broker`, `budgets-and-usage`, `owner-prerequisites`, `owner-probe-bootstrap`.
- Deleted (RENAMES.md): `architecture` → `mission-control`, `transcript-projection` →
  `provider-frames-and-transcript`, `release-and-qualification` → `qualification`.
- Spec-pack items placed: G0-G7, C0-C4, `ProofBudget` as history in `qualification`; unbuilt usage
  ledger in `budgets-and-usage`; unbuilt interface catalog in `interfaces`; deployment/release
  expansion in `deployment`. Left out: the expansion packet's four proof-status labels (repo uses
  implemented/tested/integrated/qualified); the "required now or after parity" KS tension.
- Product idea: a narrative / as-of read over run history (→ ideas workspace).
- Code/config defects (OVE issues): `deployments/ai-engineer/release.lock.json` pins 1.4.2 and
  `deployments/biotech/release.lock.json` pins 1.3.0 while remotes are at 1.8.0; `UPSTASH_*` names
  read by no code (only `REDIS_URL`); `hosted_session_retention_days` unread;
  `skills/mission-control/references/protocol.md` carries `FT-xx` availability markers; skill
  bundles do not teach `missionctl search` or `workspace check`.
- Unverified: stream on Upstash; remote installs beyond 1.8.0; a populated embedding projection;
  NEXT-SESSION 119-124 exact lines; D4, D5, D9 status inferred from code presence.
- `authoring.md`: not folded by A3 (A1 asked); Phase B decides (fold into `coordinator-surface` or
  `mission-manifest` if it fits, else keep under `surfaces`).
- Phase B: repoint `decisions.md` ADR-0068 row to `docs/adr`; `index.md`/`log.md` links to
  `execution`, `async-children`, `deep-agents-turn-stops`, `continuation-checkpoint` and the three
  A3 renames; ADR-0068 links in `workflow-systems`, `parallel-swarm`, `evaluator-optimizer`; Sprint
  OC documents link the deleted `OUTPUT-CONTRACTS.md`.
- Owner confirmation pending: "workspace navigation based search" read as the Selection Workspace.
