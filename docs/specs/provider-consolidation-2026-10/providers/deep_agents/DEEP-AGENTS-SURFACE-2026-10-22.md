---

## type: Research
title: "Deep Agents surface as of 2026-10-22: deepagents 0.7.5 installed, 0.7.30 latest; middleware, subagents, state, backends, provider tools, structured output, hooks, parallelism and Temporal"
description: "Cited fact sheet (installed source, latest wheels, docs) of the Deep Agents, LangChain and LangGraph capabilities Mission Control can make selectable: the middleware catalog with hooks and graph-node effects, sync, async and dynamic (QuickJS) subagents, state and context schemas, backends, OpenAI and Anthropic built-in tools, structured output strategies, hook equivalents, parallelism and the Temporal integrations, with the upgrade risks from 0.7.5 to 0.7.30 and the implications by capability category."
tags: [mission-control, providers, deep-agents, research, middleware, subagents, upgrade, P1]

# Deep Agents surface as of 2026-10-22

Research only, read 2026-10-22 during tracing Stage 3 (Opus 5.5). This is the dated "Deep Agents
surface as of" block that [the output-contracts specification](../../../archive/provider-consolidation-2026-10/specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md)
§5 and OC-D17 require before the version bump; it supersedes the version statements of
[`deepagents-middleware.md`](../../../archive/fast-track-2026-10/research/deepagents-middleware.md) (see
"Correction to the baseline"). The interview that decides what to adopt is
[OWNER-INTERVIEW-2026-10-22.md](../../../archive/provider-consolidation-2026-10/interview-instructions/OWNER-INTERVIEW-2026-10-22.md).

## How to read this sheet

Every fact has a label and a citation.

| Label | Meaning |
| --- | --- |
| **[SRC]** | Verified by reading package source: the installed `.venv` package, or a wheel downloaded from PyPI on 2026-10-22 and unpacked without running it. |
| **[DOCS]** | Taken from docs.langchain.com, docs.temporal.io or GitHub release notes, fetched 2026-10-22. I did not check these against source. |
| **[NF]** | Not found. I looked and could not verify it. |
| **[INF]** | My inference from verified facts. Not stated anywhere. |

### Citation keys

**Installed packages (**`I:`**).** `I:` means `platform/mission-control/.venv/Lib/site-packages/<path>:<line>`. The installed versions are:

| Package | Installed version |
| --- | --- |
| deepagents | 0.7.5 |
| langchain | 1.3.14 |
| langchain-core | 1.5.3 |
| langgraph | 1.2.10 |
| langgraph-api | 0.12.0 |
| langgraph-sdk | 0.4.2 |
| langchain-openai | 1.3.4 |
| langchain-anthropic | 1.5.4 |
| langchain-quickjs | 0.3.5 |
| temporalio | 1.34.0 |

These versions come from the `pyproject.toml:18-37` pins plus the `*.dist-info` directories.

**Downloaded wheels (**`W:`**).** `W:<pkg>==<ver> <path>:<line>` points into a wheel downloaded from PyPI and unpacked in a scratch directory (not kept in the repository; the wheel URLs below reproduce it). Wheel URLs:

- deepagents 0.7.30: https://files.pythonhosted.org/packages/d3/f7/c3096934445df7030b95a93feba8f774d570d7bbfe55db8dadc8629884f8/deepagents-0.7.30-py3-none-any.whl
- langchain 1.4.7: https://files.pythonhosted.org/packages/93/2e/86a102e61fc88ede073aebdb795fef0eb058a887bed4aa862e8ca2697565/langchain-1.4.7-py3-none-any.whl
- langchain-openai 1.7.2: https://files.pythonhosted.org/packages/39/5d/8c4888a21087e4cd1c32965613a1a17cfc8e90e41ba5205c3dad302f3410/langchain_openai-1.7.2-py3-none-any.whl
- langchain-quickjs 0.3.9: https://files.pythonhosted.org/packages/9a/4f/7c846cf88b12071414a3a2e0378caf7266bb7660299e62ca2222832a735c/langchain_quickjs-0.3.9-py3-none-any.whl
- langgraph 1.2.16: https://files.pythonhosted.org/packages/ad/eb/ceb9bed99f6549e9ec51c497b749062d19e0a1c68fea0ad801d55c4a9691/langgraph-1.2.16-py3-none-any.whl

**Other sources.**

- `PyPI:` is `https://pypi.org/pypi/<pkg>/json`, read 2026-10-22.
- `GH:` is a GitHub release page.
- `D:` is a docs page. Docs are fetched as raw markdown by appending `.md` to the URL.

### Correction to the baseline

`docs/specs/archive/fast-track-2026-10/research/deepagents-middleware.md` describes **deepagents 0.7.23 and langchain 1.4.3**. Those wheels were downloaded on 2026-10-07. The repository actually **pins and installs deepagents 0.7.5, langchain 1.3.14, langchain-openai 1.3.4 and langgraph 1.2.10**:

- [SRC] `pyproject.toml:18-37` pins these versions and allows `langchain-openai>=1.1,<1.4`.
- [SRC] `I:deepagents/_version.py:21` reads `__version__ = "0.7.5"`.

Some baseline statements are therefore not true of the installed stack:

- `SubAgent.mode="fork"` does not exist in 0.7.5.
- `UnsupportedContentMiddleware` does not exist in 0.7.5.
- `langchain.mcp` does not exist in 1.3.14.

Each case is pointed out below.

---

## 1. Latest deepagents and what changed since 0.7.5

### 1.1 Versions as of 2026-10-22 (all [SRC], from the PyPI JSON)

| Package                       | Installed           | Latest                           | Latest uploaded |
| ----------------------------- | ------------------- | -------------------------------- | --------------- |
| deepagents                    | 0.7.5 (2026-08-06)  | **0.7.30**                       | 2026-10-22      |
| langchain                     | 1.3.14 (2026-07-16) | **1.4.7**                        | 2026-10-21      |
| langchain-core                | 1.5.3               | **1.7.0**                        | 2026-10-22      |
| langgraph                     | 1.2.10 (2026-07-28) | **1.2.16**                       | 2026-10-16      |
| langgraph-prebuilt            | 1.1.0               | 1.1.1                            | 2026-10-15      |
| langgraph-checkpoint          | 4.1.1               | 4.3.0                            | 2026-10-12      |
| langgraph-checkpoint-postgres | 3.1.1               | **3.2.0** (adds `prune`)         | 2026-10-14      |
| langgraph-sdk                 | 0.4.2               | 0.4.8                            | 2026-10-16      |
| langgraph-api                 | 0.12.0              | 0.16.5 (0.18.0.dev9 pre-release) | 2026-10-22      |
| langchain-openai              | 1.3.4 (2026-07-08)  | **1.7.2**                        | 2026-10-14      |
| langchain-anthropic           | 1.5.4               | 1.7.6                            | 2026-10-12      |
| langchain-quickjs             | 0.3.5 (2026-07-29)  | **0.3.9**                        | 2026-10-13      |
| langchain-mcp-adapters        | 0.3.1               | 0.3.2                            | 2026-08-06      |
| temporalio                    | 1.34.0              | 1.34.0                           | 2026-09-30      |

### 1.2 Dependency floors that an upgrade must satisfy

**deepagents 0.7.30** [SRC] (PyPI `requires_dist`) requires:

- `langchain>=1.4.6,<2`
- `langchain-core>=1.6.12,<2`
- `langchain-anthropic>=1.7.6,<2`
- `langchain-google-genai>=4.4.2,<5`
- `langsmith>=0.14.11`
- `wcmatch>=11`
- the extra `quickjs`, which pulls `langchain-quickjs>=0.3.9`

Compare deepagents 0.7.5, which requires `langchain>=1.3.14` and `langchain-core>=1.5.0` [SRC] (`I:deepagents-0.7.5.dist-info/METADATA`).

**langchain-quickjs 0.3.9** [SRC] (PyPI) requires:

- `langgraph>=1.2.15`
- `langchain>=1.4.5`
- `langchain-core>=1.6.10`
- `deepagents>=0.7.0,<0.8.0`

**langchain 1.4.7** [SRC] (`W:langchain==1.4.7 langchain-1.4.7.dist-info/METADATA`) requires:

- `langgraph>=1.2.12,<1.3.0`
- `langchain-core>=1.6.13`

**langchain-openai 1.7.2** [SRC] (`W:… METADATA`) requires `openai>=2.45.0,<4.0.0`. The 1.5.0 release added support for the openai 3.0 SDK [DOCS] (GH `langchain-openai==1.5.0`). The repository's pin `langchain-openai<1.4` must be lifted to upgrade.

**temporalio 1.34.0, extra** `deepagents` [SRC] (`I:temporalio-1.34.0.dist-info/METADATA`) requires `deepagents>=0.7,<0.8` and `langchain>=1.3.14,<2`, so it is compatible with 0.7.30.

### 1.3 Public API diff, 0.7.5 → 0.7.30

All [SRC]. I compared the installed package with the 0.7.30 wheel using `diff -r`.

`create_deep_agent` **signature: unchanged.** Both versions take:

