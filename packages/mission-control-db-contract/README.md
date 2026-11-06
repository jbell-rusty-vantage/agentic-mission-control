# mission-control-db-contract

Distribution `mission-control-db-contract`, import `mission_control_db_contract`, CLI
`mission-db`. The single owner of the common Mission Control SQL component
(`mission_control` + `mission_control_search`), its generated MC-only contract, release
manifest and the shared fail-closed installer. Administrative tooling only: the
`mission_control` runtime never imports it. No app branching; apps (`biotech`,
`ai-engineer`) differ only by their `deployments/<app>/` manifests.

| Path | Content | Owner |
| --- | --- | --- |
| `releases/<version>/component/` | **The only release authority.** Each version's ordered common SQL (`NNNN_name.sql`, applied bytes never edited), `release-spec.json`, and the `manifest.json` + `generated/` written by `mission-db release-build`. Newest built: 1.12.0 (0001..0070) | DB lane |
| `component/` | Retired input: the frozen, built **1.4.0** release (migrations to 0041, `release-spec.json` says 1.4.0). Kept byte-identical because historical tests and the 1.4.1 preparer verify it; never select it for a new build, lock or install (it lacks 0042..0055) | frozen |
| `runtime/descriptor.json` | Pinned saver/store provisioning descriptor (`runtime/README.md`) | runtime-persistence lane |
| `seeds/` | Seed bundle content | catalog lane |
| `src/mission_control_db_contract/` | Installer, builder, snapshot, seed and runtime engines | DB lane |

Release source (Sprint V SV-17, plan row D0): `releases/<version>/component/` is the only
authority for building, locking and installing a release; the root `component/` is the retired
frozen 1.4.0 input. The Sprint V release bundle pins 1.6.0 and carries per-app target locks
(`docs/specs/provider-consolidation-2026-10/sprint-v/release/locks/<app>/release.lock.json`);
`deployments/<app>/release.lock.json` keep describing the live installations until an approved cutover.

Historical status: release 1.3.0 (0001-0034, fingerprint `sha256:3154fa8d...`, declared predecessors
1.0.0, 1.1.0 and 1.2.0) is locked in `deployments/{biotech,ai-engineer}/release.lock.json` and
installed in both live projects (upgraded from 1.0.0 on 2026-10-12; evidence in
`docs/qualification/two-project/*/20261012-live-130/`). The storage seed
`mc.storage.capability-bundles` is applied live too (owner-approved storage, 2026-10-12). Migration 0034 adds `provider_frame.lifecycle_body`, a JSON object
bounded to 4096 JSONB text bytes with an empty default for older frames. Writers retain only
allowlisted scalar lifecycle facts so raw-body truncation cannot erase normalized status.
No historical facts are inferred or backfilled. Any migration change requires a new component
version, a new `release-build` and new locks; applied migration bytes are never edited.

## Commands (exit 0 = passed, 2 = blocked gate; JSON on stdout, redacted)

```powershell
mission-db release-build --component-root packages/mission-control-db-contract/releases/<version>/component --admin-dsn-env MCDB_RELEASE_ADMIN_DSN
mission-db lock --app biotech --component-root packages/mission-control-db-contract/releases/<version>/component --deployments-root <dir>
mission-db inspect   --deployment-dir deployments/biotech
mission-db plan      --deployment-dir deployments/biotech --reader-version mission-control-runtime/1 --writer-version mission-control-runtime/1 --out plan.json
mission-db apply     --deployment-dir deployments/biotech <versions> --confirm-target <project_ref>:<installation_uuid> --expected-plan-digest <plan_digest>
mission-db verify    --deployment-dir deployments/biotech <versions>
mission-db seed-plan|seed-apply --deployment-dir ... <versions> --bundle seeds/... [--confirm-target ...]
mission-db runtime-plan|runtime-apply --deployment-dir ... <versions> --descriptor packages/mission-control-db-contract/runtime/descriptor.json [--confirm-target ... --receipt-out runtime-receipts.json]
mission-db snapshot  --target <read-only target.toml> --out protected-before.json [--chunk-size 1000]
mission-db compare   --before a.json --after b.json --allowed allowed-differences.json
mission-db qualify   --deployment-dir ... <versions> --phase before|after --out-dir docs/qualification/two-project/<target>/<run-id> [--snapshot-target ...] [--allowed ...]
```

