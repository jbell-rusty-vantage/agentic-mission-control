---
type: Working Draft
title: "Retrieval audit baseline: Mission Control and Knowledge Services, eight criteria, 2026-11-01"
description: "Baseline of the eight-criterion retrieval audit (SPEC-01 §12 item 8; IQ-02 preparation item 5) for platform/mission-control and platform/knowledge-services on the live sprint-oc branches: scores 0-10 with file-level evidence, the KS benchmark rerun, a 62-question log run through the existing search tools, candidate fixture cases from every miss, the engine features worth keeping, and the five fixes ranked by expected retrieval gain."
tags: [mission-control, knowledge-services, retrieval, audit, sdlc]
date: 2026-11-01
status: draft
---

# Retrieval audit baseline (2026-11-01)

**What this closes.** SPEC-01 §12 item 8 asks for a baseline before S2 and a re-run after S6; IQ-02
lists it as preparation item 5 for sitting II. This is that baseline. It was produced by using the
tools as a fresh agent would, with no code or documentation changed. It measures the documentation
and retrieval layer only. It says nothing about runtime behaviour or qualification.

**Scope and state observed.** `platform/mission-control` on `sprint-oc` at `ce9d2f13` (dirty: the
agentic-sdlc `LEDGER.md`, `cursor_native.py`, the sitting II answers file).
`platform/knowledge-services` on `sprint-oc` at `6a4dd30` (OVE-204 slice 4, KS side). Tools used:
MC `docs/tools/okf_search.py`, `agents_docs_index.py --check`, `validate_okf.py`, `check_links.py`,
`check_docs.py`. KS `.agent-docs/cli.mjs search|context|check|audit` and
`.agent-docs/retrieval-benchmark.mjs`. Nothing was paid, nothing was committed, no `.env` was read.

**Grading rule.** In the question log, a hit is counted only when the doc ranked 1–3 actually
contains the answer. The tools' own rank is reported next to it. This rule matters for Knowledge
Services. Its corpus has 11 concepts and the engine almost never abstains, so its raw recall@3
overstates what an agent actually learns (§3.3).

## 1. Scores

| Criterion | MC | KS | One-line justification |
| --- | --- | --- | --- |
| Entry-point quality | 4 | 6 | MC `AGENTS.md` is 29,624 B: 5.8 KB of stacked dated directions and a 19.5 KB generated index. KS is 8,969 B and well routed, but its status lines are stale. |
| Index freshness | 5 | 4 | MC `--check` reports current, but the active agentic-sdlc program is silently missing. KS `check` exits 1 (provenance drift), 4 evidence files have changed under one concept, and one `audit` decision states a wrong pin. |
| Category coverage (9) | 6 | 4 | MC covers 5 categories, 2 partially, with decisions and goals missing. KS covers 3, 4 partially, with decisions and goals missing; none of the OVE-204 knowledge-operation work is in a concept. 0 concepts in either repo carry `category:`. |
| Skill routing | 5 | 3 | MC has a precise `mission-control-docs` skill, but `AGENTS.md` names only `belllabs-method` out of 64 skills. KS has no docs or retrieval skill; `.agents/skills` holds 4 planning skills. |
| Fact placement | 4 | 5 | MC spend ceiling, Aura plane, test commands and the provenance report sit outside the search corpus or only in dated preambles. KS recent facts live only in commit messages; operations, benchmark and decisions sit outside the corpus. |
| Evidence discipline | 7 | 8 | MC: 66/66 concepts have Citations and the precedence order is explicit. KS: 11/11 concepts have `implementation_status`, `validation_status` and `sources`, and `context` hashes the evidence. |
| Staleness signals | 3 | 7 | MC: 7/66 concepts are dated, there are no evidence hashes, and the 2026-10-03 annexes outrank current concepts without warning. KS: `context` labels each evidence file unchanged/changed/missing, and `check` reports drift. |
| Search ergonomics | 6 | 6 | MC: 0.75 s, JSON, `--root`/`--type`, glossary terms as documents; no aliases/questions fields; camelCase identifiers return 0 hits. KS: aliases/questions weighted, camelCase split, bounded `context`; no abstention; usage text hides `search`/`context`. |
| **Total /80** | **40** | **43** | |

Measured retrieval for this audit (§3): MC 23/32 answer-verified in the top 3, MRR 0.646. KS 13/30
answer-verified in the top 3 (19/30 counting partial answers), against a nominal engine
recall@3 of 27/30. KS frozen benchmark, current repo: screening 17/18, heldout 6/6, negatives
3/4 (§2.8).

## 2. Evidence per criterion

### 2.1 Entry-point quality

**AGENTS.md byte size per section** (LF-normalized; KS is 8,969 B on disk with CRLF):

| Mission Control section | Bytes | Knowledge Services section | Bytes |
| --- | ---: | --- | ---: |
| Title and dated preamble (lines 1–51) | 5,768 | Title and preamble (lines 1–9) | 1,447 |
| Work by concern | 956 | Engineering planning and delivery | 874 |
| Invariants | 1,336 | Repository guide (generated) | 1,828 |
| Verify | 591 | Business logic and workflows (OKF) (generated) | 1,412 |
| Agent skills (6 subsections) | 1,451 | Code navigation (generated) | 1,542 |
| Documentation index (generated) | 19,523 | Task routes (generated) | 1,022 |
| | | Validation (generated) | 829 |
| **Total** | **29,624** | **Total** | **8,954 LF / 8,969 disk** |