> model, tools, \*, system_prompt, middleware, subagents, skills, memory, permissions, backend, interrupt_on, response_format, state_schema, context_schema, checkpointer, store, debug, name, cache

Sources: `I:deepagents/graph.py:268-288` and `W:deepagents==0.7.30 deepagents/graph.py:278-`.

**New top-level exports** (`W:… deepagents/middleware/__init__.py`): `TaskEvent`, `SkillMetadata`, `SkillToolResolver`, `SkillsState`, `UnsupportedContentMiddleware`.

**New modules:**

- `middleware/_parent_notifier.py`
- `middleware/_blob_offload.py`
- `middleware/_skill_tools.py`
- `middleware/unsupported_content.py`

**Changes to the default stack** (`W:… graph.py:376-403` docstring, `:917`, `:958`):

- `SkillsMiddleware` moved from the head of the stack to the tail, after user and profile middleware.
- A private `_ParentNotifierMiddleware()` is attached to every deep agent, inside the core stack.
- `UnsupportedContentMiddleware()` is appended near the end of the stack.
- For comparison, 0.7.5 put `SkillsMiddleware` first (`I:graph.py:817-819`).

`SubAgent` **changes** (`W:… middleware/subagents.py:84-228`):

- New `mode: "isolated" | "fork"` field. 0.7.12 added it, and 0.7.13 renamed `handoff` to `isolated`.
- `system_prompt` is now `NotRequired`. It was `Required` in 0.7.5 (`I:deepagents/middleware/subagents.py:92`).
- Duplicate subagent names are now rejected (`W:… subagents.py:331, 667`).

`AsyncSubAgent` **gains four fields** (`W:… async_subagents.py:117-160`): `webhook`, `update_strategy` (`interrupt | enqueue`), `notify_parent` (bool, default True) and `mode` (`isolated | fork`).

`FilesystemMiddleware` gains `offload_binary_content: bool = False` (`W:… middleware/filesystem.py:1894-1903`). Compare `I:` signature: `tools`, `_permissions`, no binary offload.

### 1.4 Changelog highlights, 0.7.6 → 0.7.30

All [DOCS]. Source: the GH release notes for each version, at https://github.com/langchain-ai/deepagents/releases/tag/deepagents%3D%3D0.7.N.

**0.7.6**

- History offload now uses a distinct session ID per summarization.

**0.7.8**

- The `files` state key is added only for state backends.

**0.7.9**

- Middleware tracing inputs are disabled.
- `excluded_tools` is now enforced at execution, not only hidden.
- Rubric criterion coverage is enforced.

**0.7.11**

- Rubric grader integration hooks.

**0.7.12**

- Subagent conversation forking (`mode="fork"`).

**0.7.13**

- Mode renamed `handoff` → `isolated`. The legacy alias is still accepted (`W:… subagents.py:323`).

**0.7.14**

- New `read_file` output format.
- Compaction recovery is bounded.
- `PatchToolCallsMiddleware` fixes.
- `edit_file` rejects an empty `old_string`.

**0.7.15**

- Subagent state keys are propagated for provided subagent middleware.

**0.7.16**

- Skills reload when `skills_metadata` is reset to `None`.
- Parallel edits to the same file are rejected.

**0.7.18**

- The `task` tool rejects unknown argument keys.
- `FileInfo.size` is now in bytes.

**0.7.19**

- Unsupported multimodal content is filtered by a separate middleware.

**0.7.21**

- `FilesystemMiddleware` can store blobs on the backend.

**0.7.22**

- A skill's tools load only when the skill is read (`metadata.include_tools`).

**0.7.23**

- `pinned_skills`.
- Each subagent uses its own `SkillsMiddleware`.

**0.7.24**

- Fork mode for async subagents.
- Recovery from context overflow during the summary call.
- Parent rubric preserved during parallel subagent calls.

**0.7.25**

- **Security fix:** permission rules and `interrupt_on` now also check symlink-resolved paths. Before this, `FilesystemBackend` followed symlinks _after_ the check.
- Sandbox grep prefers ripgrep.

**0.7.26**

- Async subagents report a `waiting` status for human input.
- Async subagent runs nest under the parent trace.
- The summarization middleware exposes its `summarizer`.

**0.7.27**

- The main agent is kept informed of async subagent status updates (notifications).
- Subagent names are passed to subagents.

**0.7.29**

- `CompositeBackend` accepts routes without a trailing slash.
- Text edits to binary files are rejected.
- In-memory grep skips binary files.

**0.7.30**

- Async follow-ups can queue (`update_strategy="enqueue"`).
- `notify_parent` and `webhook` on `AsyncSubAgent`.
- Async checks report server-cancelled runs and omit reasoning.
- Summaries drop reasoning blocks from replaced history.
- `LocalShellBackend` output limits are counted in UTF-8 bytes.

### 1.5 Upgrade risks specific to Mission Control

1. **The guard on the async tool surface.**
   - [SRC] `src/mission_control/adapters/deep_agents/async_subagents.py:167-172` builds a stock `AsyncSubAgentMiddleware`, extracts only its `.tools`, and raises `"tool surface drifted from 0.7.5"` if the tool _names_ change.
   - The names are unchanged in 0.7.30 [SRC] (`W:… async_subagents.py:852, 1048, 1203, 1306, 1427`).
   - What did change is tool behaviour and output: statuses gained `pending` and `waiting`, check results are content blocks with reasoning omitted, and update defaults to the `interrupt` strategy, with `enqueue` available [SRC] (`W:… async_subagents.py:182-237, 925-990, 1062-1210`).
   - [INF] The governed wrappers that parse these outputs need retesting.
2. **The new auto-notification hooks.**
   - In 0.7.30, `AsyncSubAgentMiddleware` gains `abefore_agent`, `abefore_model` and `aafter_model` (with `can_jump_to=["model"]`). These pull task status and **append notification** `HumanMessage`**s that carry the child's result blocks**, then give the model another turn [SRC] (`W:… async_subagents.py:1601-1660`).
   - [INF] Mission Control's `BellLabsAsyncSubagentMiddleware` is its own `AgentMiddleware` and only reuses the stock _tools_, so these hooks do not run on the parent. That keeps the "reveal only after admission" gate intact. If someone later attaches the stock middleware directly, the gate is bypassed.
3. **The child-side notifier.**
   - `_ParentNotifierMiddleware` is attached to every deep agent in 0.7.30, the Agent Server child included. In `aafter_agent` it wakes the parent by calling `runs.create` on the parent's thread [SRC] (`W:… _parent_notifier.py:30-95`, `async_subagents.py:626-659`).
   - It fires only if the run carries `configurable["deepagents_parent"]` or thread metadata `parent_thread_id`/`parent_assistant_id` [SRC] (`W:… async_subagents.py:343, 432-455`).
   - [INF] Mission Control's own `start` posts its own thread metadata (`belllabs_*`), so the notifier stays inert. Keep it that way, or set `notify_parent=False`.
4. **Subagent state propagation.**
   - In 0.7.5 the child receives **every parent state key** except `messages`, `todos`, `structured_response` and private keys. That includes `files`, custom keys and `skills_metadata` [SRC] (`I:deepagents/middleware/subagents.py:252-256, 529-540`).
   - In 0.7.30 the exclusions add `skills_metadata`, `pinned_skills`, `_skill_tools_disclosed`, `_deepagents_forked_context` and `rubric`. Keys returned unchanged are also dropped from the update [SRC] (`W:… subagents.py:404-452`).
5. **The repository relies on private deepagents APIs that may move between releases:**
   - `deepagents.profiles.harness.harness_profiles._harness_profile_for_model` [SRC] (`src/mission_control/adapters/deep_agents/adapter.py:24`)
   - `deepagents_async.get_client` [SRC] (`async_subagents.py:184`)
   - `create_summarization_middleware` [SRC] (`compaction.py:43`, `hooks.py:37`)
6. **deepagents is still pre-1.0.** `model=None` is deprecated, to be removed in 1.0, and `BASE_AGENT_PROMPT` is deprecated, to be removed in 0.9.0 [SRC] (`I:graph.py:121-137, 151-179`).

---

## 2. Middleware catalog

### 2.1 How hooks become graph nodes

- [SRC] `create_agent` adds a graph node for each _node-style_ hook a middleware overrides: `"{name}.before_agent"`, `"{name}.before_model"`, `"{name}.after_model"` and `"{name}.after_agent"` (`I:langchain/agents/factory.py:1502-1592`).
- [SRC] `wrap_model_call` and `wrap_tool_call` add no nodes. They wrap the `model` and `tools` nodes, with the first middleware outermost [DOCS] (`D:https://docs.langchain.com/oss/python/langchain/middleware/custom`).
- [SRC] Base hooks: `before_agent`, `before_model`, `after_model`, `after_agent`, `wrap_model_call` and `wrap_tool_call`, each with an `a*` async twin (`I:langchain/agents/middleware/types.py:419-744`).
- [SRC] Class attributes: `state_schema` and `tools`. `trace_policy` is new in langchain 1.4.x (`W:langchain==1.4.7 …/middleware/__init__.py`, exports `TracePolicy`, `configure_trace_policy`, `omit_payload`).

