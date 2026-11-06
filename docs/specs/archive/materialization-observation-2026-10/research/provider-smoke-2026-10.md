---
type: Research Note
title: "Provider smoke 2026-10: Managed Agents and Agents API field confirmation (HL-23)"
description: "Live, paid smokes of Anthropic Managed Agents (anthropic 1.13.0, claude-sonnet-5-5) and the OpenAI Agents API (openai 3.29.0, gpt-6-luna): working request shapes, ids, event names, usage and cost, the answers to Q-M1 and Q-O2, and every packet correction they caused."
tags: [mission-control, research, materialization-observation, providers, anthropic, openai]
---

# Provider smoke 2026-10 (HL-23)

Run on 2026-10-12 local time (evidence timestamps are UTC 2026-10-13) with the owner's keys from `mission-control/.env`, inside the authorised HL-23 budgets: under $1 each, Anthropic from S2 and OpenAI from S3. The scripts are `scripts/provider_smoke/` (one per provider plus `common.py`). They print only ids and statuses. Each writes an evidence JSON with ids, event names and counts, the ordered event sequence, usage and verdicts, and never any model text. Those JSON files stay in the git-ignored `.scratch/materialization-observation-2026-10/HL-23/` and are not committed.

```bash
source .scratch/materialization-observation-2026-10/run1-env.sh   # keys; never printed
uv run --no-project --python 3.12 --with anthropic==1.13.0 \
    python -m scripts.provider_smoke.anthropic_managed_agents --record <dir>/anthropic.json
uv run --no-project --python 3.12 --with openai==3.29.0 \
    python -m scripts.provider_smoke.openai_agents_api --record <dir>/openai.json
```

The pinned SDKs are not in `uv.lock` (the project has `anthropic` 0.120.2 and `openai` <3), so the smokes run in an isolated `uv run --no-project --with` environment and `pyproject.toml` is untouched. Every resource that accepts metadata carries `mc_run=run1-HL-23`. Neither Skills API accepts metadata, so the skill carries the label in its name (`mc-run1-hl-23-smoke`). Every resource was deleted or archived at the end of each run, and the cleanup outcomes are listed below.

## 1. Answers

| Question | Answer | Evidence |
| --- | --- | --- |
| Does the Agents API accept `gpt-6-luna`? | **Yes.** `agents.create(model="gpt-6-luna")` succeeded and every turn completed on it in all four OpenAI runs. No substitution was needed. | `openai-smoke-1..4`: `model_accepted: true` |
| **Q-M1** (Managed Agents): does a `user.message` sent while `running` reach the current turn? | **Yes, it is injected mid-turn.** The message was consumed (`processed_at` set) between a tool result and the next model request of the same turn, and the agent's final answer for that turn obeyed it. No extra turn was started for it. This was observed in all three runs that reached the step (1, 4 and 5). **Caveat:** sending it while the session is still waiting on a custom-tool answer returns 400 (run 2). Send it after `session.status_running`. | `anthropic-smoke-5`: `q_m1_verdict: injected_mid_turn`, `midturn_ack_in_same_turn: true`; sequence `agent.tool_result → user.message → span.model_request_start …` |
| Q-M1 analogue (Agents API steer) | **Yes.** A message sent during the turn landed in the same turn as a `message:user` item, before that turn's `final_answer`. The answer obeyed it, and no turn was created for it. | `openai-smoke-3,4`: `steer_item_in_first_turn: true`, `steer_item_before_final_answer: true` |
| **Q-O2**: does the Agents API honour an `AGENTS.md` in the hosted workspace? | **Yes, once the hosted environment is connected.** With `/workspace/AGENTS.md` uploaded as an inline environment file, a later turn quoted its canary with **no command run and no file read**. The canary is not in the instructions or the prompt. A first turn answered **before** `agent.session.environment.ready` did **not** see it (run 2). The rule is therefore: honoured after the environment connects; a turn that runs before that is blind to it. | `openai-smoke-3,4`: `q_o2_verdict: honoured_in_context`, `agents_md_listed: true`; `openai-smoke-2`: `not_honoured`, with no environment event before the answer |

## 2. Anthropic Managed Agents (`anthropic==1.13.0`, `claude-sonnet-5-5`)

### 2.1 Working request shapes (as sent, run 5)

