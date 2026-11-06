---
type: Working Draft
title: "Mission Control truth pass C: programs, ADRs and the archive"
description: "Exploration part C of the Mission Control truth pass on sprint-oc c73cb355: disposition of every document in the provider-consolidation, coordinator-surface and fault-tolerance programs (archive, stays working, feeds a concept or ADR), the ADRs whose status, supersession or concept citation is wrong, whether the archive is still the sole source of any current fact, the shortest reading path to current Sprint OC state, owner questions and ordered steps for the refactor agent."
tags: [mission-control, truth-pass, sdlc]
date: 2026-11-01
status: draft
---

# Truth pass C: programs, ADRs and the archive

Read from `sprint-oc` HEAD `c73cb355` (four OVE-206 reconciliation commits after `ce9d2f13`, so
STATE discrepancies D1-D13 are mostly already fixed). Paths are relative to `platform/mission-control/`;
`PC` = `docs/specs/provider-consolidation-2026-10/`, `NS` = `PC/sprint-oc/NEXT-SESSION.md`,
`L` = `PC/LEDGER.md`. Owner decision AS-D25 applied: promote what W0, R0-R7, OVE-204 and OVE-182
built into concepts; W1 (D1-D30) and the coordinator proposal beyond OVE-182 stay working; fault
tolerance is parked; completed work goes to the archive. Nothing was run except read-only greps,
`program_ledger.py check` (109 rows, 0 problems) and `check_links.py` (604 files, 0 broken).

## 1. Summary

- **Programs.** 97 Markdown files in scope (PC 92, coordinator surface 3, fault tolerance 2) plus
  12 JSON files in PC. Proposed: **63 PC documents to archive** (of which 3 depend on owner Q2),
  **29 PC documents stay working**, coordinator surface 3 stay, fault tolerance 2 parked in place.
  **14 documents feed a concept or ADR first** (section 2, "feeds"). Sprint V, the four completed
  interview-answer sets, the tracing work, and seven Deep Agents P1 turn documents are complete.
- **Ledger rows are stale in nine places** (completed work still `active`/`accepted`): DOC-13,
  DOC-23, DOC-33, DOC-34, DOC-36, SE-14, SE-16, IA-10, SP-10 (section 2 cites each).
- **Archiving is not purely mechanical in three places:** `docs/tools/okf_search.py:42-45` and
  `tests/unit/test_documentation_retrieval.py:37-60` hard-code `SESSION-CODEX-RESUME-2026-10-29.md`
  as a default-search entrypoint; `scripts/sprint_oc_w0_local_proofs.mjs:46` reads
  `PC/sprint-oc/release/locks`; two checksummed seeds cite `PC/SPRINT-V-DESIGN.md`
  (`packages/mission-control-db-contract/seeds/knowledge_tools.py:35`) and `PC/sprint-oc/PROOFS.md`
  (`seeds/graph_route_schemas.py:22`). `program_ledger.py move` lists these but does not fix them.
- **ADRs.** 66 files, 0001-0067, **one gap (0051), no duplicates.** 23 ADRs are `proposed` but
  implemented (0021, 0035-0050, 0052-0057); 10 accepted ADRs are cited by no concept (0001, 0002,
  0012, 0014, 0059, 0060, 0064-0067); one unmarked supersession (0021 by 0064); five accepted ADRs
  (0058-0062) share one boilerplate `description`; four lack a supersession back-marker. 27 ADRs have no problem.
- **Archive.** It has an index (`docs/specs/archive/README.md`) for whole programs; single archived
  documents are found only through ledgers. Live concepts still cite archived fast-track documents for
  **current blocker status** (B2-B7) and the only record of the ADR-0051 reservation is archived.
- **Reading path.** Today an agent meets five competing "start here" banners in `AGENTS.md:1-60` and
  a 1060-line control board whose live part is lines 9-195. Section 6 gives a ~400-line path.

## 2. Program document table

Status = ledger status now. "Archive" means `program_ledger.py archive|move`; "feeds X" means
promote the named facts into concept or ADR X first, then archive (or keep, as stated).

### 2.1 Provider consolidation, program root (22)