In the tables below:

- **Hooks** lists the hooks the class overrides. I found these by introspecting the installed classes against `AgentMiddleware`. All [SRC].
- **Nodes?** says whether the middleware adds graph nodes.

### 2.2 `langchain.agents.middleware` (installed 1.3.14)

The 1.4.7 export list is the same plus `PIIMatch`, `TracePolicy`, `configure_trace_policy` and `omit_payload` [SRC] (diff of `__init__.py`). Signatures come from `I:langchain/agents/middleware/*.py`.

| Middleware                            | What it does                                                                                                  | Knobs                                                                                                                                                                                                             | Hooks                            | Nodes?            |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- | ----------------- |
| `TodoListMiddleware`                  | Adds the `write_todos` tool and a planning prompt. State `todos`.                                             | `system_prompt`, `tool_description`                                                                                                                                                                               | `wrap_model_call`, `after_model` | yes (after_model) |
| `SummarizationMiddleware` (langchain) | Summarizes old messages by rewriting `messages`.                                                              | `model`, `trigger` (`("fraction"/"tokens"/"messages", n)`, a `TriggerClause` dict meaning AND, or a list meaning OR), `keep=("messages",20)`, `token_counter`, `summary_prompt`, `trim_tokens_to_summarize=4000`  | `before_model`                   | yes               |
| `HumanInTheLoopMiddleware`            | Interrupts before the listed tool calls.                                                                      | `interrupt_on: {tool: bool \| InterruptOnConfig{allowed_decisions, description, args_schema, when}}`, `description_prefix`. Decisions are `approve`/`edit`/`reject`/`respond` (`human_in_the_loop.py:51`).        | `after_model`                    | yes               |
| `ModelCallLimitMiddleware`            | Caps model calls. State `thread_model_call_count`, `run_model_call_count`.                                    | `thread_limit`, `run_limit`, `exit_behavior: end\|error`                                                                                                                                                          | `before_model`, `after_model`    | yes               |
| `ToolCallLimitMiddleware`             | Caps tool calls, globally or per tool.                                                                        | `tool_name`, `thread_limit`, `run_limit`, `exit_behavior: continue\|error\|end`                                                                                                                                   | `after_model`                    | yes               |
| `ModelFallbackMiddleware`             | Tries alternative models on failure.                                                                          | `(first_model, *additional_models)`                                                                                                                                                                               | `wrap_model_call`                | no                |
| `ModelRetryMiddleware`                | Retries model calls with backoff.                                                                             | `max_retries=2`, `retry_on`, `on_failure`, `backoff_factor`, `initial_delay`, `max_delay`, `jitter`                                                                                                               | `wrap_model_call`                | no                |
| `ToolRetryMiddleware`                 | Retries tool calls with backoff.                                                                              | the same, plus `tools`                                                                                                                                                                                            | `wrap_tool_call`                 | no                |
| `ToolErrorMiddleware`                 | Turns selected tool exceptions into an error `ToolMessage` (opt-in).                                          | `on_error`, `aon_error`, `tools`                                                                                                                                                                                  | `wrap_tool_call`                 | no                |
| `PIIMiddleware`                       | Detects PII and blocks, redacts, masks or hashes it.                                                          | `pii_type` (`email`/`credit_card`/`ip`/`mac_address`/`url`/custom), `strategy`, `detector`, `apply_to_input/output/tool_results`                                                                                  | `before_model`, `after_model`    | yes               |
| `ContextEditingMiddleware`            | Clears old tool uses when over a token budget.                                                                | `edits` (`ClearToolUsesEdit(trigger, clear_at_least, keep, clear_tool_inputs, exclude_tools, placeholder)`), `token_count_method`                                                                                 | `wrap_model_call`                | no                |
| `LLMToolSelectorMiddleware`           | Uses an LLM to pick relevant tools before the main call.                                                      | `model`, `system_prompt`, `max_tools`, `always_include`                                                                                                                                                           | `wrap_model_call`                | no                |
| `ProviderToolSearchMiddleware`        | Defers tools behind provider-native tool search. Anthropic and OpenAI only (`provider_tool_search.py:57-90`). | `searchable_tools`                                                                                                                                                                                                | `wrap_model_call`                | no                |
| `ShellToolMiddleware`                 | Persistent shell tool.                                                                                        | `workspace_root`, `startup/shutdown_commands`, `execution_policy` (`HostExecutionPolicy`\|`DockerExecutionPolicy`\|`CodexSandboxExecutionPolicy`), `redaction_rules`, `tool_name="shell"`, `shell_command`, `env` | `before_agent`, `after_agent`    | yes               |
| `FilesystemFileSearchMiddleware`      | Glob and grep over a real directory.                                                                          | `root_path`, `use_ripgrep=True`, `max_file_size_mb`                                                                                                                                                               | none (tools only)                | no                |
| `LLMToolEmulator`                     | Emulates tools with an LLM, for tests.                                                                        | `tools`, `model`                                                                                                                                                                                                  | `wrap_tool_call`                 | no                |
| Decorators                            | Function-style hooks.                                                                                         | `before_agent`, `before_model`, `after_model`, `after_agent`, `wrap_model_call`, `wrap_tool_call`, `dynamic_prompt`, `hook_config(can_jump_to=…)`                                                                 | n/a                              | n/a               |

[DOCS] The docs' prebuilt list matches this table and also lists the deepagents Filesystem, Subagent and Rubric middleware (`D:https://docs.langchain.com/oss/python/langchain/middleware/built-in`, lines 15-39).

### 2.3 Deep Agents middleware

Installed version is 0.7.5. Differences in 0.7.30 are noted inline.

| Middleware                                                                   | What it does                                                                                                                                                                                                                                          | Knobs                                                                                                                                                                                                                                                                                                                                                          | Hooks                                                                                                                                | Nodes?                            |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------- | ---------- | --- | --- |
| `FilesystemMiddleware`                                                       | `ls`, `read_file`, `write_file`, `edit_file`, `delete`, `glob`, `grep`, `execute`. `execute` is hidden when the backend is not a sandbox. Large tool results and human messages are evicted to files. Enforces `FilesystemPermission`. State `files`. | `backend`, `system_prompt`, `custom_tool_descriptions`, `tool_token_limit_before_evict=20000`, `human_message_token_limit_before_evict=50000`, `max_execute_timeout=3600`, `grep_max_count=1000`, `tools`, and `offload_binary_content` (0.7.30 only)                                                                                                          | `wrap_model_call`, `wrap_tool_call`                                                                                                  | no                                |
| `SubAgentMiddleware`                                                         | Sync `task` tool. See §3.                                                                                                                                                                                                                             | `backend`, `subOkaagents`, `system_prompt`, `task_description`, `private_state_keys`, `state_schema`                                                                                                                                                                                                                                                           | `wrap_model_call`                                                                                                                    | no                                |
| `AsyncSubAgentMiddleware`                                                    | Five async-task tools. State `async_tasks`. See §3.                                                                                                                                                                                                   | `async_subagents`, `system_prompt`                                                                                                                                                                                                                                                                                                                             | 0.7.5: `wrap_model_call`. **0.7.30 adds** `before_agent`**,** `before_model`**,** `after_model` **(async only, can jump to model).** | 0.7.5 no, 0.7.30 yes              |
| `SummarizationMiddleware` (deepagents, `_DeepAgentsSummarizationMiddleware`) | Compacts by recording `_summarization_event` and offloading history to `/conversation_history/{id}.md`. Does not rewrite `messages`. Retries on `ContextOverflowError`.                                                                               | `model`, `backend`, `trigger`, `keep`, `token_counter`, `summary_prompt`, `trim_tokens_to_summarize`, `truncate_args_settings{trigger, keep, max_length, truncation_text}`. 0.7.26 adds a `summarizer` replacement. Defaults: `("fraction",0.85)`/`("fraction",0.10)` when the profile has `max_input_tokens`, otherwise `("tokens",170000)`/`("messages",6)`. | `wrap_model_call`                                                                                                                    | no                                |
| `SummarizationToolMiddleware`                                                | Adds the `compact_conversation` tool, so the model can compact on demand.                                                                                                                                                                             | `summarization`, `system_prompt`                                                                                                                                                                                                                                                                                                                               | `wrap_model_call`                                                                                                                    | no                                |
| `PatchToolCallsMiddleware`                                                   | Adds `ToolMessage`s for dangling tool calls on resume or fork.                                                                                                                                                                                        | none                                                                                                                                                                                                                                                                                                                                                           | `before_agent`                                                                                                                       | yes                               |
| `SkillsMiddleware`                                                           | Progressive-disclosure skills: `SKILL.md` frontmatter goes into the prompt, and the body is read on demand. State `skills_metadata`, `skills_load_errors`. 0.7.22+ discloses `metadata.include_tools` after a read. 0.7.23+ adds `pinned_skills`.     | `backend`, `sources`, `system_prompt`, and `tools` (0.7.30: `Sequence[BaseTool]                                                                                                                                                                                                                                                                                | SkillToolResolver`)                                                                                                                  | `before_agent`, `wrap_model_call` | yes        |
| `MemoryMiddleware`                                                           | Loads `AGENTS.md` files into the system prompt. State `memory_contents`.                                                                                                                                                                              | `backend`, `sources`, `add_cache_control`, `system_prompt`                                                                                                                                                                                                                                                                                                     | `before_agent`, `wrap_model_call`                                                                                                    | yes                               |
| `RubricMiddleware`                                                           | LLM-as-judge iteration. Active only when invocation state carries `rubric`.                                                                                                                                                                           | `model`, `system_prompt`, `tools`, `max_iterations=3`, `on_evaluation`                                                                                                                                                                                                                                                                                         | `before_agent`, `after_agent`                                                                                                        | yes                               |
| `UnsupportedContentMiddleware` (0.7.19+, absent in 0.7.5)                    | Replaces input blocks the model cannot accept with a text notice.                                                                                                                                                                                     | none                                                                                                                                                                                                                                                                                                                                                           | `wrap_model_call`                                                                                                                    | no                                |
| `_ParentNotifierMiddleware` (0.7.27+, private)                               | When a deep agent run started by `start_async_task` ends or fails, wakes the launching agent.                                                                                                                                                         | none                                                                                                                                                                                                                                                                                                                                                           | `after_agent`, `wrap_model_call` (async path only)                                                                                   | yes                               |
| `_ToolExclusionMiddleware` (private)                                         | Removes the harness profile's `excluded_tools`.                                                                                                                                                                                                       | `excluded`                                                                                                                                                                                                                                                                                                                                                     | `wrap_model_call`                                                                                                                    | no                                |
| `FilesystemPermission` (data class, not middleware)                          | Permission rule. The first matching rule wins. `interrupt` auto-installs HITL.                                                                                                                                                                        | `operations: [read                                                                                                                                                                                                                                                                                                                                             | write]`, `paths`, `mode: allow                                                                                                       | deny                              | interrupt` | n/a | n/a |