Generated share: MC 66% (19.5 KB), KS about 74% (about 6.6 KB). Hand-written: MC about 10.1 KB,
KS about 2.3 KB.

- **MC.** `AGENTS.md:3-51` stacks seven dated direction paragraphs (2026-10-26 to 2026-10-31).
  They overlap and partly supersede one another: "provisional order", "completed focus", "OC-D208",
  "Preparation snapshot", "Sprint V START-HERE". `AGENTS.md:21` quotes a USD 100 Qualia
  authorization. That is the only spend figure an entry-reading agent sees; the standing Sprint OC
  rule is USD 40/15 (`sprint-oc/DECISIONS.md:325` OC-D189). The useful parts are "Work by concern"
  (`:53-66`), "Invariants" (`:68-88`) and "Verify" (`:90-99`), about 2.9 KB in total. The generated
  index (`:140-165`) lists 67 ADR slugs, 66 concepts and every sprint-oc file, but it omits the
  active agentic-sdlc program (§2.2). Neither the workspace
  `docs/navigation/DATA-PLANES-AND-CREDENTIALS.md` nor the `mission-control-docs` skill is linked.
- **KS.** `AGENTS.md:26-32` holds seven crisp invariants. `:36-50` routes each task to a concept,
  `:56-70` routes each change to a module chain, and `:89-93` gives the validation commands. Stale
  points:
  - `:7` still sends "Sprint V agents" to START-HERE.
  - `:32` says "ingestion does not write knowledge_service.operation". That predates OVE-204, under
    which `knowledge.read_intent` records reads in `knowledge_verification.operation` (commit
    `6a4dd30`) and apply writes `orchestration.operation_receipt_target` (commit `2564226`).
  - `:74` marks `NEXT-PACKAGE-CLEANUP.md` (last commit 2026-10-24) as the "current handoff".
  - The generated docs index (`:95-99`) lists ADRs 0001–0004, while `:15` says ADRs 0005–0015 are
    the authorized direction.
  - `knowledge.read_intent`, K01 and OVE-204 appear nowhere in the file.

### 2.2 Index freshness

- **MC.** `python docs/tools/agents_docs_index.py --check` prints "AGENTS.md docs index is current".
  `validate_okf.py` reports 64 concepts valid, `check_links.py` reports 595 files and 0 broken
  links, and `check_docs.py` passes 8/8. Even so, `docs/agents/index-notes.toml:11-12` carries
  notes for `docs/specs/agentic-sdlc-2026-11` and `/answers`, while `GROUPS` in
  `docs/tools/agents_docs_index.py:36-80` is hard-coded and omits them. The compiler fails on a
  directory with no note, but not on a note with no directory. So the check is green while the
  active program is unindexed.

  The hand-authored `docs/knowledge/index.md:5-36` still opens with "Current Sprint OC recovery
  (2026-10-29)", then "Run 2 ... finished", then "Next program: provider consolidation (draft;
  decisions D1–D9 open)". It does not mention the provenance sprint or Agentic SDLC.
- **KS.** `node .agent-docs/cli.mjs check --repo . --format json` returns `exitCode 1` with
  `drift: [".agent-docs/provenance.json"]` over 431 inputs. No `knowledge/` file or the provenance
  file has been committed since 2026-10-27/29, while 10 commits landed after 2026-10-29, including
  OVE-204 slices 2–4. `context --query "read intent"` reports `schema-read-and-ingestion.md` as
  `conceptFreshness: unchanged` while 4 of its 15 evidence files are `changed`: `ingestion/plan.ts`,
  `apply.ts`, `executor.ts` and `executor.integration.test.ts`.

  `audit` emits the decision "The database-contract pin is the vendored 0.4.16 tarball"
  (`.agent-docs/config.json:578`; also `docs/agents/CODE-MAP.md:404,452`). The actual pin is
  `file:../../vendor/aiengineer-database-contract-0.5.0.tgz` (`packages/knowledge-db/package.json:19`,
  since `b45adf5`, 2026-10-25).

### 2.3 Category coverage (against INFORMATION-CATEGORIES-DRAFT-2026-11-01.md)

| Category | MC | KS |
| --- | --- | --- |
| boundaries | covered (`architecture`, `knowledge-services`, `provider-lanes`, `interfaces`) | covered (`service-boundaries`) |
| surfaces | partial: the coordinator surface exists only as a proposal | covered (`execution-profiles-and-transports`, `agent-skills-and-consumer-readiness`) |
| domain-model | covered | partial: no `knowledge-operation` concept (K01, `read_intent`, receipt targets, `report_v2`, producer origin) |
| persistence | partial: no `database-component`; Aura/Postgres planes only in AGENTS.md preamble and handoffs | partial: the pin is misstated in `audit`; no `schema-ownership` |
| execution | covered (10 concepts) | covered |
| qualification | covered; no documentation-retrieval fixtures | partial: the benchmark is described only in `.agent-docs/fixtures/ks-context-v1/README.md` |
| operations | covered (`operations`, `environments`, `secret-broker`, ...); `docs/WSL2_WORKER_RUNBOOK.md` and `docs/DEVELOPMENT.md` are outside the corpus | partial: `docs/operations/runbooks.md` is outside the corpus; no `operations` concept |
| decisions | missing as a concept (ADRs are indexed and searchable) | missing; ADRs 0005–0015 are outside both index and corpus |
| goals | missing | missing |

