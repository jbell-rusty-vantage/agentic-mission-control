---
type: Research Note
title: "Codebase audit: adding lane profiles and reusable remote-session parts (2026-10-12)"
description: "AgentHarness protocol, the complete touch-point checklist for a new lane profile, reusable cursor_cloud remote-session machinery, auth handling, continuation/approval integration, tests and skill placement."
tags: [mission-control, research, materialization-observation]
---

# Codebase audit: adding `claude_managed` and `openai_hosted` lane profiles (and promoting stubs)

Repo: `C:\Users\Pinda\Proyectos\BellLabs\platform\mission-control` (read-only audit, 2026-10-12).
All paths are repo-relative; `src/` means `src/mission_control/`.
Tests run: `tests/unit/harness/test_lane_contracts.py`, `test_multi_provider_contracts.py`,
`test_lane_registry.py` (49 passed); `tests/unit/harness/test_describe_honesty.py` + `tests/unit/cursor`
(76 passed). No integration/PostgreSQL/Temporal/live runs.

Context from the packet: `docs/specs/archive/materialization-observation-2026-10/PLAN.md:164` lists
**MO-62 "Optional hosted API profiles (`claude_managed`, an OpenAI Agents hosted profile)"**, depends on
MO-40 (provider webhooks), "separate packet if chosen". `DECISIONS.md:30` (D1 option c) describes
`claude_managed` as "Fully programmable: environments, vaults, sessions, event stream and replay,
interrupt, webhooks, budgets ... API-key billing ... ignores `.claude/agents`, hooks and plugins; only
skills and the system prompt carry over". `DECISIONS.md:48` (D2 option c): "Hosted profile on the OpenAI
Agents API — programmable sessions, steering, webhooks; API billing; not Codex Cloud". `DECISIONS.md:70`
(D4): "Never silently fall back to API billing". ADR-0035 (`docs/adr/0035...md:24-26`) defines "cloud" as
the provider-hosted product; our own remote SDK worker is `worker_hosted`, never a cloud profile.

---

## 1. The AgentHarness protocol and the Harness Execution activity shape

### 1.1 Protocol (`src/application/execution/harness/protocol.py`)

`AgentHarness` (runtime_checkable Protocol, `protocol.py:65-85`) = `describe` + 9 ops:

| Op | Signature (`protocol.py`) | Request / result (`src/domain/execution/lanes.py`) |
| --- | --- | --- |
| `describe()` | `-> LaneDescribe` (67) | `LaneDescribe` 292-416 |
| `prepare` | `async (PrepareRequest) -> PreparedSession` (69) | 489-502 (run_id, operation_id, attempt_no, packet_ref -> workspace_ref, projection_digests, materialization_ref) |
| `start` | `async (StartRequest) -> SessionHandle` (71) | 505-518 (`native_session_ref`, secret-free `native_details`) |
| `reattach` | `async (ReattachRequest) -> SessionHandle` (73) | 521-523 (native_session_ref, native_turn_ref) |
| `send_turn` | `async (SendTurnRequest) -> TurnHandle` (75) | 526-537 (`status: accepted\|busy`) |
| `cancel_turn` | `async (CancelTurnRequest) -> CancelReceipt` (77) | 540-549 (`urgency normal\|immediate`) |
| `observe` | `(ObserveRequest) -> AsyncIterator[LaneFrame]` (79) | 552-581 (`after` = opaque lane cursor; LaneFrame: provider_key, cursor, kind, terminal, digest, excerpt, raw_kind, body, native_turn_ref, tool_call_ref, provider_timestamp, subordinate_ref) |
| `snapshot` | `async (SnapshotRequest) -> SnapshotManifest` (81) | 584-596 (`kind checkpoint\|git_patch\|branch`, `emulated`) |
| `usage` | `async (UsageRequest) -> UsageReport` (83) | 599-617 (`disposition settled\|estimated\|unknown`; unknown carries no tokens) |
| `end_session` | `async (EndSessionRequest) -> CleanupReceipt` (85) | 620-630 (artifact_refs, patch_ref) |

Every request extends `HarnessRequest` (`lanes.py:476-486`): scope, lane_profile, harness_execution_id,
binding_digest, idempotency_key, generation, lease, deadline.

`SessionLane(AgentHarness)` (`protocol.py:88-107`) — what `lane.turn` drives — adds
`stage(harness_execution_id, operation)`, `closing_facts(turn, frame) -> ClosingFacts`,
`async status(StatusRequest) -> ProviderStatus` (`lanes.py:633-646`), `resume_cursor(provider_key) -> str|None`.
`OperationLane` (`protocol.py:110-119`) is the Deep Agents bounded `execute` path only.

`HarnessUnsupported` (`protocol.py:48-55`): a lane whose describe says `unsupported`/`unqualified` raises
it; any other error is a conformance failure. `UnsupportedHarnessOperations` mixin (`protocol.py:136-177`)
supplies raising stubs; `implements(harness, op)` (`protocol.py:187-191`) detects overrides (used by
describe-honesty to prove every `native`/`emulated` cell is implemented). `NativeTurnLost` (58-62) means
"never resend, park in_doubt".

