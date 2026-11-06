---
type: Working Draft
title: "Experiment loop: the coordinator question set and the per-run critique template"
description: "The fixed questions the Mission Control coordinator agent answers during every E1-E5 run from public surfaces only (missionctl, the operator HTTP routes, the MCP tools; no database, no Temporal CLI), each with the surface to use, plus the per-run critique table matching rubric section 4 of the experiment loop."
tags: [mission-control, sprint-oc, experiments, coordinator, inspection, critique]
date: 2026-11-02
status: active
---

# Coordinator question set and critique template

Companion of the [experiment loop](../EXPERIMENT-LOOP-2026-11.md) (section 3, "Coordinator agent"; section 4, rubric).
Fixtures: `tests/fixtures/manifests/experiment-loop/e1..e5`; driver: `scripts/experiment_loop_driver.py`.
Routes are under `/v1/applications/{app}` and come from [public interfaces](../../../../knowledge/interfaces.md) and
`src/mission_control/interfaces/` (`http/`, `cli/main.py`, `cli/outputs.py`, `cli/knowledge.py`, `mcp/`).

## Rules for the coordinator agent

- Public surfaces only: `missionctl` (with `MISSION_CONTROL_URL`, `MISSION_CONTROL_APPLICATION_ID`, `MISSION_CONTROL_TOKEN`),
  the HTTP routes below, or the operator MCP server (`/v1/applications/{app}/mcp`). No SQL, no `temporal` CLI, no reading
  the worker log, no reading the driver's `http/` folder (that is the runner's evidence, not a surface).
- Answer each question at the checkpoint it names. Record per answer: the surface used, the number of calls, elapsed
  time, the answer, and **gap** when the surfaces could not answer it (a gap is a finding, never a guess).
- Issue only the run's overlay intervention, through `missionctl command queue|inject|cancel` or `mission_command_send`.

## The questions

Checkpoints: **S** after start, **R** while a stage or iteration is running, **W** when the run waits, **T** at terminal
(or at the hard blocker). Ids are stable across iterations so answers can be compared.

