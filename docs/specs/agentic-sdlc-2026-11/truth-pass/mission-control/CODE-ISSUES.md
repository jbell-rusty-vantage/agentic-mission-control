---
type: Working Draft
title: "Code issues found by the Mission Control documentation truth pass"
description: "Every code, seed or configuration defect the Phase A and Phase B agents found while checking documentation against source (OVE-206), one row each with evidence and a suggested owner program, for the coordinator to file as Linear issues. None was fixed in the refactor; documentation states each as it is."
tags: [mission-control, truth-pass, sdlc, code-issues]
date: 2026-11-01
status: active
---

# Code issues from the truth pass

Written by the Phase B agent, 2026-11-01. The refactor changed no behaviour; each row is a defect or gap the
documentation now states truthfully. Evidence is `path:line` at `sprint-oc` after the refactor commits unless noted
as "reported by Phase A" (read there, not re-read here). The coordinator files the Linear issues. Owner programs:
**Sprint OC** (the Deep Agents goal), **Coordinator surface**, **Agentic SDLC**, **Release/deployment**, **Knowledge Services**.

## Filed 2026-11-02

Filed as themed Linear issues (each with `## Provenance` and a `Goal:` line): OVE-215 (row 6, fixed `064df257`), OVE-216
(rows 1-4; row 2 was **wrong**: deployment pins admit only `state`/`docker`/`langsmith`, so a Daytona profile is refused at
compile as `ITEM_PIN_UNSERVED`, never at run time; the composition is now exhaustive, `4551e533`), OVE-217 (row 8),
OVE-218 (row 22, fixed `e100abcb`: the goldens were stale, not the compiler), OVE-219 (rows 11-13, 15, 17), OVE-220
(rows 10, 18-20, 24), OVE-221 (rows 5, 14, 25), OVE-222 under OVE-207 (rows 9, 16, 21, 23 and the module-guide follow-ups),
OVE-223 (rows 26-29). Row 7 is tracked inside OVE-215. OVE-149 closed (canceled). The rows below stay as the record.

## Deep Agents lane and workflow systems (nearest goal)

| # | Title | Evidence | Suggested owner |
| --- | --- | --- | --- |
| 1 | `daytona` is admitted by the contract, closure, network tier and frame redactor but no materializer factory exists | `domain/execution/contracts.py:684` (backend literal incl. `daytona`); `adapters/deep_agents/materializer.py` has no `daytona` match; `domain/execution/workspace_closure.py:45`; T001 in the fixtures | Sprint OC |
| 2 | Any sandbox backend other than `state`/`docker` falls through to the LangSmith factory, which refuses it at run time | `adapters/temporal/deployment_composition.py:518-523` (`else: LangSmithSandboxFactory()`) | Sprint OC |
| 3 | Provider options and capability pins omit `daytona` from their backend literals | `domain/authoring/provider_options.py:83`; `adapters/capabilities/capability_pins.py:286` | Sprint OC |
| 4 | `project_sandbox_egress` is tested but never called in production (no SandboxHost port, no Daytona adapter) | reported by Phase A2 (`application/environments/network.py`) | Sprint OC |
| 5 | Unshipped describe cells: Deep Agents declares `cancel: turn_boundary_guaranteed` and `cost: estimated` without a shipped proof | `adapters/deep_agents/describe.py:80,113` | Sprint OC |
| 6 | A `parallel_swarm` or `evaluator_optimizer` root compiles on Deep Agents with no blocker or warning and lowers to a one-stage Stage Graph; ADR-0068 asks for a typed `UNSUPPORTED_BEHAVIOR` | `domain/authoring/manifest_lowering.py:709-712` (`_stage_children` returns `(root,)`) | Sprint OC |
| 7 | Four-family vocabulary (`Family`, `FAMILY_OF_BEHAVIOR`, `V2_LANE_BEHAVIORS`, per-family describe rows) contradicts the three decided behaviours (OC-D204/D205, ADR-0068) | `domain/resolution/configuration.py:53-59`; `application/authoring/manifest_v2_admission.py:86`; `application/authoring/manifest_service.py:49,1470` | Sprint OC |
| 8 | `missing_output_policy` follow-up exists on the Cursor lanes and missing-output facts on Claude and Codex; none was found for Deep Agents | `adapters/cursor/local.py:207`, `adapters/cursor/kernel_hook_script.py:99`, `adapters/claude/harness.py`, `adapters/codex/harness.py`; nothing under `adapters/deep_agents/` | Sprint OC |
| 9 | `adapters/deep_agents/AGENTS.md` places the Docker sandbox in `materializer.py`; it is `docker_sandbox.py` (fixed in the module guide by Phase B; the code is right) | `adapters/deep_agents/AGENTS.md:16,22` | Agentic SDLC (S1 module blocks) |
| 10 | Mission lifecycle value names differ between the former spec (`draft/admitted/active/paused/closing/closed`) and the schema (`drafting/ready/running/dormant/closed`); the spec is deleted, so the schema is the authority, but any consumer or skill that used the spec names is stale | reported by Phase A1 (`lifecycle.md` states the schema values) | Coordinator surface |

## Migrations, releases and deployment

