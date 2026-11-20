# Public contracts

contracts.py defines scoped command/inspection envelopes; admission_contracts.py
defines typed admission/launch requests; runtime_contracts.py defines snapshot,
fork and reconciliation requests. canonical.py defines deterministic digests;
identities.py defines installation/application/tenant scoped runtime identities.
database_release.py ports the rule every consumer of an application database applies
to its release (authority: the database contract repository; never relax it here, and
keep tests/fixtures/database_release identical to that repository's cases file).

Changing canonical bytes changes idempotency and immutable pins. Reject ambiguous
Unicode keys, nonfinite values, illegal scope and payload-kind mismatches.
A contract request cannot inject trusted actor, pool or installation authority.

Evidence: tests/unit/run_control/test_mission_control_canonical.py,
test_mission_control_facade.py and tests/unit/mission_control/test_temporal_identities.py.

<!-- BEGIN:sdlc-module id=contracts -->
## Public contracts
Public envelopes: commands, inspection, admission, canonical digests. Also scoped identities, the hook, realtime, Context Packet and Knowledge Operation Protocol wire contracts, and the database release rule.
Entrypoints:
- hooks.py — Hook Script stdin/stdout contracts: mc.hook_input.v1 and mc.hook_result.v1
- contracts.py — Versioned public contracts for the inherited, qualified lifecycle controls
- database_release.py — The database release rule every consumer of an application database applies
- realtime.py — mc.realtime.v1: the /missions Socket.IO event vocabulary and its additive payloads
- knowledge_protocol.py — Knowledge Operation Protocol wire models and digests for the Mission Control side
- knowledge_protocol_results.py — Knowledge Operation Protocol result, descriptor and credential wire models
- knowledge_assessment.py — K01 trusted assessment contracts
Also: run_evidence.py, runtime_contracts.py, identities.py, canonical.py, context_packet.py, admission_contracts.py, json.py, schemas/
Tests: tests/unit/run_control/test_mission_control_canonical.py, tests/unit/run_control/test_mission_control_facade.py, tests/unit/mission_control/test_temporal_identities.py, tests/unit/mission_control/test_database_release_rule.py, tests/conformance
Invariants:
- Changing canonical bytes changes idempotency and immutable pins.
- A contract request cannot inject trusted actor, pool or installation authority.
Explained by (docs/knowledge): application-profile, capabilities, events-and-commands, hook-contributions, mission-control, mission-stream
Decided by (docs/adr): ADR-0004, ADR-0063, ADR-0001, ADR-0002, ADR-0005
Depends on: domain, domain.programs, domain.authoring, domain.execution · Used by: adapters.postgres, application, adapters.temporal, interfaces.mcp, application.missions, bootstrap (+12)
Verify: uv run pytest tests/unit/run_control tests/conformance
<!-- END:sdlc-module -->