| Id | When | Question | Surface (missionctl / HTTP / MCP) |
| --- | --- | --- | --- |
| Q1 | S, R | Which run(s) exist for this manifest, and for a chain which member is active? | `chain inspect <id>` / `GET chains/{chain_id}` / `mission_chain_inspect`; single mission: the submit receipt and `run list` / `GET runs` / `mission_run_list` |
| Q2 | R | What is running now: lifecycle, phase, which stage or role, which turn? | `run inspect <run>` / `GET runs/{id}/inspection` (lifecycle, phase, `sessions`) / `mission_run_inspect`; stage or role: `run points <run> --node <stage\|executor\|verifier>` / `GET runs/{id}/points?node=` / `mission_run_points` |
| Q3 | W | Why is it waiting, and what action releases it? | `run inspect` (`projection.active_waits`, `active_pauses`) / `GET runs/{id}/inspection`; review gates: `GET human-tasks`, `GET human-tasks/{id}` / `mission_human_task_list\|get`; held knowledge review: `knowledge review` / `POST runs/{id}/knowledge-reviews` / `knowledge_review` |
| Q4 | R, T | What did the last turn see: system and user messages, Context Packet, tool schemas, tool calls and results? | `run transcript <run> --full --node <stage>` / `GET runs/{id}/transcript?full=true` / `mission_run_transcript`; one point: `run state-as-of <run> --point <id>` / `GET runs/{id}/points/{point_id}/state-as-of` / `mission_run_state_as_of` |
| Q5 | R | Which skills, tools, MCP servers and sandbox are mounted for this stage, and which were used? | `run inspect` (`lane`) and `run transcript --full` (tool schemas offered vs tool calls made); `GET runs/{id}/inputs`. The effective run configuration route is on the technical facade only, so a missing answer is a gap |
| Q6 | before a dependent stage, T | What will the next stage receive (exact sources, revisions, expansion tier, omissions)? | `outputs plans <run>`, `outputs plan <plan_id>` / `GET runs/{id}/transfer-plans`, `GET transfer-plans/{plan_id}` / `mission_transfer_plan`; chain consumer: the link `packet_ref` in `chain inspect` |
| Q7 | R, T | Which outputs are submitted, accepted, held or unfulfilled, and why? | `outputs show <run>`, `outputs revisions <run> <key>`, `outputs events <run>` / `GET runs/{id}/outputs`, `.../outputs/{key}/revisions`, `.../output-events` / `mission_run_outputs`, `mission_run_output_revisions\|events` |
| Q8 | T, on failure | What failed, where, and with which typed cause? | `run inspect` (`execution_outcome`, `unit_failures`, `projection.terminal_outcome`); `GET runs/{id}/completion-evidence` (Stage Graph) or `GET runs/{id}/goal-completion-evidence` and `GET runs/{id}/evidence` (Goal Loop); `run closure <run> --list`. Known blind spot: activity failures are absent from `unit_failures` (loop section 2) |
| Q9 | R, T | Did the Goal Loop verifier decide, with which verdict and repair feedback, on which iteration? (E1, E4 consumer, E5 body) | `GET runs/{id}/evidence` (`family_result.verification_results`), `run points <run> --node verifier --iteration <n>`, `run transcript --node verifier` |
| Q10 | R | Did the route and revisit decide as the facts say (branch, visit count, stop reason)? (E3) | `run inspect` (`projection.active_waits`: `route-exhausted:*`, `revisit-exhausted:*`); `GET runs/{id}/completion-evidence`; `outputs revisions <run> critique.critique_verdict` (one revision per visit) |
| Q11 | R, T | What did this run and each stage spend against its budget (tokens, tool calls, USD)? | `run inspect` (`budget`, `sessions[].tool_calls`); `run transcript --full` usage entries. `GET runs/{id}/budget` is on the technical facade only (gap if inspection cannot answer) |
| Q12 | after an overlay | Was the intervention accepted, delivered and applied (three distinct facts)? | `command list <run>` / `GET runs/{id}/commands`; `run inspect` (`mailbox`, `delivery_reports`); the transcript entry of the turn that claimed it |
| Q13 | after a fault | Did recovery happen without duplicate cognition or writes? (E1 worker kill, E4 transport fault) | `run points <run>` (generations, `session_generation`), `run inspect` (`sessions[].generation`, `points_incomplete`), `GET runs/{id}/effects` is facade-only; `outputs revisions` for duplicate submissions |
| Q14 | E5 after `research` | Which checkpoint or point can a fork start from, and what would it keep? | `run points <run> --seedable`, `run checkpoint <run> --list`, `run replay <run> --point <id>` (dry run); `run fork <run> ...` / `mission_run_fork` only if the overlay says so |

## Per-run critique table (fill one per run in `.scratch/sprint-oc/experiments/iter-<n>/<e>/CRITIQUE.md`)

Header: experiment, iteration, run id(s), manifest digest (`manifest.rendered.sha256`), models, overlay, terminal
outcome, spend (USD, tokens), coordinator calls and minutes.

| # | Rubric dimension (loop section 4) | Observation (with evidence path or route) | Expected by the design | Class: fix / improve / create / document / none | Follow-up (issue or test) |
| --- | --- | --- | --- | --- | --- |
| 1 | Lifecycle: phases and waits match the design; terminal outcome and cause visible from `/inspection` | | | | |
| 2 | Context transfer: each Context Packet holds what the stage needs, no more (size, duplicates, missing inputs) | | | | |
| 3 | Materialization: mounted skills, tools, MCP, sandbox match the authored node; unused mounts | | | | |
| 4 | Prompt and messages: system vs user placement, instruction clarity, tool-schema weight, turns per role | | | | |
| 5 | Recovery: the overlay fault recovers or fails closed with a typed, inspectable cause; no duplicate cognition or write | | | | |
| 6 | Coordinator answerability: Q1-Q14 answered from public surfaces; calls and time; list every gap | | | | |
| 7 | Cost: tokens and USD per stage and role against the declared budget | | | | |

Coordinator answer log (one row per question asked): `Q-id | checkpoint | surface | calls | seconds | answer or gap`.
