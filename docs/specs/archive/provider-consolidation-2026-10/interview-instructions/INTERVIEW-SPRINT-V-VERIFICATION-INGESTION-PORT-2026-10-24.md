---
type: Interview Instruction
title: "Sprint V interview: verification, ingestion, reports and the Mission Control <-> Knowledge Services port"
description: "At most fifteen questions that produce the implementation plan for the sprint the owner calls 'the sprint before': bring the evidence-verification-report system to enterprise research grade (good enough for the medical sciences), complete the Knowledge Services proposals for it, and build the Mission Control <-> Knowledge Services port for verification, ingestion and context from the application-knowledge-boundary projection, with the data migrations across all stores, in an order that never has to be undone."
tags: [mission-control, knowledge-services, interview, sprint, verification, ingestion, reports, migration]
date: 2026-10-24
prepared_by_model: "Claude Fable 5.1"
source_commits: "mission-control 8de6fab9 (working tree with IA-07/SP-10); knowledge-services 50caaa4 (main, clean); biotech-knowledge-services d042678; ai-engineer-db-contract c809a11 (working copy 0.4.16)"
prerequisite_answers: answers/application-knowledge-boundary/claude-fable-5-1-2026-10-24/ANSWERS.md
prerequisite_projection: APPLICATION-KNOWLEDGE-BOUNDARY-DESIGN.md
status: archived
archived: 2026-11-02
archived_from: INTERVIEW-SPRINT-V-VERIFICATION-INGESTION-PORT-2026-10-24.md
archived_reason: "interview held and converted (AS-D25)"
---

> **Archived 2026-11-02** (interview held and converted (AS-D25)). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Sprint V interview: verification, ingestion, reports and the port

## 1. Purpose and place in the sequence

The owner asked for this on **2026-10-24**, after accepting the prerequisite application-knowledge-boundary
interview (IA-07, OC-D79..105) and its projection (SP-10). Verbatim:

> At one level the first suggested sprint should concern mission control <-> knowledge services connection and porting . I want the ingestion services and verification/evidence/report which really means verification + ingestion . Effectively I want to implement much of your application knowledge boundary design module map stuff as is logical . This includes knowledge services work, mission control work and the data migrations across all storage.

> There are proposals in knowledge services for an enhancement to the evidence - verification - report system. I WANT THIS COMPLETED AS WELL !

> I want the agent to take the stance of a real enterprise research system that is good enough for medical sciences. That is the level we want.

> We should be able to incrementally progress forward without having to back track later on.

> I don't want to confuse our sequence. I'm calling it the sprint before but it is really part of mission control output contracts context management and transfer and everything we are on.

The sequence this sitting sits in:

