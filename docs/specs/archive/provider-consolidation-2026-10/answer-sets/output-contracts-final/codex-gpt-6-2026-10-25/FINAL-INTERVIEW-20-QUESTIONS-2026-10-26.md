---
type: Interview Instruction
title: "IQ-07 final interview: researched twenty-question maximum"
description: "Twenty prioritized candidate slots and live accounting for the final workflow/output/transfer interview and specification/issue conversion."
tags: [mission-control, interview, final, contracts, handoff]
date: 2026-10-26
status: open
---

# Final interview: twenty-question maximum

**Latest direction, OC-D177–181:** the owner requests the
[final synthesis/publication handoff](FINAL-SPEC-AND-ISSUE-SYNTHESIS-HANDOFF-2026-10-26.md), with
post-sprint stress fixtures and direct implementation posture. Preserve accounting and unanswered
options; do not resume this question queue automatically. F20-20 was not asked. The new instruction
is not an answer to it: synthesize adopted scope and disposition unselected additions explicitly.

Read [FINAL-INTERVIEW-HANDOFF](FINAL-INTERVIEW-HANDOFF-2026-10-26.md) first. Owner OC-D159..161
requires a bounded final interview and specs/issues conversion. Extensive mission-specific setup
will precede launches; do not use these slots to design every future mission.

Fresh pre-question research is in [the source recheck](FINAL-INTERVIEW-RESEARCH-2026-10-26.md).
It confirms F20-01..03 as the first independent frontier, preserves the F20-04 skip, and corrects
F20-09/10/19 below without inferring owner acceptance. Existing effective configuration and preflight
are extended; parser support alone does not qualify nested Goal Loop, Swarm or Evaluator Optimizer.

**Current budget: 17/20 substantive questions asked; 15 answered. F20-18/19 await answers.**
At transfer the budget was 0/20. Answers are recorded through OC-D176; remaining recommendations
are unaccepted unless explicitly marked.
These are twenty researched candidate slots, not a requirement to ask a redundant question. Preserve
stable F20-01..20 identifiers and map actual answers to OC-D162 onward. F20-20 is the final FC-Q15
confirmation; reserve a slot for it. A substantive follow-up consumes a slot and replaces an unused
candidate. No hidden subquestion trees or twenty-first question. Explanations/source checks are agent
work. If the owner volunteers an answer, record it and skip its redundant question. If an essential
ambiguity survives the budget, report it explicitly rather than invent acceptance or declare final.

Ask in batches of two or three, at most four. Research first; use recommendations and concrete
consequences. Adapt ordering to dependencies, but keep the total limit. Numerical budgets, provider
choices, entity schemas, exact task coverage and real fixtures are mission setup unless needed to
settle the platform contract. The owner's fixtures remain due after the interview.

## Round A — expressive data and workflow boundaries (1–7)

### F20-01 — Explicit conditional routing mode

**Ask:** When several route conditions can be true, should every conditional routing declaration
explicitly choose either all matching branches or an ordered exclusive branch, with precedence for
the exclusive case, rather than inherit a universal routing mode?

**Recommend:** require an explicit mode, with reusable presets. **Alternative:** default to all
matching, exclusive only when declared. This changes branch count/spend and interpretation.
Do not re-ask unknown/else handling (OC-D147). Basis: Stage Graph annex §14 leaves conditional
semantics open; CONTRACTS §16.8 leaves multiplicity open. This is new target behavior, not existing syntax.

### F20-02 — Join output population

**Ask:** Should a join explicitly select a reusable result-population policy—cover a named primary
collection, reconcile both collections, or produce an intentional matched subset—rather than choose
one implicitly for all joins?

**Recommend:** explicit policy/preset, including cardinality and unmatched-row treatment.
**Alternative:** default to preserving both sides. A source/receipt join may mean account for every
source or process only successfully retrieved sources; that intent must be visible. Unexpected duplicate
matches become conflicts, not an accidental cross-product; required gaps still block under existing rules.
Basis: OC-D151 accepts joins, not a universal population default; fixed StageJoin is not a dataset join.

### F20-03 — Semantic decomposition contract

**Ask:** For partitioned or hierarchical semantic work, should the mission declare what task-relevant
information and coverage must survive decomposition, including how cross-partition dependencies are
handled, instead of treating complete item processing as sufficient evidence of task completeness?

