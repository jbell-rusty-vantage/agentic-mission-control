---
type: Current Sprint Prerequisite Record
title: "Run 2 supported Codex setup, inclusive budgets and selective data readiness"
description: "Source-bound diagnosis, safe setup correction, attributable cost limits, exact seed effects and minimal remaining actions."
---

# Remaining prerequisites after local integration

The Codex Windows setup prerequisite has a supported local correction. It does
not require stopping the preexisting computer-use process. Commit `d8857f4e`
preserves six existing Windows directory variables and prefers MXC with the
existing elevated fallback. Independent GPT-6.1 Sol review found no P1/P2.
Actual model execution and LS-07 remain unqualified.

The [current integration record](RUN-2-CURRENT-INTEGRATION-2026-10-17.md) and
[completion plan](RUN-2-COMPLETION-PLAN-2026-10-16.md) still govern the sprint.
This continuation used the later [human task authority](RUN-2-PERMISSIONS-AND-ACTIONS-2026-10-17.md).
It did not run inference, log in, change credentials/global settings, restart
shared services, apply seeds, deliver R2B, push or deploy. Cursor interactive
login remains an owner action. Attributable remaining headroom is unproved;
no new paid qualification was attempted here. Later dispatch must honor its
inclusive category ceiling and explicit uncertainty/authority envelope.

## Provenance and evidence boundary

Diagnosis/account/seed observations bind inspected main
`ffcd373f9e6d0533efff30af0d623b975d053cc4`; the setup checks additionally bind
the exact four-file overlay committed as
`d8857f4ee0d5dcada79a2898193dc668863f2f26`.
The [companion manifest](RUN-2-PREREQUISITE-EVIDENCE-2026-10-17.json) pins private
sanitized receipts and relevant source bytes. Private evidence remains under
the retained offline checkout's `.scratch/run2-completion-20261017/prerequisite-closure/`
(abbreviated **P** below). These are observations at recorded times, not current
serving guarantees. Original worktrees and frozen recovery actions are preserved.

## Codex OS32: observed cause and minimal correction

The October16 failure named the now-absent `cua_node/a9ba6825a525118c` runtime.
The current runtime is `a5a02988362ca169`. A bounded current read opened the
node executable's attributes/control handles and read its DACL successfully;
that did not prove the vendor helper could update every runtime DLL.
Existing sandbox accounts were enabled/unlocked, with no password expiry;
no credentials or sandbox-secret files were read.

The supported elevated non-inference probe reproduced OS32 on
`VCRUNTIME140_1.dll` in the current runtime. One-resource, read-only Windows
Restart Manager evidence identified preexisting `codex-computer-use-swift.exe`
PID21100, parent17188, created October16 18:49:38.272108 UTC. No shutdown,
restart, signal or process-wide scan was used. This process was preserved.
The vendor log also records read-ACE grants to the owned Temp directory and
existing `.claude.json` before failure. There is no ACL preimage proving whether
those ACEs were newly added or reapplied; do not claim all security state was
unchanged or blindly roll it back. No write-root grant or operator ACL edit occurred.

Explicit MXC initially returned `0x80070003` with the scrubbed environment.
Adding only six existing nonsecret directory variables made the exact read-only
marker/write-denial command succeed. This controlled comparison establishes a
bootstrap-environment dependency, without identifying which individual variable
is necessary. Keep the six-name allowlist; do not copy the complete environment.

The correction is confined to these paths:

| Owner/file boundary | Change / regression |
| --- | --- |
| CLI runner: `.agents/skills/coding-cli-jobs/scripts/agentjob.py:28-43` | Retain existing `SystemDrive`, `ProgramFiles`, `ProgramFiles(x86)`, `ProgramW6432`, `CommonProgramFiles`, `CommonProgramFiles(x86)` case-insensitively; selected auth and secret/database scrubbing remain |
| Codex adapter: `.agents/skills/coding-cli-jobs/scripts/adapters/codex.py:5-6` | Add `features.prefer_mxc=true`; retain `windows.sandbox="elevated"`, explicit permission/model/auth and resume ordering |
| CLI tests: `.agents/skills/coding-cli-jobs/tests/test_agentjob.py:43-105` | Initial/resume Windows versus POSIX, read/edit/full permission mapping, case-insensitive directory preservation, missing-variable refusal to fabricate, unrelated secret exclusion |
| `.agents/skills/codex-exec/SKILL.md` | Document supported route and the remaining native qualification boundary |

