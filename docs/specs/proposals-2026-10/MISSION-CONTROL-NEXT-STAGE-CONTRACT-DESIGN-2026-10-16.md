---
type: Proposal
title: "Mission Control next-stage capability and contract design (proposal, 2026-10-16)"
description: "Proposed contract families for the stage after Run 2: capability evidence and release manifests, selective maintenance policies, human steering, dashboard control plane, batches and capability evolution. Proposal only; nothing certified."
tags: [mission-control, proposal, dashboard, human-in-the-loop, batch, capability-evolution]
status: open
date: 2026-10-18
---

# Mission Control next-stage capability and contract design

Date: **2026-10-16 UTC**. Status: **proposal for work after the active Mission Control sprint**. This document defines recommended contracts and acceptance boundaries; it neither amends accepted specifications nor certifies implementation or deployment. Read it with the [evidence register](MISSION-CONTROL-NEXT-STAGE-EVIDENCE-2026-10-16.md) and the [starting research](../../research/mission-control/capability-evolution-2026-10-14.md).

## 1. Decision and scope

Evolve Mission Control as the durable coordination and acceptance system. Extend its existing capability catalog, immutable bindings, operation accounting, Human Task service, PostgreSQL inbox/outbox and Temporal workflows. Keep reusable knowledge algorithms and verification in Knowledge Services; keep scientific meaning, entity stores, personal recommendations and product policy in their domains. Provider-hosted agents are bounded execution workloads within this architecture, even when the provider operates their entire internal loop.

The next stage should add four contract families:

1. **Capability evidence and release manifests** distinguish discovery, documentation, implementation, entitlement and exact-placement qualification. Promotion changes what new work may select; it never silently repins an active Attempt.
2. **Selective maintenance policies** turn chosen outputs or domain slices from an initial Mission into recurring refresh or optimization Missions with explicit value, freshness, risk, scope and resource ceilings.
3. **External workload records** admit direct APIs, background responses, batches, decision models, parsers and GPU jobs through one durable submission/reconciliation pattern with product-specific semantics.
4. **Review and deliverable contracts** extend the existing Human Task service with explicit actor kind, human-only constraints, bounded agent delegation, immutable review history, deployment evidence and feedback-to-iteration transitions.

These are coordinated extensions, not one mandatory all-products release. A working supplement evidence slice or AI Engineer dependency-course slice can ship through a skill, MCP and API before all consumer screens exist. Existing accepted web/mobile and MCP Apps targets remain required for their applicable product release; a small vertical does not waive them.

No calendar implementation estimates are prescribed. Operational cadence and expiry are policy fields. No code, migration, sprint issue, provider configuration, deployment, tracker or secret changes are part of this research.

### 1.1 Evidence discipline

**Observed** means inspected source in the canonical checkout. **Accepted direction** means the repository's specification or decision text; it may be unimplemented or uncommitted. **Documented** means current official vendor documentation was opened on 2026-10-16, not tested account access. **Proposed** means the design below. **Unknown/conflicting** means the available evidence does not settle the combination. Illustrative record names beginning with `evolution.` are new proposals, not currently accepted wire schemas, endpoint names or capability enums.

