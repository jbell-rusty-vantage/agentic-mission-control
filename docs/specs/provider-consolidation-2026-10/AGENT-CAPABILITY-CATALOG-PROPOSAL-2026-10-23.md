---
type: Proposal
title: "Provider-specific tooling as catalog rows: how lane features and model tools are stored, searched and selected by a coordinator, and how they slot into workflows (AC-D1..D12)"
description: "Proposes the storage model for the agent capability registry built in sprint B's first slice (Deep Agents lane features, OpenAI and Anthropic model tools): one catalog kind `agent_feature` whose rows carry the registry's classification (axis, category, facet, mechanism, provenance, status) as searchable facets, a projection the hybrid capability search (ADR-0025) indexes, the coordinator's select-by-id path through the existing capability pin flow, and where a selection lives in a mission manifest per workflow system. Decides nothing; AC-D1..D12 are the owner's."
tags: [mission-control, providers, consolidation, proposal, capabilities, deep-agents, coordinator, search]
---

# Provider-specific tooling as catalog rows

Written 2026-10-23 after the first slice of sprint B landed (Linear `OVE-148`): the registry in
`domain/capabilities/features/`, the sealed `mc.agent_configuration.v1`, the builders in
`adapters/deep_agents/features/` and the Anthropic model factory. This page answers the owner's
open question from the brief: *"I don't know yet how we are going to model the storage of these
provider specific toolings and make them searchable and thus selectable by a coordinator agent."*

It proposes; it builds nothing. The code it cites is what exists today; the storage, the search
projection and the coordinator surface are the proposal. Decisions are collected as AC-D1..D12
at the end so they can enter an interview sitting beside R3.1..R3.7.

## 1. What exists after the first slice

| Part | Where | What it is |
| --- | --- | --- |
| The registry | `domain/capabilities/features/registry.py` (+ `deep_agents.py`, `openai.py`, `anthropic.py`) | 26 rows, each with `axis` (lane feature / model tool), `category` (six agentic domains), `facet` (precise sub-domain), `provenance`, `mechanism`, `observability`, `adds_graph_nodes`, `default`, `required`, a typed `config_model`, `status`, `requires`, `rank` |
| The selection | `provider_options.deep_agents.lane_features` / `.model_tools` (`domain/authoring/provider_options.py`) | Names validated against the registry at manifest validation; canonical configs stored |
| The sealed form | `mc.agent_configuration.v1` (`features/configuration.py`), on `DeepAgentProfile` and `DeepAgentExecutionBinding` | Defaults inserted explicitly; each item repeats its classification and carries a config digest; part of the binding digest |
| The receipt | `MaterializationItem(kind="feature" \| "model_tool")` from `application/authoring/lanes/deep_agents.py::_agent_configuration` | One row per item with verdict, locator and reason (a host shell is `degraded`; a shell on the state backend is `degraded` only when named) |
| The realization | `adapters/deep_agents/features/builders.py`, `materializer.py`, `adapter.py::_compile` | Middleware rows after Mission Control's own middleware in rank order; dict tools beside the agent's tools; model settings merged into the exact model component before the factory; the configured filesystem replaces the stock one by name with the effective permissions |
| The model axis | `AnthropicExactModelFactory`, `model_factory_for`, `PinnedModel.provider`, `MANIFEST_PROVIDER_SECRET_ENV` | A `provider: anthropic` model profile in the launch bindings plus a pin is a model choice; the credential reference resolves like OpenAI's |
| The proof | `tests/integration/deep_agents/test_agent_configuration_live.py` (FX-B-FEATURES) | Haiku 5.5 with todo list, context editing and call limits (0.0009 USD); GPT-6 Luna with a provider-executed web search (0.0011 USD) |

The registry is code, not catalog. That is deliberate for the first slice: a row's realization is
a reviewed builder, so a row cannot exist without code behind it, and the owner's interview has
not yet fixed the manifest spelling (R3.1). The question is how the same rows become **catalog**
facts a coordinator can search, without duplicating them.

## 2. The storage model: one kind, rows projected from code

### 2.1 A catalog kind `agent_feature`, canonical in SQL (ADR-0020), provider-neutral core (ADR-0023)

