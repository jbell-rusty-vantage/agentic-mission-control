#!/usr/bin/env node
// W1 D1 parity oracle (OVE-169): build complete `research-report/v2` registrations with the KS
// libraries themselves (research-core `recordRef`, `qualifiersDigest` and strict record schemas;
// protocol `digestBytes`) and write tests/fixtures/knowledge_protocol/ks-registration-parity.json.
// tests/unit/knowledge/test_report_registration.py checks that the model-shaped content of each
// registration (`tests.fixtures.knowledge_binding.model_content`) canonicalizes, in Mission
// Control, to exactly these bytes.
//
// Reads only the built `dist` of a Knowledge Services checkout (run `pnpm build` there first);
// records that checkout's commit in the fixture's `provenance`. Regenerate (from this repo root):
//   node scripts/ks_registration_parity.mjs <knowledge-services checkout> \
//     tests/fixtures/knowledge_protocol/ks-registration-parity.json
// Every id and digest here is fixture data; no secret, tenant or installation of a real target.
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [ksRoot, out] = process.argv.slice(2);
if (!ksRoot || !out) throw new Error("usage: ks_registration_parity.mjs <ks-root> <out.json>");
const load = (pkg) => import(pathToFileURL(`${ksRoot}/packages/${pkg}/dist/index.js`).href);
const core = await load("research-core");
const { digestBytes } = await load("knowledge-operation-protocol");
const ksCommit = execFileSync("git", ["-C", ksRoot, "rev-parse", "HEAD"], { encoding: "utf8" }).trim();

const tenant = "7f3e2d1c-0b9a-4876-9543-210fedcba987";
const binding = "aiengineer-postgres";
const producer = {
  kind: "mission_invocation",
  installationId: "0b6a2c1e-4d3f-4a5b-8c7d-112233445566",
  applicationId: "ai-engineer",
  tenantId: tenant,
  issuer: "mission-control.ai-engineer",
  subject: "mission-control-runtime",
  mission: {
    missionId: "run-parity",
    runId: "run-parity",
    activationId: "6f1d3c2a-8b4e-5d7f-9a1b-2c3d4e5f6a7b",
    operationId: "stage/draft",
    operationAttempt: 1,
    executionGeneration: 1,
    lane: "deep_agents",
  },
  recoveryAuthorityRef: null,
  invocationId: "inv-parity",
  authenticatedAt: "2026-10-28T12:00:00Z",
};
const artifact = (kind, id, version = "artifact.v1") => ({
  kind,
  id,
  version,
  digest: digestBytes(id),
  tenant,
  binding,
});
const qualifiers = (entity) => ({
  profile: "engineering.v2",
  entity,
  population: null,
  time: null,
  unit: "parameters",
  jurisdiction: null,
  baseline: null,
  negation: false,
  modality: "asserted",
  comparison: null,
  runtime: null,
  softwareVersion: null,
  configuration: null,
  benchmarkEnvironment: null,
  denominator: null,
  repositoryCommit: null,
});

const task = core.VerificationTaskContractSchema.parse({
  schemaVersion: core.TASK_SCHEMA_VERSION,
  id: "task-parity",
  tenant,
  binding,
  domain: "engineering",
  originalTask: artifact("artifact", "w1-task-ai-engineer"),
  use: "engineering_reference.model_facts",
  audience: "internal",
  obligations: [{ id: "finding.size", description: "State each size with its source.", weight: 10000, required: true }],
  asOf: "2026-10-28T00:00:00Z",
  permittedMedia: ["text_markdown"],
  rubric: artifact("rubric", "rubric-engineering", core.ENGINEERING_RUBRIC_VERSION),
  policy: artifact("policy", "policy-ai-engineer", "research-policy.ai-engineer.v2"),
  minimumRisk: "medium",
  limits: { calls: 20, tokens: 300000, costUsd: "1", deadline: "2026-11-30T00:00:00Z" },
});

const fragment = (key, selector, selected) =>
  core.EvidenceFragmentSchema.parse({
    schemaVersion: core.FRAGMENT_SCHEMA_VERSION,
    id: `frag-${key}`,
    tenant,
    binding,
    sourceVersion: `${key}@2026-10-28`,
    capture: artifact("artifact", `capture-${key}`),
    representation: artifact("artifact", `representation-${key}`),
    selector: { ...selector, resolverVersion: `${selector.kind.replace("_", "-")}.v3`, normalizationVersion: "text-norm.v1" },
    selectedDigest: digestBytes(selected),
    selectedSize: Buffer.byteLength(selected, "utf8"),
    context: { header: `${key} source`, footnotes: [], surroundingDigest: null },
    parserLineage: ["frozen-quote.v1"],
    captureCompleteness: "complete",
    access: { rights: "public", limits: [] },
    originFamily: null,
  });
// Shape 1: text quotes (the host computes the digest and size of the exact quoted bytes; one
// non-ASCII quote). Shape 2: a page region, whose selected bytes come from the capture: the
// digest and size are given and the host keeps them.
const mistralQuote =
  "We introduce Mistral 7B, a 7-billion-parameter language model engineered for superior performance and efficiency.";
const gemmaQuote = "ranging in scale from 2 billion to 27 billion parameters — “lightweight”, state-of-the-art.";
const fragments = [
  fragment("mistral-7b", { kind: "text_quote", value: mistralQuote }, mistralQuote),
  fragment("gemma-2-27b", { kind: "text_quote", value: gemmaQuote }, gemmaQuote),
  fragment(
    "llama-3-1-card",
    { kind: "page_region", value: "page 1, table 'Model Information', rows 1-3" },
    "| Llama 3.1 | 8B | 70B | 405B |",
  ),
];