1. Accepted checkpoint IA-06 (OC-D27..78) and prerequisite answers IA-07 (OC-D79..105) with SP-10.
2. **This interview (IQ-06):** the plan for **Sprint V** (verification, ingestion, reports, the port). It
   absorbs the Knowledge Services binding scope of sprint card K in the [sprint sequence](../proposals/SPRINT-SEQUENCE-2026-10-23.md#k-the-domain-family-and-the-knowledge-services-binding)
   and the migration programme A0/A/B/C/D of SP-10 §7 (OC-D102). It precedes OC-1.
3. Sprint V runs, wave by wave; each wave's proof is recorded before the next starts.
4. The **final output-contract/context-transfer interview** ([IQ-07](INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md))
   on the baseline Sprint V leaves, then its issues and sprint.

This sitting decides and plans; it builds nothing and files no external issue. The plan it produces is
what the owner reviews before filing. Decision ids use a new family, `SV-D1..`; output-contract decisions
stay in `OC-D`; question ids are `SV-Q1..15`.

## 2. Required session outputs

- **`answers/sprint-v/<model>-<YYYY-MM-DD>/ANSWERS.md`** (IA-08): the template shape, owner's words
  separate from interpretation, every question answered or recorded as an assumption, status `final` at
  close. Front matter records model, timezone, interview id and the four repository commits.
- **`SPRINT-V-PLAN.md`** (new, kind *session instruction*): the implementation plan. Waves in order, each
  wave with: repositories touched, the modules of SP-10 §2 it builds, the Knowledge Services V-issues and
  SP-10 migration letters it realizes, acceptance proofs by tier (T0 offline, T1 local PostgreSQL/Temporal
  or local Neo4j, T2 paid), budget, and the exact artefact the next wave depends on. The plan ends with
  the issue list (one row per issue, repository, provenance ids) ready to file after the owner reads it.
- **Projection updates:** SP-10 §7 gets the exact migration file names and the wave each belongs to;
  a new section §4.9 "Verification core" projects the Knowledge Services modules this interview decides
  (records, ports, bindings, sealer, oracle) with typed signatures, following `architecture-projection`.
- **Knowledge Services side:** a dated amendment note appended to
  `platform/knowledge-services/docs/specifications/evidence-verification-system-20261017/README.md` §8
  recording which V-issues, amendments A1..A5 and which proposed records Sprint V adopts, and which
  it defers, with the SV-D ids. The Knowledge Platform packet issues (`docs/specs/belllabs-knowledge-platform/issues/`,
  Linear OVE-91 onward) are the existing tracker rows for V01..V14; Sprint V comments on them rather than
  duplicating them.

## 3. Read first, then verify only the needed facts

In this order:

1. [IA-07 answers](../answer-sets/application-knowledge-boundary/claude-fable-5-1-2026-10-24/ANSWERS.md): the
   decisions and the verified source tables (Mission Control, shared KS, Biotech, AI Engineer schema).
2. [SP-10 projection](../specs/APPLICATION-KNOWLEDGE-BOUNDARY-DESIGN.md): §2 module map, §4.0 identities, §4.6
   reverse path, §7 migration map, §8 failure matrix.
3. Knowledge Services, at `platform/knowledge-services` (HEAD 50caaa4, clean main; the owner has
   checkpointed it):
   - [Evidence and verification system, consolidated proposal 2026-10-17](../../../../../../knowledge-services/docs/specifications/evidence-verification-system-20261017/README.md):
     §1 decisions, §2.1 stage table, §3 levels and routing, §5 Biotech vs AI Engineer, §6 implementation
     position, §7 "not established", §8 amendments A1..A5.
   - [Verification annex of the Knowledge Platform packet](../../../../../../knowledge-services/docs/specs/belllabs-knowledge-platform/VERIFICATION.md):
     §3 required records (`VerificationTaskContract`, `AssertionVersion`, `AssertionOccurrence`,
     `EvidenceFragment`, `SupportSet`, `VerificationObservation`, `AuthorityObservation`,
     `CalibrationProfile`, `UseDecision`, `VerificationRun`) and the eight-step algorithm; §4 rubric
     profiles; §5 persistence and the Biotech admission flow; §9 slices V01..V15 with acceptance tests.
   - [Research proposal "Evidence that earns its cost"](../../../../../../knowledge-services/docs/specifications/evidence-research-proposal-20260927/README.md)
     and its [evaluation protocol](../../../../../../knowledge-services/docs/specifications/evidence-research-proposal-20260927/evaluation-protocol.md):
     the seven properties, the seven-part evidence record, levels L0..L3, the 120-task suite, sixteen
     metrics, arms B0..B4, nine gates, the pilot ask (24 tasks, 300 USD, 60 expert hours).
   - [Content services proposal 2026-10-17](../../../../../../knowledge-services/docs/specifications/content-services-20261017/README.md)
     §2: the report catalogue (ten kinds with obligation templates), the one report envelope and its two
     store mappings, the derivation paths, `report_derive`, the four clocks.
   - [As-built verification docs](../../../../../../knowledge-services/docs/verification/README.md): what runs
     today (31 proved / 8 partial / 7 missing on 2026-09-08), the open VR rows that need external inputs.
   - Packet issues: `docs/specs/belllabs-knowledge-platform/issues/04-v01.md` … `38-v13.md`, `20-q01.md`
     (Biotech v2 schema adoption boundary, `ready-for-human`, OVE-131).
4. Mission Control: the [sprint sequence](../proposals/SPRINT-SEQUENCE-2026-10-23.md) card K and the sprint table;
   the [domain provenance supplement](../proposals/DOMAIN-PROVENANCE-AND-STATE-SUPPLEMENT-2026-10-23.md)
   DP-D4..D11; the [human review gates supplement](../../../proposals-2026-10/HUMAN-REVIEW-GATES-AND-STEERING-SUPPLEMENT-2026-10-22.md)
   (platform root) for the L3 sign-off gate.

### Facts verified on 2026-10-24 that the questions rest on

Recheck lines before relying on them; nothing was run.

| Fact | Where | Consequence |
| --- | --- | --- |
| Shared KS has **two verification pipelines** (worker-sealed rows with empty judgments; executor file-store runs that never write `evidence.verification_run`) and the admission oracle reads only the executor file store | IA-07 source table "Research pipeline, shared KS" | VE-Q1/OC-D95 ordered one `VerificationRun`; this sprint builds it |
| **Three report shapes** (`research-report.v1`, `VerificationReportLedger`, `ReportIntent`); content-services §2.2 proposes one envelope with `derivations[]` and `timeCoverage` | IA-07; content-services §2.2 | OC-D96 `research-report.v2` = that envelope |
| The as-built system seals **many families** with separate keys (run, benchmark, comparison, claims terminal, report terminal, extraction, capture, audit, adjudication) | `docs/verification/SURFACE-REFERENCE.md:15-32`; `DEPLOYMENT.md:59-121` | SV-Q4 decides how "one sealed manifest" relates to them |
| Report checker is mechanical only; the server path hard-codes `semanticVerdict: insufficient_evidence`; `coverageScope: producer_declared_assertions_only`; `report_assessment.verification_run_id` never set | IA-07 | V02 independent census and the mandatory run link are real gaps |
| Human adjudication is built (only humans or `service:human_reviewer` may decide) but `admissionChanged` is always `false`; 180 review candidates are blank; no calibration (`pending_empirical_labels`) | `docs/verification/OPERATOR-RUNBOOK.md:301`; `README.md:141,156` | Medical grade needs the sign-off path to change admission (V06) and labels (V09) |
| Production trust is static ownership grants + caller-supplied hint headers + environment-variable mission/attempt ids; only the Eve Ed25519 bridge is per-invocation | `docs/verification/DEPLOYMENT.md:160-196`; `INTEGRATION-GUIDE.md:19`; `ARTIFACT-CUSTODY.md:17` | OC-D84/85 replace this for mission calls |
| Rigor checklist against medical grade: authority tiers partial (no taxonomy), GRADE-like certainty absent, judge independence partial, retraction monitoring partial (no feed), sentence ledger partial (VR-010), human adjudication built without labels, audit bundle present, contradiction present in verdicts, calibration absent, independent-origin counting proposed only, PICO/population/clinical risk tier absent | subagent summary of the proposals, 2026-10-24 | SV-Q1 scopes which enter Sprint V |
| V01..V14 are all `ready-for-agent` except V07 (`needs-info` behind Q01); each has a Linear row (OVE-91 …); none started | `issues.json`; `LINEAR.md` | Sprint V picks a subset and comments on the rows |
| Database-contract versions disagree across KS docs (0.4.16, 0.4.3, 0.2.38); eleven AIDB migrations untracked | IA-07; `DEPLOYMENT.md:208` | Migration A0 is the first wave |
| Biotech schema authority (`biotech-meta`) is absent locally; Q01 (v2 adoption boundary) is open; the annex's Biotech mapping targets the *pinned* proposal, not the v2 candidate | IA-07; annex §5 | Biotech graph verification binding cannot be scheduled before Q01 |
| `Report.bodyUri`/`ledgerDigest` have no custody; Supabase content-addressed custody exists but the bucket is absent | IA-07 | Migration B2 |
| Mission Control `cognitive_context_values` are template-stale per attempt; no per-tool-call context; no knowledge tool exposed | IA-07 | Wave 0 fix before any origin |

## 4. The stance: an enterprise research system good enough for the medical sciences

The interviewer holds this stance in every recommendation. It is the annex's engine plus the gaps the
checklist above names. Concretely, a report earns admission only when:

- every externally checkable assertion has an exact span in the final bytes, a typed proposition with
  its qualifiers (entity, population, intervention/exposure, comparator, endpoint, quantity/unit/denominator,
  time, jurisdiction, negation, modality), and at least one support set whose required premises all pass;
- support is judged evidence-only by a verifier whose deployment differs from the producer's, with the
  verdict lattice unchanged and `not_assessed` kept as a value;
- source authority is assessed per claim class against a versioned authority register (tiers for the
  scientific profile: guideline, systematic review, RCT, observational, preprint, vendor, news), origins are
  counted once across syndication, and the retraction/correction/supersession frontier is recorded, with
  `none_found` as an explicit observation (amendment A2);
- the final census is independent of the producer's segmentation (headings, captions, table cells,
  uncited text stay in the denominator) and obligation coverage is measured against the frozen task
  contract;
