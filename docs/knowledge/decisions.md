---
type: Concept
category: decisions
title: Decisions
description: Where Mission Control decisions are recorded and what they are: the ADR index grouped by theme (0001 to 0069) with status as of 2026-11-05, the open provider consolidation decisions D2 to D9, the owner directives from the root AGENTS.md summarized by date as durable decisions, and where the owner's answers files live.
tags: [mission-control, decisions, adr, owner-directives, answers, index]
aliases: [ADR index, decision map, open decisions, owner directives, answers files]
questions:
  - Where is this decided, and which decisions are still open?
  - Which ADR governs this behavior and is it accepted?
  - What are the owner's standing directives for this repository?
  - Where do the owner's interview answers live?
updated: 2026-11-02
---

# Decisions

**Authority:** code is what runs; ADRs are what was decided; concepts explain both; program documents are working. The
specification pack that once outranked ADRs is deleted, so on a conflict between a concept and an ADR the ADR holds and the
concept is wrong. Decision records are ADRs (`docs/adr`, status in frontmatter), the glossary (`GLOSSARY.md`, language), the
Sprint OC register [DECISIONS](../specs/provider-consolidation-2026-10/sprint-oc/DECISIONS.md) (OC-D and IA ids with where each
landed), and the owner's answers files below.

## ADR index by theme

Unmarked means accepted. "built, accepted per AS-D36" is an ADR the owner accepted on 2026-11-01 that was implemented under a
`proposed` status; Phase B of the truth pass writes the acceptance into the file. Number 0051 was reserved for the Sandbox Host
placement ADR and never written (placement is funding-gated, ADR-0050 item R31). Neither 0051 nor a missing number is an error.

**Foundation and identity.** [0001](../adr/0001-one-python-distribution-clean-transformation.md) One Python distribution, clean break from the Biotech backend;
[0002](../adr/0002-one-service-two-applications-schema-per-app-database.md) One service, two applications, the schema inside each application database;
[0003](../adr/0003-common-sql-owned-by-db-contract-package.md) Common SQL owned by one installer package; [0009](../adr/0009-common-release-separate-app-authority.md) One release, separate application
authority, no shared checkpoint namespace; [0014](../adr/0014-eve-excluded.md) Eve is not a lane; [0017](../adr/0017-agent-server-runtime-persistence-separate-database.md) Agent Server persistence in
a separate app-bound database.

**Scheduling and execution semantics.** [0004](../adr/0004-temporal-sole-scheduler-transactional-outbox.md) Temporal is the sole scheduler, fed by a transactional outbox;
[0006](../adr/0006-agent-server-required-execution-host-not-scheduler.md) Agent Server hosts async subordinates and schedules nothing; [0008](../adr/0008-ordered-commands-with-urgent-stop-fence.md)
Commands durably ordered; urgent stop is a persisted fence; [0010](../adr/0010-completion-expressions-closed-typed-ast.md) Completion from a closed typed expression, never prose or code;
[0011](../adr/0011-distinct-retry-counters-and-retry-classifier.md) Distinct retry, revisit, iteration and round counters;
[0031](../adr/0031-temporal-lifecycle-synthesis-observe-activity-updates-seeded-forks.md) Provider lifecycles synthesized into Temporal by observe segments;
[0039](../adr/0039-four-independent-progress-mechanisms-compaction-native-first-continuation-sealed.md) Four independent progress mechanisms, none implies another (built, accepted per AS-D36);
[0041](../adr/0041-continuation-is-a-persisted-phase-machine-driven-by-the-operation-workflow.md) Continuation is a persisted phase machine (built, accepted per AS-D36).

**Lanes and providers.** [0005](../adr/0005-deep-agents-first-extend-not-fork.md) Deep Agents first, extended through public interfaces not forked;
[0018](../adr/0018-coding-agents-are-execution-lanes.md) Claude Code, Codex and Cursor are lanes behind one harness protocol; [0019](../adr/0019-coding-lanes-worker-hosted-local-first.md) Coding lanes
worker-hosted first, cloud a second profile; [0030](../adr/0030-cursor-lane-two-profiles-reducer-from-frames-hydrated-fork.md) Cursor is the second lane family with two profiles;
[0035](../adr/0035-seven-lane-profiles-versioned-provider-contracts-and-mission-v2.md) Lane Profiles with versioned provider contracts (seven, now nine) (built, accepted per AS-D36);
[0050](../adr/0050-nine-lane-profiles-claude-managed-and-codex-agents-and-the-mission-data-class.md) Nine Lane Profiles: claude_managed and codex_agents join (built, accepted per AS-D36);
[0052](../adr/0052-remote-session-lane-base-shared-machinery-for-provider-session-apis.md) Remote Session Lane base for provider session APIs (built, accepted per AS-D36);
[0053](../adr/0053-effect-gating-on-closed-hosted-harnesses.md) Effect gating on closed hosted harnesses (held);
[0069](../adr/0069-cross-provider-control-cognition-points-time-travel-and-intervention-on-every-lane.md) Cross-provider control on every lane (proposed 2026-11-05, OVE-224).