Optional capability protocols a lane may implement (isinstance-checked):
- `DispatchReconcilingLane.reconcile_dispatch(record, *, session) -> DispatchLookup` — `harness/dispatch.py:287-298` (MP-06; answer `not_received` only when authoritative, else `unknown` → in_doubt).
- `SteeringLane.steer(turn, *, instruction_ref) -> SteerResult` — `dispatch.py:310-315` (`cooperative_inject`; `stale_target`).
- `CooperativeInjectLane.inject(...)` — `harness/inject.py:78-82`; `resolve_interrupt_mode` (`inject.py:94-110`) requires the frozen `LANE_COMMAND_SEMANTICS` table and the describe to agree.
- `FinalTextLane.final_text(turn, frame) -> str|None` — `harness/lane_turns.py:219-225` (Completion Candidate).
- `SessionHandoverLane.pending_handover/complete_handover` — `harness/controls.py:132-136` (continuation).
- `ContextOccupancyLane.context_occupancy(...)` and `CompactingLane.compact(CompactionRequest) -> CompactionReceipt` — `src/application/context/lane_support.py:56-70`.

### 1.2 Capability / semantics declarations (`mc.lane_describe.v1/.v2`)

`LaneDescribe` (`lanes.py:292-416`): `lane`, `lane_profile`, `versions`, `controls` (exactly
`LANE_CONTROLS` = 9 ops + `pause`, `fork`; `lanes.py:166`), `delivery_semantics` (exactly
`DELIVERY_COMMANDS`: queue_instruction, interrupt_and_inject, pause, hard_pause, resume, cancel, fork,
request_continuation; `lanes.py:168-177`), `identity` (`LaneIdentityMap` session_ref/turn_ref/effect_ref/cursor),
`hooks` (`LaneHooks` mechanism/events/fail_closed), `instruction_channel`, `subagents`, `usage`,
`placement`, `qualified`; v2 adds `features` (one `FeatureEvidence` per `LANE_FEATURES`, `lanes.py:112-125`:
launch, status, observe, follow_up, cancel, usage, output_custody, environment_selection,
configuration_materialization, approval_suspension, subordinate_lineage, continuation), `approval_modes`,
`compaction_control`, `subordinate_visibility`, `enforcement_coverage`.

- `ControlSupport = native | emulated | unsupported | unqualified` (`lanes.py:44`);
  `DeliverySemantics` (`lanes.py:45-53`); `Placement worker_hosted|cloud` (54).
- `FeatureEvidence` (`lanes.py:249-283`): `implemented`, `account_enabled`, `qualified` are separate facts;
  qualified requires `evidence_ref` + `qualified_at`. Validator `complete_matrix` (`lanes.py:326-366`)
  enforces lane/placement agreement with `LANE_OF_PROFILE`/`PLACEMENT_OF_PROFILE`, full matrices, and that a
  qualified lane has no unqualified controls/features. `LaneDescribe.unqualified()` (397-416) keeps `unsupported`.
- Convention since 2026-10-09 (`docs/knowledge/lanes-and-harness.md:38-41`): implemented cells say
  `native`/`emulated` with `qualified=False`; `unqualified` only where nothing is implemented.

Declared matrices live only in `src/application/execution/harness/describe.py` (adapter `describe.py`
modules re-export): `DECLARED_LANE_MATRICES` (626-634), `V1_LANE_PROFILES` (639),
`V2_IMPLEMENTED_LANE_PROFILES` (640-642), `V2_STUB_LANE_PROFILES = {claude_cloud, codex_cloud}` (643-645).
Stubs: `CLAUDE_CLOUD_DESCRIBE` (535-578), `CODEX_CLOUD_DESCRIBE` (583-624). Implemented reference for a cloud
API lane: `CURSOR_CLOUD_DESCRIBE` (147-174 v1, 284-298 v2) with `_cursor_features(local=False)` (201-266).

Per-profile command tables beside describes (`src/domain/execution/lane_turns.py`): `LANE_COMMAND_SEMANTICS`
(186-205), `LANE_PAUSE_SEMANTICS` (212-221), `LANE_RESUME_SEMANTICS` (222-231); describe-honesty holds the
describe to them. Continuation delivery per lane: `src/domain/context/checkpoint.py:96-104` (`_DELIVERY_BY_LANE`).

### 1.3 "LaneQualification"

There is **no `LaneQualification` class**. Qualification is: `LaneDescribe.qualified` + per-feature
`FeatureEvidence.qualified`; admission via `LaneRegistry.admit` (`harness/registry.py:105-111`) raising
`LaneNotQualified` (50-60) unless `MISSION_CONTROL_ALLOW_UNQUALIFIED_LANES` (`bootstrap/settings.py:306,395`);
requirement admission `admit_requirements` (`src/domain/execution/lane_requirements.py:90`,
`LANE_REQUIREMENT_UNSUPPORTED/UNQUALIFIED`) and gate coverage `admit_gate_coverage`
(`src/application/execution/approvals_coverage.py:54`); persisted in `mission_control.lane_profile`
(`qualified`, `qualified_at`, `qualification_ref`; immutable trigger, migration 0030:45-47). Flip only via a
reviewed release citing `docs/qualification/lanes/<profile>-<date>.md` (front matter `outcome: qualified`,
`evidence: live_drill`) — `docs/qualification/lanes/README.md:10-15`.
Lane Describe endpoints: `GET /v1/applications/{app}/lanes[/{profile}]` (`src/interfaces/http/lanes.py:56,73`),
`missionctl lane list|describe`.