- critical conclusions carry qualified human sign-off that changes admission for the exact use, with
  reviewer provenance, until a calibrated slice exists; no raw model confidence is presented as calibrated;
- everything is replayable from a sealed manifest, and a correction re-opens only the affected closure.

GRADE-like certainty domains, PICO structure and clinical risk tiers are rubric artefacts of the
scientific profile, selected by application profile, never branches in the engine (annex §4, §5).

## 5. The question bank (at most fifteen)

`grill-with-answers` and `architecture-projection`; batches of at most four, recommendation first,
what each option changes later. Facts are the interviewer's; decisions are the owner's. Do not ask what
the repositories answer.

### Round 1 — scope and rigor

- **SV-Q1 — What does "medical-sciences grade" include in Sprint V?** Recommend: the annex engine as
  built (L0 mechanics, L1 evidence-only support, risk routing to L2/L3) plus, in this sprint: the §3
  records; the scientific rubric profile as a pinned artefact with GRADE-like certainty domains and PICO
  qualifiers (Biotech-selected); the authority-tier register (D11 format, amendment A5) and independent
  origin counting; the retraction/correction frontier with `none_found` (A2); the independent final
  census (V02); human sign-off that changes admission for the exact use (V06 path). Deferred to the next
  sprint: calibration labels and the pilot (V09/V13), semantic cache and batching (V10/V11), a live
  retraction feed. Decide the in/out line.
