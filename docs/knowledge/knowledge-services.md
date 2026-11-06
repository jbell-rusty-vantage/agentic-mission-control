---
type: Concept
category: boundaries
title: Knowledge Services boundary
description: Which knowledge contracts Mission Control shares with Knowledge Services (K01 transport, issuer-backed credentials, the seven Deep Agents knowledge tools, submission assessment, exact delivery, recorded discovery reads) and which stay application-owned; what the optional Biotech package implements; where the Knowledge Services repository starts.
tags: [mission-control, knowledge-services, k01, gateway, boundary, implementation]
aliases: [KS boundary, knowledge gateway, K01 transport, knowledge operation]
questions:
  - What does Mission Control own and what does Knowledge Services own?
  - How does a mission call Knowledge Services and how is a read recorded?
  - Which Knowledge Services binding serves which application?
  - Why did a knowledge effect stay uncertain instead of being resent?
updated: 2026-11-01
---

# Knowledge Services boundary

[Knowledge Services](../../GLOSSARY.md) (KS) are shared contracts and operations for evidence, source
identity, provenance, governed domain writes and retrieval. The repository is
`platform/knowledge-services` (read its `AGENTS.md`; this concept is the Mission Control side only).
A [Domain Service](../../GLOSSARY.md) is application-owned and the kernel never writes entities
([mission control](mission-control.md)). Application placement and the KS, AIDB and BKS pointers:
[applications](applications.md).

## Shared contracts and application-owned stores

Shared: source identity, version and locator; artifact custody; governed Intent, plan, apply and
Receipt with a stable effect identity and receipt lookup before any uncertain repeat; evidence
tracking; [Advisory Memory](../../GLOSSARY.md) admitted explicitly (ADR-0007); a retrieval envelope
whose score is not evidence validity (ADR-0059). Application entity reads and writes go to the
application's own adapter behind a KS binding: `aiengineer-postgres` (AI Engineer, PostgreSQL) and
`biotech-graph` (Biotech, Neo4j). Both applications keep mission state in their own Supabase
`mission_control` schema; general code cannot query an entity store or depend on its schema.

## The knowledge gateway (Sprint V; provenance slices 1-4)

Mission Control reaches an application knowledge service only through K01
`ks.knowledge_operation.v2` (schemas and golden vectors byte-copied under
`tests/fixtures/knowledge_protocol`); the Python wire models reproduce the TypeScript rules.

- **Transport and credentials.** The HTTP client speaks `/knowledge-operation/v2` `invoke`,
  `operations/{id}`, `operations/{id}/cancel`, `receipts/{effectKey}` and `describe`: strict 2xx
  validation, `protocol-error.v2` as a typed refusal, bounded `Retry-After` only for idempotent calls.
  One Ed25519 (`EdDSA`) compact JWS per transmission (300 s, single-use `jti`); the host checks
  issuer, audience, scope, origin, operations, effect and recovery.
- **Gateway.** Effects are journaled `prepared` before transmission, dispatched once, settled from the
  receipt, or left `uncertain` until a lookup proves them. At attempt start the host mints an
  effect-scoped recovery grant per uncertain effect (`recovery_authority_ref`). The effect key is over
  run and exact payload: a corrected payload is a new effect, an identical call replays the settled
  outcome unsent, a settled refusal replays as the same refusal, a replayed success reads its receipt
  back or is refused typed (`RECEIPT_UNAVAILABLE`, `RECEIPT_DIGEST_MISMATCH`). A `pending_dispatch`
  receipt stays `uncertain` until a lookup's `delivery` settles it (`applied`, or `revoked` then `rejected`).
- **Tools, submission, assessment.** Seven tools (`knowledge_read`, `knowledge_apply`,
  `report_register`, `report_derive`, `verify_claims`, `submit_output`, `knowledge_read_intent`) are
  exact Deep Agents tool components. Each call builds a fresh host access from the live attempt; its
  origin names the run's ledger `mission_run.mission_id` and the attempt's `activation.activation_id`,
  resolved once per attempt by `KnowledgeToolset.locate` over the `InvocationLocator` port
  (`PostgresInvocationLocator` in production; unresolved raises `MissionIdentityUnavailable`; slice 1).
  Refusals carry code, message and field paths, bounded and redacted. `report_register` takes content
  only; the host computes every digest ([trusted judgment](trusted-judgment.md)). The tool boundary
  parses a JSON string given for an object argument exactly once and lists `argument_coercions`.
  `submit_output` refuses a bare promise name with the valid `<position>.<promise>` keys. At node
  completion the selected report starts independent `report.assess` (`pending -> assessing ->
  assessed|held|rejected`); a report must be selected alone, other collections stay coverage-only.
- **Recorded discovery reads (`knowledge.read_intent`, slice 4).** `knowledge_read_intent` sends one
  `knowledge-read-intent-request.v1` (up to 32 allowlisted named queries) under a non-effect
  credential; `gateway.read_intent` rechecks every digest and writes one `retained_read_observation`
  per answered operation through the `RetainedReadStore` port. An unrecorded read is refused
  `CAPABILITY_UNAVAILABLE`, an evaluator `SCOPE_DENIED`. Only `aiengineer-postgres` serves it; the
  Biotech binding has no read-intent port. Implemented and tested on both sides; integrated on KS's
  disposable; **not exercised live** by a mission (PROV §3 row 4).
