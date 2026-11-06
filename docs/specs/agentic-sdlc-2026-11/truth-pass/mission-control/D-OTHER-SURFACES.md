---
type: Working Draft
title: "Mission Control truth pass D: every other tracked Markdown surface"
description: "Exploration part D of the Mission Control truth pass (2026-11-01, sprint-oc). Triage of the 324 tracked Markdown files outside docs/knowledge, docs/specs, docs/adr, mission-control-general and .agents/skills: disposition per file or group, spot-checks against source, the 33 tracked .scratch files, the 14 nested AGENTS.md files against the DOC-02 module-block grammar, the proposed module map, owner questions and ordered steps for the refactor agent. Read-only findings; nothing was moved."
tags: [mission-control, truth-pass, sdlc]
date: 2026-11-01
status: draft
---

# Truth pass D: other Markdown surfaces

**Progress toward the owner goal.** The goal is complete Deep Agents workflow and agent
configuration logic. This pass does not change the runtime. It does three things for that goal:

- It clears 69 files of noise from search: 31 to archive, 5 to delete and 33 `.scratch` files to
  untrack.
- It names the 13 nested `AGENTS.md` files that become generated module blocks. The Deep Agents
  lane block is the first of them.
- It finds a missing `CLAUDE.md`. Because of it, Claude Code sessions never load the Mission
  Control root `AGENTS.md`.

The next blocker is unchanged: the S1 CLI and `.sdlc/modules.json` must exist before module
blocks can be generated. Until then the refactor agent moves, fixes and untracks files. It does
not hand-convert the nested guides.

Method: `git ls-files '*.md'` minus the excluded trees. Last-commit dates are from
`git log -1 --format=%cs`. Inbound links were counted from `docs/knowledge`, the root
`AGENTS.md`, `README.md` and `docs/README.md`. Code loading was checked by grep over `src`,
`tests`, `scripts`, `packages` and `deployments`. Each spot-check cites file:line.

## 1. Summary counts by disposition

| Disposition | Files | Notes |
| --- | ---: | --- |
| keep-in-place | 233 | 96 are immutable release or bundle bytes; 66 are test inputs; 29 are runtime skills under seed custody |
| stays (root, edited only by its own process) | 5 | `AGENTS.md`, `GLOSSARY.md`, three `docs/agents` delta files |
| becomes module `AGENTS.md` block | 13 | 10 under `src/mission_control`, plus `tests`, `integrations/biotech`, `packages/mission-control-db-contract` |
| fold | 4 | `docs/AGENTS.md`; three `docs/agents` method files go to `belllabs-method` at S1 |
| archive | 31 | dated reports, the finished two-project plan, 8 qualification files, 10 coordinator plans inside `src/` |
| delete | 5 | `.cursor/rules/_briefings/*`, which call themselves non-authority |
| untrack (`.scratch`) | 33 | plus 68 tracked `.json` in the same tree (101 files in all) |
| **Total** | **324** | |

## 2. Table by area

Columns: path, lines, last commit, current? (with evidence), disposition.

### Root (3)

| Path | Lines | Date | Current? | Disposition |
| --- | ---: | --- | --- | --- |
| `AGENTS.md` | 166 | 11-01 | Covered by the [compressed draft](../../AGENTS-MD-MISSION-CONTROL-DRAFT-2026-11.md) | stays (regenerate at cutover) |
| `GLOSSARY.md` | 856 | 11-01 | Cited by 28 concepts | stays |
| `README.md` | 84 | 10-12 | **Stale.** L13-16: the two-project plan and "installed live… `supabase-blue-ocean`". L55: "Release 1.0.0 is installed". The newest release built is 1.12.0 and the newest deployment lock is 1.9.0 (`docs/MISSION_CONTROL_IMPLEMENTATION_STATUS.md:9-17`). L62: the `make check` comment omits conformance and skills-check (`Makefile:314`). | keep-in-place, rewrite those lines |
| `CLAUDE.md` | — | absent | **Gap.** SPEC-01 §3.2 requires `CLAUDE.md` = `@AGENTS.md`. Neither MC nor `platform/` has one. This session's loaded context held the workspace `AGENTS.md` and no MC root guide. | create (Q6) |