- **SV-Q2 — Which Knowledge Platform V-issues and amendments enter Sprint V?** Recommend V01, V02, V03,
  V05, V06 in full; V04 as the owned-object inventory and nullable MC linkage only (no component
  extraction; see SV-Q9); V07/V08 as contract stubs and conformance fixtures, their Biotech delivery after
  Q01; V09 only its label-import schema; V10..V14 deferred. Amendments A1..A5 accepted. Decide.
- **SV-Q3 — Is `research-report.v2` the content-services envelope?** Recommend yes: the §2.2 envelope
  with `derivations[]` and `timeCoverage`, the report catalogue as pinned obligation templates (the ten
  kinds; `d10.evidence-report@1` and *study appraisal* first), the deterministic rendering producing the
  sentence ledger, and `report_derive` as the compilation step from report to ingestion proposals (the
  OC-D98 step that makes "report -> ingest" deterministic). Content ingestion of the report itself,
  embeddings and retrieval-profile promotion are the next sprint. Decide.
- **SV-Q4 — How does one `VerificationRun` with one sealed manifest relate to the many sealed families
  the as-built system has?** Recommend: one run row and one run manifest that *references* the family
  seals (capture, claims terminal, report terminal, adjudication) by digest rather than re-sealing their
  bytes; the worker sealer and the executor `sealRun` converge on one writer; per-family signing keys stay;
  the oracle, report assessment (`verification_run_id NOT NULL` for new rows) and Biotech's
  `bks-sealed-verification.v1` all read that manifest. Decide.

### Round 2 — the port and its order

