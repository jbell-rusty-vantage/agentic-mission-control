#!/usr/bin/env node
// W1 parity oracle (OVE-169): the operation ids Knowledge Services gives trusted operations,
// computed by KS's own code, as golden vectors for Mission Control's `trusted_operation_id`
// (src/mission_control/contracts/knowledge_protocol.py), which recovers a KS-accepted observation
// by `operation.get` without re-sending it.
//
// The id expression and `shortDigest` are private to KS
// `packages/host/src/knowledge-operation/service.ts`; this script extracts their exact source
// text (failing when it changed), evaluates it with the built protocol package's
// `digestCanonical`, and records the KS commit, source lines and text as provenance.
//
// Reads only a Knowledge Services checkout (its source and built `dist`). Regenerate from this
// repo root:
//   node scripts/ks_operation_id_parity.mjs <knowledge-services checkout> \
//     tests/fixtures/knowledge_protocol/ks-operation-id-parity.json
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [ksRoot, out] = process.argv.slice(2);
if (!ksRoot || !out) throw new Error("usage: ks_operation_id_parity.mjs <ks-root> <out.json>");
const protocol = await import(
  pathToFileURL(`${ksRoot}/packages/knowledge-operation-protocol/dist/index.js`).href
);
const ksCommit = execFileSync("git", ["-C", ksRoot, "rev-parse", "HEAD"], { encoding: "utf8" }).trim();
const sourcePath = "packages/host/src/knowledge-operation/service.ts";
const source = readFileSync(`${ksRoot}/${sourcePath}`, "utf8");
const lines = source.split(/\r?\n/);

const idLine = lines.findIndex((line) => line.includes("const operationId = `op-${operation.replace"));
const idMatch = /const operationId = (`op-\$\{operation\.replace\("\.", "-"\)\}-\$\{shortDigest\(\{ tenant: scope\.tenant, operation, requestId: envelope\.requestId \}\)\}`);/.exec(
  lines[idLine] ?? "",
);
if (!idMatch) throw new Error("the KS trusted operation id expression changed; review the MC mirror");
const fnLine = lines.findIndex((line) => line.startsWith("function shortDigest(value: JsonValue): string {"));
const body = (lines[fnLine + 1] ?? "").trim();
if (fnLine < 0 || body !== "return digestCanonical(value).slice(7, 39);" || lines[fnLine + 2] !== "}") {
  throw new Error("KS shortDigest changed; review the MC mirror");
}
const shortDigest = new Function("digestCanonical", `return (value) => { ${body} };`)(protocol.digestCanonical);
const operationIdOf = new Function("shortDigest", "scope", "operation", "envelope", `return ${idMatch[1]};`);

const cases = [
  ["11111111-1111-4111-8111-111111111111", "report.observe", "wi03-3969897dd5370e1339f2aab98875f8766193b7d3"],
  ["11111111-1111-4111-8111-111111111111", "report.seal", "wi03-0000000000000000000000000000000000000000"],
  ["0192a4f0-0000-7000-8000-00000000b10e", "report.decide", "wi03-ffffffffffffffffffffffffffffffffffffffff"],
  ["0192a4f0-0000-7000-8000-00000000b10e", "decision.resolve", "wi03-1234567890abcdef1234567890abcdef12345678"],
  ["tenant-é-unicode", "knowledge.read", "context:report-1/judge"],
];
const vectors = cases.map(([tenant, operation, requestId]) => ({
  tenant,
  operation,
  requestId,
  operationId: operationIdOf(shortDigest, { tenant }, operation, { requestId }),
}));
writeFileSync(
  out,
  `${JSON.stringify(
    {
      schema: "mc.ks-operation-id-parity.v1",
      provenance: {
        knowledgeServicesCommit: ksCommit,
        source: sourcePath,
        idLine: idLine + 1,
        idExpression: idMatch[1],
        shortDigestLine: fnLine + 1,
        shortDigestBody: body,
        digestCanonical: "packages/knowledge-operation-protocol dist digestCanonical",
      },
      vectors,
    },
    null,
    2,
  )}\n`,
);
console.log(JSON.stringify({ out, ksCommit, vectors: vectors.length }));
