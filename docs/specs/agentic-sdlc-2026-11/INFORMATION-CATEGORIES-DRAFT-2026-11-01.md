---
type: Working Draft
title: "Information categories: the nine categories and the initial concept set per codebase"
description: "Working draft for owner feedback (AS-D2, 2026-11-01): the nine mandatory information categories, their frontmatter value, the question each answers, and for each codebase (Mission Control, Knowledge Services, AI Engineer, Biotech Knowledge Services) the concepts that should exist in that category, which existing documents fold into them, and whether the category is covered, partial, missing or not applicable today."
tags: [mission-control, agents, process, documentation, sdlc, categories]
date: 2026-11-01
status: draft
---

# Information categories and the initial concept set

Accepted in sitting I (AS-D2): every repository covers nine categories with at least one concept
each or an explicit `not applicable` line in its knowledge index. This draft proposes the initial
concepts. Statuses are from the live `sprint-oc` checkouts on 2026-11-01: **covered** (a concept
exists and cites source), **partial** (the facts exist in architecture or plan documents but not as
a concept), **missing** (nothing authored), **n/a** (the category does not apply and the index says
so).

## The nine categories

| # | `category:` value | The question it answers | Concept shape |
| --- | --- | --- | --- |
| 1 | `boundaries` | What does this service own, what does it refuse, who are its neighbours? | One concept per service; cites the AGENTS.md invariants and the boundary ADR |
| 2 | `surfaces` | How is it called: HTTP, MCP, CLI, skills, client packages? | One concept per transport family; cites handlers, capability files, skill descriptions |
| 3 | `domain-model` | What are the things, their states and lifecycle? | One concept per aggregate or lifecycle; cites GLOSSARY terms and state code |
| 4 | `persistence` | Where is state kept, who owns the schema, how does it migrate? | One concept per store; cites the contract repo, migrations, pins |
| 5 | `execution` | How does work run, retry, recover, stop? | One concept per execution mechanism; cites workers, leases, fences |
| 6 | `qualification` | How do we know it works: tests, fixtures, evaluations, release gates? | One concept per gate family; cites suites, fixtures, benchmarks |
| 7 | `operations` | How is it run, configured, deployed, observed, repaired? | One concept per runbook family; cites compose files, env kits, scripts |
| 8 | `decisions` | What is decided, what is open, where is the reasoning? | One index concept routing to ADRs and open decision maps |
| 9 | `goals` | What is this for, which product surfaces and research programs does it serve? | One charter concept per domain; cites the owner directive and product docs |

Every concept carries `category:` (one value), `type:` (Concept), `title`, `description`, `tags`,
`aliases` and `questions` (the fields the KS retrieval fixtures already use), a 160-line cap and a
Citations section. The index block groups concepts by category in this order.

## Mission Control (`platform/mission-control`, 66 concepts today)

| Category | Initial concepts (existing file in `docs/knowledge/` unless noted) | Status |
| --- | --- | --- |
| boundaries | `architecture.md`, `knowledge-services.md`, `provider-lanes.md`, `interfaces.md` | covered; add `category:` |
| surfaces | `interfaces.md` (HTTP), `capabilities.md`, `agent-configuration.md`; **new** `coordinator-surface.md` (missionctl, the `mission-control` skill router, MCP) folded from the coordinator-surface proposal | partial: skill and CLI surface is in a proposal, not a concept |
| domain-model | `mission-manifest.md`, `lifecycle.md`, `revisions.md`, `mission-chains.md`, `completion.md`, `output-contracts.md`, `human-gates.md`, `interventions.md` | covered |
| persistence | `persistence.md`, `collections-and-current-sets.md`, `workspace-closure.md`, `saved-result-settlement.md`; **new** `database-component.md` (the common database component, release numbering, who consumes it: AI Engineer and Biotech contracts) | partial: component ownership is spread across sprint docs |
| execution | `execution.md`, `durable-controls.md`, `durable-reactions.md`, `recovery.md`, `async-children.md`, `wake-channels.md`, `watchers.md`, `deep-agents-lane.md`, `deep-agents-turn-stops.md`, `parallel-swarm.md` | covered |
| qualification | `qualification.md`, `release-and-qualification.md`, `evaluator-attempts.md`, `trusted-judgment.md`; **new** `documentation-retrieval-fixtures.md` once the fixtures exist | covered; fixtures missing |
| operations | `operations.md`, `environments.md`, `environment-preparation.md`, `secret-broker.md`, `budgets-and-usage.md`, `owner-prerequisites.md`; fold `docs/WSL2_WORKER_RUNBOOK.md` and `docs/DEVELOPMENT.md` pointers | covered |
| decisions | **new** `decisions.md`: routes to `docs/adr/` 0001-0063, the Sprint OC DECISIONS.md, open D1-D9, the answers files | missing as a concept (the material exists) |
| goals | **new** `goals.md`: the owner directive (Deep Agents first), the four-domain product surfaces (skills + CLI, MCP, APIs, web and mobile), the recurring research programs; cites `AGENTS.md` and `docs/BELLLABS-SEQUENCE.md` | missing |

## Knowledge Services (`platform/knowledge-services`, 11 concepts today in `knowledge/`)

