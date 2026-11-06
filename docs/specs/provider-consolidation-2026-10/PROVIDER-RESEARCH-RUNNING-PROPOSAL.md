---
type: Proposal
title: "Provider research as a running proposal: what a supplement records, what to automate, and the improvement register"
description: "Provider documentation here is research, not a copy: it resolves hard-to-discern, lesser-known and recent facts with evidence, and ends in proposals for the current system. Defines what a provider supplement may contain, the evidence fields, the staleness rule, the automation tiers (detectors that produce a digest, a research session that resolves it, probes that turn claims into checks, and a human gate that promotes proposals), the first small increments, and the running improvement register seeded from the Deep Agents surface sheet. Draft of 2026-10-23; nothing automated yet."
tags: [mission-control, providers, research, proposal, automation, deep-agents]
---
# Provider research as a running proposal

**Status: draft, 2026-10-23. Running: edit the register, not the history.** Nothing here is built. It records the owner's goal and the smallest honest path to it.

The owner's words, 2026-10-23: "We aren't duplicating the provider's documentation. We are resolving and documenting complex things, lesser known things, up to date things. This should end in a proposal for our current system. Consider this a running proposal."

## 1. What a provider supplement is

A dated sheet per provider ([the Deep Agents sheet](providers/deep_agents/DEEP-AGENTS-SURFACE-2026-10-22.md) is the first). It records a fact only when it is one of these, and links the provider's documentation for everything else:

| Why it earns a line | Test |
| --- | --- |
| **Source-only** | The behavior is visible only in the package source, not in the docs |
| **Scattered** | Answering needs three or more pages, a changelog and an issue put together |
| **Contradicted** | Documentation and behavior disagree, or two documents disagree |
| **Recent** | It changed after our pin; the line says what, since which version |
| **Probed** | We ran a small experiment and the result surprised us |

Each finding carries: an id (`DA-12` for Deep Agents), the claim in one sentence, a label, a citation (URL, or `path:line` in a pinned wheel), the version it was read against, the date, and either `no impact` or an improvement id (`IP-n`). Labels extend the sheet's existing four: **[SRC]** read in source, **[DOCS]** read in documentation, **[ISSUE]** a maintainer statement in an issue or pull request, **[PROBE]** observed by running something (with the probe's path), **[INF]** our inference, **[NF]** looked for, not found, **[COMMUNITY]** a blog, forum or social post (see O-4).

**Staleness rule.** Front matter carries `as_of` and `pins` (package to version, as in `pyproject.toml`). A supplement whose `pins` differ from the repository's pins is stale, and its ledger row says so.

## 2. What to automate

The principle: **machines detect and verify; an agent resolves; the owner decides.** No automation edits a supplement's claims or a contract unattended.

