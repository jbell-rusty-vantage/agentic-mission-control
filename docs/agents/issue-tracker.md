---
type: Agent Configuration
title: "Issue tracker: Linear"
description: "Issues and specs for Mission Control live in Linear: workspace overtonbell, team OVE, project Mission Control (https://linear.app/overtonbell). Brainstorms start as local markdown and are promoted to Linear issues; the…"
tags: [mission-control, agents, process]
---
# Issue tracker: Linear

Issues and specs for Mission Control live in Linear: workspace `overtonbell`, team `OVE`, project **Mission Control** (`https://linear.app/overtonbell`). Brainstorms start as local markdown and are **promoted** to Linear issues; the Linear issue is the canonical record once it exists.

## Access

- **Claude Code**: the `linear` MCP server in `.mcp.json` (HTTP, `https://mcp.linear.app/mcp`). Authenticate once with `/mcp`.
- **Codex**: `[mcp_servers.linear]` in the workspace `../.codex/config.toml` (OAuth).
- **Cursor**: the `linear` entry in the user-level `~/.cursor/mcp.json` (`mcp-remote`).
- **Fallback for scripts**: the Linear GraphQL API (`https://api.linear.app/graphql`) with `LINEAR_API_KEY` from `.env`. Read the key from the file; never print it, paste it, or commit it.

Prefer the MCP tools when they are available in the session. The GraphQL operations below are the equivalents for scripts and for sessions without MCP.

## Conventions

- **Create an issue**: team `OVE`, project `Mission Control`, one category label (`Bug` or `Feature`, see `triage-labels.md`) and one state label. The description's first line is `Goal: platform/mission-control/goals#<anchor>`, an anchor of [goals](../knowledge/goals.md) (AS-D23). GraphQL: `issueCreate(input: {teamId, projectId, title, description, labelIds})`.
- **Read an issue**: by identifier (`OVE-123`). GraphQL: `issue(id: "OVE-123") { title description state { name } labels { nodes { name } } comments { nodes { body } } relations { nodes { type relatedIssue { identifier } } } }`.
- **List issues**: filter by project, state and labels. GraphQL: `issues(filter: {project: {name: {eq: "Mission Control"}}, labels: {name: {in: [...]}}})`.
- **Comment**: `commentCreate(input: {issueId, body})`.
- **Labels**: `issueUpdate(id, input: {labelIds})`; read the current set first and add or remove from it.
- **Close**: move to the team's `Done` state (`issueUpdate(id, input: {stateId})`), or `Canceled` for `wontfix`.
- **Sub-issues**: `parentId` on create, or `issueUpdate(id, input: {parentId})`.
- **Blocking**: Linear's native relation. `issueRelationCreate(input: {issueId: <blocker>, relatedIssueId: <blocked>, type: blocks})`. A ticket is unblocked when every blocker is `Done` or `Canceled`.

## Pull requests

**PRs as a request surface: no.** `/triage` reads this flag; pull requests are not feature requests here, so they do not enter the triage queue.

## Program issues

Work that belongs to a program under `docs/specs/` is filed in Linear before it starts, and its id is written in the program's `LEDGER.md` row. Nothing is back-filled. Rules and ledger mechanics: [program-workspace.md](program-workspace.md).

## Provenance

Every issue carries a `## Provenance` section so the issue knows where its content came from. Since 2026-11-17 it is one `Key: value` line per key, so `docs/tools/trace.py` can parse it ([SPEC-02](../specs/agentic-sdlc-2026-11/SPEC-02-PROVENANCE-CHAIN.md#records)). Write the keys that apply; at least one must resolve. No separate database is used for this; the links are the record.

```markdown
Goal: platform/mission-control/goals#S3, IG1

...body and acceptance...

## Provenance

Session: AS-S3
Decisions: AS-D40, AS-D41
Spec: mission-control:docs/specs/<program>/SPEC-NN-<topic>.md#<anchor>
ADR: ADR-0064
Idea: ID-1
Conversation: claude-code:<session-uuid>
Terms: <GLOSSARY.md terms the issue relies on>
```

When a local draft is promoted, add `Linear: OVE-NNN` near the top of the local file and keep the file; the issue links back to that path. Mission Control's own `authoring_session` records can later cite the Linear identifier for missions that originate from an issue.

<a id="completion"></a>
## Completion

When an issue's work is done, post one comment before moving it to `Done`. It closes the chain, and `trace check` flags a completed issue without it.

```markdown
## Completion

Commits: mission-control@abc1234, mission-control@def5678
Checks: make check passed; uv run pytest tests/unit/docs_tools passed; make test-integration unrun (no stack)
Evidence: <path, run id, or none (reason)>
Level: tested
Verified-by: self
```

`Level` is one of `implemented`, `tested`, `integrated`, `qualified` (the four labels of the invariants). `Verified-by` is `self` unless an independent session or person checked the evidence.

## Commit trailers

Every commit ends with `Refs:` naming the issue or the record it serves (`OVE-n`, `AS-S3`, `AS-D40`, `ADR-NNNN`, `ID-n`, or `none <reason>` for a chore), plus `Decisions:` and `Docs:` when they apply ([SPEC-02 §3](../specs/agentic-sdlc-2026-11/SPEC-02-PROVENANCE-CHAIN.md#trailers)). The commit-msg hook warns when they are missing.

## Local drafts

Brainstorms, specs and ticket drafts that are not yet promoted live under `.scratch/<feature-slug>/`:

- The spec is `.scratch/<feature-slug>/spec.md`.
- Draft tickets are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`.
- A `Status:` line near the top records the triage state; a `Blocked by:` line records draft dependencies.

`.scratch/` is not committed. A draft is disposable until promoted.

## When a skill says "publish to the issue tracker"

Create a Linear issue as above, with the `Goal:` line and the `## Provenance` keys. If the user asks for a draft first, write the local file and promote later.

- **A spec** (`to-spec`): write it in the repository first, under the owning program (`docs/specs/<program>/SPEC-NN-<topic>.md`, frontmatter `decisions: [...]` and `linear: [...]`, a ledger row), then create the parent issue whose `Spec:` key points to it. The spec text lives in git, not only in Linear.
- **Tickets** (`to-tickets`): sub-issues of that parent, each repeating the parent's `Session:` and `Spec:` keys and naming the decisions it implements.

## When a skill says "fetch the relevant ticket"

Read the Linear issue by identifier, including comments and relations. If given a `.scratch/` path, read the file.

## Wayfinding operations

Used by `/wayfinder`. The **map** is one Linear issue; **children** are its sub-issues.

- **Map**: an issue labelled `wayfinder:map` holding the Notes / Decisions-so-far / Fog body.
- **Child ticket**: a sub-issue of the map, labelled `wayfinder:<type>` (`research`, `prototype`, `grilling`, `task`). Create the `wayfinder:*` labels on first use.
- **Blocking**: native `blocks` relations between children.
- **Frontier**: open children with no open blocker and no assignee; first in map order wins.
- **Claim**: assign yourself, before any work.
- **Resolve**: comment the answer, move to `Done`, then append a context pointer (gist + link) to the map's Decisions-so-far.
