---
type: Proposal
title: "Provider batch inference for Mission Control and Knowledge Services (proposal, 2026-10-18)"
description: "Proposal that a provider-neutral batch module (Inference Executor with batch dispatch, Inference Sets sharded into Provider Batches, three wait strategies) be built first, standalone, then integrated with Mission Control waits. Not built; owner interview before building."
tags: [mission-control, proposal, provider-batch, anthropic, openai, batch]
status: open
date: 2026-10-18
---

# Provider batch inference for Mission Control and Knowledge Services

Date: **2026-10-18 UTC**. Status: **proposal**. This document does not amend accepted specifications, sprint claims, ADR numbering, provider configuration or code. It refines §6 ("Durable external workloads, batches and cache economics") of the [next-stage contract design](MISSION-CONTROL-NEXT-STAGE-CONTRACT-DESIGN-2026-10-16.md) for batch inference specifically. Vendor facts are cited by ID from the [evidence register](PROVIDER-BATCH-INFERENCE-EVIDENCE-2026-10-18.md) (AB = Anthropic, OB = OpenAI). New record and tool names are illustrative proposals, not accepted wire schemas.

The active Mission Control sprint (Run 2: Cursor maturity, local CLI skills, ingress and the Fargate worker, plus `claude_managed` → `codex_agents` qualification) is unaffected. This is post-sprint work. It deliberately reuses Run 2 foundations: the Standard Webhooks verification, the Provider Wake inbox, dispatch-journal reconciliation and the Secret Broker.

## 1. Summary of the recommendation

1. **Build a standalone provider-batch module first.** It is a provider-neutral Python library with thin OpenAI and Anthropic adapters, a submission journal, an observer, a result collector and a cost estimator. It runs with a SQLite store and a CLI, with no Mission Control dependency. Mission Control and an MCP server are two consumers of the same core.
2. **Batch is not a Lane.** A lane implements the session/turn harness protocol. A batch has no session, no turns, no pause and no client-tool callbacks. Model it as an **Inference Executor** program behavior with a `dispatch` mode. `batch` is the first mode; `sync`, `flex` and `background` follow when direct provider APIs land. This is the planned "blend": one request envelope and one result/usage model, with several delivery modes.
3. **Separate the request, the provider job and the wait.** An **Inference Set** is the logical set of items a node wants. It is sharded into one or more **Provider Batches**, the native jobs. Mission consumption is expressed with the dependency classes and joins Mission Control already has (`required_blocking`, `degradable_blocking`, `nonblocking`, `advisory`; `all` / `minimum` / quorum). There is no new batch-specific waiting vocabulary.
4. **Support three wait strategies as first-class behavior:**
   - **await**: the node blocks until enough items are settled.
   - **submit-and-continue**: a ticket is issued, the mission proceeds, and a later collect node or dependent stage wakes when results land.
   - **detached/advisory**: results feed maintenance or a successor mission and never block acceptance.

   In every case a waiting mission holds no worker slot, model process or HTTP connection. Temporal sleeps, and an observer or webhook wakes it.
5. **Batch-wave missions are a primary pattern.** Program shapes built entirely from waves of batches (map → validate → reduce → next wave, batch-stepped agent loops and cascades) become the default for research, ingestion, evaluation and maintenance at volume.
6. **Gate access granularly.** Activation is controlled at installation → provider account → application/tenant grant → capability (provider + product + endpoint + model + mode) → mission/node → actor/tool scope, with spend thresholds that route to a Human Gate. There is a kill switch at every level.
7. **One skill with living knowledge.** A single `provider-inference` skill is introduced now. Batch is its first module, and direct APIs, server tools and hosted agents join it later. A machine-readable, dated provider-knowledge file is refreshed by a scheduled Mission Control maintenance mission, which is itself batch-powered, and changes are published only through a reviewed bundle release.

## 2. What provider batch can and cannot do

### 2.1 Capability comparison

