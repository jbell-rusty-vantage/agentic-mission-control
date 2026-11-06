---
type: Working Draft
title: "Mission Control truth pass B: the 64 knowledge concepts against live code"
description: "Exploration part B of the Mission Control truth pass: every docs/knowledge concept checked against sprint-oc HEAD c73cb355 and the recent work (releases to 1.12.0, nine lane profiles, Sprint OC W0/R0-R7/WI, overnight workflows, Qualia and AI Engineer fixtures, Selection Workspace, provenance OVE-204), with a freshness verdict, file:line evidence and an action per concept; recent work with no concept home; a Deep Agents group proposal; owner questions; ordered refactor steps."
tags: [mission-control, truth-pass, sdlc]
date: 2026-11-01
status: draft
---

# Truth pass B: knowledge concepts (Mission Control)

Read on 2026-11-01 from `sprint-oc` HEAD `c73cb355`. That is four commits past
[STATE](../../STATE-mission-control-2026-11.md) (`ce9d2f13`): `f992ea60`, `c73cb355`, `ad28b457` and `9c0c8b7b`
already fixed STATE D1, D2-D4, D6-D10, D12 and D13 and renumbered `release_200` to 0071/0072. The
dirty `cursor_native.py` reported in STATE §5 is clean now. Paths are relative to `platform/mission-control/`:
`K/` = `docs/knowledge/`, `NS` = `docs/specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md`,
`PROV` = `…/sprint-oc/provenance-2026-10-31/REPORT.md`, `RB` = `…/sprint-oc/release/RELEASE-BUNDLE.md`.
Labels follow STATE: implemented < tested < integrated < qualified. Only W0 is qualified, with recorded
limitations (RB:22). Categories come from [DOC-07](../../CONCEPT-LISTS-DRAFT-2026-11.md). Dates are the
last commit on the concept and the newest commit among its cited non-doc sources (`MM-DD`, 2026).

Nothing was rerun. Each verdict rests on reading source, tests, migrations and the cited records.
Three helper reads covered 52 concepts and this author covered 12; the high-impact contradictions were
spot-checked in source.

## 1. Summary

| Verdict | Count | Meaning |
| --- | --- | --- |
| fresh | 13 | Load-bearing claims verified; no material later code change |
| minor drift | 19 | Claims hold, but later code or recent work is missing |
| stale | 7 | Significant claims out of date (versions, status, missing major work) |
| contradicted | 25 | At least one claim is false against code or release evidence (file:line on both sides) |

Recurring causes:
- **"Not built yet" sentences never revisited** (18 concepts): built work still reads as future, e.g.
  0060/0061/0063 are in built releases 1.7.0/1.8.0, MP-12 is integrated, IngressDrainer and the minter
  are composed.
- **Version and status facts restated inside concepts** (persistence, qualification,
  release-and-qualification, capability-seeds). These go stale the day a release is built.
- **The 10-30/10-31 work has no concept homes.** Linked exports (1.10.0/1.11.0), Qualia repairs, the paid
  fixtures as evidence, B3 native plan decisions and S3 mission-payloads appear only in `K/log.md`, or nowhere.
- **Index and log.** `K/index.md:7-34` still opens on the 10-29 recovery, Run 2 and "next program:
  provider consolidation (draft)". `hosted-api-lanes` is missing from every index table (`index.md:125`).
  `K/log.md` is 1,239 lines and has no entry for the Qualia fixtures, the AI Engineer fixtures or releases
  1.10/1.11.

Worst five: `persistence`, `release-and-qualification` (with `qualification`), `context-and-continuation`,
`output-contracts`, and the Swarm/EO trio (`workflow-systems`, `parallel-swarm`, `evaluator-optimizer`).

## 2. Concept table

Verdict codes: F fresh, D minor drift, S stale, C contradicted. The "Stale/contradicted" column cites
`concept:line vs evidence`.

