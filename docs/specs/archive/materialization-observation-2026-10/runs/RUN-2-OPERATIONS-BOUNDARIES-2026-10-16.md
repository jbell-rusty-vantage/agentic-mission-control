---
type: Operational Boundary Record
title: "Run 2 current implementation, evidence and action boundaries"
description: "Current source truth, protected evidence and exact qualification and production boundaries."
---

# Current operational boundary

Current tranche: 2026-10-16, base `a8d69c5b48506c6babcd7f3f74f0b92716423091`,
implementation/review **GPT-6.1 Sol only**. The sprint remains incomplete.
This record supersedes the earlier execution checkpoints; immutable v1/v2/v3
retain their historical statements. Start here, then use the
[ledger](RUN-2-EXECUTION-LEDGER-2026-10-16.md),
[recovery evidence](RUN-2-CURRENT-RECONCILIATION-2026-10-16.md),
[remaining work](RUN-2-REMAINING-GATES-2026-10-16.md),
[G1 mapping](RUN-2-G1-ACCEPTANCE-2026-10-16.md),
[qualification envelopes](RUN-2-QUALIFICATION-ENVELOPES-2026-10-16.md) and
[integration evidence](RUN-2-INTEGRATION-2026-10-16.md).

## Authority and limits

The initial assessment was planning-only. Human implementation authority at14:15
(`messageSentinel_87fc10ba4e708191a8c4006efaba4eb6`) and resumed authority at15:45
(`Sentinel_eb18e769c50c81918eed9c1516f8c8c4`) subsequently covered current W0-W10
source/test/document work and safe isolated validation. Human16:29
`Sentinel_d7f4846f67bc8191a13898542f01bffc` also authorized ordinary bounded
qualification once exact readiness gates pass. No redundant dispatch approval
is needed for an already eligible qualification action.

| Category | USD ceiling, inclusive of attributable prior category spend |
| --- | --- |
| Cursor CLI |20 |
| Cursor Cloud |20 |
| Anthropic local/API/Agent SDK |25 |
| Anthropic Managed Agents, including R native probe |25 |
| OpenAI hosted Agents API |20 |
| AWS test infrastructure |10 |

These are ceilings, not fresh balances. Credits/invoices can remain unknown under
the authorized conservative session/call/time reservations; report that limitation
rather than asserting a hard native currency guarantee. No automatic refill,
new subscription, credential creation, access expansion or provider substitution.
A reported200USD Anthropic API credit expiring October22 is not independently
verified balance/organization evidence and does not increase these ceilings or
fund Claude Code subscription usage. Existing native session/input ceilings
remain unchanged. Cursor uses the specified Auto/Grok4.7 choices.

Production deployment/restarts/publication, shared DB/S3 reconciliation, security
or persistent-access changes, commits/merges/pushes remain separate consequential
effects. No such action occurred in this tranche. The protected admission must
never start/resubmit/send/resume/native-cancel/end-session again.

## What changed and what is proved

R1 private custody completed16:15:31 under existing reversible read/copy authority;
the earlier request for another approval was an interpretation error. Only2946
result bytes and a sanitized manifest were retained privately on Linux. Nothing
in this source tranche reads or rewrites that private capture or the originals.

R2 now has an explicit no-native adoption service and trusted adapter composition,
not merely an inspection planner. It verifies original Temporal inputs, exact
scope/public/internal/harness/generation/native identities, binding/claim/dispatch/
cancellation/family frontiers and pinned capture provenance. A new owner epoch
fences atomic terminal frames. The existing journal settles the original claim
with pinned run-version CAS, then the normal family result service quarantines
the late result. Accepted/delivered cancellation resolves at normal terminal
commit without fabricated provider acknowledgement. Replay preserves the original
authority snapshot and verifies every changed frontier against durable decisions.

| Boundary | Source / checked behavior | Remaining practical limit |
| --- | --- | --- |
| Trusted capture | `application/recovery/terminal_evidence_capture.py`; `adapters/storage/terminal_capture.py` | R1 bridge needs an actual approved private payload-reader backend; bridge tests use owned fake payloads |
| Exact historical inputs/context | `adapters/temporal/terminal_adoption_inputs.py`; `adapters/postgres/terminal_adoption_context.py` | Closed exact histories are read without rematerialization; production history/frontiers not refreshed or exercised by this new adapter |
| Adoption/replay | `application/recovery/terminal_evidence_adoption.py:156` | Permission-gated explicit Python composition; no HTTP route/default enablement or live invocation |
| Epoch-fenced frames | `adapters/postgres/frames/repository.py:263`; `frames/identity.py` | Actual restricted-role disposable PG proves expiry/takeover, dedup/conflict refusal and final usage snapshot; no shared PG write |
| Once-only original settlement | `application/execution/operations/operation_execution.py:1282`; `journaled_operation_execution.py:172,947` | Real memory journal/run-control crash/replay proofs, not installed writer execution |
| Truthful close eligibility | `adapters/postgres/closed_workflow.py:58,130` | Unknown scalar requires digest-bound terminal usage/journal/budget proof; positive pending currency still blocks |