This follows the [official Windows sandbox guidance](https://learn.chatgpt.com/docs/windows/windows-sandbox#enable-mxc).
MXC remains subject to device and managed policy support; the existing permitted
legacy fallback remains. No weaker fallback or global configuration was added.

| Check / private receipt | Disposition and limit |
| --- | --- |
| `P/sandbox-probe-detail.json`, current vendor log | Elevated legacy setup failed/timeout; exact DLL identified. Supervision exit0 is not native success |
| `P/mxc-probe-detail.json` | Explicit MXC failed missing path with original scrubbed environment |
| `P/mxc-bootstrap-detail.json` | Explicit MXC +six existing directory values: native exit0, marker read, write denied, no created file; outer2.047s |
| `P/tests-fixed.json` and `.txt` | 23 focused pure checks passed in1.05s, outer2.140s; two unknown async-config warnings because plugin autoload was disabled and no selected test was async |
| `P/prefer-fixed-detail.json` | Restricted outer-context production-environment probe failed before marker with access-denied diagnostics; retained as nonpass |
| `P/prefer-host-fixed-detail.json` / `prefer-host-fixed.json` | Same preferred-MXC configuration and actual production `child_env`, normal host context: native exit0, marker read/write denied, outer1.937s; owned Job before release, reaped, fresh Temp removed |
| `P/setup-fix-publication.json` | Four reviewed paths, normal commit hooks, staged/HEAD/archive hashes match; no push |

These checks invoke `codex sandbox`, not `codex exec`. They prove the setup
boundary and selected command's denial. Actual exec/model identity, editing
enforcement, tool loading, sandbox-user descendant custody and LS-07/LS-08
remain open. No paid retry is justified solely by this correction.

## Inclusive category budget reconciliation

At October17 04:48 UTC, existing keys allowed Cursor identity GET200, but its
owner-filtered current-cycle spending report returned401; Anthropic organization
cost GET returned401, and OpenAI organization costs GET returned403. Each had an
8s/256KiB ceiling, no redirects/retries, and no raw body/key retention. The Cursor
POST is a documented read-only report. Denials establish unavailable report
access, not zero credit, invalid ordinary inference auth, or permission to add keys.
Use scoped redacted exports from existing billing dashboards when available.
Sources: [Cursor report semantics](https://cursor.com/docs/account/teams/admin-api#get-spending-data),
[Anthropic admin reporting](https://platform.claude.com/docs/en/manage-claude/usage-cost-api),
[OpenAI admin costs example](https://developers.openai.com/cookbook/examples/completions_usage_api#setup-api-credentials-and-parameters).

**Spent** means attributable invoice-backed dollars. **Committed** means an
unreleased category-specific reservation or liability, not cumulative planning
snapshots. None of the six categories has a complete joined invoice/reservation
history. `Unknown` is deliberately retained; zero new calls does not prove zero
prior cost. All ceilings include prior attributable usage and are not refills.

| Category | Inclusive ceiling USD | Spent USD | Committed USD | Remaining USD | Exact missing evidence / retained facts |
| --- | ---: | --- | --- | --- | --- |
| Cursor CLI | 20 | Unknown | Unknown | Unknown | CLI currently unauthenticated; no new CLI inference here. Billing401. Existing Cursor SDK926070 explicit tokens have unknown USD and unproved allocation to CLI/Cloud categories |
| Cursor Cloud | 20 | Unknown | Unknown | Unknown | Identity/model access is not billing. Need run/account/cycle and included/on-demand allocation plus outstanding-session liabilities; no new Cloud session here |
| Anthropic local/API/SDK | 25 | Unknown | Unknown | Unknown | Earlier qualification reports0tokens/USD0 on429, but Window2 reports112976 settled tokens and an earlier native-create uncertainty remains. Need prior attempt billing/auth-product allocation and unreleased reserves; cost report401 |
| Anthropic Managed | 25 | Unknown | Unknown | Unknown | Current retained tranche created0 API inference sessions; this does not prove all-history zero. Need session-level costs, pending liabilities and earlier reservation allocation; organization report401 |
| OpenAI Hosted Agents | 20 | Unknown | Unknown | Unknown | Current retained tranche created0 API inference sessions. Local Codex subscription attempts are a different product; need exact hosted session/account cost and reserve joins; costs403 |
| AWS disposable qualification | 10 | Unknown | Unknown | Unknown | Account-wide budget actual1.04/forecast1.658, limit40; last updated October16 21:03:34.622 UTC and no cost filters. Need resource/time attribution, delayed/unbilled retained-resource charges and exact reservation mapping; do not subtract1.04 from10 |

No paid Cost Explorer call or model experiment was used to measure cost. The AWS
read used existing STS identity and Budgets metadata only; no resource mutation.
The [AWS Budgets pricing page](https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/)
describes the budget service; the actual receipt, not a pricing estimate, supplies
the account-level numbers above.

The retained shared S0 pool evolves **1.35 ->1.85 ->2.85 ->3.85 ->4.85 USD** in
successive conditional reserve snapshots. These are updates to one old10USD
pool, not amounts to sum and not an invoice. The October16 06:55 "unconsumed
Cursor1.00" statement predates the accepted Cursor start. It cannot prove a
current release or new headroom. Category allocation/consumption/release remains
unproved. The historical221222-token missing-ledger liability also remains
unmapped; do not repair it through invented usage. Full3's0.05813115USD figure
is a conditional estimate with margin, not billed spend. Its88153-token total,
other combined windows, and the independent native lower bound overlap.

R2A released its technical slot/attempt and adopted the explicit926070-token
native total; dollars remain unknown. Technical settlement is not billing
reconciliation. Never add cache counters to that total or redispatch the attempt.

At04:54:15 UTC, the Codex app reported weekly quota49% used/51% remaining,
reset epoch1792757236; secondary window unavailable, extra credits balance0.
This shared app-login quota supplies no USD conversion, API-wallet balance,
CLI-account binding, serving-model identity or categorical spending allowance.
No reset was consumed. The earlier local Codex LS-07 attempt used41278 reported
tokens with unknown USD; do not charge it to Hosted20 by vendor name alone.
The reported200USD Anthropic credit email remains unverified account/product
context and does not replenish these inclusive ceilings.

## Biotech: eight pending seeds and one incompatible seed

Read-only installed-state proof already verified Biotech1.3.0,28 migration
receipts, attestation/fingerprint, roles and runtime contracts. The exact32-file
immutable release/path correction is committed as `9eba1395`; no upgrade is
implied. Current selection reports12 replay/8 pending/1 incompatible.

`packages/mission-control-db-contract/src/mission_control_db_contract/seeds.py:761-807`
classifies exact receipts and version compatibility; lines869-907 refuse invalid
dependencies and atomically apply selected records plus receipt. Pending means
the exact key/version receipt was absent in that observation; it does not identify
a failed apply or its cause. Incompatible takes precedence and does not prove
receipt absence. The manifest pins each bundle and its exact source lines.

| Bundle | Source owner | Proposed data effects if separately selected/applied | Current reason / dependency |
| --- | --- | --- | --- |
| `mc.app.biotech.agent-skills@1.0.1` | db-contract + Biotech catalog | 6 records:3 revision2 skill assets and3 decisions | Pending;1.0.0 dependency replay |
| `mc.app.biotech.agent-skills@1.0.2` | db-contract + Biotech catalog | 4 records:author/observe revision3 assets and decisions | Pending; depends on pending1.0.1 |
| `mc.app.biotech.cognition-profiles@1.0.0` | db-contract + Biotech catalog | 54 records:15 assets,15 decisions,24 plugin members | Pending; referenced custody/compatibility still needs proof |
| `mc.app.biotech.environment-kits@1.0.0` | db-contract + Biotech catalog | 12 records:6 environment definitions and decisions | Pending; does not provision environments |
| `mc.app.biotech.signal-skills@1.0.0` | db-contract + Biotech catalog | 2 records:signal skill and decision | Pending |
| `mc.app.biotech.watchers@1.0.0` | db-contract + Biotech catalog | 14 records:7 bounded templates and decisions | Pending; does not start watchers |
| `mc.catalog.approved-assets@1.0.2` | db-contract common catalog | 2 records:Mission Control0.5.0 bundle metadata and decision | Pending;1.0.1 dependency replay |
| `mc.catalog.workflow-parity@1.0.3` | db-contract common catalog | 4 records:StageGraph/GoalDirected v4 metadata and decisions | Pending; does not deploy workers |
| `mc.catalog.artifact-schemas@1.0.0` | db-contract common catalog | 2 records:S0 probe-report schema and decision | Incompatible:requires>=1.4.1 <2.0.0, installed1.3.0 |

These are catalog records, not provider starts, bundle uploads, worker
registrations or service actions. The owners above are repository/data scopes,
not invented human approvers. Select only the acceptance-required target assets
and dependency closure. Original S0/G4a targets AI Engineer1.4.2; verify its exact
existing schema/receipt/custody before proposing changes. Nothing here requires
all eight pending Biotech seeds or a Biotech upgrade. No shared data was applied.

## Minimal next packages and stop/go gates

| Order / compute | Owner and exact boundary | Acceptance / stop condition |
| --- | --- | --- |
| P0 R: retain current source/evidence | Integrator; this record/manifest and existing W0/W10 ledger | Current HEAD/status/source pins; original ten worktrees and frozen R2A/R2B hashes preserved; no relabelling old wheel/runtime evidence |
| P1 R: billing reconciliation | Operator/cost owner; private sanitized cost/reserve ledger only | Join existing dashboard exports to provider/account/product/run/cycle; resolve old4.85pool allocation and liabilities; derive each remaining cap only after attributable spend+commitments are known. No new keys/refill/paid measurement |
| P2 R: native prerequisites | Operator + CLI owner; existing auth route/config/lease only | Owner completes existing Cursor interactive login; fresh status/catalog required. Codex setup correction is done; no inference until exact budget/model/policy/input bounds and original LS-07 gates hold |
| P3 R then separately governed live: R2B | Existing recovery owner; frozen exact action/source only | Current action expired03:47:45 UTC and pins older main. Fresh state/source/expiry review plus exact human authorization required before normal phase-one delivery; never replay frozen packet or alter it in place |
| P4 U/D/L: G1, LS and S0 | Existing W3/W5/W6 owners and file leases | Refresh genuine authenticated isolated serving/build/policy/owner/lease, then original criterion proofs. One executable lease; no protected provider rerun; original18 S0 cells retained |
| P5 R then applicable D/L: data and remote | W4/W7/W8/W9 integrator leases | Select actual acceptance-required seeds; fresh/upgrade/repeat/refusal proof for any new release; exact data authority before apply. Remote R/S1, S2 then S3 retain original dependencies, two-mission, cost/custody/restart/cleanup gates |

For later implementation reuse [the Sol-only team instructions](RUN-2-SOL-EXECUTION-2026-10-16.md):
GPT-6.1 Sol lead plus at most one worker; one executable/fixture/build/native
lease, fresh>=1.5GiB available RAM, stop below1GiB, bounded owned processes and
Temp, independent review on exact hashes. Final integration still requires
applicable regression/architecture/type/release/data/documentation gates from
W10, and exact separate production authority. This continuation's passing setup
probe cannot waive original native, remote, invoice or migration acceptance.

Do not redo R2A, Full3 review/account setup, settled attempts or the Biotech
artifact repair. R2B was rejected by automatic approval review before process
creation because it would mutate a live workflow and commit shared SQL; no intent,
registration, override or SQL commit occurred. Preserve that refusal and its
expired action SHA256`3565f88628e5cbaeebb2b2b1aaeb889f163d723f40c2fbce17257aa927f49f57`.
No workaround or repeated delivery was attempted. Continue only after the exact
approval question already pending with the owner is resolved and a renewed
reviewed envelope exists. No additional confirmation is needed for these
completed independent checks.

Do not expand into next-stage capability evolution, new provider products,
broader CLI/MCP/skill redesign, AF-FOLLOWON-01 or S4. Remaining owner/access needs
are consolidated: existing Cursor login, scoped billing evidence/category
allocation, and exact renewed R2B authority. Native and remote work stays gated
by the original acceptance requirements after those prerequisites are met.


## Later read-only Claude quota candidate

The parent reported a possible unused one-time weekly limit reset in the existing
Claude web/Desktop Settings/Usage, citing the official
[limit-reset help](https://support.claude.com/en/articles/17007452-what-is-a-limit-reset).
Eligibility, expiry and account applicability remain unverified; no account/page
check or reset was performed during closure preparation. This is separate from
cloud credits and API grants. A later read-only check may use normal existing
account access; consuming it requires specific user approval. It does not supply
reconciled spending headroom or authorize another native run.
