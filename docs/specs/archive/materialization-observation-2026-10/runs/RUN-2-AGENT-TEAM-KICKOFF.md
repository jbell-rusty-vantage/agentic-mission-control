---
type: Agent Configuration
title: "Run 2 Codex agent-team kickoff: Astra lead, Sol workers and truthful acceptance"
description: "Exact user launch instructions and orchestrator prompt for remaining Specs 7-11, approved narrow acceptance additions, disjoint ownership, dependency joins, review and live authorization gates."
tags: [mission-control, agents, kickoff, implementation]
---

# Run 2 Codex team kickoff

Writing this file does not start implementation or authorize paid runs/deployment. Planning base: a2527f6f3c385a7f55272c41d90e6860b44781d0, 2026-10-14. Reinspect the actual tree/ref. The owner approved [RUN-2-PLANNING-AMENDMENTS](RUN-2-PLANNING-AMENDMENTS.md).

## Manual startup

1. Review the planning diff. Start a **new local Codex task** in C:\Users\Pinda\Proyectos\BellLabs\platform\mission-control and select **gpt-6-astra** for the lead using the available model control. A fresh checkout must include the approved uncommitted planning files.
2. Paste the exact prompt below. It explicitly authorizes bounded delegation in that new task and asks for **gpt-6.1-sol** workers. Do not manually start workers against the same writable paths.
3. Confirm the lead reports actual model assignments, HEAD/dirty files, the 40 non-funding remaining issues, claims and offline wave. Review actual owner-boundary requests when their concrete plan is ready.

For the installed CLI, local codex --help verified this syntax:

~~~powershell
codex -C C:\Users\Pinda\Proyectos\BellLabs\platform\mission-control -m gpt-6-astra -s workspace-write
~~~

This starts an interactive lead; paste the prompt there. Select appropriate host approval behavior; no bypass flag is required. Help proves option syntax, **not account model availability**. This planning task's tool schema exposes gpt-6-astra and gpt-6.1-sol; another session must check its actual tools/models. If unavailable, report it and request an owner model choice rather than silently substitute.