| Dimension | Anthropic Message Batches | OpenAI Batch |
| --- | --- | --- |
| Unit | One full Messages request per item (`params`) | One HTTP request line per item (`url`, `body`) |
| Endpoints | Messages only (beta endpoint for beta features) [AB1, AB10] | Responses, Chat, Embeddings, Completions, Moderations, Images (gen/edit); one model per file [OB6] |
| Size | 100,000 items or 256 MB [AB4] | 50,000 items or 200 MB; 2,000 creates/h [OB9] |
| Deadline | 24 h expiry; most finish in <1 h [AB4] | `24h` only [OB4] |
| Results | JSONL stream once `ended`; available 29 days from creation [AB5] | Output and error files once terminal; default 30-day expiry, configurable from 1 h to 30 d [OB5] |
| Partial results | Only after the batch ends (counts are 0 until then) [AB2] | Only at terminal; completed lines are returned on expiry or cancel [OB17] |
| Server-side tools | Web search, web fetch, code execution, MCP connector, tool search, advisor [AB8] | **Unverified** for hosted tools in a Responses batch [OB8] |
| Structured output | Inferred supported [AB10] | Documented [OB7] |
| Reasoning/thinking | Documented [AB8] | Documented [OB7] |
| Prompt caching | Best effort; use a 1 h TTL and identical prefixes; warm with a one-item batch [AB14] | Supported; cached-input batch prices listed [OB11] |
| Not allowed | Streaming, fast mode, `max_tokens: 0` [AB9] | Streaming [OB7] |
| Completion notice | **None**, polling only [AB16] | Signed webhooks `batch.*` [OB15] |
| Client metadata / idempotency | No metadata, no idempotency key [AB17] | 16 metadata pairs; no idempotency key [OB3, OB18] |
| Discount | 50%, stacks with caching [AB12] | 50%, stacks with caching for current families [OB11] |
| Rate limits | Separate batch queue (e.g. 500k queued at Scale) [AB7] | Separate pool; per-model enqueued tokens [OB9] |
| Retention / ZDR | Not ZDR/HIPAA-eligible; delete early [AB20] | Not ZDR-eligible; short expiry plus delete [OB19] |
| Spend reconciliation | Admin usage report by `service_tiers[]=batch` [AB19] | Admin usage `batch=true` [OB20] |

### 2.2 What this means

A batch item is **one stateless, bounded unit of cognition**: classify, extract, judge, summarize, translate, rank, embed or generate. On Anthropic, a single item can also run a **bounded server-side agent loop** using web search, web fetch, code execution or the MCP connector. That loop ends at `end_turn` or `pause_turn` without ever calling us back.

Batch cannot run client-side tools mid-item, stream, pause, ask a human, or hold a conversation. Anything multi-turn is built by Mission Control as **waves**. Each wave replays the conversation so far, which is cheap when the prefix is cached, and executes client tools between waves.

Batch is the right mode when the work is **many independent items**, the latency tolerance is minutes to hours, and cost or rate-limit headroom matters. It is the wrong mode for interactive agents, human-in-the-loop turns and anything whose deadline is shorter than the realistic batch latency. For small item counts with a few minutes of tolerance, OpenAI **Flex** costs the same as Batch without the job overhead [OB13]. The dispatcher should consider it.

## 3. Vocabulary (proposed additions)

| Term | Meaning |
| --- | --- |
| **Inference Executor** | Proposed program behavior (an Executor alongside Agent and Deterministic) that performs provider inference over a declared item set through a `dispatch` mode: `batch` now; `sync`, `flex` and `background` later. It carries no agent harness. |
| **Inference Item** | One provider-native request (`params`/`body`) with a stable **item key**, a template and input digest, an output schema and a provider-native option allowlist. The key is independent of array order. |
| **Inference Set** | The immutable, digest-sealed set of items one activation asks for. It is the unit of admission, budget reservation and consumption. |
| **Provider Batch** | One native job (`msgbatch_…`, `batch_…`). An Inference Set maps to one or more provider batches through sharding or coalescing. This is the external handle of the 10-16 §6 `external_workload` record. |
| **Batch Ticket** | A typed, durable reference to an Inference Set that can be passed as an output. Downstream nodes, a collect node or a successor mission bind to it to consume results later. |
| **Item Disposition** | Per-item outcome: `succeeded`, `errored_retryable`, `errored_terminal`, `invalid_output` (schema or validation failure), `expired`, `canceled`, `missing` or `unknown`. |
| **Batch Observer** | One scheduled reconciler per provider account/workspace. It lists in-flight batches and emits Provider Wakes for state changes. It replaces per-batch polling workflows. |
| **Batch Pool** | Optional coalescer that groups compatible items from several activations of the same tenant into shared provider batches, with per-item ownership, cancellation and charge allocation. |

## 4. Behaviors of the batch node

### 4.1 Node contract (manifest sketch)

