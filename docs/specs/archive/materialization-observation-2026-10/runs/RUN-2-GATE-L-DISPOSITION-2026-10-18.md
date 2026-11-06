---
type: Sprint Disposition
title: "Run 2 Gate L disposition: which of the 110 issues close in Run 2 and which carry forward"
description: "Generated 2026-10-18 from issues.json slices and the 2026-10-17 status ledger; a disposition for the Claude Code close-out team, not an edit to any issue, SPEC or status."
---

# Run 2 Gate L disposition — 2026-10-18

Owner decision D1 (2026-10-18): Run 2 closes at **Gate L** — local fundamentals (F0, F1, F3, F4), LS-07/08 and all 18 S0 cells on local and Cloud Temporal. Slices R, S1, S2, S3 and funding-held S4 carry forward into the capability-proof program as explicit open streams. F2 (knowledge workflow) is deferred by the owner. This file is derived from `issues.json` (`sprint`, `slice`) and the ledger's `current_status`; it changes neither. The close-out team updates statuses only from receipts.

| Disposition | Count |
| --- | ---: |
| Gate L: close in Run 2 | 21 |
| done (own acceptance) | 38 |
| carried forward: capability-proof program | 30 |
| carried forward: funding-held S4 | 8 |
| deferred (owner) | 13 |

Rule: `sprint: deferred` → deferred; `fully done` → done regardless of slice; slice F/LS/S0 → Gate L; slice S4 → funding-held; slices R/S1/S2/S3/Q → carried forward. Four explicit overrides: HL-20 is funding-held with the S4 placements it qualifies; CM-08 and CM-09 are cursor_cloud-only and carry forward; CM-01 stays in Gate L for its local clauses with cloud settlement carried forward. Issues in Gate L that are `blocked` or `implemented but unqualified` are exactly the Run 2 remaining work; a cell or criterion that cannot be met is recorded failed/blocked, never promoted. The Note column tells the team which clauses of a mixed issue belong to Gate L.

## Gate L: close in Run 2 (21)

| ID | Slice | Current status | SPEC | Title | Note |
| --- | --- | --- | --- | --- | --- |
| CM-01 | F | implemented but unqualified | SPEC-07-cursor-maturity | Cloud and local cost settlement | local cost-settlement clauses in Gate L via cursor_local cells; cloud settlement clauses carry forward (S1) |
| CM-02 | F | implemented but unqualified | SPEC-07-cursor-maturity | Per-run token attribution across all turns | prove on cursor_local cells; cloud attribution carries forward |
| CM-05 | F | implemented but unqualified | SPEC-07-cursor-maturity | Detached bridge and live reattach |  |
| CM-07 | F | implemented but unqualified | SPEC-07-cursor-maturity | Conversation export for forks and continuations |  |
| CM-10 | F | implemented but unqualified | SPEC-07-cursor-maturity | Parallel Cursor units in one run get distinct workspaces | prove local distinct workspaces on cursor_local; cloud fan-out carries forward (SPEC-03) |
| MO-03 | F | implemented but unqualified | SPEC-02-cognition | Back Codex kernel hooks and handle Codex hook trust |  |
| MO-07 | F | active development | GAP-REPORT | Reconcile stale documentation and status statements | documentation reconciliation is the P7 work |
| MO-73 | F | implemented but unqualified | SPEC-06-hosted-api-lanes | Verify Claude SessionStore restore with the custom transport |  |
| LS-05 | LS | implemented but unqualified | SPEC-08-local-cli-skills | Router skill, per-CLI skills, recipes and attributions |  |
| LS-07 | LS | blocked | SPEC-08-local-cli-skills | Live smoke checklist for the CLI open items |  |
| LS-08 | LS | blocked | SPEC-08-local-cli-skills | End-to-end delegation demo from a Claude Code session |  |
| CM-04 | S0 | implemented but unqualified | SPEC-07-cursor-maturity | cursor_local on Windows workers |  |
| MO-08 | S0 | implemented but unqualified | SPEC-03-workspaces-and-placement | WSL2 worker runbook and host preflight for local Claude and Codex lanes |  |
| MO-63 | S0 | implemented but unqualified | SPEC-09-local-harness-path | Lane-only worker role |  |
| MO-64 | S0 | implemented but unqualified | SPEC-09-local-harness-path | Split-host payload custody preflight |  |
| MO-67 | S0 | blocked | SPEC-09-local-harness-path | Temporal Cloud qualification run |  |
| MO-68 | S0 | implemented but unqualified | SPEC-09-local-harness-path | Preflight accepts a local deployments root |  |
| MO-69 | S0 | blocked | SPEC-09-local-harness-path | Binding digest tool for compose-bindings |  |
| MO-70 | S0 | implemented but unqualified | SPEC-09-local-harness-path | missionctl token mint helper |  |
| MO-71 | S0 | blocked | SPEC-09-local-harness-path | S0 probe manifests for all three local lanes |  |
| MO-72 | S0 | blocked | SPEC-09-local-harness-path | Slice S0 end-to-end: local harness path from all three tools |  |