```python
client = Anthropic(timeout=120.0, max_retries=0)       # creates are not idempotent

skill = client.skills.create(                           # stable namespace, no beta header
    display_name="mc-run1-hl-23-smoke",
    files=[("mc-run1-hl-23-smoke/SKILL.md", skill_md_bytes, "text/markdown")],
)                                                       # -> id, latest_version_id; no metadata field

vault = client.beta.vaults.create(display_name="mc-run1-HL-23-smoke", metadata={"mc_run": "run1-HL-23"})
credential = client.beta.vaults.credentials.create(
    vault.id,
    display_name="mc-smoke-placeholder",
    auth={"type": "environment_variable", "secret_name": "MC_SMOKE_PLACEHOLDER",
          "secret_value": "<placeholder>",
          "networking": {"type": "limited", "allowed_hosts": ["example.com"]}},
    metadata={"mc_run": "run1-HL-23"},
)

agent = client.beta.agents.create(
    name="mc-run1-HL-23-smoke", model="claude-sonnet-5-5", system="...",
    tools=[
        {"type": "agent_toolset_20260401",
         "default_config": {"enabled": False},
         "configs": [{"name": n, "enabled": True, "permission_policy": {"type": "always_allow"}}
                     for n in ("read", "glob", "grep")]},
        {"type": "custom", "name": "mc_signal", "description": "...",
         "input_schema": {"type": "object", "properties": {...}, "required": ["name"],
                          "additionalProperties": False}},
    ],
    skills=[{"type": "custom", "skill_id": skill.id, "version": skill.latest_version_id}],
    metadata={"mc_run": "run1-HL-23"},
)                                                       # -> version 1

environment = client.beta.environments.create(
    name="mc-run1-HL-23-smoke",
    config={"type": "cloud",
            "networking": {"type": "limited", "allowed_hosts": ["example.com"],
                           "allow_package_managers": False, "allow_mcp_servers": False}},
    metadata={"mc_run": "run1-HL-23"},
)

session = client.beta.sessions.create(
    agent={"type": "agent", "id": agent.id, "version": agent.version},
    environment_id=environment.id,
    vault_ids=[vault.id],
    budget={"type": "limit", "max_list_cost": {"amount": "90", "currency": "USD"}},  # minor units
    title="mc run1-HL-23 smoke",
    metadata={"mc_run": "run1-HL-23"},
    initial_events=[{"type": "user.message", "content": [{"type": "text", "text": "..."}]}],
)                                                       # -> status "running"

with client.beta.sessions.events.stream(session.id) as stream:    # stream first
    for event in chain(client.beta.sessions.events.list(session.id), stream):  # then history
        ...                                             # dedupe on (event.id, processed_at is set)

client.beta.sessions.events.send(session.id, events=[
    {"type": "user.custom_tool_result", "custom_tool_use_id": event.id,
     "content": [{"type": "text", "text": "ok"}]}])
client.beta.sessions.events.send(session.id, events=[            # after session.status_running
    {"type": "user.message", "content": [{"type": "text", "text": "..."}]}])  # -> data[0].id
client.beta.sessions.events.send(session.id, events=[{"type": "user.interrupt"}])

client.beta.sessions.retrieve(session.id).usage          # tokens, list_cost, active_seconds
client.beta.sessions.delete(session.id)
client.beta.environments.delete(environment.id)
client.beta.agents.archive(agent.id)                    # agents have no delete
client.beta.vaults.credentials.delete(credential.id, vault_id=vault.id)
client.beta.vaults.delete(vault.id)
client.skills.delete(skill.id)                          # removes its only version too
```

### 2.2 Ids, usage and cost per run

