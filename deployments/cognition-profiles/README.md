# Cognition Profiles

The per-application `mc.app.<app>.cognition-profiles@1.0.0` seed publishes
`plugin.cognition-sdlc`, `plugin.cognition-knowledge` and `plugin.cognition-mixed`.
Their searchable titles are `cognition/sdlc`, `cognition/knowledge` and
`cognition/mixed`; capability identifiers cannot contain `/`.

SDLC contains TDD, code review, publication and bug diagnosis skills with reviewer
and test-runner subagents. Knowledge contains research, citation verification,
ingestion and Knowledge Services guidance with source-verifier and summarizer
subagents. Mixed is their union, with four subagents (below Cursor's limit of 20).
The renderer adds kernel hooks and additive repository instructions; the telemetry
pack is composed by the observation integration rather than repeated in each plugin.
Native provider subagents and hosted materialization retain their declared
degradation and qualification status.

The six `.mission.yml` files are shape-valid authoring examples with exact profile
pins for each application. Their fixture goals, model and capability selections
must be replaced for the intended mission. Use only one profile per execution unit:
mixed already contains both families, and duplicate selections are refused.

Knowledge missions must extend the manifest with the application's admitted remote
Knowledge Services MCP pin and egress policy. This repository has no configured
endpoint or authoritative MCP schema to publish, so the seeds do not invent one.
The Knowledge Services skill refuses an absent binding. Output custody and
`artifact.ready` emission are explicit skill instructions; completion still needs
the mission's Completion Contract.

Generate with `python packages/mission-control-db-contract/seeds/generate_catalog_seeds.py --write`.
Publish bundle bytes through `scripts/seeds_publish_bundles.py` before applying the
new seeds. Existing seed versions are preserved. This change performs no live seed
apply and qualifies no provider profile.