### `docs/*.md` (10)

| Path | Lines | Date | Current? | Disposition |
| --- | ---: | --- | --- | --- |
| `docs/AGENTS.md` | 30 | 10-24 | Current, but it describes `agents_docs_index.py` and `okf_search.py`, which the S1 CLI replaces | fold into `docs/agents/documentation-surfaces.md`, then delete at S1 |
| `docs/README.md` | 38 | 10-24 | **Stale.** L13-15 list three archived packets. L30 covers deleted trees (a REMOVAL_GUIDE topic). L37 links the finished two-project plan. The agentic-sdlc program is missing. | keep-in-place, trim to an index of operator guides and program ledgers |
| `docs/DEVELOPMENT.md` | 172 | 10-27 | Current: its targets match `Makefile:68-375`. Its L13 `make check` comment omits `skills-check`, which L138 states. | keep-in-place (operator guide) |
| `docs/WSL2_WORKER_RUNBOOK.md` | 143 | 10-24 | Run 2 procedure for the non-Deep-Agents local lanes. The INFRASTRUCTURE draft cites it at 4 places. | keep-in-place |
| `docs/MISSION_CONTROL_LOCAL_API.md` | 1217 | 10-28 | Mostly current: `create_app` is at `bootstrap/api.py:1024` and `Makefile:184`. **Stale at L19-22** ("Release 1.0.0… installed in both Supabase projects"). | keep-in-place, fix L19-22 |
| `docs/MISSION_CONTROL_IMPLEMENTATION_STATUS.md` | 483 | 11-01 | Marked stale on 2026-11-01 (OVE-206, L9-17); nothing after 10-24 | archive (Q2) |
| `docs/REMOVAL_GUIDE.md` | 795 | 10-29 | Provenance of the 2026-10-03 clean break. 3 concepts cite it. The root draft drops it. | archive (Q2) |
| `docs/REPORT_SOURCE_FOUNDATION.md` | 178 | 10-29 | Current Sprint OC fixture procedure; `scripts/report_source_sandbox.py` exists | keep-in-place |
| `docs/LIFECYCLE_RELIABILITY_2026-10-11.md` | 482 | 10-12 | Dated handoff with 0 inbound links | archive |
| `docs/DEPLOYMENT_OPTIONS_2026-10-12.md` | 274 | 10-24 | Superseded by `sprint-oc/CLOUD-ENVIRONMENTS-AND-DEEP-AGENTS-DEPLOYMENT-2026-10-31.md`, which cites it at L66 | archive after `docs/INFRASTRUCTURE.md` exists |

### `docs/qualification` (14), `docs/plans` (4), `docs/agents` (6), `docs/research` (1), `docs/organization` (1)

