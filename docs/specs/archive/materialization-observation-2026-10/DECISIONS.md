---
type: Specification
title: "Owner decisions: recorded choices, corrections and the decisions still open"
description: "Records the owner's 2026-10-12 decisions (API billing approved; Cursor, Anthropic Managed Agents and OpenAI Agents API lanes at full maturity; subscription cloud lanes experimental; local CLI skills outside Mission Control), the evidence-based corrections to them, and the remaining open decisions with recommendations."
tags: [mission-control, specifications, decisions, providers]
---

# Owner decisions

## Recorded decisions (owner, 2026-10-12, second brief)

| # | Decision | Effect |
| --- | --- | --- |
| R1 | **API billing is approved.** Missions may use `CURSOR_API_KEY`, `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`, for both knowledge and code work. | Supersedes the earlier D4 concern for API lanes. Subscription terms still matter for the local CLI skills and the subscription cloud lanes (R5). |
| R2 | **Cursor programmability is settled.** Build `cursor_local` and `cursor_cloud` to full maturity. | [SPEC-07](SPEC-07-cursor-maturity.md) |
| R3 | **Anthropic hosted lane: Managed Agents API.** | New profile `claude_managed` ([SPEC-06](SPEC-06-hosted-api-lanes.md)). See correction C1. |
| R4 | **OpenAI hosted lane: OpenAI Agents API with the Codex harness, sandboxed.** | New profile `codex_agents` (SPEC-06). See correction C2. |
| R5 | **Subscription cloud products come after the API lanes:** `claude_cloud` as an experimental launch-and-observe lane, and `codex_cloud` as an experimental launch-and-collect lane. They are documented now and built in a later wave. | [PLAN](PLAN.md) wave E (SC-01 to SC-03) |
| R6 | **Local agent skills for driving the Cursor, Codex and Claude Code CLIs**, outside the Mission Control lifecycle. They use the owner's local credentials: `CURSOR_API_KEY`, the Claude subscription and the ChatGPT/Codex subscription. They are composed into this repo; community or official skills are acceptable. | [SPEC-08](SPEC-08-local-cli-skills.md) |
| R7 | **Full intervention, lifecycle control and workflows are expected on every API lane**, as far as each provider allows. | The SPEC-06 operation matrices declare exactly what is native, emulated or unsupported. |

## Recorded decisions (owner, 2026-10-12, third brief)

| # | Decision | Effect |
| --- | --- | --- |
| R8 | **O1 approved:** the Claude Agent SDK and Codex app-server lanes may run on rented sandboxes (Sandbox Host). | HL-15 and HL-16 in scope |
| R9 | **O2 decided:** Docker on WSL2 is the local fallback and first adapter; **Daytona** is the managed sandbox provider. `DAYTONA_API_KEY` is in `mission-control/.env`. Modal and others stay possible later. | HL-01 becomes Daytona qualification, not a three-way spike; HL-02 builds the Docker and Daytona adapters |
| R10 | **O3 approved:** profile names `claude_managed` and `codex_agents`. | HL-06 |
| R11 | **D3 partly decided:** deploy the public callback endpoints (Signal Ingress) on **Vercel** with the owner's Overton account. Whether the whole Mission Control API can live on Vercel is reviewed in the plan pass. | MO-40 deployment target |
| R12 | Install the Codex CLI and the official `codex-plugin-cc` plugin on the owner's machine. | Done 2026-10-12: Codex CLI 0.162.1 (Windows, npm global) and plugin `codex@openai-codex` 1.0.6 at user scope. **Pending owner steps:** `codex login`, then `/codex:setup` in Claude Code. The WSL install follows with MO-08, because WSL has no Node yet. |
| R13 | **Mission Control keeps a local programmatic path** for the Claude Code, Codex and Cursor harnesses through Temporal, local or Cloud, separate from the SPEC-08 skills. | Plan adds the local-harness slice S0 |

## Sprint scope (owner, 2026-10-12, fourth brief)

| # | Decision | Effect |
| --- | --- | --- |
| R14 | The sprint covers the direct-to-provider CLI skills, the real API lanes for Anthropic and OpenAI, and cloud environment and cognition materialization and observation. The owner approved the final pass. | [SPRINT.md](SPRINT.md) is authoritative |
| R15 | **Assumed from the recommendation (the owner did not object):** Cursor P0 and P1 are in; Cursor P2 levers are deferred; slice S0 (local harness path) is in, first. | Issues carry `sprint: in \| deferred` |