### 1.4 "Harness Execution" Temporal activities (`src/adapters/temporal/activities/lane_turn.py`)

- `@activity.defn(name="lane.turn")` (186-206): payload `LaneTurnRequest` (`src/domain/execution/lane_turns.py:112-123`:
  operation, lane_profile, generation, phase start|resume, cursor, turn_no, segment_no, instruction_ref,
  segment `LaneSegmentBounds` (`lanes.py:422-446`), capacity_exhausted) → `LaneTurnResult` (126-148: done, busy,
  cursor, segment_no, frames_persisted/duplicate, native refs, `ClosingFacts`, usage_estimate, operation_result).
- `lane.status` (208-223): `LaneStatusRequest`/`LaneStatusResult` (151-161).
- `lane.cancel` (225-245): `LaneCancelRequest`/`LaneCancelResult` (164-178), idempotent.
- `ClosingFacts` `mc.closing_facts.v1` (`lane_turns.py:66-89`): native_status finished|error|cancelled|expired|in_doubt,
  result excerpt/ref, output_refs, usage, cost_disposition, git_branches, patch_ref, error, missing_outputs —
  "the only lane output the reducer and settlement read".
- Error classification `_classified` (`lane_turn.py:142-184`): `session_owned_elsewhere` (retry after lease),
  `stale_session_owner` (non-retryable), `continuation_in_flight` (5 s), `provider_capacity_limit`
  (non-retryable, carries `ProviderLimitSignal`), `lane_turn_rejected` for `LaneNotQualified`/
  `HarnessUnsupported`/`ValueError`.
- Registered on `-agent-cognitive` beside `operation.execute`; Session Lanes route by
  `provider_binding.task_queue` / `cursor_binding.task_queue`; dedicated queues need
  `MISSION_CONTROL_LANE_TASK_QUEUES` (`adapters/temporal/worker.py`). `SESSION_LANE_RUNTIMES = {cursor, claude, codex}`
  (`src/domain/execution/contracts.py:1664`).
- Generic engine: `LaneTurnService` (`src/application/execution/harness/lane_turns.py:347-2585`) does
  ownership claim, dispatch journal + Stop Fence (`_dispatch_once` 792, `_fence_denies` 910, `_park` 929),
  start-and-send (655), resume cursor from persisted frames (`_resume_cursor` 968), observe segment (987),
  frame persistence before heartbeat (`_write_frame` 1911, `_persist` 1205), mailbox injection/interrupt
  (1248-1440), steer (1460), terminal handling + continuation boundary (1574, 1622), pressure/native
  compaction (1738, 1774), handover (2027), settle (2229), status (2361), cancel (2411).

---

## 2. Touch-point checklist to add a lane profile

Import-time guards will fail fast if a vocabulary is missed: `lanes.py:99-108` (LaneProfile vs
LANE_PROFILES vs LANE_OF_PROFILE/PLACEMENT_OF_PROFILE), `lanes.py:200` (hook events),
`domain/capabilities/hooks.py:201` (HOOK_EVENT_MAPPING covers every LaneProfile),
`application/environments/bootstrap.py:193` (ROUTE_EVIDENCE covers every LaneProfile).

**Lane-name decision first.** Reusing lane `claude` for `claude_managed` and lane `codex` for
`openai_hosted` (only if it really runs the Codex harness) keeps the change additive. A new lane
(e.g. `openai`) additionally touches: `LaneName`/`ExecutionRuntime`/`RUNTIME_OF_LANE`/`BOUND_LANES`
(`lanes.py:42-43,84-92`), runtime↔binding pairing (`domain/execution/contracts.py:79-118`),
`SESSION_LANE_RUNTIMES` (1664), `default_lane_profile` and `_LaneOperationPayload` (`domain/execution/lane_turns.py:39-50,92-109`),
`lane_profile_for` (`harness/registry.py:134-145`), `describe_only_registry.bound_lanes` dict (`registry.py:176-185`, KeyError otherwise),
`approvals_broker`, DB `lane_profile_lane_check` (0031:17-18) — avoid unless required.

### Domain vocabulary
1. `src/domain/capabilities/host_support.py` — `LaneProfile` StrEnum (20-31), `HOSTED_PROFILES` (36-38),
   `UNQUALIFIED_BY_DEFAULT` (39-41), `OVERLAY_KEYS` explicit per-profile entries for hook_script and
   subagent_profile kinds (70-90).
2. `src/domain/execution/lanes.py` — `LaneProfileName` Literal (33-41), `LANE_PROFILES` (57-65),
   `LANE_OF_PROFILE` (66-74), `PLACEMENT_OF_PROFILE` (75-83), `HOSTED_PROFILES` (94-96).
3. `src/domain/capabilities/hooks.py` — native hook map per profile + `HOOK_EVENT_MAPPING` (184-201).
   Managed APIs with no hook surface → `{}` like `_CODEX_CLOUD` (189).
