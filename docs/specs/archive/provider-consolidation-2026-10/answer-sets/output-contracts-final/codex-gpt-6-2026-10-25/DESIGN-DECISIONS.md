---
type: Design Decisions
title: "IQ-07 ADR consolidation and canonical amendment plan"
description: "Draft disposition of seven earlier local ADR candidates and the accepted hook decisions, preserving historical ADR status and defining the canonical amendments for final conversion."
tags: [mission-control, adr, decisions, provenance, context-transfer]
date: 2026-10-26
status: draft
---

# ADR consolidation and canonical amendment plan

<!-- final-output-contracts-2026-10-26 -->
**Converted, 2026-10-26:** the [final implementation packet](../../../../../provider-consolidation-2026-10/sprint-oc/README.md) and [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) supersede output/transfer planning and interview-resume instructions here. The [canonical target](../../../../../../knowledge/output-contracts.md) controls adopted behavior; [DECISIONS](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) disposes every OC/DP/CS recommendation and older ADR candidate. Retained source/proof claims remain historical and scoped. Start [KICKOFF](../../../sessions/KICKOFF.md); no new interview or runtime completion is implied.


This is the concrete promotion plan for final integrated confirmation. Behavior already selected by
the owner remains in [ANSWERS](ANSWERS.md) and [CONTRACTS](CONTRACTS.md). Grouping that behavior into
ADRs does not add features. Canonical numbers are allocated after a fresh directory check at conversion;
the highest found on 2026-10-26 is 0057. The missing 0051 is not available for inferred reuse.

## 1. Disposition of earlier local candidates

Sources: [IA-06 candidates](../../gpt-6-astra-2026-10-24/DESIGN-DECISIONS.md) and
[IA-07 candidates](../../application-knowledge-boundary/claude-fable-5-1-2026-10-24/DESIGN-DECISIONS.md).

| Earlier candidate | Proposed disposition | Current contract |
| --- | --- | --- |
| DC-OBL | Merge with DC-ACT into ADR-A below. | General promises, separate submission/assessment/fulfillment/finalization, exact sets and explicit completion. |
| DC-ACT | Merge into ADR-A; narrow “agent's one MC act” to “one authoritative output-submission act.” | Progressive/final submit_output; final message/output_refs not submission authority; qualified degraded file channel uses the same module. |
| DC-APP | Merge with DC-BIND into ADR-B. | Application-owned bytes/native identities; MC reference/custody/delivery coordination; one shared knowledge/report core. |
| DC-BIND | Merge into ADR-B; current BKS schema authoring replaces obsolete upstream/biotech-meta assumptions. | Explicit storage/report ports, native BKS executor, no KS Neo4j driver or duplicate verification engine. |
| DC-KOP | Merge with DC-ROLES into ADR-C. | Service-authenticated origin before canonicalization/sealing, exact protocol/native effects and recovery. |
| DC-ROLES | Merge into ADR-C. | Producer, caller, receipt, revision, adopter, assessor and consumer remain distinct. |
| DC-XFER | Promote as ADR-D, with the later single-plan/per-attempt-receipt refinement. | Exact selected sources, effective configuration, boundary-specific state, current access, budgets and real backend readiness. |
| New accepted hook decisions | ADR-E. | Durable reactions and context contributions use ordinary admitted execution; scoped reads, staged files and validated preservation proposals. |

## 2. Draft ADR content

### ADR-A — Composable obligations and one authoritative submission act

**Decision.** Named output obligations bind general forms, pinned/inline substantive contracts,
enforcement, distinct-member cardinality, coverage and evaluation scope. Agents progressively/finally
offer exact candidates through submit_output. Store submission revisions, independent assessments,
current accepted sets, obligation fulfillment and invocation finalization separately. Final assistant
prose and output_refs are not submission channels. A qualified declared-file/SUBMISSION.json fallback
enters the same protocol. A new revision does not count as another deliverable.

**Why.** Final-message scraping and automatic row counts confuse offered content, independently
usable results and mission completion. Separate records retain successful cognition across review,
effect reconciliation, revision and restart without weakening promises.

**Alternatives not selected.** One terminal provider-result boolean; parallel submission protocols;
universal mandatory helper reports; a closed domain-kind taxonomy; unbounded or fixed one-shot
repair rules unrelated to the admitted policy.

