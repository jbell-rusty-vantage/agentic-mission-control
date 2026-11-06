---
type: Proposal
title: "Fault tolerance and the error contract: one fault registry, vendor error families from Temporal, LangChain, LangGraph, Deep Agents and the provider SDKs, layered recovery and fallbacks, coordinator-selectable fault policies, and one precise error envelope across the API, MCP and CLI"
description: "Written 2026-10-23 at the owner's request, as a short diversion from provider consolidation. Audits how Mission Control fails today (no shared error module, nine overlapping failure vocabularies, the ADR-0011 retry classifier specified but not built, unlimited Temporal retry policies the spec forbids, a Deep Agents lane with no retry or fallback that reduces every provider error to its type name, four surfaces with four error shapes). Proposes the error module (a closed fault registry in the domain, a Fault value with position, causes and resolutions, one MissionControlError base), vendor mappers that import the Temporal, LangChain, LangGraph, Deep Agents, OpenAI and Anthropic error families, a recovery ladder with one owner per layer and a bounded attempt budget, declared fallbacks through LangChain middleware, the parts a coordinator may select and search (fault policies, profiles, fault cards, run fault reads), one error envelope rendered as problem+json, an MCP isError result and a CLI diagnostic, the observability that goes with it, work packages FT-0..FT-7 and decisions FT-D1..D22. Decides nothing."
tags: [mission-control, errors, fault-tolerance, retry, fallback, temporal, deep-agents, langchain, langgraph, observability, api, mcp, cli, proposal]
---

# Fault tolerance and the error contract

**Status: proposal, draft (2026-10-23).** Nothing in it is built. It decides nothing; §13 lists the
decisions FT-D1..D22 with a recommendation each. It is grounded in a read of `src/` on `main`
(`a7a8b0da`) and of the installed packages in `.venv` (temporalio 1.34.0, langchain 1.3.14,
langchain-core 1.5.3, langgraph 1.2.10, deepagents 0.7.5, langchain-openai 1.3.4,
langchain-anthropic 1.5.4, openai 2.44.0, anthropic 0.120.2, fastmcp 3.4.4, mcp 1.29.0). Where a
claim rests on something I could not verify, §14 says so.

It stays inside the system's invariants (root `AGENTS.md`): Temporal alone schedules; Deep Agents
is bounded operation cognition; reducers own lifecycle and settlement; the domain imports no
database, Temporal, FastAPI or provider SDK; the adapter never chooses a model the binding did not
name (`adapters/deep_agents/AGENTS.md`); application code never chooses a provider fallback
(`application/AGENTS.md`); retries, revisits, iterations, rounds and continuations are distinct
counters and only transient failures retry (ADR-0011).

## 0. The owner's words (verbatim, 2026-10-23)

> We need to divert from our workflow and provider consolidation path a little bit. We need to get
> started on the less sexy sides of software. Fault tolerance, error handling, fallbacks,
> hueristics, observability.
>
> 1. I need a proposal for an error module
> 2. We need to import and use the error families from temporal and from deep agents. The same
>    applies to other providers I am just constricting scope because we support a lot of providers.
> 3. We need to use langchain's / deep agents / langgraphs fault tolerance, errors, error recovery
>    and all of that now. You need to propose any parts of this that should be selectable /
>    searchable by the mission control coordinator agent. Should we allow fallback selections or
>    error behaviors to be configurable ?
> 4. PRECISE ERROR MESSAGING AND RESOLUTION PATHWAYS IF POSSIBLE across the api, mcp and cli. This
>    is a must.
>
> We want to really recover. We want to really use fallbacks and be fault tolerant. We want to use
> deep agents / langchains interfaces where applicable. We want to use temporal's errors and error
> recovery interfaces if applicable. We want to combine our internal system errors with provider
> specific errors and have a full system. Fault Tolerance, Graceful Recovery, Precise messaging,
> Helpful messaging.

| Section | Answers |
| --- | --- |
| §1 | The proposal in one page |
| §2 | How Mission Control fails today, with citations |
| §3 | Principles |
| §4 | The error module: layout, the fault registry, the Fault value, the base exception (owner item 1) |
| §5 | Vendor error families and their mappers: Temporal, LangChain/LangGraph/Deep Agents, OpenAI, Anthropic, the other lanes (owner item 2) |
| §6 | The recovery ladder: who retries what, fallbacks, graceful degradation, the attempt budget (owner item 3) |
| §7 | What the coordinator may select and search, and what it may not (owner item 3) |
| §8 | Precise messages and resolution pathways on HTTP, MCP, CLI and the stream (owner item 4) |
| §9 | Heuristics |
| §10 | Observability |
| §11 | Four worked failures, end to end |
| §12 | Work packages FT-0..FT-7 and where they meet the sprint sequence |
| §13 | Decisions FT-D1..D22 |
| §14 | Honest list |
| Appendix A | The first fault registry (about 70 codes) |

---

## 1. The proposal in one page

Mission Control has many careful local error decisions and no error *system*. Each router, each
MCP tool module, each lane and each workflow names failures in its own words, and those words
diverge across surfaces for the same failure (§2.5). The retry classifier the normative spec
requires was never built (§2.3), so Temporal retries what it is told to and the Deep Agents lane
never retries a model call at all (§2.4).

The proposal has five parts.

1. **One fault registry** (`domain/faults`). Every failure Mission Control can report has a stable
   code (`provider.rate_limited`, `run.stale_version`, `tool.invalid_arguments`) registered once
   with its family, its workflow failure class (the existing `OperationFailureClassV2`), its retry
   disposition (the nine ADR-0011 values, finally implemented), what the caller should do, its
   HTTP status, CLI exit code, Temporal retryability and category, a message template and its
   resolutions. A test refuses a code without a message and at least one resolution.
2. **Vendor mappers** (`adapters/faults`). The Temporal, LangChain-core, LangGraph, LangChain
   middleware, Deep Agents, OpenAI and Anthropic exception families are imported **only** there
   and classified **once**, at the boundary where the foreign exception is caught, into a `Fault`
   with sanitized causes (vendor, type, native code, HTTP status, request id; never raw text).
   Outbound, a `Fault` becomes a Temporal `ApplicationError` with `type=code`, the registry's
   `non_retryable`, `next_retry_delay` and `category`, so Temporal's own retry machinery obeys the
   classifier.
3. **A recovery ladder with one owner per layer** (§6). Provider SDK retries stay off. LangChain
   `ModelRetryMiddleware`, `ModelFallbackMiddleware`, `ToolRetryMiddleware` and
   `ToolErrorMiddleware` run inside the Deep Agents turn, wrapped by Mission Control so that they
   classify with the registry, charge an attempt budget, emit frames and never choose a model the
   binding did not name. Temporal activity retry covers lost workers and heartbeats. Semantic
   recovery (follow-up turn, revisit, StageGraph variant fallback, fork from a point, human gate)
   stays with the programs and reducers. Every layer is bounded; their product is bounded by one
   per-unit attempt budget.
4. **Configurable, within ceilings** (§7). Yes: fallbacks and error behaviours should be
   selectable, as a closed `fault_policy` block (or a named profile: `conservative`, `standard`,
   `resilient`) at mission, stage, agent and subagent scope, validated at compile, bounded by
   installation ceilings the coordinator can lower but never raise. Each policy knob and each fault
   code is a searchable card. The classifier, kernel retry policies, SDK retries and the
   effect-retry rule are not configurable.
5. **One error envelope** (§8), `mc.error.v1`: code, title, a one-sentence message naming what
   failed and where, the position (`unit_key`, `point_ref`, attempt), why (sanitized causes),
   whether a retry is safe and when, and ordered resolutions rendered as a `missionctl` command, an
   HTTP request and an MCP tool call. HTTP serves it as RFC 9457 `application/problem+json`; MCP as
   a tool result with `isError: true` and the envelope as structured content; the CLI as a
   three-line diagnostic on stderr (the envelope on stdout with `--json`); Socket.IO as
   `stream_error`. Same failure, same code, same resolutions, everywhere.

Nothing here needs the Deep Agents upgrade (sprint A): every middleware named is in the installed
langchain 1.3.14. FT-0 and FT-1 touch no agent configuration and can run now; the middleware and
the policy block belong with sprint B's agent configuration language; observability with sprint F
(§12).

---

## 2. How Mission Control fails today

### 2.1 No error module; nine vocabularies

Failure is named in at least these closed or semi-closed vocabularies, none derived from another:

| Vocabulary | Values | Where |
| --- | --- | --- |
| `CoordinatorErrorCode` | 28 UPPER codes; the only base with `retryable` and `details` | `domain/coordinator/errors.py:9-37,40` |
| `RunControlError` family | `code` + `status_code` class attributes, 7 subclasses | `domain/policies/errors.py:4` |
| `ControlPlaneError` family | `code` + `status_code`, `decisions` on compile rejection | `domain/authoring/errors.py:4` |
| `MissionControlRejected` | free `code` (unauthorized, unavailable, stale_version, ...) + `frontier` | `contracts/contracts.py:372-380` |
| `ForkRejectionCode`, `StreamErrorCode`, `WORKSPACE_ERROR_CODES`, `PackFailureCode` | each closed, each local | `domain/policies/forks.py:69-94`, `domain/subscriptions/streams.py:53-66`, `application/workspaces/errors.py:30-47`, `domain/context/packet.py:136` |
| `OperationFailureClass` / `V2` | 12 / 13 workflow failure classes | `domain/graph_runtime/kernel.py:20-48` |
| Frame `FailureClass` | provider_error, timeout, capacity, cancelled_by_command, infrastructure (never assigned), outputs_missing | `domain/frames/facts.py:35-41`, `application/frames/reducer.py:215-247` |
| `LimitKind` | rate_limited, quota_exhausted, overloaded, auth_failed, billing_unavailable, ... | `domain/execution/usage_admission.py:33-42` |
| Two retry vocabularies | `retry_class` safe / claim_then_reconcile / non_retryable (journal, SQL CHECK) and `retryability` never / safe / reconcile | `domain/execution/journal.py:69`, `application/execution/operations/operation_executor.py:59-89` |

