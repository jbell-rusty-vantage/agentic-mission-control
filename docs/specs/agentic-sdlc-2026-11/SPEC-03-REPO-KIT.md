---
type: Specification
title: "SPEC-03 The repository kit: one way to work in every BellLabs codebase"
description: "What every BellLabs repository carries so an agent can orient, act, prove and trace in the same way (AS-S9, AS-D67): provenance from interview to commit, ./dev runners, data-plane access that defaults to local, a short AGENTS.md, a feature map, slim purposeful docs with a retrieval bench, and CI that runs the gate. Mission Control holds the canonical copy (AS-D65); the other repositories copy it. Adoption order: Knowledge Services and the AI Engineer database contract first, because the schema work runs there, then the AI Engineer service."
tags: [mission-control, agents, process, sdlc, provenance, kit, spec]
date: 2026-11-18
status: accepted
decisions: [AS-D65, AS-D67, AS-D68, AS-D69]
linear: [OVE-243, OVE-205]
source: answers/AGENTIC-SDLC-SITTING-IX-2026-11-18-ANSWERS.md
---

# SPEC-03 The repository kit

The owner's words (AS-D67): "The same tenants apply to the other codebases. interview -> commit provenance. cli runners.
feature map. okf documentation (slim and purposeful) . Database access and knowledge and slim purposeful AGENTS.md WITH
retrieval evaluation testing for feedback loops." Order (AS-D68): set up and document, then the AI Engineer schema, then
real missions, then Mission Control web. The kit serves that order, so it stays small: a repository adopts it in one
session, and nothing in it waits on the schema.

<a id="parts"></a>
## 1. The seven parts

Each part names the canonical file in Mission Control and the check that proves a repository has it.

| # | Part | Canonical in Mission Control | Proven by |
| --- | --- | --- | --- |
| K1 | **Provenance.** Work starts in a committed answers file (`<FAM>-S<n>`, the owner's words quoted), then a spec or brief, then a Linear `OVE` issue with `Goal:` and a `## Provenance` block. Every commit ends with `Refs:` and, when they apply, `Decisions:` and `Docs:`. A finished issue gets a `## Completion` comment | [SPEC-02](SPEC-02-PROVENANCE-CHAIN.md#chain); `docs/tools/trace.py` (set `REPO_KEY`, `CUTOVER`, the goals path); `.git/hooks/commit-msg` (warn-only) | `./dev trace check` reports 0 gaps; the CI provenance job runs warn-only |
| K2 | **`./dev` runners.** One front door: `status` (orient, JSON), `doctor`, `check` (the fast gate), `test`, `trace`, and `db` (K3). Standard-library Python, so it runs before any install | `dev`, `dev.ps1`, `scripts/dev/dev_cli.py` | `./dev status` and `./dev check` run on a fresh clone |
| K3 | **Data-plane access, local by default.** One registry of identities (never credentials) names each plane, its posture (`disposable`, `protected`, `retired`) and its endpoints. `./dev db status|schema|query --plane P` is read-only unless `--write --confirm <ref>`; `--plane` is always required; schema changes go only through the repository's installer. A process with no plane named reaches loopback, never the remote. `aieng-graph` (`4773dc72`) is refused everywhere | Design: [DATA-ACCESS §5](../../../../../docs/state/2026-11-17/plan/inputs/DATA-ACCESS.md#registry) (at the workspace root). Registry file: `config/planes.toml`, built here first; other repositories carry the planes they reach | `./dev db status --plane <local plane>` answers; a remote read uses a reader login; no repository `.env` holds a remote admin DSN by default |
| K4 | **A short `AGENTS.md`.** At most 60 lines: what the repository is for, the three commands (`./dev status`, `./dev check`, `./dev trace check`), each boundary with the check that enforces it, and pointers. Generated indexes and code maps live in their own files, linked once | Mission Control's own file is the first to be cut to this shape | `wc -l AGENTS.md` ≤ 60; the docs checker passes |
| K5 | **A feature map.** `features/<feature>.md`, one per user-visible feature: what it does, where its code and tests are, how to reach it as a user, how to drive it (`./dev` or the CLI), gotchas | Template: the 2026-11-17 handoff §3.2 (at the workspace root). Mission Control's full map waits (AS-D66, OVE-240) | each feature file names a command that proves it, and that command runs |
| K6 | **Slim, purposeful docs with a retrieval bench.** A concept stays only if a retrieval fixture asks for it, it carries no line numbers, and it is not older than the code it explains. Fixtures live in `.sdlc/fixtures/retrieval/queries.json`; the bench gates on regression | `docs/tools/okf_search.py`, `docs/tools/bench_retrieval.py`, `.sdlc/fixtures/retrieval/` | `bench_retrieval.py --gate` (or the repository's own bench) is part of `./dev check` |
| K7 | **CI runs the gate** on every push to `main`, on Linux | `.github/workflows/ci.yml` | the latest `main` run is green, or its red is filed as an issue |

<a id="adoption"></a>
## 2. Where each repository starts (measured 2026-11-18)

| Repository | Has | Lacks |
| --- | --- | --- |
| `platform/mission-control` | K1, K2 (no `db`), K6, K7 | K3, K4 (131 lines), K5 |
| `platform/knowledge-services` | K7 (four workflows), its own docs system (`.agent-docs`) and retrieval checks | K1, K2, K3 (defaults to the remote AI Engineer database when no application is set), K4 (109 lines), K5 |
| `aiengineer/ai-engineer-db-contract` | K7 (fresh install from empty and 30 SQL suites on CI), `.agent-docs`, K4 (58 lines) | K1, K2, K3 (the schema workspace prefers the remote admin DSN), K5 |
| `aiengineer/ai-engineer-service` | K4 (62 lines) | K1, K2, K3 (`dev` and `start` load the remote `.env`), K5, K7 |

Where a repository already has its own working tool (the `.agent-docs` checker, its own retrieval checks), the kit wraps
it in `./dev check` instead of replacing it.

<a id="records"></a>
## 3. Where the records live

- Mission Control answers: `docs/specs/<program>/answers/`, families such as `AS`.
- The AI Engineer schema program's answers and ledger live in `platform/ai-engineer-research-2026-11-02/10-review-workspace/`,
  which is **not a git repository**. Its session ids (`B08-S<n>`) are valid in `Refs:`, but no trace can read them until the
  folder is versioned. Moving it into `aiengineer/ai-engineer-db-contract/docs/review/` (7.9 MB) is the owner's decision
  ([schema brief §3](../../../../ai-engineer-research-2026-11-02/10-review-workspace/process/OFFICIAL-SCHEMA-SEQUENCE.md#s3)).
- Each repository's trace reads its own git history and the shared Linear `OVE` snapshot.

<a id="out"></a>
## 4. Not in the kit

`./dev stack`, `feature`, `drive`, `evidence` and `deploy` come when a feature needs them, not before. No new ledger,
no new issue tracker, no blocking hooks (warn-only until the owner says block, AS-D46).