**Concept metadata gaps:**

| Gap | MC (66 files) | KS (11 concepts) |
| --- | --- | --- |
| `aliases` | 66/66 lack it | 0/11 lack it |
| `questions` | 66/66 lack it | 0/11 lack it (3–6 each) |
| `category` | 66/66 lack it | 11/11 lack it |
| Citations | 0 lack a Citations heading | 0 lack `sources:` frontmatter (only 3 also have a heading) |
| Dated | 7/66 | none carry a `date` |
| SPEC-01 160-line cap | 22/66 sit at 150–160 lines (packed to the cap); `log.md` is 1,228 lines and in the default corpus | 3 exceed it: `verification-and-admission` 258, `service-boundaries` 226, `schema-read-and-ingestion` 176 |

### 2.4 Skill routing

- **MC.** `.agents/skills` holds 64 skills, mirrored by `.claude/skills`. Many are generic
  LangChain/LangGraph quickstarts. `.agents/skills/mission-control-docs/SKILL.md` has a precise
  trigger list and a three-step procedure: `okf_search`, open the top hit, answer in glossary terms.
  `AGENTS.md:101-133` names only `belllabs-method`; it never names `mission-control-docs`,
  `mission-control-local-setup` or the `deep-agents-*` skills.
- **KS.** `.agents/skills` holds `setup-matt-pocock-skills`, `to-spec`, `to-tickets` and `triage`.
  There is no retrieval or docs-maintenance skill; the procedure lives only in `AGENTS.md:47-50`.
  `skills/` holds product skills for consumers (with `manifest.json` and `check.mjs`), not
  development routing. `CLAUDE.md` is `@AGENTS.md` (11 B).

### 2.5 Fact placement

- **MC.** Each of these lives in a document an agent cannot find in one or two hops:
  - Spend ceiling: `sprint-oc/DECISIONS.md:325` and `ESCALATION.md:44`, both outside the default
    corpus.
  - Aura plane id: `AGENTS.md:22` (as an authorization) and the handoffs. No concept states it.
  - Test commands: `AGENTS.md:90-99` and `docs/DEVELOPMENT.md`, both outside the corpus.
  - Provenance report: `sprint-oc/provenance-2026-10-31/REPORT.md`, not linked from NEXT-SESSION,
    the knowledge index or the `knowledge-services` concept (0 links each; reachable only through
    the provider-consolidation LEDGER row SE-17).
  - Model route names Astra/Sol: not in `docs/knowledge/model-catalog.md`.
- **KS.** Concepts are one per task and well routed. OVE-204 facts exist only in commit messages
  (`6a4dd30`, `2564226`, `5727a4b`, `8a38b0f`) and in MC's provenance packet. `CODE-MAP.md` is
  147,139 B: the facts are there, but it is not a one-hop surface.

### 2.6 Evidence discipline

- **MC.** Every concept has a Citations section. `docs/knowledge/index.md:22-28` and the generated
  index state the precedence order and "report the conflict". `AGENTS.md:97-98`: "Report passed,
  failed, blocked and unrun checks separately". Concepts carry no status fields, so an agent cannot
  tell implemented from specified without reading the prose.
- **KS.** All 11 concepts carry `implementation_status` (for example
  `implemented-with-transitional-surfaces`, `partial`) and `validation_status:
  source-and-test-inspected`, plus `sources:`. `context` returns `freshnessMeaning: "unchanged does
  not attest semantic correctness or deployment"`. The KS index header (`knowledge/index.md:4`)
  says the concepts are "not ... deployment attestations".

### 2.7 Staleness signals

- **MC.** `okf_search` output carries no date, status or freshness. The 2026-10-03 expansion
  packet is in the default corpus and outranks the current concept:
  - "How does Knowledge Services verify claims and admit evidence?" returns `WORKED-SCENARIOS.md`,
    `GLOSSARY.md#Step Contract` and the 2026-10-03 `expansion/KNOWLEDGE-SERVICES.md`, not
    `docs/knowledge/knowledge-services.md`.
  - "Which ai-engineer-db-contract migration head ..." returns `CODEBASE-ORGANIZATION.md` first.

  The only stale markers are index notes ("statuses stale since 2026-10-03" on the issues group;
  "W0 released, W1 unreleased").
- **KS.** Freshness is computed per concept and per evidence file (`.agent-docs/knowledge.mjs:182-212`),
  and `check` reports drift. Gaps: `search` results carry no freshness. `conceptFreshness` hashes
  only the concept's own bytes, so a concept whose code changed under it still reads `unchanged`.
  `check` names `provenance.json`, not the affected concepts.

### 2.8 Search ergonomics and the KS benchmark

**MC.** BM25 with field weights title 4, tags 3, description 2, headings 2, body 1
(`okf_search.py:48`). There is no aliases or questions field. `TOKEN_RE=[a-z0-9][a-z0-9_]+` keeps
`read_intent` whole (good), splits `OVE-204` into `ove`, `204`, and does not split camelCase:
`KnowledgeReadIntentPort` returns 0 results. The default roots (`:33-46`) exclude `AGENTS.md`,
`docs/*.md`, skills and all `docs/specs` except three sprint-oc files. It abstains on
"quantum banana telescope" (`[]`) but not on "style React checkout buttons" (ADR 0012 first).
`--root` rescues most misses once the agent knows the folder.