**Recommend:** require a task-specific preservation/coverage contract, using a justified independence
assumption, reconciliation/validation, or an explicitly limited claim. Intermediate evidence/uncertainty
and original-source access follow that contract. **Alternative:** require these safeguards only for
profiles explicitly labelled exhaustive. This is not a universal proof of all real-world facts.
Basis: CONTRACTS §18.3 is critique, not accepted; OC-D152/156 establish mechanical, not semantic, guarantees.

### F20-04 — Early exports versus final composite acceptance

**Audit disposition: skip as settled unless a new boundary-specific constraint is found.** OC-D34
already retains usable partial deliverables with explicit consumption, and OC-D47 permits authored
incremental release. Reconcile intermediate exports/final composite projection in the specification
without charging another question. Keep this slot available for an essential clarification; the
candidate below preserves the reasoning trail, not a direction to re-ask an accepted combination.

**Ask:** May an explicitly contracted, independently eligible intermediate export remain usable when
its enclosing workflow later fails, unless its own use contract or invalidated evidence makes it
dependent on the enclosing workflow's acceptance?

**Recommend:** yes; preserve the incomplete composite disposition and exact export lineage.
**Alternative:** all early exports remain contingent on composite acceptance. This reconciles
incremental delivery with the execution-model statement that only accepted outcomes project outputs.
Do not infer that every inner artifact is exported or that a useful export fulfills the composite goal.
Basis: OC-D34/47, CONTRACTS §18.2 finding 6; `00-EXECUTION_PROGRAM_MODEL.md:199`.

### F20-05 — Held content across mission boundaries for repair/review

**Ask:** Should an explicitly admitted linked repair/review mission be allowed to receive an exact
held or draft report before the source goal is accepted, while ordinary official-use links retain
their acceptance/use gates?

**Recommend:** permit this purpose-scoped exception with exact export, receiving authority and visible
held status. **Alternative:** require accepted source-goal outputs for every cross-mission transfer
in this version; conduct early repair within the source mission. This is an explicit extension to
the general invocation annex §9, which disallows provisional cross-mission bindings. OC-D121 permits
held review/repair generally but does not silently erase that cross-mission restriction.
Ordinary `supplies` retains acceptance of the owning Goal by default, or explicitly mission acceptance;
report acceptance alone does not replace that gate. The exception grants neither early official use
nor automatic invocation/composite success.

### F20-06 — Cancellation of an independently running chain consumer

**Ask:** If an upstream mission is cancelled after a chain consumer has started with valid sealed
inputs, should that consumer continue by default unless the link explicitly propagates cancellation?

**Recommend:** continue independently governed consumer work; current revocation and mandatory
input-use checks remain. **Alternative:** preserve the existing cancel-downstream chain default.
This is a deliberate proposed default change: `domain/composition/chain.py:142` defaults to cancel.
Do not confuse chains with child invocation: the canonical annex §5.2 already defaults spawned
children to cancellation and attached missions to detachment; those are retained unless explicitly revised.

### F20-07 — Cross-application qualification scope

**Ask:** For this version, should we qualify links within each application separately, while retaining
the shared contract for later cross-application links, or must AI Engineer ↔ Biotech links be qualified now?

**Recommend:** intra-application links in **both** applications first. **Alternative:** include explicit
cross-application qualification now, with receiving grants, native binding, use and provenance proof.
This does not defer either application's ordinary functionality. Shared code is not shared authority.
Basis: previous handoff §10.3 item 10; linked service uses request-scoped repository access.

**Answered, OC-D167:** linked workflows stay within a single application, qualified independently
in both applications. The owner corrects the recommendation's framing: cross-application transfer or
connection is **unadopted**, not deferred or an accepted feature awaiting qualification. The owner
explicitly confirmed this interpretation. Original candidate wording above is retained as provenance.

## Round B — bounded optimization, not universal planning (8–10)

### F20-08 — Automatic initiation of repartitioning

**Ask:** May an authored, pre-admitted recovery policy automatically create a bounded successor
partition plan for unresolved oversized/skewed work, or must a coordinator explicitly initiate each replan?

**Recommend:** allow automatic initiation only within explicit admitted partition rules/bounds.
**Alternative:** coordinator initiation only in this version. Preserve successful members and atomic
groups; this is a new plan/activation, not a retry with changed inputs. Outside committed bounds requires
a revision. An indivisible item with no admitted realization blocks. OC-D152 already requires explicit
plans/lineage; this question selects the initiator, not permission for hidden input mutation.

### F20-09 — Scheduling under retained-data pressure