**Workflows and authoring.** [0022](../adr/0022-mission-manifest-yaml-authoring-surface.md) Mission Manifest YAML compiles to the typed Mission Definition;
[0029](../adr/0029-mission-chains-compile-to-linked-missions-released-by-outbox.md) Mission chains compile to linked missions released by outbox;
[0034](../adr/0034-mission-manifest-v1-settled-environment-inheritance-chains-agents-hooks.md) Manifest v1 settled: environment inheritance, chains, agents, hooks;
[0068](../adr/0068-parallel-swarm-is-a-stage-graph-profile-and-evaluator-optimizer-runs-on-goal-loop-machinery.md) Swarm is a Stage Graph profile; Evaluator Optimizer runs on Goal Loop machinery (accepted 2026-11-01, AS-D34; draft
until Phase B).

**Capabilities and catalog.** [0012](../adr/0012-coding-effects-are-separate-capabilities.md) Checkout, patch, test, review, push, merge, deploy are separate capabilities;
[0013](../adr/0013-catalog-search-postgres-fulltext-first.md) Catalog search starts with PostgreSQL full-text; [0020](../adr/0020-capability-kinds-canonical-in-catalog.md) Capability kinds canonical
in the catalog; [0023](../adr/0023-capability-kinds-provider-neutral-core-host-projection.md) Provider-neutral capability rows with per-lane host projection;
[0024](../adr/0024-skill-bundle-custody-supabase-storage-digest-paths.md) Skill bundles in a private bucket under digest paths;
[0025](../adr/0025-hybrid-capability-search-rrf-with-lexical-fallback.md) Hybrid capability search with lexical fallback; [0026](../adr/0026-hook-scripts-one-event-vocabulary-projected-per-lane.md)
Hook scripts on one provider-neutral event vocabulary; [0033](../adr/0033-mission-control-skill-is-a-router-over-specific-skill-bundles.md) The mission-control skill is a router over bundles.

**State, context and the transcript.** [0007](../adr/0007-authoritative-state-separate-from-advisory-memory.md) Authoritative state separate from advisory memory and checkpoints;
[0027](../adr/0027-context-packet-tiers-and-workspace-materialization.md) One sealed Context Packet with four expansion tiers;
[0028](../adr/0028-native-event-store-provider-frames-and-materialized-transcript.md) Provider frames persisted verbatim in a Native Event Store;
[0040](../adr/0040-native-frames-normalized-lifecycle-lineage-graph-bounded-coordinator-subscriptions.md) Native frames beside normalized lifecycle, lineage, bounded subscriptions (built, accepted per
AS-D36); [0054](../adr/0054-the-mission-transcript-is-the-replayable-record.md) The Mission Transcript is the replayable record (built, accepted per AS-D36);
[0055](../adr/0055-retention-follows-the-mission.md) Retention follows the mission (built, accepted per AS-D36); [0056](../adr/0056-agents-never-write-tables.md) Agents never write tables (built,
accepted per AS-D36); [0057](../adr/0057-the-precise-fork-closure-family-position-and-the-seed-head.md) Precise fork: closure, family position, seed head (built, accepted per AS-D36).

**Control and humans.** [0032](../adr/0032-interventions-real-queue-inject-cancel-fork-and-subscriptions.md) Real queue, inject, cancel, fork commands and subscriptions;
[0038](../adr/0038-two-origins-of-human-control-over-one-human-task-service.md) Two origins of human control over one Human Task service (built, accepted per AS-D36);
[0049](../adr/0049-deprecate-mission-subscribe-push-in-favour-of-inbox-wait-channels.md) Inbox wait channels replace mission_subscribe push (built, accepted per AS-D36).

