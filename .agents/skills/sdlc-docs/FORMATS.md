# Formats

## Concept (`docs/knowledge/<name>.md`)

```yaml
---
type: Concept
category: execution            # one of the nine
title: <what it answers, in the words an agent would search>
description: <one or two sentences: scope, what is built, what is not>
tags: [..]
aliases: [2-5 other names an agent might use]
questions:                     # >= 3; questions[0] <= 70 chars, becomes the index line
  - How is the Deep Agents lane compiled, materialized and observed?
  - ...
updated: YYYY-MM-DD
---
```

- At most 160 lines. Ends with `## Citations` whose relative links resolve.
- Explains why it works this way, the contract, the lifecycle, the refusals; cites `path:line`.
- Where a workflow or runtime mechanism applies, cover in order: scheduling, output-contract
  obligations, context transfer, runtime and capability configuration; end with one line
  `Built / specified / goal: ...`.
- Snippets of important deep-module interfaces are allowed to illustrate, each under ~15 lines and
  preceded by `<!-- snippet: path:start-end -->` so a check can compare it with the source.
  Manifest, YAML and command examples are allowed. File-role inventories belong in module guides.
- Refer to retrieval fixtures by id only; a concept that repeats a case's words answers its own test.
- A rename or merge deletes the absorbed file and rewrites every inbound link in the same change.

## Research note (`docs/research/<subject>/<slug>.md`)

```yaml
---
type: Research
subject: deepagents           # library, provider or technology
versions: ["deepagents 0.7.5"] # the exact pins it covers
sources: [<urls or docs>]
observed: YYYY-MM-DD
confidence: high | medium | low
used_by: [<modules or concepts that depend on it>]
---
```

Facts about the outside world only. When a pin in the lock file moves past `versions`, the note is
re-verified. Code that cites a note must cite one that exists.

## Retrieval fixture case (`.sdlc/fixtures/retrieval/queries.json`)

```json
{"id": "T001", "kind": "query|task", "partition": "screening|heldout|negative",
 "query": "...", "task": "...",
 "expect": {"concepts": [], "modules": [], "research": [], "facts": []},
 "critical": true}
```

- `query` cases score recall@3, recall@10 and MRR; `task` cases score set recall per `expect` field.
- Screening cases guide tuning; held-out cases are reported separately and never tuned against;
  negative cases should return nothing.
- The author of a concept adds questions for it; every audit miss becomes a case; a real near-term
  engineering task becomes a task case.
- Baselines (`baseline.json`) move only in the same change as the concept change that moved them.

## ADR status

`proposed` until built or explicitly accepted; `accepted YYYY-MM-DD; implemented by <commit or
release>` once true; `superseded by NNNN` with a back-marker in the newer ADR. Every accepted ADR is
cited by a concept or by the `decisions` concept.