Citations for the table above:

- [SRC] Signatures, hooks and state keys: introspection of `I:deepagents/middleware/__init__.py` exports.
- [SRC] Summarization defaults: `I:deepagents/middleware/summarization.py:258-281`.
- [SRC] Overflow retry: `I:deepagents/middleware/summarization.py:1339-1382`.
- [SRC] Rubric: `I:deepagents/middleware/rubric.py:439-522`.
- [SRC] 0.7.30 lines: `W:deepagents==0.7.30 middleware/async_subagents.py:1601-1660`, `_parent_notifier.py:30-95`, `unsupported_content.py:109-121`, `skills.py:353-360, 1028-1035`.

### 2.4 The default `create_deep_agent` stack

**0.7.5** [SRC] (`I:deepagents/graph.py:816-893`), in order:

1. `SkillsMiddleware` (if `skills`)
2. `FilesystemMiddleware`
3. `SubAgentMiddleware` (if there are any sync subagents, including the auto general-purpose one)
4. `SummarizationMiddleware`
5. `PatchToolCallsMiddleware`
6. `AsyncSubAgentMiddleware` (if there are async subagents)
7. **user** `middleware`
8. profile `extra_middleware`
9. `AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")`, plus the Bedrock/Fireworks variants when installed
10. `MemoryMiddleware` (if `memory`)
11. `HumanInTheLoopMiddleware` (if `interrupt_on` or interrupt-mode permissions)
12. `_ToolExclusionMiddleware`

Rules that apply to this stack:

- A user middleware whose `.name` matches a built-in replaces it in place (`graph.py:201-235`).
- `FilesystemMiddleware` and `SubAgentMiddleware` cannot be excluded (`graph.py:238-265`).

**0.7.30** [SRC] (`W:… graph.py:376-403`, `917`, `958`), in order:

1. `FilesystemMiddleware`
2. `SubAgentMiddleware`
3. `SummarizationMiddleware`
4. `PatchToolCallsMiddleware`
5. `_ParentNotifierMiddleware`
6. `AsyncSubAgentMiddleware`
7. user middleware
8. profile middleware
9. `SkillsMiddleware`
10. prompt caching
11. `MemoryMiddleware`
12. `HumanInTheLoopMiddleware`
13. `UnsupportedContentMiddleware`
14. `_ToolExclusionMiddleware`

`TodoListMiddleware` **is not in the default stack in either version.**

- [SRC] It is added only by the OpenAI Codex harness profile, for `openai:gpt-5.1/5.2/5.3-codex` (`I:deepagents/profiles/harness/_openai_codex.py:27-31, 66-88`).
- To use it, pass `TodoListMiddleware()` in `middleware=`.

### 2.5 Provider-specific middleware

**langchain-anthropic 1.5.4, installed** [SRC] (`I:langchain_anthropic/middleware/__init__.py`):

- `AnthropicPromptCachingMiddleware(type="ephemeral", ttl="5m"|"1h", min_messages_to_cache=0, unsupported_model_behavior)`. Hook: `wrap_model_call`.
- `ClaudeBashToolMiddleware`, which subclasses `ShellToolMiddleware`.
- `StateClaudeTextEditorMiddleware` and `FilesystemClaudeTextEditorMiddleware`.
- `StateClaudeMemoryMiddleware` and `FilesystemClaudeMemoryMiddleware`. These are the Claude `memory` tool, implemented client-side.
- `StateFileSearchMiddleware`.

**langchain-openai 1.3.4, installed** [SRC]:

- `OpenAIModerationMiddleware(model="omni-moderation-latest", check_input, check_output, check_tool_results, exit_behavior: error|end|replace)`. Hooks: `before_model`, `after_model`.

**langchain-openai 1.7.2, latest** [SRC] (`W:langchain_openai==1.7.2 middleware/__init__.py`) adds:

- `OpenAIAutoModeMiddleware(tools, model, instructions)`: classifies tool calls for risk through the OpenAI Decisions API and blocks calls with a probability of 0.5 or higher (`auto_mode.py:65-123`).
- `OpenAIModelRouterMiddleware`, with `ModelChoice` and `ModelRoute`: routes the run's model through a Decisions `Choice` call and stores `model_route` in state (`model_router.py:45-90`). Beta.

### 2.6 Interpreter middleware (`langchain_quickjs.CodeInterpreterMiddleware`)

[SRC] `I:langchain_quickjs/middleware.py:121-263`.

**Knobs (0.3.5):**

| Knob                 | Default                                          |
| -------------------- | ------------------------------------------------ |
| `memory_limit`       | 64 MiB                                           |
| `timeout`            | 5 s per eval                                     |
| `max_ptc_calls`      | 256                                              |
| `tool_name`          | `"eval"`                                         |
| `max_result_chars`   | 4000                                             |
| `capture_console`    | True                                             |
| `subagents`          | True                                             |
| `ptc`                | None (an allowlist of tool names or `BaseTool`s) |
| `mode`               | `thread` (alternatives: `turn`, `call`)          |
| `max_snapshot_bytes` | `memory_limit`                                   |

- **Hooks:** `before_agent` restores the snapshot, `wrap_model_call` injects the prompt and installs the PTC bridges, and `after_agent` writes the snapshot and evicts.
- **State:** `_quickjs_snapshot_payload`, a private `DeltaChannel` (`:58-67`).
- **Marked** `@beta()` (`:120`).
- **0.3.9 adds** `max_subagent_concurrency` (default 32) and `snapshot_signing_key` (HMAC over the snapshot) [SRC] (`W:langchain_quickjs==0.3.9 middleware.py:233-248`, `_snapshot.py:27-89`). The HMAC check itself arrived in 0.3.6 [DOCS] (GH `langchain-quickjs==0.3.6`).

---

## 3. Subagents

### 3.1 Sync subagents: the `task` tool

**Spec types (0.7.5)** [SRC] (`I:deepagents/middleware/subagents.py:36-244`):

- `SubAgent{name, description, system_prompt, tools?, model?, middleware?, interrupt_on?, skills?, permissions?, response_format?}`.
- `CompiledSubAgent{name, description, runnable}`. The runnable's state must contain `messages`.
- 0.7.30 adds `mode` to both, and `system_prompt` becomes optional [SRC] (`W:… subagents.py:212-219, 309`).

**Tool schema** [SRC] (`I:subagents.py:272-282`):

- `task(description: str, subagent_type: str)`.
- Rejects unknown keys from 0.7.18 [DOCS] (GH 0.7.18).
- The tool description tells the model to "launch multiple agents concurrently … using a single message with multiple tool calls" (`:285-296`).

**Inheritance from the parent** [SRC] (`I:graph.py:656-743`):

- **Model:** inherited if `model` is omitted.
- **Tools:** the parent's tools are inherited if the `tools` key is absent. This includes dict provider tools (`:726-728`).
- **Permissions:** inherited unless overridden. An override _replaces_ the parent's rules.
- `interrupt_on`**:** inherited unless overridden.
- **Middleware:** each child gets its own `FilesystemMiddleware`, summarization, `PatchToolCalls`, skills when `skills` is set, profile middleware and prompt caching, followed by `spec.middleware`.
- **What is not inherited:**
  - `CompiledSubAgent` inherits neither `interrupt_on` nor `state_schema` (`graph.py:498-530`).
  - **Runtime context propagates to all subagents** [DOCS] (`D:https://docs.langchain.com/oss/python/deepagents/subagents`, "Context management", lines 2087-2091).
  - [SRC] The parent's callbacks, tags, configurable and metadata reach the child through LangGraph's `ensure_config` merge (`I:subagents.py:558-567`).

