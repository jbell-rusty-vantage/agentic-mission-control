---
name: ai-engineer-knowledge-charter
description: AI Engineer knowledge base purpose, source tiers, repository rules and paper levels, loaded before researching, verifying or ingesting AI engineering knowledge and paired with knowledge-research for the method.
---

# AI Engineer knowledge charter

The AI Engineer knowledge base serves a research, ingestion and education service about AI engineering, which its owner uses himself. Its first course is the comparative agent-orchestration course, so coverage is comparative: study every framework the course compares.

It records who builds what, on which models, protocols, libraries and papers, with which evidence. Every record must answer: **who said this, where, at which version, and how well is it supported.**

This charter adds the domain's sources and depth rules. **Load the knowledge-research skill for the method** (the loop, queries, tools, verification, handback). It ships with Knowledge Services, not with this service; [Availability](#availability) says where each part is reachable. Find current kinds, relations and named queries with the schema navigation tools; this charter names none.

## What belongs, and how it is shaped

- **Plan before you acquire.** Name each intended subject with its kind and each relationship with its kind. *Done when* every planned relationship's two ends are kinds that relationship allows.
- **Kinds come from the vocabulary.** A primary type is a kind. A secondary division (agent framework or inference runtime; research lab or commercial company) is a subtype term. Independent properties (modality, access, deployment, lifecycle) are separate facets. A missing kind is a contract change outside a mission: report it.
- **An organisation is separate from its product families, products, versions and features.** A bigger company means more records, not a different shape.
- **A protocol is a protocol,** not a product. MCP and A2A are protocols.
- **A benchmark number is a dated observation** with its dataset, metric, setting and denominator. It is never a property of a model.

## Source tiers for this domain

| Source tier | Here that means |
| --- | --- |
| T0 | Verified claims in this knowledge base |
| T1 | Our courses, guides, reports and dataset cards |
| T2 primary | Vendor documentation, changelogs and pricing pages; model cards and system cards; papers; official repositories; package registries; first-party talks; a lab's engineering blog writing about its own systems |
| T3 third party | Comparison articles, newsletters, practitioners' posts, issue trackers of dependent projects, forums, question-and-answer sites |
| T4 | The live web |

The owner's priors: the best sources are the conference archives and series, the labs' engineering blogs, the practitioners whose track records hold up, and the repositories that matter. A prior is a starting point. Checked claims move it.

Domain cautions:

- **A talk title or slide heading is a claim candidate,** with the speaker's role and the timecode. It is never a fact.
- **A panel transcript without speaker labels** is cited as the panel. Say that speakers are not identified.
- **Model pages and system cards change after launch.** Always record the date observed.
- **A post or newsletter dates when we learned something. A first-party page dates when it holds.**
- **Marketing language about capability or outcome is a claim** to assess, even on a first-party page. Identity (names, versions, dates) comes from official catalogs, documentation, release pages and registries.
- **Pin everything:** a repository fact to a full commit, a paper to an exact version, a release to a version and a date.

<a id="repos"></a>
## Repository rules

| Rule | Content |
| --- | --- |
| R1 | The repository is a thing with releases. Its facts sit on it: licence, language, package name, declared dependencies with their version constraints, and counts as dated observations. The file tree is reachable by locator (commit, path, lines) and is never ingested in bulk |
| R2 | Capture only the knowledge-bearing surfaces, at each release tag: README, documentation, changelog or release notes, package manifests, the public interface, schema files, examples, the security policy, the licence. Record everything else as skipped, with counts |
| R3 | Extract public symbols deterministically for each release, keyed by qualified name. Symbols added, removed or changed between releases are the evidence of a breaking change |
| R4 | Documentation is the explanation layer over symbols. Link a documentation section to the symbol it documents, with its version note. A section with no symbol and no release explains a concept |
| R5 | Issues, pull requests and discussions are claim candidates, not content. When a question needs one, the thread becomes a claim candidate, and guidance only after verification. Their counts are observations |
| R6 | Set a cap per repository per release before starting: extracted items, captured text, and symbols from the top-level public package only. Over the cap, keep README, changelog and manifest, and record the rest as skipped. Write down the cap you used |
| R7 | Acquire through the repository host's content and release interface and the release archive, over plain HTTPS, recorded as fetches. Parse locally and in isolation |

<a id="papers"></a>
## Paper levels

