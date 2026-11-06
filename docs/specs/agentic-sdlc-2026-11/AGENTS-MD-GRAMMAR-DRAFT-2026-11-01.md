---
type: Working Draft
title: "Compressed AGENTS.md: the grammar, budgets, sidecar files and update rules (best-effort draft for sitting II)"
description: "Best-effort draft, written 2026-11-01 for the owner's review in sitting II: what a repository AGENTS.md contains and in what order, the byte budgets and what happens when they are exceeded, the generated block grammar at root and module level, the sidecar files that feed it (config.json, modules.json, infrastructure.json, fixtures), who regenerates it and when, and how a threshold is changed. Everything here is a recommendation until the owner answers Q12 to Q14."
tags: [mission-control, agents, process, documentation, sdlc, agents-md, draft]
date: 2026-11-01
status: draft
---

# Compressed AGENTS.md: grammar, budgets, sidecars, update rules

Worked from the five-surface model that Mission Control already runs, the Knowledge Services
generated block, the agent-docs 8 KiB cap, and the owner's requirement that infrastructure
locations and access be extremely obvious. Numbers are proposals; sitting II fixes them.

## 1. What an agent sees, in order

A repository `AGENTS.md` is read top to bottom by every harness. The order is the priority order
of what an agent must know before touching anything:

```text
1  Title line and one-sentence purpose                      hand-written     ≤ 200 B
2  Read-before-editing (3-6 lines: directive, dirty work,   hand-written     ≤ 600 B
   branch check, the ideas pointer)
3  INFRASTRUCTURE pointer: "Data planes, remotes, secrets,  generated        ≤ 400 B
   cloud environments, MCP servers: docs/INFRASTRUCTURE.md"
   plus the three most-used commands
4  Invariants (rules an agent breaks without warning)       hand-written     ≤ 3 KiB
5  <!-- BEGIN:sdlc -->                                      generated        ≤ 8 KiB
   5a  Guide: purpose, lifecycle, what is NOT here
   5b  Knowledge index by category (9 groups; one line per concept:
       `name — question it answers` ; aliases only when the name is opaque)
   5c  Code map: one line per registered module → its AGENTS.md
   5d  Skills routing: the 6-10 skills this repo expects an agent to call, by trigger
   5e  Verify: the check, build, search, bench commands
   <!-- END:sdlc -->
6  Programs in flight (one line each: ledger link, next step) generated      ≤ 1 KiB
```

Budget: hand-written parts ≤ 4 KiB, generated block ≤ 8 KiB, whole file ≤ 14 KiB (Mission
Control is 29 KiB today; the surplus is explanation that belongs in concepts and in module
blocks). The generated block never repeats a hand-written line; `check` fails on duplication.

## 2. The generated block grammar

```text
<!-- BEGIN:sdlc v=<cli-version> built=<date> src=<config digest> -->
## Repository guide
<purpose>. Lifecycle: <lifecycle>. Not here: <two or three boundaries from config.rules>.

## Knowledge (docs/knowledge, 9 categories)
boundaries: service-boundaries — who owns what and what this service refuses
surfaces:   interfaces — the HTTP contract · capabilities — what a mission may bind · …
domain-model: mission-manifest — … · lifecycle — … · revisions — …
persistence: …
execution: …
qualification: …
operations: environments — … · secret-broker — …
decisions: decisions — ADR index and open questions
goals: goals — product surfaces and research programs
(n/a lines appear as `persistence: n/a (reason)`)
Search: node .sdlc/cli.mjs search "<terms>" · context "<question>"

## Code map
src/mission_control/core → src/mission_control/core/AGENTS.md — <one line>
…

## Skills
start a session: belllabs-method · look up a fact: mission-control-docs · interview: grill-with-answers · …

## Verify
node .sdlc/cli.mjs check · build · bench --gate · drift
<!-- END:sdlc -->
```

Rules: one line per concept, no wrapping; the line is `name — <the `questions[0]` of the concept
trimmed to 70 characters>`; categories in the fixed order; a category with more than twelve
concepts collapses to `name, name, name … (+n; see docs/knowledge/index.md#category)`.

## 3. Module-level AGENTS.md (generated)

For every entry in `modules.json`, a file `<module dir>/AGENTS.md` carrying only a generated
block (hand-written text above the marker is preserved):

```text
<!-- BEGIN:sdlc-module id=<module id> -->
# <module name>
<purpose, one or two sentences from modules.json>
Entrypoints: <path>, <path> · Tests: <path> · Owner of: <invariant lines from config>
Explained by: docs/knowledge/<concept>.md, … · Decided by: ADR-NNNN, …
Depends on: <module ids> · Used by: <module ids>
<!-- END:sdlc-module -->
```

Budget ≤ 2 KiB; depth at most two levels; a directory without a module entry gets no file.

## 4. Infrastructure: extremely obvious

`docs/INFRASTRUCTURE.md` per repository, generated from `.sdlc/infrastructure.json` and linked
from line 3 of `AGENTS.md`. Fixed table shape, names only, never values:

