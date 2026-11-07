---
type: Decision Record
title: "One vendored SDLC toolchain per repository, upstream in platform/agentic-sdlc"
description: "Accepted 2026-11-01 (AS-D1, AS-D4, AS-D5, AS-D9): every BellLabs repository satisfies one documentation contract enforced by one dependency-free CLI that is vendored and pinned into the repository; platform/agentic-sdlc is the upstream and never a runtime dependency; Mission Control's Python docs tools and the Knowledge Services .agent-docs lineage are retired at parity."
tags: [mission-control, adr, accepted, documentation, sdlc, architecture]
status: accepted
source: docs/specs/agentic-sdlc-2026-11/answers/AGENTIC-SDLC-SITTING-I-2026-11-01-ANSWERS.md (AS-D1, AS-D4, AS-D5, AS-D9); docs/specs/agentic-sdlc-2026-11/SPEC-01-AGENTIC-SDLC.md
---

# One vendored SDLC toolchain per repository, upstream in platform/agentic-sdlc

**Status: accepted 2026-11-01.** Nothing is built; the issues are in the Agentic SDLC Linear project.

**Amends [ADR-0021](0021-documentation-retrieval-okf-plus-compressed-index.md) (tooling):** Mission Control's Python docs tools are retired at parity; ADR-0021's concept bundle and retrieval evals stay.

## Context

Two documentation systems grew side by side: Mission Control's OKF bundle with Python checks, and
the Node agent-docs generator used by Knowledge Services and AI Engineer, with its own config,
generated blocks and retrieval benchmark. The codebases are large and growing, agents are the
primary developers, and the owner judged retrieval and documentation writes critical to the health
of the whole. The owner also required that a repository work alone: "I need to be able to be
inside mission-control alone and not depend on platform/agentic-sdlc."

## Decision

One contract, one implementation. The contract (concepts with nine categories, ADRs, GLOSSARY,
generated AGENTS.md blocks at root and module level, program ledgers, retrieval fixtures) is
enforced by one CLI, a single dependency-free Node file vendored into every repository under
`.sdlc/` and pinned by `.sdlc/lock.json`; the skills are vendored under `.agents/skills/` and
pinned by `skills-lock.json`. `platform/agentic-sdlc` (GitHub `jbell-rusty-vantage/agentic-sdlc` since 2026-11-06)
is the upstream of the CLI, the skills, the hook templates and the ideas workspace; no hook, check,
search or build reaches outside the repository. Updates are pulled by decision with `update`.

## Considered options

Two implementations behind one conformance fixture (rejected: the owner wants one); the Node
generator or the Python tools extended in place (rejected: neither is self-sufficient today and
the design should come from the agreed components, not from either lineage); the tooling inside
Mission Control (rejected: couples every repository's docs build to one checkout).

## Consequences

Mission Control's `docs/tools/*.py` and Knowledge Services' `.agent-docs/` and `tools/maintenance`
are retired only at proven parity. Every repository gains `.sdlc/` and the moves named in SPEC-01
§3.2. A repository can be cloned into a cloud environment or CI and pass every gate without
network access.
