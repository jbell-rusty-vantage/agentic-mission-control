---
name: ai-engineer-knowledge-charter
description: The AI Engineer knowledge charter - what the proprietary AI-industry knowledge base holds, its 36 entity kinds and endpoint-typed relationship kinds, the taxonomy rule, the evidence bar and the intent-only write path. Use before researching, verifying or ingesting AI Engineer knowledge, when choosing an entity or relationship kind, or when an aieng_ingest preview refuses.
---

# AI Engineer knowledge charter

AI Engineer is a learning and building company whose users leave engineer-ready or
entrepreneur-ready. Its official knowledge comes from the research and ingestion flywheel into a
proprietary knowledge base of the AI industry: who builds what, on which models, protocols,
libraries and papers, with which evidence. Every row answers "who said this, where, at which
version, and how well is it supported".

The knowledge base is the AI Engineer Postgres database, schema `corpus.*` (entities) beside the
evidence and ranking schemas, at contract 0.5.0. You author intents; the knowledge executor
writes.

## Charter: what belongs in the knowledge base

The 36 entity kinds (`taxonomy.entity_kind`), each a canonical `corpus.<kind>` table:

| Area | Kinds |
| --- | --- |
| Actors | `organization`, `person` |
| Products | `product`, `product_version`, `product_feature`, `model_offering`, `compute_offering`, `compute_device` |
| Models | `ai_model`, `ai_model_version` |
| Protocols | `ai_protocol`, `ai_protocol_version`, `ai_protocol_feature` |
| Software | `library`, `library_release`, `repository`, `mcp_server`, `agent_skill`, `registry`, `security_advisory` |
| Research | `paper`, `technique`, `concept`, `dataset`, `benchmark`, `benchmark_run` |
| Market | `funding_round`, `corporate_transaction`, `case_study`, `story` |
| Media and events | `media_channel`, `media_series`, `media_work`, `talk`, `industry_event`, `event_series` |

Taxonomy rule: primary types are tables; a secondary division (agent framework versus inference
runtime, research lab versus commercial company) is a term in the single-valued `entity_subtype`
facet; orthogonal properties (domain, modality, access, deployment, lifecycle, maturity, sector)
are independent, multi-valued facets. MCP and A2A are protocols (`ai_protocol`), not products.

Ingest an organization separately from its product families, products, versions and features;
size changes row count, never ontology.

Relationships are the 65 `taxonomy.relationship_kind` rows. Each constrains its endpoint kinds
and some are temporal. The families you will use most:

| Family | Kinds |
| --- | --- |
| Building and selling | `develops`, `maintains`, `vends`, `operates`, `distributes`, `offered_by`, `offered_as` |
| Versions and lineage | `version_of`, `supersedes`, `variant_of`, `depends_on`, `built_on_model`, `derived_from_model`, `trained_on` |
| Techniques and protocols | `implements_protocol`, `implements_technique`, `introduces_technique`, `uses_technique` |
| Research | `cites`, `authored_by`, `benchmark_subject`, `evaluated_on`, `benchmark_uses_dataset` |
| People and money | `employed_by`, `founded`, `investor_in`, `participates_in_round`, `recipient_of_round`, `party_to_transaction` |

Read `relationship_kinds` for the exact endpoint kinds and temporal flag before asserting any of
them.

## 1. Plan the capture

Before acquiring sources, name each intended subject with its entity kind and each relationship
with its kind. Done when every planned relationship's endpoints match that kind's `from_kinds`
and `to_kinds`.

## 2. Acquire and verify evidence

Follow [references/research-procedure.md](references/research-procedure.md). Hold every fact to
the evidence standard:

- Identity comes from official catalogs, documentation, release pages or registries.
- Marketing capability and outcome language becomes claims assessed independently, never
  accepted fact.
- Pin repository facts to a 40-hex commit, papers to an exact arXiv version, releases to a
  version and date.
- Distinguish vendor self-reports from independent evaluation, a release from the default
  branch, documented from source behavior, and preprints from peer review.
- A benchmark number is a `ranking.metric_observation` (with its denominator and date), never a
  column on a join.

## 3. Author the intent and ingest

Follow [references/ingestion-guide.md](references/ingestion-guide.md) step by step: resolve,
reuse, select only `full_support` assertions, author subjects and proposals citing their
`claimId`s, preview, repair, apply the identical previewed input. A new subject carries its
kind's NOT NULL typed payload columns. Done when `aieng_ingest` apply returns a receipt and the
host's row readback.

## 4. Proof of ingestion

Canonical facts are written only by `executor_service` (`temporal.begin_batch` to
`temporal.assert_*` to `temporal.commit_batch`) and only via a receipt. Ingestion is proven by
exact-use admission, that receipt and row readback together; a preview or `verify_evidence`
result is evaluation, not ingestion.

## Boundaries

- Writes go through `aieng_ingest` intents only; the executor alone touches tables.
- Evidence is a judged assertion; search and discovery listings stay discovery.
- Kinds and relationships come from the taxonomy tables; a missing kind is a contract change for
  `aiengineer/ai-engineer-db-contract`, outside a mission.
- Public sources and the tools your stage was given; credentials stay with the host.

## Navigation

- `aieng_schema(section='guide')` first; then `section='entity_kinds'`,
  `section='relationship_kinds'` and `section='relation', name='corpus/<kind>'` for a kind's
  typed columns.
- In the contract workspace (`aiengineer/ai-engineer-db-contract/workspace/START_HERE.md`):
  reach an operation in at most 4 reads; search before reading; read `schema-ir.json` and
  `search/index.json` only through `rg` or `jq`, never whole.

Sources: `aiengineer/ai-engineer-meta/docs/product/00-vision.md`,
`aiengineer/ai-engineer-db-contract/workspace/vocabularies/taxonomy.entity_kind.md`,
`aiengineer/ai-engineer-db-contract/workspace/vocabularies/taxonomy.relationship_kind.md`,
`aiengineer/ai-engineer-db-contract/workspace/START_HERE.md`,
`aiengineer/ai-engineer-industry-cloud-automated-research/ENTITY_TAXONOMY.md`.