| Path | Status now | Disposition | Reason |
| --- | --- | --- | --- |
| `LEDGER.md` | active | stays working | Program register; header banners L:10-48 need collapsing to one dated line |
| `README.md` | active | stays working; D1-D9 need closing (Q3) | "D1-D9 (§9) are still open" `README.md:17`; D1 "Accept the program ... before P1" `:369` is overtaken by events |
| `PROCESS.md` | active | stays working | Cited by skills `.agents/skills/belllabs-method/SESSION.md:5`, `grill-with-answers/SKILL.md:12` |
| `RUN-2-CARRY-FORWARD.md` | active | stays working | Groups 64 Linear issues; cited by `cursor-lane.md`, `release-and-qualification.md`; its sprint grouping depends on Q2 |
| `PROVIDER-RESEARCH-RUNNING-PROPOSAL.md` | draft | stays working | Cited by `.agents/skills/provider-research/SKILL.md:12` |
| `AGENT-CAPABILITY-CATALOG-PROPOSAL-2026-10-23.md` | draft, OVE-148 | stays working; built first slice feeds `agent-configuration.md` | L:72 "first slice ... built"; AC-D1..12 open |
| `WORKFLOWS-COMPUTE-AND-COMMUNICATION-PROPOSAL-2026-10-23.md` | draft | stays working | Future programs; decides nothing (L:71) |
| `COORDINATOR-PROJECTION-PROPOSAL-2026-10-23.md` | draft | **move to `coordinator-surface-2026-10/`**, stays working | Coordinator stance CO-D1..18 (L:70); owner keeps the coordinator proposal working (AS-D25) |
| `OPENAI-AGENTS-API-DESIGN.md`, `OPENAI-AGENTS-API-SURFACE-2026-10-30.md` | draft | stay working (secondary provider) | SP-15/DOC-40 L:122,145; nothing built |
| `TRACING-PROPOSAL.md` | done | **archive; feeds** ADR-0054..0057 acceptance and `transcript-projection.md`, `precise-fork.md` | Built and merged 2026-10-22 (L:64); TR-D1..19 answered (L:182) |
| `BASELINE-2026-10-19.md` | done | archive | "Historical reference, not refreshed" L:85 |
| `APPLICATION-KNOWLEDGE-BOUNDARY-DESIGN.md` | accepted | archive; feeds `knowledge-services.md` | Converted into OUTPUT-CONTRACTS and ADR-0059/0060 (`sprint-oc/DECISIONS.md:11-13`); L:140 "Nothing built" is stale since OVE-204 slices 1-3 |
| `INTERVIEW-APPLICATION-KNOWLEDGE-BOUNDARY-2026-10-24.md`, `INTERVIEW-SPRINT-V-…-2026-10-24.md`, `INTERVIEW-OUTPUT-CONTRACTS-…-FINAL-2026-10-24.md` | done | archive (`interview-instructions`) | IQ-05/06/07 done L:163-165 |
| `SPRINT-V-DESIGN.md` | accepted | archive; feeds `knowledge-services.md`, `trusted-judgment.md` | Sprint V executed A-F (L:202); seed cites path (sealed, see §5) |
| `SPRINT-V-PLAN.md` | accepted | archive | SE-07 executed (L:202); "uncommitted on every main" is stale |
| `SPRINT-V-RESEARCH.md` | active | archive | Baseline research for a finished sprint (L:92) |
| `SPRINT-SEQUENCE-2026-10-23.md`, `OWNER-INTERVIEW-2026-10-22.md`, `SESSION-INTERVIEW-SITTING-I-2026-10-24.md` | open | **Q2: archive as superseded** | Sitting I / OVE-149 "no longer a prerequisite" L:47-48; decision logs IA-01/02 empty L:179-180; sprint cards A..I replaced by Sprint OC W0-W5 and the Agentic SDLC program |

### 2.2 `PC/sprint-oc/` (25 Markdown, 8 JSON)

