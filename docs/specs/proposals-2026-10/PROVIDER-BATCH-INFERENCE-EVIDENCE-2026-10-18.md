---
type: Evidence Register
title: "Provider batch inference evidence register (2026-10-18)"
description: "What the official Anthropic and OpenAI batch documentation said on 2026-10-18, each row labelled documented, inferred, unverified or conflict, with its source URL; the source of docs/research/provider-batch/batch-apis.md."
tags: [mission-control, evidence, provider-batch, anthropic, openai, batch]
status: open
date: 2026-10-18
---

# Provider batch inference evidence register

Date: **2026-10-18 UTC**. Companion to the [batch inference proposal](PROVIDER-BATCH-INFERENCE-PROPOSAL-2026-10-18.md). This register records what official vendor documentation said when it was opened on 2026-10-18. It is **documented** evidence, not tested account access. Labels:

- **Documented**: stated on an official page.
- **Inferred**: follows from the official request schema, but no guide states it.
- **Unverified**: no official source found either way. Treat it as unknown, not as unsupported.
- **Conflict**: official sources disagree.

Every row is a candidate fact for the machine-readable knowledge file proposed in §9 of the proposal. Each fact keeps its source URL and verification date.

## Anthropic Message Batches

| ID | Fact | Label | Source |
| --- | --- | --- | --- |
| AB1 | `POST /v1/messages/batches` takes 1–100,000 `{custom_id, params}` requests. Other endpoints: retrieve, list (newest first, `after_id`/`before_id`, `limit` 1–1000), cancel, delete (only after the batch has ended) and results (streamed JSONL, also exposed as `results_url`). | Documented | [batch guide](https://platform.claude.com/docs/en/build-with-claude/batch-processing), [API create](https://platform.claude.com/docs/en/api/messages/batches/create) |
| AB2 | `processing_status` is `in_progress`, `canceling` or `ended`. `request_counts` has `processing`, `succeeded`, `errored`, `canceled` and `expired`. The non-processing counts stay at 0 until the whole batch ends. | Documented | API retrieve |
| AB3 | Result types are `succeeded`, `errored`, `canceled` and `expired`. Only `succeeded` is billed. Results come back in any order, so join them on `custom_id`. | Documented | batch guide |
| AB4 | Limits: 100,000 requests or 256 MB, whichever comes first (413 when exceeded). `custom_id` must match `^[a-zA-Z0-9_-]{1,64}$` and be unique within the batch. Batches expire 24 h after creation and most finish in under an hour. | Documented | batch guide, API create |
| AB5 | Results remain available for **29 days from `created_at`**. `archived_at` marks when they stop being available. Batches cannot be edited after submission. | Documented | batch guide |
| AB6 | Requests are validated asynchronously. Errors appear only after the batch ends. The guide advises testing one request shape on `/v1/messages` first. | Documented | batch guide |
| AB7 | Batch rate limits are shared across models and separate from Messages limits. Requests per minute: Start 1,000, Build 2,000, Scale 4,000. Queue capacity: 200k, 300k and 500k requests respectively. A batch can slightly overshoot a workspace spend limit. | Documented | [rate limits](https://platform.claude.com/docs/en/api/rate-limits#message-batches-api) |
| AB8 | Supported inside a batch: vision, tool use, server tools (web search, web fetch, code execution, MCP connector, advisor, tool search), multi-turn content, extended thinking and most beta features. Server tools run their loop server-side and may need more iterations before returning `pause_turn`. Web search is throttled per organization and retried automatically. | Documented | batch guide |
| AB9 | Rejected inside a batch: `stream`, `speed` (fast mode) and `max_tokens: 0`. | Documented | batch guide |
| AB10 | Structured outputs, citations/PDF, Files API `file_id`, `inference_geo` and `container` are accepted by the batch `params` schema. Beta features such as `mcp_servers`, `context_management` and `fallbacks` need the beta batch endpoint. Beta headers apply to the whole batch, not per request. | Inferred | [beta create](https://platform.claude.com/docs/en/api/beta/messages/batches/create) |
| AB11 | Agent Skills (container skills) working end to end inside a batch. | Unverified | none |
| AB12 | Batch pricing is 50% of standard on all tokens. It stacks with the prompt-caching multipliers and with the 1.1× `inference_geo: "us"` charge. | Documented | [pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| AB13 | Batch prices per million tokens (input / output): `claude-fable-5-1` 5 / 25; `claude-opus-5-5` 2 / 10; `claude-opus-5` 2.50 / 12.50; `claude-sonnet-5-5` and `claude-sonnet-5` 1 / 5; `claude-haiku-5-5` 0.05 / 0.25 for prompts up to 100k tokens and 0.25 / 1.25 above that. | Documented | pricing |
| AB14 | Prompt caching works inside batches on a best-effort basis (typically a 30–98% hit rate). The guide recommends the 1 h TTL with identical `cache_control` blocks in every request, optionally warmed with a single-request batch first. | Documented | batch guide, [prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) |
| AB15 | Code execution costs the same as outside a batch. Whether the $10 per 1,000 web-search fee is discounted inside a batch was not found. | Documented / Unverified | pricing |
| AB16 | **No official Message Batch webhooks exist.** The official webhook catalog covers only Managed Agents resources. One third-party blog claims batch webhooks exist; that claim is rejected. The documented way to get completion is polling. | Documented absence of events in catalog | [Managed Agents webhooks](https://platform.claude.com/docs/en/managed-agents/webhooks) |
| AB17 | The batch object has **no client metadata field**, and no create idempotency key is documented. | Inferred from schema | API create |
| AB18 | Batches belong to the workspace they were created in. `anthropic-workspace-id` selects a workspace for multi-workspace keys. | Documented | [workspaces](https://platform.claude.com/docs/en/manage-claude/workspaces#api-keys-and-resource-scoping) |
| AB19 | The usage report (`/v1/organizations/usage_report/messages`) filters and groups by `service_tiers[]=batch`, model, workspace, key and `inference_geo`. The daily cost report has a `service_tier` value on description-grouped rows. Both require an Admin API key. | Documented | [usage and cost API](https://platform.claude.com/docs/en/manage-claude/usage-cost-api) |
| AB20 | **Batch is not ZDR- or HIPAA-eligible** because of the 29-day retention. ZDR organizations are not blocked, but batch data falls outside ZDR. HIPAA batch requests are rejected with 400. `DELETE` removes a batch early. | Documented | [data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention) |
| AB21 | A batch-only beta header, `output-300k-2026-03-24`, raises `max_tokens` to 300k on the current 5.5-generation models. | Documented | batch guide |
| AB22 | Managed Agents sessions have no batch mode. | Documented | pricing |
| AB23 | Claude Platform on AWS supports Message Batches. Bedrock and Vertex have their own batch-job APIs; current-model coverage and discounts were not verified. Foundry does not support Message Batches. | Mixed | [Vertex Claude batch](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/claude/batch), [Bedrock batch](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference.html) |

## OpenAI Batch

| ID | Fact | Label | Source |
| --- | --- | --- | --- |
| OB1 | Flow: upload JSONL with `POST /v1/files` (`purpose=batch`), call `POST /v1/batches`, then retrieve, list (`limit`/`after`) and cancel. | Documented | [batch guide](https://developers.openai.com/api/docs/guides/batch), [API reference](https://developers.openai.com/api/reference/resources/batches) |
| OB2 | Status values: `validating`, `failed`, `in_progress`, `finalizing`, `completed`, `expired`, `cancelling` (up to about 10 min), `cancelled`. | Documented | API reference |
| OB3 | Batch object fields: `request_counts {total, completed, failed}`, `output_file_id`, `error_file_id`, `errors.data[]`, timestamps, `usage` (input, cached, output, reasoning tokens; only on batches created after 2025-09-07) and `metadata` (up to 16 pairs; keys ≤64 characters, values ≤512). | Documented | API reference |
| OB4 | `completion_window` supports only `"24h"`. | Documented | API create |
| OB5 | Output expiry is set with `output_expires_after {anchor: created_at, seconds 3600–2592000}`. Files take `expires_after` in the same range. Batch files expire after 30 days by default. | Documented | API create |
| OB6 | Batchable endpoints: `/v1/responses`, `/v1/chat/completions`, `/v1/embeddings`, `/v1/completions`, `/v1/moderations`, `/v1/images/generations`, `/v1/images/edits` and `/v1/videos`. `/v1/videos` is still enumerated, but the Videos API and Sora were removed on 2026-09-24. One model per input file. Embedding batches are capped at 50,000 inputs. | Documented | API create, guide |
| OB7 | Supported inside a batch: Structured Outputs/JSON mode, image inputs, reasoning models and prompt caching (cached-input and cache-write prices are listed for Batch). Streaming is not supported. | Documented | guide, pricing |
| OB8 | Hosted tools inside a Responses batch line (web_search, file_search, code_interpreter, hosted shell, MCP, computer use), as well as `background`, `store`, `previous_response_id` and per-line `service_tier`. | **Unverified** | none |
| OB9 | Limits: 50,000 requests and 200 MB per batch, 2,000 batch creations per hour, and a per-model enqueued-input-token limit shown on the organization Limits page. Batch uses a rate-limit pool separate from synchronous calls. | Documented | guide |
| OB10 | The Help Center says there is "no limit" on requests per batch and gives a 1M enqueued-embedding cap. This contradicts OB9; the developer docs take precedence. | Conflict | [Batch FAQ](https://help.openai.com/en/articles/9197833-batch-api-faq) |
| OB11 | Batch is 50% of Standard for input, cached input, cache writes and output. The cached-input discount stacks with Batch for the gpt-5.x and gpt-6.x families. Prompts over 272K tokens are billed at 2× input and 1.5× output. Data residency adds 10%. | Documented | [pricing](https://developers.openai.com/api/docs/pricing) |
| OB12 | Batch prices per million tokens (input / cached / cache write / output): `gpt-6-astra` 5 / 0.50 / 6.25 / 25; `gpt-6.1-sol` 1 / 0.05 / 1.25 / 5; `gpt-6-luna` 0.05 / 0.005 / 0.0625 / 0.25; `gpt-5.6-terra` 1 / 0.10 / 1.25 / 6. | Documented | pricing |
| OB13 | **Flex** (`service_tier: "flex"`) is priced at Batch rates. It is synchronous but slow, beta, and limited to certain models on Responses/Chat. Capacity shortages return 429 with no charge. | Documented | pricing, flex guide |
| OB14 | **Background mode** runs at Standard price on Responses only. It can be polled, supports idempotent cancel and resumable streams, and emits `response.*` webhooks. | Documented | background guide |
| OB15 | Webhooks: `batch.completed`, `batch.failed`, `batch.expired` and `batch.cancelled`. The payload is thin (`data.id`). They are signed with Standard Webhooks headers (`webhook-id`, `webhook-timestamp`, `webhook-signature`), retried with backoff for up to 72 h, never follow redirects, and should be deduplicated on `webhook-id`. | Documented | [webhooks](https://developers.openai.com/api/docs/guides/webhooks) |
| OB16 | Input line: `{custom_id, method: "POST", url, body}`. Output line: `{id, custom_id, response: {status_code, request_id, body}, error}`. Output order may differ from input order. The maximum `custom_id` length was not found. | Documented / Unverified | guide |
| OB17 | On expiry or cancel, completed requests are returned and billed. Unfinished requests appear in the error file with `code: "batch_expired"`. | Documented | guide |
| OB18 | No create idempotency key is documented. `metadata` can carry a dispatch key that can be compared using list. | Inferred | API reference |
| OB19 | **ZDR does not apply** to `/v1/batches` or `/v1/files`. Inputs, outputs and intermediate files are kept under the Batch/File retention policy. Batch is not eligible for PHI private retention. Mitigation: short file expiry (at least 1 h) and deletion after download. | Documented | [your data](https://developers.openai.com/api/docs/guides/your-data), FAQ |
| OB20 | Reconciliation: Admin `GET /v1/organization/usage/completions` takes `batch=true` and `group_by=batch`. `GET /v1/organization/costs` has `line_item`/`project_id` grouping. Whether cost line items separate Batch spend was not verified. | Documented / Unverified | usage API |
| OB21 | No Agents SDK or Codex batch path is documented. A batched multi-turn loop must be orchestrated by the caller, one batch per turn. | Documented absence | guide |

## Consequences for design

1. **Both providers return results only when a batch ends** (AB2, OB1/OB17). Neither streams partial results, so finer-grained release needs smaller batches (shards).
2. **Results are joined by `custom_id`, never by order** (AB3, OB16). The Anthropic `custom_id` format is the binding constraint: 64 characters from `[A-Za-z0-9_-]`.
3. **Completion notification is asymmetric.** OpenAI has signed webhooks that plug into the existing Standard Webhooks ingress. Anthropic requires polling.
4. **Submission reconciliation is asymmetric.** OpenAI has `metadata` plus list. Anthropic has no metadata, so ambiguous-create recovery needs a dedicated workspace and fingerprint matching, or parking (AB17/AB18).
5. **Neither provider's batch is ZDR-eligible** (AB20, OB19). The data class must allow 29–30 days of provider retention. PHI is out of scope for batch by policy.
6. **Server-side tools are documented inside Anthropic batches** (AB8) **but unknown inside OpenAI batches** (OB8). A live qualification probe must settle OB8 before any mission relies on it.
7. **Batch and caching discounts stack on both providers for current models** (AB12, OB11). Estimators must still apply each provider's own multipliers in order rather than multiplying generic discounts.
