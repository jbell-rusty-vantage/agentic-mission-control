# Lifecycle reliability implementation and deployment handoff

Date: 2026-10-11. This is implementation evidence, not a release or production qualification.
Existing uncommitted work was preserved. No live schema, provider credential, cloud resource,
public endpoint, commit or push was changed. Paid provider experiments were not run.

## Implemented changes

- Stage Graph result admission now applies terminality, cancellation, generation and execution
  failure checks to leaf stages too. Previously a stage without outgoing edges bypassed them.
- Authored output schema references and required/optional declarations survive lowering.
  Named output bindings distinguish multiple output slots, and completion validation reasons
  are recorded in the existing durable family decision payload. Declared references do not
  prove the bytes satisfy their schema; that distinction remains explicit.
- Fresh Stage Graph manifests can bind declared JSON output schemas to exact admitted
  catalog tool revisions. The schema body and source/schema digests are frozen in the
  blueprint. Unsupported references, assessment/compound criteria and unsupported schema
  features still fail closed. Existing frozen templates retain their original identity.
- Goal Directed now applies the same custody/schema validator to named declared output
  slots and their schema criteria, validates every candidate reference, persists immutable
  verification checks and recovers exact request-bound receipts after interruption.
- Explicit Stage Graph output bindings must account for every returned output reference.
  Extra unbound references are rejected before acceptance; emitted optional outputs in a
  schema-bound result also need a validator. Native Claude `aborted_tools` and
  `aborted_streaming` terminal reasons consistently reduce to cancellation.
- Frame reduction distinguishes native turns, retains late evidence under its original turn,
  and allows an authoritative terminal observation after an unknown observation. Projection
  handles paged histories and restart without treating successful batches as contention.
- Cursor ambiguous sends remain uncertain when the latest run has not changed. This does
  not authorize a resend. Expired event cursors reconcile using the provider run record.
- New scoped HTTP evidence/input retrieval is composed in the configured API.
- Typed result persistence rejects outcomes that disagree with the authoritative terminal
  run; cancelled runs cannot store a completed result through direct repository writes.
- Fresh `mc.mission_run.v1` roots now durably materialize typed terminal results before
  returning. The result activity was previously registered but never invoked. A replay patch
  preserves historical workflow behavior; ledger outcome and accepted evidence remain the
  authority for completed, failed, partially completed and cancelled results.
- Verified Biotech reports retain trusted run/operation/generation/handler provenance in
  their existing immutable digest-pinned payload. Reports do not acquire invented mission,
  provider execution or model identities; no entity/course writer was added.

The main changed paths and verification results are listed below. Detailed local test XML
and workstream reports are retained in `.scratch/overnight-reliability/`.

## Retrieval contract

The retrieval endpoints use `/v1/applications/{application_id}/runs/{run_id}` and require
`workflow_run.read` **and** `workflow.result.read`. Authentication, installation/application
authorization and service-scope matching happen before repository reads.

| Endpoint | Returned authority and limits |
| --- | --- |
| `GET .../evidence` | `mc.run_evidence.v1`: persisted mission ID when recorded, run inspection, admitted input manifest reference, exact semantic handler/input/output contract digests, typed terminal result if recorded, and continuation-manifest references |
| `GET .../inputs` | `mc.run_inputs.v1`: exact frozen semantic input binding and separately typed native templates, including bodies and document digests; unlike the evidence summary, this is a body-bearing read |
| `GET .../completion-evidence` | Bounded Stage Graph validation receipts from the existing family journal, ordered by family version; follow `next_after_family_version` using `after_family_version`; maximum page size 100 |
| `GET .../goal-completion-evidence` | Goal Directed checks from immutable `goal.verification/1` documents; follow `next_verification_id` using `after_verification_id`; maximum page size 100 |
| Existing `GET .../inspection` | Canonical phase/outcome, accepted obligation/output evidence and authority references, commands, session observations and available frame cursor |
| Existing `GET .../transcript` | Materialized mission events plus available provider frames; provider observations remain noncanonical; JSON/JSONL/Markdown and cursors |
| Existing `GET .../transcript/search` | Rebuildable search projection, not an independent history authority |
| Existing `GET .../checkpoints[/{checkpoint_id}]` | Sealed continuation manifests and transfer records; availability does not certify present external runtime/workspace availability |
| Existing snapshot/fork APIs | Recorded metadata and classified restoration semantics; not an automatic full process/filesystem checkpoint |