The inspection used Mission Control HEAD `f70f594c391927bb419f44b5cb9010ab9e7bc7ea`, branch `mo/run2-integration`, and Knowledge Services HEAD `28c4422228826c41f92dd837f3c5f0b561471b3b`, branch `main`, with dirty working trees. This is a live-source observation, not an atomic release audit. The [local register](MISSION-CONTROL-NEXT-STAGE-EVIDENCE-2026-10-16.md#local-source-register) records actual paths and critical byte hashes. Retained worktrees were inspected only as Git metadata; none was selected, created or altered.

## 2. Existing foundation and corrections

The accepted [general specification](../../knowledge/mission-control.md), [frontier runtime contract](../../knowledge/lanes-and-harness.md), [revision law](../../knowledge/revisions.md) and experience annex (`mission-control-general/.../expansion/EXPERIENCE-AND-STREAMS.md` at commit 66185d2e, since deleted) remain the architectural starting points. The active [Run 2 report](../archive/materialization-observation-2026-10/runs/RUN-2-REPORT.md) remains its own implementation/qualification record. Historical report text must not be copied as current deployment status.

| Observed foundation | Consequence for the next stage | Remaining design/proof boundary |
| --- | --- | --- |
| [ProviderExecutionBinding](../../../src/mission_control/domain/execution/bindings.py) seals lane, provider options, environment, model and auth identities. Capability pins and bundle custody already exist. | Add evidence/release references without changing historical canonical bytes or conflating a model vendor with a runtime. | A complete capability evidence lifecycle, deprecation impact graph and promotion policy are proposed. |
| [HumanGateSpec / HumanResolutionRequest](../../../src/mission_control/domain/programs/human_gate.py), [HumanTaskService](../../../src/mission_control/application/human_tasks/service.py) and [HumanGateWorkflow](../../../src/mission_control/adapters/temporal/workflows/human_gate.py) already bind packet digests, task versions, reviewers, deadlines and bounded remediation. | Reuse one task/resolution authority and durable wait; do not create a separate dashboard approval database. | Explicit human-only identity and constrained agent delegation require new contract/policy work and cross-surface qualification. |
| [Wake reduction](../../../src/mission_control/application/signals/wake.py) drops webhook claims about status, actions, URLs and usage; [signature verification](../../../src/mission_control/application/signals/verification.py) authenticates supported envelopes. | Extend by exact product/event schema, preserving fetch-and-reconcile. | Current provider mapping covers managed Anthropic/OpenAI sessions; Responses, Batch and Gemini cannot inherit those session semantics automatically. |
| [Mission revision writer](../../../src/mission_control/adapters/postgres/control_plane/mission_revisions.py) and [manifest submission](../../../src/mission_control/adapters/postgres/control_plane/manifest_submission.py) persist submitted revisions and scheduling heads. | Preserve that existing behavior. | Full running-mission proposal validation, Transition Impact and safe in-flight activation are additional work. The [revision concept](../../knowledge/revisions.md) understates the manifest writer; source inspection corrects that narrower claim. |
| Shared KS [operation catalog](../../../../knowledge-services/packages/application/src/operations/catalog.ts) distinguishes admitted, gated, declared and executor-only surfaces. | Resolve the actual published operation and profile before dispatch. | A contract name, MCP registration or schema does not certify readiness. Do not alias executor-only operations into the platform API. |
| Jev [contract](../../../../knowledge-services/packages/contracts/src/jev.ts), [provider](../../../../knowledge-services/packages/jev/src/provider.ts) and [service](../../../../knowledge-services/packages/jev/src/service.ts) implement Choice/Score/Noul, captured input, SQLite queue and child processes. | Generalize the decision abstraction while preserving provider-specific results and existing service. | Local idempotency does not prevent repeat inference after a crash. Distributed tenant admission and automatic LLM fallback are not established service behavior. |
| Interfaze [adapter](../../../../knowledge-services/packages/verification/src/providers/interfaze.ts) implements bounded extraction and five task types with captured response/precontext digests and usage. | Treat it as a specialized probabilistic workload behind KS, separate from deterministic parsing. | Current vendor model names differ from the adapter's exact `interfaze-beta` pin. Investigate compatibility; do not substitute the model during a retry. |
| [Deterministic verification](../../../../knowledge-services/packages/verification/src/deterministic/bundle-verification.ts), [semantic verification](../../../../knowledge-services/packages/verification/src/semantic/verify-case.ts) and [evidence admission](../../../../knowledge-services/packages/knowledge-db/src/ingestion/evidence-admission.ts) are distinct. | Reuse their evidence and intended-use semantics. | Model confidence, source fidelity, scientific truth and permission to publish remain different assessments. |

Important verified vendor corrections are affirmative: **OpenAI Decisions API exists** in public beta, **Gemini 4 Argon exists** as `gemini-4-argon`, and **Gemini documents completion webhooks**, including Batch events. These names must not be dismissed as hallucinations or promoted into unsupported cross-product promises. Decisions is constrained inference, Argon is a model, and webhooks are product-specific notifications. [OpenAI Decisions](https://developers.openai.com/api/docs/guides/decisions), [Gemini Interactions](https://ai.google.dev/gemini-api/docs/interactions-overview), [Gemini webhooks](https://ai.google.dev/gemini-api/docs/webhooks).

The canonical platform directories were found directly. Old Biotech/aiengineer roots are historical. The current [service inventory](../../../../../docs/navigation/SERVICE-INVENTORY.md) identifies separate Biotech domain services and an AI Engineer research dashboard. No learner application or Biotech frontend was established. A navigation reference to `mission-control/apps/dashboard` did not resolve; inspected interface code supplies HTTP/MCP/Socket.IO contracts, not evidence of a deployed dashboard.

## 3. Ownership and the capability model

### 3.1 Keep the boundaries explicit

| Owner | Owns | Must consume from another owner |
| --- | --- | --- |
| Mission Control | Mission Definition/Revision, scheduling, grants, budgets/reservations, execution attempts, Human Tasks, artifact registrations, acceptance and lineage | Domain verification/admission receipts; provider resource observations; deployment evidence |
| Shared Knowledge Services | Acquisition/preparation mechanisms, reusable decision/retrieval/evaluation/verification algorithms, sealed audit artifacts, knowledge-operation lifecycle | Application binding, native domain identity/schema/query/writer contracts and intended-use policies |
| Biotech domain KS | Compound/product/company identity, biomarker/diagnostic/scientific applicability, graph-native read/plan/apply, domain content and evidence grading profiles | Shared algorithms through published interfaces, Mission Control coordination |
| AI Engineer domain | Library/project constraints, source/course/lesson/challenge meaning, schema/query authority, executable learning validation | Shared KS operations and mission capabilities |
| Product API/BFF | User identity, entitlements/preferences/progress, personalization, conversation/view composition, user-visible recommendations | Authorized domain reads/evidence; mission launch/control when the chosen mode permits it |

This follows the [BellLabs KS direction](../../../../knowledge-services/docs/specs/belllabs-knowledge-platform/SPECIFICATION.md#ownership-and-composition). Existing `@aiengineer/*` packages and PostgreSQL bindings remain; relocation did not make them backend-neutral. A proposed dynamic resolver is a composition policy over admitted capabilities, not evidence of a third deployed service. Do not introduce another schema authority or put KS operational verification tables into Mission Control's common SQL merely for convenience.

Ordinary product reads remain typed reads. Direct/Fast/Explore/Research modes from the KS specification constrain effort and escalation; a sparse biomarker search result does not automatically authorize a paid research Mission. Domain writes still use native plan/apply and receipt reconciliation. Mission acceptance records why evidence meets the goal; domain admission decides whether it may become knowledge or a recommendation.

### 3.2 Capability descriptors and immutable execution

A capability describes an operation, not necessarily an agent. Its execution class is one of constrained inference, deterministic tool, probabilistic model, caller-owned agent harness, provider-hosted harness, batch/background job or remote service. Each class admits only its actual controls. Preserve existing catalog kinds and supported bindings; finalize any new kind through the owning contract rather than inventing an enum in an implementation ticket.

Proposed descriptor information:

~~~yaml
schema: evolution.capability_evidence.v1
identity: {capability_ref: '<existing catalog identity>', release_ref: '<immutable release>'}
subject:
  provider: '<vendor or internal owner>'
  product: '<Decisions, Responses, Managed Agents, native parser, ...>'
  endpoint_or_operation: '<exact versioned operation>'
  api_version: '<version/beta headers or unknown>'
  sdk: {package: '<name>', version: '<exact>', integrity: '<digest>'}
  model: {requested_id: '<id>', resolved_id: '<id or unknown>', alias_observed_at: '<time>'}
  tool_schema_digests: ['<digest>']
  execution_owner: '<provider|caller|split>'
  placement_profile: '<qualified host profile>'
evidence:
  documentation: {status: documented, source_refs: ['<capture refs>'], observed_at: '<time>'}
  implementation: {status: '<implemented|absent|unknown>', source_digest: '<digest>'}
  entitlement: {status: '<enabled|disabled|unknown>', account_ref: '<opaque ref>'}
  qualification: {status: '<passed|failed|blocked|unrun>', receipt_refs: []}
support_predicate_ref: '<model/product/mode/data-class/placement constraints>'
native_or_emulated: '<native|emulated|mixed|not-applicable>'
limits_and_price_snapshot_ref: '<dated immutable artifact>'
control_semantics_ref: '<cancel/pause/expiry/recovery meanings>'
~~~

Unknown fields remain unknown. A release can be searchable while unqualified and non-executable. Search results should give purpose, constraints, evidence age, next inspection operation and a small explanation of cost/authority. Required features fail closed before billed work; optional degradation must be declared and returned in the result. Do not add every provider manual to agent context: use the existing router skill, bounded search, schema summaries and digest-addressed fetches.

The **release manifest** pins the descriptor, adapter build, SDK/runtime packages, API version, model ID/alias resolution, prompt/question/rubric, tools/MCP/skill bytes, environment image, native schema/query contracts, verification/calibration profile, source captures, price snapshot and retention/data policy. Its admission receipt binds the actual application/account/placement. Secrets remain references. Persist requested and observed identities separately.

Pins make the request and environment auditable; they cannot freeze proprietary model weights or guarantee identical generated output. A provider may change behavior without a new visible ID. Record observed model metadata and qualification date, retain test inputs/results and label this limit on reproducibility. A mutable alias without a stable resolved revision is an explicit limitation, not an exact model snapshot.

## 4. Capability evolution and economic selective maintenance

### 4.1 Change signals become proposals

Discover candidate changes from official changelogs/deprecation notices, API model lifecycle lists, signed package/SDK releases, schema diffs, tool manifests and provider security advisories. Production errors, cost drift and failed regression samples are also signals. Community/news sources can prompt investigation but cannot establish support. Capture URL, access time, bytes/digest, publisher, semantic change, affected pins and uncertainty. Verify claimed breaking changes against exact endpoint/reference or release source.

Use two linked lifecycles:

~~~text
change signal -> deduplicated observation -> impact analysis -> qualification candidate
candidate -> evaluating -> approved/rejected/held -> new admitted release
admitted release -> deprecated -> retired/revoked
~~~

Model/tool retirement and security revocation differ. Retirement blocks launches that cannot run and proposes migration; revocation can immediately narrow authority or stop affected work through the existing durable command path. Neither authorizes an unreviewed replacement. When a provider stops serving a pin, the system reports `pinned_capability_unavailable`, parks/reconciles liabilities and offers a specific alternative proposal.

Impact analysis traverses release-to-Mission bindings, skill instructions, tool schemas, source transformations, verifier calibration and product projections. An improved model does not require redoing every research output. Re-evaluate only affected contracts/cases and dependent claims; preserve unaffected artifacts by exact lineage and compatible digests.

Promotion requires a frozen comparison manifest, incumbent/candidate outputs on the same eligible fixtures, held-out labels where relevant, schema/control/cost/latency/quality deltas, failures and an attributed decision. Use offline fixtures first. Paid shadow/canary trials require their own finite scope and budget. Promotion changes the selectable default for new eligible Runs. Existing Runs remain pinned; an author may propose a successor Revision under the accepted revision law. Rollback changes future selection to an earlier eligible release, after current-policy validation; it cannot undo external effects or silently reactivate a historical Mission Revision.

### 4.2 Maintenance is an explicit promotion of selected scope

An initial research, ingestion, content or product Mission may emit a **MaintenanceCandidate**. It identifies the domain slice and dependent artifacts worth keeping current. The owner/coordinator can approve a bounded MaintenancePolicy; completing the initial Mission alone does not start indefinite research. A domain slice is an explicit versioned selector resolving to a finite set, not an unbounded keyword.

~~~yaml
schema: evolution.maintenance_policy.v1
policy_id: '<scoped identity>'
version: 1
origin: {mission_ref: '<initial mission>', accepted_output_refs: ['<versions>']}
slice:
  domain: '<biotech|ai-engineer>'
  selector_ref: '<versioned predicate with maximum cardinality>'
  resolved_members_ref: '<exact member snapshot>'
  include_dependencies: '<bounded depth and allowlist>'
  expansion: requires_new_admission
objective: '<refresh evidence|optimize cost/quality|repair incompatibility>'
freshness_policy_ref: '<field/claim-specific age and disclosure rules>'
triggers:
  cadence_ref: '<bounded policy>'
  event_allowlist_ref: '<trusted release/source/deprecation events>'
  debounce_and_cooldown_ref: '<coalesce duplicate work>'
resources:
  per_run_ceiling_ref: '<tokens/tools/compute/storage/spend>'
  rolling_window_ceiling_ref: '<window and reset semantics>'
  maximum_open_runs: 1
  maximum_members_per_run: '<finite>'
  scan_quota_ref: '<cheap metadata checks>'
  deep_research_quota_ref: '<separate scarce allocation>'
ranking_policy_ref: '<value/freshness/risk/priority/cost weights>'
approval_policy_ref: '<allowed autonomous changes and human-only gates>'
state: active
supersedes_policy_ref: null
~~~

The policy itself is versioned, reviewable and pausable. States are `proposed -> approved -> active`, with `paused`, `budget_held`, `superseded` and `closed` as explicit dispositions. Pausing suppresses new research releases, records its actor/reason, and declares whether already admitted Runs finish or receive cancellation. Cancellation uncertainty and spend liabilities remain tracked. Resume rechecks grants, freshness, membership, binding availability, quotas and reserved liabilities; it does not refill budgets by changing policy version.

Separate inexpensive change detection from substantive refresh. Prefer metadata/ETag/hash/release diff checks and domain change feeds; missing data or a noisy signal is not a reason for repeated full research. Only a meaningful delta, approaching freshness limit or measured quality/cost opportunity becomes a candidate Run. Deletions, retractions, safety notices and lost access may invalidate dependent conclusions without an expensive synthesis first.

An illustrative selection score is:

~~~text
priority_score = policy_weighted(value_at_risk, freshness_debt,
                                evidence_risk, dependency_impact, owner_priority)
                 - policy_weighted(expected_total_cost, uncertainty_of_benefit)
~~~

Normalize dimensions and version the weights; do not subtract dollars from a probability without a declared utility scale. Before ranking, enforce hard scope, risk, grant, quota and cost constraints. High clinical risk can require human escalation or suppress a recommendation rather than increase autonomous spend. Include opportunity cost and unknown outstanding liabilities. A finite budget may select fewer slices; disclose which are stale or omitted.

Deduplicate by scoped slice identity, policy version, relevant change/source digest and observation window. Coalesce overlapping refreshes into one producer whose immutable results are referenced by dependent consumers; never cross tenant/data-access boundaries merely to save money. One active Run per slice/dependency generation prevents event storms. Event and cadence triggers share this same admission key. An unfinished refresh suppresses duplicates while retaining new signals for the next delta. A failed refresh leaves the previous version visible with `last_verified_at`, `last_attempt_at`, `stale_reason`, `next_eligible_check`, coverage/omissions and budget-hold status; it cannot update `last_verified_at` just because a poll succeeded.

The maintenance scheduler compiles into bounded Temporal-scheduled Missions and existing watcher/event mechanisms. A Firecrawl/provider monitor may supply a change signal; it does not own the Mission scheduling head, recurrence budget or publication policy. Avoid laptop cron loops, perpetual agent prompts and a second queue. Overlapping policies require a chosen producer and per-consumer allocation; a duplicate suppression receipt must explain the reuse.

### 4.3 Two concrete scopes

**Supplements/compounds:** an initial Mission compares evidence and manufacturer claims for an explicitly selected company/product list and compound IDs. Promotion can choose only ingredient composition/label changes for a subset, only high-value compound evidence, or only published claims used by an accepted report. Company marketing, independent studies, formulation version, dose/form and intended population remain separate. A new product cannot enter because it matches a broad company name unless membership expansion is admitted. A price change need not re-run scientific review; a formulation change invalidates applicability and dependent recommendations.

**Agent-framework course:** an initial AI Engineer Mission selects framework versions for a particular project and creates lessons/exercises. Promotion tracks the actual lockfile/package/runtime/tool/API dependencies and lesson claims affected by those dependencies. A security notice or breaking release can queue compatibility review; an unrelated framework release does not regenerate the entire course. Update only affected examples, dependency advice and source explanations. Learner personalization uses a separate user-state snapshot and privacy policy; it must not mutate shared factual evidence.

## 5. Provider capability matrix and workload selection

All vendor rows below are **documentation support observed 2026-10-16**, not new local integration or entitlement proof. Exact source/status/limits are in the [provider register](MISSION-CONTROL-NEXT-STAGE-EVIDENCE-2026-10-16.md#provider-evidence). The matrix deliberately separates API products within a vendor.

| Product | Provider operates | We still operate | Cache / Batch / completion notification | Recommended treatment |
| --- | --- | --- | --- | --- |
| OpenAI Decisions beta | Constrained predicate/choice/score inference; currently `gpt-6-luna` | Input capture, question design, calibration, escalation and effects | Endpoint-specific Batch/background/webhook compatibility unverified | KS decision adapter candidate; no new agent lane |
| OpenAI Responses | Inference and selected hosted tools; background response generation | Mission loop, caller functions/computer environment, callbacks, acceptance/custody | Model-specific prefix cache; Batch; background and Batch webhooks documented | Direct workload profile, separate from hosted Agents API |
| OpenAI Agents API beta / existing `codex_agents` | Managed Codex harness, session/context/recovery; hosted sandbox when selected | Admission, custom services/functions, receiver, external state, acceptance; self-hosted executor if chosen | Session events/webhooks; do not inherit Batch or raw Responses control semantics | Extend current exact lane qualification; preserve name with clear product label |
| OpenAI Agents SDK | Model-side services only; SDK loop runs in our deployment | SDK process, tools/sandbox/persistence and lifecycle integration | Underlying endpoint support; SDK callbacks are not provider webhooks | Caller-owned bounded harness, distinct from `codex_agents` |
| Anthropic Messages | Inference and documented server tools | Caller tool loop/functions, computer environment and durable mission logic | Prefix caching and Message Batches; general batch webhooks unverified | Direct workload profile with polling for Batch |
| Claude Agent SDK | API/model service; Claude Code harness runs where SDK deployed | Process, isolation, tools, hooks/permission bridge and recovery | Native SDK context/cache behavior; no generic hosted SDK completion webhook | Preserve existing lane |
| Anthropic Managed Agents beta / `claude_managed` | Harness/context; Anthropic container in cloud mode | MC policy, custom tools/services, callbacks; worker/isolation in self-hosted mode | Built-in caching; Managed session webhooks; not Message Batch semantics | Existing hosted lane with exact data/control qualification |
| Gemini Interactions + Argon | Model/state/background processing; selected server tools | Client tools, MC orchestration/callbacks/evidence | Interactions implicit cache; interaction webhooks; Batch not established for this API | New direct workload, not an invented Argon runtime |
| Gemini Deep Research preview | Provider research loop and supported tools | Scope/budget/callbacks, evidence extraction and independent verification | Background Interactions; no custom function/structured-output assumption | Optional research executor with source-backed acceptance |
| Gemini generateContent Batch | Hosted group inference | Submission, item mapping, polling/webhooks, custody and settlement | Model-specific explicit cache; Batch notifications documented | Separate compatibility profile; no assumed Argon/Interactions Batch parity |
| xAI Responses `x_search` | X search/tool use and inference | Mission loop, source retention/verification, caller functions | Automatic prefix cache; separate Batch API; webhooks unverified | Time-bounded discovery capability; social posts are leads/attributed statements |
| xAI deferred Chat Completions | Deferred response retained for later retrieval | Polling and crash-safe result custody | One-time retrieval within documented window; not proof of deferred `x_search` support | Restricted optional profile until destructive-read recovery is solved |
| TypeSafe Jev | Typed decision inference | Existing single-host KS queue, captured input, calibration and effects | No assumed vendor batch/webhook contract; local batch is queued jobs | Retain existing route, compare decisions on labeled cases |
| Interfaze | Specialized model tasks/extraction | Bounded adapter, provenance, freshness policy, verification and retries | Specialized-result `vcache`; general Batch/webhooks unverified | KS workload; qualify model/version drift |

### 5.1 Decisions and Jev: same category, separate semantics

OpenAI's current [Decisions guide](https://developers.openai.com/api/docs/guides/decisions) documents predicates, supplied choices and ordered rubric scores. This is comparable to Jev's Noul, Choice and Score as an interface category. It is not proof of equivalent confidence, calibration, label indexing, multimodal support, cost or accuracy. Neither typed output nor a confident distribution guarantees a true statement.

The actual Jev provider sends state/questions to direct `https://api.typesafe.ai/v1/systemone` or Gateway `https://ai-gateway.vercel.sh/v1/evaluate`; it converts Gateway Noul requests to `boolean` and normalizes the probability back. Current [Gateway decision documentation](https://vercel.com/docs/ai-gateway/modalities/decision) still documents `/v1/evaluate`. The additional TypeSafe-compatible route is not grounds to declare the existing route retired.

Propose a KS DecisionRequest carrying captured evidence refs, question/taxonomy version, primitive, label/rubric semantics, no-match/insufficient-evidence handling, model/route pin and calibration profile. DecisionResult preserves raw provider primitive/output, normalized value, distribution, native probability, derived confidence, metadata availability, requested/observed model, usage and provenance. Do not force an absent distribution into an empty measured one or map a fractional score to a class without a specified rule. A Gateway fallback can change the answering model and bill another stage; zero confidence plus an empty distribution can indicate unavailable metadata rather than measured certainty. [TypeSafe confidence](https://docs.typesafe.ai/confidence), [Gateway TypeSafe route](https://vercel.com/docs/ai-gateway/sdks-and-apis/typesafe).

Comparative promotion uses independently labeled domain cases, class/ambiguity imbalance, abstention and adversarial inputs, calibration error/selective risk, false-support rate, coverage, latency and total cost per accepted decision including escalation. A judge-generated label is agreement evidence, not human ground truth. Thresholds are keyed by primitive/question/version/domain/route; a Jev threshold cannot be copied to Decisions. Direct Jev experimental image support is route/version gated; the local service currently admits text/JSON and does not become multimodal from upstream documentation.

The owner's low-cost, low-hallucination expectation is a hypothesis to evaluate, not an adopted provider guarantee. Record current list-price units and measured accepted-decision cost, including cache writes, fallbacks, retries and review. Constrained labels reduce open-ended output space; they do not establish that the selected label or its supporting interpretation is correct.

### 5.2 Additional providers must close a specific gap

Gemini supplies an independently operated frontier/model family and hosted research option; xAI supplies native X discovery. Both need independently qualified workload adapters, not booleans added to existing OpenAI/Anthropic bindings. X citations need acquisition timestamps, post/account identity, deletion visibility and source authority; popularity is not scientific evidence.

A defensible **third missing candidate is Perplexity Search**, limited initially to evaluation of source discovery/coverage. The starting report already identified Gateway Perplexity search, and the actual [Biotech admission rule](../../../integrations/biotech/src/biotech_mission_adapters/application/execution/web_research_admission.py) currently recognizes Firecrawl/Tavily. Perplexity's [Search API](https://docs.perplexity.ai/docs/search/quickstart) provides ranked raw results with filters, distinct from a generated answer. Compare incremental relevant primary-source recall and acquisition cost against incumbents; admit only if it fills a measured gap. Do not add another autonomous runtime, general webhook promise or permanent provider dependency merely for matrix symmetry. Existing allowed-tool checks must change deliberately if a qualified alternative is later admitted.

### 5.3 Hosted execution is not outsourced authority

In fully hosted OpenAI/Anthropic modes, the provider may own both harness and sandbox. In split modes we still own executor compute, network isolation and credentials. In raw Responses/Messages/Interactions modes the provider owns inference and selected tools, while caller functions still need our service. `AsyncClient` concurrency is not a durable hosted job. Background response generation is not a hosted arbitrary application workflow. Deep Research is a provider-managed research workflow with a limited tool/output contract.

Every workload must state who runs the loop, each tool family, sandbox, callback receiver, retry/recovery and artifact transfer. Closed harnesses without a qualified pre-effect veto cannot satisfy a requirement to human-gate arbitrary writes. Restrict tools/egress/credentials to a governed prepare/review/execute gateway, use a qualified native approval mechanism, or refuse the combination. No SDK or UI framework replaces Mission Control's stop fence, grants or acceptance evaluator.

## 6. Durable external workloads, batches and cache economics

### 6.1 One durable pattern, typed product extensions

Direct API calls and ML jobs should enter through existing Agent/Deterministic Executor seams as appropriate, not masquerade as sessions with nonexistent pause/fork support. Add an external-workload port and versioned product extension only after contract review. Retain native status alongside normalized state.

~~~yaml
schema: evolution.external_workload.v1
scope_ref: '<validated installation/application/tenant>'
execution:
  mission_id: '<id>'
  run_id: '<id>'
  revision_id: '<immutable starting revision>'
  activation_id: '<id>'
  attempt_id: '<id>'
  generation: '<fence>'
dispatch_id: '<stable semantic submission identity>'
request_manifest_ref: '<immutable bytes, item map and digest>'
capability_release_ref: '<exact admitted release>'
provider_binding_ref: '<product/account/region/endpoint; no secrets>'
native_idempotency: {support: '<documented|absent|unknown>', key_ref: '<opaque identity>'}
external_handle: {kind: '<response|batch|interaction|ml_job>', id: '<id or pending>'}
recovery: {lookup_strategy_ref: '<qualified strategy>', result_read: '<repeatable|consuming|unknown>'}
deadline_at: '<mission deadline>'
provider_expires_at: '<result/job retention if known>'
retry_policy_ref: '<single retry owner and finite attempts>'
cancel_policy_ref: '<native request plus observation/late-result policy>'
reservation_ref: '<compute, provider and storage ceilings>'
status: prepared
~~~

The immutable request manifest includes per-item IDs/digests, typed input/output schema, allowed native options, source/input versions, model/tool/prompt/question pins, callback subscription reference, output bounds and usage-attribution policy. Item IDs cannot encode secrets. Default batching groups only one application/tenant with compatible product/model/data/retention/priority/deadline. Cross-Mission batching within that scope requires per-item ownership and cancellation/charge allocation; cross-tenant batching is deferred until isolation is proved.

### 6.2 State and transaction boundaries

~~~text
prepared -> submitting -> submitted -> running -> provider_terminal
                  \-> submission_unknown -> reconcile or human_recovery
provider_terminal -> results_captured -> validated -> accepted_or_not_accepted
submitted/running -> cancel_requested -> cancel_observed OR cancellation_uncertain
any retained liability -> usage_pending -> settled OR explicit_unknown_liability
~~~

These are separate axes in storage, not a claim that one enum can express all combinations. For example, compute can be cancelled with partial results captured and usage unsettled. Mission acceptance can be denied while custody and billing reconciliation continue.

1. Admission validates current grants, data class, route/mode support, quotas, input and output bounds; reserves conservative total resources. Persist effect/dispatch intent and outbox before external create.
2. A short Activity submits the exact bytes. If native idempotency is supported, use the stable admitted key. Persist native handle and response observation before declaring submitted. Do not treat an arbitrary request header as vendor idempotency support.
3. Timeout after possible acceptance becomes `submission_unknown`. Retry only a proved idempotent create or qualified lookup/list reconciliation. Metadata matching without uniqueness can be ambiguous; park rather than create another billable job. Gemini Batch documentation explicitly warns that repeated create is not idempotent.
4. Temporal waits using durable timers/conditions and scoped wake signals; it holds no model process, long-running HTTP request or Activity slot. Rate-limited Activities observe/download/settle. Polling remains available even where webhooks exist.
5. Persist authoritative native observations, item dispositions, verified output artifacts and usage observations. The application reducer checks fence/revision/stop policy before making results available to consumers. A provider terminal event is not an acceptance event.
6. An outbox conveys committed facts to Temporal; consumers deduplicate. Lost wakes delay until bounded polling. Closed workflows do not get resurrected with Signal-With-Start from old callbacks. Continue-As-New carries unresolved dispatch identities and cursors; inbox/outbox custody outlives workflow-history retention.

Extend the current PostgreSQL inbox/outbox and drainer. The edge verifies and records; the worker reconciles; Temporal schedules. Do not add Vercel Queues or another generic queue merely because the starting research listed it as an option. Temporal Signals acknowledge server receipt before application handling; Updates can return handled results but need a responsive worker and do not make provider/database commits atomic. [Temporal message passing](https://docs.temporal.io/develop/python/workflows/message-passing).

### 6.3 Webhook ingress and replay

An endpoint is registered against a trusted provider product, project/account, signing-key version and permitted event catalog. Raw body/signature validation happens before parsing normalized fields or trusting identifiers. Apply the product's documented freshness/replay checks; do not invent a signature timestamp when none is authenticated. Gemini's static Standard Webhooks and dynamic JWT/JWKS modes need different verifiers. JWT validation must pin allowed issuer/audience/algorithm/key origin and bounded key rotation; it cannot follow a payload-supplied arbitrary JWKS URL.

Store a scoped delivery identity, provider event identity, raw-body digest or restricted evidence reference, verification result, received time and normalized resource wake. Existing redacted payload hashes are not a substitute for detecting conflicting authenticated bodies. Additive ingress design must define where that extra digest belongs without rewriting existing history. Same identity/same body is a duplicate; same identity/different body is a conflict/security event. Deduplicate independent of whether timestamp is still fresh on a retry according to the provider's authenticated-delivery rules. Reject invalid deliveries; acknowledge valid ones only after durable insertion.

The worker resolves resource IDs through previously admitted native bindings, fetches authoritative state and validates product/account/scope/generation. Never fetch an arbitrary result URL from webhook content. Unknown resources are quarantined/reconciled; they do not create a Mission. Preserve out-of-order and stale events for audit; use native sequence/cursor where available, otherwise reconcile current resource/history rather than ordering by receipt time. Event-type schemas are versioned per product: OpenAI Agents session idle is not Responses completion, and Anthropic Managed events are not Message Batch events.

A completion can arrive before the submit Activity has recorded its handle. Keep the verified orphan event and attach it only when a trusted submission correlation establishes ownership, then replay reconciliation. An ingress crash after commit/before acknowledgment causes a harmless duplicate. A worker crash after result commit/before wake causes a harmless repeated wake. A crash after provider result retrieval/before local custody is more serious when retrieval consumes the result: xAI deferred retrieval documents one-time semantics. Require a crash-safe custody strategy/provider clarification or mark automatic recovery unsupported and exclude that mode from durable critical missions.

Provider-specific retry windows differ: OpenAI documents up to 72 hours, Gemini 24 hours, and Anthropic Managed a small finite attempt count with no replay/backfill. These are delivery limits, not permission to wait that long before reconciliation. Poll with jitter/backoff and a finite maximum interval derived from deadline, quota and result expiry. Persist polling leases so restarts and multiple workers cannot create a poll storm. Auth failures and exhausted retrieval windows become explicit recovery cases.

### 6.4 Partial results, expiry, cancellation and revisions

Batch item identity, not array order, joins results to requests. Validate missing/duplicate/foreign item IDs, malformed rows, error rows, counts and output digests. Record each item as succeeded, failed, cancelled, expired, missing or unknown. Partial success is admissible only if the Mission's completion contract permits that exact required/optional subset. Capture successful bytes before expiry even if another item blocks acceptance. Retry only eligible failed/missing items under linked repair identities; never resubmit the successful batch as fresh work.

Cancellation stops new item scheduling and requests the native supported cancel action. It is not a refund or proof that every item stopped. Reconcile native terminal state, partial results, external effects and usage after cancellation. If the provider cannot cancel individual items in a shared batch, mark the cancelled consumer fenced; other consumers may continue under policy. A late result may be retained for audit/billing, but cannot satisfy a cancelled activation or reactivate a revoked effect. Storage and provider-file cleanup have separate receipts.

On Revision change, preserve the starting Revision/generation. An explicit Transition Impact determines finish-existing, checkpoint, cancel-and-replace or supersede-after-completion. Result admission checks the original request plus current permitted transition; matching schema alone cannot carry results into a changed question/rubric/source scope. Carry-forward requires the accepted digest-based eligibility law, with independent evidence-freshness evaluation. Until full transition activation is implemented and qualified, support pinned Runs and explicit successor Runs/Missions rather than claiming safe hot replacement.

Expiry has three independent deadlines: Mission usefulness, provider compute deadline and result/file retention. Reserve time/quota for capture before retention ends. Credential refresh does not extend result availability. Expired output is `unavailable`, not an empty successful result. A result completed just before cancellation is settled once; the serialized application fence decides whether it is consumable. Late usage can append corrections without changing historical outcome decisions.

### 6.5 Caching and cost settlement

Prompt caching reuses prefix computation. It does not make claims fresh, cache arbitrary function effects, avoid revalidation or create durable jobs. Separate it from deterministic artifact/verification caches and Interfaze's specialized-result cache. Pin model-specific cache behavior in the release: current OpenAI settings differ across model generations; Anthropic has explicit TTL/breakpoint controls; Gemini Interactions/Argon currently use implicit caching rather than explicit cache objects; xAI hits are automatic and not guaranteed. See the [cache evidence](MISSION-CONTROL-NEXT-STAGE-EVIDENCE-2026-10-16.md#provider-evidence).

Put stable policy/tool/schema/prompt prefixes before changing source data where supported; keep tenant/private material in authorized scope. Cache keys include product/model/protocol, relevant prompt/tool/source/policy digests and the required access boundary. Never share a prefix or cached result across tenants merely by matching text. Retention, residency and revocation policy can disallow a cache even when it is cheaper. A cache hit does not bypass domain admission or current authorization.

Plan using conservative uncached cost plus bounded writes/storage/tool/hosted-compute costs; settle from observed usage. Estimate whether reuse within actual TTL amortizes write premiums. Do not multiply Batch and caching discounts blindly: applicability and ordering differ. Do not create artificial warming calls without a justified budget. Record uncached input, cache writes by TTL, cache reads, output/reasoning tokens, tools, sandbox/GPU duration, storage/egress and per-item allocation when reported. Preserve absent usage as unknown.

Usage identity is product/account/native request/item/component plus observation revision. Append late corrections; dedupe repeated observations. Reservations release only according to verified settlement or an explicit conservative unknown-liability policy. Allocate shared batch costs by measured per-item usage when possible, otherwise a declared allocation method and uncertainty; do not invent equal exact charges. Reconcile provider invoices/usage endpoints when authorized. SDK auto-retries, Temporal retries and provider retries must have one clear owner at each boundary, otherwise apparent caching savings can be overwhelmed by repeat submissions.

## 7. Deterministic tools and domain/ML workloads

Use the same resource/evidence envelope for deterministic and probabilistic work while preserving their different meanings. A deterministic parser can fail or lose fidelity; an ML model can return well-formed but unsupported output. Neither belongs inside an agent merely to fit the scheduler.

~~~yaml
schema: evolution.workload_contract.v1
operation_ref: '<published KS/domain operation and version>'
execution_class: '<deterministic_tool|decision_model|ml_model|agent_workload>'
input_schema_ref: '<typed schema digest>'
output_schema_ref: '<typed schema digest>'
input_artifact_refs: ['<immutable bytes and scope>']
preconditions_ref: '<identity, size, modality, license, consent and environment>'
environment_manifest_ref: '<image, packages, hardware, drivers, weights and data>'
resources_ref: '<CPU/RAM/GPU/VRAM/duration/storage/egress/concurrency ceilings>'
evidence_contract_ref: '<locators, transformations, uncertainty and limitations>'
completion_contract_ref: '<required outputs and checks>'
effect_class_and_grants_ref: '<read/compute/stage/apply/publish>'
recovery_ref: '<idempotency, native handle, checkpoint and cleanup>'
~~~

Result records bind actual environment/model/tool versions, input/output digests, units, provenance, random seed where supported, observed hardware, usage, execution status, validation findings and uncertainty. A seed is not a determinism guarantee on a different GPU/kernel. Store large model checkpoints/videos/structures in object custody; return bounded manifests/previews. Human/API/MCP consumers receive the same authorized typed result, with a useful display summary and downloadable bytes rather than unbounded inline payloads.

| Workload | Concrete contract and owner | Acceptance and limitations |
| --- | --- | --- |
| Native PDF/HTML parsing | Shared KS preparation; exact parser image/options, captured bytes, text/DOM/geometry projections | Preserve byte-to-locator lineage. The actual [parser](../../../../knowledge-services/services/parser/parser.py) does not execute CSS/JS layout or establish image-only facts; it has explicit process/input/output/page bounds. Do not advertise OCR through that path. |
| OCR/document extraction | Shared KS Interfaze or qualified conversion route; page/image refs, language/layout/schema options and source regions | Keep raw bytes, page/box coordinates, text and transformation residuals. Check names, numeric units and source regions deterministically where possible. OCR confidence and a schema-valid JSON object do not establish source truth. Docling conversion remains a separate [preparation route](../../../../knowledge-services/packages/preparation/src/conversion/route.ts). |
| Classification/routing/reranking | Shared decision mechanism, domain-owned taxonomy/rubric/calibration | Typed results, abstention and per-question evidence. Jev/Decisions can suggest a route; code authorizes it. No silent truncation, thresholds copied across models, or automatic domain writes. |
| Protein structure prediction | Domain-owned scientific workflow with a shared remote-job/custody adapter | Pin sequences, chains, modifications, ligands/templates/MSA databases, model weights/license, seeds and environment. Return structures plus model uncertainty/coverage/quality metrics and limitations; a predicted structure is not binding/efficacy/clinical evidence. Human scientific review is required where the intended use demands it. |
| Image/video generation or analysis | Reusable media-job mechanics; domain/product owns creative/scientific intent and rights | Pin model, prompt/assets, dimensions/frame rate/duration, safety/rights policy and budgets. Register original media, thumbnails/transcripts and render/format checks. Analysis and generation are distinct capabilities; a generated illustration cannot become empirical evidence. |

Protein folding and larger video jobs should target an explicitly admitted remote compute profile, not the owner's 16 GiB laptop. Provider-hosted inference may avoid local GPUs but still leaves preprocessing, upload/download, storage, verification and cancellation to us. A self-hosted model adds weight/database custody, license eligibility, scheduler/GPU capacity, driver/toolkit and cleanup obligations. The official [AlphaFold 3 source](https://github.com/google-deepmind/alphafold3) is a concrete model family to evaluate, not an installed or licensed platform capability. No model installation or folding experiment was performed here.

Shared KS can expose generic submit/inspect/result/reconcile primitives. Domain adapters own sequence validity, scientific applicability, biomarker meaning and recommendation constraints. Keep domain-specific labels/ontologies out of the general Mission Control kernel. A capability manifest says whether it is available as API, CLI, MCP, worker-only or local operator service; callers cannot infer one from another.

## 8. Verification quality and longitudinal evidence

### 8.1 Verify the right assertion for the intended use

Use the existing KS staged pipeline: captured source integrity and selectors, mechanical checks, evidence-closed semantic assessment, source authority/applicability and intended-use admission. The [deterministic engine](../../../../knowledge-services/packages/verification/src/deterministic/bundle-verification.ts) gates semantic eligibility; a later semantic verdict cannot reverse a deterministic failure. The [semantic engine](../../../../knowledge-services/packages/verification/src/semantic/verify-case.ts) requires runtime-authorized cases, snapshots judge identity, and calls for a distinct-family/deployment second judgment on high/critical or uncertain cases; missing agreement can result in review/abstention. These are observed mechanisms, not proof of overall quality on a new scientific domain.

An efficient verification policy starts by specifying the failure it must catch. Exact source existence/digest, locator resolution, quoted text, subject identity, unit/date/arithmetic and schema checks should run in code. Semantic judges see the bounded evidence needed for atomic claims and have no tools or authority to manufacture additional support. High-risk or disputed cases can escalate to independent methods/families and qualified people. More model calls without calibrated evidence do not create scientific certainty.

Proposed VerificationPolicy pins intended use, claim classes/risk, required source kinds, locator fidelity, deterministic checks, semantic rubric/judge/calibration, contradiction handling, allowed reuse, human-only triggers and finite escalation budget. Outcomes distinguish `supported`, `qualified`, `contradicted`, `insufficient`, `unresolved`, mechanical failure and access failure, mapped explicitly to the existing verdict vocabulary. This document does not replace the current lattice with a new incompatible enum.

Measure quality using held-out labeled cases, false support/attribution rates, qualifier omission, locator failures, abstention/coverage, source diversity, adversarial content and subgroup/applicability errors. Report uncertainty intervals and sample composition. A small smoke test establishes connectivity, not calibration. Use freezeable benchmark manifests and keep optimization labels out of the held-out acceptance set. Reuse only when claim/input/evidence/selector/policy/method/calibration dependencies match and freshness is admissible. Changed source, rubric, route or applicability invalidates the relevant assessment even if prose is unchanged.

Agent guidance should be short and actionable: atomize a claim; capture source/version; give exact locator; keep qualifiers and null/missing states; run mechanical checks; request the minimum semantic assessment; escalate the returned failure class. Do not repeatedly ask a broad model to fix an evidence failure with a better narrative. Failure repair must target acquisition, extraction, claim scope or policy as appropriate. A cross-family consensus is still model agreement and cannot waive source or human requirements.

### 8.2 Claim/source/time/applicability model

Serious longitudinal research needs a domain evidence graph with immutable assessment history. Mission Control holds references to it, not a competing scientific claim store.

~~~yaml
schema: evolution.longitudinal_claim.v1
claim_id: '<stable semantic identity>'
claim_version: '<immutable assertion bytes>'
proposition_ref: '<atomic proposition including qualifiers>'
subjects_ref: '<domain identifiers and ontology version>'
evidence_refs:
  - source_snapshot_ref: '<publisher/source version and capture>'
    locator_ref: '<resolvable page/section/table/region>'
    relation: '<supports|contradicts|qualifies|context>'
time:
  event_or_study_period_ref: '<what time the evidence describes>'
  published_at: '<time or unknown>'
  retrieved_at: '<time>'
  assessed_at: '<time>'
  valid_time_ref: '<asserted domain validity interval or unknown>'
  knowledge_sequence_ref: '<native store token, not invented cross-store sequence>'
applicability_ref: '<population/condition/stage/intervention/comparator/outcome/context>'
evidence_grade_ref: '<domain rubric/version, reasons and uncertainties>'
assessment_refs: ['<deterministic, semantic, expert and admission records>']
relations_ref: '<supersedes/retracts/contradicts/derived-from; never delete history>'
freshness_and_review_policy_ref: '<claim-specific policy>'
~~~

For cancer research, distinguish mechanistic/preclinical findings, early safety signals, controlled clinical endpoints, mature follow-up and guideline/regulatory context. Record cancer subtype, stage, biomarkers, population, intervention/dose, comparator, endpoint definition, effect estimate/interval, follow-up, design, sample size, adverse events, sponsorship and study limitations where available. A trial registration/status change is not a published efficacy result. An improved surrogate endpoint is not automatically longer survival, and neither is a universal cure. NCI describes the distinct questions and stages of [clinical trials](https://www.cancer.gov/research/participate/clinical-trials/how-trials-work).

Do not produce a single unsupported percentage of progress toward curing cancer. Present a sourced timeline and evidence gaps by subtype/intervention/outcome, showing contradiction, replication, retraction and applicability. A new contradictory study creates a linked assessment and change event; it does not erase the earlier source or silently flip all recommendations. Reconcile duplicate preprint/publication/trial records without counting them as independent corroboration. An official company announcement may establish what it claims, while independent evidence determines scientific support.

Research synthesis, diagnostic/supplement recommendation and patient-specific clinical advice are separate intended uses and grants. A research report can be acceptable with explicitly unresolved evidence. A personalized recommendation needs domain safety/clinical policies, contraindication/interaction and applicability review, qualified human involvement where required, and a clearly defined jurisdiction/product boundary. Nothing in this proposal promises scientific or clinical certainty or authorizes medical action. If necessary evidence is absent, the product abstains or routes to qualified review; a higher model confidence cannot fill that gap.

### 8.3 Human review is evidence, not infallibility

Record reviewer expertise/role, exact packet, criteria answered, caveats, conflicts and selected evidence. Separate editorial approval, scientific adjudication, domain admission, effect authorization and publication approval. Independent review can be required when the producer is a human as well as when it is an agent. Review history is immutable; a later correction appends a superseding decision and records downstream invalidation. Do not delete an adverse review to make a release appear accepted.

## 9. Dashboard control plane and HITL contracts

### 9.1 Choose a UI integration without moving authority

The existing intent already includes chat, mission graphs, progress, intervention, revision proposals and artifact/context injection. The underspecified part is what a displayed action authorizes and how it survives disconnection, delegation and revision. Resolve that in server contracts before choosing a chat component library.

| Option and current official evidence | Fit to this architecture | Recommendation / qualification |
| --- | --- | --- |
| [AI SDK UI stream protocol](https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol) supports custom backend SSE/message data; [tool approval](https://ai-sdk.dev/docs/ai-sdk-core/tools-and-tool-calling) now uses `toolApproval`, with older `needsApproval` deprecated. | A Python MC read/command bridge can project authorized data to a TS frontend. SDK-local tools and provider-executed tools have different enforcement. | Favor a thin typed dashboard/BFF adapter and MC command receipts. Never use a client approval part as a Human Task resolution without server validation. |
| [AI Elements Confirmation](https://elements.ai-sdk.dev/components/confirmation) renders request/decision states. Current banner announces migration to shadcn/ui and deprecation at the end of November 2026. | Components can display a task but do not supply durable authorization or acceptance. Their examples differ from current core approval API. | Treat components as replaceable source-level UI; qualify exact pins and replacement plan rather than coupling the domain to the old registry. The vendor date is a lifecycle fact, not an implementation schedule. |
| [CopilotKit architecture](https://docs.copilotkit.ai/concepts/architecture) uses frontend/runtime/agent over AG-UI; [HITL](https://docs.copilotkit.ai/human-in-the-loop) separates agent-invoked frontend tools from graph interrupts. | Useful for embedded copilot/shared-state interaction. A custom MC adapter can expose command/read results; a LangGraph interrupt is subordinate runtime state. | Evaluate one bounded proof against MC Human Tasks. Do not resume a graph directly from an uncommitted browser answer. Preserve MC as the business authority across all lanes. |
| [CopilotKit OSS versus Intelligence](https://docs.copilotkit.ai/concepts/oss-vs-enterprise) distinguishes optional continuity/persistence services from OSS UI/runtime. Python and other non-TS runtime options have extra service requirements in current docs. | Existing PostgreSQL/Temporal authority should remain; optional conversation persistence needs an explicit data/operational choice. | Avoid introducing another persistent service by default. If Intelligence is chosen, establish data policy and receipt/read-model boundaries; do not claim it is required for ordinary OSS UI. |
| [MCP Apps](https://modelcontextprotocol.io/extensions/apps/overview) and [MCP-UI AppRenderer](https://mcpui.dev/guide/client/app-renderer) provide host-mediated sandboxed views. | Reusable artifact/review views across capable agent hosts and dashboard. Core MCP support does not establish Apps support or mobile qualification. | Preserve the accepted MCP Apps/MCP-UI target, isolated resource bundle, negotiated capabilities and text/native fallbacks. Tool calls reauthorize at MC. |

A narrow first proof should render the same sealed review packet with task/version/conflict behavior through a plain typed view and one selected chat bridge. Compare accessibility, reconnect, auth, file preview, stale state and mobile fallback. Do not install both frameworks into the Mission Control kernel or run their built-in agents as competing mission schedulers. The actual AI Engineer research dashboard manifest has no AI SDK/CopilotKit declaration; an integration option is not existing installed architecture.

### 9.2 Extend the existing Human Task service

The task must declare **purpose** and **resolver policy**, separately from the transport:

~~~yaml
schema: evolution.review_policy.v1
origin: '<workflow_gate|provider_permission|provider_question|mcp_elicitation|governed_effect>'
purpose: '<clarification|artifact_acceptance|scientific_review|revision|effect|publication>'
resolver:
  mode: '<human_only|agent_delegable|service_check>'
  eligible_principal_policy_ref: '<server-validated actor/grants>'
  separation_of_duties_ref: '<producer/reviewer constraints>'
delegation:
  permitted_decisions: ['<explicit subset>']
  allowed_delegate_refs: ['<agent/service identities or policy>']
  maximum_depth: '<finite>'
  expiry_at: '<time>'
  token_and_spend_ceiling_ref: '<shared review budget>'
  evidence_required_ref: '<assessment and locator requirements>'
target_ref: '<immutable artifact/revision/intent set>'
packet_digest: '<digest of actual reviewed packet>'
policy_digest: '<sealed policy>'
task_version: '<expected version>'
remediation: {target_ref: '<declared node>', maximum_rounds: '<finite>'}
timeout: {decision: '<wait|escalate|stop>', default_approval: false}
~~~

This is an additive design, not a request to change existing HumanGateSpec canonical serialization. Preserve existing `approve | deny | request_changes` wire decisions and their mapping to user-facing approve/reject/request changes. New purpose/policy fields need a versioned compatibility plan; do not invent `abstain` as an accepted v1 resolution merely because an older normative annex illustrated it. An abstention can be an assessment/escalation without pretending the gate has been approved.

Server-authenticated principal kind, assurance and delegation lineage decide eligibility. A body field claiming `human` is not identity proof. Agents may inspect authorized packets, answer agent-delegable clarification/quality checkpoints, or submit a proposed resolution for human review. They cannot call the human resolver with a user's identity, inherit human-only eligibility from an owner-issued tool token, mint their own delegation, broaden decisions or self-approve a gate that excludes their producer lineage. One agent presenting another model's suggestion does not turn it into human approval.

Human-only policies should be the default for increased grants/budgets, relaxed proof, clinical/scientific adjudication where expertise is required, production/publication effects and owner-designated final acceptance. An owner can preauthorize a narrowly defined automated release policy through an independently reviewed policy change; an executor cannot reclassify its current gate as delegable. Service checks produce service attestations, never fabricated human decisions. For agent-delegable gates, configure independence by principal, deployment/model family and producer lineage as the risk warrants; different agent names alone establish no independence.

Delegation is a sealed grant intersection over task/purpose/packet/decision set/expiry/maximum depth/budget. Revocation and task supersession invalidate unconsumed delegation. Each agent assessment records actor, runtime/provider/model/skill pins, evidence inspected, tool calls, uncertainty and parent delegation. Preserve one accepted resolution in the existing ledger; append the assessment/delegation evidence it relied on. A delegate cannot reset review-round or budget counters by spawning another agent.

### 9.3 Resolution and race protocol

1. Create the task, immutable review packet and policy reference with event/outbox in one application transaction. Packet items include actual registered bytes/previews, evidence and diff; not a promise that an agent will later attach the artifact.
2. Read authorization scopes the packet and current task. The dashboard, mobile and MCP expose the same state and allowed actions, including human-only status and why an agent cannot resolve it.
3. Submit `request_id`, expected task version, reviewed packet digest, decision, feedback artifacts and delegation reference if applicable. Actor and time are server-attested. The service checks purpose, current grants, stop fence, deadline, generation, policy and separation of duties.
4. Serialize on the existing task. The identical request/actor/bytes recovers the same receipt; another decision receives an already-resolved/version conflict. No frontend optimistic update is final until this receipt commits.
5. The committed decision wakes Temporal; the waiting activation rereads authority. Returning HTTP 202/Socket acknowledgment or rendering a success card is not proof that the workflow has applied the effect.

An expiry/resolution/cancellation race has one serialized winner under the task policy. Human-only timeout never approves. Keep-waiting may retain the task while recording an escalation; notification delivery is independent. If changed artifact bytes or a revised intent changes the review target, cancel/supersede the old task and create a new task/round as appropriate. Preserve the former decision as history; it cannot authorize the changed output. If the native provider approval handle expires while durable review remains open, reconcile and obtain a fresh correlation; do not replay an approval into a new tool call by ID coincidence.

Native tool approval and workflow acceptance use different origins over the same service. Bind provider session/turn/request, normalized input digest, generation, policy and replay strategy. Editing arguments creates a new digest and re-review when required. For long waits use qualified defer/checkpoint or deny-and-park semantics; do not hold a hook process or Activity indefinitely. MCP elicitation is a request for input, not a universal before-effect gate. The existing [human-control specification](../archive/multi-provider-2026-10/SPEC-03-human-control.md) already defines the prepare/review/execute fallback; extend its exact semantics rather than bypassing it with UI callbacks.

### 9.4 Feedback, revisions and bounded recursion

Feedback is an immutable artifact with author kind/identity, reviewed packet, criterion IDs, requested changes, evidence, severity and proposed scope impact. It is untrusted task input until admitted. A comment containing instructions to change grants, skip verification or publish cannot alter policy. Attach context/artifacts through the existing authorized command path with immutable refs, visibility and causation; do not inject secrets or overwrite the system policy.

Use a bounded transition:

~~~text
candidate output -> verification -> sealed review
  approve -> acceptance evaluator -> separate eligible publication/effect
  deny -> not accepted / declared termination
  request_changes -> scope classification -> declared remediation
                    -> new candidate -> relevant re-verification -> new review
~~~

Wording/format fixes inside the same goal and authority can follow the authored remediation node. New capabilities, changed evidence criteria or planning structure require a Revision Proposal. Material goal, authority/tenant or success-meaning changes follow the accepted successor/fork law; do not squeeze them into an in-place edit. Present the transition impact and expected-head version before activation. Review approval is specific to its purpose; approving content does not grant deploy, and approving a deploy intent does not certify its resulting feature works.

All nested evaluator/optimizer/agent/human loops debit inherited counters: maximum review rounds, total remediation attempts, child count/depth, semantic calls, wall-clock usefulness deadline, compute/tool/storage ceilings and total cost. Track repeated failure/feedback signatures and no-progress criteria. At budget/round exhaustion, abstain/escalate/stop according to the admitted contract, retaining the best candidate as unaccepted if necessary. No recursive loop resets its budget by creating a child Mission; explicit separately authorized successor work records a new allocation and origin.

Read models project mission graph/activation state, blockers, review queue, source/claim lineage, budget/unknown liabilities and intervention receipts. Every durable card carries `as_of_seq`, resource version and target digest. Stale cards refresh before mutation. Socket.IO replay and custom SSE/AG-UI projections derive from the same event ledger; ephemeral token/progress previews cannot settle a task. Disconnect, mobile backgrounding or a closed chat does not cancel the Mission. Offline approvals stay drafts until revalidated against the current packet.

## 10. Artifact acceptance, deployment evidence and product slices

### 10.1 Deliverable contracts

A deliverable has separate execution, artifact validation, evidence disposition, Mission acceptance, domain admission and publication states. Use immutable ArtifactVersion refs/digests and the existing promotion/custody machinery. A downloadable file, accepted source report and deployed feature are different acceptance subjects.

| Deliverable | Required acceptance evidence | Feedback route |
| --- | --- | --- |
| PDF/report | Exact PDF bytes/MIME/digest, source/claim index, readable rendered pages tied to renderer version, page/section/table/citation integrity, completeness/uncertainty and intended-use assessment | Feedback points to PDF page/region and criterion. Revise source/content and render a new version; retain earlier PDF and review. |
| Dataset/knowledge projection | Schema/native contract pins, item dispositions, verification/admission decisions, native plan/apply receipts and scoped readback | Repair held/failed items with linked intents; do not rewrite accepted history or replay successful writes as new effects. |
| Working application feature | Base commit, patch/tree/build digest, environment/configuration identity, relevant test results, reviewed deploy intent, deployment receipt and independent feature/readback checks | Feedback binds feature version, environment and reproduction/evidence; new iteration creates a new patch/build/deploy subject. |
| Course/library recommendation | Project/learner constraint snapshot, evidence versions, compatibility rationale, runnable examples/challenges where required, exclusions and freshness | Update affected dependencies/lesson claims; distinguish learning preferences from factual correction. |
| Supplement/diagnostic/biomarker recommendation | Domain applicability, source/evidence grade, contraindication/limitation policy, intended-use admission and human review where required | Challenge evidence/applicability through domain review; do not treat chat approval as clinical validation. |

DeploymentReceipt is a versioned artifact naming application, environment, provider/project, immutable deployment ID/URL, build/source/config digests, authorized actor/effect intent, timestamps, rollout/readback checks and rollback target. Exclude secret values. A URL must be an allowed HTTPS target resolved through trusted deployment metadata; a page loading or HTTP 200 alone does not prove the intended build or feature. Verify build identity, smoke/interaction criteria, access controls and the exact acceptance behavior, recording who checked it and when. Preview and production use distinct effects/grants.

Acceptance of a feature requires the verified deployment link when deployment is a declared deliverable. If publication authority is absent, finish only the privately reviewable deliverable contract or report the deploy criterion blocked; do not invent a working link. A later feedback iteration references the deployed version and test observations, creates an admitted remediation/revision, and revalidates the changed feature. Rollback is an explicit effect with its own receipt, not deletion of a failed deployment from the record. This research deploys nothing.

### 10.2 Release vertically with shared surface contracts

Each slice pins a surface bundle: capability/skill bytes, MCP tool schemas, API/client contract, domain schema/query/profile, verification policy, dataset/content version, UI view/action schemas and readiness receipts. All surfaces carry the same scope, idempotency, native receipt and evidence/freshness semantics. A skill describes procedure; it cannot enlarge grants. Product BFFs compose user state; agents use the admitted native domain path rather than reverse-engineering GraphQL screens.

| Slice | First useful complete path | Readiness/safety gate | Follow-on surfaces and maintenance |
| --- | --- | --- | --- |
| Supplement evidence/recommendation | Selected compound/product/company research -> verified comparison/report -> domain-admitted recommendation/abstention through API + skill/MCP | Exact formulation/population/evidence/limitations and domain recommendation policy; review sensitive claims | Web/mobile comparison and feedback can follow independently; promote only selected product/evidence slices to refresh. |
| Diagnostic evidence/recommendation | Named diagnostic/assay and intended population -> source/evidence applicability -> bounded comparison/decision support | Distinguish analytical validity, clinical validity and clinical utility; required expert review and intended-use limitations | Product view and agent tools share evidence IDs; changed indication/test version triggers re-review. |
| Biomarker search/recommendation/dashboard | Authorized typed query/retrieval -> evidence packet and omissions -> approved dashboard cards | Correct units/reference/context, access controls, stale/partial disclosure and no implied diagnosis | Add personalization only through user-state/clinical policies; maintenance targets supporting evidence and selected assay dependencies. |
| AI Engineer library selection | Project constraints/lock/runtime/license/security needs -> compared candidate releases -> tested example/recommendation | Compatibility evidence, benchmark/task fit, exclusions and reproducible project snapshot | Agent skill/MCP first, project UI later; opt-in maintenance tracks selected direct/transitive dependency scope. |
| Personalized agent-framework course | Accepted evidence/library selection -> lesson/challenge versions -> user-specific course projection | Runnable exercise checks, source accuracy, accessibility and learner privacy; no nonexistent learner app assumed | Course API and skill can precede full learner UI; dependency/claim graph limits refresh to affected content. |

A slice passes its own end-to-end acceptance through at least one usable consumer plus its declared cross-surface contracts. The existing KS plan's final two-application fixture has explicit prerequisite gates; do not run or waive it early to demonstrate one slice. Component and slice qualification remain possible before every future product is finished. New web/mobile screens need their actual deployed/installed build tests; responsive web alone does not certify mobile push, background/resume or embedded Apps security.

## 11. Worked end-to-end Mission flows

These are illustrative contract walks, not authored launchable manifests or clinical recommendations. All amounts/cadences come from an admitted policy, not this document.

### 11.1 Selected supplement evidence to PDF, then economical maintenance

1. The owner selects a finite set of company/product/compound identities and intended comparison use. The coordinator resolves native domain schema, KS preparation/verification, research capability and content renderer pins, estimates input/tool/storage/verification costs and submits an admitted Mission Definition.
2. Acquisition captures manufacturer labels and independent sources separately. Native PDF/HTML parsing produces locators; Interfaze OCR is used only for affected image content under a qualified pin. Source snapshots and residuals remain immutable.
3. A Jev or Decisions workload classifies relevance/claim type using a domain question/calibration pin and an insufficient-evidence path. Unknown cases go to bounded evidence-guided analysis; classification cannot grant ingestion or recommend a dose.
4. Eligible independent items may use Batch after the product/mode check. Each external handle links to item/claim IDs. A webhook wakes reconciliation; polling recovers a lost notification. Successful items are captured even if one expires. An all-required comparison remains blocked until missing evidence is repaired or an owner admits reduced scope.
5. KS checks source/locator/value/units and semantic applicability; the domain admits a comparison or abstention for the intended use. The content node produces a PDF with explicit manufacturer assertions, evidence grades, dates, exclusions and uncertainty. Render validation is tied to exact bytes.
6. A human-only review packet includes PDF/previews, item coverage, evidence, unresolved contradictions and any proposed knowledge effects. Request changes routes to bounded content repair; a changed formulation claim invalidates the affected scientific assessment, not just the table formatting.
7. The accepted report is a private deliverable unless separate domain publication is granted. The owner chooses a MaintenanceCandidate: only selected formulations and high-value supporting claims. Its finite selector, change signals, scan/deep-research quotas and stale policy are approved independently.
8. A label change later produces one deduplicated refresh Mission. Unchanged study evidence is reused only under valid pins/freshness. Budget exhaustion marks affected outputs stale and suspends research releases; no continuous broad company search runs behind the dashboard.

Acceptance: all required selected items have an attributable disposition; no unsupported recommendation escapes domain policy; the approved PDF digest equals delivered bytes; one meaningful repeated signal yields one admitted refresh; pause prevents new releases while retaining existing liabilities.

### 11.2 AI Engineer project/library choice to course and verified feature

1. Capture project language/runtime/platform, exact dependency lock, deployment constraints, license/security requirements and task-specific evaluation criteria. Resolve allowed library releases and provider routes from fresh evidence without upgrading the project automatically.
2. A bounded research workload compares candidates against the concrete project. Deterministic dependency/API examples test compatibility; semantic judgment explains tradeoffs using cited sources. The selected library and evidence become a pinned domain result, not a global default for all projects.
3. Generate lessons and a runnable challenge tied to that result. Personalize pacing/explanations from an authorized learner-state snapshot while retaining common evidence and lesson versions. Verify educational claims and run finite exercise checks.
4. A coding node implements an explicitly scoped course/search/dashboard feature in its isolated workspace. The artifact packet contains patch, base/tree/build digests and relevant test receipts. Human review accepts the exact feature candidate.
5. If the Mission also has deploy authority, execute the separate prepared deploy intent. Register the deployment receipt and independently test the declared feature at the immutable URL/build. Show the verified link in the dashboard. If no deploy grant exists, that criterion remains blocked or is excluded by the original private-deliverable contract.
6. Feedback requests a clearer explanation and a changed interaction. The first is an in-scope content remediation; a new external data source may require a Revision Proposal/new grant. Both produce new immutable candidates and targeted re-verification, sharing the existing round/spend limits.
7. Promote maintenance only for the chosen dependency graph and affected course claims. A release/deprecation signal opens a compatibility candidate, tests changed examples, and proposes a course version; neither live project lockfile nor active Mission pins change silently.

Acceptance: candidate advice fits the captured project, challenge checks execute on the pinned environment, learner state is scoped, deployed build identity matches the accepted feature, feedback retains lineage, and an unrelated framework release causes no research Run.

### 11.3 Longitudinal cancer research without clinical certainty

1. The owner defines a research question by cancer subtype, intervention class and outcome, with finite source/query scope and a domain evidence-grade profile. Personal medical data is excluded unless an independently admitted profile permits it.
2. A hosted research capability can discover candidate sources; source snapshots/locators and trial/publication identity reconciliation are still KS/domain work. X search can discover announcements or researcher commentary, kept as attributed leads until primary evidence is captured.
3. Extract atomic claims, study/population/outcome/time and limitations. Mechanical checks precede evidence-closed semantic assessment. High-risk/contradictory claims follow the required independent/expert review; insufficient evidence remains visible.
4. Produce a PDF/timeline organized by question and evidence strength. Keep preclinical findings, clinical endpoints, trial status and mature outcomes distinct. Do not compute a universal cure score or personalize a treatment recommendation.
5. After review, promote only chosen claims/trials/dependencies into maintenance. A retraction or publication update invalidates affected assessments and triggers a bounded delta report. Duplicate preprint/journal records do not count as two corroborating studies.
6. The dashboard shows what changed, previous/current assessments, contradictions, coverage gaps and last verification time. A human adjudication can retain uncertainty; it does not certify a scientific conclusion forever.

Acceptance: every material reported claim has retrievable evidence and applicability/time; contradictory/retracted evidence remains in history; a source change updates dependent claims only; the report remains clearly separate from clinical recommendations.

### 11.4 Async completion versus cancellation and revision

| Event | Required durable response |
| --- | --- |
| Revision R4 submits batch B with items A/B/C; create response is lost | Keep original dispatch intent/reservation. Reconcile B via qualified identity; do not create B2 blindly. |
| Signed completion arrives before native handle persistence | Persist verified orphan wake; correlate only through trusted submission ownership, then fetch B. |
| R5 proposes a changed question for C while B runs | R4 stays pinned. Show Transition Impact; C cannot satisfy R5 merely because the JSON schema matches. Use approved replacement/successor semantics. |
| A succeeds, B has retryable error, C completes after cancellation fence | Capture all permitted bytes; admit A only to eligible consumer, repair B only under a new linked item identity, quarantine C from acceptance. |
| Duplicate webhook and polling observation report the same usage | One normalized observation/settlement per native item/component; preserve delivery receipts without charging twice. |
| Late reviewer approves the R4 packet from an offline device | Reject stale/superseded task; refresh current packet. The historical draft response grants no R5 effect. |
| Provider later reports a cancellation charge | Append correction and settle retained liability; do not reopen cancelled work or erase the earlier unknown state. |

Acceptance: exactly one semantic dispatch is admitted under the proved native/reconciliation guarantee; result consumption is fenced; no successful item is unnecessarily rerun; cancellation and revision cannot be undone by callbacks; unknown cost never becomes zero by omission.

## 12. Prioritized implementation backlog and acceptance tests

IDs below are proposal-local, not current sprint issues or tracker assignments. Dependencies are capability gates, not calendar phases. Existing sprint work must finish its own criteria; this design does not reopen it or alter its status.

| Priority / ID | Deliverable and dependencies | Testable exit criteria |
| --- | --- | --- |
| P0 / EV-01 | Baseline reconciliation and compatibility map; depends on actual post-sprint build/contracts | Record exact release/dirty source baseline; identify existing versus missing operations; preserve old canonical binding/manifest digests; no claim of live parity from docs or tests alone. |
| P0 / EV-02 | Capability evidence/release/impact contracts; EV-01 | A changed official schema/model lifecycle produces one candidate with source digest and affected pins; unsupported required combinations reject before paid calls; discovery cannot make a candidate executable. |
| P0 / EV-03 | External workload submission/reconciliation port; EV-01/02 | Crash before create, after acceptance/before handle, after handle/before outbox and during reconciliation produces a single admitted semantic intent or explicit ambiguous state. No fake idempotency header or blind uncertain retry. |
| P0 / EV-04 | Product-specific completion ingress; EV-03 and existing inbox/outbox/drainer | Signed fixtures test forged/stale/conflicting bodies, duplicate/reorder, unknown account/resource, early webhook, rotated key and crash-after-commit. Worker fetches authoritative state; old event cannot start/revive a Mission. |
| P0 / EV-05 | Item capture/cancellation/usage settlement; EV-03/04 | Missing/duplicate/foreign IDs and partial/expired outputs are explicit; only repairable failed items retry; cancelled/stale generations never satisfy acceptance; duplicate/late usage settles once with visible unknown liabilities. |
| P0 / EV-06 | Human-only/delegation policy extension over HumanTaskService; EV-01 | Authenticated agent cannot resolve human-only task via HTTP/MCP/Socket.IO/UI; delegated subset/depth/expiry/budget/producer rules enforced; spoofed actor kind ignored; concurrent human/agent/expiry/cancel yields one valid resolution. Historical v1 bytes remain stable. |
| P0 / EV-07 | Artifact/preview/deployment review contracts; EV-06 and existing custody | PDF preview and approval bind exact bytes; stale packet/modified artifact refused; arbitrary URL/HTTP 200 cannot satisfy deployment criterion; separate deploy authority required and verified build/feature link recorded. |
| P1 / EV-08 | Full revision/Transition Impact join where missing; EV-01/03/06 | Expected-head conflict, in-flight external work, carry-forward/freshness, revoked grant and rollback cases obey accepted law. Manifest submission support is preserved; no unsupported hot replacement is advertised. |
| P1 / EV-09 | KS decision profile for Jev/Decisions; EV-02/03/05 | Current Jev route remains compatible; result mapping preserves probability/confidence/unavailable; fixed held-out cases assess selective risk/coverage/cost; no confidence authorizes effects. Paid comparison is separate from offline adapter exit. |
| P1 / EV-10 | Interfaze/parser workload qualification; EV-02/03/05 | New documented model compatibility evaluated against incumbent pin; task/precontext/schema/size/usage/cache policy verified; native parser residuals and OCR provenance survive API/MCP/CLI; no inference that old ID is retired from absent table entry. |
| P1 / EV-11 | First economic maintenance slice; EV-02/05/06 | Finite selector and cardinality enforced; duplicate cadence/event signals yield one Run; scopes/quotas/cooldowns/pause/rolling budget/unknown liability all prevent extra spend; stale output cannot claim refreshed evidence. |
| P1 / EV-12 | One complete domain/product vertical; EV-07/09/10 and domain readiness | Choose supplement evidence or project/course slice; demonstrate declared skill/MCP/API path, domain admission/abstention and exact artifact acceptance; attach maintenance opt-in. Broader final fixtures retain their prerequisites. |
| P1 / EV-13 | Dashboard bridge qualification; EV-06/07 | Selected AI SDK or CopilotKit adapter renders task/graph/evidence and routes commands through MC; disconnect/replay/stale/offline/cross-tenant tests pass; MCP Apps isolation/fallback exercised; no client-only approval can execute an effect. |
| P2 / EV-14 | Gemini and xAI direct profiles, then Perplexity only if justified; EV-02..05 | Exact model/product/mode support matrices; Gemini retention conflict resolved or disallowed profile; no Interactions Batch assumption; x_search citations/time constraints preserved; xAI consuming-read mode withheld until recovery is proved; incremental value measured. |
| P2 / EV-15 | Scientific longitudinal profile and expert review; EV-06/10/11/12 plus domain evidence policy | Claim/source/time/applicability/contradiction/retraction tests, duplicate publication reconciliation, calibrated false-support evaluation and human-only review pass. Research output cannot be consumed as personal clinical advice without separate admission. |
| P2 / EV-16 | Remote GPU/media workloads; EV-02..07 plus licensed model/compute owner | Resource/VRAM/input/output/retention limits enforced; cancelled/lost job reconciles; actual environment/model/data pins and uncertainty accompany artifacts; local laptop never becomes an implicit heavy-compute fallback. |

Each exit report separates implemented, offline-tested, integration-tested, exact-placement live-qualified, blocked and unrun. Use criterion-to-receipt tables and retain failures. A fixture proves only its seam; an installed adapter does not certify every account, model or data class. Qualification expiry can block new launches without deleting historical results.

### 12.1 Compute-aware execution

Keep contract/schema validation, captured HTTP fixtures, replay/dedupe/race simulations, link checks and small labeled evaluations as the first proof layer. Use existing test seams; do not mirror each implementation method with tests. Durable crash/revision/authority cases justify integration tests at the database/application boundary. Paid inference and actual provider events are later finite, explicitly authorized qualification allocations.

On the 16 GiB host, run one heavy test/build/parser process at a time. Configure Jev worker count explicitly to a small bound for qualification rather than inheriting its four-worker default. Avoid parallel monorepo builds, large Docker stacks, GPU inference and full artifact scans. Reuse frozen source captures and stream bounded result files. Send real large OCR/folding/video work only to admitted remote profiles with output/storage quotas. During this research one read-only Sol worker was used; no local build, provider experiment or installation ran.

Use deterministic selection and inexpensive metadata checks before research. Benchmark cold/warm cache separately, report actual hardware/data size and do not present an unmeasured latency or dollar target as acceptance. Bound model context, fan-out, source acquisitions, semantic escalations, review cycles and outstanding bytes as well as spend. Queue waiting should consume durable state, not an idle model/sandbox allocation unless native retention requires and budgets it.

## 13. Unresolved decisions and dependencies

These are implementation design decisions, not blockers to delivery of this research:

| Decision | Recommendation / evidence needed before dependent release |
| --- | --- |
| Alias reproducibility and provider drift | Prefer immutable model IDs where exposed, record observed metadata and qualify repeated behavior; disclose aliases/opaque server weights. Decide maximum evidence age per risk/profile. |
| Approval trust and human identity assurance | Choose authenticated principal/assurance claims and service-to-service delegation attestation. Server enforcement must distinguish human-only from acting-on-behalf-of-human agents across every transport. |
| Full running Revision semantics | Reconcile actual manifest writer with the accepted proposal/Transition Impact law; keep unsupported transitions unavailable until crash/fence tests pass. |
| Maintenance utility/freshness and spend policy | Domain owner sets field/claim ages, priority/value scales, safety triggers, finite quotas and permissible autonomous changes. Start with narrow explicit member snapshots and no automatic expansion. |
| Clinical/scientific domain gates | Own intended-use profiles, evidence grading, expert requirements and legal/product boundaries in Biotech. Missing schema-authoring source or domain policy is a named blocker, not permission to invent one. |
| Google data controls | Official Interactions/background pages conflict on background `store=false` and retention. Until clarified/qualified, reject sensitive or retention-dependent combinations and use a conservative explicitly admitted non-sensitive profile if desired. |
| xAI consuming deferred result | Establish durable capture/retrieval failure behavior or leave this mode unqualified. Do not claim callback recovery for unverified webhook support. |
| UI framework and service footprint | Prefer a small typed bridge first. Choose one primary chat framework and exact pins after a bounded proof; decide separately whether optional CopilotKit Intelligence adds justified value/data obligations. |
| Operational KS schema ownership transition | Preserve current AI Engineer authority and Mission Control common component. Adopt shared operational SQL only through the accepted expand/migrate/contract gate. |
| Native stores and publication readiness | Actual Biotech schema/query/writer/review profiles, AI Engineer product schema and installed capabilities must be resolved. Existing source/GraphQL packages are not full products or deployment proof. |
| External submission idempotency/cancellation/usage | Product-specific conformance evidence is required. Unknown provider guarantees require visible reconciliation/human recovery and retained budget, not optimistic success. |
| Model/tool/provider evaluation funding | No paid evaluation is authorized here. Prepare finite comparisons, exact accounts/routes, data policy, ceilings and cleanup before seeking the missing execution authority. |

The recommended first join is EV-01 through EV-07 plus one constrained decision/preparation slice, then one explicit domain vertical and maintenance policy. This gives a useful governed result while the broader provider, scientific and product surfaces mature independently.

## 14. Delivery and validation record

The companion [evidence register](MISSION-CONTROL-NEXT-STAGE-EVIDENCE-2026-10-16.md) records current primary-source URLs, support status, unresolved contradictions, inspected repo anchors and source hashes. The starting report receives only an appended cross-reference/correction note. Runtime source, sprint docs, generated guides and existing edits are outside this task's write set.

Validation is documentary: UTF-8 readability, balanced code fences, parseable illustrative YAML, unique heading anchors, relative file/fragment targets, required source symbols and unchanged critical inspected-source hashes. External sources were opened during research; this is not a live API conformance test or an account entitlement audit. Final exact counts and filesystem verification are recorded in the evidence register after writing. No runtime tests, paid inference, external publication, live migration, deployment, install, commit or push occurred.
