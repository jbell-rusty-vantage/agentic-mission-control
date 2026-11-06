#!/usr/bin/env node
// Sprint OC W1 (OVE-169): build the FROZEN source inputs of a W1 fixture.
//
// The pack freezes only what a real task freezes: the task contract (use, audience, obligations,
// rubric/policy references) and the captured sources (one verbatim text_quote fragment per subject,
// with its capture/representation artifact refs). It never authors a claim: the producer writes the
// assertions, support sets and report body itself, and the host computes every KS record digest
// from that content (W1 fix D1, `application/knowledge/report_registration.py`).
//
// Usage (reads only the KS dist of the canonical KS checkout; ids are not secrets):
//   node scripts/sprint_oc_w1_pack.mjs --app ai-engineer --tenant <uuid> --report-id <id> //     [--audience internal|official] [--risk medium|high] --out <ignored evidence path>

import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((pairs, value, index, all) => {
    if (value.startsWith("--")) pairs.push([value.slice(2), all[index + 1]]);
    return pairs;
  }, []),
);
for (const name of ["app", "tenant", "report-id", "out"]) {
  if (!args[name]) throw new Error(`--${name} is required`);
}
const KS = resolve(args["ks-root"] ?? resolve(import.meta.dirname, "../../knowledge-services"));
const load = (pkg) => import(pathToFileURL(resolve(KS, "packages", pkg, "dist/index.js")).href);
const core = await load("research-core");
const protocol = await load("knowledge-operation-protocol");
const { digestBytes } = protocol;

const AS_OF = "2026-10-28T00:00:00Z";
const DEADLINE = "2026-11-30T00:00:00Z";

/** Frozen fixture subjects (OC-D192): one verbatim quote per subject, captured 2026-10-28. */
const FIXTURES = {
  "ai-engineer": {
    binding: "aiengineer-postgres",
    domain: "engineering",
    use: "engineering_reference.model_facts",
    audience: "internal",
    policy: ["policy-ai-engineer", "research-policy.ai-engineer.v2"],
    rubric: ["rubric-engineering", core.ENGINEERING_RUBRIC_VERSION],
    obligation: { id: "finding.size", description: "State each named model's parameter count with its source." },
    subjects: [
      {
        key: "mistral-7b",
        source: "arxiv-2310.06825-abstract",
        header: "Mistral 7B (arXiv:2310.06825), abstract",
        quote: "We introduce Mistral 7B, a 7-billion-parameter language model engineered for superior performance and efficiency.",
      },
      {
        key: "llama-3-1-405b",
        source: "hf-meta-llama-llama-3.1-model-card",
        header: "Meta Llama 3.1 model card, Model Information",
        quote: "a collection of pretrained and instruction tuned generative models in 8B, 70B and 405B sizes",
      },
    ],
  },
  biotech: {
    binding: "biotech-graph",
    domain: "scientific",
    use: "label_reference.ingredients",
    audience: "internal",
    policy: ["policy-biotech", "research-policy.biotech.v2"],
    rubric: ["rubric-scientific", core.SCIENTIFIC_RUBRIC_VERSION],
    obligation: { id: "finding.ingredients", description: "State the frozen product label's listed ingredients with the label source." },
    // One verbatim excerpt of the official supplement-facts table, captured live 2026-10-28T22:20:07Z
    // (Firecrawl scrape 01a18499-32f5-7178-9f02-5ec4f565e7a6, HTTP 200) from
    // https://www.qualialife.com/shop/qualia-mind; captured section sha256
    // 64a129370c9e7ef102c137e107bbe82d7d6666b588cf0110355221adecf221b3 (ignored evidence file).
    subjects: [
      {
        key: "qualia-mind-other-ingredients",
        source: "qualialife-shop-qualia-mind-supplement-facts",
        header: "Qualia Mind 2.0 - Supplement Facts & Ingredients",
        quote: "Other Ingredients: Hypromellose, Rice Flour, L-Leucine, Calcium Silicate, Silica",
        url: "https://www.qualialife.com/shop/qualia-mind",
        capturedAt: "2026-10-28T22:20:07Z",
        captureSha256: "sha256:64a129370c9e7ef102c137e107bbe82d7d6666b588cf0110355221adecf221b3",
      },
    ],
  },
};

const fixture = FIXTURES[args.app];
if (!fixture) throw new Error(`unknown app ${args.app}`);
if (fixture.subjects.length === 0) throw new Error(`${args.app} has no frozen subjects in this pack builder yet`);
const tenant = args.tenant;
const binding = fixture.binding;

const ref = (kind, id, version) => ({
  kind,
  id,
  version,
  digest: digestBytes(`${kind}:${id}`),
  // tenant and binding are filled by the host (report_registration: external refs keep scope).
});

const task = {
  id: `task-${args["report-id"]}`,
  domain: fixture.domain,
  originalTask: ref("artifact", `w1-task-${args.app}`, "artifact.v1"),
  use: fixture.use,
  audience: args.audience ?? fixture.audience,
  obligations: [{ ...fixture.obligation, weight: 10000, required: true }],
  asOf: AS_OF,
  permittedMedia: ["text_markdown"],
  rubric: ref("rubric", fixture.rubric[0], fixture.rubric[1]),
  policy: ref("policy", fixture.policy[0], fixture.policy[1]),
  minimumRisk: args.risk ?? "medium",
  limits: { calls: 20, tokens: 300000, costUsd: "1", deadline: DEADLINE },
};

const fragments = [];
for (const subject of fixture.subjects) {
  // selectedDigest/selectedSize are omitted: the host computes them over the exact quoted bytes.
  fragments.push({
    id: `frag-${subject.key}`,
    sourceVersion: "2026-10-28",
    capture: subject.captureSha256
      ? { ...ref("artifact", `cap-${subject.key}`, "artifact.v1"), digest: subject.captureSha256 }
      : ref("artifact", `cap-${subject.key}`, "artifact.v1"),
    representation: ref("artifact", `rep-${subject.key}`, "artifact.v1"),
    selector: {
      kind: "text_quote",
      value: subject.quote,
      resolverVersion: "text-quote.v3",
      normalizationVersion: "text-norm.v1",
    },
    context: { header: subject.header, footnotes: [], surroundingDigest: null },
    parserLineage: ["frozen-quote.v1"],
    captureCompleteness: "complete",
    access: { rights: "public", limits: [] },
    originFamily: null,
  });
}

const sources = fixture.subjects
  .filter((subject) => subject.url)
  .map(({ key, url, capturedAt, captureSha256 }) => ({ key, url, capturedAt, captureSha256 }));
const pack = { reportId: args["report-id"], task, fragments, ...(sources.length ? { sources } : {}) };
writeFileSync(args.out, JSON.stringify(pack, null, 1), "utf8");
console.log(JSON.stringify({ out: args.out, subjects: fragments.length, use: task.use, audience: task.audience, risk: task.minimumRisk, digest: digestBytes(JSON.stringify(pack)) }));