Plus about 60 `ApplicationError` type strings in the Temporal adapter (§2.3), the settlement's
four inline `failure_code` values, and the base classes `WorkspaceError`, `RemoteSessionError`,
`ProviderTransportError` and the bare `ValueError`/`RuntimeError` families of
`domain/execution/errors.py`. Code case is mixed: mostly snake_case, some UPPER
(`IDEMPOTENCY_CONFLICT` at `interfaces/http/missions.py:269`, `CURSOR_EXPIRED` at
`interfaces/http/transcript.py:171`, `PREREQUISITES_UNMET`).

### 2.2 Persistence keeps the type, not the reason

- The operation boundary catches every exception (`operation_execution.py:2075`) and settles with
  `failure_code` ∈ {`budget_exceeded`, `unsupported_runtime_policy`, `runtime_failed`,
  `preparation_failed`} and `failure_message = "<ErrorType> at governed operation boundary"`
  (`:2115-2134`, `:3117-3120`). The comment is right that provider text must not be persisted; the
  consequence is that an OpenAI 429, a 401 and a context overflow all settle as `runtime_failed`
  with a class name.
- There is no incident table. Failures land in `operation_settlement.failure_code` (free text),
  `operation_technical_attempt`, `runtime_execution_attempt.provider_detail`,
  `attempt.failure_class` (free text), `reconciliation_case`, `coordinator_audit_event.error_code`
  and free-text `mission_event.event_type` values (`turn.failed`, `tool.failed`, ...).

### 2.3 Temporal: the classifier was never built, and some retries are unlimited

- **The ADR-0011 classifier is not implemented.** RUNTIME-CONTRACTS line 90 requires a retry
  classifier over `transient_transport`, `worker_lost`, `provider_busy`, `invalid_input`,
  `authority_denied`, `quality_rejected`, `budget_exhausted`, `effect_uncertain`,
  `checkpoint_invalid`, with only the first three retrying, persisted separately from the workflow
  failure class. None of `transient_transport`, `provider_busy` appears in `src/`; `worker_lost`
  only as a frame code (`domain/frames/lifecycle.py:55`). The Deep Agents output audit says the
  same (`AUDIT-OUTPUT-TRANSFER-2026-10-22.md:329,669`).