**KS.** Weights title 5, description 3, tags 4, aliases 5, questions 4, headings 2, body 1, scaled by
the matched-term fraction (`.agent-docs/knowledge.mjs:147-161`). camelCase is split and stop words
are removed. Any single matched term yields a result: "OVE-204" returns `verification-and-admission`
on the term `ove` alone, and "Selection Workspace" (an MC concept) returns
`preparation-and-publication` at score 3.3. `node .agent-docs/cli.mjs` with no arguments prints
"Usage: ... check|build|audit", hiding `search` and `context`. `context` is bounded: 2 sections, 24
evidence files and module entrypoints/tests, 8,090 B for one result.

**KS benchmark** (`node .agent-docs/retrieval-benchmark.mjs --repo .`, fixture head `35286421`,
labels "engineer-authored ... no independent human adjudication"):

| Engine and corpus | Screening (18 positive) recall@3 / MRR | Heldout (6 positive) recall@3 / MRR | Negatives correct (of 4) | Critical failures |
| --- | --- | --- | --- | --- |
| baseline ranking, frozen 6 concepts | 0.8889 / 0.8769 | 0.8333 / 0.7833 | 2 | `service-boundaries-1` |
| improved ranking, frozen 6 concepts | 0.9444 / 0.9278 | 0.8333 / 0.7917 | 3 | none |
| current repo, 11 concepts | **0.9444 / 0.8981** | **1.0000 / 0.8333** | **3** | none |

