#!/usr/bin/env node
// W1 D20 parity oracle (OVE-169): the KS evaluation contexts (`evaluation-context-read/v1`) of the
// registration in tests/fixtures/knowledge_protocol/ks-registration-parity.json, built exactly as
// KS `evaluationContext` builds them (research-core `renderReport` frozen text and units,
// `recordRef` handles, `qualifiersDigest`; the auditor gets no support sets or evidence) and
// checked with the protocol's `EvaluationContextSchema`. Writes
// tests/fixtures/knowledge_protocol/ks-evaluation-context-parity.json; Mission Control's
// evaluator turns these contexts into the census and observations of
// tests/fixtures/knowledge_protocol/mc-evaluator-parity.json, which Knowledge Services validates
// with its own census and observation schemas (KS packages/host mc-evaluator-parity test).
//
// Reads only the built `dist` of a Knowledge Services checkout. Regenerate (from this repo root):
//   node scripts/ks_evaluation_parity.mjs <knowledge-services checkout> \
//     tests/fixtures/knowledge_protocol/ks-evaluation-context-parity.json
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [ksRoot, out] = process.argv.slice(2);
if (!ksRoot || !out) throw new Error("usage: ks_evaluation_parity.mjs <ks-root> <out.json>");
const load = (pkg) => import(pathToFileURL(`${ksRoot}/packages/${pkg}/dist/index.js`).href);
const core = await load("research-core");
const protocol = await load("knowledge-operation-protocol");
const ksCommit = execFileSync("git", ["-C", ksRoot, "rev-parse", "HEAD"], { encoding: "utf8" }).trim();

const parity = JSON.parse(
  readFileSync(new URL("../tests/fixtures/knowledge_protocol/ks-registration-parity.json", import.meta.url), "utf8"),
);
const { tenant, binding, expected } = parity;
const body = core.StructuredBodySchema.parse(expected.report.structuredBody);
const frozen = core.renderReport(body);
const text = frozen.text;
if (protocol.digestBytes(Buffer.from(text, "utf8")) !== frozen.bodyDigest) {
  throw new Error("the frozen body digest is not over the text's UTF-8 bytes");
}
const ref = (kind, id, version, digest) => ({ kind, id, version, digest, tenant, binding });
const report = ref("report", "report-parity-r1", core.REPORT_SCHEMA_VERSION, protocol.digestBytes("report-parity-r1"));
const bodyArtifact = ref("artifact", "report-parity-r1-body", "artifact.v1", frozen.bodyDigest);

function context(role) {
  const judge = role !== "auditor";
  const supportSets = judge
    ? expected.supportSets.map((set) => ({ handle: core.recordRef("support_set", set), record: set }))
    : null;
  const evidence = judge
    ? expected.fragments
        .map((fragment) => ({ handle: core.recordRef("fragment", fragment), record: fragment }))
        .sort((a, b) => (a.handle.id < b.handle.id ? -1 : a.handle.id > b.handle.id ? 1 : 0))
    : null;
  const request = { schema: "evaluation-context-read.v1", report };
  return protocol.EvaluationContextSchema.parse({
    schema: protocol.EVALUATION_CONTEXT_VERSION,
    report,
    revision: "report-parity-r1",
    kind: ref("report_kind", "evidence_report", "research-core.report_kind.v1", protocol.digestBytes("evidence_report")),
    role,
    request: protocol.digestCanonical(request),
    task: {
      handle: core.recordRef("task", expected.task),
      use: expected.task.use,
      audience: expected.task.audience,
      policy: expected.task.policy,
      rubric: expected.task.rubric,
      minimumRisk: expected.task.minimumRisk,
    },
    body: {
      artifact: bodyArtifact,
      digest: frozen.bodyDigest,
      bytes: Buffer.byteLength(text, "utf8"),
      renderer: frozen.renderer,
      text,
    },
    units: frozen.units.map((unit) => ({
      path: unit.path,
      kind: unit.kind,
      span: unit.span === null ? null : { start: unit.span.start, end: unit.span.end },
      factual: unit.factual,
      excludedReason: unit.excludedReason,
    })),
    assertions: expected.assertions.map((assertion) => ({
      handle: core.recordRef("assertion", assertion),
      record: assertion,
      qualifiersDigest: core.qualifiersDigest(assertion.qualifiers),
    })),
    supportSets,
    evidence,
  });
}

const document = {
  provenance: {
    generator: "scripts/ks_evaluation_parity.mjs",
    ksCommit,
    source: "tests/fixtures/knowledge_protocol/ks-registration-parity.json",
  },
  auditor: context("auditor"),
  judge: context("judge"),
};
writeFileSync(out, JSON.stringify(document, null, 1) + "\n", "utf8");
console.log(JSON.stringify({ out, ksCommit, units: frozen.units.length, bodyDigest: frozen.bodyDigest }));