| Run | Ids (skill / vault / credential / agent / environment / session) | Outcome | `list_cost` | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | `skill_01Nrs6LhxiT3KAfsteoWQCaB` / `vlt_011CfyUiqQSdc6Qkcv3sYPh2` / `vcrd_01M5hEnxnmaMm14fVfYkZjD5` / `agent_01Pa8vNGUrTJH7ZkDKgtmE6n` / `env_01UwN1amj49yzbdaWk97xVfb` / `sesn_01CQjiSeNPjAatawt5DP4LsE` | Full flow. `session.error` `credential_host_unreachable_error`, because the environment's `allowed_hosts` was empty while the credential's host was `example.com`. | $0.04 | All done. The skill failed first: deleting its only version returns 400. It was then deleted with `skills.delete`. |
| 2 | `skill_014B26pZicdisdttTAXLD1Rp` / `vlt_011CfyV1r9KeJoFQNqarbfEF` / `vcrd_016uX2sS9KzmQNrRzebgjWe2` / `agent_0123GJe7KRDo3QZkm63QreUx` / `env_01UZs6mQUpR8ANBy9sqjHSqr` / `sesn_011WPRxgRhvedLKqqPX4VxVC` | The mid-turn `user.message`, sent right after `user.custom_tool_result`, got **400** `invalid_request_error`: "waiting on responses to events [sevt_…]; only `user.tool_confirmation`, `user.custom_tool_result`, `user.tool_result`, or `user.interrupt` may be sent". | unknown (one model request; ≤ $0.04 estimated) | All deleted or archived |
| 3 | `skill_01UUDzYwdYvdfYK8ZaPapDuv` / `vlt_011CfyV6FBXK1Z8Hjg2hPGZK` / `vcrd_01VHar7QE6E8NHS3p77UQXyz` / `agent_013joG7NZq4WLWLtWHkhr1xW` / `env_013ThE3MME3AvhJxypSmjAb3` / `sesn_01RFQk4UNn5Vzuo1EsN55Hpu` | Full flow, but the evidence JSON was lost: an operator path error. `--record` is now validated before provisioning. | unknown (≤ $0.04 estimated) | All deleted or archived |
| 4 | `skill_0127drs9zqRTCr5mDD9iVMAZ` / `vlt_011CfyVGu5qzTYitA3kax7SA` / `vcrd_01ULer1tPKqtYCJrsJKoujLM` / `agent_01LtRh2R3cDm2A5CLxGZRVjQ` / `env_01C3DdRi6Jb8Hr17TV1rq6my` / `sesn_01D35aisSUc5eEAHNxcjPnQE` | Full flow, no errors | $0.01 | All deleted or archived |
| **5 (final code)** | `skill_018eq4DnXuVAdH3aa4jjABWs` / `vlt_011CfyWMZXcCeXzYztzNTPYf` / `vcrd_01LCqZCJa2zta39RXhFzEh8r` / `agent_01Kzoe5dwWy5FpBEvgSyADbV` / `env_01JkPingAugiz2X6trVy9EBf` / `sesn_01AvECmzptpJQrCXkaCEtrvt` | Full flow, no errors | $0.04 | All deleted or archived |

Run 5 usage (`sessions.retrieve(...).usage`): `input_tokens` 89, `output_tokens` 325, `cache_read_input_tokens` 15,070, `cache_creation.ephemeral_5m_input_tokens` 13,510, `active_seconds` 17.094, `list_cost {"amount": "4", "currency": "USD"}`, `server_tool_use` 0/0. **Anthropic total: $0.09 measured (runs 1, 4 and 5), plus at most $0.08 estimated for runs 2 and 3, so at most $0.17 against the $1 cap.**

### 2.3 Event names seen (run 5, in order; repeats collapsed)

`session.status_running` → `session.thread_status_running` → `user.message` → `span.model_request_start` → `agent.custom_tool_use` → `span.model_request_end` → `session.thread_status_idle` → `session.usage` → `session.status_idle{requires_action}` → `user.custom_tool_result` → `session.status_running` → `session.thread_status_running` → `span.model_request_start` → `agent.tool_use` → `span.model_request_end` → `agent.tool_result` → **`user.message` (mid-turn, processed)** → `span.model_request_start` → `agent.tool_use` → `span.model_request_end` → `agent.tool_result` → `span.model_request_start` → `agent.message` → `span.model_request_end` → `session.thread_status_idle` → `session.usage` → `session.status_idle{end_turn}` → `session.status_running` → `session.thread_status_running` → `user.message` → `span.model_request_start` → `span.model_request_end` → **`user.interrupt`** → `session.thread_status_idle` → `session.usage` → `session.status_idle{end_turn}`.

Runs 1 and 4 also showed `agent.thinking`. Run 1 showed `session.error`, whose `error.type` was `credential_host_unreachable_error`.

### 2.4 Observations that matter to the lane

- **Mid-turn delivery (Q-M1).** A queued `user.message` is consumed at the **next model-request boundary of the running turn**, not at turn end. `send_turn` while running therefore steers the current turn. It is not a next-turn queue.
- **The 400 race.** After `user.custom_tool_result`, the session stays in its `requires_action` wait until it emits `session.status_running`. A `user.message` sent in that window gets 400. Gate any send on `session.status_running` (or on not being `idle{requires_action}`).
- **Interrupt.** Sent at `span.model_request_start`, the interrupt lets the in-flight model request finish (`span.model_request_end`). The `user.interrupt` is then processed, no `agent.message` is emitted, and the session goes `session.status_idle{end_turn}`.
- **A `session.usage` event precedes every idle.** `list_cost.amount` is in whole cents (minor units), so short sessions settle to 1-cent resolution.
- **`session.thread_status_*` events appear for the primary thread even with multiagent off.**
- **A vault `environment_variable` credential's host must be reachable from the environment.** Under `limited` networking, put it in `allowed_hosts`, or the session reports `credential_host_unreachable_error`. The session still runs.
- **Cleanup.** `skills.delete` removes the skill together with its only version, while deleting the only version first returns 400. Agents can only be archived. An environment can be deleted once its session is deleted. Deleting a session that is still `running` fails, so wait out the `running` status after the idle event: it lags (client pattern 6).

