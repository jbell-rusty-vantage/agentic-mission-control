---
id: control
title: Steer, cancel and fork a run
summary: The interventions, the rules each one obeys, what every lane does with them, and the call for each.
---
An intervention changes what a running mission reads, when it reads it, or which run continues. It never changes the run's program, policy, authority or budget, and it never fulfils or waives a promised output.

## Rules for every intervention

1. Inspect first with {op:inspect}. A command names `expected_version` (the inspection's `version`) and `expected_generation` (its `execution_generation`). A stale value is refused with the current ones: inspect again.
2. Admission is not delivery. The receipt says the command was accepted; the Delivery Report in the next inspection says what the lane did with it.
3. Retry with the same `request_id` and the same body. A new id is a new command.
4. When a notification is the reason, send the command with {op:inbox_command}: it is recorded as caused by that notification and bounded by the inbox's rate and recursion limits.

## The interventions

| Intervention | `kind` | What happens | Call |
| --- | --- | --- | --- |
| Queue an instruction | `queue_instruction` | Read once at the next turn or iteration boundary; work continues. | {op:command_queue} |
| Add context | `add_context` | An artifact or a short note joins the next Context Packet. | {op:command_add_context} |
| Interrupt and inject | `interrupt_and_inject` | Delivered now, in the way the lane declares below. | {op:command_inject} |
| Cancel | `cancel` | `urgency: normal` stops at the next safe boundary. `immediate` first writes a Stop Fence: every later effect of the run is denied; a tool already dispatched is not halted. | {op:command_cancel} |
| Pause, resume, satisfy a wait, request continuation | `pause`, `resume`, `satisfy_wait`, `request_continuation` | Applied at a boundary. A resume adds no authority or budget. | {op:command} |
| Fork | its own call | Admits a new run from a Snapshot of this one, optionally from a cognition point and with a first instruction. The source run is never written, its in-flight commands and active children are not copied, and the fork is admitted, not started. | {op:fork}, then {op:start} |
| State as of | read-only | The agent's state at one cognition point. | {op:points}, then {op:state_as_of} |

Read the full request of a command or a fork with {op:describe_tool}.

## What each lane does

{{generated}}

Delivery: `turn_boundary_guaranteed` at the next turn boundary; `wait_then_send` once the running turn ends; `cooperative_inject` joins the next model call and the turn continues; `cancel_and_replace` cancels the running turn, settles its uncertain effects and runs a replacement turn on the same session (an effect that cannot settle parks the unit `in_doubt`); `pause_at_tool_gate` holds the turn at its next tool call; `emulated` Mission Control provides it around the provider; `unsupported` a typed rejection.

Restore: `R0` the packet only; `R1` plus the transcript to the point; `R2` plus the workspace files; `R3` the provider's own state. A fork starts from a cognition point only where the lane's fork level is `R1` or above.
