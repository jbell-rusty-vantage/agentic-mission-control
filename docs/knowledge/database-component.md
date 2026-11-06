---
type: Concept
category: persistence
title: The common database component
description: How Mission Control's SQL ships as one versioned component (mission-control-db-contract, mission-db), release numbering 1.3.0 to the built 1.14.0, who consumes it (deployment locks, the AI Engineer and Biotech installers), how the schemas live in each application's own Postgres beside the knowledge schemas, and what is installed where.
tags: [mission-control, database, release, mission-db, installer, deployment-locks, knowledge-schemas]
aliases: [mission-control-db-contract, common component, release numbering, release lock, mission-db]
questions:
  - Which component release is current and who consumes it?
  - How do the Mission Control schemas live in each application's database?
  - Which release is installed where, and which is only built?
  - How do I add a migration and what number does it take?
updated: 2026-11-02
---

# The common database component

`packages/mission-control-db-contract` (distribution `mission-control-db-contract`, CLI `mission-db`) is the
single owner of the common SQL (ADR-0003): ordered migrations, seeds, the generated contract, the release
manifest and a shared fail-closed installer. It is administrative tooling; the `mission_control` runtime never
imports it. There is no application branching: the two applications differ only by `deployments/<app>/`. The
invariants every release keeps (scope, RLS, roles) are in [persistence](persistence.md); this concept is
numbering, consumers, locks and placement. Exact digests and the full per-release change list are never
restated here: read [releases/README.md](../../packages/mission-control-db-contract/releases/README.md).

## How the schemas live in each application

The same release is installed into each application's own Supabase PostgreSQL (ADR-0002), as schemas
`mission_control`, `mission_control_search` and `mission_control_runtime`, next to the knowledge schemas that
database already carries:

| | AI Engineer database (aieng-db) | Biotech database (biotech-db) |
| --- | --- | --- |
| Mission Control | `mission_control`, `_search`, `_runtime`, Storage buckets | the same release, identity and seeds differ |
| Knowledge | KS `knowledge_verification` (component 2.5.0) and AIDB domain schemas, AIDB tables in `public` | KS `knowledge_verification`; no domain tables (the domain is the BKS Neo4j graph) |
| Relation | no foreign keys across authorities: Mission Control journals effects, handles and retained reads that carry KS origins and ids; AIDB and BKS own entities | same |

Placement and data-plane identities: [applications](applications.md). Temporal history and Agent Server
persistence are separate stores ([persistence](persistence.md)).

## Release numbering

Versions live only under `releases/<version>/component/`; there is no implicit `latest` and the root
`component/` is the frozen 1.4.0 input kept for historical tests, never a build, lock or install source. A
release is the byte-identical previous built prefix plus new migrations, prepared by
`scripts/prepare_release_<nnn>.py`; applied SQL is never edited. A minor release adds migrations with an
unchanged reader/writer protocol (`mission-control-runtime/1`). The newest built is **1.14.0** (migrations
0001..0072).

| Release | Adds (migration keys) |
| --- | --- |
| 1.3.0 | 0001-0034 (live in the October 12 installation; provider frame lifecycle body 0034) |
| 1.4.1-1.4.4 | 0035-0049: signal ingress, hosted lane profiles, environment preparation, owner prerequisites, implemented lane describes, placement capacity, ingress idempotency, cognition points, transcript joinability and entries, frame body references |
| 1.5.0 | 0050-0054: knowledge operation journal, content lineage, source bindings and retained observations, submissions, transfer plans |
| 1.6.0 | 0055: knowledge handles, assessment, delivery attempts |
| 1.7.0 | 0056-0060: output contracts and fulfillment, sealed transfer attempts, saved execution settlement, recorded use decisions, hook candidate installs |
| 1.8.0 | 0061, 0063, 0064: durable transition reactions, coordinator delivery observations, search extension privileges |
| 1.9.0 | 0066, 0067: collection member assessments, trusted handle operations |
| 1.10.0-1.11.0 | 0068, 0069: exact linked exports and the family writer grants |
| 1.12.0 | 0070: workspace closure |
| 1.13.0 | 0071, 0072: nested program activations, native plan decision columns (the former "2.0.0 candidates"; additive, so a minor inside the `<2.0.0` component range) |
| 1.14.0 | 0073: the cross-provider control describe refresh (every session lane declares `time_travel` and its fork cell; data only, schema fingerprint unchanged; OVE-224, ADR-0069) |

