# Mission Manifest cheatsheet (`manifest: mission/v1`)

Condensed from ADR-0022, ADR-0034 and `docs/specs/fast-track-2026-10/SPEC-05-mission-manifest.md`.
The JSON Schema exported beside the contracts is authoritative; this page is the shape to start from.

For current Codex 0.162.1 authoring, use
[`manifest-launch-bindings.multi-provider.codex-0.162.1.example.json`](../../../deployments/examples/manifest-launch-bindings.multi-provider.codex-0.162.1.example.json)
with owner-reviewed selections. The older multi-provider example remains historical;
its 0.162.0 pins are refused by the refreshed adapter rather than rewritten in place.

## Top level

```yaml
manifest: mission/v1
mission: { ... }            # exactly one of `mission` or `missions`
# missions: [ { key: research, ... }, { key: ingestion, ... } ]
# links:    [ { from: research.sources, to: ingestion.inputs.sources, kind: supplies, release_on: goal_accepted } ]
```

## Mission block

```yaml
mission:
  key: literature-sweep            # stable, lower-kebab
  title: Literature sweep on NAD+ precursors and skeletal muscle
  domain_pack: biotech.research    # app-owned templates, rubrics, prompts (optional)
  goals:
    - key: evidence_map
      description: Map the human evidence for NMN/NR effects on muscle function
      importance: primary          # primary | secondary | optional
      criteria:
        - key: coverage
          evidence: [source_manifest, claim_table]
          acceptance: { assessment: biotech.evidence_coverage, threshold: 0.8 }
        - key: reviewed
          acceptance: { human: review_accept }
  inputs:
    - { name: brief, artifact: "artifact://…", expand: inline }
  environment: { ... }             # mission-level defaults (below)
  program: { ... }                 # one program node, usually stage_graph or goal_loop
  controls:
    commands_allowed: [pause, cancel, queue_instruction, add_context, interrupt_and_inject, fork]
    # mission/v1 notifications are unconsumed and warn; use mission/v2 below.
```

## Environment (mission level; nodes overlay by deep merge, lists replace)

```yaml
environment:
  lane: deep_agents                # deep_agents | cursor_local | cursor_cloud
  model: { profile: frontier.default }
  sandbox: { profile: research.standard, egress: [pubmed, biorxiv] }
  workspace:
    repo: { url: "https://…", ref: main }        # cursor lanes; optional for deep_agents
    context: [ .mission/brief.md, "biotech.schema_context@search:muscle aging" ]
    skills: [ "skill.mission-control-observe@0.1.0#sha256:…" ]
  capabilities:
    - { search: "pubmed literature retrieval", kind: mcp_server, as: pubmed, require: [deep_agents] }
    - { pin: "mcp.tavily@0.2.22#sha256:…", as: web }
  agents:                          # subagent profiles
    - { pin: "agent.verifier@0.1.0#sha256:…" }
  hooks:                           # hook scripts with the events they run at
    - { pin: "hook.pre-tool-use-policy@0.1.0#sha256:…", events: [before_tool, before_shell] }
  plugins:
    - { pin: "plugin.research-web@0.1.0#sha256:…" }
  side_effects: [read_only, workspace_write]      # closed vocabulary; nodes may only narrow
  budget: { usd: 25, tokens: 2_000_000, wall_clock: 4h }
  governors: { depth: 2, fan_out: 6, iterations: 8, transfers: 3 }
```

Inheritance: a node without `environment` runs with the mission's. A node with
`environment: { budget: { usd: 10 } }` keeps every other mission value and replaces `budget.usd`.
`capabilities`, `agents`, `hooks`, `plugins`, `skills` and `context` are lists: a node that
declares one replaces the mission list for that key. Widening budget, governors or
`side_effects` at node level is a compile blocker (`ENVIRONMENT_WIDENS_AUTHORITY`).

## Program nodes

```yaml
program:
  behavior: stage_graph
  nodes:
    - key: collect
      behavior: goal_loop
      objective: evidence_map
      action_space: [pubmed, web]                 # aliases from capabilities
      environment: { budget: { usd: 10 }, governors: { iterations: 5 } }
      outputs: [ { name: sources, schema: source_manifest@1 } ]
    - key: synthesize
      behavior: agent_executor
      depends_on: [collect]
      inputs: [ { from: collect.sources, expand: materialize } ]
      outputs: [ { name: claims, schema: claim_table@1 } ]
    - key: review
      behavior: human_gate
      depends_on: [synthesize]
      task: { kind: review, reviewers: [owner], packet: [synthesize.claims] }
    - key: ingest
      behavior: deterministic_executor
      depends_on: [review]
      executor: biotech.ingestion.apply
      inputs: [ { from: synthesize.claims } ]
```

Behaviors: `stage_graph`, `goal_loop`, `parallel_swarm`, `evaluator_optimizer`,
`agent_executor`, `deterministic_executor`, `event_wait`, `timer`, `human_gate`, `proof_gate`,
`child_mission_invocation`. Lane support per behavior is validated at compile (a Parallel Swarm
runs only on `deep_agents` until qualified).

## Links (chains)

```yaml
links:
  - { from: research.sources, to: ingestion.inputs.sources, kind: supplies,
      release_on: goal_accepted,        # goal_accepted | mission_accepted | execution_complete
      on_upstream_cancel: cancel_downstream }   # cancel_downstream | detach
  - { from: research, to: ingestion, kind: depends_on }
```

## Watchers and notifications (`manifest: mission/v2` only)

```yaml
controls:
  commands_allowed: [pause, queue_instruction, satisfy_wait]
  notifications: { on: [run.completed, human_task.opened, blocked], channel: inbox }  # inbox only
  watchers:                        # see docs/knowledge/watchers.md
    - id: stalled
      on: { absence: { of: [frame, signal], for: 20m }, while: "run.phase == 'active'" }
      then: [ { notify: { kind: blocked, text: "No progress for 20 minutes" } }, { probe: {} } ]
      limits: { max_fires: 2 }
```

One trigger (`event`, `signal`, `absence`, `schedule`); `where`/`while` use the closed condition
grammar; actions are `notify`, `instruct`, `satisfy_wait`, `command` (pause, cancel,
request_continuation) and `probe`; `commands_allowed` must grant every command a watcher issues.
`channel: mcp` is rejected.

`mission/v2` notifications are consumed as notify-only watchers, implemented by
`src/mission_control/domain/authoring/mission_watchers.py` and exercised in
`tests/unit/watchers/test_watcher_manifest.py`. `mission/v1` emits
`notifications_unconsumed`; a parsed declaration is not a delivered notification.
For caller wakeup, use the observe skill's durable inbox wait/inspect/ack workflow.

Standard catalog templates are stall-detector, result-marker-stop, ci-watch,
pr-merged-release-wait, artifact-pipeline, budget-guard and heartbeat-progress.
Resolve an exact `watcher` pin with the catalog skill before inserting it; a pinned
entry names `id`, `pin` and optional narrower `limits`. Driving signal reactions need
at least provider_signed trust (`limits.min_trust`); keep max_fires and intervals bounded.
External worker/poll sources need explicit operator registrations for a live execution;
webhook draining requires the configured worker ingress path and its exact-placement
PostgreSQL/Temporal proof. Webhook delivery only wakes native reconciliation; it does not
grant acceptance or publication. Automatic launch actions and manifest watch/cron
syntax are unavailable. Use schedule/absence triggers supported by the compiler.

## Unsupported composition syntax

`templates:` and `extends:`. Do not write them; the compiler rejects unknown keys.
