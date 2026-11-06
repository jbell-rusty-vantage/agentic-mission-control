---
type: Research
title: "Mission Control capability evolution: research and design exploration (2026-10-14)"
description: "How agents discover and compose capabilities across the leading sandboxed runtimes while keeping useful native features and adapting as providers evolve: verified external facts, observed local structure, and design proposals; the starting research of the next-stage contract design."
tags: [mission-control, research, capabilities, providers, catalog]
subject: Capability discovery, composition and evolution across provider runtimes
versions: [mission-control HEAD 0a75b6ea (2026-10-14), provider docs as opened 2026-10-14]
sources:
  - platform/MISSION-CONTROL-CAPABILITY-EVOLUTION-RESEARCH-2026-10-14.md (workspace path, outside any git repository)
  - official provider documentation cited inline in the body
observed: 2026-10-14
confidence: external rows are documented; local rows are source observations at the stated revision; proposals are not decisions
used_by: [capabilities, model-catalog]
date: 2026-11-01
---

# Mission Control capability evolution: research and design exploration

Research date: **2026-10-14**. Local inspection anchor: **2026-10-14 18:53:51 UTC**; initial repository inspection began around **18:51:50 UTC**. Repository inspected: `platform/mission-control`, initial HEAD `0a75b6eac23a2d36907942e7f712e05cb26e39cb`. Other agents advanced HEAD during this read-only research; final observed HEAD at **19:04:08 UTC** was `d9e570cbe0a0072e1120a06c1dcfe77402f14736`. Source observations are from the shared live checkout during this interval, not an atomically frozen checkout. This standalone report is outside that repository. It is research input for subsequent specifications/issues; it does not amend accepted architecture or implement any proposal.

Evidence labels used throughout: **Intent** means the owner's requested behavior; **Verified external** means an official source inspected during this research; **Observed local** means a source-level observation at the revision/time above; **Proposal** means an architectural option requiring later specification and qualification; **Unknown** means documentation, account access or execution evidence does not establish the combination. Documentation support is not a successful integration test.

## 1. Scope, method and important findings

**Intent.** Mission Control should guide agents toward efficient, reliable capability discovery and run composition across leading sandboxed runtimes, while retaining useful native features and adapting as providers evolve. An individual agent configuration selects one runtime. A mission can compose multiple such configurations. A runtime provider, a model vendor, a hosting provider and a billing route are separate dimensions: Deep Agents using an Anthropic model is still a Deep Agents runtime.

**Observed local.** The code already supports much of the necessary control-plane structure: immutable execution bindings, digest-pinned capability bundles, hybrid search, host support overlays, lane-specific projection, structural configuration merging, artifact promotion, durable human gates, native event retention and provider wake signals. The report therefore examines extension and evidence gaps, rather than proposing a replacement orchestrator. Temporal scheduling and application reducers remain the accepted local authority.

**Research finding.** Provider product distinctions are essential. Anthropic Messages, Claude Agent SDK and Managed Agents differ in execution ownership and tool support. OpenAI Agents SDK, Codex local/cloud and the newer hosted Agents API are also different products. Cursor's local editor/CLI/SDK and its cloud API need separate qualification. Current Deep Agents features exceed what the local pinned 0.7.5 adapter admits. A uniform boolean such as `supports_subagents` or `supports_webhooks` loses decisive conditions.

**Proposal.** Use a stable domain-neutral contract with versioned, typed provider extensions and a separately refreshable evidence catalog. Search can be current while admitted executions remain exact and reproducible. Reject required unsupported combinations before launching; show optional degradation explicitly. Capture actual route, loaded capabilities, usage and immutable outputs in receipts.

Only this report is written. No installs, checks that mutate repository state, paid provider calls, fixtures, migrations, commits or deployment are authorized. Workspace and scoped AGENTS.md files were read. Existing untracked `mission-control/docs/specs/materialization-observation-2026-10/issues/bash.exe.stackdump` was observed and preserved. An initial Git command from `platform` failed because it is not a Git repository; read-only Git inspection was then performed from `mission-control`. Two guessed source paths did not exist and were replaced by searches. These were navigation errors, not execution blockers. Account-specific entitlement, billing and live sandbox behavior remain untested.

## 2. Requirement extraction by concern and dependency

The IDs below are report-local traceability labels, not priorities or issue IDs. They preserve the request's full breadth and show dependencies without assigning delivery order.

| ID | Intent / requirement | Concern and dependency | Evidence or treatment |
| --- | --- | --- | --- |
| R01 | Guidance/adaptation across top sandboxed runtimes, retaining native advantages | Runtime identity and discovery | Sections 3–6 |
| R02 | Prevent stale skills/configuration as products evolve | Catalog versions, evidence freshness, compatibility | Sections 5, 7 |
| R03 | Efficient agent learning, search, fetch and configuration | Progressive disclosure and exact pinning | Sections 5, 7 |
| R04 | Separate system defaults, coordinator/user choices and non-overridable policy | Authority/provenance and admission | Section 8 |
| R05 | One runtime per agent; mixed providers across workflow | Execution binding and graph composition | Sections 3, 12 |
| R06 | Runtime differs from model provider; Deep Agents supports multiple vendors | Client/protocol/model-route catalog | Sections 4, 6 |
| R07 | Preserve native web search and computer use when actually supported | Product/model/protocol/tool version matrix | Provider research annex |
| R08 | Distinguish Anthropic API, Agent SDK and Managed Agents | Product taxonomy | Provider research annex |
| R09 | Distinguish OpenAI Agents SDK, Codex local/cloud and hosted API | Product taxonomy | Provider research annex |
| R10 | Distinguish Cursor local/cloud, subagent file loading and invocation | Materialization/discovery proof | Provider research annex |
| R11 | Verify Deep Agents compaction thresholds, defaults and custom prompts | Versioned middleware and model metadata | Provider research annex; local gap G03 |
| R12 | Verify sync, async, dynamic and compiled-graph/deep-agent delegation | Ownership, resource/authority ceilings | Sections 4, 8; annex |
| R13 | Identify QuickJS's actual role | Tool execution versus OS sandbox | Annex; section 13 |
| R14 | Make capabilities selectable/customizable; disclose unsupported/unknown combinations | Admission and typed extensions | Sections 5, 7 |
| R15 | Model discovery, choice and provider identifier mapping are central | Model metadata and routes | Section 6; annex |
| R16 | Investigate Gateway exact paths, clients and native-tool limits | Protocol-specific compatibility | Section 6; annex |
| R17 | Explain direct Anthropic credits versus Gateway/BYOK billing | Billing identity and fallback | Section 6; annex |
| R18 | Native runtimes select from their allowed/entitled model sets | Account/provider authority | Sections 6, 8 |
| R19 | Versioned capability catalogs and adapter manifests | Evidence and schema evolution | Sections 5, 7 |
| R20 | Typed provider extensions without opaque config dumping | Validation and explanation | Sections 7, 8 |
| R21 | Meaningful coordinator and process hooks/callbacks | Enforcement versus observation | Section 9 |
| R22 | Verify actual webhook events by provider product | Event namespace and transport | Section 9; annex |
| R23 | Distinguish webhook, stream, local hook and polling | Observation/control semantics | Section 9 |
| R24 | Explore Vercel receiver, signatures, durable queue, idempotency, retries/order and Temporal signals | Ingress reliability | Section 9 |
| R25 | Separate file references, inline model context and sandbox materialization | Artifact transport | Section 10 |
| R26 | Represent any artifact type even if a model cannot consume it | Domain-neutral custody | Sections 10, 11 |
| R27 | MIME/bytes/tokens/checksums/storage/URLs/permissions/provenance/retention/security | Upload admission and materialization | Sections 10, 13 |
| R28 | PDFs and other content/media alongside research, ingestion and code | Output goals and validation | Sections 11, 12 |
| R29 | Domain-neutral artifact/version/evidence/goal contracts | Core boundaries | Section 11 |
| R30 | Future AI Engineer course/challenge and biotech protocol projections, no invented final schemas | Domain adapters | Section 11 |
| R31 | Human checkpoints show actual immutable artifacts/previews | Review packet integrity | Section 11 |
| R32 | Feedback, refine/continue/approve/reject and durable pause/resume | Human control and remediation | Sections 11, 12 |
| R33 | Review approval differs from publication/deployment | Effect grants and checkpoint purpose | Sections 8, 11 |
| R34 | Attributable validation/evidence for content and code | Acceptance semantics | Section 11 |
| R35 | Dated matrix and local gap map with revision/file evidence | Research auditability | Sections 4, 14; annex |
| R36 | Options/tradeoffs, illustrative contracts, defaults, mixed mission | Reviewable design exploration | Sections 7, 8, 12 |
| R37 | Security/cost/reliability and explicit unknowns/questions/further research | Qualification plan | Sections 13, 15 |
| R38 | Research only, preserve concurrent work and canonical docs | Task boundary | Sections 1, 16 |

Dependency relationships: model metadata informs context budgeting and tool compatibility; capability admission informs projection and discovery proof; artifact custody precedes review and cross-runtime transfer; verified event ingress precedes durable control application; acceptance precedes any separately authorized publication. None of these relationships implies a ranking of the requested concerns.

## 3. Runtime taxonomy and semantic boundaries

**Proposal.** Describe execution with five explicit dimensions:

1. **Harness/runtime**: Deep Agents, Claude Agent SDK, Codex app server, Cursor SDK/CLI or a hosted agent API.
2. **Placement**: local worker sandbox, provider cloud environment or qualified self-hosted environment.
3. **Model route**: vendor, exact model ID, protocol, endpoint and optional Gateway routing policy.
4. **Capabilities**: native tools, caller-executed tools, MCP, skills, middleware, hooks and delegation modes.
5. **Authority and billing**: account entitlement, grants, policy profile, payer and resource budgets.