- **SV-Q5 — Which wave order never backtracks?** Recommend six waves: **W0** A0 (commit and release the
  untracked AI Engineer migrations; pin consumers to a commit) + the `knowledge-operation-protocol`
  contracts package (pure types) + the Mission Control per-attempt coordinate fix. **W1** `research-core`
  records and ports, the `aiengineer-postgres` binding, the one sealer and oracle (V01/V02/V03 schema and
  engine parts) + AIDB migrations A1 (origin), A2 (tenant-scoped idempotency, effect key), A4 (run
  manifest). **W2** Mission Control release 1.4.5 (D tables), `KnowledgeGateway`, toolset, `submit_output`,
  lineage; the KS executors accept the envelope and the credential. **W3** the first AI Engineer experiment
  on T1 (research -> assertions -> report -> ingest -> exact retrieval -> next agent) with shape, coherence
  and ingestion guarantees. **W4** V05 authority/counterevidence, V06 exact admission with human sign-off,
  A3 report v2 projection, the five guarantees. **W5** Biotech B1/B2/B5, the `biotech-graph` binding
  (reads and `report.publish`), V07/V08 only if Q01 is answered by then. **W6** assessment reuse across
  consumers and the T2 paid proof. Confirm or reorder; name anything that would have to be undone.
- **SV-Q6 — The origin credential.** Recommend a JWT minted by the Mission Control secret broker per
  invocation (`iss` = installation issuer, `aud` = the binding's executor, `origin` claim, grants, short
  expiry), verified by both executors against the installation's JWKS; it replaces hint headers and
  environment-variable mission ids for mission calls; static ownership grants remain for standalone and
  dashboards; the Eve bridge keeps its own signed path. Decide (this is assumption S1 of SP-10).
