---
type: Concept
category: persistence
title: Report collections and the current accepted set
description: "How a report collection is judged member by member under an authored aggregate rule, how accepted heads accumulate across Goal Loop iterations into the exact current accepted set, how the verifier reads that whole set and its index file, and how a goal-scoped review wait lets independent work proceed (Sprint OC WI-07)."
tags: [mission-control, output-contracts, outputs, goal-loop, knowledge-services, sprint]
aliases: [aggregate rule, accepted heads, current set, report collection]
questions:
  - How does a report collection build its current accepted set?
  - How do accepted heads accumulate across Goal Loop iterations?
  - Why does a collection wait with MEMBER_UNASSESSED?
updated: 2026-11-01
---

# Report collections and the current accepted set

WI-07 (OVE-170) replaces the OVE-160 one-report guard for runs with named promises. The canonical
target is the output contract model (ADR-0058, ADR-0061); the base model (promises, heads, sets, fulfillment) is
[output contracts](output-contracts.md). Two shapes carry a collection, and both keep identity,
cardinality and coverage independent.

**Accumulated deliverables (the Goal Loop report collection).** One promise (for example
`reports`, form `reference`, `cardinality {min: 3, max: 3}`, `scope: goal`) whose deliverables are
the members: each report is its own deliverable with its own accepted head, so revisions of one
report count once and the distinct count is the number of heads. Each exact revision is judged by
the [trusted judgment](trusted-judgment.md) bridge with its own digest
([trusted settlement](../../src/mission_control/application/knowledge/trusted_settlement.py)); a
`submit_output` act naming several report handles finalizes and every revision is assessed alone
(the single-report K01 handoff applies only to an act naming exactly one report;
[submission service](../../src/mission_control/application/outputs/submission_service.py),
`_selected_report`). The legacy promise-free selection keeps its refusal.

**Exact manifest (form `collection`).** One deliverable whose revision lists exact members
(`CandidateRef.members`: ref + digest). An inline manifest's digest is `collection_digest`: the member
*set* plus its manifest value, so a reordered manifest is the same content; duplicate refs refuse;
coverage entries must name a listed member ([candidate rules](../../src/mission_control/domain/outputs/rules.py)).
Member requirements (`subject: member`) are judged per member by `member` assessments bound to that
member's ref and digest ([collections](../../src/mission_control/domain/outputs/collections.py));
`record_assessment` accepts only a member the manifest lists and never the producer. The
requirement's `parameters` name the aggregate rule ([contracts](../../src/mission_control/domain/outputs/contracts.py),
`aggregate_rule`): `{"aggregate": "all"}` (default; one held, rejected, waiting or unassessed member
keeps the promise unfulfilled, each named: `MEMBER_HELD`, `MEMBER_REJECTED`, `MEMBER_UNAVAILABLE`,
`MEMBER_UNASSESSED`) or `{"aggregate": "at_least", "minimum": k}` (`AGGREGATE_SHORT`, blocking once
the remaining members cannot reach `k`). Coverage counts only subjects whose manifest entry names a
passing member. A member requirement whose validator is the application's trusted-judgment pin
(the Application Profile's `assessment_pin`, required by every composition; an unresolvable
profile gives `None`, which treats every validator as trusted: fail closed) counts only standing
member assessments citing a KS decision that a `MemberDecisionPort` verified as existing, bound to
that member's exact ref and digest and standing now. Production composes `PostgresMemberDecisions`
([use decisions](../../src/mission_control/adapters/postgres/knowledge/use_decisions.py)) in the
output service, the trusted settlement and the index: the decision must be a 0059 row recorded by
the trusted bridge whose plan is `{"kind": "collection_member", "member": {ref, digest}}`; an
unreadable store verifies nothing (fail closed); a revocation is the bridge's superseding
assessment, after which the citation is no longer standing. Only the
trusted bridge actor may record `ks-use-decision:` evidence; a host or assessor citation is refused
at record time. Host and assessor passes prove only other validators. A collection whose
requirements are all member requirements, at least one required, is promoted by the host at
convergence when the verifier accepted the iteration and its members' standing assessments satisfy
the rule; an optional-only collection stays on the assessment path and never auto-promotes ([fulfillment service](../../src/mission_control/application/outputs/fulfillment.py),
`converge`); one member's pass, a judgment of the manifest or of the set never stands for another.
Judgments still combine conservatively (the worst standing result wins unless the bridge supersedes).

**Concurrency and restart.** Promotion and `pin_set` serialize on the per-run lock, a head moves
only by expected-head compare-and-set (of concurrent promotions of one deliverable exactly one wins;
distinct deliverables all land), and every pinned set's membership digest is its members' digest.
Heads, sets, assessments and decisions are durable rows, so fresh services after a restart pin the
same set and reach the same decisions.