- **Unlimited retry exists although the spec forbids it** ("No unlimited retry: installed Temporal
  `RetryPolicy.maximum_attempts=0` means unlimited"): `operation.cancel`
  (`workflows/operation.py:186-191`, `maximum_attempts=0`), session retention delete
  (`workflows/session_retention.py:24-29`), linked-run binding and observation resolution
  (`linked_run_workflow.py:92,339`), `artifact_workflow.py:22,39`, and two policies with no attempt
  limit at all (`mission_run.py:41` materialize result, `watchers.py:130` evaluate). Some of these
  are deliberate (a cancel must eventually land); the spec still wants a bound plus an escalation.
- **Temporal's own error interfaces are half used.** `non_retryable_error_types` appears once
  (`goal_directed.py:1941-1946`). `next_retry_delay` twice (`activities/lane_turn.py:165,176`).
  `ApplicationErrorCategory` (installed, `temporalio/exceptions.py:119`, `BENIGN` "emits DEBUG level
  logs and does not record metrics") never. About twenty `ApplicationError`s carry no `type`
  (`goal_directed.py:313,354,447,...`, `stagegraph.py:292,298,383,...`), two of them retryable.
  `TerminatedError`, `ServerError`, `RetryState`, `TimeoutType` and `WorkflowUpdateFailedError`
  are never inspected; `linked_run_workflow.py:242-255` classifies a `ChildWorkflowError` by
  walking cause **class names** for "Cancel" and "Timeout".
- **What works and should be kept:** `provider_capacity_limit` carries a `ProviderLimitSignal` in
  `details` and the operation workflow waits for the limit to reset on a durable timer instead of
  retrying (`operation.py:153-164,676-682,886-924`); `session_owned_elsewhere` uses
  `next_retry_delay` = lease expiry; activities distinguish a cancel from a worker shutdown
  (`operation_activities.py:222-230`); operation workflows complete with a disposition instead of
  failing (`operation.py:279-281`). These are the patterns the module generalizes.

### 2.4 Deep Agents: no retry, no fallback, the type name only

- The lane's middleware is `FenceStopMiddleware`, `HookScriptMiddleware`,
  `ObservedSummarizationMiddleware`, catalog middleware by exact digest (none registered in
  production: `deployment_composition.py:463-476`), the governed async-subagent middleware and
  `BudgetStopMiddleware` (`materializer.py:352-366`, `adapter.py:263-287`). No
  `ModelRetry`, `ModelFallback`, `ToolRetry`, `ToolError`, call-limit middleware,
  `handle_tool_errors`, `ToolException`, `GraphRecursionError` or `recursion_limit` handling exists
  in `src/`.
- `ChatOpenAI(..., max_retries=0)` (`materializer.py:257-261`): the SDK never retries. That is
  correct for accounting (every paid attempt is observed) and leaves no retry anywhere inside a
  turn; the only retry is Temporal re-running `operation.execute` (`maximum_attempts=3`,
  `operation.py:1090`), which resumes from the latest checkpoint.
- The catch-all at `adapter.py:549-587` logs the type, writes `graph.error` and a
  `graph.run_result{status: error, error_type}` frame, and raises
  `RuntimeInvocationFailure(type(error).__name__, ...)`. The provider's status, code, request id
  and `Retry-After` are lost at that line.
- `create_agent` builds its `ToolNode` with the default `handle_tool_errors`
  (`langchain/agents/factory.py:1061-1065`), which converts only `ToolInvocationError` (bad
  arguments) into an error `ToolMessage` and re-raises everything else
  (`langgraph/prebuilt/tool_node.py:383`). A tool that raises ends the turn.
- **Declared but never consumed:** `ModelPolicy.fallback_models: tuple[str, ...] = ()`
  (`domain/execution/contracts.py:161`) and the StageGraph `fallback_sequence` of operation
  variants (`domain/authoring/contracts.py:383-410`, validated, read nowhere else). The placement
  profile pins `silent_fallback: Literal[False]` (`contracts.py:1172`). The shape of the answer is
  already in the contracts.
- Only an OpenAI model factory exists (`DeepAgentModelComponent.provider: Literal["openai"]`,
  `contracts.py:574-577`; program decision D5 proposes a provider-neutral factory). Cross-provider
  model fallback waits for it; same-provider fallback does not.

### 2.5 Four surfaces, four shapes, divergent answers

| Surface | Shape today | Source |
| --- | --- | --- |
| HTTP (public `bootstrap/api.py`) | no exception handlers; each router raises `HTTPException`; body is `{"detail": {...}}` or `{"detail": "..."}` (about 50 string sites); FastAPI default 422 for validation; not problem+json | `interfaces/http/mission_control.py:275-316`, `run_control.py` (33 string sites), `middleware/body_limit.py:52` |
| MCP | `{"ok": false, "schema_version": "1", "correlation_id", "error": {code, message, retryable, details}}` returned as a **successful** tool result, never `isError`; signals MCP uses `{"ok": false, "error": {code, status}}` | `interfaces/mcp/coordinator_server.py:197-254`, `signal_tools.py:38-39` |
| CLI | prints the HTTP body to **stdout**; local errors `{"error": str(exc)}` to stderr; exit codes 0/2/3/4/5/6 from the status, but `main.py:1049-1053` exits 1 with `response.text[:500]`; `--json` has no error mode | `interfaces/cli/exits.py:9-18`, `main.py:1504-1538` |
| Socket.IO | `stream_error` with `StreamErrorCode` (12 values) | `domain/subscriptions/streams.py:53-66` |

The same failure answers differently: `RunLaunchRejected` is 409-or-422 on one router, always 409
on two others, and `CONFLICT` with `retryable` dropped on MCP (`mission_tools.py:289-292`);
`ForkRejected` keeps its code on HTTP and becomes `CONFLICT` on MCP (`run_control_tools.py:82-91`);
a missing scoped service is 503 on HTTP and `FORBIDDEN` on MCP (`run_control_tools.py:125-135`);
`CursorExpired` is 409 on HTTP, `INVALID_ARGUMENT` on MCP and exit 2 (not 4) on the CLI; HTTP 529
is a capacity code in `lifecycle.py` but `PROVIDER_ERROR` in the reducer's `CAPACITY_CODES`
(`reducer.py:99`). Raw `str(exc)` reaches users from about 30 sites
(`interfaces/http/catalog.py:232-306`, `missions.py:126,162,165,302`, `transcript_tools.py:164-167`,
...).

### 2.6 Observability

`temporalio[opentelemetry]`, `opentelemetry-sdk` and the Prometheus exporter are dependencies
(`pyproject.toml:41-55`), but no `TracingInterceptor`, `interceptors=`, `TelemetryConfig` or
`PrometheusConfig` appears in `src/`. LangSmith tracing is configured from settings
(`adapters/langsmith/tracing.py`). The Mission Transcript and provider frames (ADR-0028, ADR-0054)
are the replayable record and already have an `error` frame kind; they are the right place for
fault evidence, and today they carry the type name only.

---

## 3. Principles

- **P1. One fault, one code.** Every reportable failure has one stable code from one registry.
  Surfaces render codes; they never invent them.
- **P2. Classify once, at the catch.** The adapter that catches a foreign exception classifies it,
  with the vendor's typed attributes (status, code, `retry_after`, `TimeoutType`, `RetryState`).
  Nothing downstream re-classifies by class name or message text.
- **P3. Two axes, persisted separately** (RUNTIME-CONTRACTS line 90): the workflow failure class
  (`OperationFailureClassV2`) says *what kind of failure*; the retry disposition (the nine ADR-0011
  values) says *whether a technical retry is permitted*.
- **P4. Effects decide retry safety; exceptions only propose it.** A technical retry happens only
  when the disposition is `transient_transport`, `worker_lost` or `provider_busy` **and** the
  attempt's effect retry class (`retry_class`: safe / claim_then_reconcile / non_retryable, already
  in the journal) allows it. `effect_uncertain` reconciles; it never retries.
- **P5. One owner per recovery layer, one budget across them.** No two layers retry the same fault
  class (no retry amplification); every layer is bounded; their product is bounded by a per-unit
  attempt budget (§6.6).
- **P6. Fallback is declared, never chosen.** A fallback model, tool or lane is named in the
  compiled binding, admitted, budgeted and credentialed before the run starts; using it is
  recorded as a frame and a wake. No runtime lookup, no silent fallback (`silent_fallback` stays
  `False`).
- **P7. Recover forward, gracefully.** Prefer, in order: retry the transient call; hand the model
  a precise error it can act on; fall back to a declared alternative; settle with a governed
  outcome and offer resolutions (follow-up turn, revisit, variant, fork from the last good point,
  human gate). Never ask for more budget as a recovery (ADR-0011).
- **P8. A precise message answers five questions:** what failed, where (position), why (sanitized
  cause), whether retrying is safe and when, and what to do next (ordered, executable
  resolutions).
- **P9. Never leak.** Provider text, exception strings, stack traces and secrets stay in the
  redacted worker log (`install_log_redaction`). Envelopes, frames and settlements carry the
  registry's rendered message, typed details, and sanitized causes. An unclassified exception is
  `internal.unexpected` with a fault id the operator can grep.
- **P10. Use the vendor's interfaces; own the policy.** Temporal's `ApplicationError`,
  `RetryPolicy`, `next_retry_delay` and `category`; LangChain's retry, fallback, tool-error and
  limit middleware; LangGraph's typed errors; the SDKs' typed exceptions. Mission Control
  contributes the classifier, the bounds, the evidence and the messages, through public
  interfaces (ADR-0005: extend, do not fork).

---

## 4. The error module (owner item 1)

### 4.1 Layout

Placed to respect the dependency rule (domain imports no SDK; interfaces call application):

```text
src/mission_control/
  domain/faults/                    pure: no SDK, no I/O
    codes.py                        FaultCode registry (Appendix A), FaultFamily, ClientAction
    disposition.py                  RetryDisposition (the nine ADR-0011 values), retry rule (P4)
    fault.py                        Fault, FaultCause, FaultPosition, Resolution (value objects)
    errors.py                       MissionControlError(Exception) carrying a Fault
    messages.py                     message templates and the renderer (no surface specifics)
  contracts/faults.py               mc.error.v1 envelope and mc.fault.v1 record (public schema)
  application/faults/
    recorder.py                     records a Fault: frame, mission_event, metric, log (port-based)
    resolutions.py                  resolution builders that need application state (run, point)
  adapters/faults/                  the ONLY place vendor error families are imported
    temporal.py                     from_temporal(exc) -> Fault; to_application_error(fault)
    langchain.py                    langchain_core, langchain.agents.middleware, langgraph.errors
    openai.py, anthropic.py         SDK exception families, with provider_auth/limits.py reused
    httpx.py                        transport errors from our own HTTP clients
  adapters/deep_agents/fault_middleware.py   governed retry / fallback / tool-error middleware (§6)
  interfaces/faults/
    http.py                         problem+json renderer and the FastAPI exception handlers
    mcp.py                          CallToolResult(isError=True, structuredContent=envelope)
    cli.py                          stderr diagnostic, --json envelope, exit code
```

The existing lane tables (`adapters/remote_session/errors.py` `ErrorRule`, `adapters/cursor/bridge.py`
`provider_error`, the Claude and Codex capacity classifiers) are good precedents; they move onto the
registry lane by lane (FT-7), each returning a `Fault` instead of a lane-local exception class.

### 4.2 The registry entry

One row per code. The registry is a Python table (it must be importable by the domain and checked
by tests), and a generator writes the reference page `docs/reference/faults.md` and the fault cards
from it (§7.3). Proposed fields:

| Field | Meaning | Example (`provider.rate_limited`) |
| --- | --- | --- |
| `code` | `family.reason`, snake case, stable forever | `provider.rate_limited` |
| `family` | One of the families below | `provider` |
| `failure_class` | `OperationFailureClassV2` value (existing) | `transient_provider_failure` |
| `retry` | `RetryDisposition` (ADR-0011) or `none` for pure request faults | `provider_busy` |
| `client_action` | What the caller should do: `none`, `retry`, `retry_after`, `refresh_then_retry`, `fix_request`, `authorize`, `configure`, `wait`, `reconcile`, `revise`, `escalate` | `retry_after` |
| `http_status` | Status when it answers a request | 429 |
| `exit_code` | `missionctl` exit code | 7 (FT-D12) or 5 today |
| `temporal` | `non_retryable` and `category` (`BENIGN` for expected outcomes) | retryable, `UNSPECIFIED` |
| `frame_class` | The frame `FailureClass` it projects to | `capacity` |
| `title` | Short, fixed | "Provider rate limit reached" |
| `message` | Template over typed details | "{provider} rate limited {model} for {unit}; retry after {retry_after_s}s." |
| `resolutions` | Ordered resolution kinds (§4.4) | `automatic_retry`, `wait`, `fork_with_fallback_model` |
| `legacy` | Codes it replaces, for the one-release alias | `rate_limited`, `RATE_LIMITED`, `429` |
| `since` | Release that introduced it | `1.5.0` |

**Families** (where the failure originates): `request` (shape, size, validation), `auth`
(authentication, permission, scope), `state` (not found, conflict, stale version or generation,
idempotency), `admission` (prerequisites, compile, placement, budget admission), `capability`
(catalog, skills, MCP servers, bundles, drift), `provider` (the vendor's API: rate, quota,
overload, outage, auth, content filter), `model` (the model's behaviour: context overflow, output
invalid, length, refusal), `tool` (tool argument, execution, timeout, denial, error loop),
`runtime` (worker lost, heartbeat, timeouts, sandbox, workspace, step limit), `workflow`
(Temporal: activity, child, cancel, terminate, timeout, update), `effect` (uncertain external
effect, reconciliation), `budget` (governor exhaustion), `quality` (rejection by verifier or
review), `checkpoint` (lineage, resume, fork seed), `internal` (invariant violations and
unclassified exceptions).

### 4.3 The Fault value

A sketch, not code (`Contract` is the repository's frozen pydantic base):

```python
class FaultCause(Contract):          # sanitized; never exception text
    source: Literal["mission_control", "temporal", "langchain", "langgraph",
                    "deepagents", "openai", "anthropic", "httpx", "lane"]
    type: str                        # "RateLimitError", "ActivityError", "GraphRecursionError"
    native_code: str | None = None   # "rate_limit_exceeded", "insufficient_quota", "overloaded_error"
    http_status: int | None = None
    request_id: str | None = None    # the vendor's request id: the operator's ticket to support
    retry_state: str | None = None   # Temporal RetryState name, when present
    timeout_type: str | None = None  # Temporal TimeoutType name, when present

class FaultPosition(Contract):       # CS-D5's additive position fields
    mission_id: str | None = None
    run_id: str | None = None
    unit_key: str | None = None      # "stage:draft", "goal:iteration:2"
    point_ref: str | None = None     # last good cognition point, when one exists
    attempt: int | None = None
    lane: str | None = None
    provider: str | None = None
    model: str | None = None
    tool: str | None = None

class Fault(Contract):
    fault_id: UUID                   # grep key across envelope, frame, event, log, metric exemplar
    code: FaultCode
    details: Mapping[str, str | int | float | bool]   # typed per code, bounded
    position: FaultPosition
    causes: tuple[FaultCause, ...] = ()               # outermost first, at most 4
    retry_after_s: float | None = None
    occurred_at: datetime
    correlation_id: str | None = None
    # derived from the registry, never set by callers:
    # family, failure_class, retry, client_action, title, message, resolutions
```

### 4.4 Resolutions

A resolution is a typed, executable next step, rendered per surface from the coordinator-surface
grammar (`missionctl <noun> <verb> TARGET`, CS-D1). Proposed kinds:

| Kind | Meaning | Rendered as (examples; spelling follows CS-D1..D14) |
| --- | --- | --- |
| `automatic_retry` | Mission Control is already retrying; nothing to do | "Mission Control retries 2 more times (next in 20 s)" |
| `wait` | Retry after a time or a capacity reset | `missionctl run wait RUN --until settled` |
| `refresh_then_retry` | Read the current version, then resend | `missionctl run inspect RUN` then the same command with `--expected-version N` |
| `fix_request` | A field is wrong; points at it | `field_errors[]` with JSON pointer, code, message, allowed values |
| `authorize` / `configure` | Missing permission, secret, binding or prerequisite | `missionctl owner prerequisites MISSION`; the secret reference name, never its value |
| `reconcile` | An effect or unit is uncertain | `missionctl run reconcile RUN --unit UNIT` |
| `fork_from_point` | Restart from the last good cognition point | `missionctl run fork RUN --point POINT` |
| `fork_with_fallback_model` / `_lane` | Fork with a configuration patch naming an admitted alternative (CO-D16) | `missionctl run fork RUN --point POINT --patch model=gpt-6-luna` |
| `revise` | The mission itself must change (revision) | `missionctl mission revise MISSION` |
| `escalate` | A human must decide | the human task id and `missionctl task show TASK` |
| `report` | A defect: give the operator the fault id | "Report fault 0193... to the operator" |

Each resolution carries `safe: bool` (repeats no external effect), `requires` (permissions), and
the three renderings (`cli`, `http`, `mcp`). Resolutions that need run state (the last good
point, the admitted fallback) are built in `application/faults/resolutions.py`; a resolution that
cannot be built is omitted, never guessed.

### 4.5 One base exception, no big-bang rename

`MissionControlError(Exception)` carries a `Fault`. The existing bases re-base onto it and keep
their names and attributes for one release: `RunControlError`, `ControlPlaneError`,
`CoordinatorDomainError`, `MissionControlRejected`, `WorkspaceError`, `RunLaunchRejected`,
`ForkRejected`, `RemoteSessionError`, `RuntimeInvocationFailure`. Each subclass declares its
registry code as a class attribute (`code = FaultCode.RUN_STALE_VERSION`), and its old `code`
string becomes the `legacy` alias. `ProviderTransportError(OSError)` is replaced by a `Fault` with
family `provider`.

---

## 5. Vendor error families and their mappers (owner item 2)

The mappers are pure functions in `adapters/faults/`: `classify(exc, position) -> Fault`. Each
walks the cause chain (`__cause__`, Temporal `.cause`) outermost-first, classifies on typed
attributes, records at most four causes, and returns `internal.unexpected` for anything it does not
recognise (never a retryable default; LangGraph's own `default_retry_on` returns `True` for unknown
exceptions, which is the wrong default for paid calls).

### 5.1 Temporal (`temporalio.exceptions`, `temporalio.client`, `temporalio.service`)

**Inbound** (something Temporal raised at us):

| Temporal | Classified as | Notes |
| --- | --- | --- |
| `ApplicationError(type=T)` where `T` is a registry code | that code | Round trip: details carry the original `mc.fault.v1` |
| `ApplicationError(type=T)` with a legacy type string | the code its `legacy` alias names | For the one-release window |
| `ActivityError` | the classification of `.cause`; `retry_state` recorded | `MAXIMUM_ATTEMPTS_REACHED` adds `workflow.retries_exhausted` as the outer cause |
| `ChildWorkflowError` | the classification of `.cause` | Replaces the class-name walk at `linked_run_workflow.py:242-255` |
| `CancelledError` | `workflow.cancelled` | `BENIGN` |
| `TimeoutError(type=HEARTBEAT)` | `runtime.heartbeat_lost` (`worker_lost`) | Retryable |
| `TimeoutError(type=START_TO_CLOSE)` | `runtime.activity_timeout` (`transient_transport`) | Retryable within the policy |
| `TimeoutError(type=SCHEDULE_TO_CLOSE / SCHEDULE_TO_START)` | `runtime.deadline_exceeded` / `runtime.no_worker` | Not retryable; the second names the task queue in details |
| `TerminatedError` | `workflow.terminated` | Operator action; `escalate` |
| `ServerError` | `workflow.server_error` | `transient_transport` unless `non_retryable` |
| `WorkflowAlreadyStartedError` | `state.workflow_already_started` | Handled by submission (`submission.py:175-198`); never a user fault when the root binding matches |
| `client.WorkflowFailureError` | the classification of `.cause` | |
| `client.WorkflowUpdateFailedError` | the classification of `.cause` | Today uncaught (`boundary_commands.py:93-166`) |
| `service.RPCError(status=...)` | `NOT_FOUND` → `state.not_found`; `UNAVAILABLE`/`DEADLINE_EXCEEDED` → `runtime.temporal_unavailable`; `PERMISSION_DENIED`/`UNAUTHENTICATED` → `auth.temporal_denied`; `RESOURCE_EXHAUSTED` → `runtime.temporal_throttled` | Today only NOT_FOUND is mapped |

**Outbound** (`to_application_error(fault)`):

```python
ApplicationError(
    fault.message,                      # the rendered, safe message
    fault.to_record(),                  # details[0]: mc.fault.v1, so the workflow and the next
                                        # activity read a Fault, not a string
    type=fault.code,                    # what RetryPolicy.non_retryable_error_types matches
    non_retryable=not registry[fault.code].temporal_retryable,
    next_retry_delay=timedelta(seconds=fault.retry_after_s) if fault.retry_after_s else None,
    category=ApplicationErrorCategory.BENIGN if registry[fault.code].expected
             else ApplicationErrorCategory.UNSPECIFIED,
)
```

**Retry policies from the registry.** A `RetryProfile` per activity class (lane turn, lane control,
operation execute, cancel, reconcile, projection, retention) lives in the pinned execution profile
RUNTIME-CONTRACTS asks for (maximum attempts, initial and maximum interval, multiplier, timeouts,
total deadline). Its `non_retryable_error_types` is generated: every registry code whose retry
disposition is not one of the three transient values. Unlimited policies get bounds plus an
escalation: `operation.cancel` keeps retrying for a bounded schedule-to-close (proposed 24 h), then
records `effect.cancel_unconfirmed` and opens a reconciliation case, instead of retrying forever
(FT-D6). Every untyped `ApplicationError` gets a registry code (FT-1).

**Category.** Expected governed outcomes (`budget.exhausted`, `run.stale_version`,
`workflow.cancelled`, `provider.capacity_wait`, `goal.paused`) raise with `BENIGN`, so Temporal
logs them at DEBUG and records no failure metric; Mission Control's own metrics (§10) count them by
code instead. Defects stay `UNSPECIFIED` and alert.

### 5.2 LangChain, LangGraph and Deep Agents

| Family (import path) | Exception | Classified as |
| --- | --- | --- |
| `langchain_core.exceptions` | `ContextOverflowError` (and `AnthropicContextOverflowError`, `OpenAIContextOverflowError`, `OpenAIAPIContextOverflowError`) | `model.context_overflow` (`invalid_input`; recovery: compact, then a declared larger-context fallback) |
| | `OutputParserException` | `model.output_invalid` (`quality_rejected`; recovery: follow-up turn per `MissingOutputPolicy`) |
| `langchain_core.tools` | `ToolException`, `ToolInvocationError` | `tool.failed`, `tool.invalid_arguments` (returned to the model, §6.3) |
| `langgraph.errors` | `GraphRecursionError` | `runtime.step_limit` (governed outcome `no_progress`) |
| | `InvalidUpdateError`, `EmptyInputError`, `TaskNotFound` | `internal.graph_invariant` (defect) |
| | `NodeTimeoutError`, `NodeCancelledError` | `runtime.node_timeout`, `workflow.cancelled` |
| | `GraphInterrupt`, `NodeInterrupt`, `GraphBubbleUp`, `ParentCommand` | **not faults**: control flow; must never be caught by a fault handler |
| `langchain.agents.middleware` | `ModelCallLimitExceededError`, `ToolCallLimitExceededError` | `budget.model_calls_exhausted`, `budget.tool_calls_exhausted` |
| `deepagents` | `SubagentErrorEvent`, `TaskEvent{status: error, timeout, cancelled}` on the custom stream | `tool.subagent_failed`, `tool.subagent_timeout`, `workflow.cancelled`, with the child's own fault as cause when it has one |
| `langgraph_sdk` (async subagents) | `APIStatusError` 404 / 409 | already mapped to observations (`async_subagents.py:281,313,465,490`); 5xx → `provider.agent_server_unavailable` |

The rule for `GraphBubbleUp` matters: the lane's catch-all (`adapter.py:549`) must re-raise control
flow untouched, and every new middleware's `retry_on` must exclude it.

### 5.3 Provider SDKs

Classification uses the SDK's typed attributes (`status_code`, `body.error.code`,
`response.headers["retry-after"]`, `request_id`), reusing `adapters/provider_auth/limits.py`
(which already produces `LimitKind`) rather than adding a second classifier.

| OpenAI (`openai._exceptions`) | Anthropic (`anthropic._exceptions`) | Code | Disposition |
| --- | --- | --- | --- |
| `APIConnectionError` | `APIConnectionError` | `provider.connection_failed` | `transient_transport` |
| `APITimeoutError` | `APITimeoutError`, `DeadlineExceededError` | `provider.timeout` | `transient_transport`, **spend uncertain** (§6.2) |
| `RateLimitError` with code `rate_limit_exceeded` | `RateLimitError` | `provider.rate_limited` | `provider_busy`, honours `Retry-After` |
| `RateLimitError` with code `insufficient_quota` | billing errors | `provider.quota_exhausted` | `budget_exhausted`; never retried (a 429 is not always transient) |
| — | `OverloadedError` (529) | `provider.overloaded` | `provider_busy` (fixes the 529 split in §2.5) |
| `InternalServerError` (5xx) | `InternalServerError`, `ServiceUnavailableError` | `provider.unavailable` | `transient_transport` |
| `AuthenticationError` | `AuthenticationError` | `provider.auth_failed` | `authority_denied`; `configure` names the secret reference |
| `PermissionDeniedError` | `PermissionDeniedError` | `provider.permission_denied` | `authority_denied` |
| `NotFoundError` | `NotFoundError` | `provider.model_not_found` | `invalid_input` |
| `BadRequestError` (context length) | `BadRequestError` (prompt too long) | `model.context_overflow` | via `ContextOverflowError` above |
| `BadRequestError`, `UnprocessableEntityError` | `BadRequestError`, `UnprocessableEntityError` | `provider.request_rejected` | `invalid_input` |
| — | `RequestTooLargeError` | `provider.request_too_large` | `invalid_input` |
| `ConflictError` | `ConflictError` | `provider.conflict` | `transient_transport`, one retry |
| `ContentFilterFinishReasonError` | refusal stop reason | `model.content_filtered` | `quality_rejected` |
| `LengthFinishReasonError` | `max_tokens` stop reason | `model.output_truncated` | `quality_rejected`; recovery: follow-up turn |

### 5.4 The other lanes

One at a time, like provider consolidation (FT-7). Each already has a table to convert rather than
invent: `remote_session/errors.py:89-112` (`ErrorRule`: 429, 401/403, 404, 410), with the
`openai_agents` and `anthropic_managed` additions (409 `SessionBusy`, `AgentVersionConflict`);
`cursor/bridge.py:37-96` (rate limit, auth, transient, configuration rejected, archived agent);
`claude/session.py:313-389` (`ProcessError`, `TimeoutError`, rate-limit info); `codex/harness.py`
(`AppServerError` → `limit_signal_from_rpc_error`, `ErrorNotification`). Lane-specific codes are
allowed (`lane.cursor.agent_archived`) when no general code fits, and still carry a general family
and disposition.

---

## 6. The recovery ladder (owner item 3)

### 6.1 Who retries what

| Layer | Mechanism | Handles | Bound (proposed default) | Owner |
| --- | --- | --- | --- | --- |
| L0 | Provider SDK client retry | nothing | `max_retries=0`, kept | Materializer |
| L1 | `ModelRetryMiddleware`, wrapped (§6.2) | `transient_transport`, `provider_busy` on a model call | 2 retries, 1 s→20 s jittered, `Retry-After` honoured up to the cap | Deep Agents lane |
| L2 | `ModelFallbackMiddleware`, wrapped (§6.4) | L1 exhausted, `provider.unavailable`, `provider.overloaded`, `model.context_overflow`, optionally `provider.auth_failed` | the declared chain only | Deep Agents lane |
| L3a | `ToolErrorMiddleware` / `handle_tool_errors` (§6.3) | recoverable tool faults returned to the model as a precise error | per-tool error-loop cap (§9) | Deep Agents lane |
| L3b | `ToolRetryMiddleware`, wrapped | transient faults of tools whose card says `idempotent` | 2 retries | Deep Agents lane |
| L4 | Durable capacity wait (exists) | `provider_busy` beyond L1's cap, quota windows | the limit reset, within the run deadline | Operation workflow (`operation.py:886-924`) |
| L5 | Temporal activity retry | `worker_lost`, heartbeat loss, start-to-close timeout; resumes from the latest checkpoint (RRM-008) | 3 (`operation.execute`), 5 (`lane.turn`), from the `RetryProfile` | Temporal adapter |
| L6 | Semantic recovery: follow-up turn, revisit, iteration, StageGraph variant `fallback_sequence`, continuation, fork from a point, human gate | quality, output, exhausted lower layers | the program's own counters (ADR-0011) | Programs and reducers |
| L7 | Reconciliation | `effect_uncertain`, `in_doubt` units | the reconciliation case | Recovery |

Two rules keep the ladder honest. **No layer retries a fault another layer owns:** L1 handles a
429 inside the turn; if it gives up, the fault rises with `non_retryable` set for L5, because L4
(not L5) is the next owner of `provider_busy`. **LangGraph node `RetryPolicy` is not used:**
`create_agent` and `create_deep_agent` expose no node retry parameter, it would duplicate L1, and
Temporal's LangGraph plugin rejects it.

### 6.2 Model retries inside the turn

The stock `ModelRetryMiddleware(max_retries, retry_on, on_failure, backoff_factor, initial_delay,
max_delay, jitter)` is the mechanism; Mission Control wraps it (`GovernedModelRetryMiddleware`,
a subclass through the public `AgentMiddleware` interface) to add:

- `retry_on` = the registry classifier: retry only `transient_transport` and `provider_busy`;
  never `GraphBubbleUp`, never `invalid_input`, never `provider.quota_exhausted`.
- `on_failure="error"`, always. `"continue"` returns an error `AIMessage` the graph treats as the
  model's answer, which would settle a broken turn as completed.
- **Spend-uncertain retries are bounded separately.** A connection refused or a 429/529 is not
  billed; a read timeout may be. RUNTIME-CONTRACTS: "Technical retry is not a blanket model rerun
  after an ambiguous paid request." Proposal: at most one retry after `provider.timeout`, charged
  to the budget as an estimated attempt and recorded with `spend: uncertain` on the frame
  (FT-D9).
- A `model_retry` frame per retry (code, attempt, delay, request id) so the Transcript shows it.
- It is a `wrap_model_call` middleware: it adds no graph node, so step and checkpoint numbering do
  not move (the reason the turn stops are written the same way, `deep-agents-lane.md`).
- It sits **inside** the fence and budget stops in the stack, so a cancelled or exhausted turn
  never retries.

### 6.3 Tool errors the model can act on

Graceful recovery inside a turn mostly means telling the model precisely what went wrong. Proposal:
attach `ToolErrorMiddleware(on_error=...)` (installed, opt-in) with a Mission Control handler that:

- classifies the exception; for codes whose `client_action` is `fix_request` or `retry`
  (`tool.invalid_arguments`, `tool.not_found`, `tool.rejected`, `tool.timeout`, `tool.failed`
  with a known cause) returns an error `ToolMessage` whose content is the **registry message plus
  the first resolution**, never the raw exception text (which can carry secrets or injected
  instructions);
- returns `None` (re-raise) for everything else: authority, budget, effect-uncertain, defects;
- keeps `HookScriptMiddleware`'s `AFTER_TOOL_FAILURE` dispatch working (it sees the exception
  first; `hooks.py:924-951`).