4. `src/domain/frames/contracts.py:24` aliases `LaneProfile` (automatic).
5. `src/domain/programs/search_attributes.py` — `MissionLane` Literal (22-30) and `MC_LANES` (55-63)
   (Temporal `mc_lane` keyword values; register attribute values if constrained).
6. `src/domain/execution/lane_turns.py` — `LANE_COMMAND_SEMANTICS` (186-205), `LANE_PAUSE_SEMANTICS` (212-221),
   `LANE_RESUME_SEMANTICS` (222-231).
7. `src/domain/context/checkpoint.py:96-104` — `_DELIVERY_BY_LANE` (continuation delivery).
8. `src/domain/frames/facts.py:162` — `CURSOR_LANES` (phase events only on Cursor; review for hosted).

### Describe / registry
9. `src/application/execution/harness/describe.py` — new `*_DESCRIBE` (v2), add to `DECLARED_LANE_MATRICES`
   (626-634) and to `V2_STUB_LANE_PROFILES` or `V2_IMPLEMENTED_LANE_PROFILES` (640-645).
   Promotion of `claude_cloud`/`codex_cloud`: move from stub set to implemented set, cells to `native`/`emulated`.
10. `src/application/execution/harness/registry.py` — `describe_only_registry(...)` flags (159-190); hosted
    profiles "ride on their lane's credential" (`bound_lanes[LANE_OF_PROFILE[profile]]`), so a `claude_managed`
    on lane `claude` would appear whenever `mission_control_claude_lane` is on — needs its own flag (e.g. Anthropic API key bound).
    Caller `src/bootstrap/api.py:605-608`.
11. `src/application/execution/harness/lane_turns.py:2578-2583` — `_placement()` hard-codes the cloud set (use `PLACEMENT_OF_PROFILE`).

### Bindings (`mc.execution_binding.v2`)
12. `src/domain/execution/bindings.py` — `ProviderName` (38), `PROVIDER_OF_PROFILE` (41-46), `V2_BINDING_PROFILES` (47-52),
    new options class beside `ClaudeCloudOptions` (198-205) / `CodexCloudOptions` (208-214), add to `ProviderOptions`
    union (217-220), `ProviderExecutionBinding.lane_profile` Literal (237). Constraints in `consistent()` (256-283):
    hosted ⇒ `environment.kind == provider_hosted`, **`repo_url` and `repo_commit` required**, workspace mode
    `provider_workspace`; `pins` must contain a key starting `sdk|cli|schema|app_server` (278). For API-only knowledge
    missions without a repo this is a blocker (gap G9); `EnvironmentBinding.provider` is `cursor|anthropic|openai` (99).
13. `CursorExecutionBinding` (`lanes.py:708-760`) is Cursor-only; not touched.

### Manifest / authoring / launch
14. `src/domain/authoring/manifest.py:296-300` — `Lane = LaneProfile`, `RESERVED_LANES` (v1 rejects), `HOSTED_LANES`.
15. `src/domain/authoring/manifest_v2.py` — `PROVIDER_OF_HOSTED_LANE` (67-71), placement/provider checks (225-270),
    `workspace.repo` required for hosted & provider lanes (317-325).
16. `src/application/authoring/manifest_v2_admission.py` — `V2_LANE_BEHAVIORS` (63-71), `EVIDENCE_BLOCKED_HOSTED` (72),
    `HOSTED_EVIDENCE` (73-76), hosted-launch warning (191-203); workspace policy skip for HOSTED_PROFILES (180).
17. `src/application/authoring/provider_launch.py` — `LOCAL_PROVIDER_PROFILES`/`HOSTED_PROVIDER_PROFILES` (64-65),
    `REQUIRED_PINS` (68+), `ProviderLanes` deployment section (128-160: add an entry + options/pins validator).
18. `src/application/authoring/manifest_launch_inputs.py` — hosted refusal `if profile in HOSTED_PROVIDER_PROFILES: raise`
    (797-803), `PROVIDER_PROFILES` (163), binding sealing path for provider lanes (~805+).
19. `src/application/authoring/manifest_service.py:194` — per-lane behaviors (Cursor), check for parity.
20. JSON Schemas `src/contracts/schemas/mc.mission_manifest.v1.json` / `.v2.json` regenerate (enum gains values; checked by
    `tests/unit/authoring/test_manifest_v2.py:222`).

### Projection / materialization / environments / workspaces
21. `src/application/agentic_components/projections.py` — `_SKILL_ROOTS` (75-82, KeyError for a missing profile),
    dispatch in `render_host_files` (129-139; Deep Agents returns `in_process` — an API lane that uploads skills and a
    system prompt needs a similar non-file path), `_report_kernel_gaps` (474-476), cloud-specific refusals (896-938).
22. `src/application/agentic_components/materialization.py:141` (CODEX_CLOUD branch), `hook_runner.py:170`.
23. Golden fixtures `tests/fixtures/projections/<profile>/_projection.json` (+ `regen.py`).
24. `src/application/environments/resolver.py` — `PROVIDER_OF_HOSTED_PROFILE` (35-39), `HOSTED_BOOTSTRAP_UNQUALIFIED` (≈190-200).
25. `src/application/environments/bootstrap.py` — `ROUTE_EVIDENCE` entries per profile (≈85-180, import guard 193),
    `OUTCOME_3_PROFILES` (188-191).