| Path | Status now | Disposition | Reason |
| --- | --- | --- | --- |
| `NEXT-SESSION.md` | active | stays working; **split** (step 6) | Live board is NS:9-195; NS:197-1060 are dated batch logs (overnight, foundation, B3-B4c) |
| `README.md` | active | stays working; fix head | Cited by 13 spec-pack files; L:105 "Current implementation entrypoint" contradicts its own redirect `README.md:11-17` |
| `PROOFS.md` | accepted | stays working (W1-W5 matrix) | Seed cites it; frontmatter `status: planned` vs ledger `accepted` |
| `IMPLEMENTATION.md` | accepted | stays working | Cited by `RUNTIME-CONTRACTS.md`, `DATABASE.md`, `output-contracts.md` |
| `DECISIONS.md` | done | stays working; feeds new `decisions.md` | Still appended through OC-D207 (`DECISIONS.md:339-350`); cited by ADR-0058..0062 |
| `CLOUD-ENVIRONMENTS-AND-DEEP-AGENTS-DEPLOYMENT-2026-10-31.md` | active | stays working | DOC-41 L:123 |
| `ESCALATION.md` | accepted | stays working | Sprint OC operating rule OC-D190 (L:111) |
| `APPLICATION-PORTS.md`, `SCHEMA-AI-ENGINEER.md`, `SCHEMA-BIOTECH.md` | active | stay working | Default-search entrypoint (`okf_search.py:45`) and test target |
| `release/RELEASE-BUNDLE.md` | active | stays (locks beside it are read by a script); **feeds** `database-component.md` and `release-and-qualification.md` | W0 "RELEASED WITH RECORDED LIMITATIONS" `RELEASE-BUNDLE.md:22`; DOC-33 L:115 still says placeholders and reviewer sign-off open (one `<<integrator>>` string remains) |
| `release/RUNTIME-ENVIRONMENT.md`, `release/ENVIRONMENT-AND-DATABASES.md` | active | stay working (W1 topology) | DOC-32/35 |
| `release/W1-EVIDENCE.md` | active | stays working (W1) | DOC-39 |
| `WORK-ITEMS.json`, `release/*.json` | - | stay | Work map; locks used by `scripts/sprint_oc_w0_local_proofs.mjs:46` |
| `HANDOFF-2026-10-28.md` | active | archive | Superseded by S3 (L:116, L:118) |
| `HANDOFF-2026-10-28-S3.md` | active | archive **after** moving its facts; feeds `database-component.md` | Sole record that MC 1.8.0 + tenants + logins are installed on both remotes (`HANDOFF-2026-10-28-S3.md:4,31-33`) |
| `KICKOFF.md` | accepted | archive | SE-14 executed: W0 released, R0-R7 merged (L:112) |
| `SESSION-CODEX-RESUME-2026-10-29.md` | done | archive; **edit `okf_search.py:43-44` and the test first** | SE-15 done L:210 |
| `SESSION-OVERNIGHT-WORKFLOWS-2026-10-29.md` | active | archive; feeds `execution.md`, `mission-chains.md`, `output-contracts.md` | NS:199 "Completed bounded assignment, 2026-10-30"; ledger SE-16 L:211 still `active` |
| `RECOVERY-AUDIT-2026-10-29.md` | active | archive after step 6 copies §5 remaining scope into the board | NS:170-173 makes it per-section evidence; custody table already in NS:136-142 |
| `SELECTION-AND-ROUTING-DESIGN.md`, `SELECTION-AND-ROUTING-INTERFACES.md` | accepted | archive; feeds `application-profile.md`, `model-catalog.md`, `lanes-and-harness.md`, `agent-configuration.md` (cite ADR-0063 + source, not § numbers) | R0-R7 built 2026-10-27 (L:112-113) |
| `provenance-2026-10-31/README.md`, `REPORT.md`, `CHANGES.md` | done, done, active | archive the folder (`move`); **feeds** new concept for invocation origin and receipts (ADR-0060), `knowledge-services.md` (read intent, "not exercised live"), `capability-seeds.md` (charters, agent-skills 1.0.4), `environments.md` or `operations.md` (S3 `mission-payloads`), `workspace-closure.md`, `database-component.md` (1.12.0) | Sprint closed (L:212); `REPORT.md` §5 follow-ups must move to NS first; no concept mentions read intent or the payload store today |

### 2.3 `PC/sprint-v/` (9 Markdown, 4 JSON)