const assertion = (id, fields) =>
  core.AssertionVersionSchema.parse({
    schemaVersion: core.ASSERTION_SCHEMA_VERSION,
    id,
    tenant,
    binding,
    object: null,
    riskReasons: [],
    producer,
    premises: [],
    ...fields,
  });
const base = assertion("asr-mistral-7b", {
  logicalId: "mistral-7b-size",
  proposition: "Mistral 7B is a language model with 7 billion parameters.",
  kind: "source_report",
  value: { type: "quantity", amount: "7000000000", unit: "parameters" },
  subject: "mistral-7b",
  qualifiers: qualifiers("mistral-7b"),
});
const gemma = assertion("asr-gemma-2-27b", {
  logicalId: "gemma-2-27b-size",
  proposition: "The largest Gemma 2 model has 27 billion parameters.",
  kind: "source_report",
  value: { type: "quantity", amount: "27000000000", unit: "parameters" },
  subject: "gemma-2-27b",
  qualifiers: qualifiers("gemma-2-27b"),
});
const ratio = assertion("asr-ratio", {
  logicalId: "gemma-over-mistral",
  proposition: "The largest Gemma 2 model is larger than Mistral 7B.",
  kind: "derivation",
  value: { type: "none" },
  subject: "gemma-2-27b",
  object: "mistral-7b",
  qualifiers: qualifiers("gemma-2-27b"),
  premises: [core.recordRef("assertion", base), core.recordRef("assertion", gemma)],
});
const assertions = [base, gemma, ratio];
const fragOf = (key) => core.recordRef("fragment", fragments.find((f) => f.id === `frag-${key}`));
// Shape 3: support for an assertion of an EARLIER report (an external, complete ref with its own
// qualifier digest), with contrary evidence.
const earlier = {
  kind: "assertion",
  id: "asr-earlier-llama",
  version: core.ASSERTION_SCHEMA_VERSION,
  digest: digestBytes("asr-earlier-llama"),
  tenant,
  binding,
};
const supportSet = (id, fields) =>
  core.SupportSetSchema.parse({ schemaVersion: core.SUPPORT_SET_SCHEMA_VERSION, id, tenant, binding, contrary: [], ...fields });
const supportSets = [
  supportSet("ss-mistral-7b", {
    assertion: core.recordRef("assertion", base),
    qualifiersDigest: core.qualifiersDigest(base.qualifiers),
    provenance: "declared_citation",
    required: [{ premise: "size", evidence: [fragOf("mistral-7b")], derivedFrom: [] }],
  }),
  supportSet("ss-ratio", {
    assertion: core.recordRef("assertion", ratio),
    qualifiersDigest: core.qualifiersDigest(ratio.qualifiers),
    provenance: "declared_citation",
    required: [
      {
        premise: "sizes",
        evidence: [fragOf("gemma-2-27b")],
        derivedFrom: [core.recordRef("assertion", base), core.recordRef("assertion", gemma)],
      },
    ],
  }),
  supportSet("ss-earlier-llama", {
    assertion: earlier,
    qualifiersDigest: core.qualifiersDigest(qualifiers("llama-3-1-405b")),
    provenance: "replacement_search",
    required: [{ premise: "card", evidence: [fragOf("llama-3-1-card")], derivedFrom: [] }],
    contrary: [fragOf("mistral-7b")],
  }),
];
const claim = (record, text) => ({
  type: "claim",
  occurrenceId: `occ-${record.id}`,
  assertion: core.recordRef("assertion", record),
  text,
  obligations: ["finding.size"],
  attribution: null,
});
const text = (value) => [{ type: "text", text: value }];
const structuredBody = core.StructuredBodySchema.parse({
  schemaVersion: core.STRUCTURED_BODY_SCHEMA_VERSION,
  sections: [
    {
      id: "findings",
      heading: text("Findings"),
      headingExcludedReason: null,
      blocks: [
        {
          type: "paragraph",
          id: "p1",
          inlines: [claim(base, "Mistral 7B has 7 billion parameters"), { type: "citation", label: "c1", fragment: fragOf("mistral-7b") }],
          excludedReason: null,
        },
        {
          type: "list",
          id: "l1",
          ordered: false,
          items: [[claim(ratio, "Gemma 2 27B is larger"), { type: "citation", label: "c2", fragment: fragOf("gemma-2-27b") }]],
          excludedReason: null,
        },
        {
          type: "table",
          id: "t1",
          header: [text("Model"), text("Size")],
          rows: [[text("Gemma 2"), [claim(gemma, "27 billion"), { type: "citation", label: "c3", fragment: fragOf("gemma-2-27b") }]]],
          caption: [{ type: "text", text: "Sizes " }, { type: "citation", label: "c4", fragment: fragOf("llama-3-1-card") }],
          excludedReason: null,
          headerExcludedReason: null,
        },
      ],
    },
  ],
});
const expected = {
  task,
  fragments,
  assertions,
  supportSets,
  report: { reportId: "report-parity", revision: 1, kind: "evidence_report", structuredBody },
};
const provenance = {
  generator: "scripts/ks_registration_parity.mjs",
  ksCommit,
  command: "node scripts/ks_registration_parity.mjs <knowledge-services checkout> tests/fixtures/knowledge_protocol/ks-registration-parity.json",
};
writeFileSync(out, JSON.stringify({ provenance, tenant, binding, producer, expected }, null, 1) + "\n", "utf8");
console.log(JSON.stringify({ out, ksCommit, digest: digestBytes(JSON.stringify(expected)) }));