26. `src/application/workspaces/policy.py` — `BRANCH_SNAPSHOT_PROFILES` (39), `UNQUALIFIED_HOSTED_PROFILES` (41-43), `admit_policy` (68-85).

### Frames / reducer / lineage
27. `src/application/frames/kinds.py` — per-lane raw-kind table (`CURSOR_CLOUD_KINDS` 140 as model), `KIND_TABLES` (311-320),
    `DEDUPE_KEY_RULES` (323-347), key helpers (412-458). Unmapped kinds classify `unknown` and are **never closing**
    (`classify` 396-409), so without rows the reducer derives nothing.
28. `src/application/frames/reducer.py:194-200` — `provider_result(lane, body)` per-lane run_result shape.
29. `src/application/frames/lineage.py:84-88` — subagent usage rules (default `unattributable`).
30. `src/application/frames/provider_mapping.py` — pure provider-event→FrameObservation mappers (Claude/Codex pattern).

### Auth / bootstrap / composition
31. `src/application/execution/auth_admission.py` — `ROUTE_TABLE` (243-353: add `api_key` route, billing `api`),
    `_UNSUPPORTED_NOTES` (355-368).
32. `src/adapters/provider_auth/detection.py` — `SURFACES` (125-209; env signals `_CLAUDE_ENV` 95-104, `_CODEX_ENV` 113-117).
33. `src/bootstrap/provider_auth.py` — `_BOUND_CREDENTIAL_SETTINGS` (38-42), `provider_child_environment` (171-188; only relevant to subprocess lanes).
34. `src/bootstrap/settings.py` — `openai_api_key`/`anthropic_api_key` (61-62), `cursor_api_key` (305), lane opt-ins (362, 366).
35. `src/bootstrap/preflight.py` — `LANE_HOSTS` (322-330; KeyError at 361 for unknown names), `_OUTCOME_3` (331).
36. `src/adapters/temporal/deployment_composition.py` — `registered_lane_profiles` (494-507), `lane_continuation_registrations`
    (524-554), `compose_lane_registry` (582-603), a `compose_<profile>` like `compose_cursor_cloud` (606-639), worker wiring (970-1075).
37. `src/adapters/temporal/provider_lane_composition.py` — opt-in compose functions (80, 143), `compose_approval_broker` (62),
    `provider_registrations` (189-201).
38. `deployments/examples/provider-auth-profiles.example.json`, `tests/fixtures/provider_auth/route_preflight.fixtures.json`.

### DB contract (`packages/mission-control-db-contract`, never edit applied migrations)
39. New migration (next after `0034_provider_frame_lifecycle_body.sql`; `component/release-spec.json` is at `1.3.0`) that, like
    `0031_multi_provider_lanes.sql`, widens: `harness_execution_lane_profile_check` (0031:75-79), `provider_frame_lane_profile_check`
    (80-84), `continuation_transfer_lane_profile_check` (85-89), `search_document_host_profiles_known` (93-97),
    `capability_host_support_valid()` (102-118), `execution_binding_lane_binding_shape` + `execution_binding_cursor_lane_binding`
    (55-71); inserts `lane_profile` rows (seed pattern 0031:28-50 with `NO FORCE`/`FORCE ROW LEVEL SECURITY`). `lane_profile.lane_profile`
    itself is regex-checked only (0030:13); `lane` CHECK is `deep_agents|cursor|claude|codex` (0031:17-18).
    Promoting a stub = UPDATE through the `lane_profile_immutable` trigger in a new migration (0033 pattern, 0033:406-441).
40. `packages/mission-control-db-contract/scripts/lane_describe_refresh.py` — `REFRESHED_PROFILES` (34) and target migration;
    `component/generated/contract.json` regenerated by release-build.
41. Tests that pin the SQL to the code: `tests/unit/harness/test_lane_contracts.py:380-404`
    (`_IMMUTABLE_LANE_MIGRATIONS`, seeded/revised sets must equal `DECLARED_LANE_MATRICES`) and 406-420 (generated section);
    `tests/integration/postgres/test_lane_bindings.py`, `test_release_0033.py`.

### Qualification / release / docs
42. `docs/qualification/lanes/<profile>/` (README or FEASIBILITY + `feasibility-matrix.json`), release statement
    `docs/specs/archive/mc-surfaces-2026-10/docs/qualification/release/multi-provider-2026-10.md`, `scripts/lane_qualify.py` (`PROFILES` 47, `OFFLINE_BY_PROFILE`,
    `LIVE_TEST_BY_PROFILE`, `LIVE_FLAG_BY_PROFILE` 55-69), `Makefile:294` help text.
43. Docs: `docs/knowledge/lanes-and-harness.md`, `provider-lanes.md`, `qualification.md`, `persistence.md`, `GLOSSARY.md`, an ADR
    (0035 says "Seven Lane Profiles"; a new profile is an ADR delta), regenerate `AGENTS.md` index (`python docs/tools/agents_docs_index.py`).
44. Tests enumerating profiles: `tests/unit/harness/test_lane_contracts.py:110` ("seven profiles"), `test_multi_provider_contracts.py:75`,
    `tests/unit/frames/test_run_list_and_search.py`, `tests/unit/agentic_components/test_environments.py`,
    `test_projection_materialization.py`, `tests/unit/approvals/test_approval_coverage.py`, `tests/unit/provider_auth/test_auth_admission.py`,
    `tests/unit/workspaces/test_workspace_allocation.py`, `tests/unit/operations/test_continuation_*`, `tests/unit/authoring/test_manifest_v2_launch.py`.

