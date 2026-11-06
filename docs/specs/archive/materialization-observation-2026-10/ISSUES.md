---
type: Specification
title: "Materialization-observation issue index and dependency waves"
description: "Generated index of MO, HL, CM, SC and LS issues with owners, sizes, waves and blockers; issues.json is the source; not yet published to Linear."
tags: [mission-control, issues, agents]
---

# Issue index

Generated from `issues.json` (110 issues, 144 blocking relations). Not published to Linear; publish only with owner authorization (`docs/agents/issue-tracker.md`).

Prefixes: **MO** environment/cognition/observation/workspaces/remote operation, **HL** hosted API lanes and Sandbox Host, **CM** Cursor maturity, **SC** subscription cloud lanes (experimental), **LS** local CLI job skills.

In sprint: 97 issues. Deferred: 13. Scope is defined in [SPRINT.md](SPRINT.md).

## Run 2 approved acceptance additions (2026-10-14)

25 issue records now carry `run2_plan` in issues.json and matching issue Markdown sections. IDs, deps, sizes, in/deferred counts and blocking relations are unchanged. Read [the approved plan](runs/RUN-2-PLANNING-AMENDMENTS.md) and [current handoff](runs/RUN-2-HANDOFF.md); this index's original waves include completed Run 1 issues. `generate_issues.py` recreates the historical baseline and must not overwrite the approved additions. No Linear publication is implied.

## Wave A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup

| Issue | Slice | Owner | Size | Blocked by |
| --- | --- | --- | --- | --- |
| [CM-08 — Continuation and fork agent parity on cloud](issues/CM-08-continuation-and-fork-agent-parity-on-cloud.md) | F | Runtime | S | None |
| [CM-09 — Cloud declared-output custody and missing outputs](issues/CM-09-cloud-declared-output-custody-and-missing-outputs.md) | F | Runtime | M | None |
| [CM-10 — Parallel Cursor units in one run get distinct workspaces](issues/CM-10-parallel-cursor-units-in-one-run-get-distinct-workspaces.md) | F | Runtime | M | None |
| [CM-13 — One SSE vocabulary per run](issues/CM-13-one-sse-vocabulary-per-run.md) | F | Runtime | S | None |
| [CM-18 — Refuse unknown staged turn text](issues/CM-18-refuse-unknown-staged-turn-text.md) | F | Runtime | S | None |
| [HL-04 — Extract the Remote Session Lane base from cursor_cloud](issues/HL-04-extract-the-remote-session-lane-base-from-cursor-cloud.md) | F | Hosted | M | None |
| [HL-05 — Lane conformance suite for every lane](issues/HL-05-lane-conformance-suite-for-every-lane.md) | F | Integrator | M | None |
| [HL-06 — Profile vocabulary for claude_managed and codex_agents, data class and ADR-0050](issues/HL-06-profile-vocabulary-for-claude-managed-and-codex-agents-data-class-and-adr-0050.md) | F | Integrator | M | HL-05 |
| [HL-23 — Provider smoke: Managed Agents and Agents API field confirmation](issues/HL-23-provider-smoke-managed-agents-and-agents-api-field-confirmation.md) | S2 | Hosted | S | None |
| [LS-01 — Job and result schemas plus runner core](issues/LS-01-job-and-result-schemas-plus-runner-core.md) | LS | Skills | M | None |
| [LS-02 — Claude Code adapter](issues/LS-02-claude-code-adapter.md) | LS | Skills | S | LS-01 |
| [LS-03 — Codex adapter with WSL host support](issues/LS-03-codex-adapter-with-wsl-host-support.md) | LS | Skills | S | LS-01 |
| [LS-04 — Cursor agent adapter with direct Windows launch](issues/LS-04-cursor-agent-adapter-with-direct-windows-launch.md) | LS | Skills | S | LS-01 |
| [LS-05 — Router skill, per-CLI skills, recipes and attributions](issues/LS-05-router-skill-per-cli-skills-recipes-and-attributions.md) | LS | Skills | S | LS-01 |
| [LS-06 — Safety: env allowlist, redaction, auth guards and doctor](issues/LS-06-safety-env-allowlist-redaction-auth-guards-and-doctor.md) | LS | Skills | S | LS-01 |
| [MO-01 — Compose bundle custody into every production capability rows resolver](issues/MO-01-compose-bundle-custody-into-every-production-capability-rows-resolver.md) | F | Integrator | S | None |
| [MO-02 — Additive instruction layering and structural config merge](issues/MO-02-additive-instruction-layering-and-structural-config-merge.md) | F | Environment | M | MO-01 |
| [MO-03 — Back Codex kernel hooks and handle Codex hook trust](issues/MO-03-back-codex-kernel-hooks-and-handle-codex-hook-trust.md) | F | Runtime | M | MO-01 |
| [MO-04 — Allowlisted child environments for local provider processes](issues/MO-04-allowlisted-child-environments-for-local-provider-processes.md) | F | Runtime | S | None |
| [MO-05 — All local lanes use WorkspaceAllocator with manifest policy and cleanup](issues/MO-05-all-local-lanes-use-workspaceallocator-with-manifest-policy-and-cleanup.md) | F | Runtime | M | None |
| [MO-06 — Compose cursor_cloud with env resolver and workspace lease in production](issues/MO-06-compose-cursor-cloud-with-env-resolver-and-workspace-lease-in-production.md) | S1 | Runtime | S | None |
| [MO-07 — Reconcile stale documentation and status statements](issues/MO-07-reconcile-stale-documentation-and-status-statements.md) | F | Integrator | S | None |
| [MO-08 — WSL2 worker runbook and host preflight for local Claude and Codex lanes](issues/MO-08-wsl2-worker-runbook-and-host-preflight-for-local-claude-and-codex-lanes.md) | S0 | Environment | S | None |
| [MO-65 — Refuse Codex ChatGPT login in an isolated CODEX_HOME](issues/MO-65-refuse-codex-chatgpt-login-in-an-isolated-codex-home.md) | S0 | Runtime | S | None |
| [MO-66 — Re-pin Codex to 0.162.1 and regenerate app-server fixtures](issues/MO-66-re-pin-codex-to-0-162-1-and-regenerate-app-server-fixtures.md) | S0 | Runtime | S | None |
| [MO-68 — Preflight accepts a local deployments root](issues/MO-68-preflight-accepts-a-local-deployments-root.md) | S0 | Integrator | S | None |
| [MO-69 — Binding digest tool for compose-bindings](issues/MO-69-binding-digest-tool-for-compose-bindings.md) | S0 | Integrator | M | None |
| [MO-70 — missionctl token mint helper](issues/MO-70-missionctl-token-mint-helper.md) | S0 | Integrator | S | None |
| [MO-71 — S0 probe manifests for all three local lanes](issues/MO-71-s0-probe-manifests-for-all-three-local-lanes.md) | S0 | Integrator | S | MO-69 |
| [MO-73 — Verify Claude SessionStore restore with the custom transport](issues/MO-73-verify-claude-sessionstore-restore-with-the-custom-transport.md) | F | Runtime | S | None |
| [MO-78 — Temporal Cloud namespace setup and connection probe](issues/MO-78-temporal-cloud-namespace-setup-and-connection-probe.md) | R | Integrator | S | None |

## Wave B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability

| Issue | Slice | Owner | Size | Blocked by |
| --- | --- | --- | --- | --- |
| [CM-01 — Cloud and local cost settlement](issues/CM-01-cloud-and-local-cost-settlement.md) | F | Runtime | M | CM-02, CM-04 |
| [CM-02 — Per-run token attribution across all turns](issues/CM-02-per-run-token-attribution-across-all-turns.md) | F | Runtime | M | None |
| [CM-03 — Typed provider error taxonomy](issues/CM-03-typed-provider-error-taxonomy.md) | F | Runtime | S | None |
| [CM-04 — cursor_local on Windows workers](issues/CM-04-cursor-local-on-windows-workers.md) | S0 | Runtime | M | None |
| [CM-05 — Detached bridge and live reattach](issues/CM-05-detached-bridge-and-live-reattach.md) | F | Runtime | L | CM-04 |
| [CM-07 — Conversation export for forks and continuations](issues/CM-07-conversation-export-for-forks-and-continuations.md) | F | Runtime | S | CM-04 |
| [HL-07 — claude_managed prepare: agents, skills, environments and vaults from pack files](issues/HL-07-claude-managed-prepare-agents-skills-environments-and-vaults-from-pack-files.md) | S2 | Hosted | M | HL-06, HL-23 |
| [HL-08 — claude_managed session lifecycle and frame classifier](issues/HL-08-claude-managed-session-lifecycle-and-frame-classifier.md) | S2 | Hosted | L | HL-04, HL-07 |
| [HL-09 — claude_managed approvals, Mission Control custom tools and publication](issues/HL-09-claude-managed-approvals-mission-control-custom-tools-and-publication.md) | S2 | Hosted | M | HL-08, MO-14 |
| [HL-17 — Provider webhooks into Signal Ingress as wake signals](issues/HL-17-provider-webhooks-into-signal-ingress-as-wake-signals.md) | S2 | Events | S | MO-40 |
| [HL-18 — Data-class policy enforcement and session retention](issues/HL-18-data-class-policy-enforcement-and-session-retention.md) | S2 | Integrator | S | HL-06 |
| [LS-07 — Live smoke checklist for the CLI open items](issues/LS-07-live-smoke-checklist-for-the-cli-open-items.md) | LS | Skills | S | LS-02, LS-03, LS-04 |
| [LS-08 — End-to-end delegation demo from a Claude Code session](issues/LS-08-end-to-end-delegation-demo-from-a-claude-code-session.md) | LS | Skills | S | LS-05, LS-06, LS-07 |
| [MO-10 — mission/v2 environment additions with validation and binding population](issues/MO-10-mission-v2-environment-additions-with-validation-and-binding-population.md) | S1 | Integrator | M | MO-01 |
| [MO-11 — Secret Broker port, sources, minting, per-lane delivery and redaction](issues/MO-11-secret-broker-port-sources-minting-per-lane-delivery-and-redaction.md) | S1 | Environment | L | MO-04 |
| [MO-12 — Environment Kit capability kind, mission layer and bootstrap entrypoint](issues/MO-12-environment-kit-capability-kind-mission-layer-and-bootstrap-entrypoint.md) | S1 | Environment | L | MO-01, MO-10 |
| [MO-13 — Cursor environments and secrets REST adapter (bind/sync) with environment.json ownership check](issues/MO-13-cursor-environments-and-secrets-rest-adapter-bind-sync-with-environment-json-own.md) | S1 | Runtime | M | MO-11, MO-12 |
| [MO-14 — Git write path: scoped credentials, pre-push guard, repo_pr effect and head SHA artifacts](issues/MO-14-git-write-path-scoped-credentials-pre-push-guard-repo-pr-effect-and-head-sha-art.md) | S1 | Environment | M | MO-05 |
| [MO-15 — Network policy resolution and per-lane projection](issues/MO-15-network-policy-resolution-and-per-lane-projection.md) | S1 | Environment | S | MO-10 |
| [MO-16 — Persist environment preparation records and readiness levels](issues/MO-16-persist-environment-preparation-records-and-readiness-levels.md) | S1 | Integrator | M | MO-10 |
| [MO-40 — Signal Ingress service, SQL functions and migration 0035](issues/MO-40-signal-ingress-service-sql-functions-and-migration-0035.md) | S1 | Events | L | MO-11 |
| [MO-43 — Wake channels: missionctl wait, inbox long-poll, MCP inbox_wait, auto-subscribe](issues/MO-43-wake-channels-missionctl-wait-inbox-long-poll-mcp-inbox-wait-auto-subscribe.md) | S0 | Events | M | None |
| [MO-63 — Lane-only worker role](issues/MO-63-lane-only-worker-role.md) | S0 | Runtime | M | None |
| [MO-64 — Split-host payload custody preflight](issues/MO-64-split-host-payload-custody-preflight.md) | S0 | Runtime | S | None |
| [MO-67 — Temporal Cloud qualification run](issues/MO-67-temporal-cloud-qualification-run.md) | S0 | Integrator | M | MO-72, MO-78 |
| [MO-72 — Slice S0 end-to-end: local harness path from all three tools](issues/MO-72-slice-s0-end-to-end-local-harness-path-from-all-three-tools.md) | S0 | Integrator | M | MO-08, MO-43, MO-04, MO-05, MO-65, MO-66, MO-68, MO-69, MO-70, MO-71 |
| [MO-74 — Vercel ingress project, slim import closure and deployment](issues/MO-74-vercel-ingress-project-slim-import-closure-and-deployment.md) | S1 | Integrator | M | MO-40 |
| [MO-75 — IngressDrainer worker role](issues/MO-75-ingressdrainer-worker-role.md) | S1 | Events | M | MO-40 |
| [MO-77 — Thin Temporal worker on AWS ECS Fargate (us-east-1)](issues/MO-77-thin-temporal-worker-on-aws-ecs-fargate-us-east-1.md) | R | Integrator | M | MO-63, MO-64, MO-78 |
| [MO-79 — Remote launch-request route on the Signal Ingress](issues/MO-79-remote-launch-request-route-on-the-signal-ingress.md) | R | Events | M | MO-40, MO-75, MO-70 |

