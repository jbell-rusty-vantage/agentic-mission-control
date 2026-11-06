#!/usr/bin/env node
// Sprint OC W0 (WI-24 / OVE-168): local rehearsal, on a loopback disposable PostgreSQL, of every remote W0 command the
// integrator runs: the two root installers in --remote-reinstall mode (interrupted, resumed, repeated), their refusals,
// the mission-db refusals, the seed plan/apply and the local custody upload. Nothing here touches a remote target.
//
// It prepares throwaway `disposable_w0f_*` databases (the AI Engineer one through the AIDB Supabase stub, so the real
// 186-migration chain and the Storage seed run) and removes them, and the stub's cluster-wide roles and extension
// files, at the end. The DSN is read from the variable --admin-dsn-env names and is never printed or written.
//
//   node scripts/sprint_oc_w0_local_proofs.mjs --admin-dsn-env <NAME> --container sprint-v-pg17 --out <ignored dir>
//     [--aidb-root <dir>] [--bks-root <dir>] [--mc-root <dir with .venv>] [--keep]
//
// The evidence (`w0-local-proofs.json`) lists, per proof, the command (credential-free), exit code, refusal code and
// the before/after catalog-and-row-count digests that show a refusal wrote nothing. Exit 0 when every expectation held.
import { spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const option = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : fallback;
};
// The BellLabs umbrella: the nearest ancestor holding both `platform/` and `aiengineer/` (worktrees nest deeper).
const BELLLABS = (() => {
  for (let dir = HERE; dir !== dirname(dir); dir = dirname(dir)) {
    if (existsSync(join(dir, "platform", "knowledge-services")) && existsSync(join(dir, "aiengineer"))) return dir;
  }
  throw new Error("BELLLABS_ROOT_NOT_FOUND");
})();
const canonicalMc = existsSync(join(HERE, ".venv")) ? HERE : join(BELLLABS, "platform", "mission-control");
const aidb = resolve(option("aidb-root", join(BELLLABS, "aiengineer", "ai-engineer-db-contract")));
const bks = resolve(option("bks-root", join(BELLLABS, "biotech", "biotech-knowledge-services")));
const mcRoot = resolve(option("mc-root", canonicalMc));
const out = resolve(option("out", join(HERE, ".scratch", "sprint-oc", "evidence", "w0-local-proofs")));
const container = option("container", "sprint-v-pg17");
const adminDsn = process.env[option("admin-dsn-env", "W0_LOCAL_ADMIN_DSN")];
if (!adminDsn) throw new Error("ADMIN_DSN_MISSING: set the variable --admin-dsn-env names");
const keep = process.argv.includes("--keep");
const exe = process.platform === "win32" ? ".exe" : "";
const venv = (tool) => join(mcRoot, ".venv", process.platform === "win32" ? "Scripts" : "bin", `${tool}${exe}`);
const missionDb = venv("mission-db");
const python = venv("python");
const LOCK = (app) => join(HERE, "docs/specs/provider-consolidation-2026-10/sprint-oc/release/locks", app, "release.lock.json");
const RELEASE = join(HERE, "packages/mission-control-db-contract/releases/1.7.0/component");
const VERSIONS = ["--reader-version", "mission-control-runtime/1", "--writer-version", "mission-control-runtime/1"];
const SEEDS = join(HERE, "packages/mission-control-db-contract/seeds");

const { openStubCluster, prepareStubDatabase, catalogSnapshot } = await import(
  pathToFileURL(join(aidb, "scripts", "install-manifest.mjs")).href
);
const password = (() => {
  try {
    return decodeURIComponent(new URL(adminDsn).password);
  } catch {
    return "";
  }
})();
const scrub = (text) => [adminDsn, password].filter((s) => s && s.length >= 4).reduce((t, s) => t.split(s).join("<redacted>"), String(text ?? ""));
const digest = (value) => `sha256:${createHash("sha256").update(JSON.stringify(value)).digest("hex")}`;
mkdirSync(out, { recursive: true });

const results = [];
let failures = 0;
function expect(name, observed, ok, extra = {}) {
  results.push({ proof: name, passed: Boolean(ok), ...observed, ...extra });
  if (!ok) failures += 1;
  process.stderr.write(`${ok ? "PASS" : "FAIL"} ${name} ${observed.code ?? observed.status ?? ""}\n`);
}

