---
type: Decision Record
title: "Agent-facing documentation is an Open Knowledge Format bundle plus a compressed index embedded in AGENTS.md, measured by retrieval evals"
description: "Explanatory documentation lives as Open Knowledge Format concepts (one concept per file, YAML type, title, description and tags) under docs/knowledge/, with the normative spec pack kept in place and given the same…"
tags: [mission-control, adr, decision]
status: accepted
source: interview 2026-10-07 (Q16, Q17); Vercel, "AGENTS.md outperforms skills in our agent evals" (2026)
---

# Agent-facing documentation is an Open Knowledge Format bundle plus a compressed index embedded in AGENTS.md, measured by retrieval evals

**Status: accepted 2026-11-01; implemented by `docs/knowledge/`, `docs/tools/okf_search.py` and `docs/tools/agents_docs_index.py` (`f90daeeb`, 2026-10-07); the tooling part is amended by ADR-0064.**

**Amended by [ADR-0064](0064-one-vendored-sdlc-toolchain-per-repository.md) (tooling):** the Python documentation tools retire at parity with the vendored SDLC toolchain; the OKF concept bundle and the retrieval evals stay.

Explanatory documentation lives as Open Knowledge Format concepts (one concept per file, YAML type, title, description and tags) under `docs/knowledge/`, with the normative spec pack kept in place and given the same frontmatter. A generated, compressed index of every concept, ADR, glossary and spec file is embedded in `AGENTS.md` between markers, so that the agent always knows where documents are without loading them, and a search skill covers the cases the index does not. We chose passive index plus searchable corpus over skills-only after Vercel's evals showed skills are invoked unreliably, and we keep a retrieval experiment (`experiments/docs_retrieval/`) so the choice is re-measured rather than assumed.
