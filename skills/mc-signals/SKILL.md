---
name: mc-signals
description: Report milestones, blockers, requests for input, ready artifacts and progress back to Mission Control from inside a mission workspace with mc-signal. Use whenever you finish a meaningful step, get stuck, need a human or another agent to act, or produce an artifact someone is waiting for; signals are the only channel back, so never write status, ledger or stop files instead.
---

# Signal Mission Control

Mission Control watches this workspace through signals. Hooks already report the session
start, tool and subagent activity and the end of each turn; you add what only you know.
A signal is evidence: it can wake the coordinator or a watcher, but it never changes the
run's state by itself, and nobody replies through it. Do not wait for an answer.

## Emit

```text
.mission/bin/mc-signal milestone "tests green" --data '{"passed": 412}'
.mission/bin/mc-signal blocked "need staging DB credentials"
.mission/bin/mc-signal needs_input "which license header should new files carry?"
.mission/bin/mc-signal artifact.ready "report drafted" --data '{"path": "outputs/report.md"}'
.mission/bin/mc-signal progress "3 of 7 modules migrated"
```

Without a POSIX shell, run `python .mission/hooks/signal emit <type> [message] [--data JSON]`.
An MCP client configured with the Mission Control signals server can call `signal_emit` with
the same `type`, `message` and `data`.

- `type` is lowercase words joined by dots or underscores. Prefer the five above.
- `message` is one short sentence for a human. `--data` is a JSON object (64 KiB at most)
  with facts a watcher can match on: counts, paths, ids.
- The command prints `{"signal_id", "seq", "delivered"}`. `delivered: false` means the
  signal is spooled under `.mission/state/signals/` and goes out with the next upload; do
  not repeat it.

## When

| Moment | Type |
| --- | --- |
| A step the plan names is done and verified | `milestone` |
| You cannot continue without something outside the workspace | `blocked` |
| A decision belongs to a human or the coordinator | `needs_input` |
| An output file is complete and others can use it | `artifact.ready` |
| A long task passes a natural checkpoint | `progress` |

Emit once per moment. Never put secrets, tokens, credentials or personal data in a message
or in `--data`: signals are stored and shown to other agents as untrusted data.

## Never

- Never create status files, ledgers, `DONE` markers or stop files to report state.
- Never poll or sleep waiting for Mission Control to react to a signal.
- Never edit `.mission/hooks/`, `.mission/signal-policy.json` or the spool.
