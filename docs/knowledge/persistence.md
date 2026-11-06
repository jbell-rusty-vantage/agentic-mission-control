---
type: Concept
category: persistence
title: PostgreSQL persistence invariants
description: The invariants of Mission Control's persistence across the application PostgreSQL, Temporal history, the standalone LangGraph saver and Agent Server runtime persistence: three namespaces, scope binding and forced row-level security, restricted roles and logins, provisioned tenants, immutable additive releases, rebuildable projections and the one installer. Versions and release history live in database-component.
tags: [mission-control, persistence, postgres, rls, roles, installation, invariants]
aliases: [mission_control schema, scope binding, row-level security, restricted roles, installation readiness]
questions:
  - Which store is authoritative for mission state, and which are not?
  - How does a request bind its scope and why does missing context deny?
  - Which roles and logins exist and who may migrate?
  - Why did startup refuse an installation as not ready?
updated: 2026-11-01
---

# PostgreSQL persistence invariants

Application PostgreSQL owns lifecycle, immutable definitions and bindings, command receipts,
workspace and artifact records, candidates and subordinate details. It is written into each application's
own Supabase database (AI Engineer, Biotech) as the common component and relates to the knowledge schemas
(KS `knowledge_verification`, AIDB, BKS) without foreign keys between them ([applications](applications.md),
[database component](database-component.md)). **Release numbers, migration history, consumers and deployment
locks are in the database component; this concept holds only what stays true across releases.**

## Four stores, one authority

| Store | Holds | Authority |
| --- | --- | --- |
| Application PostgreSQL `mission_control` | missions, runs, activations, attempts, commands, effects, budgets, artifacts, events, outbox, recovery | mission truth |
| Temporal (Cloud in production, a separate local database in the dev stack) | workflow history | scheduling only (ADR-0004) |
| `mission_control_runtime` schema (pinned LangGraph saver and store, provisioned in a separate runtime phase) | standalone Deep Agents checkpoints | never mission truth |
| Agent Server runtime persistence | async subordinate state | a physically separate app-bound database (ADR-0017); never mission truth |

Runtime connections cannot substitute a schema-owner credential or migrate during startup.

## Namespaces and scope

The common component has three namespaces. `mission_control` is the business authority.
`mission_control_search` is a rebuildable capability, blueprint and plugin projection, never an
authorization store. `mission_control_runtime` is the saver. The same checksummed release is installed in
every application project; identity, seeds and data differ. Domain schemas, `auth`, `storage` and `public`
keep their owners.

Every business statement is schema-qualified and runs inside an explicit transaction after
`adapters/postgres/scope.py` binds transaction-local `mc.installation_id`, `mc.application_id`,
`mc.tenant_id` (and `mc.actor_ref`). Tenant tables force row-level security whose policies compare all three
columns with the `mission_control.ctx_*()` functions, so missing context denies. Catalog tables use
installation and application context without a fake tenant. Placement capacity is application-wide and
accessed only through scoped definer functions.

## Readiness, roles and logins

Composition checks the persisted installation identity, the complete attested release and schema
fingerprint, writer compatibility and restricted roles before marking a binding ready
(`bootstrap/common_installation.py`); startup never silently migrates, and there is no legacy-schema or
`public` fallback. Login roles hold one NOLOGIN capability role each (runtime, family writer, catalog writer,
outbox worker, readonly, checkpointer); none owns objects or bypasses RLS. Pools check
`pg_has_role(..., 'MEMBER')` and never `SET ROLE`. `mission-db login-apply` creates the `mcl_*` logins as
members of exactly one capability role `WITH INHERIT TRUE, SET FALSE`, sends only a client-side SCRAM verifier
and writes the DSNs (`sslmode=verify-full`) to an ignored owner-only env file; `login-plan` is read-only.

Tenants are provisioned, never runtime-created. Grants come from the operator `MissionDeployment`
(`tenant_ids`), but every tenant row needs `mission_control.tenant`; `mission-db tenant-plan` and
`tenant-apply` insert exactly the deployment's tenants, never revive a retired one, and write a receipt. A
submit for a missing tenant is the typed `tenant_not_provisioned` (409). Capability search needs `vector`
and `pg_trgm` in schema `extensions`, and a store refusal is `catalog_search_unavailable`, never a 500.

## Immutable, additive releases

Applied SQL and seed bytes are immutable; any change is a new component version, a new `release-build` and
new locks. Every migration is additive; an upgrade keeps earlier receipts and requires the attestation and
fingerprint of the selected release. `lane_profile` and `environment_readiness_level` are installation-
independent read-only reference data. `mission-db` (`packages/mission-control-db-contract`) is the only
installer: release build and lock, a plan bound to the before-fingerprint, atomic apply with receipts and
attestation, runtime and seed phases, and hash-only protected-object snapshots. The older `belllabs_control`
chain is historical bytes, never applied to live. Seed succession follows the same rule (a new catalog
version admits changed rows; old bundles stay fetchable by digest).

Release evidence must name the exact generated manifest and checks. The package suite tests disposable apply,
replay, drift rejection and restricted roles; `tests/qualification/two_project` independently tests two scoped
installations. A local disposable proof is never a live installation; runtime launch still requires the fresh
installation probe to match its selected release and restricted binding.

Built / specified / goal: scope binding, RLS, role verification, login and tenant provisioning and the
installer are implemented and tested (package and integration suites below); live installation state is
recorded in the database component; per-application production quality ingestion is a goal.

## Citations

- ADR: [0002](../adr/0002-one-service-two-applications-schema-per-app-database.md),
  [0003](../adr/0003-common-sql-owned-by-db-contract-package.md),
  [0009](../adr/0009-common-release-separate-app-authority.md),
  [0017](../adr/0017-agent-server-runtime-persistence-separate-database.md).
- Code: [scope binding](../../src/mission_control/adapters/postgres/scope.py),
  [common installation readiness](../../src/mission_control/bootstrap/common_installation.py),
  [composition and role verification](../../src/mission_control/bootstrap/composition.py),
  [installer package](../../packages/mission-control-db-contract/README.md).
- Tests: [two-project parity](../../tests/qualification/two_project/test_release_parity.py),
  [legacy poison round trip](../../tests/qualification/two_project/test_legacy_poison_round_trip.py),
  [receipt acceptance](../../tests/unit/mission_control/test_common_installation_receipts.py),
  [login roles](../../packages/mission-control-db-contract/tests/test_logins.py),
  [tenants](../../packages/mission-control-db-contract/tests/test_tenants.py),
  [search privileges](../../packages/mission-control-db-contract/tests/test_release_180_search_privileges.py).
- Operator commands: [local API guide](../MISSION_CONTROL_LOCAL_API.md).