| Thing | Identity | Where the credential lives (local / CI / cloud) | How an agent reaches it | Owner doc |
| --- | --- | --- | --- | --- |
| aieng-db | Supabase `wkythqbofmckbuoothhn` | `.env` `SUPABASE_URL`, `SUPABASE_SECRET_KEY` / secret `…` / network secret | MCP `supabase-aieng` (read-only); DSN in `.env` | DATA-PLANES-AND-CREDENTIALS.md |
| GitHub remote | `git@github-legacy:Overton77/mission-control.git` | `~/.ssh/config` host `github-legacy` | git | — |
| Linear | workspace `overtonbell`, team `OVE`, project Mission Control | `.env` `LINEAR_API_KEY` / secret / network secret | MCP `linear`; GraphQL | issue-tracker.md |
| Cursor adapter | `agent` CLI, model `grok-4.7-high` | `.env` `CURSOR_API_KEY` / secret / network secret | `.sdlc/cli.mjs propose` | SPEC-01 §8 |
| Local services | Docker `sprint-v-pg17` 127.0.0.1:55433; Temporal 7233; Agent Server 2024 | — | compose files | WSL2_WORKER_RUNBOOK.md |
| Cloud environments | Claude Code env `<name>`; Cursor `.cursor/environment.json` | per environment | the session | S8 guides |

The workspace root carries the same table across all repositories (today's
`docs/navigation/DATA-PLANES-AND-CREDENTIALS.md` is the seed). `check` fails when a `.env`
variable name used in code is absent from `infrastructure.json`, and when the file names a
value-looking string.

## 5. Sidecar files

| File | Hand-maintained | Feeds | Changed when |
| --- | --- | --- | --- |
| `.sdlc/config.json` | yes | guide, rules, budgets, skills routing, provider, linear | a rule, budget or routing changes (PR with `Docs:` trailer) |
| `.sdlc/modules.json` | yes | code map, module blocks, drift associations | a module is added, split or renamed (same PR as the code) |
| `.sdlc/infrastructure.json` | yes | `docs/INFRASTRUCTURE.md`, line 3 of `AGENTS.md` | a data plane, remote, secret name or environment changes |
| concept frontmatter (`category`, `aliases`, `questions`) | yes, by the concept author | knowledge index lines, search, fixtures | with the concept |
| `.sdlc/provenance.json` | no | drift, bench baseline, propose records | every `build`, `drift --record`, `propose` |
| `.sdlc/fixtures/retrieval/*` | yes (cases), no (snapshots) | `bench` | with a concept change or an audit miss |
| `docs/knowledge/index.md`, `log.md` | no | reading entry, history | every `build` (log from `CHANGES.md`) |

`index-notes.toml` (Mission Control) folds into `config.json` as `notes` per directory.

## 6. Update rules

1. **Who regenerates.** `build` runs locally at post-merge, post-checkout and post-rewrite
   (`--if-stale`), and in the merge job. A PR whose generated block is stale fails `check` in
   CI; the author runs `build` and commits, or the PR job's `propose --apply` does.
2. **Hand-written parts change only by PR** with a reviewer (the `review-posted` check); the
   generated block is never edited by hand (`check` detects an edit inside the markers by digest).
3. **Budgets are gates, not warnings.** Over budget fails `check` with the top three largest
   lines named. The fix is to move text into a concept or a module block, never to raise the cap
   in the same PR.
4. **Changing a threshold** (a budget, the 160-line concept cap, the twelve-concept collapse, the
   two-level module depth) is a one-line ADR and a `config.json` change in a PR labelled `hold`,
   because every repository inherits it on the next `update`.
5. **A concept is the unit of truth.** The index line is derived from it; if the line reads wrong,
   fix the concept's `questions[0]`, not the index.
6. **Staleness is visible.** The block header carries `built=<date>` and `src=<digest>`; `check`
   compares the digest, so a reader can trust a fresh block and distrust a stale one at a glance.
7. **Programs in flight** (section 6) are derived from ledger rows with status `active`; a
   finished program disappears from `AGENTS.md` when its ledger says `archived`.

## 7. Worked example: Mission Control today → tomorrow

Today: 29,390 bytes, sections "Work by concern", "Invariants", "Verify", "Agent skills",
"Documentation index" (a pipe-delimited directory map of 26 lines). Tomorrow under this grammar:
title and purpose (1 line), read-before-editing (5 lines), infrastructure pointer (3 lines),
invariants (the current 20 lines, trimmed to the ones an agent breaks without warning), the
generated block (guide 3 lines; 66 concepts in 9 category lines with collapses; 13 module lines;
8 skill triggers; 4 verify commands), programs in flight (3 lines). Estimated 11 to 13 KiB. The
removed material goes to `docs/knowledge/architecture.md` (the "work by concern" map) and to the
module blocks.

## 8. What sitting II must decide

Q12 (budgets and gates), Q13 (block content and order), Q14 (sidecars and update rules) in
`INTERVIEW-NAVIGATION-AND-KNOWLEDGE-2026-11-02.md`. Everything else here follows those answers.
