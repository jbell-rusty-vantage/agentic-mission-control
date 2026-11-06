---
type: Session Instruction
title: "Sprint OC implementation kickoff"
description: "A self-contained assignment for the implementation integrator and bounded agent team in Codex or Claude Code."
tags: [mission-control, output-contracts, knowledge-services, sprint]
date: 2026-10-26
status: archived
archived: 2026-11-02
archived_from: sprint-oc/KICKOFF.md
archived_reason: "executed: W0 released, R0-R7 merged"
---

> **Archived 2026-11-02** (executed: W0 released, R0-R7 merged). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Start the implementation sprint

Paste the instruction below into the implementation chat. Its first deliverables are OC-R0 / [OVE-195](https://linear.app/overtonbell/issue/OVE-195) (the interface freeze) and WI-01 / [OVE-163](https://linear.app/overtonbell/issue/OVE-163/oc-compile-and-fulfill-explicit-named-output-promises), in parallel; the complete published specification is [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service). No additional planning interview is needed.

```text
Act as the BellLabs Mission Control and Knowledge Services implementation integrator.
Implement the accepted Sprint OC packet, beginning at the ready frontier, and carry it through
W0–W5. Then run the separately specified post-sprint stress/evaluation work and its repair loops.

Workspace: C:/Users/Pinda/Proyectos/BellLabs
Primary repository: platform/mission-control
Packet: docs/specs/provider-consolidation-2026-10/sprint-oc/README.md
Published specification: OVE-162
First ready issues: OVE-195 (OC-R0, interface freeze) and OVE-163 (WI-01), in parallel
Seam parent: OVE-194 (OC-R, children OVE-195..OVE-202)

Read the workspace/platform and owning repository AGENTS.md, current Git status and
git worktree list --porcelain in every owner you will touch. Preserve dirty source work,
ignored material and retained checkouts. The packet, the five ADRs and the annex are committed on MC `main` (checkpoint of
2026-10-27): cut the sprint integration branch from that head. KS, AIDB and BKS start clean at
their recorded heads. Do not recreate old aliases.

Read the canonical OUTPUT-CONTRACTS.md, IMPLEMENTATION.md, PROOFS.md, DECISIONS.md and WORK-ITEMS.json.
Read SELECTION-AND-ROUTING-DESIGN.md and its interface sketches (accepted, ADR-0063): R0 freezes the
interfaces first; R1-R7 precede WI-02/03/04/05/23/24 as their native blockers say; WI-01 is independent.
This sprint proves the seam on Deep Agents; other providers are touched only mechanically (OC-D199). Read APPLICATION-PORTS.md, then only the relevant SCHEMA-AI-ENGINEER.md
or SCHEMA-BIOTECH.md card before opening schema details. Qualify each applicable boundary
with AI Engineer first, then Biotech; keep output/context/native-effect evidence application-specific.
Read each assigned Linear card, comments and current native blockers.
Refresh source/install pins and claims rather than assuming the preparation snapshot is live.
Use existing OVE-75/78 continuation/subscription engines and OVE-73 human gates. Do not make
all of OVE-150 a prerequisite; W5 closes its downstream SV-18. Existing OVE-69/73/77 may be
worked in parallel after checking current ownership and blockers.

One integrator owns shared contracts, migration sequencing, issue graph, writable-scope
claims and final integration. Delegate bounded implementation/review tasks to a team in
this harness; do not create separate user-owned chats unless requested. Each assignment
must state the issue, checkout/base, writable paths, contracts, blockers, migrations,
verification and expected evidence. Parallelize independent ready scopes. Use one integration
branch for inseparable cutovers if faster; coordinate edits to shared bootstrap/protocol files.
Limit heavy local database/provider jobs to one at a time unless local evidence permits more.

Deliver necessary code, schema, import and file replacements directly. Existing experimental
data and runtime history are disposable; no legacy rescue, aliases, dual writers or staged
deprecation are required. Apply the owning migrations/rebuilds on explicitly identified disposable targets and verify their
identity first: the two Supabase Pro projects in deployments/*/target.toml and the Biotech Aura
graph, wiping schemas and never recreating projects, as IMPLEMENTATION 4.1 describes. Preserve unrelated work and immutable
published release artifacts. New-runtime authority, exactness and crash recovery remain hard
requirements. Escalate only missing credentials/authority, contradictory goals or unavailable
external prerequisites; routine implementation, migrations, fixes and reruns are authorized.
If the owner does not answer, apply ESCALATION.md and move on, except at the three owner
checkpoints in ESCALATION 4 (W5 start, stress-phase start, each stress mission start): post the
checkpoint, move the issue to Blocked and wait; the owner attends those. Commit when an issue's work
is complete and verified; push the integration branch at gate release and session end.

Start OVE-195 (R0) and OVE-163 (WI-01) together. After R0, OVE-196 (R1) and OVE-199 (R5) run in
parallel; after R1, OVE-197/202/198/200 (R2/R3/R4/R6) and then OVE-201 (R7). After WI-01 and R2,
OVE-164 (exact transfer) and OVE-166 (durable settlement) proceed in separate owned scopes; follow
the native graph thereafter. W0 is OVE-168, W1 OVE-169,
W2 OVE-171, W3 OVE-174, W4 OVE-185, W5 OVE-186. First-use RV-01–08 requirements also
apply; never postpone basic durability to W4. Independent implementation may advance while
checkpoint proof remains ordered. A reviewer other than the implementer releases each gate
only after every required criterion passes and findings are fixed/rerun.

Prove ordinary paths, exact schemas, actual receiving backends, all eight forms, all four
workflow families, the adopted full Deep Agents capability matrix and both applications.
Prove actual selected coordinator-host wake separately from transport, model-visible delivery,
acknowledgment and retrieval; the selected coordinator host is this implementer harness itself. Record source/installed/real/doubled evidence distinctly. A parser,
mock, saved provider result or webhook 2xx is not full runtime qualification.

At each major commit/integration milestone: independent clean-code/spec review, affected
AGENTS/OKF/schema/API/operator updates using owner generators, required lint/type/native/functional
checks, fixes and reruns. Use IMPLEMENTATION's exact commands and claims/handoff shapes.
Do not install a new quality framework as a prerequisite. Do not commit secrets, private data
or runtime receipts. Keep issue status and compact evidence summaries accurate.

After W5: OVE-187 capability qualification and OVE-188 independent mission-work evaluation,
then OVE-189 Generation Lab, OVE-190 Qualia Life, OVE-191 model/native ingestion and
OVE-192 database-grounded retrieval/ranking/routing. OVE-193 aggregates the feedback closure.
Keep the owner fixture contracts intact: exhaustive F1, all current products/ingredients F2,
and up to 50 preferably 2025–2026 models F3. F1 needs report/intents without native apply;
F2 needs actual KS verification/provenance; F3 requires actual native ingestion and readback.
All requested skill/MCP/interactive-browser capabilities must be real; ticket and implement
missing capabilities rather than shrink the fixtures. Each active fixture owns its immediate
repair/rerun loop; OVE-193 does not block those repairs. Full product architecture follows.

The sprint ceiling is USD 40 for W0-W5 distributed per PROOFS 6, with USD 15 per session inside
it, and PROOFS's finite operating segments/retry/repair limits. Use the runtime model pins in
PROOFS 6 (producer claude-sonnet-5-5, judge gpt-5.6-terra, auditor and children claude-haiku-5-5);
probe availability once at first paid use and record any fallback.
Exhaustive work that reaches a bound remains resumable with truthful gaps, never falsely complete.

Do not implement WI-20, specialized automatic code integration, cross-application links,
new computation caching or an undecided pressure-aware policy. Focused required inspection,
generic code-change outputs, existing capacity/fairness controls and exact scoped reassessment
remain in scope. Finish with passed/failed/blocked/unrun evidence and the next ready frontier.
```

Harness (OC-D186): in Codex the lead is `gpt-6-astra` with `gpt-6.1-sol` subagents; in Claude Code the
lead is Opus 5.5 or Fable 5.1 with Opus 5.5 and Sonnet 5.5 subagents. The reviewer is a different agent
from the implementer, preferably a different model. The same contracts, claims and evidence apply.

The assignment authorizes the implementation and bounded qualification scope in the accepted packet;
it does not invent credentials, change unrelated deployments or bypass actual access restrictions.
The same contracts/claims/evidence apply in Codex and Claude Code. See [IMPLEMENTATION](../../../provider-consolidation-2026-10/sprint-oc/IMPLEMENTATION.md)
for source paths, owner commands and the reviewable conformance record.