**State passed to the child** [SRC]:

| Version | Keys excluded from the child's input                                                                                                                                                                        | Citation                          |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| 0.7.5   | `messages`, `todos`, `structured_response`, private keys. `messages` is replaced by `[HumanMessage(description)]`. Everything else passes in: `files`, custom state keys, `async_tasks`, `skills_metadata`. | `I:subagents.py:252-256, 529-540` |
| 0.7.30  | Additionally `skills_metadata`, `pinned_skills`, skill-disclosure keys, forked-context key and `rubric`.                                                                                                    | `W:… subagents.py:404-436`        |

**What** `task` **returns** [SRC] (`I:subagents.py:474-512`):

- A `Command(update={**child_state_minus_excluded, "messages": [ToolMessage(content)]})`. So `files` and custom keys written by the child merge back into the parent through their reducers.
- `content` is the JSON of `structured_response` if one is set. Otherwise it is the last non-empty `AIMessage` text.
- In 0.7.30, keys the child returns unchanged are dropped from the update (`W:… subagents.py:438-452`).

**Per-subagent structured output.** Yes, supported:

- `SubAgent.response_format` accepts `ToolStrategy`, `ProviderStrategy`, `AutoStrategy`, a type or a JSON-schema dict [SRC] (`I:subagents.py:127-164`).
- A per-call dynamic format arrives through `configurable["__deepagents_subagent_response_format"]`, which recompiles the child [SRC] (`:32, 388-399, 514-527`). The QuickJS `responseSchema` uses this (§3.3).
- `CompiledSubAgent` cannot take a dynamic schema (`:429-432`).

**Fork mode (0.7.12+, experimental).**

- The child gets the parent's effective conversation and state, and mirrors the parent's prompt middleware.
- It cannot set `skills`.
- Its `system_prompt` is appended to the parent's.
- **It cannot use** `task`**.**
- Sources: [SRC] `W:… subagents.py:84-228, 320-329`; [DOCS] `D:…/deepagents/subagents`, lines 550-563.
- Not available in the installed 0.7.5.

**General-purpose child.** Auto-added unless the harness profile sets `GeneralPurposeSubagentProfile(enabled=False)`. It gets all of the parent's tools and the parent's model [SRC] (`I:graph.py:745-814`).

**Checkpointing.** [DOCS] Children run as nested graphs inside the `tools` task. Streaming namespaces look like `tools:<pregel_task_id>` (baseline, `D:…/deepagents/streaming`). [INF] They use the parent's checkpointer.

### 3.2 Async subagents (Agent Protocol / Agent Server)

**Spec, 0.7.5** [SRC] (`I:deepagents/middleware/async_subagents.py:34-70`):

- `AsyncSubAgent{name, description, graph_id, url?, headers?}`.
- Omitting `url` gives in-process ASGI transport, and the docs say this works only on the async path [DOCS].

**Spec, 0.7.30 adds** [SRC] (`W:… async_subagents.py:95-160`): `webhook`, `update_strategy`, `notify_parent` and `mode`.

**Tools (unchanged names):**

| Tool                                           | Behaviour in 0.7.5 [SRC]                                                                                                                                             | Citation      |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| `start_async_task(description, subagent_type)` | `threads.create()`, then `runs.create(thread_id, assistant_id=graph_id, input={"messages":[{"role":"user","content":description}]})`. Returns `task_id = thread_id`. | `I:…:238-330` |
| `check_async_task(task_id)`                    | `runs.get`. On `success`, `threads.get`, and returns the last message.                                                                                               | `I:…:400-466` |
| `update_async_task(task_id, message)`          | A new run on the same thread with `multitask_strategy="interrupt"`. The child sees the full history plus the new message.                                            | `I:…:469-570` |
| `cancel_async_task(task_id)`                   | `runs.cancel`, then marks the task `cancelled`.                                                                                                                      | `I:…:573-650` |
| `list_async_tasks(status_filter)`              | Reads `async_tasks` and fetches live status for tasks that are not terminal.                                                                                         | `I:…:722-805` |

**State.** `async_tasks: dict[task_id, AsyncTask{task_id, agent_name, thread_id, run_id, status, created_at, last_checked_at, last_updated_at}]`, with a merge reducer [SRC] (`I:…:73-128`). 0.7.30 adds `superseded_run_ids` [SRC] (`W:…:182-237`).

**Two-way communication.**

- **0.7.5:** pull only. The parent polls with check and list, and pushes with update and cancel. No push from the child [SRC] (as above).
- **0.7.26/0.7.27+ (beta):** on an Agent Server, the supervisor "learns when a task finishes, fails, or needs input" in three ways:
  1. before each model call (`abefore_model`);
  2. after its final answer (`aafter_model`, then a jump back to the model);
  3. through a new run on the parent's thread when a co-deployed child ends while the parent is idle (`_awake_parent`, using `multitask_strategy="reject"`).
- Notifications are `HumanMessage`s with `additional_kwargs["deepagents_notification"] = TaskEvent{task_id, agent_name, status: success|error|timeout|cancelled|waiting, run_id}`.
- Sources: [SRC] `W:… async_subagents.py:458-660, 1601-1660`; [DOCS] `D:https://docs.langchain.com/oss/python/deepagents/async-subagents` ("requires `deepagents>=0.7.26`… beta").
- `waiting`**:** a child paused on `interrupt()` is reported as `waiting`. The supervisor cannot answer it. The application resumes it on the child thread with `runs.create(task_id, graph_id, command={"resume": …})` [DOCS] (same page).
- **Context and trace forwarding (0.7.26+):**
  - Children on the same deployment receive the parent's runtime `context` [SRC] (`W:…:404-430`).
  - Remote children (with `url`) receive no context [SRC] (docstring `:86-92`).
  - Thread metadata carries `subagent_name`, `parent_thread_id` and `parent_assistant_id` [SRC] (`:387-402`).

**Concurrency.**

- [DOCS] There is no deepagents-level limit.
- On `langgraph dev`, each active run takes a worker slot, so use `--n-jobs-per-worker` (`D:…/async-subagents`, "Size the worker pool").
- [NF] I found no concurrency cap in the deepagents source.

### 3.3 Dynamic subagents (QuickJS `task()`)

**Name and dependency.**

- The feature is `CodeInterpreterMiddleware` from `langchain-quickjs`, with its default `subagents=True` [SRC] (`I:langchain_quickjs/middleware.py:121-263`).
- The docs page "Dynamic subagents" says it requires `langchain-quickjs>=0.2.0` and Python 3.11+, and is beta [DOCS] (`D:https://docs.langchain.com/oss/python/deepagents/dynamic-subagents`).

**How it works.**

- The model calls the `eval` tool with JavaScript.
- When the agent has a Deep Agents `task` tool, the REPL exposes a global `task({description, subagentType, responseSchema?, label?})`. It returns a Promise that resolves to the child's result.
- The bridge finds the `task` tool by its `{description, subagent_type}` schema [SRC] (`I:langchain_quickjs/_subagent.py:46-155`).
- `responseSchema` is validated (at most 4096 bytes, depth 5, 32 properties) and passed as `AutoStrategy` through the dynamic response-format configurable key [SRC] (`_subagent.py:33-40, 156-222`).

**What the model writes.**

- Loops, `Promise.all` fan-out, filters between stages, results returned as the last expression.
- The prompt treats the word "workflow" as a trigger [SRC] (`I:langchain_quickjs/_prompt.py:150-260`); [DOCS] (same page).

**Streaming.** Lifecycle events `SubagentStartEvent`, `SubagentCompleteEvent` and `SubagentErrorEvent` (`type: "subagent"`) are emitted on the `custom` stream [SRC] (`_subagent.py:54-120`).

**Sandboxing.**

- QuickJS with no filesystem, network, shell or clock access [SRC] (`EvalSchema`, `middleware.py:70-77`); [DOCS] (`D:…/deepagents/interpreters`, lines 163-170, 514-529).
- Defaults: 64 MiB, 5 s, 256 PTC calls.
- **Warnings:**
  - `task()` dispatches and PTC tool calls bypass parent `interrupt_on`/HITL per call [SRC] (`middleware.py:150-180` docstrings); [DOCS] (dynamic-subagents line 1266).
  - The docs say to treat QuickJS as "a scoped interpreter runtime, not a full production sandbox backend".

**Concurrency.** `max_subagent_concurrency` (default 32 per REPL) exists only in 0.3.9 [DOCS] (GH `langchain-quickjs==0.3.9`); [SRC] (`W:…:243`). Installed 0.3.5 has no cap [NF].

**Persistence.**

- `mode="thread"` snapshots REPL state into graph state after each turn, so it is checkpointed.
- Functions do not survive a restore.
- PTC side effects are not undone.
- Sources: [DOCS] `D:…/interpreters`, lines 305-324; [SRC] `middleware.py:343-540`.