The current corpus regresses from the 2026-10-15 follow-up, which reported screening 18/18 and MRR
0.9352. `verification-and-admission-2` ("What gates semantic judging?") now ranks 6, behind the
later-added `evaluation-and-publication-gates` and `execution-profiles-and-transports`. Nothing
gates the benchmark, so the regression went unnoticed. `negative-26` ("style React checkout
buttons") still fails.

The fixture format is worth freezing as the seed:

- `queries.json` is `{labelProvenance, cases[{id, query, expected[], critical, partition}]}`.
- Partitions: 18 screening (3 per concept), 6 heldout (1 per concept), 4 negative heldout.
- 6 critical cases, the first question per concept.
- `manifest.json` pins LF-normalized SHA-256 per concept copy.
- Metrics: recall@3, MRR, correct abstentions and critical failures per partition.
- Gap: it covers only 6 of 11 concepts, and its heldout cases are already observed
  (`fixtures/ks-context-v1/README.md`).

## 3. Question log

Commands, run from each repository root:

- MC: `python docs/tools/okf_search.py "<question>" --limit 10 --json`
- KS: `node .agent-docs/cli.mjs search --repo . --query "<question>" --limit 10 --format json`

Raw rank is the first position of an expected doc. **≤3** is answer-verified (yes / partial / no).

Hops:

- **0**: the answer is in the always-loaded `AGENTS.md`.
- **1**: search, then open a top-3 hit.
- **2**: one link-follow or one rescoped `--root` search.
- **3+**: requires an unlisted path, `git log` or a code grep.

### 3.1 Mission Control (32 questions)

| id | Question | Top 3 | Raw rank | ≤3 | Hops |
| --- | --- | --- | --- | --- | --- |
| MC-01 | Where is the Deep Agents lane implemented? | lanes-and-harness, agent-configuration, deep-agents-lane | 3 | yes | 1 |
| MC-02 | What is the current status of Sprint OC W1? | sprint-oc/NEXT-SESSION, SESSION-CODEX-RESUME, knowledge-services | 1 | yes | 1 |
| MC-03 | Was Sprint OC W0 released and what did it release? | APPLICATION-PORTS, NEXT-SESSION, knowledge/index | 2 | yes | 1 |
| MC-04 | provenance sprint OVE-204 final report | knowledge/log, knowledge-services, NEXT-SESSION | – | no | 3 (LEDGER SE-17 → REPORT; `--root …/provenance-2026-10-31` gets REPORT #1) |
| MC-05 | What did the provenance sprint build: authenticated origin and native receipt provenance? | ADR 0060, APPLICATION-PORTS, GLOSSARY#Provenance Role | 1 | yes (design, not sprint status) | 1 |
| MC-06 | What is the Selection Workspace? | GLOSSARY#Selection Workspace, selection-workspace, ADR 0048 | 1 | yes | 1 |
| MC-07 | Where is the KS knowledge.read_intent contract consumed by Mission Control? | knowledge-services, GLOSSARY#Read Intent, expansion/KNOWLEDGE-SERVICES | 1 | yes | 1 (→ `application/knowledge/read_intent.py`) |
| MC-08 | Which database does Mission Control write mission records to? | SPECIFICATION, DATABASE, expansion/DEPLOYMENT-AND-RELEASE | 2 | yes (spec, not the persistence concept) | 1 |
| MC-09 | How do I run the unit tests and type checks? | selection-workspace, NEXT-SESSION, signal-ingress | – | no | 0 via AGENTS.md Verify; search useless |
| MC-10 | How do I start the local Mission Control API? | docs/agents/issue-tracker, operations, CURSOR_SDK_FACTS | 2 | yes | 1 |
| MC-11 | What was decided about auto-merge on green checks? | ADR 0067, ADR 0065, wake-channels | 1 | yes | 1 |
| MC-12 | Where are the mission-db migrations and common SQL? | ADR 0003, CODEBASE-ORGANIZATION, MC-F002 | 1 | yes | 1 |
| MC-13 | Is Temporal the only scheduler? | ADR 0004, GLOSSARY#Temporal, MC-F005 | 1 | yes | 1 |
| MC-14 | How does a precise fork from a recorded point work? | precise-fork, ADR 0057, recovery | 1 | yes | 1 |
| MC-15 | What is the paid model spend ceiling for Sprint OC? | NEXT-SESSION, agent-configuration, SESSION-CODEX-RESUME | – | no | 3 (DECISIONS OC-D189; AGENTS.md shows USD 100 instead) |
| MC-16 | Which Aura graph does Biotech ingestion write to? | WORKED-MISSION, expansion/KNOWLEDGE-SERVICES, WORKED-SCENARIOS | 7 | no | 2 via workspace DATA-PLANES (not linked from MC) |
| MC-17 | Which model does the Sol or Astra route resolve to? | SESSION-CODEX-RESUME, NEXT-SESSION, deep-agents-turn-stops | 10 | no | 3 |
| MC-18 | Cursor lane profiles and frames | cursor-lane, ADR 0035, lanes-and-harness | 1 | yes | 1 |
| MC-19 | What is the status of the Agentic SDLC program? | ADR 0064, GLOSSARY#Idea, GLOSSARY#Agentic SDLC | – | no | 2 (ADR source line → LEDGER/SPEC-01) |
| MC-20 | How do I prepare the WSL2 worker host? | GLOSSARY#Bootstrap Entrypoint, ADR 0042, cursor-lane | 4 | no | 1 via the AGENTS.md index entry; `--root docs` gets it #2 |
| MC-21 | What was decided about selection and routing across lanes and models? | ADR 0063, selection-workspace, interfaces | 1 | yes | 1 |
| MC-22 | How do async subagents report back to the parent? | async-children, deep-agents-lane, TECHNOLOGY-EVIDENCE | 1 | yes | 1 |
| MC-23 | How are output obligations fulfilled and submitted? | output-contracts, GLOSSARY#Obligation Fulfillment, OUTPUT-CONTRACTS | 1 | yes | 1 |
| MC-24 | How are secrets delivered to a lane? | ADR 0043, environment-preparation, ADR 0042 | 1 | yes | 1 |
| MC-25 | Can agents write database tables directly? | ADR 0056, SYSTEM_PROPOSAL, DATABASE | 1 | yes | 1 |
| MC-26 | Where is the mission transcript recorded and replayed? | ADR 0054, events-and-commands, knowledge/index | 1 | yes | 1 |
| MC-27 | coordinator surface missionctl skill status | ADR 0022, wake-channels, authoring | – | no | 2 (AGENTS.md index lists the LEDGER; `--root` gets LEDGER #1) |
| MC-28 | Where does the LangGraph saver live versus Agent Server persistence? | ADR 0017, APPLICATION-PORTS, expansion/VALIDATION | 1 | yes | 1 |
| MC-29 | read_intent | GLOSSARY#Read Intent, knowledge-services, log | 1 | yes | 1 |
| MC-30 | How does a StageGraph decide the next stage? | execution, workflow-systems, GLOSSARY#Stage Graph | 1 | yes | 1 |
| MC-31 | How do I check the documentation before closing a session? | program-workspace, NEXT-SESSION, documentation-surfaces | 3 | yes | 1 |
| MC-32 | What are the open provider consolidation decisions D1-D9? | program-workspace, ADR 0064, knowledge/index | (3) | partial (index.md says "open", no per-decision state) | 2 |

**MC totals:** 23/32 answer-verified in the top 3 (recall@3 0.72), MRR 0.646. 9 misses. Extra
probes:

- `KnowledgeReadIntentPort`: 0 results.
- "KnowledgeClient HTTP out-of-process caller": wake-channels, GLOSSARY#Session Owner, ADR 0036.
  `knowledge-services` is not in the top 3.
- Cross-repo "How does Knowledge Services verify claims and admit evidence?": three 2026-10-03
  annexes or glossary entries first.
- "style React checkout buttons": no abstention.

### 3.2 Knowledge Services (30 questions)

| id | Question | Top 3 | Raw rank | ≤3 | Hops |
| --- | --- | --- | --- | --- | --- |
| KS-01 | Where is knowledge.read_intent implemented? | service-boundaries, schema-read-and-ingestion, retrieval-and-evidence | 2 | **no: wrong answer** (describes the older `RETRIEVAL_UNAVAILABLE` read-intent executor) | 3+ (`git log`; `packages/knowledge-operation-protocol`, `apps/verification-executor/src/knowledge-operation/`) |
| KS-02 | What is a knowledge operation and the K01 protocol? | service-boundaries, durable-execution, schema-read | 3 | no (K01 named only in verification-and-admission, rank >3) | 3 |
| KS-03 | Which database does ingestion write to? | schema-read, service-boundaries, preparation | 1 | yes | 1 |
| KS-04 | Which ai-engineer-db-contract version is pinned? | schema-read, service-boundaries, verification-and-admission | 1 | partial (#3 says "contract 0.5.0"; `audit` and CODE-MAP say 0.4.16) | 2 |
| KS-05 | How do I run the tests and typecheck? | evaluation-gates, capture-conversion, durable-execution | 10 | no | 0 via AGENTS.md Validation |
| KS-06 | Which MCP tools does the server expose? | execution-profiles, service-boundaries, agent-skills | 1 | yes | 1 |
| KS-07 | What did OVE-204 provenance sprint change in Knowledge Services? | verification-and-admission, service-boundaries, retrieval | 6 | no (absent) | 3+ (`git log`) |
| KS-08 | How does KS verify credentials minted by Mission Control? | service-boundaries, verification, durable | 1 | no (absent; "mint" matches an intent-ID row) | 3+ |
| KS-09 | How does the Jev worker queue semantic judgments? | jev-decisions-and-workers, durable, service-boundaries | 1 | yes | 1 |
| KS-10 | What are the retrieval benchmark recall and MRR gates? | evaluation-gates, service-boundaries, retrieval | 1 | no (recall and MRR in no concept) | 3 (fixture README) |
| KS-11 | What was decided about embedding retrieval decision gates? | preparation, retrieval, evaluation-gates | 2 | partial (ADR 0015 not cited or indexed) | 2 |
| KS-12 | Is Biotech graph ingestion owned by shared Knowledge Services? | service-boundaries, verification, schema-read | 1 | yes | 1 |
| KS-13 | How is hybrid search over embeddings performed? | retrieval-and-evidence, preparation, service-boundaries | 1 | yes | 1 |
| KS-14 | Who owns shared database migrations? | service-boundaries, preparation, agent-skills | 1 | yes | 1 |
| KS-15 | How is a PDF converted with Docling? | capture-conversion-and-custody, jev | 1 | yes | 1 |
| KS-16 | Who may change the publication pointer? | evaluation-gates, preparation, service-boundaries | 1 | yes | 1 |
| KS-17 | Which skills are shipped and are they DeepAgents ready? | agent-skills, evaluation-gates, jev | 1 | yes | 1 |
| KS-18 | How do I deploy or operate the verification executor runbook? | verification, durable, execution-profiles | 3 | partial (`docs/operations/runbooks.md` outside the corpus) | 2 |
| KS-19 | Where did verification recovery go after the SV-17 cutover? | durable-execution, verification, preparation | 1 | yes | 1 |
| KS-20 | Does ingestion write an outbox or operation row? | schema-read, service-boundaries, durable | 1 | partial and **stale** (AGENTS.md:32 "does not"; OVE-204 now writes receipt targets and read operations) | 3 |
| KS-21 | AIDB typed columns preflight and per-input effects | jev, retrieval, verification | 5 | no (absent) | 3+ |
| KS-22 | receipt targets and report_v2 projection | verification, schema-read, preparation | 1 | no (absent) | 3+ |
| KS-23 | How should Mission Control call KS out of process? | service-boundaries, verification, durable | 1 | yes | 1 (also AGENTS.md:27) |
| KS-24 | Which environment variable holds the database URL? | preparation, execution-profiles, service-boundaries | 2 | no (absent) | 3+ |
| KS-25 | What does the Biotech graph binding implement? | service-boundaries, verification, durable | 1 | no (bindings in no concept) | 2 via the AGENTS.md:70 route |
| KS-26 | Where are the architecture decisions recorded? | jev, service-boundaries, verification | 2 | partial (no decisions concept) | 2 |
| KS-27 | What is the current implementation state of KS? | service-boundaries, verification, preparation | 1 | partial (`docs/architecture/current-state.md` outside the corpus) | 2 via the AGENTS.md:83 route |
| KS-28 | How does citation replay detect changed bytes? | retrieval-and-evidence, verification, capture | 1 | yes | 1 |
| KS-29 | read_intent | schema-read, service-boundaries, execution-profiles | 1 | **no: wrong answer** (same as KS-01) | 3+ |
| KS-30 | How do I add a new MCP tool with API parity? | service-boundaries, execution-profiles, verification | 1 | yes | 1 |

**KS totals:** nominal engine recall@3 27/30 (0.90). Answer-verified: 13/30 (0.43), or 19/30 with
partial answers. Extra probes:

- "Where does Mission Control consume read_intent?": service-boundaries 2.6.
- "Selection Workspace": preparation-and-publication 3.3.
- "OVE-204" and "W1" each match one token in `verification-and-admission`.

None abstains.

### 3.3 Reading the two numbers

The KS nominal 0.90 is an artifact of an 11-document corpus. With no abstention threshold, three
of eleven concepts always come back. The OVE-204 knowledge-operation work is absent from the
corpus, so the engine confidently returns the nearest older concept. KS-01 is the dangerous case:
it describes the pre-K01 read path.

The MC misses are mostly corpus-scope misses. The documents exist (ledgers, DECISIONS, REPORT,
DEVELOPMENT, the runbook) but lie outside the default roots. `--root` or the AGENTS.md index
recovers them in one extra hop.

## 4. Candidate fixture cases from misses

Failure causes: **missing concept** (no doc in the corpus holds the fact), **bad metadata**,
**ranking**, **stale**, **tokenization**. "Corpus" notes a document that exists but is outside the
default search roots.

| id | Repo | Question | Expected doc(s) | Observed top hit | Failure cause | Critical |
| --- | --- | --- | --- | --- | --- | --- |
| FX-MC-01 | MC | provenance sprint OVE-204 final report | `sprint-oc/provenance-2026-10-31/REPORT.md` | `docs/knowledge/log.md` | missing concept (corpus); tokenization (`OVE-204` → `ove`, `204`) | yes |
| FX-MC-02 | MC | How do I run the unit tests and type checks? | `docs/DEVELOPMENT.md`, a `qualification` concept | `selection-workspace.md` | missing concept (corpus: AGENTS.md and `docs/*.md` excluded) | yes |
| FX-MC-03 | MC | What is the paid model spend ceiling for Sprint OC? | `sprint-oc/DECISIONS.md` (OC-D189), a future `decisions` concept | `NEXT-SESSION.md` | missing concept; stale (AGENTS.md:21 USD 100 misleads) | yes |
| FX-MC-04 | MC | Which Aura graph does Biotech ingestion write to? | a persistence/data-plane pointer concept → `docs/navigation/DATA-PLANES-AND-CREDENTIALS.md` | `WORKED-MISSION.md` (2026-10-03) | missing concept; stale annex outranks | yes |
| FX-MC-05 | MC | Which model does the Sol or Astra route resolve to? | `docs/knowledge/model-catalog.md` | `SESSION-CODEX-RESUME` | bad metadata (no route aliases) | no |
| FX-MC-06 | MC | What is the status of the Agentic SDLC program? | `agentic-sdlc-2026-11/LEDGER.md` | ADR 0064 | stale (index GROUPS omit the program); corpus | yes |
| FX-MC-07 | MC | How do I prepare the WSL2 worker host? | `docs/WSL2_WORKER_RUNBOOK.md` | GLOSSARY#Bootstrap Entrypoint | missing concept (corpus) | no |
| FX-MC-08 | MC | coordinator surface missionctl skill status | `coordinator-surface-2026-10/LEDGER.md` | ADR 0022 | missing concept (corpus; proposed `coordinator-surface` concept) | no |
| FX-MC-09 | MC | What are the open provider consolidation decisions D1-D9? | `provider-consolidation-2026-10/LEDGER.md`, `README.md` | `program-workspace.md` | stale (index.md "draft; D1–D9 open"); corpus | no |
| FX-MC-10 | MC | KnowledgeReadIntentPort | `docs/knowledge/knowledge-services.md` | (none) | tokenization (camelCase) | no |
| FX-MC-11 | MC | How does Knowledge Services verify claims and admit evidence? | `docs/knowledge/knowledge-services.md` | `expansion/WORKED-SCENARIOS.md` | ranking; stale (2026-10-03 annex unlabelled) | yes |
| FX-MC-12 | MC | KnowledgeClient HTTP out-of-process caller | `docs/knowledge/knowledge-services.md` | `wake-channels.md` | bad metadata (no aliases); ranking | no |
| FX-MC-13 | MC | style React checkout buttons | (abstain) | ADR 0012 | ranking (no abstention) | no |
| FX-KS-01 | KS | Where is knowledge.read_intent implemented? | new `knowledge-operation.md` | `service-boundaries.md` (then `schema-read`, wrong path) | missing concept; stale | yes |
| FX-KS-02 | KS | read_intent | new `knowledge-operation.md` | `schema-read-and-ingestion.md` | missing concept | yes |
| FX-KS-03 | KS | What is a knowledge operation and the K01 protocol? | new `knowledge-operation.md` | `service-boundaries.md` | missing concept | yes |
| FX-KS-04 | KS | Which ai-engineer-db-contract version is pinned? | new `schema-ownership.md` (0.5.0) | `schema-read-and-ingestion.md`; `audit` says 0.4.16 | stale (`config.json:578`, `CODE-MAP.md:404,452`) | yes |
| FX-KS-05 | KS | How do I run the tests and typecheck? | new `operations.md` | `evaluation-and-publication-gates.md` | missing concept | yes |
| FX-KS-06 | KS | What did OVE-204 provenance sprint change in Knowledge Services? | new `knowledge-operation.md`, `decisions.md` | `verification-and-admission.md` (`ove` only) | missing concept; tokenization | yes |
| FX-KS-07 | KS | How does KS verify credentials minted by Mission Control? | new `knowledge-operation.md` | `service-boundaries.md` | missing concept | no |
| FX-KS-08 | KS | What are the retrieval benchmark recall and MRR gates? | new `retrieval-benchmark.md` | `evaluation-and-publication-gates.md` | missing concept (fixture README only) | no |
| FX-KS-09 | KS | Does ingestion write an outbox or operation row? | `schema-read-and-ingestion.md` (updated), `knowledge-operation.md` | `schema-read-and-ingestion.md` (silent); AGENTS.md:32 stale | stale | yes |
| FX-KS-10 | KS | AIDB typed columns preflight and per-input effects | `knowledge-operation.md` / `schema-read-and-ingestion.md` | `jev-decisions-and-workers.md` | missing concept | no |
| FX-KS-11 | KS | receipt targets and report_v2 projection | `schema-read-and-ingestion.md` (updated) | `verification-and-admission.md` | stale (evidence `changed`) | no |
| FX-KS-12 | KS | Which environment variable holds the database URL? | new `operations.md` | `preparation-and-publication.md` | missing concept | no |
| FX-KS-13 | KS | What does the Biotech graph binding implement? | new `applications-and-bindings.md` | `service-boundaries.md` | missing concept | no |
| FX-KS-14 | KS | What was decided about embedding retrieval decision gates? | new `decisions.md` → ADR 0015 | `preparation-and-publication.md` | missing concept (ADRs 0005–0015 unindexed) | no |
| FX-KS-15 | KS | Where are the architecture decisions recorded? | new `decisions.md` | `jev-decisions-and-workers.md` | missing concept; ranking ("decisions" in the title) | no |
| FX-KS-16 | KS | What is the current implementation state of KS? | new `goals.md` / `docs/architecture/current-state.md` | `service-boundaries.md` | missing concept (corpus) | no |
| FX-KS-17 | KS | How do I deploy or operate the verification executor runbook? | new `operations.md` | `verification-and-admission.md` | missing concept (corpus) | no |
| FX-KS-18 | KS | Selection Workspace | (abstain; or a pointer to MC) | `preparation-and-publication.md` | ranking (no abstention) | no |
| FX-KS-19 | KS | What gates semantic judging? (existing `verification-and-admission-2`) | `verification-and-admission.md` | `evaluation-and-publication-gates.md` (rank 6) | ranking (regression from 2026-10-15) | no |

## 5. What the two engines do differently that is worth keeping

1. **KS `context` evidence freshness.** Each result returns its sections, up to 24 evidence files,
   each with `unchanged`/`changed`/`missing`/`untracked`, plus module entrypoints and tests and
   status-labelled architecture routes. This is the only mechanism in either repo that noticed the
   OVE-204 drift (4 changed files under `schema-read-and-ingestion`). Keep it. Extend it so a
   concept with changed evidence reports `conceptFreshness: stale`, and so `search` carries the flag.
2. **KS metadata and weights.** `aliases` (5) and `questions` (4) are weighted, camelCase is split,
   and the status fields (`implementation_status`, `validation_status`) are in frontmatter. Seed the
   shared ranking with these, as SPEC-01 §12.3 recommends.
3. **KS benchmark shape.** Screening, heldout and negative partitions, critical flags, LF-normalized
   digests, and baseline-vs-current engines in one run. Adopt it as the fixture format; add `--gate`.
4. **MC index notes** (`docs/agents/index-notes.toml`). One line per directory that says what the
   folder is for and how far to trust it ("statuses stale since 2026-10-03", "nothing built"), with
   the compiler failing on a missing note. Keep it, and invert the check: a note for a directory
   the compiler does not index must also fail.
5. **MC `okf_search` explicit entrypoints.** The three named Sprint OC files in `DEFAULT_ROOTS`
   make "W1 status" rank NEXT-SESSION first (MC-02) without indexing all specs. Generalize this to
   "files named by an active ledger", so the list cannot go stale by hand.
6. **MC glossary terms as documents.** `GLOSSARY.md#Read Intent` and `#Selection Workspace` rank
   first, with the Avoid list attached. This is the strongest MC feature in the log (MC-06, MC-07,
   MC-29). ADRs as first-class documents also answered every "what was decided" question (MC-11,
   13, 21, 25). KS indexes neither its glossary nor its ADRs.
7. **MC `--root` and `--type`.** These turn most MC misses into 2-hop answers. Both engines should
   print the next hop ("not in default corpus; try `--root <ledger dir>`") when the score is low.

## 6. Top 5 fixes ranked by expected retrieval gain

1. **Corpus scope from ledgers and registries** (about 13 of 30 misses; 6 of the 10 critical
   cases). MC: index every document an active ledger marks `active`, plus `docs/*.md` operator
   guides and the hand-written `AGENTS.md` sections. KS: register ADRs 0005–0015,
   `docs/operations/runbooks.md`, `docs/architecture/current-state.md` and the fixture README.
   Closes FX-MC-01, 02, 06, 07, 08, 09 and FX-KS-14, 15, 16, 17.
2. **Author the missing concepts for recent and cross-cutting facts** (about 12 misses, 7 critical).
   KS: `knowledge-operation` (K01, `knowledge.read_intent`, receipt targets, `report_v2`, producer
   origin, MC credential verification), `operations`, `schema-ownership`, `decisions`, `goals`,
   `applications-and-bindings`. MC: `decisions` (spend rule OC-D189, open D1–D9, the ADR route), a
   data-plane pointer concept to the workspace registry, `goals`. Closes FX-KS-01 to 13 and
   FX-MC-03, 04.
3. **Make freshness checks truthful and blocking.** The expected gain is preventing regressions;
   the stale class covers 6 cases now.
   - KS: rebuild provenance; fix `config.json:578` and `CODE-MAP.md` (0.5.0) and `AGENTS.md:7,32,74`;
     make `check` name each concept whose evidence changed.
   - MC: derive `GROUPS` from `index-notes.toml` or the ledgers instead of `agents_docs_index.py:36-80`.
   - MC: date-stamp concepts.
   - MC: label or exclude the 2026-10-03 expansion annexes in default ranking.
   - MC: collapse the 5.8 KB of dated `AGENTS.md` preambles into one status line that links
     NEXT-SESSION.
4. **Shared ranking and metadata** (about 6 misses: FX-MC-05, 10, 11, 12, 13, FX-KS-18).
   - Add `aliases`/`questions` to MC's 66 concepts and to `okf_search` (KS weights).
   - Split identifiers the same way in both engines: camelCase, `_` (keeping the whole token), `-`,
     and `.`.
   - Add an abstention floor: require ≥ 50% of query terms matched, or a minimum score relative to
     the corpus.
5. **Fixture gate** (protects every gain above). Freeze the KS format; turn this audit's 62
   questions into the first MC set and new KS heldout cases (§4), with answer-verified labels; run
   `bench --gate` in `check`. The 18/18 → 17/18 KS screening regression would have failed it.
