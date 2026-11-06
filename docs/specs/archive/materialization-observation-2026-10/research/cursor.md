---
type: Research Note
title: "Cursor fact sheet: cloud and local agents (read 2026-10-12)"
description: "Primary-source facts for environment.json, environments and secrets REST, git access, Cloud Agents API and SDK, skills/subagents/hooks/MCP in local vs cloud, worktrees, callbacks and owner-only prerequisites, with deltas against earlier repo research."
tags: [mission-control, research, materialization-observation]
---

# Cursor fact sheet: cloud and local agents (read 2026-10-12)

## Scope, method and evidence levels

- **Read date.** Every source below was fetched on **2026-10-12**. Cursor docs pages are undated. I fetched them as the `.md` variants listed in `https://cursor.com/llms.txt`.
- **Raw copies.** Copies of every page were kept in a session scratchpad and are not retained in the repo; cite the URLs.
- **Evidence levels:**
  - **[DOC]**: stated on a cursor.com docs page, the OpenAPI spec, or the JSON schema.
  - **[REG]**: read from a package registry or GitHub releases.
  - **[CL]**: read from an official changelog or release notes.
  - **UNVERIFIED**: no primary source settles the claim.
- **Versions in force today:**
  - PyPI `cursor-sdk` **1.0.37**, uploaded 2026-10-07T20:05Z, `Requires-Python >=3.10`.
  - npm `@cursor/sdk` latest **1.0.37** (2026-10-07T20:13Z). The `next` tag is still `1.0.27-beta.0`.
  - GitHub `cursor/sdk-bridge` **v1.0.37** (2026-10-07T20:07Z). [REG]
  - These are **unchanged since the repo's 2026-10-07 research.**
  - The SDK release notes still end at 1.0.35, so the contents of 1.0.36 and 1.0.37 remain UNVERIFIED. [CL `https://cursor.com/docs/release-notes/sdk.md`]
  - The CLI's latest changelog entry is **v2026.10.08**. [CL `https://cursor.com/docs/cli/changelog.md`]
  - The Cloud Agents API v1 is "Public beta". The OpenAPI `info.version` is `1.0.0`. [DOC `https://cursor.com/docs-static/cloud-agents-openapi.yaml`]

---

## 1. Cloud agent environment setup

### 1.1 `.cursor/environment.json`: full current schema

Source: [DOC `https://www.cursor.com/schemas/environment.schema.json`] (JSON Schema draft 2019-09, `allowComments: true`, `unevaluatedProperties: false`).

**Common properties**

| Key | Type | Meaning |
|---|---|---|
| `name` | string | Environment name. |
| `user` | string | User the environment runs as. |
| `install` | string | Install script. The schema text says "run on VM startup (after pulling latest changes)", but the current docs run it **at Build time** (§1.3). |
| `start` | string | Start command, run when each agent starts. |
| `repositoryDependencies` | string[] | Repos (`github.com/org/repo`) to **include in the GitHub access token generated for the environment**. |
| `disableAllMcpServers` | bool | Blocks every user and team MCP server for agents in this environment. Cursor built-ins are never blocked. |
| `mcpServerAllowlist` | `[{name?, serverUrl? \| command?, toolAllowlist?[]}]` | Environment-level MCP allowlist. Leave it empty to inherit team or user policy. |
| `egressAllowlist` | string[] | Extra outbound domains. |
| `egressMode` | enum | One of `allow_all`, `parent_plus_network_settings`, `default_with_network_settings`, `network_settings_only`. |
| `chromeExecutablePath` | string | Chrome used for browser testing. |
| `enable_testing` | bool or `"true"`/`"false"` | Allows cloud testing (computer use). Default true. |
| `ports` | `[{name?, port (1-65535)}]` | Exposed ports, devcontainer-style. |
| `terminals` | `[{name?, command, description?}]`, or arrays of those | tmux terminals started at agent start. `description` is shown to the agent. |

**Container properties**

| Key | Type | Meaning |
|---|---|---|
| `build` | `{dockerfile \| dockerfileContents, context?}` | Docker build. `dockerfileContents` is **new**: an inline Dockerfile. |
| `image` | string | Explicit registry image as the base. **New.** |
| `snapshot` | string | Snapshot ID. Takes precedence over `build` and `image`. |
| `agentCanUpdateSnapshot` | bool | Defaults to true for snapshot-based and default-base environments. **Always false when the base is `build` or `image`.** |

**Path rules** [DOC `https://cursor.com/docs/cloud-agent/setup.md`]:
- `build.dockerfile` and `build.context` are relative to `.cursor/`, and `context` defaults to `.cursor`.
- `.`, `./` and `..` are special-cased to mean the **repo root**.
- `install` runs from the project root.
- Do not `COPY` the project into the image. Cursor manages the checkout.

The environment-file editor validates `egressAllowlist`, `egressMode`, `image`, `dockerfileContents`, `chromeExecutablePath` and `enable_testing`. [CL release-notes.md line ~972]

### 1.2 Resolution order, scope and multiple environments [DOC setup.md]

- **Resolution, by repository or repo group, first match wins:**
  1. `.cursor/environment.json` in the repo.
  2. A **personal** saved environment.
  3. A **team** saved environment.
- **Consequence for Mission Control.** A committed `.cursor/environment.json` **overrides any saved environment that is created through the API for the same repo.**
- **Scope.** Environments are owned `personal` or `team` (API field `owner`) and cover one repo or a **multi-repo group**. One API create takes up to 100 repos. [DOC endpoints.md]
- **Multiple environments per repo** are allowed. The CL entry "Continue on Cloud shows saved environment names ... tell apart two environments on the same repo" confirms it. [CL release-notes.md line ~22]
  - Names must be unique per owner; a duplicate returns `409 environment_name_conflict`.
- **Default pick (recent change).** "New cloud agents use your repo's default environment"; before this, the UI could preselect a teammate's environment. [CL release-notes.md ~line 21]
- **Self-hosted Machines** (pool or machine) use only the environment's repositories and **never read `.cursor/environment.json`**. Builds, environment secrets and egress policy do not reach them. [DOC setup.md, builds.md, security-network.md]

### 1.3 Builds, base images and snapshots

Sources: [DOC `https://cursor.com/docs/cloud-agent/builds.md`; `https://cursor.com/docs/cloud-agent/security-network.md`]

**Build lifecycle**
1. Trigger.
2. Prepare: start from the base image, clone every repo at its **default branch**, run `install`.
3. Snapshot the disk with the environment version and the per-repo commit SHA.
4. Activate.
5. Start agents. Cursor keeps pre-warmed copies of the active Build.

**Triggers.** `RECURRING` (skipped when nothing changed), `CONFIG_CHANGE` (a config or **secret** change), `MANUAL`, and Agent-requested.
- **Recent change:** "Environment builds are always on" and can no longer be turned off. [CL week of Sep 28 2026, release-notes.md ~line 195]