Example content the model sees: *"tool.invalid_arguments: web_fetch rejected argument `url`: not an
absolute https URL. Send an absolute https URL."*

`ToolRetryMiddleware` is attached only for tools whose capability card declares `idempotent: true`
(read-only fetches, searches). A tool with an external effect never retries at this layer; its
effect goes through the journal's `claim_then_reconcile` rule.

### 6.4 Declared fallbacks

`ModelFallbackMiddleware(first_model, *additional_models)` tries the primary, then each fallback
via `request.override(model=...)`, and re-raises the last exception. It already strips Anthropic
cache-control markers for non-Anthropic fallbacks. Mission Control wraps it
(`GovernedModelFallbackMiddleware`) so that:

- the chain comes **only** from the compiled binding: `ModelPolicy.fallback_models`, which exists
  and is unused, becomes part of the sealed binding; each fallback model is admitted (route,
  credential reference resolved at materialization, budget dimensions, `response_format` support
  checked at compile; GPT-6 models are not in `ProviderStrategy`'s regex list, so the binding must
  set the strategy explicitly);
- it engages only on the codes the policy lists (§7.1), after L1 has given up;
- **sticky** (proposed default `turn`): once a fallback served a call, the rest of the turn uses it,
  instead of paying for a failing primary on every call; `call` and `run` are the alternatives;