---

## 4. State, context and schemas

**Custom state on** `create_agent` [SRC]:

- `create_agent(..., state_schema: type[AgentState] | None, context_schema: type | None, ...)` (`I:langchain/agents/factory.py:808-827`).
- The base `AgentState` has `messages` (with an `add_messages` reducer), `jump_to` (ephemeral and private) and `structured_response` (`OmitFromInput`) (`I:…/middleware/types.py:347-352`).
- Input and output graph schemas are `InputAgentState` and `OutputAgentState`. Fields are hidden with `OmitFromInput`, `OmitFromOutput` or `PrivateStateAttr` annotations (`types.py:327-379`).
- Reducers use standard `Annotated[T, reducer]` syntax. Example: `async_tasks: Annotated[NotRequired[dict], _tasks_reducer]` (`I:deepagents/middleware/async_subagents.py:115-128`).

**Custom state on** `create_deep_agent` [SRC]:

- `state_schema` must subclass `DeepAgentState`, which wraps `messages` in a `DeltaChannel(snapshot_frequency=50)` to cut checkpoint growth.
- The schema is forwarded to declarative `SubAgent`s, so subagents see the same custom fields.
- It is not forwarded to `CompiledSubAgent` or to async subagents.
- Sources: `I:deepagents/graph.py:70-73, 508-542, 838, 894-896, 934`.

**Middleware-declared state** [SRC]:

- A middleware declares fields with a class attribute, e.g. `state_schema = ModelCallLimitState`.
- `create_agent` merges every middleware's schema.
- Decorator hooks accept `state_schema=` (`I:types.py:395, 931-944`).
- deepagents computes the private keys across all schemas and strips them from subagent I/O (`I:graph.py:894-898`).

**Reading and writing state and context from middleware** [SRC]:

- Node hooks receive `(state, runtime: Runtime[ContextT])` and return a state-update dict, optionally with `jump_to`.
- `ModelRequest` exposes `state`, `runtime` (so `request.runtime.context` works), `model`, `messages`, `system_message`, `tools`, `tool_choice`, `response_format` and `model_settings`. Modify it with `request.override(...)` (`I:types.py:86-130`).
- Wrap hooks write state by returning `ExtendedModelResponse(command=Command(update=…))`.
- `ToolCallRequest` exposes `tool_call`, `tool`, `state` and `runtime` (a `ToolRuntime`).
- `ToolRuntime` fields: `state`, `context`, `config`, `stream_writer`, `tool_call_id`, `store`, `tools`, `execution_info`, `server_info`.
- `Runtime` attributes: `context`, `store`, `stream_writer`, `execution_info`, `server_info`, `heartbeat`, `control`, `drain_requested`, `previous` (introspected from `I:langgraph/runtime`, `langchain.tools.ToolRuntime`).

**Subagents and custom keys** [SRC]:

- Declarative children share the parent's `state_schema`.
- At call time they receive every non-excluded parent key and return their changes through the `Command` update (§3.1).
- Async children receive only messages, plus context when co-deployed in 0.7.30.

**Runtime context for subagents** [DOCS]: it flows automatically (`D:…/deepagents/subagents`, line 2089).

---

## 5. Backends

**Exports, 0.7.5** [SRC] (`I:deepagents/backends/__init__.py`):

- `StateBackend()`
- `FilesystemBackend(root_dir, virtual_mode=True, max_file_size_mb=10)`
- `LocalShellBackend(root_dir, *, virtual_mode=True, timeout=120, max_output_bytes=100000, env, inherit_env=False)`
- `StoreBackend(*, namespace: Callable[[Runtime], tuple[str,...]], store=None)`
- `CompositeBackend(default, routes, *, artifacts_root="/")`
- `LangSmithSandbox(sandbox)`
- `ContextHubBackend(identifier, *, client)`

Separately, `SandboxBackendProtocol` and `BaseSandbox` live in `protocol.py` and `sandbox.py`. All signatures are introspected.

**Protocol.**

- `BackendProtocol`: `ls`, `read`, `grep`, `glob`, `write`, `edit`, `delete`, `upload_files`, `download_files`, each with an async twin.
- `SandboxBackendProtocol` adds `id` and `execute(command, timeout)`.
- `BaseSandbox` builds the file operations on top of `execute` [SRC] (`W:… backends/protocol.py:404, 886`); [DOCS] (`D:…/deepagents/sandboxes`, "The `execute` method").
- Mission Control already has a `BaseSandbox` subclass in `adapters/deep_agents/docker_sandbox.py:11-16` [SRC].

**Interaction with checkpointing** [DOCS] (`D:https://docs.langchain.com/oss/python/deepagents/backends`):

| Backend            | Scope and persistence                                                                                                  |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| `StateBackend`     | Thread-scoped. Files live in graph state and persist across turns through the checkpointer (lines 40, 186).            |
| `StoreBackend`     | Cross-thread, through LangGraph `BaseStore`. Namespace factories can be per user, assistant or thread (lines 456-610). |
| `CompositeBackend` | Routes by prefix, typically `/memories/` → Store (lines 735-902).                                                      |
| Internal artifacts | Offloaded tool results and history go to the _default_ backend (line 902).                                             |
| Binary offload     | Opt-in. Earlier checkpoints still hold the original payload (lines 904-922).                                           |
| Sandboxes          | State is external to checkpoints. Scope is thread or assistant (`D:…/sandboxes`, lines 326-554).                       |

**Sandbox providers** [DOCS] (`D:https://docs.langchain.com/oss/python/integrations/sandboxes/index`):

- `DaytonaSandbox`
- `ModalSandbox`
- `AgentCoreSandbox` (AWS)
- `RunloopSandbox`
- `E2BSandbox`
- `VercelSandbox`
- `OpenSandboxBackend`
- `OpsenSandbox`
- `RuntimeSandbox`
- `KubernetesSandbox`
- `NonoSandbox`
- `OpenShellSandbox` (NVIDIA)
- `IsloSandbox`
- `BaponiSandbox`
- `UpstashBoxSandbox`
- `Leap0Sandbox`
- `NovitaSandbox`
- `SuperserveSandbox`
- LangSmith sandbox
- `LizardSandbox`

**Community filesystem backends** [DOCS] (`D:…/integrations/backends/index`): Azure Blob and MongoDB VFS.

**Seeding and retrieval.** `upload_files` and `download_files` use provider-native transfer, separate from the agent's tool plane [DOCS] (`D:…/sandboxes`, lines 1259-1300).

**Policy hooks.** Subclass or wrap a backend for audit, rate limits or deny rules [DOCS] (`D:…/backends`, lines 1020-1080).

**Isolation caveats.** Sandboxes do not protect against context injection or network exfiltration unless the provider blocks the network [DOCS] (`D:…/sandboxes`, lines 1022-1031).

**Temporal-durable backends.** `temporalio.contrib.deepagents.TemporalBackend(FilesystemBackend|LocalShellBackend|StoreBackend)` turns built-in file and shell operations into `deepagents.backend_op` Activities [SRC] (`I:temporalio/contrib/deepagents/README.md`, "Durable file and shell backends").

---

## 6. Provider-specific tools

### 6.1 OpenAI built-in tools (langchain-openai)

**Binding.**

- Pass a dict tool, e.g. `model.bind_tools([{"type": "web_search"}])`, or pass it as an invoke param.
- Any dict whose `type` is not `function` is treated as built-in and **routes the call to the Responses API** [SRC] (`I:langchain_openai/chat_models/base.py:4119-4133`).
- Known types in 1.3.4 and 1.7.2: `file_search`, `web_search_preview`, `web_search`, `computer_use_preview`, `code_interpreter`, `mcp`, `image_generation`, `tool_search`, `apply_patch` [SRC] (`I:…base.py:185-195`; `W:langchain_openai==1.7.2 …base.py:204-212`).

**Inside** `create_agent` **and** `create_deep_agent`**.**

- `create_agent` splits dict tools out as `built_in_tools`. They are sent to the model but **are not placed in the** `ToolNode` [SRC] (`I:langchain/agents/factory.py:1051-1077, 1936`).
- `create_deep_agent` accepts dict tools (`I:graph.py:270`) and passes them to sync children that inherit tools (`:728, 794`).
- [DOCS] The tool-search example uses `create_agent(tools=[…, {"type":"tool_search"}])` (`D:https://docs.langchain.com/oss/python/integrations/chat/openai`, lines 755-790).
- [INF] Server-side calls never pass through `wrap_tool_call`, `ToolCallLimitMiddleware`, HITL or `ToolRetry`, because they are not in `AIMessage.tool_calls` or the `ToolNode`.
- **Client-executed exceptions:** `apply_patch` (the app applies the diff and returns `apply_patch_call_output`) and computer use (a `computer_call_output` reply) need app code [DOCS] (lines 1042-1070, 1248-1320).
- `deepagents.profiles.provider._openai` sets `use_responses_api=True` for `openai:` models [SRC] (`I:deepagents/profiles/provider/_openai.py:4, 23`).

**Outputs in messages.**

