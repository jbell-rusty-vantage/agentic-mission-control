<!-- BEGIN:sdlc-module id=adapters.capabilities -->
# Capability custody adapters
Capability bundle custody, MCP registry, browser and skill discovery. Covers immutable skill bundles and their object store, browser subprocess transport, npx skills discovery, quarantine inspection and capability pins.
Entrypoints:
- capability_pins.py — Digest/revision pins of the search and browser capabilities a deployment mounts
- capability_bundles.py — Complete immutable directory bundles; no archive extraction or install hooks
- local_bundle_store.py — A filesystem BundleObjectStore with the custody semantics of the private bucket
- capability_embeddings.py
- quarantine_inspection.py
- mcp_registry.py
- npx_skills_discovery.py
- browser_subprocess.py — Bounded, framework-neutral subprocess transport for admitted browser capabilities
- agentic_components/ — Persistence and provider adapters for the Agentic Components harness
Tests: tests/unit/capability
Invariants:
- Bundles are complete immutable directories; no archive extraction or install hooks.
Explained by (docs/knowledge): capabilities, capability-seeds, selection-workspace
Decided by (docs/adr): ADR-0013, ADR-0023, ADR-0025, ADR-0033, ADR-0020
Depends on: application, domain, domain.authoring, bootstrap, domain.execution, adapters.deep_agents · Used by: bootstrap, adapters.agent_server, adapters.deep_agents, adapters.postgres, adapters.temporal
Verify: uv run pytest tests/unit/capability
<!-- END:sdlc-module -->