- **SV-Q7 — Which tools does the mission agent get in Sprint V, and who runs verification?** Recommend the
  agent-facing set per binding: `knowledge_read`, `knowledge_apply` (ingestion intent), `report_register`
  (v2), `report_derive`, `verify_claims` (L0/L1 progressive, returns handles), plus `submit_output`. The
  harness always runs the final census and the five guarantees on submission (the "independent final
  auditor" of the research proposal); the agent cannot assess its own report. Decide the set and the rule.
- **SV-Q8 — Who is the verifier of record in Sprint V?** Recommend the KS gateway judge and cross-family
  second judge as today, as a KS-hosted semantic step; mission agents are producers (extraction, authoring);
  independence is checked on identities (producer origin's deployment ≠ judge deployment); Jev is advisory
  only (A1); the "semantic step hostable by an MC agent" of OC-D98 is exercised for extraction, not for
  judging, in this sprint. Decide.

### Round 3 — data and migrations

- **SV-Q9 — Where do the V01 records live, given three schema authorities?** Recommend: the new records
  (task contract, assertion version/occurrence, support set, observation, authority observation, use
  decision, run manifest) are AI Engineer DB-contract migrations in letter A, written against the annex's
  "no competing migration tree" rule; the common-component extraction (V04) is designed on paper in this
  sprint and executed later; Mission Control's 1.4.5 tables hold only Mission Control facts (SP-10 §7.5);
  Biotech's PostgreSQL consumes the component only after extraction. Decide.
- **SV-Q10 — How much Biotech enters Sprint V while Q01 is open and `biotech-meta` is absent?** Recommend:
  B1 (Activity origin), B2 (body/ledger custody and re-read), B5 (credential) through a BKS pin v2.1 whose
  upstream source is located first; the `biotech-graph` binding for reads and `report.publish`; the
  verification binding (V07) and cross-store delivery (V08) only after Q01. Alternative: defer Biotech
  entirely to a follow-on sprint. Decide.
- **SV-Q11 — Does human sign-off change admission in Sprint V?** Recommend yes for AI Engineer: an L3
  critical gate becomes a Mission Control Human Task (review gates supplement) whose decision is recorded
  through KS `recordAdjudicationDecision` as `human_reviewer` and binds the exact use (V06), making
  `admissionChanged` real; Biotech's superseding sealed record follows V07. Decide.
- **SV-Q12 — Evaluation inside Sprint V.** Recommend: build the label-import schema and the honest
  benchmark projection (V09 schema part; synthetic labels can never import as human), keep every quality
  flag `false`, and take the pilot commissioning (24 tasks, 300 USD, 60 expert hours) as a separate owner
  decision after W3 shows the loop. Decide now whether the pilot is commissioned, deferred, or declined.

### Round 4 — plan shape and confirmation

- **SV-Q13 — Size, tiers and spend.** Recommend ~12 sessions across four repositories; T0 offline for
  every module; T1 on local PostgreSQL + Temporal (Mission Control) and local Neo4j (Biotech, W5); one
  T2 paid experiment at the end of W3 and one at W6, each under a budget the owner names (recommend
  ≤ 25 USD each). Decide the budget and the stop rule.
- **SV-Q14 — Issue shape and trackers.** Recommend: Knowledge Services work lands as comments and
  claims on the existing V-issue rows (OVE-91 onward) plus new KS issues for the protocol package, the
  bindings layer and the one sealer; Mission Control work and the migration letters get `OVE` issues in
  the Mission Control project, one per wave item, each with `## Provenance` naming SV-D, OC-D and V ids;
  filing happens after the owner reads `SPRINT-V-PLAN.md`. Decide.
- **SV-Q15 — Confirmation.** Restate the plan as the owner will see it: the wave table, the first
  artefact of each wave, what the first experiment shows, and the list of what is explicitly not in
  Sprint V. The owner confirms or corrects; the record closes `final`.

## 6. Plan completion requirements

`SPRINT-V-PLAN.md` is complete when:

- every wave names its repositories, modules (SP-10 §2 ids), V-issues, migration files (proposed names
  from SP-10 §7, confirmed by the schema owner), tests by seam (SP-10 §8 rows plus the annex's V-issue
  acceptance tests), tiers and budget;
- the dependency between waves is a DAG with no edge pointing backwards, and the text names, for each
  wave, the one thing a later wave would otherwise have to undo if the order were different;
- the issue list is complete and each row carries provenance ids;
- the "not in Sprint V" list is explicit: calibration claims, semantic cache, batching, live retraction
  feeds, embeddings and retrieval promotion, physical topology, subagent tools, the Biotech verification
  binding before Q01;
- `python docs/tools/check_docs.py` passes in Mission Control and `node .agent-docs/cli.mjs check --repo .`
  passes in Knowledge Services after the amendment note.

## 7. Ready-to-use prompt for the next session

```text
Run the Sprint V interview from
docs/specs/archive/provider-consolidation-2026-10/interview-instructions/INTERVIEW-SPRINT-V-VERIFICATION-INGESTION-PORT-2026-10-24.md.

Start from IA-07 (OC-D79..105) and the SP-10 projection; preserve those decisions. Read the Knowledge
Services proposals the instruction lists (evidence-verification-system-20261017, the Knowledge Platform
verification annex and V-issues, the research proposal and evaluation protocol, content-services §2) and
the as-built verification docs. Do not ask me for facts the repositories answer.

Take the stance of an enterprise research system good enough for the medical sciences. Use
grill-with-answers and architecture-projection. Ask SV-Q1..15 in batches of at most four, recommendation
first. Create the attributed ANSWERS.md before the first question.

Produce SPRINT-V-PLAN.md: waves in an order that never backtracks, modules, V-issues, migration files,
tests, tiers, budgets, the issue list with provenance, and the explicit not-in-scope list. Update SP-10 §7
with exact migration names and add §4.9 for the verification core. Append the amendment note to the
Knowledge Services proposal. Build nothing and file nothing in this sitting; I file after I read the plan.
```

## 8. Completion and handoff

This preparation is complete when the instruction, its ledger row and the documentation checks are in
place. The interview is complete when IA-08 is `final`, `SPRINT-V-PLAN.md` exists with every wave proven
on paper, and the owner has confirmed SV-Q15. Sprint V itself is complete when each wave's proof is
recorded in the Deep Agents change ledger (`providers/deep_agents/CHANGES.md`, next turn) and the
Knowledge Services counterpart, and the final interview (IQ-07) can start from the baseline it leaves.