- `output_version` defaults to `"responses/v1"` since langchain-openai 1.0 [SRC] (`I:base.py:1053-1071`).
- Output items `reasoning`, `compaction`, `web_search_call`, `file_search_call`, `computer_call`, `code_interpreter_call`, `mcp_call`, `mcp_list_tools`, `mcp_approval_request`, `image_generation_call`, `tool_search_call`/`_output`, `apply_patch_call`/`_output` are kept as content blocks in `AIMessage.content` [SRC] (`I:base.py:4770-4790`).
- `content_blocks` normalizes them to standard `server_tool_call` and `server_tool_result` blocks, text with `citation` annotations, and `image` blocks [DOCS] (`D:…/chat/openai`, lines 580-687).
- Code interpreter: `include=["code_interpreter_call.outputs"]`. The container ID is in `extras` [DOCS] (lines 1202-1247).
- Remote MCP: `{"type":"mcp","server_label","server_url","require_approval"}`, with approval round-trips [DOCS] (lines 1322-1398).
- Server-side compaction: `ChatOpenAI(context_management=[{"type":"compaction","compact_threshold":N}])`. `compaction` blocks must be kept in history [SRC] (`I:base.py:968-971`); [DOCS] (lines 1491-1507).

**Not found:**

- [NF] I found no `shell`/`local_shell` output parsing in 1.3.4 or 1.7.2. Only `custom_tool_call` and `computer_call_output` appear [SRC] (grep of both `base.py` files). A `{"type":"shell"}` dict would still be routed to the Responses API, but its output items are not in the content-block list.

**Streaming.**

- Responses streaming chunks are converted to the same block types (`I:base.py:4870-`).
- [DOCS] Text streams with `stream_events(..., version="v3")` (`D:…/chat/openai`, line ~620).
- [INF] Mission Control's frame recorder must accept `server_tool_call` and `server_tool_result` blocks that have no matching `ToolMessage`.

### 6.2 Anthropic server and client tools (langchain-anthropic), briefly

[DOCS] `D:https://docs.langchain.com/oss/python/integrations/chat/anthropic`, lines 1812-2930.

- **Server-side:** `web_search_20260209`, `web_fetch_20250910`, code execution (`2025-08-25`, no internet; `reuse_last_container`), remote MCP and tool search.
- **Client-side:** bash, text editor, computer use and the `memory_20250818` tool. These need execution code, or the turnkey middleware in §2.5.
- **Server context management:**
  - `clear_tool_uses_20250919` (beta `context-management-2025-06-27`).
  - `compact_20260112` automatic compaction (Opus 4.6+, `langchain-anthropic>=1.3.0`, beta `compact-2026-01-12`).
- Bind with `bind_tools` or pass in `create_agent(tools=…)`. LangChain adds the beta headers automatically.

---

## 7. Structured output

`create_agent` [SRC] (`I:langchain/agents/structured_output.py`; `factory.py:979-1000, 1321-1345`):

- `response_format` accepts `ToolStrategy(schema, tool_message_content=None, handle_errors=True)`, `ProviderStrategy(schema, strict=None)`, `AutoStrategy(schema)`, a bare type, or a dict.
- A raw schema, **including a dict in source**, is wrapped in `AutoStrategy`.
- At call time, `AutoStrategy` becomes `ProviderStrategy` if `_supports_provider_strategy(model, tools)`. Otherwise it becomes `ToolStrategy`.
- `ToolStrategy` supports Union and `oneOf` variants and retries on validation errors.
- The result lands in `state["structured_response"]`.

**How provider support is detected** [SRC] (`I:factory.py:154-174, 528-575`):

- The model profile's `structured_output` flag, with an exception for Gemini below 3 when tools are present.
- Otherwise a regex fallback list: `gpt-4.1`, `gpt-4o`, `gpt-5`–`gpt-5.5`, `claude-(fable|mythos)-5`, `claude-haiku-4-5`, `claude-opus-4-5..8`, `claude-sonnet-4-5/6`, `grok-4`, `grok-build`.
- [INF] Models not in the profile or the list, such as Mission Control's GPT-6 Sol/Luna, fall back to `ToolStrategy` unless the profile says otherwise. Use explicit `ProviderStrategy` if native output is wanted.

**Docs conflict** [DOCS] (`D:https://docs.langchain.com/oss/python/langchain/structured-output`): the docs say JSON-Schema dicts "must be wrapped in an explicit strategy" and also require top-level `title`/`description` for dict schemas. This contradicts the source behaviour above.

**deepagents** [SRC]:

- `create_deep_agent(response_format=…)` passes through to `create_agent` (`I:graph.py:280, 927`).
- Each `SubAgent` has its own `response_format`, and its JSON is the child's `ToolMessage` content.
- A dynamic per-call schema is possible through the configurable key (§3.1).

---

## 8. Hooks: what exists that resembles Claude Code / Cursor hook scripts

**deepagents SDK, LangChain and LangGraph.**

- [SRC] No lifecycle mechanism runs external commands. A grep of deepagents 0.7.30 for "hook" finds only middleware and trace-policy wording.
- [NF] I found no `before_tool`, `after_tool` or `on_compact` hook in langchain 1.3.14 or 1.4.7.
- Lifecycle points map onto middleware as follows [SRC] (`I:types.py:419-744`):

| Lifecycle event                               | Middleware equivalent                                                                                                     |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| SessionStart / UserPromptSubmit               | `before_agent`                                                                                                            |
| PreModel                                      | `before_model` / `wrap_model_call`                                                                                        |
| PreToolUse / PostToolUse / PostToolUseFailure | `wrap_tool_call` (before, after, or except `handler`)                                                                     |
| Stop                                          | `after_model` with `jump_to="model"` to continue, or `after_agent`                                                        |
| PreCompact                                    | wrap or replace the deepagents `SummarizationMiddleware` by name, or intercept `compact_conversation` in `wrap_tool_call` |
| SubagentStart / SubagentStop                  | `wrap_tool_call` on `task`, or `start_async_task`, plus `TaskEvent` notifications (0.7.27+)                               |

**Deep Agents Code (**`dcode`**)** has Claude-compatible command hooks [DOCS] (`D:https://docs.langchain.com/oss/deepagents/code/hooks`):

- Configured in `~/.deepagents/hooks.json`, project `.deepagents/hooks.json` (after workspace trust) and plugin `hooks/hooks.json`.
- Event → matcher group → `{type:"command", command|argv, timeout (600s default), statusMessage}`.
- The JSON payload goes to stdin. Credential-like environment variables are stripped. Handlers run concurrently and are combined by precedence.
- **Events:**
  - Client-side: `SessionStart`, `UserPromptSubmit`, `SessionEnd`, `PermissionRequest`, `Notification`.
  - Server-side: `PreToolUse`, `PostToolUse`, `PreCompact`, `Stop`, `SubagentStart`, `SubagentStop`.
- **Correction to the baseline:** `PostToolUseFailure` is **not** in the current docs' events table (lines 131-147).

**Agent Server.**

- Run webhooks: `AsyncSubAgent.webhook` → `runs.create(webhook=…)` in 0.7.30 [SRC] (`W:… async_subagents.py:117-118, 404-418`).
- `deployment_auth` handlers already filter requests in Mission Control (see `ASYNC-SUBAGENTS-EXPLAINED.md` §5).

**Mission Control already has the pieces.**

- [SRC] `src/mission_control/adapters/deep_agents/hooks.py:89-187` defines `ResolvedHookScript`, `HookScriptRunner` and `SubprocessHookScriptRunner`, plus kernel hook ports.
- [SRC] The 0.7.26 `summarizer` parameter on the deepagents summarization middleware (`W:… summarization.py:613-726`) is a clean seam for a PreCompact hook.

---

## 9. Parallelism and Temporal

**LangGraph parallelism.**

- **Fan-out:**
  - Multiple outgoing edges, or a list returned from a router, run in the **same superstep in parallel** [DOCS] (`D:https://docs.langchain.com/oss/python/langgraph/graph-api`, lines 759, 783).
  - `Send(node, state)` gives map-reduce with per-branch state (lines 821-835).
  - `defer=True` holds a join node until all pending tasks finish (`D:…/use-graph-api`, lines 1334-1415).
- **Supersteps are transactional:**
  - If any branch raises, none of the superstep's updates apply.
  - With a checkpointer, successful branches are saved and are not rerun on resume.
  - `RetryPolicy` retries only the failing branches.
  - Sources: [DOCS] `D:…/use-graph-api`, lines 1310-1325.
- `max_concurrency` is a top-level config key, not under `configurable`, and caps concurrent tasks [DOCS] (line 1328).
- **Parallel tool calls in** `create_agent`**:**
  - Each pending tool call becomes its own `Send("tools", [tool_call])`. Tool calls from one AI message run as parallel tasks in a single superstep, which includes parallel `task` subagents [SRC] (`I:langchain/agents/factory.py:1881`).
  - [INF] Parallel `task` calls inherit superstep semantics: they are all-or-nothing on exception, but checkpointed per task.
  - OpenAI's `parallel_tool_calls` can be disabled with `bind_tools(parallel_tool_calls=False)` [SRC] (`I:langchain_openai/chat_models/base.py:2163-2195`).
