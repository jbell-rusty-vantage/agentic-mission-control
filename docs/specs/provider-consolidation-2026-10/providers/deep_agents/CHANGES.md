---
type: Sprint Disposition
title: "P1 deep_agents change ledger: general and provider-specific changes made on the way, with where to read each finished part"
description: "Cumulative record of what the deep_agents sprint changed in the kernel (lane-neutral) and in the Deep Agents lane (provider-specific), one entry per session turn, each with the module to read, the test that proves it and the API sequence it sits in. Kept so later provider sprints inherit the general parts and the owner can navigate the system as it is built."
tags: [mission-control, providers, consolidation, deep-agents, changes, P1]
---

# P1 deep_agents change ledger

Read [DESIGN.md](DESIGN.md) for the positions and [AUDIT.md](../../../archive/provider-consolidation-2026-10/docs/AUDIT.md) for the starting state.
Every entry says whether a change is **general** (every lane inherits it) or **deep_agents**
(this lane only), names the module that is the finished part, and the test that proves it.
Paths are relative to `src/mission_control/` unless they start with `tests/` or `docs/`.

## 2026-10-31 — provenance sprint slices (OVE-204)

Appended 2026-11-01 (OVE-206) from the sprint's [final report](../../../archive/provider-consolidation-2026-10/sprint-oc/provenance-2026-10-31/REPORT.md)
and commit `03f11594`; read the report for per-slice proof and spend.

**General:** true invocation origin (slice 1): every knowledge origin names the run's ledger
mission id and the attempt's real activation id (`InvocationLocator`, `PostgresInvocationLocator`),
and the runtime unit key fills journal/handle/submission `unit_key`. Production gateway minting
for the AI Engineer fixture (slice 2). `knowledge_read_intent` and `RetainedReadStore` (slice 4).
S3-compatible payload store settings and the `mc.storage.mission-payloads` seed (slice 7).
Release 1.12.0 (`0070_workspace_closure.sql`) stores Workspace Closures.

**Deep Agents:** `adapters/deep_agents/workspace_closure.py` records every agent-visible file of an
attempt at `attempt_settled`/`attempt_failed`/`attempt_cancelled` (slice 5; see
[Workspace Closure](../../../../knowledge/workspace-closure.md)); `docker_sandbox.py` gains
per-target writable host directories; `knowledge_tools.py` adds the read-intent tool; the
knowledge charter skills (`skills/*-knowledge-charter`, agent-skills 1.0.4) compile-mount on
knowledge missions (slice 6).

**Labels:** slices 1, 2 and 5 integrated by the live run `source-mc-origin-01` (disposable targets);
slice 4 tested on the MC side only (not exercised live); slice 6 tested, not mounted in any run;
slice 7 a local S3 round trip only. Nothing qualified; 1.12.0 and agent-skills 1.0.4 have no remote
install.

## 2026-10-31 — Selection Workspace

**General** (lane-neutral, `016d27a1`, merged `79525ed4`): `application/selection/workspace.py`
composes Capability Search, the Lane Registry, the Model Catalog, sandbox profiles and Workflow
Types into one search and one read-only draft check, served as `missionctl search` /
`missionctl workspace check`, `POST …/selection/search|check` and MCP `mission_search` /
`selection_check`. Proof: `tests/unit/selection/`. Tested over in-memory ports only; no live catalog
and no agent-skills guidance yet (whether it goes into 1.0.4 or 1.0.5 is open, NEXT-SESSION).
See [Selection Workspace](../../../../knowledge/selection-workspace.md).

## 2026-10-30/31 — Qualia and AI Engineer StageGraph fixture repairs

From [NEXT-SESSION](../../sprint-oc/NEXT-SESSION.md) (Qualia and AI Engineer sections) and commits
`0eccfa2d` (Qualia), `e8eea445` and `3e974b75` (AI Engineer fixtures).

**Deep Agents and general runtime repairs found by live fixtures:** finite Deep Agents network
grants (`application/environments/network.py`, `adapters/deep_agents/adapter.py`), named-output
settlement (`application/programs/named_outputs.py`), schema-only input gates
(`application/programs/artifact_validation.py`, `completion_validation.py`), concurrent stage
authority (`application/programs/service.py`), producer-scoped effect liability and bounded queued
turns (`application/execution/operations/`, `mailbox.py`, `harness/inject.py`), trusted manifest
fork provenance (`application/authoring/manifest_fork_admission.py`) and explicit
capture/assessment feedback.

**Labels:** integrated with live paid models on disposable/registered targets (Qualia source09 and
fork05; AI Engineer source-02/fork-01 and source-04/fork); changed-unit checks recorded as passing
(427 tests). Broad legacy test/type failures remain. Not qualified; W1/W2 unreleased. Private
evidence: `.scratch/qualia-stagegraph-2026-10-30/READ-FIRST.md`,
`.scratch/aieng-stagegraph-2026-10-31/READ-FIRST.md`.

## 2026-10-29 — report/source foundation

**Service-specific setup follow-up:** `scripts/report_source_sandbox.py` packages six exact
skill directories with selected report contracts and schema/entity navigation. Canonical KS
sources stay unchanged; missing skill-name metadata is repaired only in the inventoried copy.
`tests/integration/deep_agents/test_report_source_sandbox.py` proves actual parser discovery and
complete instruction/reference reads through StateBackend. This is attachment proof, not provider
tool admission or search/capture service qualification. Current resume instructions define that
next partial fixture and stop at submission or a concrete unproved capture-to-K01 boundary.

**General:** `application/outputs/invocation_view.py` projects owned pinned obligations and recorded
state; submission feedback preserves typed findings and recovery metadata. Expected-head checking
runs under the PostgreSQL promotion lock after replay detection. Knowledge-tools 1.1.0 adds the
enhanced capability without changing the original seed. See `tests/unit/knowledge/test_submission_foundation.py`
and `tests/integration/postgres/test_output_contracts_postgres.py`.

**Deep Agents proof:** deterministic canonical report/source contexts are read fully through the
real backend in `tests/integration/deep_agents/test_report_source_context.py`. The
joined `test_report_source_real_service.py` verifies held-to-repaired report delivery from real
KS custody and completed-unit replay without new cognition through reconstructed services.
The [fixture guide](../../../../REPORT_SOURCE_FOUNDATION.md) separates local/scripted evidence from
full process recovery, composed mission and paid qualification. W1/W2 remain unreleased.

## The sequence a manifest follows (where to look)

```text
POST /v1/applications/{app}/missions:compile          interfaces/http/missions.py:176
  └ MissionManifestService.compile                    application/authoring/manifest_service.py:1715
      └ ManifestCompileService.compile                 manifest_service.py:544   (parse, resolve catalog pins, lane admission)
          ├ domain/authoring/manifest.py               Environment (lane-neutral; `provider_options` keyed by lane)
          ├ manifest_v2_admission.admit_node           requires/approvals against the lane's describe
          └ ManifestProgramCompiler.compile            manifest_service.py:425   (lowering to the family blueprint)
POST /missions:submit  → the run is admitted           interfaces/http/missions.py:243
POST /missions:start   → _start                        interfaces/http/missions.py:276
  └ ManifestLaunchInputAuthor.family_input / bind     application/authoring/manifest_launch_inputs.py:2609
      └ ManifestLaunchResolver.stage_templates | goal_templates
          └ ManifestLaunchResolver.node               (neutral: model, sandbox, MCP, Skills, tools)
              └ DeepAgentsLaneAdapter.adapt           application/authoring/lanes/deep_agents.py   ◄ the deep module
                  (subagent profiles → children, provider options, slices, receipt)
              └ ManifestLaunchResolver._request       → compile_deep_agent_execution_binding   domain/execution/materialization.py
                  = DeepAgentExecutionBinding (exact, digest-sealed, with provider_options + materialization_receipt)
Temporal family workflow → operation.execute activity
  └ DeepAgentRuntimeAdapter.execute                    adapters/deep_agents/adapter.py:189
      └ ExactDeepAgentMaterializer.prepare             adapters/deep_agents/materializer.py   (applies the sealed binding: children, MCP tools, summarization trigger)
          └ create_deep_agent(...)
```

The finished parts to read, in order (turn 3 added the discriminator and the child shapes):

1. `domain/capabilities/subagents.py` — the one subagent vocabulary: kinds, the two child
   shapes, seeds, `SUBAGENT_FIELDS` (general).
2. `domain/capabilities/subagent_overrides.py` and `domain/authoring/provider_options.py` — the
   typed per-lane registries (general shape, Deep Agents entries).
3. `application/authoring/subagent_discriminator.py` with `lanes/support.py` — compile-time
   verdicts per lane and the seeds a child owns (general).
4. `application/authoring/lanes/deep_agents.py` — contract → Deep Agents adaptation (deep_agents).
5. `domain/execution/materialization_receipt.py` — what the lane signs (general).
6. `adapters/deep_agents/materializer.py::_materialize_subagents` and
   `adapters/deep_agents/adapter.py::_disable_implicit_general_purpose_child` — the runtime side
   (deep_agents).

## Sprint OC W1 fix D27 (2026-10-29): the verifier never acts as the producer

Linear `OVE-169`, branch `sprint-oc-w1fix-l` (base `2c0738dc`). Evidence: run 9cc17684, where the
verifier re-submitted the producer's report as revision 2. Nothing paid; no schema change.

