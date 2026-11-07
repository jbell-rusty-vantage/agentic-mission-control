---
type: Specification
title: "SPEC-01 Agentic SDLC: the documentation and lifecycle system, its stack, infrastructure, and implementation plan"
description: "The full specification and implementation plan written from sitting I (AS-D1 to AS-D20, 2026-11-01): the principle (agents must navigate these codebases), the one contract vendored into every repository, the CLI, the nine information categories, the provenance chain with trace, the git-event table and auto-merge rule, the provider adapter (Cursor first, Claude second), the tech stack and every environment variable and infrastructure location by name, the slices with their acceptance, what is worked out, what is in development, and the open items the navigation-quality session must resolve before full implementation."
tags: [mission-control, agents, process, documentation, sdlc, spec]
date: 2026-11-01
status: accepted
source: answers/AGENTIC-SDLC-SITTING-I-2026-11-01-ANSWERS.md; SDLC-SYSTEM-PROPOSAL-2026-11-01.md; INFORMATION-CATEGORIES-DRAFT-2026-11-01.md; INTERVIEW-AGENTIC-SDLC-2026-11-01.md (facts F1-F16)
---

# SPEC-01 Agentic SDLC

## 0. How to read this document

Three statuses are used throughout. **Worked out**: decided by the owner in sitting I and
specified here to the level the next agent can build from. **In development**: decided in
direction, with the exact shape left to the navigation-quality session or to the slice that builds
it. **Open**: not decided; listed in §12 with the question to ask. Nothing in this document is
evidence that anything is built; §11 names the proof each slice must leave.

Decisions are cited by id (`AS-Dn`) and are quoted in the owner's words in the answers file. The
system proposal (PR-01) is the design narrative; this specification is the contract.

## 1. Principle and goal

Agents are the primary developers of BellLabs. The most critical thing this program builds is the
ability of an agent, with no prior context, to find the correct and current fact about any part of
Mission Control, Knowledge Services, AI Engineer and Biotech in one or two hops, and to leave the
documentation at least as true as it found it, as a side effect of ordinary git work.

Five principles follow (worked out):

1. **One contract, one implementation** (AS-D1, AS-D5): every repository satisfies the same
   documentation contract, enforced by the same CLI.
2. **Self-sufficient repositories** (AS-D5): the CLI and the skills are vendored and pinned; a
   repository works alone in a clone, a worktree, a cloud environment or CI. `platform/agentic-sdlc`
   is the upstream, never a runtime dependency.
3. **Git lifecycle, not a scheduler** (owner, pre-sitting; AS-D7): documentation work is triggered
   by commits, pushes, pull requests and merges. The only time-based thing permitted later is a
   safety net that re-runs the merge job.
4. **Evidence over activity**: every check distinguishes what is implemented, tested, integrated
   and qualified; a hash proves bytes were observed, never that prose is true.
5. **The owner's subscriptions, provider-selectable** (AS-D10): model-driven steps run through the
   Cursor CLI first and the Claude Code CLI second, behind one adapter.

## 2. Decision register

| Id | Decision (short) | Status | Carried by |
| --- | --- | --- | --- |
| AS-D1 | One contract, one implementation | worked out | this spec, ADR-0064 |
| AS-D2 | Nine information categories, mandatory coverage | worked out | §5, DOC-01 |
| AS-D3 | Four glossaries plus a workspace `GLOSSARY-MAP.md` | worked out | §4.3 |
| AS-D4 | Shared tooling in a new platform repository | worked out | §4.1, ADR-0064 |
| AS-D5 | Self-sufficient repositories; design from components | worked out | §3, ADR-0064 |
| AS-D6 | Matrix accepted with defaults | worked out | §5 |
| AS-D7 | Model work through the owner's subscription CLI; deterministic installer | worked out | §8, ADR-0065 |
| AS-D8 | Hash-based drift with trailer override | worked out | §7.3 |
| AS-D9 | System proposal accepted as final | worked out | PR-01 |
| AS-D10 | Cursor first, Claude second, provider adapter | worked out | §8, ADR-0066 |
| AS-D11 | Provenance chain with `trace`; ideas workspace; remote mirror considered | worked out | §6 |
| AS-D12 | Repository scope and order | worked out | §11 |
| AS-D13 | Ideas workspace in `agentic-sdlc/ideas/` with the writing guide | worked out | §6.2 |
| AS-D14 | Git canonical; publish later to a dedicated Supabase project | worked out | §6.3 |
| AS-D15 | One Linear project per owning repository | worked out | §9 |
| AS-D16 | Feature set; auto-merge in the startup phase | worked out | §7.5, ADR-0067 |
| AS-D17 | GitHub Actions plus Bugbot on PRs | worked out | §7.4 |
| AS-D18 | The exact auto-merge rule | worked out | §7.5, ADR-0067 |
| AS-D19 | Cloud environments, both providers, documented and smoke-tested last | worked out | §10 |
| AS-D20 | Convert and set up now; full implementation after the navigation-quality session | worked out | §11, §12 |

