---
type: Concept
category: execution
title: The Model Catalog and model routes
description: How Model Profiles are declared as data in deployments/<app>/models.toml (vendor, exact model id, context window, list prices, supports, structured-output strategy, Data Class ceiling), loaded into the Model Catalog at bootstrap, paired with a lane's declared model routes at resolution (MODEL_ROUTE_UNSUPPORTED), referenced by the Deep Agents launch bindings, and listed for a coordinator over HTTP and missionctl.
tags: [mission-control, models, resolution, lanes, deep-agents, interfaces, implementation]
aliases: [Model Profile, models.toml, model routes, model route verdict]
questions:
  - Which models exist and which lane can route each one?
  - How do I add a model route or a model profile?
  - How does a node's output schema bind to a model's structured-output strategy?
  - Where are model prices read, and by whom?
updated: 2026-11-01
---

# The Model Catalog and model routes

A **Model Profile** (`mc.model_profile.v1`, ADR-0063, OC-R6) is one `[[models]]` row of
`deployments/<app>/models.toml` (`mc.model_catalog.v1`): the name a manifest writes in
`environment.model.profile`, its `vendor` (`anthropic` or `openai`), the exact `model_id`, the
vendor's `context_window_tokens`, the largest prompt it accepts (`max_input_tokens`: what sizes a
context, at most the window), the list prices `cost_per_million_input` / `_output` (USD) with any
long-prompt `[[models.price_tiers]]` (`above_input_tokens`, billed for the whole request), what it
`supports` (structured output, tool use, images) and its `data_class_ceiling`. A row names no
lane. The checked-in catalogs of both applications carry the PROOFS §6 pins as `*.default`
(producer `claude-sonnet-5-5`, judge `gpt-5.6-terra`, auditor and child `claude-haiku-5-5`, probe
`gpt-5.6-luna`) and the fallbacks as `*.fallback`, so the W0 availability probe substitutes by data.
Each row's facts cite the vendor page and retrieval date in the file; every ceiling is `internal`
(both vendors retain API inputs and outputs up to 30 days without a separate ZDR or BAA).

**Loading.** `bootstrap/model_profiles.py::compose_model_catalog(root, app)` parses the file into the
`ModelCatalog` (`application/resolution/registries.py`); a missing file, an invalid row or a profile
named twice fails closed (`ModelCatalogError`). The manifest launch author
(`bootstrap/manifests.py::compose_manifest_launch_inputs`), the readiness preflight
(`bootstrap/preflight.py`, `MODEL_CATALOG_UNAVAILABLE`, `MODEL_PROFILE_UNCATALOGUED`) and the API
(one catalog per configured application) compose it. There is no settings default model any more.

**Pairing.** The resolver looks the profile up (`MODEL_UNKNOWN`), then asks the lane's declaration
for a route for the row's vendor: none, or `unsupported`, refuses `MODEL_ROUTE_UNSUPPORTED` at the
manifest's `model.profile`; it also bounds the mission's Data Class by the row's ceiling. The
resolved `ModelPin` is the row, with the mission's mapped settings. A lane declares its routes in its
package: the Deep Agents lane's are `adapters/deep_agents/routes.py::DEEP_AGENTS_MODEL_ROUTES`
(both vendors `native`, in-process `ChatAnthropic` / `ChatOpenAI`); the other lanes' come with their
registrations (R3).

**API surface (W1 D24).** An OpenAI row declares `api_surface`: `responses` is required on every
OpenAI row whose calls carry function tools (`tool_use`, or a `tool_forced`/`tool_auto` strategy),
because OpenAI refuses function tools with reasoning on `/v1/chat/completions` for gpt-5.6-terra
("use /v1/responses or set reasoning_effort to 'none'", W1 session 7). Loading `models.toml`
refuses an OpenAI tool row without it (`API_SURFACE_UNSUPPORTED`), a non-OpenAI row may not declare
one, the lane compiles it into the model component (`settings.use_responses_api`; a binding that
sets it false is `api_surface_conflict`) and the trusted evaluators build `ChatOpenAI` with
`use_responses_api` (`RolePin.api_surface`). Every checked-in OpenAI row (gpt-5.6-terra,
gpt-5.6-luna, gpt-5.4-mini) declares `responses`; the model keeps its own reasoning. Proof:
`tests/unit/resolution/test_w1_d24_api_surface.py`, the judge's `/v1/responses` body in
`tests/unit/knowledge/test_w1_d23_evaluator_causes.py`.