## done (own acceptance) (38)

| ID | Slice | Current status | SPEC | Title | Note |
| --- | --- | --- | --- | --- | --- |
| CM-03 | F | fully done | SPEC-07-cursor-maturity | Typed provider error taxonomy |  |
| CM-13 | F | fully done | SPEC-07-cursor-maturity | One SSE vocabulary per run |  |
| CM-18 | F | fully done | SPEC-07-cursor-maturity | Refuse unknown staged turn text |  |
| CM-19 | F | fully done | SPEC-07-cursor-maturity | Cancel robustness |  |
| HL-04 | F | fully done | SPEC-06-hosted-api-lanes | Extract the Remote Session Lane base from cursor_cloud |  |
| HL-05 | F | fully done | SPEC-06-hosted-api-lanes | Lane conformance suite for every lane |  |
| HL-06 | F | fully done | SPEC-06-hosted-api-lanes | Profile vocabulary for claude_managed and codex_agents, data class and ADR-0050 |  |
| MO-01 | F | fully done | SPEC-02-cognition | Compose bundle custody into every production capability rows resolver |  |
| MO-02 | F | fully done | SPEC-02-cognition | Additive instruction layering and structural config merge |  |
| MO-04 | F | fully done | SPEC-01-environments | Allowlisted child environments for local provider processes |  |
| MO-05 | F | fully done | SPEC-03-workspaces-and-placement | All local lanes use WorkspaceAllocator with manifest policy and cleanup |  |
| LS-01 | LS | fully done | SPEC-08-local-cli-skills | Job and result schemas plus runner core |  |
| LS-02 | LS | fully done | SPEC-08-local-cli-skills | Claude Code adapter |  |
| LS-03 | LS | fully done | SPEC-08-local-cli-skills | Codex adapter with WSL host support |  |
| LS-04 | LS | fully done | SPEC-08-local-cli-skills | Cursor agent adapter with direct Windows launch |  |
| LS-06 | LS | fully done | SPEC-08-local-cli-skills | Safety: env allowlist, redaction, auth guards and doctor |  |
| MO-78 | R | fully done | SPEC-11-remote-worker-on-aws | Temporal Cloud namespace setup and connection probe |  |
| MO-43 | S0 | fully done | SPEC-04-watchers-and-callbacks | Wake channels: missionctl wait, inbox long-poll, MCP inbox_wait, auto-subscribe |  |
| MO-65 | S0 | fully done | SPEC-09-local-harness-path | Refuse Codex ChatGPT login in an isolated CODEX_HOME |  |
| MO-66 | S0 | fully done | SPEC-09-local-harness-path | Re-pin Codex to 0.162.1 and regenerate app-server fixtures |  |
| MO-06 | S1 | fully done | SPEC-01-environments | Compose cursor_cloud with env resolver and workspace lease in production |  |
| MO-10 | S1 | fully done | SPEC-01-environments | mission/v2 environment additions with validation and binding population |  |
| MO-15 | S1 | fully done | SPEC-01-environments | Network policy resolution and per-lane projection |  |
| MO-16 | S1 | fully done | SPEC-01-environments | Persist environment preparation records and readiness levels |  |
| MO-20 | S1 | fully done | SPEC-05-owner-prerequisites | Owner prerequisite store and generated paste-ready content |  |
| MO-21 | S1 | fully done | SPEC-05-owner-prerequisites | missionctl preflight and PREREQUISITES_UNMET launch refusal |  |
| MO-30 | S1 | fully done | SPEC-02-cognition | Per-lane layout table and full cognition projection |  |
| MO-32 | S1 | fully done | SPEC-02-cognition | Plugin expansion into constituent kinds for every lane |  |
| MO-35 | S1 | fully done | SPEC-02-cognition | Publish Cognition Profiles for SDLC, knowledge and mixed work |  |
| MO-40 | S1 | fully done | SPEC-10-ingress-on-vercel | Signal Ingress service, SQL functions and migration 0035 |  |
| MO-44 | S1 | fully done | SPEC-04-watchers-and-callbacks | Watchers: schema, compiled descriptors, evaluator, actions and boundaries |  |
| MO-45 | S1 | fully done | SPEC-04-watchers-and-callbacks | External signal sources: GitHub, Cursor v0 webhook, schedules, worker watches |  |
| MO-46 | S1 | fully done | SPEC-04-watchers-and-callbacks | Standard watcher library |  |
| MO-47 | S1 | fully done | SPEC-04-watchers-and-callbacks | Observe skill v2 and router/author skill updates |  |
| MO-50 | S1 | fully done | SPEC-03-workspaces-and-placement | Generalised cloud branch preparation with large-input references |  |
| MO-52 | S1 | fully done | SPEC-03-workspaces-and-placement | Placement limits, fan-out admission and lane preference |  |
| HL-17 | S2 | fully done | SPEC-06-hosted-api-lanes | Provider webhooks into Signal Ingress as wake signals |  |
| HL-19 | S2 | fully done | SPEC-06-hosted-api-lanes | Owner prerequisites and probes for API lanes |  |