| Path | Lines | Date | Current? | Disposition |
| --- | ---: | --- | --- | --- |
| `qualification/lanes/README.md` (Cursor scope only) | 67 | 10-24 | Cited by `cursor-lane`, `lanes-and-harness` and `qualification` | keep-in-place |
| `qualification/lanes/{claude_agent_sdk,codex,cursor_cloud,cursor_local}/README.md` | 100-168 | 10-12…10-27 | Per-lane evidence for the secondary lanes; cited by `provider-lanes` and `cursor-lane` | keep-in-place |
| `qualification/lanes/{claude_cloud,codex_cloud}/{FEASIBILITY,REVALIDATION-2026-10-09}.md` (4) | 117-249 | 10-09…10-24 | Outcome 3 (not admitted); decision provenance | archive |
| `qualification/local-profiles/README.md` | 36 | 10-09 | MP-22 readiness, multi-provider era | archive |
| `qualification/parity/multi-provider-2026-10-09.md`, `qualification/release/multi-provider-2026-10.md` | 224, 265 | 10-10, 10-24 | The packet was archived 2026-10-23. L25 of the release file already says "historical". | archive |
| `qualification/two-project/LIVE_PLAN.md` | 140 | 10-12 | **Stale.** Titled "awaiting owner approval", but the install ran 2026-10-03. `packages/.../AGENTS.md:33` still says to read it before touching Supabase. | archive; fix that pointer |
| `qualification/wake-channels/README.md` | 126 | 10-13 | Proof record cited by `wake-channels` | keep-in-place |
| **Gap** | | | `qualification/lanes/` has no `deep_agents` entry. Deep Agents proof lives in `docs/specs/provider-consolidation-2026-10/providers/deep_agents/`. | none; Deep Agents remains program-owned |
| `plans/mission-control-two-project-rollout/*` (4) | 100-632 | 10-07…10-12 | Finished 2026-10-03/12; 0 concept links | archive |
| `agents/issue-tracker.md`, `triage-labels.md`, `domain.md` | 81, 23, 51 | 10-07…10-24 | `to-tickets`, `triage` and `to-spec` need them; they are MC deltas | stays |
| `agents/documentation-surfaces.md`, `program-workspace.md`, `matt-pocock-skills.md` | 85, 82, 58 | 10-24 | Workspace method that the S1 contract absorbs; cited by `belllabs-method` and 9 skills | fold into `belllabs-method` at S1 (Q5) |
| `research/2026-10-07-coding-lane-surfaces.md` | 183 | 10-12 | Cited by ADR-0023, ADR-0026 and ADR-0028 | keep-in-place |
| `organization/README.md` | 18 | 10-03 | Its JSON maps are loaded by `tests/qualification/two_project/test_static_architecture.py` | keep-in-place |

### `packages/mission-control-db-contract` (105)

| Path | Files | Date | Current? | Disposition |
| --- | ---: | --- | --- | --- |
| `AGENTS.md` | 1 | 11-01 | Current table ("newest built 1.12.0"). **L32-33 are stale:** they point to LIVE_PLAN and require owner approval, while the owner's rule makes remote Supabase disposable. | module block (hand table above the marker) |
| `README.md`, `releases/README.md` | 2 | 10-31, 11-01 | Current release authority and release notes | keep-in-place |
| `releases/<v>/{component/generated/contract.md, runtime/README.md, runtime/AGENT_SERVER_TOPOLOGY.md}` | 37 | 10-14…10-31 | Generated per release and immutable. The runtime copies match the top-level ones byte for byte (`diff` on 1.4.1 and 1.12.0). | keep-in-place, never edit |
| `component/generated/contract.md` | 1 | 10-14 | Frozen 1.4.0 input that is no longer used to build | keep-in-place |
| `runtime/README.md`, `runtime/AGENT_SERVER_TOPOLOGY.md` | 2 | 10-07 | Current: `langgraph-api==0.12.0` matches `pyproject.toml:33` and `agent_server/langgraph.json:3` | keep-in-place |
| `seeds/README.md`, `seeds/AGENT_CAPABILITY_SEED_NOTES.md` | 2 | 10-24, 10-28 | Seed documentation | keep-in-place |
| `bundle-sources/README.md` + `agent-skills-1.0.{0,1,2,3}/**` | 60 | 10-14…10-31 | Byte-frozen copies pinned by `FROZEN_BUNDLES`. Identical to `skills/` (`diff -q` was silent on all 12 pairs checked). | keep-in-place, never edit |

### `skills/` (29): runtime agent skills shipped by Mission Control

| Path | Files | Date | Current? | Disposition |
| --- | ---: | --- | --- | --- |
| `mission-control{,-author,-observe,-catalog,-compose,-intervene}/**` | 14 | 10-07…10-27 | Every `missionctl` verb used exists in `interfaces/cli`. Their wording is under review in the coordinator-surface program. | keep-in-place: bytes are custody-pinned, and an edit needs a new seed version |
| `biotech-knowledge-charter/**`, `ai-engineer-knowledge-charter/**` | 6 | 10-31 | Loaded by `bootstrap/application_profiles.py` | keep-in-place |
| `mc-cognition-*/SKILL.md` | 8 | 10-14 | 8-line stubs referenced by the cognition-profile seeds | keep-in-place |
| `mc-signals/SKILL.md` | 1 | 10-13 | **Duplicate**, byte-identical to `src/.../agentic_components/mc_signals_skill.md` | keep-in-place; dedupe in code later (Q4) |