**What persists and what runs**
- Builds preserve **disk state only**. Processes, shell exports and in-memory caches are gone.
- `start` and `terminals` run at **each agent start**.
- A failed Build never replaces the active Build.
- Before the first successful Build, agents run on Cursor's default image (`universal_image`).

**Git freshness**
- Default-branch runs start at the Build's commit.
- With **Update stale builds** on, runs pull the latest code when the Build is older than the **Staleness threshold**. The default is 24 h; `0` always pulls.
- Feature-branch runs check out the requested branch on top of the Build's disk.
- **Builds use the `environment.json` from the default branch.** A config change on a feature branch has to be pushed, and the agent may rerun `install` itself.

**Base options.** Agent-driven setup (snapshot), Dockerfile, `image`, or `snapshot` ID.
- "Cursor-configured Dockerfiles" are in private beta for Enterprise.
- Dockerfile layer caching is used.
- There is **no direct machine access**.
- Default VM resources are fixed. More requires Enterprise support; self-serve is "coming soon". [DOC setup.md]

**Snapshot persistence**
- Environment snapshots are deleted after **90 days of inactivity**. Every start or resume extends the window by 90 days.
- Snapshots **cannot be deleted on demand**.
- Conversation history is kept indefinitely by default. Enterprise can choose a 90-day policy. [DOC security-network.md "Data retention"]
- Builds whose snapshot was deleted show "Snapshot expired" and cannot be activated. [CL ~line 245]

**Cost.** "Builds are included with Cloud Agents" (no extra charge). [DOC builds.md]

### 1.4 Setup agent flow [DOC setup.md; capabilities.md "Cursor Cloud MCP"]

**Guided setup** runs from the dashboard (`cursor.com/dashboard/cloud-agents#environments`) or the Agents Window.
1. Connect the SCM.
2. Pick the repos.
3. Provide env vars and secrets.
4. The agent installs in a shared terminal and verifies the result.
5. Cursor saves the environment after a **successful Build**.

**Built-in Cursor Cloud MCP tools used by the setup agent:** `trigger-environment-build`, `propose-environment-json`, `take-environment-snapshot`, `check-environment-snapshot`, `request-environment-setup-actions` (asks a human to add a secret, for example), `list-environment-builds`, `environment-build-logs`, `environment-info`, `run-info`, `get-events`, `list-cloud-agents`, `batch-fetch-details`.
- Any cloud agent can use these, so **an agent can trigger and inspect Builds from inside the VM**.
- Admins can disable the Cursor Cloud MCP.

**Dashboard actions:** "Update with Agent", "New Setup Run", "Restore" (from version history), "Fix Build". [DOC settings.md; CL]

### 1.5 API vs dashboard for environments (NEW since repo research)

The **v1 REST environment endpoints** are documented. [DOC `https://cursor.com/docs/cloud-agent/api/endpoints.md#environments`; OpenAPI paths]

| Endpoint | Operation |
|---|---|
| `POST /v1/environments` | `{owner: personal\|team, name, repos[{url}] (≤100), environmentJson: "<JSON string>"}` → `201`. Errors: `409 environment_name_conflict`, `400 repository_access`, `400 validation_error`. |
| `GET /v1/environments?limit&cursor` | List environments. |
| `GET /v1/environments/{id}` | Returns `environmentJson`, `versionId`, and `repoFile{url,path}` when the config comes from a repo file. |
| `PATCH /v1/environments/{id}` | `{name?, environmentJson?}`; replaces the whole config; atomic; `204`. |
| `DELETE /v1/environments/{id}` | Delete an environment. |
| `GET /v1/environments/{id}/history` | Event `source` is one of `dashboard`, `setup_flow`, `restore`, `api`, `agent_run`, `repo_file`, `request_override`. |
| `GET /v1/environments/{id}/builds` | Up to 10 per page. Fields `status: IN_PROGRESS\|SUCCEEDED\|FAILED\|CANCELLED\|SKIPPED`, `trigger: RECURRING\|CONFIG_CHANGE\|MANUAL`, `draft`, `failure{type: INSTALL_FAILED\|TERMINAL_FAILURE, code}`. |
| `GET /v1/environments/{id}/builds/{buildId}` | Read one Build. |
| `GET /v1/environments/{id}/builds/active` | `{type: build\|universal_image, buildId?}`. |

- **Not in the API** (absent from the OpenAPI path list): trigger, cancel, activate or pin a Build, and start an agent from a specific Build. These are **dashboard-only**, or done by an agent through Cursor Cloud MCP `trigger-environment-build`.
- A save through the API is labelled "API" in version history and fires a `CONFIG_CHANGE` Build. [CL week of Sep 28 2026]
- **The SDKs (Python/TypeScript 1.0.37) expose no environment or secret management.** That surface is REST only.
- **CLI:** `agent env deploy <file>` exists. Comments and trailing commas are accepted since v2026.10.08. [CL cli/changelog.md]
  - Its flags and semantics are **UNVERIFIED**; I found no reference page.