## Wave C — S2 claude_managed drill, then S3 codex_agents; S1 cursor_cloud end to end; full cognition projection; preflight; signals, gates and watchers

| Issue | Slice | Owner | Size | Blocked by |
| --- | --- | --- | --- | --- |
| [HL-11 — codex_agents prepare: saved agents, environment templates, prewarm and vaults from pack files](issues/HL-11-codex-agents-prepare-saved-agents-environment-templates-prewarm-and-vaults-from.md) | S3 | Hosted | M | HL-06, HL-23 |
| [HL-12 — codex_agents session lifecycle, recovery recipe and frame classifier](issues/HL-12-codex-agents-session-lifecycle-recovery-recipe-and-frame-classifier.md) | S3 | Hosted | L | HL-04, HL-11 |
| [HL-13 — codex_agents function-tool effect gating and custody](issues/HL-13-codex-agents-function-tool-effect-gating-and-custody.md) | S3 | Hosted | M | HL-12, MO-14 |
| [HL-19 — Owner prerequisites and probes for API lanes](issues/HL-19-owner-prerequisites-and-probes-for-api-lanes.md) | S2 | Environment | S | MO-20 |
| [HL-21 — Hosted lanes: full Cognition Pack and Secret Broker projection](issues/HL-21-hosted-lanes-full-cognition-pack-and-secret-broker-projection.md) | S3 | Hosted | M | HL-07, HL-11, MO-30, MO-11 |
| [HL-24 — Slice S2: claude_managed cloud end to end, launched remotely](issues/HL-24-slice-s2-claude-managed-cloud-end-to-end-launched-remotely.md) | S2 | Integrator | M | HL-09, HL-17, HL-18, HL-23, MO-74, MO-77, MO-79 |
| [HL-25 — Slice S3: codex_agents hosted end to end, launched remotely](issues/HL-25-slice-s3-codex-agents-hosted-end-to-end-launched-remotely.md) | S3 | Integrator | M | HL-13, HL-17, HL-24 |
| [MO-20 — Owner prerequisite store and generated paste-ready content](issues/MO-20-owner-prerequisite-store-and-generated-paste-ready-content.md) | S1 | Environment | M | MO-12 |
| [MO-21 — missionctl preflight and PREREQUISITES_UNMET launch refusal](issues/MO-21-missionctl-preflight-and-prerequisites-unmet-launch-refusal.md) | S1 | Integrator | M | MO-20 |
| [MO-22 — missionctl setup wizard, probe missions and attestations](issues/MO-22-missionctl-setup-wizard-probe-missions-and-attestations.md) | S1 | Environment | M | MO-21 |
| [MO-30 — Per-lane layout table and full cognition projection](issues/MO-30-per-lane-layout-table-and-full-cognition-projection.md) | S1 | Environment | M | MO-01, MO-02 |
| [MO-31 — Evidence-based hook event mapping and Cursor binding v2](issues/MO-31-evidence-based-hook-event-mapping-and-cursor-binding-v2.md) | S1 | Runtime | M | MO-03 |
| [MO-32 — Plugin expansion into constituent kinds for every lane](issues/MO-32-plugin-expansion-into-constituent-kinds-for-every-lane.md) | S1 | Environment | S | MO-30 |
| [MO-33 — Ambient cognition inventory and policy](issues/MO-33-ambient-cognition-inventory-and-policy.md) | S1 | Environment | M | MO-30 |
| [MO-34 — Discovery proof per lane](issues/MO-34-discovery-proof-per-lane.md) | S1 | Runtime | M | MO-30 |
| [MO-35 — Publish Cognition Profiles for SDLC, knowledge and mixed work](issues/MO-35-publish-cognition-profiles-for-sdlc-knowledge-and-mixed-work.md) | S1 | Environment | S | MO-30 |
| [MO-41 — Telemetry Hook Pack, mc-signal CLI and signal_emit tool](issues/MO-41-telemetry-hook-pack-mc-signal-cli-and-signal-emit-tool.md) | S1 | Events | M | MO-40, MO-30 |
| [MO-42 — Gate hooks and remote stop fence](issues/MO-42-gate-hooks-and-remote-stop-fence.md) | S1 | Events | M | MO-41 |
| [MO-44 — Watchers: schema, compiled descriptors, evaluator, actions and boundaries](issues/MO-44-watchers-schema-compiled-descriptors-evaluator-actions-and-boundaries.md) | S1 | Events | L | MO-43 |
| [MO-76 — Signed artifact uploads with quarantine and custody](issues/MO-76-signed-artifact-uploads-with-quarantine-and-custody.md) | S1 | Events | M | MO-40, MO-75 |

