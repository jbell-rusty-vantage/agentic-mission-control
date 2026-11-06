---
type: Implementation Evidence
title: "Sprint OC W0 release bundle (WI-24): pins, four-owner schema fit, installs, refusals, seeds and the live describe check"
description: "The W0 bundle for the AI Engineer and Biotech disposable targets: knowledge_verification 2.5.0, Mission Control common 1.7.0 with the Sprint OC target locks, AIDB contract 0.5.0 head 20261025010200, BKS biotech-schema-v2.2.0, the model pins and their probes, and the installer commits; the four-owner schema fit; what is real-installed, doubled and unrun; the integrator's remote commands for the live describe capture, seed custody and refusal proofs, with placeholders for their results; and the W1 prerequisites. Local proofs ran on sprint-v-pg17 on 2026-10-28."
tags: [mission-control, knowledge-services, biotech, ai-engineer, sprint-oc, wi-24, w0, release, install]
status: active
date: 2026-10-28
---

# Sprint OC W0 release bundle (WI-24, OVE-168)

Machine-readable twin: [release-bundle.json](release-bundle.json). Target locks:
[locks/ai-engineer](locks/ai-engineer/release.lock.json), [locks/biotech](locks/biotech/release.lock.json).
Runtime environment (names only): [RUNTIME-ENVIRONMENT.md](RUNTIME-ENVIRONMENT.md). Format follows the Sprint V
[release bundle](../../../archive/provider-consolidation-2026-10/sprint-v/release/RELEASE-BUNDLE.md).

The two targets are the identified disposable Supabase projects of [IMPLEMENTATION §4.1](../IMPLEMENTATION.md)
(OC-D184) and the Biotech Aura graph (OC-D196). Placeholders marked `<<integrator>>` take the integrator's remote
results. Placeholders marked `<<reviewer>>` take the independent reviewer's sign-off. No value in this page is a
credential.

**W0 status: RELEASED WITH RECORDED LIMITATIONS (2026-10-28).** Every integrator row is filled; the independent reviewer signed (section 8.2).

## 1. Pins and digests

| Unit | Owner | Pin | Digest |
| --- | --- | --- | --- |
| `knowledge_verification` component | KS `packages/knowledge-db-contract` | **2.5.0** (0001..0008; 0008 = `effect_dispatch_journal`, WI-05) | component `sha256:00550d59a2fe487a80e97d746d1897234e2f98c246091c06e5d2d5a07b108b88`; K01 `pinnedSchema` `knowledge-verification-2.5.0` release digest `sha256:728e4d8aa64a857185be19181886da22ad8952dcec6e4f8a3bf9bf0578d2fd18` |
| Mission Control common component | MC `packages/mission-control-db-contract/releases/1.7.0/component` | **1.7.0** (53 migrations, keys 0001..0060; 0061 of WI-22 is unreleased and dormant) | schema fingerprint `sha256:ee099c29…64ba`, contract `sha256:f19e0785…9feb`, manifest file `sha256:6134aa4d…5ef1`, source `git:9a32a589…+inputs:sha256:536e14d9…ef86` |
| AI Engineer domain schema | AIDB `supabase/migrations` | contract **0.5.0**, head **20261025010200** (186 migrations) | head file `sha256:83085f4b…4849` |
| Biotech graph schema | BKS `schema/source/biotech-schema-v2.2.0` | **biotech-schema-v2.2.0** | release `sha256:2df9d3bc…5a74`, DDL `sha256:f0622dba…ddb3` |
| K01 protocol | KS `packages/knowledge-operation-protocol` | `ks.knowledge_operation.v2` | unchanged since Sprint V; MC copy under `tests/fixtures/knowledge_protocol` |

### Target locks (Sprint OC)

| App | Lock file | File digest | Written by |
| --- | --- | --- | --- |
| ai-engineer | `sprint-oc/release/locks/ai-engineer/release.lock.json` (57 pinned files) | `sha256:5dcfef94d7f1d32cfd2bbe2e59e9f1b31611ac077150e04350d77ba12ce402b0` | MC `5444f169` |
| biotech | `sprint-oc/release/locks/biotech/release.lock.json` | `sha256:d4c2a84ac43799cb11df7a7e263aa3c1a640adadf10e0098e143ed32b614b925` | MC `5444f169` |

`deployments/<app>/release.lock.json` still names the older releases. Every `mission-db` command below passes the
Sprint OC lock with `--lock` and the release root with `--release-root`. `--deployment-dir` alone would select the
old lock.

### Installers and source commits

| Repository | Commit | Pins it carries |
| --- | --- | --- |
| AIDB `aiengineer/ai-engineer-db-contract` (`scripts/install-ai-engineer.mjs`) | `1dbc810a7eebe00e7aa4a454d4ceea15d92056d9` | KS 2.5.0 `00550d59…`, MC 1.7.0 lock `5dcfef94…` |
| BKS `biotech/biotech-knowledge-services` (`scripts/install-biotech.mjs`) | `6971fed202b6c619e4fd3be46e847e86d5e66005`; `component-grants` step `a43f325` | KS 2.5.0 `00550d59…`, MC 1.7.0 lock `d4c2a84a…`, BKS v2.2.0 |
| KS `platform/knowledge-services` `sprint-oc` | `9b52c08ff51a532d9d451db33865c7992488865c` | component 2.5.0; `MIN_COMPONENT_VERSION` 2.5.0 |
| KS `sprint-oc-w0-finish` | `e4589f0` (capture added in `9cbcfe1`; review fixes N4–N6 in `e4589f0`) | adds `apps/verification-executor/scripts/capture-live-describe.mjs` |
| MC `sprint-oc` | `764e16fd` | release 1.7.0, Application Profiles, model catalogs |
| MC `sprint-oc-w0-finish` | this bundle's commit | describe conformance script and test, local proof driver, this bundle |

The canonical KS checkout's `apps/verification-executor/dist` has been rebuilt at 2.5.0 by the integrator
(2026-10-28) with the build command in section 5.1. The earlier dist predated WI-05 and said
`MIN_COMPONENT_VERSION = "2.4.0"`.

### Model pins (PROOFS §6, `deployments/<app>/models.toml`)

| Role | Profile | Pin | Probe (integrator, 2026-10-28) |
| --- | --- | --- | --- |
| Producer | `producer.default` | `claude-sonnet-5-5` | succeeded |
| Producer fallback, auditor, child | `producer.fallback`, `auditor.default`, `child.default` | `claude-haiku-5-5` | succeeded |
| Judge | `judge.default` | `gpt-5.6-terra` | succeeded |
| Judge fallback, probes | `judge.fallback` | `gpt-5.6-luna` | succeeded |
| Catalog embeddings | (catalog) | `text-embedding-3-small` | succeeded |

The five probes cost under USD 0.001 in total, inside W0's USD 1 allocation. A probe shows only that the model is
available. It does not show isolation.

## 2. Four-owner schema fit