~~~yaml
- key: extract_claims
  behavior: inference_executor          # proposed behavior
  dispatch:
    mode: batch                         # batch | flex | sync | background (later)
    provider: anthropic                 # or openai; or `auto` with a route policy
    capability: anthropic.messages.batch.claude-sonnet-5-5   # catalog pin
    shard: { max_items: 2000, max_bytes: 64MB }              # smaller shards = earlier partial release
    pool: tenant_shared                 # none | tenant_shared  (Batch Pool)
    deadline: PT6H                      # mission usefulness deadline, not the provider 24h
    on_deadline: { escalate_remaining: flex, else: degrade }  # or cancel | wait_provider_expiry
  items:
    from: inputs.papers                 # artifact / output ref; one item per row
    key: "${row.doc_id}"                # stable; hashed into custom_id
    template: prompts/extract_claims@3  # pinned prompt, tools and output schema
    cache_prefix: [system, tools, schema]   # stable prefix first (1h TTL on Anthropic)
    output_schema: claim_set@2
  validate:
    - schema                            # deterministic, per item
    - executor: agreement_check         # optional deterministic cross-checks
  consume:
    dependency_class: degradable_blocking   # required_blocking | degradable_blocking | nonblocking | advisory
    join: { minimum: 0.95 }                  # all | any | minimum(n or fraction) | quorum
    release: per_shard                       # per_shard | on_join | on_set_terminal
  repair:
    retry: { dispositions: [errored_retryable, expired, missing, invalid_output], max_rounds: 2, mode: batch }
  outputs:
    - { name: claims, schema: claim_set_collection@2 }
    - { name: ticket, schema: batch_ticket@1 }
  budget: { reserve: estimate_x1.25, ceiling_usd: 180 }
~~~

### 4.2 Required behaviors

1. **Prepare (no spend).** Expand items from inputs and render the pinned template. Compute item keys and per-item digests. Validate each item against the provider-native option allowlist and limits (custom_id, size, model, endpoint and server-tool policy). Count tokens or estimate them. Choose shards. Produce a cost and latency estimate comparing batch, flex and sync. Seal the Inference Set digest. Prepare is idempotent on its inputs.
2. **Admit and reserve.** Check grants, data class (batch is never ZDR/PHI-eligible: AB20, OB19), quotas (provider queue headroom), the budget reservation and the Human Gate threshold. Write the operation intent and dispatch journal before any provider call.
3. **Probe (optional, recommended for new templates).** Send one item synchronously, or as a one-item batch, to catch shape errors. Anthropic validates only at batch end [AB6], so without a probe a bad template wastes up to 24 hours. A one-item batch also warms the Anthropic cache [AB14].
4. **Submit.** One short Activity per shard. OpenAI uploads the file (with `expires_after`), then creates the batch with `metadata.mc_dispatch=<key>` and `output_expires_after`. Anthropic creates the batch in the dedicated workspace. Persist the native handle before declaring the shard submitted. An ambiguous outcome becomes `submission_unknown` (§5.3).
5. **Sleep.** The workflow waits on a durable condition (wake counter, timer or deadline) and holds nothing else.
6. **Wake.** An OpenAI `batch.*` webhook arrives through the existing Signal Ingress (Standard Webhooks) as a Provider Wake. An Anthropic batch is detected by the Batch Observer. Both wake paths fall back to the observer. A wake carries only the resource ID; the worker re-reads the provider.
7. **Collect.** Stream the results JSONL into an immutable Artifact (raw bytes digest), then parse it into item results joined by `custom_id`. Validate per item and record Item Dispositions and per-item usage. Collect is crash-safe because both providers serve results repeatedly within retention.
8. **Release.** The reducer checks fence, generation and revision, then releases consumers according to `consume` (§4.3).
9. **Repair.** Ineligible items (errored, expired, missing or invalid) are resubmitted as a **linked repair set**: new item identities that point at their original items. Successful items are never resubmitted.
10. **Cancel.** Writes a stop fence, requests native cancel and reconciles. Completed items are still billed and captured [OB17]. A late result is retained for audit but cannot satisfy a fenced activation.
11. **Settle.** Settle from observed per-item usage multiplied by the price catalog version pinned at admission. Missing usage stays `unknown`, never zero. Reconcile with the Admin usage APIs when authorized [AB19, OB20].
12. **Clean up.** After custody and settlement, delete the provider batch or files according to the data-class retention policy. Cleanup has its own receipt.

### 4.3 Wait strategies: the user-facing choice

| Strategy | Expressed as | Behavior | Use when |
| --- | --- | --- | --- |
| **Await all** | `dependency_class: required_blocking`, `join: all` | Dependents wait for every item to be settled, including repairs. Missing evidence blocks acceptance. | Every item is required, e.g. a full comparison table. |
| **Await enough** | `degradable_blocking`, `join: minimum`, plus `deadline` | Releases when the quorum holds or the deadline passes. The remainder is repaired, escalated to flex or sync, or recorded as degraded scope. | Coverage targets ("95% of papers") and long-tail failures. |
| **Submit and continue** | `nonblocking`, emit `ticket`; a later `batch_collect` durable control, or any dependent stage, binds the ticket | The node finishes its "submitted" phase and independent branches keep running. When nothing else can run, the mission is *partially complete and asleep*. The wake releases the collectors, and the mission resumes exactly where results are needed. | The batch's result is needed later in the mission, with useful work to do in between. |
| **Progressive** | `release: per_shard` with small shards | Each shard releases its items to a per-item downstream (a stream of sub-activations or a swarm member per item). | Pipelines where downstream work per item is independent. |
| **Detached / advisory** | `advisory`, with the ticket routed to a successor mission (Mission Chain `supplies` with `release_on: execution_complete`) or to a maintenance policy | The mission can be accepted without results. Late results feed a successor or a refresh. | Enrichment, speculative prefetch, nightly maintenance. |
| **Hedged** | `on_deadline: escalate_remaining: flex\|sync` | Items unfinished at the mission deadline are cancelled from the batch and re-dispatched at higher cost under a pre-approved budget delta. | Deadline-critical runs that still want the discount for most items. |