## Wave D — Workspaces and fan-out, external signal sources; funding-gated S4 (Daytona, SandboxHost, Model Gateway, self-hosted placements, harnesses on Sandbox Host)

| Issue | Slice | Owner | Size | Blocked by |
| --- | --- | --- | --- | --- |
| [CM-19 — Cancel robustness](issues/CM-19-cancel-robustness.md) | F | Runtime | S | None |
| [HL-01 — Daytona qualification on the current tier](issues/HL-01-daytona-qualification-on-the-current-tier.md) | S4 | Environment | S | None |
| [HL-02 — SandboxHost port with Docker (WSL2) and Daytona adapters](issues/HL-02-sandboxhost-port-with-docker-wsl2-and-daytona-adapters.md) | S4 | Hosted | M | HL-01 |
| [HL-03 — Model Gateway: keyless model access from sandboxes](issues/HL-03-model-gateway-keyless-model-access-from-sandboxes.md) | S4 | Environment | M | MO-11, HL-02, MO-74 |
| [HL-10 — claude_managed self_hosted placement on SandboxHost](issues/HL-10-claude-managed-self-hosted-placement-on-sandboxhost.md) | S4 | Hosted | L | HL-08, HL-02 |
| [HL-14 — codex_agents self_hosted executor on SandboxHost](issues/HL-14-codex-agents-self-hosted-executor-on-sandboxhost.md) | S4 | Hosted | M | HL-12, HL-02 |
| [HL-15 — claude_agent_sdk on Sandbox Host (real Claude Code harness)](issues/HL-15-claude-agent-sdk-on-sandbox-host-real-claude-code-harness.md) | S4 | Hosted | L | HL-02, HL-03, MO-73 |
| [HL-16 — codex app-server with remote exec-server executor](issues/HL-16-codex-app-server-with-remote-exec-server-executor.md) | S4 | Hosted | M | HL-02 |
| [MO-45 — External signal sources: GitHub, Cursor v0 webhook, schedules, worker watches](issues/MO-45-external-signal-sources-github-cursor-v0-webhook-schedules-worker-watches.md) | S1 | Events | M | MO-40, MO-44 |
| [MO-46 — Standard watcher library](issues/MO-46-standard-watcher-library.md) | S1 | Events | S | MO-44 |
| [MO-47 — Observe skill v2 and router/author skill updates](issues/MO-47-observe-skill-v2-and-router-author-skill-updates.md) | S1 | Events | S | MO-43, MO-44 |
| [MO-50 — Generalised cloud branch preparation with large-input references](issues/MO-50-generalised-cloud-branch-preparation-with-large-input-references.md) | S1 | Environment | M | MO-11, MO-12, MO-30 |
| [MO-51 — Knowledge workspaces and output channels](issues/MO-51-knowledge-workspaces-and-output-channels.md) | S1 | Environment | M | MO-40, MO-50 |
| [MO-52 — Placement limits, fan-out admission and lane preference](issues/MO-52-placement-limits-fan-out-admission-and-lane-preference.md) | S1 | Runtime | M | MO-21 |