### `src/mission_control` (21)

| Path | Lines | Date | Current? | Disposition |
| --- | ---: | --- | --- | --- |
| `AGENTS.md`, `contracts/`, `domain/`, `application/`, `interfaces/`, `adapters/`, `adapters/temporal/`, `adapters/postgres/` | 13-23 | 10-03…10-07 | Cited paths exist (32 checked). `application/AGENTS.md:10` "ports/payloads" is now `ports/payloads.py`. | module block |
| `bootstrap/AGENTS.md` | 21 | 10-27 | **L6 is stale.** `installation.py` "pending removal" was deleted in `f90daeeb`. | module block; drop L6-7 |
| `adapters/deep_agents/AGENTS.md` | 37 | 10-27 | Current: `deepagents==0.7.5` (`pyproject.toml:18`), `langgraph==1.2.10` (`:32`). The worked block is in the draft §f. | module block (the first one) |
| `application/agentic_components/mc_signals_skill.md` | 51 | 10-13 | Loaded by `telemetry.py` | keep-in-place |
| `interfaces/mcp/COORDINATOR_ARCHITECTURE_AND_PLAN.md` + `implementation_plans/*` (9) | 114-1107 | 10-03…10-07 | Interview plans dated 2026-07-27 from the predecessor repo. They cite the absent `biotech-meta` and deleted `docs/interview_and_research_result_documentation`. 0 inbound links and 0 code references. | archive (Q3) |

### `tests/` (69)

| Path | Files | Current? | Disposition |
| --- | ---: | --- | --- |
| `tests/AGENTS.md` | 1 | Current | module block |
| `tests/conformance/lanes/README.md` | 1 | 10-27, cited by 3 concepts | keep-in-place |
| `unit/context/goldens/worked_example.context.md`, `unit/frames/goldens/transcript.md`, `integration/postgres/goldens/transcript_c1_run.md` | 3 | Loaded by `test_render.py`, `test_transcript.py:206` and `test_transcript_postgres.py` | keep-in-place |
| `fixtures/**` (skills, projections, report-source-foundation, manifests, schema_context) | 62 | Test inputs. `schema_context/trudiagnostic_report_2026-03-30.md` is public company research, not PHI (its README). `projections/deep_agents/memory/AGENTS.md` is a fixture, not a guide. | keep-in-place; exclude from AGENTS.md scanning |
| `archive/README.md`, `archive/SCHEMA_CONTEXT_SELECTION_WORKFLOW_HANDOFF.md` | 2 | Self-described "stale notes, not executed" | archive into `docs/specs/archive` |

### `deployments/` (11), `experiments/` (10), `integrations/` (2), `.cursor/` (5)

| Path | Lines | Date | Current? | Disposition |
| --- | ---: | --- | --- | --- |
| `deployments/hosted-packs/ai-engineer/**` (5) | 11-14 | 10-13 | Loaded by `adapters/{anthropic_managed,openai_agents}/pack.py` | keep-in-place |
| `deployments/cognition-profiles/README.md` | 32 | 10-14 | Seed documentation | keep-in-place |
| `deployments/cloud_runtime/README.md` | 247 | 10-12 | "Prepared, not deployed" (L7). It documents `plan.py`, and the 10-31 cloud roadmap links it. | keep-in-place; add a pointer to the 10-31 roadmap |
| `deployments/cloud_runtime/{APPROVAL_PLAN,INVENTORY}.md` | 307, 59 | 10-12 | Dated 2026-10-11 Lightsail proposal and inventory. They hold the AWS account id and an IAM user name. These are identifiers, not secrets. | archive |
| `deployments/worker-aws/README.md`, `deployments/ingress-vercel/README.md` | 77, 36 | 10-14 | Package READMEs. `worker-aws` holds the account, namespace and VPC ids. | keep-in-place; `INFRASTRUCTURE.md` should cite them |
| `experiments/docs_retrieval/**` (5) | 7-57 | 10-09 | Measures ADR-0021 retrieval, which feeds `RETRIEVAL-AUDIT-BASELINE` | keep-in-place; cite from the bench baseline |
| `experiments/{dynamic_research_swarm,langgraph_temporal_stagegraph}/**` (4) | 64-128 | 10-03 | Imported by `tests/experiments/*` | keep-in-place |
| `experiments/LANGGRAPH_TEMPORAL_DEEPAGENTS_STAGEGRAPH_EXPERIMENT_HANDOFF.md` | 898 | 10-03 | Experiment brief with 0 links | archive |
| `integrations/biotech/AGENTS.md` | 39 | 10-07 | Current; the paths exist | module block |
| `integrations/biotech/README.md` | 99 | 10-03 | Cited by 1 concept | keep-in-place |
| `.cursor/rules/_briefings/*` (5) | 7-117 | 08-11…10-07 | The README says "not agent-facing authority… must not be applied". `03` targets the absent `biotech-meta`. | delete |

