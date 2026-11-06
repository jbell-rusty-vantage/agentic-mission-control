# Pure rules and decisions

programs contains family interpretation; execution owns operation/run invariants;
authoring owns immutable definitions and compilation; composition owns delegated
run contracts; context owns the Context Packet (mc.context_packet.v1), the pure
Context Packer and its renderers (ADR-0027). Policies remain explicit admitted inputs.

Domain imports neither Temporal, database clients, FastAPI nor model/provider SDKs.
Do not turn interpreter proposals into authoritative lifecycle changes. Preserve
determinism and immutable content identity across retries and forks.

Start with the relevant tests/unit/orchestration, run_control, operations or
control_plane tests. Use docs/knowledge/temporal-synthesis.md for the request-to-settlement path.

<!-- BEGIN:sdlc-module id=domain -->
## Pure rules and decisions
Pure rules and decisions with no I/O. Covers programs, execution, authoring, composition, context, resolution, capabilities, outputs and reactions; policies are explicit admitted inputs.
Entrypoints:
- authoring/ — Authoring: manifests, definitions and their compilation
- execution/ — Provider-neutral semantic operation execution contracts
- programs/ — Deterministic blueprint orchestration contracts and scheduling decisions
- policies/
- context/ — Context Packet contract, deterministic Context Packer and renderers
- capabilities/ — Provider-neutral cores of the agent-composition capability kinds
- outputs/ — Output contracts: named promises, candidates, assessments, fulfillment
- coordinator/ — Pure coordinator capability-retrieval contracts and policy
- frames/ — Provider frames, closing facts and transcript rendering; pure rules only
- resolution/ — Pure resolution types: the neutral agent configuration, the selection…
Also: reactions/, subscriptions/, agentic_components/, graph_runtime/, composition/, knowledge/, prerequisites/
Tests: tests/unit/orchestration, tests/unit/run_control, tests/unit/operations, tests/unit/control_plane, tests/architecture/test_package_boundaries.py
Invariants:
- Imports no Temporal, database client, FastAPI or provider SDK.
- Determinism and immutable content identity hold across retries and forks.
Explained by (docs/knowledge): capabilities, completion, output-contracts, context-and-continuation, budgets-and-usage, durable-controls
Decided by (docs/adr): ADR-0010, ADR-0007, ADR-0008, ADR-0011, ADR-0013
Depends on: contracts · Used by: application, adapters.postgres, adapters.deep_agents, application.recovery, adapters.temporal, application.authoring (+16)
Verify: make test-arch; uv run pytest tests/unit/orchestration tests/unit/operations
<!-- END:sdlc-module -->
