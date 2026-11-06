---
type: Implementation Plan
title: "Codex 0.162.1 describe successor: isolated candidate"
description: "Reviewable additive component inputs, disposable-build boundary and remaining release integration."
tags: [mission-control, codex, database, run-2]
---

# Codex describe successor

The Run 2 runtime describes Codex CLI 0.162.1. Immutable component 1.4.0 migration
0040 describes 0.162.0. Two lane-contract tests correctly expose that mismatch.
Do not rewrite 0040 or relax those assertions to disguise an inconsistent release.

`scripts/prepare_codex_describe_successor.py` prepares a proposed **1.4.1** in a
fresh directory outside the source package. It checks the exact 1.4.0 manifest,
historical migration set and bytes, runtime descriptor, and release-spec digest.
It copies those inputs unchanged and adds proposed
`0042_codex_01621_lane_describe.sql`. The candidate updates only the Codex version
fields and requires the exact old unqualified describe. It restores the immutable
trigger and forced RLS within the existing migration runner's transaction. It
does not change qualification, bindings, other lanes or capability seeds.

The original Codex-only candidate was built successfully on the owner-authorized
disposable PostgreSQL 17 fixture on 2026-10-14. Its generated contract digest is
`sha256:58909583f666e3f891766644dc7c223b98d8b6268b349068ec16432a49a738a8`
and manifest digest is
`sha256:189a50f9ad6fa4f0662a4420766b04125b29669f9c2e7d9adf0925b7a3bb9247`.
The temporary database was dropped; no new fixture database or role remained.
This proves build execution only, not an installed upgrade or live qualification.
The original candidate is retained unchanged in ignored local custody.

The complete Run 2 successor additionally needs the approved artifact-schema seed
compatibility entry and the Cursor cost-observation document contract. A separate
`scripts/prepare_run2_release.py` prepares these additive inputs under
`packages/mission-control-db-contract/releases/1.4.1/`. It preserves the frozen
`component/` 1.4.0 history and the original Codex-only proposal. The complete
successor needs its own generated identity and fresh install/upgrade/refusal proof;
the original candidate's receipt does not cover these additions.

## Concrete disposable proof

From the repository root, with the existing environment:

```powershell
.venv/Scripts/python.exe scripts/prepare_codex_describe_successor.py --out .scratch/materialization-observation-2026-10/run2/integration/component-1.4.1-reviewed
```

After the exact disposable fixture scope is authorized and a private environment
reference is supplied, the proposed build command is:

```powershell
.venv/Scripts/mission-db.exe release-build --component-root .scratch/materialization-observation-2026-10/run2/integration/component-1.4.1-reviewed/component --admin-dsn-env MCDB_RELEASE_ADMIN_DSN
```

Target: existing disposable PostgreSQL 17 container `mc-ft-disposable-pg17`,
loopback `127.0.0.1:55433`, never an application database or Temporal persistence.
The builder checks loopback/major, creates one random `mcdb_release_<12 hex>`
database, installs extensions there, executes migrations in a rolled-back
transaction, and drops that exact database in `finally`. Interrupted cleanup
must be inspected and reported before another attempt; no broad database deletion.
The administrator DSN stays private. No credentials or environment-file values
belong in output or committed receipts.

The owner separately authorized this `mcdb_release_*` disposable release build,
in addition to the `mct_*` persistence fixture. Neither approval authorizes a live
application database, cloud resource or provider execution.

## Release completion after proof

Validate fresh install and 1.4.0-to-candidate transition, exact Codex describe,
unchanged qualification, drift refusal and restored trigger/RLS. Then review the
generated contract/fingerprint/manifest and select the additive release layout
while preserving the complete frozen 1.4.0. Update reference-release tests and
deployment locks only as part of that reviewed successor. Re-run lane contracts,
component qualification and old-binding/seal compatibility checks. Local proof
does not authorize live apply or establish provider qualification.

The owner selected the current Biotech Knowledge Services schema deployed on Fly,
release `biotech-schema-v2.0.2`. Its source SHA-256 matches the live API identity.
That domain integration and its semantic overlay are validated separately from
this common database release. See [Run 2 report](RUN-2-REPORT.md).
