---
type: Session Instruction
title: "Sprint V agent team workspace"
description: "Ownership, dependency claims, agent briefs, proof receipts and integration rules for the clean verification and knowledge-port refactor."
tags: [mission-control, knowledge-services, sprint-v, agents, implementation]
date: 2026-10-24
status: active
---

# Sprint V team workspace

Start with [repository and database navigation](START-HERE.md), [plan](../sessions/SPRINT-V-PLAN.md), [design](../specs/SPRINT-V-DESIGN.md),
[owner answers](../answer-sets/sprint-v/codex-gpt-6-2026-10-24/ANSWERS.md), then
[work-item manifest](WORK-ITEMS.json) and [proof log](PROOFS.md).
This is the shared coordination workspace. It is not a monorepo package or a replacement schema owner.

## 1. Standing direction

The owner authorizes a full refactor and disposal of existing test data/history. AI Engineer's PostgreSQL
knowledge graph is first, Biotech's versioned Neo4j GraphQL SDL immediately after, both in Sprint V.
BKS is the schema owner. Two complete report types: evidence report and study appraisal.
Existing dirty source work from other sessions remains protected from accidental overwrite.

**Real-work gate is closed.** Only disposable engineering fixtures and bounded model tests before all
four workflow systems, output contracts/context transfer and the Deep Agents provider are complete.
No agent may equate a direct KS proof, Sprint V completion, or a synthetic model run with opening that
gate. SV-18 owns downstream closure, with proof for every required capability and workflow boundary.

## 2. Roles and writable boundaries

| Role | Owns | Must coordinate |
| --- | --- | --- |
| Integrator/spec owner | This packet, task claims, contract decisions, final review and release matrix | The only writer of WORK-ITEMS.json; synthesizes helper reports; no fabricated approval or proof. |
| Schema lead | Common KS component plus AIDB consumer transition; migration naming and types | MC DB author and Biotech schema author; one migration owner per object. |
| KS core lead | K01..K05/K07/K08 core, sealer/oracle, reports and tests | Protocol shapes freeze before MC and BKS clients branch; avoid two agents editing packages/application simultaneously. |
| Biotech lead | schema/source, generator/pin, contracts, kg-ops and K06 protocol binding | Source SDL is authored; pinned/generated artifacts are produced by tooling; source/pin digest agreement required. |
| MC lead | M01..M06, live coordinates, ports, journals, lane projection and tests | Shared protocol and canonical MC annex update; no KS internals in MC runtime. |
| Proof/release lead | Disposable harnesses, model reservations, fault fixtures, evidence manifest and operator runbook | Does not create synthetic human labels or approve its own scientific conclusions. |

At most three helpers plus the integrator in this chat. With that limit, run schema, KS core and MC
baseline in parallel; replace the finished MC baseline helper with Biotech authoring. Root keeps the
specification and integration review. GPT 6.1 Sol helpers are authorized for exploration/assistance.

## 3. Claim protocol and checkouts

1. Read root/domain/repository/scoped AGENTS in the target owner. Run Git from that repository;
   record branch, HEAD, status and `git worktree list --porcelain`. Never use old compatibility paths.
2. Integrator selects only items whose dependencies have reviewed proof. No implementation of a
   dependent contract while its shape is unsettled. Local item IDs are not fake Linear IDs.
3. Refresh existing V issues and file required new OVE integration work with provenance before code
   starts, following the repository process. This packet has not sent messages or filed remote issues.
4. Integrator sets `claim` to `{agent, repository, checkout, branch, base_commit, started_at, paths}`.
   Mutate the manifest serially; this JSON file is not a distributed lock. Conflicting paths prohibit
   concurrent writers. Separate repositories may run independently under the dependency graph.
5. Reuse a suitable checkout or create a managed worktree when isolation is needed. Worktree branch
   names are implementation choices, not paths assumed to exist. Never reset or stash another agent's
   work. Before integration compare actual commits/diffs and conformance, not just agent summaries.