**Structured-output strategy (W1 D16, D18).** A row that `supports` structured output declares
`structured_output = "tool_forced"` (the schema is a tool the model must call: `tool_choice` any),
`"provider_native"` (the vendor's response-format constraint: Anthropic `output_config.format`,
OpenAI `response_format`, with `tool_choice` auto) or `"tool_auto"` (an ordinary tool with
`tool_choice` auto: `structured_response.with_auto_tool_choice` never forces it and
`RequireStructuredResponse` reminds a turn that ends without the call, twice at most; no grammar
is compiled); a row that does not support it declares none (`ModelProfile` validator). Claude
Sonnet 5.5 refuses forced tool choice (D16) and compiled the executor observation as "Schema is too
complex" (D18), so its rows are `tool_auto`; Claude Haiku 5.5 rows are `tool_forced`, and
the OpenAI rows keep the strategy LangChain auto-detection gave them in the earlier proofs. The
pin carries it (`ModelPin.structured_output`, digest-neutral when absent); a lane route lists the
strategies it realizes (`ModelRoute.structured_output`, both for both Deep Agents routes) and the
compile refuses an unrouted one (`MODEL_ROUTE_UNSUPPORTED`) and seals it into
`DeepAgentModelComponent.structured_output`. The materializer wraps the node's output schema in
exactly that strategy (`materializer.response_format_for`: `ToolStrategy` or `ProviderStrategy`,
never a raw schema LangChain would auto-detect) and refuses a component without one; the launch
author refuses any family's template that binds a schema on a row without one, and the trusted
evaluators (`RolePin`, `EvaluatorBinding`) bind theirs the same way. For `provider_native` on
Anthropic, `adapters/deep_agents/output_format.py` computes the exact `output_config.format`
schema langchain-anthropic sends (`anthropic.transform_schema`) and refuses one outside the
supported subset (unsupported keywords or types, an object without `additionalProperties: false`,
recursion, the published 24 optional / 16 union-typed parameter limits, and a self-chosen
heuristic budget of 24 properties / 12 optional / 8 union-typed, not an Anthropic limit, set
below the one D18 failure at 30 / 23 / 1, which may refuse a schema Anthropic would compile)
before any model call; every registered goal and evaluator schema is checked offline against
every checked-in row's strategy. `tool_auto` parses a JSON-string object field once (D17 rules),
refuses a response call mixed with other tool calls, and bounds reminders plus refused calls at
three per invocation (marked messages, append-only).
Such a fault is `OutputSchemaUnsupported`: the operation settles `failed` with
`output_schema_unsupported` once, never retried; the trusted path checks its evaluator rows and
answer schemas at composition (`OUTPUT_SCHEMA_UNSUPPORTED`).

**Deep Agents bindings are references.** `mc.manifest_launch_bindings` `model_profiles` maps a catalog profile name to the served definition and default settings, never a vendor or model id; the compile
pairs each binding with its row and seals the resolved vendor and model id ([agent configuration](agent-configuration.md#the-compile-path-and-its-refusals), `compile.catalog_model_components`). Every served model
definition states what it serves (the pin file's `models[].provider` and `model_id`, or a registered component's `model_identities`); composition and readiness compare it with the row
(`MODEL_PIN_VENDOR_MISMATCH`, `MODEL_PIN_MODEL_MISMATCH`, `MODEL_PIN_UNDECLARED`), the worker's `ExactModelFactory`/`IdentityCheckedModelFactory` enforce it, and a registered factory may not replace a
pinned one (`MODEL_FACTORY_COLLISION`); only a composition flagged `qualification` is exempt. The hosted async technical child runs on the installation's `child.default` row
(`adapters/agent_server/async_subagents/bindings.py`). Vendor feature rows (`anthropic.*`, `openai.*`) live in the same `routes.py`; the manifest compile refuses an unknown or misconfigured
`model_tools` entry through the lane's `ChecksLaneOptions` (`application/resolution/lane_options.py`), with no vendor vocabulary in the core.

**Listing.** `GET /v1/applications/{app}/models` and `GET .../models/{profile}`
(`interfaces/http/models.py` over `application/resolution/model_listing.py`) and
`missionctl model list|describe` return each profile with vendor, id, window, prices, supports,
ceiling and a route verdict per lane profile of the vocabulary: `native | emulated | unsupported`
from a registered `LaneRegistration`, `unbound` for a lane the installation binds no credential
for (absent from `lane list`, OC-R3), `unregistered` for one listed with a runtime-only describe.
`lane describe` carries the lane's `model_routes` (`null` without a registration). These profiles
seed workflows; the AI Engineer knowledge schema's model entities are knowledge and unrelated.

One runtime consumer reads prices: the trusted evaluators price `usage.costUsd` from the `models.toml` row (base or long-prompt tier by input tokens;
`adapters/deep_agents/evaluators.py:22-24,183-186`; test `tests/unit/resolution/test_w1_d24_api_surface.py`). Lane budgets do not yet read prices or windows: Deep Agents reports tokens and turns, not cost
([budgets and usage](budgets-and-usage.md), [Deep Agents lane](deep-agents-lane.md)). The example and test launch bindings still bind fixture names `frontier.*`, which the installed catalogs do not declare.

Built / specified / goal: catalog, routes, listing and structured-output binding built and tested; Deep Agents routes both vendors natively; other lanes' routes are declarations only.

## Citations

- Research: [capability evolution](../research/mission-control/capability-evolution-2026-10-14.md) (how models and capabilities adapt as providers change).
- Code: [catalog loader](../../src/mission_control/bootstrap/model_profiles.py),
  [registries](../../src/mission_control/application/resolution/registries.py),
  [resolver](../../src/mission_control/application/resolution/resolver.py),
  [routes](../../src/mission_control/adapters/deep_agents/routes.py),
  [compile](../../src/mission_control/adapters/deep_agents/compile.py),
  [output format](../../src/mission_control/adapters/deep_agents/output_format.py),
  [listing](../../src/mission_control/application/resolution/model_listing.py),
  [HTTP](../../src/mission_control/interfaces/http/models.py),
  [biotech catalog](../../deployments/biotech/models.toml).
- Tests: [catalog pairing](../../tests/conformance/resolution/test_model_catalog_pairing.py),
  [structured-output strategy](../../tests/unit/deep_agents/test_structured_output_strategy.py),
  [model routes](../../tests/unit/deep_agents/test_model_routes.py),
  [listing](../../tests/unit/harness/test_model_listing.py).
- Decisions: [ADR-0063](../adr/0063-one-resolution-seam-over-declared-lane-model-and-application-registries.md),
  OC-D185 and OC-D201 ([decisions](../specs/provider-consolidation-2026-10/sprint-oc/DECISIONS.md)).
