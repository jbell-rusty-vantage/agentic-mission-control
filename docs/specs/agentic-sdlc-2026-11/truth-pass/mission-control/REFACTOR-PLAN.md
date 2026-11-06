---
type: Working Draft
title: "Mission Control documentation refactor plan: the knowledge map, formats, phases and acceptance"
description: "The execution plan for the Mission Control truth pass (AS-D24, AS-D27, AS-D33..D36): the owner's model of Mission Control restated, the target knowledge map by category with built/specified/goal markers, the concept, research and fixture formats, the phases the Sonnet 5.5 refactor agents run (harvest and delete mission-control-general, rewrite concepts, ADRs, programs, other surfaces, the compressed AGENTS.md, fixtures and bench), and what proves it is done."
tags: [mission-control, truth-pass, sdlc, refactor, plan]
date: 2026-11-01
status: draft
---

# Mission Control documentation refactor plan

## 0. Goal, inputs, constraints

**Goal (owner, AS-D33):** "The mechanics of stage graph, goal directed, parallel swarm, evaluator
optimizer and linked workflows at the scheduling, output contract obligation, context transfer and
agent runtime and capability configuration should be COMPLETELY KNOWN." An agent with no context
finds the correct, current fact in one or two hops. "We will most likely have to enhance the
documentation after some fixtures so we need to start the best way we can": the bench after this
refactor is the baseline for the next round, not the end.

**Inputs (read before acting):** `../../answers/AGENTIC-SDLC-SITTING-II-2026-11-02-ANSWERS.md`
(AS-D21..D36 and the two verbatim sections), `A-MISSION-CONTROL-GENERAL.md`,
`B-KNOWLEDGE-CONCEPTS.md`, `C-PROGRAMS-ADRS-ARCHIVE.md`, `D-OTHER-SURFACES.md`,
`TASK-FIXTURE-T001-SANDBOX-PROVIDER.md`, `../../AGENTS-MD-MISSION-CONTROL-DRAFT-2026-11.md`
(DOC-08, with grammar edits G1-G16 accepted by AS-D31), `../../CONCEPT-LISTS-DRAFT-2026-11.md`
(MC section: categories and drafted `questions[0]`), `../../RETRIEVAL-AUDIT-BASELINE-2026-11.md`
(34 miss cases), `../../STATE-mission-control-2026-11.md`.

