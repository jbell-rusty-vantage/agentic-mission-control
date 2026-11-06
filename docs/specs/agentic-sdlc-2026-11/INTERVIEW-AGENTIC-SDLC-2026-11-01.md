---
type: Interview Instructions
title: "Agentic SDLC interview: retrieval audit, git-lifecycle documentation hooks, Linear + GitHub baseline, cloud environment"
description: "The instrument for the owner interview of 2026-11-01 that turns the agentic SDLC request into a plan: fact placement and information categories across Mission Control, Knowledge Services, AI Engineer and Biotech; git-lifecycle (not scheduled) documentation hooks; retrieval fixtures as quality gates; the idea to interview to spec to Linear provenance chain; and the Claude Code cloud environment documented last."
tags: [mission-control, agents, process, documentation, sdlc, interview]
date: 2026-11-01
status: active
---

# Agentic SDLC interview (sitting I, 2026-11-01)

## The owner's request, made coherent

Agents are the primary developers in this workspace. The SDLC fundamentals (documentation, tests,
issues, reviews, pull requests, bug capture) must be enforced at the agentic level and triggered by
the git lifecycle, not by a scheduler, so that startup-mode speed does not rot the retrieval surface
agents depend on. The work runs on `sprint-oc` in every repository, merges, and Sprint OC resumes.

Order the owner set: (1) this interview produces the specification and plan; (2) fix documentation
in every codebase under `platform/`, `aiengineer/`, `biotech/`; (3) run the retrieval audits, which
start the feedback loop; (4) document the Claude Code cloud environment last.

Decided before the sitting: documentation automation binds to git events. The trigger table under
test is pre-commit (fast checks, blocking), post-commit (ledger entry, no model), pre-push (docs
drift, blocking), PR opened/synchronized (agent docs proposal, tests, review, Linear link), merge to
main (indexes, release notes, Linear transition), post-merge/checkout/rewrite (reconcile).

## Verified facts the questions rest on (2026-11-01, live `sprint-oc` checkouts)