Paths in this table are relative to `src/mission_control/` at the reviewed overlay;
exact hashes are in v4. Cost remains unknown when unknown. This protected binding
admits only slot1/attempt1 and no currency: do not invent currency debt. Positive
admitted currency remains pending unless proven settled. Raw total926070 is
authoritative and retained in ClosingFacts; applicable declared/run token dimensions
alone enter budget accounting. Text custody is distinct from declared file outputs
and accepted product output. Native FINISHED is distinct from workflow completion.

Latest validation: **163 offline tests /15.26s**, one pre-existing Langsmith
deprecation warning; Ruff and formatting on32 files; dependency-skipping mypy on15
source files. A100s full-import mypy attempt timed out; this is not the full type
gate, and `application/programs/service.py` is excluded from the local type claim
because skipped dependencies produce four unchanged alias diagnostics. Two real
disposable PG tests passed15.54s; exact container/network removed, five protected
Biotech services unchanged. Independent Sol review found and verified fixes for
replay authority drift and known-currency replay discharge; no remaining P1/P2
in its explicitly reviewed boundaries. This does not establish a full audit.

## Current qualification facts

Two bounded CLI attempts ran in a newly owned read-only fixture, with no application
dispatch. Neither qualified: Claude Code received429 weekly limit/overage rejection
(reported0 tokens/USD0); Codex0.162.1 requested Sol but its Windows sandbox failed
before reading the file (41278 tokens, invoice unknown). The runner's `done`/
subtype reporting does not override those native failures. No automatic retry,
overage toggle or sandbox/auth modification followed.

Seven bounded authenticated GETs, zero inference/session creations/provider writes,
established separate API readiness: Cursor Cloud models include exact `default`
(Auto) and `grok-4.7`; Anthropic models and Managed Agents listing200, no saved
agents; OpenAI models and hosted `agents=v1` listing200, no saved agents. Sol is
in the API model catalog; this does not amend the existing S3 model envelope.
API authentication does not prove serving quota, billing balance, repository/
environment grants, saved policies or lifecycle qualification. Cursor CLI status
is authenticated but model discovery refuses authentication; expiry is unproved.

Full G1 remains unqualified despite57 lifecycle/transport tests. Actual registry/
alias admission, independent native supervisor/private custody, principal/route,
direct/wrapper descendants/listener absence and host cleanup must still be built
or demonstrated. Transport stays default-off; G1 fixtures do not release S0.

## Ordered continuation

1. Complete full G1 assembly and inspect actual private payload-reader composition;
   keep one editor per seam, lead plus one Sol worker and one heavy/native lease.
   Use the exact files/criteria in the linked gate records. Do not replace native
   supervisor/host evidence with more fixture counts.
2. Prepare exact R2 dry-run request/frontiers/principal/payload identity from current
   installed read-only observations. Only a separately authorized shared-data action
   may invoke the reviewed service. Retain same request through partial completion;
   no direct SQL/status edits, fabricated rejection/ack or protected native control.
3. Repair/confirm CLI readiness separately, then original LS07 -> LS08; after full
   G1/R2, selected S0 -> remaining original18 cells. Ordinary eligible bounded
   dispatch is already authorized. Preserve every original acceptance requirement.
4. Prepare immutable build/current rollback and exact production action envelope
   for R, then R -> S1 -> S2 -> S3 subject to their existing dependency and authority
   gates. No new deployment authority is implied by funding or working catalog GETs.
5. Final W10: migration/data readiness, regression/type gates, original two-project/
   two-mission/native/remote evidence, cost reconciliation, owned cleanup and docs.

Do not redo frozen v1/v2/v3, original migrations, protected inference, account
onboarding or unchanged broad suites. Do not expand into AF-FOLLOWON-01, capability
evolution or Knowledge Services. Preserve inherited dirty documents and other
worktrees; retain all unknowns and failed qualification evidence.