| Level | What is kept | When |
| --- | --- | --- |
| P0 Reference | The paper as a thing: title, authors, venue, date, identifiers, links to code and data, and who cites it. No capture | Any paper mentioned by an ingested talk, repository, documentation page or paper |
| P1 Digest (default) | P0, the abstract and conclusion, and a structured digest: problem, method, key results (each number a benchmark-observation candidate with its conditions), limitations, artifacts, and what it changes for practitioners as claim candidates. The full text is captured for locators only | Every paper selected for a course, a report or a question |
| P2 Full | P1 and the complete structure: sections, figures, tables, captions, claim sentences, references | By promotion only: cited by one of our modules or guides, listed as a talk's resource, needed by a decision question, or chosen by the owner |

- First-party **model cards and system cards are P2 by default**: their evaluation tables are facts about the model as stated by its maker.
- **Technical reports** follow the paper levels.
- **Case studies** are P1, source tier T2 or T3, claim candidates only. They never produce a fact without a first-party locator.
- **Promotion is a recorded decision:** the level, who decided, and why.

## Checks on libraries

- A probe's cells are **dates**: the environment a learner who followed a tutorial written that day would have got. Include the day before a major release.
- Use a deterministic fake model unless the check is a labelled live arm.
- When a watched library releases, the checks that cover it are due again.

## Restatement, in this domain

Community claims arrive as "the post states that X". A check proves X, not what a post says. Before admission, restate: drop the attribution, drop any half the check did not test (for example "and the docs do not mention this"), write a shown qualification into the statement, and have a person confirm the wording. The original stays as the record of what the source said. Detail: the verification reference of the knowledge-research skill, under restatement.

## Writing to the knowledge base

You propose; the governed knowledge tools write. Ingestion is proven by an admitted decision and its receipt. A preview, a verification result or a finished run is evaluation, not ingestion.

<a id="availability"></a>
## Availability, checked 2026-11-16

Checked against the AI Engineer service source. Lines marked "outside this service" come from Mission Control and Knowledge Services records of 2026-11-15 and were not re-checked here.

- **This charter** is served by the AI Engineer service guide as the topic ai-engineer-knowledge-charter (`aieng_guide`, `aieng guide`) and ships in the service's skills folder. Missions still receive the older charter shipped with Mission Control, which names retired schemas and fixture-only tools (outside this service).
- **The knowledge-research skill** is not served by this service. It lives in the Knowledge Services skills folder; an agent without that folder has this charter and no method skill.
- **Reading the knowledge base through this service:** `search_knowledge` (keyword search over the corpus and the evidence), `inspect_knowledge` (one claim with its verdicts and probe cells, an entity card or library dossier, the evidence behind a fact or a summary, an entity's changes, a source's assessments and track record, what is due) and `schema_search` with `schema_get` for kinds, relations and named queries. The CLI has the same reads: `aieng knowledge search`, `aieng knowledge claim`, `aieng knowledge entity`, `aieng knowledge source`, `aieng knowledge due`, `aieng schema search` and `aieng schema get`.
- **Citing it in authored content:** a lesson binds a verified claim to the block that states it, and a statement can name the shared claim it restates; `inspect_authoring` reads both back (lab, 2026-11-16).
- **Not in this service:** web search, capture, verification, restatement, admission and every write to the knowledge base. The governed knowledge tools belong to Knowledge Services and reach an agent through a mission. Here you can read, and you can request research with `propose_research`, which a person accepts.
- **Seeded for AI Engineer missions** (outside this service): Tavily, Firecrawl, the browser, and SEC filings through `mcp.edgartools`. GitHub, arXiv's own interface and Context7 exist only as test fixtures. See the routing reference of the knowledge-research skill.
- **Conference archive:** on 2026-11-08 the AI Engineer conference published machine-readable talks: an archive search server, per-edition session and speaker lists, and each talk page as Markdown with slides and a timestamped transcript without speaker labels. Re-check before relying on it.
- **Not swept:** Reddit and X are at watch level W0 by owner decision of 2026-11-13 (terms not reviewed; noise).
- **Default R6 cap in the accepted rule:** about 400 extracted items and 2 MB of captured text per repository per release. Loop 3 raised it deliberately for a "fully ingest" exercise.
- **Verified so far:** 27 claims, all on the disposable lab, about the LangChain, LangGraph and Deep Agents migration. Nothing is on the remote database.
