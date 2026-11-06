# Report/source foundation fixture

This fixture separates submission usability, context delivery, real Knowledge Services persistence,
and paid qualification. Its local checks do not release W1/W2. The current disposition belongs in
[NEXT-SESSION](specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md).

## Service-specific sandbox setup

Prepare an AI Engineer context with the command below, then run:

```powershell
.venv/Scripts/python.exe scripts/report_source_sandbox.py --context .scratch/foundation-aie-context --out .scratch/source-partial-sandbox-<fresh>
.venv/Scripts/python.exe scripts/report_source_sandbox.py --verify --out .scratch/source-partial-sandbox-<fresh>
```

The result is six portable directories under `sandbox/skills/`. Attach each as an exact skill
bundle through the existing Deep Agents materializer; the manifest inventories every byte.
`report-source-procedure/references/START_HERE.md` provides task direction and `SCHEMA_ROUTE.md`
provides targeted contract/task reads. Shared report contracts live beside those directions;
optional entity cards live in the schema-explore bundle. These are fixture-only projections.
Omitted links require targeted canonical retrieval, not guesses or broad schema loading.

Tavily/Firecrawl entries are fixture-authored guidance over host-admitted tools, not upstream
skill distributions or installed binaries. Canonical KS skills retain their bytes except an
explicitly recorded missing-name frontmatter repair. Historical MCP snapshots are not live
tool admission. The operator must select managed KS discovery or direct tools plus self-reported
import, supply the corresponding transport/custody configuration, and verify the capture-to-K01
bridge. The setup itself performs no network calls or installation.

`partial-fixture.json` records limits, preset guidance, agent-authored decisions and required
proofs. The runtime loading test is `test_report_source_sandbox.py`; it proves discovery and
complete instruction/context reads, not service integration. Follow the
[current session instructions](specs/archive/provider-consolidation-2026-10/sessions/SESSION-CODEX-RESUME-2026-10-29.md)
for the bounded service fixture that ends at submission.

## Local preparation and proof

Use the primary MC virtualenv and installed dependencies. BKS must have completed its ordinary
`pnpm build`; KS package outputs must match the source under test. Provide
`MISSION_CONTROL_TEST_ADMIN_DSN` from the verified **local** disposable PostgreSQL target. The
runner never reads repository `.env` files. It creates fresh fixture databases through existing
test helpers and refuses a non-loopback DSN. Do not point it at a remote installation.

Build the KS protocol before the host: a host-only rebuild can import a newly added protocol
export from an older `dist` package and fail before the fixture starts. From the KS repository,
the protocol command is `corepack pnpm --filter @aiengineer/knowledge-operation-protocol build`;
then rebuild `@aiengineer/knowledge-host`. A source-mapped TypeScript check alone does not verify
those runtime package outputs.

```powershell
.venv/Scripts/python.exe scripts/report_source_proof.py --out .scratch/sprint-oc/foundation-proof-<fresh-label>
```

The runner executes serially, saves logs and `matrix.json`, preserves nonzero/timeout exits and
leaves dependent steps unrun after failure. A fresh directory is mandatory. `qualified` is always
false. The matrix records repository HEADs and dirty state; retain the reviewed source diff with
the logs when testing an uncommitted candidate. No paid call or mission launch occurs.

Individual context and fixture preparation:

```powershell
.venv/Scripts/python.exe scripts/report_source_context.py --profile ai-engineer --out .scratch/foundation-aie-context
.venv/Scripts/python.exe scripts/report_source_foundation.py --app ai-engineer --shape repair --context .scratch/foundation-aie-context --out .scratch/foundation-aie-repair
```

Repeat with `biotech`; use `--shape transfer` for the separate StageGraph producer/consumer shape.
These generated manifests use the existing `sprint_oc_w1_driver.py` operator routes and pack/model
substitution. Compile/launch against a configured service only under its explicit run packet.
The repair shape uses GoalDirected with at most three iterations. It is not nested in StageGraph.
It explicitly increments a successfully registered held report's revision, binds `supersedes`
to the prior exact receipt and uses fresh changed-record ids. It does not re-register revision 1.
The transfer shape selects `produce.report`; it does not link to the repair run automatically.
The generated manifest includes verified selected context and records its digest. Native
derive/apply capabilities are excluded.

The inherited replay packs currently contain two model sources for AI Engineer and one label
for Biotech. `fixture.json` records that narrower scope separately from proposed live limits.
The requested two-label fixture remains an unmet qualification case; the renderer does not
manufacture a second label or count the navigation profile as captured evidence.

## What each layer establishes

| Layer | Evidence | Limit |
| --- | --- | --- |
| Submission | `tests/unit/knowledge/test_submission_foundation.py`, PostgreSQL output-contract regressions | Scripted calls; acknowledgements are not fulfillment |
| Canonical subsets | `scripts/report_source_context.py`, profiles and unit tests | Bounded read-only context, not write authority or a complete domain schema |
| Actual receiving bytes | `tests/integration/deep_agents/test_report_source_context.py` | Real Deep Agents StateBackend and paginated scripted reader; plan store is in memory |
| Exact accepted transfer | Existing `test_wi02_dependent_stage_transfer.py` | Real lane; verifying fake KS binding; not the real-service end-to-end chain |
| Joined MC→KS→consumer | `tests/integration/deep_agents/test_report_source_real_service.py` | Real scoped MC tools/stores and KS HTTP/custody, exact Deep Agents read; scripted assessment and controller promotion, not a Temporal mission |
| KS report repair/restart | KS `apps/verification-executor/src/knowledge-operation/report-source-foundation.integration.test.ts` | Real K01 HTTP registration/read, component PostgreSQL, custody and restarted executor; scripted application-direct judge/auditor, not evaluator HTTP/model qualification |