| Owner | Objects on each target | Delivering items | Fit at W0 |
| --- | --- | --- | --- |
| MC common 1.7.0 | `mission_control`, `mission_control_search`, six NOLOGIN `mission_control_*` roles; extensions `vector` and `pg_trgm` in `extensions`; obligations and fulfillment (WI-01), saved execution settlement (0058, WI-04), recorded use decisions (0059, WI-03), hook candidate installs (0060, WI-17) | WI-01..05, WI-17 | installed through `mission-db plan/apply/verify` by both installers (integrator) |
| KS `knowledge_verification` 2.5.0 | operations, report, observation, seal, decision, review, credential use, protocol receipts, effect dispatch journal and fence (0008) | WI-03, WI-05 | installed with application/binding `ai-engineer`/`aiengineer-postgres` and `biotech`/`biotech-graph` (integrator; the upgrade applied only 0008) |
| AIDB domain (AI Engineer) | 18 domain schemas plus `knowledge_service` (binding pin), nine `knowledge_verification_*` grants, forced RLS on custody and four `research` tables | Sprint V SV-17; WI-03/05 use it unchanged | installed by the AIDB installer (integrator); `custody-grants` verifies grants and RLS on every run |
| BKS graph v2.2.0 (Biotech) | Aura graph: release DDL and `KsReleaseMarker`; the PostgreSQL side is the component only | Sprint V SV-D10; WI-05 apply port unchanged | installed by the BKS installer `graph-release` step (integrator) |

The AI Engineer native schema needed no new migration for W0. Its exact-use guard and v2 report projection are the
Sprint V objects that WI-03/05 read (IMPLEMENTATION §4 "AIDB native schemas/projections"). The BKS SDL did not
change either. Neither change claim rests on JSON extensibility: both rest on fields their installers verify.

## 3. Real-installed, doubled and unrun (PROOFS §2, W0 row)

| Evidence | Class | Where |
| --- | --- | --- |
| Wipe of both projects and of the Aura graph | real-installed | integrator, 2026-10-28 ~04:37Z, from clean dry-runs (section 4) |
| Fresh install, repeat `changed: false`, in-place upgrade to KS 2.5.0, repeat `changed: false`, both targets | real-installed | integrator (section 4) |
| Live `knowledge.describe` of each binding against its Application Profile | real composition, local and **remote** (ai-engineer 15/15; biotech see section 5.1) | section 5.1 |
| Interrupted install, then resume | local real installer on `sprint-v-pg17` (AIDB full chain on the AIDB Supabase stub; BKS to the end of `mission-control`); **remote real-installed** (cheap variant, both targets) | sections 6.1, 7 |
| Wrong confirm, wrong installation, wrong `system_identifier`, tampered lock | local real installer and `mission-db`; **remote real refusals**, snapshot-identical | sections 6, 7 |
| Wrong grants | local only (a deliberate REVOKE or GRANT); remotely, no write-free refusal exists | section 7.1 |
| Seed plan/apply of the catalog bundles; custody upload to `capability-bundles` | local, **doubled** (the Storage schema is the AIDB stub; custody is a local directory); **remote real-installed** (Supabase Storage, minted scoped tokens) | section 5.2 |
| Saver schema `mission_control_runtime` (`mission-db runtime-plan` / `runtime-apply`) | local rehearsal on `sprint-v-pg17` (`runners/rehearse_saver.sh`: needs schema `extensions` with `vector` and `pg_trgm`, as Supabase provides); **remote real-installed** (both targets) | section 8.1 |
| Evaluator isolation, trusted ingress, saved-result settlement, native receipt recovery | source plus local service tests of WI-03, WI-04 and WI-05 on `sprint-v-pg17` (merged on `sprint-oc`); not run against the remotes | those items' merge commits |
| W0 negative rows (wrong scope/origin/role, unsupported contract, declared-but-missing promise, same-key changed bytes, stale head/generation, denied review/current use, commit-before-receipt restart, backend access/aggregate refusal) | deterministic local suites of WI-01..05; not run against the remotes | those items' tests |
| Scripted auditor | doubled; disposable-only and unset in the W1 environment | RUNTIME-ENVIRONMENT §3 |
| Any model behaviour beyond the five availability probes | unrun (W1) | PROOFS §2 |

**No test-populated authority.** The remotes hold only what the installers and the reviewed seed bundles write. No
test fixture, scripted auditor receipt or doubled native write was applied to them. Seeded catalog rows are
reviewed data, not behaviour proof (PROOFS §1).

## 4. Remote wipe, install, repeat and upgrade (integrator)

Integrator facts so far:

- **Wipes** ran at 2026-10-28 ~04:37Z, each from a clean dry-run.
  - Biotech dropped `capability_search`, the MC schemas and 832 graph nodes.
  - AI Engineer dropped 18 domain schemas, `knowledge_service`, the MC schemas, 41 `public` tables (86,960 disposable
    rows) and 21 legacy relations allowed by name. It deleted 228 ledger rows and kept 34,773 storage objects.
- Then a fresh install, a repeat with `changed: false`, the upgrade to KS 2.5.0 (only 0008 applied), and a repeat with
  `changed: false`.
- Receipts are in each installer repository's ignored `.scratch/sprint-oc/evidence/` (`wipe/` and
  `install-state/<project_ref>/`). `install-receipt.json` holds only the latest run, so the run rows below cite the
  append-only `progress.jsonl` start timestamps (UTC, 2026-10-28).

| Run | ai-engineer `wkythqbofmckbuoothhn` | biotech `bxnetwiimwhtlrjlbtab` + Aura `8032ec07` |
| --- | --- | --- |
| Wipe dry-run receipt (path, inventory digest) | `wipe/dry-run-wkythqbofmckbuoothhn-20261028T043641.452Z-e6a3.json`, `dry-run-clear`, `sha256:0632a45a…22ce4` (21 legacy relations allowed by name; the earlier `e71a` run was `dry-run-blocked`) | `wipe/dry-run-bxnetwiimwhtlrjlbtab-20261028T043557.049Z-872b.json`, `dry-run-clear`, `sha256:93250b69…13f00` |
| Wipe receipt (path, `changed`, objects dropped) | `wipe/wipe-wkythqbofmckbuoothhn-20261028T043719.319Z-4949.json`, `complete`, `changed: true`, same inventory digest as its dry-run; 18 domain schemas, `knowledge_service`, MC schemas, 41 `public` tables, 228 ledger rows | `wipe/wipe-bxnetwiimwhtlrjlbtab-20261028T043617.894Z-12f2.json`, `complete`, `changed: true`, same digest; `capability_search`, `mission_control_runtime`, `mission_control_search`, `mission_control`, 832 graph nodes |
| Fresh install receipt (path, steps, `changed: true`) | 05:05:52Z: component, domain-migrations, mission-control `applied`; custody-grants `verified`; `changed: true` | 05:11:51Z: component, mission-control, graph-release `applied`, then refused at executor-config (`EXECUTOR_CONFIG_MISSING`, runtime env not yet generated); resumed 05:23:15Z: all `current`, executor-config `verified`, `changed: false`. No single Biotech run reports `changed: true` |
| Repeat receipt (`changed: false`) | 05:11:07Z, all `current`, `changed: false` | 05:23:15Z (above), `changed: false` |
| Upgrade receipt (component `applied: [0008_effect_dispatch_journal]`) | 05:49:59Z: component `applied` (0008 only), others `current`, `changed: true` | 05:50:52Z: component `applied` (0008 only), others `current`, `changed: true` |
| Repeat after upgrade (`changed: false`) | 05:50:20Z, `changed: false` | 05:51:27Z, `changed: false` |
| Component installation id | `7ebb2034-a3d6-41aa-893d-ab655a61593f` | `a34b1309-3f91-4ce1-9eed-3030fdd57b92` |
| MC installation id (`target.toml`) | `01a103c0-9a9e-70f3-9398-eb1573a98324` | `01a103c0-9a9e-7a95-961b-29dda83c842b` |