function run(command, args, { cwd, env = {}, display } = {}) {
  const r = spawnSync(command, args, { cwd, env: { ...process.env, ...env }, encoding: "utf8", windowsHide: true, timeout: 1_800_000 });
  const text = scrub(`${r.stdout ?? ""}\n${r.stderr ?? ""}`);
  let body = null;
  for (const candidate of [r.stdout?.trim().split(/\r?\n/).at(-1), r.stdout?.slice(r.stdout.indexOf("{"))]) {
    try {
      body = JSON.parse(candidate ?? "");
      break;
    } catch {
      /* next */
    }
  }
  return { exit: r.status, signal: r.signal, body, tail: text.slice(-600), command: display ?? [command, ...args].join(" ") };
}

const tomlTarget = ({ app, ref, id, port, user, database, envName }) => `format_version = 1

[target]
app = "${app}"
application_id = "${app}"
project_label = "${ref}"
project_ref = "${ref}"
installation_id = "${id}"
environment = "disposable"
database_host = "127.0.0.1"
database_port = ${port}
database_name = "${database}"
database_user = "${user}"
database_url_env = "${envName}"

[approval]
approved_by = "sprint_oc_w0_local_proofs.mjs (loopback disposable rehearsal)"
identity_evidence = "loopback disposable database created by this run"
`;

async function state(pg, dsn) {
  const c = new pg.Client({ connectionString: dsn });
  await c.connect();
  try {
    const catalog = await catalogSnapshot(c);
    const rows = (
      await c.query(`select table_schema || '.' || table_name as rel,
        (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text::bigint as n
        from information_schema.tables where table_type = 'BASE TABLE' and table_schema not in ('pg_catalog', 'information_schema') order by 1`)
    ).rows;
    return { catalog: digest(catalog), rows: digest(rows), relations: rows.length, totalRows: rows.reduce((s, r) => s + Number(r.n), 0) };
  } finally {
    await c.end();
  }
}

// A copy of the app's lock with its first pinned member checksum changed by one hex digit (the checksum probe).
function tamperLock(app, path) {
  const lock = JSON.parse(readFileSync(LOCK(app), "utf8"));
  const member = Object.keys(lock.files).sort()[0];
  lock.files[member] = lock.files[member].replace(/^(.)/, (c) => (c === "0" ? "1" : "0"));
  writeFileSync(path, `${JSON.stringify(lock, null, 2)}\n`);
  return path;
}

async function sql(pg, dsn, text) {
  const c = new pg.Client({ connectionString: dsn });
  await c.connect();
  try {
    return (await c.query(text)).rows;
  } finally {
    await c.end();
  }
}