A raw model API is not automatically a sandboxed agent harness. A hosted model-side search tool does not mean the agent has a browser workspace. A computer-use tool may ask the caller to execute actions in a separately provisioned environment. A LangGraph checkpoint does not establish OS isolation. A provider session's idle/completed status does not establish output acceptance.

The accepted local specification distinguishes execution completion, output validity, evidence disposition, mission acceptance, domain admission and publication. Preserve those distinctions when adding products. The current lane vocabulary is an implementation vocabulary, not a statement that every product has passed live parity: `deep_agents`, `cursor_local`, `cursor_cloud`, `claude_agent_sdk`, `codex`, `claude_cloud`, `codex_cloud`, `claude_managed`, `codex_agents` ([local host support](../../../src/mission_control/domain/capabilities/host_support.py), [bindings](../../../src/mission_control/domain/execution/bindings.py)). In particular, `codex_agents` currently denotes the OpenAI Agents API, not the open-source Agents SDK; naming deserves explicit explanation in user-facing discovery.

## 4. Dated capability matrix and interpretation

This matrix is a **2026-10-14 documentation snapshot**, with expanded sources and exact limitations in the provider annex. `Conditional` means model, SDK version, placement, endpoint or account matters. `Caller-owned` means the application must implement execution/hosting. `Unknown` is not a promise of forthcoming support.

| Product | Execution / sandbox ownership | Models | Web/computer capabilities | Composition / context | Controls and observations |
| --- | --- | --- | --- | --- | --- |
| Anthropic raw Messages API | Caller loop; server tools where documented; computer actions caller-executed | Anthropic API model catalog and account access | Versioned web search/fetch; computer/browser toolsets conditional | Tool runner or caller composition; API compaction where documented | HTTP/SSE; product-specific webhooks, not generic tool hooks |
| Claude Agent SDK | Claude Code harness in caller environment; OS containment caller-qualified | SDK-supported Anthropic routes and documented alternative endpoints | Harness tools/MCP; browser/computer SDK support must be version qualified | Native SDK subagents, hooks, permission callbacks, automatic context handling | Streaming messages; SDK hooks/permission callbacks; no blanket hosted SDK webhook |
| Anthropic Managed Agents | Provider harness with cloud or documented self-hosted sandbox | Managed Agents-supported Claude models | Hosted toolset differs; raw computer toolset unavailable | Managed session context and multiagent facilities | Persisted session events/SSE; real Managed Agents webhook catalog |
| OpenAI Agents SDK | Caller-owned SDK agent loop, tool execution and persistence | OpenAI plus SDK-supported non-OpenAI clients, conditional capabilities | Responses hosted tools where supported; computer actions require execution environment | Handoffs, agents-as-tools, hooks, sessions and compaction facilities | SDK hooks and stream events; underlying API webhooks are separate |
| Codex local/app server | Local harness; local sandbox/approvals configured | Runtime/account/provider model capabilities, not arbitrary global catalog | Native tools/skills/MCP/web/browser conditional on configuration | Roles/subagents and runtime context handling | JSON-RPC requests/notifications/approvals plus versioned local hooks |
| Codex cloud product | Provider cloud task/environment | Allowed cloud runtime model set | Cloud environment/tool surface, no assumed local parity | Task/follow-up surface; cloud setup distinct | Product task controls; do not inherit Responses/Agents API webhooks |
| OpenAI hosted Agents API | Managed sessions/environments; separate product | Agents API allowed catalog | Hosted tools/custom functions per API | Native session/turn controls, managed artifacts | Session webhooks plus richer stream events; idle is not turn success |
| Cursor local editor/CLI/SDK | Local environment; sandbox and host ownership vary | Cursor available/allowed model set | Native Agent tools plus MCP; headless/editor differences | Custom `.cursor/agents/*.md`, hooks/context; discovery must be proven | SDK/CLI streams/local hooks, transport-specific controls |
| Cursor cloud | Cloud VM/environment; v0/v1 APIs differ | Cloud API model discovery and entitlements | Cloud tool/config surface; no universal desktop computer-use assumption | Docs now describe subagents across editor/CLI/cloud | v0 limited status webhooks; v1 docs say webhooks coming soon |
| Deep Agents library / LangGraph | Caller-selected backend; OS sandbox is separate | Tool-calling LangChain chat models, including Anthropic/OpenAI | Add tools or bind supported native model tools; no universal built-in web browser | Filesystem, skills, middleware, summarization, sync/compiled/async/dynamic delegation by version | LangGraph streams, callbacks, checkpoints/interrupts; hosted deployment is separate |

**Unsupported or unknown combinations to expose explicitly:** Managed Agents plus raw Anthropic computer toolset; Cursor v1 plus v0 completion webhooks; arbitrary Gateway model plus Codex cloud; custom Deep Agents middleware in a closed hosted harness; local hook-file projection into a hosted API that never executes those files; arbitrary PDF/video bytes treated as native model context; compiled graph delegation assumed available in local 0.7.5 binding; required pre-tool veto implemented only by asynchronous webhook; hard pause inferred from budget exhaustion. An account catalog can add further restrictions even where documentation describes support.

## 5. Capability discovery as an agent learning contract

**Observed local.** The catalog already separates search candidates from admitted assets. Search filters scope/admission/lane/effect class and uses ranked lexical/vector projections with lexical fallback. Pins contain ID, version and digest. Bundle materialization verifies individual file bytes; host projection reports unsupported/degraded fields. See [search](../../../src/mission_control/application/capabilities/capability_search.py), [catalog](../../../src/mission_control/application/capabilities/catalog.py), [bundle custody](../../../src/mission_control/application/capabilities/bundle_custody.py), [projection](../../../src/mission_control/application/agentic_components/projections.py).

**Proposal: discovery loop.** A coordinator first obtains a small system capability index and relevant policy summary, searches by goal and required features, inspects candidate metadata, fetches only needed skill/contracts, resolves exact pins, previews native configuration, validates the composed run, and then launches an authorized immutable binding. Agents should be taught this loop through a short router skill, not a giant provider manual in every prompt.

Search results should include a plain-language purpose, runtime/placement support, native versus emulated behavior, effect class, prerequisites, freshness, account-access status and the next inspection/fetch operation. A search hit is not permission to install or execute. New externally discovered tools enter quarantine until source, package integrity, license, security, authentication and capability semantics are reviewed.

The fetch operation should return compact schema summaries and bounded documentation sections plus digest references. Large tool catalogs should use progressive tool loading where the selected runtime supports it. The fetch receipt should record the skill/version used, so a future audit can tell which guidance influenced authoring. A provider feature whose exact shape is unknown should return `unqualified`, an explanation and an alternative, rather than disappear from search.

Agent efficiency depends on avoiding repeated discovery, not on guessing: cache by digest; reuse per-scope search projections; batch independent metadata reads; return typed incompatibilities with JSON pointers; expose cost/context estimates; reserve concurrency before subagent launch; carry useful summaries and evidence refs across stages. Learning means retrieving trustworthy, current capability knowledge, not silently rewriting a model's weights or persisting arbitrary user data as memory.

## 6. Model discovery, route mapping and Gateway compatibility

**Proposal.** Model selection should be a first-class planning operation. Candidate matching considers tool calling, multimodal inputs/outputs, structured output, reasoning controls, maximum input/output, tokenizer/counting support, latency class, retention constraints, regional restrictions, pricing and account entitlement. Native runtimes must constrain choices to the models their own API/harness permits; a cross-provider catalog cannot override that boundary.

Use distinct identifiers for the logical model policy, upstream vendor model, Gateway `provider/model` slug, runtime-native alias, protocol/client and observed actual serving route. Names should be copied from live discovery rather than derived by replacing dots/hyphens. Gateway virtual models and fallback aliases are mutable unless resolved/pinned separately; record their policy revision and actual model/provider selected for each generation. A model existing in `/v1/models` is necessary but insufficient proof of account access or native tool support.

The provider annex documents exact Gateway paths. The compatibility conclusion is conditional: Deep Agents accepts an appropriate LangChain chat client, which can target documented Gateway OpenAI-compatible or Anthropic-compatible endpoints. This is model transport compatibility, not hosting Deep Agents inside Gateway. Anthropic credits can be consumed through intentional Anthropic BYOK; Gateway-funded routing uses Gateway billing. Provider fallback can change payer, residency, caching, retention and model behavior, so permitted fallback needs a separately validated list and spend accounting.

**Proposed model record (illustrative; not an existing contract):**

```yaml
schema: research.model_route.v1
logical_profile: research-analyst
runtime: deep_agents
model_vendor: anthropic
upstream_model_id: <exact ID from vendor discovery>
client: langchain_anthropic.ChatAnthropic
protocol: anthropic_messages
transport: vercel_gateway
base_url: https://ai-gateway.vercel.sh
gateway_model_id: <exact provider/model from live discovery>
auth_ref: secret://gateway-request-auth
billing_route: anthropic_byok
byok_account_ref: account://approved-anthropic-account
fallback_policy_ref: policy://no-payer-change
required_features: [tool_calling, pdf_input]
metadata_snapshot_ref: catalog://models/<immutable digest>
qualification_ref: evidence://client-protocol-model-tools/<digest>
```

This fragment deliberately does not claim every placeholder combination is qualified. Exact request authentication, SDK version and upstream BYOK configuration must match the documented client path. Keep secrets outside prompts/config artifacts. A future validator should reject, for example, Gateway-only routing fields mistakenly placed into direct Anthropic settings, or Responses native tools passed through an unsupported Chat Completions route.

## 7. Catalog evolution, adapter manifests and architecture options

**Proposal A: stable core plus typed extensions.** Keep common identity, scope, immutable inputs/outputs, budgets, control semantics and evidence in the core. Give each runtime/product/protocol version its own extension schema and validator. This preserves native features without making opaque dictionaries the public configuration surface. Tradeoff: more schemas and adapter maintenance, but incompatibilities become reviewable.