## 3. OpenAI Agents API (`openai==3.29.0`, `gpt-6-luna`)

### 3.1 Working request shapes (as sent, run 4)

```python
client = OpenAI(timeout=120.0, max_retries=0)

skill = client.skills.create(files=[("mc-run1-hl-23-smoke/SKILL.md", skill_md_bytes, "text/markdown")])
# -> id, name and description from SKILL.md, default_version "1", latest_version "1"; no metadata field

vault = client.beta.agents.vaults.create(name="mc-run1-HL-23-smoke", metadata={"mc_run": "run1-HL-23"})
credential = client.beta.agents.vaults.credentials.create(
    vault.id, name="mc-smoke-placeholder",                     # name is required here
    auth={"type": "environment_variable", "secret_name": "MC_SMOKE_PLACEHOLDER",
          "secret_value": "<placeholder>",
          "networking": {"type": "limited", "allowed_hosts": ["example.com"]}},
    metadata={"mc_run": "run1-HL-23"},
)

agent = client.beta.agents.create(
    model="gpt-6-luna", name="mc-run1-HL-23-smoke", instructions="...",
    tools=[{"type": "function", "name": "mc_signal", "description": "...",   # description required
            "parameters": {"type": "object", ...}}],
    multi_agent={"enabled": False},
    metadata={"mc_run": "run1-HL-23"},
)

session = client.beta.agents.sessions.create(
    agent_id=agent.id,
    environment={"type": "openai_hosted", "container_size": "small",       # inline; no template needed
                 "network": {"access": "restricted", "allowed_domains": ["example.com"]},
                 "files": [{"type": "inline", "path": "/workspace/AGENTS.md", "data": "<base64>"}],
                 "skills": [{"type": "skill_reference", "skill_id": skill.id}]},  # version optional
    vault_ids=[vault.id],
    metadata={"mc_run": "run1-HL-23"},
)                                                                # no input -> status "idle"

with client.beta.agents.sessions.events.stream(session.id) as stream:      # stream first
    client.beta.agents.sessions.events.create(session.id, idempotency_key=str(uuid4()), events=[
        {"type": "agent.session.input.message",
         "input": [{"role": "user", "content": [{"type": "input_text", "text": "..."}]}]}])
    ...
# function call: event.session.required_actions[i] = {type: function_call, call_id, turn_id, name, arguments}
events.create(..., events=[{"type": "agent.session.input.tool_result", "turn_id": ..., "call_id": ...,
                            "success": True, "output": "ok"}])
events.create(..., events=[{"type": "agent.session.input.cancel"}])     # retry on 409 (below)

client.beta.agents.sessions.items.list(session.id, order="asc")    # durable history
client.beta.agents.sessions.turns.list(session.id, order="asc")    # per-turn usage
client.beta.agents.sessions.retrieve(session.id).usage             # was null in every run
client.beta.agents.sessions.delete(session.id)                     # retry on 409
client.beta.agents.delete(agent.id)
client.beta.agents.vaults.credentials.delete(credential.id, vault_id=vault.id)
client.beta.agents.vaults.delete(vault.id)
client.skills.delete(skill.id)
```

### 3.2 Ids, usage and cost per run