| # | Scope | Change | Proof |
| --- | --- | --- | --- |
| W1.27 | general + deep_agents | `application/knowledge/roles.py` names the producer's tools; the launch author leaves them out of the verifier's agent configuration (inherited) or refuses the launch (selected in the verifier's own environment); `LiveInvocation.evaluator` comes from the sealed plan's `independent_evaluator` isolation and the toolset refuses `report_register`, `knowledge_apply` and `submit_output` with `ROLE_SEPARATION`. Position ownership alone could not refuse: both roles are templated at the root position | `tests/unit/knowledge/test_verifier_role_separation.py` |
| W1.27R | general + deep_agents | Review: `is_evaluator` also reads the sealed runtime unit's GoalDirected `verifier` role (fail closed without a transfer); an evaluator declares no producer promise and finalizes `no_declared_obligations`/`fulfilled` (`owes_nothing`); sync children inherit `CURRENT_INVOCATION` and its role; a real goal-loop verifier template (fixture `knowledge-tools-goal-loop.yml`) lacks the producer tools and keeps its output schema | same |

## Sprint OC W1 fix D18 (2026-10-29): Sonnet 5.5 "Schema is too complex"

Linear `OVE-169`, branch `sprint-oc-w1fix-f` (base `77783f30`). Evidence: run 457bd952 (every
request 400 "Schema is too complex." under `provider_native`). Nothing paid; no schema change.

| # | Scope | Change | Proof |
| --- | --- | --- | --- |
| W1.18 | general + deep_agents | Third strategy `tool_auto`: `ToolStrategy` bound with `tool_choice` auto (`structured_response.with_auto_tool_choice`) plus host enforcement (`RequireStructuredResponse`, two bounded reminders, then no result, refused by the node's missing-output handling); Sonnet 5.5 rows are `tool_auto`; `output_format` enforces the published 24/16 limits and an MC grammar budget (24/12/8) below the observed failure (30/23/1), so a too-complex `provider_native` schema is `OutputSchemaUnsupported` before any call; evaluators support `tool_auto` | `tests/unit/deep_agents/test_structured_output_strategy.py` (every registered schema x every checked-in row; offline Sonnet body: tool choice auto, no `output_config.format`) |
| W1.18R | general + deep_agents | Review: the response tool parses JSON-string object fields once (`response_schema`, D17 rules); a response call mixed with other calls is refused append-only so the others run; reminders and refused calls share one bound (3) counted by invocation-scoped markers; the wrapped client keeps the model's identity; golden digests prove the untargeted rows unchanged | `tests/unit/deep_agents/test_tool_auto_enforcement.py` |

## Sprint OC W1 fixes D11-D13, D16, D17 (2026-10-28): what the first real model runs needed

Linear `OVE-169`, branch `sprint-oc-w1fix-c` (base `f37c6c26`). Evidence: the W1 session 3 runs
(0da30ad0 Sonnet 400; 361d04a8, 3081b3e4, 202c49b2, 4ad5c958 Haiku). Concepts:
[model catalog](../../../../knowledge/model-catalog.md),
[Knowledge Services](../../../../knowledge/knowledge-services.md). Nothing paid; no schema change.

| # | Scope | Change | Proof |
| --- | --- | --- | --- |
| W1.16 | general + deep_agents | `models.toml` rows declare `structured_output` (`tool_forced` / `provider_native`, required with `supports` structured_output); `ModelPin`, `ModelRoute.structured_output`, `DeepAgentModelComponent.structured_output` carry it (digest-neutral when absent); `materializer.response_format_for` wraps the schema in `ToolStrategy` / `ProviderStrategy` (never a raw schema: LangChain auto-detection forced `tool_choice` any on Sonnet 5.5); compile refuses an unrouted strategy, launch a schema-binding role without one; the evaluators bind the same way. Sonnet 5.5 rows `provider_native` | `tests/unit/deep_agents/test_structured_output_strategy.py` (offline Anthropic payload: `output_config.format`, no `tool_choice`), launch and evaluator tests |
| W1.17 | general + deep_agents | `KnowledgeStructuredTool` parses a JSON-object string for an object-typed argument once (strict, object, 2 MiB bound) before the args schema; `argument_coercions` in the result; schema digest unchanged | `tests/unit/knowledge/test_w1_tool_boundary.py` |
| W1.11 | general | `KnowledgeResult.refusal` keeps the KS `ProtocolError`; the tool result carries code, message, field paths, issues (bounded, redacted) | same |
| W1.12 | general | A settled refusal replays as the same refusal (`gateway._replayed`), never `ok: true`; the key was already over the exact payload, so the dry3 retry (identical bytes) replayed the rejection as success | same |
| W1.13 | general | `submit_output` refuses an undeclared key with this invocation's valid `<position>.<promise>` keys; the description states the form | same |
| W1.R | general + deep_agents | Review fixes: a replayed success reads its settled receipt back and carries the original handles (S1); the schema/strategy refusal applies to every family's template (S2); `output_format.anthropic_output_schema` checks the exact `output_config.format` schema against Anthropic's subset, refused at materialization, every registered schema checked offline (S3); a list of objects sent as one JSON string is coerced (N3); redaction covers userinfo URLs, `sb_*` and AWS keys, key=value secrets and local paths (N4); empty route strategies stay out of dumps (N2) | same two files |
| W1.R2 | general + deep_agents | Confirm review: an unprovable replayed receipt is a typed refusal (`RECEIPT_UNAVAILABLE` / `RECEIPT_DIGEST_MISMATCH` / `RECEIPT_DIGEST_MISSING`); a schema fault is `OutputSchemaUnsupported`, settled once as `output_schema_unsupported` (never retried), and the trusted path checks evaluator rows and schemas at composition | `test_w1_tool_boundary.py`, `test_operation_execution.py`, `test_structured_output_strategy.py` |

## Sprint OC WI-23 (2026-10-28): sealed dynamic async children and check-time admission

Linear `OVE-184`, branch `sprint-oc-wi23`. Builds SUBAGENTS WP-S3 (Q3 option A) and WP-S4 (Q4)
under OUTPUT-CONTRACTS §§10-11. Concept: [async children](../../../../knowledge/deep-agents-children.md).
No schema change: the scoped, immutable `subordinate_contract` row is the sealed binding's
custody (no migration 0062). Nothing paid.

| # | Scope | Change | Finished part | Proof |
| --- | --- | --- | --- | --- |
| 23.1 | general | `SealedAsyncChildBinding` (`belllabs.async-child-binding.v1`, digest over prompt and binding); `AsyncSubagentContract.child_binding` (excluded while absent); `AsyncServedGraphIdentity.binding_mode` and `admits()`; `sealed_child_assistant_id` | `domain/execution/contracts.py`, `async_subagent_reconciliation.py` | `tests/unit/deep_agents/test_async_child_sealed_binding.py` |
| 23.2 | deep_agents | A `kind: async` profile bound with `binding_mode: sealed_child` seals its own prompt, model, narrowed tools/Skills/MCP plus seeds (or the parent's set when inheriting) and the OVE-148 registry's lane features (`max_turns` -> `call_limits`); approval gates and prompt bundles refuse | `adapters/deep_agents/lane.py::_seal_async_child`, `child_binding.py` | same |
| 23.3 | deep_agents | One assistant per binding and scope with the digests in its configuration; runs and follow-ups name it; final content blocks read as text | `adapters/deep_agents/async_subagents.py` | `tests/unit/operations/test_async_child_check_time_admission.py` |
| 23.4 | deep_agents | Agent Server `belllabs_async_child`: scope from the claim, assistant audience, custody read under the scope, digest re-verification, compile through the worker adapter, stamp; auth admits only the caller's own sealed assistant | `adapters/agent_server/async_subagents/sealed.py`, `deployment.py`, `deployment_auth.py`, `entrypoints.py`, `http_app.py`, `adapters/postgres/async_subagents/sealed_child_custody.py` | `tests/unit/agent_server/test_sealed_child_graph.py`, `tests/integration/agent_server/test_wi23_sealed_child_server.py` |
| 23.5 | general | Check-time admission in the governed `check_async_task` (audience, one decision per child, live generation, `child_result_index` entry); the boundary settles once; a non-live child accepts no message | `application/subordinates/admission.py`, `service.py`, `async_subagents.py` | unit above; `tests/integration/postgres/test_wi23_async_children_postgres.py` |
| 23.6 | general | Explicit exact adoption (`adopt_async_task_output`) through the parent's ordinary `SubmitOutput@2` with the `async-child-result:` derivation; never assesses or fulfills | `application/subordinates/adoption.py`, `adapters/deep_agents/child_adoption.py`, composition | unit above |
| 23.7 | deep_agents | End to end from a manifest: sealed binding, real local Agent Server, Temporal, PostgreSQL; the parent's cognition used the admitted result | `tests/acceptance/mission_control/test_manifest_sealed_async_child.py` | passed locally (deterministic models) |

Found on the real server (H6): the pinned langgraph-api 0.12.0 calls the assistants **read**
handler before it runs a non-system assistant, and a follow-up to a completed child reached
the provider before the ledger refused it. Both are fixed above. W5 still owes the paid
observation (real models, C10-C13) and the production persistence topology of the server.

## Turn 8, sprint B first slice (2026-10-23): the agent configuration, selectable lane features and model tools, Anthropic as a model provider

Linear `OVE-148`, approved by the owner, not committed. The first slice of sprint B of
[SPRINT-SEQUENCE](../../../archive/provider-consolidation-2026-10/proposals/SPRINT-SEQUENCE-2026-10-23.md): a registry of the capabilities an agent can
be given, a manifest spelling to select them, a sealed and receipted result, and the Deep Agents
realization of each. The storage question (catalog rows, search, coordinator selection) is the
separate proposal [AGENT-CAPABILITY-CATALOG-PROPOSAL-2026-10-23](../../AGENT-CAPABILITY-CATALOG-PROPOSAL-2026-10-23.md)
(AC-D1..D12, open). No Linear status changed.

### Turn 8 finish: what to read first

**One finished part to read** (the whole path of one selection, in reading order):
`domain/capabilities/features/registry.py` (the types: axis `lane_feature | model_tool`, the six
domains, the facets, mechanism `middleware | provider_tool | model_setting`, observability,
provenance, status `available | needs_upgrade | planned`) with its rows in
`features/deep_agents.py`, `features/openai.py` and `features/anthropic.py` -> `features/configuration.py`
(`mc.agent_configuration.v1`, `FeatureSelection` with a config digest, `resolve_agent_configuration`)
-> `domain/authoring/provider_options.py` (`lane_features`, `model_tools`, validated against the
registry at manifest validation; `effective_summarization`) ->
`application/authoring/lanes/deep_agents.py::_agent_configuration` (resolves, seals and receipts
every item; receipt kinds `feature` and `model_tool` in `domain/execution/materialization_receipt.py`)
-> `domain/execution/contracts.py` (`DeepAgentProfile.agent_configuration`,
`DeepAgentExecutionBinding.agent_configuration`, excluded while absent so earlier digests hold) ->
`adapters/deep_agents/features/builders.py` (one builder per row) ->
`adapters/deep_agents/materializer.py::prepare` (`MaterializedDeepAgentArguments.provider_tools`,
`_with_model_settings`) -> `adapters/deep_agents/adapter.py::_compile` (`filesystem_replacement`).
Proofs: `tests/unit/capability/test_agent_feature_registry.py`,
`tests/unit/authoring/test_deep_agents_lane_adapter_features.py`,
`tests/unit/deep_agents/test_agent_configuration_materialization.py`, and the paid
`tests/integration/deep_agents/test_agent_configuration_live.py` (FX-B-FEATURES).

**The sequence it sits in:** manifest compile (`provider_options.deep_agents.lane_features` and
`model_tools` validated against the registry) -> `ManifestLaunchResolver.node` ->
`DeepAgentsLaneAdapter.adapt` (`_agent_configuration`: defaults inserted explicitly, refusals for
an unknown id, an unavailable status with `requires`, `model_tool_provider_mismatch` and an invalid
config; one receipt item per selection) -> the launch author puts `agent_configuration` into the
profile -> `compile_deep_agent_execution_binding` seals it -> `DeepAgentRuntimeAdapter.execute` ->
`ExactDeepAgentMaterializer.prepare` -> `create_deep_agent(...)`. Middleware rows are appended after
Mission Control's middleware in rank order; provider tools are dict tools passed beside the agent's
tools; model settings are merged into the exact model component before the factory runs. The
`environment_materialized` frame facts gain `model.provider` and `agent_configuration`.

**How to use it:**

```yaml
environment:
  lane: deep_agents
  model: { profile: frontier.anthropic_haiku }
  provider_options:
    deep_agents:
      lane_features:
        todo_list: {}
        context_editing: { trigger_tokens: 60000, keep_tool_uses: 4 }
        call_limits: { model_calls_per_run: 40 }
      model_tools:
        anthropic:
          web_search: { max_uses: 3 }
```

Defaults (`deep_agents.filesystem`, `deep_agents.bash` on sandbox backends, `anthropic.prompt_caching`)
are inserted without being named and appear in the receipt. A row with status `needs_upgrade` or
`planned` is refused at compile with its `requires`. The Anthropic profile needs
`ANTHROPIC_API_KEY` (`Settings.manifest_provider_secret_env` now includes `anthropic`), the pin
`model.claude-haiku-5-5` in `infra/capability-pins/research-capabilities.json` and the model profile
in `deployments/examples/manifest-launch-bindings.deep-agents.example.json`.

**Spend:** the live FX-B-FEATURES run, 0.0020 USD in total (Anthropic claude-haiku-5-5, 4 model
calls, 0.000939 USD; OpenAI gpt-6-luna, 1 call, 0.001073 USD). Ledger:
`.scratch/agent-configuration/spend.jsonl`.

### What changed

| # | Scope | Change | Finished part | Proof |
| --- | --- | --- | --- | --- |
| 8.1 | general | The registry of selectable capabilities: types (axis, domain, facet, mechanism, observability, provenance, status) and rows for Deep Agents (filesystem, bash, todo_list, context_editing, summarization, call_limits; `needs_upgrade` or `planned`: filesystem_permissions, memory, rubric, code_interpreter), OpenAI (web_search, file_search, code_interpreter, compaction, moderation; `needs_upgrade`: auto_mode, model_router) and Anthropic (prompt_caching, web_search, web_fetch, code_execution, bash, memory, clear_tool_uses, compaction; `planned`: text_editor) | `domain/capabilities/features/registry.py`, `deep_agents.py`, `openai.py`, `anthropic.py` | `tests/unit/capability/test_agent_feature_registry.py` |
| 8.2 | general | `mc.agent_configuration.v1`: `AgentConfiguration`, `FeatureSelection` with a config digest, and `resolve_agent_configuration` (defaults inserted explicitly; refusals for an unknown id, an unavailable status with `requires`, `model_tool_provider_mismatch` and an invalid config) | `domain/capabilities/features/configuration.py` | `test_agent_feature_registry.py` |
| 8.3 | deep_agents | Manifest selection `provider_options.deep_agents.lane_features` and `model_tools.{openai or anthropic}`, validated against the registry; `effective_summarization` unifies the old `summarization` key and the `summarization` lane feature | `domain/authoring/provider_options.py` | `tests/unit/authoring/test_deep_agents_lane_adapter_features.py` |
| 8.4 | deep_agents | The lane adapter resolves and receipts every item; new receipt kinds `feature` and `model_tool`; `DeepAgentsAdaptation.agent_configuration` reaches the profile through the launch author | `application/authoring/lanes/deep_agents.py::_agent_configuration`, `domain/execution/materialization_receipt.py` | `test_deep_agents_lane_adapter_features.py` |
| 8.5 | general | `agent_configuration` on `DeepAgentProfile` and `DeepAgentExecutionBinding`, excluded from the digest while absent so earlier digests hold | `domain/execution/contracts.py` | `test_agent_configuration_materialization.py` and the existing digest tests |
| 8.6 | deep_agents | Realization by mechanism: middleware rows appended after Mission Control's middleware in rank order; provider tools as dict tools beside the agent's tools (`MaterializedDeepAgentArguments.provider_tools`); model settings merged into the exact model component before the factory (`_with_model_settings`); `filesystem_replacement` replaces the stock FilesystemMiddleware by name with the effective permissions when the mission configured it | `adapters/deep_agents/features/builders.py`, `materializer.py`, `adapter.py::_compile` | `tests/unit/deep_agents/test_agent_configuration_materialization.py` |
| 8.7 | deep_agents | The `environment_materialized` frame facts gain `model.provider` and `agent_configuration` | `adapters/deep_agents/materializer.py` | `test_agent_configuration_materialization.py` |
| 8.8 | deep_agents | Anthropic as a Deep Agents model provider: `DeepAgentModelComponent.provider` and `PinnedModel.provider` are `openai` or `anthropic`; `AnthropicExactModelFactory` (ChatAnthropic) translates `max_completion_tokens` to `max_tokens` and `reasoning_effort: minimal` to `low`, defaults `max_tokens` to 8192 and refuses `verbosity`, `service_tier` and `use_responses_api`; `model_factory_for(provider)` is used by the Temporal deployment composition and the async subagent graph | `adapters/deep_agents/` model factories, `adapters/temporal/deployment_composition.py`, `adapters/agent_server/async_subagents/graph.py` | `test_agent_configuration_materialization.py`; FX-B-FEATURES (Anthropic leg) |
| 8.9 | general | `Settings.manifest_provider_secret_env` default includes `anthropic: ANTHROPIC_API_KEY`; the pins file gains `model.claude-haiku-5-5`; the example launch bindings gain `frontier.anthropic_haiku` | settings, `infra/capability-pins/research-capabilities.json`, `deployments/examples/manifest-launch-bindings.deep-agents.example.json` | the T0 tests above |
| 8.10 | deep_agents | Live proof FX-B-FEATURES: Anthropic claude-haiku-5-5 with `todo_list`, `context_editing` and `call_limits` called `write_todos`, wrote a file through the file tools and finished; OpenAI gpt-6-luna with `openai.web_search` produced a `web_search_call` content block (provider-executed, never in the tool node) | `tests/integration/deep_agents/test_agent_configuration_live.py` (gate `BELLABS_RUN_AGENT_CONFIGURATION_LIVE=1`) | one paid run, 0.0020 USD; `uv run mypy src/mission_control` clean, ruff clean on the new code |

### Deferred (honest list)

- **R3.1, the manifest spelling.** The selection lives under `provider_options.deep_agents` for now. Whether it moves to a lane-neutral key is an open owner question this slice did not decide.
- **R3.5, frames for server tool calls.** A provider-executed tool call (web search) never passes through the tool node, so it has no tool frame yet. Open owner question.
- **Per-child selection (AC-D8).** The selection applies to the node's agent. A sync child does not choose its own features.
- **`missionctl lane features` and the catalog projection.** Both belong to the proposal (AC-D1..D12); nothing is built.
- **Sync children do not inherit dict provider tools yet.**
- **`anthropic.bash` and `deep_agents.bash` on Docker and host executions** are built but unproven live. Only `sandbox` on a state backend ran, degraded by design.
- **`openai.moderation`** is built but unproven live.

## Turn 7, Stage 3 (2026-10-22): adversarial review, clean code, test gaps, documentation

[SESSION-STAGE-3.md](../../../archive/provider-consolidation-2026-10/sessions/SESSION-STAGE-3.md) on `sprint/tracing-stage-1`, Opus 5.5 lead with Opus 5.5
reviewers and implementers and Sonnet 5.5 for the clean-code review and the documentation.
Commits: `c42afa86` (line endings), `3daa7112` (F-S2-12), `d92516b8` (one maintenance-queue
derivation), `40757e8d` (the review's fixes), then the documents. Merged to `main` and pushed at
the end, as the owner chose.

### Stage 3 finish: what to read first

**One finished part to read** (the most consequential fix): the seed head of a precise fork.
`application/recovery/run_forks.py::SemanticForkService.fork` (the seed now runs inside the saga,
before the receipt) -> `application/recovery/cognitive_seed.py` (the seed key compared without the
locator; the head's message count read from the lane) -> `adapters/deep_agents/time_travel.py::seed_fork`
and `_inject_message` (the point's own pending delta writes are not copied when a message is
injected, so the head is exactly the state at the point plus the message; `_DeltaSnapshot` values
unwrapped) -> `application/execution/run_launch.py` (a seeded fork without its seed refuses to
launch, `fork_seed_pending`). Proofs: `tests/unit/deep_agents/test_fork_seed_head.py` (a
delta-channel graph forked at an intermediate point), `tests/unit/recovery/test_seeded_fork_saga.py`,
and FX-DA-FORK, FX-TR-FORK-CYCLE, FX-TR-FORK-GD.

**The sequence it sits in:** `POST runs/{id}/forks` -> `SemanticForkService.fork` (closure,
`start_position`, the baseline reservation defaulted from the source) -> `RuntimeForkService.fork`
(materialize, then `before_receipt` = the cognitive seed on the maintenance worker, then the
receipt) -> `POST runs/{derived}/launch` -> `run_launch._apply_fork` -> the family workflow ->
the seeded unit resumes from the head.

**How to use it:** `missionctl run fork RUN --at stage:S2,cycle:2 --point P --inject msg.json`
(no `--baseline-reservation` needed any more), then `missionctl run transcript DERIVED --by step`:
the derived `S2@c2`'s first `model_request` carries the conversation as of P, then your message,
and nothing the source did after P.

**Owner decisions (2026-10-22, recorded):** F-S2-12 **terminalize** (a declared wait in front of
unreleasable stages is skipped and the run ends with MP-20's concluded failure); F-S2-10 **default
to the source's baseline**; finalize by **merge to `main` and push**.

**Spend:** the live FX-TR-DISCONNECT re-proof, 0.0066 USD (one Sol call, no cache hit). Stages 2
and 3 together: **0.81 USD**.

### The review

Five read-only reviewers over `63ca7777..52661e57`: R1 settlement paths and idempotency, R2 the
precise fork and the remote saver, R3 the Deep Agents lane's capture and turn stops, R4 the read
model, retention and stream, and a clean-code review. Every finding was verified by its
implementer before it was fixed; four implementers then worked on disjoint files in one checkout
(worktrees would have imported the main checkout's editable install).

| # | Scope | Finding (severity) | Disposition | Finished part | Proof |
| --- | --- | --- | --- | --- | --- |
| 7.1 | general | F-S2-12 (medium): a failed required producer behind a declared wait parked the run forever | fixed, patch `tracing-s3-stagegraph-skip-unreachable-wait` | `adapters/temporal/workflows/stagegraph.py` | `test_tracing_stream.py::test_failed_producer_behind_a_declared_wait_terminalizes`; RRM-007 and replay suites |
| 7.2 | general | Fifteen files flipped LF/CRLF by the sprint's patch helpers (8 223 lines of churn) | fixed | `c42afa86` | `git diff --ignore-cr-at-eol` empty |
| 7.3 | general | Five spellings of the maintenance queue (Stage 1 carry-forward) | fixed | `registration/task_queues.py::maintenance_task_queue` | `test_worker_maintenance.py` |
| 7.4 | general | R1-F1 (high): a fence whose cancel the reducer rejected ended every later model call and units settled `completed` with the stop text | fixed: the model-call check reads the run (`run_fence_stops`); a fenced turn without a journaled cancel retries (`OperationStopFencePending`) | `domain/policies/stop_fence.py`, `application/execution/stop_fence.py`, `operation_execution.py`, `deployment_composition.py` | `tests/unit/operations/test_fenced_turn.py`, `tests/unit/run_control/test_run_fence_backing.py`, FX-TR-CANCEL T0 |
| 7.5 | general | R1-F2 (medium-high): a transient fence-read error settled `failed` with zero usage | fixed: usage, capture and points first; the check fails open | `operation_execution.py::_turn_fence` | `test_fenced_turn.py` |
| 7.6 | general | R1-F4, F8 (medium): the fenced `cancelled` settlement dropped points and could be cut by the heartbeat cancel | fixed: points passed; settlement shielded | `operation_execution.py::_settle_fenced_turn` | `test_fenced_turn.py` (the heartbeat case fails without the shield) |
| 7.7 | general | R1-F5, R3-F3 (medium): fence generation compared with the unit's generation (a generation-2 unit never fenced) | fixed for the three turn readers: the run's execution-target generation and `covers` | `run_fence_generation` | `test_fenced_turn.py` (four generation cases) |
| 7.8 | general | R1-F6 (medium-high): a wrong `output_contract_ref` failed the Goal family and left the run active; 5 reconcile attempts could not ride out a Postgres restart | fixed: folded into `output_unparseable`; `RECONCILE_MAX_ATTEMPTS = 64` | `application/programs/goal_directed.py::_parsed` | `test_goal_schema_completion.py` (+5), `test_goal_output_unparseable.py` |
| 7.9 | general | R1-F10, F12, F14 (low): rollover record fatal; `exhausted` at `>=`; `record_temporal_ids` refused None | fixed (patch `tracing-stage-3-tolerate-rollover-record`) | Goal workflow, `settlement_budget_snapshot`, both repositories | unit tests; replay histories |
| 7.10 | general | R1-F3 (high): a points-write failure blocked the lifecycle settlement (TR-D6 promised an incident) | fixed: savepoint; transition and result commit with a `points_status: incomplete` marker the reconciler repairs | `adapters/postgres/operations/checkpoint_lineage.py`, `cognition_points.py` | Postgres integration (fault and FK violation, verified by the implementer), FX-TR-RECONCILE |
| 7.11 | general | R1-F7, F13 (medium, low): cross-cycle parents derived for records with an external locator; one frame scan per point | fixed | `_resolve` (both repositories), the reconciler pass | `test_point_reconciliation.py`, `test_cognition_points.py` |
| 7.12 | deep_agents | R3-F1 (high, probed): a turn could return an earlier turn's `structured_response` | fixed: only a value this invocation wrote counts (channel version against the source checkpoint) | `adapter.py::_structured_response_written` | `test_structured_output.py` |
| 7.13 | deep_agents | R3-F2 (medium): both stops ran inside the summarizer, so a stopped turn could still pay a summarization call | fixed: the summarizer checks the stops first | `compaction.py`, `adapter.py::_compile` | `test_turn_stops.py` |
| 7.14 | deep_agents | Stage 3 decision: a sync child's calls are also stopped inside the child | built: `StopGuardedSummarizationMiddleware` plus the parent's stops on every child spec; wrap-only, step numbering unchanged | `adapter.py::_subagent_specs` | `test_turn_stops.py`; FX-DA-POINTS, FX-TR-SUB |
| 7.15 | deep_agents | R3-F4 (medium): the budget stop undercounted a resumed turn | fixed: `_TurnSpend.resume_from` | `adapter.py` | `test_budget_stop.py` |
| 7.16 | deep_agents | R3-F5 (medium): parallel `task` calls attributed by order of appearance | fixed: `on_tool_start` binds `tool_call_id` to `tools:<id>` | `frames.py`, `adapter.py::_TaskNamespaceObserver` | `test_deep_agents_frames.py` (reversed order; a real parallel step) |
| 7.17 | deep_agents | R3-F6, R2-14 (medium): a long child namespace raised in-doubt; subagent points of budget-bounded walks lost; first folded usage measured from zero | fixed: bounded, deadline-shared nested walks marked incomplete; true parent usage | `cognition_points.py` | `test_cognition_points_collector.py` |
| 7.18 | deep_agents | R3-F8..F16 (low): hook frame ids depended on other runs; stops indistinguishable in frames; a DENY over a stop counted a turn; no sync fence stop; a fence read fatal; a promotion failure aborted the turn; failure-path log without `exc_info` | fixed | `hooks.py`, `frames.py`, `budget.py`, `writer.py` | `test_kernel_hook_ports.py`, `test_turn_stops.py`, `test_frame_writer.py` |
| 7.19 | general | R4-F6 (medium, security): `frame-body://` downloads were not bound to the run or tenant | fixed: a frame of the path's run in the caller's scope must reference the digest; `nosniff`, `attachment`; `&ref=` removed | `application/frames/artifact_bodies.py`, `PostgresFrameBodyIndex`, `bootstrap/api.py` | `test_artifact_download.py`, FX-TR-STEP-PROJECTION |
| 7.20 | general | R4-F1, F2 (high): expired frames stayed readable through the projection and `--full`; a run never projected lost its deltas | fixed without a migration: retention projects first or holds back (`skipped_unprojected`) and invalidates the projection it expires under; placeholders carry no refs | `adapters/postgres/frames/retention.py`, `transcript.py::keep_expired` | `test_transcript_entries.py`, `test_provider_frames_postgres.py`, FX-TR-RETAIN |
| 7.21 | general | R4-F3..F8 (medium, low): the projection never current for a finished run and never retried; `inline` on truncated JSON; unbounded `--full`; late frames; state moving backwards | fixed | `projection_trigger.py`, `transcript_projection.py`, `transcript.py`, `transcript_entries.py` | `test_transcript_projection_trigger.py`, `test_transcript_full_reads.py` |
| 7.22 | general | R4-F11, F12; Stage 3 items 6 and 7: the CLI paged silently; `run points --limit 5000` got 422; kernel hook pairs dominated `transcript.md` | fixed: the CLI pages; the Markdown collapses consecutive kernel hook pairs (deny, defer and failed stay expanded) | `interfaces/cli/main.py`, `domain/frames/render.py` | `test_transcript_interfaces.py`, `test_transcript_markdown_readable.py` |
| 7.23 | general + deep_agents | R2-1 (high, reproduced): a seeded fork with an injected message continued one step after the point | fixed (the finished part above) | `time_travel.py` | `test_fork_seed_head.py`, FX-DA-FORK |
| 7.24 | general | R2-2, R2-3 (high): typed seed refusals became 500; a derived run could launch without its seed; the same seeded fork twice failed | fixed | `fork_seed.py`, `run_forks.py`, `checkpoint_lineage.py` (both) | `test_fork_seed_runner.py`, `test_seeded_fork_saga.py` |
| 7.25 | general | R2-4..R2-10 (high, medium): Goal Directed forks that could never run (whole-run patch, revisions below `at`, verifier seeds, session mismatch, unreached iteration); upstream cycled stages restarted at cycle 0 | fixed: typed refusals (`fork_position_unavailable`, `cognitive_seed_not_supported`); stages outside the frontier at the source's cycle | `run_forks.py`, `domain/policies/forks.py` | `test_precise_fork.py`, FX-TR-FORK-GD, FX-TR-FORK-CYCLE |
| 7.26 | general | R2-11..R2-15, R2-17, R2-19, R2-21 (medium, low) | fixed: re-snapshot over pre-1.4.4 manifests; a normalised saver locator; a locator-free seed key; an honest kernel route; the admission payload; MCP details; `point_state_missing` 404; narrowed saver errors | various | unit and Postgres integration |
| 7.27 | general | F-S2-10 (owner: default to the source) | built server-side, so HTTP, MCP and CLI agree | `run_forks.py` | `test_cli_fork_baseline.py` |
| 7.28 | general | A Stage 3 digest site (`ProjectionMarks.catch_up_reason` on a JSON dump) | fixed: `stable_json_digest` | `application/frames/search.py` | `test_digest_set_order_guard.py` back to its pre-existing set |
| 7.29 | general | Clean code (the reviewer's items 2, 3, 6, 8, 9, 12, 13, 16, 17, 18 and parts of 14, 20, 21) | done: dead `FullBodyPolicy` and `&ref=`; one transcript merge per projection; the reconciler's wrappers; one registry resolver; one HTTP permission helper and constant; `is_turn_stop`; `_promote`; `_missing`; `_failure_detail`; split `_apply_fork` | - | the suites above |

**Deferred (the honest list of Stage 3):**

- R1-F9, R2-16: command and fork fingerprints changed by 1.4.4's additive fields; a retry that
  straddles an upgrade gets `IdempotencyConflict`. No production installation exists; documented
  on `fork_request_fingerprint`.
- The effect-admission path (`fence_verdict`, `admit_effect`, `budget_controls`, `lane_turns`)
  still compares a unit's generation and ignores whether the cancel was journaled, and an orphaned
  fence denies effects forever. The writer-side fix (retry the cancel, or record the fence
  rejected) needs repository and reducer changes; `test_stop_fence.py:71` asserts the current rule.
- R2-18: `ReusedUnit.source_result_point` and `receipt.seed_point` hold checkpoint ids (locators
  that `find_point(kind="checkpoint")` resolves), kept because the acceptance proofs assert them.
- R2-12's consequence: DSNs spelled `localhost` (or with no host) get a new locator digest, so
  their existing points answer `saver_not_served`; two names for one remote server still differ.
- R4-F2's trade-off: a run that can never be projected holds back expiry of older frames in its
  tenant scope.
- R3-F7 (the batch body is still redacted per call because replay compares its digest), R3-F11
  (`model.turns` spends one extra call), R3-F15 (callback identity fields from the payload),
  R3-F17 (a nested request may land in the previous point's window), R4-F9 (merge cost), R4-F10
  (a frame cursor can change, pre-existing), R4-F13 (the `mc.event.v1` schema version is
  unchanged; CS-D5 is implemented though still listed open).
- Clean-code items 1 (a generic outbox relay for chains and the projection), 4 (digest helpers), 5
  (one time-travel registry factory), 7 (one Deep Agents key parser), 10 (`family_unit_facts` out
  of the adapter), 11 (`point_frames` out of the router), 15 (`HookScope.request_scope`), 19 (the
  CLI's `at` derivation), the renderers out of `application/frames/transcript.py`, and the two
  completion record fields.
- The describe matrix cells Stage 2 proved (`cancel` enforced at the model call; `usage.cost`
  `unknown`; structured output through the tool strategy): the describes are seeded by the common
  SQL release (`test_lane_contracts.py` holds them to 0040/0042), so they ship with release 1.4.5.
- `run inspect`'s run-account `budget` marks a dimension exhausted at `consumed >= hard_cap` (no
  headroom left to reserve), unlike a unit's exceeded rule: deliberate.

### Checks run (2026-10-22, Windows host, at `40757e8d`)

- `ruff check .`, `ruff format --check .` clean (1 981 files); `mypy` clean (856 source files).
- `tests/unit` in four chunks: **5 612 passed**; **28 failed, pre-existing**:
  `test_run2_worker_deploy_script.py` (22, `pwsh`), `test_cursor_local.py` (4, RF-20),
  `test_digest_set_order_guard.py` (2, the same unchanged sites as before, none new).
- `tests/architecture`, `tests/conformance`: green.
- `tests/integration/temporal`: replay histories, RRM-007, RRM-008 operation cancellation, RRM-016
  Goal journaled, WP-BP-010: **52 passed**.
- `tests/integration/postgres`: stop fence (two files), transcript entries, provider frames, run
  forks, checkpoint lineage, FT-F4 fork, transcript, transcript search, terminal frames, budget
  admission, managed budget controls: **31 passed**. `test_realtime_channels_postgres.py` fails
  (Windows ProactorEventLoop in the in-process app) **identically on the tree before Stage 3's
  fixes** (checked in a temporary worktree): pre-existing.
- `tests/acceptance/mission_control`: FX-DA-FORK, FX-TR-FORK-CYCLE, FX-TR-FORK-GD, FX-TR-RETAIN,
  FX-TR-STEP-PROJECTION, FX-TR-REPLAY, FX-TR-STEP, FX-TR-RECONCILE (and its CLI twin), the
  FX-TR-STEP lifecycle half, FX-TR-SUB, FX-TR-HOOK, the blueprint cycle, the four stream T0 twins,
  F-S2-12, the unparseable Goal role, FX-DA-POINTS (both families), FX-DA-INJECT: **all passed**.
  FX-TR-HOOK failed once in three runs (after FX-TR-SUB in one process; the log was not captured)
  and passed alone and in the same pair again: a flake to watch.
- Live: `test_tracing_live.py::test_live_provider_disconnect` **passed** (run
  `a9016667-557e-5bd3-ab95-27f0215e74e9`, on the tree committed as `40757e8d`, 0.0066 USD):
  F-S2-11 is proven live.

### Documents of Stage 3

The knowledge concepts (`provider-frames-and-transcript`, new `transcript-projection`,
`events-and-commands`, `mission-stream`, new `unit-and-point-joinability`, `deep-agents-lane`,
new `deep-agents-turn-stops`, `execution`, `budgets-and-usage`, `interventions`, `recovery`), the
ADR candidates of TRACING-PROPOSAL §C.3 (proposed), the operator guide, the dated
[DEEP-AGENTS-SURFACE-2026-10-22.md](DEEP-AGENTS-SURFACE-2026-10-22.md) (installed 0.7.5, latest
0.7.30), revision 2 of [the output-contracts specification](../../../archive/provider-consolidation-2026-10/specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md)
(OC-D19..D26, subagent and communication obligations, the transfer points) and the
[owner interview](../../../archive/provider-consolidation-2026-10/interview-instructions/OWNER-INTERVIEW-2026-10-22.md) that orders the next sprints.

**The handoff** is the owner interview: it runs before any build session.

## Turn 6, Stage 2 (2026-10-22): real fixtures on GPT-6 Sol and Luna

[SESSION-STAGE-2.md](../../../archive/provider-consolidation-2026-10/sessions/SESSION-STAGE-2.md) on `sprint/tracing-stage-1` (from `720545a4`; the
documents commit `17bd1abf` first), Opus 5.5, one commit per fixture, no push, no merge. The
live harness is `tests/acceptance/mission_control/test_tracing_live.py` (gate
`BELLABS_RUN_TRACING_LIVE=1`) over `tests/fixtures/live_models.py` (Sol parent, Luna sync
child, both through the production `OpenAIExactModelFactory`; a per-call `SpendMeter` that
appends every call to `.scratch/tracing-stage-2/calls/` as it happens) and
`tests/fixtures/stage2_outputs.py` (the owner's §4a files). Model profile digests (the exact
model components the binding seals; settings `reasoning_effort: low`, Responses API,
`streaming`, `stream_usage`): **parent `gpt-6-sol sha256:117d644c…58aa2`**, **child
`gpt-6-luna sha256:9e74dc5f…11b54`** (full digests in each run's `evidence.json`). Prices:
the 2026-10 standard rates (`research/openai-hosted-agents.md` §6), Sol 2.00 / 0.20 cached /
10.00 USD per 1M tokens, Luna 0.10 / 0.01 / 0.50.

### Stage 2 finish (2026-10-22): what to read first

Nine commits on `sprint/tracing-stage-1` after `720545a4`, not pushed, not merged:
`17bd1abf` (the documents), then one per fixture: `2f81b977` (1, F-T3-1), `15ee2747` (2, the
Stage Graph mission with STREAM, RECONCILE-LIVE, RETAIN), `11c56dcd` (3, BUDGET), `5e4a9509` (4,
CANCEL-LIVE), `e1dd436e` (5, the fork from S2 cycle 2), `47f8b171` (6, the Goal Loop and its
fork, ledger only), `5f7a3b45` (7, REMOTE at T0), `0b9727b1` (8, DISCONNECT); the finish
documents follow. **Spend: 0.804 USD of the 12 USD ceiling** (every metered call in
`.scratch/tracing-stage-2/calls/`, the per-run totals in `spend.jsonl`, the recovered 0.0096 in
`spend-adjustments.jsonl`), plus the unknown spend of two cut calls (fixture 8).

**Every fixture of §2, §4 and §4c ran against GPT-6 Sol and Luna** except FX-TR-REMOTE, which
stays T0 by design; every live claim held at the end except two: FX-TR-DISCONNECT's usage and
points after the cut (fixed as 6.17 and proven at T0; the fixture had used its one re-run) and
the Goal Loop's outcome (both runs `failed` because the verifier never receives the executor's
note: the output-contracts problem, parked).

**Findings of Stage 2, by priority** (all fixed in this stage unless marked):

| Id | Severity | Scope | Finding | Fix (row, commit) |
| --- | --- | --- | --- | --- |
| F-S2-1 | high | deep_agents | The lane dropped every structured answer produced through `create_agent`'s structured-output tool (a pydantic instance in `structured_response`, the final message a tool call); likely turn 3's "near miss" too | 6.3, `2f81b977` |
| F-S2-9 | high | general + deep_agents | `cancel --urgency immediate` did not stop a running Deep Agents turn: after the denied tool call the model was called again and the unit settled `completed` under the fence | 6.15, `5e4a9509` |
| F-S2-7 | high | deep_agents | The unit budget was checked only at settlement: a turn ran to its end on 5x its reservation | 6.13, `11c56dcd` |
| F-T3-1 | high | general | A non-parsing Goal executor payload retried without bound | 6.1, `2f81b977` |
| F-S2-2 | high | general | A non-parsing verifier payload ended in a failed family workflow with the run left active | 6.2, `2f81b977` |
| F-S2-11 | high | deep_agents + general | A provider failure mid-turn settled with no usage (spend lost to the budget) and no points | 6.17, `0b9727b1` (T0; live re-proof open) |
| F-S2-6 | medium | general + deep_agents | After an inject, the interrupted turn's points settled without frame ranges; `points:reconcile` on a complete run wrote ranges | 6.10, `15ee2747` (proven live in fixture 5) |
| F-S2-3 | medium | general | The transcript did not show what the model saw: request bodies named prompts by reference only, and the Markdown showed bare titles | 6.5, `2f81b977` |
| F-S2-8 | medium | general | 34 of 54 live request entries were truncated JSON marked `inline` | 6.11, `15ee2747` |
| F-S2-5 | medium | general | Frames retention deleted vanished from the transcript instead of reading `expired` | 6.9, `15ee2747` |
| F-S2-4 | medium | general | Stream envelopes did not name the unit and point of a frame or event | 6.8, `15ee2747` |
| F-S2-10 | medium | general | The owner's `run fork` CLI could not name the derived run's baseline, so the derived run could not be launched with the source's family input | 6.16, `e1dd436e` (whether a fork should default to the source's baseline: open) |
| F-S2-12 | medium | general (open) | A Stage Graph run whose required producer failed waits at a declared human wait for a consumer that can never be admitted (fixtures 3 and 8, attempt 1) | not fixed: family semantics, Stage 3 |
| OC-D4 (parked) | high for the contracts session | general (parked) | A model's `output_refs` replace or stand in for the refs an attempt registered: on the Stage Graph `"output_refs": []` erased S1's outputs (fixture 2, attempt 1); on the Goal Loop the verifier received only the executor's own path and rejected every iteration (fixture 6) | not fixed here (scope guard); §4b |

**Describe matrix: what Stage 2 proved on `deep_agents` (for Stage 3 to flip)**:
`delivery_semantics.cancel` is now enforced at the next **model call** after an immediate cancel
(the fence), with the unit settling `cancelled` (6.15), which is stronger than the declared
`turn_boundary_guaranteed`; `interrupt_and_inject: cancel_and_replace` proven live with the
interrupted and replacement points and their ranges; `fork: emulated` and
`time_travel.fork: R3` proven live for both families (Stage Graph at a stage cycle, Goal
Directed at an iteration) with the message delivered to the seed head; `observe: native`
proven equal to the transcript on the Socket.IO stream; `usage.tokens: settled_per_turn` is
now also enforced inside the turn (6.13) and recorded on a provider failure (6.17), while
`usage.cost: estimated` is not what the lane reports (`cost_micros unknown` on every usage
entry); `hooks` `before_tool` with the catalog hook and the kernel ports proven live; the
lane's structured output through `create_agent`'s tool strategy (6.3) belongs beside
`versions` (deepagents 0.7.5, langchain-openai 1.3.4, Responses API).

**Checks run at the finish (2026-10-22, Windows host, final tree)**: `ruff check .` and
`ruff format --check .` clean (1 975 files); `tests/unit` in five foreground-sized chunks
(5 364 passed, 30 skipped, 2 xfailed) with `tests/conformance`, `tests/architecture` and
`tests/integration/temporal/test_replay_histories.py` (185 passed). **Failed, pre-existing**
(as on `720545a4`): `tests/unit/control_plane/test_digest_set_order_guard.py` (2; every
flagged site is in prerequisites, closed-workflow and journaled-execution code, none of Stage
2's), `tests/unit/harness/test_cursor_local.py` (4, RF-20); the `pwsh` deploy-script tests
deselected. Per-fixture checks are in each fixture entry. **Unrun**: the live re-proof of 6.17;
`tests/integration/postgres` beyond the transcript and frame suites named in fixture 2.

**The handoff** is [SESSION-STAGE-3.md](../../../archive/provider-consolidation-2026-10/sessions/SESSION-STAGE-3.md); the §4b parking lot is filled in
[SESSION-STAGE-2.md](../../../archive/provider-consolidation-2026-10/sessions/SESSION-STAGE-2.md#entries-filled-2026-10-22-from-the-stage-2-transcripts).

**The honest list (Stage 2)**:

- FX-TR-DISCONNECT's two claims fixed by 6.17 are proven at T0 only (§5's one re-run was
  spent); the live re-proof costs about 0.003 USD.
- The budget stop (6.13) sees a sync child's calls only when the parent next calls its model:
  a child task running when the cap is crossed finishes its own calls.
- The fence check (6.15) compares the fence's generation with the unit's execution
  generation, as the kernel fence hook already did; a run-generation versus unit-generation
  distinction is not exercised.
- 6.9 relies on the projection having been written before the expiry: a run never projected
  before its frames expired still loses its delta entries without a placeholder.
- `missionctl run points RUN --limit 5000` (the §4a instruction) exceeds the route's cap of
  500; the owner's files page through every page instead.
- No public route serves `workspace-candidate://` bytes; `outputs/custody/` is read by the
  fixture from custody (AUDIT §A3, specification §3.5).
- The run's `external.openai` budget dimension is never charged by this lane; `currency.*`
  dimensions stay 0.
- The Goal Loop `goal_input` of a derived run is still built by the fixture from the receipt
  (Stage 1's carry-forward); a manifest-driven derived launch is unproven.
- Kernel hook entries are more than half of every transcript (usability, §4b).
- Two disposable databases left by this session's killed runs were dropped; the 30 older
  `mct_*` databases on the cluster (Stage 1 and before) were left alone.

### Fixture 1: F-T3-1 (§2), T0 then live

| # | Scope | Change | Finished part | Proof |
| --- | --- | --- | --- | --- |
| 6.1 | general (F-T3-1) | A Goal Directed executor payload that is missing or does not validate settles as a typed observation `disposition: failed` with `irrecoverable_failure_ref = output_unparseable:<sha256 of error, payload, text>` (specification §3.6); the settlement already observed stands, the verifier sees the failed iteration, convergence stops on the irrecoverable fact. The activity classifies a pydantic `ValidationError` as non-retryable `goal_output_invalid`; the workflow's `reconcile_operation` retry policy is bounded (`RECONCILE_MAX_ATTEMPTS = 5`, was `maximum_attempts=0`; retry attributes are not part of command matching, replay unchanged) | `application/programs/goal_directed.py::GoalDirectedOperationResultService._parsed/_executor_observation`, `adapters/temporal/activities/goal_directed.py::prepare_handoff`, `adapters/temporal/workflows/goal_directed.py` | `tests/acceptance/mission_control/test_goal_output_unparseable.py[executor]` (T0); `test_tracing_live.py::test_live_f_t3_1_prose_executor_settles_failed` (live) |
| 6.2 | general (F-S2-2, found live) | The verifier's non-parsing payload settles the same way (`decision: rejected`, `progress_made: false`, the `output_unparseable` reference): before it, a bounded retry ended in a failed family workflow with the run left `running` (the first live attempt waited out the guard) | `_verifier_observation` (same module) | `test_goal_output_unparseable.py[verifier]` (T0) |
| 6.3 | deep_agents (F-S2-1, found live, high) | The lane dropped a structured answer the model produced: `create_agent`'s structured-output strategy leaves the validated pydantic instance in `structured_response` and the final message carries the `GoalVerifierObservation` tool call, but `_structured_output` accepted only a `dict`. It now dumps a `BaseModel` and falls back to the result snapshot's channel. Turn 3's "near miss" (F-T3-1's origin) is probably the same drop; not re-run | `adapters/deep_agents/adapter.py::_structured_output` | `tests/unit/deep_agents/test_structured_output.py` (2); the live verifier's typed observation reconciled in attempt 2 |
| 6.4 | general | `run inspect` names typed unit failures: `unit_failures [{unit: goal/1/executor, reason: output_unparseable, failure_ref}]`, read from the Goal Directed iteration and verification documents (`UnitFailureReader`, composed beside `points_incomplete`); absent sections stay absent | `contracts/contracts.py::UnitFailureView`, `application/missions/inspection.py`, `adapters/postgres/run_control/inspection_repository.py::PostgresUnitFailureReader`, `bootstrap/composition.py` | both T0 cases and the live proof assert it |
| 6.5 | general (F-S2-3, found reading the live transcript) | The transcript did not show what the model saw: a `model_request` names its system prompt and messages by `frame-body://` reference and `--full` resolved only the frame's own body, so no prompt text appeared in `transcript.jsonl`, `--by step` or `transcript.md`; and the Markdown rendered `message` and `model_request` as bare titles. `--full` now resolves the nested bodies (added as `body` beside each reference); the Markdown quotes each message's text and tool calls (never the encrypted reasoning) and, per model request, the model, step, tools and every prompt part **once**, where the model first saw it | `application/frames/transcript.py::_with_request_bodies`, `domain/frames/render.py::_message_lines/_request_lines` | `tests/unit/frames/test_transcript_markdown_readable.py`; `tests/unit/frames` (211); the regenerated T0 `transcript.md` shows the system prompt, the objective and the answers |
| 6.6 | deep_agents | `streaming` is an allowed exact OpenAI model setting (the live profile streams, so `messages`-mode chunks reach the delta retention class; §0) | `adapters/deep_agents/materializer.py::OpenAIExactModelFactory` | the live runs record `message_delta` frames |
| 6.7 | fixture | Live overrides on the tracing fixture (`UNIT_RESERVATION`, `STAGE_OBJECTIVES`, `GOAL_OBJECTIVES`, `GOAL_SCHEMA_DIGESTS`; T0 defaults unchanged), the scripted Goal role's prose answer (`MISSION_CONTROL_TECHNICAL_PROSE_ROLE`), `SCOPED_PROOF_TOKEN_SECONDS`; the §4a writer (missionctl over loopback for the transcript views, `run inspect`, every points page, `run artifact` for every output reference, and the workspace candidates read from custody and labelled so, because no public route serves `workspace-candidate://` bytes yet, AUDIT §A3) | `tests/fixtures/rrm009_production_stack.py`, `live_models.py`, `stage2_outputs.py` | the runs below |

Runs (spend recorded before the next run started):

| Run | Tier | Outcome | Spend |
| --- | --- | --- | --- |
| `f-t3-1-t0-executor` | T0 | executor prose → `failed/output_unparseable`, each `reconcile_operation` attempt 1, run terminal `failed`, `unit_failures` names it (55 s) | 0 |
| `f-t3-1-t0-verifier` | T0 | verifier prose → typed rejection, run terminal `failed` | 0 |
| `9455b783-990c-5cb2-b17d-b8df5b1243fb` (live attempt 1) | T2 | executor prose settled `failed`; the verifier's structured answer was dropped by the lane (6.3), its reconcile failed bounded and the family workflow failed with the run left active; killed by the 590 s guard before the meter flushed. Spend recovered from the run's `turn_ended` frames on the left-over database `mct_e8e8456a27` | 0.0096 USD (`.scratch/tracing-stage-2/spend-adjustments.jsonl`) |
| `922aa870-a6e1-5843-b506-d55756a8da5d` (live attempt 2, worker `17bd1abf` + this diff) | T2 | **passed**: Sol executor wrote `/goal/1/executor/work/note.md` and answered two sentences of prose → `failed/output_unparseable:sha256:824b9a87…`; the Sol verifier answered through the structured tool, `rejected`; both `reconcile_operation` activities attempt 1; run `completed/terminal`, execution outcome `failed`; 64 s | 6 Sol calls, 20 139 in (19 185 cached) / 453 out: **0.0103 USD** |

| `9f77dba6-f421-53c3-a97f-31ffcd840812` (live attempt 3, after 6.5) | T2 | **passed** again, re-run only so the owner's `transcript.md` carries the prompts and answers (6.5): same shape, 62 s | 5 Sol calls, 16 505 in (15 769 cached) / 391 out: **0.0085 USD** |

Files for the owner: `.scratch/tracing-stage-2/f-t3-1-live/9f77dba6-f421-53c3-a97f-31ffcd840812/`
(`transcript.md`, `transcript.jsonl`, `transcript-by-step.jsonl`, `transcript-by-iteration.jsonl`,
`mission.json`, `inspect.json`, `evidence.json`, `outputs/custody/…note.md`); attempt 2's
files (`922aa870-…`) are the pre-6.5 rendering. The T0 runs' files are under
`f-t3-1-t0-executor/` and `f-t3-1-t0-verifier/`. Stage spend after fixture 1: **0.0284 USD**.

Checks for fixture 1 (commit `2f81b977`): `ruff check`/`format` clean; `mypy` on the changed
modules; `tests/architecture` with `tests/unit/{orchestration,deep_agents,frames,mission_control}`
(768); `tests/integration/temporal/test_replay_histories.py` with
`tests/unit/{run_control,operations}` (463, after fixing
`test_ft_f6_inspection.py::test_existing_clients_keep_parsing_the_inspection_body`, which
already failed on `720545a4`: Stage 1's `points_incomplete` was missing from its list of
optional sections); `tests/unit/{workspaces,streams,subscriptions,recovery,authoring}` (780,
10 POSIX skips); the two T0 and the live acceptance proofs above.

### Fixture 2: the Stage Graph mission live (§4 item 1) with FX-TR-STREAM, FX-TR-RECONCILE-LIVE, FX-TR-RETAIN

`test_tracing_live.py::test_live_stage_graph_mission`: the FX-TR tracing blueprint
(`S1 -> S2 -> {S3, S4}`, `StageCyclePolicy(max_cycles=3)` on S2) with live objectives (a WAL
durability brief; each stage asks the Luna child once, calls `lookup_binding_marker`, writes
its record under `/workspace/output`, ends with its JSON), S2 cycled by **the model's own
evaluation** (cycle 0 and 1 answer `evaluation: cycle` with a `Brief cycle N` objective, cycle 2
accepts), one `interrupt_and_inject` into S1's running turn after its second call, a Socket.IO
client subscribed from launch. Two cycles were kept (the brief said one) because §4 item 2 forks
at `stage:S2,cycle:2`. Reservations per unit 150 000 tokens / 24 turns; ceilings 3 M tokens.

| # | Scope | Change | Finished part | Proof |
| --- | --- | --- | --- | --- |
| 6.8 | general (F-S2-4, FX-TR-STREAM) | The stream did not say whose a frame or event is: `provider_frames` envelopes carried `after_point_ref` and no `unit_key`; `mission_events` envelopes (`mc.event.v1`) carried neither of the 1.4.4 joinability columns. Frame envelopes now carry `unit_key` (the execution's attempt -> activation key, read once per execution by `PostgresStreamSource.executions` into `ExecutionRef.unit_key` / `StreamPosition.unit_key`); event envelopes carry `unit_key` and `point_ref` from `mission_event` (absent when null, so run-level bodies are unchanged). The stream has no `after_point_ref` subscribe parameter: a client resumes from a point by taking the cursor of the last frame before the first frame whose `after_point_ref` is that point | `adapters/realtime/stream_source.py`, `application/streams/{ports,service}.py`, `domain/subscriptions/contracts.py`, `adapters/postgres/subscriptions/store.py` | `tests/acceptance/mission_control/test_tracing_stream.py::test_fx_tr_stream_t0` (T0, 1 140 frames = transcript, 100 points in order, resume exact) and live |
| 6.9 | general (F-S2-5, FX-TR-RETAIN) | Deleted deltas vanished from the Transcript instead of reading `expired`: the placeholder existed only for frames a mission event cites, and no event cites a delta (Stage 1's T0 never had a delta to delete). The persisted projection is now the record of what was there: `keep_expired(projected, fresh)` turns every provider-frame entry whose frame left the store into a `frame_expired` placeholder at its own cursor (`body.state: expired`), on re-projection (`TranscriptProjector.project`) and on a read while the projection is behind (`_current_entries`). A first version used arrival-ordinal gaps and was withdrawn: the frame store keeps gaps where deduplicated provider keys kept their ordinals (one appeared at the inject, ordinals 47..49, before any expiry) | `application/frames/transcript.py::keep_expired`, `application/frames/search.py`, `adapters/postgres/frames/transcript_entries.py::projected_entries` | `tests/unit/frames/test_keep_expired.py` (2); live: 20 deltas deleted, every one reads `expired` |
| 6.10 | general + deep_agents (F-S2-6, FX-TR-RECONCILE-LIVE) | After an `interrupt_and_inject`, the interrupted turn's points settled without frame ranges: the replacement turn's recorder never saw those frames, so it gave the points no keys, and `points:reconcile` on a complete run then wrote ranges (live: 2 points of S1; T0: 5). The key rule the reconciler applies (`frames_of_point`: a root key names the checkpoint it followed, the result checkpoint, or its step) moved to the domain and the settlement writer applies it to a root point the recorder gave no keys, reading the thread's stored frames in the same transaction | `domain/execution/cognition_points.py::frames_of_point/frame_range_of`, `adapters/postgres/operations/cognition_points.py::_resolve`, `application/execution/operations/point_reconciliation.py` (delegates) | `test_tracing_stream.py::test_fx_tr_reconcile_after_inject_t0`: failed before (`frame_ranges_filled: 5`), passes after (0, ranges unchanged); live proof in the fork fixture's source run (§4 item 2) |
| 6.11 | general (F-S2-8, found reading the live transcript) | 34 of the 54 live `model_request` entries said `body.state: inline` while their excerpt was cut at the list cap (2 048 characters; bodies ~3 KB): the state is computed from the frame's whole stored excerpt and the entry was cut afterwards, so the JSON was truncated and `--full` (6.5) had nothing to resolve; the injected operator note was therefore invisible in the transcript. Entries of the full-body kinds (model request, message, tool result, run result) keep the whole body the frame stored; other kinds keep the cap | `application/frames/transcript.py::_entry_excerpt` | `tests/unit/frames` (213); the fork fixture's source transcript must contain the injected note |
| 6.12 | fixture | `tests/fixtures/stream_capture.py` (the namespace mounted on the started app, a client that acknowledges as it reads, `compare` against the transcript), `test_tracing_stream.py` (the T0 twins), the live mission test and the owner's step and replay files | `tests/fixtures/stream_capture.py`, `test_tracing_live.py` | below |

Runs:

| Run | Tier | Outcome | Spend |
| --- | --- | --- | --- |
| `fx-tr-stream-t0` | T0 | first pass: `unit_key` on every frame, events carry `unit_key`/`point_ref`; differences were the turn-opening frames (written before the first checkpoint, no `after_point_ref`: listed, not failures) and the child's frames (subscribe with `include_descendants`); then passed (132 s) | 0 |
| `85a2a071-eae8-531b-b550-9ad229d366f7` (live attempt 1) | T2 | S1 ran (inject applied, `interrupted`/`replacement_start` points), then the run terminalized `failed`: the fixture had told the model to end with `"output_refs": []`, which the Stage Graph merges over the result and so erased the refs the attempt registered (AUDIT §A4/§D4, OC-D4: parked in §4b, not fixed here); the instruction no longer names the key | 0.017 USD |
| `cfc84d11-6ad6-557d-8e35-a19dc3d04403` (live attempt 2, worker `2f81b977`) | T2 | **completed** in 238 s: ten units (`S1@c0`, `S2`/`S3`/`S4` at cycles 0..2); S2 cycled twice on its own evaluation ("Brief cycle 1: Clarify how WAL-before-data ordering ...", "Brief cycle 2: Sharpen the distinction between ... synchronous ... and asynchronously acknowledged commit"), accepted at 2; inject receipts `accepted -> queued -> delivered -> observed -> applied`, S1 roles include `interrupted`, `replacement_start`; FX-TR-SUB 40 nested child points, `subagent_ended` frames; FX-TR-HOOK the catalog hook on all 10 MCP calls; FX-TR-STEP `--by step --point b794289c… --full` holds the whole 13 107-byte tool result; `replay --dry-run` **exact** (`batch_digest` `sha256:022d99c4…` reconstructed); FX-TR-STREAM 1 198 frames received = 1 198 in the transcript, 105 points in order, resume from a point boundary exact (65 frames); FX-TR-RETAIN 20 `message_delta` frames, all deleted, 1 178 step frames kept (with 6.9 every deleted delta reads `expired`; the run itself used the withdrawn gap rule); FX-TR-RECONCILE-LIVE **failed**: 0 points, 2 frame ranges written (6.10), transcript digest and `written_by` unchanged | 53 calls (41 Sol, 12 Luna), Sol 217 427 in (166 821 cached) / 4 574 out, Luna 17 667 in / 1 621 out: **0.181 USD** |
| `fx-tr-reconcile-t0` | T0 | reproduced 6.10 (5 ranges), then passed with the fix (0) | 0 |

Files for the owner: `.scratch/tracing-stage-2/stage-graph-live/cfc84d11-6ad6-557d-8e35-a19dc3d04403/`:
`transcript.md` (252 KB, written before 6.8's whole bodies, so later model requests show only
the model, step and tools line), `transcript.jsonl`, `transcript-by-step.jsonl`,
`transcript-by-stage.jsonl`, `mission.json` (blueprint, objectives, inject, launch, inspect,
every point), `inspect.json`, `step-b794289c-74e7-5720-89c1-d6c05949420f.jsonl` (the
tool-calling step of S1 with the whole tool result), `replay-b794289c-….json`,
`stream-report.json`, `evidence.json`, `outputs/custody/` (the ten stage records: S1 facts,
three S2 briefs, three S3 summaries, three S4 risk lists). Stage spend after fixture 2:
**0.227 USD**.

Checks for fixture 2: `ruff`, `mypy` on the changed modules; `tests/unit/{frames,streams}` and
`tests/architecture` (262); `tests/unit/{operations,subscriptions,socketio,coordinator,
run_control}` with `tests/integration/postgres/{test_transcript_entries,
test_provider_frames_postgres}.py` (621); `test_tracing_stream.py` (2, final code, 348 s).

### Fixture 3: FX-TR-BUDGET (§4c)

`test_tracing_live.py::test_live_budget_cap`: the two-stage blueprint (`draft` -> declared wait
-> `review`), `tokens.total` reserved per unit at 5 000 (one Sol call carries a ~3 000-token
prompt), run ceiling 20 000.

| # | Scope | Change | Finished part | Proof |
| --- | --- | --- | --- | --- |
| 6.13 | deep_agents (F-S2-7) | The unit budget was checked only at settlement, so a turn that crossed its reservation kept calling the model to its natural end (live: 25 892 tokens and 8 calls on a 5 000-token reservation, the cap crossed at call 3) and then settled `failed/budget_exceeded`. `BudgetStopMiddleware` wraps the model call (no added graph node: step and checkpoint numbering unchanged) and answers instead of the model once the invocation's spend, read from the chat-model observer the settlement charges (parent and in-process children), **exceeds** a bounded dimension (`tokens.total`, `model.turns`; reaching a limit exactly stays within budget): the turn ends after the call that crossed the cap, a child task already running finishes its own calls, and the attempt settles `budget_exceeded` as before. The stop message is marked `mc_budget_stop` and is not a model turn. A first version (a `before_model` hook stopping at "reached") added a graph node and broke the recovery suites' step positions; replaced | `adapters/deep_agents/budget.py`, `adapters/deep_agents/adapter.py` (wiring, `_ModelCallObserver.spent`, `_usage`) | `tests/unit/deep_agents/test_budget_stop.py` (3); `tests/unit/{deep_agents,operations,run_control,mission_control}` and `tests/architecture` (675); live |
| 6.14 | general | The result point's `budget_snapshot` names the bound `limits`, the `exhausted` dimensions and the settlement's `failure_code`; `run inspect` gains a `budget` section (`BudgetView`: per dimension hard cap, reserved, consumed, pending, `exhausted`; the run's account from `canonical.budget_state`, which only the runtime-inspection route served before) | `application/execution/operations/operation_execution.py`, `contracts/contracts.py::BudgetView`, `application/missions/inspection.py::BudgetViewReader`, `adapters/postgres/run_control/inspection_repository.py::PostgresBudgetViewReader`, `bootstrap/composition.py` | live; `test_ft_f6_inspection.py` lists `budget` among the optional sections |

Runs:

| Run | Tier | Outcome | Spend |
| --- | --- | --- | --- |
| `3ca78df1-9385-51db-9272-f1d36d66fe48` (before 6.13) | T2 | **failed** the fixture: the draft settled `failed` (usage 25 892 tokens, 8 turns: 4 Sol, 4 Luna) and `review` was not admitted, but the spend ran to the turn's end; `run inspect` had no budget state | 8 calls: **0.0173 USD** |
| `48485d3e-bede-5dac-8942-132d713609ae` (after 6.13/6.14) | T2 | **passed**: two Sol calls (2 965, then 3 100 tokens: the cap crossed at the second, which asked the child), the Luna child's one call, then the stop ("Mission Control ended this turn: the operation budget is exhausted (tokens.total)."); draft `failed`, result point `{usage: 7 927 tokens / 3 turns, limits: {tokens.total: 5000, ...}, exhausted: [tokens.total], failure_code: budget_exceeded}`; `run inspect` `budget.dimensions[tokens.total] = {hard_cap: 20000, consumed: 7927}`; `review` not admitted | 3 calls: **0.0043 USD** |

Observed, not changed: after the draft failed, the run stayed `running` in phase `waiting`
(this blueprint declares a human wait before `review`); the run-level outcome of a failed
required producer behind a declared wait is the family's, recorded for Stage 3. The run's
`external.openai` dimension (hard cap 20) is never charged by this lane.

Files: `.scratch/tracing-stage-2/fx-tr-budget/48485d3e-bede-5dac-8942-132d713609ae/` (and the
pre-fix `3ca78df1-…/`): `transcript.md` (the stop message closes the draft's turn),
`transcript.jsonl`, `transcript-by-step.jsonl`, `transcript-by-stage.jsonl`, `mission.json`,
`inspect.json` (with `budget`), `evidence.json`, `outputs/custody/`. Stage spend after fixture
3: **0.248 USD**.

### Fixture 4: FX-TR-CANCEL-LIVE (§4c)

`test_tracing_live.py::test_live_cancel_immediate`: the two-stage blueprint with a long draft
(eight `write_file` calls, then the MCP tool, then the answer); `cancel --urgency immediate`
after the draft's second model call.

| # | Scope | Change | Finished part | Proof |
| --- | --- | --- | --- | --- |
| 6.15 | general + deep_agents (F-S2-9; WP-TR-2's observation) | An immediate cancel reaches the operation Activity only through its next heartbeat, so a short turn finished first: the fence denied the next tool call, the model was then called once more, and the unit settled `completed` under a persisted fence (the stop-fence report never reached `provider_acknowledged`/`settled`). Two changes. The lane asks the fence before every model call (`FenceStopMiddleware`, the same wrapper shape as 6.13; `StopFenceGate.run_fenced` over `KernelHookFenceGate.run_fence`, the run generation's persisted fence, no effect needed), so a fenced run calls the model no more. The governed body, when a turn returns under a fence persisted for its generation and run control journaled the cancel, settles the unit `cancelled` through the existing `_settle_cancelled` (usage of the completed calls recorded, the fence milestones written) instead of `completed` | `adapters/deep_agents/budget.py::FenceStopMiddleware`, `adapters/deep_agents/hooks.py`, `adapters/deep_agents/materializer.py`, `application/execution/stop_fence.py::run_fence`, `application/execution/operations/operation_execution.py::_fenced_after_turn` | `test_tracing_stream.py::test_fx_tr_cancel_t0`: without the change two more model calls and `completed`; with it none and `cancelled`; live |

Runs:

| Run | Tier | Outcome | Spend |
| --- | --- | --- | --- |
| `bb1c72fe-9e4a-55a4-97cf-9310de869a11` (before 6.15) | T2 | **failed** the fixture: fence persisted 22:03:45.10, the next `write_file` denied by `mc.stop_fence` at 22:03:47.58, one more `model_request` at 22:03:47.63, the draft settled `completed` (4 turns, 12 342 tokens); the run's outcome `cancelled`; `operation.cancel` retried while the live attempt held the lease (by design, `operation_execution_in_progress`) | 4 calls: **0.0079 USD** |
| `9d6e6e66-ae8d-5901-b62e-9fe3f23725e3` (after) | T2 | **passed**: fence persisted 22:13:07.60, the tool call the in-flight answer requested denied at 22:13:11.04, no `model_request` and no completed tool call after the cancel, the draft settled `cancelled` (3 turns, 9 100 tokens), the stop-fence report `settled` with `provider_acknowledged_at` and `settled_at` | 3 calls: **0.0067 USD** |

Files: `.scratch/tracing-stage-2/fx-tr-cancel-live/9d6e6e66-ae8d-5901-b62e-9fe3f23725e3/` (and
the pre-fix `bb1c72fe-…/`): `transcript.md` (the deny `hook_result` closes the turn),
`transcript.jsonl`, `transcript-by-step.jsonl`, `transcript-by-stage.jsonl`, `mission.json`,
`inspect.json`, `evidence.json` (the four fence timestamps), `outputs/custody/`. Checks:
`tests/unit/{deep_agents,operations,run_control,harness}` with `tests/architecture` (890 passed;
the 4 failures are the pre-existing `test_cursor_local.py` RF-20 set). Stage spend after
fixture 4: **0.263 USD**.

### Fixture 5: the fork from S2 cycle 2 (§4 item 2, FX-TR-FORK-CYCLE live)

`test_tracing_live.py::test_live_fork_from_s2_cycle_2`. Each live test owns a fresh database, so
the fork's source is its own run of fixture 2's mission (with the same inject into S1, which
also makes it the live proof of 6.10); then the owner's command over loopback HTTP,
`missionctl run fork SOURCE --at stage:S2,cycle:2 --point P --inject msg.json --from-snapshot
… --sponsorship-ref … --approval-ref … --baseline-reservation tokens.total=40`, with P the
middle seedable root step of the source's `S2@c2`, and the derived run launched with the fork's
semantic input binding and run to completion.

| # | Scope | Change | Finished part | Proof |
| --- | --- | --- | --- | --- |
| 6.16 | general (F-S2-10) | The owner's fork command could not be followed by a launch: a CLI fork admits the derived run with no baseline reservation (the HTTP route accepts `baseline_reservations`, the CLI had no flag), and `run_launch` then refuses the family input that carries the source's baseline (`409 budget_mismatch`). Stage 1's CLI proof checked only the receipt. `missionctl run fork --baseline-reservation DIMENSION=AMOUNT` (repeatable) passes it through. Whether a fork should default to the source's admitted baseline is left to Stage 3 | `interfaces/cli/main.py::fork_body` | `tests/unit/run_control/test_cli_fork_baseline.py` (2); live attempt 2 |

Runs:

| Run | Tier | Outcome | Spend |
| --- | --- | --- | --- |
| source `02839ca9-5181-539f-93fd-47cba45d8290` (attempt 1) | T2 | the source completed and the fork answered its receipt; the derived launch was refused `409 budget_mismatch` (6.16); only `state-as-of-6fe962fd-….json` was written | 58 calls: **0.1843 USD** |
| source `455c660c-fd90-575f-ba85-a35f18f5520b`, derived `7ae62697-9bcb-5f9a-a065-6f7d32f1467e` (attempt 2) | T2 | **passed** (457 s). Source: ten units, S2 cycled twice on its own evaluation, the inject into S1 applied and **visible in the transcript** (6.11), `points:reconcile` writes **0 points and 0 frame ranges** with the transcript digest and `written_by` unchanged (**6.10 proven live**). Receipt: `frontier_requested [S2]`, `frontier_closed [S2, S3, S4]`, `reused_units` = the source `S1@c0` with its result point `1f1ce66f-…`, `seed_point 1f1ce675-…` (P), `message_delivery seed_head`, `start_position {workflow_cycle_ordinal: 0, stage_cycle_ordinals: {S2: 2}, stage_objectives: {S2: "Brief cycle 2: Make the distinction between replayed physical changes and committed, visible transactions even clearer."}}`. Derived: units exactly `S1@c0` (one `reused` point), `S2@c2`, `S3@c0`, `S4@c0`, run `completed`; `S2@c2`'s first root input point descends from the `fork_seed` point, its last human message is the injected instruction; its first `model_request` carries 7 messages (P had 3): the copied conversation, the injected message, then the stage prompt again (the packet turn follows the injected message, as Stage 1 found) | 74 calls (55 Sol, 19 Luna), source 0.185 + derived 0.059: **0.2434 USD** |

Files: source `.scratch/tracing-stage-2/fork-s2-c2-live/455c660c-fd90-575f-ba85-a35f18f5520b/`
(`transcript.md`, `transcript.jsonl`, `transcript-by-step.jsonl`, `transcript-by-stage.jsonl`,
`mission.json`, `inspect.json`, `state-as-of-b4890ac0-d224-5474-a9fa-9ce3d574b725.json` (the seed
point P), `outputs/custody/` (ten stage records)); derived
`.scratch/tracing-stage-2/fork-s2-c2-live/7ae62697-9bcb-5f9a-a065-6f7d32f1467e/` (the same views,
`mission.json` with the fork receipt, `evidence.json`, `outputs/custody/` with the derived S2
brief, which has the injected `synchronous_commit = off` paragraph, S3 and S4). Stage spend
after fixture 5: **0.691 USD**.

### Fixture 6: the three-iteration Goal Loop and its fork at iteration 2 (§4 item 3, FX-TR-FORK-GD live)

`test_tracing_live.py::test_live_goal_loop_and_fork`: `goal_blueprint(max_iterations=3)`, Sol as
executor and verifier with their registered structured-output schemas (`response_format`; the
lane keeps the pydantic answer since 6.3), the executor writing a WAL note into its work slot
each iteration, the verifier told to reject at iterations 1 and 2 and judge on the merits at 3;
then a fork over HTTP at `{iteration: 2, session_generation}` from the iteration-2 executor's
seedable input point with an injected message, the derived run launched through the fixture's
`goal_input` with the receipt's `derived_goal_revision_id` and `start_position` (Stage 1's
carry-forward: the launch author reads them from the receipt). The source was not patched (the
WP-TR-4 fail-closed reuse case was not entered). No code change in this fixture.

| Run | Tier | Outcome | Spend |
| --- | --- | --- | --- |
| source `21449cb9-b227-5eea-a944-0d5664aadb84`, derived `3dea6a17-2ca0-5276-ae8e-9a3aa3c741ad` | T2 | **passed** the fork claims (214 s). Source: executor and verifier at iterations 1, 2, 3 (six units), every observation through the structured tool (no `output_unparseable`). Receipt: `message_delivery seed_head`, `seed_point 1f1ce68a-…`, `start_position {goal_iteration: 2, session_generation: 1, agent_run: 2}`, `derived_goal_revision_id sha256:77ce756c…`, `reused_units` = the iteration-1 executor and verifier. Derived: iteration 1 one `reused` point per role; the iteration-2 executor's first input point descends from the `fork_seed` point with the injected message as its last human message; the iteration-2 verifier ran fresh; iteration 3 ran; the run terminal. **Both runs ended `failed`**: the verifier never received the executor's note (it was named only by the executor's own `output_refs` path, `read_file /goal/N/executor/work/note.md`, 0 bytes, "unresolved executor output"), rejected all three iterations and the loop stopped at its limit. That is AUDIT §A4/§D4 on the Goal Loop (OC-D4), parked for the contracts session (§4b), not fixed here | 37 Sol calls, 193 050 in (170 063 cached) / 2 914 out; source 0.064 + derived 0.045: **0.1091 USD** |

Files: source `.scratch/tracing-stage-2/goal-loop-live/21449cb9-b227-5eea-a944-0d5664aadb84/`
(`transcript.md`, `transcript.jsonl`, `transcript-by-step.jsonl`, `transcript-by-iteration.jsonl`,
`mission.json`, `inspect.json`, `state-as-of-3a2a23b5-15d1-5183-8f92-08ca53a37cb7.json` (the seed
point), `outputs/custody/` (the three notes)); derived
`.scratch/tracing-stage-2/goal-loop-live/3dea6a17-2ca0-5276-ae8e-9a3aa3c741ad/` (the same views,
`mission.json` with the fork receipt, `evidence.json`, `outputs/custody/` with the iteration 2
and 3 notes rewritten for the on-call reader the injection asked for). Stage spend after
fixture 6: **0.800 USD**.

### Fixture 7: FX-TR-REMOTE (§4 item 5, T0)

Stage 1's `test_tracing_remote.py::test_fx_tr_remote` (the saver behind the delaying
`SaverProxy`, a 1 ms points-walk budget, the saver cut for the reads) on the final Stage 2 code,
now also writing the owner's files. **Passed** (88 s, 0 USD); no change beyond the files.
Files: `.scratch/tracing-stage-2/fx-tr-remote-t0/ee824d88-e3f5-56b1-82be-005167f90851/`
(`transcript.md`, `transcript.jsonl`, `transcript-by-step.jsonl`, `transcript-by-stage.jsonl`,
`mission.json`, `inspect.json` with `points_incomplete`, `evidence.json`; read with the saver
cut).

### Fixture 8: FX-TR-DISCONNECT (§4c, last)

`test_tracing_live.py::test_live_provider_disconnect`: every provider connection through a
loopback HTTP `CONNECT` tunnel (`tests/fixtures/tcp_proxy.py::ConnectProxy`, `HTTPS_PROXY`,
loopback excluded); one second into the second model call of the run every open tunnel is
severed (one tunnel, `api.openai.com:443`). There is no retry classifier for provider errors;
the outcome is recorded as it happened.

| # | Scope | Change | Finished part | Proof |
| --- | --- | --- | --- | --- |
| 6.17 | deep_agents + general (F-S2-11) | A provider failure mid-turn settled the unit `failed` with **no usage** (`usage: {}`, although the call that completed before the cut spent 2 953 tokens) and **no points** (the turn's frames survived with no point to belong to). `RuntimeInvocationFailure` now carries the usage of every call the chat-model observer saw complete (parent and in-process children, the operation's bound dimensions) and the points of the partial lineage up to the latest durable checkpoint (collected with the recorder, best effort); the failed settlement records both | `domain/execution/errors.py::RuntimeInvocationFailure`, `adapters/deep_agents/adapter.py::_observed_usage` and the failure path, `application/execution/operations/operation_execution.py` | `test_tracing_stream.py::test_fx_tr_disconnect_t0` (the scripted parent fails its call after the first tool result, `MISSION_CONTROL_TECHNICAL_FAIL_AT_TOOLS`): without the change `usage: {}` and 0 points, with it `{model.turns: 2, tokens.total: 10}` and points holding the frames; `tests/unit/{deep_agents,operations,run_control}` and `tests/architecture` (533) |

Runs:

| Run | Tier | Outcome | Spend |
| --- | --- | --- | --- |
| attempt 1 (two-stage blueprint, 22:40 UTC) | T2 | the cut hit the Luna child's call: `httpx.RemoteProtocolError: peer closed connection without sending complete message body (incomplete chunked read)`; the turn recorded an `error` frame and `run_result {status: error, error_type: RemoteProtocolError}`; the attempt settled `failed` (`RuntimeInvocationFailure (RemoteProtocolError)`) after one attempt, no retry; then the Stage Graph set the declared human wait before `review` (`workflow_run.set_wait`) and the run waited instead of terminating (as in fixture 3; recorded for Stage 3, F-S2-12). The test's wait raised `TimeoutError`, which it did not catch, so no files were written; the facts above come from the run's database while it waited | 1 completed Sol call: **0.0023 USD**; the cut Luna call reported no usage (unknown, under 0.001 USD at Luna rates) |
| `6172cc20-53b6-51d5-8b1c-c117171d4779` (attempt 2, the four-stage blueprint, no declared wait) | T2 | **failed the fixture on 6.17's two claims**, everything else held: the cut hit the second call 1 s in; the error is typed (`RemoteProtocolError`, `error` and `run_result` frames); one attempt, no retry (bounded); S1 settled `failed`; the run reached `terminal` with outcome `failed` in 10 s; the frames of the cut turn survived (session, request, delta, the `task` call); but the settlement recorded `usage: {}` and the turn had no points. 6.17 was then made and proven at T0; the fixture had used its one re-run, so the live re-proof is left to Stage 3 (`BELLABS_RUN_TRACING_LIVE=1 pytest …::test_live_provider_disconnect`, about 0.003 USD) | 1 completed Sol call: **0.0024 USD**; the cut call unknown, as above |

Files: `.scratch/tracing-stage-2/fx-tr-disconnect/6172cc20-53b6-51d5-8b1c-c117171d4779/`
(`transcript.md` ends with the `error` and `run_result` frames, `transcript.jsonl`,
`transcript-by-step.jsonl`, `transcript-by-stage.jsonl`, `mission.json`, `inspect.json`,
`evidence.json` with the tunnel and the cut). Stage spend after fixture 8: **0.804 USD**
(metered calls 0.795 + the recovered 0.0096), plus the two cut calls' unknown spend.

## Turn 5, Stage 1 (2026-10-21): the tracing work packages

[SESSION-STAGE-1.md](../../../archive/provider-consolidation-2026-10/sessions/SESSION-STAGE-1.md) run under [PROCESS.md](../../PROCESS.md) against
[TRACING-PROPOSAL.md](../../../archive/provider-consolidation-2026-10/proposals/TRACING-PROPOSAL.md) on the sprint branch `sprint/tracing-stage-1`
(from `main` at `63ca7777`); one commit per work package, no push, no merge, spend 0 USD.
Subagents ran the independent streams after each shared step; the acceptance proofs ran
serially on the production offline stack (real PostgreSQL 17 on release 1.4.4, local Temporal,
production workers, scripted cognition).

### WP-TR-1: joinable, transactional, lifecycle-complete (general)

The sequence a settlement follows now reads: `operation.execute` -> adapter -> `collect_points`
-> `CheckpointLineageService.record_result(..., points)` -> **one** Postgres transaction
(`checkpoint_transition`, `unit_result_observation`, `cognition_point` rows with
`budget_snapshot`, `cycle_start`/`rollover_start` parents) -> `operation_settlement` ->
`FrameFactProjector` -> `mission_event{activation_id, unit_key, point_ref}`; the family's
`result_decided` writes `completion_decision` and `completion_candidate` in the family
transaction; `POST runs/{id}/points:reconcile` re-derives missing points from the saver.

| # | Scope | Change | Finished part | Proof |
| --- | --- | --- | --- | --- |
| 5.1 | general | Release **1.4.4** (`packages/mission-control-db-contract/releases/1.4.4`, fingerprint `sha256:dcb652ba...`): `0047_transcript_joinability` (`mission_event.unit_key`, `point_ref`; `cognition_point.subordinate_ref`, `restore_level`, `pruned_at`, `prune_policy`; the five new frame kinds, the closing rule with `subagent_ended`, the generated `retention_class`; `frame_retention_policy.step_retain_days`, `prune_mode`; `expire_provider_frames` narrowed to the delta class and `expire_step_provider_frames` for terminal runs; the `mission_run.temporal_*` column grant; the completion table grants and the family writer's `activation` read), `0048_transcript_entry` (`transcript_entry`, `transcript_projection_state`), `0049_frame_body_refs` (the `frame-body://` scheme on the columns). `scripts/prepare_release_144.py` reproduces the tree. Audit correction: the proposal's 0047 replaced only the closing rule; the inline `kind` CHECK is replaced too | `scripts/release_144/0047_transcript_joinability.sql` | `tests/integration/postgres/test_run2_release_144.py` (fresh, from 1.4.3, from 1.3.0, retention class and expiry: 4 passed) |
| 5.2 | general | Contracts: `FrameKind` gains `model_request`, `environment_materialized`, `subagent_started`, `subagent_ended` (closing), `progress_note` (reserved); `FULL_BODY_KINDS` and `DELTA_RETENTION_KINDS`; the Deep Agents raw kinds; point roles `cycle_start`, `reused`, `subagent_root`; `CheckpointPoint` is a root checkpoint or a nested one naming its `subordinate_ref`; `CognitionPointObservation.workspace_checkpoint_ref`, `native_observed_at`; `CognitionPointRecord.pruned_at`; `DomainEventEnvelope.unit_key`, `activation_id`, `point_ref` (unserialized when unset) | `domain/frames/contracts.py`, `domain/execution/cognition_points.py`, `domain/policies/contracts.py` | `tests/unit/frames`, `tests/unit/operations/test_cognition_points.py` |
| 5.3 | general (TR-D6) | The settlement transaction: `CheckpointLineageRepository.record_result(result, transition=, points: PointBatch)` inserts the transition, the result and the point rows on one connection (`record_points_in`); a points failure rolls everything back and raises (`checkpoint_lineage_conflict`; the unit goes `in_doubt`); the logged-not-raised path is gone; `budget_snapshot` (settled usage, reservation id) on the result point; `cycle_start` and `rollover_start` parents resolved from the location alone; `subordinate_ref` and `restore_level` columns written. Test-only fault `MISSION_CONTROL_TEST_POINTS_FAULT` (`skip` or `raise`) | `application/execution/operations/checkpoint_lineage.py` -> `adapters/postgres/operations/checkpoint_lineage.py` -> `adapters/postgres/operations/cognition_points.py` | `tests/unit/operations/test_cognition_points.py` (one-call settlement, rollback, cross-cycle parents); FX-TR-STEP (lifecycle half) |
| 5.4 | general | The reconciler: `PointReconciler.reconcile` (`mc.points_reconciliation.v1`: `generations_checked`, `points_added`, `frame_ranges_filled`, `pruned`, `saver_unreachable`) over `CheckpointLineageRepository.list_run_generations` and the new `TimeTravelLane.collect_points` port (Deep Agents: the recorder-less `walk_points`); frames attributed by key (step, result checkpoint id) and, on a re-derivation, bracketed by the checkpoints' own `ts` against the frames' `observed_at` (same worker clock); `written_by = reconciler`; `POST .../runs/{id}/points:reconcile` (`workflow_run.reconcile_unit`), `missionctl run points RUN --reconcile [--unit-key K]`, MCP `mission_run_points_reconcile` | `application/execution/operations/point_reconciliation.py` | `tests/unit/operations/test_point_reconciliation.py` (6); **FX-TR-RECONCILE** and its CLI form (passed) |
| 5.5 | general (TR-D7) | Joinable events: `LifecycleCommand.unit_key`, `activation_id`, `point_ref` stamped by the reducer onto every event it emits (frame-fact events take the action's activation and per-fact point refs; `FrameFactTarget.unit_key` from the adapter and the lane turns); `canonical.append_events` and `append_mission_events` bind the three columns; admission, result and cycle commands carry the unit key; run-level events keep NULLs | `domain/policies/reducer.py`, `adapters/postgres/run_control/canonical.py`, `application/frames/reducer.py` | `tests/unit/run_control/test_transcript_joinability.py` (5), `tests/unit/frames/test_frame_facts.py`; FX-TR-STEP (lifecycle half) |
| 5.6 | general (TR-G9) | Lifecycle writers: `StageOperationAdmissionProposal.released_by` (`StageReleasedBy` per dependency, producer identity and unit key) and `continues_from` (`StageContinuesFrom`, the prior cycle's attempt and result refs); `GoalFamilyDecisionMutation.released_by` (`GoalReleasedBy`, a contract); `completion_decision` and `completion_candidate` written inside the family transaction (`CompletionRecords` on the Stage Graph mutation; `PostgresCompletionRepository` for the Goal Directed verifier), `decision_key = mutation_id` / `verification_id`, `candidate_key = operation_settlement_id(binding_id)`, dispositions mapped (`admit` to `accepted`, `cycle` to `needs_more_work`, `degrade`/`escalate`/cancel to `abandoned`, else `rejected`), unused columns NULL; `record_rollover` action and `workflow_run.record_rollover` event before each Goal Directed `continue_as_new` (patch `tracing-record-rollover-1.4.4`); `mission_run.temporal_workflow_id/run_id` recorded at launch (`RunControlRepository.record_temporal_ids`; a rebind is refused `temporal_identity_conflict`) | `application/programs/service.py`, `adapters/postgres/orchestration/completion_repository.py`, `adapters/postgres/run_control/run_control_repository.py`, `application/execution/run_launch.py` | `tests/unit/orchestration` (`test_stagegraph_v2`, `test_completion_validation_service`, `test_wp_bp_020_goal_directed`), `tests/unit/run_control/test_run_launch.py`, `tests/integration/temporal/test_replay_histories.py` (24); FX-TR-STEP (lifecycle half) |
| 5.7 | general (P5.5) | The `reused` point: `_settle_reused` records one point per unit a fork settles by reference (`roles=("reused",)`, `source="fork"`, `parent_coordinate` = the source result point, `written_by="fork_seed"`) | `application/execution/operations/operation_execution.py::_settle_reused` | `tests/unit/operations/test_fork_reuse_execution.py` |
| 5.8 | general (found by the first real cycle) | Three kernel defects the FX-TR fixture exposed, none of them tracing code: (a) `apply_cycle` recorded the cycle policy's usage against no reservation (`reservation_required`); it now records it against the run's standing `baseline` reservation; (b) a cycled stage re-materializes its workspace with the next Context Packet: `stage_cycle_workspace_slots` admits the same writable slots with a later cycle's inputs as one manifest revision (entries at the same paths replaced, no second reservation) and the filesystem provisioner replaces a stale read-only mount whose governed content changed; (c) the operation failure log names the error type and, for Mission Control's own idempotency and materialization errors, the message | `domain/execution/materialization.py::stage_cycle_workspace_slots`, `application/artifacts/workspace_materialization.py`, `adapters/storage/filesystem_workspace.py` | `tests/unit/workspaces/test_goal_role_slot_ownership.py::test_stage_workspace_is_materialized_again_by_the_next_cycle`; the tracing smoke proof |
| 5.9 | fixture | The FX-TR fixture: `tracing_stage_blueprint()` (`S1 -> S2 -> {S3, S4}`, `StageCyclePolicy(max_cycles=3)` on S2), the scripted stage answer carrying `evaluation: cycle` at S2's cycles 0 and 1 from the operation id, the `StageGraphTracing` family tag, the tracing ceilings; the fixture grant gains `workflow_run.reconcile_unit`; `tests/conftest.py` lists `test_tracing.py` among the psycopg selector modules | `tests/fixtures/rrm009_production_stack.py`, `tests/acceptance/mission_control/test_tracing.py` | the four proofs below |

Proofs on the production offline stack (T0, zero spend, 2026-10-21, release 1.4.4):

- **Tracing smoke** (`test_tracing_blueprint_cycles_s2_twice_and_completes`, 82 s): ten units
  (`S1@c0`, then `S2`/`S3`/`S4` at cycles 0, 1, 2: the workflow applies a pending cycle only
  when nothing is active, so `S3@c0` and `S4@c0` settle before the first cycle), two
  `cycle_decided` mutations, the run completes.
- **FX-TR-RECONCILE** (`test_fx_tr_reconcile`, `test_fx_tr_reconcile_cli`): with
  `MISSION_CONTROL_TEST_POINTS_FAULT=skip` every settled generation has its transition and no
  point rows; `points:reconcile` (and `missionctl run points RUN --reconcile`) restores every
  stamped root checkpoint as a `written_by = reconciler` row with its frame range.
- **FX-TR-STEP, lifecycle half** (`test_fx_tr_step_lifecycle_half`): every frame-derived
  event (`session.*`, `tool_call.completed`) carries `activation_id` and `unit_key`; the
  admission events carry the unit key; a `completion_decision` per settled stage unit keyed
  by the result mutation id with its candidate keyed by the operation settlement id; the
  S2 cycle-1 and cycle-2 input points carry `cycle_start` and the previous cycle's result as
  `parent_coordinate`; S2@c1's proposal carries `continues_from`, S3's `released_by`;
  `mission_run.temporal_*` set. (`attempt.completed` is not a frame-derived event on this
  lane: the attempt outcome is deferred to the operation settlement.)
- The four **FX-DA** proofs stay green on 1.4.4 (17-83 s each).

### Checks run (2026-10-21, Windows host, after WP-TR-1)

- **Passed**: `ruff check .` and `ruff format --check .`; `mypy` on the 40 changed source
  modules; `tests/architecture`; `tests/unit/{operations,deep_agents,recovery,run_control,
  orchestration,frames,runtime,harness,authoring,workspaces,streams,subscriptions,temporal,
  mission_control,context,effects,continuation,coordinator,chains,control_plane,capability}`
  and `tests/conformance` (in foreground chunks: 1937 + 402 + 897 + 110 passed);
  `tests/integration/temporal/test_replay_histories.py` (24); the release proof (4); the
  eight acceptance proofs above.
- **Failed, pre-existing** (identical on `main` at `63ca7777`): the four
  `tests/unit/harness/test_cursor_local.py` closing-facts cases (RF-20); the two
  `tests/unit/control_plane/test_digest_set_order_guard.py` audits (unaudited sites in the
  prerequisites, closed-workflow and journaled-execution modules; this sprint's one site was
  made set-order independent); `tests/unit/runtime/test_run2_worker_deploy_script.py`
  (`pwsh` not on PATH, deselected).
- **Unrun**: `tests/unit` as one job (the host's memory reaper stops it; run in chunks), T2.

### WP-TR-2: capture completeness (deep_agents, with the general promoter)

The sequence an attempt follows now reads: `materializer.prepare` (manifest facts, real
kernel hook ports, the callback endpoint minted) -> `recorder.begin` -> the
`environment_materialized` frame -> per model call `_ModelRequestObserver` ->
`model_request` frame (per-message objects promoted once by digest, the batch under
`full_requests`) -> `message` / `tool_call_*` (oversized bodies promoted to
`frame-body://`) -> `subagent_started` ... the child's own frames and points ...
`subagent_ended` -> `hook_invoked`/`hook_result` from the stream sink -> `collect_points`
(root and nested) -> settlement; every frame's key names the root point it followed
(`after_point_ref` on the stream).

| # | Scope | Change | Finished part | Proof |
| --- | --- | --- | --- | --- |
| 5.10 | deep_agents (TR-G1, TR-D2) | `_ModelRequestObserver` (`run_inline`, on every `config["callbacks"]`): at `on_chat_model_start` the exact batch `[system, *messages]`, the bound tools and `invocation_params` become one `model_request` frame per call (`langgraph.step/node/checkpoint_ns`, model name and provider, per-message ids and digests, tool schema digests, `tool_choice`, `follow_up`, `batch_digest`, `call_index`); human and system message objects promoted once per attempt by digest, the whole batch under the `full_requests` profile; the observer's work is drained by the recorder before the next stream part, so the request frame precedes its response frames | `adapters/deep_agents/adapter.py::_ModelRequestObserver` -> `adapters/deep_agents/frames.py::model_request_capture` | `tests/unit/deep_agents/test_model_request_observer.py` (three calls through a real `create_deep_agent`, standard and `full_requests`); **FX-TR-STEP** |
| 5.11 | general (TR-D2a, TR-D3) | The capture profile and the promoter: `application/frames/capture_policy.py` (`FrameCapturePolicy`, `standard` and `full_requests`, `capture_profile(name)`, `FrameCapture`), chosen by the deployment setting `MISSION_CONTROL_FRAME_CAPTURE_PROFILE` (`bootstrap/frame_capture.py::compose_frame_capture`), never by a manifest; `FrameWriter(capture=, promoter=)` and `promote_object`; `adapters/storage/frame_body_promoter.py::PayloadStoreFrameBodyPromoter` over the content-addressed payload store, emitting exactly `frame-body://sha256:<hex>?bytes=<n>&type=<media>`; the three payload stores derive the address of a digest (`address_for`), so the granted body reader resolves a bare reference under `workflow.result.read` and verifies the bytes; the profile recorded as `harness_execution.native_identity.frame_capture_profile`. `FullBodyPolicy` stays as a compatibility shim | `application/frames/capture_policy.py` -> `application/frames/writer.py` -> `adapters/storage/frame_body_promoter.py` -> `application/frames/artifact_bodies.py` | `tests/unit/frames/test_capture_policy.py`, `test_frame_body_promoter.py`, `test_frame_writer.py` (round trip under the grant); FX-TR-STEP (`full=true` resolves a 12 KiB tool result) |
| 5.12 | deep_agents (TR-G4, TR-D4) | Real kernel hook ports in the deployment composition: `StopFenceShim(KernelHookFenceGate(PostgresStopFenceRepository))`, `HookIntentLedgerShim(PostgresHookIntentLedger)`, `StreamFrameSink` (`mc.hook_invoked`/`mc.hook_result` through the graph's stream writer, kernel ids first) and `StreamUsageRecorder` (`mc.usage`, now a Deep Agents raw kind); `HookContext` carries the namespace, the workspace root and a `HookCallbackEndpoint` minted at `prepare` through `HookCallbackService` with a `deep_agents` mapper (identity over `mc.hook_input.v1`); catalog hook script bundles reach the registry from `DeploymentCapabilityComponents.hook_scripts`; the subprocess runner falls back to a worker thread where the event loop cannot spawn (Windows selector loop) | `adapters/deep_agents/hooks.py` (ports, shims, sinks) -> `adapters/temporal/deployment_composition.py::compose_kernel_hook_ports` -> `adapters/deep_agents/materializer.py::_hook_dispatcher` | `tests/unit/deep_agents/test_kernel_hook_ports.py` (12), `test_hook_middleware.py`, `test_hook_graph.py`; **FX-TR-HOOK** |
| 5.13 | deep_agents (TR-G5, TR-D5) | Subagents as steps: a `task` call brackets `subagent_started` and `subagent_ended` (closing; usage summed from the child's frames); the recorder keeps per-namespace checkpoint windows; `collect_points` walks every `tools:<id>` namespace the recorder observed and yields nested points with `subordinate_ref`, `parent_locator` = the root step that spawned the child and the `subagent_root` role; the reducer derives `subordinate.started/ended` facts (`domain/frames/facts.py`) from the closing frame | `adapters/deep_agents/cognition_points.py::_subagent_points`, `adapters/deep_agents/frames.py` | `tests/unit/deep_agents/test_cognition_points_collector.py` (real saver, one child); **FX-TR-SUB** |
| 5.14 | deep_agents (TR-G8, TR-D8) | The environment: `MaterializedDeepAgentArguments.manifest_facts` (skills, MCP servers, model, state and sandbox files) plus the Context Packet files the adapter seeds become the `environment_materialized` frame (files with slot, bytes, digest and destination; manifest digest) and the input point's `channel_facts.materialization_digest`; the result point's `workspace_checkpoint_ref = workspace-candidates://{execution}/{generation}#<digest>` over the registered candidates; `read_as_of` lists sandbox uploads with `source` and the `materialization_digest` (`withheld` names an unread manifest when no frame reader is composed on the API) | `adapters/deep_agents/frames.py::materialization_manifest`, `adapters/deep_agents/time_travel.py::read_as_of` | `tests/unit/frames/test_deep_agents_frames.py` (digest stable across prepares); FX-TR-STEP (environment question) |
| 5.15 | general (TR-D7) | Every Deep Agents frame key carries the last root checkpoint the recorder had seen; the Socket.IO `provider_frame` payload gains `after_point_ref` and `lane_profile`; the frame-fact events of every closing frame carry a `point_ref` (`relation: result` from `turn_ended`/`run_result`, `relation: after` from the key otherwise); the reconciler attributes frames by key first (begin frames to the input point) and by time only for frames recorded before 1.4.4 | `application/frames/streams.py::deep_agents_after_point_ref`, `application/frames/reducer.py::checkpoint_point_refs`, `application/execution/operations/point_reconciliation.py::attribute_frames` | `tests/unit/frames/test_frame_facts.py`, `tests/unit/operations/test_point_reconciliation.py`; FX-TR-STEP, FX-TR-RECONCILE |
| 5.16 | fixture | A stdio MCP server fixture (`tests/fixtures/rrm009_mcp_server.py`) whose `lookup_binding_marker` answers 12 KiB under the pinned schema digest; a catalog hook script (`rrm009.annotate`, `before_tool`, allow plus `additional_context`) bound to the tracing family; `close_saver(stack)`; the API registers the granted body reader; the fixture grant gains `workflow_run.admin`; the FX-DA helpers index root points only | `tests/fixtures/rrm009_production_stack.py`, `tests/fixtures/scoped_api_stack.py` | the proofs below |

Proofs on the production offline stack (T0, zero spend, 2026-10-21, release 1.4.4):

- **FX-TR-STEP** (`test_fx_tr_step`, 87 s): for every root point of S2 cycle 1 and the child's
  points, the `model_request` frames in the point's range list ids whose bodies resolve (AI
  and tool digests match their frames; six human and system objects read back through the
  bare `frame-body://` reference); the 12 886-byte tool result is promoted and whole under
  `full=true`; `environment_materialized` names `/.mission/inputs.json`,
  `/.mission/context.md` and the Skill file with digests equal to the state's and the input
  point's `materialization_digest`; the lifecycle facts; `frame_capture_profile == standard`;
  `workspace_checkpoint_ref` set; with the API's saver connection closed the transcript and
  points routes still answer (`state-as-of` raises through the route: the typed 503 is
  WP-TR-5's).
- **FX-TR-SUB** (`test_fx_tr_sub`, 86 s): `subagent_started` at ordinal 18, the child's
  `model_request` at 25, `subagent_ended` at 42 with its usage, all inside the parent step's
  window; the child's points carry `subordinate_ref`, `input`/`subagent_root`, and the
  parent step's root point as parent. The lineage graph's `visibility` is not served over
  HTTP (stream only); unasserted.
- **FX-TR-HOOK** (`test_fx_tr_hook`, 105 s): per tool call the `hook_invoked`/`hook_result`
  frames carry the kernel ids first (`mc.stop_fence`, `mc.operation_intent`,
  `mc.frame_capture`, `mc.usage`) then `rrm009.annotate`; the usage port's frames equal the
  observer's counts and the settlement's; after `cancel --urgency immediate` the stop fence
  port denies the next tool calls (`hook_result` deny frames) with the fence persisted.
  **Observed, not asserted:** the run still ended `completed` (the operation cancel retried
  on `operation_execution_in_progress`); the owner's call for the review stage.
- The four WP-TR-1 proofs and the four **FX-DA** proofs stay green on the integrated tree.

### Checks run (2026-10-21, Windows host, after WP-TR-2)

- **Passed**: `ruff check .` and `ruff format --check .`; `mypy` on the 24 changed source
  modules; `tests/architecture`; `tests/unit/{frames,deep_agents,operations,streams,
  subscriptions,run_control,recovery,workspaces,harness}` (in foreground chunks: 1083 and
  1149 passed); the eleven acceptance proofs above (one stack at a time).
- **Failed, pre-existing**: the four `tests/unit/harness/test_cursor_local.py` cases (RF-20).
- **Unrun**: `tests/unit` as one job, T2.

### WP-TR-3: read model and retention (general)

The sequence a settlement follows now reads: `_commit_settlement` writes the result, the
points and one `transcript_projection` outbox intent in the settlement transaction -> the
relay on the maintenance worker leases the intent and starts `mc.transcript_project.v1` ->
`TranscriptProjector.project` merges the run's events, frames and points into
`mc.transcript_entry.v2` entries (each placed by unit and point) and replaces the run's
`transcript_entry` rows and its `transcript_projection_state` row in one transaction ->
reads serve the stored rows while the state row equals the live marks, the live merge
otherwise -> `transcript?by=step|stage|iteration`, `points/{pid}/frames`, `artifacts/{ref}`
and `points/{pid}/replay` read that model; `frames.expire` deletes the delta class only.

| # | Scope | Change | Finished part | Proof |
| --- | --- | --- | --- | --- |
| 5.17 | general (TR-D10, P4.1) | `mc.transcript_entry.v2`, additive over v1: `entry_seq`, `unit_key`, `activation_id`, `attempt_no`, `node_key`, `cycle`, `iteration`, `session_generation`, `point_id`, `parent_point_id`, `subordinate_ref`, `reused_from`, `body` (`state` inline/excerpt/artifact/expired/pruned, `bytes`, `media_type`, `artifact_ref`), `execution` (harness execution, generation, arrival ordinal, native turn, Temporal ids), `refs.point_ref`; `TranscriptQuery.by/point/unit`, `TranscriptGroup`, `TranscriptPage.groups`; `merge(..., points=)` places every entry by the run's cognition point index (`_PointIndex`: the root point whose range holds the frame's ordinal, its unit and parent) and numbers `entry_seq` by position; `group_entries(level, unit_facts=)` builds the step, stage and iteration groups; the stage group's facts carry `released_by`, `continues_from`, the result decision and the cycle decision from the family admission journal and the completion row (`FamilyFactsReader`; Stage Graph identities only) | `domain/frames/transcript.py` -> `application/frames/transcript.py::merge`, `entries_v2`, `group_entries` -> `adapters/postgres/frames/transcript_reads.py::PostgresFamilyFactsReader` | `tests/unit/frames/test_transcript_v2.py` (12), `test_transcript.py` (goldens regenerated); FX-TR-STEP (projection) |
| 5.18 | general (P4.2) | Commands and routes: `GET transcript?by=&point=&unit=&full=`, `GET points/{pid}/transcript`, `GET points/{pid}/frames` (the frames of the point's range and their entries), `GET artifacts/{ref}` (the verified bytes of a `frame-body://` or governed reference under `workflow.result.read`, the media type of the reference, `413 payload_too_large` above the cap); `missionctl run transcript --by --point --unit --full`, `run artifact RUN REF --out FILE`, `run replay RUN --point ID --dry-run [--out]`; MCP `mission_run_transcript(by, point, unit)`, `mission_run_point_frames`, `mission_run_replay`; `CognitionPointReadService.frames_for_point` over the frame reader and the granted body reader composed with it (`501 frame_reader_unavailable` without them) | `interfaces/http/transcript.py`, `interfaces/http/artifacts.py`, `interfaces/http/cognition_points.py`, `interfaces/cli/main.py`, `interfaces/mcp/{transcript_tools,cognition_point_tools}.py`, `application/execution/cognition_point_reads.py` | `tests/unit/frames/test_transcript_interfaces.py`, `test_artifact_download.py` (4); FX-TR-STEP (projection), FX-TR-REPLAY (CLI) |
| 5.19 | general (TR-D11, P4.3) | Replay, dry run only: `ReplayService.dry_run` selects the point's `model_request` frame at `call_index`, reconstructs its batch from the frames and the promoted objects (`source` per message: `frame`, `object`, `missing`), digests it with `domain/frames/body.py::batch_frame_body` (the one rule; the Deep Agents observer now digests through it too) and answers `mc.replay_report.v1` (`batch_digest_recorded`, `batch_digest_reconstructed`, `exact`, `first_difference`, the batch under `include_batch`); `dry_run=False` answers `paid_replay_not_available` | `application/frames/replay.py` -> `domain/frames/body.py::batch_frame_body` | `tests/unit/frames/test_replay.py` (9); FX-TR-REPLAY |
| 5.20 | general (TR-D10, P3.9) | The persisted projection: `PostgresTranscriptEntries.replace` (one transaction per run under a run-keyed advisory lock: delete, set-based inserts of 250 rows per statement, the row count re-read before the `transcript_projection_state` row is written; `current_entries` answers only while the state row equals the live marks), `live_marks`; the settlement writes the `transcript_projection` outbox intent; `TranscriptProjectionRelay` leases intents (`FOR UPDATE SKIP LOCKED`, lease owner, retry on failure) and starts `mc.transcript_project.v1` on the maintenance queue, `TranscriptProjectionPump` drives it; `TranscriptProjectionActivities.project` runs `TranscriptProjector.project` (search documents, then the entries) per run; `POST transcript/refresh` runs the same projector on demand; the maintenance worker registers the workflow and the activity and starts the relay | `adapters/postgres/operations/operation_journal.py::_commit_settlement` -> `application/frames/projection_trigger.py` -> `adapters/temporal/activities/transcript_projection.py` -> `application/frames/search.py::TranscriptProjector` -> `adapters/postgres/frames/transcript_entries.py` -> `bootstrap/worker.py::transcript_projectors` | `tests/unit/frames/test_transcript_projection_trigger.py` (7), `tests/integration/postgres/test_transcript_entries.py` (3); FX-TR-STEP (projection: the state row within seconds of completion without a refresh) |
| 5.21 | general (P8a, TR-D1) | Retention classes: `FrameRetentionPolicy.step_retain_days` (NULL: the step clock never runs) and `prune_mode` (`delete`; `tombstone` reserved for TR-D17, prunes nothing); `PostgresFrameRetention.expire` runs the narrowed `expire_provider_frames` (deltas only, 0047) and `expire_step_provider_frames(now - step_retain_days)` when set; the report carries `expired_delta`, `expired_step`, `step_retain_days`, `prune_mode`; `frames.expire` activity and `mc.frames_expire.v1` carry them; a deleted delta reads `body.state == "expired"` in the transcript | `adapters/postgres/frames/retention.py` -> `adapters/temporal/activities/frames_expire.py` | `tests/unit/frames/test_frame_retention.py` (4), `tests/integration/postgres/test_provider_frames_postgres.py` (delta and step counts, purge); FX-TR-RETAIN |
| 5.22 | fixture | The scoped stack's maintenance worker serves `mc.transcript_project.v1` and runs the relay (`lease_owner = scoped-proof-transcript-projection`); `projection_snapshot` reads the state row, `max(seq)` and the rows under one REPEATABLE READ snapshot; the FT-C1 golden regenerated for v2; T3's three proofs | `tests/fixtures/scoped_api_stack.py`, `tests/acceptance/mission_control/test_tracing.py` | the proofs below |

Proofs on the production offline stack (T0, zero spend, 2026-10-22, release 1.4.4):

- **FX-TR-RETAIN** (`test_fx_tr_retain`, 81 s): with `retain_days = 1` and the expiry clock
  400 days ahead, `mc.frames_expire.v1` on the maintenance queue deletes nothing of the step
  class (1 140 step frames before and after; every `model_request`, `message`, `tool_call_*`,
  `environment_materialized`, `subagent_*`, `hook_*` id survives a terminal run) and reports
  `expired_delta = 0`, `expired_step = 0`, `step_retain_days = null`, `prune_mode = delete`;
  the re-projected transcript shows no `expired` entry. **Unexercised:** the scripted model
  writes no delta frames (no `_stream`), so the "deltas deleted and read `expired`" half runs
  against an empty class; a streaming fixture is Stage 2's.
- **FX-TR-REPLAY** (`test_fx_tr_replay`, 85 s): at the tool-calling step of `S2@c1`,
  `GET points/{pid}/replay?include_batch=true` answers `mc.replay_report.v1` with
  `exact: true`, both digests `sha256:797f31fc…` (the `model_request` frame's `batch_digest`
  at `call_index 1`), six messages from `frame` and `object` sources, `first_difference`
  null; `missionctl run replay RUN --point ID --dry-run` prints the same report over loopback
  HTTP; with the API's saver connection closed the route still answers it.
- **FX-TR-STEP (projection)** (`test_fx_tr_step_projection`, 89 s): the state row lands
  0.2 s after completion without a refresh (the outbox-released trigger; 1 308 entries through
  seq 168); after `POST transcript/refresh` the row reads `projected_through_seq 170 ==
  max(seq)`, 1 310 rows all `mc.transcript_entry.v2`, `entry_seq` 1..1310, one `projected_at`
  across the rows and equal to the state row's; every frame entry of `S2@c1`'s root points
  carries its `point_id`, `unit_key`, `node_key S2`, `cycle 1`; `by=step&point=` returns one
  group of that point's cursors; `by=stage` one group per unit with `S3@c2`'s `released_by`
  and decision; `GET transcript` equals the rows; `points/{pid}/frames` is the point's range;
  `artifacts/{ref}` streams the 12 886-byte tool result with its digest; `run artifact` and
  `run transcript --by step --point ID --full` print the same bytes and the step group.
- The seven earlier tracing proofs (blueprint 88 s, reconcile 81 s, reconcile CLI 86 s,
  lifecycle half 87 s, step 83 s, sub 82 s, hook 101 s) and the four FX-DA proofs (187 s
  together) stay green on the integrated tree, run three proofs per foreground job.

What this package found on the way (the honest list):

- **A stalled bulk write.** asyncpg 0.31's pipelined `executemany` of the 1 310 projection
  rows stalled mid-batch under the test's Windows selector loop: the server sat in
  `ClientRead` inside the open transaction for over ten minutes with the Python process idle
  (`py-spy`: the loop in `select`), the refresh then waiting on the advisory lock. `replace`
  now writes set-based `INSERT ... SELECT FROM unnest(...)` statements of 250 rows and
  re-reads the run's row count before the state row is written, so a partial batch can never
  commit. One earlier run (before that change) read 1 268 of 1 310 rows with `entry_seq`
  gaps under the old write path; it was observed once, is not reproduced since, and its
  mechanism is not established. The proof now reads state, marks and rows under one
  REPEATABLE READ snapshot.
- **A one-off lock timeout** (`LockNotAvailableError` on a `mission_run` row during one
  run of the projection proof, 2026-10-21 21:52); not reproduced in eleven later runs. The
  disposable cluster keeps `log_lock_waits = on`, `deadlock_timeout = 500ms` and
  `log_min_duration_statement = 1000` (ALTER SYSTEM) so a recurrence leaves a trace.
- `PostgresFamilyFactsReader` maps Stage Graph identities only; Goal Directed stage groups
  carry the event facts without `released_by`.
- `prune_mode = tombstone` is reserved (TR-D17): it prunes nothing until the tombstone writer
  exists. No pruning, no `pruned` body state is written yet.
- The relay runs on every maintenance worker with a fixed lease owner per worker and no
  deployment setting to disable it; the search documents stay the v1 projection.
- From WP-TR-2, still observed and not asserted: a run completes after
  `cancel --urgency immediate`; `state-as-of` with the saver closed raises through the route
  (the typed 503 is WP-TR-5's).

### Checks run (2026-10-22, Windows host, after WP-TR-3)

- **Passed**: `ruff check .` and `ruff format --check .` (1 951 files); `mypy` on the 28
  changed and new source modules; `tests/architecture` with `tests/unit/{frames,operations}`
  (477); `tests/unit/{deep_agents,streams,subscriptions,run_control,recovery,workspaces}`
  (642, 10 POSIX skips); `tests/unit/{harness,mission_control}` (503);
  `tests/unit/{temporal,orchestration,control_plane}` (458);
  `tests/integration/postgres/{test_run2_release_144,test_provider_frames_postgres,
  test_transcript_entries}.py` (14); the ten tracing proofs and the four FX-DA proofs.
- **Failed, pre-existing**: the four `tests/unit/harness/test_cursor_local.py` cases
  (RF-20); the two `tests/unit/control_plane/test_digest_set_order_guard.py` audits.
- **Unrun**: `tests/unit` as one job (killed by the host's memory reaper), T2.

### WP-TR-4: the precise fork (general, with the Deep Agents seed head)

The sequence a fork follows now reads: `POST /runs/{id}/forks` with `at`, `cognitive_seed`,
`message` and `frontier_policy` (or `missionctl run fork RUN --at stage:S2,cycle:2 --point
ID --inject msg.json`) -> `SemanticForkService.prepare` resolves the seed point, derives
`at` from it when absent, closes the frontier over the source blueprint (`close`) or refuses
a narrower one (`strict`), computes the reuse decisions (Stage Graph by frontier; Goal
Directed by iteration under the minted revision) and the start position -> the saga admits
the derived run and records the receipt -> the cognitive seed copies the source lineage to
the point and puts the seed head whose `messages` write is the injected message ->
`POST /runs/{derived}/launch` fills `start_position` from the receipt -> the family starts
there: Stage Graph candidates of the `at` stage at its cycle with the source's objective,
Goal Directed iterations below the position settled by reference, the executor of the
position pinned to the seeded role thread.

| # | Scope | Change | Finished part | Proof |
| --- | --- | --- | --- | --- |
| 5.23 | general (P5.1) | `mc.runtime_fork.v1` gains `at` (`{stage, cycle}` or `{iteration, session_generation}`), `message` (`instruction` stays a deprecated alias: a request naming either reads back with both set) and `frontier_policy: close \| strict`; the operator command and the run-control router carry the same three; `ForkAt`, `ForkStartPosition`, `ReusedUnit` and the policy literals in `domain/policies/forks.py`; the frontier member pattern accepts stage ids as blueprints name them (`S2`) | `contracts/runtime_contracts.py`, `domain/policies/forks.py`, `application/recovery/run_forks.py::ForkCommand`, `interfaces/http/run_forks.py` | `tests/unit/recovery/test_precise_fork.py`; FX-DA-FORK |
| 5.24 | general (TR-D12, P5.2) | Frontier closure: `domain/programs/dependencies.py` (`descendants_by_stage`, `stage_descendants`, `closed_frontier`, the one rule the interpreter's cycle invalidation now uses too); `SemanticForkService.prepare` reads the source blueprint through `ForkBlueprintReader` (`EffectiveConfigurationBlueprintReader` over the run's ERC `selected_blueprint`, composed on the API), adds the `at` stage to the requested frontier, records `frontier_requested` and `frontier_closed` on the request and the receipt, refuses `frontier_not_closed` under `strict` naming the missing stages (the HTTP detail carries `reasons`), `invalid_patch` for unknown stages; without a reader the frontier stands as requested | `application/recovery/run_forks.py::SemanticForkService._close_frontier`, `domain/programs/dependencies.py` | `test_precise_fork.py` (close, strict, no reader); **FX-TR-FORK-CYCLE** |
| 5.25 | general (TR-D13, P5.3) | Start position: `StageGraphStartPosition` (`workflow_cycle_ordinal`, `stage_cycle_ordinals`, `stage_objectives`) on `StageGraphRunInput`; `interpreter.initial_projection(start=)` starts the stage's candidates at the cycle with the objective override and refuses unknown stages or a cycle above the policy; the snapshot's `FamilyPosition` records `stage_cycle_ordinals` and `stage_objectives` of the head projection (not serialized while empty: older snapshots keep their digest); `prepare` places the derived run from `at`, the decisions (the stage must have reached the cycle, else `fork_position_unavailable`) and the snapshot's objective; `RunLaunchService._apply_fork` fills `start_position` (both families) from the receipt and refuses a caller's different one (`fork_start_position_mismatch`) | `domain/programs/interpreter.py`, `application/recovery/run_forks.py::_start_position`, `application/execution/run_launch.py::_apply_fork`, `adapters/temporal/workflows/stagegraph.py` | `test_precise_fork.py` (position, objective, interpreter start); FX-TR-FORK-CYCLE (`S2@c2` admitted first with the source's cycle-2 objective, `S2@c0`/`S2@c1` never admitted) |
| 5.26 | general (TR-D14, P5.4 option B) | Goal Directed reuse by iteration: `derived_goal_revision_id(source, derived_run)` mints the derived run's initial revision id; `derived_unit_identity(..., goal_revision_id=)` and `compute_reuse_decisions(at=, derived_goal_revision_id=)` reuse every settled unit below `at.iteration` under the substituted revision and invalidate the rest; `decision_is_exact` compares after the substitution; `GoalDirectedStartPosition` on `GoalDirectedRunInput`, honoured by `initial_state` as a pin carried on the execution and continuation state (the executor claim of the pinned iteration must find the pinned session and agent run, else `fork start position drift`); the launch refuses an initial revision other than the minted one (`fork_revision_mismatch`); `reuse_compatibility_digest` compares a Goal Directed unit's Context Packet segment and read mounts by shape (their digests cover the minted revision and the run-scoped workspace of the reused executor's output) | `domain/policies/forks.py`, `domain/programs/goal_directed.py::initial_state`, `claim_execution`, `application/recovery/run_forks.py::reuse_compatibility_digest` | `test_precise_fork.py` (reuse by iteration, minted id), `tests/unit/orchestration/test_goal_directed_fork_position.py` (7); **FX-TR-FORK-GD** |
| 5.27 | deep_agents (P5.3) | The seed head: `ForkSeedRequest.message` is honoured by `seed_fork`: after the copy, the message becomes a `messages` write of the copied point (`fork-seed:<request>`) and one more root checkpoint after it (the `messages` version advanced, the point's stamps copied, `source: fork`, stamped `belllabs_fork_seed`) is the head the derived unit pins to; a stored `messages` channel is appended, a delta channel folds the write; idempotent per fork request; the `fork_seed` point counts the message and records `channel_facts.fork_message` | `adapters/deep_agents/time_travel.py::_inject_message`, `application/recovery/cognitive_seed.py::seed` | `tests/unit/deep_agents/test_fork_seed_head.py` (2); FX-DA-FORK, FX-TR-FORK-CYCLE, FX-TR-FORK-GD (the marker is the last human message at the derived input point) |
| 5.28 | general (P5.1, owner 2026-10-21) | Delivery decided by the seed: with a cognitive seed an inline message goes to the seed head and is never queued (`message_delivery: seed_head`, the mailbox receipt's `instruction_command_id` is null); without a seed, or as a content reference, it is the derived mailbox's first instruction (`mailbox`); recorded on the request and the receipt | `application/recovery/run_forks.py::_message_delivery`, `application/missions/runtime.py::fork` | `test_precise_fork.py`; FX-DA-FORK |
| 5.29 | general (P5.2, P5.5) | The receipt: `at`, `frontier_policy`, `frontier_requested`, `frontier_closed`, `reused_units[{unit_key, source_unit_key, source_result_point}]`, `seed_point`, `start_position`, `derived_goal_revision_id`, `message_delivery` (additive; the request's new fields are not serialized at their defaults, so the fingerprint of a request reserved before 1.4.4 is unchanged); `stable_json_dump` now honours `exclude_if` like `model_dump` and the digest walker do, so a stored payload and its stable dump agree (the set-order fixture follows the same rule) | `domain/policies/forks.py::RunForkReceipt`, `application/recovery/runtime_recovery.py::_record_receipt`, `domain/authoring/canonical.py::_stabilize_sets` | `tests/unit/runtime`, `tests/unit/control_plane/test_contract_digest_set_order.py`; the three fork proofs |
| 5.30 | general (fix) | A second fork of one snapshot collided on `execution_lineage_edge.edge_digest` (`UNIQUE` per tenant; every fork records `snapshot contains source`): the edge digest now names the edge in its lineage (`sha256({lineage_key, edge})`); rows written before 1.4.4 keep the bare digest, no reader recomputes it | `adapters/postgres/runtime/stage3_kernel_repository.py::append_lineage_in_transaction` | `tests/integration/postgres/test_run_forks_postgres.py` (5), `test_ft_f4_fork_postgres.py`; FX-TR-FORK-CYCLE (the owner's command forks the same point again) |
| 5.31 | CLI | `missionctl run fork RUN --at stage:S2,cycle:2 --point ID --inject FILE [--frontier S --frontier-policy strict]`: `--point` reads the point (`MissionClient.point`) into `cognitive_seed` and derives `at` from its location when `--at` is absent; `--inject` is the message (text or JSON content) | `interfaces/cli/main.py::parse_fork_at`, `fork_point_fields`, `fork_body` | FX-TR-FORK-CYCLE (the owner's two commands over loopback HTTP) |
| 5.32 | fixture | `goal_revision`/`goal_input` take `revision_id`, `envelope_digest`, `start_position`; the Goal Directed fork proof persists the derived run's role documents under the fork's binding ref; `test_tracing_forks.py` registered for the Windows selector loop; FX-DA-FORK asserts the seed head | `tests/fixtures/rrm009_production_stack.py`, `tests/acceptance/mission_control/test_tracing_forks.py`, `test_cognition_points.py`, `tests/conftest.py` | the proofs below |

Proofs on the production offline stack (T0, zero spend, 2026-10-22, release 1.4.4):

- **FX-TR-FORK-CYCLE** (`test_fx_tr_fork_cycle`, 130 s; the §P5.6 example on the tracing
  run): a fork at `{stage: S2, cycle: 2}` seeded at an intermediate step of `S2@c2` (ordinal
  4, 3 messages) with the marker and no frontier of its own records `frontier_requested
  [S2]`, `frontier_closed [S2, S3, S4]`, `reused_units [S1@c0]` naming the source result
  point, `start_position {workflow_cycle_ordinal: 0, stage_cycle_ordinals: {S2: 2},
  stage_objectives: {S2: "RRM-009 tracing stage S2 cycle 2: revise the stage record."}}`,
  `seed_point` P, `message_delivery seed_head`; 9 invalidated units (S2, S3, S4 at each
  cycle the source ran them); the `fork_seed` point is the head after the copied P on a new
  thread with 4 messages; the same narrow frontier under `strict` is refused `422
  frontier_not_closed` with `reasons [S3, S4]`; the derived run admits `S1@c0` (one `reused`
  point, `source fork`, `written_by fork_seed`, parent the source result point), then
  `S2@c2` first (its root input point descends from the seed on the seeded thread, its
  state there ends `tool, ai, human: <marker>`, its objective override is the source's),
  then `S3@c0` and `S4@c0` fresh; the source's points are unchanged; `missionctl run fork
  RUN --at stage:S2,cycle:2 --point P --inject msg.json --from-snapshot ...` answers a receipt
  with the same `start_position` and `seed_head` delivery (a second derived run, not
  launched); `missionctl run transcript DERIVED --by stage` prints the four stage groups.
- **FX-TR-FORK-GD** (`test_goal_directed_fork_at_an_iteration_reuses_earlier_iterations_and_pins_the_seed`,
  69 s; the §P5.7 example on the fixture's two-iteration Goal Directed run): a fork at
  `{iteration: 2, session_generation: 1}` seeded at the iteration-2 executor's input point
  (ordinal 10) with the marker records `start_position {goal_iteration: 2, session_generation: 1,
  agent_run: 2}`, a minted `derived_goal_revision_id`, `seed_head` delivery, `reused_units`
  = the iteration-1 executor and verifier with their source result points, two invalidated
  units; the derived run (launched with the minted revision, the source's envelope digest
  and the receipt's position) settles iteration 1 by reference (one `reused` point per role,
  parent the source result point) and runs the iteration-2 executor first on the seeded
  thread (root input point descending from the `fork_seed` point; state there ends with the
  marker as the last human message), then the verifier fresh; the source is unchanged.
- **FX-DA-FORK** (47 s): as before, now with the receipt's position, closure and delivery
  asserted and the injected instruction as the seeded head's last human message.
- The four FX-DA proofs and the ten tracing proofs of WP-TR-3 were not rerun after 5.26
  and 5.30 except FX-DA (4, green) and the tracing run inside FX-TR-FORK-CYCLE; the full set
  runs once more after WP-TR-5.

What this package found on the way (the honest list):

- **Reuse compatibility is weaker for Goal Directed than for Stage Graph.** The packet
  digest covers the minted revision and a reused verifier's read mounts are the derived
  run's materialization of the reused executor's output, so for Goal Directed units the
  compatibility digest compares those two by shape (segment present, trust class, mount
  paths) and everything else by value. A patched objective invalidates every iteration
  before this rule applies. Stage 3 should decide whether the packet's run- and
  revision-independent content deserves its own digest.
- **A fail-closed reuse stalls a Goal Directed run.** Before 5.26's second rule the
  derived verifier settled `failed/incompatible_restore` and the family then recorded
  nothing more for the rest of the proof's timeout (`active`, no further events, no logged
  warning). The Stage Graph path terminates cleanly; the Goal Directed workflow's handling of
  a failed-by-reference settlement is Stage 3's.
- **The derived Goal Directed launch carries its own templates.** `_apply_fork` derives
  Stage Graph templates only; the Goal Directed proof persists the executor and verifier
  documents under the fork's binding ref itself. A manifest-driven launch of a Goal Directed
  fork needs the launch author to read `derived_goal_revision_id` and `start_position` from
  the receipt (not wired).
- The packet turn still follows the injected message: the derived unit's first model call
  sees the copied conversation, the marker, then the Context Packet's own human turn (the
  marker is the last human message *of the seeded state*, as §P5.3 words it).
- `at.session_generation` is taken as given (default 1); a fork at a session the source
  rolled over to pins that session, and the derived run reaches it only if its reused
  iterations roll over identically (the pin reports drift otherwise).
- The ERC-backed blueprint reader raises `frontier_closure_unavailable` (503) when the
  configuration cannot be read; the router composition without a catalog closes nothing.

### Checks run (2026-10-22, Windows host, after WP-TR-4)

- **Passed**: `ruff check .` and `ruff format --check .` (1 956 files); `mypy` on the 20
  changed and new source modules; `tests/architecture` with
  `tests/unit/{recovery,runtime,run_control,orchestration,deep_agents,mission_control,
  temporal,operations,frames}` (1 674, 10 POSIX skips); `tests/unit/{control_plane,authoring}`
  (512); `tests/integration/postgres/{test_run_forks_postgres,test_ft_f4_fork_postgres}.py`
  (7); FX-DA (4), FX-TR-FORK-CYCLE, FX-TR-FORK-GD.
- **Failed, pre-existing**: the two `tests/unit/control_plane/test_digest_set_order_guard.py`
  audits; the `pwsh` deploy script tests (deselected); RF-20 (not rerun).
- **Unrun**: `tests/unit` as one job; the WP-TR-3 tracing proofs (rerun after WP-TR-5); T2.

### WP-TR-5: the remote saver (deep_agents, general outcomes)

The sequence a settlement follows now reads: `_classify` lists only the thread suffix after
the expected source -> cognition -> `_own_result_config` lists only the suffix after the
pinned checkpoint -> `collect_points` folds the lineage under the points walk budget
(`MISSION_CONTROL_POINTS_WALK_BUDGET_MS`, 5 000 by default), every key naming the saver's
locator; past the budget the result point records `points_status: incomplete` and the
settlement proceeds -> `run inspect` lists the unit under `points_incomplete` -> `run points
--reconcile` re-walks the generation and clears it. A fork's copy runs on the maintenance
worker (`mc.fork_seed.v1`); a point read whose saver does not answer is `503
state_unavailable`, a seed whose saver does not answer is `cognitive_seed_unavailable`.

| # | Scope | Change | Finished part | Proof |
| --- | --- | --- | --- | --- |
| 5.33 | general (P6.2) | The locator digest: `saver_locator_digest(conninfo)` = sha256 over host, port, dbname and schema of the bound conninfo (never the DSN), held by `StandalonePersistence.locator_digest`, declared on `PinnedPersistence.locator_digest`, handed to the adapter (`saver_locators`) and the lane (`locators`); `QualifiedCheckpointKey.saver_locator_digest` (additive, digest-neutral, not serialized while absent) on every point key the settlement, the reconciler and the fork seed write; lineage keys (heads, transitions, captures), which the adapter compares by value, never carry it | `adapters/deep_agents/persistence.py::saver_locator_digest`, `domain/graph_runtime/identities.py`, `adapters/temporal/deployment_composition.py`, `bootstrap/{api,runtime_control}.py` | `tests/unit/deep_agents/test_remote_saver.py` |
| 5.34 | deep_agents (P6.1) | Bounded walks: `_classify` and `_own_result_config` list the thread newest-first with `limit = MAX_LINEAGE_WALK + 1` and stop at the expected source (or the pinned checkpoint), the boundary item included, since checkpoint ids are time-ordered; the lineage after the source is all that can descend from it | `adapters/deep_agents/adapter.py::_classify`, `_own_result_config` | `tests/unit/operations/test_checkpoint_recovery_classification.py` (27, the own-tip drift case kept) |
| 5.35 | deep_agents (P6.1) | The points walk budget: `walk_points(budget_seconds=)` stops when the wall-clock budget is spent, always folds the result checkpoint, and the result observation records `channel_facts.points_status == "incomplete"` with `points_walked`; `collect_points` passes the adapter's budget (`points_walk_budget_ms`, from `MISSION_CONTROL_POINTS_WALK_BUDGET_MS`) and skips the nested namespaces of an exhausted walk; the settlement proceeds with what was folded | `adapters/deep_agents/cognition_points.py::walk_points`, `_fold_result_only`, `points_incomplete` | `test_remote_saver.py` (budgeted walk, collect); **FX-TR-REMOTE** |
| 5.36 | general (P6.1) | The typed outcome: `RunSnapshot.points_incomplete` and `RunInspection.points_incomplete` (run control) and the `points_incomplete` section of `mc.inspection.v1` (`PointsStatusReader`, `PostgresPointsStatusReader` over the result points of each unit's latest generation); the reconciler re-walks a generation whose result point is incomplete, keeps the rows it holds, adds the gap, sets `points_status: complete` and reports `walks_completed` | `adapters/postgres/run_control/inspection_repository.py`, `application/missions/inspection.py`, `application/execution/operations/point_reconciliation.py` | `tests/unit/operations/test_point_reconciliation.py` (incomplete walk completed); FX-TR-REMOTE (`run inspect`, `run points --reconcile`) |
| 5.37 | deep_agents (P6.1) | The lane's outcomes: a saver the registry does not hold is `checkpointer_not_registered`; a key naming another location is `saver_not_served`; a saver that raises a connection or driver error during `read_as_of`, `seed_fork` or `collect_points` is `saver_unreachable` (`_saver_outcome`), each a `TimeTravelUnsupported` carrying the checkpointer digest; the copy has a wall-clock budget (`copy_budget_seconds`, 120 s) and stops with `copy_incomplete` | `adapters/deep_agents/time_travel.py::_saver_for`, `_saver_outcome`, `application/execution/harness/time_travel.py::TimeTravelUnsupported.saver` | `test_remote_saver.py` (not served, unreachable) |
| 5.38 | general (P6.1) | `GET points/{pid}/state-as-of` answers `503 state_unavailable {reason, saver, restore_level, withheld}` for `saver_unreachable` and `saver_not_served` (501 otherwise, as before); `CognitiveSeedService.seed` refuses `cognitive_seed_unavailable` (503) for those reasons and `copy_incomplete`, `cognitive_seed_not_supported` otherwise | `interfaces/http/cognition_points.py`, `application/recovery/cognitive_seed.py`, `domain/policies/forks.py` (the code), `interfaces/http/{mission_control,run_forks}.py` | FX-TR-REMOTE (503 with the proxy closed; `run transcript --by step --full` still answers) |
| 5.39 | general (P6.1) | The copy on a worker activity: `mc.fork_seed.v1` (`ForkSeedWorkflow`) hosts `fork_seed.copy` (`ForkSeedActivities` over the worker's time-travel registry, built in the deployment composition as `WorkerActivityComposition.time_travel`); `TemporalForkSeedRunner` on the API starts it on the maintenance queue (`<base>-maintenance`, workflow id `fork-seed/<request>/<unit>`, `USE_EXISTING` on conflict) and waits; a typed refusal comes back as the same `TimeTravelUnsupported`; `CognitiveSeedService(seed_runner=)` prefers the runner and keeps the in-process lane as the fallback; the worker's maintenance worker and the scoped stack's register both | `adapters/temporal/activities/fork_seed.py`, `adapters/temporal/workflows/fork_seed.py`, `application/recovery/cognitive_seed.py`, `bootstrap/{api,worker}.py`, `tests/fixtures/scoped_api_stack.py` | FX-DA-FORK, FX-TR-FORK-CYCLE, FX-TR-FORK-GD (the seed copy served by the worker) |
| 5.40 | docs, fixture | The topology note (`providers/deep_agents/TOPOLOGY-NOTE.md`, ADR candidate: two databases, never a shared schema; child state through the server API; the locator on every point); `tests/fixtures/tcp_proxy.py` (`SaverProxy`: a byte proxy with `delay_seconds` and `set_closed`) and `scoped_stack(saver_proxy=)` routing the saver DSN through it; `tests/acceptance/mission_control/test_tracing_remote.py` | `TOPOLOGY-NOTE.md`, `tests/fixtures/tcp_proxy.py` | `tests/unit/fixtures/test_tcp_proxy.py` (2); FX-TR-REMOTE |
| 5.41 | general (correction of 5.29) | `stable_json_dump` no longer honours `exclude_if` (the WP-TR-4 change is reverted with the set-order fixture): digests recorded before 1.4.4 over contracts with `exclude_if` fields (`CursorExecutionBinding` v1) must keep verifying. The additive fork request fields, the family position's cycle maps and the key's locator are marked `digest_omit_default` instead, the repository's own rule for an additive field, so fingerprints and digests of records written before them are unchanged by either walker | `domain/policies/forks.py`, `domain/graph_runtime/identities.py`, `domain/authoring/canonical.py` (as in WP-TR-3) | `tests/unit/harness/test_lane_contracts.py`, `tests/unit/runtime/test_run_snapshot_manifest.py`, `tests/unit/control_plane/test_contract_digest_set_order.py` |

Proofs on the production offline stack (T0, zero spend, 2026-10-22, release 1.4.4):

- **FX-TR-REMOTE** (`test_fx_tr_remote`, 53 s): with the saver DSN routed through the proxy
  (0.15 s per query after launch) and the budget at 50 ms, both units of the Stage Graph run
  settle with `points_status: incomplete` on their result points; `GET runs/{id}/inspection`
  and `missionctl run inspect RUN` list both under `points_incomplete`; with the delay
  removed `missionctl run points RUN --reconcile` reports `points_added 20`,
  `walks_completed` the two units, no `saver_unreachable`, and the inspection lists none;
  with the proxy closed `state-as-of` answers `503 state_unavailable {reason:
  saver_unreachable, saver: <checkpointer digest>}` and `missionctl run transcript RUN --by
  step --full` exits 0 with the whole transcript (454 KB). `restore_level` in the 503 reads
  null: the adapter's own points record no restore level (the fork seed's do).
- **FX-DA-FORK** (30 s), **FX-TR-FORK-CYCLE** (117 s), **FX-TR-FORK-GD** (54 s): green with
  the seed copy served by `mc.fork_seed.v1` on the maintenance queue.
- The ten tracing proofs (blueprint 93 s, reconcile 90 s, reconcile CLI 90 s, lifecycle half
  89 s, step 82 s, sub 82 s, step projection 90 s, hook 102 s, retain 85 s, replay 84 s) and
  the four FX-DA proofs (188 s together) green on the final tree, run three to four proofs
  per foreground job.

What this package found on the way (the honest list):

- **The locator stays off the lineage keys.** Stamping it on the seeded namespace head made
  the derived unit's first attempt fail `checkpoint_lineage_conflict` (the capture's source
  key, built by the adapter without a locator, no longer equalled the plan's expected
  source). The rule is now: point keys name the saver, lineage keys name the checkpoint.
  `saver_not_served` is therefore proven on the lane (unit) and not on the stack.
- **The API's maintenance queue is derived from the base task queue**, as the worker derives
  it, not from the deployment's `root_task_queue` (in the proof stack that is the Stage Graph
  coordinator queue, and the first run of FX-DA-FORK waited forever on a queue nobody
  served). A deployment whose base queue differs between API and worker settings would stall
  every seeded fork: Stage 3 should put the maintenance queue on `TemporalDeployment`.
- The fold-backwards optimization of P6.1 (one `alist` for the lineage, delta history once
  for the result) is not built; the walk still reads each checkpoint and its delta history
  (the budget bounds the cost, the reconciler completes it).
- `_classify` and `_own_result_config` rely on checkpoint ids being time-ordered (uuid6):
  a saver whose ids are not would list the suffix wrongly; LangGraph's are.
- `heartbeat` reads with `checkpoint_read: stale`, `capture_incomplete` and
  `MAX_LINEAGE_WALK` for `is_stamped_descendant` (the other P6.1 rows) are unchanged.
- The first FX-TR-REMOTE run's `run inspect` showed no section because the mission
  inspection (`mc.inspection.v1`) and the run-control inspection are different contracts;
  both carry `points_incomplete` now.
- The stable-dump reversal (5.41) means a stored payload and its stable dump still disagree
  on `exclude_if` fields whose predicate holds (a replay compare of such a transition,
  `stored_payload_matches`, would mismatch); that pre-existing gap is noted for Stage 3.

### Checks run (2026-10-22, Windows host, after WP-TR-5)

- **Passed**: `ruff check .` and `ruff format --check .` (1 963 files); `mypy` on the 27
  changed and new source modules; `tests/architecture` with
  `tests/unit/{frames,operations,deep_agents,streams,subscriptions}` (669);
  `tests/unit/{run_control,recovery,workspaces,harness,mission_control,temporal,orchestration,
  control_plane,fixtures,runtime}` (1 729, 10 POSIX skips); the digest-sensitive suites after
  5.41 (368); `tests/integration/postgres/{test_run2_release_144,test_provider_frames_postgres,
  test_transcript_entries,test_run_forks_postgres,test_ft_f4_fork_postgres}.py` (21); the
  seventeen acceptance proofs above on the final tree.
- **Failed, pre-existing**: the four `tests/unit/harness/test_cursor_local.py` cases
  (RF-20); the two `tests/unit/control_plane/test_digest_set_order_guard.py` audits; the
  `pwsh` deploy script tests (deselected).
- **Unrun**: `tests/unit` as one job; T2.

### Stage 1 finish (2026-10-22): the parts to read, the sequence, the owner's commands

Six commits on `sprint/tracing-stage-1` from `main` at `63ca7777`, in order: `27b1eea7`
(release 1.4.4), `6b3f172f` (WP-TR-1), `c7555e7c` (WP-TR-2), `05d92929` (WP-TR-3),
`4a281b36` (WP-TR-4), `8a71b6b1` (WP-TR-5). Not pushed, not merged; zero USD spent; every
proof T0 on the production offline stack. The handoff for Stage 2 is
[SESSION-STAGE-2.md](../../../archive/provider-consolidation-2026-10/sessions/SESSION-STAGE-2.md).

**One finished part, in reading order** (the §9 list of SESSION-STAGE-1, with where each
part now lives):

1. `application/execution/operations/checkpoint_lineage.py::record_result(points=)` and
   `application/execution/cognition_points.py::compose_batch`: the points composed with the
   settlement, their cross-cycle parents (general, WP-TR-1).
2. `adapters/postgres/operations/checkpoint_lineage.py` and `operations/cognition_points.py`:
   the one settlement transaction that writes transition, result, points and the
   `transcript_projection` outbox intent; `operations/point_reconciliation.py`: the reconciler
   that re-derives, attributes frames and completes a budget-bounded walk (general, WP-TR-1,
   WP-TR-3, WP-TR-5).
3. `adapters/deep_agents/adapter.py::_ModelRequestObserver` with `frames.py`, `hooks.py`,
   `cognition_points.py` (the budgeted walk, the locator on every key) and
   `time_travel.py` (the seed head, the typed outcomes): what the Deep Agents lane records
   and how it reads back (deep_agents, WP-TR-2, WP-TR-5).
4. `application/frames/transcript.py` (`merge(points=)`, `entries_v2`, `group_entries`),
   `adapters/postgres/frames/transcript_entries.py` (the persisted projection) and
   `application/frames/replay.py` (the dry run): the read model (general, WP-TR-3).
5. `application/recovery/run_forks.py::SemanticForkService.prepare` with
   `domain/programs/dependencies.py`, `domain/policies/forks.py`,
   `application/execution/run_launch.py::_apply_fork`,
   `domain/programs/interpreter.py::initial_projection(start=)` and
   `application/recovery/cognitive_seed.py` (the copy on `mc.fork_seed.v1`): the precise
   fork (general, WP-TR-4, WP-TR-5).

**The sequence it sits in** (the proposal's closing diagram, as built):

```text
POST runs/{id}/launch ──────────────────────── mission_run.temporal_* (WP-TR-1)
Temporal family workflow
  ├ admit_operation ─ journal operation_admitted{released_by, continues_from} + event{unit_key} (WP-TR-1)
  ├ operation.execute activity
  │   ├ record_attempt ─ activation, attempt, attempt observation (exists)
  │   ├ adapter.execute
  │   │   ├ materializer.prepare ─ environment_materialized frame, kernel hook ports (WP-TR-2)
  │   │   ├ _classify ─ the thread suffix after the expected source only (WP-TR-5)
  │   │   ├ astream ─ per step: model_request (callback) → message → tool_call_* (promoted)
  │   │   │           → subagent_started … subagent_ended → hook_invoked/result (WP-TR-2)
  │   │   ├ _capture_result, collect_points ─ root + nested, under the points budget,
  │   │   │           every key naming the saver's locator (WP-TR-2, WP-TR-5)
  │   │   └ recorder.finish ─ turn_ended, run_result (exists)
  │   └ settle ─ ONE transaction: transition, result, points{workspace_checkpoint_ref, budget_snapshot},
  │              settlement, derived events{activation_id, unit_key, point_ref},
  │              the transcript_projection outbox intent (WP-TR-1, WP-TR-3)
  ├ result_decided ─ journal + completion_decision + completion_candidate (WP-TR-1)
  ├ cycle_decided ─ journal; the next cycle's input point parent = the prior result (WP-TR-1)
  └ continue_as_new (Goal) ─ workflow_run.record_rollover (WP-TR-1)
Outbox ─ relay → mc.transcript_project.v1 → transcript_entry + transcript_projection_state (WP-TR-3)
Retention ─ frames.expire deletes the delta class; step frames live for the evidence life (WP-TR-3)
Reads ─ run transcript --by step|stage|iteration --point --full · run artifact · run replay --dry-run
        · run points --reconcile · run inspect (points_incomplete) · state-as-of (503 when the saver is away)
Fork ─ run fork --at --point --inject → closure, start_position, the seed head with the message
        (copied on the maintenance worker, mc.fork_seed.v1), reused points (WP-TR-4, WP-TR-5)
```

**The two commands, with what the owner sees** (recorded by FX-TR-STEP on the projection and
FX-TR-FORK-CYCLE over loopback HTTP, 2026-10-22):

```text
missionctl run transcript RUN --by step --point ID --full
```

One `mc.transcript_entry.v2` group per line: the step group of the point (its `unit_key`,
`node_key S2`, `cycle`, the point id and its parent), then the group's entries in transcript
order: the `model_request` entry (model name and provider, the batch digest, the message ids
and their promoted bodies resolved under `--full`), the `message` entries, the
`tool_call_started` / `tool_call_completed` pair with the whole 12 886-byte tool result inline
(the `frame-body://` reference resolved by the granted body reader), the `hook_invoked` /
`hook_result` entries naming the kernel ports first, and the lifecycle facts of the unit; 96 KB
of JSON lines for one step of the tracing run.

```text
missionctl run fork RUN --at stage:S2,cycle:2 --point ID --inject msg.json \
    --from-snapshot SNAPSHOT --sponsorship-ref sponsorship:... --approval-ref approval:...
missionctl run transcript DERIVED --by stage
```

The fork answers `mc.runtime_fork_receipt.v1`: `receipt.at {stage: S2, cycle: 2}`,
`frontier_requested [S2]`, `frontier_closed [S2, S3, S4]`, `reused_units [{S1@c0, its
source result point}]`, `seed_point` (the point's checkpoint id), `start_position
{workflow_cycle_ordinal: 0, stage_cycle_ordinals: {S2: 2}, stage_objectives: {S2: "RRM-009
tracing stage S2 cycle 2: revise the stage record."}}`, `message_delivery seed_head`,
`target_run_id` (the derived run), the lineage with nine invalidated units; `seed.instruction_command_id`
null (the message went to the seed head, not the mailbox). After the derived run is launched
and completes, the stage transcript prints one group per unit: `S1@c0` (settled by
reference, its `reused` point naming the source result), `S2@c2` (the seeded head and the
marker as the last human message before the unit's own steps), `S3@c0` and `S4@c0` (fresh,
`released_by` the derived `S2@c2`), each group with `released_by`, `continues_from`, the
result decision and the completion row from the family journal.

## Turn 5 preparation (2026-10-21): the tracing proposal and the three stages

No source changes. The research and proposal session for
[archive/specs/TRACING-AND-OBSERVABILITY.md](../../../archive/provider-consolidation-2026-10/specs/TRACING-AND-OBSERVABILITY.md) ran under PROCESS §1
(orient, audit with seven read-only explorations citing `file:line` on `main` at `2714ae0f`,
research R1-R5 against the installed packages and fetched pages, plan, confirm). Output:
[TRACING-PROPOSAL.md](../../../archive/provider-consolidation-2026-10/proposals/TRACING-PROPOSAL.md) (audit corrections §A.2; P1-P11; Part C, the
three stages) and [SESSION-STAGE-1.md](../../../archive/provider-consolidation-2026-10/sessions/SESSION-STAGE-1.md), the instruction for Stage 1.
Owner answers recorded in the proposal §P10 (2026-10-21): three stages, (1) implementation
and minimal verification over work packages WP-TR-1..5 (two sessions recommended, 1A the
write side and 1B the read side and the fork, one allowed, subagents on independent streams),
(2) real fixtures on a 10 USD cognition budget with fixes for what they expose (F-T3-1 named
as the Goal Directed blocker), (3) adversarial review, clean code, tests and the documentation
pass; one release 1.4.4 cut first; `model_request` records per-message objects plus the batch digest
by default, the full batch under a `full_requests` capture profile chosen by a deployment
setting and never by a manifest, with `FrameCapturePolicy` and `FrameBodyPromoter` as the
extension points for other transcript storage behaviour; fork frontiers auto-close and are
recorded; Goal Directed forks reuse iterations below the seed by a reuse rule (no revision
identity change). Spend: 0 USD (no model run).

Interview answers (owner, 2026-10-21, before Stage 1; recorded in the proposal §P10): one
session runs all five work packages; retention columns as proposed (`retain_days` for deltas,
nullable `step_retain_days`, `prune_mode` reserved); frame bodies by the light
`frame-body://sha256:<hex>` scheme over the payload store; lifecycle decisions written into
the existing `completion_candidate` and `completion_decision` tables, improvements deferred
to the output-contracts session by the owner's stated perspective; the persisted Transcript
refreshed at every settlement through the outbox and on demand, no schedule; one fork field
`message` (`instruction` a deprecated alias) delivered to the seed head or the mailbox by the
seed; commits after each work package on the sprint branch, no push or merge until the owner
says so; Deep Agents may do code work (not forbidden), so nothing may assume the lane never
edits files.

Findings registered against the brief, each cited in the proposal §A.2: the stream envelope
has no `point_ref` field (the unwritten field is `payload_ref`); the promoter branch of the
frame writer is complete but has no implementation and no caller; the settlement is three
transactions (transition and result, points, settlement); a middleware passed through
`create_deep_agent` sits before the prompt-caching tail and cannot see the final model input,
so the record comes from a callback at the chat-model boundary (the adapter already attaches
two); the Agent Server in this checkout persists in memory (pickle files), not in a database;
the saver is one locked connection per process and a settlement walk costs about four round
trips per checkpoint; `checkpointer_ref_digest` is a catalog definition digest that never
changes with the DSN; the Stage Graph workflow already accepts an `initial_projection` input
and the interpreter already closes a cycle's invalidation over dependants, which the fork
policy never sees.

## Turn 4 (2026-10-21): the cognition coordinate, forks from a point, intervention, K02

Plan and owner answers in [COGNITION-POINTS.md](../../../archive/provider-consolidation-2026-10/specs/COGNITION-POINTS.md) (Q1–Q4 recorded
2026-10-21). The sequence a point follows now reads: `operation.execute` (attempt with its task
queue) → adapter `execute` (the recorder keys every step's frames by the root checkpoint the
`checkpoints` stream mode reports) → `_capture_result` → `collect_points` (one observation per
root checkpoint of the attempt's lineage, folded from the saver) → `RuntimeResult.cognition_points`
→ settlement `record_result` (transition, result, then the points: parent by locator in the
run, turn by native refs, frame range by provider keys) → `GET .../runs/{id}/points`,
`.../points/{id}/state-as-of` (the lane's `read_as_of`), `missionctl run points | state-as-of`,
MCP `mission_run_points | mission_run_state_as_of`.

| # | Scope | Change | Finished part | Proof |
| --- | --- | --- | --- | --- |
| 4.1 | general | Release **1.4.3** (`packages/mission-control-db-contract/releases/1.4.3`, built on the disposable cluster, manifest fingerprint `sha256:9e8297f7…`): `0045_cognition_points` (`mission_control.cognition_point`, `session_turn.point_ref`, `activity_attempt_observation.task_queue`, the `agent_session.checkpoint_namespace` grant) and `0046_lane_describe_subagent_fields` (every lane describe gains `subagents.fields`, Deep Agents its `time_travel`; generated by `lane_describe_refresh.py::render_successor_section`, each revision guarded by the exact 1.4.2 literal, the qualified `deep_agents` row named explicitly). `scripts/prepare_release_143.py` reproduces the tree. The common-db test fixture and the offline stack now install the newest *built* release (`MISSION_CONTROL_TEST_COMPONENT_ROOT` overrides); deployment locks untouched | `packages/.../releases/1.4.3/component/migrations/0045_cognition_points.sql`, `scripts/release_143/`, `packages/.../scripts/lane_describe_refresh.py` | `tests/integration/postgres/test_run2_release_143.py` (fresh, from 1.4.2, from 1.3.0, drifted-describe refusal: 4 passed); `tests/unit/harness/test_lane_contracts.py` |
| 4.2 | general (Q8) | `LaneSubagents.fields` and `LaneDescribe.time_travel` on the domain contract (additive, digest-neutral for documents that lack them); the describe constants carry every lane's subagent field table (the Deep Agents row from its adapter, file lanes derived in `domain/execution/subagent_support.py`, hosted APIs unsupported); `application/authoring/lanes/support.py` reads the describe; the HTTP sibling key is retired (`GET .../lanes/{profile}` serves `subagents.fields` from the document) | `domain/execution/lanes.py`, `application/execution/harness/describe.py` | `tests/unit/authoring/test_subagent_discriminator.py`, `tests/conformance/lanes` |
| 4.3 | general | `mc.cognition_coordinate.v1`, `mc.cognition_point.v1`, `mc.state_as_of.v1`: the discriminated point union (`checkpoint`, `session_cursor`, `thread_item`, `workspace_snapshot`), the coordinate, the point record with the denormalized unit location (stage or role, iteration or workflow cycle, stage cycle, session generation), attempt facts, frame range, redacted facts, roles (`input`, `intermediate`, `leaf`, `result`, `interrupted`, `replacement_start`, `fork_seed`, `rollover_start`), `restore_level`; `RuntimeResult.cognition_points`; `OperationActivityAttempt.task_queue` | `domain/execution/cognition_points.py` | `tests/unit/operations/test_cognition_points.py` |
| 4.4 | general | The index: `CognitionPointRepository` (Postgres and in-memory; idempotent by point id; resolves the lineage root's parent by locator within the run, the session turn by native session and turn refs, the frame range from the step's provider keys), `compose_points`, the settlement writer in `CheckpointLineageService.record_result` (points never gate settlement; a write failure is logged), the operator read service, HTTP router, CLI and MCP tools, the `TimeTravelLane` port and registry (the one router), the API-side saver composition (`compose_time_travel`, also registers the inspection checkpoint reader on the operator API: P1-A1) | `application/execution/cognition_points.py`, `adapters/postgres/operations/cognition_points.py`, `application/execution/harness/time_travel.py`, `interfaces/http/cognition_points.py` | `test_cognition_points.py` (unit), FX-DA-POINTS |
| 4.5 | deep_agents | The lane's points: `collect_points` walks the attempt's lineage (result inclusive, source exclusive), folds the `messages` delta channel by identity, usage per step, the `files` digest and the allowlisted channel facts, keys frames per checkpoint (`DeepAgentFrameRecorder` consumes `stream_mode="checkpoints"`), marks the inject's interrupted leaf and the replacement start; the closing frames carry the result checkpoint so the frame identity writer fills `session_turn.point_ref` and `agent_session.checkpoint_namespace/checkpoint_ref` | `adapters/deep_agents/cognition_points.py`, `adapters/deep_agents/frames.py`, `adapters/postgres/frames/identity.py` | `tests/unit/deep_agents/test_cognition_points_collector.py` (real LangGraph saver) |
| 4.6 | deep_agents | `read_as_of` at R3 (`DeepAgentsTimeTravel`): the graph state at a point with secrets and oversized content hidden, never counts only (Q2): messages with role, name, tool calls and redacted text under the excerpt cap with digests, files with size and digest, the other channels as redacted values, pending tasks, interrupts, step, source, stamps; gated by `workflow_run.read_checkpoint_summary` (no new permission) | `adapters/deep_agents/time_travel.py` | FX-DA-POINTS (`state-as-of` on the live stack) |
| 4.7 | general (WP-2) | `cognitive_seed` forks: admitted when the point is seedable and the lane declares `time_travel.fork: R3` (`CognitiveSeedService.resolve`); after the saga admits the derived run, `seed_fork` restores the point into the derived unit's namespace, the namespace head is seeded (`seed_namespace_head` on both lineage repositories; `_refuse_sealed_head` admits a head without a transition), and a `fork_seed` point with `parent_coordinate` and `restore_level` is written on the derived run; the fixture grant gains `state_inspector` and `workflow_run.control` (P1-A6) | `application/recovery/cognitive_seed.py`, `domain/policies/forks.py` (`cognitive_seed_allowed`), `application/recovery/run_forks.py` | FX-DA-FORK |
| 4.8 | deep_agents (WP-2) | `seed_fork` copies the source thread's root lineage up to the point into the derived thread with the saver primitives (same checkpoint ids, metadata and parent links, each checkpoint's pending writes so the delta history reconstructs); nothing after the point is copied, the source thread is never written, the copy is idempotent; `restore_level: R3, history: native` | `adapters/deep_agents/time_travel.py::seed_fork` | FX-DA-FORK (the derived stage's input checkpoint has the copied point as parent, its state is the copied conversation, it ends in a new result) |
| 4.9 | general (K02) | Goal Loop rollovers are authorable: `governors.transfers` lowers to `max_rollovers` (default 3, the hard-coded 0 is gone); a threshold crossing the policy cannot honour (cap exhausted, no typed handoff) **pauses** the run with reason `rollover_limit` or `handoff_missing` instead of failing the family; an authored fresh session without a handoff stays an authoring error | `domain/authoring/manifest_lowering.py`, `domain/programs/goal_directed.py` | `tests/unit/orchestration/test_wp_bp_020_goal_directed.py` (two tests updated, one added); goldens 02/03 regenerated (`max_rollovers: 3`) |
| 4.10 | deep_agents (fixture) | `MISSION_CONTROL_TECHNICAL_MODEL_DELAY_SECONDS` on the scripted model widens the window for an inject inside a running turn | `tests/fixtures/rrm009_production_stack.py` | FX-DA-INJECT |

### Proofs on the production offline stack (T0, zero spend, 2026-10-21)

`tests/acceptance/mission_control/test_cognition_points.py` (real Postgres 17 on release 1.4.3,
local Temporal, production workers, scripted cognition, the configured API over loopback):

- **FX-DA-POINTS** (`test_goal_directed_points_index_every_root_checkpoint_of_iteration_two`,
  44 s): 44 points for the four units; every stamped root checkpoint of every unit has exactly
  one row with its attempt (workflow, run, activity, attempt, task queue), its turn, its step
  and message count; iteration 2's lineage root has iteration 1's result as parent on the same
  role thread; filters narrow exactly; `state-as-of` at iteration 2's result returns the
  scripted conversation (`task`, `write_file`, `lookup_binding_marker` calls, the `/goal/…`
  report file, the stamps, usage). The steps that stream nothing (`__start__`, the Deep Agents
  middleware nodes before the first model call) carry no frame range, every other point does,
  and ranges never overlap.
- **FX-DA-POINTS-SG** (`test_stage_graph_points_index_each_stage_in_its_own_thread`, 33 s):
  two stages, each in its own thread, cycle 0, no session generation; the review stage's
  result state holds the sealed packet files and its written output.
- **FX-DA-FORK** (`test_stage_graph_fork_from_a_point_continues_the_copied_thread`, 41 s):
  snapshot at `stage_settled`, fork with `cognitive_seed` at (review, step 4) and an
  instruction; the derived run holds a `fork_seed` point (R3, native) in its own stage thread
  before launch; after launch and the re-declared wait, the derived review stage's input
  checkpoint has the copied point as parent (same id, new thread), its state is the copied
  conversation, the result state holds the fork instruction, the source run's points are
  unchanged.
- **FX-DA-INJECT** (`test_interrupt_and_inject_into_running_cognition_marks_the_points`,
  98 s): an `interrupt_and_inject` lands inside iteration 1's executor turn (2.5 s per model
  call); receipts read "cancel_and_replace: the replacement turn started"; the executor's
  points show step 7 `interrupted` and step 8 `input, replacement_start` on the same thread,
  and the injected text is in the result state. Evidence
  `.scratch/pc-p1-deep-agents/turn4/inject-evidence.json`.
- Hand drills (git-ignored): `.scratch/pc-p1-deep-agents/turn4/drill-gd/` (`points-vs-frames.txt`,
  the CLI outputs) and `drill-sg/` (fork receipt, seed point, derived points, derived
  inspection and transcript, `state-as-of` of the derived input point).

### Findings registered

- **F-T4-1 (kernel, medium)**: Goal Directed units are never reused by ref in a fork
  (`compute_reuse_decisions`), so a Goal Directed `cognitive_seed` continues the derived
  *role thread* from the point while the iteration counters restart at 1; the Stage Graph
  seed is exact. Run-independent revision ids would let the fork reuse iterations by ref.
- **F-T4-2 (kernel, low)**: `mission_run.temporal_workflow_id/run_id` are still never written
  (the point rows carry the Temporal ids; the run row does not).
- **F-T4-3 (deep_agents, low)**: the delivery report of an inject names turns (`turn:N`),
  not points; the interrupted leaf and the replacement start are on the point rows only.
- The six skill-origin leaks of COGNITION-POINTS §7 are **P1-A8..A13** (pin-file workspace
  origin, the older hash-only store fallback, compile never checks `bundle_ref`, hosted
  packs inline skill bytes, `mc-signals` from package source, origin `bundle_ref`s admitted).
  Decision Q4 (O1): custody-only materialization and reviewed acquisition imports, in a
  dedicated turn.

### What is still not materialized on this lane (honest list)

- A live Goal Directed **rollover** (K02 crossing with a typed handoff): the scripted executor
  emits no handoff, so the T0 fixture reaches the pause path, not the roll; the cross-session
  `rollover_start` role and `parent_coordinate` link are declared, not yet written.
- Mid-iteration continuation (K03): the Deep Agents hydrator and snapshot ports are still not
  registered in production; `request_continuation` on this lane is recorded only.
- The reconciler that re-derives points from the saver after a crash, `point_ref` on the
  Socket.IO `provider_frame` events, `budget_snapshot` and `workspace_checkpoint_ref` on
  points (K11), cycle deliveries and the governed cap (K05): next session, with context
  transfer.
- Everything deferred from turn 3 (WP-S3, WP-S4, WP-S5, F-T3-1, F-T3-2, the seeded child
  observed using its tool and Skill) is unchanged.

### Checks run (2026-10-21, Windows host)

- **Passed**: `ruff check` and `ruff format --check` on every changed module; `mypy` on the
  changed modules; `tests/architecture` (12); `tests/unit/harness/test_lane_contracts.py`,
  `tests/unit/authoring` (378, goldens 02/03 regenerated), `tests/unit/orchestration/
  test_wp_bp_020_goal_directed.py` (35), `tests/unit/operations tests/unit/run_control
  tests/unit/recovery tests/unit/deep_agents tests/unit/frames tests/unit/harness
  tests/unit/capability tests/architecture tests/conformance` (1533 passed, 10 skipped);
  `tests/integration/postgres/test_run2_release_143.py` (4); the four acceptance proofs above.
- **Failed, pre-existing**: the four `tests/unit/harness/test_cursor_local.py` closing-facts
  cases (RF-20), unrelated to this turn.
- **Unrun**: the full unit sweep as one job (host rule), the RF-20 PowerShell 7 set, a T2 run
  (no model needed; spend 0 USD).

## Turn 3 (2026-10-20): subagents, WP-S1 and WP-S2

Owner answers recorded in [SUBAGENTS.md](../../../archive/provider-consolidation-2026-10/specs/SUBAGENTS.md) §4 (Q4–Q7). The sequence a child follows
now reads: manifest `agents:` → compile `subagent_discriminator` (verdicts per lane, seeds queued
as the child's own capability requests) → launch `_subagents` (seeds routed to the child, never
the parent) → `DeepAgentsLaneAdapter` (inherit or seeded child, typed overrides, receipt) →
`compile_deep_agent_execution_binding` → materializer (children's own MCP tools and Skills; the
implicit `general-purpose` child disabled and drift-checked).

| # | Scope | Change | Finished part | Proof |
| --- | --- | --- | --- | --- |
| 3.1 | general | `mc.subagent_profile.v1` gains `capabilities: inherit \| seeded` and `seeds` (exact catalog pins: `skills`, `mcp_servers`, `plugins`, `tools`); an `inherit` profile may omit its prompt and names nothing of its own; `requested_fields()` speaks the one dotted vocabulary `SUBAGENT_FIELDS`; all additive and digest-neutral (published seed bundles unchanged) | `domain/capabilities/subagents.py` | `tests/unit/capability/test_subagent_profile_kinds.py` |
| 3.2 | general | Typed per-lane subagent overrides: `SUBAGENT_OVERRIDE_MODELS` (Deep Agents: `writable_root`, `state_channels`); a lane without a model accepts no key; validated at profile publication | `domain/capabilities/subagent_overrides.py` | same test |
| 3.3 | general | Per-lane subagent field support table: the Deep Agents row declared by its adapter, the file lanes derived from `LANE_LAYOUTS` until WP-S5, the hosted agent APIs all `unsupported`; served beside the describe document as `subagent_fields` on `GET .../lanes/{profile}` (so `missionctl lane describe` shows it) | `application/authoring/lanes/support.py`, `interfaces/http/lanes.py` | `tests/unit/authoring/test_subagent_discriminator.py` (vocabulary completeness), `tests/unit/harness/test_lane_dispatch.py` |
| 3.4 | general | Compile-time `SubagentDiscriminator`: per `agents:` entry and lane, a verdict per requested field (manifest overlay folded in); blockers for named items a lane cannot honour (kind, child shape, seeds, tools, Skills, MCP, `interrupt_on`, placement), warnings for losses; off-lane `provider_overrides` refused; seeds queued at `.../seeds/<group>/<i>` tagged `subagent_seed_of`, plugin seeds expanded to members carrying the owner | `application/authoring/subagent_discriminator.py`, `manifest_service.py::_resolve_mission` | `test_subagent_discriminator.py`; `test_subagent_seeds_compile_and_launch.py`; goldens regenerated (two `readonly` degrade warnings now reported at compile) |
| 3.5 | general | Launch resolver routes seeds to their child (`_seeds`, `_component`), skips them for the parent, and adds the children's seeded MCP credentials and the async deployment credentials to the operation's `secret_refs`; `async_result_policy_refs` handed to the adapter from the deployment | `application/authoring/manifest_launch_inputs.py` | `test_subagent_seeds_compile_and_launch.py`, `test_manifest_launch_inputs.py` |
| 3.6 | deep_agents | The adapter's two child shapes: `inherit` → explicit `SubAgent` with every parent tool, MCP tool and Skill root and the lane's default child prompt (`INHERIT_CHILD_PROMPT`, receipted by digest); `seeded` → narrowing plus `seeded_*` components inside the delegation ceiling, a seed equal to a parent component folded into narrowing, name collisions refused; typed overrides move the writable root and widen the state slice; the lane's `SUBAGENT_FIELDS` row; async graphs need a registered admission policy; receipt rows per child component (`<child>/<component>`) | `application/authoring/lanes/deep_agents.py` | `tests/unit/authoring/test_deep_agents_lane_adapter_children.py` (+ the 8 turn 2 cases) |
| 3.7 | deep_agents | `SyncSubagentProfile` carries `inherits_parent`, `seeded_tools`, `seeded_skills`, `seeded_mcp_servers` (additive, digest-stable); the binding compiler keeps the subset rule and refuses seeded tool names colliding with the parent's | `domain/execution/contracts.py`, `domain/execution/materialization.py` | WP-CP-040 suite unchanged and green |
| 3.8 | deep_agents | Materializer: an inheriting child gets the parent's loaded tools and Skill roots; a seeded child connects its own MCP servers and mounts its own Skill bundles beside the parent's (`_mount_skills` over explicit components, shared bundles mounted once); `_materialize_subagents` is async and returns the children's state files | `adapters/deep_agents/materializer.py` | `tests/unit/deep_agents/test_materializer_children.py` |
| 3.9 | deep_agents | The implicit deepagents `general-purpose` child is disabled through the harness profile registry under the keys `create_deep_agent` consults, and the lookup is replayed: a profile that would still add it is a runtime drift. A node with no `agents:` has no `task` tool; children are exactly the declared ones | `adapters/deep_agents/adapter.py::_disable_implicit_general_purpose_child` | `test_materializer_children.py::test_the_implicit_general_purpose_child_is_never_added` |
| 3.10 | deep_agents | WP-S2: `AsyncSubagentGraphBinding.dependency_classes` defaults to `required_blocking`; the spawn picks its class inside the sealed contract (`spawn_dependency_class`); the admission policy registry `ASYNC_RESULT_POLICIES` lives in the application layer and an unknown ref is refused at launch; `missionctl lane async-graphs` prints the served graphs as a `deep_agents_async_graphs` block; the hosted technical child's model is deployment configuration (`MISSION_CONTROL_ASYNC_TECHNICAL_CHILD_MODEL`) | `adapters/deep_agents/async_subagents.py`, `application/subordinates/parent_completion.py`, `interfaces/cli/main.py`, `adapters/agent_server/async_subagents/bindings.py` | `tests/acceptance/mission_control/test_manifest_async_child.py` |
| 3.11 | general | Retired: the dead `agent_server_endpoint` / `agent_server_api_key` settings and the operation workflow's `record_async_child` signal (no producer ever sent it; the active child ids stay request-fed and the ceiling check stays) | `bootstrap/settings.py`, `adapters/temporal/workflows/operation.py` | `tests/unit/operations/test_operation_execution.py` (three signal tests removed) |

### The async child from a manifest (FX-DA-SUB2, T0, passed)

`tests/acceptance/mission_control/test_manifest_async_child.py`: Mission 2's `research` member on
Deep Agents pins `subagent.async-child` (a catalog row, also published into the installation
catalog); the production launch author seals the `AsyncSubagentContract` from
`deep_agents_async_graphs` and the credential into `secret_refs`; the scripted parent calls
`start_async_task`; the deterministic child on a real local `langgraph dev` answers; after
cognition the child is admitted (`admit`) and settled, the run completes. Evidence:
`.scratch/pc-p1-deep-agents/turn3/acceptance-manifest-async.log` (run
`75c4bade-7a56-5127-a247-0b52fc9e723b`, child `ef507f5b-6fdb-504b-90b6-a95ff7b8b06d`).

### The live drill (FX-DA-SUB3, T2, Sol parent, Luna child)

`tests/acceptance/mission_control/test_manifest_async_child_live.py` (gated by
`BELLABS_RUN_P1_ASYNC_LIVE=1`): the same path with the parent on `gpt-6-sol` through the
production OpenAI factory (a live pin file entry) and the production technical child on
`gpt-6-luna`. Outcome: **child proven, parent not terminal** (two attempts, 2026-10-20 20:48 and 21:05 UTC).

- The Luna child: spawned from the manifest-launched parent's `start_async_task` on the local
  `langgraph dev` serving the production technical child on `gpt-6-luna`; one OpenAI call;
  answered `PONG`; admitted (`admit`) and settled in Postgres (child
  `72bd4d3a-6068-5f88-b59c-d42e2117dbf0`, attempt 2). This is the FX-DA-SUB3 claim for the
  subagent path.
- The Sol parent (`gpt-6-sol`, `reasoning_effort: low`): one executor turn, then the family's
  `goaldirected.reconcile_operation` activity failed with a pydantic `ValidationError` for
  `GoalNamedExecutorObservation` (the real model answered with a near miss: a JSON object with
  `output_bindings: {evidence_map: '/goal/1/executor/work/evidence_map.json'}` where the kernel
  requires `output_refs` as a tuple and two more required fields) and **retried without bound**
  (attempt 82 after 25 minutes) until the test's wait expired; the run never reached a terminal
  outcome. The deterministic parent of the T0 proof emits the typed observation, which is why
  T0 completes.
- Spend: the budget ledger consumed **1,935 tokens** in attempt 2 (parent turn plus child);
  attempt 1 was killed by the default 900 s pytest timeout before its evidence was written
  (its server log shows the same single child call); both far below the 15 USD ceiling.
- Evidence: `.scratch/pc-p1-deep-agents/turn3/live-sol-luna.json` (ids, lifecycle, budget
  ledger, no payloads), `live-attempt-1/` and `live-attempt-2/` (pytest and Agent Server logs).

Findings registered for the next turns (not fixed here, outside this turn's scope):

- **F-T3-1 (kernel, high)**: a Goal Directed executor whose final message does not parse as
  `GoalNamedExecutorObservation` makes `reconcile_operation` retry a non-retryable validation
  error indefinitely instead of settling the operation as failed with a reason. Any real model
  without a structured-output binding hits it (K04/WP-4 territory; a retry classifier case).
- **F-T3-2 (deep_agents, medium)**: `result_output_text` of a child answered through the
  Responses API is the Python repr of the content-block list
  (`[{'type': 'text', 'text': 'PONG', ...}]`), not the text; WP-S4 must extract text blocks
  before the parent reads an admitted result.

### What is still not materialized on this lane (honest list)

- The async child runs the **fixed** technical child; the profile's prompt, tools and Skills do
  not reach it until WP-S3 (sealed child binding by reference; reported `degraded` when a
  profile seeds an async child).
- Result delivery during the parent's cognition (Q4 accepted: admit at check time) is WP-S4.
- A plugin seed's hook, prompt, resource and subagent members are deferred (`degraded`).
- `subagents.fields` is served beside the describe document, not inside the persisted
  `mc.lane_describe.v2`: that needs a lane-describe migration (owner decision, next turn).
- Seeded children on the file lanes (Claude, Codex, Cursor) are refused at compile until WP-S5
  gives those lanes adapters that render seeds and sign receipts.
- `linked_run`, `interrupt_on`, `readonly`, `background`, `context_mode: fork`, `max_turns`,
  `sandbox: own` on sync children: unchanged from turn 2.
- A child observed *using* its seeded MCP tool and Skill on the offline stack: unrun (the
  scripted child answers without calling tools; the materializer-level proof stands).

### Checks run (2026-10-20, Windows host)

- **Passed**: `ruff check .` and `ruff format --check .` clean; `deptry src` clean; `mypy` clean on
  the 21 changed source modules; `tests/architecture` (12); `tests/unit/authoring` and
  `tests/unit/capability` (all, after the goldens were regenerated); `tests/unit/harness/
  test_lane_contracts.py`, `tests/conformance/lanes` and `tests/unit/capability` (400);
  `tests/unit/deep_agents`, `tests/acceptance/control_plane/test_wp_cp_040.py` and
  `tests/unit/integrations/test_capability_directory_bundles.py` (85); `tests/unit/operations/
  test_operation_execution.py` (40); `tests/unit/harness/test_lane_dispatch.py`;
  `tests/acceptance/mission_control/test_manifest_async_child.py` on the live local stack
  (FX-DA-SUB2, 44 s, zero spend).
- **Partial**: the live drill FX-DA-SUB3 (child proven on Luna, Sol parent not terminal: F-T3-1).
- **Interrupted, not failed**: the combined `tests/unit tests/conformance tests/architecture`
  sweep reached 59% with zero failures when the host's memory guard stopped it (the session was
  idle and RAM critically low); it was not restarted. The per-suite runs above cover every
  directory this turn touched; the untouched remainder of `tests/unit` is unrun as one sweep.
- **Unrun**: `tests/acceptance/mission_control/test_postgres_children_and_artifacts.py` (the
  hand-built async binding path; its fixtures still compile and the manifest path supersedes it
  for the proof), the pre-existing RF-20 set (PowerShell 7, harness closing facts, digest guard).
- **Goldens**: `tests/golden/manifests/02-*.resolution.json` and `03-*.resolution.json` gained
  one warning each (`subagent_field_degraded`, `readonly` on deep_agents), regenerated with
  `UPDATE_GOLDENS=1`; `tests/fixtures/catalog/fast_track_seeds.json` regenerated with the three
  new profile rows (`subagent.seeded-researcher`, `subagent.general`, `subagent.async-child`).

## Turn 3 preparation (2026-10-20): process, subagent packet, hand-off

No source changes. [PROCESS.md](../../PROCESS.md) fixes the session sequence (with the owner
confirmation step) and the discriminator-and-router rule; [SUBAGENTS.md](../../../archive/provider-consolidation-2026-10/specs/SUBAGENTS.md) is the
next part's packet (starting state with the two async blockers, the per-lane subagent forms,
the routing decision, owner questions Q1–Q6, work packages WP-S1..S5); `NEXT-SESSION.md`
was the historical next-session instruction (the file is no longer present).

## Turn 2 (2026-10-20): DESIGN §2.1 and §2.2 built

| # | Scope | Change | Finished part | Proof |
| --- | --- | --- | --- | --- |
| 2.1 | general | `mc.subagent_profile.v1` gains `kind` (`sync`, `async`, `linked_run`), `placement`, `sandbox`, `budget`, `provider_overrides`; defaults are excluded from dumps, so every published profile keeps its catalog digest | `domain/capabilities/subagents.py` | `tests/unit/capability/test_subagent_profile_kinds.py` |
| 2.2 | general | Manifest `environment.provider_options`, keyed by lane profile, validated by a per-lane registry; an off-lane key is the compile blocker `provider_options_lane_mismatch`; digest-neutral when unset (ADR 0020 rule) | `domain/authoring/provider_options.py`, `domain/authoring/manifest.py` (`Environment.provider_options`, `_lane_issues`) | `tests/unit/authoring/test_provider_options.py`; committed schemas regenerated (`contracts/schemas/mc.mission_manifest.v{1,2}.json`) |
| 2.3 | general | `mc.materialization_receipt.v1`: per item `native`, `emulated`, `degraded` or `unsupported`, with locator, digest and reason; content-addressed | `domain/execution/materialization_receipt.py` | adapter tests (receipt digest and ordering) |
| 2.4 | deep_agents | The deep module: subagent profiles → `SyncSubagentProfile` (inline digest-pinned prompt, model inherit or profile, tool/Skill/MCP narrowing, state and context slices, ceiling-bounded budget) or `AsyncSubagentContract` (served graph from the new `deep_agents_async_graphs` launch binding); `linked_run` refused with reason; provider options checked against the bound sandbox and placement; receipt signed | `application/authoring/lanes/deep_agents.py` | `tests/unit/authoring/test_deep_agents_lane_adapter.py` (8 cases incl. sealing through `compile_deep_agent_execution_binding`) |
| 2.5 | deep_agents | `SyncSubagentProfile` carries `system_prompt` (must hash to `system_prompt_ref.digest`), `mcp_server_refs`, `interrupt_on`; `DeepAgentProfile` and `DeepAgentExecutionBinding` carry `provider_options` and `materialization_receipt`; all additive and digest-stable (`exclude_if`) | `domain/execution/contracts.py`, `domain/execution/materialization.py` | `tests/acceptance/control_plane/test_wp_cp_040.py` unchanged and green (digests stable) |
| 2.6 | deep_agents | Launch resolver: `node()` runs the adapter; `_subagents` reads profiles from catalog rows (`deep_agents_roles` added to the row pointers); `_capabilities` no longer refuses `agents:`; `_request` seals children, options, slices, degradations and the receipt | `application/authoring/manifest_launch_inputs.py` | `tests/unit/authoring/test_manifest_cursor_launch.py::test_the_deep_agents_verifiers_as_authored_are_refused` (now launches the inherited subagent profile) |
| 2.7 | deep_agents | Materializer honours the sealed binding: inline child prompt, child MCP tools narrowed from the parent's loaded tools, node summarization trigger and keep window | `adapters/deep_agents/materializer.py` | `tests/unit/deep_agents/test_materializer_children.py` |

### What is still not materialized on this lane (honest list)

- `linked_run` subagents (no spawning tool yet; refused at launch with the reason).
- `interrupt_on` (sealed into the binding, reported `degraded`; the materializer wires it with the
  Human Task binding in WP-5).
- `readonly`, `background`, `context_mode: fork`, `max_turns`, `sandbox: own` on sync children
  (reported `degraded` with reasons; the child runs correctly without them).
- Hooks and plugins from manifests on this lane (still refused at `_capabilities`; WP-3).
- Compile-time admission of subagent `kind` against the lane (today the kind is checked at launch
  by the adapter; a compile warning needs the catalog body, which compile resolves but admission
  does not yet read).

### Checks run (2026-10-20, Windows host)

- `ruff check` clean; `mypy` clean on the ten changed modules; `deptry` clean; `ty` reports one
  pre-existing warning (`materializer.py:703`, untouched code).
- `tests/unit/authoring`, `tests/unit/capability`, `tests/unit/deep_agents`,
  `tests/unit/agentic_components`, `tests/acceptance/control_plane/test_wp_cp_040.py`: all pass
  (1 skip: no Python 3.8–3.10 on PATH).
- `tests/unit/{harness,operations,integrations,control_plane,runtime,mission_control}` and
  `tests/conformance`: 1407 passed; the 28 failures are the pre-existing RF-20 set (22
  `run2_worker_deploy_script` cases needing PowerShell 7, 4 `harness` closing-facts, 2
  `control_plane` digest-guard), unrelated to this change.
- `generate_catalog_seeds.py --check` and `manifest_schemas.py --check` pass; the committed
  cognition-profile seed bundles keep their bytes because the new profile fields are marked
  `digest_omit_default` (the stable JSON walker ignores `exclude_if`, a general rule to know:
  an additive contract field needs both).
- `tests/architecture`: 12 passed (the new `application/authoring/lanes` package respects the
  boundaries).

## Turn 1 (2026-10-20): audit and design

No source changes. [AUDIT.md](../../../archive/provider-consolidation-2026-10/docs/AUDIT.md), [DESIGN.md](DESIGN.md), the offline live trace
(private evidence under `.scratch/pc-p1-deep-agents/`).