**Ask:** Within admitted fairness and resource limits, may scheduling reduce new producers and favor
ready consumers when doing so demonstrably relieves constrained intermediate capacity before its hard
limit is reached?

**Recommend:** permit pressure-aware draining with downstream headroom and unrelated-work fairness.
**Alternative:** retain ordinary priority/fairness until the affected backlog reaches its explicit ceiling.
This selects a throughput/latency policy; thresholds, paging and storage implementations are engineering.
Consuming an immutable report need not free retained bytes; this grants no evidence-deletion authority.
Do not assume every consumer reduces storage or that file spill removes model-context limits.
Basis: OC-D153 leaves backpressure detail open; current fairness does not implement byte-pressure scheduling.

### F20-10 — Narrow deterministic result reuse

**Ask:** Should this version automatically reuse exact results of transformations explicitly qualified
as pure within the same admitted run, or leave computational memoization for later?

**Recommend:** defer automatic same-run computation memoization this version; retain required
idempotency, recovery, selective carry-forward and explicit recorded reuse.
**Alternative:** include opt-in same-run exact-match reuse keyed by implementation,
parameters, ordered input revisions, contract/schema and declared dependencies, with current access checks.
Neither option adds cross-run caching, undeclared external reads, model-result equivalence or general freshness.
This intentionally offers a smaller current version; OC-D151/156 do not require a new cache subsystem.

**Round B dispositions:** F20-08 is answered with coordinator/agentic successor planning (OC-D168),
not acceptance of an autonomous deterministic research replanner. F20-09's policy decision is
postponed until local dedicated-worker evidence (OC-D169), with existing resource safety retained.
F20-10's new automatic computation cache is excluded from this version (OC-D170).

## Round C — hooks and context continuity (11–16)

### F20-11 — Durable-boundary reactions

**Ask:** Should authors be able to attach bounded preparation/reaction steps to durable output and
workflow transitions, in addition to the existing in-operation hook events?

**Recommend:** yes, implemented through ordinary admitted executions with obligations, budgets and
replay. **Alternative:** use explicit ordinary workflow nodes only; keep hook attachment inside operations.
Do not invent a second scheduler. Provider stop is not submitted/assessed/fulfilled/delivered/settled.
Examples: prepare a selected report index after assessment, or propose the next context package.
Basis: old handoff §11 and WORKFLOW-CONTEXT-HOOKS §4; current scripts are middleware events.

### F20-12 — Hook read access

**Ask:** May an admitted hook use scoped read handles for selected outputs and workspace content
in addition to a bounded versioned event/state projection?

**Recommend:** projection plus explicitly scoped backend-mediated reads with resource/access receipts.
**Alternative:** projection-only; materialize all needed data up front. No private middleware state,
raw credentials or implicit whole-workspace/KS access. Current hook cwd is a private `mc-hooks-*`
directory, not the agent sandbox (`materializer.py:554–631`). Field names/storage design are engineering.

### F20-13 — Hook writes to the agent workspace

**Ask:** In this version, should hook-produced files be staged as candidate preparation outputs and
installed by the host at a supported boundary, rather than let hooks directly mutate live agent files?

**Recommend:** staged candidate outputs and host-validated installation. **Alternative:** permit
explicitly scoped direct sandbox writes under an admitted hook contract, including concurrency/receipt
rules. This decides local mutation scope, distinct from read access or external effects. A hook-created
file cannot by itself seal a transfer, establish acceptance or fulfill an obligation; admitted submission
and validation may make it a qualifying output.

### F20-14 — Effectful hook execution scope

**Ask:** Should hook requests for model work or external writes be dispatched as separate admitted
operations, keeping hook-script execution itself limited to bounded observation/guard/local preparation?

**Recommend:** separate admitted operations. **Alternative:** allow directly effectful hook scripts with
equivalent operation identity, grants, budgeting, reconciliation and recovery obligations. This is a
scope choice, not a proposal to bypass permission or receipts. It controls whether this version needs
an additional directly effectful script execution surface. KS still owns evidence/use/native binding semantics.
This asks whether the hook process itself becomes an effect executor; requesting an ordinary admitted
operation does not create a second execution path. Existing effect-class syntax is not recovery proof.

### F20-15 — Persistent hook-generated working notes

**Ask:** May hooks contribute attributed candidate notes or index updates to a persistent journal/artifact
stream that an authored policy can validate/select for later context?