All nine (`START-HERE`, `TEAM-WORKSPACE`, `NEXT-SESSION`, `HANDOFF-2026-10-25`,
`PROOFS`, `IQ-07-BRIEFING`, `ADVERSARIAL-READINESS-2026-10-25`, `READINESS-REPAIRS-2026-10-25`,
`release/RELEASE-BUNDLE`) plus `WORK-ITEMS.json` and `release/` → **archive the folder with `move`**.
Sprint V closed 2026-10-25 (L:93, L:202-204); `sprint-v/NEXT-SESSION.md:11-12` already redirects to
Sprint OC; DOC-13 L:95 says "superseded as the entry point"; DOC-17's "Uncommitted" is stale
(repairs are in `1863017c`). No code reads `sprint-v/`; `AGENTS.md:47` ("For accepted Sprint V work,
start with START-HERE") must be removed in the same change.

### 2.4 `PC/answers/` (25)

| Path | Status now | Disposition | Reason |
| --- | --- | --- | --- |
| `SPRINT-OC-RECOVERY-SITTING-1-2026-10-29-ANSWERS.md` | open (IA-11) | stays working; **feeds a new ADR** (OC-D204 Swarm is a StageGraph profile; OC-D205 EO reuses GoalDirected) and `parallel-swarm.md`, `evaluator-optimizer.md`, `workflow-systems.md` | Spec pack and GLOSSARY carry OC-D204 (`03-PARALLEL_SWARM.md:9,41`) but the concepts still say "specified, not implemented" and list Swarm as a separate system (`workflow-systems.md:25,126-130`; `parallel-swarm.md:4`) with no reclassification |
| `gpt-6-astra-2026-10-24/` (6) | done | archive folder | IA-06, SP-06..09, PR-10 converted to OUTPUT-CONTRACTS + ADR-0058/0059/0061 (L:73, L:136-139, L:184) |
| `application-knowledge-boundary/claude-fable-5-1-2026-10-24/` (2) | done | archive folder | IA-07, PR-11 (L:74, L:185) |
| `output-contracts-final/codex-gpt-6-2026-10-25/` (14) | done / active rows | archive folder | IA-09 `final`; SE-10..13, IQ-08, SP-12/13, DOC-18..22 all converted (L:100-104, L:142-143, L:166, L:187, L:205-208) |
| `sprint-v/codex-gpt-6-2026-10-24/ANSWERS.md` | done | archive | IA-08 L:186 |
| `sprint-oc-start/claude-fable-5-1-2026-10-27/ANSWERS.md` | active | archive | IA-10 L:188: all of OC-D182-203 converted into `DECISIONS.md §5` and ESCALATION |

### 2.5 `PC/providers/deep_agents/` (11)

| Path | Status now | Disposition | Reason |
| --- | --- | --- | --- |
| `CHANGES.md` | active | stays working | Change ledger, appended 2026-11-01 (L:91) |
| `DEEP-AGENTS-SURFACE-2026-10-22.md` | active | stays working (provider supplement) | Pin 0.7.5 rechecked, "latest" figure unrefreshed (L:90) |
| `DESIGN.md` | active | stays working | WP list still names what remains for the Deep Agents goal (L:131) |
| `TOPOLOGY-NOTE.md` | open | stays working; fold into the DOC-41 deployment decision packet | ADR candidate on saver/Agent Server topology (L:67), exactly the deployment-architecture question now open |
| `AUDIT.md`, `AUDIT-OUTPUT-TRANSFER-2026-10-22.md` | done | archive (`docs`) | L:87-88 |
| `ASYNC-SUBAGENTS-EXPLAINED.md`, `SUBAGENTS.md` | done | archive; `async-children.md:15-16` already cites them as design history | L:89, L:132 |
| `COGNITION-POINTS.md` | done | archive | Built Turn 4 (L:133); covered by `precise-fork.md`, `interventions.md` |
| `SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md`, `DOMAIN-PROVENANCE-AND-STATE-SUPPLEMENT-2026-10-23.md` | done | archive | IA-03, PR-03 disposed in DECISIONS (L:66, L:134, L:181) |

### 2.6 Coordinator surface (3) and fault tolerance (2)

| Path | Status now | Disposition | Reason |
| --- | --- | --- | --- |
| `coordinator-surface-2026-10/LEDGER.md` | active | stays working; rewrite next step | L:14-16 routes to "round R8" and "sprint I" of SPRINT-SEQUENCE (Q2); OVE-182 is shipped (`958957e6`) |
| `coordinator-surface-2026-10/PROPOSAL-COORDINATOR-SURFACE-2026-10-22.md` | open, OVE-182 | stays working; the OVE-182 part feeds `coordinator-attention.md` (exists) and planned `coordinator-surface.md` | AS-D25 |
| `coordinator-surface-2026-10/README.md` | active | stays working; mark §2 "What the surfaces say today (audited 2026-10-21)" dated | Predates OVE-182 and the Selection Workspace (`missionctl search`, `workspace check`) |
| `fault-tolerance-2026-10/LEDGER.md`, `FAULT-TOLERANCE-PROPOSAL.md` | active / draft | **park in place** (Q4) | Nothing built; last reconciled 2026-10-23 (`LEDGER.md:10,30`); index note says "ACTIVE program" |

## 3. Proposed archive moves

The tool exists: `python docs/tools/program_ledger.py {archive|archive-program|move} … [--dry-run]`.
Run every command with `--dry-run` first. `A=docs/specs/archive/provider-consolidation-2026-10`.

Single files (`archive <file> --kind <kind> --reason "…"`, destination `A/<kind>/<file>`):

- `PC/TRACING-PROPOSAL.md` → `A/proposals/` · `PC/BASELINE-2026-10-19.md` → `A/docs/`
- `PC/APPLICATION-KNOWLEDGE-BOUNDARY-DESIGN.md`, `PC/SPRINT-V-DESIGN.md` → `A/specs/`
- `PC/SPRINT-V-PLAN.md` → `A/sessions/` · `PC/SPRINT-V-RESEARCH.md` → `A/docs/`
- `PC/INTERVIEW-*-2026-10-24.md` (3) → `A/interview-instructions/`
- (Q2) `PC/SPRINT-SEQUENCE-2026-10-23.md` → `A/proposals/`; `PC/OWNER-INTERVIEW-2026-10-22.md`,
  `PC/SESSION-INTERVIEW-SITTING-I-2026-10-24.md` → `A/interview-instructions/`
- `PC/providers/deep_agents/{AUDIT,AUDIT-OUTPUT-TRANSFER-2026-10-22,ASYNC-SUBAGENTS-EXPLAINED}.md` → `A/docs/`
- `PC/providers/deep_agents/{SUBAGENTS,COGNITION-POINTS,SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER}.md` → `A/specs/`
- `PC/providers/deep_agents/DOMAIN-PROVENANCE-AND-STATE-SUPPLEMENT-2026-10-23.md` → `A/proposals/`
- `PC/sprint-oc/{HANDOFF-2026-10-28,HANDOFF-2026-10-28-S3,RECOVERY-AUDIT-2026-10-29}.md` → `A/docs/`
- `PC/sprint-oc/{KICKOFF,SESSION-CODEX-RESUME-2026-10-29,SESSION-OVERNIGHT-WORKFLOWS-2026-10-29}.md` → `A/sessions/`
- `PC/sprint-oc/SELECTION-AND-ROUTING-{DESIGN,INTERFACES}.md` → `A/specs/`

Folders (`move <src> <dest>`, structure kept):

- `PC/sprint-v` → `A/sprint-v`
- `PC/sprint-oc/provenance-2026-10-31` → `A/sprint-oc/provenance-2026-10-31`
- `PC/answers/gpt-6-astra-2026-10-24` → `A/interview-answers/gpt-6-astra-2026-10-24`
- `PC/answers/application-knowledge-boundary` → `A/interview-answers/application-knowledge-boundary`
- `PC/answers/output-contracts-final` → `A/interview-answers/output-contracts-final`
- `PC/answers/sprint-v` → `A/interview-answers/sprint-v`
- `PC/answers/sprint-oc-start` → `A/interview-answers/sprint-oc-start`

Within active programs: `PC/COORDINATOR-PROJECTION-PROPOSAL-2026-10-23.md` →
`docs/specs/coordinator-surface-2026-10/` (new row PR-02 there; PC row PR-07 → pointer).
After each `move`, check that answers files' frontmatter `interview:` still resolves (the tool rewrites
Markdown links and prose paths; frontmatter is not documented as rewritten) and set rows to `archived`.