| Concept | Cat. | Lines | Date / src | V | Stale or contradicted claims | Highest label of main claim (proof) | Recent work to absorb | Action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| architecture | boundaries | 38 | 10-12/11-01 | D | none false | tested (`tests/architecture/test_package_boundaries.py`) | resolution seam (`domain/resolution`, `application/resolution`, `application/selection`); lane packages own their writers (OC-R3) | update: add the seam and lane-package rows |
| knowledge-services | boundaries | 160 | 10-31/10-31 | D | `:100` read_intent does not say it was "not exercised live" (PROV §3 row 4) | integrated, slice 1 (PROV:33) | slice 2 gateway minting (PROV:34) | update labels; move the Biotech inventory `:40-74` out (at cap) |
| application-profile | boundaries | 90 | 10-27/10-31 | D | `:71` W0 live describe is done; `[workspace]` (`domain/resolution/profiles.py:143-190`) and `charter_skill` (`deployments/ai-engineer/application.toml:41`) absent | tested (`tests/conformance/applications/test_application_profiles.py`) | slices 5 and 6 profile tables | update |
| interfaces | surfaces | 160 | 10-31/10-31 | S | `:11-12` claims to list what is mounted; 7 routers mounted at `bootstrap/api.py:965-982` are absent (ingress, cognition_points incl. `/closures`, artifacts, run_evidence, coordinator_inbox, output_inspection, knowledge_reviews); CLI `:59-66` and MCP `:78-100` miss groups | tested (`tests/unit/mission_control/test_public_interfaces.py`) | slice 5 closure routes; WI-19; WI-07/08 output routes | split: generate the inventory; keep the spec-gap prose |
| events-and-commands | surfaces | 159 | 10-24/10-31 | C | `:128-129` "request_continuation … MP-12 not integrated" vs `K/continuation-checkpoint.md:52`, `adapters/temporal/workflows/operation.py:90-97`; event types miss WI-19 `output.*`/`transfer.*` (`adapters/postgres/knowledge/attention_events.py:7-11`) | tested (subscription PostgreSQL suites) | WI-19 attention events | update |
| mission-stream | surfaces | 160 | 10-24/10-22 | F | none (`domain/subscriptions/streams.py:34-52`, `interfaces/socketio/server.py:102`) | tested (`tests/integration/postgres/test_realtime_channels_postgres.py`) | none | keep |
| unit-and-point-joinability | surfaces | 56 | 10-22/10-29 | F | none | integrated locally (`tests/acceptance/mission_control/test_tracing_stream.py`) | none | keep |
| wake-channels | surfaces | 79 | 10-28/10-31 | D | operator MCP list `:64-68` misses selection, cognition-point and knowledge-review tools (`interfaces/mcp/operator_server.py:40,49-55`) | integrated locally (`tests/acceptance/mission_control/test_wake_channels.py`) | Selection MCP tools | update |
| coordinator-attention | surfaces | 133 | 10-28/11-01 | C | `:53-55` "candidate migration 0063 … unregistered" vs `packages/mission-control-db-contract/releases/1.8.0/component/manifest.json:294` | tested (`test_wi19_attention_postgres.py`) | 1.8.0 registration; C14 real run still unrun | update |
| signal-ingress | surfaces | 159 | 10-27/10-27 | C | `:149-150` IngressDrainer/quarantine/remote launch "remain run-2 work" vs `bootstrap/worker_ingress.py:168`, `application/signals/drainer.py` (since `e3999d85`) | tested; not deployed | Run 2 disposition | update `:147-151` to the deployment gaps |
| capabilities | surfaces | 148 | 10-27/11-01 | C | `:53-54` bundle seed "not applied to Supabase" vs RB:270-271; `:95-96` sentence broken at "Mission Control's four" | qualified with limitations (RB:96, 270-271) | W0 custody; `mc.storage.mission-payloads` seed (slice 7) | update; fix the splice; receive Agent Host generation from deep-agents-lane |
| capability-seeds | surfaces | 89 | 10-31/10-31 | C | `:63` router manifest "0.3.0" vs `skills/mission-control/manifest.json:4` (0.5.0); seven seed families absent (knowledge-tools 1.2.0, cognition-profiles, signal-skills, watchers, workflow-parity 1.0.5, runtime-profiles 1.0.1, mission-payloads) | tested (slice 6, PROV:38) | Selection guidance missing from agent-skills (STATE D11) | update the inventory from `seeds/` |
| mission-manifest | domain-model | 159 | 10-27/10-31 | C | `:26-28` nested Goal Loop "lowered as a stage" vs `domain/authoring/manifest_lowering.py:9-12` (sealed `NestedBody` child, WI-13); `:99` codex-cli 0.162.0 vs `adapters/codex/describe.py:67` (0.162.1) | integrated locally (NS:217-416) | WI-13, `GRAPH_SEMANTICS_V1`, named outputs, charter mount | update; move provider/Cursor bindings `:95-122` to their lane concepts |
| authoring | domain-model | 148 | 10-24/10-31 | S | `:118-119` "no context-pack selection operation exists": Selection Workspace not mentioned; `:94-114` repeats `K/mission-manifest.md:55-73` | tested (coordinator facade units) | Selection Workspace | merge `:94-114` into mission-manifest; link selection-workspace |
| revisions | domain-model | 115 | 10-12/10-30 | C | `:85-91` "only writer is insert_admitted_run" vs `adapters/postgres/control_plane/mission_revisions.py:1-6` (manifest submit, chains, nested runs) | tested (`tests/unit/control_plane/test_control_plane.py`) | manifest, chain and nested revision writers | update |
| lifecycle | domain-model | 73 | 10-29/10-31 | C | `:26-27` "instruction injection … fail explicitly" vs `application/missions/service.py:412-423` | tested (`tests/integration/temporal/test_w1_family_failure_root.py`) | none | update `:24-27` |
| mission-chains | domain-model | 126 | 10-24/10-30 | S | no WI-16 exact linked exports (`domain/composition/chain.py:147-154`; releases 1.10.0 `0068`, 1.11.0 `0069`); `:70-71` per-member cancel superseded (NS:348) | integrated locally (NS:285-290, fresh and upgrade to 1.10/1.11) | WI-16, overnight linked chains | update |
| completion | domain-model | 144 | 10-28/10-31 | C | `:99` "no src writes completion_candidate/decision" vs `adapters/postgres/orchestration/completion_repository.py:87,128` | integrated (`tests/integration/postgres/test_w1_fulfillment_postgres.py`; NS:231-238) | named stage-output settlement (`8e88b800`) | update `:92-99` |
| output-contracts | domain-model | 160 | 10-31/10-31 | C | `:138` "link inputs refuse" vs `domain/context/transfer_builders.py:230-259` (`linked_mission`, `abac1fde`); only nested refuses | integrated (`tests/integration/postgres/test_output_contracts_postgres.py`; paid fixtures NS:32-98) | releases 1.10/1.11 linked exports | update; split exact transfer into its own concept (at cap) |
| human-gates | domain-model | 160 | 10-24/10-31 | D | `:15` "nothing here is live-proven": GoalDirected review integrated with scripted approval (NS:238) | integrated, scripted (NS:238) | `NamedReviewPacketRequest` (`domain/programs/human_gate.py:276`) | update |
| interventions | domain-model | 140 | 10-24/10-31 | C | `:104` "MP-12 … not integrated" vs `K/continuation-checkpoint.md:50-52`; `:21-26` omit `next_turn` follow-up (`application/execution/harness/inject.py:323-340`, `0eccfa2d`) | integrated (Run 2 live inject; `tests/acceptance/mission_control/test_cognition_points.py`) | Qualia bounded queued turns, crash-safe queued input | update |
| model-catalog | domain-model | 132 | 10-29/10-29 | C | `:111` "no runtime consumer reads … prices yet" vs `adapters/deep_agents/evaluators.py:22-24,183-186` (evaluator `usage.costUsd` priced from `models.toml`) | tested (`tests/unit/resolution/test_w1_d24_api_surface.py`); rows verified in `deployments/*/models.toml:69-203` | evaluator pricing | update `:111`; move `:82-102` (Deep Agents bindings) to agent-configuration |
| workflow-systems | domain-model | 160 | 10-29/10-31 | C | `:129-131` "search finds no swarm/evaluator_optimizer" vs `domain/authoring/manifest.py:406-407,986-997`, `adapters/deep_agents/describe.py:158-159` | integrated locally (NS:285) | named outputs (`8e88b800`), repair context (`d2378a0c`); wi14/wi15 unmerged | update `:126-138` |
| recursive-composition | domain-model | 138 | 11-01/11-01 | F | none (`:82` = `scripts/release_200/0071_nested_program_activations.sql`) | tested (`tests/integration/temporal/test_wi13_nested_temporal.py`); migration unregistered | `sprint-oc-wi15` also uses key 0071 (`0c14071a`) | keep; note the collision |
| parallel-swarm | domain-model | 96 | 10-12/10-29 | C | `:77-78,83` "no hits / no swarm value" vs `manifest.py:406,986-990`, `mission_revisions.py:298` | specified only on HEAD (authoring model only) | `sprint-oc-wi14` unreviewed (`cf2575d6`, `4fa865b7`, `6c558096`) | update `:75-84` |
| evaluator-optimizer | domain-model | 97 | 10-12/10-30 | C | `:72-74` "returns nothing" vs `manifest.py:407,993-997`, `application/authoring/manifest_v2_admission.py:90` | specified only on HEAD | `sprint-oc-wi15` unreviewed (`0c14071a`) | update `:70-74` |
| persistence | persistence | 150 | 10-29/11-01 | C | `:4` describes 1.4.0; `:67-68` "recorded live installations are 1.3.0" vs `…/HANDOFF-2026-10-28-S3.md:4,42` (1.8.0 on both remotes); `:97` "Releases 1.4.1 to 1.4.3" vs `releases/1.3.0`…`1.12.0`; `:139-141` cite retired `component/migrations/` vs `releases/README.md:3-8`; table `:75-95` stops at 0046 | integrated locally for 1.12.0 (`tests/integration/postgres/test_sprint_oc_release_1120.py`) | 1.5.0-1.12.0, locks 1.9.0, S3 payloads (slice 7) | rewrite as invariants only; versions go to new database-component |
| collections-and-current-sets | persistence | 127 | 10-29/11-01 | F | none (`deployment_composition.py:727-728`; 1.9.0 `releases/README.md:265-273`) | tested (`tests/integration/postgres/test_wi07_collections_postgres.py`) | none | keep |
| saved-result-settlement | persistence | 108 | 10-28/10-29 | C | `:94-95` "no production path promotes an accepted head" vs `application/programs/goal_directed.py:1423`, `application/programs/named_outputs.py`; `:81` WI-03 shipped | tested (`tests/integration/temporal/test_wi04_saved_settlement_restart.py`) | B3 native decisions in the settlement pass (`0072`, unregistered) | update Limits |
| workspace-closure | persistence | 108 | 11-01/10-31 | F | none (caps `domain/resolution/profiles.py:140,154-155`) | integrated (PROV:37, 8 closures) | none | keep; link from Deep Agents group |
| provider-frames-and-transcript | persistence | 112 | 10-24/10-31 | D | `:28-29` writer list misses `adapters/{claude,codex,anthropic_managed,openai_agents}/frames.py`; `:50-74` duplicate transcript-projection | integrated (`tests/integration/deep_agents/test_provider_frames_deep_agents.py`) | closure expiry inside `frames.expire` | merge with transcript-projection |
| transcript-projection | persistence | 119 | 10-22/10-31 | D | `:68-79` only `frame-body://`; route also serves `closure-body://` (`application/frames/artifact_bodies.py`) | tested (`tests/unit/frames/test_deep_agents_frames.py`) | slice 5 bodies; Qualia transcript exports | merge target (one `transcript.md`) |
| execution | execution | 137 | 10-28/10-30 | D | none false (`manifest_lowering.py:861-863`; `adapters/temporal/workflows/goal_directed.py:159`) | integrated locally (NS:285) | nested dispatch, WI-08 routes/revisits, named outputs, repair context, governed linked release/cancel | update: "overnight integration" section |
| durable-controls | execution | 121 | 10-13/10-29 | D | omits authoring-only `TimerNode`/`ProofGateNode` (`manifest.py:1063-1075`) | integrated (Human Gate, NS:238) | WI-08 held waits `route-exhausted:`/`revisit-exhausted:` | update |
| durable-reactions | execution | 160 | 10-28/10-28 | C | `:138` "0061 is not in a built release" vs `releases/README.md:226-232` (1.8.0); no `ReactionRelayPump` composed still true | tested (`tests/integration/temporal/test_wi22_reaction_dispatch.py`); not composed | none | update `:138` |
| watchers | execution | 160 | 10-24/10-29 | F | none (`domain/programs/watchers.py:79-80`) | tested (`tests/integration/temporal/test_mo44_watchers_workflow.py`) | WI-19 link | keep |
| recovery | execution | 147 | 10-24/10-31 | D | `:86-100` repeat `K/precise-fork.md:27-29` | integrated, live paid (Qualia fork05, NS:81-83) | `ForkAdmissionProvenance` (`0eccfa2d`) | update; move `:50-89` into precise-fork |
| precise-fork | execution | 113 | 10-22/10-31 | D | outcome table `:83-90` lacks `fork_templates_mismatch` (`application/execution/run_launch.py`, `0eccfa2d`) | integrated, live paid (NS:81-83); `--at`/`--frontier` tested only | trusted manifest-provenance fork admission (`application/authoring/manifest_fork_admission.py`); PROV:46-50 refusal was the fixture USD ledger, not MC | update |
| context-and-continuation | execution | 160 | 10-24/10-31 | C | `:78-79` "no packet has fed a paid model run" vs NS:36-40, NS:70-73; `:128-140` repeat `K/continuation-checkpoint.md:50-74` | integrated, live paid (NS:32-98) | WI-01/02 exact transfers, WI-07/08 frozen inputs | update proof line; cut `:128-140` to a pointer |
| continuation-checkpoint | execution | 114 | 10-24/10-31 | F | none (`checkpoint.py:898-903`, `pressure.py:41-43`) | tested (fixture lanes); no live transfer | none | keep; owns MP-12 |
| hook-contributions | execution | 142 | 10-27/10-28 | C | `:117` "0060 not in a built release" vs `releases/1.7.0/component/manifest.json:283` | tested (unit, PostgreSQL); no production store composed | none | update `:116-117` |
| instruction-layering | execution | 76 | 10-24/10-27 | C | `:69-70` MO-33 ambient "not done" vs `application/agentic_components/ambient.py:1`, `materialization.py:12-15` | tested | say Deep Agents has no layering | update |
| evaluator-attempts | qualification | 107 | 10-29/10-31 | F | none (`application/knowledge/judgment.py:224`) | tested (`tests/integration/postgres/test_w1_d30_uncomposed_postgres.py`) | audience fix `8bf10f85` | keep |
| trusted-judgment | qualification | 152 | 10-29/10-31 | D | omits native-write decisions (`application/knowledge/native_write.py`; `adapters/postgres/knowledge/use_decisions.py:48-66`) | integrated, live paid (NS:97) | B3/B3-R (`ecdba045`, `f3274e77`); reviewer origin ledger id | update |
| lanes-and-harness | execution·lanes | 160 | 10-27/10-31 | D | none false (nine profiles `:30-32`; only `deep_agents` flag `qualified=True`, `adapters/deep_agents/describe.py:119`; segment loop default false, `bootstrap/settings.py:395`); `:64-66` migration list stops at 0040; `:70` sends readers to the stale qualification.md | tested | none | update pointer; trim inventory to module AGENTS.md |
| session-ownership-and-dispatch | execution·lanes | 135 | 10-27/10-31 | S | `:98` "no route is account-enabled" and `:14-15` vs Run 2 live Claude/Codex with `MISSION_CONTROL_AUTH_PROFILES_PATH` (`docs/WSL2_WORKER_RUNBOOK.md:47`) | tested (fixture lanes) | OC-R2 sealed binding slot | update `:14-15`, `:98` |
| placement-admission | execution·lanes | 62 | 10-14/10-27 | D | no `tags`; `## Citations`; unprefixed paths do not resolve | tested | registry moved to `application/resolution/registries.py` (`4cf16f02`) | update hygiene |
| cursor-lane | execution·lanes | 155 | 10-27/10-31 | F | none (MR-03 still blocked; `adapters/cursor/describe.py:92,124`) | implemented, offline-tested; live blocked | cloud-environments roadmap pointer | keep |
| provider-lanes | execution·lanes | 158 | 10-27/10-27 | D | `:118` "account enablement unknown" vs its own `:120-121` (Run 2 live) | integrated live, not qualified (`RUN-2-CARRY-FORWARD.md:39-40`) | roadmap pointer | update `:118` |
| hosted-api-lanes | execution·lanes | 48 | 10-24/10-27 | D | missing from index tables (`K/index.md:125` only); cites archive SPEC-06 only | tested (`tests/unit/openai_agents/test_tools.py`) | none | add index row |
| deep-agents-lane | execution·deep-agents | 160 | 10-28/10-31 | D | `:10` "first and only qualified Lane" means the describe flag (`describe.py:119`), not a W-gate (W1 unreleased, NS:119-121); `:33` omits `tool_auto` (`adapters/deep_agents/routes.py:61-76`); silent on Qualia adapter repairs (`0eccfa2d`), the `docker_sandbox.py` rewrite and `knowledge_tools.py`/`workspace_closure.py` (`03f11594`) | integrated, live paid (NS:32-98; PROV:33-37); flag `qualified=True` | see §4 | merge with turn-stops; see §4 |
| deep-agents-turn-stops | execution·deep-agents | 88 | 10-27/10-31 | S | `:61-66` "corrected cells ship with the next SQL release": five releases later `describe.py:80` still reads `cancel: turn_boundary_guaranteed` and `:113` `cost="estimated"`; `:66-68` 0.7.30 "latest" dates from 10-22 | tested (`tests/unit/deep_agents/test_turn_stops.py`); T0 cancel integrated (`test_tracing_stream.py`) | none | merge into deep-agents-lane; state the unshipped cells as open |
| agent-configuration | execution·deep-agents | 85 | 10-27/10-29 | F | none; B1 residual still true (`domain/capabilities/features/{configuration,deep_agents,registry}.py`; `domain/execution/contracts.py:1154,1319`) | tested (`tests/unit/deep_agents/test_lane_adapter_features.py`); paid live test exists, run not verified | charter mount (slice 6), launch compile, model bindings | expand (see §4) |
| async-children | execution·deep-agents | 125 | 10-28/10-31 | F | none (`adapters/agent_server/async_subagents/sealed.py:63,69,71`) | integrated locally, real Agent Server with a deterministic model (`tests/integration/agent_server/test_wi23_sealed_child_server.py`); paid C10-C13 = W5 | sync children from deep-agents-lane | rename and expand (see §4) |
| operations | operations | 116 | 10-28/10-31 | D | `:81` "Temporal Cloud not exercised" holds only for the outage drill (Run 2 ran on Cloud) | tested; Run 2 live WSL worker | slice 7 S3 settings and preflight (`03f11594`); `scripts/offline_operator_stack.py`; WSL2 runbook | update |
| environments | operations | 144 | 10-24/10-31 | C | `:49` "a Deep Agents node only warns" and no `deep_agents` row in `:101-109` vs `application/environments/network.py:20,72,403`, `manifest_v2_admission.py:234-245` (`0eccfa2d`) | integrated, live paid (NS:89) | Deep Agents network grants | update |
| environment-preparation | operations | 148 | 10-24/10-27 | F | cites 0037 under the retired root `component/` | tested | say Deep Agents is not on the `LaneTurnService` gate | keep; fix the path |
| secret-broker | operations | 111 | 10-24/10-27 | C | `:48-50` "worker composes no minter" vs `adapters/temporal/deployment_composition.py:959-961,986` (`ScopedSecretMinter`, MO-41) | tested (PostgreSQL Vault) | K01 `Ed25519CredentialMinter` (`bootstrap/composition.py:695`) | update |
| budgets-and-usage | operations | 159 | 10-27/10-31 | C | `:114` "no budget or cost code reads prices" vs `adapters/deep_agents/evaluators.py:183-186` | tested; one live observation | Qualia cumulative failure usage (`0eccfa2d`); fixture-only USD SpendLedger | update `:80-81`, `:114` |
| owner-prerequisites | operations | 160 | 10-24/10-27 | S | probe list `:50-60` omits `cursor_native_host` and `managed_mcp_oauth` (`adapters/prerequisites/probes.py:72,88,102`) | tested | none | update (trim elsewhere: at cap) |
| owner-probe-bootstrap | operations | 87 | 10-14/10-27 | D | none false | tested (fixture provider); no paid probe | OC-R4 profiles | keep; date stamp |
| selection-workspace | surfaces | 53 | 10-31/10-31 | F | none (routes `interfaces/http/selection.py:3-5`; 16 test functions, NS:51-52 says 21) | tested, in-memory ports (`tests/unit/selection/`) | skill guidance absent from agent-skills (STATE D11) | keep; add the guidance gap |
| qualification | qualification | 87 | 10-24/11-01 | S | `:4` "seven lane profiles", and table `:52-57` omits `claude_managed`/`codex_agents`; `:54` "no live run" for deep_agents vs NS:32-98; no W0-W5; cites the status doc marked historical by `f992ea60` | qualified only via W0 (RB:22) | W0 release, paid Deep Agents fixtures | merge into release-and-qualification |
| release-and-qualification | qualification | 159 | 10-24/10-27 | C | `:55-60` "what is live today: 1.0.0" vs `HANDOFF-2026-10-28-S3.md:42` (1.8.0); no W-gate vocabulary; `:136-142` status-doc contradiction obsolete since `f992ea60` | qualified (W0, RB:22) | W0/W1 status by pointer; 1.9.0 locks | rewrite as the one `qualification.md` (see Q2) |