**Environments, secrets and signals.** [0037](../adr/0037-mission-control-allocates-workspaces-fork-is-snapshot-plus-packet-plus-conversation.md) Mission Control allocates workspaces; a fork is
snapshot plus packet plus conversation (built, accepted per AS-D36); [0042](../adr/0042-environment-kits-and-two-layer-base-mission-setup-with-one-bootstrap-entrypoint.md) Environment kits, two-layer
setup, one bootstrap entrypoint (built, accepted per AS-D36); [0043](../adr/0043-secret-broker-per-lane-delivery-minted-signal-credentials-never-commit-secrets.md) Secret broker, minted credentials,
never commit secrets (built, accepted per AS-D36); [0044](../adr/0044-additive-instruction-layering-and-structural-config-merge.md) Additive instruction layering and structural config merge (built,
accepted per AS-D36); [0045](../adr/0045-signal-ingress-trust-tiers-signals-are-evidence-never-authority.md) Signal ingress trust tiers; signals are evidence, never authority (built, accepted per
AS-D36); [0046](../adr/0046-watchers-as-compiled-bounded-deterministic-descriptors.md) Watchers are compiled bounded deterministic descriptors (built, accepted per AS-D36);
[0047](../adr/0047-owner-prerequisites-and-preflight-block-launch.md) Owner prerequisites are typed and block launch (built, accepted per AS-D36);
[0048](../adr/0048-knowledge-workspaces-and-mission-branches.md) Knowledge workspaces and mission branches (built, accepted per AS-D36).

**Surfaces.** [0015](../adr/0015-remote-mcp-oauth-no-jwt-forwarding.md) Remote MCP OAuth with PKCE, no JWT forwarding; [0016](../adr/0016-required-ui-surfaces-with-fallback.md) Required UI surfaces
each with a non-UI fallback; [0036](../adr/0036-mission-stream-is-socket-io-over-shared-handlers-postgres-replay-redis-fanout.md) Mission stream: Socket.IO over shared handlers, Postgres replay, Redis
fanout (built, accepted per AS-D36).

**Output contracts and knowledge authority.** [0058](../adr/0058-composable-output-obligations-and-one-submission-act.md) Composable output obligations and one submission act;
[0059](../adr/0059-application-content-and-shared-knowledge-authority.md) Application content ownership and shared knowledge authority;
[0060](../adr/0060-authenticated-origin-and-native-receipt-provenance.md) Authenticated origin and native receipt provenance; [0061](../adr/0061-one-sealed-transfer-plan-and-attempt-receipts.md) One
sealed transfer plan and attempt receipts; [0062](../adr/0062-durable-reactions-and-host-validated-context-contributions.md) Durable reactions and host-validated context contributions;
[0063](../adr/0063-one-resolution-seam-over-declared-lane-model-and-application-registries.md) One resolution seam over lane, model and application registries.

**Documentation and the SDLC.** [0021](../adr/0021-documentation-retrieval-okf-plus-compressed-index.md) Agent docs are an OKF bundle plus a compressed index (built, accepted per AS-D36);
[0064](../adr/0064-one-vendored-sdlc-toolchain-per-repository.md) One vendored SDLC toolchain per repository; [0065](../adr/0065-documentation-automation-bound-to-git-events-not-a-scheduler.md)
Documentation automation bound to git events; [0066](../adr/0066-provider-adapter-for-model-driven-sdlc-steps-cursor-first.md) Provider adapter for model-driven SDLC steps, Cursor first;
[0067](../adr/0067-auto-merge-on-green-checks-during-the-startup-phase.md) Auto-merge on green checks in the startup phase.
## Open decisions (provider consolidation, README section 9)

D1 (accept the program) is overtaken by events. D2 to D9 have no recorded owner answer in the README; what the code and later
records show:

| ID | Question | State |
| --- | --- | --- |
| D2 | Accept design positions 6.1 to 6.9 as the Sprint 0 ADR set | open; the accepted target decisions came from Sprint OC instead (0058 to 0063) |
| D3 | Meaning of `claude_cloud` and `codex_cloud` | partly taken by ADR-0050 (`claude_managed`, `codex_agents` are the controlled cloud placements); the two stubs remain, neither dropped nor built |
| D4 | An `openai-agents` SDK-run lane | not added; the `openai_agents` adapter serves the hosted `codex_agents` profile; the design documents stay draft |
| D5 | Deep Agents default model provider | an Anthropic exact model factory exists ([agent configuration](agent-configuration.md)); no decision recorded |
| D6 | Per-sprint spend ceilings and the T3 tier | set per sprint (OC-D189, [budgets and usage](budgets-and-usage.md)); tier open |
| D7 | Human Gate enrichment timing | open ([human gates](human-gates.md)) |
| D8 | In-run coordinator credential `mc.coordinate` | open; the symbol does not occur in `src/` |
| D9 | Approval timeout default | `keep_waiting` is the code default in the Claude and Codex approval adapters; not recorded as a decision |

