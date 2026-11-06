# Mission Control
General runtime that admits missions, schedules them on Temporal and runs bounded agent cognition through provider lanes, Deep Agents first, for AI Engineer and Biotech.

## Read before editing
- Report against the [owner goal](../../AGENTS.md#owner-goal-and-reporting-directive-2026-10-29) (Deep Agents workflow and agent configuration). Current direction: the Sprint OC checkpoint in [NEXT-SESSION](docs/specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md); owner directives by date: [decisions](docs/knowledge/decisions.md#owner-directives-by-date).
- Work lands on `main` (`sprint-oc` is a retiring alias kept equal to it since 2026-11-05): check `git status` and `git worktree list --porcelain`; preserve dirty work, ignored `app/personal_code` and retained worktrees.
- Read the closest module `AGENTS.md` (code map) before editing there. Unshaped ideas: `../agentic-sdlc/ideas/`.

<!-- BEGIN:sdlc-infra -->
Data planes, credentials, MCP servers: [workspace registry](../../docs/navigation/DATA-PLANES-AND-CREDENTIALS.md). Tooling: [DEVELOPMENT](docs/DEVELOPMENT.md); API and workers: [operator guide](docs/MISSION_CONTROL_LOCAL_API.md).
`make dev` (compose up, healthy) · `make check` (fast gate) · `make preflight` (read-only installation check).
<!-- END:sdlc-infra -->

## Invariants
- Authority: code: what runs · ADRs: what was decided · concepts explain both · programs are working. Report a conflict; dated specs and `docs/specs/archive` are provenance.
- Temporal alone schedules missions. Deep Agents is bounded operation cognition. Reducers own lifecycle and settlement.
- Accepted command, delivered signal and applied effect are distinct; execution completion is not mission acceptance.
- Domain imports no database, Temporal, FastAPI or provider SDK; adapters implement application ports; bootstrap wires them. One distribution in `src/mission_control`; no `app/` kernel.
- Common SQL lives only in `packages/mission-control-db-contract`, mode `production_common`, no legacy fallback; application PostgreSQL and Temporal persistence stay separate.
- Never invent provider bindings, schemas, grants or model routes.
- Local disposable proof is not a live installation; runtime claims need real local PostgreSQL/Temporal. Report implemented, tested, integrated and qualified apart, and checks as passed, failed, blocked or unrun. Documentation releases no gate.
- Destructive migrations, volume deletion, deployment and paid calls only on an accepted packet's disposable targets within its budget; take a recoverable checkpoint before broad cleanup.
- Use `GLOSSARY.md` terms and honour its Avoid lists.
- Commit when an issue's work is complete and verified; push at gate release and session end (owner rule 2026-10-27).

<!-- BEGIN:sdlc v=0.2.0 src=c96efdf187b9 -->
## Repository guide
General Mission Control runtime and the common database component. Provider consolidation, one provider at a time; Deep Agents is the primary lane and the reference adapter shape (ADR-0005). Not here: application knowledge (`integrations/biotech`, never imported by the kernel), AI Engineer or Biotech schema authority, Knowledge Services internals.

## Knowledge (docs/knowledge, 9 categories)
boundaries:
- mission-control — What does Mission Control own and what does it refuse?
- application-profile — What may differ per application and where is it declared?
- applications — Which application database and graph does a mission use?
- knowledge-services — What does Mission Control own and what does Knowledge Services own?
surfaces:
- more (questions in docs/knowledge/index.md#surfaces): authoring, coordinator-surface, interfaces, mission-stream, selection-workspace, signal-ingress, unit-and-point-joinability, wake-channels
domain-model:
- workflow-systems — Which workflow systems exist and which does the code run?
- stage-graph — How does a Stage Graph release, route and revisit stages?
- goal-loop — What does the built GoalDirected run versus the target Goal Loop?
- parallel-swarm — How does Parallel Swarm run as a Stage Graph profile?
- evaluator-optimizer — How would an Evaluator Optimizer improve one deliverable?
- mission-chains — How does one mission release the next and transfer state?
- output-contracts — How are named output promises submitted, assessed and fulfilled?
- context-and-continuation — How is a Context Packet built and handed to the next stage?
- more (questions in docs/knowledge/index.md#domain-model): completion, durable-controls, events-and-commands, human-gates, interventions, lifecycle, mission-manifest, recursive-composition, revisions
persistence:
- more (questions in docs/knowledge/index.md#persistence): collections-and-current-sets, database-component, persistence, provider-frames-and-transcript, saved-result-settlement, workspace-closure
execution:
- deep-agents-lane — How does the Deep Agents lane materialize and run an agent?
- agent-configuration — How is a Deep Agents node configured, from manifest to sealed binding?
- deep-agents-children — How do a node's children get capabilities and return results?
- temporal-synthesis — How do provider lifecycles run as Temporal workflows over snapshots?
- lanes-and-harness — How does the harness drive a lane turn, and which lanes exist?
- more (questions in docs/knowledge/index.md#execution): capabilities, capability-seeds, coordinator-attention, cross-provider-control, cursor-lane, durable-reactions, hook-contributions, hosted-api-lanes, instruction-layering, model-catalog, placement-admission, precise-fork, provider-batch, provider-lanes, recovery, session-ownership-and-dispatch, watchers
qualification:
- documentation-retrieval-fixtures — How is documentation retrieval measured and gated here?
- evaluator-attempts — Why is an evaluator waiting and how many runs are billed?
- qualification — What do local tests prove, and what is still unproved?
- trusted-judgment — How do judge and auditor verdicts reach KS and get promoted?
operations:
- more (questions in docs/knowledge/index.md#operations): budgets-and-usage, deployment, environment-preparation, environments, operations, owner-prerequisites, owner-probe-bootstrap, secret-broker
decisions:
- decisions — Where is this decided, and which decisions are still open?
goals:
- goals — What is Mission Control for, and what is the nearest goal?
Search: `python docs/tools/okf_search.py "<terms>"` (`--programs` adds active program documents) · retrieval fixtures: `.sdlc/fixtures/retrieval/`

## Code map (read the closest guide before editing)
src/mission_control/adapters/deep_agents — Deep Agents lane (ADR-0005): bounded cognition over LangGraph, never forked
src/mission_control/domain/execution — Provider-neutral operation execution contracts, no I/O
src/mission_control/application/authoring — Mission Manifest compile, submit and start use cases
src/mission_control/application/environments — Environment resolution, preparation gate and network projection
src/mission_control/adapters/temporal — Workflows and activities: mission_run, stagegraph, goal_directed, operation
src/mission_control/application/recovery — Macro snapshots, semantic forks, reconciliation and terminal-evidence adoption
src/mission_control/domain/programs — Pure Stage Graph and GoalDirected interpretation; interpreters propose only
src/mission_control/application/programs — Stage Graph and GoalDirected orchestration use cases over persisted authority
agent_server — LangGraph Agent Server deployment config
deployments — Per-application and per-environment deployment inputs, not code
integrations/biotech — Optional Biotech adapters; the kernel never imports them
packages/mission-control-db-contract — Common SQL, releases and the mission-db admin tool (ADR-0003)
skills — Shipped agent skill bundles with digest manifests
src/mission_control — Runtime layers: contracts, domain, application, adapters, interfaces, bootstrap
src/mission_control/adapters — Concrete I/O behind the application ports
src/mission_control/adapters/agent_server — Hosts the bounded LangGraph graphs of the Agent Server (ADR-0006)
src/mission_control/adapters/capabilities — Capability bundle custody, MCP registry, browser and skill discovery
src/mission_control/adapters/claude — The local claude_agent_sdk lane
src/mission_control/adapters/codex — The codex lane: Codex app-server over stdio on a worker
src/mission_control/adapters/cursor — Cursor lane family (ADR-0030): cursor_local and cursor_cloud
src/mission_control/adapters/postgres — Scoped repositories, immutable content and transaction boundaries
src/mission_control/application — Use cases that map public controls to domain rules behind ports
src/mission_control/application/missions — Mission admission, lifecycle facade, inspection and run retrieval
src/mission_control/application/selection — The Selection Workspace: faceted search and read-only draft check
src/mission_control/bootstrap — Trusted startup and composition
src/mission_control/contracts — Public envelopes: commands, inspection, admission, canonical digests
src/mission_control/domain — Pure rules and decisions with no I/O
src/mission_control/domain/authoring — Mission Manifest, MissionDefinition@1, Environment Kits and the compiler
src/mission_control/domain/frames — Provider Frames, closing facts, usage and Transcript renderers
src/mission_control/interfaces — Transport only: http, cli, mcp and socketio
src/mission_control/interfaces/cli — missionctl: a thin authenticated client, never a second lifecycle authority
src/mission_control/interfaces/http — Typed application-scoped HTTP operations
src/mission_control/interfaces/mcp — Coordinator and operator MCP servers and the governed gateway
tests — Where each kind of proof lives

## Skills
start a session or place a fact: belllabs-method · find or update docs, truth pass: sdlc-docs · assert an MC fact: mission-control-docs · Deep Agents API: deep-agents-core · subagents or HITL: deep-agents-orchestration · unclear provider behaviour: provider-research · design before code: architecture-projection · interview the owner: grill-with-answers · build test-first: tdd · something broken: diagnosing-bugs · edit AGENTS.md or a skill: writing-for-agents
Tracker: Linear overtonbell/OVE, project Mission Control (docs/agents/issue-tracker.md) · labels: docs/agents/triage-labels.md · domain docs: single-context GLOSSARY.md and docs/adr (docs/agents/domain.md)

## Verify
Code: `make check` · `make typecheck` (mypy, authoritative) · `make test-integration` (real PostgreSQL and Temporal) · `uv run --group biotech pytest <selection>` (Biotech-domain tests).
Docs: `make docs-check` (= `python docs/tools/check_docs.py`) · `python docs/tools/agents_docs_index.py --check` · `python docs/tools/bench_retrieval.py --gate`.
<!-- END:sdlc -->

## Programs in flight
<!-- BEGIN:sdlc-programs -->
- [Provider consolidation](docs/specs/provider-consolidation-2026-10/LEDGER.md) — next: Sprint OC W1: AI Engineer rerun, then Biotech ([NEXT-SESSION](docs/specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md)); record: [Deep Agents CHANGES](docs/specs/provider-consolidation-2026-10/providers/deep_agents/CHANGES.md)
- [Agentic SDLC](docs/specs/agentic-sdlc-2026-11/LEDGER.md) — next: beside Sprint OC: KS truth pass, BKS, AIDB, then S1 ([handoff](docs/specs/agentic-sdlc-2026-11/HANDOFF-2026-11-02.md))
- [Coordinator surface](docs/specs/coordinator-surface-2026-10/LEDGER.md) — next: owner reads the proposal beyond the shipped OVE-182 part
- [Proposals (unbuilt)](docs/specs/proposals-2026-10/LEDGER.md) — next: owner interview per proposal before building (provider batch, human review loop, next-stage contracts)
Parked (resumes on owner request): [Fault tolerance](docs/specs/fault-tolerance-2026-10/LEDGER.md).
<!-- END:sdlc-programs -->