`recorded`, `not_recorded`, `unavailable`, `pending`, and `missing_terminal_result` have
different meanings. A terminal run lacking a typed result is visible as an evidence gap.
Disagreeing scope/configuration/result records or a run version changing during assembly
return `409 run_evidence_inconsistent`; unknown or other-tenant runs return 404. This is a
bounded multi-store read with a ledger-version check, not a claim of one atomic database
snapshot. Provider URLs, trace URLs, current sandbox state and artifact-byte availability
remain explicitly uncollected/unverified in this aggregate. Native session/execution refs
are exposed only where persisted; no vendor URL is constructed from a guessed ID.

Run completion, accepted obligation evidence, valid output evidence, domain admission and
publication remain separate. Consult `inspection.projection` and typed result evidence;
neither a provider terminal frame nor existence of a result record establishes generalized
mission fulfillment.

The aggregate includes the first completion-evidence page only. Receipts preserve the
writer's versioned output and criterion checks, artifact/schema hashes, reasons and scope.
Legacy `not_evaluated` evidence is not upgraded into a successful validation. While a
publication retry is still uncommitted, the read can truthfully show `not_recorded`.
Historical rejected and accepted receipts are not collapsed into an inferred fulfillment
verdict. A receipt fingerprint, scope, run or cursor conflict fails closed.

Not every launch route writes the coordinator semantic binding table. Native technical,
manifest and fork templates are therefore returned separately as `native_templates`, not
fabricated semantic bindings. The reader decodes the durable `mc.mission_run.v1` start input,
verifies its scope/run/configuration against the admitted ledger, and uses its exact binding
reference to read existing digest-checked PostgreSQL templates. Template placeholders are
preserved. Temporal history must remain available; this read does not recover expired root
history or infer a binding from naming conventions. The summary reports the template count.
Goal verification pagination is ordered by recorded time and identity; historical checks
remain observations, while run-control acceptance remains the authority.

## Declared artifact validation

The supported slice is Stage Graph and Goal Directed JSON outputs, including multiple named slots,
whose declared schema reference selects an
exact admitted catalog `MCPToolDefinition.output_schema` revision. No new domain-wide schema
registry is invented. Validation requires recorded artifact/workspace-candidate custody,
matching source reference, a supported JSON media type, bounded bytes, exact byte length and
SHA-256 digest, strict finite JSON with unique keys, and a frozen Draft 2020-12 schema.
External schema resolution, alternate dialects, regex constraints and unknown references
remain unsupported. `format` follows Draft 2020-12 annotation semantics, not an assertion.
The validator records hashes and reason codes, never artifact bodies.

Each output and schema criterion has durable satisfied, unsatisfied or unavailable evidence
when the result is settled. Schema-owned obligations are derived from trusted checks;
provider assertions cannot satisfy them. A producer result lacking a required output is
rejected. Referenced custody or bytes that are not published yet cause a retry before any
family mutation. The stable activity input survives restart; a 15-minute publication grace
period ends in explicit unmet evidence. Unsupported artifact media and missing validators
remain distinct from a schema mismatch.

Validation receipts commit with the reducer-authorized family decision. If that commit
succeeds but its activity response is lost, a replay reads the exact immutable journal
mutation and verifies the original request digest and recorded projection/proposal. It
does not re-read artifact bytes or apply acceptance twice. A changed delivery reusing the
same identity is rejected. Optional bytes can expire after settlement without rewriting
the historical validation claim. This does not certify continued artifact availability.

Goal Directed validates every executor output reference before binding the independent
verifier result. A schema failure overrides provider acceptance; successful schema criteria
derive their owned obligations. The existing immutable verification envelope retains the
checks and exact request digest, allowing lost-response recovery without artifact re-read.
Pending publication retries have the same 15-minute bound and stop retrying when the run
is cancelling/terminal. A replay patch limits the new workflow path to fresh schema-bound
runs; a distinct lowering identity preserves previously published Goal Directed definitions.
Multiple Goal Directed slots require explicit `output_bindings` from slot names to references.
Every returned reference must be bound; unknown slots and unregistered references fail before
artifact reads. Each slot uses its own pinned schema. An invalid required or emitted optional
output rejects the candidate without accepted obligations. A changed binding invalidates exact
receipt replay and the verification frontier even when flat references are unchanged.
Single-output observations retain their historical flat-reference behavior. Absent bindings
are omitted from historical wire/document payloads and lineage digests; the original executor
schema digest is unchanged. Deep Agents multi-output launches require the explicitly configured
`GoalNamedExecutorObservation` schema. Both schemas are registered; the prepared
[binding fragment](../../../../../deployments/cloud_runtime/goal-named-output-binding.json) is not applied
to an operator configuration. General assessment/compound
expressions remain blocked without an explicit evaluator. Non-JSON artifact validation and
automatic capture of arbitrary provider output files are not implemented by this slice.
The declared output contract is included in schema-bound stage prompts, but providers still
must publish into admitted artifact custody and return references through their supported
result contract.