## Owner directives, by date

- **2026-10-26** Sprint OC preparation: five target ADRs (0058 to 0062) and 31 issues (OVE-162 and children) replaced an interview-first route.
- **2026-10-29** (OC-D204, OC-D205, OC-D208) Swarm is a Stage Graph profile and Evaluator Optimizer reuses the Goal Loop machinery
  (ADR-0068); make Deep Agents workflows functional through small fixtures, local implementation and review without a per-batch approval pause,
  paid calls, remote operations, push and W5 still separately controlled.
- **2026-10-30** bounded Qualia fixtures over the supplement ecosystem with a USD 100 ceiling and bounded Biotech Aura writes; supersedes the
  earlier OpenAI Agents API design priority; W1 and W2 stay separate (completed 2026-10-31).
- **2026-10-31** sequencing: W0/W1 and general refinement may run locally before cloud coding environments; the direction is cloud development
  environments for Cursor, Claude Code and Codex, deployment architecture and owner education, then the W0/W1 checkpoint, a remote-readiness sprint
  and the first major local-and-cloud deployment ([deployment](deployment.md)); Biotech source and process optimization is a later effort.
- **2026-10-29 and 2026-10-31, BellLabs workspace:** report progress toward the nearest goal (Deep Agents first, deep modules, provider-neutral
  contracts; [goals](goals.md)); startup delivery mode: break things and move fast, migrate disposable targets in-session, commit verified work
  without a separate approval round; never commit secrets or PHI, never write the AI Engineer Aura graph `4773dc72`, report implemented versus
  tested versus qualified truthfully, keep paid spend within the stated ceiling.
- **2026-11-02** Sprint OC resumes beside the Agentic SDLC passes ("knock two birds with one stone": real work doubles as the
  navigation experiment); the owner approved the disposable remote rollout W1 needed (release 1.13.0, seeds, custody, deployment
  files on the AI Engineer remote), which the board had listed as owner-gated.
- **2026-11-05** cross-provider control: the Deep Agents control (inspection, forking, queueing, steering) on every other lane, Cursor first,
  then Managed Agents, Agents API, Codex, Claude Code; fixtures where credentials allow, faithful records otherwise ([design](../specs/provider-consolidation-2026-10/providers/cross-provider-control/DESIGN.md), ADR-0069, OVE-224).
- **Standing rules** (owner, 2026-10-27): commit when an issue's work is complete and verified, push at gate release and session end; no live
  destructive migration, volume deletion, deployment or paid experiment outside an accepted packet's disposable targets and budget.

## Where the answers live

Interview answers carry stable ids (`IA-`, `AS-D`, `OC-D`) and become an ADR, a spec section, a glossary term, an issue or nothing (with a reason):
`docs/specs/agentic-sdlc-2026-11/answers/` (the Agentic SDLC sittings, AS-D1 onward, including the goals text and the Mission Control context
verbatim), `docs/specs/provider-consolidation-2026-10/answers/` (the Sprint OC recovery sitting; finished sets move to the archive) and
[DECISIONS](../specs/provider-consolidation-2026-10/sprint-oc/DECISIONS.md). Program status is in each program's `LEDGER.md`
(`docs/agents/program-workspace.md`). Unbuilt proposals (provider batch, the review loop, next-stage contracts, spec-pack ideas) are
in the [proposals ledger](../specs/proposals-2026-10/LEDGER.md); none is a decision until the owner interview.

Built / specified / goal: the ADRs above are the record; statuses marked built are implemented in source and tests cited by their concepts.

## Citations

- Index sources: [ADR directory](../adr/), [GLOSSARY](../../GLOSSARY.md), [root AGENTS.md](../../AGENTS.md),
  `BellLabs/AGENTS.md`.
- Program: [provider consolidation README](../specs/provider-consolidation-2026-10/README.md),
  [LEDGER](../specs/provider-consolidation-2026-10/LEDGER.md), [DECISIONS](../specs/provider-consolidation-2026-10/sprint-oc/DECISIONS.md).
- Answers: [Agentic SDLC sitting II](../specs/agentic-sdlc-2026-11/answers/AGENTIC-SDLC-SITTING-II-2026-11-02-ANSWERS.md),
  [Sprint OC recovery sitting](../specs/provider-consolidation-2026-10/answers/SPRINT-OC-RECOVERY-SITTING-1-2026-10-29-ANSWERS.md).
- Triage: [truth pass C](../specs/agentic-sdlc-2026-11/truth-pass/mission-control/C-PROGRAMS-ADRS-ARCHIVE.md).