**Recommend:** yes, with exact source references and separation from authoritative state.
**Alternative:** hook feedback stays transient; persistent handoffs come only from contracted agent or
preparation-node outputs. OC-D137's mandatory Goal Loop progress note remains; this is an additional
source of candidate context, not permission to overwrite objectives, obligations, acceptance or liability.
If F20-11..14 already settle this path through ordinary admitted outputs, record that consequence and
skip the redundant question; keep the slot for an essential clarification.

### F20-16 — Compaction preservation proposals

**Ask:** May a compaction hook submit a bounded proposal of notes/references to preserve for host
validation, or should compaction hooks remain observation-only in this version?

**Recommend:** permit admitted preservation proposals. The host validates the proposal for the
applicable in-session compaction or continuation process; required authoritative state and exact
references remain independently preserved. Keep compaction and continuation identities, triggers
and budgets distinct. **Alternative:** observation-only, preservation through existing profiles.
Current compaction dispatch discards returned HookResult; this selects new behavior, not existing support.
No arbitrary summary replacement, private reasoning extraction or sealed-plan rewrite is permitted.

## Round D — delivery and concrete version boundary (17–19)

### F20-17 — Automatic coordinator content

**Ask:** Should mission setup be able to admit automatic delivery of selected excerpts or small
designated outputs to the coordinator, while default notices remain bounded references/status/gaps?

**Recommend:** allow explicitly selected content under coordinator grants and context budgets;
otherwise retrieve on demand. **Alternative:** automatic notices always reference-only this version.
Do not re-ask inspection, subscriptions or actionable wakes (OC-D125/126). Persisted notice, actual
host wake, model-visible delivery, acknowledgment and content read remain distinct proof obligations.
Optional content delivery uses a separate coordinator subscription/retrieval mechanism; it does not
silently expand the Child Portal, which remains a bounded reference/status/blocker/budget projection.

### F20-18 — Specialized code integration reducer scope

**Ask:** Should this version stop at general typed code-change outputs and admitted deterministic/
agent execution, deferring a specialized automated branch-merge/test conflict-resolution reducer?

**Recommend:** defer the specialized code integration engine while preserving generic code contracts
and required repository checks. **Alternative:** explicitly include that engine with isolated bases,
merge ordering, conflict/rollback/effect policy and coding-lane proof. The old compute proposal §3.5
offers it; no owner answer adopted its whole taxonomy. This does not declare Deep Agents exclusively
knowledge/content or waive code fixes needed to implement the accepted runtime/fixtures.

### F20-19 — Bounded coordinator preflight/impact view

**Ask:** Should this version extend existing preflight/admission inspection into one bounded
pre-launch/revision preview showing the new effective output/transfer contracts, input bindings,
unresolved prerequisites, capability/resource fit and affected work, while leaving general
mission-planning automation and broad coordinator-interface redesign for later?

**Recommend:** include that focused inspectable compilation/impact view through existing surfaces.
**Alternative:** expose the already accepted effective-node/readiness inspection only, deferring the
integrated preview extension. Preflight and launch-ticket admission preview already exist
(`manifest_service.py:1738–1757`; `coordinator_launch.py:365–454`); do not build a second authority.
The broader coordinator powers in CONTRACTS §18 are recommendations, not accepted
features. The view must distinguish static checks, estimates and runtime unknowns; it cannot certify
future reasoning success. Extensive mission setup remains an interactive coordinator responsibility.

## Round E — final integrated confirmation (20)

### F20-20 — Accept the coherent version (also FC-Q15)

**Ask only after drafting the integrated pack:** Does this worked model, explicit current-version
scope/deferred list and specification-to-issue/proof matrix accurately capture the version you want
implemented, including the answers and corrections from this final interview?

**Recommend:** accept the concrete presented version if faithful; corrections replace the draft
before conversion is marked complete. This is one integrated confirmation, not twenty new subquestions.
Show author, executor and coordinator views across direct transfer, a nested Goal Loop, a bounded
mapped/reduced graph, Swarm/Evaluator Optimizer boundaries and linked missions. Include hooks, review,
missing/held/revised inputs, cancellation and recovery. Clearly label proposed syntax until implemented.

Before asking, prepare the revised CONTRACTS, draft WORK-ITEMS with owners/dependencies/proof, a
disposition of old OC/CS/ADR candidates and the proposed issue mapping. Issue identifiers may still
be pending creation; after acceptance, perform required issue conversion and verification. Final
interview confirmation does not mean code or real fixtures passed. No final status until actual conversion.

## Coverage and no-repeat map