- each engagement writes a `model_fallback` frame (from, to, code, request id), adds the fallback
  model to the unit's receipt, and fires the coordinator's `decision_point` wake that the
  coordinator projection already lists for "a model fallback" (COORDINATOR-PROJECTION §6.2);
- usage is charged per model (the budget ledger must not assume one model per turn).

Cross-provider fallback (OpenAI to Anthropic) needs the provider-neutral model factory (program
decision D5). Same-provider fallback (GPT-6 Sol to Luna) works on today's factory.

**Above the turn**, the StageGraph `fallback_sequence` of operation variants (declared, validated,
unused) becomes the lane-level fallback: when a stage's operation settles with a fault whose policy
says `on_exhausted: next_variant`, the interpreter admits the next variant, which may name another
lane. That is a new semantic attempt with its own identity (ADR-0011), not a retry, and it is
recorded as such.

### 6.5 Graceful degradation the lane already does, and what joins it

Already present: the summarizer's own retry on `ContextOverflowError`; the budget and fence turn
stops; the durable capacity wait; `in_doubt` parking with reconciliation; a failed invocation
keeping its spend and partial points (F-S2-11). Joining them: context overflow → compact (the
summarizer, or `compact_conversation`) → declared larger-context fallback → `model.context_overflow`
settlement with `fork_from_point` offered; structured output invalid → the existing
`MissingOutputPolicy` (`follow_up_turn`) with the parser's validation errors rendered as a precise
message; `GraphRecursionError` → a governed `no_progress` outcome, with `recursion_limit` (9 999
today, `deepagents/graph.py:935-937`) made a governed knob.

### 6.6 The attempt budget

The product of the layers is bounded by one per-unit **attempt budget**: a new budget dimension
`model.attempts` (every request sent to a provider, including retries and fallbacks), distinct from
`model.turns`, read from the chat-model observer that already feeds `BudgetStopMiddleware`. When it
is exceeded the retry and fallback wrappers stop and the fault rises; the turn stop answers at the
next call. Worst case today with the proposed defaults: (1 + 2 retries) × (1 + fallbacks) calls per
model call, × 3 Temporal attempts on a lost worker; the attempt budget caps the total regardless.

### 6.7 What stays out

`temporalio.contrib.deepagents` (installed, unused) is an alternative durability model, not a
recovery feature; adopting it remains the open architecture decision recorded in the surface sheet.
`ModelCallLimitMiddleware` stays out (the lane's `BudgetStopMiddleware` agrees with the settlement;
the limit middleware adds graph nodes and would move step numbering). `ToolCallLimitMiddleware`
(per tool, `exit_behavior="continue"`) is selectable with that cost stated on its card.

---

## 7. What the coordinator may select and search (owner item 3)