## 3. Architecture

### 3.1 Components

| Component | Responsibility | Status |
| --- | --- | --- |
| **Contract** | what a concept, an ADR, a glossary, an `AGENTS.md` block, a program ledger, an answers file, an idea, a retrieval fixture must contain; the nine categories; the precedence rule (spec > ADR > knowledge > status document) | worked out |
| **CLI** (`.sdlc/cli.mjs`) | enforces the contract (`check`), generates navigation (`build`), retrieves (`search`, `context`), measures (`bench`), detects drift (`drift`), proposes documentation through a provider (`propose`), runs program mechanics (`ledger`, `ideas`, `trace`), talks to Linear (`issue`), installs hooks (`hooks`), updates itself (`update`) | in development (commands fixed; ranking and block shapes to the navigation-quality session) |
| **Skills** (`.agents/skills/`) | the method (`belllabs-method`), the interview (`grill-with-answers`), the documentation update skill the provider runs (`sdlc-docs-update`), the review skill, the upstream Matt Pocock set | in development |
| **Hooks** | six git hooks calling the CLI; optional in-session mirrors for Cursor and Claude Code | worked out |
| **CI** (`.github/workflows/sdlc.yml`) | the PR job and the merge job | worked out |
| **Provider adapter** | one interface, two implementations (Cursor, Claude) | worked out |
| **Ideas workspace** | `agentic-sdlc/ideas/` | worked out |
| **Remote mirror** | `sdlc publish` to a dedicated Supabase project | open (scheduled) |
| **Cloud environments** | one per repository, both providers | worked out, last slice |

### 3.2 Per-repository layout (the contract's physical form)

```text
<repo>/
├── AGENTS.md                 invariants by hand + <!-- BEGIN:sdlc --> generated guide, category index, code map <!-- END:sdlc -->
├── CLAUDE.md                 @AGENTS.md (adapter only)
├── GLOSSARY.md               the repository's terms
├── skills-lock.json          pinned skills (npx skills)
├── .agents/skills/           vendored skills; .claude/skills/ links are machine-local
├── .sdlc/
│   ├── cli.mjs, vendor/      the vendored CLI (dependency-free Node; vendored js-yaml)
│   ├── lock.json             upstream version, commit, file digests
│   ├── config.json           registration: purpose, lifecycle, rules, budgets, docs[], categories, provider{}, linear{}
│   ├── modules.json          module id → source entrypoints, tests, concepts[], generated AGENTS.md target
│   ├── provenance.json       normalized hashes at the last build; drift observations; propose runs (generated)
│   ├── fixtures/retrieval/   queries.json + frozen concept snapshots + baseline.json
│   └── hooks/                the six git hook scripts (generated)
├── .cursor/cli.json          allow/deny for the Cursor adapter (writes limited to docs/, GLOSSARY.md, .sdlc/)
├── .cursor/environment.json  Cursor cloud agent environment (last slice)
├── .claude/settings.json     optional in-session mirrors of the gates (Claude adapter)
├── docs/
│   ├── knowledge/            OKF concepts; index.md and log.md generated
│   ├── adr/NNNN-<slug>.md    decisions
│   ├── specs/<program>/      LEDGER.md, proposals, specs, projections, answers/, CHANGES.md; docs/specs/archive/
│   ├── agents/               per-repository process deltas only
│   └── <operator guides>
└── <module dirs>/AGENTS.md   generated per registered module
```

