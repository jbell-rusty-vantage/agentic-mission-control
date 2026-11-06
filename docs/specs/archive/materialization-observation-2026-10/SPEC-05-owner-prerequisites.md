---
type: Specification
title: "SPEC-05: Owner prerequisites and pre-spawn preflight — what only the owner can do, surfaced before a mission spawns"
description: "Typed owner prerequisites with generated paste-ready content, verification probes and freshness, a missionctl preflight/setup flow that blocks or degrades launch, and the current per-provider catalog of human-only steps (2026-10-12)."
tags: [mission-control, specifications, preflight, owner, providers, setup]
---

**Run 2 close-out disposition (2026-10-18, Gate L):** Gate L: the same `PREREQUISITES_UNMET` list at preflight and launch, and verified/expired behavior, for the local lanes (fixture F0, phase P3). The `claude_cloud` fresh-installation example belongs to deferred SC scope. Carried forward: Cursor C1–C7 for S1. Criteria below are unchanged; see [the disposition](runs/RUN-2-GATE-L-DISPOSITION-2026-10-18.md) and [close-out instructions](RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md).

# SPEC-05: Owner prerequisites and pre-spawn preflight

Owner requirement: *"If there are things that an agent simply can not do and that I MUST DO then I will need those instructions before an agent spawns the mission."* Gap G4.

## 1. Owner Prerequisite

`mc.owner_prerequisite.v1` is a catalog-like record kept per installation.

```yaml
id: claude_cloud.environment.envkit-python-uv-node-3
provider: anthropic
scope: environment            # account | org | repo | environment | host
title: "Create the Claude Code cloud environment 'mc-python-uv-node-3'"
why: "Claude cloud environments are UI-only; the lane needs this base layer."
blocks: [{lane: claude_cloud, features: [launch]}]
steps:
  - "Open claude.ai/code → environment selector → New environment."
  - "Name: mc-python-uv-node-3. Network access: Custom. Include defaults: yes."
  - {paste: allowed_domains, content_ref: generated/claude-cloud/domains.txt}
  - {paste: setup_script, content_ref: generated/claude-cloud/setup.sh}
  - {paste: env_vars, content_ref: generated/claude-cloud/env.template}   # names only; owner fills values
  - "Copy the environment id (env_...) and run: missionctl prereq attest <id> --value env_..."
verify:
  method: probe_mission       # api_probe | probe_mission | attestation | file_check
  probe: "missions/probes/claude-cloud-env@1"   # cheap mission that emits env.prepared with toolchain versions
freshness: {revalidate_after: 30d, on_change_of: [kit_digest]}
generated_from: {kit: "envkit/python-uv-node@3#sha256:…", policy_digest: "…"}
```

- **Generated content.** Mission Control renders every pasteable artifact from the same kit and policy that the mission binds: setup scripts, domain lists, env var templates and the entrypoint. What the owner pastes is therefore exactly what the binding expects, and the `generated_from` digest detects drift.
- **Verification methods, strongest first:**
  - `api_probe`: Mission Control reads provider state. Examples: Cursor `GET /v1/environments`, GitHub App installation, `codex cloud list --json`.
  - `probe_mission`: a minimal real launch that emits a readiness signal.
  - `file_check`: a local file or credential exists and has not expired.
  - `attestation`: the owner says it is done. This is the weakest and is recorded as such.
- **Freshness.** Credentials with known expiry are tracked and warned about before expiry. Example: Claude cloud session control requires `claude auth login` every 30 days.

## 2. Preflight and setup flow

- **`missionctl preflight <manifest|run-draft>`** (also an MCP tool and an HTTP endpoint). It compiles the manifest, resolves the lane plan, and lists:
  - **unmet** prerequisites: blocking, with steps;
  - **stale** prerequisites;
  - **degradations** the run will accept (for example "no in-environment signals on codex_cloud");
  - **readiness levels** each lane can reach.

  It exits non-zero when blocked. Coordinators run it before launch. The launch API runs it too and refuses with a typed `PREREQUISITES_UNMET` error that carries the same list.
- **`missionctl setup <provider|lane>`** walks the owner through the unmet items interactively:
  - It uses the repo's `wizard` skill pattern: a generated script that opens URLs, prints paste blocks, waits for attestation and runs the verification.
  - It records results.
  - It never handles secret values itself. The owner enters them in the provider UI or the local Secret Broker store.
- **Agent behaviour.** An orchestrating agent that receives `PREREQUISITES_UNMET` must stop and relay the steps to the human. It must not attempt workarounds. The Mission Control router skill states this explicitly.
- **Lane fallback.** When a manifest lists several acceptable lanes, the preflight reports the first lane that is ready, and why the earlier ones are not. Fallback across lanes happens only when the manifest allows it.

## 3. Current catalog of human-only steps (2026-10-12)

Sources: [Cursor](research/cursor.md) §8, [Claude Code](research/claude-code.md) Q8 and [Codex](research/codex.md) §7. Items marked † are per account and must be checked.

### Cursor (cursor_local, cursor_cloud)

