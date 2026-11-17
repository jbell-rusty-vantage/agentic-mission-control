---
type: Session Instruction
title: "Session: Mission Control feature maps, ./dev runners and an operability evaluation that works as a feedback loop"
description: "The build session for OVE-240 (AS-S7, AS-D63..AS-D65): the eleven operability questions with their verified answers, the feature maps and ./dev groups that must answer them, the sync test, the scored evaluation with a baseline and a gate, one T0 drive, the defects found while mapping, the order of work, the rules and the acceptance."
tags: [mission-control, agents, sdlc, feature-maps, dev-cli, evaluation, session]
date: 2026-11-17
status: parked
decisions: [AS-D63, AS-D64, AS-D65]
linear: [OVE-240]
---

# Session: feature maps, `./dev` runners and an operability evaluation

**Parked 2026-11-17 (AS-D66):** the AI Engineer schema is finished and migrated first; re-verify §3 before resuming.

**Start here.** Linear OVE-240. Owner words: [sitting VII](answers/AGENTIC-SDLC-SITTING-VII-2026-11-17-ANSWERS.md).
Run Opus 5.5 agents only (AS-D51). Every commit ends with `Refs: OVE-240, AS-S7`. Before anything: `./dev status`,
`git worktree list`, `git log -5`. Another agent (the test-suite review, AS-S5, OVE-238) works in this repository from
its own worktrees; never commit in the main checkout while it has uncommitted files there.

<a id="goal"></a>
## 1. Goal