---

## 3. The `cursor_cloud` reference lane and what is reusable

Files: `src/adapters/cursor/cloud.py` (1353 lines), `cloud_api.py` (236), `sse.py` (102), `frames.py`, `controls.py`, `scm.py`,
`snapshot.py`, `workspace.py`. Composition `deployment_composition.py:606-639`.

| Concern | Implementation |
| --- | --- |
| Launch | `prepare` (`cloud.py:370-452`) pushes branch `mc/<run>` with Host Projection + Context Packet files (`GitBranchPublisher`), records provider-workspace lease (`CURSOR_CLOUD_POLICY` 161-166). `start` (476-538) creates agent with deterministic client id `client_agent_id = bc-uuid5(heid:generation)` (172-175); `409 agent_id_conflict` ⇒ already created; or `Idempotency-Key` when `envVars` are needed (`CursorCloudOptions` `lanes.py:681-699`); create enqueues turn 1. |
| Follow-up | `send_turn` (598-639): `409 agent_busy` ⇒ `TurnHandle(status="busy")` (`wait_then_send`), `429` ⇒ `ProviderCapacityLimited` with `capacity_signal` (248-263). |
| Observe (SSE w/ replay) | `observe` (791-842) → `_stream_frames` (844-894) using `Last-Event-ID`; per-run cursor `run@eventId` (`stream_cursor`/`last_event_id` 188-206), provider key `sse:<run>:<id>` (182-185), id-less leading status deduped by content hash (`_content_key` 220), heartbeats dropped, `done` ends; `InvalidLastEventId` ⇒ reopen without cursor once. Parser `sse.py:61-85` (WHATWG rules) plus `render_sse` for fakes. |
| Poll fallback | `410 stream_expired` ⇒ one `stream.expired` status frame then `_reconcile_run` (896-950): run record is terminal truth; synthesizes `run.final` frame (key `cursor_cloud_final_key`), or polls with status frames per change up to `_expired_poll_limit`. |
| Frames → reducer | `LaneFrame.terminal` on `result`/`run.final`; `closing_facts` (952-956) via `adapters/cursor/frames.py:225 closing_facts(body)`; `final_text` (958-965); `resume_cursor` (967-973) maps persisted provider_key back to a cursor. Kind rows `application/frames/kinds.py:140` `CURSOR_CLOUD_KINDS`; reducer `application/frames/reducer.py`. |
| Commands | `cancel_turn` (1109-1125) `POST .../cancel` then `GET run` (`RunNotCancellable` ⇒ already terminal); `status` (1086-1107) agent+run; interrupt = `cancel_and_replace` (staged turn texts `stage_turn` 975); continuation = `CursorCloudSessionHydrator` (`controls.py:181`) creating a fresh agent on the branch; `reconcile_dispatch` (641-753) by client agent id / `latestRunId` anchors. |
| Workspace via branch | `snapshot` (1180-1204) ⇒ `branch:<branch>@<sha>` (`branch_snapshot` 209); `end_session` (1206-1303) diff patch from SCM, artifact download with digests, lease release after custody, archive agent. Reattach rehydrates branch/lease/anchor (`_rehydrate` 558-590). |
| Usage | `usage` (1127-1160): settled only when `/usage?runId=` reports this run; cost via optional `CloudCostReader`; else `unknown`, never zero. |
| HTTP client | `CloudAgentsClient` (`cloud_api.py:118-236`) + typed errors (`AgentIdConflict`, `StreamExpired`, `AgentNotFound`, `InvalidLastEventId`, `CloudCapacityLimited`, `_raise` 90-116). Tests use `httpx.MockTransport` fakes (`tests/fixtures/cursor_cloud.py`). |

**Reusable for a generic "remote session lane" base** (currently Cursor-specific, worth extracting to e.g.
`adapters/remote_session/`):
- Already generic (in `LaneTurnService`, no work needed): dispatch journal + Stop Fence + session ownership,
  persisted-frame-as-truth resume, segment bounds/heartbeat, busy/capacity waits, settlement from `ClosingFacts`,
  output custody (`application/execution/operations/lane_outputs.py`), continuation phase machine, mailbox delivery reports.
- Extractable from Cursor: SSE parser/renderer (`sse.py`, provider-neutral); per-run cursor scheme and
  `last_event_id` resolution; stream-open/expired status frames; "stream then reconcile from the status record,
  bounded poll" loop (`observe` + `_reconcile_run`) parameterised by `stream()`, `get_turn()`, terminal-status set,
  terminal event name; deterministic client idempotency ids (uuid5 of heid:generation) and `parse_dispatch_key`
  (229-245); `DispatchReconcilingLane` "known_runs/anchor" bookkeeping; capacity signal from `429 Retry-After`;
  busy (409) ⇒ `TurnHandle(status="busy")`; usage "settled only if reported" rule; `closing_facts`/`final_text`
  from a terminal body; `resume_cursor` from provider key; branch publication + `branch:<b>@<sha>` snapshot and
  end-session custody (for repo-bound work); typed HTTP error taxonomy.
