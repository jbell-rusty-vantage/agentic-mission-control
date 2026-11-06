---
type: Research
title: "Sprint V: verified baseline and research recommendations"
description: "Source-backed findings and primary-source research for the verification, reports and knowledge-operation upgrade; separates inspected implementation, proposed design and unrun proof."
tags: [mission-control, knowledge-services, verification, research, sprint-v]
date: 2026-10-24
status: archived
archived: 2026-11-02
archived_from: SPRINT-V-RESEARCH.md
archived_reason: "baseline research for a finished sprint"
---

> **Archived 2026-11-02** (baseline research for a finished sprint). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Sprint V research and baseline

Reading route: [answers](../answer-sets/sprint-v/codex-gpt-6-2026-10-24/ANSWERS.md),
[implementation plan](../sessions/SPRINT-V-PLAN.md), [contract projection](../specs/SPRINT-V-DESIGN.md),
[team workspace](../sprint-v/TEAM-WORKSPACE.md).

## 1. Evidence boundary

Audited by Codex with three GPT 6.1 Sol read-only agents. No integrated runtime, provider, database or
migration proof was run. Later in this sitting, 68 direct KS component tests passed; see the proof log.
Source inspection establishes implementation, not operational qualification.
Local tracker files were read; remote issue status was not refreshed.

| Repository | Observed revision | Working state |
| --- | --- | --- |
| Mission Control | Started at `8de6fab94fd5d17d79f2ecfd92e55329bb282a36`; advanced externally during inspection to `df0a2a9e349284e0fd6aff5c70096a8183710405` | Existing interview changes were committed by another actor; this session did not commit. Own answers/ledger edits remain. Source findings unchanged by that documentation commit. |
| Knowledge Services | `50caaa41e9302717f9cadc727027841ddec67797` | Clean before this work; one checkout. |
| AI Engineer DB contract | `c809a11a96268f6e1c673e8e03766afcb2ca0dab` | Existing modifications and eleven untracked migrations; preserve them. |
| Biotech Knowledge Services | `d042678cb06de3c3c8b8f85e8ff9dff99858ad84` | Existing guide/navigation changes; preserve them. |

Paths in the next table are relative to the named repository. Line numbers describe this audit.

## 2. Findings that change the plan

| ID | Assertion and evidence | Verdict and consequence |
| --- | --- | --- |
| E01 | MC `src/mission_control/application/authoring/manifest_launch_inputs.py:2078` constructs template coordinates; `:2112` freezes cognitive values. `application/programs/goal_directed.py:1561` and `service.py:1801` rebind outer coordinates without refreshing them. `adapters/deep_agents/materializer.py:503` consumes them. | Confirmed source defect. Refresh live invocation context before credentials or tool admission. Test both workflow families and local/hosted execution. |
| E02 | KS executor `apps/verification-executor/src/store.ts:385` writes file state; `knowledge/evidence-oracle.ts:186` expects executor artifacts. `packages/persistence/src/verification-claims-report-reads.ts:358` reads database runs with another hydration path. | Two representations and readers. Introduce one durable run repository and canonical hydration path; legacy readers become explicit import adapters. |
| E03 | KS `packages/application/src/verification/operations/verification-claims.ts:468` declares producer-only coverage. `packages/verification/src/report/report-wide.ts:109` inserts insufficient support and unknown origin information. Worker `apps/worker/src/verification-claims-sealer.ts:335` runs semantic checks but `:710` retains earlier report summary. | Real claim semantics exist; report aggregation is incomplete. Recompute report assessment after authoritative observations. Do not characterize the whole engine as mechanical-only. |
| E04 | KS `packages/verification/src/report/decomposition.ts:42` validates supplied segmentation. Executor `executor.ts:1397` locates supplied text via string search. | Neither establishes an independent final census. Audit exact rendered bytes, including headings, captions, tables and uncited text. |
| E05 | KS `apps/verification-executor/src/knowledge/report-assessment.ts:111,203,245,257,293,371` checks faithful reuse, premise roles, attributed use, derivations and body mapping. | Retain these behaviors as compatibility fixtures in the new report core. |
| E06 | KS `packages/application/src/verification/operations/verification-adjudication-decision.ts:99` restricts reviewer identities; `:154` returns `admissionChanged:false`. | Review persistence exists; exact-use admission after review remains work. Human review must create an attributable successor decision, never toggle an approved boolean. |
| E07 | MC `integrations/biotech/src/biotech_mission_adapters/knowledge/adapter.py:970` reconciles uncertain effects; `:1159` stops new dispatch while reconciling. Human tasks at `application/human_tasks/service.py:200` resolve attributed decisions. | Reuse lifecycle semantics. No new scheduler or parallel review authority. |
| E08 | AIDB `package.json:3` says 0.4.16, `workspace/manifest.json:16` ends at 20260916020200, but SQL includes 20261001170000. KS `pnpm-lock.yaml:259` pins a vendored 0.4.16 tarball. | A0 must reconcile migration history, generated projections and reproducible package provenance before releasing. A version number alone is insufficient. |
| E09 | AIDB `supabase/migrations/20260826001500_api_and_grants.sql:275,291,297` defines SECURITY DEFINER submit_intent with global idempotency and no explicit tenant. Explicit grants at :319 name service roles. | Fix tenant binding and inspect/revoke PUBLIC execution as applicable. Live anonymous access is not established by this read-only audit. |
| E10 | MC DB `component/manifest.json:9` says 1.4.0, root SQL ends at 0041; `releases/1.4.4/component/manifest.json:215` includes 0047–0049. | Reconcile the release builder's authoritative predecessor before adding 0050+. Never build a new release from a source that drops 0042–0049. |
| E11 | BKS `schema/pinned/PIN.json:3,11,15` pins v2.0.2 and names absent upstream biotech-meta with dirty-authoring provenance. Custody missing-bucket note is dated October 12 (`packages/kg-ops/src/admission/custody-supabase.ts:18`). | Schema source/Q01 must resolve before graph migration. Bucket absence is historical, not a fresh live observation. Re-probe during local qualification. |
| E12 | SP-10 binds invocation origin into native digest but describes retry-stable effect keys derived from that digest. | Clarify immutable originating origin versus current authenticated caller. Retry identical frozen native bytes under fresh recovery authorization; never strip origin from the sealed payload. |
| E13 | Canonical MC knowledge annex still defines `mc.knowledge_request.v1`; OC-D84 chooses KS-native protocol. | Promote an explicit versioned contract amendment when implementation is authorized. Do not silently reinterpret old v1 bytes. |