| # | Fact | Where |
| --- | --- | --- |
| F1 | Mission Control runs the five-surface model: OKF concepts in `docs/knowledge/` (66 files, 160-line cap, Citations heading, `validate_okf.py`), Matt Pocock flow (`GLOSSARY.md`, `docs/adr/` 0001-0063, programs under `docs/specs/` with `LEDGER.md` and `answers/`), `AGENTS.md` with the compiled index (`agents_docs_index.py`, sidecar `index-notes.toml`), provider supplements, skills (`.agents/skills/`, 60 dev-time; `skills/`, 15 shipped). Precedence on conflict: spec pack, then ADR, then knowledge, then the status document | `docs/agents/documentation-surfaces.md`; `docs/tools/check_docs.py` |
| F2 | Mission Control `AGENTS.md` is 29,390 bytes; the compiled index block is lines 140-166. Hooks today: prek pre-commit (ruff, ty, deptry, uv-lock, secrets); no `docs-check` hook installed; no GitHub workflows | `AGENTS.md`; `.pre-commit-config.yaml`; `.github/` absent |
| F3 | Knowledge Services runs a different system: `knowledge/` at the repo root (11 concepts with aliases and example questions), `.agent-docs/config.json` (8 KiB budget per instruction file) driving a generated `AGENTS.md` block, `docs/architecture/0001-0015` as ADRs, `GLOSSARY.md`; generator vendored from `ai-engineer-meta/tools/agent-docs` 1.2.0 | `platform/knowledge-services/AGENTS.md`; `.agent-docs/` |
| F4 | Knowledge Services already has a git-driven agent maintenance pilot: `tools/maintenance/cli.mjs` installs pre-commit (`check-staged`), pre-push (`check-push`), post-commit/merge/checkout/rewrite (`enqueue` into SQLite at `.git/maintenance/state.sqlite`), a local watcher, and `.github/workflows/agent-maintenance.yml` (PR, push to main, issue-comment commands; providers codex/claude/cursor; tasks review/docs/tests/fix; no auto-merge). Deployment not proven | `docs/operations/agent-maintenance.md`; `.git/maintenance/hooks/` |
| F5 | Knowledge Services already has retrieval fixtures: `.agent-docs/fixtures/ks-context-v1/` (six frozen concepts, SHA-pinned; `queries.json` with 18 screening and 10 held-out cases carrying `expected`, `critical`, `partition`), `retrieval-benchmark.mjs` (recall@3, MRR, abstentions, critical failures), `retrieval.test.mjs` as a regression gate | `.agent-docs/fixtures/ks-context-v1/README.md` |
| F6 | Mission Control retrieval is `okf_search.py` (BM25 over glossary, ADRs, knowledge, agent docs, spec pack; `docs/specs` excluded by default, three Sprint OC entrypoints added). No fixtures, no benchmark | `docs/tools/okf_search.py`; `docs/navigation/RETRIEVAL.md` |
| F7 | AI Engineer: five repos carry `.agent-docs/` and generated `AGENTS.md` blocks; none has a `knowledge/` bundle. `ai-engineer-meta` holds the generator, the Matt Pocock `CONTEXT.md` (architecture vocabulary) with `CONTEXT-MAP.md`, five ADRs, and four documentation plans (strategy, maintenance, test, bootstrap, 2026-09-15) whose model-driven maintenance was superseded by the KS git pilot. `ai-engineer-meta` has no commits: every file is untracked on an unborn `main` | `aiengineer/AGENTS.md`; `ai-engineer-meta/docs/agents/workspace/README.md`; `git status` |
| F8 | Biotech: only `biotech-knowledge-services` is a git repository (`sprint-oc`, `ci.yml`, ADRs in `docs/architecture/`, no glossary, no knowledge bundle, no `.agent-docs`). `biotech-knowledge-catalog` has its own `tools/validate_okf.py` (the source of Mission Control's validator) and an Obsidian vault; the catalog, `biotech-postgres-db-contract` and `biotech/BellLabs` are not repositories | `biotech/AGENTS.md`; `biotech-knowledge-catalog/tools/` |
| F9 | Workspace root: hand-authored `AGENTS.md`, `docs/navigation/` (inventory, retrieval, worktrees, `check-navigation.mjs` over an explicit file list). Not a git repository | `docs/navigation/RETRIEVAL.md` |
| F10 | Linear: workspace `overtonbell`, team `OVE`; Mission Control uses project Mission Control, Knowledge Services project BellLabs Knowledge Platform; every issue carries `## Provenance`; forward-only from 2026-10-23 | `docs/agents/issue-tracker.md` in both repositories |
| F11 | Upstream rule: Matt Pocock skills stay byte-identical (v1.3.1 checked 2026-10-23); upstream renamed `CONTEXT.md` to `GLOSSARY.md`; Mission Control and Knowledge Services use the new name, `ai-engineer-meta` still the old | `docs/agents/matt-pocock-skills.md`; `ai-engineer-meta/CONTEXT-MAP.md` |
| F12 | The existing hook recipes (Claude Code `Stop` hook and prek `docs-check`) are written but not installed; `HARNESSES.md` still names a scheduler for the full check | `.agents/skills/belllabs-method/HARNESSES.md` |
| F13 | Claude Code on the web (code.claude.com docs, read 2026-11-01): one session may attach several GitHub repositories, but repository `.claude/settings.json` hooks, `.mcp.json` and skills are honored only in single-repository sessions; Projects threads load only `CLAUDE.md` and `.claude/rules/`. Environment variables are set per environment (readable by everyone using it) and are not visible to the setup script; API keys go in network secrets. Ubuntu 24.04, Python with uv, Node 22 default (Node 24 not listed), Docker, PostgreSQL 16 installed but not running; setup script cached about seven days. Scheduled tasks share the same environments. Repositories without a GitHub remote (`ai-engineer-meta`) cannot be attached | `docs/en/cloud-environments.md`, `settings.md`, `claude-projects.md`, `routines.md` |
| F14 | Claude Code subscription in automation (docs read 2026-11-01): `claude setup-token` yields a one-year OAuth token (`CLAUDE_CODE_OAUTH_TOKEN`) usable by `claude-code-action@v1` so CI runs bill the subscription; local `claude -p` uses the `/login` subscription unless `ANTHROPIC_API_KEY` is exported (then the key always wins) or `--bare` is used (skips OAuth); `--max-turns`, `--max-budget-usd` (estimate), `--permission-mode`, `--allowedTools`, `--output-format json` exist. Claude Code hooks filter commands with `if: "Bash(git push *)"`; exit 2 blocks in `PreToolUse`. Cloud scheduled tasks can start a session on `pull_request.opened` | `authentication.md`, `headless.md`, `hooks.md`, `github-actions.md`, `routines.md` |
| F15 | Cursor CLI on the host: `cursor-agent` 2026.10.01-14929f9 under `%LOCALAPPDATA%\cursor-agent` (`.cmd` shims; not on the bash PATH), `status` reports authenticated; with the `.env` key loaded `--list-models` offers `grok-4.7-low|medium|high|xhigh` (and `-fast` variants), `cursor-grok-4.6-*`, `claude-*`, `gpt-5.*`, `composer-2.5`, `auto`. `CURSOR_API_KEY` is set in `mission-control/.env` and `knowledge-services/.env`, not in the workspace `.env`. The `cursor-agent-headless` skill documents `-p --output-format stream-json --trust`, `--force`, `--mode ask`, `--model`, `--resume`, direct `node.exe index.js` launch on Windows | `.agents/skills/cursor-agent-headless/SKILL.md`; live `--list-models` 2026-11-01 |
| F16 | Cursor docs (cursor.com, read 2026-11-01): the CLI is `agent` (`-p/--print`, `--output-format text|json|stream-json`, `--model`, `--force`, `--trust`, `--sandbox`, `--workspace`, `--api-key`; no turn or spend flag; prompt as an argument; reads `AGENTS.md`, `.cursor/rules`, skills in `.agents/skills` and `.cursor/skills`; allow/deny in `.cursor/cli.json`). `CURSOR_API_KEY` from Dashboard, recommended for CI; Cursor models (Grok 4.7, 4.6, 4.5, Composer 2.5) draw on the plan's included pool, third-party models bill prepaid credit; the owner's 60 USD plan is legacy Pro+ (maps to Super: Cloud Agents, Automations, Bugbot included). Hooks `.cursor/hooks.json`: `beforeShellExecution` matches the full command and exit 2 or `permission: deny` blocks (e.g. `git push`); `stop` with follow-up loops. PR side: Automations start cloud agents on pull request opened/pushed/merged on plan usage; Bugbot reviews every PR update; GitHub Actions run `agent -p` with the key, no official action. Windows native installer exists | `cursor.com/docs/cli/*`, `docs/models-and-pricing`, `docs/agent/hooks`, `docs/cloud-agent/automations`, `docs/bugbot` |

## Rounds

Round 1 (frontier, at most four per batch, twenty in all): the unit of documentation truth across
repositories; information categories; fact placement for the two existing systems; the git event
that owns each documentation action; retrieval fixtures as gates; the provenance chain idea to
interview to spec to Linear; glossary naming; the uncommitted generator; Biotech scope; the cloud
environment's place.

Answers are recorded in `answers/AGENTIC-SDLC-SITTING-I-2026-11-01-ANSWERS.md` (family `AS-D`).