## 3. Recent work with no concept home

| Recent work (label, proof) | Home now | Where it should go |
| --- | --- | --- |
| Releases 1.10.0/1.11.0 exact linked exports, governed release/cancellation (integrated locally; NS:285-312, `abac1fde`) | `K/log.md` only | mission-chains (link fields) + a new exact-transfer concept split from output-contracts |
| Release and version facts 1.5.0-1.12.0, locks 1.9.0, remote 1.8.0, `release_200` candidates (`releases/README.md`) | persistence (wrong) | new `database-component.md` that points at `releases/README.md`, never restating fingerprints |
| Qualia repairs: crash-safe queued input and bounded follow-up turns (`inject.py:323-340`) | none | interventions |
| Qualia repairs: trusted fork admission provenance, `fork_templates_mismatch` (`manifest_fork_admission.py`, `run_launch.py`) | none | precise-fork |
| Qualia repairs: Deep Agents network grants (`network.py:20,403`) | none | environments (and a pointer from deep-agents-lane) |
| Qualia repairs: sync-child usage retention across replay (`adapters/deep_agents/adapter.py`, `0eccfa2d`) | none | budgets-and-usage |
| Paid Deep Agents fixtures as evidence (Qualia, AI Engineer; integrated, NS:32-98) | none | the qualification Deep Agents row; context-and-continuation and execution proof lines |
| Overnight integration: named stage outputs, ordered inputs, GoalDirected repair context (NS:217-416) | none | execution, completion, saved-result-settlement |
| B3/B3-R native plan decisions (integrated, focused restart; `0072` unregistered) | none | trusted-judgment, plus a knowledge-services pointer |
| Provenance slice 2, production gateway minting (integrated, PROV:34) | partial | knowledge-services |
| Provenance slice 6, charter skill default mount (tested, PROV:38) | capability-seeds, knowledge-services | add to agent-configuration and application-profile |
| Provenance slice 7, S3 endpoint and `mission-payloads` bucket (integrated at smoke level, PROV:39) | none | operations (settings, preflight) + database-component (bucket seed) |
| Evaluator usage priced from `models.toml` (`evaluators.py:22-24`) | none | model-catalog, budgets-and-usage |
| W0 release with limitations (qualified, RB:22) | none | merged qualification.md |
| Selection guidance not yet in agent-skills (STATE D11) | none | selection-workspace limits |
| Unmerged recovery branches `sprint-oc-wi14`/`wi15` (unreviewed) | none | one line each in parallel-swarm and evaluator-optimizer; key 0071 collision noted in recursive-composition |