| # | Step | Scope | Verification |
| --- | --- | --- | --- |
| C1 | Paid plan; accept the **spend-limit prompt** on first cloud use (cloud agents bill at API pricing) | account | probe_mission |
| C2 | Privacy Mode (not "Legacy") in Dashboard → Cloud Agents | account | probe_mission |
| C3 | Install the Cursor GitHub app on target, dependency and knowledge repos (needs Cursor admin and GitHub org admin) and connect your own Git account. Unmet on 2026-10-14 for `mission-control` and `ai-engineer-knowledge-services` (MO-13 drill): launches on them are `400` ("SCM integration does not have access") and environments with `repos` are `400 repository_access`, although `GET /v1/repositories` lists them | repo | probe_mission (branch push observed) |
| C4 | Create an API key (Dashboard → API Keys) and store it in the Mission Control Secret Broker as `secret:cursor/api_key` | account | api_probe (`GET /v1/me`-equivalent) |
| C5 | Confirm `envVars` launch support † (otherwise per-run tokens fall back to Cursor OIDC). Confirmed enabled 2026-10-14 (MO-13 drill). | account | api_probe |
| C6 | Build Secrets, if the kit's Build-time install needs a secret (no API) | environment | attestation, then a probe Build |
| C7 | Decide on a committed `.cursor/environment.json` per target repo: remove it, or let Mission Control own it (SPEC-01 §7). For this repo, decided 2026-10-12: Mission Control owns it (DECISIONS R24); the marker is `mc:envkit.mission-control-dev@1` since MO-12, and the `main` copy that still carries `mc:envkit/mission-control-dev@1` reads as foreign until that change lands (MO-13 preflight). | repo | file_check |
| C8 | Optional: turn off "Include third-party plugins, skills and configs" for strict cognition isolation (SPEC-02 §8) | user | attestation |
| C9 | Local: Cursor desktop/CLI signed in on the worker host; verify that worktree cleanup leaves the Mission Control root alone (Q-W1) | host | file_check |

### Claude Code (claude_agent_sdk, claude_cloud)

| # | Step | Scope | Verification |
| --- | --- | --- | --- |
| A1 | Pro/Max/Team/Enterprise plan; not a ZDR/HIPAA org | account | probe_mission |
| A2 | Team/Enterprise only: Owner enables remote sessions and Routines | org | probe_mission |
| A3 | Install the Claude GitHub App on each repo (or `/web-setup`) | repo | probe_mission |
| A4 | Create the cloud environment from generated content: network **Custom** with the ingress host, setup script (base layer), env var names; record `env_…` | environment | probe_mission |
| A5 | For callbacks: environment-key secret (env var, or Pro/Max network secret for the ingress host) | environment | probe_mission (signal received) |
| A6 | Interactive `claude auth login` on the automation host; **expires every 30 days** | host | file_check plus expiry tracking |
| A7 | If the routine-trigger launch path is used: create a routine and its API trigger token in the web UI (shown once) and store it in the broker | account | api_probe |
| A8 | Local lane: WSL2 worker with the Claude CLI pinned version (DECISIONS D5); `setup-token` or login for SDK auth | host | file_check |
| A9 | Get written confirmation from Anthropic of how owner-only automation is billed on a subscription (open question, DECISIONS D4) | account | attestation |

### Codex (codex, codex_cloud)

| # | Step | Scope | Verification |
| --- | --- | --- | --- |
| X1 | ChatGPT Plus/Pro/Business/Enterprise/Edu; Enterprise admin enables Codex Cloud | account | probe |
| X2 | Connect GitHub.com to ChatGPT and select repos (no GitLab or GHES) | repo | `codex cloud list --json` |
| X3 | Create, test and **Publish** the cloud environment from generated content: install script, Start skill (bootstrap entrypoint), env vars, network secrets, Custom domains with the ingress host | environment | probe_mission |
| X4 | `codex login` (or `--device-auth`) on the worker; keep `auth.json` refreshed (headless seeding is supported) | host | file_check |
| X5 | Record `ENV_ID` (`codex cloud` picker or `list --json`) with `missionctl prereq attest` | environment | api_probe |
| X6 | Local lane: WSL2 worker with the pinned Codex CLI (DECISIONS D5) | host | file_check |

### Mission Control installation (all cloud callbacks)

| # | Step | Verification |
| --- | --- | --- |
| M1 | Public Signal Ingress and Model Gateway on Vercel (SPEC-10 §9): Pro team `overtons-projects`, the project's `*.vercel.app` host, Supabase migration to 1.4.0 and ingress role (approved, R18), Production env vars. A tunnel is used only for local-database drills. | api_probe from outside (probe mission signal) |
| M2 | Mission Control GitHub App (preferred) or owner `gh` credential for branch preparation and PRs | api_probe |
| M3 | Knowledge workspace repo per Application (SPEC-03 §4) | api_probe |
| M4 | Secret Broker store initialised, with the values the kits require | file_check (names only) |

## 4. Acceptance

- Preflight of a manifest that targets claude_cloud on a fresh installation lists A1–A7 and M1–M4 with generated paste blocks, and exits non-zero.
- After the steps and attestations, the probe mission runs and the prerequisites flip to `verified`.
- An expired A6 turns the lane back to blocked before the next launch.
- A launch through the API with unmet prerequisites returns `PREREQUISITES_UNMET` with the same list. The coordinator skill relays it verbatim.