`.agents/skills` (not triaged): 11 directories are absent from `skills-lock.json` and were authored
locally: `architecture-projection`, `belllabs-method`, `claude-code-headless`, `codex-exec`,
`coding-cli-jobs`, `cursor-agent-headless`, `grill-with-answers`, `mission-control-coordinator`,
`mission-control-docs`, `mission-control-local-setup`, `provider-research`. SPEC-01 §3.3 rule 9
(lock matches vendored skills) will fail on them unless the lock separates "local" from
"vendored".

## 3. Tracked `.scratch` findings

`.gitignore:149` ignores `.scratch/`. Even so, 101 files are tracked: 33 `.md` and 68 `.json`
under `workspace-profile-smoke/`. They were added in six commits between 2026-07-19 and
2026-07-24 (`7de54a57` through `16fa63de`), before the ignore rule. Nothing in `src`, `tests`,
`scripts`, `packages`, `docs/knowledge`, `docs/adr`, `Makefile` or `pyproject.toml` references
them. They are predecessor-repo planning material (GitHub issues for
`Overton77/belllabs-research-ingestion-evaluation-content-services`).

| File(s) | Lines | Private runtime receipt? |
| --- | ---: | --- |
| `.scratch/issue-7-8-artifact-acceptance-test-note.md` | 12 | **Yes.** L8 is an S3 bucket name that embeds the AWS account id. L10 has live workflow and artifact UUIDs. |
| `.scratch/handoffs/2026-07-19T15-58-00-04-00-f2-to-f3/HANDOFF.md` | 244 | **Credential-shaped string at L206.** It is a loopback dev-compose DSN with an inline user and password (127.0.0.1:55432). It is low risk, but secret scanners will flag it. |
| `.scratch/handoffs/issue-7-8-live-artifact-acceptance.md` | 77 | Run procedure (S3, Mongo, Tavily); no values |
| `.scratch/handoffs/2026-07-19T14-35-00-04-00-f1-to-f2/HANDOFF.md`, `…T16-35…-f3-stagegraph-to-f3-goaldirected/HANDOFF.md` | 202, 73 | No; July session handoffs |
| `.scratch/tuning_goals/schema-context-selection-workflow-python-goal.md` | 1591 | One UUID at L941 (a fixture id); no account data |
| `.scratch/control-plane-foundations-and-capabilities/issues/{01..21}-*.md`, `issues/INDEX.md` | 44-357 | No; issue drafts with GitHub URLs |
| `.scratch/control-plane-foundations-and-capabilities/{specs/11-schema-grounding-pipeline-spec.md, handoffs/11-schema-grounding-pipeline-handoff.md}` | 910, 553 | No. The work was promoted into `integrations/biotech` (schema grounding). |
| `.scratch/ISSUE_BRANCH_PR_LIFECYCLE.md` | 156 | No; superseded by SPEC-01 §7 |
| `.scratch/cursor-rules-proposal-2026-07-20.md` | 156 | No; it names a private SSH host alias for the old remote |
| `.scratch/workspace-profile-smoke/schema/skills/schema-navigation/SKILL.md` (+68 `.json`) | 8 | No; a smoke projection of the Biotech schema |

