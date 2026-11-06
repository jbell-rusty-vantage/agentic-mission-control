---
type: Interview Record
title: "Sprint OC start interview (IA-10): operating decisions before the first implementation session"
description: "Thirteen gap questions asked after the four behavior interviews, the owner's verbatim answers of 2026-10-27, and the decision each one became (OC-D182–OC-D194)."
tags: [mission-control, output-contracts, sprint, interview, operations]
date: 2026-10-27
---

# Sprint OC start interview

Asked by Claude Fable 5.1 on 2026-10-27 after reading the whole [Sprint OC packet](../../../../../provider-consolidation-2026-10/sprint-oc/README.md),
live Git state and the five older Linear cards the packet leans on. The four earlier interviews settled
behavior; these questions covered how the sprint is **run**. Owner quotes are verbatim. Each answer's
canonical destination is in [DECISIONS §5](../../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md#5-sprint-start-operating-decisions-2026-10-27);
the operating consequences are in [IMPLEMENTATION](../../../../../provider-consolidation-2026-10/sprint-oc/IMPLEMENTATION.md),
[PROOFS](../../../../../provider-consolidation-2026-10/sprint-oc/PROOFS.md), [KICKOFF](../../../sessions/KICKOFF.md) and
[ESCALATION](../../../../../provider-consolidation-2026-10/sprint-oc/ESCALATION.md). Questions 8 and 9 were deferred by the owner and are
answered in the follow-up section at the end once it exists.

| # | Question (gap and evidence) | Owner answer, 2026-10-27 | Decision |
| --- | --- | --- | --- |
| 1 | The packet is uncommitted on `main` (nine untracked paths, about thirty modified docs); a new worktree would not contain it. Commit first or carry dirty? | "Commit everything in all relevant codebases so we start from a clean checkpoint." | OC-D182 |
| 2 | Standing rule says commit/push when told, but four repositories, integration branches and context-bounded sessions need a cadence. | "No it's not commit when told. It is commit when the work is complete. Please change that." | OC-D183 |
| 3 | W0 needs fresh/repeat/interrupted installs on "two identified disposable targets". Remote Supabase projects, local containers, or both? Is wiping the remotes authorized? | "Yes wiping and re-installing the remotes is authorized in the issue part where it should occur. I will defer to you for the best way to operate from app creation -> migration. Yes they are remote supabase pro projects. We will start enforcing data retention once we produce quality ingestion and reports. I don't want to be slowed down until then. Please carve out the least friction filled path." | OC-D184 |
| 4 | Runtime model routes are unnamed; settings default to claude-haiku-4.5 and the deprecated gpt-5.4-nano. Name producer, judge and auditor pins. | "Okay I am going to select a few cost effective models now. Ensure you get the right names GPT-5 family up to 5.6. Choose models. Claide Haiku and Sonnet new versions." | OC-D185 |
| 5 | Which harness and models implement and review? Must the reviewer be a different harness or model family? | "I'm not sure if I will use codex or claude code. Codex will be GPT 6 Astra lead agent with GPT 6.1 sol subagents and claude code Opus 5.5 or Fable 5.1 lead agent with Opus 5.5 and Sonnet 5.5 subagents" | OC-D186 |
| 6 | C14 and the annex require the "actually selected coordinator host" to prove six observations including idle wake. Which host? | "The coordinator host is the implementer harness so the claude code or codex models and harness. Effectively YOU in this environment would be the coordinator agent calling mission control." | OC-D187 |
| 7 | Standalone saver, Agent Server, or both for C12 and W5? | "Are we using an async subagent in w5? As long as the savers operate like they would with a remote production postgres (like they will later on) I don't care what saver is used temporarily. Use docker postgres where needed or use an in memory." | OC-D188 |
| 8 | OVE-69/73/77 are In Progress, unassigned since 2026-10-09; OVE-73 natively blocks W5. Finish them fully or only the seam each wave needs? | "Come back to these after including the rest of my answers." | pending (follow-up below) |
| 9 | OVE-75/78 are Backlog yet named as engines to reuse for WI-18/19. In-sprint deliverables or existing source only? | "Come back to these after including the rest of my answers." | pending (follow-up below) |
| 10 | USD 15 per session is the only cap; W1–W5 run real models in both apps. Sprint ceiling or session count? | "How about this. <= 40 dollars maximum for the sprint. Distribute this throughout the plan" | OC-D189 |
| 11 | Where does a blocked escalation land, and what happens if you are away? | "Write out a special ESCALATION.md document. I really can't foresee this happening. All the infrastructure and credentials are present. If I do not answer because I am away I need hueristics applied and the sprint to move on." | OC-D190 |
| 12 | Pressure-aware scheduling policy (OC-D169) is undecided pending WI-10 evidence. Stop and ask, or defer? | "Defer the decision. Later sprints will deal with more advanced scheduling and processing" | OC-D191 |
| 13 | May W1–W5 fixtures use tiny slices of the F1/F2/F3 subjects? | "Yes that works" | OC-D192 |
| — | Q16/Q17 of the final interview (specialized code-integration engine, integrated preflight preview) remain unanswered; the packet treats them as unselected. | No objection raised. | OC-D193: unselected stands |
| — | Closing instruction | "Take my answers , reason about them and then include them in the sprint documents. Come back to me about 8 and 9 and further set up work." | OC-D194 |

## Interpretations recorded as engineering choices, not owner quotes

- **Push.** The owner changed the commit rule only. The packet now says: commit when an issue's or
  milestone's work is complete and verified; push the integration branch at every gate release and at
  session end so the checkpoint exists remotely. Pushing is not separately gated.
- **Which remotes.** The two Supabase Pro projects named in `deployments/*/target.toml` are the disposable
  targets. The Biotech Neo4j Aura graph is treated the same way under the same "disposable until quality
  ingestion exists" rule; the owner named only Supabase, so the integrator records the first Aura wipe
  as an assumption in the evidence log and in the ledger (see ESCALATION H3).
- **Model availability.** Pins were chosen from the public OpenAI and Anthropic catalogs on 2026-10-27;
  a bounded availability probe at first paid use is still required (PROOFS §6).
- **F1–F3 budget.** The USD 40 ceiling covers the sprint (W0–W5 including repairs). The post-sprint
  stress fixtures receive their own allocation when WI-25 starts; the owner has not set it.
- **Reviewer independence.** A different agent in the same harness satisfies "implementer and reviewer
  are different agents". Where the harness offers it, use a different model for the reviewer.

## Follow-up on questions 8 and 9 (same day)

Recommendation put to the owner: seam-only with a W0 baseline audit. During WI-24 one helper compares each
of OVE-69/73/75/77/78 against source and tests (no paid runs); the integrator sets each card's honest
state (close with evidence, or scope the remainder in a comment and move it to Backlog); Sprint OC builds
only the seam a criterion needs (human gates for C08/C09 from OVE-73, interventions for C06/C07 from
OVE-69, continuation for WI-18 from OVE-75, subscriptions for WI-19 from OVE-78; OVE-77 Socket.IO
handlers are needed by no criterion and stay open); the native blocker links OVE-75→OVE-181 and
OVE-78→OVE-182 are replaced by the audit's outcome. The alternative, finishing all five cards in full,
was rejected as roughly a wave of unproven scope.

| # | Owner answer, 2026-10-27 | Decision |
| --- | --- | --- |
| 8, 9 | "Okay I accept those recommendations for questions 8 and 9." | OC-D195 |
| Aura | "Yes you confirmed correctly about neo4j aura. We will take much more care for storage and history ONCE WE progress further." | OC-D196: the Aura assumption in IMPLEMENTATION §4.1 is confirmed; it is no longer an assumption |

The owner then asked for a selection-and-routing design before any implementation or agent-team spawn
(OC-D197). The request, verbatim in its key sentence: "I want you to design the deep modules for SELECTION
and ROUTING across the variation axes of this system, and to decide on the adaptation mechanism before any
implementation starts." The four axes, what must adapt, the decisions required with rejected alternatives,
the depth test, the six deliverables and the constraints (depth over flexibility, configuration-as-data,
do not implement, ask before assuming) are reproduced in the design's §1, §2 and §14. Deliverables:
[SELECTION-AND-ROUTING-DESIGN](../../../specs/SELECTION-AND-ROUTING-DESIGN.md),
[SELECTION-AND-ROUTING-INTERFACES](../../../specs/SELECTION-AND-ROUTING-INTERFACES.md) and the proposed
[ADR-0063](../../../../../../adr/0063-one-resolution-seam-over-declared-lane-model-and-application-registries.md).

## Answers to the design's five open questions (same day)

| # | Owner answer, 2026-10-27 | Decision |
| --- | --- | --- |
| 1 | "I accept your reccomendation" | OC-D198 |
| 2 | "Yes currently we have the openai agents api with codex harness not the openai agents sdk . This sprint does not at all or minimally touches other providers. After this sprint proves workflows with deep agents working splendidly with output contracts , context transfer and re-proving our forking and lifecycle control we will sweep through all the providers . I hope you understand this strategy." | OC-D199 |
| 3 | "Yes confirmed" | OC-D200 |
| 4 | "Model profiles as files rather than catalog rows in a database ? Yes I probably agree with that. THe model selected string or the abstracted choice a coordinator agent uses has to work with an agent provider . Don't get the ai model table in ai engineer mixed up with mission controls use of models inside of effective run configurations. One is ai engineer knowledge and the other is for seeding a workflow. Wait don't we need to map model <-> provider string and expose this to the coordinator agent. Let's make sure these things work. We are going to work on coordinator agent mission control search and documentation (the process a mission control skill agent uses to find workflow types, model choices, provider specific stuff, mission control commands etc)" | OC-D201 |
| 5 | "The older biotech knowledge path. It is not being used ? Delete it now." | OC-D202 |
| close | "Can you add commit and push everything. Ready the sprint completely. Finish any pre-sprint work you have identified that would help and get me ready to start the sprint." | Packet committed and pushed; OC-R issues filed; ADR-0063 accepted; deletion done with checks. |

## Final question: the complex fixtures (same day)

| Owner words, 2026-10-27 | Decision |
| --- | --- |
| "The advanced fixtures, the fixtures that are essentially cohesive real-world type of missions when do those start running [...] These fixtures are slated for after the main work and some smaller fixtures right ? I want to be part of this complex fixture time and I want to be notified when these start ." | OC-D203: confirmed; owner checkpoints with a wait at W5 start, stress-phase start and each stress mission start (ESCALATION §4). |