## 4. ADR problems

| ADR | Problem | Evidence | Fix |
| --- | --- | --- | --- |
| 0021 | `proposed` but implemented; tooling part superseded by 0064 without a marker | `docs/knowledge/`, `docs/tools/okf_search.py`, `agents_docs_index.py` exist; 0064 retires "Mission Control's Python docs tools" at parity (`0064…md:4,43`) and does not name 0021 | Accept 0021; add "Amended by ADR-0064 (tooling)" to 0021 and "Amends ADR-0021" to 0064 |
| 0035-0041 | `proposed` (multi-provider packet), built and integrated on `main` | LaneProfile 226 src files; socketio 16; `continuation_transfer` 8; concepts `mission-stream.md`, `continuation-checkpoint.md`, `human-gates.md` describe them as built; archive README credits ADRs 0035-0041 with the program outcome | Q1: accept en bloc with "accepted 2026-11-xx, implemented by <commit/release>" |
| 0042-0050, 0052, 0053 | `proposed` (materialization-observation Run 2, finished and integrated 2026-10-20) | `environment_kit` 44 files, secret broker 22, `signal_ingress` 43, watcher descriptors 12, `owner_prerequisite` 22, `coordinator_inbox_wait` 10, `claude_managed` 89, `remote_session` 47; `log.md:1021-1180` records each as "proposed ADR-…" built | Q1; 0053 needs a code check (no `native_call_intent` symbol found) before accepting |
| 0054-0057 | `proposed`, built by tracing Stages 1-3 (merged 2026-10-22) | TR-D1..19 answered (L:182); `transcript_entry` v2 17 files, `retention_class` 4, `seed_head` 12 | Q1 |
| 0049 | Same as above; also contradicts accepted 0032, which still lists `subscribe` as CLI surface (`0032…md:17`) | Interview kept it proposed (`answers/.../DESIGN-DECISIONS.md:187`) | Accept, then mark 0032 "amended by ADR-0049" |
| 0050 | Amends 0035 (`0050…md:4`); 0035 carries no back-marker | — | Add "Amended by ADR-0050" to 0035 |
| 0027, 0029 | Partially superseded by 0061 (`0061…md:36`); they carry a 2026-10-26 amendment section but no "superseded in part by ADR-0061" line | `0027…md:12`, `0029…md:12` | Add the back-marker line |
| 0058-0062 | Identical boilerplate `description` ("Accepted output-contract target decision …") hurts retrieval; body says "does not certify runtime implementation" although OVE-204 slices 1-3 implement 0060 | `0060…md:4,12` | Write real descriptions; add an "Implementation" line citing `PROV/REPORT.md:33-35` |
| 0001, 0002, 0012, 0014, 0059, 0060 | Accepted, cited by no concept (0001 only by `index.md`) — fails SPEC-01 §3.3 rule 3 | grep of `ADR-00NN`/`adr/00NN` over `docs/knowledge` excluding `log.md`/`index.md` | Cite from `architecture.md` (0001), `persistence.md`/`database-component.md` (0002), `capabilities.md` (0012), `lanes-and-harness.md` (0014), `knowledge-services.md` (0059), new origin/receipts concept (0060), or the planned `decisions.md` |
| 0064-0067 | Accepted, cited by no concept; not Mission Control runtime | SDLC program ADRs | Cite from the planned `decisions.md` (rule 3 allows it) |
| 0037, 0048, 0053, 0054, 0056 (proposed) | Cited by no concept | same grep | Cite when accepted (0054 from `transcript-projection.md`, 0056 from `completion.md`, 0037/0048 from `environments.md`) |
| gap 0051 | Number reserved for "Sandbox Host placement and the `SandboxHost` port" and never written; the same plan reserved 0054 for "Local CLI job skills…", later reused for the transcript | `archive/materialization-observation-2026-10/DECISIONS.md:149-163`; no `SandboxHost` in `src/` | Leave the gap; record "0051 reserved, never written; placement funding-gated (R31, `0050…md:42`)" in `decisions.md` |
| (none) | OC-D204/OC-D205 changed the workflow-system taxonomy with no ADR | Only IA-11, DECISIONS `:347-348`, spec pack | Write ADR-0068 "Swarm is a StageGraph profile; EO reuses GoalDirected machinery" |

