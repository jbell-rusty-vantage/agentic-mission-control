---
type: Working Draft
title: "Mission Control AGENTS.md, compressed by hand under the DOC-02 grammar (sitting II input)"
description: "Best-effort input for sitting II of the Agentic SDLC program, written 2026-11-01. The proposed compressed root AGENTS.md for Mission Control, built by hand from the 29,624-byte file of 2026-11-01 under the DOC-02 grammar; measured byte counts per section against the budgets; where each removed line went; two worked module-level blocks (Deep Agents lane adapter, domain); and the grammar problems found while applying it, written as edits proposed to DOC-02. Nothing here changes the live AGENTS.md."
tags: [mission-control, agents, sdlc, agents-md, draft]
date: 2026-11-01
status: draft
---

# Mission Control AGENTS.md, compressed under the DOC-02 grammar

This draft applies [DOC-02](AGENTS-MD-GRAMMAR-DRAFT-2026-11-01.md) to today's root
[`AGENTS.md`](../../../AGENTS.md) (29,624 bytes, sprint-oc, 2026-11-01). It feeds Q12 to Q14 of
[the sitting II interview](INTERVIEW-NAVIGATION-AND-KNOWLEDGE-2026-11-02.md). It shows the target
the S1 CLI would generate, written by hand: concept `category`/`questions` and `.sdlc/*.json` do
not exist yet. Every `questions[0]` line below is drafted here as a proposal for the concept's
frontmatter. The [writing-for-agents](../../../.agents/skills/writing-for-agents/SKILL.md) skill
sets the pruning test: a line stays in the root only if every branch needs it on every turn.

**Progress toward the workspace goal.** This work does not change the runtime. It makes Deep
Agents workflow and agent configuration material reachable in one hop from the root. That
material is the `adapters/deep_agents` code-map line, the `deep-agents-lane`,
`deep-agents-turn-stops` and `agent-configuration` knowledge entries, the two Deep Agents
skills, and the lane's change ledger in the programs list. It also cuts the per-turn load from 29,624 to 10,460 bytes. The largest cuts are 19,522
bytes of directory index and 5,736 bytes of dated session direction. The Sprint OC W1
checkpoint is unchanged.

**Cutover prerequisites.** The proposed file is only valid once these exist. Until then it
would contain dangling pointers:

1. `docs/INFRASTRUCTURE.md`, generated from `.sdlc/infrastructure.json`.
2. `category` and `questions` in all 64 concepts.
3. `#category` anchors in `docs/knowledge/index.md`.
4. A `modules.json` entry and generated `AGENTS.md` for `adapters/agent_server`.
5. The `decisions` and `goals` concepts (DOC-01).

## (c) The proposed root AGENTS.md

````markdown
# Mission Control
General runtime that admits missions, schedules them on Temporal and runs bounded agent cognition through provider lanes, Deep Agents first, for AI Engineer and Biotech.