## Existing storage authorities and capture strategy

The common SQL authority remains `packages/mission-control-db-contract`. No redundant event,
artifact or checkpoint tables were introduced. Component **1.3.0** adds migration
`0034_provider_frame_lifecycle_body.sql` to preserve bounded lifecycle facts alongside the
existing provider-frame excerpt. Only disposable databases were upgraded; live app locks
and installations were not changed.

| Persisted fact | Existing authority | Treatment |
| --- | --- | --- |
| Immutable input/routing | Admission/input manifest and `mc.semantic-input-binding/1` execution binding | Read exact digest-pinned binding; do not reconstruct from provider prompts |
| Business lifecycle and decisions | App-local mission ledger, outbox, run projection, family mutation decisions | Preserve acceptance, command delivery, applied effect and execution outcome independently |
| Provider observations | Native Event Store `provider_frame`, identity records, projection cursors | Deduplicate stable frame IDs; ordering is observation evidence, not authorization; retain uncertainty after gaps |
| Completion checks | Existing `family_admission_journal`, `goal.verification/1` detail envelopes and accepted evidence digests | Immutable scoped validation receipts; result/activity replay recovers exact prior decisions |
| Typed family result | `coordinator_workflow_result` | Immutable per scoped run; missing/conflicting terminal result is not success |
| Artifact registration | `artifact`, `artifact_metadata_revision`, workspace candidate descriptors | Digest and custody metadata in SQL; bytes in the configured durable payload store |
| Semantic continuation | Sealed continuation checkpoint, transfer phase records, Context Packet and workspace references | Validation of a manifest differs from verifying current resumability |
| Deep Agents cognition recovery | Registered scoped LangGraph checkpointer/store | Restore graph progress; application reducer remains business authority |
| Agent Server recovery | Server-owned native checkpointer/store | Do not inject a conflicting standalone saver; verify the pinned server topology separately |
| Tracing | LangSmith/external tracing | Diagnostic evidence with its own retention; never the mission ledger |

The existing frame retention default is 30 days for nonclosing frames, with closing frames
preserved and an 8 KiB excerpt cap. Mission events survive frame expiry and transcripts can
show expired-frame placeholders. Do not delete artifact bytes still referenced by completion
evidence or a retained checkpoint. Durable payload-store retention, export jobs and restore
qualification must be agreed and verified before production; this task did not enable a new
purge job or claim a complete backup policy. Sandbox snapshots, retained file bytes, a
continuation manifest and a natively resumable graph checkpoint are separate capabilities.

Cursor capture now records its known run/activation/attempt/harness/generation attribution,
observed native run IDs and capture timestamp. Agent-scoped artifacts remain agent-scoped;
the capture explicitly says it is not a resumable execution checkpoint. Expiring provider
download URLs must not be treated as durable object addresses.

Cancellation and replacement now paginate the persisted frame history rather than stopping
at 10,000 frames. Provider lifecycle summaries survive an oversized excerpt and are consumed
after PostgreSQL recomposition by reduction and continuation. This preserves known terminal
status without storing full messages in the summary. Old truncated frames that lack those
facts remain uncertain. Usage with a new native turn ID cannot settle a previously ended
turn; genuinely delayed usage with that prior ID retains its correct attribution.

## Provider support and observation limits

This matrix distinguishes inspected repository paths from newly documented provider APIs.
Documentation findings were supplied by the coordinating research task on 2026-10-11;
account eligibility and paid execution were not tested here.