## 4. The Deep Agents group

**What each concept holds now.**

- `deep-agents-lane.md` (160, at cap). Sections:
  - `:10-34`: adapter, harness and materializer. Exact registry by digest; sandboxes State/LangSmith/Docker; fail-closed placement.
  - `:36-42`: cognition points and time travel (R3).
  - `:44-59`: frames, hook middleware, compaction observer, async subordinates.
  - `:61-66`: turn-stop summary.
  - `:68-80`: Agent Host configuration generation. Provider-neutral; not lane content.
  - `:82-95`: "the lane adapter at launch", the resolution seam to compile to binding to rebind (OC-R1..R7). Line 84 alone is a ~1,800-character paragraph.
  - `:97-124`: children (inherit/seeded shapes, seeds, discriminator, async pointer).
  - About 68 `.py` path references. `src/mission_control/adapters/deep_agents/AGENTS.md:10-22` already duplicates the file inventory.
  - Silent on the 10-28..10-31 changes: `tool_auto` (D18), queued-input crash safety, child usage retention, network grants, the `docker_sandbox.py` rewrite, `knowledge_tools.py` (read_intent), the closure capture hook.
  - Undocumented modules everywhere except the module AGENTS.md: `browser_tool.py`, `capability_lineage.py`, `checkpoint_{history,reads,verifier}.py`, `runtime_persistence_verifier.py`.
