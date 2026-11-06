---
type: Research
title: Anthropic Message Batches and OpenAI Batch as of 2026-10-18
description: The documented limits, result handling, completion notice, retention and price facts of the two provider batch APIs that a Mission Control batch wait would rely on, distilled from the provider-batch evidence register. Documented, not tested against the owner's accounts.
tags: [mission-control, research, provider-batch, anthropic, openai, batch]
subject: Anthropic Message Batches API and OpenAI Batch API
versions: [Anthropic Message Batches (platform docs 2026-10-18), OpenAI Batch API (developers docs 2026-10-18), claude-sonnet-5-5 and gpt-6.1-sol price rows]
sources:
  - platform/PROVIDER-BATCH-INFERENCE-EVIDENCE-2026-10-18.md (workspace path, outside any git repository; 74 rows AB1-AB23, OB1-OB21)
  - platform/PROVIDER-BATCH-INFERENCE-PROPOSAL-2026-10-18.md (section 2.1 comparison table)
  - https://platform.claude.com/docs/en/build-with-claude/batch-processing
  - https://developers.openai.com/api/docs/guides/batch
observed: 2026-10-18
confidence: documented (official pages as opened that day); never run against an account here; AB11, AB15, OB8, OB10, OB16, OB20 are unverified or in conflict as marked
used_by: [provider-batch]
date: 2026-11-01
---

# Provider batch APIs

Labels follow the evidence register: **Documented** (official page), **Inferred** (follows from the schema), **Unverified**.

| Dimension | Anthropic Message Batches | OpenAI Batch |
| --- | --- | --- |
| Unit | one Messages request per item (`custom_id`, `params`) | one HTTP request line per item (`custom_id`, `method`, `url`, `body`) |
| Create | `POST /v1/messages/batches`, 1-100,000 items or 256 MB | upload JSONL (`purpose=batch`), `POST /v1/batches`, 50,000 items or 200 MB, 2,000 creates/h, one model per file |
| Endpoints | Messages | Responses, Chat, Embeddings, Completions, Moderations, Images |
| Deadline | expires 24 h after creation; most end under 1 h | `completion_window` only `"24h"` |
| Status | `in_progress`, `canceling`, `ended`; per-result counts stay 0 until the batch ends | `validating`, `in_progress`, `finalizing`, `completed`, `failed`, `expired`, `cancelling`, `cancelled` |
| Results | JSONL stream after `ended`; join on `custom_id`; available 29 days from creation | output and error files at terminal; join on `custom_id`; 30-day default expiry, configurable 1 h to 30 d |
| Partial results | none until the batch ends; only `succeeded` is billed | none until terminal; on expiry or cancel completed lines are returned and billed |
| Completion notice | **none**: no official batch webhooks, polling only | signed Standard Webhooks `batch.completed/failed/expired/cancelled`, thin payload (`data.id`), retried up to 72 h |
| Idempotency / metadata | none, none | no idempotency key; 16 metadata pairs |
| Streaming | not allowed | not allowed |
| Hosted tools | web search, web fetch, code execution, MCP connector run server-side (documented); Agent Skills unverified | hosted tools inside a Responses batch line **unverified** |
| Prompt caching | best effort, use 1 h TTL, warm with a one-item batch | supported, cached-input batch prices listed |
| Price | 50% of standard (stacks with caching); e.g. `claude-sonnet-5-5` 1 / 5 USD per million tokens | 50% of standard; e.g. `gpt-6.1-sol` 1 / 0.05 cached / 5 |
| Retention | **not ZDR or HIPAA eligible** (29-day retention); `DELETE` removes early; HIPAA batch requests get 400 | **ZDR does not apply** to `/v1/batches` or `/v1/files`; not eligible for PHI private retention |
| Spend reconciliation | Admin usage report `service_tiers[]=batch` | Admin usage `batch=true` |

Consequences recorded in the register: results arrive only when a batch ends, so finer release needs smaller batches (shards);
`custom_id` (Anthropic: `^[a-zA-Z0-9_-]{1,64}$`) is the join key; completion notice is asymmetric (OpenAI webhook, Anthropic polling); an
ambiguous create cannot be recovered the same way (OpenAI metadata plus list, Anthropic dedicated workspace plus fingerprint or parking);
neither batch may carry PHI; OpenAI Flex (`service_tier: "flex"`) costs the same as Batch without job overhead for small sets.

## Citations

- Register: `platform/PROVIDER-BATCH-INFERENCE-EVIDENCE-2026-10-18.md` and proposal `platform/PROVIDER-BATCH-INFERENCE-PROPOSAL-2026-10-18.md` (workspace root `platform/`, not inside a git repository as of 2026-11-01).
- Used by: [provider batch](../../knowledge/provider-batch.md).