- Needs per-provider code: request/event mapping, kind table rows, reducer `provider_result` shape,
  describe matrix, binding options, auth route, and (for Managed Agents/OpenAI) session-level interrupt vs per-run cancel,
  native approvals if the API exposes tool-confirmation events (→ `ApprovalBroker`).

---

## 4. Auth and secret handling today

- Settings fields (pydantic `SecretStr`): `openai_api_key`, `anthropic_api_key` (`bootstrap/settings.py:61-62`),
  `cursor_api_key` (305). Cursor lanes are composed iff `cursor_api_key` set (`deployment_composition.py:498,597,617,654`);
  `CloudAgentsClient(settings.cursor_api_key)` (623). Cursor envVars via injected `CloudEnvResolver`
  (`cloud.py:306,500-505`), not composed in production (PLAN MO-06).
- Raw env reads: `OPENAI_API_KEY` in `adapters/agent_server/async_subagents/graph.py:53-56`; Deep Agents secret refs
  `environment:OPENAI_API_KEY` (`adapters/deep_agents/materializer.py:210`), resolved by `EnvironmentSecretResolver`
  (`adapters/operations/runtime_ports.py:38-63`, env-only; other providers refused), composed at
  `deployment_composition.py:968`, `bootstrap/subscriptions.py:82,121`. Ports: `SecretResolutionPort`
  (`application/execution/operations/operation_execution.py:627`), `SecretValues` (`harness/lane_turns.py:240`).
- Auth profiles (MP-05): `mc.auth_profile.v1` (`application/execution/auth_admission.py:152-217`), `credential_ref`
  syntax `env:|settings:|secret:|keyring:` (141, 199-207), but only `env:` is ever resolved
  (`adapters/codex/launcher.py:140-146`); `ROUTE_TABLE` (243-353); billing consent `allowed_billing_modes`
  (`AUTH_BILLING_NOT_CONSENTED`). Composition `bootstrap/provider_auth.py:134-168` from
  `MISSION_CONTROL_AUTH_PROFILES_PATH`; detection surfaces `adapters/provider_auth/detection.py:125-209` read env-var
  names, never values. Child env: `provider_child_environment` (`bootstrap/provider_auth.py:171-188`) is a **deny-list**
  (whole worker env minus `env_unset`) — the Claude leak G12 (`SPEC-01:127`); Codex uses an allowlist (`launcher.py:149+`).
- Redaction: `domain/frames/body.py:33-39` names CURSOR/OPENAI/ANTHROPIC keys; `adapters/cursor/frames.py:247 scrub`.

What the Secret Broker (SPEC-01 §4, `SPEC-01-environments.md:112-137`) must replace/extend:
`EnvironmentSecretResolver` (env-only) → sources keyring/file, Supabase Vault, `provider_held`; resolve
`secret:`/`keyring:` `credential_ref`s for auth profiles (today syntactic only); replace settings-field credentials
(`cursor_api_key`, `anthropic_api_key`, `openai_api_key`) as the control-plane API key source for hosted API lanes;
replace `provider_child_environment` deny-list with allowlist delivery; implement `CloudEnvResolver`/per-lane delivery
(Cursor secrets API, Managed Agents vaults, OpenAI equivalents); `mint:signal_token`; exact-match redaction of resolved
values in frames/receipts/logs; secret names (never values) in `EnvironmentBinding.secret_refs` (`bindings.py:107,140-141`).
For API-billed lanes the broker must also bind billing consent: route `api_key` with `billing_mode="api"` and explicit
consent; never fall back from subscription.

---

## 5. Continuation/compaction and approvals integration points

Continuation (ADR-0039/0041):
- Register `LaneContinuationRegistration(lane_profile, hydrator, snapshots, qualified=False)`
  (`application/context/hydrators.py:30-38`) via `lane_continuation_registrations(extra=...)`
  (`deployment_composition.py:524-554`) / `provider_registrations` (`provider_lane_composition.py:189-201`). Without it a
  transfer is refused `unsupported_control` (`hydrators.py:63-70`).
- Implement `SessionHydrator.hydrate(HydrationRequest) -> HydrationReceipt` and `WorkspaceSnapshotPort.snapshot/load`
  (`application/context/continuation.py:340-384`); `SessionHandoverLane` (`harness/controls.py:132-136`) so the next turn
  goes to the target session; `_DELIVERY_BY_LANE` entry (`domain/context/checkpoint.py:96-104`).
- Optional `ContextOccupancyLane` / `CompactingLane` (`application/context/lane_support.py:56-70`); describe
  `compaction_control`; unknown occupancy must be reported unknown (ADR-0039). The workflow drives
  `continuation.pending/advance`; `lane.turn` raises `ContinuationInFlight` while fenced.
Approvals / Human Gate (ADR-0038):
- `ApprovalBroker.bind(NativeApprovalRequest)` / `wait` / `recover` (`application/execution/approvals_broker.py:108-130,188-346`),
  one broker per worker (`compose_approval_broker`, `provider_lane_composition.py:62`); `mc.approval_binding.v1`;
  policy digest = binding digest; wait ≤ `MISSION_CONTROL_APPROVAL_WAIT_S`; fail-closed `DenyWithoutGateway` without broker.