**Consequences.** Explicit partial/intermediate exports can remain usable without accepting their
composite. Required/expected/optional enforcement does not replace validity or use checks. Completion
still uses the closed typed AST; admitted custom transformations do not authorize executable acceptance
predicates. Required Goal Loop notes and other tools are compatible with one *submission* act.

**Provenance.** DC-OBL/DC-ACT; OC-D27..78 as refined by OC-D83/89/114–119/133/137/139–148/162–164.

### ADR-B — Application content ownership and a shared report/verification core

**Decision.** MC owns orchestration and its ledger/reference/delivery evidence. Shared KS owns reusable
report, evidence, verification, permitted-use and native-operation semantics behind explicit ports.
AIDB owns AI Engineer native SQL; BKS owns graph SDL and its admitted executor. The KS Biotech binding
calls that executor. Logical commonality does not create another domain schema or verification authority.

**Why.** A universal MC artifact table or separate domain-specific verification engines would duplicate
authority and make exact native identity/lineage difficult to preserve. Existing package namespaces do
not establish backend neutrality.

**Alternatives not selected.** Copy all application bytes into MC by requirement; write graph content
directly from shared KS; author domain schema in the common MC component; invent absent upstream repos.

**Consequences.** Four-owner schema-fit review/migration belongs to each affected slice. Exact current
release/schema pins are checked during implementation; old candidate version names are historical.
Cross-application linking is unadopted, not a required consequence of shared ports.

**Provenance.** DC-APP/DC-BIND; OC-D64/70/77/79..105/117/167 and the recurring schema-fit directive.

### ADR-C — Authenticated origin and receipt-backed provenance

**Decision.** The receiving service binds live origin from authenticated invocation credentials before
native intent canonicalization/sealing, rejects conflicting supplied origin and retains exact
producer/caller/receipt/revision/adopter/assessor/consumer roles. Propagate admitted child and durable
origins through the same trust boundary. Reconcile an uncertain native effect before re-execution.

**Why.** Coordinates copied by a model, a content digest, or a declared role cannot establish trusted
authorship, authority or a completed write. Distinct roles are necessary when work is repaired, revised,
adopted, assessed or reused.

**Alternatives not selected.** Trust model-supplied mission identity; seal first and append unbound
origin later; collapse producer and adopter; treat a pending dispatch or permission as effect proof.

**Consequences.** Standalone self-origin remains service-authenticated standalone work, not a means
to assert MC identity. Exact receipt/effect mappings join native and orchestration records; byte equality
alone proves neither semantic equivalence nor identity/admission. Required readback is independent.

**Provenance.** DC-KOP/DC-ROLES; OC-D79/80/84/85/89/99/101/108–113/117.

### ADR-D — One sealed transfer authority and separate delivery receipts

**Decision.** Extend the existing effective configuration path. Profile or inline definitions are
admitted/pinned, preferences specialize profile→mission→unit→input, and hard constraints combine.
Resolve exact eligible named sources into one sealed receiver plan. Render prompt/index/files/handles
from that plan and append separate attempt-specific delivery/readiness receipts. Required host state
and workflow-specific state builders remain authoritative.

**Why.** Competing selection and materialization authorities can deliver unrelated or stale sources,
silently weaken placement, or claim access from a path string. One plan makes exact replay, resource
accounting and inspection meaningful.

**Alternatives not selected.** Run-wide report loading; filename/stem/output-position guesses;
unbounded history; hidden lossy summaries; submission-time changes to receiver policy; a copied
credential/permission freeze.

**Consequences.** Aggregate prompt/file accounting includes reserves and later tool reads. Use only
authored satisfying placement alternatives; otherwise refuse/repair. Maintain current access/use and
explicit revision boundaries. Held/draft linked repair is permitted only within one application under
its admitted purpose; ordinary cross-mission supply retains source acceptance and use gates.
Already-running chain consumers continue on upstream cancellation unless propagation was selected.
Child spawn/attach cancellation defaults remain distinct.

**Provenance.** DC-XFER; OC-D52..61/99/101/116/119/121–124/133–148/165–167.
Partially supersedes ADR-0027 placement simplifications and ADR-0029's running-consumer cancellation default.