Key law: **a provider terminal state is not acceptance.** Release depends on item dispositions, validation and the completion contract, as in 10-16 §6.2 step 5.

The `batch_collect` durable control is the single new control. It is an Event Wait specialized to one ticket: `ticket`, `join`, `deadline` and `on_deadline`. It also lets a Goal Loop iteration submit now and collect two iterations later, and lets a *different* mission collect a ticket it was granted.

## 5. Runtime design

### 5.1 State axes (extending 10-16 §6.2)

~~~text
Inference Set:  prepared -> admitted -> dispatching -> dispatched -> collecting -> settled_items -> released
                                                     \-> partially_released (per_shard / minimum joins)
Provider Batch: pending_submit -> submitting -> submitted -> provider_running -> provider_terminal(ended|completed|expired|failed|cancelled)
                     \-> submission_unknown -> adopted | parked_in_doubt | abandoned_by_owner
                provider_terminal -> results_captured -> parsed -> cleaned
Item:           queued -> in_provider -> settled(disposition) -> [repair_linked -> ...]
Usage:          reserved -> observed(per item) -> settled | explicit_unknown_liability
~~~

Native status is always stored alongside the normalized state.

### 5.2 Item identity and `custom_id`

The Anthropic limit (`[A-Za-z0-9_-]{1,64}`, AB4) sets the format for both providers: `mc_<set-short>_<item-hash>`. Here `set-short` is 10 base32 characters of the set digest and `item-hash` is 22 base32 characters of (item key + template digest + repair round). The ID never contains secrets, PII or domain identifiers in clear text. A mapping table, `item_hash → item key`, lives in the store. Duplicate, foreign and missing custom_ids are all detected at collect time.

### 5.3 Ambiguous submission

| Provider | Recovery strategy | Fallback |
| --- | --- | --- |
| OpenAI | `metadata.mc_dispatch` carries the dispatch key. List batches created after the journal timestamp and adopt the unique match. Input-file upload is also journaled and matched by filename/purpose/bytes. | Park in doubt. |
| Anthropic | No metadata [AB17]. Use a **dedicated workspace per installation**, which limits which batches can match. List newest first after the journal timestamp and match on request count and creation window against unclaimed handles. Adopt only on a *unique* match. After the batch ends, confirm by checking that every result's custom_id is in our map. | Park in doubt. The owner chooses between waiting for confirmation and accepting a duplicate-spend risk. This is recorded as a qualification gap. |

Never blindly re-create. A duplicate batch costs up to the full set price.

### 5.4 Observation: one observer per account, not one poller per batch

- **Batch Observer** is a Temporal schedule per provider account or workspace. It pages `list` (newest first) and compares each in-flight handle's status and counts with the stored observation. It writes a Provider Wake row only on change. One call covers up to 1,000 batches (AB1 list limit), so observation cost is independent of mission count.
- **Cadence** is adaptive per account, driven by the youngest in-flight batch: 1 min for the first 15 min, then 2 min, then 5 min, with a 15 min cap and jitter. It tightens near any mission deadline and stays inside the batch rate limit (AB7). A persisted lease prevents several workers from polling at once.
- **OpenAI webhooks** (OB15) reuse the existing `POST /provider/{provider}` route and Standard Webhooks verifier, extended with the batch event catalog. The observer still runs at a slower cadence to recover lost deliveries.
- **The drainer** maps a wake to the owning Inference Set and its activations, possibly several when pooled, and signals each workflow. Unknown batch IDs are quarantined, never adopted from webhook content alone.

### 5.5 Custody and data class

- Collect immediately when a batch reaches terminal. Do not lean on the 29- or 30-day retention.
- Store raw result bytes as a digest-registered Artifact. Per-item parsed outputs are derived artifacts.
- Results are **untrusted model output**. Server-tool items (web search or fetch) can carry prompt-injection payloads, so they enter Knowledge Services only through its normal verification and evidence admission.
- Data class gating:

  | Data class | Batch handling |
  | --- | --- |
  | `public` / `internal` | Allowed |
  | `confidential` | Only with a short provider expiry plus deletion after custody |
  | `phi` / `regulated` | **Denied** (AB20, OB19) |

  This matters for Biotech. Clinical PHI never goes to batch; public literature does.