- Describe `approval_modes` and `enforcement_coverage`; `admit_gate_coverage` refuses workflows needing gates the lane
  cannot enforce. Cursor cloud declares only `workflow_gate` (no vendor approval surface).

---

## 6. Test layout and qualification recording

- Per-lane unit suites: `tests/unit/cursor/` (cloud capacity/busy, reconcile, stream expiry, usage unknown, workspace/resume),
  `tests/unit/claude/` (`fixtures.py` FixtureClient), `tests/unit/codex/` (`fixture_app_server.py`), `tests/unit/harness/test_cursor_cloud.py`.
- Fakes/fixtures: `tests/fixtures/cursor_cloud.py` (Cloud Agents API fake over `httpx.MockTransport`), `cursor_local.py`,
  `tests/fixtures/provider_frames/{claude,codex}/` (Codex schema pin), `tests/fixtures/projections/<profile>/` golden projections,
  `tests/fixtures/lane_turns.py`, `mp06_lanes.py`, `mp12_lanes.py`, `mp20_parity.py` (one production stack, all local lanes, FIXTURE at provider seam).
- Cross-lane contract tests (closest to a conformance suite): `tests/unit/harness/test_lane_contracts.py`
  (parametrized over declared matrices; SQL ⇔ code), `test_multi_provider_contracts.py`, `test_lane_registry.py`,
  `test_lane_dispatch.py`, `test_mp06_dispatch_recovery.py`, `test_lane_final_text.py`, `test_lane_output_custody.py`.
  **`test_describe_honesty.py` is Cursor-only** (`PROFILES = ("cursor_local","cursor_cloud")`, line 66) — there is no
  shared, parametrized lane conformance suite that any new SessionLane can plug into; Claude/Codex reimplement theirs.
  Recommend extracting a reusable `SessionLaneConformance` (drive every native/emulated cell through `LaneTurnService`
  against a fake provider) before adding two more lanes.
- Integration: `tests/integration/temporal/test_lane_turn.py`, `test_lane_replay_histories.py` (histories `ft_lanes/`),
  `test_mp07_claude_lane_turns.py`, `test_mp08_codex_lane_turns.py`; `tests/integration/cursor/test_mp09_cloud_segment_loop_real_services.py`.
- Drills: `make lane-qualify PROFILE=... [LIVE=1]` → `scripts/lane_qualify.py` (offline suites + live test gated by
  finite `MC_PAID_BUDGET_USD`, per-profile `MC_LIVE_*` flags); live runners `tests/integration/{cursor,claude,codex}/test_*live*.py`
  + `live_drill.py`; records `docs/qualification/lanes/<profile>-<date>.md` and scrubbed recordings
  `tests/integration/cursor/recordings/...` (`docs/qualification/lanes/README.md:27-55`).

---

## 7. Skills placement

| Location | What it is | Lock/publish |
| --- | --- | --- |
| `skills/` (mission-control, -author, -catalog, -compose, -intervene, -observe) | `mc.skill_bundle.v1` bundles that teach agents to operate Mission Control (ADR-0033 router); seeded into the catalog as `skill_bundle` capabilities | `manifest.json` digests; `make skills-manifest` / `make skills-check` (`scripts/skills_manifest.py`, part of `make check`, Makefile 287-300) |
| `.agents/skills/` | Canonical, tracked repo-local agent skills (third-party installs + local ones: `mission-control-coordinator`, `mission-control-docs`, `mission-control-local-setup` with gitignored ledger) | Third-party ones recorded in `skills-lock.json` (53 entries; `source`, `skillPath`, `computedHash`; `npx skills` installs). Local ones are not in the lock. |
| `.claude/skills/` | Machine-local symlinks to `.agents/skills/*` (absolute paths) | gitignored (`.gitignore:223-224`) |
| Catalog skill bundles for lanes | `packages/mission-control-db-contract/seeds/agent_skills.py` + `mc.app.<app>.agent-skills` seeds; bytes uploaded by `scripts/seeds_publish_bundles.py` / `publish_skill_bundle.py` (ADR-0024 custody) | seed versions immutable |

The BellLabs workspace root has no `.agents`/`.claude` skills dir; workspace AGENTS.md says skills stay scoped to their owning repo.
**Recommendation:** put general-purpose local skills ("drive Cursor/Codex/Claude CLIs") in
`platform/mission-control/.agents/skills/<name>/` (SKILL.md + `scripts/` + `references/`, following `mission-control-local-setup`
and the `writing-for-agents` skill), with a machine-local `.claude/skills/<name>` symlink. Do not put them in `skills/`
(reserved for catalog-published MC lifecycle bundles with manifests) and do not add them to `skills-lock.json` (external-sourced only).
Only if a lane must materialize the skill into provider sessions does it also become a catalog `skill_bundle` seed.
Scripts conventions: repo `scripts/` (flat Python CLIs, `scripts/dev/` for dev helpers, `scripts/hooks/`), no `tools/` dir
(only `docs/tools/`); the only console entry point is `missionctl = "mission_control.interfaces.cli.main:main"` (`pyproject.toml:57-58`);
skill-private scripts live inside the skill's own `scripts/` dir.