**Proposal B: common minimal profile plus explicit native profile.** Offer a portable profile for common work and an advanced native profile with exact product configuration. Tradeoff: simpler introductory learning, but portable profiles can hide useful capability differences unless they expose restrictions and escape routes. Never advertise the portable profile as maximum feature parity.

**Proposal C: provider capability broker with generated skills.** Ingest official docs/model metadata/SDK schemas into versioned evidence; publish reviewed capability records and generated concise skills. Tradeoff: stronger adaptation and discovery, but crawler output must remain quarantined until reviewed, and generated instructions cannot become security authority.

These options can coexist: A for execution contracts, B for authoring ergonomics, C for maintenance. They do not require replacing Temporal with provider SDK orchestration. Provider-native subagents can remain bounded internal cognition; cross-runtime agents with independent goals, effects, budgets or durable review should use Mission Control subordinate/child mission contracts.

**Illustrative adapter manifest:**

```yaml
schema: research.adapter_manifest.v1
adapter_id: deep-agents-python
adapter_revision: <immutable source digest>
runtime_package: {name: deepagents, version: <qualified version>}
placement_profiles: [worker_sandbox, agent_server]
model_protocols: [openai_chat_completions, openai_responses, anthropic_messages]
features:
  compiled_subagent:
    status: unqualified
    constraints: [matching_state_contract, bounded_delegation]
  context_compaction:
    status: native
    parameters_schema_ref: schema://summarization/<version>
    evidence_ref: evidence://summarization/<digest>
controls:
  pause: {mechanism: emulated, semantics_ref: contract://sealed-pause}
native_extensions_schema_ref: schema://deep-agents/<version>
documentation_observed_at: 2026-10-14T00:00:00Z
review_due_policy_ref: policy://provider-evidence-freshness
```

Feature status should distinguish documentation availability, installed version support, adapter implementation, account enablement and live qualification. Current `supported/unsupported/unqualified` is useful but insufficient by itself to capture all five evidence dimensions. Record `native/emulated` separately from support status.

**Proposal: maintenance lifecycle.** Refresh public docs, package release metadata, tool schemas and model lists on a bounded schedule and relevant release signals; compute a diff; classify added/changed/removed behavior; review and qualify affected adapters; publish a new catalog/skill version; notify authors of migration candidates. Existing bindings retain exact versions. New executions are blocked when critical qualification expires or a provider deprecation makes their route unavailable. Security revocation applies immediately even to pinned assets.

Pin evidence source URL, retrieved time, content digest, SDK tag/commit, observed API version/beta header, test kind and account/placement conditions. Keep old evidence for reproduction but mark it historical. Never auto-upgrade a running mission or silently substitute a model. Provider docs can contradict stale overview pages; prefer exact endpoint/reference/source evidence and document the contradiction.

## 8. Defaults, overrides, policy and validation

**Proposal.** Resolve configuration as an explained composition, not arbitrary last-write-wins JSON. Effective values need origin receipts: provider default, system profile, workflow default, coordinator selection, user override, repository instruction, or policy restriction. Model/native options remain in their typed extension. Limits narrow by intersection/minimum; effect authority never grows through inheritance.

| Concern | System default proposal | Coordinator / user may customize | Policy / runtime boundary |
| --- | --- | --- | --- |
| Runtime/model | Qualified profile suited to goal; explain choice | Select allowed runtime/model, explicit fallback list | Installed/account-supported product/model only |
| Context | Runtime-native compaction; reserve output/tool headroom | Threshold, summary prompt/model if supported | Cannot discard authoritative goals, obligations or evidence ledger |
| Tools/skills | Minimal admitted role set | Add exact admitted pins, native tool variants | Tool grant, host/protocol support and effect ceilings required |
| Subagents | Bounded delegation, isolated task context | Role/model/tools, sync/async mode within capability | Depth/concurrency/cost/data/network ceilings cannot be widened |
| Hooks | Required kernel hooks and process audit | Additional role-specific observer or enforceable hook | Mandatory enforcement cannot be removed or replaced by observation |
| Artifacts | Private immutable custody, refs in context | Choose derived views/materialization/output format | Scope, retention, MIME/size/network restrictions apply |
| Review | Review actual outputs; keep waiting by default | Reviewers, feedback/remediation, bounded rounds | No implied approval; reviewer grants and immutable packet check |
| Publication | Separate explicitly granted effect | Request publish/deploy step or target | Review acceptance alone grants no publish/deploy permission |
| Billing/retries | Finite budget, explicit payer, bounded retries | Lower ceilings; authorized allocation/route choices | No unlimited retries, silent payer change or ambiguous launch replay |
| Workspace | Isolated owned environment; read-only durable inputs | Allowed tool placement and writable output paths | Host sandbox/network policy must enforce grants |

Preflight should return a composed explanation: chosen product/runtime/placement, exact model route and payer, required/optional capabilities, native projection preview, loaded-cognition proof status, overridden defaults, policy intersections, predicted input/context/tool costs, unsupported combinations and actionable blockers. Distinguish syntax validation, catalog resolution, capability qualification, account readiness and effect authorization. Do not describe schema validation as successful execution.

## 9. Hooks, callbacks, webhooks, streams and durable coordination

These mechanisms have different authority and timing:

| Mechanism | Useful purpose | Limit |
| --- | --- | --- |
| Local/SDK pre-tool hook | Check path/network/effect policy before execution | Only enforcement if harness honors block synchronously |
| Permission callback | Return approval/denial for a pending native action | Requires durable task binding; timeout cannot imply approval |
| Post-tool / compaction hook | Capture provenance, usage, summary lineage | Observation cannot undo an executed effect |
| SDK/LangGraph/native stream | Progress, tool calls, turn outcomes, usage | Reconnect/replay retention varies; not automatically durable |
| Provider webhook | Wake control plane on documented product events | May duplicate/reorder/drop; not arbitrary per-token or pre-tool control |
| Polling | Reconcile current state, fill gaps, recover missed notifications | Costs latency/API quota; bounded schedule required |
| Mission Control coordinator inbox | Deliver durable mission-level facts/questions | Distinct from provider events and model context |

**Observed local.** Hooks already carry enforce/observe evidence and unsupported fail-closed behavior is blocked. Kernel hooks include stop fence, operation intent, frames and usage. Signal ingress verifies signatures and reduces provider webhooks to resource wakes; status is re-read rather than accepted from the webhook. This is an important existing foundation, not a wholly missing feature ([hook contract](../../../src/mission_control/contracts/hooks.py), [capability hooks](../../../src/mission_control/domain/capabilities/hooks.py), [wake reduction](../../../src/mission_control/application/signals/wake.py), [verification](../../../src/mission_control/application/signals/verification.py), [ingress](../../../src/mission_control/interfaces/http/ingress.py)).

**Proposal: meaningful hook inventory.** Coordinator hooks: before draft submission, after validation, before authorized launch, after artifact custody, review required, reviewer feedback, acceptance, publication intent and reconciliation needed. Process hooks: before tool/shell/network/egress, after execution, before/after compaction, delegation admission/settlement, budget threshold, sandbox cleanup and stream gap. Bind each to an explicit action/decision contract; do not invent provider event names for these Mission Control semantics.

