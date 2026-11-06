---
name: provider-research
description: Resolve what is hard to discern, lesser known, recent or contradicted about a provider (Deep Agents, LangGraph, LangChain, Claude Agent SDK, Codex, Cursor, OpenAI Agents, Temporal) from primary sources and record it as dated evidence with an improvement proposal for Mission Control. Use when a provider sprint starts, when a pin moves or a digest arrives, when a claim about a provider cannot be cited from the current supplement, or when the owner asks what changed in a provider.
---

# Provider research

Provider documentation here is **research, not a copy**: a dated sheet per provider that records
only what the provider's own documentation does not settle, cites every line, and ends in
proposals for the current system. The contract for the sheet, the labels, the automation tiers
and the register is the
[running proposal](../../../docs/specs/provider-consolidation-2026-10/PROVIDER-RESEARCH-RUNNING-PROPOSAL.md);
this skill is its tier 1, the research session. Reading legwork is delegated with the `research`
skill (a background agent on primary sources); this skill decides what counts and where it goes.

## 1. Scope the sitting

- The lane and its current sheet: `docs/specs/<program>/providers/<lane>/<LANE>-SURFACE-<date>.md`
  (Deep Agents: `DEEP-AGENTS-SURFACE-2026-10-22.md`). Read its front matter `as_of` and `pins`.
- The repository's pins: `pyproject.toml` and `uv.lock` for the provider packages. A sheet whose
  pins differ from the repository's is stale; say so in its ledger row.
- The input: a digest under `.scratch/provider-research/<lane>/<date>-digest.md` (tier 0 output,
  never committed), a question from the owner, or the start of a provider sprint (then the whole
  sheet is re-read against the current pin).

**Done when:** the list of items to resolve is written down, each with the version it must be
read against.

## 2. Resolve each item against primary sources

Primary means the provider's documentation, the installed wheel's source (unpack it from the
`.venv`; cite `path:line` in the pinned version), the repository at the pinned tag, and maintainer
statements in issues or pull requests. One `research` background agent per independent item.

A line earns its place only when it is one of: **source-only**, **scattered** (three or more
sources needed), **contradicted**, **recent** (changed after our pin; say since which version),
**probed** (we ran it and were surprised). Everything else is a link to the provider's page.

Every finding carries: an id (`DA-12`, `CX-3`), the claim in one sentence, a label, a citation,
the version read, the date, and `no impact` or an improvement id `IP-n`. Labels: `[SRC]` read in
source, `[DOCS]`, `[ISSUE]`, `[PROBE]` (with the probe's path), `[INF]` our inference, `[NF]`
looked for and not found, `[COMMUNITY]` a blog or forum post, allowed only when extremely
pertinent and never the sole citation of a claim.

**Done when:** every item is a finding or an `[NF]` line, and no claim lacks a citation and a
version.

## 3. Probe what a contract will rest on

When a claim would change a contract, a lane declaration or a default, confirm it by running
something small: offline first (the installed package, a fake model, the disposable Postgres);
a paid probe needs the owner's authorization and counts against the session cap. Until the
probes folder of the running proposal exists, the probe lives under `.scratch/` and the finding
cites its path; a promoted probe is wired into the offline suite.

**Done when:** each `[PROBE]` finding names a runnable path and the observed result.

## 4. Write the sheet and the register

1. A new dated sheet, or a revision of the current one with superseded lines marked (never
   deleted), front matter `as_of: <date>` and `pins:` (package to version, as in `pyproject.toml`).
2. One register row per proposal for the current system in the running proposal's §5:
   `IP-n | provider | proposal | evidence (sheet §) | lands in (sprint or spec) | draft`.
3. Facts that span lanes go to `docs/research/<date>-<topic>.md` (`type: Research Note`,
   "evidence for ADR-n; it decides nothing").
4. The ledger: the sheet's row (kind `docs`) created or updated with its status and staleness;
   nothing else moves. A contract, ADR or lane declaration changes only through the interview
   (`grill-with-answers`) after the owner accepts a register row.

**Done when:** `python docs/tools/program_ledger.py check --program docs/specs/<program>` passes,
the sheet validates (`python docs/tools/validate_okf.py docs/specs/<program>` is not required;
front matter type, title, description and tags are), and the register rows name where each lands.

## 5. Report

The final message lists: what moved since `as_of` (one line per finding, with label and impact),
the register rows added, the probes run and their results, what was looked for and not found, and
the owner decisions the register now waits on.