- `deep-agents-turn-stops.md` (88). Budget/fence stops via `wrap_model_call`, structured output only when written, exact `task` namespaces, bounded point walks (512), describe pins.
  - One stale promise: `:61-66`, the corrected cells "ship with the next SQL release". They never shipped (`describe.py:80,113`). This is a code defect, not only a doc defect.
- `agent-configuration.md` (85). Feature registry (lane features, model tools; `middleware`/`provider_tool`/`model_setting`), manifest spelling, sealed `mc.agent_configuration.v1` and receipt, builders, Anthropic factory, and the neutral `mc.agent_configuration.v2` with nine item kinds.
  - Honest B1 residual: v1 still in the domain, moves with the OVE-203 provider sweep.
  - Fresh. It is the concept closest to the owner's nearest goal, but the compile path that uses it lives in deep-agents-lane `:84` and the model binding in `model-catalog.md:82-102`.
- `async-children.md` (125). Exact versus `sealed_child` graph, sealing at launch, custody in `subordinate_contract`, one assistant per binding and scope, check-time admission, exact adoption into `SubmitOutput@2`.
  - Proof is integrated locally with a deterministic model; paid observation is W5. Fresh.
- Deep Agents-only neighbours: `workspace-closure.md` (evidence; fresh), `model-catalog.md` (routes, structured-output strategy; contradicted at `:111`), `selection-workspace.md` (pre-manifest check).
- Deep Agents-relevant claims that are wrong elsewhere: `context-and-continuation.md:78-79`, `environments.md:49`, `budgets-and-usage.md:114`, `precise-fork.md:83-90`, `qualification.md:54`.