**Proposal: Vercel receiver architecture.** Terminate provider webhooks in a short Vercel Function, verify the raw body and product-specific signature using the official SDK or qualified verifier, enforce timestamp/replay limits where supported, map endpoint/account to trusted scope, persist an ingress receipt/outbox or durably enqueue, and only then return success. Avoid keeping an agent run or a Temporal worker alive in the webhook request. Current Functions have a 4.5 MB body limit; media should upload directly to object storage. [Vercel Functions limits](https://vercel.com/docs/functions/limitations).

Use a durable queue (Vercel Queues is currently beta and documents at-least-once delivery, or an existing qualified queue/outbox). Key ingress by product/account/delivery identity, preserve provider event ID separately, reject equal delivery IDs with inconsistent bodies, and make consumers idempotent. Consumers re-read the provider session, persist attributable native observations, and deliver a scoped Temporal signal via an outbox. Redelivery after a crash between persistence and signaling must be safe. [Vercel Queues](https://vercel.com/docs/queues).

Temporal Signals are asynchronous: server acceptance does not mean the workflow handler applied the effect. Updates can return a workflow result but require a responsive worker. Distinguish ingress accepted, resource reconciled, signal delivered and application effect applied. For closed/fenced executions retain a stale-event record and reconcile; do not use Signal-With-Start to create a fresh mission from an old provider event. [Temporal message passing](https://docs.temporal.io/develop/python/workflows/message-passing).

Ordering should use native sequence/cursor when available, not webhook arrival time. When absent, fetch authoritative resource state and append facts under the current generation fence. Retry transient errors with backoff/jitter and dead-letter or reconciliation queue; repeated authorization errors require operator attention. Avoid routing sensitive provider payloads through unnecessary external logging. Store minimal event metadata and restricted raw evidence only when needed. Use a periodic reconciliation sweep even when webhooks exist.

## 10. Media and artifact inputs: three distinct operations

**Intent.** Any artifact type can be represented. Model consumption is a separate capability. Preserve original bytes even when only a derived text/OCR/thumbnail/transcript representation is suitable for the selected model.

| Operation | Meaning | Example / constraints |
| --- | --- | --- |
| Reference | Durable address/identity in object custody or provider file registry | A 2 GB video can exist as an artifact ref without fitting model context |
| Model context | Inline content block, provider file ID or fetched URL interpreted by a model | PDF text/page images incur tokens; supported MIME/model/protocol required |
| Sandbox materialization | Verified bytes placed in admitted workspace paths | A spreadsheet can be manipulated by Python without native spreadsheet model input |

**Verified external limits, 2026-10-14.** OpenAI file inputs permit multiple files, each under 50 MB and at most 50 MB combined per request; PDF parsing includes text and page images. Anthropic PDF requests have a 32 MB request ceiling, 600 pages where the request has a 1M-token context window, otherwise 100; dense documents may exceed context sooner. Anthropic Files API storage permits 500 MB per file and 1 TB per organization; this does not enlarge model context, and file contents used in Messages are billed as input tokens. These are product-specific observations, not a universal upload rule. [OpenAI file inputs](https://developers.openai.com/api/docs/guides/file-inputs), [Anthropic PDF support](https://platform.claude.com/docs/en/build-with-claude/pdf-support), [Anthropic Files API](https://platform.claude.com/docs/en/build-with-claude/files).

**Proposal: admission pipeline.** Mint scoped upload intent; upload bytes directly to a private object store; verify digest/size and server-detected MIME; quarantine and scan; inspect archive structure; register immutable source version/provenance/permissions/retention; derive safe representations through bounded deterministic tools; validate suitability against the selected model route; materialize only admitted paths; capture provider-file bindings with account scope and expiration. An upload completion callback is evidence to verify, not proof supplied by the user alone.

Token estimation must include extraction, image/page representation, prompt, tools, expected output, compaction overhead and concurrent child usage. Byte limits are checked before upload/request, token limits before generation. Provider URLs must be fetched only under approved egress and URL policies. Signed URLs are short-lived credentials: keep them out of ordinary prompts/logs, mint at use, bind object/scope and refresh after pause. A provider file ID is account/workspace scoped and cannot be accepted as a globally trustworthy artifact reference.

Safe materialization refuses absolute paths, traversal, symlinks/hardlinks escaping the root, duplicate/conflicting normalized paths, archive bombs, unbounded decompression, executable auto-run, and unexpected content-type changes. Extraction needs file/count/ratio/CPU/time quotas in a sandbox. Fetchers defend against SSRF, redirects into private networks and DNS rebinding. Parsers/renderers need isolated resource limits; preview HTML/scripts and PDFs are untrusted active content.

Retention covers original bytes, derived representations, previews, provider uploads, sandbox snapshots, traces and model-side retained state. Deletion/revocation must prevent new fetches; immutable provenance can retain non-sensitive tombstones subject to policy. Pause/resume must check expiration and grants again. Do not promise removal of copies outside the system's control.

**Illustrative input contract, not implemented:**

```yaml
schema: research.input_manifest.v1
inputs:
  - artifact_ref: artifact://<scoped immutable version>
    sha256: <64 hex digits>
    media_type: application/pdf
    size_bytes: <verified bytes>
    provenance_ref: evidence://acquisition/<digest>
    grants_ref: policy://input-read
    retention_ref: policy://mission-retention
    context_view: {kind: extracted_sections, ref: artifact://<derived version>}
    sandbox_delivery: {path: /inputs/source.pdf, read_only: true}
    provider_file_binding_ref: null
    transformations: [<versioned parser/tool receipt refs>]
```

## 11. Domain-neutral outputs, evidence and human checkpoints

**Proposal.** Separate four contracts: ArtifactVersion (identity/digest/bytes/type/custody/lineage), EvidenceAssessment (claim/subject/checker/method/result/scope), GoalContract (intended outcomes, required outputs, acceptance and effect bounds), and DomainProjection (application-owned mapping/admission). Do not make a PDF, patch, dataset or protocol document authoritative merely because it is an artifact.

Artifact types can include PDF/DOCX/HTML/Markdown, images/audio/video, CSV/Parquet, code patches, notebooks, tool logs, structured datasets, archives, model checkpoints and arbitrary binary formats. Previews are derived immutable artifacts tied to the exact original digest and renderer version. Code and knowledge work can share custody and review machinery without sharing all validators.

Content evidence should name cited source versions/URLs and retrieval dates, locations supporting claims, extraction/OCR methods, transformation lineage, uncertainty and independent checks. Assess factual coverage, citation fidelity, licensing, internal consistency, readability and format validity separately. Code evidence should bind base commit, exact patch/tree digest, environment/tool versions, tests executed and results, static/security review and known limitations. A passing test suite does not prove a research statement; a sourced statement does not prove a deployed feature.

Future AI Engineer projections may translate accepted neutral outputs into course/challenge drafts and associated evidence; biotech projections may translate protocol drafts and experimental rationale. The owning domain must define final schemas, units, ontology/version references, admission and safety review. This report deliberately specifies no final course/challenge/protocol schema. A model proposal or content approval cannot authorize a wet-lab action or production domain write.

**Human checkpoint proposal.** Seal candidate outputs before review. A review packet names exact artifact versions, original bytes, actual previews, evidence assessments, diff from previous version, unresolved caveats and the decision's purpose. Store packet digest, reviewer identity/grant, task/version, allowed decisions, feedback, timestamps and remediation target. Approving a proposal to begin review is different from reviewing the actual result; accepting the result is different from publishing it.

Support approve, reject and request changes; continue/refine should map to an authored remediation route or revision request with bounded rounds. Feedback is durable input, not a direct mutation of immutable output. New candidates receive new versions with lineage. Feedback changing goal/acceptance/effect scope requires a new admitted revision; wording/style corrections can remain within the existing authorized loop. Late approvals must fail when task/packet/version changed.

Durable pause means no new scheduling releases and an explicit disposition for in-flight tools, children, external effects and usage; hard pause is only available where qualified. Resume revalidates grants/bindings/expiry and restores a sealed checkpoint or native state under a fence. Human silence should normally keep waiting, escalate or stop according to explicit policy; elapsed time alone is not consent. Approval cannot turn missing enforcement in a closed harness into verified safety.

**Observed local.** HumanGateSpec and resolution validation already support reviewer attribution, packet digest checks, stale task rejection, keep-waiting policy and request-changes only where remediation/rounds permit it. Goal review requests repair without resetting budgets and counters. Artifact promotion verifies custody bytes and validation authority before exposure ([human gate](../../../src/mission_control/domain/programs/human_gate.py), [goal review](../../../src/mission_control/domain/programs/human_review.py), [task service](../../../src/mission_control/application/human_tasks/service.py), [promotion](../../../src/mission_control/application/artifacts/artifact_promotion.py)). End-to-end actual-preview behavior still needs separate qualification.

## 12. Example mixed-provider mission with revision loop

**Illustrative proposal; no mission launched.** Goal: produce a source-backed research brief and PDF, ingest accepted evidence into a knowledge workspace, and implement a small retrieval/UI feature using that evidence. Each agent below has one runtime; the workflow combines them through durable artifacts and explicit dependency contracts.

1. **Discovery/authoring coordinator:** obtains runtime/model/capability/policy summaries; selects allowed profiles and budgets; validates and presents the mission. This is guidance work, not blanket permission to run or publish.
2. **Research agent:** Deep Agents with an admitted Anthropic model route (direct or qualified Gateway/BYOK), selected source acquisition tools and a summarization profile. Independent source tasks can use bounded sync subagents; external ingestion side effects remain gated. Output: source snapshots, evidence index and draft claims with locations.
3. **Ingestion operation:** deterministic/domain-owned Knowledge Services capability validates source identity, license, provenance and extraction. It admits evidence to a private staged workspace, records transformations and returns immutable refs; unsupported media remains representable without forced inline context.
4. **Content agent:** Claude Agent SDK or Managed Agents, selected after actual format/tool needs are checked, produces Markdown plus PDF through admitted tools. It reads immutable refs/materialized inputs, not the research runtime's private checkpoint. Output includes original source-backed draft and actual rendered PDF/preview.
5. **Code agent:** Codex local or Cursor cloud under separate model/account entitlement, isolated workspace and base commit. It implements the retrieval/UI feature, runs bounded authorized tests and captures patch/log artifacts. Cloud auto-push/PR behavior must match grants; publication is not inferred from workspace write access.
6. **Verification:** independent deterministic and cognitive checks assess claims/citations, render validity, ingestion reconciliation, patch scope/tests and evidence attribution. Candidate completion remains separate from mission acceptance.
7. **Human review:** packet contains exact PDF, thumbnails/page previews, claim evidence, staged knowledge changes, exact patch/diff and test receipts. Reviewer requests clearer uncertainty language and a changed table/UI label. Mission pauses durably; feedback is recorded against that packet digest.
8. **Refinement:** content/code remediation nodes produce new immutable versions. Research is revisited only if claims change. Evidence/checks are rerun only where changes invalidate them. Budgets/rounds continue rather than reset; a new scope requires a revision.
9. **Acceptance:** reviewer approves the new exact packet and the goal evaluator records acceptance. Optional publish/domain-promotion/deploy nodes require separate explicit grants and their own immutable subject refs. If those grants are absent the mission can finish with reviewed private deliverables.

Compaction is internal to each runtime. Cross-stage transfer uses a neutral context/evidence packet containing goal/revision, constraints, artifact refs, settled decisions, open questions and obligations; it does not copy hidden reasoning, secrets or active child ownership. A hosted session reattachment is different from transferring work to a new provider.

```yaml
# Conceptual composition, not current mission/v2 syntax
agents:
  source_research:
    runtime: deep_agents
    model_route_ref: model://qualified-anthropic-route
    capability_pins: [<research skill pin>, <source-fetch tool pin>]
  content:
    runtime: claude_agent_sdk
    native_profile_ref: profile://qualified-document-production
  feature:
    runtime: codex_local
    native_profile_ref: profile://qualified-code-role
workflow:
  dependencies: [research_to_ingestion, evidence_to_content, evidence_to_feature]
  review: {packet: immutable_outputs_and_checks, remediation: refine_content_and_code}
  acceptance: {requires: [verified_evidence, valid_artifacts, human_acceptance]}
  publication: {requires_separate_grant: true}
```

## 13. Security, cost and reliability consequences

**Proposal: security.** Enforce scope and permissions at tool/service/sandbox boundaries, not only in prompts. Skills, web content, uploads, tool results and reviewer feedback are untrusted instructions unless explicitly authorized by the control plane. Separate browsing from privileged writes, apply network egress allowlists, use least-privilege short-lived credentials and keep domain/account grants out of model-controlled configuration. Computer-use automation needs credential/UI exposure controls and per-effect authorization. Native hosted tools with no pre-effect veto cannot be assumed governed merely because a reporting tool exists.

OS sandbox policy is independent from virtual filesystem middleware. Read-only flags and QuickJS isolation do not automatically establish process/network containment. Host tools remain privileged bridges and need their own validation. Restrict transitive MCP tools and child agents; delegation cannot amplify access. Preview rendering and archive extraction require isolation too. Preserve tenant separation across traces, checkpoints, object stores, provider file IDs and queue messages.

**Proposal: cost.** Budget model tokens, cached tokens, native search/tool calls, sandbox CPU/storage/idle duration, provider hosted-session costs, Gateway charges/BYOK fallback, queue/function traffic, extraction/rendering, object egress and human-loop rework. Record estimated/reserved/observed/settled/unknown separately. Fan-out needs reservation before launch. Compaction saves future context but costs a generation and can lose useful detail; choose threshold and summary model based on evidence rather than assuming it is free. Token-based and list-cost ceilings are not a proof of immediate stop of every tool.

Do not quote invented provider price estimates. Prices/access should be resolved from fresh metadata at planning/admission and preserved as an estimate snapshot. Failed/cancelled requests and ambiguous launches may still be charged. Blind SDK retries plus Temporal retries can multiply costs; choose one retry owner for each effect and suppress replay until ambiguous provider state is reconciled.

**Proposal: reliability.** Use deterministic dispatch identity and persisted intent before external create; reconcile uncertain results by native IDs/metadata. Prefer native reattachment when qualified. Persist stream cursor and gaps; treat webhooks as wakes; poll to reconcile. Preserve usage/children/effects across pause, fork and remediation. A provider session's deletion/archival may not stop compute; cancellation requires an observed receipt. Exact package pins are necessary but insufficient where provider models/docs/endpoints change server-side. Expiring credentials, signed URLs and capabilities must be revalidated on resume.

## 14. Current-code gap map

All rows are source observations during the revision/time interval in section 1; tracked tree was clean at initial inspection. Because other agents were working concurrently, this is not a frozen-revision audit. These are source-level findings, not test results. Links are relative to this standalone report.

| Gap | Observed current source and positive foundation | Difference from requested evolution / investigation |
| --- | --- | --- |
| G01 Model vendor separation | [DeepAgentModelComponent](../../../src/mission_control/domain/execution/contracts.py) has `provider: Literal["openai"]`; [OpenAIExactModelFactory](../../../src/mission_control/adapters/deep_agents/materializer.py) creates ChatOpenAI | Deep Agents upstream supports more vendors. Contract cannot currently admit an Anthropic model component; add a later typed route design/qualification rather than merely a new UI choice |
| G02 Gateway route | Model factory allowlist includes Responses mode/reasoning/usage, rejects unknown settings; no Gateway/base URL in that factory | Explicit protocol/auth/BYOK/route metadata and qualified factory needed. Extensible exact registry is a useful seam; generic settings dict should not be broadened indiscriminately |
| G03 Compaction | [ObservedSummarizationMiddleware](../../../src/mission_control/adapters/deep_agents/compaction.py) accepts trigger/keep, adopts upstream defaults; [materializer](../../../src/mission_control/adapters/deep_agents/materializer.py) installs it | Actual materializer call passes no per-run trigger/keep/custom prompt. Wrapper accesses private helper/copies internals; upgrade sensitivity deserves source-compatibility qualification |
| G04 Delegation/version | [execution contracts](../../../src/mission_control/domain/execution/contracts.py) pin cognitive state Deep Agents 0.7.5 and define exact sync/async profiles, slices, ceilings and uncertainty | Current upstream dynamic/fork/QuickJS/compiled options must not be advertised through this pin without adapter support and lifecycle/effect qualification |
| G05 Model catalog | [ModelPin](../../../src/mission_control/domain/execution/bindings.py) pins profile/model/context-window; [Codex protocol](../../../src/mission_control/adapters/codex/protocol.py) names model/list and modelProvider/capabilities/read | Existing pins do not establish central live catalog across product/account/protocol/native tools; naming a method does not prove authoring fetches/reconciles it |
| G06 Catalog evolution | [host_support](../../../src/mission_control/domain/capabilities/host_support.py), [pins](../../../src/mission_control/domain/capabilities/pins.py), [search](../../../src/mission_control/application/capabilities/capability_search.py) | Need dated external evidence/SDK/product route constraints/freshness and invalidation records beyond per-lane status |
| G07 Native extensions | [ProviderExecutionBinding](../../../src/mission_control/domain/execution/bindings.py) uses discriminated ProviderOptions, frozen digest, placement consistency | Good pattern to extend. Required native features and exact loaded/configured capabilities need account/version evidence; do not treat all settings as portable |
| G08 Projection/loading | [projections](../../../src/mission_control/application/agentic_components/projections.py), [layering](../../../src/mission_control/application/agentic_components/layering.py), [layouts](../../../src/mission_control/domain/capabilities/layouts.py) | Native paths/fields are already explicit; provider evolution can invalidate them. Loading/invocation proof, including Cursor custom subagent use, remains distinct from written-file proof |
| G09 Defaults/policy | [manifest_v2](../../../src/mission_control/domain/authoring/manifest_v2.py), [instruction layering](../../knowledge/instruction-layering.md) | Structural inheritance/merge exists. More explicit effective-value origin and system/user/policy explanation would prevent opaque config dump. Docs note stale lane-describe instruction channels |
| G10 Hosted products | [Anthropic client](../../../src/mission_control/adapters/anthropic_managed/client.py), [harness](../../../src/mission_control/adapters/anthropic_managed/harness.py), [OpenAI API client](../../../src/mission_control/adapters/openai_agents/client.py) | Concrete adapters exist, so claims that only local runtimes exist would be wrong. Current self-hosted funding-gated placement is explicitly refused by bindings; current docs capability is not local admission |
| G11 Event ingress | [signature verification](../../../src/mission_control/application/signals/verification.py), [wake](../../../src/mission_control/application/signals/wake.py), [remote wake](../../../src/mission_control/adapters/remote_session/wake.py), [ingress](../../../src/mission_control/interfaces/http/ingress.py) | Existing signature/dedupe/wake design aligns with proposal. Need product-specific current event schemas and deployment/queue/retry/ordering evidence; no reason to create duplicate generic webhook authority |
| G12 Arbitrary media | [DurableInputManifestEntry](../../../src/mission_control/domain/execution/contracts.py), [workspace materialization](../../../src/mission_control/application/artifacts/workspace_materialization.py), [artifact promotion](../../../src/mission_control/application/artifacts/artifact_promotion.py) | Durable refs/digests/read-only inputs and MIME/size candidates exist. Requested route-specific inline/file-ID materialization limits, derived views, token checks, scanning/unpacking/retention need traced coverage and qualification |
| G13 Actual review | [human gate](../../../src/mission_control/domain/programs/human_gate.py), [human_review](../../../src/mission_control/domain/programs/human_review.py), [task service](../../../src/mission_control/application/human_tasks/service.py) | Packet/version/digest/feedback remediation exists. Need end-to-end proof that each media/code viewer renders exact immutable output and publication purpose cannot be confused with acceptance |
| G14 Catalog publish/readiness | [capabilities knowledge](../../knowledge/capabilities.md) documents resolver custody and unavailable configured API publish/render paths plus seed gaps | Do not confuse implemented handlers with operational deployment. Confirm current wiring and app-specific admitted inventory later; no live setup performed here |
| G15 Qualification evidence | Tests and docs name mock/fixture/live checks; [bindings](../../../src/mission_control/domain/execution/bindings.py) distinguish identity from readiness | This report ran no tests or paid probes. Future issue/spec work should attach exact scope/version/environment receipts, not promote documentation support into live parity |

The accepted spec pack has historical baseline language (including early Deep Agents-first assumptions), while newer ADRs/code add nine lanes and hosted products. Respect repository precedence when turning findings into specs; report contradictions rather than silently editing canonical documents. This report itself is not a competing authority.

## 15. Unknowns, questions and further qualification

Questions for later specification are not blockers to this research delivery:

1. Which products, placements and account entitlements must be supported, and which are optional alternatives? A capability catalog should not imply every installed plugin/provider is launch-ready.
2. Which native tools require synchronous enforcement, and which effects can run only in a restricted hosted harness? What degradation is acceptable when native tools cannot be intercepted?
3. Which model/Gateway fallback routes may change vendor, payer, region, retention or native tools? Is Anthropic BYOK with no system-credential fallback required for credit use?
4. How should mutable native model aliases/virtual models be resolved, pinned and revalidated without promising immutable server-side weights?
5. Which compaction invariants must survive summaries, and what evidence measures loss? Should summary model differ from executor model? What exact installed middleware version exposes supported replacement semantics?
6. Which delegation cases remain native bounded cognition versus durable Mission Control subordinates/child missions? How are dynamically created roles admitted without granting arbitrary executable config?
7. What actual live replay/retention/ordering/idempotency/cancellation semantics apply for each hosted API, SDK and account? Which create operations have native idempotency and which require reconciliation?
8. Which artifact formats/maximum sizes/retention classes and preview renderers are required? Which provider-side files must expire/delete when the mission ends?
9. What checks/assessors establish content versus code acceptance, and which domain owner defines course/challenge/protocol projections?
10. How should the coordinator display unsupported required features, stale evidence, actual payer and preview integrity without overwhelming the user?

**Further research/qualification proposal.** For each runtime/product, compare official docs with exact package/source lock; validate typed config and golden projections; inspect loaded skills/tools/subagents; run finite authorized conformance cases for tool veto, compaction preservation, native model route, file limits, process loss, duplicate events, stream gaps, provider create ambiguity, pause/resume/cancel, human revision and output custody. Use a separately authorized budget and non-sensitive fixtures. Inspect deployment wiring/account policy before any operational claim. Include a compatibility delta whenever upgrading Deep Agents, Codex/Cursor/Claude SDK or hosted beta APIs.

## 16. Deliverable and verification boundary

This report is the sole intended change. Local source inspection was read-only; canonical documentation and runtime files were preserved. Report structural verification checks file existence, headings, links to inspected local paths and byte size; it does not claim runtime tests passed. Final filesystem/Git observations are recorded after the provider annex is completed. Concurrent unrelated work must be reported separately if visible; a global clean-workspace claim is not appropriate in a shared workspace.

**Verification observations, 2026-10-14 19:04:08 UTC:** the report existed at the requested absolute path; pre-verification-note size was 89,773 bytes and about 10,287 whitespace-delimited words. It contained 17 main sections, six provider annex subsections and 12 balanced code fences. All relative Mission Control file links resolved. Only `apply_patch` calls targeting this report were used for writes by this research task; no delegated researcher edited files. No runtime tests, installs or live provider calls were run.

At final repository inspection, other concurrent work was visible: modified `docs/specs/materialization-observation-2026-10/README.md`, new `docs/specs/materialization-observation-2026-10/runs/RUN-2-HANDOFF.md`, the pre-existing untracked stackdump and the HEAD movement recorded in section 1. These were not changed by this task. Consequently the defensible result is **only the intended report was written by this task**, not “the shared repository has no changes.” No cleanup or reset was performed. No remaining blocker prevents delivery of the report; live compatibility/account qualification remains intentionally unperformed research follow-up.

## 17. Provider research annex: official sources and exact conditions

The following sections expand the matrix with product-specific verified facts, dated 2026-10-14. Their design implications remain proposals. Sources are linked next to the facts; examples with placeholders are illustrative and unimplemented.

### 17.1 Anthropic: raw API, Agent SDK and Managed Agents

**Verified external: raw API.** Messages (`/v1/messages`), batches, token counting and model discovery (`/v1/models`) are separate APIs; a Messages call is not a provisioned agent sandbox. Current Models schema exposes capabilities, lifecycle state (`active/deprecated/retired`), deprecation/retirement dates and input/output limits. Nullable capabilities are not affirmative support, and actual model data must come from discovery rather than placeholder reference examples. [API overview](https://platform.claude.com/docs/en/api/overview), [Models list](https://platform.claude.com/docs/en/api/models/list).

Current raw computer use includes `computer_toolset_20260801`, a 17-member client toolset. The caller executes screenshot/mouse/keyboard operations in its environment. The official page explicitly says this toolset is not currently available in Managed Agents. Older versions have model/platform-specific compatibility. [Computer use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool).

Raw web search is server executed. Versions include `web_search_20250305`, `web_search_20260209` with dynamic filtering and `web_search_20260318` with response inclusion. Later versions' caller defaults matter: direct callers disable dynamic filtering and are needed on incompatible models. Domain restrictions, localization and `max_uses` are configurable; model capability discovery reports web-search support. These API organization controls do not automatically govern Managed Agents. [Web search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool).

Raw on-demand compaction uses beta `compact-2026-09-04` and top-level `compaction`; the caller replaces history with the returned summary. Threshold compaction is a different beta (`compact-2026-01-12`, edit `compact_20260112`): default trigger 150,000 input tokens, minimum 50,000, `pause_after_compaction=false`, and custom `instructions` fully replace the default prompt. These are not Deep Agents or Managed Agents defaults. [On-demand compaction](https://platform.claude.com/docs/en/build-with-claude/compaction), [Threshold compaction](https://platform.claude.com/docs/en/build-with-claude/compaction-threshold).

**Verified external: Agent SDK.** Python/TypeScript Agent SDK embeds Claude Code's binary and agent loop in the application-operated process, with tools, permissions, sessions, MCP, hooks and subagents. The raw API client SDK instead exposes model calls/tool-runner facilities. [SDK overview](https://code.claude.com/docs/en/agent-sdk/overview).

Configuration uses aliases/full model names and documented fallback chains. `allowedTools` preapproves tools; it does **not** remove unlisted tools. Tool availability, permission policy and preapproval therefore need different fields. `settingSources` selects user/project/local settings; `[]` disables those sources. Explicit settings outrank selected filesystem sources, while managed policy remains stronger. [SDK configuration](https://code.claude.com/docs/en/agent-sdk/configuration).

Automatic SDK compaction emits `compact_boundary`; `/compact` permits manual compaction. Repository guidance is reinjected, and deferred MCP schema loading has compatibility behavior. Budget caps observed after model responses can overshoot through the last response and still-running subagents. [Agent loop/context](https://code.claude.com/docs/en/agent-sdk/agent-loop).

SDK hook callbacks run in the application's process. Supported events include pre/post tool, failures, prompts, stop, subagent lifecycle, precompact, permissions and notifications; language parity varies, with additional TypeScript events. Pre-tool decisions can allow/deny/ask/defer; deferral can end a turn for later resumption. Nonblocking callbacks cannot enforce a decision after execution progresses. [SDK hooks](https://code.claude.com/docs/en/agent-sdk/hooks).

Subagents can be programmatic definitions, `.claude/agents/` files or built-in roles; programmatic names override filesystem definitions. Prompt/model/tools/skills/MCP/effort/background and nested-agent behavior are version/language sensitive. Current TypeScript `autoCompactWindow` is 100,000–1,000,000 tokens and requires SDK >=0.3.296; detect current `Agent` and historical `Task` tool names in adapters. These options cannot be projected indiscriminately to Python or older versions. [SDK subagents](https://code.claude.com/docs/en/agent-sdk/subagents).

**Verified external: Managed Agents.** This is the managed harness/session product with beta `managed-agents-2026-04-01`, distinct agent/environment/session/event resources, prompt caching and compaction. Cloud and documented self-hosted sandboxes are possible upstream. Stateful Managed Agents currently lacks ZDR and HIPAA BAA eligibility; this is relevant to biotech data policy and requires future terms checks. [Managed overview](https://platform.claude.com/docs/en/managed-agents/overview).

Managed configuration supports Claude 4.5 and later as documented; model configuration can include speed/effort/inference geography. Agent updates create versions with optional optimistic concurrency (`409` on mismatch). Session overrides include model/system/tools/MCP/skills. Model objects and arrays replace rather than merge, and workspace geography constraints still apply. A generic merge algorithm would be wrong here. [Agent setup](https://platform.claude.com/docs/en/managed-agents/agent-setup).

`agent_toolset_20260401` includes bash, file operations, glob/grep and web fetch/search, enabled when the toolset is included. Default and per-tool configs customize behavior. Long outputs can be offloaded to files; custom tools require application execution/result delivery. [Managed tools](https://platform.claude.com/docs/en/managed-agents/tools).

Toolset permissions default to `always_allow`; MCP defaults to `always_ask`. `auto` can allow, deny or pause but is not an attributed human review checkpoint. Custom tools are outside these permission policies. Concurrent pending confirmations may exist while the session is running, so waiting for idle alone misses approval requests. [Permission policies](https://platform.claude.com/docs/en/managed-agents/permission-policies).

Current `multiagent_20261001` supports subagents, workflows and advisor; subagent/workflow/inline facilities default enabled within the block, advisor disabled. Predefined agents retain their own configurations; inline agents inherit origin model/tools/skills. Thread histories are isolated but sandbox/filesystem/vault credentials are shared. This is context isolation, not permission isolation. [Multiagent orchestration](https://platform.claude.com/docs/en/managed-agents/multiagent-orchestration).

Managed streaming requires attention to subscription race: open the stream before sending input. Persisted history can be listed; stream-only preview deltas are not persisted. `system.message` is model-gated and primary-thread-only. Tool/result/context-compaction/usage/workflow events in the stream do not imply equivalent webhook delivery. [Events/streaming](https://platform.claude.com/docs/en/managed-agents/events-and-streaming), [Reference](https://platform.claude.com/docs/en/managed-agents/reference).

Verified Managed webhook session types include `session.run_started`, `session.status_idled`, `session.budget_reached`, `session.rescheduled`, `session.terminated`, thread created/idled/terminated, outcome evaluation ended, updated and deleted; resource events are also documented. Note stream `session.status_idle` versus webhook `session.status_idled`. Raw-body signature checking uses Standard Webhooks headers and freshness. Delivery is unordered, up to three attempts with jittered 5–120-second backoff, then dropped without a loss signal; redirects disable endpoints and replay/backfill is unavailable. Resource GET/reconciliation is necessary. [Managed webhooks](https://platform.claude.com/docs/en/managed-agents/webhooks).

Files can be mounted separately from model context (up to 500 files/session as documented), including add/remove during a running session. Managed history persists until deletion; sandbox state has a documented 30-day lifetime from creation, and uploads/memory/vaults require separate lifecycle handling. Download produced outputs before deletion. [Managed files](https://platform.claude.com/docs/en/managed-agents/files), [Secure deployment/monitoring](https://platform.claude.com/docs/en/managed-agents/secure-deployment-monitoring).

**Unknown:** raw Messages/batch webhook scope was not verified here; do not invent `agent.completed` for raw API or SDK. Managed compaction threshold/prompt customization was not established. New beta toolsets passing through Gateway remain unqualified. Native raw computer toolset availability is not proof it is an SDK built-in. No account inventory or live calls were performed.

### 17.2 OpenAI: Agents SDK, Codex and hosted Agents API

**Verified external: Agents SDK.** Agent configuration includes instructions/tools/model settings/handoffs/guardrails/structured output. Handoffs transfer control; agents-as-tools retain the parent as answer owner. Handoff routing schemas do not replace conversation input; filters control forwarded history. [Agents](https://openai.github.io/openai-agents-python/agents/), [Handoffs](https://openai.github.io/openai-agents-python/handoffs/).

The SDK is not exclusively OpenAI-model execution. Responses/Chat Completions coexist with configurable providers and best-effort beta Any-LLM/LiteLLM paths. Deferred tools, namespaces, tool search and programmatic tool calling require Responses and are rejected on other backends. Native feature compatibility must be checked at the actual model/client path. [Models](https://openai.github.io/openai-agents-python/models/).

Hosted tools include web/file search, code interpreter, MCP, image generation and tool-search/programmatic-call facilities where supported. Computer/apply-patch tools execute in the application's environment; shell may be local or hosted. Function tools execute application code. Web-search settings include filters/location/context size/external access/image search. Support for ComputerTool alone does not provision a computer. [Tools](https://openai.github.io/openai-agents-python/tools/).

Current `SandboxAgent` separates agent capabilities from workspace `Manifest` and `SandboxRunConfig`. A supplied capabilities list replaces defaults, including filesystem/shell/compaction. Skills can load lazily. Backend isolation matters: Unix-local manifests do not restrict arbitrary shell beyond OS permissions/external containment. Resume needs trusted manifest/credential grants, not authority inferred from serialized state. [Sandbox concepts](https://openai.github.io/openai-agents-python/sandbox/guide/).

RunHooks/AgentHooks expose LLM/agent/tool start/end and handoff callbacks; these are process callbacks. Local context is not automatically model context. `Runner.run_streamed()` emits raw response/run-item/agent-update events; consume the iterator through completion because final tokens can precede persistence/approval/compaction. RunState supports approval interruption and resumption, distinct from artifact acceptance. [Lifecycle](https://openai.github.io/openai-agents-python/ref/lifecycle/), [Context](https://openai.github.io/openai-agents-python/context/), [Streaming](https://openai.github.io/openai-agents-python/streaming/).

`OpenAIResponsesCompactionSession` wraps a session with configurable/manual `responses.compact`; it must not wrap `OpenAIConversationsSession`. Compaction is awaited before stream closure, contributes usage and can use input-based behavior with `store=False`. It is not a universal non-OpenAI summarizer. [Sessions](https://openai.github.io/openai-agents-python/sessions/).

**Verified external: Codex local.** Official legacy Codex documentation URLs now redirect to `learn.chatgpt.com/docs`; preserve resolved URLs and dates. App-server `model/list` reports reasoning efforts/defaults/modalities/hidden/upgrade metadata; `modelProvider/capabilities/read` reports provider/model bounds; `experimentalFeature/list` reports staged features. These are typed requests/notifications, not webhooks. Query available models instead of hard-coding sample names. [App server](https://learn.chatgpt.com/docs/app-server).

Codex configuration exposes model/provider/context window/catalog JSON/automatic-compaction threshold and scope. Unset compaction uses model defaults. Web search has disabled/cached/indexed/live modes, normally cached and live under full access. Search filters do not restrict shell network, connectors or MCP. [Config reference](https://learn.chatgpt.com/docs/config-file/config-reference).

Custom role files use TOML under project/user `.codex/agents/`, with built-in default/worker/explorer. Explicit spawn model/effort can override role defaults. Current concurrency setting is `agents.max_concurrent_threads_per_session`, with legacy `agents.max_threads` alias. Cursor Markdown frontmatter is not interchangeable. [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents).

Current Codex hooks cover tool/permission, compaction, session, subagent, prompt, stop and interrupt events. Command/MCP handlers differ from parsed-but-skipped prompt/agent handlers; malformed/error paths can fail open. Cloud orchestration and enterprise-managed hooks have different restrictions. Hook presence cannot replace sandbox policy. [Hooks](https://learn.chatgpt.com/docs/hooks).

**Verified external: Codex cloud.** Environments are prepared/published filesystem setups; new tasks start from prepared state while existing tasks retain their files. Network secrets use destination-restricted proxy substitution rather than raw credentials in processes; direct environment variables differ. Sharing an environment is not sharing someone else's task. Local files/hooks/settings cannot be assumed loaded. [Cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environments).

**Verified external: actual webhooks.** Responses webhooks include background response completion/cancellation/failure/incomplete events, not all SDK/Codex lifecycle events. The common guide documents raw-body verification, prompt acknowledgment and retries up to 72 hours. [Webhook reference](https://developers.openai.com/api/reference/resources/webhooks), [Webhook guide](https://developers.openai.com/api/docs/guides/webhooks).

A separately documented hosted **Agents API** provides `agent.session.created`, `agent.session.action_required`, `agent.session.in_progress`, `agent.session.idle`, `agent.session.failed`. Action-required requires session retrieval; idle is readiness for input, not last-turn success. Turn completed/failed/cancelled are stream events. Session deletion has no webhook and does not stop compute. Environment-connection waits are not an input queue. These events are not attributable to the open-source Agents SDK or assumed Codex cloud API. [Agents API session webhooks](https://developers.openai.com/api/docs/guides/agents-api/sessions/webhooks).

**Unknown:** authenticated runtime model inventory, exact local/cloud feature rollout and generic Codex cloud lifecycle webhook support. Current docs support richer hooks/product APIs than historical assumptions, but installed adapter qualification remains separate.

### 17.3 Cursor: files, invocation, local/cloud and API versions

**Verified external.** Cursor custom subagents use Markdown plus YAML frontmatter in project/user `.cursor/agents/`. Name/description inform automatic delegation; explicit invocation supports `/name` or natural-language naming. Foreground waits, background returns immediately. Model may inherit or specify one, but plan/admin constraints can cause fallback. The docs state availability in editor, CLI and cloud; that is not proof of identical settings/MCP/permission behavior. Cloud handoff `/in-cloud` uses a separate VM/branch, repository cloud environment and team cloud MCP instead of local MCP; agents can be resumed by ID. [Subagents](https://cursor.com/docs/subagents).

For a Mission Control projection, writing the file proves only materialization. A discovery receipt should establish that the selected runtime read it, recognized its fields and invoked the named role. Record requested and actual model, foreground/background mode, local/cloud target and active tool grants. This is a proposal for qualification, not a claim of an existing Cursor introspection endpoint.

Local hooks receive JSON on stdin and return JSON on stdout; prompt-based hooks also exist. Events cover tools, shell/MCP, files, subagents, compaction, session, prompt and stop. Exit code 2 blocks; other nonzero exits generally fail open, while malformed successful JSON blocks permission hooks. These failure semantics differ from other runtimes and need explicit manifest evidence. [Cursor hooks](https://cursor.com/docs/hooks).

Cloud Agents API v1 is public beta and separates agents from per-prompt runs, with streaming/artifact retrieval and `GET /v1/models` discovery including supported parameter combinations. Model defaults resolve user→team→system. `customSubagents` permits up to 20 definitions. Prompt images allow five at up to 15 MB each via URL/base64 and supported MIME. The v1 page explicitly says webhooks are coming soon while legacy v0 supports them. Do not collapse v0/v1 into a single capability row. [Cloud API endpoints](https://prod.cursor.com/docs/cloud-agent/api/endpoints).

Legacy cloud webhook docs describe `statusChange` for `ERROR`/`FINISHED`, HMAC-SHA256 raw-body signature, delivery ID and event headers. They do not establish per-tool/subagent lifecycle events. [Cloud webhooks](https://cursor.com/docs/cloud-agent/api/webhooks).

**Unknown:** local hook parity in v1 cloud, rollout/account support for each custom field, provider override/fallback semantics in the installed SDK and actual file loading in the chosen lane. Prefer exact endpoint docs over search excerpts still describing older APIs.

### 17.4 Deep Agents / LangGraph: middleware, delegation and QuickJS

**Verified external.** Current docs distinguish library/self-hosted Deep Agents from Managed Deep Agents in LangSmith, where runtime backend/store/checkpointer ownership differs. Self-hosted Docker deployment is also documented. These merit separate placement/product profiles. The maintainer PyPI listing showed 0.7.25 released on 2026-10-14 while search snippets still showed 0.7.24; local contracts pin 0.7.5. This report does not upgrade it. [Comparison](https://docs.langchain.com/oss/python/deepagents/comparison), [Package listing](https://pypi.org/project/deepagents/).

Models can be provider-qualified strings or BaseChatModel objects. Tool-calling support and correct LangChain provider clients/model profiles matter; runtime identity does not imply model vendor. [Models](https://docs.langchain.com/oss/python/deepagents/models).

**Verified compaction distinctions:**

| Surface | Current documented/source behavior | Qualification implication |
| --- | --- | --- |
| Default `create_deep_agent` factory | Trigger at 85% of model `max_input_tokens`, retain 10%; fallback 170,000 tokens / six messages without profile | Gateway/client metadata must be accurate; this is not a fixed global threshold |
| Direct `SummarizationMiddleware` constructor | Source defaults retain 20 messages and `trim_tokens_to_summarize=4000`; factory no-trim behavior differs | Constructor defaults cannot be quoted as harness defaults |
| Custom replacement | trigger/keep/token counter/summary prompt/trim/argument truncation/summarizer configurable; same-name middleware replaces default | Pin source/version and preserve observer hooks when replacing |
| Separate summarizer | Can use model or Runnable/function; prompt unused for Runnable/function | Record executable summarizer identity and cost separately |
| Manual helper | `compact_conversation` helper supplements automatic compaction | User-driven compaction is a separate capability |

Default compaction follows eligible offloading; context overflow can trigger immediate summarization/retry and original conversation text is preserved through filesystem history. [Context engineering](https://docs.langchain.com/oss/python/deepagents/context-engineering). Constructor/replacement details come from mutable upstream source; `history_path_prefix` was removed in 0.7 in favor of `CompositeBackend.artifacts_root`. Recheck against the exact release before implementation. [Summarization source](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/middleware/summarization.py).

Synchronous delegation blocks the supervisor even with parallel calls; general-purpose subagent is default. Dictionary specs can customize model/prompt/tools/middleware/interrupts/permissions/skills/structured output; skills/middleware do not simply inherit. CompiledSubAgent accepts a compiled graph with `messages` state. **Inference:** an entire deep-agent compiled graph can use this boundary, but state/tool/lifecycle compatibility needs a version-specific test. Fork mode is beta, requires >=0.7.13, inherits conversation and rejects a `skills` parameter; compiled fork graphs keep their own system prompt. [Subagents](https://docs.langchain.com/oss/python/deepagents/subagents).

Async subagents use Agent Protocol servers such as LangSmith Deployments or compatible self-hosted servers, with `graph_id`, URL/headers or co-deployed ASGI transport. Tools start/check/update/cancel/list async tasks; start immediately returns identity. Updating interrupts an old run and starts another on the same thread, not merely a live message into unchanged execution. Python `ainvoke` alone does not establish this lifecycle. [Async subagents](https://docs.langchain.com/oss/python/deepagents/async-subagents).

Dynamic delegation means dispatching **configured** subagents from interpreter code via `task({description, subagentType, responseSchema?})`, including loops/batches/structured results, rather than unrestricted new role creation. Dispatch inside `eval` bypasses normal parent per-dispatch `interrupt_on`; gate `eval` or disable the bridge (`CodeInterpreterMiddleware(subagents=False)`) when per-child approval is required. [Dynamic subagents](https://docs.langchain.com/oss/python/deepagents/dynamic-subagents).

QuickJS is an optional in-memory JavaScript interpreter, beta, with Python >=3.11 and `langchain-quickjs>=0.2.0`. It has no host filesystem/network/shell/package manager/clock by default. Explicit bridges expose admitted tools/subagents; programmatic tool calling is off by default. Shell/install/test operations require a separate execution sandbox backend. State normally persists by thread; this is different from OS sandbox durability. [Interpreters](https://docs.langchain.com/oss/python/deepagents/interpreters).

Skills can gate tools until the relevant SKILL.md is read; summarization dropping that read can require rereading to reopen tool access. Tool-name resolvers matter when human-readable catalog names differ from generated names. Typed streaming (introduced in 0.6) supports subagent/message/tool/value projections; it is a runtime stream, not a provider webhook. [Skills](https://docs.langchain.com/oss/python/deepagents/skills), [Streaming](https://docs.langchain.com/oss/python/deepagents/streaming).

**Unknown:** compiled/deep-agent-as-subagent and dynamic/fork modes in the local 0.7.5 binding; upgrade compatibility of private summarization observer internals; live async cancellation/message/effect attribution across server outages; managed LangSmith parity. These are qualification cases, not implied by an upstream feature list.

### 17.5 Vercel AI Gateway: exact transport paths and billing

The Vercel AI Gateway skill was consulted as research guidance. It required fresh official protocol/model documentation; this task implements no integration or paid probe. Model examples below remain placeholders to avoid stale IDs.

| Integration | Exact documented base / client path | Interpretation |
| --- | --- | --- |
| Generic OpenAI-compatible/LangChain client | `https://ai-gateway.vercel.sh/v1`; ChatOpenAI/OpenAI client | Chat Completions or Responses selected explicitly |
| Anthropic-compatible SDK | `https://ai-gateway.vercel.sh`; client appends `/v1/messages` | Do not accidentally append `/v1` twice |
| Responses compaction | `POST https://ai-gateway.vercel.sh/v1/responses/compact` | Documented for OpenAI models |
| Deep Agents CLI/dcode | `https://ai-gateway.vercel.sh/coding-agent/v1`; `langchain_openai:ChatOpenAI`, `use_responses_api=false` | Dedicated CLI path, not automatically generic SDK default |
| Claude Code / Agent SDK | `https://ai-gateway.vercel.sh/claude-code` | Dedicated integration; SDK env reaches subprocess |
| Model catalog | `GET https://ai-gateway.vercel.sh/v1/models` | Public metadata, not account permission |
| Provider endpoints | `GET /v1/models/{creator}/{model}/endpoints` | Route-specific parameters/price/latency metadata |

Official LangChain integration documents JavaScript ChatOpenAI with Gateway key/OIDC, creator/model IDs and `/v1` base URL. **Inference:** passing an appropriately configured LangChain model into a Deep Agents model slot is composable; Python ChatOpenAI/ChatAnthropic exact arguments must be validated against the lock. Gateway is not a Deep Agents execution host. [LangChain integration](https://vercel.com/docs/ai-gateway/ecosystem/framework-integrations/langchain).

The current Deep Agents CLI guide configures provider `vercel-ai-gateway`, `class_path="langchain_openai:ChatOpenAI"`, dedicated coding-agent base URL and `use_responses_api=false`. A model shortlist feeds `/model` and is not a request allowlist; `/model vercel-ai-gateway:<exact gateway ID>` can select another. Setup also supplies token-limit profiles. [Deep Agents CLI](https://vercel.com/docs/ai-gateway/coding-agents/deepagents).

Anthropic compatibility documents Messages/counting/early-access batches, while Responses compatibility documents text/streams/function tools/structured output/reasoning/images and OpenAI compaction. Neither establishes every new Anthropic beta or every OpenAI hosted product feature/webhook. [Messages compatibility](https://vercel.com/docs/ai-gateway/sdks-and-apis/anthropic-messages-api), [Responses compatibility](https://vercel.com/docs/ai-gateway/sdks-and-apis/responses).

Native search is documented but tool formats differ: Anthropic Messages uses `web_search_20250305`; Responses supports OpenAI web search with OpenAI models; Chat Completions offers Gateway server-tool definitions such as `vercel:perplexity_search`; AI SDK has its own provider-tool interfaces. These are typed variants, not one interchangeable tool JSON. Full computer-use, hosted code-interpreter, Files API and raw provider compaction parity were not established. Mark unknown rather than universally unsupported. [Gateway search](https://vercel.com/docs/ai-gateway/models-and-providers/web-search).

Model catalog includes context/pricing/reasoning options; endpoint discovery adds provider parameters/uptime/throughput/latency. Copy exact discovered IDs; availability does not establish entitlement, funds or native-tool compatibility. [Models and providers](https://vercel.com/docs/ai-gateway/models-and-providers).

**Billing correction.** Gateway-funded requests use Gateway credits. BYOK uses provider credentials and explicitly supports consuming provider credits; failed BYOK requests can fall back to Gateway system credentials, changing payer. BYOK route policy and credit eligibility must be checked for the actual Anthropic account/credit terms. Provider credentials do not replace Gateway request authentication. A request-scoped BYOK extension can use `providerOptions.gateway.byok.anthropic`, but it must stay server-side and be validated for the chosen protocol. [BYOK](https://vercel.com/docs/ai-gateway/authentication-and-byok/byok), [Gateway pricing](https://vercel.com/docs/ai-gateway/pricing).

The dedicated Claude Code/Agent SDK guide also documents a Claude subscription flow and SDK environment setup. Thus a blanket statement that native SDKs can only use first-party direct endpoints would be wrong. Native cloud products still retain their own model/entitlement boundaries; do not infer that Codex cloud can use arbitrary Gateway models. The dedicated guide differs from older root-URL Messages guidance; qualify the product-specific path. [Claude Code/Agent SDK integration](https://vercel.com/docs/ai-gateway/coding-agents/claude-code).

**Illustrative Python transport fragment, not tested or implemented:**

```python
# Requires exact model IDs, server-side credentials, pinned clients and qualification.
from langchain_openai import ChatOpenAI
from deepagents import create_deep_agent

model = ChatOpenAI(
    model=resolved_gateway_model_id,
    api_key=resolved_gateway_request_key,
    base_url="https://ai-gateway.vercel.sh/v1",
    use_responses_api=False,
    max_retries=0,
)
agent = create_deep_agent(model=model, tools=admitted_tools, backend=qualified_backend)
```

This demonstrates a generic client boundary, not native Anthropic tool-block compatibility or sandbox deployment. Choose a different typed client/protocol for Anthropic Messages or OpenAI Responses requirements. Do not use this generic example as dcode configuration; its official endpoint differs.

### 17.6 Selectable capabilities and qualification record

**Proposal.** The catalog should expose each configurable capability with a support predicate rather than one runtime-wide flag:

```yaml
# Illustrative fact record, not an implementation schema
capability: native_web_search
subject:
  runtime_product: <exact product>
  runtime_version: <exact SDK/CLI or hosted API version>
  placement: <qualified placement>
  model_route: <exact model/client/protocol>
configuration_schema_ref: schema://native-tool/<digest>
support:
  documented: true
  implemented: <boolean>
  account_enabled: <true|false|unknown>
  qualified: <true|false|unknown>
semantics: {execution_owner: provider, authority: observation_or_effect_as_declared}
limits_ref: catalog://limits/<digest>
source_refs: [<official source evidence>]
observed_at: 2026-10-14T00:00:00Z
```

Applying this pattern to compaction, subagent invocation, async tasks, file inputs, pre-tool blocking, cloud materialization and webhook subscriptions would make unsupported combinations explicit. It also lets newer native capabilities become searchable without making them executable until the exact adapter/account/policy evidence is present.


## 18. Follow-on contract design and evidence (2026-10-16)

The substantial [next-stage contract design](../../specs/proposals-2026-10/MISSION-CONTROL-NEXT-STAGE-CONTRACT-DESIGN-2026-10-16.md) develops the post-sprint capability-release, selective-maintenance, durable external-workload and HITL/deliverable contracts. Its companion [evidence and validation register](../../specs/proposals-2026-10/MISSION-CONTROL-NEXT-STAGE-EVIDENCE-2026-10-16.md) records fresh official sources, current canonical repo anchors, actual Jev/Interfaze/verification findings, unresolved decisions and qualification limits.

Read this report's findings as the dated 2026-10-14 snapshot. The follow-on verifies that OpenAI Decisions and Gemini 4 Argon are real current products, documents Gemini completion/Batch webhooks, preserves the still-documented Jev Gateway /v1/evaluate route, and identifies Interfaze model-pin drift as a compatibility question rather than a proven broken alias. It also records the current AI SDK approval API and AI Elements lifecycle notice. These are fresh evidence/contract corrections, not implementation, entitlement or live qualification claims. Existing report bytes above this note are preserved; the active Mission Control sprint and canonical service contracts are unchanged by this research.
