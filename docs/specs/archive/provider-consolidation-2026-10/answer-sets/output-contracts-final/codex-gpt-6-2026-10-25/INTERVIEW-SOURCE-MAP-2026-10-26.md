---
type: Source Map
title: "Verified interview and derivative map for final specification synthesis"
description: "Reading order, exact paths, decision ranges, derivative status, runtime gaps, tracker drafts, schema ownership and quality entrypoints for the final agent-team specification session."
tags: [mission-control, navigation, interview, specifications, handoff]
date: 2026-10-26
status: active
---

# Final synthesis source map

Workspace: `C:/Users/Pinda/Proyectos/BellLabs`.
Owning repository: `C:/Users/Pinda/Proyectos/BellLabs/platform/mission-control`.
All links below are resolved from this file. Read the [session instruction](FINAL-SPEC-AND-ISSUE-SYNTHESIS-HANDOFF-2026-10-26.md)
and [latest owner direction](OWNER-DIRECTION-AND-STRESS-FIXTURES-2026-10-26.md) first.

## 1. Four substantive answer records, in decision order

| Record | Exact source and decisions | Role/status |
| --- | --- | --- |
| IA-06 | [GPT 6 Astra output-contract answers](../../gpt-6-astra-2026-10-24/ANSWERS.md): OC-D27–78, 52 rows | Final accepted checkpoint, expressly revisable by later owner decisions. General outputs/guarantees, workflows, transfer, adoption, providers, application ownership. |
| IA-07 | [Application-boundary answers](../../application-knowledge-boundary/claude-fable-5-1-2026-10-24/ANSWERS.md): OC-D79–105, 27 rows | Final; not numerically sorted. Trusted origin, one output-submission act, storage/report ports, native bindings and provenance roles. OC-D83 revises old OC-D4/5. |
| IA-08 | [Sprint V answers](../../sprint-v/codex-gpt-6-2026-10-24/ANSWERS.md): SV-D1–14 | Final. Full refactor/disposable data, shared verification core, both domains, BKS schema authority, service versus workflow proof. SV-D13 accepted that specification/workspace. |
| IA-09 | [Current final-contract answers](ANSWERS.md): OC-D106–181 after this handoff | Open for conversion. Detailed output/current-set/transfer/workflow/hook/coordinator decisions; final capped answers through OC-D176, then new owner direction OC-D177–181. |

There are exactly four substantive `ANSWERS.md` files in the program at this audit. IA-01/02's old
logs are empty and IA-05 is planned; no completed `DEEP-AGENTS-SITTING-I-…-ANSWERS.md` was found.
Do not invent missing sessions or confuse proposal rows with additional owner interviews.