| Run | Ids (skill / vault / credential / agent / session) | Outcome | Cost (estimated) | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | `skill_6acd9ef8a3908191beda419165a2f77f0620cf473f7f84bb` / `vault_7c105e290b534ae9aa9eeb41a1d39d512046fa6916ec4b1a89` / `credential_c99a5bbaa75e46e4ad9c2fa6cacba71b7f8fedaabf42495991` / `agent_d5744e6e83ff4e75800797df441bdd74fd82091dd80040529c` / `sess_01b546107889e42f006acd9f1577fc81929cecd1f5f217873b` | Turn 1 completed on `gpt-6-luna`. A cancel sent at `turn.in_progress` got **409** `conflict_error`: "active session turn changed during cancellation; retry the request". | ~$0.01 | All deleted |
| 2 | `skill_6acd9f860ffc8191aa22420cd6383cda0113521c2574f9b6` / `vault_fc46e3ce43bb4ab2a94d090333c7916eec9ba1ec193f4a9faa` / `credential_e73be560af5a4d559128d4f3aae8d6ca43d5975a7d8f4999af` / `agent_c65e649dfda94089a79512a6a1b1a9f09a2c7ee5682843c889` / `sess_0ab3c36af1307fed006acd9f8bd6b481a1855708e081f2e6af` | The canary question came in turn 1, with no tool use, and was answered **before** the environment connected: no canary (Q-O2 timing). The cancel was retried and the turn was cancelled. | ~$0.01 | All deleted |
| 3 | `skill_6acda020b4fc8191b76a406e5ba204850edf3fee25827717` / `vault_9c526bee3a034a4e9490195097a00a38b24e91bb41d54c73ac` / `credential_cd8d487b731d4f51b2248212845ff8a6ebb8933a208d4c14a6` / `agent_8a1bce5f1f0e4115ba7a6cbcc74b1866a3f016439422436b80` / `sess_0943610b2900efc2006acda026f2ec8192aa19987c701cd2cd` | Three turns: steered in turn 1, canary quoted in turn 2 (`honoured_in_context`), turn 3 cancelled | $0.0098 + the cancelled turn | All deleted |
| **4 (final code)** | `skill_6acda20193e08191801c74a05eaf04c307d45e7c5939091a` / `vault_e0fa289101ef48ea9eac63583e9c03e373ea9a23c32d497987` / `credential_8da1d3f6a3604cc887e07c42ce3fd5d5a9088ce41e8e4e18ae` / `agent_75b704124afa4d2092d3625ea4e506d38149a78e85c148f795` / `sess_097d41437383f8ad006acda206d674819fbdf1a70a463cc711` | Same as run 3 | $0.0103 + the cancelled turn | All deleted |

Run 4 per-turn usage from `turns.list`:

| Turn | Input tokens (cached) | Output tokens (reasoning) |
| --- | --- | --- |
| 1 | 63,840 (45,209) | 581 (186) |
| 2 | 10,893 (10,738) | 49 (34) |
| 3, cancelled | `null` | `null` |

`sessions.retrieve(...).usage` was `null` in every run. The estimate uses the research price table (`gpt-6-luna` $0.10 / $0.01 cached / $0.50 per 1M tokens; a small container at $0.03 per 20 minutes with a 5-minute minimum). The container minimum ($0.0075) is most of it. **OpenAI total: about $0.04 estimated across four runs, against the $1 cap. The Agents API reports no settled cost.**

### 3.3 Event names seen (run 4, in order; repeats and deltas collapsed)

`agent.session.turn.created` → `agent.session.in_progress` → `agent.session.turn.in_progress` → `agent.session.turn.item.added` → `agent.session.turn.content_part.added` → `agent.session.turn.output_text.delta` → `agent.session.turn.output_text.done` → `agent.session.turn.content_part.done` → `agent.session.turn.item.done` → `agent.session.requires_action` → (tool result, steer) → `agent.session.in_progress` → … → **`agent.session.environment.ready`** → `agent.session.turn.item.added` → **`agent.session.environment.connected`** → (command execution items) → `agent.session.turn.completed` → `agent.session.idle` → turn 2 (… `agent.session.environment.ready` …) → `agent.session.turn.completed` → `agent.session.idle` → turn 3 → `agent.session.turn.cancelled`.

The run 4 durable item sequence was: `message:user, message:assistant, function_call, function_call_output, reasoning, message:assistant, message:user (steer), reasoning, reasoning, message:assistant, command_execution, reasoning, message:assistant, message:user, reasoning, message:assistant, message:user, reasoning`. `agent.session.created` is not seen when the stream opens after create. The session is `idle` until the first input arrives.

### 3.4 Observations that matter to the lane

- **The environment comes up lazily.** `agent.session.environment.ready` and `connected` arrive when the turn first needs the sandbox, not at session create. AGENTS.md is honoured only after that (Q-O2).
- **Cancel can return 409 `conflict_error`** when it races the turn start. Retry it, and treat 202 as accepted only.
- **Usage.** Session `usage` stayed `null`. Per-turn usage comes from `turns.list` and is `null` for a cancelled turn. Cost is an estimate, and any turn without usage stays unknown.
- **The steer lands in the same turn** as a `message:user` item. No separate turn is created for it.
- **Vault and skill paths.** The SDK uses `/v1/agents/vaults` (`client.beta.agents.vaults`), and it worked. Skills (`/v1/skills`) take only `files`, and the name and description come from `SKILL.md`.