## 5. Integrator commands: describe capture and seed custody

The commands are PowerShell, run in a session that already holds the target DSN variables the install used.
`$MC` is the canonical Mission Control checkout, `$KS` the canonical KS checkout, `$KSW` the KS worktree
`platform/ks-w0-finish` (until it merges), `$EV = "$MC\.scratch\sprint-oc\evidence\w0"` (ignored). Nothing prints a
value.

### 5.1 Live describe and the Application Profile check

```powershell
# Once: rebuild the 2.5.0 executor and its workspace dependencies in the canonical KS checkout (done by the
# integrator 2026-10-28). `corepack pnpm ... run build` aborts on a non-TTY node_modules reinstall; this form does not.
cd $KS; pnpm --config.verify-deps-before-run=false --workspace-concurrency=1 -r --filter "@aiengineer/knowledge-verification-executor..." run build

# Capture each application's live describe from its generated ks-executor.env (read-only; no secret is written).
node $KSW\apps\verification-executor\scripts\capture-live-describe.mjs `
  --env-file $MC\.scratch\sprint-oc\runtime\ai-engineer\ks-executor.env `
  --executor-dist $KS\apps\verification-executor\dist\index.js `
  --expect-application ai-engineer --out $EV\live-describe.ai-engineer.json
node $KSW\apps\verification-executor\scripts\capture-live-describe.mjs `
  --env-file $MC\.scratch\sprint-oc\runtime\biotech\ks-executor.env `
  --executor-dist $KS\apps\verification-executor\dist\index.js `
  --expect-application biotech --out $EV\live-describe.biotech.json

# Check both profiles against the captures (MC worktree sprint-oc-w0-finish, canonical venv).
cd $MC\.claude\worktrees\w0-finish
$env:PYTHONPATH = "$PWD\src"
& $MC\.venv\Scripts\python.exe scripts\sprint_oc_describe_conformance.py --require-all `
  --capture $EV\live-describe.ai-engineer.json --capture $EV\live-describe.biotech.json `
  --out $EV\describe-conformance.json
# Refresh the offline copy (atomic write). It is refused when any check fails, and when the live registrations differ
# from ks_backend_descriptors.json; the report's descriptorDiff lists every differing field either way. Only after
# reviewing that diff, rerun with --accept-descriptor-change (written only if every check passes against the
# refreshed descriptors) and commit the change to ks_backend_descriptors.json.
& $MC\.venv\Scripts\python.exe scripts\sprint_oc_describe_conformance.py --require-all `
  --capture $EV\live-describe.ai-engineer.json --capture $EV\live-describe.biotech.json `
  --refresh-descriptors --out $EV\describe-refresh.json
```

What the capture does: it calls `startExecutorServer` of the built executor, which is what `knowledge-verify serve`
calls. It uses only the env file's values, with the local capture store moved to a temporary directory. For each
backend it records `KnowledgeOperationService.descriptorFor`, the registry's `BACKEND.describe()` and the served
capabilities. Backends open the component in a READ ONLY transaction, and no K01 operation is called. It exits 2
with `EXECUTOR_COMPOSITION_FAILED` if the env file names another installation (`COMPONENT_INSTALLATION_MISMATCH`)
or the component is older than 2.5.0. `describeDigest` changes per process because `describedAt` is the start
instant. Error details are scrubbed of secrets and of the URL hosts and usernames of DSN-like values; the written
document is refused if any credential value occurs in it.