**Proposal: one `deep-agents` group of three concepts** (group field or subdirectory per SPEC-01 §3.3).
Each answers one question and stays under 160 lines:

| Concept | Answers (`questions[0]`) | Built from | Est. lines |
| --- | --- | --- | --- |
| `agent-configuration.md` | How is a Deep Agents node configured, from manifest to sealed binding? | itself + deep-agents-lane `:82-95` (resolution seam, compile, `ITEM_*`/`LANE_OPTIONS_INVALID` refusals, template step, rebind) + `model-catalog.md:82-102` (model bindings are references) + `provider_options.deep_agents` (sandbox, summarization, `interrupt_on`, network grants pointer) + charter mount (tested) + "check first with the Selection Workspace" | ~150 |
| `deep-agents-lane.md` | How does the Deep Agents lane run one attempt, and how does a turn stop? | itself `:10-66` + turn-stops condensed (stops, structured output, namespaces, point walks) + `tool_auto` + Qualia repairs (queued input, child usage) + capture points (frames, compaction, closure, read_intent tool, as pointers) + the open defect: describe cells `cancel`/`usage.cost` unshipped. File inventory moves to `adapters/deep_agents/AGENTS.md`; `:68-80` (Agent Host generation) moves to capabilities.md | ~150 |
| `deep-agents-children.md` (renamed from `async-children.md`) | How do a node's sync and async children get capabilities and return results? | async-children + deep-agents-lane `:97-124` (inherit/seeded, seeds, discriminator, no implicit `general-purpose` child); trim proof prose | ~155 |

