# Cognition Profiles

The per-application `mc.app.<app>.cognition-profiles` seeds publish
`plugin.cognition-sdlc`, `plugin.cognition-knowledge` and `plugin.cognition-mixed`.
Their searchable titles are `cognition/sdlc`, `cognition/knowledge` and
`cognition/mixed`; capability identifiers cannot contain `/`.

SDLC contains TDD, code review, publication and bug diagnosis skills with reviewer
and test-runner subagents (revision 1, seed 1.0.0). Knowledge is at revision 2
(seed 1.0.1): it mounts the method skills their owning repositories maintain,
`skill.knowledge-research` (the research and verification method with its tool
playbooks) and `skill.knowledge-verify` (source capture as evidence), then the
application's knowledge charter (`skill.<app>-knowledge-charter`), with
source-verifier and summarizer subagents. Mixed is their union, with four
subagents (below Cursor's limit of 20). Revision 1 of knowledge and mixed mounted
four eight-line `mc-cognition-*` knowledge skills; it stays in the catalog for
missions that pinned it, and `@latest` resolves to revision 2.

The method skills are exact copies, imported at one commit into
`packages/mission-control-db-contract/bundle-sources/imported/` and published by
`mc.app.<app>.agent-skills@1.0.5`; `scripts/skills_import.py --check` holds the
copies to their recorded digests. A revision 2 plugin's host support is the
intersection of its members': supported on the worker-hosted lane profiles, and on
the provider-hosted ones unqualified for `ai-engineer` and unsupported for
`biotech`, whose charter row declares the worker-hosted profiles only. The renderer adds kernel hooks and
additive repository instructions; the telemetry pack is composed by the
observation integration rather than repeated in each plugin.

The six `.mission.yml` files are shape-valid authoring examples with exact profile
pins for each application. Their fixture goals, model and capability selections
must be replaced for the intended mission. Use only one profile per execution unit:
mixed already contains both families, and duplicate selections are refused.

A knowledge mission also selects its knowledge tools and, where it reads a remote
Knowledge Services endpoint, the application's admitted MCP pin and egress policy.
Since 2026-11-16 the common seed `mc.catalog.agent-capabilities@1.1.0` publishes
the executor's capture, source, schema and guide tools as `mcp.knowledge-capture`,
with a tool list captured from a running executor. It is `unqualified` on every
lane and a member of no profile: no lane can yet narrow the executor's 40 tools to
that allowlist, and a deployment binds its own endpoint (the
[capability seeds concept](../../docs/knowledge/capability-seeds.md#not-wired-or-not-published)
says what is missing). The charter in the plugin is the one compile
mounts on a knowledge mission anyway (`[knowledge] charter_skill`): a mission that
selects the plugin gets it once. Output custody and `artifact.ready` emission are
explicit skill instructions; completion still needs the mission's Completion
Contract.

Generate with `python packages/mission-control-db-contract/seeds/generate_catalog_seeds.py --write`.
Publish bundle bytes through `scripts/seeds_publish_bundles.py` before applying the
new seeds. Existing seed versions are preserved. This change performs no live seed
apply and qualifies no provider profile.