### ADR-E — Durable reactions and staged context contributions use normal execution

**Decision.** Attach bounded durable-transition reactions through ordinary admitted execution,
scheduled by Temporal. Hook scripts receive bounded event snapshots and scoped host-mediated reads;
they stage candidate files for host validation/installation. Model work/external writes use separate
ordinary operations. Compaction can consume bounded preservation proposals under host validation.
Persistent candidate notes follow this output path when configured.

**Why.** Turning scripts into an additional scheduler, effect executor or authoritative state store
would duplicate budgets, permission, reconciliation and replay machinery. Event-specific capabilities
make the actual guard/observation/post-effect behavior explicit.

**Alternatives not selected.** Implicit whole-workspace/KS access, direct live-file mutation, directly
effectful script execution, arbitrary summary replacement, a second automatic memory system, or a claim
that a late denial reverses an already committed effect.

**Consequences.** Preserve kernel-first execution and catalog admission. Before-effect guards can block;
post-effect/observation events cannot undo committed work. Separate compaction from continuation and
keep mandatory state independently preserved. Reconcile ADR-0026's unconditional denial wording with
this event-specific matrix.

**Provenance.** OC-D171–175, with OC-D137/138 and retained kernel invariants.

## 3. Canonical amendments to accompany promotion

| Destination | Required current-rule amendment |
| --- | --- |
| General SPECIFICATION, authoring/compiler/common semantics | One submission protocol; general forms and three enforcement levels; exact current sets/fulfillment; explicit early exports; purpose-scoped held use. Preserve the closed completion AST. |
| DATABASE records/transactions | Separate submission revision, current set, fulfillment, saved-result settlement, sealed plan and attempt receipts; exact references and concurrency. No second domain SQL authority. |
| KNOWLEDGE-SERVICES expansion annex | Shared-core/storage-port ownership; origin bound before native digest; seven provenance roles; trusted semantic observations/sealing/review; commit/receipt recovery. Version any changed native intent contract rather than mutate approved bytes. |
| CONTEXT-STATE-AND-CONTROL and continuation annex | One plan; exact named/current-set selection; purpose versus access; required held repair bytes; workflow-specific state; event-specific hooks and validated preservation. |
| Execution program model and composite export clauses | Distinguish independently eligible early export from accepted final composite projection. Inner artifacts remain internal unless explicitly exported. |
| Mission invocation annex §9 | Add exact held/draft repair/review exception within one application; retain ordinary owning-Goal or explicit Mission Acceptance and use gates. |
| ADR-0027 | Dated partial-supersession pointer for plan/receipt authority and required delivery forms; retain deterministic packing/tiered representation. |
| ADR-0029 | Dated partial-supersession pointer for already-running chain consumer cancellation; do not infer a change to unreleased consumer gates. |
| ADR-0026 | Dated partial-supersession pointer for unconditional deny wording; retain kernel-first/catalog requirements. |

Do not rewrite old ADR prose as if it always contained the new decision.

## 4. Existing proposed ADRs stay proposed

Fresh source inspection finds 0037, 0049 and 0057 **proposed** in frontmatter and body. The same applies
to 0039, 0040 and 0056. Source implementations or references do not promote their entire proposals.
The selected fork, output and notification requirements may use existing mechanisms without accepting
unrelated worktree topology, legacy deprecation or broader tracing claims.

## 5. Older OC/CS document conversion

[CONTRACTS §14](CONTRACTS.md#14-earlier-decision-dispositions) is the row-by-row disposition authority
for OC-D1..26 and CS-D1..14. Preserve their original quotes/recommendation rows. Apply dated revisions
at the affected sections of the Deep Agents output/transfer session and domain supplement, including
one submit act, general forms, current sets, exact selected transfer, required held repair inputs,
optional helpers and required Goal Loop notes. Retire domain_effect as a special output kind in favor
of general effect_receipt contracts.

The coordinator proposal keeps its history and gains explicit scope dispositions; its “hook points”
are interface/documentation integration points, not executable runtime hooks. Focused inspection,
events/wakes and selected content delivery are in scope; broad grammar/bundle/HTTP/legacy changes
retain their prior disposition. ADR-0049 is not automatically accepted.

No canonical promotion or tracker publication has occurred in this draft.