The 33 files are: 21 issue drafts plus the index, 1 spec, 1 issue-11 handoff, 4 handoffs, 2
issue-7/8 notes, 1 tuning goal, 1 lifecycle, 1 cursor proposal and 1 smoke SKILL.

Disposition for all 101: **untrack** with `git rm -r --cached .scratch`. The files stay on disk.
Git history keeps the account id and the loopback DSN. Neither is a cloud secret. A history
rewrite is not recommended (Q1).

## 4. Nested AGENTS.md files and the proposed module map

There are 14 tracked nested guides. Two more files match the name but are not guides:
`tests/fixtures/projections/deep_agents/memory/AGENTS.md` (a fixture) and
`docs/specs/.../deep_agents/SUBAGENTS.md`.

| Guide | Bytes | Shape today | Conforms to DOC-02 §3? |
| --- | ---: | --- | --- |
| `src/mission_control/AGENTS.md` | 850 | prose | No markers; fully replaceable |
| `contracts/`, `domain/`, `interfaces/`, `adapters/temporal/`, `adapters/postgres/`, `adapters/` | 751-1,075 | prose | No markers; fully replaceable. The draft §f block for `domain` replaces 773 B. |
| `application/` | 1,259 | prose | No; it names entrypoints, which fit `Entrypoints:` |
| `bootstrap/` | 1,421 | prose | No; it holds one stale line (L6) |
| `adapters/deep_agents/` | 2,627 | table + Invariants + Verify | Closest. Its table stays above the marker (G5). Verify has no slot (G6). |
| `packages/mission-control-db-contract/` | 2,431 | table + Invariants + Verify | Same as `deep_agents`; L32-33 are stale |
| `integrations/biotech/` | 2,160 | table + Invariants | Same pattern |
| `tests/` | 896 | prose | No; it is about tests rather than code |
| `docs/AGENTS.md` | 2,081 | prose rules | Not a code module: fold it (section 2) |

None of the 14 has `<!-- BEGIN:sdlc-module -->` markers, and none has the `Explained by:`,
`Decided by:`, `Depends on:` or `Used by:` lines.

**Proposed module map (≤2 levels below the package root).** Take the draft's 14 code-map entries
as they are. `adapters/agent_server` (36 `.py`, no guide today) is cutover prerequisite 4. Add
two entries for the owner goal:

| Module id | Directory | Why |
| --- | --- | --- |
| `domain.programs` | `src/mission_control/domain/programs` (18 `.py`) | The workflow systems (Stage Graph, Goal Loop) that the owner goal names |
| `domain.authoring` | `src/mission_control/domain/authoring` (20 `.py`) | Manifest compile: the agent-configuration path behind `agent-configuration.md` |
| `skills` | `skills/` | Not code. It needs one `Owner of:` line: bytes are pinned by `FROZEN_BUNDLES`, so an edit means a new seed version (Q4). |

Do not generate blocks for `docs/`, `tests/fixtures/**`, `deployments/*` or `experiments/*`.
Their READMEs suffice. `modules.json` should exclude `tests/fixtures/**` from guide discovery.

## 5. Owner questions

1. **Untrack `.scratch` now?** Recommendation: yes. Run `git rm -r --cached .scratch` (101 files)
   in one commit and do not rewrite history. Nothing references these files. The only private
   receipt, the issue-7/8 note, holds an account id, not a credential. The promoted
   schema-grounding spec is already superseded by `integrations/biotech`.
2. **One archive batch, and does implementation status leave the precedence chain?**
   Recommendation: yes to both. Move the 31 archive rows into
   `docs/specs/archive/mc-surfaces-2026-10/` with `program_ledger.py archive` or `git mv`, and
   rewrite the concept links. Then restate the precedence rule as spec > ADR > knowledge >
   program ledger / `NEXT-SESSION`. The status file already defers to those (L9-17).