Worked out. Path moves this implies (performed with `ledger move`, links rewritten): Knowledge
Services `knowledge/` → `docs/knowledge/`; Knowledge Services and Biotech Knowledge Services
`docs/architecture/000N-*.md` → `docs/adr/`; AI Engineer `ai-engineer-architecture/CONTEXT.md` →
`GLOSSARY.md`.

### 3.3 The contract rules (`check`)

Worked out, enforced offline, exit 1 on failure (exit 2 with `--hook`):

1. Every concept has `type: Concept`, `category` (one of nine), `title`, `description`, `tags`,
   `aliases`, `questions`; at most 160 lines; a Citations section whose links resolve inside the
   repository.
2. Every category has at least one concept or an `n/a` line in `docs/knowledge/index.md`.
3. Every ADR has `status`; every accepted ADR is cited by at least one concept or by the
   `decisions` concept.
4. Every glossary term referenced as `**Term**` in a concept exists in `GLOSSARY.md` or in a
   glossary the workspace map names.
5. The generated `AGENTS.md` blocks, `index.md` and module `AGENTS.md` blocks match the sources.
6. Instruction files stay within budget (8 KiB per generated block; root budget in config).
7. Ledger rows point at existing files with known statuses; answers files are well-formed
   (`interview:` resolves; `final` only with **Becomes** and **Folded** on every row; `Source`
   present on every row of a sitting that cites an idea).
8. Retrieval fixtures' digests match; `bench --gate` passes the recorded baseline.
9. `skills-lock.json` matches the vendored skills; `.sdlc/lock.json` matches the vendored CLI.
10. No file under `docs/` contains a secret pattern (reuse the detect-private-key rule).

## 4. Tech stack (worked out)