const suffix = randomUUID().slice(0, 8);
const cluster = await openStubCluster({ adminDsn, container });
const { pg } = cluster;
const created = [];
const evidence = { format: "sprint-oc.w0-local-proofs.v1", startedAt: new Date().toISOString(), container, suffix, results };
try {
  const admin = new URL(adminDsn);
  const port = Number(admin.port || 5432);
  const user = decodeURIComponent(admin.username);
  const ksCli = join(BELLLABS, "platform", "knowledge-services", "packages", "knowledge-db-contract", "dist", "cli.js");

  // ------------------------------------------------------------------------------------ AI Engineer (AIDB installer)
  const aieDb = `disposable_w0f_aie_${suffix}`;
  const prepared = await prepareStubDatabase({ cluster, adminDsn, database: aieDb, ksCli, installComponent: false });
  created.push(aieDb);
  const aieDsn = `${prepared.dsn}?sslmode=disable`;
  const aie = { app: "ai-engineer", ref: `disposable-w0f-aie-${suffix}`, id: randomUUID(), port, user, database: aieDb, envName: "W0F_AIE_TARGET_DSN" };
  const aieComponent = randomUUID();
  const aieTarget = join(out, "aie-target.toml");
  writeFileSync(aieTarget, tomlTarget(aie));
  const aieEnv = { W0F_AIE_TARGET_DSN: aieDsn };
  const aieConfirm = `${aie.ref}:${aie.id}`;
  const aieInstall = (stateDir, extra = [], target = aieTarget, confirm = aieConfirm) =>
    run(process.execPath, ["scripts/install-ai-engineer.mjs", "--remote-reinstall", "--target", target, "--confirm-target", confirm,
      "--component-installation-id", aieComponent, "--mc-root", mcRoot, "--state-dir", stateDir, ...extra], { cwd: aidb, env: aieEnv });

  const aState = join(out, "aie-install");
  const crashed = aieInstall(aState, ["--interrupt-after", "component"]);
  expect("aie.interrupted-after-component", crashed, crashed.exit !== 0 && existsSync(join(aState, "install.lock")));
  const resumed = aieInstall(aState);
  const journal = readFileSync(join(aState, "progress.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
  const starts = journal.filter((e) => e.event === "start").map((e) => e.resumedAfterInterruption);
  expect("aie.resumed", resumed, resumed.exit === 0 && resumed.body?.changed === true && starts.join() === "false,true", { starts });
  const repeat = aieInstall(join(out, "aie-repeat"));
  expect("aie.repeat-changed-false", repeat, repeat.exit === 0 && repeat.body?.changed === false);

  // Refusals: each must leave the catalog and every table's row count unchanged.
  const before = await state(pg, prepared.dsn);
  const refusal = (name, result, code) => expect(name, { ...result, code: result.body?.code ?? null }, result.exit === 2 && result.body?.code === code);
  refusal("aie.refuse.wrong-confirm-target", aieInstall(join(out, "r-confirm"), [], aieTarget, `${aie.ref}:${randomUUID()}`), "CONFIRM_TARGET_MISMATCH");
  const wrongTarget = join(out, "aie-target-wrong-installation.toml");
  const wrongId = randomUUID();
  writeFileSync(wrongTarget, tomlTarget({ ...aie, id: wrongId }));
  refusal("aie.refuse.wrong-installation", aieInstall(join(out, "r-install"), [], wrongTarget, `${aie.ref}:${wrongId}`), "TARGET_IDENTITY_MISMATCH");
  const evidenceFile = join(out, "identity-evidence-wrong-sysid.json");
  writeFileSync(evidenceFile, JSON.stringify({ source: "management-api", project_ref: aie.ref, name: aie.ref, region: "local", installation_id: aie.id,
    system_identifier: "1", observed_at: new Date().toISOString() }));
  refusal("aie.refuse.identity-evidence-wrong-system-identifier", aieInstall(join(out, "r-sysid"), ["--identity-evidence", evidenceFile]), "TARGET_SYSTEM_IDENTIFIER_MISMATCH");
  const tampered = tamperLock("ai-engineer", join(out, "release.lock.tampered.json"));
  refusal("aie.refuse.tampered-lock (installer)", aieInstall(join(out, "r-lock"), ["--mc-lock", tampered]), "MISSION_CONTROL_LOCK_PIN_MISMATCH");
  const mdb = (args, env = aieEnv) => run(missionDb, args, { cwd: HERE, env });
  const blocked = (name, result, pattern) =>
    expect(name, { ...result, code: result.body?.code ?? null, error: result.body?.error ?? null }, result.exit === 2 && pattern.test(result.body?.error ?? ""));
  blocked("aie.refuse.tampered-lock (mission-db verify)", mdb(["verify", "--target", aieTarget, "--lock", tampered, "--release-root", RELEASE, ...VERSIONS]), /checksum|differs|pin/i);
  blocked("aie.refuse.wrong-confirm (mission-db apply)", mdb(["apply", "--target", aieTarget, "--lock", LOCK("ai-engineer"), "--release-root", RELEASE, ...VERSIONS,
    "--confirm-target", `${aie.ref}:${randomUUID()}`, "--expected-plan-digest", "sha256:0"]), /confirmation/i);
  blocked("aie.refuse.wrong-installation (mission-db verify)", mdb(["verify", "--target", wrongTarget, "--lock", LOCK("ai-engineer"), "--release-root", RELEASE, ...VERSIONS]), /identity|installation/i);
  blocked("aie.refuse.wrong-confirm (mission-db seed-apply)", mdb(["seed-apply", "--target", aieTarget, "--lock", LOCK("ai-engineer"), "--release-root", RELEASE, ...VERSIONS,
    "--bundle", join(SEEDS, "common"), "--confirm-target", `${aie.ref}:${randomUUID()}`]), /confirmation/i);
  const after = await state(pg, prepared.dsn);
  expect("aie.refusals-wrote-nothing", { status: "compared", before, after }, before.catalog === after.catalog && before.rows === after.rows);

  // Grants: a deliberate local drift (a write, so local only), then restored.
  await sql(pg, prepared.dsn, "revoke knowledge_verification_reader from app_reader");
  refusal("aie.refuse.grants-drift (installer, after a local REVOKE)", aieInstall(join(out, "r-grants")), "GRANTS_DRIFT");
  await sql(pg, prepared.dsn, "grant knowledge_verification_reader to app_reader");
  const relation = (await sql(pg, prepared.dsn, "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'mission_control' and c.relkind = 'r' order by 1 limit 1"))[0].relname;
  await sql(pg, prepared.dsn, `grant select on mission_control.${relation} to anon`);
  blocked("aie.refuse.grant-drift (mission-db verify, after a local GRANT)", mdb(["verify", "--target", aieTarget, "--lock", LOCK("ai-engineer"), "--release-root", RELEASE, ...VERSIONS]), /fingerprint/i);
  await sql(pg, prepared.dsn, `revoke select on mission_control.${relation} from anon`);
  const restored = mdb(["verify", "--target", aieTarget, "--lock", LOCK("ai-engineer"), "--release-root", RELEASE, ...VERSIONS]);
  expect("aie.verify-after-restore", restored, restored.exit === 0 && restored.body?.status === "verified");

  // Seeds: plan, apply, re-plan (all replay), repeat apply (no change).
  const bundles = ["--bundle", join(SEEDS, "common"), "--bundle", join(SEEDS, "ai-engineer")];
  const seedArgs = ["--target", aieTarget, "--lock", LOCK("ai-engineer"), "--release-root", RELEASE, ...VERSIONS, ...bundles];
  const plan1 = mdb(["seed-plan", ...seedArgs]);
  const pending = (plan1.body?.bundles ?? []).filter((b) => b.status === "pending").length;
  expect("aie.seed-plan", { exit: plan1.exit, status: plan1.body?.status, pending, command: plan1.command }, plan1.exit === 0 && pending > 0);
  const apply1 = mdb(["seed-apply", ...seedArgs, "--confirm-target", aieConfirm]);
  expect("aie.seed-apply", { exit: apply1.exit, status: apply1.body?.status, error: apply1.body?.error ?? null, command: apply1.command }, apply1.exit === 0);
  const plan2 = mdb(["seed-plan", ...seedArgs]);
  const notReplay = (plan2.body?.bundles ?? []).filter((b) => b.status !== "replay").map((b) => `${b.seed_key}@${b.seed_version}:${b.status}`);
  expect("aie.seed-plan-after-apply-all-replay", { exit: plan2.exit, notReplay, bundles: plan2.body?.bundles?.length ?? 0 }, plan2.exit === 0 && notReplay.length === 0);
  const seedBefore = await state(pg, prepared.dsn);
  const apply2 = mdb(["seed-apply", ...seedArgs, "--confirm-target", aieConfirm]);
  const seedAfter = await state(pg, prepared.dsn);
  expect("aie.seed-apply-repeat-no-change", { exit: apply2.exit, status: apply2.body?.status, rowsUnchanged: seedBefore.rows === seedAfter.rows },
    apply2.exit === 0 && seedBefore.rows === seedAfter.rows);
  const bucket = await sql(pg, prepared.dsn, "select id, public from storage.buckets where id = 'capability-bundles'");
  expect("aie.storage-bucket-seeded (Supabase stub)", { status: JSON.stringify(bucket) }, bucket.length === 1 && bucket[0].public === false);

  // Custody upload to a local directory (the Supabase upload needs the publisher token; see the release bundle).
  const custody = join(out, "custody");
  const publish = (target) => run(python, ["scripts/seeds_publish_bundles.py", "--target", target, "--storage", `local:${custody}`], { cwd: HERE, env: { PYTHONPATH: join(HERE, "src") } });
  for (const app of ["ai-engineer", "biotech"]) {
    const first = publish(app);
    const second = publish(app);
    // A null body (no JSON report) fails: the first upload must report objects, the repeat exactly none.
    const objects = (r) => (Number.isInteger(r.body?.uploaded_objects) ? r.body.uploaded_objects : null);
    expect(`${app}.custody-local-upload-then-idempotent`,
      { exit: first.exit, secondExit: second.exit, firstUploadedObjects: objects(first), secondUploadedObjects: objects(second),
        secondVerifiedObjects: second.body?.verified_objects ?? null, command: first.command },
      first.exit === 0 && second.exit === 0 && first.body != null && second.body != null
        && objects(first) > 0 && objects(second) === 0);
  }

  // ------------------------------------------------------------------------------------- Biotech (BKS installer gates)
  const bioDb = `disposable_w0f_bio_${suffix}`;
  const adminUrl = new URL(adminDsn);
  await sql(pg, adminDsn, `create database ${bioDb}`);
  created.push(bioDb);
  adminUrl.pathname = `/${bioDb}`;
  adminUrl.hostname = "127.0.0.1";
  const bioDsn = `${adminUrl.toString()}?sslmode=disable`;
  const bio = { app: "biotech", ref: `disposable-w0f-bio-${suffix}`, id: randomUUID(), port, user, database: bioDb, envName: "W0F_BIO_TARGET_DSN" };
  const bioTarget = join(out, "bio-target.toml");
  writeFileSync(bioTarget, tomlTarget(bio));
  const bioConfirm = `${bio.ref}:${bio.id}`;
  const graph = ["--neo4j-uri", "neo4j://127.0.0.1:7690", "--neo4j-password-env", "W0F_UNUSED_NEO4J_PASSWORD", "--confirm-graph", "127.0.0.1"];
  const bioInstall = (stateDir, extra = [], target = bioTarget, confirm = bioConfirm) =>
    run(process.execPath, ["scripts/install-biotech.mjs", "--remote-reinstall", "--target", target, "--confirm-target", confirm, ...graph,
      "--component-installation-id", randomUUID(), "--mc-root", mcRoot, "--state-dir", stateDir, ...extra], { cwd: bks, env: { W0F_BIO_TARGET_DSN: bioDsn } });
  const bState = join(out, "bio-install");
  const bCrash = bioInstall(bState, ["--interrupt-after", "mission-control"]);
  expect("bio.interrupted-after-mission-control (component + MC 1.7.0 installed; graph not reached)", bCrash, bCrash.exit !== 0 && existsSync(join(bState, "install.lock")));
  const bBefore = await state(pg, bioDsn.replace("?sslmode=disable", ""));
  refusal("bio.refuse.wrong-confirm-target", bioInstall(join(out, "b-confirm"), [], bioTarget, `${bio.ref}:${randomUUID()}`), "CONFIRM_TARGET_MISMATCH");
  const bioWrong = join(out, "bio-target-wrong-installation.toml");
  const bioWrongId = randomUUID();
  writeFileSync(bioWrong, tomlTarget({ ...bio, id: bioWrongId }));
  refusal("bio.refuse.wrong-installation", bioInstall(join(out, "b-install"), [], bioWrong, `${bio.ref}:${bioWrongId}`), "TARGET_IDENTITY_MISMATCH");
  const bioEvidence = join(out, "bio-identity-evidence-wrong-sysid.json");
  writeFileSync(bioEvidence, JSON.stringify({ source: "management-api", project_ref: bio.ref, name: bio.ref, region: "local", installation_id: bio.id,
    system_identifier: "1", observed_at: new Date().toISOString() }));
  refusal("bio.refuse.identity-evidence-wrong-system-identifier", bioInstall(join(out, "b-sysid"), ["--identity-evidence", bioEvidence]), "TARGET_SYSTEM_IDENTIFIER_MISMATCH");
  const bioTampered = tamperLock("biotech", join(out, "bio-release.lock.tampered.json"));
  refusal("bio.refuse.tampered-lock (installer)", bioInstall(join(out, "b-lock"), ["--mc-lock", bioTampered]), "MISSION_CONTROL_LOCK_PIN_MISMATCH");
  const bAfter = await state(pg, bioDsn.replace("?sslmode=disable", ""));
  expect("bio.refusals-wrote-nothing", { status: "compared", before: bBefore, after: bAfter }, bBefore.catalog === bAfter.catalog && bBefore.rows === bAfter.rows);
} finally {
  if (!keep) {
    for (const database of created) await sql(pg, adminDsn, `drop database if exists ${database} with (force)`).catch(() => undefined);
  }
  const cleanup = await cluster.close();
  evidence.cleanup = { droppedDatabases: keep ? [] : created, stubCleanup: cleanup };
  evidence.finishedAt = new Date().toISOString();
  evidence.failures = failures;
  const text = `${JSON.stringify(evidence, null, 2)}\n`;
  writeFileSync(join(out, "w0-local-proofs.json"), scrub(text));
}
process.stdout.write(`${JSON.stringify({ status: failures ? "failed" : "passed", failures, proofs: results.length, evidence: join(out, "w0-local-proofs.json") })}\n`);
process.exit(failures ? 1 : 0);
