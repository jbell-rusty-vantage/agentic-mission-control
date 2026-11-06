---
type: Research
title: Deep Agents 0.7.5 surface Mission Control builds on
description: Version-pinned facts about deepagents 0.7.5 (the pin in pyproject.toml) - the default create_deep_agent middleware stack and its order, sync and async subagents, backends, structured output strategies, hook equivalents - and what changes by 0.7.30, harvested from the 2026-10-22 surface sheet.
tags: [mission-control, research, deep-agents, middleware, subagents, structured-output, upgrade]
subject: deepagents public surface (create_deep_agent, middleware, subagents, backends) as installed and as upgraded
versions: [deepagents==0.7.5, langchain==1.3.14, langgraph==1.2.10, langchain-openai 1.3.4 installed, langchain-anthropic==1.5.4, deepagents 0.7.30 (latest at 2026-10-22, not adopted)]
sources:
  - docs/specs/provider-consolidation-2026-10/providers/deep_agents/DEEP-AGENTS-SURFACE-2026-10-22.md (full sheet, 938 lines, [SRC]/[DOCS]/[INF]/[NF] labels)
  - pyproject.toml:18-37 (pins)
  - .venv deepagents-0.7.5 (installed source)
observed: 2026-10-22 (sheet); pins re-checked 2026-11-01
confidence: high for 0.7.5 [SRC] facts; medium for 0.7.30 facts (wheel read, not run); [DOCS] items were not checked against source
used_by: [deep-agents-lane, deep-agents-children, agent-configuration]
date: 2026-11-01
---

# Deep Agents 0.7.5 surface

`pyproject.toml:18` pins `deepagents==0.7.5`; `describe.py:60` declares `{"deepagents": "0.7.5", "langgraph": "1.2.10"}`
and `DeepAgentExecutionPlacementProfile.deepagents_version` is `Literal["0.7.5"]`
(`domain/execution/contracts.py:1197`). Everything below is 0.7.5 unless it names another version. The full sheet
(the source of this note) is the file named in `sources`; it is dated and not maintained.

## Default middleware stack of `create_deep_agent` (0.7.5, `graph.py:816-893`)

In order: `SkillsMiddleware` (if `skills`), `FilesystemMiddleware`, `SubAgentMiddleware` (if any sync subagent),
`SummarizationMiddleware`, `PatchToolCallsMiddleware`, `AsyncSubAgentMiddleware` (if async subagents),
**user `middleware=`**, profile `extra_middleware`, `AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore")`,
`MemoryMiddleware` (if `memory`), `HumanInTheLoopMiddleware` (if `interrupt_on`), `_ToolExclusionMiddleware`.

- A user middleware whose `.name` equals a built-in replaces it in place (`graph.py:201-235`); Mission Control
  uses this for `FilesystemMiddleware` and the summarizer.
- `FilesystemMiddleware` and `SubAgentMiddleware` cannot be excluded (`graph.py:238-265`).
- `TodoListMiddleware` is **not** in the default stack; only the OpenAI Codex harness profile adds it.
- 0.7.30 reorders (Skills moves after profile middleware), adds `_ParentNotifierMiddleware` and
  `UnsupportedContentMiddleware`.
- Hooks that define node-style methods (`before_agent`, `before_model`, `after_model`, `after_agent`) add graph
  nodes; `wrap_model_call` and `wrap_tool_call` add none, and the first middleware is outermost
  (`langchain/agents/factory.py:1502-1592`). This is why the turn stops are `wrap_model_call` (a node-style stop
  moved the recovery suites' step numbers).

## Sync subagents (`task`)

`SubAgent{name, description, system_prompt, tools?, model?, middleware?, interrupt_on?, skills?, permissions?, response_format?}`
(`middleware/subagents.py:36-244`). `task(description, subagent_type)`. The child inherits model, tools (including dict
provider tools), permissions and `interrupt_on` when its spec omits them; an override **replaces** the parent's rules. The
child's input state is every parent key except `messages`, `todos`, `structured_response` and private keys
(`subagents.py:252-256,529-540`), so `files`, custom keys and `skills_metadata` pass in. The return is a
`Command(update=...)` whose `ToolMessage` content is the child's `structured_response` JSON or last text. A
general-purpose child is auto-added unless the profile disables it (`graph.py:745-814`). `SubAgent.mode="fork"` does
**not** exist in 0.7.5.

## Async subagents

`AsyncSubAgent{name, description, graph_id, url?, headers?}`. Five tools: `start_async_task`, `check_async_task`,
`update_async_task` (new run on the same thread, `multitask_strategy="interrupt"`), `cancel_async_task`,
`list_async_tasks`; state `async_tasks`. In 0.7.5 communication is **pull only**; 0.7.26+ adds push notifications
(beta). Mission Control reuses only the stock tools and raises a `RuntimeError` ("tool surface drifted from 0.7.5", `async_subagents.py:190`) if their names
change (`adapters/deep_agents/async_subagents.py`).

## Backends

See [sandbox providers](sandbox-providers.md): `StateBackend`, `FilesystemBackend`, `LocalShellBackend`, `StoreBackend`,
`CompositeBackend`, `LangSmithSandbox`, `ContextHubBackend`; `BaseSandbox` builds file operations on `execute`.

## Structured output

`create_agent(response_format=...)` accepts `ToolStrategy`, `ProviderStrategy`, `AutoStrategy`, a type or a dict; a bare
schema becomes `AutoStrategy`, which picks the provider strategy only for models the profile or a regex list names.
Models outside the list (the GPT-6 family) fall back to `ToolStrategy`. Mission Control therefore binds an explicit
strategy per Model Catalog row (`response_format_for`, `materializer.py`; [model catalog](../../knowledge/model-catalog.md)).
`create_agent` never clears `structured_response`, so a later turn on one thread can return an earlier verdict; the lane
checks the channel version (`adapter.py::_structured_response_written`).

## Hooks

deepagents has no external-command hooks. Lifecycle events map to middleware: SessionStart to `before_agent`, PreToolUse
and PostToolUse to `wrap_tool_call`, Stop to `after_model`/`after_agent`, PreCompact to replacing the summarization
middleware by name. Mission Control's `HookScriptMiddleware` (`adapters/deep_agents/hooks.py`) is exactly that mapping.

## Upgrade risks to 0.7.30 (not adopted; for the next version bump)

1. Stock async tool outputs changed (statuses `pending`, `waiting`; interrupt update default); the governed wrappers need retesting.
2. 0.7.30 `AsyncSubAgentMiddleware` appends notification messages with child results; attaching the stock middleware would bypass the admission gate.
3. `_ParentNotifierMiddleware` wakes a parent only when thread metadata names a parent; Mission Control's `belllabs_*` metadata keeps it inert.
4. Child state exclusions grow (`skills_metadata`, `pinned_skills`, `rubric`).
5. Private APIs relied on: `_harness_profile_for_model`, `deepagents_async.get_client`, `create_summarization_middleware`.
6. Pre-1.0: `model=None` and `BASE_AGENT_PROMPT` are deprecated.

## Citations

- Source sheet: [DEEP-AGENTS-SURFACE-2026-10-22](../../specs/provider-consolidation-2026-10/providers/deep_agents/DEEP-AGENTS-SURFACE-2026-10-22.md) (sections 1.5, 2.4, 3, 5, 7, 8).
- Code: `pyproject.toml`, `src/mission_control/adapters/deep_agents/{describe,adapter,async_subagents,hooks,materializer}.py`.
- Proof ledger: [CHANGES.md](../../specs/provider-consolidation-2026-10/providers/deep_agents/CHANGES.md).