Clean (accepted, no supersession issue, cited by at least one concept): **27** —
0003-0011, 0013, 0015-0020, 0022-0026, 0028, 0030, 0031, 0033, 0034, 0063. Problems: 23 proposed,
16 accepted. No duplicate numbers; `docs/adr/` has no README (the index lives in
`AGENTS.md`).

## 5. Archive findings

- **Index exists.** `docs/specs/archive/README.md` lists the three whole programs (fast-track 63
  files, multi-provider 40, materialization-observation 225; total 334 with README and 5 single
  documents). Single documents under `archive/provider-consolidation-2026-10/` (4) and
  `archive/coordinator-surface-2026-10/` (1) are reachable only through ledger rows SP-05, SE-01..03
  and coordinator SE-01; acceptable by convention, but the README should list the per-program
  folders once this pass adds ~60 files there.
- **Sole source of current facts (promote):**
  - Fast-track `OWNER-FIXTURE-RUNBOOK.md` is cited by ten live files as the source of **current**
    blockers B2-B7: `capability-seeds.md:48,76`, `events-and-commands.md:137`, `authoring.md:114`,
    `cursor-lane.md:145`, plus `persistence`, `operations`, `mission-manifest`, `docs/DEVELOPMENT.md`,
    `docs/MISSION_CONTROL_LOCAL_API.md`. The runbook describes the release 1.1.0 stack. Re-verify each
    blocker against code and restate it in the concept; cite the runbook as provenance only.
  - ADR-0051 reservation and the Sandbox Host deferral exist only in the archived
    materialization-observation `DECISIONS.md:149-163` (see §4).
  - Archived `RUN-1-REPORT.md` is the evidence behind lane claims in `capabilities.md:126`,
    `cursor-lane.md:137`, `hosted-api-lanes.md:48`, `persistence.md:122`. Evidence-in-archive is fine
    by the README's rule; flag only if `release-and-qualification.md` should carry the lane status itself.
