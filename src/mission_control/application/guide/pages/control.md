---
id: control
title: Steer, cancel and fork a run
summary: The interventions, the rules each one obeys, what every lane does with them, and the call for each.
---
An intervention changes what a running mission reads, when it reads it, or which run continues. It never changes the run's program, policy, authority or budget, and it never fulfils or waives a promised output.

## Rules for every intervention

1. Inspect, send, and on `stale_version` resend once. {op:inspect} gives `expected_version` (its `version`) and `expected_generation` (its `execution_generation`). A version moves with every event, so a command beside running work is often stale: nothing was admitted and the refusal carries the current values. Resend once with them; if stale again, inspect and decide.
2. Admission is not delivery. The receipt says the command was accepted; the Delivery Report in the next inspection says what the lane did with it.
3. Repeat a request whose answer you lost with the same `request_id` and body. A new id is a new command.
4. When a notification is the reason, send the command with {op:inbox_command}: it is recorded as caused by it and bounded by the inbox's limits.

## The interventions

| Intervention | `kind` | What happens | Call |
| --- | --- | --- | --- |
| Queue an instruction | `queue_instruction` | Read once at the next turn or iteration boundary; work continues. | {op:command_queue} |
| Add context | `add_context` | An artifact or a short note joins the next Context Packet. | {op:command_add_context} |
| Interrupt and inject | `interrupt_and_inject` | Delivered now, in the way the lane declares below. | {op:command_inject} |
| Cancel | `cancel` | `urgency: normal` stops at the next safe boundary. `immediate` first writes a Stop Fence: every later effect of the run is denied; a tool already dispatched is not halted. | {op:command_cancel} |
| Pause, resume, satisfy a wait, request continuation | `pause`, `resume`, `satisfy_wait`, `request_continuation` | Applied at a boundary. A resume adds no authority or budget. | {op:command} |
| Fork | its own call | Admits, never starts, a new run from a Snapshot of this one, optionally from a cognition point and with a first instruction, under a `sponsorship_ref` you hold ({op:whoami}). The source run is not written; its in-flight commands and active children are not copied. | {op:fork}, then {op:start} |
| State as of | read-only | The agent's state at one cognition point. | {op:points}, then {op:state_as_of} |

A fork needs a Snapshot, taken only at a safe boundary: a run waiting at a Human Gate refuses it (`CHECKPOINT_INVALID`) until the gate is resolved or the run ends. {op:describe_tool} gives the full request of a command or a fork, and when a fork is possible.

## What each lane does

{{generated}}

Delivery: `turn_boundary_guaranteed` at the next turn boundary; `wait_then_send` once the running turn ends; `cooperative_inject` joins the next model call; `cancel_and_replace` cancels the running turn, settles its uncertain effects and runs a replacement turn on the same session (an effect that cannot settle parks the unit `in_doubt`); `pause_at_tool_gate` holds the turn at its next tool call; `emulated` Mission Control provides it around the provider; `unsupported` a typed rejection.

Restore: `R0` the packet only; `R1` plus the transcript to the point; `R2` plus the workspace files; `R3` the provider's own state. A point seeds a fork only where the lane's fork level is `R1` or above.