| # | Title | Evidence | Suggested owner |
| --- | --- | --- | --- |
| 11 | Migration key reservation: key 0071 is claimed by `scripts/release_200/0071_nested_program_activations.sql` (renumbered 2026-11-01) and by `sprint-oc-wi15`; `sprint-oc-wi14` claims 0070; no rule fails a reused key | `docs/knowledge/database-component.md` (migration table and the candidates paragraph) | Release/deployment |
| 12 | Deployment locks pin older releases than the remotes: AI Engineer 1.4.2, Biotech 1.3.0 versus 1.8.0 installed on both disposable remotes | `deployments/ai-engineer/release.lock.json` (`release_root` ... `releases/1.4.2/component`); `deployments/biotech/release.lock.json` | Release/deployment |
| 13 | `UPSTASH_*` variable names are read by no code (only `REDIS_URL`), so a remote Upstash Redis cannot be configured by the documented names | reported by Phase A3 (`mission-stream` concept) | Release/deployment |
| 14 | `hosted_session_retention_days` is declared but read by nothing | `domain/resolution/profiles.py:188` | Sprint OC |
| 15 | Sealed bytes cite the deleted spec pack and moved program documents: lane describe strings and migrations `0033`, `0040`, `0046` (all releases), `seeds/graph_route_schemas.py:22` (cites `sprint-oc/PROOFS.md`, still in place), `seeds/knowledge_tools.py:35` (cites `SPRINT-V-DESIGN.md`, now archived); fixing them changes digests and needs a release | `adapters/cursor/describe.py:142,258`; `adapters/cursor/qualification.py:54`; `packages/mission-control-db-contract/component/migrations/0033_*.sql`, `0040_*.sql`, `releases/1.10.0/.../0046_*.sql`; the two seed files | Release/deployment |
| 16 | `MC interfaces` inventory is hand-written and drifts (seven routers were missing from the concept before the refactor) | `docs/knowledge/interfaces.md`; generation is slice work | Agentic SDLC |
| 17 | `scripts/sprint_oc_w0_local_proofs.mjs` reads the `sprint-oc/release/locks` directory by path; any move of `release/` breaks it | `scripts/sprint_oc_w0_local_proofs.mjs:46` | Release/deployment |

## Coordinator surface and skills

| # | Title | Evidence | Suggested owner |
| --- | --- | --- | --- |
| 18 | `skills/mission-control/references/protocol.md` carries `Availability: FT-xx` markers from the fast-track packet; the skill bundle is byte-pinned, so a fix needs a new seed version | `skills/mission-control/references/protocol.md:8,18,22` | Coordinator surface |
| 19 | The skill bundles do not teach `missionctl search` or `workspace check` (agent-skills 1.0.4 was built without the Selection Workspace guidance) | no `mission_search`/`selection_check` in `skills/`; Sprint OC board | Coordinator surface |
| 20 | `skills/mc-signals/SKILL.md` and `application/agentic_components/mc_signals_skill.md` are byte-identical duplicates | `skills/mc-signals/SKILL.md`; `src/mission_control/application/agentic_components/mc_signals_skill.md` | Coordinator surface |
| 21 | `.agents/skills` has 11 locally authored skills absent from `skills-lock.json`, so a "lock matches vendored skills" rule (SPEC-01 section 3.3 rule 9) would fail | `skills-lock.json` versus `.agents/skills/` | Agentic SDLC |

## Tests and documentation tooling

| # | Title | Evidence | Suggested owner |
| --- | --- | --- | --- |
| 22 | Three owner-manifest golden tests fail at HEAD (stale goldens) | `tests/unit/authoring/test_manifest_compile.py` (Sprint OC board, open items) | Sprint OC |
| 23 | The docs-retrieval experiment still reads the deleted spec pack as its corpus, so it can no longer be rerun as written | `experiments/docs_retrieval/run.py:31,90`; `tasks.jsonl` | Agentic SDLC |
| 24 | Fast-track blockers B2-B7 are still cited as current status from the archived `OWNER-FIXTURE-RUNBOOK.md` (release 1.1.0 stack) by `authoring.md` and others; each needs re-verification against code | `docs/knowledge/authoring.md`; `docs/specs/archive/fast-track-2026-10/` | Coordinator surface |
| 25 | The saver and Agent Server topology note (an ADR candidate) is undecided although the cloud deployment roadmap depends on it | `docs/specs/provider-consolidation-2026-10/providers/deep_agents/TOPOLOGY-NOTE.md` | Sprint OC |

## Companion repositories (not Mission Control code)

| # | Title | Evidence | Suggested owner |
| --- | --- | --- | --- |
| 26 | BKS Fly executor reports v2.0.2 while the graph is v2.2.0 | REFACTOR-PLAN section 6 | Knowledge Services |
| 27 | KS protocol 2.1.0 version disagreement between the service and the mirrored schemas | REFACTOR-PLAN section 6 | Knowledge Services |
| 28 | KS test hygiene: `.agent-docs/provenance.json` drift has no rebuild script; the AIDB `INTENT_AND_EXECUTOR_CONTRACTS.md` lacks `targets`/`report` receipt fields; the assertion-subject projection path has no test | Sprint OC board (provenance REPORT section 5) | Knowledge Services |
| 29 | `plan_preview` admits subjects missing NOT NULL typed columns; no production MC-to-AIDB producer-attempt projection | Sprint OC board (AI Engineer fixtures) | Knowledge Services |

## Not code, for the coordinator

- Close OVE-149 (sitting I is retired, 2026-11-01).
- Rotate the remote Supabase pooler password that a helper printed into its own transcript on 2026-10-31 (Sprint OC board).
- The four proposal originals in `platform/` stay until the owner confirms removal; they are copied into `docs/specs/proposals-2026-10/`.