**Observed 2026-10-14 (MO-13 drill; records in the run's `.scratch/.../MO-13/`, not committed):**
- `POST` answers `201 {id, name, owner, repos, createdAt, updatedAt}` without the configuration.
  A taken name is `409 environment_name_conflict`, and its error carries the existing `environmentId`.
- `GET /v1/environments/{id}` carries `versionId` and `repos` (`[{url}]`) but **not** `environmentJson`. The configuration
  is in `GET .../history`: each entry has `{id, createdAt, kind: created|updated, title,
  description, source, current, environmentJson}`. `environmentJson` is the string stored
  verbatim, and the entry with `current: true` is the live version. Dashboard-created
  environments may have an empty history and no `name` in the listing.
- `PATCH` answers `204` and adds an `updated` entry with `source: api` and a new `versionId`.
  `DELETE` answers `200 {id}`. A later `GET` is `404 environment_not_found`.
- A new environment has no Builds, and its active Build is `{type: universal_image}`.
- On this account, `POST` with any `repos` entry is refused with `400 repository_access`
  ("doesn't exist or isn't accessible to Cursor's GitHub or GitLab integration").
  `GET /v1/repositories` lists those same repositories. A repository-less environment is accepted.
- UNVERIFIED (no repository-bound environment could be created): whether `repos` is echoed
  in the spelling it was sent, and whether `PATCH` can change it. Mission Control compares
  repository URLs without case, trailing slash or `.git`, and never patches `repos`.

---

## 2. Secrets and environment variables in cloud agents

### 2.1 Scopes and precedence

Sources: [DOC endpoints.md "Secrets", "Which Value An Agent Gets"; setup.md; builds.md]

**Scopes:** **team**, **user (personal)**, **environment** (new, environment-scoped), and **per-agent / per-run** values passed at launch.

**Precedence** (a name at a higher level hides the same name below it):
1. Launch values (`envVars` on create; SDK per-run `cloud.env_vars`).
2. Environment secrets.
3. User secrets.
4. Team secrets.

**Repo scoping and limits**
- Each secret version can be limited to `repos[]` (up to 100); `[]` means every repo.
- One name can have several versions for disjoint repo sets.
- At most 1,000 secrets per environment and per team.
- Names are case-insensitive and unique.
- Reserved names: anything containing `CURSOR_SANDBOX`, plus `HTTP_PROXY`, `HTTPS_PROXY` and `ALL_PROXY`.
- Values are 1 to 4,096 bytes.

### 2.2 Types and redaction [DOC security-network.md "Secret protection"]

| Type | Behavior |
|---|---|
| `environment_variable` | Visible to the agent. Meant for non-sensitive config. |
| `runtime_secret` (formerly "Redacted Secrets"; the API default) | Loaded as an env var but **redacted to `[REDACTED]`** in tool results, the transcript, commits and commit messages. Still visible to a human in the VM terminal. |
| `build_secret` | Available only to the Docker build through `RUN --mount=type=secret,id=NAME,env=NAME`. **Cannot be set through the API yet** (`400 validation_error`); `DELETE` works. |

Other protections:
- MCP `env`, `headers` and `CLIENT_SECRET` are encrypted and write-only after saving. [DOC capabilities.md]
- HTTP MCP credentials never enter the VM. Stdio MCP `env` does. [DOC capabilities.md]

### 2.3 Exposure timing

Sources: [DOC builds.md "How secrets work with Builds"; endpoints.md "Changing Secrets"; cloud-agent.md troubleshooting]

- **During install / Build:** **team and environment secrets** are available. **User secrets are not**; they are added only at agent start and never baked into shared snapshots.
- **At runtime:** secrets are injected as env vars when an agent starts. Running agents keep their values.
- Build-booted agents see a change only **after a newer Build finishes**, because a secret change triggers a Build.
- API reads can lag behind writes.

### 2.4 APIs to set secrets (NEW since repo research) [DOC endpoints.md; OpenAPI]

| Endpoint | Purpose |
|---|---|
| `GET /v1/secrets?scope=team\|user\|members\|environment&environmentId&name&repo` | Unified list. Values are never returned. |
| `GET /v1/environments/{id}/secrets` | List one environment's secrets. |
| `PUT /v1/environments/{id}/secrets/{name}?id=` | Body `{value, type?: runtime_secret\|environment_variable, repos?}`. |
| `DELETE /v1/environments/{id}/secrets/{name}?id=` | Delete an environment secret. |
| `GET /v1/team/secrets` | List team secrets. |
| `PUT /v1/team/secrets/{name}` | Set a team secret. |
| `DELETE /v1/team/secrets/{name}` | Delete a team secret. |

- **No API exists to set *user* (personal) secrets.** `scope=user` is list-only.
- Observed 2026-10-14 (MO-13 drill):
  - An environment-secret `PUT` answers `201 {id: secv_…, name, type, repos, createdAt}`.
  - The listing items have the same fields and never a value. The unified list adds
    `owner{type: environment, environmentId}`.
  - `DELETE` answers `200 {name}`. An unknown name is `404 secret_not_found`.
- **Allowed keys:** a user API key, an **agent-scoped service-account key**, or a user-scoped token from `POST /v1/sub-tokens`.
- **Refused keys:** team API keys, automation-webhook keys and `grok_` keys (`403 key_not_supported`).
- **Repo-limited keys** cannot set team secrets (`403 repository_access`).
- If the team restricts secret changes to admins, everyone else (service accounts included) gets `403 team_admin_required`.
- Every change emits a `cloud_agent_secret` audit event.

### 2.5 Launch-time `envVars` [DOC endpoints.md Create An Agent; sdk/python.md]

- Session-scoped, encrypted at rest, injected into the agent shell, and deleted with the agent.
- Limits: 50 entries; names up to 255 bytes and not starting with `CURSOR_`; values up to 4,096 bytes.
- **Cannot be combined with a client `agentId`.**
- Still **beta**: if not enabled for the account, the field is **silently ignored**.
  - **Enabled on the owner's account** (MO-13 drill A2, 2026-10-14): a launch value was present
    in the agent's shell. The Q-C2 answer is yes.
- SDK per-run `cloud.env_vars` (Python `SendOptions.cloud`) are removed after the run. They are **not available for public repositories**.

### 2.6 Alternatives to stored secrets

- **OIDC tokens.** Minted at `POST` on `/run/cursor/api.sock` (`CURSOR_AGENT_SOCKET`).
  - Issuer `https://api.cursor.com`, JWKS at `/keys`, RS256.
  - `exp = iat + 300`; audience-bound; `sub` is `user:<id>` or `service_account:<id>` or a projected `team_id`, `organization_id` or `environment_id`.
  - Claims include `cloud_agent_id`, repo URLs and `agent_runtime`.
  - Limit: 30 mints/min, bursts of 10; at most 8 socket connections, shared with metadata. [DOC `https://cursor.com/docs/cloud-agent/identity.md`]
- **AWS IAM role** through the `CURSOR_AWS_ASSUME_IAM_ROLE_ARN` secret plus a team external ID (admin). [DOC setup.md]

---

## 3. Git access in cloud agents

- **Providers:** GitHub (Cloud and Enterprise Server), GitLab (Cloud and Self-Hosted), Bitbucket Cloud, Azure DevOps. [DOC cloud-agent.md; endpoints.md]
- **Two layers of access:**
  - An **admin installs the app** on the Git organization, choosing all or selected repos. This needs both a Cursor admin and a Git org admin. [DOC integrations/github.md]
  - **Each user connects their own Git account.**
  - Agent access is "inherited, never widened": only repos the triggering user can reach. [DOC cloud-agent/security.md]
- **Service accounts** (Enterprise only) need a **team-level** GitHub integration. A personal integration is not enough. [DOC account/enterprise/service-accounts.md]
- **Permissions.** "You need read-write privileges to your repo and any dependent repos or submodules." [DOC cloud-agent.md]
- **Token for private dependencies.** `repositoryDependencies` in environment.json lists repos to add to the **GitHub access token generated for the environment**. [DOC schema]
  - The exact credential mechanism inside the VM (credential helper, token lifetime) is **UNVERIFIED**.
- **Multi-repo environments** clone every repo and can "open pull requests in the repos it changes". [DOC setup.md]
  - Pushing to repos *outside* the agent's repos or `repositoryDependencies` is **UNVERIFIED**.
- **Branches.**
  - With `workOnCurrentBranch: false` (the default), the agent pushes a new `cursor/...` branch from `startingRef` or the PR base.
  - With `true`, it pushes to `startingRef`, or to the PR head when `prUrl` is set.
  - **No branch-name field in v1.** [DOC endpoints.md]
  - Dashboard "Base branch" sets the default fork point. [DOC settings.md]
- **Pull requests.**
  - `autoCreatePR` opens the PR. Security docs describe a **draft** PR handoff.
  - `skipReviewerRequest` is available.
  - SDK `open_as_cursor_github_app` defaults to true for service-account keys. [DOC endpoints.md; security.md; SDK release notes 1.0.27]
- **Commits** are signed with an HSM-backed Ed25519 key and show "Verified". [DOC security-network.md]
- **Git results.** `git.branches[]{repoUrl, branch?, prUrl?}` is **per-agent state**, identical on every run. No SHA and no diff endpoint. [DOC endpoints.md]
- **Controls.** Protected Git Scopes and repo blocklists (admin). A git egress proxy is available for IP allow lists. [DOC security-network.md]
- **Auto CI fixing** (GitHub Actions; Teams) and **subscriptions** to PR, CI, Slack, Linear and timer events. Subscriptions are **not available to service-account-owned agents**. [DOC capabilities.md]

---

## 4. Programmatic launch and control

### 4.1 REST v1 [DOC endpoints.md; OpenAPI 1.0.0]

**Paths**
- `/v1/agents` (POST, GET), `/v1/agents/{id}` (GET, DELETE)
- `/archive`, `/unarchive`
- `/runs` (POST follow-up, GET list), `/runs/{runId}` (GET), `/runs/{runId}/stream` (SSE), `/runs/{runId}/cancel`
- `/usage`, `/artifacts`, `/artifacts/download`
- `/v1/environments/**`, `/v1/secrets`, `/v1/team/secrets/**`
- `/v1/sub-tokens`, `/v1/me`, `/v1/models`, `/v1/repositories`
- Pools and workers still live under `/v0/private-workers/*`.

**Create (`POST /v1/agents`)**

| Field | Notes |
|---|---|
| `prompt{text, images≤5×15MB}` | Required. |
| `model{id, params[]}` | Optional. |
| `name` | Optional. |
| `env{type: cloud\|pool\|machine, name?}` | Optional. |
| `repos[≤20]{url, startingRef?, prUrl?}` | Optional. |
| `workOnCurrentBranch`, `autoCreatePR`, `skipReviewerRequest` | Optional. |
| `envVars` | Beta. |
| `mcpServers[≤50]` | HTTP, SSE or stdio. |
| `customSubagents[≤20]{name, description, prompt, model?}` | Optional. |
| `mode: agent\|plan` | Optional. |
| `agentId` (`bc-<uuid>`) | Optional; for idempotent create. |

**Targeting a specific environment:**
- `env:{type:"cloud", name:"<saved environment name>"}` selects a **named Cursor-hosted environment**.
- This is **mutually exclusive with `repos`**, so `startingRef` and `prUrl` cannot be passed together with a named environment.
- With `repos` and no name, Cursor resolves the environment by repo (§1.2).
- **No field targets a specific Build or snapshot.** That is dashboard-only (UNVERIFIED via API; absent from OpenAPI).
- Whether the cloud `env.name` accepts the environment *ID* as well as the name is **UNVERIFIED**.
- **Confirmed 2026-10-14 (MO-13 drill):**
  - `env.name` together with `repos` is `400 validation_error` ("env.name cannot be combined with
    repos for cloud environments; choose either a named environment or explicit repositories").
  - A named launch of a repository-less saved environment ran the environment's `start` in
    `/agent` with no git checkout. It received the environment secret and the launch `envVars`.
  - The run's `GET .../usage` reported `cost{rawCostCents, chargedCents}` per run.
- A launch with `repos[{url, startingRef}]` on a repository the account's SCM integration
  cannot read is `400 validation_error` ("The SCM integration does not have access to
  repository … to verify branch existence"). So whether `start` runs on the `startingRef`
  checkout (Q-C1, first part) stays **UNVERIFIED** for this account.

**Run model**
- Follow-up: `POST /runs {prompt, mcpServers?, mode?}`.
- **One active run per agent**; another request returns `409 agent_busy`.
- Cancel is terminal (`409 run_not_cancellable` if the run is not active).
- Statuses: run `CREATING|RUNNING|FINISHED|ERROR|CANCELLED|EXPIRED`; agent `ACTIVE|IDLE|ARCHIVED`.

**SSE stream**
- Events: `status`, `assistant`, `thinking`, `tool_call{callId,name,status,args?,result?,truncated?}`, `interaction_update`, `heartbeat`, `result`, `error`, `done`.
- Resume with `Last-Event-ID`. Retention is in `X-Cursor-Stream-Retention-Seconds`; after it, `410 stream_expired`.
- **Unchanged from repo beliefs.**

**Conversation and artifacts**
- There is **still no v1 conversation endpoint**.
- In-VM, the Cursor Cloud MCP `batch-fetch-details` returns transcripts for runs the caller can see.
- v0 `GET /v0/agents/{id}/conversation` remains, as the legacy API.
- Artifacts: list, plus a 15-minute presigned download.

**Rate limits and concurrency**
- Rate limits: "Standard rate limiting". The cross-API default is "20 requests per minute" unless documented otherwise. [DOC api.md]
- Concurrent-agent caps per plan are **not documented**. The docs say "run as many agents as you want in parallel" (UNVERIFIED in practice).

**Limits.** Pool watch streams: 4 per service account. Metadata: 120 req/min.

### 4.2 Webhooks

- **v1 still says "Webhooks are coming soon."** Only **v0** supports them. [DOC endpoints.md; `https://cursor.com/docs/cloud-agent/api/webhooks.md`]
- v0 create: `webhook{url, secret (≥32 chars)}`.
- Event: `statusChange`, fired only on `FINISHED` and `ERROR`.
- Headers: `X-Webhook-Signature: sha256=<HMAC-SHA256(raw body)>`, `X-Webhook-ID`, `X-Webhook-Event`, `User-Agent: Cursor-Agent-Webhook/1.0`.
- Payload: `{event, timestamp, id, status, source{repository,ref}, target{url,branchName,prUrl}, summary}`.
- Retried "if your endpoint returns an error status code". The policy is undocumented.
- v0 "remains available during the migration window". [DOC `https://cursor.com/docs/cloud-agent/api/v0.md`]
- **UNVERIFIED** whether an agent created through v0 with a webhook can then be driven with v1 runs and streams.
- **Inbound webhooks also exist.** Automations offer a webhook trigger: a private HTTP endpoint plus an API key that **starts** an automation run. [DOC `https://cursor.com/docs/cloud-agent/automations.md`]
  - This is not a status callback.

### 4.3 Cursor SDK (Python `cursor-sdk` 1.0.37 / TypeScript `@cursor/sdk` 1.0.37)

Sources: [DOC sdk/python.md, sdk/typescript.md, sdk/bridge.md; REG]

**Settable at cloud launch** (`CloudAgentOptions` / `cloud`):
- `env` (`CloudEnvironment(type, name)`, which includes a **named saved environment**)
- `repos[{url, starting_ref, pr_url}]`
- `work_on_current_branch`, `auto_create_pr`, `open_as_cursor_github_app`, `skip_reviewer_request`
- `env_vars`; `metadata` (gated, else `403 feature_unavailable`)

**Settable at the top level:** `model` (`ModelSelection` with params), `mcp_servers`, `agents` (subagents), `mode`, `idempotency_key`, and prompt images (`UserMessage(text, images)`).

**Per send:** `cloud.env_vars` (per run), `mcp_servers` (replaces the create-time set), `model`, `mode`.

**Local only:**
- `tools` / `disallowed_tools`, `custom_tools`, `sandbox_options`, `store`, `auto_review`, `setting_sources`
- `system_prompt` (TypeScript only)
- Steer (TypeScript only)

**Not in the SDK:** environment, Build or secret management, and webhooks.

**MCP sources**
- Cloud: inline send > inline create > **user and team servers from cursor.com/agents**.
- Local: send > create > plugins > project `.cursor/mcp.json` > user, gated by `setting_sources`. [DOC sdk/typescript.md "Configuration sources at a glance"]

---

## 5. Cognition materialization: local vs cloud

| Artifact | Path / format | Local (IDE, CLI, SDK) | Cloud |
|---|---|---|---|
| **Rules** | `.cursor/rules/**/*.mdc` with frontmatter `description`, `globs`, `alwaysApply`. **A plain `.md` file in `.cursor/rules` is ignored.** Precedence: Team → Project → User. | Yes | Yes (from repo). Rule `@file` mentions are not inlined "in the editor, the CLI, and Cloud Agents". [DOC rules.md] |
| **AGENTS.md** | Root and nested subdirectories. | Yes | Yes. The docs recommend a "Cursor Cloud specific instructions" section. [DOC setup.md] |
| **Skills** | `.agents/skills/`, `.cursor/skills/` (project); `~/.agents/skills/`, `~/.cursor/skills/` (user); compatibility `.claude/skills/`, `.codex/skills/` and `~` equivalents. Nested `.cursor/skills` or `.agents/skills` are auto-scoped to their subtree. Frontmatter: `name` (= folder; required), `description` (required), `paths` (legacy `globs`), `disable-model-invocation`, `icon`, `color`, `metadata`. CLI also: `user-invocable: false` [CL]. Spec warnings above 64-char names, 1,024-char descriptions, and bodies over about 5k tokens [CL v2026.10.08]. | Yes | **Project skills from the repo: yes** (implied: "On self-hosted workers, use project skills from the repo"; cloud loads `project`). **`~/.cursor/skills` only with "Sync Skills for Cloud Agents"** (user toggle; team admin can disable). **`~/.agents/skills` never syncs.** [DOC skills.md] |
| **Subagents** | `.cursor/agents/*.md` (also `.claude/agents/`, `.codex/agents/`; user `~/...`). Frontmatter: `name`, `description`, `model` (`inherit` or an ID with `[k=v]` params), `readonly`, `is_background`. `.cursor` beats `.claude`/`.codex`; project beats user. | Yes | Yes ("editor, CLI, and Cloud Agents"; cloud picks up project files from the clone). API/SDK inline `customSubagents` / `agents` lack `readonly` and `is_background`. [DOC subagents.md; sdk/typescript.md] |
| **Hooks** | `.cursor/hooks.json` `{version:1, hooks:{event:[{command, type: command\|prompt, timeout, matcher, failClosed, loop_limit}]}}`. | Yes | **Project command hooks only**, plus team and enterprise hooks on Enterprise. No `~/.cursor/hooks.json` and no prompt hooks. See §5.1. |
| **Claude Code hooks** | `.claude/settings.local.json`, `.claude/settings.json`, `~/.claude/settings.json`; loaded when "Include Third-Party Plugins, Skills, and Other Configs" is on (default on); lower priority than `.cursor`. | IDE: yes [DOC reference/third-party-hooks.md]. CLI: "Claude Code settings.json hooks are read and merged" [CL]. | **UNVERIFIED** |
| **MCP** | `.cursor/mcp.json` (project), `~/.cursor/mcp.json`. | Yes (SDK only with `setting_sources`). | **Project `.cursor/mcp.json` is NOT a documented cloud source.** Cloud uses inline API/SDK servers, plus user and team servers from cursor.com/agents and Dashboard > Plugins & MCPs. HTTP and stdio only (no SSE, no `mcp-remote`). OAuth is per-user. Environment-level `mcpServerAllowlist` / `disableAllMcpServers`. [DOC capabilities.md; sdk/typescript.md; schema] |
| **Commands** | Markdown slash commands, managed in Customize and bundled by plugins. | Yes | **UNVERIFIED**. Cursor is migrating commands into skills (`/migrate-to-skills`, which marks them `disable-model-invocation: true`). [DOC skills.md] |
| **Plugins / marketplace** | `.cursor-plugin/plugin.json` (rules, skills, agents, commands, MCP, hooks, variables) or Agent Plugins `plugin.json`. Cursor Marketplace; team marketplaces (Default marketplace links Team MCPs). | Yes; CLI `--plugin-dir`; plugin hooks run in the CLI [CL]. | "Cloud always loads `plugins`" (SDK docs). Exactly which plugin components apply in a cloud VM is **UNVERIFIED**. [DOC plugins.md; sdk/python.md] |

### 5.1 Hooks contract [DOC `https://cursor.com/docs/hooks.md`]

**Agent events:** `sessionStart`, `sessionEnd`, `preToolUse`, `postToolUse`, `postToolUseFailure`, `subagentStart`, `subagentStop`, `beforeShellExecution`, `afterShellExecution`, `beforeMCPExecution`, `afterMCPExecution`, `beforeReadFile`, `afterFileEdit`, `beforeSubmitPrompt`, `preCompact`, `stop`, `afterAgentResponse`, `afterAgentThought`. **Tab events:** `beforeTabFileRead`, `afterTabFileEdit`. **App event:** `workspaceOpen`.

**I/O contract**
- JSON on stdin and JSON on stdout.
- Common input fields: `conversation_id`, `generation_id`, `model`, `model_id`, `model_params`, `hook_event_name`, `cursor_version`, `workspace_roots`, `user_email`, `transcript_path`.
- Env vars: `CURSOR_PROJECT_DIR`, `CURSOR_VERSION`, `CURSOR_USER_EMAIL`, `CURSOR_TRANSCRIPT_PATH`, `CURSOR_CODE_REMOTE`, `CLAUDE_PROJECT_DIR`.

**Blocking semantics**
- Exit `0` means use the stdout JSON. Exit `2` means deny.
- Any other exit code is fail-open unless `failClosed: true`.
- Permission hooks block on invalid JSON even without `failClosed`.
- Merge across all sources: `deny` beats `ask` beats `allow`. Messages are concatenated; for other fields the last response wins.
- Priority order: Enterprise → Team → Project → User.

**Per-event behavior**
- `preToolUse` accepts `ask` but does not enforce it.
- `subagentStart` treats `ask` as `deny`.
- `sessionStart` is fire-and-forget, with `env` and `additional_context` outputs.
- `stop` and `subagentStop` take `followup_message` (`loop_limit` default 5).
- `preCompact` is observe-only.
- These match the repo's fact sheets; **no contract change found.**

**Cloud matrix**
- Supported: `beforeShellExecution`, `afterShellExecution`, `beforeReadFile`, `afterFileEdit`, `preToolUse`, `postToolUse`, `postToolUseFailure`, `subagentStart`, `subagentStop`, `beforeSubmitPrompt`, `preCompact`, `afterAgentResponse`, `afterAgentThought`, `stop`.
- Not supported:
  - `sessionStart` and the MCP hooks: "deferred while cloud agents can still start in a read-only environment".
  - `sessionEnd`.
  - Tab hooks and `workspaceOpen`.
- No hooks run during early read-only exploratory turns.
- Self-hosted workers fire `sessionStart` and `sessionEnd` on claim and release.
- **Unchanged.**

**CLI hooks.** Session start/end, stop with follow-up loops, pre-compaction, subagent hooks, `afterAgentThought` / `afterAgentResponse`, and Claude-format responses all run. [CL cli/changelog.md entries ~lines 406, 428, 450]

**SDK hooks.** File-based only. `agent.reload()` re-reads them. A per-hook matrix for headless SDK local runs is still **UNVERIFIED**.

---

## 6. Worktrees and parallelism

**Local worktrees** [DOC `https://cursor.com/docs/configuration/worktrees.md`; cli/reference/parameters.md]
- The UI-native feature is in the **Agents Window** only. The IDE uses `/worktree`, `/apply-worktree`, `/delete-worktree` and `/best-of-n <models> <task>`.
  - `/best-of-n` runs each model in its own worktree and does **not** merge.
- **Location** (CLI): `~/.cursor/worktrees/<reponame>/<name>`, via `agent -w/--worktree [name] --worktree-base <ref>`. `--skip-worktree-setup` skips setup.
- **Setup file:** `.cursor/worktrees.json` with keys `setup-worktree-unix`, `setup-worktree-windows`, `setup-worktree`. Each takes a command array or a script path relative to the json file.
  - `$ROOT_WORKTREE_PATH` is available.
  - The file is looked up in the worktree first, then the project root.
- **Cleanup** (Cursor 3.5+): machine-wide `cursor.worktreeMaxCount` (default **25**) and `cursor.worktreeCleanupIntervalHours`.
  - Worktrees made outside the manager (`git worktree add`) **are eligible for deletion**.

**Subagent isolation.** On request, each subagent gets its own worktree and branch, or its own cloud VM. `/in-cloud` hands off to a cloud subagent; `/autopilot` takes over a PR (desktop Agents Window). [DOC subagents.md]

**Cloud isolation.** One Firecracker microVM per agent, and one branch per agent by default (`cursor/...`). Best-of-N tabs exist in the cloud UI. [DOC security.md; CL]

**Cursor CLI (`agent`, formerly `cursor-agent`)** [DOC cli/headless.md, cli/reference/parameters.md, cli/reference/output-format.md]
- `-p/--print` for headless runs.
- `--output-format text|json|stream-json`. `stream-json` emits `system/init`, `user`, `assistant`, `tool_call` started/completed, and `result{duration_ms, request_id, session_id}`.
- `--stream-partial-output`.
- `--resume [chatId]`, `--continue`, `create-chat`, `ls`.
- `-f/--force` (`--yolo`); without it, print mode only proposes edits.
- `--trust`, `--sandbox`, `--approve-mcps`, `--mode plan|ask`, `--plugin-dir`, `--add-dir`, `--api-key` / `CURSOR_API_KEY`.
- `agent worker start` for self-hosted machines.
- `agent acp`, the ACP server; subagents appear as child sessions [CL].
- `agent env deploy` (§1.5).
- The CLI runs rules, skills, subagents, hooks and plugins.
- "Single-turn runs wait for their subagents." [CL]

---

## 7. Callbacks and observation

- **Push from Cursor:** v0 webhooks only (`statusChange` on FINISHED / ERROR, HMAC-signed). v1 webhooks are still "coming soon".
- **Pull:** v1 SSE with `Last-Event-ID`, and polling `GET run` / `GET agent`.
- **Hooks inside the VM can make arbitrary HTTP calls.** They are spawned processes; the docs give a `stop` hook example that `fetch`es a telemetry URL. [DOC hooks.md]
  - Cloud hooks are limited to the events in §5.1. In particular, cloud has no `sessionStart` or `sessionEnd`.
- **Egress**
  - The default is **internet access allowed**.
  - Three modes: Allow all / Default + allowlist / Allowlist only. The team-level allowlist is shared with the desktop sandbox.
  - Settings exist at user, environment (inherit / inherit + allowlist / own mode) and team level (Enterprise can lock).
  - Even "Allowlist only" keeps Cursor services and SCM reachable.
  - `*.example.com` now also matches `example.com` [CL Sep 28 week].
  - Artifact uploads need `cloud-agent-artifacts.s3.us-east-1.amazonaws.com`.
  - Egress IPs come from `https://cursor.com/docs/ips.json` (clusters `us3p`, `us4p`, `us5p`). [DOC security-network.md]
  - **So a cloud agent can reach an arbitrary HTTPS endpoint unless the user, team or environment egress policy restricts it.**
- **Authenticated callback.** The VM mints an OIDC JWT; the receiver verifies it against `https://api.cursor.com/keys`, `aud`, and `cloud_agent_id` / `sub`. [DOC identity.md]
- **In-VM metadata** (preview), on `/run/cursor/api.sock` at `/v1/meta-data/`:
  - `agent/id|name|source|runtime`
  - `owner/user-id|user-email|service-account-id|team-id`
  - `turn/id|user-id|user-email|started-at|model` (present only during a turn)
  - `workspace/repo-url|repo-urls|branch-name|environment-id|automation-id`
  - Readable by hooks and install scripts; not a credential. [DOC metadata.md]
- **Subscriptions** let an agent wake on GitHub PR / CI, Slack, Linear or timer events, for at most 180 days.
  - Unavailable to service-account-owned agents. [DOC capabilities.md]
- **Enterprise OpenTelemetry export** exists (`/docs/enterprise/opentelemetry-export.md`). Not read in detail; **UNVERIFIED** for cloud agent events.

---

## 8. Human-only prerequisites before automated cloud launches

1. **Paid plan.**
   - "You need to be on a paid Cursor plan." [DOC cloud-agent.md troubleshooting; help/ai-features/cloud-agents.md]
   - Cloud Agents bill at **API pricing**, and **"You'll be asked to set a spend limit when you first start using them"** (interactive). [DOC cloud-agent.md "Billing"]
   - On Teams, on-demand usage is on by default; team and member spend limits are set in the dashboard. [DOC account/teams/pricing.md]
2. **Privacy Mode.** Must be on **Privacy Mode**, not **Privacy Mode (Legacy)**. Switch in Dashboard → Cloud Agents. [DOC security-network.md]
3. **SCM app install.** Requires a Cursor admin and a Git-org admin. For service accounts, the GitHub integration must be **team-level**. [DOC integrations/github.md; service-accounts.md]
4. **Each human user connects their own Git account** under Integrations. [DOC security.md]
5. **API key creation** in Dashboard → API Keys (user). Service accounts are Enterprise-only, created at Dashboard → Settings → API Keys → Service Accounts; the key is shown once. [DOC api.md; service-accounts.md]
6. **Dashboard-only settings:**
   - Team follow-ups, Long-running agents, Computer use (Enterprise).
   - Display agent summary; Auto-fix CI.
   - "Allow posting artifacts to GitHub".
   - Default model, repo and base branch.
   - Network access mode and allowlists (no API found; environment-level egress can be set inside `environmentJson`).
   - Secret-change admin restriction; Sync Skills for Cloud Agents.
   - Team MCP servers (Dashboard > Plugins & MCPs) and personal MCP OAuth (per-user OAuth through the UI).
   - Team rules and hooks (Enterprise).
   - AWS IAM external ID; Build pin / activate / trigger / start-from-Build.
   - **Build secrets** (not settable through the API).
   - **User secrets** (no write API).
7. **Beta / rollout features to confirm per account:** `envVars` (silently ignored if not enabled) and `metadata` (`403 feature_unavailable`).
8. **Optional: run the guided environment setup once.** The alternative is to create the environment through the API or commit `.cursor/environment.json` and wait for the first successful Build. Until then, agents start on the default universal image.

---

## Materialization map

| Artifact | Path / API | Local honored? | Cloud honored? | Automatable? | Source |
|---|---|---|---|---|---|
| Environment config | `.cursor/environment.json` (repo, default branch) | n/a | Yes; wins over saved environments | Yes (commit) | setup.md; schema |
| Saved environment | `POST/PATCH /v1/environments` (`environmentJson`) | n/a | Yes, unless the repo file exists | Yes (REST only; no SDK) | endpoints.md |
| Build trigger / pin / start-from-Build | Dashboard; in-VM Cursor Cloud MCP `trigger-environment-build` | n/a | n/a | Partly (only an agent can trigger; no REST) | builds.md; capabilities.md |
| Team / environment secrets | `PUT /v1/team/secrets/{n}`, `/v1/environments/{id}/secrets/{n}` | n/a | Yes, as env vars (Builds get team + env) | Yes (not `build_secret`) | endpoints.md |
| User secrets | Dashboard | n/a | Yes, at start only | **No API** | endpoints.md; builds.md |
| Launch env vars | `envVars` / SDK `env_vars`, `cloud.env_vars` | Process env | Yes (beta) | Yes | endpoints.md; sdk/python.md |
| Rules | `.cursor/rules/*.mdc` (plain `.md` ignored) | Yes | Yes (repo) | Yes (commit) | rules.md |
| AGENTS.md | Root and nested | Yes | Yes | Yes | rules.md; setup.md |
| Skills | `.cursor/skills`, `.agents/skills`, `.claude/skills`, `.codex/skills` | Yes | Project: yes; `~/.cursor/skills` with sync; `~/.agents` no | Yes (commit) | skills.md |
| Subagents (file) | `.cursor/agents/*.md` (`.claude/agents`, `.codex/agents`) | Yes (SDK: `setting_sources` includes project) | Yes | Yes | subagents.md; sdk/typescript.md |
| Subagents (inline) | SDK `agents` / REST `customSubagents` | Yes | Yes (≤20; no `readonly` / `is_background`) | Yes | endpoints.md |
| Hooks | `.cursor/hooks.json` | Yes (IDE / CLI / SDK) | Command hooks only; 14 events; no session or MCP hooks | Yes (commit) | hooks.md |
| Claude hooks | `.claude/settings.json` | IDE + CLI yes | UNVERIFIED | Yes | third-party-hooks.md; CLI changelog |
| MCP (file) | `.cursor/mcp.json` | Yes (SDK gated) | **Not documented for cloud** | Yes (local) | sdk/typescript.md |
| MCP (inline) | SDK `mcp_servers` / REST `mcpServers` | Yes | Yes (HTTP / stdio) | Yes | endpoints.md |
| MCP (dashboard) | cursor.com/agents; Plugins & MCPs | Via marketplace install | Yes | No (UI; per-user OAuth) | capabilities.md; mcp.md |
| MCP policy | env `mcpServerAllowlist`, `disableAllMcpServers` | n/a | Yes | Yes | schema |
| Egress policy | env `egressMode`, `egressAllowlist`; dashboard user / team | Sandbox only | Yes | Environment: yes; user / team: dashboard | schema; security-network.md |
| Worktree setup | `.cursor/worktrees.json` | Yes (Agents Window / IDE / CLI) | n/a | Yes | worktrees.md |
| Plugins | `.cursor-plugin/`, marketplace, `--plugin-dir` | Yes | "plugins" loaded; detail UNVERIFIED | Partly | plugins.md |
| Commands | Customize / plugins | Yes | UNVERIFIED | Partly | customize-cursor.md |
| Status callback | v0 `webhook{url,secret}` | n/a | Yes (v0 only) | Yes | webhooks.md |
| In-VM callback auth | OIDC socket `/run/cursor/api.sock` | n/a | Yes (managed VMs) | Yes | identity.md |

---

## Delta vs repo beliefs

Repo sources compared: `docs/research/2026-10-07-coding-lane-surfaces.md` (Cursor), `docs/specs/archive/fast-track-2026-10/research/cursor-platform.md`, `mission-control-general/runtime-facts/CURSOR_SDK_FACTS.md`, `docs/specs/archive/multi-provider-2026-10/RESEARCH.md`, and `.cursor/{environment.json, Dockerfile, scripts/}`.

### Contradictions / corrections

1. **Environments and secrets are scriptable.**
   - cursor-platform.md §4.5 says `/v1/environments` "exist in the OpenAPI. They are not detailed here", and the repo has no plan to use them.
   - They are now fully documented: environment CRUD, history, Builds read, active Build, and secrets CRUD for team and environment scope (§1.5, §2.4).
   - They were added around the week of Sep 28 2026 [CL].
   - Remaining limits: no user-secret write, no `build_secret` write, no Build trigger or start-from-Build.
2. **Project `.cursor/mcp.json` is not a cloud MCP source.**
   - cursor-platform.md implication 1 says to write `.cursor/mcp.json` and "commit or push them ... for cloud".
   - The SDK docs list cloud MCP sources as inline send > inline create > dashboard user / team servers. Use inline `mcpServers` (re-sent on resume) or dashboard servers for cloud.
   - Cloud MCP supports **HTTP and stdio only; SSE is not supported**. The repo lists sse as an option.
3. **`.cursor/environment.json` precedence.**
   - The committed repo file **overrides** personal and team saved environments.
   - The mission-control repo already commits one (named "Biotech backend (Docker Compose)", last changed 2026-07-22), so an API-created environment for this repo would be shadowed.
4. **`install` runs at Build time against the default branch, not per agent.**
   - Builds are now **always on**.
   - `cloud-install.sh` runs during Builds with team and environment secrets but **without user secrets**.
   - The `git clone https://github.com/Overton77/biotech-meta` in `cloud-install.sh` relies on `repositoryDependencies` token scoping, and the exact in-VM credential mechanism is UNVERIFIED.
   - Changes to environment.json on a feature branch do not rebuild.
5. **Named environment targeting exists but excludes `repos`.**
   - The repo models `env` only as cloud / pool / machine routing.
   - `env:{type:"cloud", name}` selects a saved environment and is mutually exclusive with `repos` (and so with `startingRef` / `prUrl`).
6. **Plain `.md` files in `.cursor/rules/_briefings/` are ignored** by the Cursor rules system; only `.mdc` loads. They are only reachable if referenced.
7. **Cursor will also load the repo's `.claude/skills/`** (compatibility directories). If a `.claude/settings.json` with hooks is ever added, Cursor would load it in the IDE and CLI (third-party imports are on by default). The repo assumes per-provider isolation of materialized cognition, so these cross-provider imports need to be either intended or disabled.

### Additions (not in repo beliefs)

8. **Cursor Cloud MCP** (built-in, admin-disableable).
   - Exposes transcripts, run events, environment info, Build logs and **Build triggering** to in-VM agents.
   - In-VM transcript retrieval works despite there being no v1 conversation endpoint.
9. **Secret semantics**: types (`runtime_secret` redaction to `[REDACTED]`, `environment_variable`, `build_secret`), the four-level precedence, Build visibility, and per-repo versions.
10. **OIDC tokens** give a signed, audience-bound way for hooks and agents to call Mission Control back (`exp` 300 s; claims `cloud_agent_id`, repos, `environment_id`).
11. **Snapshot retention**: 90 days of inactivity, rolling, not deletable; `DELETE /v1/agents/{id}` removes the transcript and artifacts only.
12. **Egress** is controllable per environment in `environmentJson` (`egressMode`, `egressAllowlist`), and MCP is controllable per environment (`mcpServerAllowlist`, `disableAllMcpServers`).
13. **Subscriptions** (PR / CI / Slack / Linear / timer wakeups) and auto CI fixing.
    - They do not apply to service-account-owned agents, which matters if Mission Control launches with a service account.
14. **CLI**: `agent env deploy`; worktree flags with the `~/.cursor/worktrees/<repo>/<name>` location; `.cursor/worktrees.json` keys; worktree cap of 25 per machine with cleanup of unmanaged worktrees (a risk for Mission Control-managed worktrees under `~/.cursor/worktrees`).
15. **Human prerequisites**: spend-limit prompt on first use, Privacy Mode (Legacy) unsupported, team-level GitHub integration for service accounts, Enterprise-only service accounts.

### Confirmations (unchanged)

- SDK / bridge 1.0.37 is still latest; release notes still end at 1.0.35.
- REST v1 is public beta.
- One active run per agent (`409 agent_busy`); cancel is terminal.
- SSE events, `Last-Event-ID`, retention header and `410 stream_expired`.
- `git` is per-agent; no SHA or diff; no branch-name field.
- Webhooks are v0-only `statusChange` (FINISHED / ERROR) with HMAC; v1 says "coming soon".
- Hooks: event list, I/O contract, exit-2 deny, `failClosed`, `ask` not enforced for `preToolUse`, cloud matrix (no `sessionStart` / `sessionEnd` / MCP hooks; none in read-only turns; command-only; no user hooks).
- Subagent frontmatter has 5 fields; nesting depth is 2.
- Skill frontmatter; Sync Skills for Cloud.
- Rate limit is "standard", with a 20/min default; concurrency caps are undocumented.
- `envVars` is beta (silently ignored) and cannot be combined with `agentId`.
- `metadata` is gated.

### Still UNVERIFIED

- Per-plan concurrent cloud agent limits.
- Stream retention seconds.
- v0 webhook retry policy, and whether v0-created agents can be driven through v1.
- `agent env deploy` semantics.
- Whether named `env.name` accepts an ID.
- Cloud honoring of commands, plugin components and Claude-format hooks.
- The headless-SDK per-hook matrix.
- In-VM git credential mechanism and pushing to repos outside `repos` / `repositoryDependencies`.
- Python `system_prompt` (still absent).

## Citations (all read 2026-10-12)

- https://cursor.com/llms.txt (docs index)
- https://cursor.com/docs/cloud-agent.md
- https://cursor.com/docs/cloud-agent/setup.md
- https://cursor.com/docs/cloud-agent/builds.md
- https://cursor.com/docs/cloud-agent/capabilities.md
- https://cursor.com/docs/cloud-agent/metadata.md (preview)
- https://cursor.com/docs/cloud-agent/identity.md
- https://cursor.com/docs/cloud-agent/security.md
- https://cursor.com/docs/cloud-agent/security-network.md
- https://cursor.com/docs/cloud-agent/settings.md
- https://cursor.com/docs/cloud-agent/automations.md
- https://cursor.com/docs/cloud-agent/api/endpoints.md (v1 public beta)
- https://cursor.com/docs-static/cloud-agents-openapi.yaml (OpenAPI 3.0.3, info.version 1.0.0)
- https://cursor.com/docs/cloud-agent/api/webhooks.md
- https://cursor.com/docs/cloud-agent/api/v0.md (legacy)
- https://www.cursor.com/schemas/environment.schema.json
- https://cursor.com/docs/api.md
- https://cursor.com/docs/hooks.md
- https://cursor.com/docs/reference/third-party-hooks.md
- https://cursor.com/docs/skills.md
- https://cursor.com/docs/subagents.md
- https://cursor.com/docs/rules.md
- https://cursor.com/docs/mcp.md
- https://cursor.com/docs/plugins.md
- https://cursor.com/docs/customize-cursor.md
- https://cursor.com/docs/configuration/worktrees.md
- https://cursor.com/docs/cli/headless.md
- https://cursor.com/docs/cli/reference/parameters.md
- https://cursor.com/docs/cli/reference/output-format.md
- https://cursor.com/docs/cli/changelog.md (latest v2026.10.08)
- https://cursor.com/docs/sdk/python.md
- https://cursor.com/docs/sdk/typescript.md
- https://cursor.com/docs/sdk/bridge.md
- https://cursor.com/docs/release-notes/sdk.md (latest entry 1.0.35)
- https://cursor.com/docs/release-notes.md (unified timeline incl. 3.23, week of Sep 28 2026, Oct 1 2026)
- https://cursor.com/docs/integrations/github.md
- https://cursor.com/docs/account/enterprise/service-accounts.md
- https://cursor.com/docs/account/teams/pricing.md
- https://cursor.com/help/ai-features/cloud-agents.md
- https://pypi.org/pypi/cursor-sdk/json (1.0.37, 2026-10-07T20:05Z)
- https://registry.npmjs.org/@cursor/sdk (latest 1.0.37, next 1.0.27-beta.0)
- https://api.github.com/repos/cursor/sdk-bridge/releases (v1.0.37, 2026-10-07T20:07Z)
- Local: `platform/mission-control/.cursor/environment.json` (git last change 2026-07-22), `.cursor/Dockerfile`, `.cursor/scripts/cloud-install.sh`, `.cursor/scripts/cloud-start.sh`, `.cursor/rules/`