## Wave E — Qualification drills

| Issue | Slice | Owner | Size | Blocked by |
| --- | --- | --- | --- | --- |
| [CM-21 — Cursor qualification drills CD-01..CD-20](issues/CM-21-cursor-qualification-drills-cd-01-cd-20.md) | Q | Runtime | M | CM-01, CM-05, CM-09, CM-10 |
| [HL-20 — Self-hosted placement and Sandbox Host qualification drills (funding-gated)](issues/HL-20-self-hosted-placement-and-sandbox-host-qualification-drills-funding-gated.md) | Q | Integrator | M | HL-10, HL-14, HL-15, HL-16 |

## Deferred (not this sprint)

| Issue | Owner | Size | Blocked by |
| --- | --- | --- | --- |
| [CM-06 — Local store and conversation fork, drill-gated](issues/CM-06-local-store-and-conversation-fork-drill-gated.md) | Runtime | M | CM-05 |
| [CM-11 — Model selection with params and validation](issues/CM-11-model-selection-with-params-and-validation.md) | Runtime | S | None |
| [CM-12 — Subagent honesty](issues/CM-12-subagent-honesty.md) | Runtime | S | MO-30 |
| [CM-14 — Context occupancy for Cursor](issues/CM-14-context-occupancy-for-cursor.md) | Runtime | S | CM-02, CM-11 |
| [CM-15 — Plan-then-approve gate](issues/CM-15-plan-then-approve-gate.md) | Runtime | M | None |
| [CM-16 — Local approval and question channel through custom tools](issues/CM-16-local-approval-and-question-channel-through-custom-tools.md) | Runtime | M | CM-05 |
| [CM-17 — Cloud agent hygiene sweep](issues/CM-17-cloud-agent-hygiene-sweep.md) | Runtime | S | CM-08 |
| [CM-20 — Follow-up prompt images and per-turn mode passthrough](issues/CM-20-follow-up-prompt-images-and-per-turn-mode-passthrough.md) | Runtime | S | MO-30 |
| [CM-22 — No-repo cursor_cloud agents for knowledge work](issues/CM-22-no-repo-cursor-cloud-agents-for-knowledge-work.md) | Runtime | M | MO-40, MO-51 |
| [MO-53 — Cross-lane forks between cloud and local](issues/MO-53-cross-lane-forks-between-cloud-and-local.md) | Runtime | M | MO-50 |
| [SC-01 — Qualification probes for subscription cloud surfaces](issues/SC-01-qualification-probes-for-subscription-cloud-surfaces.md) | Integrator | S | MO-40 |
| [SC-02 — claude_cloud experimental launch-and-observe lane](issues/SC-02-claude-cloud-experimental-launch-and-observe-lane.md) | Runtime | L | SC-01, MO-41, MO-42, MO-50, MO-20 |
| [SC-03 — codex_cloud experimental launch-and-collect lane](issues/SC-03-codex-cloud-experimental-launch-and-collect-lane.md) | Runtime | M | SC-01, MO-50, MO-20 |
