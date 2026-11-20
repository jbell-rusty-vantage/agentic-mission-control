# Mission Control
General runtime that admits missions, schedules them on Temporal and runs bounded agent cognition through provider lanes, Deep Agents first, for AI Engineer and Biotech.

## Read before editing
- Report against the [owner goal](../../AGENTS.md#owner-goal-and-reporting-directive-2026-10-29) (Deep Agents workflow and agent configuration). Current direction: the Sprint OC checkpoint in [NEXT-SESSION](docs/specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md); owner directives by date: [decisions](docs/knowledge/decisions.md#owner-directives-by-date).
- Work lands on `main`, the only branch; check `git status` and `git worktree list --porcelain` and preserve dirty work and ignored `app/personal_code`. History starts at the 2026-11-06 clean-slate baseline on the jbell-rusty-vantage account; commit IDs in older docs are dated labels to re-verify against live source ([repository history](docs/REPOSITORY-HISTORY.md)).
- Read the closest module `AGENTS.md` before editing there ([code map](docs/CODE-MAP.md)). Unshaped ideas: tell the owner; the old `agentic-sdlc/ideas/` workspace was deleted on 2026-11-17 (AS-D65).

## Commands
- `./dev status` to orient (JSON) · `./dev check` before finishing (`./dev planes check` plus `make check`; `--full` is CI plus provenance) · `./dev trace check` for provenance gaps.
- `./dev db status|schema|query --plane P` reads one named data plane in a read-only session; `./dev planes list|show|check` shows the registry [config/planes.toml](config/planes.toml) (identities and credential names, never values).
<!-- BEGIN:sdlc-infra -->
Data planes, credentials, MCP servers: [workspace registry](../../docs/navigation/DATA-PLANES-AND-CREDENTIALS.md). Tooling: [DEVELOPMENT](docs/DEVELOPMENT.md); API and workers: [operator guide](docs/MISSION_CONTROL_LOCAL_API.md).
`make dev` (compose up, healthy) · `make check` (fast gate) · `make preflight` (read-only installation check).
<!-- END:sdlc-infra -->

## Provenance (from 2026-11-17)
- Work begins in a committed answers file (session `<FAM>-S<n>`), then a spec and a Linear issue with `Goal:` and the fixed `## Provenance` keys ([issue tracker](docs/agents/issue-tracker.md#provenance)); a finished issue gets a `## Completion` comment.
- Every commit ends with `Refs: OVE-n | <FAM>-S<n>` and, when they apply, `Decisions:` and `Docs:` → `./dev trace check`, the commit-msg hook and CI, warn-only until the owner switches them to block. `./dev trace show <id>` prints a chain ([SPEC-02](docs/specs/agentic-sdlc-2026-11/SPEC-02-PROVENANCE-CHAIN.md)).

## Boundaries and invariants (rule → what enforces it)
- Authority: code is what runs, ADRs what was decided, concepts explain both, programs are working documents; dated specs and `docs/specs/archive` are provenance. Report a conflict → review.
- Temporal alone schedules missions; Deep Agents is bounded operation cognition; reducers own lifecycle and settlement → `make test-arch` (workflow sources import no application or provider I/O), the unit and conformance suites.
- Accepted command, delivered signal and applied effect are distinct; execution completion is not mission acceptance → the unit suites, then review.
- Domain imports no database, Temporal, FastAPI or provider SDK; adapters implement application ports; bootstrap wires them; one distribution in `src/mission_control`, no `app/` kernel → `make test-arch` ([package boundaries](tests/architecture/test_package_boundaries.py)).
- Common SQL lives only in `packages/mission-control-db-contract`, mode `production_common`, no legacy fallback; application PostgreSQL and Temporal persistence stay separate → `make test-arch`, `./dev test db-contract`.
- Never invent provider bindings, schemas, grants or model routes → `make test-arch` (the kernel names no application binding), then review.
- Database variables are `MC_{AIENG,BIOTECH,LOCAL}_DB_*`, one plane per process chosen by `MISSION_CONTROL_APPLICATION`, read only through `Settings.db`, no aliases; the runtime DSN is the restricted `mission_control_runtime` login from the generated runtime env ([ENVIRONMENT](docs/ENVIRONMENT.md)) → `make env-check` (`config/env.registry.yaml`, `Settings` and `.env.example` agree).
- Data planes are reached by name: `--plane` always, read-only by default, schema changes only through `mission-db` or the owning installer, `aieng-graph` (`4773dc72`) never → `./dev planes check` and the `./dev db` refusals ([tests](tests/unit/docs_tools/test_data_plane_access.py)).
- Destructive migrations, volume deletion, deployment and paid calls only on an accepted packet's disposable targets within its budget; take a recoverable checkpoint before broad cleanup → `./dev db` refuses protected and retired planes, `mission-db` and the installers gate identity, then review.
- Local disposable proof is not a live installation; runtime claims need real local PostgreSQL and Temporal (`make test-integration`). Report implemented, tested, integrated and qualified apart, and checks as passed, failed, blocked or unrun; documentation releases no gate → review.
- Use `GLOSSARY.md` terms and honour its Avoid lists → review.
- Commit when an issue's work is complete and verified; push at gate release and session end (owner rule 2026-10-27) → review.

<!-- BEGIN:sdlc v=0.3.0 src=2b9c48482494 -->
## Repository guide
General Mission Control runtime and the common database component. Provider consolidation, one provider at a time; Deep Agents is the primary lane and the reference adapter shape (ADR-0005). Not here: application knowledge (`integrations/biotech`, never imported by the kernel), AI Engineer or Biotech schema authority, Knowledge Services internals.
Knowledge: [index](docs/knowledge/index.md) (one question per concept, 9 categories) · code map: [CODE-MAP](docs/CODE-MAP.md) · search: `python docs/tools/okf_search.py "<terms>"` (`--programs` adds program documents) · retrieval fixtures: `.sdlc/fixtures/retrieval/`

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