Official [Codex subagent guidance](https://learn.chatgpt.com/docs/agent-configuration/subagents), checked 2026-10-14, supports per-agent model assignment subject to availability. Prompt prose does not select the lead model. Do not edit global configuration. This session's spawn API requires fork_turns: "none" for a model override; give fresh workers complete briefs. Follow the actual next session tool schema, not invented parameters.

## Exact copy-paste lead prompt

~~~text
Implement the remaining Mission Control Run 2 scope in this repository with the approved narrow planning additions. You are the orchestrator/integrator. I explicitly authorize bounded subagent delegation: gpt-6-astra for the lead and complex repair/review; gpt-6.1-sol for ordinary workers when supported. Verify/report actual assignments. This text does not select your lead model. If unavailable, request an owner choice, continue independent read-only/offline work, and do not silently substitute.

Read in order:
1. Workspace/repository and scoped AGENTS.md, GLOSSARY.md, relevant accepted general spec/runtime annex.
2. docs/specs/archive/materialization-observation-2026-10/runs/RUN-1-REPORT.md.
3. RUN-2-HANDOFF.md, RUN-2-PLANNING-AMENDMENTS.md, RUN-2-OPENAI-ARCHITECTURE.md and RUN-2-AGENT-TEAM-KICKOFF.md beside it.
4. SPRINT, DECISIONS, PLAN, TEAM-WORKSPACE; original Run 1 dispatch/migration prose is historical where superseded.
5. Actual SPEC-07..11, assigned issue Markdown including Run 2 section, issues.json deps/run2_plan and cited research.

Inspect status, branch, HEAD and local origin/main before work. Do not fetch/reset/stash/clean/overwrite dirty work. Record concurrent changes. Preserve issues/bash.exe.stackdump. Inspect current code before implementing historical defects; CM-10 cloud per-unit branches already exist. Specs 1-6 are integrated: reuse contracts and satisfy deps by evidence. issues.json is current; do not regenerate the original baseline over approved additions.

First deliver offline implementation/tests and concrete handoffs. Paid/control-plane runners stay default-off. Temporal alone schedules; reducers authorize lifecycle/acceptance. Provider done, webhook, uploaded path and human acceptance do not independently grant publication. Retain PostgreSQL inbox/outbox and native reconciliation; no third queue or generic config/model catalog.

Preserve old canonical binding bytes/digests, capability/seed/release identities, grants, fences, approval seals, routing, capacity and retry/reattach/continuation/fork semantics. Shared contracts/migrations/release are integrator-only. Component 1.4.0 is locally proven, not applied live. 0035 already includes mission_request; 0040 lane descriptions, 0041 capacity, 0039 unused: none is independently available for MO-79.

Provider priority: 1 Claude Agent SDK + Anthropic Managed Agents; 2 Deep Agents; 3 Cursor local/cloud; 4 existing hosted OpenAI Agents API; 5 Codex local/cloud; 6 Claude Code local/cloud. This prioritizes unblocked work, not deferred scope. codex_agents is custom HTTP hosted Agents API, not SDK/direct Responses. claude_agent_sdk drives local Claude Code; standalone CLI jobs are separate. No broad Deep Agents, direct API, CM-11, subscription cloud, media UI or S4 promotion.

Astra takes over complex contract/recovery/security/replay work or a worker who fails independent review twice, invents claims, broadens scope or cannot resolve material uncertainty. Give corrective evidence first; narrow/reassign. Sol workers get explicit model override, complete fresh-context task brief and exact file lease. At most five workers/reviewers plus lead, fewer if tool/host limits require. One heavy test process at a time; no recursive delegation without a lead-approved disjoint task.

Use fresh isolated worktrees where appropriate after checking attachments/refs. Never recreate retired Run 1 checkouts. Because approved planning may be uncommitted, a HEAD-only worktree omits it: record a planning-file digest manifest, copy only reviewed docs into new worktrees and verify identical bytes; never copy secrets/private receipts/unrelated dirty code. If establishing a base would disturb concurrent work, complete read-only scoping and ask for the concrete boundary decision. Do not invent an authorized commit.

Workers report baseline, dependency evidence, exact writable lease, tests/risks/claim, then implement only that lease. Independent reviewer is read-only with diff/base/criteria. Integrator reviews small patches and validates joins in integration checkout. Check actual owner authority before commits/merges/pushes; if absent retain reviewable diffs/handoffs and continue independent work. Historical main merge approval is not reusable. Installs, disposable fixtures and external mutations require verified scope/target/authority; missing dependencies are blocked, not auto-installed.

Before paid inference, cloud resource write/deploy, webhook registration, secret write, live migration or production namespace action, establish exact current authority/prerequisites from direct owner evidence. Prepare concrete reviewed scripts/plans first. Historical $10 slice/$40 monthly ceilings are maximums, not new authority or known remaining balance; reconcile unknown spend. Remain within AI Engineer/dev/exact us-east-1 resources where authorized. Never print keys/.env, put org keys in sandboxes or broaden model/account/region/size; ECS Exec retains its explicit gate. Ask only for genuinely missing decisions, explaining their source, while continuing unaffected work.

Managed budget-gate pause/resume is a known acceptance blocker: helpers lack production workflow callers and describe/domain provider pause is unsupported. Boundary holding is separate. Prove/report the gap; do not change flags to manufacture support or downgrade HL-24. Any bounded wiring first needs integrator-owned explicit implementation scope with replay/ceiling/fence tests; paid proof is separate.

Report meaningful wave/owner-boundary progress and at least every 60 seconds while active. Distinguish implemented, offline-tested, exact-placement live-qualified, blocked and unrun. Retain failures, unknown costs and cleanup liabilities. Final done needs criterion-to-evidence on the actual integrated build. Do not publish Linear or weaken missing Biotech SDL gates. Follow this kickoff's task templates, acceptance matrix and handoff checklist.
~~~

## Remaining issues and waves

These are the handoff's **40 non-funding issues**, not all 97 original entries. Eight additional issues remain funding-gated. No issue IDs/deps/scope counts changed.

| Wave | Dispatch/joins | Exit |
| --- | --- | --- |
| A | MO-07; CM-10/09/08/18/13; LS-01 then LS-02..06; MO-65/66/68/69/70 then MO-71; MO-78 prepare/setup | Current-code proofs, offline CLI harness, auth/version/config summaries, S0 manifests. Cloud setup only with its actual gate. |
| B | CM-02/03/04 then CM-05/07 and CM-01; LS-07/08 gated live; MO-63/64; MO-72 then MO-67; MO-74/75/79; MO-77 | Offline production wiring; authorized isolated proofs, ingress/drainer/admission and exact remote worker. |
| C | MO-76; HL-24 then HL-25; carried HL21 owner-binding and local S3 acceptance | Custody, exact remote S2/S3 receipts or named blockers. Budget-pause remains blocked unless explicitly resolved. |
| D | CM-19; S4 only after explicit release | Robust cancellation; separately authorized S4. |
| E | CM-21; HL-20 only after released/implemented S4 | Exact in-scope feature/profile/placement qualification, no blanket flag. |

Critical joins: MO-69 -> MO-71. MO-72 joins MO-65/66/68/69/70/71 plus integrated MO-08/43/04/05; MO-67 joins MO-72/78. CM-04 -> CM-05/07; CM-02/04 -> CM-01; CM-21 joins CM-01/05/09/10. MO-40 -> MO-74/75; MO-75/70 -> MO-79; MO-76 joins MO-40/75. MO-63/64/78 -> MO-77. HL-24 joins MO-74/77/79 and integrated HL-09/17/18/23; HL-25 follows HL-24 and HL-13/17. Use exact issues.json deps plus acceptance evidence joins; fixture evidence is not live prerequisite verification.

## Ownership and worktree discipline

| Owner | Bounded work | Exclusions |
| --- | --- | --- |
| Astra integrator | Shared contracts/enums/describe, bootstrap/preflight/CLI, manifests, public schemas, SQL/release, deployments and docs/index; MO-07/68..72/74/77/78 and acceptance joins | No silent contract widening, migration allocation or main push; lease explicit file sets. |
| Sol Cursor | adapters/cursor/ and leased tests; remaining CM issues | Shared frames/domain/bootstrap/accounting settlement require explicit lease or proposed patch. |
| Sol CLI Skills | Four SPEC-08 .agents/skills/ directories and fake-CLI tests; LS issues | No runtime import/catalog/global auth/config writes. |
| Sol local host | Leased Codex/Claude launch/version/auth and worker-role tests; MO-63..66 | Bootstrap remains shared; no implicit WSL install. |
| Sol Events | Leased signals/ingress/drainer tests; MO-75/76/79 | SQL/bootstrap need integrator lease; coordinate ingress interface with MO-74. |
| Sol hosted evidence/reviewer | Read-only HL21/S3/HL24/25 evidence/tests; adapter fixes only by explicit lease | No paid retries, qualifying flag or broad reopening of completed HL work. |

Activate fewer workers when leases overlap. Claim in canonical ignored .scratch/materialization-observation-2026-10/run2/<issue>/ records exact base/overlay, worktree/branch, writable files, deps and tests. A role is not permission to edit every directory file concurrently. Branch names may follow mo/<issue>-<slug> after collision check. Prefer a task-specific integration worktree to unrelated canonical changes. Do not archive worktrees until reviewed changes and needed ignored receipts are retained.

## Worker and independent-review templates

~~~text
Worker: <IDs, exact outcome>. Actual model: <verify gpt-6.1-sol>.
Repository/worktree: <absolute>; immutable implementation base: <HEAD>.
Approved planning overlay: <digest manifest>; claim: <path>.
Read scoped AGENTS, handoff/amendments/OpenAI evidence, exact spec and issue run2_plan.
Deps established by <source/commits/tests>; unresolved <specific blockers>.
Writable lease <explicit file list>; everything else read-only.
Implement <bounded extension>; non-goals <exact exclusions>.
Minimum tests <existing commands and new negative/regression cases>; fixture/live gates <scope>.
Preserve <digest/approval/reattach/fork/security/cost invariants>.
Report baseline/already-satisfied criteria first, then proceed within lease.
No nested delegation or external/Git/live action beyond verified authority.
Deliver diff/base, criterion evidence, check dispositions, liabilities and blockers.
~~~

~~~text
Independent reviewer (read-only): review <diff/base/worktree> against <issue criteria>.
Check current-code fit/scope, production wiring, negatives, canonical/digest/approval seals,
retry/reattach/fork replay, grants/cleanup, runtime/model/product identity and truthful cost/qualification.
No edits/live providers/tracker messages. Cite file/line findings, severity, smallest remedy.
Distinguish defect, missing evidence and optional suggestion. Review exact submitted diff;
stale review does not approve subsequent changes.
~~~

## Acceptance matrix

| Concern/issues | Offline minimum | Evidence needed for stronger claims |
| --- | --- | --- |
| MO-69/71/72 | Summary determinism/default/unknown identity, pin drift, before-create refusal, redaction and old digests | Actual selected SDK/CLI/host/auth/model/discovery/tool controls for each S0 caller/placement. |
| CM-01/02/03/08/13/21 | Unknown/delayed cost, replay one charge, ambiguous-create reconciliation, request parity, dual SSE normalization | Applicable in-scope CD drills by profile/OS/build; no deferred promotion. |
| LS-01..06 | Fake binaries/schema/argv/refusal/default model/resume/env/redaction | Authorized LS-07/08 actual CLI/auth/permissions and independently verified jobs. |
| HL-24 | Selected tools/skills/version read-back, degradation/refusal, exact approval seal/deny/timeout | Both remote missions, native approval, authoritative wake/recovery, governed publication and settled cost/cleanup; pause blocker visible. |
| MO-74/75/79 | Slim closure/product/session auth, duplicate/reorder/stale generation, normal admission | Disposable restricted PostgreSQL/isolated Temporal persist/wake crash safety; deployed latency only measured with authority. |
| CM-09/MO-76/MO-77/HL24/25 | Missing outputs, size/digest/scope mismatch, replay/stale review, no publication from acceptance | Actual bytes to immutable registered version; remote build/roles/queues/release/S3, laptop-off/restart/cleanup. |
| HL-25 | Hosted HTTP fixtures, shell-approval refusal, index/action recovery, seals and item dedupe | Finite authorized accepted native function approval after spend reconciliation; remote proof follows S2. |

Implemented: reviewed production path exists. Offline-tested: named deterministic checks passed on that revision. Live-qualified: exact account/profile/version/configuration/placement receipts satisfy the criterion. Blocked: concrete input/dependency/authority/proof missing. Unrun remains unrun. These may coexist; none equals mission acceptance.

## Handoff and operational gates

Include issue/spec IDs; base/integrated revision and overlay; changed paths; criterion evidence table; commands and passed/failed/blocked/unrun; original failures; identity/configuration seals; native/emulated semantics; redaction; requested/observed model; cost disposition; resource IDs/retention/custody/cleanup; deps and smallest next step. Public summaries sanitized; raw receipts ignored/private.

Before a gated action present reviewed script/plan, exact target/account/region/namespace/build/config, current prerequisites, allowance and cleanup/cost plan. Historical authority applies only where trusted owner evidence still covers the exact action/conditions. Webhook registration, owner secret script, GitHub App creation, ECS Exec, main merge/push, S4, different model/region/account/size, prod namespace and Linear retain explicit boundaries. This kickoff is not blanket permission.

Carry blockers: exact missing Biotech SDL; live 1.4.0 not applied; incomplete full-owner HL21; S3 acceptance/unknown spend; Managed budget-pause wiring; actual WSL/login/Cursor repo access and AWS owner inputs. Do not invent replacements, claim all checks green or weaken acceptance to finish.