**Constraints:** branch `sprint-oc`; commit in logical commits `<type>(<scope>): <subject>
(OVE-206)` ending `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; stage only your own
paths (other sessions have untracked files). No source-code behaviour changes (code defects become
OVE issues, listed in §6); test files change only where they hard-code a moved document path. No
paid model runs, no remote operations, never print `.env` values. Every claim is labelled
implemented / tested / integrated / qualified with a committed proof path (AS-D29: never a private
`.scratch/` path alone). Code is the truth for what runs; ADRs are the truth for what was decided
(MC-1, resolved by the deletion of the spec pack).

## 1. The owner's model of Mission Control (what the docs must make obvious)

1. **Purpose.** Bring the agent platforms (Deep Agents first; Claude Agent SDK, Codex, Cursor,
   Managed Agents, Codex Agents; more as adapters) together as robust, controllable **missions**,
   supplied as a real service. Known for deep-research knowledge production and for putting all
   coding agents under one roof.
2. **Provider lifecycles synthesized by Temporal.** Each provider has a native lifecycle; Mission
   Control wraps it in Temporal workflows so it can read and write **mission state snapshots** and
   control the run: fork, queue a message, inject context, interrupt, and (goal) **mutate per
   policy**, e.g. change a workflow mid-workflow.
3. **Workflow systems.** Stage Graph, Goal Loop (GoalDirected in code), Parallel Swarm (a Stage
   Graph profile, OC-D204), Evaluator Optimizer (on Goal Loop machinery, OC-D205), and **linked
   workflows** (mission chains). Each must be known at four levels: **scheduling**, **output
   contract obligations**, **context transfer**, **agent runtime and capability configuration**.
4. **Deep Agents** is the most refined lane and the reference representation of agent capability
   and workflow architecture; other lanes follow its adapter shape.
5. **Persistence.** Mission Control's schemas are installed into each application's PostgreSQL
   (AI Engineer, Biotech) as the common component, and relate to the knowledge schemas (KS, AIDB,
   BKS). Temporal persistence and Agent Server persistence are separate.
6. **Events.** Redis and WebSockets (Socket.IO) publish and subscribe granular workflow and agent
   events; a remote Upstash Redis now exists.
7. **Search.** Mission Control finds workflows, agent providers and configuration by keyword,
   semantic and workspace-navigation search (the Selection Workspace, the catalog).
8. **Surfaces.** MCP server, agent skills + CLI (`missionctl`), HTTP API; later the dashboard
   control plane.
9. **Goals not yet built** (each a `goal` section, never stated as built): local↔cloud in one
   session across providers (today a local/cloud split); per-policy mutation; **provider batch
   APIs** (Anthropic, OpenAI batch requests, a workflow waits on the batch output and continues);
   the **human review loop** (mission output reaches the owner, who continues, rejects with
   feedback and redoes, or starts new; human gates exist, this loop is not architected);
   deployment (proposal stage; the Vercel ingress server is up).

## 2. Target knowledge map (`docs/knowledge/`)

Markers: **B** built (state the label), **S** specified-not-built, **G** goal. `*` = new concept.
Existing files not listed are merged into the listed one (B-KNOWLEDGE-CONCEPTS §2 table governs).

| Category | Concepts |
| --- | --- |
| boundaries | `mission-control`* (what MC owns and refuses; the apps own content; replaces `architecture`), `knowledge-services` (pointer + contract), `application-profile`, `applications`* (AI Engineer and Biotech placement; pointer concepts to KS/AIDB/BKS for `search --workspace`) |
| surfaces | `interfaces` (HTTP; 7 missing routers fixed), `coordinator-surface`* (MCP, `missionctl`, the mission-control skill router; OVE-182 B, rest S), `mission-stream` (Redis/Upstash + Socket.IO, B; Upstash noted from infra), `selection-workspace` (keyword, semantic, navigation search; B tested), `dashboard`* (G, one short section in `coordinator-surface` instead if under 30 lines) |
| domain-model | `mission-manifest`, `workflow-systems` (rewritten to OC-D204/D205, one table: system × scheduling × obligations × transfer × runtime config), `stage-graph`*, `goal-loop`* (target model vs GoalDirected built subset), `parallel-swarm`, `evaluator-optimizer`, `mission-chains` (linked workflows; Child Mission Invocation S section), `output-contracts`, `context-and-continuation` (merged with `continuation-checkpoint`), `lifecycle`, `revisions` (incl. per-policy mutation G), `interventions` (queue, inject, interrupt, fork), `human-gates` (+ the review loop G), `durable-controls`, `recursive-composition`, `completion` |
| persistence | `persistence` (invariants only), `database-component`* (release numbering 1.x, consumers, locks, how app DBs carry MC schemas, relation to knowledge schemas), `collections-and-current-sets`, `workspace-closure`, `saved-result-settlement`, `provider-frames-and-transcript` (merged with `transcript-projection`) |
| execution | **pinned first:** `deep-agents-lane` (absorbs turn-stops; middleware order S/B; sandbox backends, Daytona half-wired), `agent-configuration` (compile path, model bindings), `deep-agents-children` (renamed `async-children` + sync children); then `temporal-synthesis`* (how provider lifecycles become Temporal workflows over mission state snapshots; replaces `execution`), `lanes-and-harness` (adapter shape every provider follows), `provider-lanes`, `cursor-lane`, `hosted-api-lanes`, `provider-batch`* (G: batch APIs + workflow wait), `session-ownership-and-dispatch`, `recovery`, `precise-fork`, `durable-reactions`, `watchers`, `coordinator-attention`, `placement-admission`, `hook-contributions`, `instruction-layering`, `model-catalog`, `capabilities`, `capability-seeds` |
| qualification | `qualification` (merged with `release-and-qualification`, keyed to W0-W5), `evaluator-attempts`, `trusted-judgment`, `documentation-retrieval-fixtures`* |
| operations | `operations`, `environments` (merged with `environment-preparation` if under cap), `secret-broker`, `budgets-and-usage`, `owner-prerequisites`, `owner-probe-bootstrap`, `deployment`* (proposal stage; Vercel ingress up; local/cloud split today, local↔cloud one-session G; points at `docs/DEPLOYMENT_OPTIONS_2026-10-12.md` and the 10-31 roadmap) |
| decisions | `decisions`* (ADR index by theme, open decisions D2-D9 folded, the answers files, owner directives by date: this is where the six dated AGENTS.md paragraphs' durable content lands) |
| goals | `goals`* (from AS-D22 Mission Control and Knowledge Services paragraphs and AS-D33 §1.9; thresholds and requirements, never dates; anchors for the `Goal:` line) |

Each concept answers, where it applies, the four levels of §1.3 in that order, and ends with a
"Built / specified / goal" line.

## 3. Formats

**Concept** (`type: Concept`): frontmatter `category` (one of nine), `title`, `description`,
`tags`, `aliases` (2-5), `questions` (≥3; `questions[0]` ≤70 chars, natural agent phrasing; seed
from CONCEPT-LISTS and DOC-08 §g), `updated` (date). ≤160 lines. Explains why, the contract, the
lifecycle and the refusals; cites `file:line`. Snippets (AS-D30): short interface excerpts of
important deep modules, each preceded by its anchor `<!-- snippet: path:start-end -->`; manifest,
YAML and command examples allowed. Entrypoint and file-role inventories go to module `AGENTS.md`,
not concepts. Ends with `## Citations`.