| Concern | Choice | Why |
| --- | --- | --- |
| CLI runtime | Node 24 on the host (24.18 present), Node 22 in Claude cloud images (24 installed by the setup script); one ES module file, no `npm install`; vendored `js-yaml` | every repository already runs Node; a single file vendors cleanly; the agent-docs lineage proved the shape |
| Retrieval | lexical BM25 with field weights, identifier tokenization, aliases and example questions; no embeddings | deterministic, offline, benchmarkable; the owner's prior audit found lexical sufficient when the corpus is well authored |
| Skills | open Agent Skills layout under `.agents/skills/`, pinned with `npx skills` (`skills-lock.json`) | already the mechanism for Matt Pocock's and LangChain's sets; Cursor, Codex and Claude Code read it |
| Hooks | plain shell scripts under `.sdlc/hooks/`, `core.hooksPath`; prek (MC) and biome (KS) chained, not replaced | no framework dependency; post-* events covered |
| CI | GitHub Actions, one `sdlc.yml` per repository generated by the CLI | the repositories are on GitHub under `jbell-rusty-vantage` (moved 2026-11-06) |
| Model providers | Cursor CLI (`agent`, default, `grok-4.7-high`), Claude Code CLI (`claude`, second) | AS-D10; both subscriptions; one adapter |
| Issue tracker | Linear, team `OVE`, GraphQL with `LINEAR_API_KEY` in scripts, the MCP in sessions | existing convention |
| Remote mirror (later) | Supabase Storage + Postgres in a dedicated project `belllabs-sdlc` | AS-D14 |
| Repository hosting | GitHub account `jbell-rusty-vantage`, HTTPS through the `gh` credential helper (2026-11-06; the `Overton77` account and its `github-legacy` SSH alias are retired) | [worktree routing](../../../../../docs/navigation/WORKTREES.md#github-move-and-clean-slate-2026-11-06) |
| Python | stays the Mission Control application language; the Python docs tools are retired at parity | AS-D1, AS-D5 |

### 4.3 The workspace map

`BellLabs/GLOSSARY-MAP.md` (hand-written at the workspace root) lists the four glossaries:
`platform/mission-control/GLOSSARY.md`, `platform/knowledge-services/GLOSSARY.md`,
`aiengineer/ai-engineer-meta/GLOSSARY.md`, `biotech/biotech-knowledge-services/GLOSSARY.md`, and
how they relate (platform terms owned by MC and KS; domain terms by AIE and Biotech; a domain
glossary may cite a platform term, never redefine it). `BellLabs/workspace.json` lists the
repositories for cross-repository checks and for `trace` across repositories. Worked out.

## 5. Information categories (worked out)

The nine categories, their `category:` values, the question each answers and the initial concept
set per codebase are in [DOC-01](INFORMATION-CATEGORIES-DRAFT-2026-11-01.md), accepted with its
defaults (AS-D6): `boundaries`, `surfaces`, `domain-model`, `persistence`, `execution`,
`qualification`, `operations`, `decisions`, `goals`. The index block groups concepts in this order.
`goals` is one charter concept per domain and carries the product surfaces (agent skills plus CLI,
MCP servers, APIs, web and mobile apps) and the recurring research programs (developing-economy and
research trends; breakthrough developments in curing conditions; longevity protocols and
treatments; longevity-purposed machines), each supplying human-collaborated, evidence-backed
reports.

## 6. Provenance chain, ideas, mirror

### 6.1 The chain (worked out, AS-D11)

```text
idea (ID-n)  →  interview instrument (cites ID-n)  →  answers rows (Source: ID-n; AS-Dn)
             →  spec section / ADR / glossary term (Becomes, Folded)
             →  Linear issue OVE-n (## Provenance: idea, answers rows, spec §, ADR)
             →  commits (OVE-n in subject or trailer)  →  PR  →  merge (commit list posted to the issue)
```

`sdlc trace <OVE-n | ID-n | AS-Dn | ADR-NNNN | <commit>>` prints the whole chain from any link,
reading git, the ledgers, the answers files and Linear (when a key is present; otherwise the
cached issue snapshot). Across repositories it reads `BellLabs/workspace.json`.

### 6.2 The ideas workspace (worked out, AS-D13)

`platform/agentic-sdlc/ideas/`: `README.md` (the writing guide: the itch, the outcome, where it
lives, constraints, evidence, open questions, pick-up instruction), `TEMPLATE.md`, one file per
idea `<YYYY-MM-DD>-<slug>.md` with frontmatter `id`, `title`, `status` (`seed | interviewing |
specified | building | shipped | parked`), `domains`, `created`, `owner`, `promoted_to`, `linear`;
`archive/`. `sdlc ideas new <slug>` assigns the id; `sdlc ideas archive <id>` moves it. Every
repository's `AGENTS.md` carries the pointer line. Agents never edit the itch paragraph.

### 6.3 The remote mirror (scheduled, AS-D14)

Git stays canonical. `sdlc publish`, run by the merge job, writes `trace.json`, the ideas and the
answers snapshots to Storage bucket `sdlc-trace` and upserts `sdlc.trace_links` in a dedicated
Supabase project `belllabs-sdlc` (never `biotech-db` or `aieng-db`, which are disposable). Scheduled
after `trace` works in one repository.

## 7. The git lifecycle (worked out)

### 7.1 Hooks

| Event | Runs | Blocks | Model |
| --- | --- | --- | --- |
| pre-commit | `check --staged --hook`; then the repository's fast lint (prek in MC, biome in KS) | yes | no |
| commit-msg | subject or trailer carries `OVE-n`, or `Docs: none <reason>` | yes | no |
| post-commit | `drift --record` | no | no |
| pre-push | `drift` (gate), `bench --gate`; on drift, offers `propose --apply` (provider adapter) and resumes the push after the docs commit; `SDLC_PROPOSE=auto|ask|never` controls the prompt | yes | on request |
| post-merge, post-checkout, post-rewrite | `build --if-stale` | no | no |

`hooks install` writes the scripts, sets `core.hooksPath`, chains an existing hook path (prek,
husky, the KS maintenance hooks until retired) by calling it after the CLI, and prints status.
Hooks never read `ANTHROPIC_API_KEY`; the Cursor adapter reads `CURSOR_API_KEY` from the process
environment or the repository `.env` without echoing it.

### 7.2 Commit message contract

`<type>(<scope>): <subject> (OVE-n)` with trailers `Docs: none <reason>` (exempts drift) or
`Docs: proposed-by <provider> <session-id>` (written by `propose --apply`). Existing commits are
not back-filled.

### 7.3 Drift (AS-D8)

A registered module drifts when its normalized source hash differs from the hash recorded at the
last `build` and no concept listed in `modules.json` for that module changed in the same range. The
gate fails pre-push unless a commit in the pushed range carries `Docs: none`. `drift --since
<ref>` is what CI runs over the PR range.

### 7.4 The PR job (AS-D17)

`sdlc.yml` on `pull_request: [opened, synchronize, reopened, ready_for_review]`:

1. `check`, `bench --gate`, `drift --since <base>`, the repository's test suite; each a named
   status check.
2. Provider step (needs `CURSOR_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` as a repository secret):
   `propose --apply` on drift (commits to the PR branch), then review with the `code-review` skill
   posting findings as PR comments and a `review-posted` status; bugs filed with `issue bug`.
3. `issue link` adds the PR URL to the Linear issue.

Bugbot is enabled per repository in the Cursor dashboard as an additional reviewer. Cursor
Automations are not used.

### 7.5 The merge job and the auto-merge rule (AS-D16, AS-D18)

On `push: main`: `build`, release notes from `CHANGES.md` into a GitHub release, `issue
transition` to Done, `issue bug` for deferred findings, later `publish`.

Branch protection on `main` requires `check`, `bench`, `drift`, `tests`, `review-posted`. A PR with
green required checks squash-merges automatically unless it carries the label `hold` or touches a
protected path (`packages/*/migrations/**`, `supabase/migrations/**`, `.github/workflows/**`,
`.sdlc/lock.json`, `skills-lock.json`), which keeps a human merge. Docs-only PRs (only `docs/`,
`GLOSSARY.md`, `.sdlc/` except the lock) skip `review-posted`. Sunset: revisit when the startup
delivery mode ends (ADR-0067).

## 8. The provider adapter (worked out, AS-D10, AS-D17)

```json
"provider": {
  "default": "cursor",
  "cursor": { "model": "grok-4.7-high", "timeoutMinutes": 15 },
  "claude": { "model": "claude-fable-5-1", "maxTurns": 20, "maxBudgetUsd": 2, "timeoutMinutes": 15 }
}
```

Interface: `run(task, inputs) → {patch, summary, sessionId, provider, model, durationMs, cost?}`
where `task` is `docs-update | review` and `inputs` are the drift set, the skill path, the allowed
paths and the PR range. `SDLC_PROVIDER` and `SDLC_MODEL` override per run.

| | Cursor (default) | Claude |
| --- | --- | --- |
| Command | `agent -p "<prompt>" --output-format json --model grok-4.7-high --force --trust --workspace <repo>` | `claude -p "<prompt>" --output-format json --model <model> --max-turns N --max-budget-usd X --permission-mode acceptEdits --allowedTools "Read,Grep,Glob,Edit,Write,Bash(git diff *)"` |
| Auth | `CURSOR_API_KEY` (user key; bills the plan's included pool for Cursor models) | the `/login` subscription locally; `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` in CI; `ANTHROPIC_API_KEY` unset |
| Scope | `.cursor/cli.json` allow/deny: `Write(docs/**)`, `Write(GLOSSARY.md)`, `Write(.sdlc/**)`, deny the rest; `Shell(git diff)` allowed | `--allowedTools` as above |
| Caps | wall clock (no turn or spend flag) | turns, estimated spend, wall clock |
| Prompt | the task, the drift set and the skill path in the argument; long inputs by path | same, or stdin |
| Skills | reads `.agents/skills` and `AGENTS.md` natively | reads `.claude/skills` links |
| Programmatic management | Cloud Agents API (`POST /v1/agents`, Bearer key) and the Agent SDK need no browser; the API key, Bugbot and Automations toggles are one-time dashboard actions | `claude setup-token` once; the Action is configuration |

Every run is recorded in `provenance.json` (`propose_runs[]`) and in the PR body.

## 9. Linear integration (worked out, AS-D15)

`.sdlc/config.json` carries `linear: { team: "OVE", project: "<name>", labels: {category: [Feature, Bug], state: [...]} }`.
Projects: Mission Control, BellLabs Knowledge Platform, and new: Agentic SDLC, Biotech Knowledge
Services, AI Engineer. `issue link <OVE-n> <url>`, `issue transition <OVE-n> <state>`, `issue bug
--title --body --fingerprint <sha>` (deduplicated on the `fingerprint:` line), `issue create` (used
by `to-tickets` with `## Provenance`). Cross-repository work gets a parent issue in the project of
the repository that merges last. GraphQL with `LINEAR_API_KEY`; the MCP server in sessions.

## 10. Infrastructure, environment variables and their locations (worked out)

No values here; names and places only. Read `docs/navigation/DATA-PLANES-AND-CREDENTIALS.md` for
the data planes.

| Name | Purpose | Local location | CI location | Cloud location |
| --- | --- | --- | --- | --- |
| `CURSOR_API_KEY` | Cursor adapter | `platform/mission-control/.env`, `platform/knowledge-services/.env` (present); to add to the other five repositories' `.env`; not in the workspace `.env` | repository secret `CURSOR_API_KEY` | Claude cloud: network secret for `api.cursor.com`; Cursor cloud: the account |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude adapter in CI (optional) | not stored locally (the `/login` session is used) | repository secret | n/a |
| `ANTHROPIC_API_KEY` | Mission Control runtime only | `platform/mission-control/.env` | not for sdlc jobs | unset in hooks |
| `LINEAR_API_KEY` | `issue`, `trace` | `platform/mission-control/.env` (present) | repository secret | network secret for `api.linear.app` |
| `SDLC_PROVIDER`, `SDLC_MODEL`, `SDLC_PROPOSE` | per-run overrides | shell | workflow env | environment variable |
| `GITHUB_TOKEN` | the Action's default token (does not retrigger workflows) | n/a | automatic | n/a |
| GitHub remotes | `https://github.com/jbell-rusty-vantage/<repo>` (`agentic-mission-control`, `agent-knowledge-services`, `agent-engineer-db-contract`, `agentic-sdlc`, `biotech-knowledge-services`, `biotech-postgres-db-contract`, `ai-engineer-services`, `ai-engineer-cloud-agent-knowledge-repo`); clean slates since 2026-11-06 | `gh` credential helper | n/a | the GitHub App |
| Linear | workspace `overtonbell`, team `OVE`, projects per §9 | `.mcp.json` `linear` | GraphQL | MCP connector |
| Supabase `belllabs-sdlc` | the mirror (later) | not created | not created | not created |
| Cloud environments | one Claude Code environment and one `.cursor/environment.json` per repository | n/a | n/a | per repository, last slice |

Secrets rules unchanged: never printed, never committed, never in documentation; the hook reads
`.env` with a pattern match and passes the value only to the provider child process.

## 11. Implementation plan

Repository order (AS-D12): `agentic-sdlc`, `mission-control`, `knowledge-services`,
`biotech-knowledge-services`, `ai-engineer-db-contract`, `ai-engineer-meta` (committed, remote
added), `biotech-postgres-db-contract` (made a repository). The three dirty AI Engineer research
repositories are a later slice.

| Slice | Deliverable | Acceptance (the proof it leaves) | Status |
| --- | --- | --- | --- |
| S0 Conversion | this spec; ADR-0064 to 0067; glossary terms; Linear project and issues; the skill and template updates; `platform/agentic-sdlc` initialized with `ideas/`; commits on `sprint-oc` | `program_ledger.py check` green; the answers file `final`; the MC docs checks green; the upstream repository pushed | this sitting |
| S0.5 Navigation quality | the design of retrieval and navigation: ranking, the `AGENTS.md` block shapes, `context` output, fixture authoring policy, cross-repository navigation, budgets, measurement | an accepted projection (`NAVIGATION-DESIGN.md`) and the fixture format frozen; the open items of §12 answered | next session (AS-D20) |
| S1 The CLI | `check`, `build`, `search`, `context`, `bench`, `drift`, `ledger` (with `trace`), `ideas`, `hooks`, `update`, `lock`; contract tests ported from both lineages; the parity fixture over the 66 MC concepts | `node tools/cli.test.mjs` green; `check` and `build` reproduce MC's current `AGENTS.md` index and KS's generated block from their sources | in development |
| S2 Vendor into MC | `.sdlc/` in Mission Control; Python docs tools retired; hooks installed; concepts gain `category`; the new concepts of DOC-01 | `check` green in MC; `bench` baseline recorded; `pre-push` blocks a seeded drift in a fixture repository | planned |
| S3 KS, BKS, AIDB | moves (`knowledge/`, `docs/architecture` → `docs/adr`); `.sdlc/`; concepts per DOC-01; KS maintenance queue retired | `check` green in each; KS benchmark preserved as the first fixture set | planned |
| S4 AI Engineer meta and Biotech contract | `ai-engineer-meta` committed with a remote; `GLOSSARY.md` rename; `biotech-postgres-db-contract` initialized; `GLOSSARY-MAP.md` and `workspace.json` at the root | `trace` resolves across all seven repositories | planned |
| S5 Provider adapter and CI | `propose`, `issue`, `sdlc.yml` generated per repository, Bugbot enabled, secrets placed, branch protection per §7.5 | one PR per repository shows: docs commit proposed by Cursor, review posted, Linear transitioned, auto-merge on green | planned |
| S6 Retrieval audits | the eight-criterion audit per repository (`RETRIEVAL-AUDIT.md`), scores with file-level evidence, fixtures extended from the misses | scores recorded; every critical miss becomes a fixture case and a concept fix | planned |
| S7 Mirror | `publish`, the `belllabs-sdlc` project | one repository's chain readable from the bucket | scheduled later |
| S8 Cloud environments | one Claude Code environment and one Cursor environment per repository; operator guides; smoke sessions | each smoke session runs `check` and one `propose` on a throwaway branch | last |

## 12. Open items for the navigation-quality session (AS-D20)

These are the questions the next session must answer before S1 is built, each with the
recommendation to start from:

1. **What does an agent read first?** The generated root block: guide (purpose, lifecycle, rules),
   then the category index (nine groups, one line per concept: title, aliases, the question it
   answers), then the code map (modules with entrypoints). Recommendation: keep the root block
   under 8 KiB and push everything else behind module `AGENTS.md` and `context`.
2. **Module-level materialization.** Which directories get a generated `AGENTS.md` block, what it
   holds (purpose, entrypoints, tests, the concepts that explain it, the invariants), and how
   nested blocks avoid repeating the root. Recommendation: one block per `modules.json` entry, no
   deeper than two levels.
3. **Ranking.** Field weights (title, aliases, questions, tags, description, headings, body),
   identifier tokenization, the treatment of glossary terms and ADR titles as first-class
   documents, and whether `docs/specs` of active programs join the default corpus.
   Recommendation: BM25 with the KS weights as the seed, specs opt-in by ledger status `active`.
4. **`context` output.** The bounded sections, entrypoints, tests, decisions and freshness it
   returns, and its size cap. Recommendation: the KS `context` shape plus the category and the
   glossary terms used.
5. **Fixture authoring policy.** Who writes `queries.json` cases (the author of a concept writes
   three questions; the audit adds misses), the critical flag, the held-out partition, and when
   baselines move. Recommendation: fixtures change only with a concept change in the same PR.
6. **Cross-repository navigation.** How an agent in Mission Control finds a Knowledge Services
   concept: `workspace.json` plus `search --workspace`, or pointer concepts. Recommendation: pointer
   concepts in `boundaries` plus `search --workspace` when the sibling checkout exists.
7. **Budgets.** The root `AGENTS.md` of Mission Control is 29 KB today; what moves out, and the
   hand-written invariants' cap. Recommendation: 12 KiB hand-written plus 8 KiB generated.
8. **Measurement.** The retrieval audit rubric (entry-point quality, index freshness, category
   coverage, skill routing, fact placement, evidence discipline, staleness signals, search
   ergonomics), scored 0 to 10 with file-level evidence, and the bench numbers it must correlate
   with. Recommendation: run it before S2 as the baseline and after S6 as the proof.
9. **Skills routing.** Which skills the `AGENTS.md` block names, in what order, and how the
   provider adapter's `sdlc-docs-update` skill is kept byte-identical across repositories.
10. **The two engines' remaining differences** worth keeping: KS `context` evidence freshness,
    MC index notes, MC `okf_search` explicit entrypoints.

## 13. Program acceptance

The program is done when every repository in §11 passes `check` and `bench --gate`, the hooks and
`sdlc.yml` are installed and one PR per repository has gone through the full table, the retrieval
audits are recorded with their scores, `trace` resolves an `OVE-n` across repositories, the ideas
workspace holds its guide and at least one idea picked up through the chain, and the cloud
environments are documented with their smoke sessions. Spend stays inside the owner's ceilings and
is reported per run from `provenance.json`.
