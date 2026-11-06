# Standard watcher examples

Each mission/v2 manifest is a complete authoring example with an inline copy of one
standard template. Resolve its normal model/sandbox/capability selections against
the application catalog before launch. The catalog versions are also published in
`mc.app.<application>.watchers@1.0.0`; pin exact definitions under controls.watchers
and only narrow their limits. These files are fixtures, not executed provider runs.

| Template | Evidence and reaction |
| --- | --- |
| stall-detector | No frame/signal for 20m while active: blocked notification and inspection probe, max 2 |
| result-marker-stop | Trusted worker.log matched: progress notification and admitted cancel, max 1 |
| ci-watch | GitHub check-suite failure: queued repair instruction, max 3, 10m apart, 50k token ceiling |
| pr-merged-release-wait | Trusted merged PR: satisfy the declared await-merge wait, max 1 |
| artifact-pipeline | PDF artifact.ready: notify and queue next ingestion-stage instruction, max 10 |
| budget-guard | Trusted budget.threshold exhausted report: blocked notification and admitted pause, max 1 |
| heartbeat-progress | progress signal: notification, max 24, 5m apart |

Operator source registrations bind GitHub checks/PR reads and worker log watches
to a live run execution/generation and owning worker host (MO45). Configure the
result marker's literal log pattern through that trusted registration. Match data
does not contain log contents. Provider webhook draining is the separate MO75 seam.

Result markers never settle successful completion. Artifact evidence never admits
an artifact or bypasses custody; this template continues an already admitted pipeline.
Automatic watcher launch actions remain unavailable. Budget reports are advisory;
the canonical budget governor remains authoritative. Event-wait execution declares
the wait before the PR watcher releases it; early matching evidence is held.

Tests compile every example, exercise every source/condition in the pure planner,
and prove all seven template action paths and firing deduplication on real PG17.
