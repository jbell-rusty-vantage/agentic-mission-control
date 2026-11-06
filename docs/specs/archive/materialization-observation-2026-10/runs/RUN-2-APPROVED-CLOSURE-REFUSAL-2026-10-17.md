---
type: Recovery Execution Record
title: "Run 2 approved closure: prelaunch capacity refusal and unchanged live state"
description: "One authorized invocation stopped before live clients; distinct read-only observation verified the held frontier and cleanup."
---

# Approved closure remains unexecuted

The owner explicitly approved the reviewed remaining family/root closure at
**2026-10-17 18:07 UTC**. The single execute invocation refused at the existing
1.5 GiB start-memory gate, before credentials, output creation, WSL host spawn,
database or Temporal client creation. **No closure mutation occurred.** There
was no second execute invocation and no automatic retry. No session or service
was stopped to free memory.

Read the [current integration](RUN-2-CURRENT-INTEGRATION-2026-10-17.md),
[reviewed proposal](RUN-2-REMAINING-CLOSURE-PROPOSAL-2026-10-17.md) and
[exact evidence](RUN-2-APPROVED-CLOSURE-REFUSAL-EVIDENCE-2026-10-17.json).
This record supersedes earlier statements that specific owner approval is absent;
it does not change the original acceptance criteria.

## Authority and source identity

Only `phase_action.expires` was refreshed to **18:22:49.661242 UTC**, 650 seconds
ahead. All other fields and every reviewed application, 15-component host and
supporting-receipt pin matched. Stable envelope excluding expiry:
`sha256:f82bf605e66a7d03bb0e3fa3b85d14365a7f0f7ae165fce216b8136bade5561a`.
The retained `approved-action.json` literal SHA256 is
`4ef0d1c6ef84a057fd803f8fb02d084c66d8ea6bea62b33730d4da3282ed2dfb`.
Inspected owned main was clean at `c0298800ee02c2d4dfe8ab31cb396f03f4a89486`.

The 18:11:59 UTC read-only check verified unchanged installed runtime package
versions and selected source/binary hashes, the exact private registry/header,
consumed phase-one intent and absent remaining-closure intent. A separate fresh
registry check at18:13:33 UTC again confirmed the remaining intent absent.
These local checks made no network calls or intent claims.

## Attempt boundary and current observation

The invoked command was the frozen `run_host.py --execute <literal SHA256>
approvedlive1`. Its traceback terminates at `run_host.py:57`,
`memory_start_gate`. Source order proves that the invocation reached no owned
WSL child, AWS credential delivery, SQL/Temporal connection, workflow routing
change or worker registration. Neither `owned-host-approvedlive1.txt` nor its
JSON receipt exists. The saved refusal receipt is an operator record of that
traceback/control-flow boundary; it is not represented as an emitted live-host
receipt. The exact available-byte value at refusal was not retained.

The later native Windows counter showed2,330,714,112 available bytes (2.17 GiB),
85% load. The initial sandbox CIM inventory was unavailable/virtualized and its
zero fields were invalid readings, not actual RAM measurements. No resource
cleanup, tuning, process termination or service restart was attempted.

With recovered capacity, a **distinct read-only observer** completed at
**18:14:28.969934 UTC**, outer37.562s / guardian37.222s under its78s ceiling:

| Observation | Actual retained evidence |
| --- | --- |
| Database | Protected28-domain digest `sha256:e4cbbcc91db9dabeb976b40233bb519ee8f6e41a185606adf8bc30a44e4024d1`; run8/cancelling and family2 unchanged; typed result absent |
| Family/root | Both running; exact prior42/16 events and history digests retained |
| Protected work | Foreign maintenance2 events unchanged; original failed operation verified |
| Default routing | `mission-control.0.1.0-a8d69c5b4850`, revision10; no routing mutation |
| Principals and cleanup | Fresh read-only pool principals; all owned pools closed, exact child reaped, no forced kill, source pins unchanged; credentials not retained |

Read-only observation deliberately permits expired mutation authority. Its
separate generated observation action hash is not authorization to execute.
It proves the held state at the observation time; it does not prove a live
terminal SQL CAS, family/root closure or final-result insertion.

## Remaining work and dispatch limits

The authorized terminal transition **run8/cancelling to run9/cancelled,
family2 to3**, original cancellation application and immutable typed result
remain unperformed. The permanent remaining intent is unused. R2A and R2B phase
one remain consumed and must never be replayed. Provider admission, default
Current/ramp changes and unrelated workflow serving remain forbidden by this
closure envelope.

This worker stops after the prelaunch refusal and independent readback. A later
explicitly coordinated dispatch must retain the same reviewed envelope, refresh
only expiry within the approved650s policy, and repeat capacity/source/principal/
state/routing/intent gates. It must not interpret this refusal as proof that
live gates or SQL acceptance passed, nor weaken the memory threshold. Existing
owner authority is recorded; no duplicate human permission question was issued.

The sprint remains incomplete: native/local enforcement, remote providers,
real G1 serving, Cursor login, inclusive budget evidence, release/data and the
original S0/LS/R/S1/S2/S3 qualification still require their original evidence.
The [issue-by-issue audit](RUN-2-ISSUE-STATUS-2026-10-17.md) distinguishes these
gates from completed source changes and added recovery work.
