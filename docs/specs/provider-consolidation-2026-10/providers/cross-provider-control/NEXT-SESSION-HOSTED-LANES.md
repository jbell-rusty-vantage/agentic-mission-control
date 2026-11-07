---
type: Handoff
title: "Next session: hosted lanes (Managed Agents, OpenAI Agents API) to a real Stage Graph mission, with the prerequisites questioned and the GitHub home set up"
description: "Handoff of 2026-11-06 after iteration 3. Correction of the owner prerequisites given earlier: Anthropic Managed Agents needs no GitHub for a repository-less knowledge mission; the catalog requires M2/M3/MA4 for every hosted launch and must become conditional. Owner actions now (jbell-rusty-vantage repository and tokens, Vercel ingress webhook, Console), the code work in order (conditional prerequisites, hosted named-output tool, OpenAI Agents API gaps, live steer and connection-loss proofs), exact commands, the intervention range, and what is integrated versus open."
tags: [mission-control, handoff, claude_managed, codex_agents, prerequisites, github, signal-ingress, vercel, interventions]
status: active
date: 2026-11-06
---

# Next session: hosted lanes to a real Stage Graph mission

Read first: [iteration 3](../../sprint-oc/experiments/ITER-3-2026-11-06.md) (both phases), [ADR-0070](../../../../adr/0070-operator-instructions-and-the-deep-agents-gentle-steer.md),
the [goal](../../../../knowledge/goals.md#goal-provider-native-macro-scheduler), and the hosted runbook in
[NEXT-SESSION-LIVE-FIXTURES](NEXT-SESSION-LIVE-FIXTURES.md) §4.2.1 and §4.3.1. Owner session rules: no budget controls; models
`claude-haiku-5-5` (Anthropic), `gpt-6.1-sol` (OpenAI lanes), `gpt-6.1-terra` (judge); report cost at the end.

## 1. The goal this serves and where it stands

The product is lifecycle control, inspection, context transfer and output fulfillment working on every lane. On
`main` (`fc01583b`, not pushed), the status per lane:

- **Deep Agents.** Every part is integrated live: lifecycle, inspection, forks from a cognition point (reuse, start, gates,
  operator note) and operator instructions. The gentle steer is unit- and operation-tested only.
- **Managed Agents.** A turn and an interrupted turn are integrated live on the real `OperationWorkflow`. Pack sync is live.
  A Stage Graph mission through the API is refused `PREREQUISITES_UNMET`.
- **OpenAI Agents API.** The function-approval drill passes live (HL-13, `gpt-6.1-sol`) after the start-heartbeat fix.
  A Stage Graph mission through the API is not run.
- **Both hosted lanes.** Neither can submit named outputs, so neither carries context between stages or fulfils output
  obligations (F2-G3). That is the largest gap against the goal.

## 2. Correction: what Managed Agents really needs

The prerequisite list relayed at the end of iteration 3 was read off the refusal without questioning it. The code says:

| Code | What it is for | Needed for a repository-less knowledge mission? |
| --- | --- | --- |
| MA1 Console access and limits | the Anthropic key and workspace | yes (the key; spend limits are optional under "no budget controls") |
| MA2 webhook | the provider pushes session events to the Signal Ingress host (`application/prerequisites/generators.py` `_webhook`) | **no for the turn itself**: the Managed harness follows the session through its own event stream (`adapters/anthropic_managed/harness.py` `observe`). It is a wake/observation channel |
| MA4 read-only repository token | the sandbox clones a named repository (`hosted_lane_composition.py` readonly evidence) | **no**: the Managed pack's vault holds only `FIRECRAWL_API_KEY` |
| MA5 MCP OAuth | OAuth MCP servers in the pack | no (the pack selects none; attestable as not applicable) |
| M1 Signal Ingress | `mc_signal` and webhooks reach the durable inbox | the login is required to compose the lane (done); the probe only matters with ingress traffic |
| M2 publication credentials | governed branch and PR publication of code work (`adapters/github/credentials.py`) | **no** |
| M3 knowledge repository | publishing knowledge workspaces to a GitHub repository | **no** |
| M4 Secret Broker | named credentials resolvable | yes (names in the worker environment) |

**Answer: no, Managed Agents does not need GitHub.** The agent runs in Anthropic's managed environment
(`deployments/hosted-packs/ai-engineer/claude_managed/environment.yaml`, egress `api.firecrawl.dev` plus the ingress
host). The refusal comes from `application/prerequisites/catalog.py` `_LANES`, a **static list per lane**:
`claude_managed` requires MA1, MA2, MA4, MA5, M1, M2, M3 and M4 on every launch, and `codex_agents` requires OA1, OA2,
MA4, M1, M2, M3 and M4. Requiring repository and publication items for a mission that names no repository is a defect
(F2-G4), fixed in §4.1. GitHub is still worth setting up now: Cursor cloud, Codex cloud and Claude Code cloud
(the Goal Directed half of the plan), code missions and knowledge publication all need it.

## 3. Owner actions (can be done now)

### 3.1 GitHub on jbell-rusty-vantage (paid Pro): done 2026-11-07

1. **Repository.** `jbell-rusty-vantage/mission-control-fixtures` (plural; private) exists. The Cursor fixture
   manifests and the Cursor/Codex/Claude cloud fixtures name it.
2. **Read-only token** (MA4; also the Agents API pack's sandbox `GITHUB_TOKEN`). A fine-grained token created
   2026-11-07: repository access only `mission-control-fixtures`, Contents read and Metadata read. Its name is
   `MC_GITHUB_READONLY_TOKEN` (the name the pack reads), held in `BellLabs/.secrets/github.env` and the MC `.env`.
   Never paste it in chat or commit it.
3. **Publication credential** (M2; code work only). The GitHub App `agentic-mission-control-app` exists on
   `jbell-rusty-vantage`, installed on that repository with Contents read/write, Pull requests read/write and Metadata
   read. Its names are `MC_GITHUB_APP_ID`, `MC_GITHUB_APP_INSTALLATION_ID` and `MC_GITHUB_APP_PRIVATE_KEY_PATH` (a
   `.pem` outside every repository), in the same two files. Its installation-token exchange was verified on
   2026-11-07. The `gh` fallback in `adapters/github/credentials.py` now expects the `jbell-rusty-vantage` account.
4. The fixture references have moved off `Overton77` (dated evidence records keep their original names).

Provider cloud agents (Cursor cloud, Codex cloud, Claude Code web) reach repositories through their own GitHub app
installs on the account, not through these environment values. Names and readers: [ENVIRONMENT](../../../../ENVIRONMENT.md#github).

### 3.2 Webhook on the Vercel signal ingress

There is a live deployment from Run 2: `https://mission-control-ingress.vercel.app` (`/health/live` answers 200 on
2026-11-06; source `deployments/ingress-vercel/`, its README is the runbook). It does not appear under team
`overtons-projects` in the Vercel connector, so first confirm which Vercel account or scope owns it. Its production
variables were set for AI Engineer at 1.4.2 with an older ingress login, so treat them as stale. Steps:

1. Set production variables:
   - `MC_INGRESS_DSN`: the new restricted login, `MC_INGRESS_DSN` in `.scratch/sprint-oc/runtime/ai-engineer/logins.env`,
     created 2026-11-06 by `mission-db login-apply`. Use `sslmode=verify-full&sslrootcert=/var/task/certs/supabase-root.pem`.
   - `MC_INGRESS_INSTALLATION_ID=01a103c0-9a9e-70f3-9398-eb1573a98324`
   - `MC_INGRESS_APPLICATION_ID=ai-engineer`
   - `MC_INGRESS_ORIGIN=https://mission-control-ingress.vercel.app`

   An agent can do this through the Vercel connector once you confirm the project. Values go in as sensitive and are
   never echoed.
2. Rebuild the closure (`python deployments/ingress-vercel/scripts/vendor_closure.py`), review its digest manifest and
   redeploy production.
3. **Anthropic Console:** register the webhook URL `https://mission-control-ingress.vercel.app/v1/ingress/provider/anthropic`
   (`PROVIDER_WEBHOOK_PATH` in `generators.py`).
4. Store the signing secret as Vercel `MC_INGRESS_ANTHROPIC_WEBHOOK_SECRET`.
5. Do the same for OpenAI at `/v1/ingress/provider/openai` with `MC_INGRESS_OPENAI_WEBHOOK_SECRET` (OA2).
6. Then `missionctl prereq verify` for M1, MA2 and OA2.

Webhooks are optional for running a turn (§2), so they must not block §4.3 if this takes longer.

### 3.3 Consoles

- **Anthropic (MA1):** the key's workspace; limits are optional.
- **OpenAI (OA1):** a dedicated project key with Agents, Responses, Vaults and Traces scopes.

Record each with `missionctl prereq verify <id>` once its probe passes, or `missionctl prereq attest` where the
catalog allows.

## 4. Code work, in order (agents in worktrees, test-first)

Setup that worked: create worktrees yourself at `HEAD` (`git worktree add .claude/worktrees/<name> -b <branch> HEAD`; the
Agent tool's own isolation branched from the pushed `origin/main`); `git config core.longpaths true`; every pytest through
`.scratch/testlock.sh` (15 GB host); one venv per worktree (`uv sync --frozen --all-groups`).

1. **Conditional prerequisites (F2-G4).** Derive each lane's required items from the mission definition and its bindings,
   not the static `_LANES` list:
   - repository items (MA4, M2, M3, and the C/A/X repository steps) only when a node names `workspace.repo`, declares
     publication, or binds the knowledge workspace repository;
   - webhook items (MA2, OA2) only when the deployment selects webhook observation;
   - MA5 only when OAuth MCP servers are selected.

   (Done 2026-11-07: the `gh` fallback account is now `jbell-rusty-vantage`, `OWNER_GH_ACCOUNT` in
   `adapters/github/credentials.py`.)
   Prove it: a repository-less F2 compiles **and starts** with only MA1, M1 and M4 satisfied.
2. **Named outputs on hosted lanes (F2-G3)**, the core gap. Give both hosted lanes Mission Control's submission act as a
   provider tool: a Managed `custom_tools` entry and an Agents API function tool, `mc_submit_output(obligation, item)`.
   The worker answers it with `SubmissionService.submit_output` under the unit's invocation, exactly as Deep Agents'
   `submit_output`.
   - Then make the F2/F3 manifests `required`, with `from:` inputs.
   - Deliver the upstream outputs into the hosted session the way the hosted environment allows: a file in the
     environment, or inline in the turn's packet.
   - Proof: F2 and F3 complete with accepted heads and a transfer plan, like Deep Agents F1.
3. **OpenAI Agents API gaps**:
   - the pack declares no `mc_prepare`, so `mc_upload_artifact` returns `environment_not_prepared`
     (`adapters/openai_agents/tools.py`);
   - the pack's `GITHUB_TOKEN` was dropped from the hosted bindings because every turn then demands a read-only
     repository proof, so re-add it conditionally once §3.1 step 2 exists;
   - declared steering (`turn/steer`-style message during the turn) is implemented but declared `cancel_and_replace`:
     prove it live and declare it;
   - the HL-25 end-to-end drill: F3 with §3 of NEXT-SESSION-LIVE-FIXTURES (points, state-as-of R1, fork, inject,
     cancel).
4. **Managed Agents**: run F2 (§4.2.1 runbook), then the same §3 assertions (HL-24). Prove the declared steer (a message
   during the turn) and decide whether to declare `cooperative_inject`.
5. **Deep Agents proofs**:
   - the live gentle steer, triggering on the running operation in Temporal, not the transcript, which lags (L2-12);
   - re-prove F1-G7: the pooler connection reset now retries;
   - install release 1.15.0 (0074, the `deep_agents` describe row) on the AI Engineer remote through `mission-db`
     with a receipt.
6. **Composite context**: one queued or steered command carrying text, images (content blocks), sandbox files the text
   references by path, and MCP servers or skills (a capability addition admitted at the next boundary). Design note
   first, then Deep Agents, then the hosted lanes.

## 5. Interventions: the range (owner, 2026-11-06)

Support the whole range and let the operator choose per situation:
- **queue context** at the next boundary;
- **gentle steer** into the running turn (preferred for sudden intervention, not exclusive);
- **interrupt and inject** (`cancel_and_replace`) when the running work must stop now;
- **immediate cancel** behind the Stop Fence;
- **fork** from a cognition point with context.

Today each lane declares one `interrupt_and_inject` mode (`LANE_COMMAND_SEMANTICS`): Deep Agents is now
`cooperative_inject`, the others `cancel_and_replace`. The next step is a per-command choice:
- the command names `steer` or `interrupt`;
- a lane that can do both (Deep Agents, Codex, Managed, Agents API) honours either;
- the delivery report states which ran.

## 6. Running the stack

- **Processes (Windows host):** `.scratch/sprint-oc/experiments/iter-3/stack-up-hosted.ps1 -Which temporal,ks,api,worker -Tag <x>`.
  It includes the hosted variables, and `stack-up.ps1` is the Deep Agents-only variant. Kill only PIDs from `iter-3/PIDS.txt`
  (`tree.ps1 -Root <pid> -Kill`).
- **Tokens:** `scripts/sprint_oc_deployment_file.py --app ai-engineer token --role operator|reviewer --ttl-minutes 720`.
  The fork sponsorship is `sponsorship:sprint-oc-w1`.
- **Forks:** use `iter-3/fork.py` (240 s timeout). `missionctl run fork` times out at 30 s while the saga copies the seed
  (E-02).
- **Integration database:** disposable PostgreSQL 17 `mc-ft-disposable-pg17-56433` on 127.0.0.1:56433 (55433 is in a
  Windows-reserved range); the DSN is in the session scratchpad only, so recreate it from the container env.
- **Memory:** about 1.4 to 2 GB free with your apps open. Drop the Docker WSL cache
  (`wsl -d docker-desktop -u root sh -c "sync; echo 1 > /proc/sys/vm/drop_caches"`) before heavy runs. Never stop your
  apps.

## 7. Evidence and records

- **Iteration record:** `ITER-3-2026-11-06.md` (LEDGER DOC-64).
- **Private evidence:**
  - `.scratch/sprint-oc/experiments/iter-3/` (SESSION-TRANSCRIPT.md, per-run folders, `domain_readout.py`,
    `family_head.py`);
  - `.scratch/cross-provider-live-2026-11-06/`;
  - the login receipt `.scratch/sprint-oc/evidence/ai-engineer-login-receipt-ingress-20261106.json`.

Nothing is qualified; push `main` to `jbell-rusty-vantage` at session end.