### 5.6 Cost and capacity planning

- The **Estimate** is (token count or estimate per item) × the batch price from the pinned catalog version, using the provider's own cache multipliers (1 h write premium on Anthropic, cache-write price on OpenAI) and long-context surcharges (OB11, AB13). Output is bounded by `max_tokens` × items for the reservation, and the expected value is used for display.
- **Cache economics:** order prompts as stable system, then tools, then schema/rubric, then variable item data. On Anthropic, warm with a one-item batch and use the 1 h TTL [AB14]. Record the expected and observed cache-hit ratio per set; batch cache hits are best effort.
- **Capacity:** check queue headroom before submit (Anthropic queued requests [AB7], OpenAI enqueued tokens [OB9]). When there is no room, hold the shard in `pending_submit` with backoff, or route a shard to the other provider if the capability route allows it. This uses the existing `ProviderLimitSignal` / `LimitWaitPolicy` seams.
- **Route choice per set:** `batch` when items ≥ N (default 50) and the deadline is at least 1 h; OpenAI `flex` when items are few and a few minutes' latency is acceptable [OB13]; `sync` otherwise. The choice is recorded in the plan and the human sees it in the estimate.

### 5.7 Where it attaches in Mission Control (observed seams)

| Need | Existing seam to extend |
| --- | --- |
| Webhook verification and wake | `interfaces/http/ingress.py` `POST /provider/{provider}`; `application/signals/verification.py` (Standard Webhooks); `application/signals/wake.py`; `signals/drainer.py` |
| Ambiguous-dispatch recovery | Dispatch Journal and `remote_session/dispatch.py` lookup pattern (MP-06), as a model rather than a dependency |
| Budget | `domain/execution/usage_admission.py` `reserve()` / `settle()`; `domain/policies/reducer.py` ledger |
| Waiting | Temporal workflow condition plus wake signal, as in `adapters/temporal/workflows/operation.py` |
| Joins and partial release | `JoinKind`, `SlowSiblingPolicy`, `DependencyDisposition` in `domain/authoring/contracts.py` and `domain/programs/contracts.py` |
| Secrets | Secret Broker references; provider keys never enter bindings |
| HTTP clients | Plain `httpx` clients with `MockTransport` tests, matching `anthropic_managed/client.py` and `openai_agents/client.py` |

There is currently no direct Messages/Responses client in Mission Control; the module adds the first. `ProviderExecutionBinding` is lane-shaped, so an Inference Executor needs a sibling **inference binding** (provider, account ref, workspace/project, endpoint, model, mode, template digest, option allowlist digest and price-catalog version) rather than a ninth lane profile.

## 6. Batch-wave missions

Batch-only programs are Stage Graphs, Goal Loops, Swarms and Evaluator-Optimizers whose working nodes are Inference Executors in batch mode, with deterministic executors between them. They cost about half as much, consume none of the synchronous rate limits, and can sit in hundreds of concurrent missions while costing nothing to wait.

| Pattern | Shape | Research / ingestion / KS example |
| --- | --- | --- |
| **Map → validate → reduce** | Batch map over N items → deterministic schema and agreement checks → one reduce call (sync or a small batch) | Extract claims from 40k papers, then validate against the schema, deduplicate and build a claim index |
| **Cascade (triage → escalate)** | Cheap-model batch (`claude-haiku-5-5`, `gpt-6-luna`) labels and scores → items under a confidence threshold go to a frontier-model batch → residue goes to a Human Gate | Relevance screening of a corpus before deep extraction; biotech entity normalization |
| **Multi-judge / self-consistency** | k samples or k judge models per item in one batch → agreement executor | KS verification: semantic support of claim versus source by two providers |
| **Batch-stepped Goal Loop** | Each iteration is one batch of next turns for M independent agent threads, with Mission Control running client tools between waves and cached conversation prefixes | A "slow swarm" of 500 literature-review threads, each advancing one turn per wave |
| **Server-tool wave (Anthropic)** | Each item runs bounded web search, fetch or code execution server-side [AB8] → results enter KS capture/verification | Source discovery per research question; small computations per dataset |
| **Evaluator-Optimizer in waves** | Produce wave → judge wave against the rubric → refine only failing items | Course lesson drafts in AI Engineer; summary quality loops |
| **Embedding builds (OpenAI)** | `/v1/embeddings` batch, 50k inputs per batch [OB6] | Re-embedding a KS index after a model change |
| **Maintenance refresh** | A scheduled mission re-runs a pinned template on changed or aged items only | The selective maintenance policies of 10-16 §4: nightly literature delta, monthly re-verification |
| **Evaluation sweeps** | Labeled eval set × candidate prompts and models in one batch → scoring executor | Qualifying a new model before promoting a capability release |