## carried forward: capability-proof program (30)

| ID | Slice | Current status | SPEC | Title | Note |
| --- | --- | --- | --- | --- | --- |
| CM-08 | F | implemented but unqualified | SPEC-07-cursor-maturity | Continuation and fork agent parity on cloud | cursor_cloud-only acceptance (S1) |
| CM-09 | F | implemented but unqualified | SPEC-07-cursor-maturity | Cloud declared-output custody and missing outputs | cursor_cloud-only acceptance (S1) |
| CM-21 | Q | blocked | SPEC-07-cursor-maturity | Cursor qualification drills CD-01..CD-20 |  |
| MO-77 | R | implemented but unqualified | SPEC-11-remote-worker-on-aws | Thin Temporal worker on AWS ECS Fargate (us-east-1) |  |
| MO-79 | R | implemented but unqualified | SPEC-10-ingress-on-vercel | Remote launch-request route on the Signal Ingress |  |
| MO-11 | S1 | implemented but unqualified | SPEC-01-environments | Secret Broker port, sources, minting, per-lane delivery and redaction |  |
| MO-12 | S1 | implemented but unqualified | SPEC-01-environments | Environment Kit capability kind, mission layer and bootstrap entrypoint |  |
| MO-13 | S1 | implemented but unqualified | SPEC-01-environments | Cursor environments and secrets REST adapter (bind/sync) with environment.json ownership check |  |
| MO-14 | S1 | implemented but unqualified | SPEC-01-environments | Git write path: scoped credentials, pre-push guard, repo_pr effect and head SHA artifacts |  |
| MO-22 | S1 | implemented but unqualified | SPEC-05-owner-prerequisites | missionctl setup wizard, probe missions and attestations |  |
| MO-31 | S1 | implemented but unqualified | SPEC-02-cognition | Evidence-based hook event mapping and Cursor binding v2 |  |
| MO-33 | S1 | implemented but unqualified | SPEC-02-cognition | Ambient cognition inventory and policy |  |
| MO-34 | S1 | implemented but unqualified | SPEC-02-cognition | Discovery proof per lane |  |
| MO-41 | S1 | implemented but unqualified | SPEC-04-watchers-and-callbacks | Telemetry Hook Pack, mc-signal CLI and signal_emit tool |  |
| MO-42 | S1 | implemented but unqualified | SPEC-04-watchers-and-callbacks | Gate hooks and remote stop fence |  |
| MO-51 | S1 | implemented but unqualified | SPEC-03-workspaces-and-placement | Knowledge workspaces and output channels |  |
| MO-74 | S1 | implemented but unqualified | SPEC-10-ingress-on-vercel | Vercel ingress project, slim import closure and deployment |  |
| MO-75 | S1 | implemented but unqualified | SPEC-10-ingress-on-vercel | IngressDrainer worker role |  |
| MO-76 | S1 | implemented but unqualified | SPEC-10-ingress-on-vercel | Signed artifact uploads with quarantine and custody |  |
| HL-07 | S2 | implemented but unqualified | SPEC-06-hosted-api-lanes | claude_managed prepare: agents, skills, environments and vaults from pack files |  |
| HL-08 | S2 | implemented but unqualified | SPEC-06-hosted-api-lanes | claude_managed session lifecycle and frame classifier |  |
| HL-09 | S2 | implemented but unqualified | SPEC-06-hosted-api-lanes | claude_managed approvals, Mission Control custom tools and publication |  |
| HL-18 | S2 | implemented but unqualified | SPEC-06-hosted-api-lanes | Data-class policy enforcement and session retention |  |
| HL-23 | S2 | implemented but unqualified | MANAGED-AGENTS-REMOTE-PATH | Provider smoke: Managed Agents and Agents API field confirmation |  |
| HL-24 | S2 | blocked | SPRINT | Slice S2: claude_managed cloud end to end, launched remotely |  |
| HL-11 | S3 | implemented but unqualified | SPEC-06-hosted-api-lanes | codex_agents prepare: saved agents, environment templates, prewarm and vaults from pack files |  |
| HL-12 | S3 | implemented but unqualified | SPEC-06-hosted-api-lanes | codex_agents session lifecycle, recovery recipe and frame classifier |  |
| HL-13 | S3 | implemented but unqualified | SPEC-06-hosted-api-lanes | codex_agents function-tool effect gating and custody |  |
| HL-21 | S3 | implemented but unqualified | SPEC-06-hosted-api-lanes | Hosted lanes: full Cognition Pack and Secret Broker projection |  |
| HL-25 | S3 | blocked | SPRINT | Slice S3: codex_agents hosted end to end, launched remotely |  |

