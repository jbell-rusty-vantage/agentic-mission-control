---
type: Agent Configuration
title: "Matt Pocock skills: what we carry, how Mission Control wires them, how to stay current"
description: "The upstream repository mattpocock/skills, the promoted engineering and productivity skills carried in .agents/skills byte-identical to upstream (checked 2026-10-23 against main, release v1.3.1), how the setup skill's output maps to docs/agents and AGENTS.md here, the buckets deliberately not carried, and the command that reports drift."
tags: [mission-control, agents, process, skills, upstream]
---
# Matt Pocock skills

Upstream: <https://github.com/mattpocock/skills> (MIT). **Checked 2026-10-23** against `main` (commit `5beb35b`, 2026-10-19; latest release v1.3.1, 2026-10-04): all 27 promoted skills present, **0 files drifted** after `wizard/template.sh` was refreshed that day.

```text
python scripts/dev/check_matt_pocock_skills.py          # exit 1 when a carried skill drifted
python scripts/dev/check_matt_pocock_skills.py --ref v1.3.1
```

Run it at the start of any session that changes skills or this configuration, and after the newsletter or release notes announce a change. To update, copy the drifted upstream files over ours unchanged, then rerun.

## What we carry

| Upstream bucket | Carried | Skills |
| --- | --- | --- |
| `skills/engineering` | all | `ask-matt`, `code-review`, `codebase-design`, `diagnosing-bugs`, `domain-modeling`, `grill-with-docs`, `implement`, `implement-spec`, `improve-codebase-architecture`, `pr`, `prototype`, `research`, `retro`, `setup-matt-pocock-skills`, `tdd`, `to-spec`, `to-tickets`, `triage`, `wayfinder`, `wizard` |
| `skills/productivity` | all | `grill-me`, `grilling`, `handoff`, `teach`, `to-questionnaire`, `wait-what`, `writing-for-agents` |
| `skills/in-progress`, `skills/misc` | none | Not promoted upstream (`chief-of-staff`, `loop-me`, `setup-pre-commit` and others). Adopt one only by decision, and then keep it upstream-identical |

Files sit in `.agents/skills/<name>/`; `.claude/skills/<name>` are local symlinks onto them (git-ignored); each skill also ships `agents/openai.yaml` for Codex.

## How Mission Control is wired

`setup-matt-pocock-skills` was run once; its output is configuration that the other skills read. Edit these files, never the skills.

| Skill need | Where it is answered here |
| --- | --- |
| Issue tracker (`to-spec`, `to-tickets`, `triage`, `wayfinder`, `implement`) | [issue-tracker.md](issue-tracker.md): Linear, workspace `overtonbell`, team `OVE`, project Mission Control. Upstream offers GitHub, GitLab or local files and treats anything else as "other", described in prose; this is the "other" case |
| Triage roles (`triage`) | [triage-labels.md](triage-labels.md): the five default roles as Linear labels, `Bug` and `Feature` for the categories |
| Domain docs (`grill-with-docs`, `domain-modeling`, `improve-codebase-architecture`, `code-review`) | [domain.md](domain.md): single context, `GLOSSARY.md` and `docs/adr/` at the root, plus `docs/knowledge/` |
| Pointer from the harness | The `## Agent skills` block in the root `AGENTS.md`, with one line per file above |

The flow the skills implement, in the order a feature moves: `grill-with-docs` (language and ADRs) → `to-spec` → `to-tickets` → `implement` or `implement-spec` (driving `tdd`) → `code-review` → `pr`. `wayfinder` plans work larger than one session as a map of decision tickets; `retro` proposes environment improvements after a session; `ask-matt` routes when unsure which to use. Program documents and their ledger ([program-workspace.md](program-workspace.md)) are where this flow leaves files.

## Our skills beside the set

Four skills of ours wrap or complement the upstream flow without editing it. Each lives in `.agents/skills/<name>/` with its `agents/openai.yaml`, so Claude Code (through the `.claude/skills` links), Cursor and Codex see the same files.

| Ours | Relation to upstream | Why it is ours and not an edit |
| --- | --- | --- |
| `belllabs-method` | the map over everything: surfaces, canonical versus working documents, the phase-to-skill table, the session loop, harness wiring and hook recipes | `ask-matt` routes the upstream flow; this one attaches our records (answers files, ledgers, projections, supplements) and our checks |
| `grill-with-answers` | runs `grilling` and `domain-modeling` exactly as `grill-with-docs` does, then records every decision in the sitting's `answers/` file with the owner's words, **Becomes** and **Folded** | `grill-with-docs` leaves only `GLOSSARY.md` and ADRs; the owner wants each answer recorded separately and converted before the sitting ends |
| `architecture-projection` | sits between `to-spec` (which keeps paths and snippets out of the spec) and `tdd` (which needs agreed seams): modules, real signatures, file tree, dependency chain, sequence, seams, then a conformance table after the build | the owner plans in code shape and checks the implementation against it |
| `provider-research` | drives `research` for the reading, adds the evidence fields, labels, staleness rule and improvement register of [the running proposal](../specs/provider-consolidation-2026-10/PROVIDER-RESEARCH-RUNNING-PROPOSAL.md) | provider facts need a version, a label and a promotion path that upstream `research` does not carry |

In Mission Control the entry to the main flow is therefore `grill-with-answers`; the rest of the flow (`to-spec` → `to-tickets` → `implement` → `code-review` → `pr`, `retro`) is upstream unchanged.

## Notes for the owner

- Upstream renamed the glossary convention from `CONTEXT.md` to `GLOSSARY.md`. Mission Control already uses `GLOSSARY.md`; no change needed.
- Upstream says to rerun `setup-matt-pocock-skills` only to switch trackers or start over. It is a prompt-driven skill, so rerunning it asks again rather than diffing.
- Our own dev-time skills (`mission-control-docs`, `mission-control-coordinator`, the LangChain family and others) sit beside the upstream set in `.agents/skills`; the shipped bundles under `skills/` are a separate population ([documentation-surfaces.md](documentation-surfaces.md#skills-two-populations-one-rule)).