**Research note** (`docs/research/<subject>/<slug>.md`, `type: Research`; Q18 recommendation,
pending owner confirmation): `subject`, `versions` (exact pins it covers), `sources`, `observed`,
`confidence`, `used_by`. Moves in: `runtime-facts/CURSOR_SDK_FACTS.md` → `docs/research/cursor/`,
`EVE_FACTS.md` → `docs/research/eve/`, `docs/research/2026-10-07-coding-lane-surfaces.md` →
`docs/research/coding-lanes/`; write `docs/research/daytona/sandbox-tiers.md` stub from
`application/environments/network.py:31` context (cited by code, currently missing) and
`docs/research/deep-agents/` from the Deep Agents surface notes in the provider packet.

**Retrieval fixtures** (`.sdlc/fixtures/retrieval/`): `queries.json` cases
`{id, kind: "query"|"task", partition: "screening"|"heldout"|"negative", query|task, expect: {concepts[], modules[], research[], facts[]}, critical}`;
`baseline.json` (metrics per partition); T001 verbatim from its file.

## 4. Phases

### Phase A: three Sonnet agents in parallel, disjoint concept sets

Each harvests from `mission-control-general` at `HEAD` (`git show HEAD:<path>`; the working tree
already deleted 86 files) using A-MISSION-CONTROL-GENERAL §2-§3, verifies against code, rewrites
or creates its concepts in §3 format, and fixes the B-report stale/contradicted claims for them.

| Agent | Owns |
| --- | --- |
| A1 workflows | `workflow-systems`, `stage-graph`, `goal-loop`, `parallel-swarm`, `evaluator-optimizer`, `mission-chains`, `output-contracts`, `context-and-continuation` (+ merge), `recursive-composition`, `completion`, `lifecycle`, `revisions`, `interventions`, `human-gates`, `durable-controls`, `mission-manifest`; ADR-0068 draft |
| A2 runtime | the Deep Agents group, `temporal-synthesis`, `lanes-and-harness`, the other lane concepts, `provider-batch`, `session-ownership-and-dispatch`, `recovery`, `precise-fork`, `durable-reactions`, `watchers`, `coordinator-attention`, `placement-admission`, `hook-contributions`, `instruction-layering`, `model-catalog`, `capabilities`, `capability-seeds`; `docs/research/deep-agents/`, `daytona/` |
| A3 platform | boundaries, surfaces, persistence, qualification, operations categories; `decisions`, `goals` |