- **Async subagent concurrency:** bounded by Agent Server worker slots only (§3.2).
- **QuickJS** `task()` **concurrency:** bounded by `max_subagent_concurrency` in 0.3.9 (§3.3).

**Temporal + LangGraph** [DOCS] (`D:https://docs.temporal.io/develop/python/integrations/langgraph`):

- `temporalio[langgraph]` (`temporalio>=1.27.0`) provides `LangGraphPlugin(graphs={…}, default_activity_options, streaming_topic)`. It is in **Public Preview**.
- Every node must set `metadata={"execute_in": "activity"|"workflow", …Temporal activity options}`. LangGraph `retry_policy=` is rejected.
- Checkpointers: use `InMemorySaver`. "Third-party checkpointers (like PostgreSQL or Redis) are not needed."
- **Stores are not supported** in Activity nodes.
- Context is reconstructed in Activities and must be serializable.
- Continue-as-new is supported through `cache()`.
- `streaming_topic` carries only `stream_mode="custom"`.
- [INF] `create_agent`/`create_deep_agent` graphs do not set `execute_in` on their nodes. I found no guidance for running them under `LangGraphPlugin` [NF].

**Temporal + Deep Agents: a dedicated plugin, already installed.**

- `temporalio.contrib.deepagents` ships in the installed temporalio 1.34.0 [SRC] (`I:temporalio/contrib/deepagents/README.md`, `_plugin.py`, `workflow.py`). The repository does not use it: a grep of `src/` found no import. Temporal labels it "Pre-release" and experimental [DOCS] (`D:https://docs.temporal.io/develop/python/integrations/deepagents`).
- **What it does:** `DeepAgentsPlugin(model_activity_options, tool_activity_options, streaming_topic)` and `create_temporal_deep_agent(...)` run the deep-agent loop _inside the Workflow_, deterministically replayed, with **each LLM call and each I/O tool call as an Activity**.
- **Helpers:**
  - `activity_as_tool` and `tool_as_activity`
  - `TemporalBackend` for real-I/O backends
  - HITL through the native `__interrupt__`/`Command(resume=…)` protocol plus Query/Update
  - `run_deep_agent(..., state_snapshot=…)` for continue-as-new, which carries messages and todos
- Subagents inherit durability through the shared model object.
- **Limitations** [DOCS] ("Runtime behavior and limitations"):
  - Durable checkpointers such as Postgres "are not replay-safe" inside a Workflow. The plugin warns, and recommends `InMemorySaver` plus continue-as-new.
  - The plugin patches deepagents' model-resolution seam while the worker runs.
- [INF] This conflicts with Mission Control's current topology, where the Deep Agent runs inside an `operation.execute` Activity with `AsyncPostgresSaver` checkpoints and LangGraph-level cognition points. Adopting it would be an architecture decision, not a drop-in.

---

## Implications for Mission Control (capabilities to make selectable, by category)

These are recommendations built on the facts above. "Installed" means the capability works on the 0.7.5 stack. "Needs upgrade" means it requires 0.7.30 / langchain 1.4.x / quickjs 0.3.9.

**Context management**

1. Deep Agents summarization (installed). Configurable fields: `trigger`, `keep`, `truncate_args_settings`, `trim_tokens_to_summarize`, `summary_prompt`, plus the `summarizer` model (needs upgrade, 0.7.26+).
2. An on-demand `compact_conversation` tool through `SummarizationToolMiddleware` (installed).
3. `ContextEditingMiddleware` / `ClearToolUsesEdit` for cheap tool-output trimming (installed).
4. Provider-native compaction: OpenAI `context_management` compaction, and Anthropic `clear_tool_uses` / `compact_20260112`. These are model settings, not middleware. Mission Control must keep the `compaction` blocks.
5. Filesystem eviction thresholds (`tool_token_limit_before_evict`, `human_message_token_limit_before_evict`) and binary offload (`offload_binary_content`, needs upgrade).
6. `LLMToolSelectorMiddleware` and `ProviderToolSearchMiddleware` to shrink tool payloads.
7. `MemoryMiddleware` (AGENTS.md) and `SkillsMiddleware`. With the upgrade: `pinned_skills` and lazy skill tools (`metadata.include_tools`).

**Tooling**

1. Built-in filesystem tools, with a per-agent `tools=` subset.
2. `execute` through a sandbox backend.
3. `ShellToolMiddleware` with Docker or Codex execution policies.
4. `TodoListMiddleware` (`write_todos`), which is opt-in. It is not default, so make it an explicit mission flag.
5. `CodeInterpreterMiddleware` with a PTC allowlist (beta). `max_subagent_concurrency` and the signed snapshot need the upgrade.
6. `ToolRetryMiddleware`, `ToolErrorMiddleware` and `LLMToolEmulator` (for test missions).

**Subagents and delegation**

1. Sync `SubAgent` with per-child model, tools, skills, permissions, `interrupt_on`, middleware and `response_format`. This is the natural carrier for per-child output contracts.
2. `CompiledSubAgent` for hand-built graphs.
3. Explicit configuration of the general-purpose child (`GeneralPurposeSubagentProfile`).
4. Fork-mode children (needs upgrade, experimental).
5. Async subagents on the Agent Server. With the upgrade: `update_strategy="enqueue"`, `webhook`, `notify_parent`, fork mode, `waiting`, and context forwarding when co-deployed.
   - Keep Mission Control's governed wrapper.
   - Never attach the 0.7.30 stock middleware directly: its hooks inject child results before admission.
   - Set `notify_parent=False` where Mission Control owns delivery.
6. Dynamic subagents through QuickJS `task()`, with typed `responseSchema`. These bypass HITL per dispatch, so gate `eval` itself.

**Control and safety**

1. HITL through `interrupt_on` with `allowed_decisions`, `when` predicates and `args_schema`. Decisions are approve, edit, reject and respond.
2. `FilesystemPermission` allow, deny or interrupt. The 0.7.25 symlink fix argues for upgrading.
3. `ModelCallLimitMiddleware` and `ToolCallLimitMiddleware` as budget governors.
4. `ModelFallbackMiddleware` and `ModelRetryMiddleware`.
5. `PIIMiddleware` and `OpenAIModerationMiddleware`. `OpenAIAutoModeMiddleware` (tool-risk gating) needs langchain-openai 1.7.
6. `RubricMiddleware` for self-grading.
7. Hook scripts stay a Mission Control adapter that maps onto `wrap_tool_call`, `before_*`/`after_*` and the summarizer seam. dcode's `hooks.json` is the vocabulary precedent.

**State**

1. A custom `state_schema` that subclasses `DeepAgentState` (DeltaChannel messages) for mission fields. It is shared with declarative children.
2. Middleware-scoped state with `PrivateStateAttr` / `OmitFromInput` / `OmitFromOutput`, to keep governance keys out of child I/O.
3. A typed `context_schema` for immutable run identity (mission, run, operation, scope). It propagates to sync children, and to co-deployed async children on 0.7.30. Put it in `context`, not in state.
4. Child state merge-back is real: children can write `files` and custom keys. Decide per key whether that is wanted, because 0.7.5 also copies `skills_metadata` and `async_tasks` into children.

**Persistence**

1. Backends selectable per mission:
   - `StateBackend`, which is checkpointed and thread-scoped;
   - `StoreBackend` on `AsyncPostgresStore` for cross-thread memory;
   - `CompositeBackend` routes;
   - `FilesystemBackend` / `LocalShellBackend`, for development only;
   - sandbox providers (Daytona, Modal, Runloop, E2B, Vercel, LangSmith, AgentCore and others).
2. `langgraph-checkpoint-postgres` 3.2.0 adds `prune`, which is relevant for the checkpoint-history service.
3. The LangGraph 1.2.13–1.2.16 fixes concern DeltaChannel forks, `update_state` and resume. These matter directly to Mission Control's time-travel and fork work and argue for upgrading langgraph.
4. `temporalio.contrib.deepagents` is installed but unused. It is an alternative durability model (in-workflow loop, Activity-per-LLM-call, no durable checkpointer) that would replace the current Activity-wrapped, Postgres-checkpointed design. Record it as an open decision; it is not a capability to switch on.

**Provider-specific**

1. OpenAI Responses built-ins as dict tools: `web_search`, `file_search`, `code_interpreter`, `image_generation`, remote `mcp`, `tool_search`, plus `apply_patch` and computer use, which need client execution.
   - They work in `create_agent` and `create_deep_agent`, but bypass `ToolNode` middleware, so HITL, limits and retries do not apply.
   - They are inherited by sync children that inherit tools.
2. OpenAI server compaction and `previous_response_id` conversation state.
3. Anthropic server tools (`web_search`, `web_fetch`, `code_execution`, MCP, tool search), client tools (bash, text editor, memory) through the `langchain_anthropic.middleware` classes, and prompt caching. Prompt caching is already automatic in deepagents.
4. Mission Control's GPT-6 models are not in the `ProviderStrategy` fallback regex list. Set `ProviderStrategy` explicitly, or set a model profile, when native structured output is required.