| Tier | What | Output | Cost |
| --- | --- | --- | --- |
| **0. Detectors** (deterministic) | Pin versus latest for each provider package (PyPI JSON; GitHub releases for CLIs and SDKs). Release notes since our pin. A change in watched documentation pages (a list per provider). Public-API diff between the installed wheel and the latest (what the Deep Agents sheet's §1.3 did by hand: unpack both wheels, compare exports and signatures). Status changes of the issues and pull requests a supplement cites | A **digest** per provider: what moved since `as_of`, nothing more | Free; seconds |
| **1. Research session** (agent, on a digest or at the start of a provider sprint) | Takes each digest item, resolves it against primary sources, writes findings with the fields above, marks the lines it supersedes, drafts register entries | An updated dated sheet and register diff, reviewed like any change | Tokens only; no provider spend |
| **2. Probes** (deterministic, offline first) | A claim labelled [PROBE] ships a small runnable check. On a version bump the probes rerun; a failing probe means a finding went stale | Red or green per finding | Free offline; paid probes need the owner's authorization and the 15 USD session cap |
| **3. Promotion** (human gate) | An improvement becomes a ledger proposal row, then an `OVE` issue once the owner accepts it | Ledger rows; Linear issues | Owner attention |

Not automated, on purpose: deciding that something is hard to discern or worth a line; changing a contract, ADR or lane declaration; any paid run.

**Triggers (owner, 2026-10-23).** Time-based, not event-based: a schedule (weekly to start), plus on demand for one lane and at the start of a provider sprint. A pin change is read by the next scheduled run rather than triggering one.

**Where it runs (owner, 2026-10-23).** Detectors are scripts in `scripts/dev/` following `check_matt_pocock_skills.py` (stdlib, read-only, nonzero exit on drift). The research session is an **agent skill of ours (`provider-research`) that any coding agent can run** (Claude Code, Cursor, Codex) with the tools they have: Tavily, Firecrawl, Context7, GitHub and the local terminal. None of those agents schedules natively, so scheduling is a thin wrapper around the agent's CLI or SDK run by a **local cron** first, remote later. When Mission Control is mature and complete this becomes an automated mission.

## 3. First increments

Each is small, independent and reversible. None is started.

1. Add `as_of` and `pins` front matter to the Deep Agents sheet, and a check that compares `pins` with `pyproject.toml`.
2. Detector for pin versus latest, printing the digest header. Start with `deepagents`, `langchain`, `langgraph`, `langgraph-api`, `temporalio`.
3. A watch list per provider (`docs/agents/provider-watch.toml`: package, repository, documentation pages, cited issues).
4. The `provider-research` skill: digest in, findings and register diff out, following the evidence fields above.
5. A probes folder for [PROBE] findings, wired into the offline suite.
6. The schedule: a wrapper script that runs the skill through an agent CLI or SDK, and a local cron entry.

## 4. Owner decisions (2026-10-23)

| ID | Question | Decision |
| --- | --- | --- |
| O-1 | Where do generated digests live? | Not committed; under `.scratch/`. Only the resulting sheet and register are committed |
| O-2 | Which provider goes first? | Deep Agents |
| O-3 | Who runs tier 1? | An agent skill that any coding agent can run with its tools (Tavily, Firecrawl, Context7, GitHub, terminal), on a schedule through a CLI or SDK wrapper and a local cron to start; a Mission Control mission once the product is mature. Time-based, not event-based |
| O-4 | May community posts count as sources? | Yes, only when labelled `[COMMUNITY]` and extremely pertinent. The bar is very high for letting a community source be any part of the reasoning for a change to our system; it is never the sole citation of a claim |

## 5. Improvement register

Running. One row per proposal for the current system; evidence points into the sheet it came from. `draft` means no owner decision yet. When the owner accepts a row it becomes a ledger proposal row and an `OVE` issue; rejected rows stay with the reason.

| ID | Provider | Proposal for the current system | Evidence | Lands in | Status |
| --- | --- | --- | --- | --- | --- |
| IP-001 | Deep Agents | Upgrade `deepagents` 0.7.5 to 0.7.30 with the langchain and langgraph floors; retest the governed async wrappers, whose output shape changed | Sheet §1, §1.5 items 1-4 | Sprint A | draft |
| IP-002 | Deep Agents | Hide the three private-API imports behind one seam and cover it with a probe, so a release cannot move them silently | Sheet §1.5 item 5 | Sprint A | draft |
| IP-003 | OpenAI | Set `ProviderStrategy` (or a model profile) explicitly for the GPT-6 models whenever native structured output is required; they are not in the fallback pattern list | Sheet, Implications, Provider-specific 4 | Output contracts (OC-1) | draft |
| IP-004 | Deep Agents | Make `write_todos` an explicit mission flag instead of an implicit default, and publish the capability list by category as selectable | Sheet, Implications, Tooling 4 and the category lists | Sprint B | draft |
| IP-005 | Deep Agents | Gate `eval` of dynamic subagents, since a dispatch inside it bypasses human-in-the-loop | Sheet, Implications, Subagents 6 | Sprint R | draft |
| IP-006 | Deep Agents | Decide, per state key, whether a child's writes merge back to the parent; the library copies more keys into children than Mission Control intends | Sheet §1.5 item 4; Implications, State 4 | Sprint OC-2 | draft |
| IP-007 | Deep Agents, Temporal | Decide whether `temporalio.contrib.deepagents`, installed but unused, is a future durability model or stays out; record the choice as an ADR either way | Sheet, Implications, Persistence 4 | Sprint H | draft |
