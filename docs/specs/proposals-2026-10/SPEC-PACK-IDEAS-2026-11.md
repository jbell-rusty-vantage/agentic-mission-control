---
type: Proposal
title: "Product ideas harvested from the deleted mission-control-general spec pack"
description: "The product-level ideas of the 2026-09/10 spec pack that no concept carries (goal families and workflow templates, experiments as swarm variants, recursive self-improvement, source intelligence, memory manager, narrative and improvement reads, intra-mission conversation, sandboxed interview sessions, generative UI), each with its source section at commit 66185d2e. Ideas, not decisions; nothing here is built."
tags: [mission-control, proposal, ideas, harvest, goals]
status: open
date: 2026-11-01
---

# Product ideas harvested from the spec pack

The spec pack `mission-control-general/` was deleted on 2026-11-01 (OVE-206, AS-D33). Its contracts live in
the ADRs and concepts; these ideas are product direction, not contracts, so they are recorded here as
proposals. Every source below is read with `git show 66185d2e:<path>`. None is built; none is a decision
(owner interview before building). The `goals` concept links this file.

| # | Idea | What it says | Source (commit 66185d2e) |
| --- | --- | --- | --- |
| 1 | Goal families | Research, course/challenge/project, application creation, experiment, recursive self-improvement and personal-intelligence platforms as pipelines over the same kernel (`specify -> scaffold -> implement -> test -> preview -> review -> improve`) | `mission-control-general/MISSION_CONTROL_SPEC.md` §16 |
| 2 | Workflow templates | Parameterized, versioned authoring aids the compiler expands into an ordinary definition (research flywheel, build-test-preview-improve, course projection, harness comparison, after-commit optimizer, blank 20-node graph); exemplars are immutable tested expansions used in CI | `MISSION_CONTROL_SUPPLEMENT.md` §6; spec §5.5 |
| 3 | Experiments as swarm variants | Experiment kinds `harness_comparison`, `model_comparison`, `adversarial`, `compaction_comparison`, `prompt_cache_ablation`, `eval_benchmark`: fan-out arms as a Parallel Swarm profile (ADR-0068), frozen inputs, verify, compare, seal; an LLM judge is one typed arm, never the only gate | spec §13.4; `MISSION_CONTROL_SUPPLEMENT.md` §3 |
| 4 | Recursive self-improvement | Event policy: after a major commit, merged PR, failed verification or upstream release, arm an optimizer node when budget and an open improvement objective remain; proof before accepting the new head | spec §16 |
| 5 | Improvement from narrative | Pattern across successful and failed missions, an attributed hypothesis, a candidate instruction/skill version that never mutates prior runs, baseline vs candidate on pinned and held-out cases, promotion through the owning service; observational improvement is not causal proof | `MISSION_STORAGE_AND_RETRIEVAL_PROJECTION.md` §7 |
| 6 | Narrative / as-of reads | A deterministic evidence package (manifest, milestones, causal links, decisions, evidence, cost, gaps) that an agent turns into prose; recorded facts, attributed assessments and retrospective interpretation kept apart; new evidence yields a new narrative version | same file, §5 (Reads A-F) |
| 7 | Source intelligence | A first-class ledger of what was asked of the world, what came back and whether to ask again (`SourceEncounter`: reason, method, result digest, cost, freshness, authority, downstream consumers) | `MISSION_CONTROL_SUPPLEMENT.md` §9 |
| 8 | Memory manager | Curated semantic, procedural and episodic memory behind `memory.write/search/pin/forget`; mission state and transcripts are not memory | `MISSION_CONTROL_SUPPLEMENT.md` §10 |
| 9 | Credits ledger and prompt-cache policy | Per-path credit accounting as a ledger; cache rules that actually save money (the Deep Agents row `anthropic.prompt_caching` is the only built trace; see [budgets and usage](../../knowledge/budgets-and-usage.md)) | `MISSION_CONTROL_SUPPLEMENT.md` §1.2, §5; spec §12.2 |
| 10 | MissionFS and deliverable review | Navigable mission context and a reviewed deliverable lifecycle (product conventions proposed in section H of the system proposal); the review loop itself is in the [human review supplement](HUMAN-REVIEW-GATES-AND-STEERING-SUPPLEMENT-2026-10-22.md) | `mission-control-general/general-mission-control/MISSION_CONTROL_SYSTEM_PROPOSAL.md` §H |
| 11 | Intra-mission conversation | Addressable agent-to-agent conversations (open, park, resume, seal) and a progress ledger on one mission, without a second message bus that bypasses commands and artifacts | `2026-09-19_CONTROL_PLANE_EXPERIENCE_AND_SANDBOX_SEED.md` §2-§3 |
| 12 | Sandboxed interview sessions | A bounded authoring agent session attached to a draft (`InterviewCreate@1`, `InterviewTurnSubmit@1`, `interview_session`/`interview_turn`), refining outcome, rubric, effects and budgets before a mission exists; not built | `general-mission-control/expansion/EXPERIENCE-AND-STREAMS.md` lines 19-47 |
| 13 | Generative UI and MCP Apps | Isolated, host-mediated UI resources attached to tools, with text fallback; host support varies; ADR-0016 requires fallbacks | `expansion/EXPERIENCE-AND-STREAMS.md`; `expansion/TECHNOLOGY-EVIDENCE.md` UI-E01..E03 |
| 14 | Sandbox snapshot seeding | Seeding a sandbox from coordinator artifacts (metadata load, sandbox snapshot) | `2026-09-19_CONTROL_PLANE_EXPERIENCE_AND_SANDBOX_SEED.md` §4 |

The naming conventions of the system proposal §B (`mc.<contract>.v<major>`, noun-verb CLI,
`mission_<resource>_<verb>` MCP tools, `mc://` references) are followed by the code and are written down in
[coordinator surface](../../knowledge/coordinator-surface.md).
