---
name: mission-control-docs
description: Look up Mission Control knowledge before asserting it. Use when a task names missions, runs, revisions, activations, workflow systems (Stage Graph, Goal Loop, Parallel Swarm, Evaluator Optimizer), harness or lanes, capabilities or the catalog, Agent Server, mission-db, Temporal, outbox, effects, checkpoints, forks, or any term you cannot define from GLOSSARY.md.
---

# Mission Control docs

Retrieval-led, not pretraining-led: Mission Control vocabulary and contracts are project-specific and recent.

1. Search the corpus: `python docs/tools/okf_search.py "<two to five terms>" --limit 6`. Glossary terms, ADRs, OKF concepts, research notes and the module `AGENTS.md` guides are ranked together (`--programs` adds active program documents). Narrow with `--type "Decision Record"` or `--type Concept` when the hit list is noisy.
2. Open the top hit before answering. A glossary hit (`GLOSSARY.md#Term`) gives the canonical word and its Avoid list; an ADR gives the decision and why; a concept under `docs/knowledge/` points at the code and tests; a module guide names the closest code and the checks.
3. Answer in glossary terms and cite the path you read.

Authority when documents disagree: the code is what runs, `docs/adr/` is what was decided, `docs/knowledge/` explains both, and program ledgers are working documents. Report the disagreement instead of picking silently.

The compressed index in `AGENTS.md` lists every document by directory; use it to jump straight to a file when you already know which one you need.
