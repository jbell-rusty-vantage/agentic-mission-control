---
name: mission-control-signals
description: How a Mission Control knowledge agent prepares its session and reports lifecycle signals. Use at the start of every session and whenever a mission step finishes.
---

# Mission Control signals

1. Call `mc_prepare` first. Run the returned commands in order with `bash`, from the working
   directory it names. Do not run anything else before they finish.
2. Call `mc_signal` with `name: env.prepared` once every command succeeded. If a command
   failed, stop and report which one; do not signal readiness.
3. When a mission step finishes, call `mc_signal` with the step name the mission gave you.
4. Put deliverables in `/mnt/session/outputs/`; Mission Control collects them after the turn.
