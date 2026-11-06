# Lane conformance suite

Every lane profile runs the same scenarios against its fake provider (SPEC-06 section 3,
`docs/specs/archive/materialization-observation-2026-10/SPEC-06-hosted-api-lanes.md`). A lane merges
only when the suite passes for it. Run it with `make test-conformance` (part of `make check`).
FIXTURES only: no network, no credentials, no paid call.

## What runs

Compile conformance (ADR-0063, Sprint OC R0) is a sibling suite in `compile/`: every lane's pure
`LaneAdapter.compile` against the eight canonical items and one model pin per vendor
(`compile/fixtures.py`), registered in `compile/registry.py`. Deep Agents runs it with its real
compile; every other lane package registers the describe-only compile (OC-R3, OC-D199) and runs
every check but describe honesty, which it declares as an exception citing the launch and
projection suites that prove its materialization (`compile/describe_only.py`). The narrow stub is a
suite probe, not a lane (`SUITE_PROBES`).

Residuals after R3 (for the provider sweep):

- 21 modules outside a lane package still decode a sealed lane binding
  (`tests/architecture/test_package_boundaries.py::SEALED_BINDING_READERS_OUTSIDE_LANES`); each
  needs a lane-owned port, not a move.
- 221 lane-name hits in 33 application files (`rg -n "claude_agent_sdk|codex_agents|claude_managed|cursor_local|cursor_cloud|claude_cloud|codex_cloud|\"codex\"|\"cursor\"|\"claude\"" src/mission_control/application`; about 25 are prose). By owner module:
  auth routes and secret delivery (`execution/auth_admission.py`, `secrets/delivery.py`);
  environments and workspace policy (`environments/*`, `workspaces/policy.py`); frames and
  signals (`frames/kinds.py`, `frames/provider_mapping.py`, `frames/transcript.py`,
  `signals/service.py`); the deployment-file schemas (`authoring/provider_launch.py`,
  `authoring/cursor_launch.py`, one field per profile); prerequisites (`prerequisites/*`);
  ambient discovery, leases and watchers (`agentic_components/ambient.py`,
  `execution/harness/leases.py`, `watchers/sources.py`). The aggregator
  (`execution/harness/describe.py`) and `resolution/` are allowed by design.


| Scenario | Test | Claimed when the describe says |
| --- | --- | --- |
| describe honesty | `test_describe_honesty.py` | always |
| start, observe and settle | `test_session_turns.py` | `prepare`, `start`, `send_turn`, `observe`, `usage`, `end_session` implemented |
| reattach mid-stream, no duplicate frame | `test_session_turns.py` | `observe`, `reattach` implemented |
| `send_turn` while busy | `test_session_turns.py` | `send_turn` implemented, `queue_instruction` not `unsupported` |
| cancel | `test_session_turns.py` | `cancel_turn` implemented, `cancel` not `unsupported` |
| `interrupt_and_inject` | `test_session_turns.py` | `send_turn` implemented, `interrupt_and_inject` not `unsupported` |
| approval round trip | `test_session_controls.py` | `approval_suspension` implemented, `provider_permission` listed |
| budget stop | `test_session_turns.py` | `usage` implemented |
| fork emulation | `test_session_controls.py` | `snapshot`, `fork` implemented, `fork` not `unsupported` |
| continuation hand-over | `test_session_controls.py` | `continuation` implemented, `request_continuation` not `unsupported` |
| unknown usage stays unknown | `test_session_turns.py` | `usage` implemented |

"Implemented" means `native` or `emulated` (`contract.CLAIMS`). The lane does not choose its
scenarios; its declared matrix in its lane package's `describe.py` does (aggregated by
`application/execution/harness/describe.py`). A scenario the
describe does not claim is not run, and describe honesty proves the lane refuses it instead
(`HarnessUnsupported`, or a typed admission refusal). Session scenarios drive the production
`LaneTurnService` inside a real Run with its command mailbox, so they prove Mission Control's
controls on the lane, not the fake alone.

## Registering a lane

1. Declare the profile's matrix and `LaneDeclaration` in the lane package's `describe.py`, add it to
   the aggregator (`application/execution/harness/describe.py`), the frozen command tables and the
   hook mapping, and register the package's `lane.py::LANES` in `bootstrap/lanes.py` (which puts it in
   the compile suite).
   From then on `test_registry.py` fails until step 3 is done.
2. Write `adapters/<lane>.py`:
   - a `LaneFake` subclass reading the fake provider: `sends`, `until_held`, `release`,
     `cancels`, `ended` and, when approvals are claimed, `approval_answers`;
   - a `LaneAdapter` subclass with `profile`, `harness(tmp_path)` (the harness exactly as a
     worker registers it) and `open(tmp_path, script, ...)`, which plays each `Script` inside a
     fresh admitted Run: `admitted_unit` plus `compose_control_stack` from
     `tests/fixtures/cursor_controls.py`, as the existing adapters do;
   - `continuation_ports` when the describe claims continuation, and `write_workspace` plus
     `fork` when it claims fork emulation.
3. Add one entry to `CONFORMANCE_LANES` in `registry.py`.

A profile with a declared describe and no adapter yet registers as
`DescribeOnlyConformance("<profile>")`; its describe must then claim nothing.

A lane built on the remote-session base (`adapters/remote_session/`, ADR-0052) registers the
same way: its adapter puts the provider-API fake (for example an `httpx.MockTransport`) behind
the lane's harness, as `adapters/cursor.py` does for the Cloud Agents API and
`adapters/managed.py` for Anthropic Managed Agents (`claude_managed`).

## Declared exceptions

A claimed scenario that this suite cannot drive for a lane is a `DeclaredException` on the
adapter: a reason and the repository paths that prove the behaviour instead. `test_registry.py`
refuses an exception for describe honesty, for a scenario the lane does not claim, or one citing
a missing file. Today only `deep_agents` declares exceptions: it is governed (the operation
boundary runs it through `operation.execute`; `lane.turn` never drives it), so its session
scenarios cite the suites that prove them on that path.

## Layout

| Module | Role |
| --- | --- |
| `contract.py` | Scenarios, claims, `Script`, `LaneFake`, `LaneAdapter`, `DeclaredException` |
| `drive.py` | Lane-neutral plumbing: segments, held turns, harness requests, approvals, continuation |
| `registry.py` | `CONFORMANCE_LANES` and the per-scenario parametrisation |
| `records.py` | The qualification records the describe-honesty gate reads |
| `adapters/` | One adapter per lane |
