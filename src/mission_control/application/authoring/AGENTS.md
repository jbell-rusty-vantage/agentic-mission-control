<!-- BEGIN:sdlc-module id=application.authoring -->
# Authoring use cases
Mission Manifest compile, submit and start use cases. Also the production launch inputs of a manifest run, per-lane launch bindings (local providers and Cursor), the subagent discriminator and the control-plane repository port.
Entrypoints:
- manifest_launch_inputs.py — Production launch inputs of a manifest run
- manifest_service.py — Mission Manifest compile
- manifest_v2_admission.py — mission/v2 compile admission
- provider_launch.py — Deployment launch bindings of the local provider lanes
- manifest_submit.py — Mission Manifest submit and start
- service.py
- cursor_launch.py — Deployment launch bindings of the Cursor lanes
- purpose_card.py — The Purpose Card: why the mission exists and what this node's part is, for every…
- subagent_discriminator.py — Compile-time subagent discriminator: one profile, every lane it may run on, a…
- run_brief.py — Reading a run's Mission Brief back: the brief its revision's definition seals
Also: control_plane_repository.py, goal_verifier_objective.py, completion_support.py, manifest_fork_admission.py, subagent_support.py, capability_summaries.py
Tests: tests/unit/authoring, tests/unit/control_plane, tests/unit/deep_agents
Invariants:
- Fail closed at fresh launch when authored acceptance has no runtime evaluator.
Explained by (docs/knowledge): mission-manifest, authoring, environments, agent-configuration, cursor-lane, deep-agents-children
Decided by (docs/adr): ADR-0022, ADR-0034, ADR-0063, ADR-0006, ADR-0015
Depends on: domain.authoring, domain, domain.execution, domain.programs, application.programs, application.environments (+1) · Used by: bootstrap, adapters.temporal, application.programs, adapters.deep_agents, interfaces.http, adapters.postgres (+2)
Verify: uv run pytest tests/unit/authoring tests/unit/control_plane
<!-- END:sdlc-module -->