3. **The ten coordinator plans inside `src/.../interfaces/mcp/`: archive or delete?**
   Recommendation: archive them beside the coordinator-surface program. Round R8 may want the
   July reasoning, and Markdown inside a wheel package is misplaced either way.
4. **Should `skills/` get a module block, and the `mc-signals` duplicate be resolved?**
   Recommendation: give it a block now (custody rule only). Leave the code dedupe of
   `mc_signals_skill.md` to the coordinator-surface program. Changing those bytes changes seed
   pins.
5. **Do the three method files in `docs/agents` move into `belllabs-method` at S1?**
   Recommendation: yes at S1, not now. Keep `issue-tracker`, `triage-labels` and `domain` as MC
   deltas (SPEC-01 §3.2 "process deltas only").
6. **Create `CLAUDE.md` (`@AGENTS.md`) in Mission Control now, ahead of S1?** Recommendation:
   yes. It is one line, SPEC-01 §3.2 requires it, and without it Claude Code never loads the MC
   root guide.

## 6. Ordered execution steps for the refactor agent

Work on `sprint-oc`. Preserve dirty work. Run every step from
`platform/mission-control`.

1. **Untrack** (Q1): `git rm -r --cached .scratch`. Check that `git check-ignore .scratch/x`
   reports `.gitignore:149` and that the files remain on disk.
2. **Adapter** (Q6): create `CLAUDE.md` containing `@AGENTS.md`.
3. **Delete** `.cursor/rules/_briefings/` (5 files).
4. **Archive** (Q2, Q3): move these 31 files into one dated archive folder with a README listing
   their origins:
   - the 4 dated `docs/*.md`
   - `docs/plans/mission-control-two-project-rollout/` (4)
   - the 8 qualification files
   - `interfaces/mcp/COORDINATOR_*.md` and `implementation_plans/` (10)
   - `tests/archive/` (2)
   - the experiments handoff (1)
   - `deployments/cloud_runtime/{APPROVAL_PLAN,INVENTORY}.md` (2)

   Keep `DEPLOYMENT_OPTIONS` in place until `docs/INFRASTRUCTURE.md` exists.
5. **Rewrite links** to the moved files in these places:
   - concepts: `qualification`, `release-and-qualification`, `persistence`,
     `lanes-and-harness`, `provider-lanes`, `operations`, `knowledge-services`,
     `output-contracts`, `index`
   - `README.md`, `docs/README.md`, `packages/.../AGENTS.md`
   - the cloud roadmap (L66)

   Leave `log.md` entries unchanged, since they are history.
6. **Fix stale lines in the files that stay:**
   - `README.md` L13-16, L55-57 and L62
   - `docs/MISSION_CONTROL_LOCAL_API.md` L19-22
   - `docs/README.md`: drop L13-15, L30 and L37; add the agentic-sdlc ledger
   - `src/mission_control/bootstrap/AGENTS.md` L6-7
   - `packages/mission-control-db-contract/AGENTS.md` L32-33: point to the disposable-target
     rule and to `releases/README.md`
   - `docs/DEVELOPMENT.md` L13: add `skills-check`
7. **Fold** `docs/AGENTS.md` into `docs/agents/documentation-surfaces.md`, keeping its OKF and tool
   rules, then delete it. The `docs/agents` method files wait for S1 (Q5).
8. **Do not touch** these: `skills/**`, `packages/.../bundle-sources/**`, `releases/**`,
   `tests/fixtures/**`, `deployments/hosted-packs/**` and any golden file. Tests or seed pins
   load their bytes.
9. **Regenerate and check:** `python docs/tools/agents_docs_index.py`, then
   `python docs/tools/check_docs.py` and `make docs-check`. Report each check as passed or failed.
10. **Commit** once the checks pass. Use one docs commit, or one per step 1/3/4. Name OVE-206 if
    the owner keeps that issue for the truth pass.
11. **At S1 (not now):** register the 17 module ids from section 4 in `.sdlc/modules.json` and
    generate the blocks. The `adapters/deep_agents` block from draft §f goes first. Then fold
    the `docs/agents` method files.