A typical batch-wave ingestion mission:

~~~text
discover(stage, batch, server web_search)  ─┐
                                           ├─> dedupe(det) ─> extract(batch, sonnet) ─> schema+agreement(det)
seed_sources(det) ──────────────────────────┘                     │ nonblocking ticket
                                                                   ├─> triage_low_conf(batch, haiku→opus cascade)
build_report_skeleton(agent, sync)  <── runs while extract sleeps   └─> verify(batch, 2 judges) ─> KS admission(det) ─> report(agent)
~~~

**Batch Pool (phase 3).** Within one tenant scope, compatible items from many missions (same provider, endpoint, model, data class, retention and deadline class) can be coalesced into shared batches. That fills batches better, improves cache sharing and reduces create calls. Each item keeps its owning activation, so cancellation fences only that owner's items, and charges are allocated by measured per-item usage. Cross-tenant pooling is excluded, as in 10-16 §6.1.

## 7. Granular access and activation

### 7.1 Layers

| Layer | Controls | Default |
| --- | --- | --- |
| **Installation** | `provider_batch.enabled`; providers enabled; account refs (Secret Broker) mapped to a **dedicated Anthropic workspace and OpenAI project** for batch; observer on/off; webhook endpoint registration; global kill switch (`drain`: stop submits, keep observing and collecting) | Off |
| **Provider account** | Allowed endpoints and models; queue-headroom reserve; daily and monthly spend ceilings; retention/expiry defaults; data residency | Conservative |
| **Application / tenant grant** | Capabilities granted (e.g. `anthropic.messages.batch.claude-haiku-5-5`, `openai.responses.batch.gpt-6.1-sol`, `openai.embeddings.batch.*`); server-tool allowlist (web search costs per call); maximum items per set; maximum in-flight sets; data classes; pooling allowed | None granted |
| **Capability release** | Provider + product + endpoint + model + mode (capability-key rule in the [10-16 evidence register](MISSION-CONTROL-NEXT-STAGE-EVIDENCE-2026-10-16.md)), with qualification state `documented` → `probed` → `qualified`. Unverified features (OB8, AB11) stay unusable until probed. | Documented only |
| **Mission / node** | Environment overlay pins the capability; budget ceiling; deadline; dispatch mode | Inherit |
| **Actor / tool scope** | Read (capabilities, estimate, status, results), prepare (no spend), submit, cancel, repair, admin (observer, cleanup, kill switch). Submissions above a spend threshold, or the first use of a template, become a **Governed Effect**: prepare → Human Task review of the estimate → execute once. | Read and prepare |

### 7.2 Standalone module layout (proposed)

~~~text
platform/mission-control/packages/provider-batch/    # proposed; no mission_control imports
  provider_batch/
    envelope.py        # InferenceItem, InferenceSet, ItemResult, Usage, Disposition (pydantic)
    adapters/openai.py      # files + batches + webhook event schema (httpx)
    adapters/anthropic.py   # messages/batches (+ beta endpoint) (httpx)
    shard.py  ids.py        # sharding by provider limits; custom_id scheme
    estimate.py  catalog/   # price & limits catalog, versioned, from provider knowledge
    journal.py              # submission journal + ambiguous-create reconciliation
    observer.py  collect.py # list-based observation; JSONL streaming capture + join
    store/ sqlite.py  port.py   # store port; Mission Control supplies a Postgres implementation
    cli.py                  # `batchctl estimate|prepare|submit|status|wait|results|cancel|repair`
  tests/                    # MockTransport fixtures per provider
~~~

Mission Control's adapter wraps the library: Temporal Activities, the Postgres store, the ledger, Provider Wake and Artifact registration. The Knowledge Services (TypeScript) MCP and executors call it through the Mission Control API or the batch MCP rather than reimplementing it. If a KS-native client is later justified, it should consume the same knowledge/catalog file and envelope JSON Schema.

Placement is open (§11, Q1). Mission Control owns provider lanes and shared orchestration under the BellLabs ownership table, which is why the library is proposed there as a separately versioned package.

## 8. MCP server and agent interface

### 8.1 Tools

The same tool contract works in standalone mode (SQLite, tenant-scoped API key) and inside Mission Control, where the tools are mounted on the operator MCP with application, mission and run scope and authority comes from grants.