6. States: `specified -> claimed -> implementing -> proof_pending -> review -> complete`;
   `blocked` records the exact missing contract/source/runtime. A passing stub never closes a real
   database/model/runtime gate. Roll back a claim only after its changes are handed off safely.

## 4. Ready-to-use agent briefs

### Schema/core foundation (SV-02/03/04/05)

Implement the new Knowledge Operation Protocol and pure research records from design §§2–6. Start with
shared schema ownership and golden contracts. Create one common operational component and two
disposable app-local installs, then one durable run/sealer/oracle. Remove obsolete run truth paths after
the new seams pass. Existing data has no preservation requirement. Do not import MC into KS core or
copy domain SQL into the common component. Return exact migration/source/type manifests, executed
commands, counts, proof limitations and conformance deviations.

### Reports/verification (SV-06/07/08)

Build evidence report and study appraisal over report v2. Reuse proven integrity mechanics, replace
producer-only coverage with independent final census, and aggregate after authoritative semantic
observations. Bind authority/challenge frontiers, scientific qualifiers, exact-use review and correction
closure. Study certainty and citation support stay separate. Deterministic report_derive cannot invent
entity resolution. Prove against the first PostgreSQL domain binding before Biotech integration.

### Biotech (SV-10/11/12)

Author the next SDL release in BKS's designated source tree, using verified current versioned modules as
input. Update provenance and scoped ownership guidance, generate/verify/pin, then implement graph
report/evidence/admission bindings and custody. Common operational runs remain in app PostgreSQL;
canonical graph writes and marker are one Neo4j transaction. Prove outbox, uncertain writes, duplicate
delivery, revoked eligibility and exact report export. This is required in this sprint, not a follow-up.

### Mission Control (SV-01/13/14/15/16)

First repair live attempt/context propagation in both program families. Build the neutral gateway,
per-invocation tool access, frozen-effect/current-caller contract, journal and receipt-first recovery.
Wire a minimal submission/review/export seam to today's runtime; keep advanced OC implementation in
the downstream gate. Update the canonical knowledge annex to the new versioned contract. Prove actual
dispatch/reconcile through local Temporal/Postgres and both domain services; separate mocked tests.

### Proof and release (SV-09/12/16/17)

Build a direct service harness using locked synthetic or public-source fixtures with explicit provenance,
then exercise both bindings and current MC ports. Paid model tests stay under USD 15/session, with
reservation before calls, discovered/pinned routes and independent producer/judge identities. No live
research accumulation. Package hashes, schema versions, grants, installation commands, test receipts,
failed/blocked/unrun gates and the CLOSED real-work gate belong in the release manifest.

## 5. Handoff and proof format

Every handoff supplies: item ID, source commit and dirty diff digest, changed paths, projected/as-built
deviations, inputs/schema/rubric/model pins, commands and results, cost, retained artifact digests,
remaining limits, next dependency and reviewer. Runtime receipts and secrets stay out of commits;
use ignored `.scratch/sprint-v/proofs/<item>/<run>/` in the owning repository. Commit-safe PROOFS.md
contains summaries and digest references, not credentials or private source text.

An item closes only after a second review checks its seam evidence against the specification. Final
release requires both stores' native proof, current MC integration, clean build/docs checks and an
honest supported-capability matrix. W6 still owns real-world usage readiness.

## 6. Immediate next actions

**2026-10-25 continuation:** the initial kickoff below has been executed. Resume from
[NEXT-SESSION.md](NEXT-SESSION.md), the checkpoint handoff and current WORK-ITEMS states; do not
restart SV-01/SV-02. Review foundations, finish both service paths, connect/prove MC, then cut over.

The owner accepted this workspace and specification on 2026-10-24 (SV-D13). Begin with START-HERE.md,
then record current checkout state and associated tracker items. Claim SV-01 and SV-02 first. In parallel prepare SV-03's schema
ownership inventory and SV-10's SDL source scaffolding, without modifying consumer shapes before K01
is pinned. File/claim the associated tracker items when implementation starts. No code has been built
by this planning workspace setup.