| Surface | Repository/deployment status | Evidence and limits |
| --- | --- | --- |
| Deep Agents in Temporal worker | Existing library/checkpointer/store adapter; preferred primary cognition path | Synchronous graph durability and qualified lineage; hosted async subordinate path is separate; no duplicate business ledger in graph state |
| Deep Agents async subagents | Existing Agent Server/Agent Protocol integration requires qualified binding | Agent Protocol-compatible server required by async middleware; several graphs can share one server, subject to shared capacity and isolation |
| Cursor cloud v1 | Existing v1 adapter, strengthened in this task; not live-qualified here | Durable agent/workspace plus per-prompt run; SSE cursor recovery and provider run reconciliation; v1 webhooks unavailable; agent-scoped files/git snapshots are not immutable per-run outputs |
| Existing Codex cloud profile | Non-executable `codex_cloud` declaration/stub; no repository harness | Do not equate local SDK/cloud product affordances with the newly documented Agents API |
| OpenAI Agents API with managed Codex harness | Newly documented distinct surface; unimplemented/unqualified here | Session/turn IDs, stored items, optional hosted sandbox; stream has no missed-event replay, so reconcile saved item IDs; idle is not successful fulfillment |
| Existing Claude cloud profile | Non-executable `claude_cloud` declaration/stub; no repository harness | Do not equate self-hosted Agent SDK, Claude Code web routines and Managed Agents |
| Claude Managed Agents | Newly documented separate API; unimplemented/unqualified here | Session states and workflow execution states differ; unordered/lost webhooks require retrieval; published outputs can lag idle |
| Claude Code routine-fire | Launch-only API, not implemented in this task | Routine token cannot read session state, no documented idempotency; successful launch is not completion |
| Local Codex/Claude/Cursor lanes | Existing lifecycle context, outside new cloud deployment scope | No new local-lane deployment or qualification claim |

Primary references:

