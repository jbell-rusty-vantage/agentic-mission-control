---
type: Proposal
title: "The agentic SDLC system: one self-sufficient documentation and lifecycle toolchain per repository, pinned from platform/agentic-sdlc"
description: "Proposal for owner acceptance (AS-D5, 2026-11-01): the final shape of the documentation system built from the agreed components (module-level AGENTS.md generator, searchable OKF knowledge, ADRs, GLOSSARY, sidecars, maintenance rules run by git hooks), vendored and pinned into every repository so each works alone; the CLI, the per-repository layout, the git-event table, the model-driven path on the owner's Claude Code subscription, the cloud mapping, and what is retired."
tags: [mission-control, agents, process, documentation, sdlc, proposal]
date: 2026-11-01
status: open
---

# The agentic SDLC system

Designed from the components decided in sitting I, not from either current implementation. Where
a current implementation already matches the design it is named as the seed, nothing more.

## 1. Principle: upstream once, vendored everywhere

`platform/agentic-sdlc` is the **upstream**: the source of the CLI, the skills, the hook templates
and the contract tests. No repository depends on it at runtime. Each repository carries a vendored,
pinned copy and is complete alone, in a local checkout, a worktree, a cloud environment or CI:

| Pinned thing | Lives in each repository at | Pinned by | Pulled with |
| --- | --- | --- | --- |
| The CLI (one dependency-free Node file plus a vendored YAML parser) | `.sdlc/cli.mjs`, `.sdlc/vendor/` | `.sdlc/lock.json` (upstream version, commit, file digests) | `node .sdlc/cli.mjs update --to <version>` (fetches from the upstream GitHub release, verifies digests) |
| The skills (ours and Matt Pocock's) | `.agents/skills/<name>/` with `.claude/skills` links | `skills-lock.json` (already the mechanism: source, path, hash) | `npx skills add Overton77/agentic-sdlc` and `npx skills add mattpocock/skills` |
| Hook templates and the GitHub workflow | `.sdlc/hooks/`, `.github/workflows/sdlc.yml` | the same `lock.json` | `node .sdlc/cli.mjs hooks install` writes them |
| The contract (what a concept, index block, fixture and ledger must look like) | enforced by the vendored CLI's `check`; documented once in the upstream and mirrored by the `belllabs-method` skill | the CLI version | with the CLI |

Node is the runtime because every repository already has it on the host (24.18) and in the cloud
image (22 default; 24 installed by the setup script); the CLI uses no package install.

## 2. The per-repository layout (the contract)

```text
<repo>/
├── AGENTS.md                 invariants by hand + <!-- BEGIN:sdlc --> generated guide, category index, code map <!-- END:sdlc -->
├── CLAUDE.md                 @AGENTS.md (adapter only)
├── GLOSSARY.md               the repository's terms (Matt Pocock domain-modeling format)
├── skills-lock.json          pinned skills
├── .agents/skills/           dev-time skills (vendored); .claude/skills/ links are machine-local
├── .sdlc/
│   ├── cli.mjs, vendor/      the vendored CLI
│   ├── lock.json             upstream version and digests
│   ├── config.json           registration: purpose, lifecycle, rules, budgets, docs[], categories, linear{project, labels}
│   ├── modules.json          module id → source entrypoints, tests, concepts[]  (the drift and code-map sidecar)
│   ├── provenance.json       normalized hashes recorded at the last build (generated)
│   ├── fixtures/retrieval/   queries.json (expected routes, critical, partition) + frozen concept snapshots
│   └── hooks/                the six git hook scripts (generated)
├── docs/
│   ├── knowledge/            OKF concepts: one file each, category: + type: + aliases + questions, ≤160 lines, Citations; index.md and log.md generated
│   ├── adr/NNNN-<slug>.md    decisions (status: proposed | accepted | superseded)
│   ├── specs/<program>/      programs: LEDGER.md, proposals, specs, projections, answers/, CHANGES.md; archive/ is the one archive
│   ├── agents/               only the per-repository deltas of process (issue tracker project, labels); the method itself is the skill
│   └── <operator guides>     runbooks the operations concepts cite
└── <module dirs>/AGENTS.md   generated per registered module: purpose, entrypoints, tests, the concepts that explain it, invariants from config
```

Rules the CLI enforces (`check`): every concept has `category` (one of nine), `type`, `title`,
`description`, `aliases`, `questions`, ≤160 lines and a Citations section whose links resolve;
every category has a concept or an `n/a` line in `index.md`; every ADR has a status and is cited by
at least one concept or the decisions concept; every GLOSSARY term used in a concept exists; the
generated blocks match the sources; instruction files stay under budget (8 KiB per `AGENTS.md`
block, configurable); the ledger rows point at existing files with known statuses; the answers
files are well-formed; the fixtures' digests match; `skills-lock.json` matches the vendored skills.

## 3. The CLI

`node .sdlc/cli.mjs <command>` (alias `sdlc` through a repo script):

| Command | Does | Model call | Used by |
| --- | --- | --- | --- |
| `check [--staged] [--only <names>]` | every offline rule above; exit 1 on failure, exit 2 in `--hook` form | no | pre-commit, CI, Claude Code `Stop` hook |
| `build` | regenerates the `AGENTS.md` blocks (root and module), `docs/knowledge/index.md`, `log.md` entries from `CHANGES.md`, `provenance.json` | no | after editing; merge to main |
| `search "<terms>" [--json]` and `context "<question>"` | BM25 with aliases, questions and identifier tokens over knowledge, glossary, ADRs, agent docs; `--root` for a program packet; `context` returns bounded sections, entrypoints, tests, decisions | no | agents, the `mission-control-docs` style skills |
| `bench [--gate]` | runs the retrieval fixtures: recall@3, MRR, abstentions, critical failures; `--gate` fails on a critical miss or a drop below the recorded baseline | no | pre-push, CI |
| `drift [--since <ref>] [--record]` | modules whose source hash changed with no changed associated concept; honours `Docs: none <reason>` trailers; `--record` writes the observation into `provenance.json` | no | post-commit (record), pre-push (gate), CI |
| `propose [--modules <ids>] [--apply]` | runs the Claude Code CLI with the `sdlc-docs-update` skill on the drift set; the result is a patch to concepts, glossary, log and index; `--apply` commits it as `docs(sdlc): …` with `Docs: proposed-by claude` | yes, subscription | pre-push on request; the PR job |
| `ledger check|new-answers|archive|move` | the program mechanics (ported from `program_ledger.py`) | no | interviews, session close |
| `issue link|transition|bug` | Linear through GraphQL with `LINEAR_API_KEY` (or the MCP in a session): read the `OVE-n` from branch or trailer, move state, create a bug with provenance | no | PR job, merge job |
| `hooks install|status|uninstall` | writes `.sdlc/hooks/*` and sets `core.hooksPath`; chains an existing prek or husky hook instead of replacing it | no | once per clone; setup script |
| `update --to <version>` | pulls the pinned upstream release into `.sdlc/`, verifies digests, rewrites `lock.json` | no | by decision |

## 4. The git-event table (final)

| Event | Runs | Blocks | Model |
| --- | --- | --- | --- |
| pre-commit | `check --staged --hook`, then the repository's own fast lint (prek in MC, biome in KS) | yes | no |
| commit-msg | requires an `OVE-n` reference in the subject or a trailer, or `Docs: none <reason>` for a documentation-exempt commit | yes | no |
| post-commit | `drift --record` | no | no |
| pre-push | `drift` (gate), `bench --gate`; on drift, prints the modules and offers `propose --apply` (runs `claude -p` on the subscription, bounded by `--max-turns` and a budget; the push resumes after the docs commit) | yes | yes, on request |
| post-merge, post-checkout, post-rewrite | `build --if-stale` (regenerate blocks and provenance locally) | no | no |
| PR opened / synchronized (GitHub) | `check`, `bench --gate`, `drift`, tests; then the Claude Code job: review (the `code-review` skill, findings as PR comments) and `propose --apply` on the PR branch when drift exists; `issue link` adds the PR to the Linear issue | review required to merge | yes, see §5 |
| merge to main (GitHub) | `build`, release notes from `CHANGES.md`, `issue transition` to Done, `issue bug` for deferred findings | no | no |

No scheduler. The only time-based thing allowed later is a safety net that re-runs the merge job.

## 5. Model-driven work on the owner's subscriptions, provider-selectable (AS-D10)

The model-driven steps (`propose`, review) run through a **provider adapter** chosen in
`.sdlc/config.json`:

```json
"provider": { "default": "cursor", "cursor": { "model": "grok-4.7-high", "timeoutMinutes": 15 },
              "claude": { "model": "claude-fable-5-1", "maxTurns": 20, "maxBudgetUsd": 2 } }
```

Both adapters take the same inputs (the drift set, the skill, the allowed paths) and return the
same output (a patch, a summary, the session id); `SDLC_PROVIDER=claude` overrides per run. Cursor
is the default now: Grok 4.7 is a Cursor model and draws on the plan's included weekly pool, while
third-party models bill prepaid credit (cursor.com `models-and-pricing`, read 2026-11-01).

| Place | Cursor adapter (default) | Claude adapter | Shared |
| --- | --- | --- | --- |
| Local clone (Windows host, WSL2); fired by the git pre-push hook, in any harness or a plain shell | `agent -p "<prompt>" --output-format json --model grok-4.7-high --force --trust --workspace <repo>` with `CURSOR_API_KEY` from the repository `.env` (present in MC and KS; the hook reads the file, never prints it); allow/deny in `.cursor/cli.json` restricts writes to `docs/`, `GLOSSARY.md`, `.sdlc/`; no turn flag, so the CLI enforces the wall clock | `claude -p` with the subscription login, `--max-turns`, `--max-budget-usd`, `--permission-mode acceptEdits`, `--allowedTools` scoped the same way; the hook unsets `ANTHROPIC_API_KEY`; never `--bare` | git hooks do not depend on any session; Cursor's `.cursor/hooks.json` (`beforeShellExecution` on `git push`) and Claude's `.claude/settings.json` (`PreToolUse` with `if: "Bash(git push *)"`) are optional in-session mirrors of the same gate |
| GitHub PR job (`.github/workflows/sdlc.yml`) | a `run:` step installs the CLI and calls `agent -p` with `CURSOR_API_KEY` as a repository secret (no official action exists); Bugbot may additionally review every PR update on the same plan | `claude-code-action@v1` with `claude_code_oauth_token` from `claude setup-token` | the deterministic gates (`check`, `bench --gate`, `drift`, tests) run first and without any key; the job commits docs as `docs(sdlc): …` with `Docs: proposed-by <provider>` |
| Cloud sessions | Cursor Cloud Agents (Automations on pull request opened/pushed/merged, plan usage; `.cursor/environment.json` per repository) | Claude Code cloud environment per repository (committed hooks; a scheduled task on `pull_request.opened`) | both are documented last in this program (§6); neither is required for the gates |

Caps: Claude by turns, estimated spend and wall clock; Cursor by wall clock and permissions
(Cursor documents no turn or spend flag). Every run writes its session id, provider, model,
duration and result into `provenance.json` and the PR body.

## 6. Cloud environment mapping

One cloud environment per repository (single-repository sessions keep hooks, skills and
`.mcp.json`; multi-repository sessions lose them and are used only to read across). The setup
script installs Node 24, uv and the repository's dependencies, runs `node .sdlc/cli.mjs check`, and
is cached. Environment variables carry the non-secret configuration; the Linear key and provider
keys are network secrets. `ai-engineer-meta` and the Biotech non-repositories must become GitHub
repositories before they can have an environment (AS-D6 already makes `biotech-postgres-db-contract`
one). Documented last in this program, as the owner ordered.

## 7. What converges, what is retired

| Today | Becomes |
| --- | --- |
| MC `docs/tools/{validate_okf,agents_docs_index,okf_search,check_links,check_docs,program_ledger}.py` | `check`, `build`, `search`, `ledger` in the vendored CLI; retired at parity, proven by a parity fixture over the 66 concepts |
| KS and AIE `.agent-docs/` (generator 1.2.0, config, modules, provenance, fixtures, benchmark) | the seed of `.sdlc/`: same shapes, renamed, plus categories, glossary and ADR search, ledger, drift, propose, hooks |
| KS `knowledge/` at the root; KS and BKS `docs/architecture/000N` as ADRs | `docs/knowledge/` and `docs/adr/` everywhere (moved with `ledger move`, links rewritten) |
| KS `tools/maintenance` (SQLite queue, watcher), `.github/maintenance`, `agent-maintenance.yml` | retired; kept in the archive as evidence; replaced by the hook table and `sdlc.yml` |
| `ai-engineer-meta/tools/agent-docs` and the four 2026-09 documentation plans | the upstream repository; the plans are archived as the design history |
| AIE `CONTEXT.md`, `CONTEXT-MAP.md` | `GLOSSARY.md` and the workspace `GLOSSARY-MAP.md` (AS-D3) |
| `docs/agents/documentation-surfaces.md`, `program-workspace.md`, `belllabs-method` | one `belllabs-method` skill in the upstream, vendored everywhere; per-repository deltas stay in `docs/agents/` |
| Workspace `docs/navigation/check-navigation.mjs` | the workspace root keeps a hand-written `AGENTS.md`, `GLOSSARY-MAP.md` and a `workspace.json` the CLI reads for cross-repository checks |

## 8. Order of the build

1. Create `platform/agentic-sdlc` (git, GitHub remote); move the generator in; add categories,
   glossary and ADR search, drift, `ledger`, `hooks`, `update`; contract tests from both lineages.
2. Vendor into Mission Control first (largest corpus, the parity fixture), then Knowledge
   Services, Biotech Knowledge Services, the AI Engineer repositories.
3. Author the missing concepts per the matrix (DOC-01), in that repository order.
4. Record retrieval fixtures per repository; run `bench`; set baselines.
5. Install hooks; wire `sdlc.yml`; prove one PR end to end.
6. Document the cloud environments.

## 9. The ideas workspace (AS-D11)

One place where the owner writes ideas and any agent, in any repository, picks them up:
`platform/agentic-sdlc/ideas/` (a git repository with a remote, so it is reachable from a cloud
environment and from CI; the workspace root is not a repository). Every repository's `AGENTS.md`
carries one line: "Ideas: `../agentic-sdlc/ideas/` (workspace) or the `Overton77/agentic-sdlc`
repository; read `ideas/README.md` before picking one up."

Layout and lifecycle:

```text
ideas/
├── README.md                  the writing guide (below) and the pick-up rule
├── TEMPLATE.md
├── <YYYY-MM-DD>-<slug>.md     one idea per file; status in the frontmatter
└── archive/                   parked or shipped ideas, moved by `sdlc ideas archive`
```

Frontmatter: `id: ID-<n>` (assigned by `sdlc ideas new <slug>`), `title`, `status: seed |
interviewing | specified | building | shipped | parked`, `domains: [mission-control,
knowledge-services, aiengineer, biotech]`, `created`, `owner`, `promoted_to:` (the program and
answers rows once an interview takes it), `linear:` (the `OVE-n` once ticketed).

The writing guide (what the owner writes, in this order, each one short): **the itch** (what is
wrong or missing, one paragraph, in the owner's words), **the outcome** (what is true when it is
done, observable), **where it lives** (which repository or product surface), **constraints** (spend,
providers, contracts that must not change), **evidence** (links, prior decisions, research), **open
questions** (what an interview must resolve), **pick-up instruction** (what an agent should do
first: research, prototype, interview, or spec). An idea with only the itch is valid; the agent
fills the rest through `grill-with-answers` and the chain records it.

The pick-up rule for agents: read `README.md`, choose by `status: seed` and `domains`, set
`status: interviewing`, create the program (or choose the existing one), cite `ID-n` in the interview
instrument and in every answers row's `Source`, and never edit the owner's itch paragraph.

## 10. Remote accessibility of the chain (considerations for AS-D11)

The question: keep the chain filesystem-based, or mirror it to a bucket and a small database?

1. **Git is already the remote store.** Every link of the chain (idea, instrument, answers rows,
   spec, ADR, ledger, `CHANGES.md`) is a file in a repository with a GitHub remote. A cloud
   environment, CI, a scheduled task, a web app or another agent reads it through the GitHub API or
   a clone. `sdlc ledger trace OVE-n` runs anywhere the repository is checked out. Linear holds
   the issue side of the chain and is itself remote.
2. **What git cannot do:** answer "show me every open idea and every issue it became" across all
   seven repositories in one query without cloning them; serve a dashboard; survive a repository
   being rewritten. That is a read model, not a source of truth.
3. **Both current Supabase projects are disposable targets** until quality ingestion (owner
   standing rule); a mirror there would be wiped with the next reinstall. A new small project
   (or a bucket in the owner's AWS account) is the only durable option today.

Recommendation: git stays canonical in this program; add `sdlc publish` as a merge-to-main step
that writes `trace.json` (the whole chain, one document per repository) plus the ideas and answers
snapshots to a Storage bucket `sdlc-trace` and upserts rows into a `sdlc.trace_links` table in a
**dedicated** small Supabase project `belllabs-sdlc` (never the disposable planes), with the
cross-repository read model (`ideas`, `programs`, `answers`, `issues`, `commits`) as views. Nothing
reads the mirror to make a decision; the chain is verified from git. Build order: the publish step
is a later slice of this program, after the trace command exists and one repository publishes.