- **Sealed-artifact note must grow.** README "Sealed artifacts that cite old paths" names only the
  three archived packets. After this pass, add `PC/SPRINT-V-DESIGN.md` (cited by
  `seeds/knowledge_tools.py:35` and `mc.catalog.knowledge-tools-1.0.0..1.2.0.json`) and, if ever
  archived, `PC/sprint-oc/PROOFS.md` (`seeds/graph_route_schemas.py:22`, `artifact-schemas-1.0.1.json`).
- **Not in this repo's archive but program-owned:** PR-05's Human Review Gates supplement still
  sits at `platform/HUMAN-REVIEW-GATES-AND-STEERING-SUPPLEMENT-2026-10-22.md` (L:68, row `planned`).

## 6. Shortest reading path to current Sprint OC state (after the refactor)

Today: `AGENTS.md:1-60` has six dated banners that point at nine documents, three of them finished
(`SESSION-OVERNIGHT`, `KICKOFF`, `sprint-v/START-HERE`); `NS` is 1060 lines; `L:10-48` repeats
four more banners; facts are spread across HANDOFF-S3, RECOVERY-AUDIT, W1-EVIDENCE and the
provenance REPORT (~2,400 lines). Target, about 400 lines in four reads:

1. `AGENTS.md` — one dated "Current state" line: Sprint OC paused until Agentic SDLC merges; W0
   released, W1 open; link to NS. All other banners move to NS history or are deleted.
2. `NS` (≤150 lines, live part only): state and authority (W0/W1/W2-W4, OVE-169), versions and
   remote install state (1.8.0 both remotes; 1.9.0-1.12.0 built, no remote install), the W1 frontier
   (D27-D30 integrated, regression and rerun remaining; Biotech W1 never run), open proofs (live
   `knowledge_read_intent`, charter mount, MC→AIDB producer attribution, KS typed-column planner),
   source custody of `sprint-oc-wi14/wi15` and `w1fix-n`, next action. Dated batch logs NS:197-1060
   move to `A/docs/SPRINT-OC-LOG-2026-10-29-31.md`.
3. `PC/sprint-oc/release/W1-EVIDENCE.md` and the W1 rows of `PROOFS.md` — what W1 must prove.
4. Concepts for behaviour, not program files: `release-and-qualification.md` / `database-component.md`
   (W0, releases), `output-contracts.md`, `execution.md`, `workspace-closure.md`, the origin/receipts
   concept. `DECISIONS.md` and `IMPLEMENTATION.md` only on demand.

`okf_search.py` default roots then hold NS and APPLICATION-PORTS only; the retrieval test asserts the same.

## 7. Owner questions

1. **Accept the 23 implemented `proposed` ADRs (0021, 0035-0050, 0052-0057) en bloc?** Each gets
   "accepted 2026-11-xx; implemented by <release/commit>". *Recommend yes*, except hold 0053 until its
   native-call-intent gating is located in code. Without this, SPEC-01 rule 3 will treat the core of
   the lane and transcript architecture as undecided.