Earlier OC-D1–26 live in [the original output session §8](../../../specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md#8-decisions-for-the-owner-recommendation-marked),
not another answers file. Current [CONTRACTS §14](CONTRACTS.md#14-earlier-decision-dispositions)
dispositions them individually. The later source note [SESSION-ANSWERS](SESSION-ANSWERS-2026-10-26.md)
preserves the preceding resumed-chat wording, especially OC-D139–161; it is not the current decision register.

## 2. Every derivative in those answer directories

| Packet | Documents | How to use |
| --- | --- | --- |
| IA-06 product/record packet | [SPECIFICATION](../../gpt-6-astra-2026-10-24/SPECIFICATION.md), [CONTEXT-TRANSFER](../../gpt-6-astra-2026-10-24/CONTEXT-TRANSFER.md), [CONTRACTS](../../gpt-6-astra-2026-10-24/CONTRACTS.md) | Read the general spectrum, substantive guarantees, exact identities/concurrency, custody/retention, adoption, completion expressions and transfer semantics. Apply later revisions; old required boolean/two-authority wording is not current. |
| IA-06 conversion drafts | [WORK-ITEMS](../../gpt-6-astra-2026-10-24/WORK-ITEMS.md), [DESIGN-DECISIONS](../../gpt-6-astra-2026-10-24/DESIGN-DECISIONS.md) | OO-1–9, AC-1–6, QR-1 and QA-1 are planning keys, not tracker IDs. Merge coverage into final work; do not publish overlapping packs. DC-OBL/DC-APP/DC-XFER are the earlier candidates here. |
| IA-07 architecture candidates | [DESIGN-DECISIONS](../../application-knowledge-boundary/claude-fable-5-1-2026-10-24/DESIGN-DECISIONS.md) | DC-KOP/DC-ACT/DC-BIND/DC-ROLES and related refinements; reconcile current BKS schema authoring and actual service source. |
| IA-09 integrated target | [CONTRACTS](CONTRACTS.md), [WORK-ITEMS](WORK-ITEMS.md), [DESIGN-DECISIONS](DESIGN-DECISIONS.md) | Current pre-handoff synthesis: coherent §15 walkthrough; 22 candidate vertical slices, including conditional WI-20; five grouped ADR proposals, no canonical numbers allocated. Latest direction and post-sprint fixtures still must be integrated into final deliverables. |
| IA-09 source research | [WORKFLOW-CONTEXT-HOOKS](WORKFLOW-CONTEXT-HOOKS.md), [FINAL-INTERVIEW-RESEARCH](FINAL-INTERVIEW-RESEARCH-2026-10-26.md) | Source findings, runtime distinctions, primary-source cross-checks and three-reviewer corrections. Read exact relevant source again before asserting current behavior. |
| IA-09 earlier handoffs | [CHECKPOINT](CHECKPOINT-2026-10-25.md), [INTERVIEW-HANDOFF](INTERVIEW-HANDOFF-2026-10-26.md), [FINAL-INTERVIEW-HANDOFF](FINAL-INTERVIEW-HANDOFF-2026-10-26.md) | Historical resumption/source maps. Their old next-question/launch instructions are superseded by the new synthesis instruction. |
| IA-09 interview accounting | [FINAL-INTERVIEW-20-QUESTIONS](FINAL-INTERVIEW-20-QUESTIONS-2026-10-26.md), [SESSION-ANSWERS](SESSION-ANSWERS-2026-10-26.md) | Preserve 17 asked/15 answered, F20-04/15 skipped, F20-18/19 unanswered and F20-20 unasked. New owner steering does not fabricate those answers. |
| This handoff | [Owner direction and fixtures](OWNER-DIRECTION-AND-STRESS-FIXTURES-2026-10-26.md), [source map](INTERVIEW-SOURCE-MAP-2026-10-26.md), [session instruction](FINAL-SPEC-AND-ISSUE-SYNTHESIS-HANDOFF-2026-10-26.md) | Current entry point: direct synthesis/publication, implementation mandate, post-checkpoint missions/evaluation and later product architecture. |

## 3. Program-level derivatives and as-built baseline

| Read | Purpose |
| --- | --- |
| [LEDGER](../../../../../provider-consolidation-2026-10/LEDGER.md), [PROCESS](../../../../../provider-consolidation-2026-10/PROCESS.md), [README](../../../../../provider-consolidation-2026-10/README.md) | Status/pointer register, standing process and program scope. The ledger is not an alternate specification. |
| [Application knowledge boundary design](../../../specs/APPLICATION-KNOWLEDGE-BOUNDARY-DESIGN.md) | Accepted storage/report/native boundary projection, especially §§4, 6, 7, 10; current source can supersede historical inventories. |
| [Sprint V research](../../../docs/SPRINT-V-RESEARCH.md), [design](../../../specs/SPRINT-V-DESIGN.md), [plan](../../../sessions/SPRINT-V-PLAN.md) | Prerequisite design and implementation decisions. Sprint V's implementation defaults are not all owner choices; later OC-D112/113 includes governed recommendation/forecast contracts beyond its old default. |
| [Sprint V START-HERE](../../../sprint-v/START-HERE.md), [NEXT-SESSION](../../../sprint-v/NEXT-SESSION.md), [IQ-07-BRIEFING](../../../sprint-v/IQ-07-BRIEFING.md) | Current repository/schema entrypoints and explicit runtime readiness gaps. NEXT-SESSION's older interview-first instruction is superseded here. |
| [Sprint V WORK-ITEMS.json](../../../sprint-v/WORK-ITEMS.json), [PROOFS](../../../sprint-v/PROOFS.md), [TEAM-WORKSPACE](../../../sprint-v/TEAM-WORKSPACE.md) | Existing claims, reviews, actual proof limits and reusable team coordination. Preserve status; don't re-ticket completed prerequisite work. |
| [ADVERSARIAL-READINESS](../../../sprint-v/ADVERSARIAL-READINESS-2026-10-25.md), [READINESS-REPAIRS](../../../sprint-v/READINESS-REPAIRS-2026-10-25.md) | Independent audit and bounded repairs; RV-01–08 remain explicit downstream obligations at their first affected use. |
| [Release bundle](../../../sprint-v/release/RELEASE-BUNDLE.md) | Recorded disposable release/install evidence and pins; not current deployed-state proof. |
| [Original IQ-07 instrument](../../../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md) | Detailed per-round folds and prior conversion requirements; use current directive rather than restarting its question bank. |
| [Original prerequisite instrument](../../../interview-instructions/INTERVIEW-APPLICATION-KNOWLEDGE-BOUNDARY-2026-10-24.md), [Sprint V instrument](../../../interview-instructions/INTERVIEW-SPRINT-V-VERIFICATION-INGESTION-PORT-2026-10-24.md) | Question provenance only; their completed answers govern. |
| [Deep Agents CHANGES](../../../../../provider-consolidation-2026-10/providers/deep_agents/CHANGES.md), [DESIGN](../../../../../provider-consolidation-2026-10/providers/deep_agents/DESIGN.md), [SUBAGENTS](../../../specs/SUBAGENTS.md) | Actual lane history, adopted configuration, Q1–Q8 subagent decisions and asynchronous admission/context behavior. |
| [Original output session](../../../specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md), [domain provenance supplement](../../../proposals/DOMAIN-PROVENANCE-AND-STATE-SUPPLEMENT-2026-10-23.md) | Original OC/DP proposals with dated semantic supersession notices; old special domain kinds, final-message submission and universal helper rules are retired/refined. |
| [Tracing proposal](../../../proposals/TRACING-PROPOSAL.md) | TR-D1–19 plus TR-D2a and later Part C amendments. Keep actual Transcript/provenance capability; historical T0-only/spend rows are not current fixture authorization. |
| [Coordinator proposal](../../../../../coordinator-surface-2026-10/PROPOSAL-COORDINATOR-SURFACE-2026-10-22.md), [coordinator projection](../../../../../coordinator-surface-2026-10/COORDINATOR-PROJECTION-PROPOSAL-2026-10-23.md) | CS-D1–14 have scoped dispositions; focused inspection/wake/content is selected, broad grammar/bundle/API redesign is not. “Hook points” in the proposal means UI/doc connections, not executable hook policy. |
| [Workflow compute proposal](../../../../../provider-consolidation-2026-10/WORKFLOWS-COMPUTE-AND-COMMUNICATION-PROPOSAL-2026-10-23.md), [capability catalog proposal](../../../../../provider-consolidation-2026-10/AGENT-CAPABILITY-CATALOG-PROPOSAL-2026-10-23.md) | Useful candidate designs. Only independently selected requirements enter final scope. |
| [Provider research proposal](../../../../../provider-consolidation-2026-10/PROVIDER-RESEARCH-RUNNING-PROPOSAL.md), [Run 2 carry-forward](../../../../../provider-consolidation-2026-10/RUN-2-CARRY-FORWARD.md), [baseline](../../../docs/BASELINE-2026-10-19.md) | O-1–4 process decisions, still-proposed IP improvements and existing tracker work; don't infer adoption from presence. |

## 4. Canonical amendment targets and ownership

Within MC, reconcile the current accepted target into:

- [General SPECIFICATION](../../../../../../knowledge/mission-control.md),
  [RUNTIME-CONTRACTS](../../../../../../knowledge/lanes-and-harness.md)
  and [DATABASE](../../../../../../knowledge/database-component.md).
- [Knowledge integration](../../../../../../knowledge/knowledge-services.md)
  and [context/state/control](../../../../../../knowledge/context-and-continuation.md).
- [Workflow annex index](../../../../../../knowledge/workflow-systems.md): 00 program model,
  01 Stage Graph, 02 Goal Loop, 03 Swarm, 04 Evaluator Optimizer, 05 executors/controls,
  06 mission invocation, 07 revision, 08 continuation/compaction/transfer, 09 events/commands.
- [GLOSSARY](../../../../../../../GLOSSARY.md), [ADRs](../../../../../../adr), and source-backed
  [OKF knowledge](../../../../../../knowledge/index.md). Accepted target amendments do not
  rewrite as-built knowledge as if implementation had occurred.

Highest ADR found during this interview: 0057; recheck before allocating. Existing 0037/0039/0040/
0049/0056/0057 remain proposed. New decisions may partially supersede 0026 hook-denial wording,
0027 transfer packing and 0029 running-chain cancellation; preserve dated rationale rather than
pretend the old ADR always said the new thing.

| Owner, BellLabs-relative path | Read before editing; authority |
| --- | --- |
| `platform/mission-control` | AGENTS, docs/AGENTS, relevant scoped guide; common DB is `packages/mission-control-db-contract`. MC owns orchestration/lifecycle/fulfillment/transfer, not application entity schema. |
| `platform/knowledge-services` | AGENTS, `docs/agents/CODE-MAP.md`, `knowledge/index.md`; shared report/evidence/verification/use/native-operation core and operational schema. Existing `@aiengineer/*` names are not proof of domain neutrality. |
| `aiengineer/ai-engineer-db-contract` | Domain AGENTS then repo AGENTS; `supabase/migrations`, `src/database.generated.ts`, `workspace/START_HERE.md`, installer. Owns AI Engineer SQL/types. |
| `biotech/biotech-knowledge-services` | Domain AGENTS then repo AGENTS; `schema/source/README.md`, `docs/NAVIGATION.md`, authored SDL and native executor. Owns current Biotech graph schema; do not invent absent `biotech-meta`. |
| `aiengineer/ai-engineer-meta` | Product/domain architecture and canonical `.agents/skills/maintain-agent-docs/SKILL.md`; future full education architecture comes after stress fixtures. |
| BellLabs `docs/BELLLABS-SEQUENCE.md` | Cross-repository owner pathway, updated by latest direction; not an implementation or installation receipt. |

The navigation inventory is dated; Sprint V's current BKS source-authoring and release records
supersede its old absent-authoring/pin statements. Recheck each live repository HEAD, dirty work,
worktrees, package pins and actual installed proof before issuing new claims. Never choose a retained
checkout from its name alone.

## 5. Runtime findings the final plan must cover

Current research is detailed in CONTRACTS §§6/13/18 and FINAL-INTERVIEW-RESEARCH; these are source
observations at MC `1863017c`, not new tests:

- EffectiveRunConfiguration and preflight already exist: extend them; do not invent parallel authority.
- Ordinary graph lowering selects first outputs/required-all in places and loses named binding meaning;
  separate run-wide report loading remains. Exact common selection must reach prompt and sandbox.
- Nested Goal Loops can be flattened; runtime family support is narrower than manifest syntax. All
  four family behaviors and recursive execution need real proof, not parser examples.
- Goal verification uses latest executor refs; report collections are refused; the current accepted
  set and per-member coverage are implementation work.
- RV-01 saved provider result/settlement; RV-02 collections; RV-03 exact selection; RV-04 trusted
  semantic/review composition; RV-05 aggregate budgets/readiness; RV-06 native commit/receipt recovery;
  RV-07 honest evidence; RV-08 official use versus operational read. Gate each before its first use.
- Compaction currently discards hook returns in inspected paths; staged output/read capabilities and
  consumed preservation proposals need real end-to-end work. An after-effect callback cannot undo it.
- Deterministic wake tests do not establish actual external idle coordinator-host wake/content delivery.

## 6. Tracker and local drafts

Tracker: **Linear / overtonbell / OVE / Mission Control**. Read
[issue-tracker](../../../../../../agents/issue-tracker.md) and
[triage labels](../../../../../../agents/triage-labels.md). Discover a connector first. When absent,
the documented authenticated GraphQL fallback works; read its local credential privately, never
print or include it in a prompt/artifact. No remote mutations occurred in this handoff work.

Current drafts under MC `.scratch/iq07-final-interview/`:

- `spec.md`: parent specification draft, **predates OC-D177–181**.
- `issues/*.md`, `issue-drafts.json`: 22 individual slice drafts and ordering; WI-20 conditional.
- `build-drafts.py`: historical renderer; refuses overwrite. Do not rerun to replace refined drafts.
- `linear-known-issues.json`, `linear-project-index.json`, `linear-related-issues.json`,
  `linear-incoming-relations.json`: read-only snapshots; refresh before publication.
- `linear-read.ps1`: read-only GraphQL helper; deliberately refuses mutations. Use a separately
  reviewed explicit publication path for writes and verify actual results.

Existing mapping: OVE-150 Sprint V parent (preserve); OVE-151/152/157/158 reviewed baseline seams;
OVE-160 temporary report-collection refusal and OVE-161 file-byte guard are limited repairs, not
the new runtime features. OVE-75 owns baseline continuation, parent OVE-63, blocked by 65/69;
OVE-78 owns baseline subscriptions, parent OVE-63, blocked by 76/77. Add the actual preservation/
content/inspection deltas without duplicating those engines. Their previous issue states are dated
observations, not permission to mark them done. Old Done hook/context/chain cards likewise do not
qualify the new behavior.

Final synthesis must refine the 22 drafts, add post-sprint F1/F2/F3 and mission-work evaluation/
feedback-loop scope, and incorporate per-major-commit quality into every applicable done definition.
Add necessary migrations/cutovers and fixture-driven capability work. The count is not a fixed limit.
Publish native blocking edges in dependency order and map every local key/decision to real IDs.

## 7. Verified quality entrypoints

No `.quality.config.json` was found in MC, KS, AIDB or BKS. The global
`C:/Users/Pinda/.codex/skills/quality-checkpoints/SKILL.md` describes turn-end triage, not an already
active per-major-commit gate. KS separately has maintenance hooks and isolated proposals under
`tools/maintenance/`; their presence does not prove successful review or automatic application.

| Repository | Commands/mechanisms to reuse, according to affected scope |
| --- | --- |
| MC | `make ci` (authoritative mypy included), `make docs-check`, `make skills-check`; affected integration/acceptance suites on real local services. For changes: `make manifest-schemas-check`, `make test-db-contract`, `make seeds-validate`. Regenerate `python docs/tools/agents_docs_index.py`, then `python docs/tools/check_docs.py`. `make check` alone is not all these gates. |
| KS | `corepack pnpm verify`; affected `test:maintenance`/`test:context`. Update authored knowledge and semantic module registrations, then `node .agent-docs/cli.mjs build --repo .` and `node .agent-docs/cli.mjs check --repo .`. Do not inflate lint/boundary baselines to hide failure. |
| AIDB | `npm run typecheck`, `npm test`, generated-type drift, `npm run workspace:check`, `npm run workspace:validate`; same `.agent-docs` build/check. Migration + generated types together. Reuse `.github/workflows/contract.yml` fresh/repeat/install and native binding/projection proof; `scripts/install-ai-engineer.mjs` owns release install. No generic OKF opt-in exists here. |
| BKS | `pnpm build`, `pnpm workspace:verify`, `pnpm test`, `pnpm client:pack-check`; affected real Neo4j integration. Use `schema/source/README.md` source→generate/check/verify→pin→workspace/API/client workflow. AGENTS/navigation is authored; do not invent a generic OKF or `.agent-docs` gate. |

Use MC `.agents/skills/implement-spec`, `implement`, `code-review`, `architecture-projection`,
`domain-modeling`, `to-spec`, `to-tickets` and `belllabs-method` for their applicable phases.
The latest direct publication mandate replaces redundant interview/ceremonial approval steps.
The current `sprint-v/TEAM-WORKSPACE.md` supplies reusable claims/ownership/handoff fields, not
fixed models or a requirement to preserve old implementation. Another reviewer assesses both
spec behavior and code quality against a known baseline; an integrator owns shared-file integration.

## 8. Fixture capability, ingestion, retrieval and evaluation source map

Paths in this table are relative to their named repository. These are inspected source entrypoints,
not claims that the requested fixture profile is installed or fully qualified.

| Owner / path | Finding and final-plan consequence |
| --- | --- |
| MC `packages/mission-control-db-contract/seeds/agent_capabilities.py`, `seeds/agent_skills.py`; `skills/mission-control-catalog/SKILL.md` | Tavily, Firecrawl, Vercel agent-browser, PubMed and BioMCP candidates exist. Pin/admit actual capabilities and MCP allowlists. No separate ClinicalTrials.gov seed was found in this seed file: discover and wire the requested server; do not silently substitute a different interface based only on BioMCP trial support. |
| MC `src/mission_control/adapters/deep_agents/async_subagents.py`, `domain/capabilities/subagents.py` | Start/check/update/cancel/list task mechanisms and browser/general-purpose vocabulary exist. Qualify the exact general and dedicated async browser profiles. Seed presence does not prove deployment, parent join, context delivery or usable results. |
| MC `src/mission_control/adapters/deep_agents/browser_tool.py` | `agent_browser_page` returns bounded single-page URL/title/text. It is not full interactive Vercel browser control and cannot substitute for the requested browser-subagent proof. The upstream browser skill seed is a thin stub. |
| MC `packages/mission-control-db-contract/seeds/knowledge_tools.py`; KS `packages/host/src/knowledge-operation/service.ts` | Catalog candidates differ from actual injected binding/assessor/native-port availability. Executable service code implements and advertises `report.derive`; the header saying unsupported is stale. `verify.claims` is not advertised. Research, inspection, assessment and native apply must use supported qualified paths or receive implementation work. |
| KS `packages/application/src/operations/catalog.ts`, `packages/application/src/knowledge/retrieval/canonical-retrieval-executor.ts`, `packages/contracts/src/evaluation.ts` | Public retrieval, evidence packet, evaluation dataset, experiment and evaluation-run surfaces exist. Retrieval needs embedding configuration and has versioned reranking/degraded policy. Reuse these seams; they do not prove end-to-end use-case model routing. |
| KS `skills/knowledge-retrieval-and-evidence/SKILL.md`, `knowledge-evaluation/SKILL.md`, `knowledge-verification/SKILL.md`, `knowledge-ingest/SKILL.md` | Existing skill families to read and qualify for F2/F3 and mission-work evaluation; don't assume every declared skill is already loaded into an MC stage. |
| BKS `.agents/skills/skill-routing.json`, `biotech-kg-ingest/SKILL.md`, `biotech-kg-query/SKILL.md` in that skill tree | Native plan/apply/receipt/verify-effects and official-use v3 query/authority revalidation. Inspect exact product/ingredient/study schema fit rather than invent names. |
| AIDB `workspace/relations/corpus/{ai_model_version,model_offering,benchmark_run}.md`, `workspace/relations/ranking/{ranking_policy,ranking_run}.md` and related result/selection cards | Native model/version/benchmark and ranking representations already exist. Read generated workspace/types and authored migrations. Missing qualification is not proof the schema is absent; revise it if the actual fixture dimensions require more. |

No Generation Lab, Qualia Life or current model/benchmark data was fetched in this handoff. Capability
and fixture discovery belongs to the implementation/evaluation work, not fabricated research results.