**Should fallbacks and error behaviours be configurable? Yes, by selection within ceilings.** The
coordinator selects from closed options and typed knobs (COORDINATOR-PROJECTION §1: "I select, I
never compose code"); the compiler validates them; installation ceilings bound them.

### 7.1 The `fault_policy` block (proposed `mc.fault_policy.v1`)

Allowed at `mission`, `stage`, `goal`, `agent` and `subagent` scope; the nearest scope wins
field by field (ADR-0044 structural merge).

```yaml
agents:
  drafter:
    lane: deep_agents
    model:
      provider: openai
      model: gpt-6-sol
      fallback_models: [gpt-6-luna]          # existing ModelPolicy field, now sealed and admitted
    fault_policy:
      profile: resilient                     # conservative | standard | resilient
      model_retry: {max_retries: 2, max_delay_s: 20}
      model_fallback:
        on: [provider_busy, provider.unavailable, model.context_overflow]
        sticky: turn                         # call | turn | run
      tool_errors:
        to_model: [tool.invalid_arguments, tool.not_found, tool.rejected, tool.timeout]
        error_loop_limit: 3
      tool_retry: {tools: [web_fetch, web_search], max_retries: 2}   # idempotent tools only
      attempts: {model: 12}                  # the per-unit attempt budget (§6.6)
      on_exhausted: next_variant             # settle | next_variant | escalate | pause
```

| Profile | Model retry | Fallback | Tool errors to model | On exhausted |
| --- | --- | --- | --- | --- |
| `conservative` | 0 | none | invalid arguments only | settle |
| `standard` (default) | 2 | declared chain on `provider_busy`, `provider.unavailable` | the four recoverable tool codes | settle |
| `resilient` | 2 | declared chain on the above plus context overflow | the four, plus `tool.failed` | next variant, else escalate |

`on_exhausted: escalate` opens a Human Gate task (ADR-0038) with the fault's resolutions as its
options; `pause` parks the run with the fault as the reason.

### 7.2 Ceilings and what is not configurable

Installation configuration sets ceilings (maximum retries, maximum delay, maximum attempt budget,
which fallback routes are admissible); a policy may lower them, never raise them; compile rejects
an excess with `admission.fault_policy_exceeds_ceiling`. Not configurable by any mission: the
classifier and the registry; kernel workflow and activity `RetryProfile`s; SDK client retries; the
P4 effect rule; anything unlimited; a fallback to a model, lane or route the installation has not
admitted; silent fallback.

### 7.3 Cards and search

- **Policy cards** in the coordinator projection's "Control and safety" category, one per knob
  family: `deep_agents.model_retry`, `deep_agents.model_fallback`, `deep_agents.tool_errors`,
  `deep_agents.tool_retry`, `deep_agents.tool_call_limit`, `mission.fault_profile`,
  `stagegraph.variant_fallback`, with `visibility: governed`, `effect` (no graph node for the
  wrap middleware; nodes for the call limit), `maturity: installed`, knobs, ceilings and an
  example that compiles.
- **Fault cards**, one per registry code, generated: code, title, family, disposition, what
  Mission Control does automatically, resolutions, the policies that change its handling, and the
  frames it produces. A coordinator that sees `provider.rate_limited` in a wake can read exactly
  what happens next and what it may do.
- **Reads** (names follow the coordinator-surface grammar, CS-D1, and HTTP rule CS-D14):

| Read | CLI | HTTP | MCP |
| --- | --- | --- | --- |
| Search fault codes | `missionctl fault search <terms>` | `GET /v1/faults?q=` | `fault_search` |
| One code | `missionctl fault get CODE` | `GET /v1/faults/{code}` | `fault_get` |
| A run's faults | `missionctl run faults RUN [--unit U] [--since T]` | `GET /v1/runs/{run_id}/faults` | `run_faults` |
| One occurrence | `missionctl run fault RUN FAULT_ID` | `GET /v1/runs/{run_id}/faults/{fault_id}` | `run_fault` |

- **Wakes.** `failed` exists; add `degraded` (a fallback engaged, or a unit settled after
  recovery) carrying the fault code and position, and let run-time watch conditions (CO-D6) use a
  `fault` fact root (`fault.code`, `fault.family`, count in a window). Retries are not wakes; they
  are frames.

---

## 8. Precise messages and resolution pathways (owner item 4)

### 8.1 The envelope (`mc.error.v1`)

```json
{
  "schema": "mc.error.v1",
  "code": "provider.rate_limited",
  "legacy_code": "rate_limited",
  "family": "provider",
  "title": "Provider rate limit reached",
  "message": "OpenAI rate limited gpt-6-sol for stage:draft of run 7c1e…; retry after 20 s.",
  "status": 429,
  "retry": {"disposition": "provider_busy", "safe": true, "after_s": 20, "automatic": true},
  "position": {"mission_id": "…", "run_id": "7c1e…", "unit_key": "stage:draft",
               "point_ref": "pt_…", "attempt": 2, "lane": "deep_agents",
               "provider": "openai", "model": "gpt-6-sol"},
  "causes": [{"source": "openai", "type": "RateLimitError", "native_code": "rate_limit_exceeded",
              "http_status": 429, "request_id": "req_…"}],
  "resolutions": [
    {"kind": "automatic_retry", "title": "Mission Control retries 2 more times", "safe": true},
    {"kind": "wait", "title": "Wait for the run to settle", "safe": true,
     "cli": "missionctl run wait 7c1e… --until settled",
     "http": "GET /v1/runs/7c1e…", "mcp": {"tool": "run_wait", "arguments": {"run_id": "7c1e…"}}},
    {"kind": "fork_with_fallback_model", "title": "Fork from the last point on gpt-6-luna",
     "safe": true, "cli": "missionctl run fork 7c1e… --point pt_… --patch model=gpt-6-luna"}
  ],
  "field_errors": [],
  "fault_id": "0193…",
  "correlation_id": "…",
  "docs": "docs/reference/faults.md#provider-rate_limited"
}
```

`field_errors[]` (`{path, code, message, allowed}` with a JSON pointer) replaces FastAPI's default
`{"detail": [{loc, msg, type}]}` and the compiler's `decisions` for request and manifest faults, so
a coordinator fixing a manifest gets every wrong field in one answer.

### 8.2 Message rules

1. One sentence: **what failed, where, why**; then the action. "OpenAI rate limited gpt-6-sol for
   stage:draft; retry after 20 s." Never "operation failed".
2. Name things by the public vocabulary (GLOSSARY): unit key, point, stage, iteration, lane; never
   checkpoint namespaces, thread ids or Python class names.
3. Include the vendor's native code and request id in `causes`, never its message text.
4. Never a secret value; name the secret reference (`OPENAI_API_KEY ref openai/default`).
5. Say whether Mission Control is already handling it (`retry.automatic`), so nobody races the
   system.
6. Resolutions are ordered safest first and are executable as written; a resolution that needs
   state Mission Control does not have is omitted.
7. Unexpected exceptions: "Mission Control hit an unexpected error in {operation}. Nothing was
   retried. Report fault {fault_id}." The traceback is in the worker log under the same id.

### 8.3 HTTP

- Global exception handlers in `bootstrap/api.py` (today: none) for `MissionControlError`,
  `RequestValidationError` (→ `request.invalid` with `field_errors`), `HTTPException` (legacy
  pass-through, wrapped), and `Exception` (→ `internal.unexpected`, no text). Routers raise
  `MissionControlError` subclasses instead of `HTTPException` (FT-0 migrates them; the per-router
  `_error()` tables become registry rows).
- Body: RFC 9457 `application/problem+json`. `type` = `urn:mission-control:fault:<code>`, `title`,
  `status`, `detail` = message, `instance` = `urn:mission-control:fault-occurrence:<fault_id>`,
  and the envelope's other fields as extension members.
- Headers: `Retry-After` for `retry_after` actions; `X-Request-Id`/correlation echoed.
- Compatibility for one release (FT-D10): the body also carries `detail: {code: <legacy_code>,
  message}` so existing clients (the CLI included) keep working; CS-D14's "no renames" holds for
  paths.
- The body-limit middleware renders `request.too_large` with the configured limit
  (`deployment.max_request_bytes`), not the hard-coded 1000000.

### 8.4 MCP

- A tool failure returns `CallToolResult(isError=True, content=[text], structuredContent=envelope)`.
  The MCP specification reports tool execution errors inside the result with `isError` so the
  model sees and can act on them; protocol errors (unknown tool, malformed request) stay JSON-RPC
  errors. Today's `{"ok": false, ...}` success result hides the failure from clients that check
  `isError`.
- The text content is the message plus the resolutions, written for a model: "provider.rate_limited:
  OpenAI rate limited gpt-6-sol for stage:draft; retry after 20 s. Mission Control is retrying.
  Next: run_wait(run_id=7c1e…)".
- Resolutions carry `mcp: {tool, arguments}` so the coordinator's next call is a copy.
- `mask_error_details=True` stays for unexpected exceptions; the envelope is always safe.
- The three MCP shapes (coordinator, operator, signals) collapse to this one; the per-module
  translation tables (`run_control_tools.py:59-96`, `subscriptions.py:298-314`,
  `human_task_tools.py:54-59`, `governed_gateway.py:83-88`, `mission_tools.py:255-292`) are deleted.

### 8.5 CLI

Human output on **stderr**:

```text
error[provider.rate_limited]: OpenAI rate limited gpt-6-sol for stage:draft of run 7c1e…
  why:   429 rate_limit_exceeded (request req_…); retry is safe after 20 s
  auto:  Mission Control retries 2 more times
  next:  missionctl run wait 7c1e… --until settled
  or:    missionctl run fork 7c1e… --point pt_… --patch model=gpt-6-luna
  more:  missionctl fault get provider.rate_limited   (fault 0193…)
```

- `--json` (or `--output json`) prints the envelope to **stdout** for scripts and agents, so a
  failing command is as parseable as a succeeding one.
- Exit codes come from the registry. Today's table (0 success, 2 invalid, 3 denied, 4 conflict,
  5 unavailable, 6 wait timeout or blocked) stays; the stray exit 1 is removed; FT-D12 proposes
  7 for "retry later" (429 or capacity wait with `Retry-After`), distinct from 5 (unreachable or
  5xx), and 8 for "needs reconcile or a human" (`in_doubt`, escalated).
- Local errors (bad file, bad flag) use the same renderer with `request.*` codes; no raw
  `str(exc)`.

### 8.6 Stream, Transcript and inspection

- Socket.IO `stream_error` carries `mc.error.v1`; `StreamErrorCode` values become registry codes.
- The provider `error` frame and a `fault.recorded` mission event carry `mc.fault.v1` (the Fault
  record: code, position, causes, details, fault id). The Transcript shows faults inline at their
  point, retries and fallbacks as frames between model requests.
- `run inspect` gains `faults: {by_code: {...}, last: <envelope>}` per unit; `UnitFailureView`
  (`contracts/contracts.py:327-333`) carries the code and fault id.

---

## 9. Heuristics

Heuristics are evidence and advice, never authority (ADR-0007, ADR-0045). Each is bounded,
recorded, and overridable by policy.

| Heuristic | Rule | Where |
| --- | --- | --- |
| Retry-After first | Honour the vendor's `Retry-After` (or reset headers via `ProviderLimitSignal`); beyond L1's cap, hand to the durable capacity wait | L1, L4 |
| Jittered exponential backoff | Full jitter, capped; never synchronized retries across parallel units | L1, L3b, Temporal `RetryProfile` |
| Per-worker circuit breaker | After N `provider_busy`/`provider.unavailable` faults for one provider and model within a window, the worker's breaker opens: units with a declared fallback start on it (sticky `run`); units without one wait (L4) instead of hammering. Advisory, in memory, recorded as a `circuit_opened` frame | Deep Agents lane |
| Tool error-loop detection | The same tool failing with the same code `error_loop_limit` times in one turn stops sending errors to the model and raises `tool.error_loop` (stops paying for a model stuck on one mistake) | L3a |
| Stall detection | Heartbeat alive but no frame for a configured interval: `runtime.stalled` wake via the existing Watchers absence trigger; not a cancel | Watchers |
| Unknown is not transient | An unclassified exception is `internal.unexpected`, non-retryable, alerting; never LangGraph's "retry by default" | Mappers |
| Classification order | Typed attributes (status, native code, `TimeoutType`) before class, class before module family; message text is used only for vendor codes documented as message-only, each listed in the mapper with its source | Mappers |
| Idempotency from cards | Tool retry needs `idempotent: true` on the card, not a guess from the tool name | L3b |

---

## 10. Observability

- **Every fault, one id, five places:** the `error` frame and `fault.recorded` event (Transcript),
  the structured worker log line (`fault_id`, code, position; traceback only here), the metric
  below with the fault id as an exemplar, the LangSmith run metadata (`mc.fault_code`,
  `mc.fault_id`), and the envelope the caller saw. One grep joins them.