## 3. External primary-source research

Read on 2026-10-24. Recommendations below are design inferences, not claims that BellLabs conforms to
a clinical standard or has passed empirical quality gates.

| Source | Finding | Design inference |
| --- | --- | --- |
| [Cochrane Handbook chapter 14](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-14), version 6.5, chapter last updated August 2023 | Certainty concerns a body of evidence for a specific outcome; domains include bias, inconsistency, indirectness, imprecision and publication bias. | Store outcome-level `EvidenceSynthesisAssessment` separately from source-support verdicts and study appraisal. A paper tier or model agreement cannot supply an overall certainty rating. |
| [PRISMA 2020](https://www.prisma-statement.org/prisma-2020) | Reporting guidance provides checklists and flow diagrams for original and updated systematic reviews. | Make report obligations and search/selection provenance explicit. Ordinary evidence reports must not call themselves systematic reviews solely because the renderer uses a checklist. |
| [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | Deposited scholarly metadata includes post-publication updates and Retraction Watch information. | Add an on-demand revision/retraction adapter. Store provider, query time, identifiers, coverage and failure state. A negative lookup means no update found within that frontier, never universally unretracted. |
| [JWT BCP, RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.html) | Applications must constrain algorithms and validate issuer/subject and intended audience. | Pin issuers and algorithm allowlists, validate tenant/grants/audience on each dispatch, and keep signing trust separate from knowledge admissibility. Never load keys from a model-supplied URL. |
| [NIST exact binomial bounds](https://itl.nist.gov/div898/software/dataplot/refman2/auxillar/exacbino.htm) | Exact limits are available for one-sided or two-sided binomial proportions, particularly useful with small counts. | Qualification must report uncertainty. For independent zero-error cases, the one-sided 95% upper bound is `1 - 0.05^(1/n)`; 24 cases imply about 11.7%, not 2%. Correlated assertions require task/source-cluster analysis, not this independence shortcut. |

Research used the installed Firecrawl search skill and primary web sources. Raw scraped pages remain
in ignored `.scratch/sprint-v/.firecrawl/`; they are not specification authority or commit material.

## 4. Recommended changes to the old interview's defaults

Owner amendments after this research: both domains in the same sprint; full refactor with disposable
old data/history; BKS becomes schema author; real research/ingestion/retrieval waits for all workflow,
output/context and Deep Agents qualification. These supersede the preservation/deferral alternatives
in the original research questions. Current SDL is `schema/pinned/release/sdl/assembled.graphql`,
with modules and generator present; missing biotech-meta meant missing historical authoring checkout.

1. Include minimal dependency invalidation and correction handling in the first usable release.
   Deferring all of V12 would leave accepted knowledge usable after a known correction. Full automated
   feeds and optimal recomputation can follow; current-use revocation must work now.
2. Include protocol/capability parity for shipped surfaces now. Defer broad V14 consumer rollout, not
   the compatibility checks needed by the MC client itself.
3. Separate implementation readiness from evaluator qualification. The first release can support
   rigorous human-reviewed research without claiming calibrated automatic scientific admission.
4. Bring report v2 into the first loop. Building a disposable v1 path before replacing it would create
   avoidable report migration work.
5. Treat source tiers as profile-specific routing priors. Claim type, methodology, directness, outcome,
   applicability and origin independence decide fitness; there is no universal ordinal source score.
6. Start the full shared storage extraction design now. Preserve existing migration ownership until
   the component's upgrade and consumer gates pass; never create parallel ownership during transition.

## 5. Verification in this sitting

- KS documentation baseline: `node .agent-docs/cli.mjs check --repo .` passed (405 selected inputs).
- MC documentation baseline: six checks passed, link check failed on three pre-existing links in
  CHANGES, DOMAIN-PROVENANCE and SPRINT-SEQUENCE. The program ledger already records the absent review
  supplement at PR-05. No runtime or calibration result is implied by documentation checks.
- Further checks and final dispositions are recorded in the team workspace proof log.