An agent new to Mission Control answers and executes the owner's questions (§3) from `AGENTS.md`, `./dev` and
`features/` alone. An evaluation scores it, deterministically in `make check` and by an owner-run blind agent pass,
so a change to docs or tooling shows up as a number. Design sources (outside this repo): the 2026-11-17 handoff §3.1-§3.3
(`BellLabs/docs/state/2026-11-17/HANDOFF.md`), `BellLabs/docs/state/2026-11-15/deep/DEV-CLI-AND-FEATURE-MAP.md`,
`VERIFY-SKILLS-DESIGN.md` there, and the pstack digest in
`BellLabs/platform/ai-engineer-research-2026-11-02/14-slop-talk-research/PSTACK-DIGEST.md` (Lauren Tan's plugin).

<a id="reuse"></a>
## 2. What exists to build on (verified 2026-11-17 at `b96e08b1`)

- `./dev` (`scripts/dev/dev_cli.py`): `status`, `doctor`, `check [--full]`, `test LAYER`, `trace`. Exit 0/1/2/3.
- Local stack: `scripts/dev/local_installation.py`, `scripts/dev/local_stack.py` (make `local-infra`, `local-install`,
  `local-up`, `local-status`, `local-eval`, `local-down`); the base for `dev stack` and `dev evidence`. No memory gate yet.
  `scripts/offline_operator_stack.py` drops its database, so its evidence does not survive; do not build on it.
- Scored-loop template: `docs/tools/bench_retrieval.py` + `.sdlc/fixtures/retrieval/` (51 cases; partitions
  screening/heldout/negative; `baseline.json`; `--gate`; README rules: never tune a case to pass, heldout only judges,
  the baseline moves only with a docs change that explains it). It scores search hits, not answers.
- Scorecard template: `scripts/consumer_surface_eval.py` (`Check(question, path, passed, observed, wanted)`, runs in the
  CI local-stack job as a scorecard, always exits 0).
- Generated sources a map must stay in sync with: `AGENT_FEATURES` (`src/mission_control/adapters/deep_agents/routes.py:474`,
  26 rows; `describe()` fields id, axis, status, requires, ...) and `missionctl` (65 leaves, `build_parser()` in
  `src/mission_control/interfaces/cli/main.py`). The MCP tool names are the FastMCP registrations under
  `src/mission_control/interfaces/mcp/`.
- `docs/tools/agents_docs_index.py` + `.sdlc/modules.json` generate the `AGENTS.md` blocks and `docs/knowledge/index.md`.

<a id="questions"></a>
## 3. The questions and their verified answers (the evaluation key)

These answers are the ground truth the fixtures encode. A candidate agent in the blind pass never sees this section or
`.sdlc/fixtures/`; the maps must carry the answers in their own words. Re-verify each against live code before relying on it.

| Q | Owner's question | Verified answer (2026-11-17) |
| --- | --- | --- |
| Q1 | How do you start the APIs? | Production-shaped local stack, one application: `make local-infra` (PostgreSQL 17 on 127.0.0.1:55434), `make local-install [APP=ai-engineer\|biotech] [RECREATE=1]` (writes `.scratch/local-stack/<app>/` with `deployment.json`, `operator-token.txt`, `mission-control.env`; database `mc_local_<app>`, Temporal namespace `mc-local-<app>`), `make local-up` (API on :8000, waits for `/health/ready`, then the worker and a Temporal poller), `make local-status`, `make local-down`. Entrypoint `mission-control api` (`bootstrap/cli.py:105-116`). Compose dev path: `make dev` / `make server` / `make worker` (needs `MISSION_CONTROL_DEPLOYMENT_FILE`). Ready = `/health/ready` 200 |
| Q2 | How do you start the MCPs? | The operator MCP is mounted inside `mission-control api` at `/v1/applications/{app}/mcp/` (Streamable HTTP, bearer token = the REST token; local stack: `.scratch/local-stack/<app>/operator-token.txt`); signal ingress at `/v1/ingress/{app}/mcp`. `make mcp-server` (:8010/mcp) is a development coordinator server with no auth, no guide and no start. No repo `.mcp.json` entry configures Mission Control; an external agent adds an HTTP MCP server with an `Authorization: Bearer` header |
| Q3 | How do you use the mission-control CLI (coordinator agent)? | `missionctl` (`interfaces/cli/main.py`), env `MISSION_CONTROL_URL`, `MISSION_CONTROL_APPLICATION_ID`, `MISSION_CONTROL_TOKEN` (env only). Start: `missionctl whoami`, `missionctl guide`, then the job bundles. Skill: `skills/mission-control/SKILL.md` (+ `-author`, `-catalog`, `-observe`, `-intervene`, `-compose`); the user's yes before `mission submit` and `mission start`. MCP twin: `mission_guide`, `mission_describe`, `mission_whoami` |
| Q4 | How do you use the `./dev` runners for [every group]? | `./dev --help` and each group's `--help` with examples; the groups this session adds (§4) |
| Q5 | Where are the workflows? | Types: `Behavior` enum `domain/authoring/manifest.py:403`. Temporal: `adapters/temporal/workflows/` (`belllabs.stagegraph`, `belllabs.goal-directed`, `mc.mission_run.v1`, `belllabs.operation.v2`, ...). Interpreters: `domain/programs/interpreter.py:98` (Stage Graph), `domain/programs/goal_directed.py:32`. Chains: `application/chains/`. Parallel Swarm and Evaluator Optimizer are refused by the compiler (`application/authoring/manifest_service.py:303`). Templates: `application/guide/templates/*.mission.tmpl` (`smallest`, `research-report` = goal_loop, `staged-review`, `system-improvement`) |
| Q6 | Where are the accepted provider configs? | Lanes: `LANE_PROFILES` `domain/execution/lanes.py:78`, each `adapters/<lane>/describe.py`, `LaneRegistry` `application/resolution/registries.py:74`; only `deep_agents` is `qualified=True` (`adapters/deep_agents/describe.py:119`); unqualified lanes are refused unless `MISSION_CONTROL_ALLOW_UNQUALIFIED_LANES=true`. Per application: `deployments/{ai-engineer,biotech}/` (`target.toml`, `application.toml`, `models.toml`, `release.lock.json`). Seeds: `packages/mission-control-db-contract/seeds/`; pins `infra/capability-pins/research-capabilities.json` via `scripts/pin_research_capabilities.py`, `make seeds-validate`. Lane features: `AGENT_FEATURES` |
| Q7 | How does the coordinator search workflow and agent profiles with MCP? | `mission_guide(topic)`, `mission_describe(ref)` (`guide_tools.py:204,211`), `mission_search(query, facets, kinds, lane_profile, ...)` and `selection_check(draft)` (`selection_tools.py:96,129`) over the Selection Workspace (`application/selection/workspace.py`; facets `capability`, `lane`, `model`, `sandbox_profile`, `workflow_type`, `template`; cognition configurations are `plugin.cognition-{sdlc,knowledge,mixed}`). HTTP `POST /v1/applications/{app}/selection/search`; CLI `missionctl search`, `missionctl workspace check`, `missionctl describe` |
| Q8 | Where are the schema workspace materialization algorithms and how do you run them? | Biotech (in this repo): `materialize_schema_workspace` `integrations/biotech/src/biotech_mission_adapters/application/schema/schema_workspace.py:167`, run by `SchemaCatalogBuildService` as a Temporal activity; tests `uv run --group biotech pytest tests/unit/schema/test_schema_workspace.py`. AI Engineer: not in this repo, `aiengineer/ai-engineer-db-contract/scripts/schema-workspace/cli.mjs materialize --scope <id>`. Mount into a sandbox: `scripts/report_source_context.py --profile ai-engineer\|biotech --out <dir>`, then `scripts/report_source_sandbox.py`. No runner exists yet |
| Q9 | How do you access Supabase per application? | `MISSION_CONTROL_APPLICATION` picks the plane (`bootstrap/settings.py:66`, `Settings.db` `:643`); names `MC_{AIENG,BIOTECH}_DB_*`, `MC_LOCAL_DB_*` (`config/env.registry.yaml`, `docs/ENVIRONMENT.md`, `make env-check`). Admin: `mission-db` (`packages/mission-control-db-contract`), `make db-inspect\|db-plan\|db-verify APP=...` read-only, `make db-apply` owner-gated; `mission-db` reads the DSN named by `target.toml` (`AIENG_DB_ADMIN_DSN`, `BIOTECH_DB_ADMIN_DSN`). Read-only MCP: `supabase-aieng`, `supabase-biotech` (workspace `.mcp.json`). Plane registry: `BellLabs/docs/navigation/DATA-PLANES-AND-CREDENTIALS.md` |
| Q10 | How do you run the Agent Server (LangGraph, async subagents)? | `make agent-server` = `langgraph dev --config agent_server/langgraph.json --port 2024`; graphs `belllabs_async_technical_child`, `belllabs_async_child`, `block_c_*`. Binding: `missionctl lane async-graphs --agent-server http://127.0.0.1:2024 --scope S` writes the `deep_agents_async_graphs` block of the launch bindings file (`MANIFEST_LAUNCH_BINDINGS_PATH`); `ASYNC_SUBAGENT_SPAWNING_ENABLED`, `LANGGRAPH_RUNTIME_ENABLED` |
| Q11 | (implied) How do you prove a feature works? | `./dev drive <feature>` then `./dev evidence check <run>` (this session) |

<a id="build"></a>
## 4. What to build

1. **One exit-code table** for `./dev`, written in `features/README.md` and enforced by a test. Today three disagree
   (`./dev` 0/1/2/3, `missionctl` `exits.py` 0/2/3/4/5/6 where 3 means denied, the mcdrive design 0/1/2/5/7/8). Keep
   `missionctl` as it is; give `./dev` its own documented table.
2. **`features/`**: `README.md` (baseline preconditions, driving conventions, proof and skip reporting, the exit-code
   table, the index, `## Not mapped` with a path and a reason per entry) and one file per user-visible feature with
   frontmatter `id`, `goal` (goals.md anchors), `code`, `tests`, `drive`, `expect`, `status`, and exactly four sections:
   Sub-features (each `verified` / `unverified` / `verified-unreachable`), How to get to it (user POV), Driving it with
   `./dev drive`, Gotchas. Maps: `local-stack` (Q1), `mcp-servers` (Q2), `coordinator-cli` (Q3), `workflows-and-templates`
   (Q5), `provider-lanes` (Q6), `profile-search` (Q7), `schema-workspaces` (Q8), `application-databases` (Q9),
   `agent-server` (Q10), and the seeds `goal-directed-run`, `stage-graph-waits`, `transcript-and-evidence`,
   `cognition-points-and-forks`, `agent-configuration` (with the generated `AGENT_FEATURES` block). Implementation detail
   stays in code; a map names the user action, the exact command and the observable result.
3. **`./dev` groups**, each `--help` with examples and JSON out: `where TERM|FEATURE|ERROR` (term → map and code paths;
   feature → code, tests, drive; error signature → known fix), `feature list|show ID|check|render`, `stack up|down|status|logs`
   over `local_installation.py` / `local_stack.py` with a memory gate (refuse below 2.5 GiB free) and PIDs recorded,
   `drive FEATURE [--scenario] [--dry-run]` returning a run id and an evidence directory, `evidence show|check RUN`
   against `<id>.expect.json`, kept after `stack down`.
4. **Sync test** `tests/unit/verify/test_feature_map_sync.py` in `make check`: paths in `code`/`tests` exist; `goal`
   anchors resolve; the generated block re-renders with no diff; every backticked `deep_agents.*`/`openai.*`/`anthropic.*`
   id exists; every `missionctl` leaf is in a Driving section or under Not mapped and every cited `missionctl ...` parses
   with `build_parser()`; every cited MCP tool name is registered.
5. **Operability evaluation** `.sdlc/fixtures/operability/`: cases `{id, partition, question, expect: {commands[], paths[],
   facts[]}, critical}` for Q1-Q11 (screening) plus held-out paraphrases; a scorer `docs/tools/bench_operability.py`
   that (a) routes each question through `./dev where` and the maps, (b) checks every expected command parses (`./dev`
   and `missionctl` parsers, make targets exist) and every path exists, (c) checks the facts; `baseline.json`, `--gate`,
   in `make check`. Then an **owner-run blind agent pass**: a candidate agent gets only `AGENTS.md`, `./dev --help` and
   `features/` (never §3 or the fixtures), answers each question and runs the read-only commands; a judge from another
   model family scores it against the key; transcripts are kept. Only with John's spend ceiling for that run.
6. **One T0 drive**: `./dev stack up` (scripted model, no provider call) → `./dev doctor` → `./dev drive goal-directed-run`
   → `./dev evidence check` → `./dev stack down`; the evidence directory survives.
7. **Slim `AGENTS.md`** last, only if the scores hold: purpose, `./dev status` / `./dev where` / `./dev check`, boundaries
   with their checks, pointers to `features/`. The evaluation must not drop.
8. **A private Artifact page** (load `artifact-design`): the before/after scores per question, the chain
   (`./dev trace show AS-S7`), the feature index with sub-feature status, the defects below and the owner's decisions.

<a id="defects"></a>
## 5. Defects found while mapping (put each in a map's Gotchas; fix the cheap ones with their own commit)

1. `make socketio-smoke` targets `127.0.0.1:8000/socket.io`, but `make server` serves `bootstrap.api:create_app` without
   Socket.IO (that is `bootstrap.realtime:create_asgi_app`); `RECOMMENDATION.md:116` claims `mission-control api` serves it.
2. `make mcp-server` is called the coordinator server for Cursor, but it has no auth, no guide, no start and no run control,
   so the coordinator skill's flow cannot run through it; only the operator MCP or `missionctl` can.
3. The compose dev database is PostgreSQL 16 while `docker-compose.yml:27-33` says the common component needs 17
   (inferred from the comment; verify by running).
4. `AGENT_SERVER_GOAL_DIRECTED_ID` defaults to `belllabs_goal_directed`, which `agent_server/langgraph.json` does not register.
5. `BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN` (one L) beside `BELL_LABS_*` names.
6. `Dockerfile.schema-experiment` copies `app/` and runs `scripts/run_schema_context_selection.py`; neither exists.
7. `AGENTS.md` asks "How does Parallel Swarm run as a Stage Graph profile?" though the compiler refuses it.
8. `deep_agents` is `qualified=True` with no `docs/qualification/lanes/deep_agents/` record, and `make lane-qualify` has no
   deep_agents profile.
9. `make db-*` defaults to `APP=biotech` while `make local-*` defaults to ai-engineer; `mission-db` reads `AIENG_DB_ADMIN_DSN`
   / `BIOTECH_DB_ADMIN_DSN`, which contradicts `AGENTS.md`'s "`MC_*` only, no aliases" (documented in `ENVIRONMENT.md:38`).
10. `docs/MISSION_CONTROL_LOCAL_API.md:328,416` start raw `uvicorn` / `python -m ...worker`; `DEVELOPMENT.md` and `README.md`
    do not mention `./dev`; the Makefile has 96 targets and `docs-check`, `skills-link` are missing from `.PHONY`.
11. Greps return everything twice while `.worktrees/verify-ove238/` (an untracked full copy) exists; exclude `.worktrees/`.

<a id="rules"></a>
## 6. Rules

- No paid model or web calls without John's ceiling for that run; T0 drives use the scripted model. Memory: check the tier
  before `stack up` (the windows-resource-care thresholds).
- Report every result as implemented / tested / integrated / qualified, and checks as passed / failed / blocked / unrun.
- Linux CI is the referee: run `make ci` locally and read the GitHub run after pushing (`gh run list`).
- Never weaken a journey or tune a case to make it pass; the baseline moves only with a change that explains it.
- New decisions go in an answers file (`AS-S8`, ids from `AS-D66`); the session closes OVE-240 with a `## Completion` comment.

<a id="acceptance"></a>
## 7. Acceptance

- `make check` green, including the sync test and `bench_operability.py --gate`; the GitHub CI run for the final commit read.
- Q1-Q11 deterministic score recorded in `baseline.json`, with the per-question result on the Artifact page.
- One T0 drive with its evidence directory listed and `evidence check` passing.
- The blind agent pass run (or marked unrun with the reason, e.g. no spend ceiling given).
- OVE-240 `## Completion` with commits, checks, evidence and level; `./dev trace show OVE-240` shows the chain.

<a id="ask"></a>
## 8. Ask John at the end

1. The blind agent pass: model, judge and spend ceiling.
2. Slim `AGENTS.md` now (the scores held) or after Knowledge Services adopts the same shape?
3. Where unshaped ideas go now that `agentic-sdlc/ideas/` is gone; whether to archive the GitHub repo `agentic-sdlc`.