- **Metrics** (OpenTelemetry, exported through the installed Prometheus exporter):
  `mc_faults_total{code, family, disposition, lane, provider}`,
  `mc_recovery_attempts_total{layer, code, outcome}`,
  `mc_fallbacks_total{from_model, to_model, code}`,
  `mc_capacity_wait_seconds{provider}`, `mc_circuit_state{provider, model}`,
  `mc_units_settled_total{outcome, recovered}`. Labels are bounded: codes and families are closed;
  model ids are the admitted route ids.
- **Temporal:** wire `temporalio.contrib.opentelemetry.TracingInterceptor` on client and worker,
  and the SDK runtime's metrics (`TelemetryConfig`), so activity retries, schedule-to-start latency
  and task-queue backlog are visible. `BENIGN` category keeps expected outcomes out of Temporal's
  failure metrics.
- **Recovery is a first-class outcome:** a unit that settled after a retry or a fallback is
  `completed` with `recovered: true` and the faults it survived, so "how often did we really
  recover" is a query, not a log search.
- **Dashboards and alerts** (FT-6): fault rate by family and code; recovery rate; fallback rate per
  route; capacity wait time; `internal.*` count (alert on any); `effect.*` and `in_doubt` count
  (alert); unlimited-retry guard (alert if any activity exceeds its profile's attempts).

---

## 11. Four worked failures

**A. OpenAI 429 mid-turn in a Stage Graph stage (Deep Agents, policy `standard`).**
The model call raises `openai.RateLimitError` (429, `rate_limit_exceeded`, `retry-after: 8`).
`GovernedModelRetryMiddleware` classifies `provider.rate_limited` (`provider_busy`), writes a
`model_retry` frame, waits 8 s, retries; the second call returns 429 again; the third succeeds. The
turn continues; the unit settles `completed` with `recovered: true`; `mc_recovery_attempts_total`
counts two; no wake fires. If the third had failed: `GovernedModelFallbackMiddleware` engages
`gpt-6-luna` (declared), writes `model_fallback`, fires `degraded`; the rest of the turn uses Luna
(sticky `turn`). If no fallback was declared: the fault rises as a non-retryable `ApplicationError`
with `next_retry_delay`; the operation workflow's capacity wait (L4) takes it; `run inspect` shows
the envelope of §8.1.

**B. A stale command over three surfaces.** A coordinator sends `pause` with an old
`expected_version`. The application raises `RunVersionConflict` (now code `run.stale_version`,
legacy `stale_run_version` / `request_conflict` / `IDEMPOTENCY_CONFLICT`). HTTP answers 409
problem+json; MCP answers `isError: true` with the same envelope; the CLI prints
`error[run.stale_version]: run 7c1e… is at version 14, the command expected 12` with
`next: missionctl run inspect 7c1e…` and exits 4. Today these are three different codes (§2.5).

**C. A tool called with a bad argument.** The model calls `web_fetch` with a relative URL; the tool
raises `ToolInvocationError`. The tool-error handler returns an error `ToolMessage`:
"tool.invalid_arguments: web_fetch rejected argument `url`: not an absolute https URL. Send an
absolute https URL." The model corrects itself on the next step. If it repeats the mistake three
times, `tool.error_loop` ends the turn with `fork_from_point` offered.

**D. The worker dies mid-turn.** The heartbeat stops; Temporal raises
`TimeoutError(type=HEARTBEAT)`; the mapper classifies `runtime.heartbeat_lost` (`worker_lost`); the
`RetryProfile` for `operation.execute` permits a retry; the activity resumes from the latest
checkpoint (RRM-008). The Transcript shows the gap with a `worker_lost` frame; usage of the lost
attempt is kept (F-S2-11). If the third attempt also dies:
`workflow.retries_exhausted` wraps it; the unit settles `failed` with `fork_from_point` and
`reconcile` (if effects were claimed) as resolutions.

---

## 12. Work packages and placement

| WP | Builds | Proves | Touches agent configuration? | Where it fits |
| --- | --- | --- | --- | --- |
| **FT-0** Registry and surfaces | `domain/faults`, `contracts/faults.py`, the registry with today's codes as legacy aliases, `MissionControlError` and re-based families, HTTP handlers and problem+json, MCP `isError`, CLI renderer and `--json` errors, `docs/reference/faults.md` generator | A contract test: each failure in §2.5 yields the same code and resolutions on HTTP, MCP and CLI; every registry code renders on every surface; no `str(exc)` in a response (grep test) | no | Now; independent of the sprint sequence |
| **FT-1** Temporal | `adapters/faults/temporal.py`, the classifier (ADR-0011 built), `RetryProfile`s in the pinned execution profile, generated `non_retryable_error_types`, bounded former-unlimited policies with escalation, every `ApplicationError` typed, `category=BENIGN` for expected outcomes, `ChildWorkflowError` and `RPCError` mapping | Replay tests unchanged (patch markers where history changes); unit tests per Temporal exception; a T0 run with a killed worker | no | Now; needs workflow patching care |
| **FT-2** Deep Agents classification | SDK and LangChain mappers, the lane's catch-all keeping a `Fault` (codes, causes, request id) instead of a type name, settlement `failure_code` from the registry, `error` frames with `mc.fault.v1` | FX fixtures with a fake chat model raising each SDK exception; the settlement row and the Transcript show the code | no | Before or with sprint A |
| **FT-3** Deep Agents recovery | `GovernedModelRetry`, `GovernedModelFallback` (sealed `fallback_models`), tool-error handler, idempotent tool retry, `model.attempts` budget, frames, circuit breaker | Fake-model fixtures for every row of §6.1; one live T2 proof under 1 USD: a forced 429 recovered, a forced fallback recorded | yes | Sprint B (agent configuration language) |
| **FT-4** Policies and coordinator | `mc.fault_policy.v1`, profiles, ceilings, compile checks, policy and fault cards, `fault` and `run faults` reads on three surfaces, `degraded` wake, `fault` watch facts, StageGraph `fallback_sequence` executed | Compile rejects; a coordinator scenario that searches a fault, reads a run's faults and forks with a fallback patch | yes | Sprints B (policy) and I (cards, search) |
| **FT-5** Persistence | `fault.recorded` events and, if FT-D14 chooses it, a `fault_occurrence` table and view in the next SQL release; `UnitFailureView` with codes | `run faults` served from the record; retention follows the mission (ADR-0055) | no | With the next release (1.4.5 / 1.4.6) |
| **FT-6** Observability | OTel interceptor and SDK metrics, `mc_*` metrics, LangSmith metadata, dashboards and alerts | Metrics visible on T0; alert fires on an injected `internal.unexpected` | no | Sprint F |
| **FT-7** Other lanes, one at a time | Each lane's table onto the registry (remote session family, Cursor, Claude, Codex) | Per-lane fault fixtures | per lane | With each lane's consolidation sprint |

FT-0 and FT-1 are the "less sexy" foundation and divert the program by about two sessions without
reordering it. FT-2 can ride with sprint A, FT-3 and FT-4 with B, FT-6 with F.

---

## 13. Decisions (recommendation marked)

| ID | Decision | Options | Recommendation |
| --- | --- | --- | --- |
| FT-D1 | Adopt one fault registry and the `Fault` value as the only way failures are named (§4) | (a) adopt; (b) keep per-module vocabularies, add a mapping layer | **(a)** |
| FT-D2 | Code format | (a) `family.reason` snake case; (b) flat UPPER (CoordinatorErrorCode style); (c) numeric | **(a)**; legacy codes kept as aliases |
| FT-D3 | Build the ADR-0011 classifier now as `RetryDisposition`, persisted beside `OperationFailureClassV2` (P3) | (a) now, in FT-1; (b) wait for sprint F | **(a)** |
| FT-D4 | Unify `retry_class` and `retryability` into the journal's `retry_class` as the effect axis of P4 | (a) unify; (b) keep both | **(a)** |
| FT-D5 | Vendor exceptions imported only in `adapters/faults` (and lane adapters calling it) | (a) enforce with an architecture test; (b) convention only | **(a)** |
| FT-D6 | Bound every unlimited Temporal retry policy, with an escalation (reconciliation case) at the bound | (a) bound all; (b) keep cancel unlimited as a justified exception | **(a)**, 24 h schedule-to-close for cancel |
| FT-D7 | Use `ApplicationErrorCategory.BENIGN` for expected governed outcomes | (a) yes; (b) no | **(a)** |
| FT-D8 | Provider SDK retries stay off (`max_retries=0`) and LangChain middleware owns in-turn retries | (a) yes; (b) let the SDK retry | **(a)**: every paid attempt stays observable |
| FT-D9 | Retry after a possibly billed timeout | (a) at most one, charged as estimated, `spend: uncertain`; (b) never; (c) like any transient | **(a)** |
| FT-D10 | Wire compatibility | (a) one release carrying `legacy_code` and the old `detail.code`; (b) break now | **(a)** |
| FT-D11 | HTTP error format | (a) RFC 9457 problem+json with extension members; (b) keep `{"detail": ...}` | **(a)** |
| FT-D12 | CLI exit codes | (a) keep 0, 2-6, remove 1, add 7 retry later and 8 needs reconcile or human; (b) keep the table as is | **(a)**; amends RUNTIME-CONTRACTS |
| FT-D13 | MCP tool failures | (a) `isError: true` with the envelope as structured content; (b) keep `ok: false` success results | **(a)** |
| FT-D14 | Where fault occurrences are stored | (a) `fault.recorded` mission events plus frames, a view for `run faults`; (b) a new `fault_occurrence` table | **(a)** first; (b) only if queries need it |
| FT-D15 | Fallbacks and error behaviours configurable by the coordinator | (a) yes, the closed `fault_policy` block and profiles within installation ceilings; (b) installation only; (c) free-form | **(a)** |
| FT-D16 | Default profile | `conservative`, `standard`, `resilient` | **`standard`** |
| FT-D17 | Fallback stickiness default | `call`, `turn`, `run` | **`turn`** |
| FT-D18 | Activate `ModelPolicy.fallback_models` as the sealed, admitted fallback chain | (a) yes; (b) a new field | **(a)**: it already exists, unused |
| FT-D19 | Execute the StageGraph `fallback_sequence` as lane-level fallback (`on_exhausted: next_variant`) | (a) yes, a new semantic attempt; (b) leave unused | **(a)** |
| FT-D20 | Tool errors returned to the model | (a) the registry message and first resolution only; (b) raw exception text | **(a)** |
| FT-D21 | Per-worker circuit breaker | (a) advisory, in memory, recorded; (b) shared state in Postgres or Redis; (c) none | **(a)** |
| FT-D22 | Program placement | (a) a short program now (FT-0, FT-1), the rest folded into sprints A, B, F, I; (b) a full separate sprint after B | **(a)** |

---

## 14. Honest list

- I ran nothing. Every "today" claim comes from reading `src/` on `main` (`a7a8b0da`) and the
  installed packages; line numbers can drift with the dirty working tree.
- The billing behaviour of a timed-out OpenAI or Anthropic request is not established here; FT-D9
  assumes "possibly billed". The quota-versus-rate split on OpenAI 429s rests on the documented
  `insufficient_quota` code; Anthropic's billing errors were not enumerated.
- I did not verify how `ModelFallbackMiddleware` interacts with `ToolStrategy` structured output,
  with the `ObservedSummarizationMiddleware` order, or with the budget observer's per-model
  accounting; FT-3 must prove each with a fake model before a live run.
- Whether the operator and coordinator MCP clients in use honour `isError` with
  `structuredContent` (MCP 2025-06 and later) was not tested; FT-0 must check the clients the
  coordinator skill uses.
- The middleware stack order (fence and budget stops outside retry and fallback) is a design
  intent; deepagents inserts custom middleware after its core stack and before its tail
  (`deepagents/graph.py:361-390`), and the exact resulting order must be asserted by a test.
- `temporalio` 1.34 has `ApplicationErrorCategory` with only `UNSPECIFIED` and `BENIGN`; no other
  categories were assumed.
- The registry in Appendix A is a first cut: about 70 codes from the vocabularies in §2.1. FT-0
  will find more in the routers; every one found is added, with its legacy alias, before a router
  is migrated.
- The names (`fault`, `run faults`, `fault_policy`, profile names, metric names, exit 7 and 8) are
  placeholders until the coordinator-surface grammar and the glossary take them (CS-D1, CS-D6).
- The relation to the human review gates supplement (HG-D1..24, at the platform root) is only
  `on_exhausted: escalate`; how a fault opens a review gate task belongs to that supplement.

---

## Appendix A. The first fault registry

Disposition abbreviations: TT `transient_transport`, WL `worker_lost`, PB `provider_busy`, II
`invalid_input`, AD `authority_denied`, QR `quality_rejected`, BE `budget_exhausted`, EU
`effect_uncertain`, CI `checkpoint_invalid`, — none (a pure request fault). Exit codes use FT-D12.

| Code | Disposition | HTTP | Exit | Caller action | Replaces (legacy) |
| --- | --- | --- | --- | --- | --- |
| `request.invalid` | II | 422 | 2 | fix_request | FastAPI 422, `INVALID_ARGUMENT`, `COORDINATOR_INVALID_REQUEST`, `command_rejected` |
| `request.too_large` | II | 413 | 2 | fix_request | `content_too_large`, body-limit string |
| `request.cursor_expired` | — | 409 | 4 | refresh_then_retry | `CURSOR_EXPIRED` |
| `auth.unauthenticated` | AD | 401 | 3 | authorize | `bearer_token_required`, `UNAUTHENTICATED` |
| `auth.forbidden` | AD | 403 | 3 | authorize | `unauthorized`, `FORBIDDEN` |
| `auth.scope_unavailable` | — | 503 | 5 | retry_after | scoped service missing (HTTP 503 vs MCP `FORBIDDEN`) |
| `state.not_found` | — | 404 | 2 | fix_request | `resource_not_found`, `NOT_FOUND`, `not_found` |
| `state.conflict` | — | 409 | 4 | refresh_then_retry | `CONFLICT`, `request_conflict` |
| `state.idempotency_conflict` | — | 409 | 4 | fix_request | `IDEMPOTENCY_CONFLICT` |
| `run.stale_version` | — | 409 | 4 | refresh_then_retry | `stale_version`, `stale_run_version` |
| `run.stale_generation` | — | 409 | 4 | refresh_then_retry | `stale_generation`, `stale_execution_generation` |
| `run.not_pending` / `run.not_terminal` | — | 409 | 4 | wait | `run_not_pending`, `RUN_NOT_TERMINAL` |
| `run.launch_rejected` | II | 409 | 4 | revise | `RunLaunchRejected` (one status everywhere) |
| `fork.rejected.<reason>` | II | from reason | 2/4 | per reason | `ForkRejectionCode` values |
| `admission.prerequisites_unmet` | II | 422 | 2 | configure | `PREREQUISITES_UNMET` |
| `admission.compile_rejected` | II | 422 | 2 | fix_request | `CompilationRejected` (decisions → `field_errors`) |
| `admission.fault_policy_exceeds_ceiling` | II | 422 | 2 | fix_request | new |
| `admission.launch_ticket_expired` | — | 409 | 4 | refresh_then_retry | `LAUNCH_TICKET_EXPIRED`, `_INVALIDATED` |
| `capability.not_found` / `forbidden` / `incompatible` / `unavailable` | II / AD / II / TT | 404 / 403 / 422 / 503 | 2/3/2/5 | per code | `CAPABILITY_*` |
| `capability.drift` | II | 409 | 4 | revise | `CAPABILITY_SOURCE_CHANGED`, `_SCHEMA_CHANGED`, `capability_drift` |
| `provider.connection_failed` | TT | 503 | 5 | retry | `ProviderTransportError`, `transient_transport` |
| `provider.timeout` | TT (spend uncertain) | 504 | 5 | retry | new |
| `provider.rate_limited` | PB | 429 | 7 | retry_after | `rate_limited`, `429`, `RATE_LIMITED` |
| `provider.overloaded` | PB | 503 | 7 | retry_after | `529`, `overloaded` |
| `provider.capacity_wait` | PB (BENIGN) | — | 7 | wait | `provider_capacity_limit` |
| `provider.quota_exhausted` | BE | 402/429 | 3 | configure | `quota_exhausted`, `billing_unavailable` |
| `provider.unavailable` | TT | 503 | 5 | retry | provider 5xx |
| `provider.auth_failed` | AD | 502 | 3 | configure | `auth_failed`, `AccessDenied` |
| `provider.permission_denied` | AD | 502 | 3 | configure | `entitlement_missing` |
| `provider.model_not_found` | II | 502 | 2 | revise | new |
| `provider.request_rejected` / `request_too_large` | II | 502 | 2 | revise | new |
| `provider.session_busy` / `session_not_found` / `stream_expired` | PB / II / TT | 409 / 404 / 410 | 4/2/5 | per code | `SessionBusy`, `SessionNotFound`, `StreamExpired` |
| `model.context_overflow` | II | — | 2 | revise | `ContextOverflowError`, `CONTEXT_BUDGET_EXCEEDED` |
| `model.output_invalid` | QR | — | 2 | revise | `OutputParserException`, `goal_output_invalid`, `invalid_result_contract` |
| `model.output_truncated` / `content_filtered` | QR | — | 2 | revise | new |
| `tool.invalid_arguments` | II | — | — | fix_request (to model) | `ToolInvocationError` |
| `tool.failed` / `not_found` / `timeout` / `rejected` | II / II / TT / AD | — | — | fix_request (to model) | `ToolException`, `tool.failed` event, hook DENY |
| `tool.error_loop` | QR | — | — | revise | new |
| `tool.subagent_failed` / `subagent_timeout` | per cause | — | — | per cause | `SubagentErrorEvent`, `TaskEvent` |
| `runtime.heartbeat_lost` | WL | — | 5 | automatic_retry | `worker_lost` frame code |
| `runtime.activity_timeout` / `deadline_exceeded` / `no_worker` | TT / BE / TT | — | 5 | per code | Temporal `TimeoutType` |
| `runtime.step_limit` | QR | — | — | revise | `GraphRecursionError` |
| `runtime.stalled` | — | — | — | wait | new (Watchers absence) |
| `runtime.workspace.<reason>` | per reason | 409/422 | 4/2 | per reason | `WORKSPACE_ERROR_CODES` |
| `runtime.temporal_unavailable` / `temporal_throttled` | TT / PB | 503 | 5/7 | retry_after | `RPCError` UNAVAILABLE, RESOURCE_EXHAUSTED |
| `workflow.cancelled` | — (BENIGN) | — | 0 | none | `CancelledError`, `cancelled_by_command` |
| `workflow.terminated` | — | — | 8 | escalate | `TerminatedError` |
| `workflow.retries_exhausted` | per cause | — | per cause | per cause | `RetryState.MAXIMUM_ATTEMPTS_REACHED` |
| `workflow.server_error` | TT | 503 | 5 | retry | `ServerError` |
| `effect.uncertain` | EU | — | 8 | reconcile | `ambiguous_external_effect`, `in_doubt`, `lane_in_doubt_unrecorded` |
| `effect.cancel_unconfirmed` | EU | — | 8 | reconcile | new (FT-D6 bound) |
| `budget.exhausted` | BE (BENIGN) | — | 6 | revise | `budget_exceeded`, `budget_exhausted`, governor exhaustion |
| `budget.model_calls_exhausted` / `tool_calls_exhausted` / `attempts_exhausted` | BE | — | 6 | revise | `ModelCallLimitExceededError`, `ToolCallLimitExceededError`, new |
| `quality.rejected` | QR | — | 6 | revise | `quality_rejected`, `not_accepted` |
| `checkpoint.invalid` / `lineage_conflict` / `incompatible_resume` | CI | 409 | 4 | fork_from_point | `CHECKPOINT_INVALID`, `checkpoint_lineage_conflict`, `incompatible_resume` |
| `checkpoint.time_travel_unsupported` | II | 422 | 2 | revise | `time_travel_unsupported` |
| `internal.invariant_violation` | — | 500 | 5 | report | `internal_invariant_violation` |
| `internal.unexpected` | — | 500 | 5 | report | `INTERNAL_ERROR`, every unclassified exception |