| Tool | Scope | Purpose |
| --- | --- | --- |
| `batch_capabilities` | read | Providers, endpoints, models, limits, prices, qualification state and the `verified_at` date of each fact |
| `batch_estimate` | read | Items (or a template plus a sample and count) → tokens, cost for batch / flex / sync, shards, expected latency, cache assumptions |
| `batch_prepare` | prepare | Items from an artifact or inline sample, plus a template → sealed Inference Set (`set_id`, digest, plan). No spend. |
| `batch_probe` | submit (small) | Run 1–3 items synchronously or as a one-item batch to validate shape and warm the cache |
| `batch_submit` | submit | `set_id`, `idempotency_key` and a budget ref → `dispatched`, or `approval_required` with a Human Task ID |
| `batch_status` | read | Normalized and native status per set and per batch, item counts by disposition, next observation time |
| `batch_wait` | read | Long-poll until the status changes or the timeout passes (mirrors inbox wait channels), so agents don't write polling loops |
| `batch_results` | read | Paged item results filtered by disposition, or an artifact reference. Never returns 100k rows inline. Includes the schema-validation outcome. |
| `batch_cancel` | cancel | Fence plus native cancel; returns what was already captured or billed |
| `batch_repair` | submit | Linked repair set for selected dispositions |
| `batch_list` | read | Sets by owner, mission, status or age |

Resources: `batch://capabilities`, `batch://pricing/{catalog_version}`, `batch://sets/{id}/plan`, `batch://sets/{id}/results.jsonl` (artifact-backed).

### 8.2 Interface rules for agents

- **Estimate before submit.** Submit refuses a set whose estimate is stale (older than its catalog version) or that was never estimated.
- **Bind results to keys, not prompts.** Agents read results by item key and disposition and never assume order.
- **Treat results as data.** Results are wrapped as untrusted content, especially server-tool outputs.
- **Wait without polling.** An agent that needs results calls `batch_wait` or ends its turn with a ticket. Inside a mission, the program waits; agents do not.
- **Respect the 24-hour reality.** The interface shows typical and worst-case latency, so a chat agent is not tempted to block a user on a batch.

## 9. The `provider-inference` skill and living provider knowledge

### 9.1 Skill shape

A single skill avoids competing triggers when direct APIs arrive. It lives with the module and follows the existing `mc.skill_bundle.v1` manifest and digest pins.

~~~text
skills/provider-inference/
  SKILL.md                       # router: choose mode (batch/flex/sync/background), compose patterns, invariants
  manifest.json                  # digests, operation catalog digest, knowledge digest
  references/
    choose-mode.md               # decision table: items, deadline, interactivity, data class, cost
    batch/authoring.md           # templates, custom_id, cache-prefix layout, structured outputs, probes
    batch/mission-patterns.md    # §4.3 wait strategies + §6 wave patterns with manifest snippets
    batch/operations.md          # MCP/CLI ops, failure handling, repair, cancel
    providers/anthropic.md       # human-readable, generated from knowledge.json + curated notes
    providers/openai.md
    knowledge.json               # machine-readable facts (below)
    operations.json              # tool/CLI catalog
  # later: references/direct/*, references/server-tools/*, references/hosted-agents/*
~~~

The SKILL.md route table covers four cases:

| Need | Route |
| --- | --- |
| "Run X over many items" | estimate → prepare → probe → submit → wait/collect |
| "Make a mission that does X at scale" | pick a pattern from `batch/mission-patterns.md` and compose with `mission-control-compose` |
| "Which provider or model, and how much?" | `batch_capabilities` / `batch_estimate`, never memory |
| "Can batch do Y?" | `knowledge.json`, honoring `label` and `verified_at` |

Invariants: never answer prices or limits from memory; unverified features need a probe; batch is never used for PHI; provider terminal is not acceptance.

Knowledge Services and domain skills (`mc-cognition-ingest`, KS `knowledge-ingest`) link to it instead of duplicating provider facts.

### 9.2 `knowledge.json` fact model

~~~json
{
  "schema": "provider_knowledge.v1",
  "catalog_version": "2026-10-18.1",
  "facts": [
    {"id": "anthropic.batch.max_requests", "value": 100000, "unit": "requests",
     "label": "documented", "verified_at": "2026-10-18", "source": "https://platform.claude.com/docs/en/build-with-claude/batch-processing",
     "evidence_ref": "AB4", "stale_after_days": 30},
    {"id": "openai.batch.responses.hosted_tools", "value": null,
     "label": "unverified", "verified_at": "2026-10-18", "probe": "probe.openai.responses_batch_web_search"}
  ],
  "prices": [{"provider": "anthropic", "model": "claude-sonnet-5-5", "mode": "batch",
              "input_per_mtok": 1.0, "output_per_mtok": 5.0, "effective_from": "2026-10-18", "evidence_ref": "AB13"}]
}
~~~