## Readiness decisions (owner, 2026-10-12, fifth brief)

| # | Decision | Effect |
| --- | --- | --- |
| R16 | **No paid Daytona tier for now.** Make Daytona work on the current tier and raise the tier later for long-running work. | On Tier 1/2, sandboxes reach only Daytona's essential-services list, which includes `*.vercel.app`, `*.anthropic.com`, `*.openai.com`, `*.chatgpt.com`, GitHub and the package registries ([research/daytona.md](research/daytona.md) §4). The sprint therefore serves the Signal Ingress **and the Model Gateway** from the Vercel project's `*.vercel.app` host (R17). Codex's remote executor and Managed Agents self-hosted keep their loops outside the sandbox. HL-01 records the observed tier; `describe()` reports `egress_control: org_essential_services_only` below Tier 3. Tier 3+ is needed later only for strict per-sandbox allowlists, custom hosts, open-web research inside a sandbox, or pools above 10 vCPU (Tier 1) / 100 vCPU (Tier 2). Daytona's $200 free compute credit covers the S4 drills. |
| R17 | **Vercel: Pro**, team `overtons-projects` (the owner authenticated through Cursor). | Verified 2026-10-12: the Vercel CLI (`npx vercel`) is logged in as the owner with two Pro teams, **and its current scope is the other team (`vantage-4d3db9ef`)**, so every CLI command passes `--scope overtons-projects`. The claude.ai Vercel connector in Claude Code sees `overtons-projects` only. The `vercel-plugin` Claude Code plugin was installed but disabled and is now enabled. The ingress and the Model Gateway use the project's production `*.vercel.app` host; no custom subdomain is needed (a custom domain would not be reachable from Daytona Tier 1/2). SPEC-10 phase 2's **Model Gateway routes move into this sprint** (HL-03). |
| R18 | **Live database upgrade approved.** | **Done 2026-10-12:** release 1.3.0 (0001–0034, fingerprint `sha256:3154fa8d…`) is applied, verified and seeded on both live projects through the `LIVE_PLAN.md` procedure. The protected-data diff was identical (0 differences) on both. Biotech first needed `pg_trgm` in schema `extensions`, which was provisioned. The storage seed `mc.storage.capability-bundles` (a private bucket plus `storage.objects` policies) was held back at first because LIVE_PLAN §6.5 gates storage separately. The owner then approved it, and it was applied the same day; qualify-after passes on both projects. Evidence: `docs/qualification/two-project/*/20261012-live-130/`. Release **1.4.0** (slots 0035–0039 plus the restricted ingress login role) is **pre-approved**: the integrator applies it after the disposable-cluster proofs and local PostgreSQL tests pass, with the same `qualify before → apply → verify → seed → qualify after` evidence. |
| R19 | **Checkpoint the tree:** commit all documentation and code changes locally and push to `origin/main`. | Done 2026-10-12. The team branches from that commit, and the S0 worker runs committed code. |
| R20 | **Temporal Cloud namespaces chosen.** The API key is `TEMPORAL_CLOUD_API_KEY` in `.env` (an account-owner user key, valid until 2027-09-01). | Created 2026-10-12 in `aws-us-east-1` with API-key auth: **`mission-control-dev.ih0e7`** (7-day retention) for every sprint drill and MO-67, and **`mission-control-prod.ih0e7`** (30-day retention), reserved for real workflows after qualification. The existing `verification-cph-20260908.ih0e7` is left untouched. The gRPC endpoint is `us-east-1.aws.api.temporal.io:7233`. `.env` gains the non-secret names `TEMPORAL_CLOUD_ADDRESS`, `TEMPORAL_CLOUD_NAMESPACE` and `TEMPORAL_CLOUD_NAMESPACE_PROD`. A process selects Cloud with `TEMPORAL_TARGET=cloud`, `TEMPORAL_ADDRESS=$TEMPORAL_CLOUD_ADDRESS` and `TEMPORAL_NAMESPACE=$TEMPORAL_CLOUD_NAMESPACE`; local development keeps `localhost:7233`/`default`. |
| R21 | **Defaults the owner did not object to:** the Claude worker uses `ANTHROPIC_API_KEY` (no subscription login on the worker), and Codex is re-pinned to **0.162.1**. | MO-68/MO-69 and the S0 runbook use them. The `~/.codex/config.toml` default of `danger-full-access` remains the owner's choice; jobs and lanes override it. |
| R23 | **Knowledge workspace repos.** | Biotech: **`Overton77/bell-missions-biotech`**, created private on 2026-10-12 with `README.md`, `AGENTS.md` (knowledge-work conventions) and `outputs/`. AI Engineer: the existing **`Overton77/bell-missions-ai-engineer`**, renamed from `ai-engineer-industry-cloud-automated-research` (GitHub redirects the old URL; the local checkout keeps its folder name at `aiengineer/ai-engineer-industry-cloud-automated-research`, with its remote updated). Its current content is obsolete and is reset when the first knowledge mission configures it. The repo is **public**, so mission outputs would be public until it is made private. These are the Application Bindings' `application_knowledge_repo` values (SPEC-03 §4). |
| R24 | **Cursor C7 resolved: the repo's `.cursor/environment.json` is Mission Control-owned.** | The stale "Biotech backend" file is replaced by `mc:envkit/mission-control-dev@1`. It uses the same Docker image (minus the `biotech-meta` bits, plus `make`, `jq` and `ripgrep`). `install` = `uv sync --frozen --group biotech --group dbcontract` plus a Compose config check. `start` = start Docker, then the bootstrap entrypoint `.mission/setup/run --phase start` when present (SPEC-01 §1). The Compose stack starts in a background `infra` terminal instead of blocking every agent start. The `name` carries the kit marker that preflight's mc-owned check reads (SPEC-01 §7). The envkit catalog bundle (MO-12/MO-13) adopts these files as its first rendered output. |
| R25 | **Provider GitHub access.** The Claude and Codex GitHub integrations have full access to the owner's GitHub and see `mission-control`. The current `CURSOR_API_KEY` stays (no new Cursor keys for now). | A3 and X2 (SPEC-05) are attested. Cursor C3 still needs the Cursor GitHub app to see `mission-control` and both knowledge repos. |
| R26 | **Mission Control GitHub App** is being created by the owner (2026-10-12). | `.env` names: `MC_GITHUB_APP_ID`, `MC_GITHUB_APP_INSTALLATION_ID`, `MC_GITHUB_APP_PRIVATE_KEY_PATH` (a `.pem` path outside every repo). Permissions: Contents RW, Pull requests RW, Metadata R; webhook off; installed on `mission-control`, `bell-missions-biotech` and `bell-missions-ai-engineer`. Until it lands, the fallback is the owner's `gh` login as `Overton77`; the active `gh` account on this machine is `jbell-rusty-vantage`, so the fallback must select `Overton77` explicitly. |
| R22 | **Drill budgets and models.** At least **$10 per slice**. Cursor: **Auto** and **Grok 4.7**. OpenAI: **`gpt-6-luna`**. Anthropic: **`claude-sonnet-5-5`**. | See the drill table in [SPRINT.md](SPRINT.md#drill-budgets-and-models). Every model id was verified on 2026-10-12 against the provider's model list with the owner's keys (read-only). |

## Sharpening decisions (owner, 2026-10-12, sixth brief)

Context: [MANAGED-AGENTS-REMOTE-PATH](MANAGED-AGENTS-REMOTE-PATH.md) (the owner's managed-agents question) and [SPEC-11](SPEC-11-remote-worker-on-aws.md). R27 and R28 are the owner's words. R29–R33 adopt the proposals R-NEW-1 to R-NEW-5 from that document, which the owner asked to be folded into the plan.

| # | Decision | Effect |
| --- | --- | --- |
| R27 | **Hosted lane order: `claude_managed` first, then `codex_agents`.** `claude_cloud` and `codex_cloud` stay deferred (confirms R5). | S2 runs before S3. HL-25 (the S3 drill) is blocked by HL-24 (the S2 drill). |
| R28 | **A thin Temporal worker deployment is permitted. Platform: AWS ECS Fargate in `us-east-1`**, one service per application, starting with AI Engineer, 0.5 vCPU / 2 GiB, no inbound path, $40/month AWS budget with alerts. Fly.io, Temporal Serverless Workers, Lightsail and Vercel were considered and rejected (SPEC-11 §1). | New slice **R**: MO-78 (namespace setup), MO-77 (worker). The WSL2 worker becomes lane-only for local lanes once the AWS worker is live (one base worker per namespace and application). Pre-approved in TEAM-WORKSPACE. |
| R29 | **Remote launch through the Signal Ingress** (R-NEW-1): `POST /v1/ingress/{app}/missions:request` writes an inbox row; the IngressDrainer admits it through the normal application handler. Vercel still holds no Temporal credentials. | MO-79. SPEC-10 §2 gains two routes. |
| R30 | **Minimal file-based prepare for the hosted lanes** (R-NEW-3): `claude_managed` and `codex_agents` read checked-in pack files, so S2 and S3 do not wait for the S1 foundations (MO-30, MO-11). | HL-07 and HL-11 depend only on HL-06 and HL-23. HL-21 later swaps in the full projection. HL-07 to HL-09 move to wave B. |
| R31 | **Slice S4 is funding-gated** (R-NEW-4): Daytona, SandboxHost, the Model Gateway, both self-hosted placements and the self-run harnesses on Sandbox Host stay in the sprint but start only when the owner releases them. | HL-01, HL-02, HL-03, HL-10, HL-14, HL-15 and HL-16 are in wave D and marked `Gate: funding`. HL-20 qualifies them; the cloud placements qualify in HL-24 and HL-25. |
| R32 | **No second scheduler** (R-NEW-5): Vercel Workflows and provider-native composition are not used as Mission Control schedulers. Temporal stays the sole scheduler (ADR-0004). | Recorded only |
| R33 | **Provider-native composition inside one lane turn** (gap G-R4): read-only knowledge missions on `claude_managed` may enable `multiagent` and `user.define_outcome`. Outcome results are evidence for the Completion Contract, never acceptance. | HL-08 work item; SPEC-06 §4.2 |

**Provider smoke first.** HL-23 confirms the exact request shapes, Q-M1, Q-O2 and the `gpt-6-luna` acceptance before lane code depends on them, at under $1 per provider from the S2 and S3 budgets.

## Corrections the evidence forces

Sources: [research/anthropic-managed-agents.md](research/anthropic-managed-agents.md) and [research/openai-hosted-agents.md](research/openai-hosted-agents.md), read 2026-10-12.

- **C1. Managed Agents is not the Claude Code harness.**
  - It runs Anthropic's own hosted loop, with the tools `bash`, `read`, `write`, `edit`, `glob`, `grep`, `web_fetch` and `web_search`, plus custom tools, remote MCP, skills and multiagent threads.
  - It does **not** load `CLAUDE.md` or `AGENTS.md`, `.claude/agents`, settings hooks, plugins or `.mcp.json`.
  - Anthropic offers the Claude Code harness on an API key only as software we run ourselves: the Agent SDK or `claude -p` in any container. That is our existing `claude_agent_sdk` lane.
  - **The owner's wish to customize repo, worktree and coding behaviour is still reachable in two ways:**
    - Managed Agents **self-hosted placement**: Anthropic runs the loop, and our worker executes every tool call in a sandbox we control, which gives full tool interception, worktrees and any git remote.
    - `claude_agent_sdk` with a **Sandbox Host** placement (O1).
- **C2. The OpenAI Agents API *is* the Codex harness ("the Codex harness through an OpenAI-managed API"), but closed.**
  - Missing: hooks, approval of shell or patch, `config.toml` or sandbox policy, fork, diff items, and an event replay cursor.
  - Cancel *is* documented.
  - Execution runs `openai_hosted` (OpenAI sandbox) or `self_hosted` (our `codex exec-server` connecting out to OpenAI).
  - Agents SDK "sandbox agents" are **not** Codex: the SDK's loop runs in our process. Codex inside OpenAI containers is not possible: there is no exec API.
  - For the full Codex control plane (steer, interrupt, per-command approvals, hooks, `thread/fork`, diffs), the `codex` app-server lane with `OPENAI_API_KEY` remains the right lane, optionally executing in a sandbox through the experimental `environment/add` remote exec-server.
- **C3. Neither hosted API is ZDR-eligible.** Transcripts persist until deleted, and tool inputs and outputs pass through the provider. Both lanes must refuse missions classified as PHI or secret-bearing. Biotech work must pass a data-class check (SPEC-06 §8).

## Open decisions (with recommendations)

### O1 — Allow "Sandbox Host" placement for the Claude Agent SDK and Codex app-server lanes?

The 2026-10-08 rule "cloud means provider-hosted only" excluded running harnesses on our own remote compute. With API billing approved, a **Sandbox Host** placement is the only way to run the *real* Claude Code harness off the owner's machine. It is also the cleanest way to give the Codex app-server an isolated executor.

Sandbox Host means an API-controlled sandbox from a third-party provider, or a Docker or WSL2 host for local proof.

**Recommendation.** Yes. Add `execution_environment.kind: sandbox_host` (SPEC-06 §2). Keep the provider-hosted profiles for "the provider runs it". Use Sandbox Host for "we run the provider's harness on rented compute".

### O2 — Sandbox provider

One provider is needed for four uses:

- Managed Agents self-hosted executors;
- OpenAI Agents self-hosted `codex exec-server`;
- Claude Agent SDK on Sandbox Host;
- Codex app-server remote executor.

Both providers' docs list compatible ones: E2B, Modal, Daytona, Vercel, Cloudflare, Blaxel and Runloop.

**Criteria:**

- per-sandbox egress allowlists;
- streaming exec with stdin;
- snapshot and restore;
- long-lived outbound WebSocket support;
- persistent volumes for git clones;
- pricing and concurrency;
- a Python SDK;
- region;
- no inbound exposure required.

**Recommendation.**

1. Build a `SandboxHost` port with a **Docker adapter** first, running on the WSL2 worker for proof.
2. Run spike HL-01 that scores E2B, Modal and Daytona against the criteria with one live smoke each.
3. Then pick one managed adapter.

### O3 — Profile names and ADR delta

**Recommendation:**

- `claude_managed` on the existing `claude` lane, with placements `cloud` and `self_hosted`.
- `codex_agents` on the existing `codex` lane, with placements `openai_hosted` and `self_hosted`.
- Reusing the lanes avoids about eight extra touch points and a DB check change ([research/codebase-new-lanes.md](research/codebase-new-lanes.md)).
- ADR-0035's "seven profiles" becomes nine. That delta is recorded as ADR-0050.

### Still open from the first pass

- **D3 — public Signal Ingress reachability.** **Resolved** by R11, R17 and R29: the ingress, webhooks and launch route run on Vercel `overtons-projects`.
- **D5 — WSL2 worker for the local Claude and Codex lanes.** **Resolved** by R28: WSL2 serves the local lanes. After MO-77 it runs in lane role, and the AWS worker serves the base and hosted-lane queues. Cursor local can run natively on Windows after CM-04.
- **D6 — Mission Control owns `.cursor/environment.json` via `sync`.** Recommendation unchanged.
- **D7 — Deep Agents.** Awaiting the owner's brief. Unaffected except for shared signals, watchers and custody.
- **D4 — subscription terms.** Applies now only to the local CLI skills and to `claude_cloud`/`codex_cloud`. Re-read Anthropic's 2026-10-07 change (Max/Team monthly API credits covering `claude -p`) before heavy automation.

## Proposed ADRs (written as `proposed` when implementation starts)

| # | Decision |
| --- | --- |
| 0042 | Environment Kits and two-layer base/mission setup with one bootstrap entrypoint |
| 0043 | Secret Broker; per-lane delivery; minted signal credentials; never commit secrets |
| 0044 | Additive instruction layering and structural config merge |
| 0045 | Signal Ingress trust tiers; signals are evidence, never authority |
| 0046 | Watchers as compiled, bounded, deterministic descriptors |
| 0047 | Owner prerequisites and preflight block launch |
| 0048 | Knowledge workspaces and mission branches |
| 0049 | Deprecate `mission_subscribe` push in favour of inbox wait channels |
| 0050 | Nine lane profiles: `claude_managed` and `codex_agents` added; amends ADR-0035 |
| 0051 | Sandbox Host placement and the `SandboxHost` port |
| 0052 | Remote Session Lane base: shared machinery for provider session APIs; conformance suite required for every lane |
| 0053 | Effect gating on closed hosted harnesses: credential-free sandboxes plus Mission Control-executed function/custom tools |
| 0054 | Local CLI job skills live outside the Mission Control lifecycle (`.agents/skills`), with no Mission Control runtime dependency |

## Run 2 approved refinements (2026-10-14)

The owner approved six narrow identity/configuration, Cursor truthfulness/continuation, standalone CLI, Anthropic qualification, ingress reliability and custody/review refinements. The OpenAI ambiguity is resolved from source: codex_agents is the hosted Agents API HTTP integration, not Agents SDK. No lane rename, direct API/Deep Agents expansion, CM-11 promotion or S4 release was approved. Managed budget-pause remains a visible blocker, not a new supported capability. Existing historical decisions and receipts remain provenance.

[Approved plan](runs/RUN-2-PLANNING-AMENDMENTS.md) · [Codex team kickoff](runs/RUN-2-AGENT-TEAM-KICKOFF.md) · [OpenAI architecture](runs/RUN-2-OPENAI-ARCHITECTURE.md).
