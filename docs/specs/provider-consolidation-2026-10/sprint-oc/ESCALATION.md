---
type: Operating Rule
title: "Sprint OC escalation and away-mode heuristics"
description: "Where a blocked question goes, how long to wait, and the default the integrator applies when the owner does not answer; the sprint moves on."
tags: [mission-control, sprint, operations, escalation]
date: 2026-10-27
---

# Escalation and away-mode

The owner's instruction (OC-D190): all infrastructure and credentials are present; escalation should be
rare; when the owner does not answer, apply these heuristics and move on. Only four classes of question
may escalate at all (KICKOFF): missing credential or authority, contradictory goals, unavailable external
prerequisite, and a model/provider/credential decision not already made. Everything else is routine work.

## 1. Where an escalation lands

Write it in all three places in this order, in one short block (what is blocked, what was tried, the
default you will apply, when you will apply it):

1. A comment on the blocked Linear issue, and the issue moved to **Blocked**.
2. A row in the sprint evidence log under the ignored evidence directory and a line in the
   [program ledger](../LEDGER.md) row of the affected document or issue.
3. `NEXT-SESSION.md` in this folder if the session is ending; otherwise the session's running handoff.

Never block the whole sprint on one escalation. Continue every independent ready scope.

## 2. How long to wait

Wait one working turn (continue other work for the rest of the session). If the owner has not answered
by the next session start, apply the heuristic below, record it as a **provisional decision** with the
next free `OC-D` number in [DECISIONS §5](DECISIONS.md#5-sprint-start-operating-decisions-2026-10-27)
and proceed. A provisional decision is reversible: the owner can overturn it, and the integrator must
then rerun the affected proof at the affected boundary.

## 3. Heuristics (apply in this order)

| ID | Situation | Default |
| --- | --- | --- |
| H1 | Two packet documents disagree | Precedence: spec pack annex > accepted ADR > DECISIONS later row > IMPLEMENTATION/PROOFS > KICKOFF. Later explicit owner decisions govern earlier wording. Record the conflict; do not rewrite history. |
| H2 | A credential name exists but the value is missing or rejected | Check `.env`, `deployments/*/target.toml` env names and the Sprint V release bundle names. Do not print values. If still missing: mark the real proof `blocked`, run the same proof on the local disposable target, continue. |
| H3 | Target identity uncertain (project ref, installation id, Aura URI) | Never wipe an unidentified target. Verify against `target.toml` and the stored identity evidence first. If identity cannot be verified, use the local Docker target and leave the remote proof `blocked` with the reason. |
| H4 | A pinned model is unavailable or renamed | Fallback order in PROOFS §6 (same vendor, next cheaper tier). Record the substitution in the evidence row. Never substitute the judge with the producer's vendor. |
| H5 | Sprint budget (USD 40) or session cap (USD 15) would be exceeded | Stop paid cognition. Finish unpaid work (code, migrations, deterministic tests, docs). Mark remaining paid proofs `unrun` with the exact shortfall. Do not borrow from the post-sprint allocation. |
| H6 | An upstream provider, skill or host behaves differently from its documentation | Bounded probe (PROOFS §6 limits), record the observed behavior as source evidence, implement to observed behavior, file a `Bug` issue if it blocks a criterion. |
| H7 | An older card (OVE-69/73/75/77/78) is less built than its status suggests | Build only the seam a Sprint OC criterion needs, attach the evidence to the older card, leave its remainder scoped in a comment; do not expand the sprint to finish the card unless DECISIONS §5 says so. |
| H8 | A schema invariant needs a migration in another owner (KS, AIDB, BKS) | Make it: migrations are part of the work (PROCESS §1.3). Allocate the version at claim time from the live head. |
| H9 | Required capability is unsupported by the selected provider | Refuse truthfully in code, record `unsupported`, author a qualified alternative only if a criterion requires one; never silently waive. |
| H10 | Evidence is ambiguous (passed on local, failed on remote, or reviewer disagrees) | The stricter reading wins. The gate stays closed. One repair round, rerun, then escalate if still ambiguous. |
| H11 | A question is really a product or architecture decision (freshness policy, scheduling priority, cross-app links, product schemas) | Out of scope by DECISIONS §3 and OC-D191. Do not decide it. Note it for a later sprint and continue. |
| H12 | Contradictory goals that no heuristic resolves | Take the reading that preserves exactness, authority and crash recovery (the three hard requirements), record it provisionally, continue. |

## 4. Owner checkpoints (notify and wait; no heuristic applies)

Three moments are the owner's to attend (OC-D203). At each, the integrator posts the checkpoint comment
on the named issue, moves it to **Blocked**, writes `NEXT-SESSION.md`, and starts no paid work for that
phase until the owner answers. Unpaid preparation (fixtures, pins, deterministic probes) continues.

| Checkpoint | Issue | What the owner decides there |
| --- | --- | --- |
| W5 start | [OVE-186](https://linear.app/overtonbell/issue/OVE-186) | Confirms the W5 fixture set (the first full-family real runs in both applications) and whether to watch them live. |
| Stress phase start | [OVE-187](https://linear.app/overtonbell/issue/OVE-187) | Sets the F1/F2/F3 budget (PROOFS §6 leaves it to the owner), confirms the fixture subjects and versions (Generation Lab, Qualia Life, the model set; any addition such as TruDiagnostic), and names the model pins for the stress runs. |
| Each stress mission start | [OVE-189](https://linear.app/overtonbell/issue/OVE-189), [OVE-190](https://linear.app/overtonbell/issue/OVE-190), [OVE-191](https://linear.app/overtonbell/issue/OVE-191) | Sees the frozen rubric and thresholds before the first paid run, and the mission manifest that will be launched. |

## 5. What never happens without the owner

Deleting or rotating credentials; changing a Supabase project, Aura instance or Fly service other than
the identified disposable targets; pushing to any branch other than the sprint integration branches and
`main` at gate release; spending beyond USD 40 for the sprint; starting W5 or any F1/F2/F3 mission before its checkpoint in §4 is
answered; committing secrets, private receipts or fixture data; changing an accepted ADR's decision.