- [Cursor v1 endpoints](https://cursor.com/docs/cloud-agent/api/endpoints): distinguish v0
  webhooks from v1, use one event representation to avoid duplicate ingestion, reconcile
  410 cursor expiry. Download URLs expire; capture bytes before expiry.
- [OpenAI Agents API](https://developers.openai.com/api/docs/guides/agents-api/overview):
  separate API/auth/eligibility and managed execution contracts. A future adapter needs
  open/buffer/list/reconcile semantics, event idempotency and effect-aware recovery.
- [Claude Managed Agents](https://platform.claude.com/docs/en/managed-agents/overview) and
  [routines-fire](https://platform.claude.com/docs/en/api/claude-code/routines-fire): separate
  products with different observability and control; no inferred read access.
- [Deep Agents async subagents](https://docs.langchain.com/oss/python/deepagents/async-subagents)
  and [Agent Server](https://docs.langchain.com/langsmith/agent-server): thread/run recovery
  differs from HTTP connection lifetime and sandbox lifetime.

## Deployment decision and remaining blockers

The [cloud runtime package](../../../../../deployments/cloud_runtime/README.md) supplies an offline ECS
review renderer, nonroot Dockerfile, example and tests. [Inventory](../deployments/cloud_runtime/INVENTORY.md)
records the bounded read-only AWS inspection. Temporal remains the scheduler. API and
long-lived workers remain distinct process roles; managed Agent Protocol hosting is a
candidate for bounded asynchronous child graphs only when entitlement, isolation and runtime
binding are verified. A single small serverless deployment is not assumed sufficient for
both applications' isolation requirements.

The specification provisionally suggests app-private Agent Server schemas, but ADR-0017 and
the pinned runtime topology audit require separate native runtime placement. This conflict is
reported, not silently resolved through `search_path` or business-schema reuse.

**Actual deployment: none. Verified new endpoints: none.** No numeric spending cap was
received by this task. No free reusable Mission Control capacity or unused LangSmith account
deployment entitlement was established. Exact networking/ingress/egress, IAM and secret
references, image/configuration digests, current schema/Temporal readiness, payload store,
Agent Server isolation and paid proof budget remain gates. Public Plus plan descriptions do
not verify this account's historic “Pro” entitlement or an unused serverless slot. See the
deployment package for official cost sources, assumptions, operations and recovery steps.

The [concrete approval proposal](../deployments/cloud_runtime/APPROVAL_PLAN.md) specifies
Ohio private Fargate tasks (API 0.5 vCPU/2 GiB, two workers each 1 vCPU/2 GiB), one public TLS
ALB, one NAT, app-private artifact storage, scoped roles and named secret recipients. Its
conditional two-app AWS estimate is $166-185/month, or $185-205 with contingency; managed
services and model usage are additional. The plan is not executed or approved.

The minimum AWS candidate is one app on a new 4 GB Lightsail host ($24/month fixed
compute), with a proposed $40/month AWS planning ceiling including snapshots and
contingency. This is neither approved nor an enforced billing cap; managed services and
providers are separate. Capacity, access, supervision, production bindings and restore
qualification remain gates. The existing local Docker host ($0 new AWS compute) is a
local alternative and does not fulfill the requested AWS deployment. An included LangSmith Small Serverless
slot remains account-unverified and would host eligible child graphs, not an assumed
replacement for Mission Control's continuously polling Temporal worker. See the plan's
fixed/usage separation and exact approvals; no starter resources were created.

Remaining engineering gaps are not disguised as deployment blockers: unsupported completion
operators, universal
trace/provider URL retrieval and all-provider sandbox exports remain incomplete. Newly
documented OpenAI/Anthropic managed APIs need explicit adapter work and qualification;
additional mock-only transports would not qualify those paths. Entity/course provenance
requires the owning domain's ingestion boundary. Historical roots that already returned
without a typed result, and family crashes before authoritative terminality, require an
explicit reconciliation/backfill path; the new root activity does not rewrite old histories.

Human acceptance must also match the gate's actual resolution action. Goal Loop review
acceptance requires `review_accept`; Stage Graph acceptance derives the action from its Human
Task kind. Approved gates carry only their pinned, attributable owned obligations. Required
dependency edges reject a missing producer output; an absent optional output cannot satisfy
a required downstream binding.

## Changed source and deliverables

| Concern | Main paths |
| --- | --- |
| Authored completion and output requirements | `src/mission_control/domain/authoring/{contracts,manifest_lowering,mission_definition,stagegraph_builder}.py`; `application/authoring/{completion_support,manifest_launch_inputs}.py` |
| Runtime acceptance and durable decision evidence | `domain/programs/{interpreter,human_gate}.py`; `application/programs/service.py`; `adapters/temporal/workflows/stagegraph.py` under `src/mission_control/` |
| Artifact schema checks and restart-safe acceptance | `src/mission_control/application/programs/{artifact_validation,completion_validation}.py`; `domain/programs/completion.py`; execution repository port plus scoped PostgreSQL journal lookup; runtime dependency declarations in `pyproject.toml`/`uv.lock` |
| Lifecycle observation and Cursor recovery/capture | `src/mission_control/application/frames/reducer.py`; `adapters/cursor/cloud.py` |
| Large-frame and long-history recovery | Frame body/domain/writer/repository and `application/execution/harness/lane_turns.py`; DB-contract component 1.3.0, additive migration 0034 and generated release evidence |
| Scoped evidence and input retrieval | `src/mission_control/contracts/run_evidence.py`; `application/missions/retrieval.py`; `interfaces/http/run_evidence.py`; `bootstrap/api.py` |
| Typed result authority check | `src/mission_control/adapters/postgres/coordinator/workflow_result_repository.py` |
| Durable terminal result materialization | `src/mission_control/adapters/temporal/workflows/mission_run.py`; activity registration; `application/coordinator/coordinator_results.py`; `domain/coordinator/{launch,workflow_completion}.py` |
| Validation receipt retrieval | `src/mission_control/application/missions/completion_evidence.py`; `adapters/postgres/orchestration/completion_evidence.py`; `/completion-evidence` HTTP route and aggregate field |
| Goal Directed validation and replay | `application/programs/goal_directed.py`; `domain/programs/goal_directed_runtime.py`; Temporal goal workflow/activity composition; `adapters/postgres/orchestration/{goal_directed_repository,goal_completion_evidence}.py` |
| Native input binding | `adapters/temporal/native_inputs.py`; `adapters/postgres/orchestration/native_inputs.py`; typed native-template response in `contracts/run_evidence.py` |
| Owned worker interruption proof | `tests/fixtures/{owned_process,validation_restart_worker}.py`; `tests/acceptance/mission_control/test_worker_process_recovery.py` |
| Biotech report provenance | `integrations/biotech/src/biotech_mission_adapters/domain/coordinator/web_research_runtime.py`; `application/web_research/web_research_semantic_handlers.py` |
| Deployment preparation | `deployments/cloud_runtime/{Dockerfile,plan.py,plan.example.toml,test_plan.py,README.md,INVENTORY.md,APPROVAL_PLAN.md,BUILD_EVIDENCE.json}` |
| Operator/API documentation | This report; `docs/MISSION_CONTROL_LOCAL_API.md`; generated root `AGENTS.md` documentation index |

Focused tests accompany the changes under `tests/unit/{authoring,orchestration,frames,cursor,
harness,mission_control,web_research,control_plane}` and `tests/integration/postgres`. Three
manifest resolution goldens were regenerated for versioned lowering. Existing unrelated
dirty files and concurrent documentation changes were preserved.

The browser runtime blocker was resolved by preserving 11 extra unpinned nested guide files
outside the admitted skill directory. The reviewed top-level skill bytes and every pin
remain unchanged. Expected and repaired bundle hash:
`sha256:30722859c783baa15e5a073984e66e716566bc0bef28dbd2cef3ed78e2d1fab3`.
The contaminated bundle was
`sha256:f65791f560252446d91923cfdc0d9989be71700a0a8420b6666d988bcfd8130d`.
The declared/installed browser is `agent-browser@0.33.0`; its pinned entrypoint verifies.
Recovery inventory, verified hashes, preserved files and the exact restore command are in
`.scratch/provider-lifecycle-2026-10-11/REPORT.md`. The stale tooling test now checks the
existing canonical `WORKSPACE_ROOT`; production runner/settings edits were preserved.

## Verification record

**Passed:**

- Final complete post-cancellation-fix unit/architecture run: **2,999 passed, 19 skipped,
  two expected failures, 28 warnings**, exit zero in **511.68 seconds**. This supersedes
  earlier broad runs below; see `cancel-race-final-broad.xml` and `.txt`.
- Final cancellation-race runtime regression: **four signed-API cases passed in 121.23
  seconds** (248 dependency/sandbox warnings), including delayed publication, cancellation
  during validation, pre-admission verifier preparation and post-admission cancellation
  with intentionally delayed Temporal delivery. Real PostgreSQL custody, filesystem bytes,
  Deep Agents checkpoints and production workers are used; only cognition is deterministic.
  The admitted verifier performs no model call; executor/verifier claims end respectively
  `settled`/`cancelled`, with exactly two receipts and two settlements. Duplicate command
  submission, late publication, typed terminal result and root/family/operation replay pass.
  Five focused unit regressions additionally cover unrelated failures, old-patch behavior,
  authority scope/phase rejection and durable waiting for delivery. Evidence:
  `cancel-race-final-acceptance.xml` and `test_operation_cancel_delivery_race.py`.
- Previous complete post-multi-output unit/architecture run: **2,994 passed, 19 skipped,
  two expected failures, 28 warnings**, exit zero in **526.72 seconds**. This supersedes
  the earlier broad result below; see `multi-goal-broad.xml` and `.txt`.
- Multi-output continuation: **51 focused tests** and **nine real PostgreSQL tests** passed.
  They cover different slot schemas, missing/extra/unregistered references, invalid bytes,
  exact receipt replay, changed bindings, cancellation, optional outputs and legacy payload
  compatibility. Real custody tests show a foreign tenant's registered summary cannot be
  read and its bytes are never fetched; immutable receipt replay fetches no bytes.
- The final signed-API multi-output Goal Directed proof passed both completion and cancellation
  cases in **90.78 seconds** (157 warnings). Production workers run the actual Goal Directed
  and operation workflows against PostgreSQL custody descriptors, filesystem payloads and
  a real Deep Agents checkpointer. Publication is delayed at the validator activity, then
  either supplied or cancelled through the signed API. Cancellation terminalizes with no
  accepted output/obligation; late publication cannot change the cancelled typed result.
  Root, Goal Directed family and operation histories replay successfully. Cognition is
  deterministic; this is not paid-provider qualification. See `multi-goal-final-acceptance.xml`.
- Previous complete pre-multi-output unit/architecture run: **2,981 passed, 19 skipped, two expected failures,
  28 warnings**, exit zero, in **469.92 seconds**. This is the complete rerun after the final
  single-output Goal Directed, native-input, reviewer, catalog-serialization and deterministic-clock
  fixes; `final-green-broad.xml` and `.txt` record the result. Skips and expected failures
  are described separately below.
- Continued implementation: 97 focused unit/compiler/retrieval/digest tests passed; 13
  catalog/capacity tests passed after preserving default-field serialization and replacing
  the setup-time-sensitive Retry-After check with an exact injected-clock assertion.
- Goal Directed immutable PostgreSQL validation/recomposition/retrieval: two tests passed,
  including pending publication, valid/invalid bytes, cross-tenant denial and exact receipt
  recovery without artifact reads. The updated authenticated production-worker test passed
  with native StageGraph/GoalDirected templates returned through `/inputs`.
- The final forced worker process-loss test passed in **48.43 seconds**. A fixture-owned
  Windows Job Object is assigned while its child is suspended, then resumed; only that
  launcher/interpreter tree is forcibly stopped. Its private Temporal server and fresh
  PostgreSQL database are fixture-owned; shared services are not stopped. A crash after
  the real StageGraph decision commits but before Temporal acknowledgement retries at
  activity attempt **2**, preserves the exact receipt/accepted output evidence, and reads
  artifact custody **zero** times during replay. Cancellation accepted while workers are
  absent quarantines the late result after restart and leaves no accepted output/obligation.
  This exercises the production decision service through a small test workflow with
  deterministic custody, not a paid provider session. The offline-cancel run stays
  `cancelling`; complete cancellation/terminal-result behavior is separately proven by
  the authenticated production-worker acceptance test. It is not a forced full-provider
  process/sandbox restoration claim. See `final-forced-restart.xml` and
  `forced-restart-proof.json` in the task-local evidence directory.
- The review regressions for unbound/nonexistent/cross-scope output references and native
  Claude aborted terminal reasons passed against PostgreSQL. All candidate references
  must be accounted for, and no extra reference gains accepted output evidence on replay.

- Repository Ruff, authoritative Mypy (620 source files), and Deptry. The first-pass
  `ty check` exited zero with 11 warnings; it is not a warning-free result.
- Documentation index check and knowledge validation (34 concept documents).
- Declared schema compilation/prompt/byte-validation/service tests: 57 passed. Final
  digest-guard, completion replay and retrieval selection: 85 passed. Final catalog seed
  and digest regression selection: 11 passed. Biotech provenance: eight passed; repaired
  browser/tooling selection: 23 passed. Selections overlap and must not be added.
- Real disposable PostgreSQL 17: final validation/retrieval selection four passed, including
  pending publication, interrupted validator, closed-pool recomposition, valid/invalid
  results, persisted criteria and exact lost-response replay without artifact re-read.
  Artifact custody bytes are deterministic fixtures; lifecycle/budgets/journals/roles are
  real. Scoped receipt paging, corruption rejection and cross-tenant denial are covered.
- Oversized Cursor/Claude terminal-frame PostgreSQL write/recomposition/reduction: six
  passed; existing PostgreSQL frame tests: five passed. Bounded facts/turn ordering: 14;
  long-history and continuation: 13. Component schema/upgrade/bounds selection: 36 passed.
- Authenticated local API acceptance **passed** in 84.88 seconds with common component
  1.3.0, real PostgreSQL 17, real local Temporal 1.32.0, production workers and deterministic
  Deep Agents/MCP. StageGraph (two operations), GoalDirected (four operations), and a
  StageGraph cancelled at its durable wait all returned durable typed results through the
  signed API. Controls, duplicate command delivery, scope checks and root/operation history
  replay passed. There were 35 deterministic model events and 131 dependency/sandbox
  warnings, no paid provider calls or skipped prerequisites. See the task-local
  `local-acceptance.md` report. Replay is not proof of a forced worker process crash.
- Terminal result integration: 29 focused tests cover both families, all four ledger
  outcomes, lost-save response/recomposition and historical patch behavior.
- Real local Temporal: 30 dispatch-recovery, continuation and historical replay tests
  passed with fixture providers. After the Human Gate workflow patch, the final replay plus
  retrieval selection passed 33 tests. This is not paid provider qualification.
- Deployment renderer: 14 tests, including AWS request-shape validation, passed.
- Linux/amd64 image built with digest-pinned Python 3.12.15 and uv 0.12.23, frozen lock and
  192 distributions. API and worker imports passed as UID 10001 with networking disabled,
  a read-only filesystem and no credentials. See [build evidence](../../../../../deployments/cloud_runtime/BUILD_EVIDENCE.json).
  This verifies packaging/imports, not configured process startup or a release image receipt.
  The final source comparison additionally checked all **620 installed Python files**
  byte-for-byte against `src/mission_control`; the image ID and source-tree hash are in
  the refreshed build evidence. No earlier image is being represented as final source.
  Final post-cancellation-fix image: `sha256:081cf7d500541f15d598afecc2289558f1172340363499cc526de035b92dde78`;
  source tree: `55645b1ce2c0a36b9da51c294d03013837831fa08b8f411d7e18740f1a5a7b14`.
- CRLF-aware `git diff --check` passed. Independent reviews completed; their identified
  required-output, Human Gate obligation and acceptance-action defects were corrected and
  included in the final focused regressions.

**Failed checks and their disposition:**

- The early verifier-preparation cancellation timeout was investigated separately from
  publication validation. A deterministic post-admission/pre-dispatch barrier reproduced
  the defect: accepted cancellation fenced cognition before Temporal delivery, then
  `operation_execution_rejected` failed the child. The application now emits typed
  `operation_cancellation_pending`; a new workflow patch waits durably for actual cancel
  delivery and invokes the existing authority-checked cancellation settlement. A failed
  activity already completed when delivery arrives also enters that settlement path.
  Unrelated activity failures and histories without the patch retain earlier behavior.
  The exact failing reproduction now passes with real PostgreSQL/Temporal and root,
  family and operation history replay (`admitted-cancel-race-before.xml` versus
  `admitted-cancel-race-after.xml`). No cancellation authority, binding, catalog or schema
  validation was relaxed; no new SQL or provider invocation is required for this fix.
- An additional settlement assertion initially counted a cancelled claim as `settled`.
  The journal deliberately stores it as `cancelled`; the regression now requires one
  completed executor claim, one cancelled verifier claim, two receipts and two settlements.
  An accidental `deptry .` invocation included package tests and reported dependency issues;
  the prescribed Makefile command, `deptry src`, passes on all 620 runtime files.
- Earlier broad failures are resolved and superseded by the complete green rerun above.
  The second run's receipt fingerprint and activity catalog failures were corrected with
  the canonical fingerprint helper and `mc.catalog.workflow-parity@1.0.2` (asset version 3).
  The subsequent 2,979-pass/two-failure run exposed new default Goal Directed fields in
  stable catalog bytes and a Cursor Retry-After test measuring fixture setup time. Default
  fields are now digest-neutral; the test uses the existing injected clock and checks
  exactly seven seconds. Both corrections are included in the final complete run.
- Every existing seed JSON remains unchanged. The new seed depends on frozen 1.0.1;
  generator integrity checks pass. No seed was applied to a live installation.
- Earlier failures from the browser digest, stale tooling path, missing terminal-result
  invocation and new acceptance-fixture assumptions are resolved. No integrity pin or
  authorization check was relaxed. The final real acceptance result supersedes its earlier
  failed attempts; their reports remain available as diagnostic history.
- `ruff format --check .` reports five files already dirty before this task:
  `docs/tools/agents_docs_index.py`, the Biotech live coordinator runner, the Scenario B live
  runner, `bootstrap/settings.py`, and `test_reviewed_capability_promotion.py`. They were not
  reformatted as unrelated work.

**Blocked / unrun:**

- No live cloud-provider execution, paid workflow proof, production persistence test, image
  push, cloud deployment or endpoint verification. Spending/security approvals and concrete
  operator assets remain unresolved as described above.
- The broad suite's 19 skips require an unconfigured Agent Server endpoint; its two expected
  failures belong to the existing reference-research run-control limitation.
- Four package seed database tests stopped at fixture setup because
  `MCDB_TEST_ADMIN_DSN_A` was not supplied to that selection. They are not reported as
  passed; the separate common-component and runtime PostgreSQL proofs above did run.
- General assessment/compound evaluators,
  new managed Codex/Claude adapters, complete trace/sandbox capture,
  paid-provider restore qualification and account-specific LangSmith
  entitlement verification remain incomplete. Full local Goal Directed schema-bound
  completion and delayed-publication cancellation now have signed-API qualification with
  production workers, real PostgreSQL custody/receipts and filesystem payloads. Cognition is
  deterministic; this does not qualify a paid provider or production object store.
  The owned process-loss proof covers the decision-service commit boundary, not every
  production worker activity or provider-native checkpoint restoration.

Current task-local evidence includes `cancel-race-final-broad.xml`, `cancel-race-final-acceptance.xml`,
`admitted-cancel-race-before.xml`, `admitted-cancel-race-after.xml`,
`cancel-race-image-proof.txt`, `multi-goal-broad.xml`, `multi-goal-final-acceptance.xml`,
`multi-goal-postgres-final.xml`, `multi-goal-image-proof.txt`,
`final-green-broad.xml`, `final-forced-restart.xml`,
`forced-restart-proof.json`, `third-runtime.xml`, `third-restart-postgres.xml`,
`second-pass-unit.xml`, `final-completion-unit.xml`,
`final-completion-postgres.xml`, `final-seed-and-digest.xml`,
`frame-recovery-postgres.xml`, `local-acceptance.md`, `fulfillment.md` and the prior-pass
XML under `.scratch/overnight-reliability/`. The provider/schema reports and preserved skill
tree are under `.scratch/provider-lifecycle-2026-10-11/`. Counts are separate runs and must
not be added. Detailed reports are local working evidence, not a production release receipt.