The group header in `K/index.md` gives the Deep Agents reading order for workflow and agent configuration:
`selection-workspace` → `mission-manifest` → **agent-configuration** → **deep-agents-lane** →
**deep-agents-children** → `execution`/`workflow-systems` → `output-contracts`/`workspace-closure` →
`qualification` (Deep Agents row). `turn-stops` retires into the lane. `model-catalog`, `workspace-closure`
and `selection-workspace` stay in their categories, cross-linked.

What this closes: today an agent asking "how do I configure a Deep Agents node" lands on
agent-configuration and finds no compile path, no model binding and no network/charter facts. After the merge
one concept answers it, and the lane concept answers runtime behaviour with current proofs.

## 5. Owner questions

1. **Deep Agents group: three concepts, as in §4?** The alternatives are DOC-07's four, or one file over the cap.
   *Recommend:* three. Merge turn-stops into the lane, rename async-children to deep-agents-children, and make
   agent-configuration absorb the compile path and model bindings. Also record the unshipped describe cells
   (`describe.py:80,113`) as a code issue for the next release.
2. **Qualification: fold `qualification.md` into `release-and-qualification.md` as one `qualification.md`
   keyed to the W0-W5 gates?** It would hold the proof ladder, a nine-profile table and W status by pointer
   to NS rather than restated. G0-G7 and the fast-track/multi-provider/Run 2 positions shrink to one
   history paragraph with archive links. *Recommend:* yes.