2. **Retire the sitting-I / sprint-sequence track?** SPRINT-SEQUENCE (cards A..I), OWNER-INTERVIEW
   (R0-R9), SESSION-INTERVIEW-SITTING-I, rows IQ-01/02/04, IA-01/02/05, SE-04/05/06, IS-01, OVE-149.
   *Recommend archive as superseded by Sprint OC and Agentic SDLC*; carry still-wanted open decision
   families (CO-D, WC-D, AC-D, HG-D) as one row each pointing at their proposal, and close OVE-149.
3. **Close D1-D9 of the program README?** *Recommend* recording D1 as overtaken (program running
   since 10-19) and folding D2-D9 into the `decisions.md` concept as open or answered, rather than
   leaving "still open" on the program's entry page.
4. **How is "parked" recorded for fault tolerance?** No `parked` status exists. *Recommend* keeping
   the folder in place, ledger header "Parked 2026-11-01 (AS-D25); resumes on owner request" and
   index note "PARKED program" — the archive is reserved for completed work.
5. **Write ADR-0068 for OC-D204/OC-D205 (Swarm as StageGraph profile, EO on GoalDirected
   machinery)?** *Recommend yes*; the taxonomy change otherwise lives only in an `open` answers file
   and the spec pack, and three concepts still contradict it.
6. **Split NS and archive its dated batch logs (NS:197-1060) now, while Sprint OC is paused?**
   *Recommend yes*; it is the single largest reading cost and the owner's W1 frontier is already
   stated in NS:117-129.

## 8. Ordered execution steps for the refactor agent

Work on `sprint-oc`; no secrets; commit per step with the OVE-206 (or successor) id.

1. Record owner answers Q1-Q6 in the sitting answers file; do not proceed on unanswered items.
2. **Fix code that names program paths:** remove `SESSION-CODEX-RESUME-2026-10-29.md` from
   `docs/tools/okf_search.py:43-44` and from the expected set in
   `tests/unit/test_documentation_retrieval.py:56-60`; run that test.
3. **Promote facts before moving** (one commit per concept): W0 release and remote-install state
   → `release-and-qualification.md` and new `database-component.md`; R0-R7 → `application-profile`,
   `model-catalog`, `lanes-and-harness`, `agent-configuration` citing ADR-0063 and source; OVE-204 →
   new origin/receipts concept (cites ADR-0060), `knowledge-services` (read intent, ADR-0059),
   `capability-seeds` (charters, 1.0.4), payload store into `environments` or `operations`,
   `workspace-closure`; overnight outcomes → `execution`, `mission-chains`, `output-contracts`;
   OVE-182 → `coordinator-attention`; OC-D204/205 → `parallel-swarm`, `evaluator-optimizer`,
   `workflow-systems`. Label each fact implemented / tested / integrated / qualified with its proof path.
4. ADR edits (§4): status changes per Q1, back-markers (0021/0064, 0027, 0029, 0032/0049,
   0035/0050), real descriptions for 0058-0062, ADR-0068 per Q5, concept citations for the ten
   uncited accepted ADRs.
5. Re-verify fast-track blockers B2-B7 against code; restate them in the citing concepts (§5).
6. Split NS: keep NS:9-195 rewritten to ≤150 lines (§6 step 2), copy RECOVERY-AUDIT §5 remaining
   scope and the provenance REPORT §5 follow-ups into it, move NS:197-1060 to
   `A/docs/SPRINT-OC-LOG-2026-10-29-31.md` with `program_ledger.py move`.
7. Collapse `AGENTS.md` banners (lines 1-60, incl. `:47` Sprint V) to one current-state line; collapse
   `L:10-48` and the sprint-oc `README.md:11-17` head the same way.
8. Run the §3 archive and folder moves, each with `--dry-run` first; fix what the tool lists in
   non-Markdown files; extend the archive README sealed-artifact note (§5); check every moved answers
   file's `interview:` frontmatter.
9. Update ledger rows: set moved rows `archived`; correct DOC-13, DOC-23, DOC-33, DOC-34, DOC-36,
   SE-14, SE-16, IA-10, SP-10; move PR-07 to the coordinator ledger; add the parked header (Q4) to the
   fault-tolerance ledger and update `docs/agents/index-notes.toml`; rewrite the coordinator ledger's
   R8/sprint-I next step.
10. Close the session: `python docs/tools/program_ledger.py check`,
    `python docs/tools/agents_docs_index.py`, `python docs/tools/check_links.py`,
    `python docs/tools/check_docs.py`, and the retrieval unit test; report passed/failed separately.