No candidate is outstanding: 0073 shipped in 1.14.0 (2026-11-05, source `scripts/release_1140/`, rendered by
`scripts/prepare_release_1140.py`; no remote install yet). The
runtime refuses to start on a release without a migration it reads (`REQUIRED_MIGRATIONS` in
`bootstrap/common_installation.py`; a unit test keeps every key inside the newest built release). The
unreviewed branches `sprint-oc-wi14` (0070) and `sprint-oc-wi15` (0071) carry colliding keys and must be
renumbered when integrated. Keys are assigned by the integrator, so branches can collide: a `check` rule that
fails a reused key is a navigation-program item, and the integrator renumbers (never edits an applied file).

## Consumers and deployment locks

A deployment lock (`deployments/<app>/release.lock.json`, written by `mission-db lock --app ...
--component-root releases/<v>/component`) pins the file digests of one release for one application; the API
and workers refuse an installation whose attested release or fingerprint differs. Consumers:

- `deployments/ai-engineer` and `deployments/biotech`: `target.toml` (installation identity, approved
  project, `database_url_env` as a variable name), `release.lock.json`. These two locks still name the older
  releases (AI Engineer 1.4.2, Biotech 1.3.0) until an approved cutover.
- Sprint OC target locks beside the release bundle: `sprint-oc/release/locks` (1.7.0), `locks-180` (1.8.0) and
  `locks-190` (1.9.0) and `locks-1130` (1.13.0, AI Engineer); `scripts/sprint_oc_w0_local_proofs.mjs` reads the `locks` directory.
- The installers of the other repositories pin a lock: AIDB `scripts/install-ai-engineer.mjs`, BKS
  `scripts/install-biotech.mjs` (with a `component-grants` step because Supabase's admin is not superuser) and
  the thin Biotech wrapper `biotech/biotech-postgres-db-contract` (`biotech-db`).
- `mission-db` verbs: `release-build`, `lock`, `inspect`, `plan`, `apply`, `verify`, `seed-plan|apply`,
  `runtime-plan|apply`, `login-plan|apply`, `tenant-plan|apply`, `snapshot`, `compare`, `qualify`; apply
  requires `--confirm-target <project_ref>:<installation_uuid>` and the plan digest.

## What is installed where

Built, locally proven: 1.13.0 (`tests/integration/postgres/test_sprint_oc_release_1130.py`: fresh, upgrade from
1.12.0, verify, replay). Remotes (2026-11-02): the **AI Engineer** disposable remote (`wkythqbofmckbuoothhn`) runs
**1.13.0** verified (63 migrations, upgraded from 1.9.0 with plan `sha256:d6283af2…`), with seeds through
agent-skills 1.0.4, knowledge-tools 1.2.0, workflow-parity 1.0.5 and mission-payloads 1.0.0 applied and their custody
bytes published; the **Biotech** remote runs **1.9.0** (W1 session 7) and none of those seeds. Earlier: 1.8.0 with
the saver, seeds, bundle custody, restricted logins and tenants
([handoff](../specs/archive/provider-consolidation-2026-10/docs/HANDOFF-2026-10-28-S3.md) section 3). Receipts are
private under `.scratch/sprint-oc/evidence/w1/` (`verify-190.*`, `s11/`).
Local proofs run on the `sprint-v-pg17` container; a local disposable proof is not a live installation.

Built / specified / goal: numbering, locks, installer and releases through 1.13.0 are implemented and tested
locally; remote state is 1.13.0 (AI Engineer) and 1.9.0 (Biotech) on disposable targets; a production application install and its upgrade policy
are a goal tied to [deployment](deployment.md).

## Citations

- ADR: [0002](../adr/0002-one-service-two-applications-schema-per-app-database.md),
  [0003](../adr/0003-common-sql-owned-by-db-contract-package.md),
  [0009](../adr/0009-common-release-separate-app-authority.md).
- Code: [package guide](../../packages/mission-control-db-contract/README.md),
  [release history](../../packages/mission-control-db-contract/releases/README.md),
  [1.13.0 sources](../../scripts/release_1130/0071_nested_program_activations.sql),
  [AI Engineer lock](../../deployments/ai-engineer/release.lock.json),
  [Biotech lock](../../deployments/biotech/release.lock.json).
- Proof: [W0 release bundle](../specs/provider-consolidation-2026-10/sprint-oc/release/RELEASE-BUNDLE.md),
  [provenance report](../specs/archive/provider-consolidation-2026-10/sprint-oc/provenance-2026-10-31/REPORT.md),
  `BellLabs/docs/navigation/DATA-PLANES-AND-CREDENTIALS.md`.
- Tests: [release 1.13.0](../../tests/integration/postgres/test_sprint_oc_release_1130.py),
  [release 1.12.0](../../tests/integration/postgres/test_sprint_oc_release_1120.py),
  [release 1.9.0](../../tests/integration/postgres/test_sprint_oc_release_190.py),
  [two-project parity](../../tests/qualification/two_project/test_release_parity.py).