The KS test uses explicitly synthetic replay data. A contradictory first revision remains held;
fresh assertion/support records correct the successor. Scientific qualifiers are used for Biotech,
without clinical inference. Exact captured/body bytes and registration receipts survive restart;
wrong digests and another tenant are refused. No native knowledge application runs.

The context manifest inventories canonical bytes, dependency closure, source fingerprints,
selection, omitted navigation targets, byte counts and explicit LF prompt normalization. AIDB's
materializer retains all vocabularies in its evidence tree; these are not all copied into context.
BKS's advisory slice can be `complete` yet not `compileable`; those distinct flags remain visible.
The BKS domain slice's 12,000-token estimate is not the size of the combined KS/domain context.

## Remaining qualification packet

Before claiming the foundation complete, the joined real-service test must pass and the composed
workflow must preserve its transfer plan across restart/redelivery without duplicate cognition.
The joined test uses controller-supplied assessment and promotion. Its PostgreSQL transfer plan,
journal, lineage and saver support a bounded reconstructed-service redelivery check, while result
payloads and staged inputs retain in-memory fixture custody. It cannot establish full process
recovery or independent evaluator HTTP identity. The separate
KS restart test proves persisted reports and registration replay only. These limits remain even
when all local test steps pass.

Reuse existing KS `source_discover`, `source_attempt`, `source_select`, acquisition/capture and
artifact custody operations. `knowledge/context.ts` composes discovery only with configured
database and artifact storage; `knowledge/operations.ts` otherwise refuses
`SOURCE_DISCOVERY_REMOTE_CUSTODY_REQUIRED`. The provider host admits Tavily/Firecrawl requests;
do not add a parallel search surface or interpret failed searches as absence of evidence.
The foundation manifests currently admit report operations only: search/acquisition capability
bindings and the custody target still need a concrete service-level fixture packet.
The existing KS `source-discovery.integration.test.ts` also requires disposable database **and**
artifact-storage configuration. Component report custody used by the report tests does not
qualify that separate discovery storage route; its target must be verified independently.

Proposed live packet, **not executed or approved by these tests**:

- AI Engineer first: two primary model sources, one named technical property, two to four claims.
- Biotech next: two product labels, listed ingredients only; no clinical efficacy inference.
- Per application: at most three queries, three captured sources, three repair iterations;
  producer/judge/auditor model profiles pinned independently, exact source/tool/policy/schema pins
  saved before launch. Proposed cost ceiling: USD 2 per application, USD 4 total, with hard stop.
- Target: identified local MC/KS service endpoints plus separately approved search/model providers
  and artifact-custody installation. No remote installation, migration, or native graph/entity write.
- Record selected/omitted search results, failed/uncertain attempts, captured bytes, assertions,
  report revisions, assessment/use decisions, sealed transfer and actual receiving-byte receipts.
  Persistent failure stays unmet. URLs/snippets alone are not captured evidence.

Resolve these targets and pins before requesting paid-run approval. The previously approved native
review→application→readback work remains queued afterwards; Swarm/EO and W1/W2 gates are unchanged.


## Submission discovery and repair

**Producer discovery and repair (foundation detour).** The common
[invocation view](../src/mission_control/application/outputs/invocation_view.py) powers
`submit_output({"action":"inspect"})`, optionally narrowed by a full obligation key. It reads
existing invocation pins and the host-bound owner position; it cannot select a tenant, run,
actor or private evaluator result. The projection separates the latest invocation submission's
assessment state, accepted-head revision IDs, and the last recorded fulfillment decision with
its exact frontier ID. A recorded frontier decision is historical evidence, not a fresh evaluation
of current heads. An unbound position refuses; inspection never creates pins.

The default action remains submission with `mode: final`; `progressive` and `expected_head`
are exposed for named promises. `expected_head` names an accepted revision ID. The
[PostgreSQL store](../src/mission_control/adapters/postgres/knowledge/output_contracts.py)
checks it inside the submission transaction under the promotion run lock, after identical replay
and finalization checks. Replaying the same tool-call payload still returns the original revision
after the head moves; changed payloads refuse. Derivation references remain host-only.
Acknowledgements retain findings and label canonical `accepted` as `recorded_draft`; refusals
retain field pointers, retry state, recovery owner, actions and correlation.

For example, after `report_register` returns `result.affected[0]`, copy its `handle` and `digest`
into `submit_output({"obligation":"root.report","items":[{"kind":"handle","ref":handle,
"digest":digest}]})`. Registration creates operational content; independent assessment, promotion
and fulfillment remain separate. Mixed report selections and report collections refuse on the
agent tool surface. A new tool-call ID submits repaired content; the same ID retries identical content.

For a successor registration, set `report.supersedes` to that prior receipt's `{handle, digest}`
and increment `report.revision`. Common registration resolves host scope; the service validates the
exact predecessor. Changing evidence requires fresh changed-record IDs. A new revision does not
inherit an earlier verification decision.

The immutable successor catalog seed is `mc.catalog.knowledge-tools@1.1.0`, with
`tool.knowledge-submit-output@2`; admitted revision-1 component schemas remain served under their
original digests. Focused behavior is covered by
[real tool-binding tests](../tests/unit/knowledge/test_submission_foundation.py) and
[PostgreSQL race/replay tests](../tests/integration/postgres/test_output_contracts_postgres.py).
These local checks do not release W1/W2 or qualify paid provider execution.