## Read before editing
- Report against the [owner goal](../../AGENTS.md#owner-goal-and-reporting-directive-2026-10-29) (Deep Agents workflow and agent configuration); the nearest checkpoint is [NEXT-SESSION](docs/specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md).
- Work lands on `sprint-oc`: check `git status` and `git worktree list --porcelain`; preserve dirty work, ignored `app/personal_code` and retained worktrees.
- Read the closest module `AGENTS.md` (code map) before editing there.
- Unshaped ideas: `../agentic-sdlc/ideas/` (README).

<!-- BEGIN:sdlc-infra -->
Data planes, remotes, secrets, Linear, local services, cloud environments, MCP servers: [docs/INFRASTRUCTURE.md](docs/INFRASTRUCTURE.md).
Most used: `make dev` (compose up, healthy) · `make check` (fast gate) · `make preflight` (read-only installation check).
<!-- END:sdlc-infra -->

## Invariants
- Authority on conflict: [spec pack](mission-control-general/general-mission-control/SPECIFICATION.md) > `docs/adr` > `docs/knowledge` > implementation status; report the conflict. Dated specs and `docs/specs/archive` are provenance.
- Temporal alone schedules missions. Deep Agents is bounded operation cognition. Reducers own lifecycle and settlement.
- Accepted command, delivered signal and applied effect are distinct; execution completion is not mission acceptance.
- Domain imports no database, Temporal, FastAPI or provider SDK; adapters implement application ports; bootstrap wires them. One distribution in `src/mission_control`; no `app/` kernel.
- Common SQL lives only in `packages/mission-control-db-contract`, mode `production_common`, no legacy fallback; application PostgreSQL and Temporal persistence stay separate.
- Never invent provider bindings, schemas, grants or model routes.
- Local disposable proof is not a live installation; runtime claims need real local PostgreSQL/Temporal. Report implemented, tested and qualified apart, and checks as passed, failed, blocked or unrun. Documentation releases no gate.
- Destructive migrations, volume deletion, deployment and paid calls only on an accepted packet's disposable targets within its budget; take a recoverable checkpoint before broad cleanup.
- Use `GLOSSARY.md` terms and honour its Avoid lists.
- Commit when an issue's work is complete and verified; push at gate release and session end (owner rule 2026-10-27).

<!-- BEGIN:sdlc v=0.1.0 built=2026-11-01 src=<config digest> -->
## Repository guide
General Mission Control runtime and the common database component. Lifecycle: provider consolidation, one provider at a time; Deep Agents is the only qualified lane. Not here: application knowledge (`integrations/biotech`, never imported by the kernel), AI Engineer or Biotech schema authority, Knowledge Services internals.

## Knowledge (docs/knowledge, 9 categories)
boundaries:
- architecture — Which layer owns what, and what may each layer import?
- knowledge-services — Which knowledge contracts are shared and which stay app-owned?
- application-profile — What may differ per application, and where is it declared?
surfaces:
- interfaces — Which HTTP routes, missionctl groups and MCP tools exist today?
- mission-stream — How does a client follow a mission over Socket.IO?
- wake-channels — How is an orchestrating agent woken by its coordinator inbox?
- signal-ingress — How do signals, webhooks and uploads enter, at which trust tier?
- authoring — How does a mission go from description to an explicit start?
- capabilities — What may a mission bind, and how is it projected per lane?
- capability-seeds — Which MCP servers, skill bundles and hooks do the seeds admit?
- agent-configuration — How does a manifest select Deep Agents features and model tools?
- selection-workspace — How does a coordinator search and check a lane/model selection?
- model-catalog — Where are model profiles declared and how are routes resolved?
domain-model:
- mission-manifest — What does a Mission Manifest contain and how is it compiled?
- lifecycle — How do scope, immutable admission and command effects connect?
- revisions — How does a definition become a revision, and how does the head move?
- mission-chains — How do linked missions compile and release each other?
- completion — Why are completion, acceptance and admission different facts?
- output-contracts — How are output promises submitted, assessed and fulfilled?
- human-gates — How does a Human Gate run and resolve its human task?
- interventions — How are queue, inject, interrupt, cancel and continue delivered?
- workflow-systems — How do the four workflow systems compose one program?
- events-and-commands — How do events leave the ledger and commands get receipts?
- recursive-composition — How does a Goal Loop nest in a Stage Graph, and back?
- durable-controls — How do Event Wait, Timer and gates hold a wait as nodes?
persistence:
- persistence — Who owns the common SQL, which release, live or disposable?
- collections-and-current-sets — How is a collection judged and its accepted set kept?
- workspace-closure — Which files could the agent see when an attempt settled?
- saved-result-settlement — How is a provider result saved and settled without a rerun?
- provider-frames-and-transcript — Where are native provider frames kept, and what derives?
- transcript-projection — How is the transcript v2 read model persisted and paged?
- unit-and-point-joinability — How do events and frames name their unit and point?
execution: deep-agents-lane, deep-agents-turn-stops, lanes-and-harness … (+18; see docs/knowledge/index.md#execution)
qualification:
- qualification — What do local tests prove, and what is unproved per lane?
- release-and-qualification — Which proof statuses and gates exist, and what is live?
- evaluator-attempts — How is each evaluator run, bounded and recovered?
- trusted-judgment — How do judge and auditor calls reach KS sealing and review?
operations:
- operations — How do API, worker and Agent Server start without fake readiness?
- environments — What does a mission environment declare, and what may widen?
- environment-preparation — How are Environment Kits provisioned and readiness kept?
- secret-broker — How do secrets reach a lane without entering prompts or git?
- budgets-and-usage — How is a run's budget reserved, enforced and settled?
- owner-prerequisites — Which human-only steps must precede a lane spawn?
- owner-probe-bootstrap — How are credentials probed before hosted admission?
decisions: pending `decisions.md` (DOC-01); until then docs/adr and sprint-oc/DECISIONS.md
goals: pending `goals.md` (DOC-01); until then the owner goal linked above
Search: node .sdlc/cli.mjs search "<terms>" · context "<question>"

## Code map
src/mission_control → src/mission_control/AGENTS.md — runtime layout; request to settlement
src/mission_control/contracts → src/mission_control/contracts/AGENTS.md — public envelopes and canonical digests
src/mission_control/domain → src/mission_control/domain/AGENTS.md — pure rules: programs, execution, authoring, context
src/mission_control/application → src/mission_control/application/AGENTS.md — use cases: missions, execution, programs, recovery
src/mission_control/adapters → src/mission_control/adapters/AGENTS.md — concrete I/O behind ports, one directory per lane or store
src/mission_control/adapters/deep_agents → src/mission_control/adapters/deep_agents/AGENTS.md — the Deep Agents lane (ADR-0005)
src/mission_control/adapters/agent_server → src/mission_control/adapters/agent_server/AGENTS.md — hosted graphs for Deep Agents async children
src/mission_control/adapters/temporal → src/mission_control/adapters/temporal/AGENTS.md — workflows and activities: mission_run, stagegraph, goal_directed
src/mission_control/adapters/postgres → src/mission_control/adapters/postgres/AGENTS.md — scoped repositories, immutable content, app migrations
src/mission_control/interfaces → src/mission_control/interfaces/AGENTS.md — transport only: http, cli, mcp, socketio
src/mission_control/bootstrap → src/mission_control/bootstrap/AGENTS.md — trusted startup, preflight, composition
packages/mission-control-db-contract → packages/mission-control-db-contract/AGENTS.md — common SQL, releases, mission-db
integrations/biotech → integrations/biotech/AGENTS.md — optional Biotech adapters; the kernel never imports them
tests → tests/AGENTS.md — unit, integration, conformance, acceptance: where each proof lives

## Skills
start a session or place a fact: belllabs-method · assert an MC fact: mission-control-docs · Deep Agents API: deep-agents-core · subagents or HITL: deep-agents-orchestration · unclear provider behaviour: provider-research · design before code: architecture-projection · interview the owner: grill-with-answers · build test-first: tdd · something broken: diagnosing-bugs · edit AGENTS.md or a skill: writing-for-agents
Tracker: Linear overtonbell/OVE, project Mission Control (docs/agents/issue-tracker.md) · labels: docs/agents/triage-labels.md · domain docs: single-context GLOSSARY.md and docs/adr (docs/agents/domain.md)

## Verify
make check · make typecheck (mypy, authoritative) · make test-integration (real PostgreSQL/Temporal) · uv run --group biotech pytest <selection> (Biotech-domain tests)
node .sdlc/cli.mjs check · build · bench --gate · drift (until S1: make docs-check)
<!-- END:sdlc -->

## Programs in flight
<!-- BEGIN:sdlc-programs -->
- [Provider consolidation](docs/specs/provider-consolidation-2026-10/LEDGER.md) — next: Sprint OC W1 checkpoint ([NEXT-SESSION](docs/specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md)); Deep Agents lane record: [CHANGES](docs/specs/provider-consolidation-2026-10/providers/deep_agents/CHANGES.md)
- [Agentic SDLC](docs/specs/agentic-sdlc-2026-11/LEDGER.md) — next: SESSION-NAVIGATION-QUALITY, then slice S1; merges before Sprint OC resumes
- [Coordinator surface](docs/specs/coordinator-surface-2026-10/LEDGER.md) — next: owner reads the proposal (round R8)
- [Fault tolerance](docs/specs/fault-tolerance-2026-10/LEDGER.md) — next: owner answers FT-D1..D22
<!-- END:sdlc-programs -->
````

## (d) Byte counts against the budget

Measured with `wc -c` on the fenced text above after extraction. LF line endings, UTF-8, so
`—` counts 3 bytes and `·` and `→` count 2 and 3. Each section count includes its trailing
blank line.

| § | Section | Kind | Bytes | DOC-02 budget | Result |
| --- | --- | --- | ---: | ---: | --- |
| 1 | Title and purpose | hand | 188 | 200 | within |
| 2 | Read before editing | hand | 562 | 600 | within |
| 3 | Infrastructure pointer and three commands | generated | 312 | 400 | within |
| 4 | Invariants (10 lines) | hand | 1,509 | 3,072 | within |
| 5 | `sdlc` block, markers included | generated | 7,130 | 8,192 | within |
| 5a | Repository guide | generated | 346 | none | |
| 5b | Knowledge index: 43 full lines, execution collapsed, 2 pending | generated | 4,004 | none | |
| 5c | Code map (14 modules) | generated | 1,783 | none | |
| 5d | Skills (10 triggers) and tracker | generated | 646 | none | |
| 5e | Verify | generated | 268 | none | |
| 6 | Programs in flight (4 active ledgers) | generated | 756 | 1,024 | within |
| | **Hand-written total (1+2+4)** | | **2,259** | **4,096** | within |
| | **All generated text (3+5+6)** | | **8,198** | **8,192?** | **over by 6** if "generated ≤ 8 KiB" covers 3 and 6 as well as 5 (see G2) |
| | **Whole file** | | **10,460** | **14,336** | within; DOC-02 §7 estimated 11-13 KiB |

The same measurements for alternatives that sitting II should weigh (see G3 and G4):

| Variant | `sdlc` block |
| --- | ---: |
| A. As above (literal collapse: three names plus `(+18 …)`) | 7,130 |
| B. Execution expanded to 21 full lines, code map without the redundant `→ <dir>/AGENTS.md` | 8,162 |
| C. Execution expanded, code map unchanged | 8,780 (over) |
| D. Names-only collapse (all 21 names, no questions), code map unchanged | 7,479 |
| E. D plus code map without the redundant target | 6,861 |

## (e) Where every removed line went

Line numbers refer to today's `AGENTS.md`. **Kept** means the fact is in the proposed root,
possibly compressed. **Moved** means the target already holds the fact today. **Gap** means
the target does not hold it yet and needs a one-line addition at cutover. **Dropped** means it
is reachable by lookup or no longer true.

| Today (lines, bytes) | Content | Disposition | Where it is now |
| --- | --- | --- | --- |
| L1 | Title | kept | `# Mission Control` and the purpose line |
| L3-5 | Sequencing clarification 2026-10-31 (W0/W1 may run before cloud setup) | moved | provider-consolidation `LEDGER.md` L10-12 and `sprint-oc/NEXT-SESSION.md`, both verbatim; the programs line points at both |
| L7-15 | Current owner direction 2026-10-31 and the cloud/Deep Agents deployment roadmap link | moved | `LEDGER.md` L14-18 and `NEXT-SESSION.md`, both linking `CLOUD-ENVIRONMENTS-AND-DEEP-AGENTS-DEPLOYMENT-2026-10-31.md` |
| L17-26 | Completed Qualia fixture focus: USD 100 GPT-6.1 authority, bounded writes to Aura `8032ec07`, Tavily fork | moved, and deliberately removed from the root | `NEXT-SESSION.md`, which owns proof status (`8032ec07` and `USD 100` both there). The authority was assignment-scoped and the assignment is complete. Left in a per-turn file, an agent can read it as a standing authorization. |
| L28-34 | Qualia assignment completed 2026-10-31; private `.scratch/qualia-stagegraph-2026-10-30/READ-FIRST.md` | moved | `NEXT-SESSION.md` L64-66 |
| L36 | BellLabs owner goal and reporting directive | kept | Read-before bullet 1 (the link carries the full text) |
| L38 | Sprint OC direction OC-D208: fixtures, Astra/Sol, recovery audit, no per-batch pause | moved | `NEXT-SESSION.md` (OC-D208 twice, `SESSION-OVERNIGHT`, `RECOVERY-AUDIT`). Its clause that paid calls, remote operations and push stay controlled is now invariant 8. |
| L40-41 | Preparation snapshot 2026-10-26 (OVE-162, KICKOFF) | moved | `LEDGER.md` "Preparation entry" L35-40, marked historical there |
| L43 | Application ports and schema routes for integration work | moved | `docs/knowledge/index.md` already links `APPLICATION-PORTS.md`; also covered by the `knowledge-services` and `application-profile` index lines |
| L46-47 | Spec pack first, then annexes and the closest scoped `AGENTS.md` | kept | Invariant 1 (spec pack link and precedence); read-before bullet 3 |
| L48 | Knowledge navigation | kept | `## Knowledge` header of the block |
| L49 | Removal guide | dropped from root | `docs/README.md` L12 links it. Recovering moved paths is a lookup, not a per-turn need. |
| L51 | Sprint V `START-HERE` repository/database navigation | **gap** | No concept cites it today. Add one Citations line to `persistence.md` at cutover. |
| L53-66 (956 B) | Work by concern, 10 rows | moved | Code map lines and module blocks. Row 1: `interfaces`, `bootstrap`. Rows 2 and 5: `application` (its module block names `missions`, `execution`, `recovery`). Row 3: the `domain` block (`programs/`, worked in f). Row 4: `temporal`. Row 6: `postgres`. Row 7: `db-contract` line; `deployments/<app>` is in `application-profile`, which cites it 4 times. Row 8: `adapters`, `deep_agents`. Row 9: the `integrations/biotech` line and the guide's "Not here". Row 10: `bootstrap`. DOC-02 §7 sends this table to `architecture.md`. I recommend against that: the table would duplicate the code map. |
| L70-73 | Layering; one distribution; no `app/` kernel | kept | Invariant 4 |
| L75-77 | Temporal schedules; Deep Agents is bounded cognition; reducers settle; command ≠ signal ≠ effect; completion ≠ acceptance | kept | Invariants 2 and 3 |
| L79-82 | Separate persistence; common SQL in db-contract; `production_common`; disposable ≠ live; invent nothing | kept | Invariants 5, 6 and 7 |
| L84-85 | Preserve dirty work and ignored `app/personal_code`; recoverable checkpoints | kept | Read-before bullet 2; invariant 8 (checkpoint) |
| L85-87 | Commit and push rule; no live destructive or paid work outside packet targets and budget | kept | Invariants 10 and 8 |
| L88 | Historical WPs and specs are provenance | kept | Invariant 1 |
| L92-95 | `make check` composition; mypy authoritative; `--group biotech` | kept / dropped | Verify line keeps mypy-authoritative and the biotech group. The composition of `make check` is dropped because `make help` prints it (an environment lookup). |
| L96 | `docs/DEVELOPMENT.md` | moved | `INFRASTRUCTURE.md` owner-doc column (Local services row). The `mission-control-local-setup` skill does not cite it today. |
| L97-98 | Real PostgreSQL/Temporal for runtime claims; report passed, failed, blocked and unrun | kept | Invariant 7 |
| L99 | Operator guide `MISSION_CONTROL_LOCAL_API.md` | moved | `operations.md` already cites it; also the `INFRASTRUCTURE.md` Local services row |
| L103-108 | Method: `belllabs-method`; `check_docs.py` | kept | Skills line 1; Verify (`make docs-check` runs `check_docs.py`) |
| L110-113 | Linear `overtonbell` / `OVE` / Mission Control; `.scratch/<feature>/` brainstorms promoted with Provenance | kept / moved | Tracker line; the Provenance rule is in `docs/agents/issue-tracker.md` L39-44. **Load-bearing:** `to-tickets`, `to-spec` and `triage` say the tracker "should have been provided to you", so this line must stay in the root (G7). |
| L115-117 | Triage labels | kept | Tracker line |
| L119-121 | Domain docs: single-context `GLOSSARY.md` and `docs/adr` | kept | Tracker line; invariant 9 (Avoid lists) |
| L123-127 | Five documentation surfaces; upstream skill sync | moved | The `belllabs-method` skill cites `documentation-surfaces.md` and `matt-pocock-skills.md` |
| L129-133 | Program ledgers convention; provider-consolidation ledger | moved | `belllabs-method` cites `program-workspace.md`; the four ledgers are in Programs in flight |
| L137-138 | "Generated by `agents_docs_index.py`; do not edit" | replaced | The `<!-- BEGIN:sdlc v= built= src= -->` header (DOC-02 §6 rule 6) |
| L142 index | Root note; the spec pack is normative | kept | Invariant 1 |
| L143 index | "IMPORTANT: prefer retrieval-led reasoning" | kept | Skills: "assert an MC fact: mission-control-docs"; that skill's description carries the rule |
| L144 index | `okf_search.py` | replaced | The `Search:` line (S1 CLI). Until S1, `python docs/tools/okf_search.py` stays the command. |
| L145 index | Precedence on conflict | kept | Invariant 1 |
| L146 index | `GLOSSARY.md`: use its terms, honour Avoid lists | kept | Invariant 9 |
| L147 index | Programs are read through `LEDGER.md`; archive not indexed | moved | Programs in flight lists ledgers only; `program-workspace.md` |
| L148 index | 13 subsystem `AGENTS.md` notes | kept | Code map (14 lines; adds `adapters/agent_server`) |
| L149 index (3,943 B) | 66 ADR slugs | moved | The `decisions` concept (pending, DOC-01) and `search`. ADR-0005 is named in the code map. Until `decisions.md` exists the index line points to `docs/adr`; listing the directory is an environment lookup. |
| L150 index (3,372 B) | 66 concept titles cut to 44 chars | replaced | `## Knowledge`: 43 question lines, execution collapsed (21), `index` and `log` excluded |
| L151 index | `docs/agents` files | kept | Tracker line and `belllabs-method` |
| L152 index | `docs/research` | dropped from root | Reached through ADR citations and `search` |
| L153-157 index | Program folders, including `sprint-oc` (18 files) and `providers/deep_agents` (11 files) | moved | Programs in flight, ledger first. The Deep Agents lane record (`CHANGES.md`) is linked on the provider-consolidation line. `DESIGN.md` is behind the module block's proposed `Program:` slot (G6). |
| L158 index | `docs/` operator guides and implementation status | moved | `INFRASTRUCTURE.md` owner docs (`DEVELOPMENT`, `MISSION_CONTROL_LOCAL_API`, `WSL2_WORKER_RUNBOOK`, `DEPLOYMENT_OPTIONS`); implementation status in invariant 1 |
| L159 index | Spec pack files | kept / dropped | `SPECIFICATION.md` linked in invariant 1. The other 11 files are reached from it and the pack README. |
| L160 index | `expansion/` packet | dropped from root | It supports the spec and is not normative; the pack README links it |
| L161 index | `workflow-types/` annexes | moved | `workflow-systems.md` cites the annexes 7 times |
| L162 index | `runtime-facts/` (Cursor SDK, Eve) | **gap** | `cursor-lane.md` does not cite `CURSOR_SDK_FACTS.md` today. Add a citation at cutover. |
| L163 index | Archive | dropped from root | `docs/specs/archive/README.md` |
| L164 index | Expansion issue views | dropped | Statuses stale since 2026-10-03; not the tracker |
| absent today | `docs/specs/agentic-sdlc-2026-11` | newly visible | `index-notes.toml` has its note, but `agents_docs_index.py` hard-codes `GROUPS`, so the program never appears in today's index (`--check` reports the block "current"). The programs line derives from ledger status instead (DOC-02 §6 rule 7). |

## (f) Two worked module-level blocks

Both follow DOC-02 §3 exactly. Facts are from source on 2026-11-01. Imports were found by
grep. Prose mentions in docstrings are excluded.

### `src/mission_control/adapters/deep_agents/AGENTS.md` (block 1,288 bytes, budget 2,048)

```text
<!-- BEGIN:sdlc-module id=adapters.deep_agents -->
# Deep Agents lane adapter
The first and only qualified execution lane (ADR-0005): bounded operation cognition on deepagents 0.7.5 over LangGraph 1.2.10, extended through public interfaces, never forked. It executes what the binding pins and schedules nothing.
Entrypoints: compile.py (DeepAgentsCompileAdapter), lane.py, binding.py, describe.py, harness.py, adapter.py, materializer.py, routes.py, features/ · Tests: tests/unit/deep_agents, tests/integration/deep_agents, tests/conformance/lanes · Owner of: never choose a model, tool or skill the binding did not name; model clients and credentials stay server-side, never in prompts, files, checkpoints or artifacts; an uncertain provider state is reconciled, never relaunched; native messages and checkpoints are recovery state, not mission truth
Explained by: docs/knowledge/deep-agents-lane.md, agent-configuration.md, deep-agents-turn-stops.md, async-children.md, workspace-closure.md, lanes-and-harness.md · Decided by: ADR-0004, ADR-0005, ADR-0006, ADR-0007, ADR-0063
Depends on: domain, application, contracts, adapters.capabilities · Used by: bootstrap, adapters.temporal, adapters.agent_server, application.execution.harness (describe data only)
<!-- END:sdlc-module -->
```

Notes:

- Today's hand-written file (2,627 bytes) has a "Where things are" table. It would stay
  above the marker, which puts the file at about 3.9 KB (G5).
- `application/execution/harness/describe.py` imports `adapters.deep_agents.describe`. That
  is an application → adapter edge. The adapter's own guide calls it "pure data the application
  aggregates", so the block records it rather than hiding it. Whether `test-arch` should allow
  it is a separate question.
- The verify text in today's file has no slot in §3 (G6): "`uv run pytest
  tests/integration/deep_agents` needs the real stack; paid calls need authorization".

### `src/mission_control/domain/AGENTS.md` (block 1,130 bytes, budget 2,048)

```text
<!-- BEGIN:sdlc-module id=domain -->
# Domain: pure rules and decisions
Family interpretation (programs), operation and run invariants (execution), immutable definitions and compilation (authoring), delegated run contracts (composition), the Context Packet and packer (context), and the pure rules for capabilities, resolution, outputs and reactions.
Entrypoints: programs/, execution/, authoring/, composition/, context/, resolution/ · Tests: tests/unit/{orchestration,run_control,operations,control_plane,domain}, tests/architecture/test_package_boundaries.py · Owner of: imports only mission_control.contracts and itself (no Temporal, database, FastAPI or provider SDK); interpreters propose, reducers authorize and terminalize; policies are explicit admitted inputs; determinism and immutable content identity hold across retries and forks
Explained by: docs/knowledge/architecture.md, execution.md, workflow-systems.md, context-and-continuation.md, completion.md, revisions.md · Decided by: ADR-0001, ADR-0010, ADR-0027, ADR-0063
Depends on: contracts · Used by: application, adapters, bootstrap
<!-- END:sdlc-module -->
```

Notes:

- This block replaces today's 773-byte hand-written file completely.
- Verified: domain imports only `mission_control.domain` (384) and `mission_control.contracts`
  (6).
- Row 3 of "Work by concern" ("StageGraph or GoalDirected decisions") lands here as
  `programs/`.

## (g) Grammar problems found, as proposed edits to DOC-02

| # | Problem met while applying | Proposed edit to DOC-02 |
| --- | --- | --- |
| G1 | §1 5b says "one line per concept", §2's example puts a whole category on one line joined by `·`, and §7 says "9 category lines". The draft uses one line per concept under a category label. | §2: "A category label line, then one `- name — question` line per concept". Drop the `·`-joined example. |
| G2 | The budget line says "generated block ≤ 8 KiB". Sections 3 and 6 are also generated and have their own caps. Counted together, all generated text is 8,198 B, 6 over. | §1: "the `sdlc` block (5) ≤ 8 KiB; sections 3 and 6 have their own caps and do not count toward it." State the sum of all caps (13,488 B) beside the 14 KiB whole-file cap. |
| G3 | The collapse rule `name, name, name … (+n)` is ambiguous (which three?), and it hides 18 of 21 execution concepts. Those include `async-children`, `recovery` and `precise-fork`, which a Deep Agents task needs. | Replace with names-only collapse: every name, no questions, one line, with `questions in index.md#<category>` (variant D, +349 B). Order within a category by `config.json` `pin` first, then alphabetically. Pin `deep-agents-lane`, `deep-agents-turn-stops`, `async-children` and `agent-configuration`, so the provider the owner prioritizes always appears first. |
| G4 | The code map's `dir → dir/AGENTS.md — line` repeats the path; the target is always `<dir>/AGENTS.md` (618 B over 14 lines). | §2: `<dir> — <one line>`, target implied. With G3 the whole knowledge index could then be expanded (variant B, 8,162 B) or kept collapsed with headroom (variant E, 6,861 B). |
| G5 | §3 sets "budget ≤ 2 KiB" without saying whether it covers the block or the file. The Deep Agents file has a 2,627 B hand-written table above the marker. | §3: "the block ≤ 2 KiB; hand-written text above it ≤ 2 KiB; `check` names the larger." Hand-written "where things are" tables move into the block as an `Entrypoints:` list over time. |
| G6 | §3 has no slot for verify commands (real stack, paid-call authorization) or for the program record that governs the module (`providers/deep_agents/CHANGES.md`, `DESIGN.md`). | Add `Verify: <commands>` and `Program: <ledger or change record>` lines, both from `modules.json`. Without `Program:`, Deep Agents design is two hops from the root. |
| G7 | No home for the tracker, label and domain-doc configuration. `to-tickets`, `to-spec` and `triage` expect it to be "provided to you" via the `## Agent skills` section. `setup-matt-pocock-skills` would re-add that section outside the markers. | §2 5d: a generated `Tracker:` line from `config.linear` and `config.docs`. Document that `setup-matt-pocock-skills` must not be re-run after cutover (or teach it the marker). |
| G8 | No home for authority and precedence: the spec pack is normative; `docs/adr` > `docs/knowledge` > status. Today it lives in the index header. | §1 item 4: "Invariants begin with the authority line". Or §2 5a: guide carries `Authority: <precedence>` from `config.rules`. |
| G9 | 5e conflates two kinds of verification. The repo's code gates (`make check`, mypy authoritative, the biotech test group) differ from the sdlc commands. §2 shows only the latter. | 5e: `config.verify.code[]` and `config.verify.docs[]`, rendered as two lines. |
| G10 | Sections 3 and 6 are generated but have no markers, so `build` cannot splice them and `check` cannot detect a hand edit. | Markers `<!-- BEGIN:sdlc-infra -->` and `<!-- BEGIN:sdlc-programs -->` (used above), digests included in the §6 rule 6 staleness check. |
| G11 | The grammar has no form for a mandatory category whose concept is not written yet (`decisions`, `goals`). `n/a` would be false. | Add `<category>: pending <file> (<source>); until then <pointer>`. `check` warns, and fails after a date set in `config.json`. |
| G12 | Index lines derive from `questions[0]`, but no concept has `questions` or `category` today. The 64 lines here are drafted. | Make the field migration a slice step: S1 `build` refuses to emit the index until every concept has both fields. The 43 drafted questions above, plus the 21 execution drafts below, seed it. |
| G13 | A program that owns a lane record (`deep_agents/CHANGES.md`) needs one more pointer than "ledger link, next step" allows; the 1 KiB cap has room for it (756 B used). | §1 item 6: "ledger link, next step, and at most one `record:` link from the ledger's frontmatter". |
| G14 | Read-before-editing at 600 B fits four bullets, not six. The directive, branch, worktree and dirty-work checks and the ideas pointer compete. | Keep 600 B. Fold "read the closest module `AGENTS.md`" into the code map heading, which frees a bullet. |
| G15 | The 4 KiB hand-written cap is far above need (2,259 B used). SPEC-01 §12 item 7 recommends 12 KiB, which contradicts DOC-02 §1's 4 KiB. | Settle at 4 KiB (DOC-02) and strike SPEC-01 §12 item 7's 12 KiB. Unused cap invites sediment. |
| G16 | `agents_docs_index.py` hard-codes `GROUPS`, so a new program (agentic-sdlc) is invisible while `--check` passes. | §6 rule 7 already fixes this by deriving from ledger status. Add a `check` rule: every `docs/specs/*/LEDGER.md` with status Active appears in section 6. |

### Draft `questions[0]` for the collapsed execution concepts (seed for G12)

```text
execution — How do StageGraph and GoalDirected share Temporal and settlement?
deep-agents-lane — How is the Deep Agents lane compiled, materialized and observed?
deep-agents-turn-stops — When does a Deep Agents turn stop, and what is captured?
async-children — How does a Deep Agents async child run from its sealed binding?
lanes-and-harness — What is the harness protocol and how does lane.turn drive a lane?
session-ownership-and-dispatch — How is a native session fenced and each dispatch journaled?
context-and-continuation — How does a Context Packet carry state across handoffs?
continuation-checkpoint — How is a continuation checkpoint sealed and transferred?
recovery — How do snapshots, forks and reconciliation keep lineage intact?
precise-fork — How does a fork name its position and build its seed head?
durable-reactions — How is a reaction to a transition captured and dispatched?
watchers — How do declared watchers compile and fire admitted commands?
coordinator-attention — How is a coordinator notice delivered, acked and retrieved?
placement-admission — How is provider capacity reserved before sealing?
hook-contributions — How do hook scripts read scopes and install candidates safely?
instruction-layering — How does a lane merge its projection into a repo's AGENTS.md?
cursor-lane — How do the cursor_local and cursor_cloud lanes run and fork?
provider-lanes — How do the Claude Agent SDK and Codex local lanes run?
hosted-api-lanes — How do Managed Agents and Codex Agents lanes run and publish?
parallel-swarm — How would a swarm count accepted peers and converge?
evaluator-optimizer — How would bounded evaluation rounds improve one deliverable?
```

### Category placement departures from DOC-01

- `provider-lanes` and `interfaces` are listed under `boundaries` in DOC-01. Here they sit in
  `execution` and `surfaces`, because a concept takes one category.
- `durable-controls` moves to `domain-model` (it defines program nodes).
- `agent-configuration` stays in `surfaces`, as DOC-01 places it. It is the manifest spelling
  that selects Deep Agents features.
- `application-profile` joins `boundaries`.
- With these placements, only `execution` exceeds twelve concepts.