- **Exact delivery (WI-02).** A report is delivered only when a receiver's sealed transfer plan names
  it, read through `readSelected` (`selected-report-read/v2`) at each realization, so a revoked revision
  stops readiness ([output contracts](output-contracts.md)).
- **Production minting (slice 2).** The AI Engineer fixture ran through the production gateway: seven
  Mission-Control-minted calls, 14 host calls with minter `mission-control` (integrated, not qualified;
  PROV §2-§3).
- **Composition.** `compose_knowledge_lane` reads `KNOWLEDGE_BINDING_URL`, `KNOWLEDGE_BINDING_AUDIENCE`,
  `KNOWLEDGE_ISSUER`, `KNOWLEDGE_ISSUER_KEY_FILE` (plus an optional retiring key) and
  `KNOWLEDGE_COMPONENT_INSTALLATION_ID` (every K01 origin names the KS component installation, never
  MC's own). It takes binding, contract and layout from the [Application Profile](application-profile.md),
  fails closed naming missing variables, and runs a `describe` preflight whose digest enters a sanitized
  startup receipt (`src/mission_control/bootstrap/composition.py:482`). K01 annex: component >= 2.4.0.

## Backend registration on the KS side (Sprint OC R5)

Which KS backend serves an application is data on both sides of K01; Mission Control never names a
backend in code. Each KS binding package exports one `BACKEND: BackendRegistration`; capabilities are
exactly the ports it wires (`research`, `apply`, `delivery`, `native_receipt_lookup`, `revocation`).
`aiengineer-postgres` declares `apply` conditional on a host-injected port; `biotech-graph` declares it
unconditionally. `readback` is unservable in K01, so both Application Profiles declare
`readback_capability = "unsupported"`. `tests/conformance/applications/ks_backend_descriptors.json`
is a hand copy of each `BACKEND.describe()` at the KS commit it records; W0 repeats the check against
the live describe.

## What `integrations/biotech` implements

The optional distribution `biotech-mission-adapters` (`integrations/biotech`, depends on
`mission-control`, `neo4j`, `graphql-core`) is a transition home the kernel never imports
(`tests/architecture/test_package_boundaries.py:178`). It is read-side schema grounding, context
selection and reference-research verticals over the generic operation seams, with a Neo4j bounded read
executor and an optional scoped records table that is never part of the common release. No Neo4j writer
or AI Engineer PostgreSQL adapter exists in this repository; domain stores stay behind the KS bindings.
Package guide and module list: [integrations/biotech README](../../integrations/biotech/README.md).

Built / specified / goal: the gateway, tools, assessment and exact delivery are implemented and tested;
slices 1-3 and 5 are integrated on a disposable AIDB, slice 4 is not exercised live; nothing is
qualified until W1 ([qualification](qualification.md)). KS generalization beyond the two bindings is a
goal ([goals](goals.md#goal-knowledge-services-service)).

## Citations

- ADR: [0007](../adr/0007-authoritative-state-separate-from-advisory-memory.md),
  [0059](../adr/0059-application-content-and-shared-knowledge-authority.md),
  [0060](../adr/0060-authenticated-origin-and-native-receipt-provenance.md),
  [0061](../adr/0061-one-sealed-transfer-plan-and-attempt-receipts.md).
- Proof: [provenance report](../specs/archive/provider-consolidation-2026-10/sprint-oc/provenance-2026-10-31/REPORT.md)
  (sections 2-3, 5), [APPLICATION-PORTS](../specs/provider-consolidation-2026-10/sprint-oc/APPLICATION-PORTS.md).
- Code: [gateway](../../src/mission_control/application/knowledge/gateway.py),
  [toolset](../../src/mission_control/application/knowledge/toolset.py),
  [read intent](../../src/mission_control/application/knowledge/read_intent.py),
  [submissions](../../src/mission_control/application/outputs/submission_service.py),
  [HTTP client](../../src/mission_control/adapters/knowledge/http_client.py),
  [credentials](../../src/mission_control/adapters/knowledge/credentials.py),
  [Biotech composition](../../integrations/biotech/src/biotech_mission_adapters/bootstrap/composition.py).
- Tests: [gateway](../../tests/unit/knowledge/test_gateway.py),
  [submission bounds](../../tests/unit/knowledge/test_submission_assessment.py),
  [tool refusals](../../tests/unit/knowledge/test_knowledge_tools.py),
  [K01 negative](../../tests/conformance/test_knowledge_protocol_negative.py),
  [PostgreSQL](../../tests/integration/postgres/test_knowledge_gateway_postgres.py),
  [T1-MC runtime](../../tests/acceptance/mission_control/test_knowledge_gateway_runtime.py),
  [package boundaries](../../tests/architecture/test_package_boundaries.py),
  [profile conformance](../../tests/conformance/applications/test_application_profiles.py).
- Operations: [operator guide](../MISSION_CONTROL_LOCAL_API.md#knowledge-gateway-configuration-sprint-v-sv-16sv-17),
  [removal guide](../specs/archive/mc-surfaces-2026-10/docs/REMOVAL_GUIDE.md#older-biotech-knowledge-path-retirement-2026-10-27).
