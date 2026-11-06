# PostgreSQL authority

Repositories enforce scoped identity, immutable content and transaction boundaries.
Apply scope on every acquired connection, including after pool reset. Runtime and
family-writer roles are distinct; do not use schema-owner credentials as a fallback.

Every statement is schema-qualified to mission_control or mission_control_search
and runs inside an explicit transaction after scope.apply_scope (or the catalog
variant); forced RLS denies missing context. Never reference legacy schemas or
fall back to them.

Schema changes belong to packages/mission-control-db-contract (new versioned
migration, never edited bytes). migrations/ here is the historical transitional
chain, pinned by docs/organization/legacy-belllabs-control-chain.json and never
applied to live. Never apply destructive live changes or delete records to make a
test pass. See docs/knowledge/persistence.md and tests/qualification/two_project.

<!-- BEGIN:sdlc-module id=adapters.postgres -->
## PostgreSQL authority
Scoped repositories, immutable content and transaction boundaries. Runtime and family-writer roles stay distinct; every statement is schema-qualified and runs in an explicit transaction after scope is applied.
Entrypoints:
- run_control/
- control_plane/
- knowledge/ — PostgreSQL knowledge journal and output submission stores
- frames/ — PostgreSQL Native Event Store: frames, native identity records, retention
- subscriptions/
- context/ — PostgreSQL adapters for Context Packets: selection ledger and output capture
- operations/
- runtime/
- lanes/ — PostgreSQL lane state: harness execution native identity, leases, hook task tokens
- chains/ — PostgreSQL authority for Mission Chains: rows, the in-transaction release hook…
Also: orchestration/, async_subagents/, reactions.py, human_tasks/, ingress.py, capability_bundles.py, workspace_closures.py, watchers.py, environments/, scope.py, capability/, approvals/, workspaces/, closed_workflow.py, coordinator/, ingress_drainer.py, terminal_adoption_context.py (+6)
Tests: tests/integration/postgres, tests/qualification/two_project
Invariants:
- Apply scope on every acquired connection; never use schema-owner credentials as a fallback.
- Schema changes belong to the db-contract package; migrations/ here is historical and never applied live.
Explained by (docs/knowledge): revisions, provider-frames-and-transcript, events-and-commands, interventions, recovery, budgets-and-usage
Decided by (docs/adr): ADR-0032, ADR-0008, ADR-0054, ADR-0055, ADR-0004
Depends on: application, domain, contracts, domain.authoring, domain.execution, domain.programs (+9) · Used by: bootstrap, adapters.temporal, interfaces.mcp, interfaces.http, adapters.agent_server
Verify: uv run pytest tests/integration/postgres (needs real PostgreSQL)
<!-- END:sdlc-module -->
