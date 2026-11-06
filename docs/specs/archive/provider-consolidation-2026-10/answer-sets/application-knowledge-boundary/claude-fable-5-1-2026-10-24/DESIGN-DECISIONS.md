---
type: Proposal
title: "Application knowledge boundary: ADR candidates from the prerequisite interview"
description: "Four local ADR candidates recorded from OC-D79..105 on 2026-10-24: the Knowledge Operation Protocol with origin bound from a per-invocation credential (DC-KOP), submit_output as the agent's one Mission Control act (DC-ACT), one evidence-backed report core with storage bindings inside Knowledge Services and Biotech bound through its own executor protocol (DC-BIND), and seven separable provenance roles (DC-ROLES). Candidates for canonical docs/adr review, not accepted ADRs."
tags: [mission-control, adr-candidate, application-boundary, knowledge-services, provenance]
date: 2026-10-24
status: proposed
answers: ANSWERS.md
---

# Application knowledge boundary: ADR candidates

<!-- final-output-contracts-2026-10-26 -->
**Converted, 2026-10-26:** the [final implementation packet](../../../../../provider-consolidation-2026-10/sprint-oc/README.md) and [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) supersede output/transfer planning and interview-resume instructions here. The [canonical target](../../../../../../knowledge/output-contracts.md) controls adopted behavior; [DECISIONS](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) disposes every OC/DP/CS recommendation and older ADR candidate. Retained source/proof claims remain historical and scoped. Start [KICKOFF](../../../sessions/KICKOFF.md); no new interview or runtime completion is implied.


Each candidate meets the three tests of `domain-modeling` (hard to reverse, surprising without context,
a real trade-off). They are local candidates; the canonical ADR is written in `docs/adr/` after the
final output-contract/context-transfer interview, with the next free number.

## DC-KOP: Knowledge Services binds origin from a per-invocation credential, inside the native intent digest

Mission agents call application knowledge services through a Mission Control gateway, but the service,
not the gateway, decides whether an asserted mission origin is true: it verifies a credential minted
for that invocation, binds the origin from the credential's claims, puts it into the native intent
digest before planning or approval, and refuses a payload that disagrees. Standalone work uses the same
protocol with `issuer = self`. We chose this over a Mission-Control-side envelope with services unchanged
because today both services record origin as asserted and AI Engineer's origin columns are foreign keys
into its own orchestration; only a service-side binding makes "which mission produced this" a fact
rather than a claim, and only a shared protocol keeps standalone and mission paths one code path.
Decisions: OC-D79, OC-D84, OC-D85, OC-D87, OC-D88.

## DC-ACT: `submit_output` is the agent's one Mission Control act

The only Mission Control responsibility a mission agent keeps is to call `submit_output(obligation,
selection)` naming file paths and tool-returned handles; it is progressive and final, the harness
completes it, returns the durable ref, reminds once, auto-finalizes only unambiguous matches, repairs
once and then blocks. The final message is not read. We chose this over a structured final message
(parseable but unanswerable; a claim at best) and over strict submit-only (fails on forgetfulness)
because one harness-completed act keeps bookkeeping out of the model, lets the agent learn its refs from
the runtime, and still tolerates the agent forgetting when attribution is unambiguous. Decisions:
OC-D83, OC-D89, OC-D90; revises the two-channel wording of OC-D4/D5.

## DC-BIND: one evidence-backed report core with storage bindings; Biotech binds through its own executor

Knowledge Services holds one storage-neutral research core (`research-report.v2`, Assertion,
VerificationRun, step contracts) behind store ports. The PostgreSQL binding is today's SQL refactored
behind those ports inside Knowledge Services. The Biotech binding compiles port writes into intent-v2
proposals and reads via read-v2 against Biotech's admitted executor; Knowledge Services holds no Cypher
and no Neo4j driver, and Biotech's schema authority stays upstream. We chose this over a Neo4j driver
in Knowledge Services (bypasses Biotech's admission, markers and receipts) and over Biotech
re-implementing the pipeline (two implementations to keep identical) because the owner requires that
evidence-backed reports be "generally identical with modularization" while Biotech remains a distinct
domain service. Decisions: OC-D82, OC-D86, OC-D95, OC-D96, OC-D97, OC-D98.

## DC-ROLES: seven separable provenance roles, joined across stores by receipt and digest only

Every deliverable records producer, caller, receipt, revision, adopter, assessor and consumer as
separate facts; adopting existing content never writes producer; ingesting in another mission writes
caller and receipt, not producer; cross-store identity joins only by receipt/effect key and content
digest, never by id translation. We chose this over producer/consumer-only (re-attributes authorship on
reuse) because the operator question "which mission produced this, which ingested it, which revision did
this agent receive" must be answerable for reused and pre-existing content, and because the owner forced
this interview precisely to settle it. Decisions: OC-D80, OC-D90; consistent with DP-D14.