Add one capability kind to the common component: `agent_feature`. One row per registry entry,
written by a seed step from `AGENT_FEATURES.describe()` (the registry stays the source of the
rows' meaning; the catalog is where they are searched and pinned). A row's provider-neutral core
is the classification the registry already carries; its "host support" is the two axes:

```text
asset_version.kind = 'agent_feature'
logical_id          = the registry id            e.g. deep_agents.context_editing
revision            = bumped when config_model or realization changes
digest              = sha256 of describe() minus volatile fields
core (jsonb)        = {axis, category, facet, provenance, mechanism, observability,
                       adds_graph_nodes, default, required, status, requires, summary,
                       config_schema}
host_support        = lane features: {deep_agents: supported}, every other lane: unsupported
                      model tools:   {<lane that drives an LLM through LangChain>: supported}
                      + a `model_provider` overlay: openai | anthropic
search_text         = id + category + facet + provenance + summary + config field names
```

Why a kind of its own and not `tool` or `middleware`: a `tool` row is something the agent calls
by name through the tool node; a model tool of mechanism `provider_tool` is never in the tool node
and a `model_setting` row is not a tool at all. Reusing `tool` would make "tools the agent may
call" and "ways the model is configured" indistinguishable in search results and in receipts.
The old `middleware` kind (which ADR-0023 stopped mapping to `hook`) is also not reused: the
registry rows are *curated features*, not catalog-authored middleware code (OWNER-INTERVIEW R3.3,
option (c) rejected).

### 2.2 Facets are columns, not prose

The hybrid capability search (ADR-0025: Postgres full text and embeddings fused by RRF, lexical
fallback) ranks by text. Classification must also be a **filter**, because a coordinator asking
for "context editing on Anthropic" wants an exact cut, not a ranked guess. The projection table
therefore carries `axis`, `category`, `facet`, `mechanism`, `provenance`, `model_provider` and
`status` as indexed columns beside the search vector. A search request gains optional filters on
those columns; the text query ranks within the cut.

### 2.3 What is not stored

- Builders, middleware classes and SDK versions: realization is code behind the digest.
- The mission's configuration values: those live in the manifest and the sealed binding.
- Package floors as data the catalog enforces: `status` and `requires` are informative; the
  refusal happens at compile time against the installed registry (`features/configuration.py`),
  which is what actually runs.

## 3. Search: how a coordinator finds a feature

The coordinator already has one search path for capabilities (`capability_search` in the
operator MCP and `missionctl catalog search`). The proposal is to extend that path, not add a
second one:

1. **Query shape.** `capability_search(text, kinds=["agent_feature"], filters={category,
   facet, axis, model_provider, status, mechanism})`. The default `status` filter is
   `available`; `needs_upgrade` and `planned` rows appear only when asked for, with their
   `requires` text, so the coordinator can tell the owner what an upgrade would unlock.
2. **Result card** (PR-07's card shape): id, category and facet, one line of summary, the
   mechanism and observability in words ("provider-executed; no hook or limit sees its calls"),
   `adds_graph_nodes` as a warning line, the config schema's required fields, and the default
   flag. The card is the same text `missionctl lane features deep_agents` prints.
3. **Describe cells.** Every row generates one describe cell per lane
   (`application/execution/harness/describe.py`): `supported` on `deep_agents`, `unsupported`
   elsewhere with the registry's own wording, so the coordinator's lane choice and feature
   choice are checked by the same matrix.
4. **Skill reference.** The `mission-control-coordinator` skill gets a generated section
   listing the rows by category with the manifest spelling, regenerated by the docs tools
   (`docs/tools/agents_docs_index.py` convention) so the skill never drifts from the registry.

The first-slice `FeatureRegistry.search` is the T0 version of step 1: lexical over id, category,
facet, provenance, mechanism and summary. It is enough for tests and for `missionctl` until the
projection exists.

## 4. Select: from a search hit to a sealed binding

Selection follows the existing pin flow so nothing new is sealed:

1. The coordinator writes the id into the manifest at the agent it configures (today:
   `environment.provider_options.deep_agents.lane_features.<name>` or
   `.model_tools.<provider>.<name>`; after R3.1: `lane_features:` / `model_tools:` on the
   `agents:` entry). A pin is the id plus revision; the catalog row's digest is what the
   compile checks the installed registry against (`registry_drift` when the worker's registry
   revision differs from the pinned row).
2. Manifest validation refuses unknown names and invalid configs (done; `provider_options.py`).
3. The lane adapter resolves defaults, refuses axis and provider mismatches and unavailable rows,
   and receipts each item (done; `lanes/deep_agents.py::_agent_configuration`).
4. The binding seals `mc.agent_configuration.v1`; the receipt and the `environment_materialized`
   frame carry the ids and config digests (done).
5. The transcript shows what each row did: middleware rows through their tool calls and graph
   nodes, provider-tool rows through `server_tool_call` / `web_search_call` content blocks on
   the model message (observed in FX-B-FEATURES; a dedicated frame class is R3.5's decision).

What stays the coordinator's judgement and what the system checks is the same split as for
skills and MCP servers: the coordinator chooses, the compiler refuses what cannot run, the
receipt says what ran.

## 5. Where a selection lives per workflow system

A feature is a property of an **agent** (the configuration of one harness instance), never of
a workflow system. The workflow annexes (`mission-control-general/workflow-types/` (deleted 2026-11-01; last at `66185d2e`)) compose
agents into Stage Graph, Goal Loop, Parallel Swarm and Evaluator Optimizer programs; each node
runs one agent with one sealed binding. So:

| Workflow system | Where the selection lives | Notes |
| --- | --- | --- |
| Stage Graph | the node's `environment` (overlay over the mission environment) | per-stage differences are overlays: a research stage adds `openai.web_search`, a synthesis stage adds `deep_agents.context_editing` |
| Goal Loop | the loop's environment; iterations share it | `deep_agents.call_limits` per iteration is the natural governor; summarization and compaction knobs matter most here |
| Parallel Swarm | the swarm's worker environment (one for all workers) and the reducer's | PR-08's compute pools would let a pool pin the shell row (`execution: docker` vs the sandbox) |
| Evaluator Optimizer | producer and evaluator environments separately | `anthropic.memory` on the producer, `deep_agents.rubric` (planned) on the evaluator |
| Sync subagents | inherit the parent's configuration today (one stack per child from the parent's model and tools); `provider_overrides.deep_agents.lane_features` per child is a later slice | model tools follow the child's model provider, so a child on another provider cannot inherit the parent's model tools |
| Async subagents (Agent Server) | the served graph's own binding | the graph host's registry decides; the parent's selection does not travel |

Inheritance follows the manifest's environment overlay rules (ADR-0044: additive instruction
layering, structural config merge): a node may add rows and reconfigure rows; it cannot remove
a required row.

## 6. Composition with the catalog's other kinds

- **Plugins** (ADR-0023) may pin `agent_feature` rows beside skills and MCP servers: a
  "literature research" plugin pins `openai.web_search` or `anthropic.web_search` by the
  model provider it was written for, and the compile refuses the plugin on a mismatched model
  with the same `model_tool_provider_mismatch` pointer.
- **Environment kits** (ADR-0042) may carry a default `lane_features` block (a kit for a
  Docker sandbox sets `bash: {execution: sandbox}` and the eviction limits).
- **Hook scripts** (ADR-0026) are the neutral alternative for behaviour that does not need to
  be middleware; the registry's `observability` tells a coordinator when a hook will not see a
  call (provider tools), which is when a hook script cannot substitute for a feature.

## 7. Decisions for the owner (AC-D1..D12)

| ID | Question | Strawman |
| --- | --- | --- |
| AC-D1 | One catalog kind `agent_feature` for both axes, or two (`lane_feature`, `model_tool`)? | one kind, `axis` as a column |
| AC-D2 | Rows seeded from code (`describe()`) by a release step, or authored in the catalog with the code checking against them? | seeded from code; the registry is the authority |
| AC-D3 | The six categories and the facet list as fixed enums (a new facet is a code change) or an open vocabulary? | fixed enums; search needs stable filters |
| AC-D4 | `status` filter default `available` in search; show `needs_upgrade` rows with their `requires` text on request? | yes |
| AC-D5 | Manifest spelling after R3.1: keep the rows under `provider_options.deep_agents` or lift `lane_features` / `model_tools` to the agent entry? | lift; the names already match the strawman |
| AC-D6 | Model-tool observability (R3.5): accept `server_side` rows on missions that require approvals, recorded from content blocks as `server_tool_call` frames? | accept and record; refuse only when the mission's effect gating names the facet (web, code execution) |
| AC-D7 | Default rows: filesystem always; bash by default only on sandbox backends (built); prompt caching by default on Anthropic (built). Confirm? | confirm |
| AC-D8 | Per-child selection: `provider_overrides.deep_agents.lane_features` on a sync subagent profile, inheriting the parent's rows unless overridden? | yes, after OC-2 (subagent transfer) |
| AC-D9 | Plugins may pin `agent_feature` rows? | yes |
| AC-D10 | A `missionctl lane features <lane>` command and the `capability_search` filters as the first surface, before the catalog projection? | yes; the T0 lexical search backs it |
| AC-D11 | Registry drift at launch: refuse when the worker's registry revision differs from the pinned row, or receipt `degraded` and continue? | refuse (`registry_drift`), as for every other exact component |
| AC-D12 | Which rows join the next slice: `deep_agents.memory`, `deep_agents.rubric`, `anthropic.text_editor`, OpenAI `tool_search` through `ProviderToolSearchMiddleware`? | memory and rubric after OC-4; tool search when the catalog has enough tools to need it |

## 8. What this does not propose

- A dynamic or general knowledge service for features; the registry is static code by design.
- Arbitrary middleware by import path (R3.3 option (c)).
- Changing the sealed `mc.agent_configuration.v1` shape; the catalog projection reads it.