3. **Versions out of concepts: create `database-component.md` (release numbering, consumers, where locks
   live) that points at `releases/README.md` and the deployment locks, and strip version tables from
   persistence?** *Recommend:* yes. persistence keeps the invariants: namespaces, scope, roles, installer.
4. **Unmerged `sprint-oc-wi14`/`wi15`:** should concepts state only HEAD truth plus a one-line pointer
   ("implementation on unreviewed branch X")? Should wi14's own OKF commit `4fa865b7` stay out until review?
   *Recommend:* yes to both, and note the wi15/HEAD key-0071 collision.
5. **Proof citations for paid fixtures:** cite tracked NS lines as the proof path, with private `.scratch/`
   paths as secondary? *Recommend:* yes; a concept never relies on a private path alone (STATE §6).
6. **`interfaces.md`: generate the HTTP/CLI/MCP inventory from `bootstrap/api.py`, the CLI and the MCP
   servers (a `docs/tools` script plus a check), or hand-edit?** *Recommend:* hand-fix the seven missing
   routers now. Schedule generation in the Agentic SDLC slices; it is the recurring drift source.

## 6. Ordered execution steps for the refactor agent

Docs only, on `sprint-oc`; one commit per step group; run `python docs/tools/check_docs.py`,
`python docs/tools/validate_okf.py` and `python docs/tools/agents_docs_index.py --check` after each group.
Do not change ledgers beyond adding this file's row (step 0), and do not touch code.

0. Add a `draft` row for this file to `docs/specs/agentic-sdlc-2026-11/LEDGER.md`. `program_ledger.py
   check` fails without it.
1. **Contradiction fixes (one line or one paragraph each; no restructuring).** For each, cite the evidence
   from §2 and label it implemented/tested/integrated:
   - events-and-commands `:128-129`; interventions `:21-26`, `:104`
   - coordinator-attention `:53-55`; durable-reactions `:138`; hook-contributions `:116-117`
   - signal-ingress `:147-151`; secret-broker `:48-50`; instruction-layering `:69-70`
   - capabilities `:53-54`, `:95-96`; capability-seeds `:63`; mission-manifest `:26-28`, `:99`
   - revisions `:85-91`; lifecycle `:24-27`; completion `:92-99`; saved-result-settlement Limits
   - model-catalog `:111`; budgets-and-usage `:114`; environments `:49` plus a `deep_agents` network row
   - context-and-continuation `:78-79`; output-contracts `:138`
   - workflow-systems `:126-138`, parallel-swarm `:75-84` and evaluator-optimizer `:70-74`: HEAD truth
     plus the branch pointer (Q4)
   - session-ownership-and-dispatch `:14-15`, `:98`; provider-lanes `:118`; owner-prerequisites probe list
2. **Deep Agents group (Q1):** build the three concepts in §4.
   - Move the file inventory into `src/mission_control/adapters/deep_agents/AGENTS.md`, keeping it within
     its budget.
   - Move Agent Host generation to capabilities.md.
   - Delete deep-agents-turn-stops.md and async-children.md after `git mv`. Update inbound links:
     `grep -rl "deep-agents-turn-stops\|async-children" docs GLOSSARY.md`.
3. **Qualification (Q2):** write the merged `qualification.md` and retire release-and-qualification.md
   with link updates. The Deep Agents row cites NS:32-98 (integrated) and RB:22 (W0).
4. **Persistence (Q3):** create `database-component.md`, rewrite persistence.md as invariants, and point
   environment-preparation and other migration citations at `releases/<v>/component/`.
5. **Absorb recent work (§3):**
   - mission-chains and a new exact-transfer concept (moved out of output-contracts to free the cap)
   - interventions, precise-fork (and move recovery `:50-89` into it), execution, trusted-judgment
   - knowledge-services, operations, application-profile
6. **Merges:**
   - provider-frames-and-transcript + transcript-projection become `transcript.md`.
   - context-and-continuation `:128-140` becomes a pointer to continuation-checkpoint.
   - authoring `:94-114` folds into mission-manifest.
7. **interfaces.md (Q6):** add the seven routers and the missing CLI/MCP groups; trim to 160 by moving the
   per-route prose into one table.
8. **Hygiene:** placement-admission tags, `# Citations` and prefixed paths; hosted-api-lanes index row;
   architecture seam rows; wake-channels operator tools; selection-workspace guidance gap; owner-probe-bootstrap
   date.
9. **Index and log:**
   - Rewrite `K/index.md:7-34` to a current-state pointer: NS for W0/W1, Sprint OC paused for the Agentic
     SDLC program, Run 2 as history.
   - Add the Deep Agents group header with the §4 reading order.
   - Add one dated `K/log.md` entry per step group. Leave log compaction to the sitting II answer.
10. Report the counts after the refactor against §1 and list any claim left "not verified".

Not verified in this pass: whether WI-19 lists settlement waits; whether launch refuses a compiled
`parallel_swarm` node on `deep_agents`; whether `test_agent_configuration_live.py` has run; environments `:64`;
the instruction-layering describe channels.