The estimator, `batch_capabilities` and the provider pages are all generated from this one file. Admission rejects a capability that is `unverified`. Estimates using a fact past `stale_after_days` carry a staleness warning.

### 9.3 Recurring knowledge refresh, as a Mission Control maintenance mission

1. **Trigger.** A weekly schedule, plus a change monitor on the canonical pages: batch guides, API references, pricing, rate limits, webhooks, data retention, and changelogs/release notes for both providers. A changelog hit triggers an immediate run.
2. **Capture.** Fetch the pages and store digest snapshots as Artifacts. Unchanged digests end the run cheaply.
3. **Extract.** For changed pages, a **batch** extraction (structured output into the `knowledge.json` fact schema) with two-model agreement. The mission dogfoods the feature it documents.
4. **Validate deterministically.** Schema checks; price sanity (no unexplained change over 3×, units consistent); limit monotonicity warnings; diffs against prior facts; conflicts recorded explicitly (e.g. OB10).
5. **Probe.** For facts that change behavior, or `unverified` facts with a probe defined, run a tiny live qualification batch under a small fixed budget, e.g. one Responses-batch line using `web_search`. Probes promote facts from `documented` to `qualified`.
6. **Review.** A Human Gate shows the diff, evidence and probe receipts.
7. **Publish.** Release a new skill bundle version and price catalog version. The capability releases referencing changed facts are re-evaluated. Running Inference Sets keep their pinned catalog version and are never silently re-priced or re-routed (10-16 §3.2 promotion law).
8. **Quarterly drill.** Run the full live qualification suite: one tiny batch per granted capability, covering the submit → wake → collect → settle → cleanup path on each provider.

## 10. Phased delivery and acceptance

| Phase | Scope | Acceptance |
| --- | --- | --- |
| **P0 Standalone core** | Envelope, both adapters, sharding/IDs, estimator with catalog v1, journal, SQLite store, list-based observer, collect/join, CLI | MockTransport suites for every native status and failure row; one live tiny batch per provider settles end to end; ambiguous-create drill (kill after create) adopts or parks and never duplicates |
| **P1 Agent interface** | MCP server (standalone), `provider-inference` skill v0 with `knowledge.json`, probes defined | An agent completes estimate → prepare → probe → submit → wait → results without polling loops; the above-threshold submit produces an approval task |
| **P2 Mission Control integration** | Inference Executor (`dispatch: batch`), inference binding, `batch_collect` control, Batch Observer schedule, OpenAI batch webhook catalog in ingress, artifact custody, ledger settlement, data-class gate, cleanup receipts | The race table of 10-16 §11.4 passes for batch; a submit-and-continue mission sleeps with zero worker slots and resumes on the wake; per-shard release; repair sets; cancellation fences late items; usage is never zero by omission |
| **P3 Waves and pooling** | Batch-wave pattern library, batch-stepped Goal Loop, cascade, multi-judge, Batch Pool within a tenant, knowledge-refresh mission live | A 10k-item ingestion slice costs ≤55% of the sync baseline at equal acceptance; pool cancellation affects only the owning activation |
| **P4 Direct API blend** | `sync`, `flex` and `background` dispatch modes on the same envelope; server-tool and hosted-agent references in the skill | One template runs unchanged in all four modes; the route choice is recorded and explained |

## 11. Open decisions

1. **Placement of the standalone library.** Options are a package inside `platform/mission-control` (recommended: one owner, Python, close to the seams) or a new platform repository. Placing it in Knowledge Services would mean TypeScript and duplicate durable state, so it is not recommended.
2. **Inference Executor as a new Behavior versus Agent Executor with a `direct_model` lane.** This proposal recommends a new executor behavior, because batch lacks the harness controls a lane must describe. It needs a contract review and an ADR once the Run 2 ADR range is settled.
3. **Anthropic ambiguous-create policy.** The choice is between parking (safe and slow) and adopting a unique fingerprint match. A dedicated workspace is a prerequisite either way. Ask Anthropic whether an idempotency key or metadata field is planned.
4. **OpenAI hosted tools inside batch (OB8) and Anthropic Skills inside batch (AB11).** Probe both before any pattern depends on them.
5. **Default shard size.** Smaller shards release earlier and recover more cheaply but cost more create calls and fill caches less. Proposed starting point: 2,000 items, tuned from observed latency.
6. **Webhook signature secret custody** for the OpenAI project endpoint, and whether the existing provider route needs a per-product event catalog version.
7. **Cost reconciliation authority.** Whether the Admin API keys exist, and who may hold them (Secret Broker scope).
8. **Data-class policy for `confidential`** under batch retention, especially for Biotech partner data.