### Phase B: one Sonnet agent, after A (sequential, touches shared files)

1. **ADRs:** ADR-0068 (from A1's draft); accept 0021, 0035-0050, 0052, 0054-0057 with "accepted
   2026-11-01; implemented by <commit/release>" (hold 0053); superseded markers (0021→0064 and the
   four back-markers); distinct descriptions for 0058-0062.
2. **Delete `mission-control-general/` fully** (after A confirms harvest): `git rm -r`; rewrite
   inbound links repo-wide; `okf_search.py` corpus updated (drop the pack; add `docs/research`;
   active-program specs opt-in flag).
3. **Programs (C report):** archive moves (63 after harvest; fix the 4 code/test/seed path
   references), `NEXT-SESSION.md` split into a ≤150-line live board plus archived batch logs,
   sitting-I/sprint-sequence track retired, D1 overtaken and D2-D9 into `decisions`, `parked`
   status added to `program_ledger.py` and fault tolerance marked parked, ledgers reconciled.
4. **Other surfaces (D report):** 31 archived, 5 deleted, 10 `src/.../mcp` plan files archived
   beside coordinator-surface, `git rm -r --cached .scratch` (no history rewrite), research moves.
5. **AGENTS.md:** replace the root file with the DOC-08 draft updated for this refactor (G1-G16;
   `Authority:` line "code: what runs · ADRs: what was decided · concepts explain both · programs
   are working"; the six dated directive paragraphs replaced by one "current direction" line to the
   Sprint OC ledger). Update `docs/tools/agents_docs_index.py` to render the new block from concept
   frontmatter (`category`, `questions[0]`, pins) so it is the parity target for S1; fold
   `index-notes.toml` content into the hand-written lines or the generator's config.
6. **Fixtures and bench:** write `.sdlc/fixtures/retrieval/queries.json` (≥18 screening, ≥10
   held-out over the concepts, the MC cases among the audit's 34 misses, 5-10 task fixtures
   including T001 and one each for: add a workflow output obligation; inject context into a running
   Goal Loop; fork a Stage Graph at a recorded point; add a model route; wire a new lane adapter);
   run them through `okf_search.py` before (at `HEAD` of today) and after; write `baseline.json`.
7. **Verify:** `python docs/tools/check_docs.py`, `python docs/tools/program_ledger.py check` for
   every touched program, `python docs/tools/agents_docs_index.py --check`, the link checker;
   focused tests for any test file whose hard-coded path changed.

## 5. Acceptance

- `mission-control-general/` absent; no inbound link to it; every harvested item has a home (A §3
  table annotated with its destination in the commit body or the log).
- Every concept has the §3 frontmatter, ≤160 lines, Citations resolving; zero contradicted claims
  from B §2 remain (spot list in the final report).
- `AGENTS.md` ≤14 KiB with the generated block reproduced by `agents_docs_index.py`.
- Bench: T001 concept recall@10 ≥ 0.7 and module recall ≥ 0.5 (modules are reachable only through
  module `AGENTS.md` files until S1 indexes them; report honestly); screening recall@3 reported
  before and after; every critical case listed with pass/fail.
- All checks in Phase B step 7 green; commits pushed only on the owner's instruction.

## 6. Code issues to file (not fixed in this refactor)

Daytona factory missing in `materializer.py`; unshipped describe cells `describe.py:80,113`; four→
three workflow family vocabulary (OC-D204/D205); migration-key reservation rule; MC `interfaces`
inventory generation; BKS Fly executor v2.0.2 vs graph v2.2.0; KS protocol 2.1.0; KS test hygiene.

## 7. Open with the owner before Phase A

- Where the **provider batch prototype and proposal** live (not found in MC files, MC history or
  Linear on 2026-11-01).
- Q18 (research space), Q19 (task fixtures, code entrypoints as documents), Q20 (trace inside
  `context`): this plan assumes the recommendations.