**The verifier reads the whole current set.** For a Goal Loop verifier and a later executor the
produced-output binding keeps every accepted head of the promise and puts the exact producing
operation's newer finalized, unrejected revision in its deliverable's place or beside the others
([materializer](../../src/mission_control/application/context/materialization.py),
`ProducedOutputResolver`; each member records `accepted` or `submitted`). Held and rejected
revisions are never admitted, nor a collection whose held or rejected members keep its aggregate
rule unmet (members only unassessed, or held ones an `at_least` rule tolerates, still deliver; an
inline manifest is delivered as its canonical member-set document). Both receivers also get the **current-set index**, a required file
(`/inputs/current-set/<set>/current-set.json`, never inline): `application_selector` binding
`mc.current-set@1` ([builder](../../src/mission_control/domain/outputs/current_set.py),
`with_current_set_index`, applied in
[GoalDirected preparation](../../src/mission_control/application/programs/goal_directed.py)), resolved
by [`CurrentSetIndexResolver`](../../src/mission_control/application/outputs/current_set.py), the only
selector the [production composition](../../src/mission_control/adapters/temporal/deployment_composition.py)
registers. At seal it pins the set and writes `mc.current_set_index.v1`: per promise its heads with
per-requirement and per-member judgments, distinct count against cardinality, missing coverage, gaps
and the newest finalized non-head candidates labelled `held`, `rejected`, `waiting` or `pending`. The
index is a projection (no fulfillment decision, no authority); the plan is sealed per receiver, so a
redelivery reads the same bytes. Preparation runs in an activity: no workflow command changed.

**Independent work during a goal-scoped wait (OC-D134).** A trusted review wait on a promise with
`evaluation_scope` `goal` or `mission` is reported in `goal_waits` and never holds the invocation, so
the next iteration proceeds while the required promise stays unfulfilled and the verifier's
acceptance is turned into a rejection at convergence. Each later settlement re-resolves the run's
standing goal-scoped review waits through the bridge's `resume`; an approved successor supersedes and
promotes once. An invocation-scoped review still holds its own invocation, and its own later passes
now re-resolve it (before WI-07 a second pass dropped the wait: a held revision is no longer a
submitted output).

**Per-iteration records (W1 D21).** At convergence a requirement-free promise is promoted from the
iteration executor's finalized submission only when the verifier accepted (fix D), so in a rejected
iteration (run 9a1a484e) every text promise stayed unmet. §7 requires "a compact attributed progress
note at each normal iteration handoff", and a rejected verdict still hands off; §2 makes text a
shape-only form (exact bytes) when no requirement is declared. Reading recorded under ESCALATION
H12 (exactness and authority): `scope: iteration` on a requirement-free text or control_record
promise declares it a per-iteration record, fulfilled by that iteration's finalized submission
whatever the verdict; with any declared requirement it goes through the assessment path instead;
every other promise keeps the verdict gate, and a missing note is never fabricated ([fulfillment service](../../src/mission_control/application/outputs/fulfillment.py),
`_iteration_record`). The W1 fixtures author `progress_note` at the default `invocation` scope, so
they need `scope: iteration` for the note to count after a rejection (the W3 fixtures have it).

**Schema.** The 1.8.0 assessment guard binds a `member` subject only under `candidate.value`;
`scripts/release_190/0066_collection_member_assessments.sql`, released in **1.9.0**, replaces the
guard function body to also admit a member listed in a collection revision's `candidate.members`. No table, column, grant or KS change: members reuse the
existing per-report KS assessments.

**Limits.** The trusted bridge judges KS report revisions (the accumulated shape), not yet the
members of a `collection` manifest nor records member decisions yet: until it does, a collection
whose member requirement names the trusted pin waits (`MEMBER_UNASSESSED`) and is never promoted
from host passes or unverified citations; members under other
validators are recorded through the host assessment interface. The
manifest authoring model (`domain/authoring/manifest.py`) still restricts `coverage`/`members` to
structured outputs, so a `collection` with member requirements is authored in contracts, not YAML.
No real model run has exercised this (W3 fixtures exist; paid proofs are the integrator's).

Built / specified / goal: the accumulated-deliverables shape and release 1.9.0's member guard are implemented and
tested on PostgreSQL (integrated locally); collection manifests with member requirements and a paid W3 proof
are not built or not run; qualified: no.

## Citations

- Unit: `tests/unit/outputs/test_collections.py`, `tests/unit/knowledge/test_wi07_report_collections.py`,
  `tests/unit/context/test_wi07_current_set_transfer.py`, `tests/unit/authoring/test_sprint_oc_w3_fixtures.py`.
- PostgreSQL: `tests/integration/postgres/test_wi07_collections_postgres.py` (1.8.0 refuses, 0066 admits).
- Fixtures: `tests/fixtures/manifests/sprint-oc-w3/`.
- [Submission and fulfillment decision](../adr/0058-composable-output-obligations-and-one-submission-act.md);
  [sealed transfer authority](../adr/0061-one-sealed-transfer-plan-and-attempt-receipts.md);
  [proof matrix](../specs/provider-consolidation-2026-10/sprint-oc/PROOFS.md) (W3, RV-02).