| Category | Initial concepts (existing file in `knowledge/` unless noted) | Status |
| --- | --- | --- |
| boundaries | `service-boundaries.md` | covered |
| surfaces | `execution-profiles-and-transports.md` (HTTP, MCP, CLI, workers), `agent-skills-and-consumer-readiness.md` | covered |
| domain-model | `capture-conversion-and-custody.md`, `preparation-and-publication.md`, `retrieval-and-evidence.md`; **new** `knowledge-operation.md` (operation, intent, read observation, the K01 protocol) folded from the OVE-204 provenance work | partial |
| persistence | `schema-read-and-ingestion.md`; **new** `schema-ownership.md` (ai-engineer-db-contract pin, `knowledge_service` schema, the common-component cutover from ADR 0008) | partial |
| execution | `durable-execution-and-recovery.md`, `jev-decisions-and-workers.md` | covered |
| qualification | `evaluation-and-publication-gates.md`, `verification-and-admission.md`; **new** `retrieval-benchmark.md` (the frozen fixture, recall@3, MRR, critical cases) | partial: the benchmark is documented only in a fixture README |
| operations | fold `docs/operations/runbooks.md`, `agent-maintenance.md`, `code-quality-and-delivery-process.md` into **new** `operations.md` | partial |
| decisions | **new** `decisions.md`: routes to `docs/architecture/0001-0015`, the specification decision logs, the BellLabs Knowledge Platform Linear project | missing as a concept |
| goals | **new** `goals.md`: shared foundation for AI Engineer and Biotech retrieval, verification and evidence; the research-report pipeline it must supply | missing |

## AI Engineer (`aiengineer/`, five repositories, no knowledge bundle today)

The domain gets one bundle per repository that has behaviour, and one domain-level charter in
`ai-engineer-meta`. Smaller repositories cover a category with one short concept or `n/a`.

| Category | `ai-engineer-db-contract` | `research_starter_pre_research_agent` | `agents_dashboard` | `ai-engineer-industry-cloud-automated-research` | `ai-engineer-meta` |
| --- | --- | --- | --- | --- | --- |
| boundaries | **new** from the generated guide rules (schema authority, no second migration authority) | **new** (intake and packet pipeline; not Mission Control) | **new** (proof UI over the ledger; dashboard overlap with MC is open) | **new** (cloud research environment; reconcile with MC) | **new** domain charter: what AI Engineer is, which repos exist, which are absent (learner app) |
| surfaces | type-only package, SQL `api` schema | HTTP routes, CLI, Apify intake | Next.js route handlers | `research-cloud.mjs`, research intents | n/a (documentation only) |
| domain-model | fold `docs/knowledge-model/SCHEMA-SUMMARY.md` | packet stages, intents, deterministic apply | n/a (reads the ledger) | entity taxonomy (`ENTITY_TAXONOMY.md`) | the glossary (renamed per AS-D3) |
| persistence | migrations, generated types, the disposable-reset guard, the common-component relationship | pre-research Postgres ledger, Supabase storage | n/a | contract projections | n/a |
| execution | n/a | pipeline controller, v2 stages, completion rule | n/a | mission procedures, pinned tools | n/a |
| qualification | contract CI, `workspace:validate` | packet verification, fixture proofs (StageGraph fixtures 2026-10-31) | n/a | n/a | generator tests (44) |
| operations | `install-ai-engineer.mjs`, disposable tools | run, apply, recover | run locally | cloud operating context | the documentation build |
| decisions | routes to `ai-engineer-meta/ai-engineer-architecture/adr/` | same | same | same | the five ADRs; the open RESPONSIBILITIES.md items |
| goals | n/a (points to meta) | n/a | n/a | n/a | **new** `goals.md`: product intent (`docs/product/00-vision.md`, `11-north-star-path.md`), agent skills + CLI, MCP, APIs, web and mobile apps for software and agent engineering, the recurring research reports |

## Biotech Knowledge Services (`biotech/biotech-knowledge-services`, no bundle today)

| Category | Initial concepts (folded from) | Status |
| --- | --- | --- |
| boundaries | **new** from `docs/NAVIGATION.md` and ADR 0004/0005 (domain graph service; not shared KS; not MC) | partial |
| surfaces | **new** `surfaces.md`: executor HTTP and MCP with the capability catalog, consumer GraphQL API, product BFF, Python client, the four first-party skills | partial |
| domain-model | **new** `schema-releases.md`: node and relationship types, the release source tree, the pin, the sidecar authority, intent v2 artifacts (ADR 0003) | partial |
| persistence | **new** `graph-and-postgres.md`: Neo4j graph (biotech-graph), the Biotech PostgreSQL consumer of the common MC component (`biotech-postgres-db-contract`, not yet a repository) | partial |
| execution | **new** `ingestion-and-admission.md`: plan, apply, admission, run identity with Mission Control (ADR 0004) | partial |
| qualification | **new** `evals-and-verify.md`: `evals/`, `workspace:verify`, release digest verification | partial |
| operations | fold `docs/deployment/executor.md`, `graphql-api.md` | partial |
| decisions | **new** `decisions.md`: ADRs 0001-0005, SV-D10, the schema v2 release record | missing as a concept |
| goals | **new** `goals.md`: diagnostics and the biotech product surfaces, the recurring research programs (curing conditions, longevity protocols and treatments, longevity-purposed machines, developing-economy research) with human-collaborated evidence reports; cites `biotech/BellLabs/index.md` | missing |

## Out of the matrix

`biotech-knowledge-catalog` is the owner's hand-authored OKF vault; it keeps its own validator and
is not a service bundle. `biotech/BellLabs` is authored product vision, cited by the goals concepts,
not a bundle. `becoming-master-ai-engineer` and `internal/` folders are local material.

## Open for owner feedback

1. Whether the two AI Engineer research repositories (`agents_dashboard`, `industry-cloud`) get a
   bundle now or only a boundaries concept plus `n/a` lines until their reconciliation with
   Mission Control is decided.
2. Whether `goals` is one concept per domain (recommended) or one per repository.
3. Whether `biotech-postgres-db-contract` becomes a repository in this program so it can carry a
   bundle.