## carried forward: funding-held S4 (8)

| ID | Slice | Current status | SPEC | Title | Note |
| --- | --- | --- | --- | --- | --- |
| HL-20 | Q | blocked | SPEC-06-hosted-api-lanes | Self-hosted placement and Sandbox Host qualification drills (funding-gated) | qualifies the S4 placements; funding-gated with them |
| HL-01 | S4 | blocked | SPEC-06-hosted-api-lanes | Daytona qualification on the current tier |  |
| HL-02 | S4 | blocked | SPEC-06-hosted-api-lanes | SandboxHost port with Docker (WSL2) and Daytona adapters |  |
| HL-03 | S4 | blocked | SPEC-06-hosted-api-lanes | Model Gateway: keyless model access from sandboxes |  |
| HL-10 | S4 | blocked | SPEC-06-hosted-api-lanes | claude_managed self_hosted placement on SandboxHost |  |
| HL-14 | S4 | blocked | SPEC-06-hosted-api-lanes | codex_agents self_hosted executor on SandboxHost |  |
| HL-15 | S4 | blocked | SPEC-06-hosted-api-lanes | claude_agent_sdk on Sandbox Host (real Claude Code harness) |  |
| HL-16 | S4 | blocked | SPEC-06-hosted-api-lanes | codex app-server with remote exec-server executor |  |

## deferred (owner) (13)

| ID | Slice | Current status | SPEC | Title | Note |
| --- | --- | --- | --- | --- | --- |
| CM-06 | - | genuinely not started | SPEC-07-cursor-maturity | Local store and conversation fork, drill-gated |  |
| CM-11 | - | genuinely not started | SPEC-07-cursor-maturity | Model selection with params and validation |  |
| CM-12 | - | genuinely not started | SPEC-07-cursor-maturity | Subagent honesty |  |
| CM-14 | - | genuinely not started | SPEC-07-cursor-maturity | Context occupancy for Cursor |  |
| CM-15 | - | genuinely not started | SPEC-07-cursor-maturity | Plan-then-approve gate |  |
| CM-16 | - | genuinely not started | SPEC-07-cursor-maturity | Local approval and question channel through custom tools |  |
| CM-17 | - | genuinely not started | SPEC-07-cursor-maturity | Cloud agent hygiene sweep |  |
| CM-20 | - | genuinely not started | SPEC-07-cursor-maturity | Follow-up prompt images and per-turn mode passthrough |  |
| CM-22 | - | genuinely not started | SPEC-07-cursor-maturity | No-repo cursor_cloud agents for knowledge work |  |
| MO-53 | - | genuinely not started | SPEC-03-workspaces-and-placement | Cross-lane forks between cloud and local |  |
| SC-01 | - | blocked | DECISIONS | Qualification probes for subscription cloud surfaces |  |
| SC-02 | - | genuinely not started | DECISIONS | claude_cloud experimental launch-and-observe lane |  |
| SC-03 | - | genuinely not started | DECISIONS | codex_cloud experimental launch-and-collect lane |  |