| Area | Questions | Already settled / engineering work |
| --- | --- | --- |
| Stage Graph expression/reduction | 1–4, 8–10 | OC-D139..156; exact selections, omissions, group closure, tree qualification, inventory windows; schema/wire naming and implementation are agent work. |
| Linked/nested/all workflow families | 4–7, 20 | Typed boundary/projection, Graph versus Goal Loop scheduling, swarm modes, evaluator independence, explicit adoption, own authority/budgets; qualify all four and both applications. |
| Hooks/context | 11–16 | Kernel-first hooks, versioned assets, host authority, required note and one sealed plan; event return matrix and failure/replay are engineering. |
| Coordinator/scope | 17–20 | Focused inspection/actionable wakes, routine batching, real host wake proof; no global grammar overhaul or automatic acceptance of ADR-0049. |

Keep general freshness/invalidation deferred except accepted synthesis/report revisions and exact
held-source reassessment. No automatic semantic optimizer, whole-run context dump, hidden parent success,
duplicated schema authority or mandatory reducer on ordinary direct transfers follows from this instrument.

## Question accounting — final session in progress

| Field | Current state |
| --- | --- |
| Asked | 17 / 20 |
| Answered | 15 |
| Skipped as already settled/inapplicable | F20-04; F20-15 follows from OC-D171/174/175; reserve for essential clarification if needed |
| Replaced by essential follow-up | none yet |
| Reserved final confirmation | F20-20 / FC-Q15 |
| Next decision ID | OC-D182 after volunteered owner steering OC-D177–181; capped question count unchanged |

First round answered through the question tool on 2026-10-26: Q1 = F20-01 → OC-D162,
Q2 = F20-02 → OC-D163, Q3 = F20-03 → OC-D164.
Second round answered: Q4 = F20-05 → OC-D165, Q5 = F20-06 → OC-D166,
Q6 = F20-07 → OC-D167, with the application-scope correction explicitly confirmed.
Third round answered: Q7 = F20-08 → OC-D168, Q8 = F20-09 → OC-D169,
Q9 = F20-10 → OC-D170. Q9's exclusion implies no future caching commitment.
Fourth round answered: Q10 = F20-11 → OC-D171, Q11 = F20-16 → OC-D172.
Fifth round answered: Q12 = F20-12 → OC-D173, Q13 = F20-13 → OC-D174,
Q14 = F20-14 → OC-D175. F20-15 is skipped as a consequence of the selected output path,
not a new answer or permission to overwrite authoritative state.
Sixth round: Q15 = F20-17 answered as OC-D176; Q16 = F20-18 and Q17 = F20-19 remain pending.
No default is taken while pending.
F20-20 is reserved for final confirmation after concrete drafting; F20-04 remains skipped.

| Slot | Status |
| --- | --- |
| F20-01 | Answered; OC-D162, explicit branching mode/preset |
| F20-02 | Answered; OC-D163, explicit data-join population policy/preset |
| F20-03 | Answered; OC-D164, semantic preservation/coverage required |
| F20-04 | Skipped as settled; reserve for essential clarification |
| F20-05 | Answered; OC-D165, purpose-scoped linked repair/review permitted |
| F20-06 | Answered; OC-D166, running consumer continues unless propagation selected |
| F20-07 | Answered/corrected; OC-D167, same-application links only; cross-application feature unadopted |
| F20-08 | Answered/corrected; OC-D168, coordinator or agentic partition planning |
| F20-09 | Answered/postponed policy; OC-D169, review after local dedicated-worker evidence |
| F20-10 | Answered; OC-D170, new automatic computation cache excluded |
| F20-11 | Answered; OC-D171, durable reactions through ordinary admitted execution |
| F20-12 | Answered; OC-D173, scoped host-mediated reads |
| F20-13 | Answered; OC-D174, staged files with host installation |
| F20-14 | Answered; OC-D175, model/external effects use ordinary operations |
| F20-15 | Skipped as redundant consequence of OC-D171/174/175 |
| F20-16 | Answered; OC-D172, host-validated preservation proposals |
| F20-17 | Answered; OC-D176, opt-in bounded content with reference-oriented default |
| F20-18 | Asked as Q16; awaiting answer |
| F20-19 | Asked as Q17; awaiting answer |
| F20-20 | Reserved final integrated confirmation |

Keep an asked/answered/skipped/replaced status per slot as the session runs. Preserve original wording
when a slot is replaced and record why. Do not keep asking after budget exhaustion to make a ledger final.