## 4. Corrections applied to the packet

| # | Document and place | Was | Now |
| --- | --- | --- | --- |
| 1 | MANAGED-AGENTS-REMOTE-PATH §3.1, beta header row | Skills and Files need the `skills-2025-10-02` and `files-api-2025-04-14` betas | Skills and Files are stable namespaces in `anthropic` 1.13.0 (`client.skills`, `client.files`), with no beta header. Skills were exercised live. |
| 2 | MANAGED-AGENTS-REMOTE-PATH §3.1, skills row | ≤500 per session | ≤20 per agent per the current Managed Agents tools docs (UNVERIFIED by drill). Skills carry no metadata on either API. OpenAI skills take only `files`. |
| 3 | MANAGED-AGENTS-REMOTE-PATH §3.1, own-tools and secrets rows | OpenAI function shape elided; no host rule for vault variables | The function tool needs `description`. A tool result is `{turn_id, call_id, success, output}`. A vault variable's host must be in the environment `allowed_hosts`. |
| 4 | MANAGED-AGENTS-REMOTE-PATH §3.2 code | `client.beta.skills.create(display_title=…)`, `vaults.create(name=…)`, `credentials.create(vault.id, type=…)` | `client.skills.create(display_name=…, files=[(dir/SKILL.md, bytes, mime)])`, `vaults.create(display_name=…)`, `credentials.create(vault.id, display_name=…, auth={type, …})`, skill pinned by `latest_version_id`, tools configured per tool |
| 5 | MANAGED-AGENTS-REMOTE-PATH §3.3 code | Session `environment` from a template; `input` at create | Inline `openai_hosted` environments work without a template. Input is sent with `events.create(…, idempotency_key=…)` after the stream opens. The skill reference `version` is optional. Vault credentials need `name`. |
| 6 | MANAGED-AGENTS-REMOTE-PATH §2.2 (AGENTS.md row) and §7 step 1 | Q-O2 unverified; smoke pending | Honoured once the environment connects, and still inline critical rules. Step 1 is done (this note). |
| 7 | SPEC-06 §4.1, secrets row | No host rule | The credential host must be in the environment allowlist, or the session reports `credential_host_unreachable_error`. |
| 8 | SPEC-06 §4.2 `send_turn` / `interrupt_and_inject` / `usage` / `end_session` / `observe` rows | Next-turn delivery; mid-turn undocumented | Injected at the next model-request boundary of the running turn. Gate the send on `session.status_running` after any tool answer (400 race). `list_cost` is in whole cents. Primary-thread `session.thread_status_*` events always appear. Agents are archived only; skills are deleted with their only version. |
| 9 | SPEC-06 §5.1 | Q-O2 unverified | Honoured after environment connect; still inline critical rules; environments come up lazily |
| 10 | SPEC-06 §5.2 `cancel_turn`, `usage`, `start` rows | Cancel without retry; per-session usage | Cancel retries 409 `conflict_error`. Session usage was null; per-turn usage comes from `turns.list` and is null for cancelled turns. `start` can omit `input` and send it after the stream opens. |
| 11 | SPEC-06 §9 matrix | `steer / inject` for `claude_managed` cloud `E (interrupt+msg)` | `?`: mid-turn `user.message` injection observed, native once HL-24 qualifies it |
| 12 | research/harness-in-sandbox.md Q-M1 and Q-O2 | PARTIAL: treat it as next-turn delivery; hosted build not inspectable | Answered by this note |
| 13 | research/anthropic-managed-agents.md open question 1, and research/openai-hosted-agents.md §4 (AGENTS.md) and vault path | UNVERIFIED | Answered by this note |

## 5. Still open after the smoke

- **Q-M4:** does an interrupt drop `user.message` events queued before it? Not exercised.
- **Q-O3:** does a vault placeholder work for git over HTTPS? Not exercised.
- **Q-O4:** can `spend_control` be set? It is absent from the SDK 3.29.0 `AgentSession` model.
- **Q-M2:** server-side tool-result wait (self-hosted). Not exercised.
- Whether the Anthropic skills limit is 20 per agent or 500 per session was not drilled.
- OpenAI settled cost: the API reports tokens only, and they are best-effort.