The check first refuses (exit 2, `CAPTURE_SHAPE`) a capture whose keys or value types differ from
`ks.live-describe-capture.v1`. It then runs these 15 checks per application: `minimums_not_below_annex`,
`describe_digest` (recomputed from `describe` with the capture script's canonical JSON), `binding_advertised`
(served, same application and binding), `descriptor_parses` (MC `BindingDescriptor`), `protocol_pinned`
(`protocolVersions` equals exactly `["ks.knowledge_operation.v2"]`), `component_supported` (≥ 2.5.0),
`pinned_schema` (name equals `--expect-component`, default `knowledge-verification-2.5.0`, and digest equals
`--expect-schema-digest`, default the section 1 release digest), `registration_equals_descriptors` (the registry
`BACKEND.describe()` equals its `ks_backend_descriptors.json` entry exactly, or `--descriptors-file`),
`describe_matches_descriptors` (live `writeAtomicity` and `nativeCancellation` guarantees, protocol versions and
`knowledge.apply` agree with that entry), `apply_contract_equals_native_contract`, `apply_served` (`knowledge.apply`
is listed; for AI Engineer this needs `KNOWLEDGE_DB_URL` in the env file), `storage_class`, `write_atomicity`
(profile, registry and live guarantee), `readback_capability` and `describe_honesty`. Exit 0 means every check
passed; exit 1 means a check failed or a refresh was refused; exit 2 means an input was refused.

| Result | ai-engineer | biotech |
| --- | --- | --- |
| Local, 2026-10-28 (KS 740df8c build, component 2.5.0 on `sprint-v-pg17`; rechecked with the 15-check script) | 15/15 passed; 13 operations including `knowledge.apply`; `auditorKind: none` | 15/15 passed; 13 operations; `auditorKind: none` |
| Remote capture (path, `describeDigest`, executor `distSha256`) | evidence/w0 `live-describe.ai-engineer.json`; `sha256:7a955930…2285`; dist `sha256:b2ac663e…965e` (KS `8986048`, clean); 13 operations, `knowledge-verification-2.5.0` | evidence/w0 `live-describe.biotech.json`; `sha256:a15f079a…2a6e`; same dist; 13 operations, `knowledge-verification-2.5.0`. First attempt refused `EXECUTOR_COMPOSITION_FAILED` (`permission denied to set role knowledge_verification_reader`); fixed by the BKS `component-grants` step (see below) |
| Remote conformance (`status`, failed checks) | `passed`, 15/15, none failed | `passed`, 15/15, none failed (joint run `--require-all`, evidence/w0 `describe-conformance.json`) |
| Descriptor diff; descriptors refreshed (commit, or none when the diff is empty) | empty; none | empty; none |

**W0 finding: the component login could not `SET ROLE` on Biotech.** On Supabase (PG 17.6) the admin `postgres` is not a
superuser and holds the `knowledge_verification_*` roles WITH ADMIN only (`inherit=false`, `set=false`). The KS bindings run
`set local role knowledge_verification_*`, so the Biotech executor refused. AI Engineer works only incidentally, through
`postgres → service_role → AIDB domain roles → knowledge_verification_*`. BKS `a43f325` adds an installer step
`component-grants` (after `component`) that self-grants SET-only membership (`grant <role> to <login> with inherit false,
set true`); remote run 17:35Z `applied`, repeat `current`, `changed: false`. AI Engineer has no equivalent explicit step;
its path depends on AIDB's grants to `service_role` (W1 follow-up, not a W0 failure).

Locally, the live registrations equal `ks_backend_descriptors.json` exactly (`registration_equals_descriptors`,
empty `descriptorDiff`). `tests/conformance/applications/test_live_describe_conformance.py` asserts this and the
refusals: drift from the descriptors fails, a refresh without `--accept-descriptor-change` is refused, a malformed
capture exits 2, and a tampered `describeDigest` fails. 37 tests passed (51 with
`test_application_profiles.py`).

### 5.2 Seed bundles and bundle custody (W0's, per capability-seeds)

Seed apply and custody upload are W0 work. [capability-seeds](../../../../knowledge/capability-seeds.md) says so
(agent-skills 1.0.3, "custody upload and apply are W0's"), and so does the R7 commit `cb7faf4a` (OVE-201). Neither
installer runs them, because both stop at `plan/apply/verify`. Sprint V listed them as unrun (Sprint V bundle §7).
At W1, a launch that selects a skill bundle or hook script is refused with `bundle_custody_unavailable` unless the
bytes are in custody and the reader is configured (`application/authoring/manifest_launch_inputs.py`). Order matters:
seed-apply first, because the common `mc.storage.capability-bundles@1.0.0` creates the private bucket and its
policies. Then upload the bytes.

```powershell
cd $MC\.claude\worktrees\w0-finish   # or $MC after merge; the seeds and locks are identical on sprint-oc
$mdb = "$MC\.venv\Scripts\mission-db.exe"
$v = @("--reader-version","mission-control-runtime/1","--writer-version","mission-control-runtime/1")
$rr = "packages\mission-control-db-contract\releases\1.7.0\component"
# ai-engineer (DSN variable MC_AI_ENGINEER_MIGRATION_DATABASE_URL, named by target.toml)
$a = @("--target","deployments\ai-engineer\target.toml","--lock","docs\specs\provider-consolidation-2026-10\sprint-oc\release\locks\ai-engineer\release.lock.json","--release-root",$rr) + $v + @("--bundle","packages\mission-control-db-contract\seeds\common","--bundle","packages\mission-control-db-contract\seeds\ai-engineer")
& $mdb seed-plan @a > $EV\seed-plan.ai-engineer.json
& $mdb seed-apply @a --confirm-target wkythqbofmckbuoothhn:01a103c0-9a9e-70f3-9398-eb1573a98324 > $EV\seed-apply.ai-engineer.json
& $mdb seed-plan @a > $EV\seed-replan.ai-engineer.json       # expect every bundle "replay"
# biotech (DSN variable MC_BIOTECH_MIGRATION_DATABASE_URL)
$b = @("--target","deployments\biotech\target.toml","--lock","docs\specs\provider-consolidation-2026-10\sprint-oc\release\locks\biotech\release.lock.json","--release-root",$rr) + $v + @("--bundle","packages\mission-control-db-contract\seeds\common","--bundle","packages\mission-control-db-contract\seeds\biotech")
& $mdb seed-plan @b > $EV\seed-plan.biotech.json
& $mdb seed-apply @b --confirm-target bxnetwiimwhtlrjlbtab:01a103c0-9a9e-7a95-961b-29dda83c842b > $EV\seed-apply.biotech.json
& $mdb seed-plan @b > $EV\seed-replan.biotech.json

# Custody upload, one project at a time; the second run must upload nothing (it re-reads and compares).
$env:PYTHONPATH = "$PWD\src"
$env:SUPABASE_URL = "https://wkythqbofmckbuoothhn.supabase.co"
$env:CAPABILITY_BUNDLE_PUBLISHER_TOKEN = <publisher JWT for this project>   # name only here; see the gap below
$env:SUPABASE_PUBLISHABLE_KEY = <this project's publishable key>          # optional apikey header
& $MC\.venv\Scripts\python.exe scripts\seeds_publish_bundles.py --target ai-engineer --storage supabase > $EV\custody.ai-engineer.json
& $MC\.venv\Scripts\python.exe scripts\seeds_publish_bundles.py --target ai-engineer --storage supabase > $EV\custody.ai-engineer.repeat.json
# then the same three variables for https://bxnetwiimwhtlrjlbtab.supabase.co and --target biotech
```

Storage credentials, by name: `SUPABASE_URL`, `CAPABILITY_BUNDLE_PUBLISHER_TOKEN` (publisher) and optionally
`SUPABASE_PUBLISHABLE_KEY`. They are read through MC `Settings`, so the process value wins over `.env`. The script
refuses the service key. The runtime reader at W1 uses `CAPABILITY_BUNDLE_BACKEND=supabase`,
`CAPABILITY_BUNDLE_READER_TOKEN` and `CAPABILITY_BUNDLE_NAMESPACE`. The bucket is `capability-bundles`, and its
policies confine each role to the `<application_id>/` prefix through the JWT claim `mc_capability_role`.

**Risk: the Storage policies.** `mc.storage.capability-bundles@1.0.0` creates policies on `storage.objects`. Live
bucket policies are unqualified (capability-seeds, "Not wired or not published"). If the Supabase admin login may not
create them, `seed-apply` stops at that bundle and reports the bundles it completed before the failure. Its dependents
then stay `pending` in the re-plan. Record that outcome as found; do not work around it.

**Gap: the publisher token.** No tool in the repositories mints a per-project JWT with `role: authenticated` and
`mc_capability_role: publisher` (nor the reader one). The integrator has to supply it (ESCALATION H2). Until then the
custody upload is blocked, and the seed-apply is not.

| Result | ai-engineer | biotech |
| --- | --- | --- |
| Local (Supabase stub DB on `sprint-v-pg17`) | plan 24 bundles pending; apply `seeded`; re-plan 24/24 `replay`; repeat apply wrote no row; bucket `capability-bundles` private | not run on a database (same bundles code path); local custody below |
| Local custody (`--storage local:<dir>`) | 29 bundle uploads, repeat 0 | 30 bundle uploads, repeat 0 |
| Remote seed-plan / seed-apply / re-plan | 24 `pending`, 0 conflicts; `seeded`; 24/24 `replay` (evidence/w0 `seed-{plan,apply,replan}.ai-engineer.json`); the storage policies were created without error | 23 `pending`, 0 conflicts; `seeded`; 23/23 `replay` |
| Remote custody upload / repeat | 29 bundles, 100 objects uploaded; repeat 0 uploaded, 100 verified (HS256 tokens minted from `aiengineer/.env` `SUPABASE_JWT_SECRET`); reader token lists its own prefix (200) | 30 bundles, 129 objects uploaded; repeat 0 uploaded, 129 verified (HS256 from the owner's legacy secret, `secrets/biotech/legacy-jwt.env`) |

## 6. Integrator commands: refusal proofs (each a pure refusal)

Every command below refuses before any write. The surrounding snapshots prove that.

- `mission-db snapshot` digests every non-MC schema: its structure, row counts and in-database row content. That
  covers `knowledge_verification`, the AIDB domain schemas, `knowledge_service` and `storage.buckets`.
- `mission-db verify` re-checks the MC schemas' grant-inclusive fingerprint.
- The refusals never connect to the graph.

`$id` is a fresh UUID (`[guid]::NewGuid()`). Exit 2 with `{"status":"refused","code":...}` (installers) or
`{"status":"blocked",...}` (`mission-db`) is the expected outcome. Use a scratch `--state-dir` so the real
install-state directory is not touched.

```powershell
$AIDB = "C:\Users\Pinda\Proyectos\BellLabs\aiengineer\ai-engineer-db-contract"
$BKS  = "C:\Users\Pinda\Proyectos\BellLabs\biotech\biotech-knowledge-services"
$T_A = "$MC\deployments\ai-engineer\target.toml"; $C_A = "wkythqbofmckbuoothhn:01a103c0-9a9e-70f3-9398-eb1573a98324"
$T_B = "$MC\deployments\biotech\target.toml";     $C_B = "bxnetwiimwhtlrjlbtab:01a103c0-9a9e-7a95-961b-29dda83c842b"
$L_A = "$MC\docs\specs\provider-consolidation-2026-10\sprint-oc\release\locks\ai-engineer\release.lock.json"
$L_B = "$MC\docs\specs\provider-consolidation-2026-10\sprint-oc\release\locks\biotech\release.lock.json"
$id = [guid]::NewGuid().ToString()
# Before (read-only):
& $mdb snapshot --target $T_A --out $EV\snap-before.ai-engineer.json
& $mdb snapshot --target $T_B --out $EV\snap-before.biotech.json

# R1 wrong --confirm-target -> CONFIRM_TARGET_MISMATCH (checked before connecting)
cd $AIDB; node scripts/install-ai-engineer.mjs --remote-reinstall --target $T_A --confirm-target "wkythqbofmckbuoothhn:$id" --component-installation-id 7ebb2034-a3d6-41aa-893d-ab655a61593f --state-dir $EV\r1-a
cd $BKS;  node scripts/install-biotech.mjs --remote-reinstall --target $T_B --confirm-target "bxnetwiimwhtlrjlbtab:$id" --neo4j-uri $env:NEO4J_URI --neo4j-password-env NEO4J_PASSWORD --confirm-graph 8032ec07.databases.neo4j.io --component-installation-id a34b1309-3f91-4ce1-9eed-3030fdd57b92 --state-dir $EV\r1-b
& $mdb apply --target $T_A --lock $L_A --release-root "$MC\$rr" @v --confirm-target "wkythqbofmckbuoothhn:$id" --expected-plan-digest sha256:0   # BLOCKED, no connection
& $mdb seed-apply --target $T_A --lock $L_A --release-root "$MC\$rr" @v --bundle "$MC\packages\mission-control-db-contract\seeds\common" --confirm-target "wkythqbofmckbuoothhn:$id"   # BLOCKED, no connection

# R2 wrong installation: a target copy with another installation_id -> TARGET_IDENTITY_MISMATCH (read-only probe) and VERIFY_HOLD
node -e "const f=require('fs');f.writeFileSync(process.argv[2],f.readFileSync(process.argv[1],'utf8').split(process.argv[3]).join(process.argv[4]))" $T_A $EV\target.wrong.ai-engineer.toml 01a103c0-9a9e-70f3-9398-eb1573a98324 $id
node -e "const f=require('fs');f.writeFileSync(process.argv[2],f.readFileSync(process.argv[1],'utf8').split(process.argv[3]).join(process.argv[4]))" $T_B $EV\target.wrong.biotech.toml 01a103c0-9a9e-7a95-961b-29dda83c842b $id
cd $AIDB; node scripts/install-ai-engineer.mjs --remote-reinstall --target $EV\target.wrong.ai-engineer.toml --confirm-target "wkythqbofmckbuoothhn:$id" --component-installation-id 7ebb2034-a3d6-41aa-893d-ab655a61593f --state-dir $EV\r2-a
cd $BKS;  node scripts/install-biotech.mjs --remote-reinstall --target $EV\target.wrong.biotech.toml --confirm-target "bxnetwiimwhtlrjlbtab:$id" --neo4j-uri $env:NEO4J_URI --neo4j-password-env NEO4J_PASSWORD --confirm-graph 8032ec07.databases.neo4j.io --component-installation-id a34b1309-3f91-4ce1-9eed-3030fdd57b92 --state-dir $EV\r2-b
& $mdb verify --target $EV\target.wrong.ai-engineer.toml --lock $L_A --release-root "$MC\$rr" @v   # VERIFY_HOLD "Database installation identity differs"

# R3 identity evidence with a wrong system_identifier -> TARGET_SYSTEM_IDENTIFIER_MISMATCH
#    (or TARGET_SYSTEM_IDENTIFIER_UNREADABLE when the Supabase login may not read pg_control_system(); both refuse, read-only)
#    region: both projects are us-east-1 (Supabase management API get_project); the installers require a non-empty string.
$now = (Get-Date).ToUniversalTime().ToString("o")
@{source="management-api";project_ref="wkythqbofmckbuoothhn";name="supabase-blue-ocean";region="us-east-1";installation_id="01a103c0-9a9e-70f3-9398-eb1573a98324";system_identifier="1";observed_at=$now} | ConvertTo-Json | Out-File -Encoding ascii $EV\evidence.wrong.ai-engineer.json
@{source="management-api";project_ref="bxnetwiimwhtlrjlbtab";name="biotech-research-ingestion";region="us-east-1";installation_id="01a103c0-9a9e-7a95-961b-29dda83c842b";system_identifier="1";observed_at=$now} | ConvertTo-Json | Out-File -Encoding ascii $EV\evidence.wrong.biotech.json
cd $AIDB; node scripts/install-ai-engineer.mjs --remote-reinstall --target $T_A --confirm-target $C_A --identity-evidence $EV\evidence.wrong.ai-engineer.json --component-installation-id 7ebb2034-a3d6-41aa-893d-ab655a61593f --state-dir $EV\r3-a
cd $BKS;  node scripts/install-biotech.mjs --remote-reinstall --target $T_B --confirm-target $C_B --identity-evidence $EV\evidence.wrong.biotech.json --neo4j-uri $env:NEO4J_URI --neo4j-password-env NEO4J_PASSWORD --confirm-graph 8032ec07.databases.neo4j.io --component-installation-id a34b1309-3f91-4ce1-9eed-3030fdd57b92 --state-dir $EV\r3-b

# R4 tampered lock copy (one checksum digit changed) -> MISSION_CONTROL_LOCK_PIN_MISMATCH (preflight, before the component step)
$tamper = "const f=require('fs');const l=JSON.parse(f.readFileSync(process.argv[1],'utf8'));const k=Object.keys(l.files).sort()[0];l.files[k]=(l.files[k][0]==='0'?'1':'0')+l.files[k].slice(1);f.writeFileSync(process.argv[2],JSON.stringify(l,null,2)+'\n')"
node -e $tamper $L_A $EV\lock.tampered.ai-engineer.json; node -e $tamper $L_B $EV\lock.tampered.biotech.json
cd $AIDB; node scripts/install-ai-engineer.mjs --remote-reinstall --target $T_A --confirm-target $C_A --mc-lock $EV\lock.tampered.ai-engineer.json --component-installation-id 7ebb2034-a3d6-41aa-893d-ab655a61593f --state-dir $EV\r4-a
cd $BKS;  node scripts/install-biotech.mjs --remote-reinstall --target $T_B --confirm-target $C_B --mc-lock $EV\lock.tampered.biotech.json --neo4j-uri $env:NEO4J_URI --neo4j-password-env NEO4J_PASSWORD --confirm-graph 8032ec07.databases.neo4j.io --component-installation-id a34b1309-3f91-4ce1-9eed-3030fdd57b92 --state-dir $EV\r4-b
& $mdb verify --target $T_A --lock $EV\lock.tampered.ai-engineer.json --release-root "$MC\$rr" @v   # BLOCKED "Release checksum mismatch"

# After (read-only): no difference, and MC still verifies.
& $mdb snapshot --target $T_A --out $EV\snap-after.ai-engineer.json; & $mdb compare --before $EV\snap-before.ai-engineer.json --after $EV\snap-after.ai-engineer.json
& $mdb snapshot --target $T_B --out $EV\snap-after.biotech.json;     & $mdb compare --before $EV\snap-before.biotech.json --after $EV\snap-after.biotech.json
& $mdb verify --target $T_A --lock $L_A --release-root "$MC\$rr" @v; & $mdb verify --target $T_B --lock $L_B --release-root "$MC\$rr" @v
```

`$v`, `$rr` and `$mdb` are as in section 5.2; every path here is absolute, so the `cd` between commands does not matter. For
Biotech, `NEO4J_URI` and `NEO4J_PASSWORD` are the names in `install.env`. `--confirm-graph` names the Aura host pinned in
`deployments/biotech/graph.toml` on `sprint-oc` (`8032ec07.databases.neo4j.io`, merged in `abdeefaf`). The refusals
stop before the graph step, so they never connect to the graph.

### 6.1 Interrupted remote run, then resume

- **Cheap variant (no wipe).** Kill an installed target's run after one step, then rerun. The rerun takes over the
  dead owner's lock (`resumedAfterInterruption: true`) and finishes with `changed: false`.
- **Full variant.** Repeat the 04:37Z wipe first (dry-run, then `--from-dry-run`), then kill the fresh install part
  way through. The rerun then applies the rest (`changed: true`), and a repeat reports `changed: false`.

```powershell
cd $AIDB
node scripts/install-ai-engineer.mjs --remote-reinstall --target $T_A --confirm-target $C_A --component-installation-id 7ebb2034-a3d6-41aa-893d-ab655a61593f --interrupt-after component    # exit 1, lock left
node scripts/install-ai-engineer.mjs --remote-reinstall --target $T_A --confirm-target $C_A --component-installation-id 7ebb2034-a3d6-41aa-893d-ab655a61593f                              # resumes
cd $BKS
node --env-file=$MC\.scratch\sprint-oc\runtime\biotech\install.env scripts/install-biotech.mjs --remote-reinstall --target $T_B --confirm-target $C_B --neo4j-uri $env:NEO4J_URI --neo4j-password-env NEO4J_PASSWORD --confirm-graph 8032ec07.databases.neo4j.io --component-installation-id a34b1309-3f91-4ce1-9eed-3030fdd57b92 --interrupt-after mission-control
node --env-file=$MC\.scratch\sprint-oc\runtime\biotech\install.env scripts/install-biotech.mjs --remote-reinstall --target $T_B --confirm-target $C_B --neo4j-uri $env:NEO4J_URI --neo4j-password-env NEO4J_PASSWORD --confirm-graph 8032ec07.databases.neo4j.io --component-installation-id a34b1309-3f91-4ce1-9eed-3030fdd57b92
# check progress.jsonl in the default state dir: two "start" events, resumedAfterInterruption false then true
```

These use the default `--state-dir` (`<repo>/.scratch/sprint-oc/evidence/install-state/<project_ref>`), so the
receipts land beside the earlier ones. If `NEO4J_URI` comes only from `install.env`, `$env:NEO4J_URI` must be set in
the PowerShell session too, because it is expanded on the command line.

| Result | ai-engineer | biotech |
| --- | --- | --- |
| R1 wrong confirm (installer; `mission-db apply`; `seed-apply`) | `CONFIRM_TARGET_MISMATCH`; `apply` BLOCKED "Apply requires exact project-ref:installation-UUID confirmation"; `seed-apply` BLOCKED; all exit 2 | same three refusals, exit 2 |
| R2 wrong installation (installer; `mission-db verify`) | with the real evidence file: `TARGET_IDENTITY_UNPROVEN` (evidence installation differs from target); with evidence matching the wrong target (R2b): `TARGET_IDENTITY_MISMATCH` from the live probe; `verify` `VERIFY_HOLD` "Database installation identity differs from explicit target" | same (`TARGET_IDENTITY_UNPROVEN`, R2b `TARGET_IDENTITY_MISMATCH`, `VERIFY_HOLD`) |
| R3 wrong `system_identifier` | `TARGET_SYSTEM_IDENTIFIER_MISMATCH` (the admin login can read `pg_control_system()`) | `TARGET_SYSTEM_IDENTIFIER_MISMATCH` |
| R4 tampered lock (installer; `mission-db verify`) | `MISSION_CONTROL_LOCK_PIN_MISMATCH`; `verify` BLOCKED "Release checksum mismatch" | same |
| Snapshot compare `identical`; verify `verified` after R1–R4 | `identical`, 0 differences, 0 unallowed; `verified` (1.7.0, `ee099c29…64ba`) | `identical`, 0 differences; `verified` |
| Interrupted then resumed (variant, exit codes, journal, final `changed`) | cheap variant, 16:38Z: `--interrupt-after component` exit 1 (lock left); rerun exit 0, journal `resumedAfterInterruption` false then true, `changed: false` | cheap variant, 16:38Z: `--interrupt-after mission-control` exit 1; rerun exit 0, journal false then true, `changed: false`, executor-config `verified` |

## 7. Local proofs (sprint-v-pg17, 2026-10-28)

The driver is `scripts/sprint_oc_w0_local_proofs.mjs`.

- It builds throwaway `disposable_w0f_*` databases. The AI Engineer one goes through the AIDB Supabase stub, so the
  real 186-migration chain and the Storage seed run on plain PostgreSQL.
- It runs the real installers in `--remote-reinstall` mode against loopback `environment = "disposable"` target files.
- It drops everything at the end: both databases, the stub's three created roles, and the stub extension files.

**28/28 passed.** Evidence (ignored): `platform/mission-control/.scratch/sprint-oc/evidence/w0-finish-local/`
(`w0-local-proofs.json` `sha256:8d9ac8533187966d29ac113434ea527dca6cb3e3285f4afc22658185c77e00dd`, describe
captures and the conformance report). The custody proof row of that run recorded uploaded-list counts; the driver
now requires the first upload's `uploaded_objects` > 0 and the repeat's `uploaded_objects` = 0, and fails on a
missing report (review S6), so a rerun records object counts.

| Proof | ai-engineer | biotech |
| --- | --- | --- |
| `--interrupt-after` (SIGKILL, lock left) | after `component`: exit 1 | after `mission-control`: exit 1 (component and MC 1.7.0 installed; graph not reached) |
| Resume | exit 0, `changed: true`, journal starts `[false, true]` | not run: needs a Neo4j for `graph-release` (memory budget); Sprint V F2 proved it |
| Repeat | `changed: false` | n/a |
| Wrong confirm | `CONFIRM_TARGET_MISMATCH`; `mission-db apply` and `seed-apply` BLOCKED (confirmation) | `CONFIRM_TARGET_MISMATCH` |
| Wrong installation | `TARGET_IDENTITY_MISMATCH`; `mission-db verify` `VERIFY_HOLD` (identity differs) | `TARGET_IDENTITY_MISMATCH` |
| Wrong `system_identifier` evidence | `TARGET_SYSTEM_IDENTIFIER_MISMATCH` | `TARGET_SYSTEM_IDENTIFIER_MISMATCH` |
| Tampered lock | `MISSION_CONTROL_LOCK_PIN_MISMATCH`; `mission-db verify` BLOCKED "Release checksum mismatch" | `MISSION_CONTROL_LOCK_PIN_MISMATCH` |
| Refusals wrote nothing | catalog digest and per-table row counts equal (597 relations, 1,057 rows) | equal (209 relations, 79 rows) |
| Wrong grants (local write to create the drift) | REVOKE one of the nine grants: `GRANTS_DRIFT`; GRANT one `mission_control` table to `anon`: `mission-db verify` `VERIFY_HOLD` (fingerprint not admitted); restored, verify `verified` | BKS `component-grants` (`a43f325`): typed `GRANTS_DRIFT` (direct INHERIT or foreign ADMIN membership); real-PostgreSQL tests (denied before, allowed after, repeat unchanged, drift, superuser) with `INSTALL_WIPE_PG_ADMIN_DSN` on `sprint-v-pg17`, integrator rerun 2026-10-28: 51 passed, 1 skipped (needs the graph), 0 failed; `mission-db verify` is shared |
| `mission-db snapshot` / `compare` around a refused apply | `identical`, 0 differences (plain database `w0f_aie`) | |

### 7.1 Why grants have no remote refusal command

The two grant checks, the AIDB `custody-grants` step (`GRANTS_DRIFT`) and the grant-inclusive MC fingerprint in
`mission-db verify`, refuse only when grants have actually drifted. Making a remote target drift is a write. On the
remotes the evidence is therefore positive: the repeat install's `custody-grants: verified` (nine grants, RLS forced)
and `mission-db verify` `runtime_roles_verified`. An optional write variant on the disposable target is acceptable
under OC-D184, but it is the integrator's choice. It runs `revoke knowledge_verification_reader from app_reader`, a
repeat install (expect `GRANTS_DRIFT`), `grant knowledge_verification_reader to app_reader`, and then a repeat
(`changed: false`).

## 8. W1 prerequisites (RUNTIME-ENVIRONMENT §§4, 6) and review

| Prerequisite | Owner | State |
| --- | --- | --- |
| Independent auditor credential (a second Anthropic key; `EVALUATOR_CREDENTIAL_SHARED` otherwise) and its env name (WI-06) | owner (H2) | missing; the live describe shows `auditorKind: none` |
| Restricted logins `MC_RUNTIME_DSN`, `MC_FAMILY_WRITER_DSN`, `MC_CHECKPOINTER_DSN` per remote (`mission-db apply` creates only NOLOGIN roles) | integrator | W1: identity-gated login tooling in progress (WI-06, `sprint-oc-wi06`); not a W0 criterion |
| Saver schema `mission_control_runtime`: `mission-db runtime-plan` / `runtime-apply` (section 8.1), before the `MC_CHECKPOINTER_DSN` login | integrator | done on both remotes 2026-10-28 (section 8.1), after a local rehearsal |
| Operator deployment file, its binding digest, and `MISSION_CONTROL_RUNTIME_OPTIONS_FACTORY` | integrator / W1 harness | missing |
| Bundle custody reader: `CAPABILITY_BUNDLE_BACKEND=supabase`, `CAPABILITY_BUNDLE_READER_TOKEN`, `CAPABILITY_BUNDLE_NAMESPACE` (absent from the generated `mission-control.env`) | integrator, after section 5.2 | missing |
| Publisher token for the custody upload (section 5.2) | integrator (H2) | missing |
| `BKS_TARGET=production` via `--confirm-graph` for the Aura graph | integrator | generator option |
| Dedicated `knowledge_verification_outbox_worker` login for `BKS_VERIFICATION_DSN` | optional | the admin login is used |
| Canonical KS executor rebuilt at 2.5.0 (section 5.1) | integrator | done 2026-10-28 (`pnpm --config.verify-deps-before-run=false … run build`) |
| Temporal queue collision: both profiles name `biotech-research-ingestion`; run one application's workers at a time or separate namespaces | W1 | open |
| Biotech dispatch drain (what triggers `POST /kg/admission/dispatch/consume`), Agent Server env passthrough, `SET ROLE` of the component login on the remotes, one DSN for component and `KNOWLEDGE_DB_URL`, tenant agreement | W1 | unverified (RUNTIME-ENVIRONMENT §6) |
| Generator fixes of `sprint-oc-w0-runtime-2` (`1cc7b40b`: blank-as-unset settings, full owner `.env` probe) | integrator | done: merged on `sprint-oc` in `abdeefaf` |

### 8.1 Saver schema `mission_control_runtime` (integrator)

`mission-db runtime-apply` runs the bound runtime descriptor (`packages/mission-control-db-contract/runtime/descriptor.json`,
`sha256:b0330c546284548791dffae3c19452952db008fe5b32d36e8cc1a63488b93cfd`, bound in the 1.7.0 manifest's
`runtime_descriptor`). It connects with the migration login of `target.toml` (`database_url_env`), verifies the
common component first, holds the session advisory lock, and writes a per-step receipt. Its first step creates the
NOLOGIN role `mission_control_checkpointer` and the schema; it aborts if a same-named role already exists with
elevated attributes or memberships.

**Order.** Run it after the install and seed steps (section 5.2) and **before** creating the `MC_CHECKPOINTER_DSN`
login. Do not create a role named `mission_control_checkpointer` yourself. Create the checkpointer login and grant it
membership in `mission_control_checkpointer` only after the re-plan reports `complete`. `MC_RUNTIME_DSN` and
`MC_FAMILY_WRITER_DSN` depend only on roles `mission-db apply` already created, so they may be created before or
after. The worker's readiness check (`inspect_checkpoint_binding`) then verifies the checkpointer login.

```powershell
cd $MC\.claude\worktrees\w0-finish   # or $MC after merge; the descriptor and locks are identical on sprint-oc
$mdb = "$MC\.venv\Scripts\mission-db.exe"
$v = @("--reader-version","mission-control-runtime/1","--writer-version","mission-control-runtime/1")
$rr = "packages\mission-control-db-contract\releases\1.7.0\component"
$desc = "packages\mission-control-db-contract\runtime\descriptor.json"
$L_A = "docs\specs\provider-consolidation-2026-10\sprint-oc\release\locks\ai-engineer\release.lock.json"
$L_B = "docs\specs\provider-consolidation-2026-10\sprint-oc\release\locks\biotech\release.lock.json"
$C_A = "wkythqbofmckbuoothhn:01a103c0-9a9e-70f3-9398-eb1573a98324"
$C_B = "bxnetwiimwhtlrjlbtab:01a103c0-9a9e-7a95-961b-29dda83c842b"
# ai-engineer (DSN variable MC_AI_ENGINEER_MIGRATION_DATABASE_URL)
$ra = @("--target","deployments\ai-engineer\target.toml","--lock",$L_A,"--release-root",$rr) + $v + @("--descriptor",$desc)
& $mdb runtime-plan @ra > $EV\runtime-plan.ai-engineer.json        # expect "pending", descriptor_bound_to_release true, no holds
& $mdb runtime-apply @ra --confirm-target $C_A --receipt-out $EV\runtime-apply.ai-engineer.json
& $mdb runtime-plan @ra > $EV\runtime-replan.ai-engineer.json      # expect "complete"
& $mdb runtime-apply @ra --confirm-target $C_A --receipt-out $EV\runtime-apply.ai-engineer.repeat.json   # every step "already_complete"
& $mdb verify --target deployments\ai-engineer\target.toml --lock $L_A --release-root $rr @v   # still "verified"
# biotech (DSN variable MC_BIOTECH_MIGRATION_DATABASE_URL)
$rb = @("--target","deployments\biotech\target.toml","--lock",$L_B,"--release-root",$rr) + $v + @("--descriptor",$desc)
& $mdb runtime-plan @rb > $EV\runtime-plan.biotech.json
& $mdb runtime-apply @rb --confirm-target $C_B --receipt-out $EV\runtime-apply.biotech.json
& $mdb runtime-plan @rb > $EV\runtime-replan.biotech.json
& $mdb runtime-apply @rb --confirm-target $C_B --receipt-out $EV\runtime-apply.biotech.repeat.json
& $mdb verify --target deployments\biotech\target.toml --lock $L_B --release-root $rr @v
# Only now: create the MC_CHECKPOINTER_DSN login per target (member of mission_control_checkpointer only),
# then re-plan once more (expect "complete").
```

| Result | ai-engineer | biotech |
| --- | --- | --- |
| `runtime-plan` before (status, `descriptor_bound_to_release`, holds) | `pending`, `true`, no holds; descriptor `sha256:b0330c54…3cfd` | same |
| `runtime-apply` receipt (path, `status: complete`, steps) | evidence/w0 `runtime-receipt.ai-engineer.json`, `complete`, 17 steps `completed` | `runtime-receipt.biotech.json`, `complete`, 17 steps `completed` |
| Re-plan `complete`; repeat apply all `already_complete` | `complete`; 17/17 `already_complete` | `complete`; 17/17 `already_complete` |
| `mission-db verify` after the runtime phase | `verified` | `verified` |
| Checkpointer login created after the re-plan; final re-plan `complete` | W1 prerequisite (login tooling, WI-06); saver itself `complete` | same |

### 8.2 Independent review

#### Definition-of-done checks (integrator, 2026-10-28)

| Check | Result |
| --- | --- |
| MC full suite on `eae4194e` (all W0 merges) | unit 36 failed (the pre-sprint baseline groups, bisected to `main`) / 6132 passed; conformance + architecture 420 passed; PG17 + Temporal integration 82 passed |
| MC `ruff check .`, `ruff format --check .`, `mypy` (`d27a7b7a`) | clean; clean (2193 files); no issues in 966 source files |
| `python docs/tools/check_docs.py` | 7/7 passed |
| KS `knowledge-db-contract` effect journal, installer and component suites against `sprint-v-pg17` (KS `8986048`) | 23 passed |
| KS WI-05 native recovery: unit; integration across fresh processes (Biotech component PostgreSQL + local Neo4j `bks-neo4j-test` + the real BKS consumer, BKS `a43f325`) | 8 passed; 6 passed |
| BKS `scripts/install-target.test.mjs` with the PostgreSQL DSN | 51 passed, 1 skipped, 0 failed |

#### Recorded limitations (outside W0's required criteria)

1. The remote wrong-grants refusal is not exercised (it needs a write to create drift); grants refusal is proven locally, remote grants are positively verified.
2. The remote interrupt is the cheap variant on installed targets; the full-chain interrupt on a fresh target is local, AI Engineer only.
3. Evaluator isolation, trusted ingress, settlement and native recovery are local service tests, not remote runs (remote use starts at W1).
4. AI Engineer's `SET ROLE` path to the `knowledge_verification_*` roles is incidental (through `service_role`); an explicit AIDB step is a W1 follow-up.
5. Pre-existing baseline failures: 36 unit tests (pre-sprint `main`).
6. `target.toml` says `environment = "production"` while OC-D184 treats both projects as disposable; the identity gates, not the label, authorize the wipes.
7. An aborted AI Engineer start at 05:04:09Z (preflight only, no receipt) precedes the fresh install in `progress.jsonl`.

Independent reviewer: Claude Sonnet 5.5 independent reviewer subagent, 2026-10-28. Verdict: RELEASE WITH RECORDED
LIMITATIONS (the limitations above; its conditions, the section 7 Biotech grants row, the Biotech Neo4j and KS native-recovery
suite status and the lint/type/suite results, are recorded above, with the suites rerun rather than marked unrun). Sections
reviewed: 1, 3, 4, 5.1, 5.2, 6, 6.1, 7, 7.1, 8, 8.1 against evidence/w0, the installer `progress.jsonl` and wipe receipts,
CLAIMS.md, and merges `3c23462f`, `6006d375`, KS `8986048` and BKS `a43f325`.
