# Concrete adapters

postgres implements scoped repositories and immutable persistence; temporal
implements deterministic workflows/activities and client transport; deep_agents
materializes bounded cognition; agent_server hosts subordinate graphs;
capabilities and supabase_storage handle admitted bundles and object custody.
auth/jwt.py verifies public identity; storage owns payload I/O; realtime owns
PostgreSQL/Redis event transport; operations owns concrete execution ports. There
is no general infrastructure catchall for new implementations.

Adapters implement application ports. They cannot invent completion semantics,
privileged grants or cross-application routing. Scoped command delivery is separate
from command admission and application. Preserve exact immutable binding receipts.

Run real PostgreSQL/Temporal tests for durability claims. SDK calls must match
pinned official source. No paid provider experiment without finite authorization.
Application database migrations are under postgres/migrations; runtime startup
never applies them.

<!-- BEGIN:sdlc-module id=adapters -->
## Concrete adapters
Concrete I/O behind the application ports. Covers postgres, temporal, deep_agents, agent_server and the other lanes, storage, auth, realtime and operations; there is no general infrastructure catchall for new implementations.
Entrypoints:
- postgres/
- deep_agents/ — The Deep Agents lane package
- temporal/ — Durable workflow bootstrap for the Agents SDK and sandbox execution
- cursor/ — Cursor lane family
- codex/ — The codex Lane Profile: Codex app-server on a worker
- claude/ — The local Claude Agent SDK lane
- realtime/
- capabilities/
- remote_session/ — Remote Session Lane base: shared machinery for provider session APIs
- agent_server/ — Import-safe BellLabs Agent Server package exports
Also: openai_agents/, knowledge/, anthropic_managed/, auth/, workspaces/, storage/, provider_auth/, prerequisites/, supabase_storage/, github/, operations/, secrets/, subscriptions/, langsmith/, agents/, document_models/
Tests: tests/unit, tests/integration, tests/conformance/lanes
Invariants:
- Adapters implement application ports; they cannot invent completion semantics, privileged grants or cross-application routing.
- No paid provider experiment without finite authorization.
Explained by (docs/knowledge): mission-stream, hosted-api-lanes, knowledge-services, cross-provider-control, cursor-lane, durable-controls
Decided by (docs/adr): ADR-0007, ADR-0008, ADR-0016, ADR-0018, ADR-0019
Depends on: application, domain.execution, domain, domain.authoring, domain.frames, bootstrap (+3) · Used by: bootstrap, application, interfaces.cli, interfaces.http, interfaces.mcp
Verify: make check; make test-integration (needs compose services)
<!-- END:sdlc-module -->