`--deployment-dir` supplies `target.toml` and `release.lock.json`; the lock's
`release_root` locates the component. Targets (`format_version = 1`, `[target]` +
`[approval]`) hold `app`, `project_label`, `project_ref`, `environment`, `application_id`
(= `app`), `installation_id`, `database_host/port/name/user` and `database_url_env` (an
environment-variable NAME). Placeholders, unknown fields and missing approval/evidence
references hold. The DSN must match host/port/user/database exactly.

## Release protocol `mission-control-sql/v2`

- `release-build` runs only against a loopback disposable PostgreSQL 17 server: scratch
  database, required extensions created in schema `extensions`, migrations in ONE
  rolled-back transaction with `search_path = pg_catalog, pg_temp`, then the database is
  dropped. Identical inputs produce identical `manifest.json`/`generated/*` bytes.
- Fingerprint `mc-pg-catalog-v2`: v1 normalization per schema (relations, columns,
  constraints, indexes, functions, policies, triggers, views, enums, types, sequences,
  named grants; owner names/OIDs/rows excluded), explicit schema list, per-schema digests.
- Manifest: component/version/source identity, `source_revision` (git HEAD + sha256 of
  component inputs), protocol, fingerprints, contract path/digest, PG 17 / 170000,
  `required_extensions` (`vector` in `extensions` for `mission_control_search`), ordered
  migrations, reader/writer sets, runtime roles, predecessors, seed compatibility,
  runtime descriptor sha. Never self-referential; the app lock hashes every payload file.
- `plan` binds identity, receipts, attestations, `mission_control_*` roles, extensions,
  server version and before-fingerprint into a body whose sha256 is `plan_digest`.
- `apply` takes the migration advisory lock, re-observes and recomputes the plan; a
  different digest is `STALE_PLAN` (unless nothing is pending and the release verifies:
  concurrent equal installers -> one applies, one no-ops). Migration SQL, receipts,
  installation insert/version update and `release_attestation` commit in one
  transaction after final fingerprint/role verification. Bounded lock/statement timeouts.
- Holds before creating anything: owned schema without receipts; any `mission_control_*`
  role with LOGIN/SUPERUSER/BYPASSRLS/CREATEROLE/CREATEDB; identity/version/extension
  mismatch; unknown/changed/non-prefix receipts; non-admitted fingerprint; differing
  attestation. Driver errors report only SQLSTATE.

## Protected snapshot, seeds, runtime

- `snapshot` (REPEATABLE READ, read-only) discovers every non-system schema except
  `mission_control*`; records structure digests, row counts and chunked in-database
  sha256 row digests (PK order, else row text), sequence states, roles/memberships
  (attributes only), extensions and `storage.buckets` settings. No rows or secrets leave
  the database. `compare` exits 2 on any difference not matched by an allowed rule
  (`{"path": glob, "change": added|removed|changed, "reason": ...}`).
- Seeds (`schemas/seed-bundle.v1.schema.json`; `seeds.validate_bundle` enforces): whole
  set + dependency closure validated first; one transaction per bundle under an
  installation-keyed advisory lock; same digest replays, changed digest conflicts;
  logical keys -> UUIDv7 via `seed_identity`; revoked grants never revived; assets and
  decisions append-only; transaction-local `mc.*` context satisfies FORCE RLS.
- Runtime phase executes `runtime/descriptor.json` per `runtime/README.md`
  (`schemas/runtime-descriptor.schema.json`): session advisory lock, private
  `search_path`, exact per-step sha256, autocommit concurrent indexes, ledger rows only
  after verify, completion derived from catalog probes, per-run JSON receipt, invalid
  indexes held and never retried.

## Tests

Two disposable clusters (`pgvector/pgvector:pg17`, loopback 55501/55502):

```powershell
uv run python packages/mission-control-db-contract/scripts/disposable.py start   # prints DSN env lines
$env:MCDB_TEST_ADMIN_DSN_A = '...'; $env:MCDB_TEST_ADMIN_DSN_B = '...'
uv run --group dbcontract pytest packages/mission-control-db-contract/tests -p no:cacheprovider
uv run ruff check packages/mission-control-db-contract
uv run --group dbcontract mypy --config-file packages/mission-control-db-contract/pyproject.toml packages/mission-control-db-contract/src
uv run python packages/mission-control-db-contract/scripts/disposable.py stop
```

Cluster A installs as the superuser with a corpus/storage fixture; cluster B installs as a
non-superuser CREATEROLE principal (Supabase-like) with legacy `capability_search` data and
a REVOKE-ALL `belllabs_control` poison schema. Database tests fail, never skip, without
the DSN variables. Tests build releases from temp copies of whatever migrations exist.
