"""Generate issues.json, issues/*.md and ISSUES.md for the materialization-observation packet."""

import json
import pathlib
import re
import sys

PACKET = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent
P = "docs/specs/materialization-observation-2026-10"


def issue(iid, title, owner, wave, size, spec, deps, paths, problem, work, acceptance):
    return {
        "id": iid,
        "title": title,
        "owner": owner,
        "wave": wave,
        "size": size,
        "spec": spec,
        "deps": deps,
        "paths": paths,
        "problem": problem,
        "work": work,
        "acceptance": acceptance,
    }


ISSUES = [
    # ---------------- W0 unblock and correct ----------------
    issue(
        "MO-01",
        "Compose bundle custody into every production capability rows resolver",
        "Integrator",
        "A",
        "S",
        "SPEC-02-cognition.md",
        [],
        [
            "bootstrap/manifests.py",
            "adapters/temporal/provider_lane_composition.py",
            "adapters/temporal/deployment_composition.py",
            "application/capabilities/bundle_custody.py",
            "tests/integration/",
        ],
        "CatalogProjectionRows/CatalogRows are built without custody, so every skill bundle and hook script raises 'custody is not configured' on every lane in production (gap G1, handoff C5).",
        [
            "Pass the configured BundleCustody (local FS or Supabase bucket) into all rows resolvers at bootstrap/manifests.py:213, provider_lane_composition.py:103,163, deployment_composition.py:628,672.",
            "Workers fetch bundles through signed URLs per ADR-0024; cache by digest.",
            "Fail launch with a typed error when custody is unavailable instead of at materialization time.",
        ],
        [
            "Integration test: one skill bundle and one hook-script pin materialize with matching digests on cursor_local, claude_agent_sdk and codex through production composition.",
            "Missing custody is a launch-time typed refusal, not a worker crash.",
        ],
    ),
    issue(
        "MO-02",
        "Additive instruction layering and structural config merge",
        "Environment",
        "A",
        "M",
        "SPEC-02-cognition.md",
        ["MO-01"],
        [
            "application/agentic_components/materialization.py",
            "application/agentic_components/projections.py",
            "adapters/cursor/projection.py",
            "adapters/claude/harness.py",
            "adapters/codex/harness.py",
        ],
        "Cursor overwrites the repo AGENTS.md; Claude/Codex refuse repos that already have AGENTS.md, CLAUDE.md, .mcp.json or settings (gap G8).",
        [
            "Cursor: mission overlay as .cursor/rules/mc-mission.mdc (alwaysApply); never touch AGENTS.md.",
            "Claude: never create CLAUDE.md; local overlay through system_prompt preset append; cloud overlay .claude/rules/mc-mission.md.",
            "Codex: developerInstructions on thread/start locally; merged AGENTS.override.md (repo AGENTS.md + delimited mission section, <=32 KiB) for cloud.",
            "Structural merge for .claude/settings.json, .cursor/hooks.json, .codex/hooks.json, .mcp.json, .codex/config.toml with provenance markers and materialization.conflicts policy; receipt lists merged keys.",
        ],
        [
            "A fixture repo with its own AGENTS.md, .claude/skills and .cursor/hooks.json launches on all three local lanes; repo files are byte-identical after the run.",
            "Discovery reports both repo and mission items; conflicts follow the declared policy.",
        ],
    ),
    issue(
        "MO-03",
        "Back Codex kernel hooks and handle Codex hook trust",
        "Runtime",
        "A",
        "M",
        "SPEC-02-cognition.md",
        ["MO-01"],
        [
            "adapters/codex/harness.py",
            "adapters/codex/compose.py",
            "adapters/cursor/kernel_hook_script.py",
            "interfaces/http/hook_callback.py",
            "docs/qualification/release/multi-provider-2026-10.md",
        ],
        ".codex/hooks.json calls .mission/hooks/kernel.py which the Codex lane never writes; no hook callback service or token is composed; non-managed hooks need hash trust (gap G11).",
        [
            "Write kernel.py, context.json and the per-execution token in the Codex lane exactly as cursor_local does; compose HookCallbackService for codex.",
            "Record hook trust for exact digests in the isolated CODEX_HOME or install kernel hooks as managed requirements (resolve Q-X2).",
            "Correct the release statement until a live drill proves fail-closed hooks.",
        ],
        [
            "Live Codex CLI drill: kernel before_tool deny enforced end to end.",
            "Release statement matches evidence.",
        ],
    ),
    issue(
        "MO-04",
        "Allowlisted child environments for local provider processes",
        "Runtime",
        "A",
        "S",
        "SPEC-01-environments.md",
        [],
        [
            "bootstrap/provider_auth.py",
            "adapters/claude/transport.py",
            "adapters/codex/launcher.py",
            "adapters/cursor/bridge.py",
        ],
        "The Claude CLI inherits the whole worker environment (DB DSNs, other provider keys); Codex strips secrets its MCP servers need (gap G12).",
        [
            "Start every provider child from an empty env plus an explicit allowlist (auth route, kit-declared variables, per-MCP env).",
            "Pass declared MCP secret env to Codex servers.",
            "Correct HANDOFF-2026-10-10 'credential-free' statement.",
        ],
        [
            "Sentinel test proves only allowlisted names reach each child process on all local lanes."
        ],
    ),
    issue(
        "MO-05",
        "All local lanes use WorkspaceAllocator with manifest policy and cleanup",
        "Runtime",
        "A",
        "M",
        "SPEC-03-workspaces-and-placement.md",
        [],
        [
            "adapters/codex/harness.py",
            "adapters/cursor/local.py",
            "adapters/temporal/provider_lane_composition.py",
            "application/workspaces/service.py",
            "adapters/temporal/workflows/",
        ],
        "Codex and Cursor local ignore the manifest workspace policy; WorkspaceAllocator.cleanup and join_shared have no production callers (gap G10).",
        [
            "Route Codex and Cursor local through WorkspaceAllocator.allocate with the manifest policy.",
            "Invoke cleanup from the operation workflow after Artifact registration and liability settlement; never force-delete unsnapshotted dirty work.",
            "Make shared_checkout reachable through join_shared.",
        ],
        [
            "within_run reuse and cleanup verified on all local lanes; snapshots retained; dirty work preserved."
        ],
    ),
    issue(
        "MO-06",
        "Compose cursor_cloud with env resolver and workspace lease in production",
        "Runtime",
        "A",
        "S",
        "SPEC-01-environments.md",
        [],
        ["adapters/temporal/deployment_composition.py", "adapters/cursor/cloud.py"],
        "cursor_cloud is composed without env_resolver and workspaces, so env_vars_ref is UNSUPPORTED_BEHAVIOR and no provider-workspace lease is recorded.",
        [
            "Compose env_resolver (Secret Broker adapter once MO-11 lands; worker env meanwhile) and the WorkspaceAllocator into compose_cursor_cloud."
        ],
        [
            "Production-composition test records a provider-workspace lease and resolves env_vars_ref."
        ],
    ),
    issue(
        "MO-07",
        "Reconcile stale documentation and status statements",
        "Integrator",
        "A",
        "S",
        "GAP-REPORT.md",
        [],
        [
            "docs/knowledge/capabilities.md",
            "docs/knowledge/cursor-lane.md",
            "docs/knowledge/lanes-and-harness.md",
            "docs/qualification/release/multi-provider-2026-10.md",
            "skills/mission-control-author/references/manifest-cheatsheet.md",
            "skills/mission-control-observe/SKILL.md",
        ],
        "Several docs claim behaviour the code does not have (gap G17).",
        [
            "Fix each statement listed in research/codebase-materialization.md §4 and codebase-observation.md §7.",
            "Remove or flag controls.notifications and mission_subscribe guidance until wired.",
        ],
        ["python docs/tools/validate_okf.py passes; every corrected statement cites code."],
    ),
    issue(
        "MO-08",
        "WSL2 worker runbook and host preflight for local Claude and Codex lanes",
        "Environment",
        "A",
        "S",
        "SPEC-03-workspaces-and-placement.md",
        [],
        ["docs/MISSION_CONTROL_LOCAL_API.md", "bootstrap/preflight", "scripts/"],
        "Local Claude and Codex lanes refuse Windows hosts; the owner's machine is Windows (gap G16, decision D5).",
        [
            "Document and script a WSL2 worker with the workspace root on the WSL filesystem and pinned CLIs.",
            "Preflight checks host OS, CLI versions and auth per lane.",
        ],
        ["Preflight passes on the owner's WSL2 worker for claude_agent_sdk and codex."],
    ),
    # ---------------- environment model ----------------
    issue(
        "MO-10",
        "mission/v2 environment additions with validation and binding population",
        "Integrator",
        "B",
        "M",
        "SPEC-01-environments.md",
        ["MO-01"],
        [
            "domain/authoring/manifest_v2.py",
            "domain/execution/bindings.py",
            "application/authoring/manifest_launch_inputs.py",
            "contracts/schemas/",
        ],
        "The manifest cannot express variables, secrets, kits, network, git write or provider environment strategy (gap G2).",
        [
            "Add kit, variables, secrets, network, git, provider_environment to EnvironmentV2 with inheritance rules (no widening).",
            "Compile-time check of kit requires vs declared variables/secrets/egress; secret names only in bindings.",
            "Populate EnvironmentBinding.setup_pin, secret_refs, network_policy_ref, observed_config_digest, readiness.",
            "Relax repo requirement per profile (SPEC-03 §4 correction).",
        ],
        [
            "One manifest compiles offline for all profiles; mismatches are validation errors with JSON pointers; regenerated schemas reproducible."
        ],
    ),
    issue(
        "MO-11",
        "Secret Broker port, sources, minting, per-lane delivery and redaction",
        "Environment",
        "B",
        "L",
        "SPEC-01-environments.md",
        ["MO-04"],
        [
            "application/secrets/",
            "adapters/secrets/",
            "bootstrap/",
            "adapters/cursor/",
            "adapters/claude/",
            "adapters/codex/",
        ],
        "Secrets resolve only from the worker env; keyring/secret refs are accepted but never resolved; no minted per-run credentials.",
        [
            "Port with keyring/file source and Supabase Vault adapter; provider_held verification.",
            "mint:signal_token bound to scope/run/unit/generation, digest stored, expiry.",
            "Delivery adapters: process env allowlist, Cursor env/team secrets API and launch envVars, provider vaults (Anthropic, OpenAI).",
            "Exact-match redaction for frames/logs/receipts; pre-commit scan of every Mission Control commit to mission branches.",
        ],
        [
            "Sentinel secret appears in no commit, frame, log or binding.",
            "Minted token expires and is bound; wrong-run use rejected.",
        ],
    ),
    issue(
        "MO-12",
        "Environment Kit capability kind, mission layer and bootstrap entrypoint",
        "Environment",
        "B",
        "L",
        "SPEC-01-environments.md",
        ["MO-01", "MO-10"],
        [
            "domain/capabilities/",
            "application/capabilities/",
            "application/environments/",
            "skills/ or catalog seeds",
            "packages/mission-control-db-contract",
        ],
        "Nothing provisions packages/runtimes or runs setup; no readiness receipt (gap G2/G3).",
        [
            "Add Capability Kind environment_kit with mc.environment_kit.v1 manifest.",
            "Render .mission/setup/run from kit mission steps; receipt.json contract; bootstrap entrypoint per lane.",
            "Publish starter kits: python-uv, node, python-uv-node, mission-control-dev, knowledge-research, biotech-backend.",
        ],
        [
            "Local lanes reach readiness 'prepared' with a receipt; kits searchable in the catalog with host_support."
        ],
    ),
    issue(
        "MO-13",
        "Cursor environments and secrets REST adapter (bind/sync) with environment.json ownership check",
        "Runtime",
        "B",
        "M",
        "SPEC-01-environments.md",
        ["MO-11", "MO-12"],
        [
            "adapters/cursor/cloud_api.py",
            "adapters/cursor/environments.py",
            "application/environments/",
        ],
        "Cursor launch sends only env.type; deployment environment_ref is never transmitted; a committed environment.json silently overrides API environments.",
        [
            "Implement /v1/environments CRUD and secrets PUT/DELETE; naming mc-<kit>-<digest8>; version history read-back digest.",
            "Preflight check: committed .cursor/environment.json mc-owned / foreign / absent.",
            "Resolve Q-C1 (start on startingRef) and Q-C2 (envVars) by drill before relying on them.",
        ],
        [
            "Drill: environment created once, reused by a second mission; foreign committed file refused; secret names synced."
        ],
    ),
    issue(
        "MO-14",
        "Git write path: scoped credentials, pre-push guard, repo_pr effect and head SHA artifacts",
        "Environment",
        "B",
        "M",
        "SPEC-01-environments.md",
        ["MO-05"],
        [
            "adapters/workspaces/git_workspaces.py",
            "application/effects/",
            "adapters/github/",
            "adapters/cursor/scm.py",
        ],
        "No push/PR path for local lanes; repo_commit never pinned; cloud push uses ambient worker credentials.",
        [
            "Worktree-scoped credential helper using a Mission Control GitHub App installation token (owner gh fallback).",
            "Mission Control-owned pre-push guard allowing only mc/{run}/*.",
            "repo_pr Governed Effect; head SHA artifacts for every lane (Claude-Session trailer, Cursor branch lookup).",
        ],
        [
            "Push to a non-mc ref rejected; draft PR created through the effect and recorded with SHA."
        ],
    ),
    issue(
        "MO-15",
        "Network policy resolution and per-lane projection",
        "Environment",
        "B",
        "S",
        "SPEC-01-environments.md",
        ["MO-10"],
        ["application/environments/", "adapters/cursor/", "adapters/codex/", "adapters/claude/"],
        "sandbox.egress only enters a policy digest; nothing is enforced (gap G2).",
        [
            "Resolve network policy; project to Cursor egress fields, Codex sandbox network, Claude sandbox settings, Managed Agents limited networking, OpenAI environment allowlists, SandboxHost egress.",
            "Record enforced/advisory/unsupported per lane in the receipt.",
        ],
        [
            "Receipt honest per lane; Signal Ingress and Model Gateway hosts always included when required."
        ],
    ),
    issue(
        "MO-16",
        "Persist environment preparation records and readiness levels",
        "Integrator",
        "B",
        "M",
        "SPEC-01-environments.md",
        ["MO-10"],
        ["packages/mission-control-db-contract", "adapters/postgres/", "application/environments/"],
        "mc.environment_preparation.v1 is deferred (C15); readiness is copied from deployment declarations.",
        [
            "Common SQL migration plus seeds in the db-contract package; repository adapter; readiness ladder declared→exercised.",
            "Validation Report and Launch Ticket cite the record.",
        ],
        ["Real local PostgreSQL test; launch policy enforces the minimum readiness level."],
    ),
    # ---------------- preflight ----------------
    issue(
        "MO-20",
        "Owner prerequisite store and generated paste-ready content",
        "Environment",
        "C",
        "M",
        "SPEC-05-owner-prerequisites.md",
        ["MO-12"],
        ["domain/prerequisites/", "application/prerequisites/", "adapters/postgres/"],
        "Human-only steps are not surfaced before spawn (gap G4).",
        [
            "mc.owner_prerequisite.v1 with steps, generated content refs, verification method and freshness.",
            "Generators for Cursor, Claude, Codex, Managed Agents and OpenAI Agents items from kit/policy digests.",
            "Expiry tracking (Claude 30-day login, tokens).",
        ],
        [
            "Generated content digests match the binding; expiring credentials flagged before launch."
        ],
    ),
    issue(
        "MO-21",
        "missionctl preflight and PREREQUISITES_UNMET launch refusal",
        "Integrator",
        "C",
        "M",
        "SPEC-05-owner-prerequisites.md",
        ["MO-20"],
        [
            "interfaces/cli/main.py",
            "interfaces/http/",
            "interfaces/mcp/",
            "skills/mission-control/SKILL.md",
        ],
        "Launch fails late or silently degrades when human setup is missing.",
        [
            "Preflight CLI, HTTP endpoint and MCP tool listing unmet/stale prerequisites, degradations and reachable readiness per lane.",
            "Launch API refuses with typed PREREQUISITES_UNMET carrying the same list.",
            "Router skill rule: relay steps to the human, never work around.",
        ],
        [
            "Fresh installation plus a claude_managed manifest yields the full list and non-zero exit."
        ],
    ),
    issue(
        "MO-22",
        "missionctl setup wizard, probe missions and attestations",
        "Environment",
        "C",
        "M",
        "SPEC-05-owner-prerequisites.md",
        ["MO-21"],
        ["interfaces/cli/", "scripts/", "missions/probes/"],
        "Owner needs a guided path to complete and verify setup.",
        [
            "Wizard per provider (open URL, paste block, attest, verify) following the repo wizard skill pattern.",
            "Probe missions per cloud/API lane emitting readiness signals; prereq attest command.",
        ],
        [
            "Owner completes Cursor and Anthropic setup through the wizard; probes flip items to verified."
        ],
    ),
    # ---------------- cognition ----------------
    issue(
        "MO-30",
        "Per-lane layout table and full cognition projection",
        "Environment",
        "C",
        "M",
        "SPEC-02-cognition.md",
        ["MO-01", "MO-02"],
        [
            "domain/capabilities/layouts.py",
            "application/agentic_components/projections.py",
            "adapters/cursor/projection.py",
            "tests/fixtures/projections/",
        ],
        "Native layouts are hard-coded and partially wrong per provider; API lanes need non-file projection.",
        [
            "Data-driven layout table per profile (paths, frontmatter fields, limits).",
            "Full subagent field mapping per provider with degradation reports; skills placement; Cursor cloud inline customSubagents/mcpServers re-sent every run.",
            "API projection targets for claude_managed (agent/skills/MCP) and codex_agents (saved agent/skills/tools).",
            "Move C14 lane-neutral helpers out of adapters/cursor.",
        ],
        [
            "Golden fixtures for all nine profiles re-recorded from the fact sheets with degradation reports."
        ],
    ),
    issue(
        "MO-31",
        "Evidence-based hook event mapping and Cursor binding v2",
        "Runtime",
        "C",
        "M",
        "SPEC-02-cognition.md",
        ["MO-03"],
        [
            "domain/capabilities/hooks.py",
            "domain/execution/lanes.py",
            "application/authoring/cursor_launch.py",
        ],
        "_CODEX mapping was copied from _CLAUDE; Cursor binding cannot carry hook scripts or plugins (parity gap 15).",
        [
            "Rebuild HOOK_EVENT_MAPPING per profile with enforce/observe, cloud support, timeouts, fail-closed form.",
            "mc.cursor_binding.v2 with hook_script_pins and plugin_expansion_digest.",
        ],
        [
            "Missions 2 and 3 launch on Cursor as authored; validation rejects unsupported enforced events per lane."
        ],
    ),
    issue(
        "MO-32",
        "Plugin expansion into constituent kinds for every lane",
        "Environment",
        "C",
        "S",
        "SPEC-02-cognition.md",
        ["MO-30"],
        ["application/capabilities/plugins.py", "application/agentic_components/projections.py"],
        "Provider plugin formats differ and Claude cloud ignores repo plugins.",
        [
            "Expand catalog plugins into skills/agents/hooks/MCP; reject cycles and collisions; native plugin loading only behind qualification."
        ],
        ["One plugin yields equivalent parts on all lanes."],
    ),
    issue(
        "MO-33",
        "Ambient cognition inventory and policy",
        "Environment",
        "C",
        "M",
        "SPEC-02-cognition.md",
        ["MO-30"],
        ["application/agentic_components/materialization.py", "domain/capabilities/"],
        "Providers load cognition Mission Control did not place (Cursor reads .claude/* and .codex/agents) (gap G13).",
        [
            "Scan every root each lane loads; record ambient inventory in the receipt.",
            "Policy allow | inventory | refuse_conflicts; local suppression where providers allow.",
        ],
        ["Receipt lists ambient items on each local lane; conflicts refused under policy."],
    ),
    issue(
        "MO-34",
        "Discovery proof per lane",
        "Runtime",
        "C",
        "M",
        "SPEC-02-cognition.md",
        ["MO-30"],
        ["adapters/claude/", "adapters/codex/", "adapters/cursor/", "application/environments/"],
        "A generated file does not prove the provider loaded it (gap G14).",
        [
            "Claude init/InstructionsLoaded; Codex skills/list, hooks/list, config/read; Cursor setting read-back; materialization.observed signal for cloud; API read-back for claude_managed/codex_agents."
        ],
        ["Readiness reaches 'discovered' on local lanes, cursor_cloud and both API lanes."],
    ),
    issue(
        "MO-35",
        "Publish Cognition Profiles for SDLC, knowledge and mixed work",
        "Environment",
        "C",
        "S",
        "SPEC-02-cognition.md",
        ["MO-30"],
        ["skills/", "catalog seeds"],
        "Task families need default cognition packs.",
        [
            "Publish cognition/sdlc, cognition/knowledge, cognition/mixed as plugins/workflow templates sized to lane limits."
        ],
        ["Manifests reference them; capability search finds them."],
    ),
    # ---------------- observation ----------------
    issue(
        "MO-40",
        "Signal Ingress with trust tiers",
        "Events",
        "B",
        "L",
        "SPEC-04-watchers-and-callbacks.md",
        ["MO-11"],
        [
            "interfaces/http/ingress.py",
            "application/signals/",
            "adapters/postgres/",
            "interfaces/http/hook_callback.py",
        ],
        "No authenticated public ingress; cloud lanes are blind beyond provider APIs (gap G6).",
        [
            "Mount /v1/ingress/{signals,artifacts,provider/{p},github}; tiers run_token, provider_oidc (Cursor JWT), provider_signed (standard-webhooks/HMAC), environment_key with session binding.",
            "Persist as provider frames (source ingress), dedupe, size and rate limits; unify the loopback hook callback onto the same handler.",
        ],
        ["Per-tier accept/reject tests; real PostgreSQL persistence; duplicates dropped."],
    ),
    issue(
        "MO-41",
        "Telemetry Hook Pack, mc-signal CLI and signal_emit tool",
        "Events",
        "C",
        "M",
        "SPEC-04-watchers-and-callbacks.md",
        ["MO-40", "MO-30"],
        ["skills/mc-signals/", "application/agentic_components/", "interfaces/mcp/"],
        "Agents and hooks have no formal channel back to Mission Control (replaces ad hoc watcher/status files).",
        [
            "Dependency-free signal script with spool, seq and batching; mc-signal CLI; signal_emit MCP tool; mc-signals skill.",
            "Native projection per lane per SPEC-04 §4.2.",
        ],
        [
            "cursor_cloud drill: session.started, materialization.observed and stop arrive ordered with no gaps."
        ],
    ),
    issue(
        "MO-42",
        "Gate hooks and remote stop fence",
        "Events",
        "C",
        "M",
        "SPEC-04-watchers-and-callbacks.md",
        ["MO-41"],
        ["application/signals/gates.py", "skills/mc-signals/"],
        "Lanes without a cancel API cannot be stopped mid-turn; remote VMs lack Stop Fence parity.",
        [
            "Synchronous gate endpoint returning allow/deny/stop mapped to native hook outputs; trust-tier rules; fail-closed when declared."
        ],
        [
            "cursor_cloud drill stops within one tool call after cancel; fail-closed gate denies when ingress is down."
        ],
    ),
    issue(
        "MO-43",
        "Wake channels: missionctl wait, inbox long-poll, MCP inbox_wait, auto-subscribe",
        "Events",
        "B",
        "M",
        "SPEC-04-watchers-and-callbacks.md",
        [],
        [
            "interfaces/cli/main.py",
            "interfaces/http/coordinator_inbox.py",
            "interfaces/mcp/",
            "bootstrap/api.py",
            "application/subscriptions/",
        ],
        "Nothing wakes the orchestrating agent; MCP surfaces are split; auto-subscribe missing (gap G5).",
        [
            "missionctl wait (--follow); GET inbox?wait=; MCP inbox_wait on the authenticated server; unify inbox/transcripts/signal_emit onto it.",
            "Auto-subscribe the launcher on every coordinator launch; relay on by default; webhook payload: summary; deprecate mission_subscribe (ADR-0049).",
        ],
        [
            "A Claude Code coordinator is woken by background missionctl wait on run.completed (recorded transcript)."
        ],
    ),
    issue(
        "MO-44",
        "Watchers: schema, compiled descriptors, evaluator, actions and boundaries",
        "Events",
        "C",
        "L",
        "SPEC-04-watchers-and-callbacks.md",
        ["MO-43"],
        [
            "domain/authoring/manifest_v2.py",
            "domain/programs/",
            "application/watchers/",
            "adapters/temporal/",
        ],
        "Manifests cannot declare watchers/callbacks/limits; controls.notifications is dead; event_wait only releases manually (gap G7).",
        [
            "controls.watchers with closed ADR-0010 conditions, typed actions and mandatory boundaries; Capability Kind watcher.",
            "Deterministic Watcher Evaluator over outbox/frames/timers; watcher.fired/failed events; dedupe key (watcher_id, trigger_event_id).",
            "controls.notifications consumed as sugar; event_wait satisfiable by watcher.",
        ],
        [
            "Temporal test env: sample watchers fire deterministically; replay causes no duplicate actions; limits enforced."
        ],
    ),
    issue(
        "MO-45",
        "External signal sources: GitHub, Cursor v0 webhook, schedules, worker watches",
        "Events",
        "D",
        "M",
        "SPEC-04-watchers-and-callbacks.md",
        ["MO-40", "MO-44"],
        ["interfaces/http/ingress.py", "adapters/github/", "adapters/temporal/activities/"],
        "Watchers need PR/CI, provider status, timers and process/log/file watches.",
        [
            "GitHub webhook + poll fallback; Cursor v0 statusChange; Temporal schedules; S6 worker watches with heartbeats."
        ],
        ["Each source produces typed signals consumed by a watcher in tests."],
    ),
    issue(
        "MO-46",
        "Standard watcher library",
        "Events",
        "D",
        "S",
        "SPEC-04-watchers-and-callbacks.md",
        ["MO-44"],
        ["skills/ or catalog seeds"],
        "Replace the owner's ad hoc supervisor/poll/stop scripts with reusable templates.",
        [
            "stall-detector, result-marker-stop, ci-watch, pr-merged-release-wait, artifact-pipeline, budget-guard, heartbeat-progress."
        ],
        ["Each template has an example manifest and a test."],
    ),
    issue(
        "MO-47",
        "Observe skill v2 and router/author skill updates",
        "Events",
        "D",
        "S",
        "SPEC-04-watchers-and-callbacks.md",
        ["MO-43", "MO-44"],
        [
            "skills/mission-control-observe/",
            "skills/mission-control/",
            "skills/mission-control-author/",
        ],
        "Observe skill advertises a broken push and lacks wait recipes.",
        [
            "Rewrite around launch-then-wait, supervise-many, inspect-on-wake, declare-watchers; follow writing-for-agents; update manifest digests."
        ],
        ["Recipes executed in a recorded session; make skills-check passes."],
    ),
    # ---------------- workspaces ----------------
    issue(
        "MO-50",
        "Generalised cloud branch preparation with large-input references",
        "Environment",
        "D",
        "M",
        "SPEC-03-workspaces-and-placement.md",
        ["MO-11", "MO-12", "MO-30"],
        ["adapters/cursor/scm.py", "application/workspaces/", "adapters/github/"],
        "Only Cursor prepares branches; inputs are committed regardless of size or sensitivity.",
        [
            "Shared mc/{run}/{unit} preparation for all branch-based cloud lanes with secret scan.",
            "Inputs over 256 KiB or sensitive become Artifact references fetched at runtime.",
        ],
        ["Large inputs never committed; branch carries pack, mission layer and packet."],
    ),
    issue(
        "MO-51",
        "Knowledge workspaces and output channels",
        "Environment",
        "D",
        "M",
        "SPEC-03-workspaces-and-placement.md",
        ["MO-40", "MO-50"],
        [
            "domain/authoring/manifest_v2.py",
            "adapters/cursor/workspace.py",
            "application/workspaces/",
            "interfaces/http/ingress.py",
        ],
        "Knowledge/research/content missions cannot launch without a target code repo (gap G9).",
        [
            "workspace.kind code|knowledge|mixed; Application knowledge repo binding; research lease reachable; repo-optional for API lanes and Cursor no-repo agents.",
            "Output channels: ingress artifact upload, branch commit, provider artifacts; Completion Contract names the evidence channel.",
        ],
        [
            "A knowledge mission with no code repo completes on cursor_cloud, claude_managed and a local lane with an accepted output Artifact."
        ],
    ),
    issue(
        "MO-52",
        "Placement limits, fan-out admission and lane preference",
        "Runtime",
        "D",
        "M",
        "SPEC-03-workspaces-and-placement.md",
        ["MO-21"],
        ["application/missions/admission.py", "adapters/temporal/", "bootstrap/settings.py"],
        "Parallel cloud work needs per-provider concurrency budgets and lane fallback.",
        [
            "placement_limits per profile; durable waits when exceeded; placement prefer_cloud|cloud_only|local_only; first-qualified lane resolution."
        ],
        ["Five-member fan-out throttled at three active without busy loops."],
    ),
    issue(
        "MO-53",
        "Cross-lane forks between cloud and local",
        "Runtime",
        "D",
        "M",
        "SPEC-03-workspaces-and-placement.md",
        ["MO-50"],
        ["application/recovery/", "application/workspaces/snapshots.py"],
        "Forks must move between placements without copying provider transcripts.",
        [
            "Cloud→local fetch of mission branch into a lease; local→cloud snapshot push and launch; continuation per ADR-0039."
        ],
        ["Cloud head SHA reproduced in a local lease and vice versa."],
    ),
    # ---------------- hosted API lanes ----------------
    issue(
        "HL-01",
        "Sandbox provider spike: score E2B, Modal and Daytona",
        "Environment",
        "A",
        "S",
        "SPEC-06-hosted-api-lanes.md",
        [],
        ["docs/specs/materialization-observation-2026-10/research/"],
        "Decision O2 needs evidence: one sandbox provider serves Managed Agents self-hosted, Codex exec-server, Claude SDK and app-server executors.",
        [
            "Score against criteria (egress allowlist, streaming exec with stdin, snapshot/restore, outbound WebSocket, volumes, pricing/concurrency, Python SDK, region).",
            "One owner-authorized live smoke per provider; write a research note with a recommendation.",
        ],
        ["Owner picks a provider from a cited comparison."],
    ),
    issue(
        "HL-02",
        "SandboxHost port and Docker adapter",
        "Runtime",
        "B",
        "M",
        "SPEC-06-hosted-api-lanes.md",
        ["HL-01"],
        [
            "application/execution/ports.py",
            "adapters/sandboxes/docker/",
            "adapters/sandboxes/<provider>/",
        ],
        "Self-hosted executors and Sandbox Host placements need one provider-neutral port.",
        [
            "Port per SPEC-06 §2 with describe flags; Docker adapter on the WSL2 worker; managed provider adapter after HL-01.",
            "Labels {run, unit}; orphan sweep; egress policy from MO-15; kit-built images.",
        ],
        [
            "Conformance tests for create/exec(streaming stdin)/files/snapshot/terminate on Docker; sweep removes orphans."
        ],
    ),
    issue(
        "HL-03",
        "Model Gateway: keyless model access from sandboxes",
        "Environment",
        "B",
        "M",
        "SPEC-06-hosted-api-lanes.md",
        ["MO-11", "HL-02"],
        ["interfaces/http/model_gateway.py", "application/secrets/"],
        "Claude CLI or Codex inside a sandbox would otherwise need the organisation API key.",
        [
            "Egress proxy authenticating per-run minted tokens and injecting provider keys (Anthropic; OpenAI if base-URL override verified).",
            "Usage capture per run; rate limiting; deny non-model paths.",
        ],
        [
            "Sentinel test: no org key in any sandbox env or file; Claude CLI in Docker completes a turn through the gateway."
        ],
    ),
    issue(
        "HL-04",
        "Extract the Remote Session Lane base from cursor_cloud",
        "Runtime",
        "A",
        "M",
        "SPEC-06-hosted-api-lanes.md",
        [],
        [
            "adapters/remote_session/",
            "adapters/cursor/cloud.py",
            "adapters/cursor/sse.py",
            "adapters/cursor/cloud_api.py",
        ],
        "Two new hosted lanes would duplicate SSE, reconcile, idempotency, error and custody machinery.",
        [
            "Move provider-neutral parts into adapters/remote_session (ADR-0052); cursor_cloud becomes the first client with no behaviour change."
        ],
        ["All existing cursor_cloud tests pass unchanged; base has its own unit tests."],
    ),
    issue(
        "HL-05",
        "Lane conformance suite for every lane",
        "Integrator",
        "A",
        "M",
        "SPEC-06-hosted-api-lanes.md",
        [],
        ["tests/conformance/lanes/", "tests/unit/cursor/test_describe_honesty.py"],
        "Describe honesty is tested for Cursor only; no shared lane scenarios exist.",
        [
            "Shared scenarios per SPEC-06 §3 run against each lane fake; generalise describe-honesty."
        ],
        [
            "All existing lanes pass or have documented, declared exceptions; new lanes must pass to merge."
        ],
    ),
    issue(
        "HL-06",
        "Profile vocabulary for claude_managed and codex_agents, data class and ADR-0050",
        "Integrator",
        "A",
        "M",
        "SPEC-06-hosted-api-lanes.md",
        ["HL-05"],
        [
            "domain/capabilities/host_support.py",
            "domain/execution/lanes.py",
            "domain/execution/bindings.py",
            "domain/authoring/manifest.py",
            "domain/authoring/manifest_v2.py",
            "application/execution/harness/describe.py",
            "application/authoring/provider_launch.py",
            "bootstrap/provider_auth.py",
            "packages/mission-control-db-contract",
        ],
        "New profiles touch every vocabulary listed in research/codebase-new-lanes.md §2.",
        [
            "Add both profiles on existing lanes (claude, codex) with placements; describe matrices per SPEC-06 §9; options classes; api_key auth routes with billing consent.",
            "Add data_class to missions and enforce per-lane admission (SPEC-06 §8).",
            "DB migration after 0034 widening profile checks; regenerate schemas; ADR-0050 proposed.",
        ],
        [
            "Import-time guards pass; describe-only registry lists both profiles unqualified; PHI-classed mission refused."
        ],
    ),
    issue(
        "HL-07",
        "claude_managed prepare: agents, skills, environments and vaults sync",
        "Runtime",
        "C",
        "M",
        "SPEC-06-hosted-api-lanes.md",
        ["HL-06", "MO-30", "MO-11"],
        ["adapters/anthropic_managed/prepare.py", "adapters/anthropic_managed/client.py"],
        "Cognition and environment must be projected through the Managed Agents API.",
        [
            "Agent per materialization digest (optimistic version), skills upload by bundle digest, environment per kit digest with explicit limited networking, vaults per secret-set digest.",
            "Render repo AGENTS.md into system; record API read-back digests as discovery proof.",
        ],
        ["Fake-API tests; drill creates resources once and reuses them."],
    ),
    issue(
        "HL-08",
        "claude_managed session lifecycle and frame classifier",
        "Runtime",
        "C",
        "L",
        "SPEC-06-hosted-api-lanes.md",
        ["HL-04", "HL-07"],
        [
            "adapters/anthropic_managed/harness.py",
            "adapters/anthropic_managed/frames.py",
            "application/frames/kinds.py",
        ],
        "Full harness operations on Managed Agents sessions.",
        [
            "start with budget and metadata reconcile; observe SSE + history with cursor (created_at,id,threads); reattach; send_turn queue; cancel via user.interrupt; interrupt_and_inject; pause via budget gate; usage from list_cost; end via interrupt→archive→delete.",
            "KIND_TABLES/DEDUPE rows; closing facts from idle end_turn correlated with interrupts; multiagent off by default.",
        ],
        ["Conformance suite passes; reattach after worker kill yields no duplicate frames."],
    ),
    issue(
        "HL-09",
        "claude_managed approvals, Mission Control custom tools and publication",
        "Runtime",
        "C",
        "M",
        "SPEC-06-hosted-api-lanes.md",
        ["HL-08", "MO-14"],
        ["adapters/anthropic_managed/tools.py", "application/approvals/"],
        "Managed Agents has no hooks; gating and effects need custom tools and permission policies.",
        [
            "always_ask → Human Task → user.tool_confirmation; mc_signal, mc_request_approval, mc_checkpoint, mc_record_intent, mc_prepare, mc_publish answered after Stop Fence.",
            "Readiness gating via always_ask until env.prepared; bundle-based publication with verify→push→repo_pr.",
        ],
        [
            "Approval round trip and bundle publication drills pass; no push credential in cloud sandbox by default."
        ],
    ),
    issue(
        "HL-10",
        "claude_managed self_hosted placement on SandboxHost",
        "Runtime",
        "D",
        "L",
        "SPEC-06-hosted-api-lanes.md",
        ["HL-08", "HL-02"],
        ["adapters/anthropic_managed/worker.py", "adapters/temporal/activities/"],
        "Code work needs our worktrees, remotes, services and real tool interception.",
        [
            "Environment worker with our wrapped tool implementations (Stop Fence, Operation Intent, kernel policy, frame capture) over SandboxHost exec in the lease.",
            "Own runner without the 150 s cap; staged repos; environment key from Secret Broker.",
        ],
        ["Drill: code mission in a Docker lease with kernel deny and verified publication."],
    ),
    issue(
        "HL-11",
        "codex_agents prepare: saved agents, environment templates, prewarm and vaults",
        "Runtime",
        "C",
        "M",
        "SPEC-06-hosted-api-lanes.md",
        ["HL-06", "MO-30", "MO-11"],
        ["adapters/openai_agents/prepare.py", "adapters/openai_agents/client.py"],
        "Project Cognition Pack and kits through the Agents API.",
        [
            "Saved agent per pack digest (instructions append + inlined repo rules); skills/plugins; environment templates and prewarm with Idempotency-Key; vault credentials."
        ],
        ["Fake-API tests; drill reuse by digest."],
    ),
    issue(
        "HL-12",
        "codex_agents session lifecycle, recovery recipe and frame classifier",
        "Runtime",
        "C",
        "L",
        "SPEC-06-hosted-api-lanes.md",
        ["HL-04", "HL-11"],
        [
            "adapters/openai_agents/harness.py",
            "adapters/openai_agents/frames.py",
            "application/frames/kinds.py",
        ],
        "Full harness operations on Agents API sessions without replay cursors.",
        [
            "start with metadata reconcile; observe SSE with documented buffer→retrieve→items?after→apply recovery; status-gated send vs steer; cancel; usage; DELETE end; environment state events (suspended/expired/reset) handled.",
            "Closing facts only from item.done and turn terminal events.",
        ],
        ["Conformance suite passes; worker-kill recovery reconciles with no duplicates."],
    ),
    issue(
        "HL-13",
        "codex_agents function-tool effect gating and custody",
        "Runtime",
        "C",
        "M",
        "SPEC-06-hosted-api-lanes.md",
        ["HL-12", "MO-14"],
        ["adapters/openai_agents/tools.py", "application/effects/"],
        "Built-in shell/patch cannot be approved or hooked.",
        [
            "Credential-free sandbox; mc_publish, mc_open_pr, mc_comment, mc_signal, mc_request_approval, mc_upload_artifact executed after fence + intent keyed (session,turn,call).",
            "Diff custody via git bundle/format-patch artifacts; multi_agent off unless read-only.",
        ],
        ["Approval round trip via required_actions; verified bundle push drill."],
    ),
    issue(
        "HL-14",
        "codex_agents self_hosted executor on SandboxHost",
        "Runtime",
        "D",
        "M",
        "SPEC-06-hosted-api-lanes.md",
        ["HL-12", "HL-02"],
        ["adapters/openai_agents/executor.py"],
        "Code work needs image control, worktrees and snapshots.",
        [
            "Run codex exec-server --remote with environment key in the lease; version pin and compatibility check; 5-minute connect deadline handling; snapshot via SandboxHost."
        ],
        ["Drill: code mission in Docker executor; reconnect after executor restart."],
    ),
    issue(
        "HL-15",
        "claude_agent_sdk on Sandbox Host (real Claude Code harness)",
        "Runtime",
        "D",
        "L",
        "SPEC-06-hosted-api-lanes.md",
        ["HL-02", "HL-03"],
        ["adapters/claude/transport.py", "adapters/claude/host.py", "adapters/claude/session.py"],
        "The owner wants the Claude Code harness off the local machine on API billing.",
        [
            "Bridge SDK stdio to the CLI in the sandbox (custom transport or relay, resolve Q-S1); Model Gateway for model access; SessionStore mirroring for cross-host resume.",
            "execution_environment.kind sandbox_host; keep in-process kernel hooks and can_use_tool.",
        ],
        [
            "Drill: CLI in Docker through the gateway, hooks fire in-process, resume on another worker."
        ],
    ),
    issue(
        "HL-16",
        "codex app-server with remote exec-server executor",
        "Runtime",
        "D",
        "M",
        "SPEC-06-hosted-api-lanes.md",
        ["HL-02"],
        ["adapters/codex/launcher.py", "adapters/codex/protocol.py"],
        "Full Codex control plane with isolated execution.",
        [
            "environment/add to exec-server in SandboxHost; TurnEnvironmentParams per thread; resolve Q-S2 (where hooks/approvals run); fallback app-server-in-sandbox."
        ],
        ["Drill: per-command approval and turn/steer with remote execution."],
    ),
    issue(
        "HL-17",
        "Provider webhooks into Signal Ingress as wake signals",
        "Events",
        "C",
        "S",
        "SPEC-06-hosted-api-lanes.md",
        ["MO-40"],
        ["interfaces/http/ingress.py", "application/signals/"],
        "Managed Agents and OpenAI Agents webhooks should wake workflows.",
        [
            "Standard-webhooks verification for both providers; dedupe on webhook-id; re-read resource state; never trust payload."
        ],
        ["Signed fixture deliveries accepted; forged or replayed rejected."],
    ),
    issue(
        "HL-18",
        "Data-class policy enforcement and session retention",
        "Integrator",
        "C",
        "S",
        "SPEC-06-hosted-api-lanes.md",
        ["HL-06"],
        [
            "application/missions/admission.py",
            "adapters/anthropic_managed/",
            "adapters/openai_agents/",
        ],
        "Neither hosted API is ZDR; BellLabs keeps PHI and secrets out.",
        [
            "Admission by data_class per profile and Application Binding; session delete after custody plus retention."
        ],
        ["PHI-classed mission refused on all API lanes; sessions deleted on schedule."],
    ),
    issue(
        "HL-19",
        "Owner prerequisites and probes for API lanes",
        "Environment",
        "C",
        "S",
        "SPEC-06-hosted-api-lanes.md",
        ["MO-20"],
        ["application/prerequisites/"],
        "MA1-MA5, OA1-OA4, SH1-SH2 must be surfaced and verified before spawn.",
        ["Add catalog entries, generated instructions and api_probe/probe_mission verifications."],
        ["Preflight on a fresh installation lists them; probes verify."],
    ),
    issue(
        "HL-20",
        "Hosted lane qualification drills",
        "Integrator",
        "E",
        "M",
        "SPEC-06-hosted-api-lanes.md",
        ["HL-09", "HL-10", "HL-13", "HL-14", "HL-15"],
        ["docs/qualification/lanes/claude_managed/", "docs/qualification/lanes/codex_agents/"],
        "qualified flips only on recorded evidence; open questions Q-M1..3, Q-O2..4, Q-S1..2 need drills.",
        [
            "Owner-authorized, finite-budget drills per SPEC-06 §11; record transcripts, frames, usage disposition."
        ],
        ["Each profile/placement has a drill record; describe matrices updated from evidence."],
    ),
    # ---------------- subscription cloud lanes (experimental) ----------------
    issue(
        "SC-01",
        "Qualification probes for subscription cloud surfaces",
        "Integrator",
        "E",
        "S",
        "DECISIONS.md",
        ["MO-40"],
        ["docs/qualification/lanes/claude_cloud/", "docs/qualification/lanes/codex_cloud/"],
        "Experimental lanes depend on unverified behaviours (Q-L1, Q-L2, Q-X1, Q-X3).",
        ["Run owner-authorized probes and record results."],
        ["Each question answered with evidence."],
    ),
    issue(
        "SC-02",
        "claude_cloud experimental launch-and-observe lane",
        "Runtime",
        "E",
        "L",
        "DECISIONS.md",
        ["SC-01", "MO-41", "MO-42", "MO-50", "MO-20"],
        ["adapters/claude_cloud/"],
        "Owner decision R5: Claude Code cloud as an experimental lane after API lanes.",
        [
            "Routine-trigger launch, nonce session binding, hook-pack observation (environment_key tier), gate stop, -p --cloud follow-up, branch/PR results, 30-day credential tracking; honest describe (no status/cancel API)."
        ],
        ["Drill completes a bounded task; describe declares the gaps."],
    ),
    issue(
        "SC-03",
        "codex_cloud experimental launch-and-collect lane",
        "Runtime",
        "E",
        "M",
        "DECISIONS.md",
        ["SC-01", "MO-50", "MO-20"],
        ["adapters/codex_cloud/"],
        "Owner decision R5: Codex Cloud as an experimental lane after API lanes.",
        [
            "codex cloud exec with env and branch; status/list --json poll; diff/apply collection; Start-skill entrypoint; strict max_active_tasks."
        ],
        ["Bounded task completes and is collected; describe declares no cancel or observation."],
    ),
    # ---------------- local CLI skills ----------------
    issue(
        "LS-01",
        "Job and result schemas plus runner core",
        "Skills",
        "A",
        "M",
        "SPEC-08-local-cli-skills.md",
        [],
        [
            ".agents/skills/coding-cli-jobs/scripts/agentjob.py",
            ".agents/skills/coding-cli-jobs/schemas/",
        ],
        "Agents need a config-in, goal-directed way to run other coding CLIs without Mission Control.",
        [
            "PEP 723 uv script: run/status/cancel/doctor; git worktree per job; iteration loop with runner-owned verify; resume vs sealed hand-over; status.json heartbeat; result.json; wall-clock kill of process tree; asyncio parallelism."
        ],
        [
            "Fake-CLI harness drives done, blocked, budget_exhausted, timeout and cancelled paths on Windows and POSIX."
        ],
    ),
    issue(
        "LS-02",
        "Claude Code adapter",
        "Skills",
        "A",
        "S",
        "SPEC-08-local-cli-skills.md",
        ["LS-01"],
        [".agents/skills/coding-cli-jobs/scripts/adapters/claude.py"],
        "Map the job contract to claude -p.",
        [
            "stream-json --verbose parsing; --json-schema; --session-id/--resume; permission profiles; --max-turns/--max-budget-usd; subscription guard (no --bare, scrub ANTHROPIC_*)."
        ],
        ["argv and event-parsing unit tests from recorded fixtures."],
    ),
    issue(
        "LS-03",
        "Codex adapter with WSL host support",
        "Skills",
        "A",
        "S",
        "SPEC-08-local-cli-skills.md",
        ["LS-01"],
        [".agents/skills/coding-cli-jobs/scripts/adapters/codex.py"],
        "Map the job contract to codex exec.",
        [
            "--json events; --output-schema/-o; exec resume; sandbox/approval profiles; stdin closed; forced_login_method chatgpt; host auto→wsl on Windows with path translation."
        ],
        ["argv and event-parsing unit tests; WSL path translation tests."],
    ),
    issue(
        "LS-04",
        "Cursor agent adapter with direct Windows launch",
        "Skills",
        "A",
        "S",
        "SPEC-08-local-cli-skills.md",
        ["LS-01"],
        [".agents/skills/coding-cli-jobs/scripts/adapters/cursor.py"],
        "Map the job contract to Cursor agent -p.",
        [
            "stream-json parsing; --force/--trust/--sandbox/--mode; --resume; generated .cursor/cli.json allow/deny in the worktree; Windows launch via versions/<ver>/node.exe index.js; schema extract-and-validate."
        ],
        ["argv and parsing unit tests; Windows launcher resolution test."],
    ),
    issue(
        "LS-05",
        "Router skill, per-CLI skills, recipes and attributions",
        "Skills",
        "A",
        "S",
        "SPEC-08-local-cli-skills.md",
        ["LS-01"],
        [
            ".agents/skills/coding-cli-jobs/SKILL.md",
            ".agents/skills/claude-code-headless/SKILL.md",
            ".agents/skills/codex-exec/SKILL.md",
            ".agents/skills/cursor-agent-headless/SKILL.md",
        ],
        "Teach any agent when and how to delegate, and how to wait.",
        [
            "Write with the writing-for-agents skill: delegation heuristics, job contract, permission profiles, background waiting recipes, gotchas, subscription notes; NOTICE.md for MIT attributions; link trailofbits second-opinion; document codex-plugin-cc adoption."
        ],
        ["Skills load in Claude Code, Codex and Cursor sessions (discovery check)."],
    ),
    issue(
        "LS-06",
        "Safety: env allowlist, redaction, auth guards and doctor",
        "Skills",
        "A",
        "S",
        "SPEC-08-local-cli-skills.md",
        ["LS-01"],
        [".agents/skills/coding-cli-jobs/scripts/"],
        "Jobs must not leak keys or silently switch billing.",
        [
            "Child env allowlist; token redaction; auth guard per CLI and auth mode; never copy credential files; never push or merge; refuse full profile without explicit acknowledgement."
        ],
        [
            "Sentinel key never appears in run.jsonl/result.json; subscription job refuses when only API keys are available."
        ],
    ),
    issue(
        "LS-07",
        "Live smoke checklist for the CLI open items",
        "Skills",
        "B",
        "S",
        "SPEC-08-local-cli-skills.md",
        ["LS-02", "LS-03", "LS-04"],
        [".agents/skills/coding-cli-jobs/references/"],
        "Several CLI behaviours are unverified (Cursor --force/stdin, Codex Windows exits, Claude result subtypes, claude -p usage pool).",
        ["Owner-authorized cheap prompts; record results in references; adjust adapters."],
        ["Every open item in SPEC-08 §9 answered."],
    ),
    issue(
        "LS-08",
        "End-to-end delegation demo from a Claude Code session",
        "Skills",
        "B",
        "S",
        "SPEC-08-local-cli-skills.md",
        ["LS-05", "LS-06", "LS-07"],
        [".agents/skills/coding-cli-jobs/examples/"],
        "Prove the owner workflow.",
        [
            "Claude Code launches a Codex fix job and a Cursor review job in parallel in the background, is woken on completion and reads both results."
        ],
        ["Recorded session transcript and result files."],
    ),
]

# ---- Cursor maturity items from research/cursor-maturity.md ----
CM = [
    (
        "CM-10",
        "Parallel Cursor units in one run get distinct workspaces",
        "A",
        "M",
        [],
        [
            "adapters/cursor/workspace.py",
            "adapters/cursor/cloud.py",
            "adapters/cursor/scm.py",
            "application/workspaces/policy.py",
        ],
        "Two parallel Cursor units in one run share a worktree path (local) or mc/<run> branch (cloud).",
        [
            "Per-unit lease key and branch mc/{run}/{unit}; retries reuse their own lease; reattach finds per-unit branch."
        ],
        [
            "Stage Graph with two parallel local and two parallel cloud stages gets four distinct leases and branches."
        ],
    ),
    (
        "CM-09",
        "Cloud declared-output custody and missing outputs",
        "A",
        "M",
        [],
        ["adapters/cursor/cloud.py", "adapters/cursor/scm.py"],
        "Cloud registers only artifacts/, never outputs/ from the branch.",
        [
            "Register outputs/* at branch head as candidate refs with digests; missing_outputs closing fact; optional single follow-up; persist prUrl before archive."
        ],
        ["Outputs registered; missing-output follow-up fires once; prUrl persisted."],
    ),
    (
        "CM-08",
        "Continuation and fork agent parity on cloud",
        "A",
        "S",
        [],
        ["adapters/cursor/cloud.py", "adapters/cursor/controls.py"],
        "Continuation agent drops subagents, env and metadata; source never archived.",
        [
            "Shared _create_body for start and hydrate; Idempotency-Key path with env_vars_ref; archive source after handover."
        ],
        ["Body parity test; source archived idempotently."],
    ),
    (
        "CM-18",
        "Refuse unknown staged turn text",
        "A",
        "S",
        [],
        ["adapters/cursor/local.py", "adapters/cursor/cloud.py"],
        "A missing staged instruction silently resends the original prompt.",
        ["Raise NativeTurnLost when instruction_ref has no staged text."],
        ["Unit tests for both lanes."],
    ),
    (
        "CM-13",
        "One SSE vocabulary per run",
        "A",
        "S",
        [],
        ["application/frames/kinds.py", "adapters/cursor/cloud.py"],
        "Both simplified and interaction_update events are persisted, risking double counting.",
        ["Prove double counting with a test; keep one transcript-bearing family; other raw-only."],
        ["Transcript and usage counted once."],
    ),
    (
        "CM-02",
        "Per-run token attribution across all turns",
        "B",
        "M",
        [],
        [
            "adapters/cursor/bridge.py",
            "adapters/cursor/local.py",
            "adapters/cursor/cloud.py",
            "application/execution/harness/lane_turns.py",
            "domain/execution/lanes.py",
        ],
        "Local charges agent totals; cloud counts only the final run; cache tokens dropped.",
        [
            "Per-run usage summed across replaced and continuation turns; additive cache_read/cache_write tokens; unknown stays unknown."
        ],
        ["Cancel-and-replace plus continuation fixture charges each run once."],
    ),
    (
        "CM-01",
        "Cloud and local cost settlement",
        "B",
        "M",
        ["CM-02", "CM-04"],
        ["adapters/cursor/cost.py", "adapters/temporal/deployment_composition.py"],
        "Cloud cost reader is never composed; local cost read once though it settles late.",
        [
            "Settle from charged_cents; estimated until reported; bounded delayed re-read; budget charged once; compose cost_reader."
        ],
        ["Describe cost estimated_then_settled true in production; no zero-fill."],
    ),
    (
        "CM-03",
        "Typed provider error taxonomy",
        "B",
        "S",
        [],
        ["adapters/cursor/bridge.py", "adapters/cursor/cloud_api.py"],
        "Local maps no rate-limit/auth/network errors; cloud maps only 429.",
        [
            "Map SDK and HTTP errors to typed retryable/non-retryable errors with retry_after and request_id; wire ADR-0011 classifier."
        ],
        ["Each class routes to the correct retry counter; no secrets in messages."],
    ),
    (
        "CM-04",
        "cursor_local on Windows workers",
        "B",
        "M",
        [],
        [
            "adapters/cursor/bridge.py",
            "bootstrap/preflight",
            "adapters/cursor/kernel_hook_script.py",
        ],
        "cursor_local is refused on Windows.",
        [
            "Launch bridge via asyncio.to_thread(Bridge.launch) plus AsyncClient.connect; resolved interpreter for hook commands; gate behind a setting until CD-15."
        ],
        [
            "Fixture bridge launches, sends, observes and closes on a Windows SelectorEventLoop worker."
        ],
    ),
    (
        "CM-05",
        "Detached bridge and live reattach",
        "B",
        "L",
        ["CM-04"],
        ["adapters/cursor/bridge.py", "adapters/cursor/local.py"],
        "The local bridge dies with the worker, leaving in-flight runs in_doubt.",
        [
            "Sidecar bridge per lease with 0600 discovery file; connect on reattach; list_runs reconciliation; orphan sweep at worker start."
        ],
        [
            "Killing the worker mid-run and restarting resumes the same live run with no duplicate frames."
        ],
    ),
    (
        "CM-06",
        "Local store and conversation fork, drill-gated",
        "D",
        "M",
        ["CM-05"],
        ["adapters/cursor/snapshot.py", "adapters/cursor/local.py"],
        "Local conversation fork may be possible by copying the bridge store.",
        [
            "Include store in snapshot; fork restores and resumes source agent id; close as unsupported if CD-09 fails."
        ],
        ["CD-09 recorded either way."],
    ),
    (
        "CM-07",
        "Conversation export for forks and continuations",
        "B",
        "S",
        ["CM-04"],
        ["adapters/cursor/controls.py"],
        "Forks and continuations carry no conversation excerpt.",
        [
            "Bounded scrubbed transcript excerpt via run.conversation() or v0 /conversation with digest and source; report absence, never invent."
        ],
        ["Fork packet carries the excerpt or an explicit absence."],
    ),
    (
        "CM-11",
        "Model selection with params and validation",
        "D",
        "S",
        [],
        [
            "application/authoring/cursor_launch.py",
            "adapters/cursor/bridge.py",
            "adapters/cursor/cloud.py",
        ],
        "Only a model id is passed; no params or validation.",
        [
            "Additive model_params; validate against models.list() or /v1/models with MODEL_UNAVAILABLE; resolved model in closing facts."
        ],
        ["Invalid params refused before launch."],
    ),
    (
        "CM-12",
        "Subagent honesty",
        "D",
        "S",
        ["MO-30"],
        ["adapters/cursor/cloud.py"],
        "Cloud silently truncates inline subagents to 20.",
        ["Refuse >20 and built-in name collisions at launch."],
        ["Launch refusal tests."],
    ),
    (
        "CM-15",
        "Plan-then-approve gate",
        "D",
        "M",
        [],
        [
            "adapters/cursor/cloud.py",
            "adapters/cursor/bridge.py",
            "application/programs/human_gates",
        ],
        "Cursor's plan mode is unused as a native pre-execution approval lever.",
        [
            "Turn 1 in plan mode; workflow_gate Human Task shows the plan; approve sends turn 2 in agent mode; deny ends not_accepted."
        ],
        ["CD-17 passes on both profiles."],
    ),
    (
        "CM-16",
        "Local approval and question channel through custom tools",
        "D",
        "M",
        ["CM-05"],
        [
            "adapters/cursor/custom_tools.py",
            "adapters/cursor/bridge.py",
            "adapters/cursor/qualification.py",
        ],
        "cursor_local has no per-action approval or provider question channel.",
        [
            "mc_request_approval and mc_ask custom tools opening Human Tasks with a 600 s cap; re-supplied on resume."
        ],
        ["CD-18 passes; admission lists provider_question implemented for cursor_local."],
    ),
    (
        "CM-17",
        "Cloud agent hygiene sweep",
        "D",
        "S",
        ["CM-08"],
        ["adapters/temporal/activities/", "adapters/cursor/cloud_api.py"],
        "Orphaned mc-* cloud agents accumulate.",
        [
            "Archive agents with mc metadata and no open execution; never delete; report in inspection."
        ],
        ["Sweep test with fake API."],
    ),
    (
        "CM-19",
        "Cancel robustness",
        "D",
        "S",
        [],
        ["adapters/cursor/cloud.py"],
        "Cancel edge cases (agent not found, CREATING runs) are unhandled.",
        [
            "Tolerate AgentNotFound after cancel; cover CREATING; set provider-acknowledged timestamp."
        ],
        ["Unit tests for each edge."],
    ),
    (
        "CM-20",
        "Follow-up prompt images and per-turn mode passthrough",
        "D",
        "S",
        ["MO-30"],
        ["adapters/cursor/cloud.py", "adapters/cursor/bridge.py"],
        "Packet images and per-turn mode never reach the provider.",
        ["Pass up to 5 images (15 MB) and mode per turn."],
        ["Request-body tests."],
    ),
    (
        "CM-22",
        "No-repo cursor_cloud agents for knowledge work",
        "D",
        "M",
        ["MO-40", "MO-51"],
        ["domain/execution/lanes.py", "adapters/cursor/cloud.py"],
        "Cursor cloud agents can run without a repo, but the lane requires one.",
        [
            "prepare skips the branch; packet via prompt plus ingress fetch; outputs via artifacts API or ingress."
        ],
        ["A knowledge mission with no repo completes on cursor_cloud."],
    ),
    (
        "CM-14",
        "Context occupancy for Cursor",
        "D",
        "S",
        ["CM-02", "CM-11"],
        ["adapters/cursor/local.py", "adapters/cursor/cloud.py"],
        "No occupancy reading, so context pressure never triggers continuation.",
        [
            "Occupancy from last run input+cache-read tokens vs model window when known; else unknown with reason; record summary-completed as native compaction."
        ],
        ["Continuation policy triggers on a fixture at the soft ratio."],
    ),
    (
        "CM-21",
        "Cursor qualification drills CD-01..CD-20",
        "E",
        "M",
        ["CM-01", "CM-05", "CM-09", "CM-10", "CM-15", "CM-16"],
        ["docs/qualification/lanes/cursor_local/", "docs/qualification/lanes/cursor_cloud/"],
        "qualified flips only on recorded drill evidence.",
        [
            "Run owner-authorized drills per research/cursor-maturity.md and carried-over README drills; record transcripts, frames, journal rows and usage disposition."
        ],
        ["Every drill recorded; describe matrices updated from evidence."],
    ),
]
for iid, title, wave, size, deps, paths, problem, work, acc in CM:
    ISSUES.append(
        issue(
            iid,
            title,
            "Runtime",
            wave,
            size,
            "SPEC-07-cursor-maturity.md",
            deps,
            paths,
            problem,
            work,
            acc,
        )
    )

# ---------------------------------------------------------------------------
# Final-pass amendments (2026-10-12): new issues, field updates, sprint scope
# ---------------------------------------------------------------------------
NEW = [
    issue(
        "MO-63",
        "Lane-only worker role",
        "Runtime",
        "B",
        "M",
        "SPEC-09-local-harness-path.md",
        [],
        [
            "bootstrap/worker.py",
            "adapters/temporal/worker.py",
            "adapters/temporal/deployment_composition.py",
            "bootstrap/settings.py",
        ],
        "Every worker is monolithic: it polls root and family queues and needs family-writer and checkpointer DB logins, which blocks safe workers on other hosts (Daytona).",
        [
            "MISSION_CONTROL_WORKER_ROLE=lane serves only MISSION_CONTROL_LANE_TASK_QUEUES with the runtime DB role only.",
            "Same build id enforcement; readiness reports the role.",
        ],
        [
            "A second worker serving only lane queues runs lane.turn without the family-writer DSN and starts no root or family pollers."
        ],
    ),
    issue(
        "MO-64",
        "Split-host payload custody preflight",
        "Runtime",
        "B",
        "S",
        "SPEC-09-local-harness-path.md",
        [],
        ["adapters/temporal/deployment_composition.py", "bootstrap/preflight.py"],
        "API and workers on different hosts silently use different filesystem payload roots.",
        [
            "Preflight compares payload-root identity across API and worker (marker file) and requires S3 when not shared; document the S3 path for remote workers."
        ],
        ["Preflight flags a non-shared ARTIFACT_PAYLOAD_ROOT; shared /mnt/c root passes."],
    ),
    issue(
        "MO-65",
        "Refuse Codex ChatGPT login in an isolated CODEX_HOME",
        "Runtime",
        "A",
        "S",
        "SPEC-09-local-harness-path.md",
        [],
        ["adapters/codex/harness.py", "adapters/codex/compose.py", "bootstrap/preflight.py"],
        "Isolated CODEX_HOME has no auth.json, yet admission passes and the lane launches signed out.",
        [
            "Typed refusal at preflight and admission for owner_cli_login with isolated home; owner mode launches signed in; API-key route works in isolated mode."
        ],
        ["Profile codex-owner-chatgpt + isolated is refused; owner mode passes readiness."],
    ),
    issue(
        "MO-66",
        "Re-pin Codex to 0.162.1 and regenerate app-server fixtures",
        "Runtime",
        "A",
        "S",
        "SPEC-09-local-harness-path.md",
        [],
        [
            "application/execution/harness/describe.py",
            "tests/fixtures/provider_frames/codex/schema",
            "adapters/codex/protocol.py",
        ],
        "Mission Control pins Codex 0.162.0 while the owner machine has 0.162.1; the LS skills and lane should share one version.",
        [
            "Re-pin to 0.162.1 (owner may override), regenerate the app-server schema fixture, re-run codex unit and conformance tests; readiness checks the WSL binary against the pin."
        ],
        ["codex --version equals the pin on the worker; schema fixture regenerated reproducibly."],
    ),
    issue(
        "MO-67",
        "Temporal Cloud qualification run",
        "Integrator",
        "B",
        "M",
        "SPEC-09-local-harness-path.md",
        ["MO-72"],
        [
            "adapters/temporal/client.py",
            "scripts/register_belllabs_search_attributes.py",
            "docs/MISSION_CONTROL_LOCAL_API.md",
        ],
        "Temporal Cloud is only unit-tested with a mocked connection.",
        [
            "Document address/namespace settings, register search attributes on the namespace, decide versioning promotion permissions; run the S0 probe set on Cloud and record it."
        ],
        ["Three-lane S0 probe set completes on a Cloud namespace with a recorded run."],
    ),
    issue(
        "MO-68",
        "Preflight accepts a local deployments root",
        "Integrator",
        "A",
        "S",
        "SPEC-09-local-harness-path.md",
        [],
        ["bootstrap/preflight.py"],
        "db_release reads only the tracked 1.1.0 lock, so a local 1.3.0 install is always red.",
        ["Profile-level deployment_dir for local/scratch installs; tracked locks untouched."],
        ["Readiness green for a local 1.3.0 install outside version control."],
    ),
    issue(
        "MO-69",
        "Binding digest tool for compose-bindings",
        "Integrator",
        "A",
        "M",
        "SPEC-09-local-harness-path.md",
        [],
        ["bootstrap/preflight.py", "application/authoring/provider_launch.py", "scripts/"],
        "The launch-bindings file needs 62 hand-resolved values (model ids, digests, policy refs) (owner action O7).",
        [
            "Compute environment, image, package and runtime digests and reviewed agent_profile_ref digests from owner selections; emit a file with zero BINDING_UNRESOLVED."
        ],
        ["compose-bindings produces a valid three-lane local file from owner selections only."],
    ),
    issue(
        "MO-70",
        "missionctl token mint helper",
        "Integrator",
        "A",
        "S",
        "SPEC-09-local-harness-path.md",
        [],
        ["interfaces/cli/main.py", "adapters/auth/"],
        "Operators hand-write JWTs to use the API locally.",
        [
            "missionctl token mint from an operator key with scopes and expiry; never prints the key."
        ],
        ["S0 runbook needs no hand-written JWT code."],
    ),
    issue(
        "MO-71",
        "S0 probe manifests for all three local lanes",
        "Integrator",
        "A",
        "S",
        "SPEC-09-local-harness-path.md",
        ["MO-69"],
        [
            "docs/specs/materialization-observation-2026-10/examples/",
            "packages/mission-control-db-contract (seeds, if needed)",
        ],
        "Existing examples depend on test-only schemas.",
        [
            "One probe manifest per lane (claude_agent_sdk, codex, cursor_local) against a fixture repo, compiling on production and qualification seeds; exercises inject and cancel."
        ],
        ["compile reports 0 blockers on the local install for all three lanes."],
    ),
    issue(
        "MO-72",
        "Slice S0 end-to-end: local harness path from all three tools",
        "Integrator",
        "B",
        "M",
        "SPEC-09-local-harness-path.md",
        ["MO-08", "MO-43", "MO-04", "MO-05", "MO-65", "MO-66", "MO-68", "MO-69", "MO-70", "MO-71"],
        [
            "docs/qualification/lanes/claude_agent_sdk/",
            "docs/qualification/lanes/codex/",
            "docs/qualification/lanes/cursor_local/",
        ],
        "Prove the local programmatic harness path (owner decision R13).",
        [
            "Run SPEC-09 §8 runbook: nine runs (three lanes x three launching tools) with wait, inject, cancel/complete and cleanup; record transcripts, frames and usage disposition (owner-authorized spend)."
        ],
        ["SPEC-09 §9 acceptance met on local Temporal; records saved."],
    ),
    issue(
        "MO-73",
        "Verify Claude SessionStore restore with the custom transport",
        "Runtime",
        "A",
        "S",
        "SPEC-06-hosted-api-lanes.md",
        [],
        ["adapters/claude/transport.py", "adapters/claude/session.py", "tests/unit/claude/"],
        "With a custom transport the SDK skips SessionStore resume; the existing local lane may never restore mirrored sessions.",
        [
            "Test cross-process resume through the lane; if broken, restore the transcript into CLAUDE_CONFIG_DIR before resume=<id>."
        ],
        ["Resume on a fresh worker process restores the session with no lost turns."],
    ),
    issue(
        "MO-74",
        "Vercel ingress project, slim import closure and deployment",
        "Integrator",
        "B",
        "M",
        "SPEC-10-ingress-on-vercel.md",
        ["MO-40"],
        [
            "deployments/ingress-vercel/",
            "src/mission_control/interfaces/http/ingress.py",
            "tests/unit/ingress/",
        ],
        "The ingress must run on Vercel without the heavy package.",
        [
            "Project layout per SPEC-10 §6 (app.py, pyproject/uv.lock, vercel.json fluid/iad1/30s/no trailing slash); vendor_closure script and import-closure test; env var contract; deploy to the owner's Vercel team after plan and subdomain decisions (authorized)."
        ],
        [
            "Import-closure test passes; preview build succeeds; production deploy answers health and rejects unauthenticated calls."
        ],
    ),
    issue(
        "MO-75",
        "IngressDrainer worker role",
        "Events",
        "B",
        "M",
        "SPEC-10-ingress-on-vercel.md",
        ["MO-40"],
        ["application/signals/drainer.py", "adapters/postgres/ingress.py", "bootstrap/worker.py"],
        "Inbox rows must become frames, watcher input, reconciliations and Temporal wake-ups without the edge holding credentials.",
        [
            "LISTEN mc_ingress + 5 s poll; SKIP LOCKED batches; FrameWriter with ingress provider_key; webhook reconcile; artifact custody trigger; ingress_wake signal; dead-lettering."
        ],
        [
            "Real PostgreSQL test: replay is a no-op; latency under 200 ms with LISTEN; dead rows after N failures."
        ],
    ),
    issue(
        "MO-76",
        "Signed artifact uploads with quarantine and custody",
        "Events",
        "C",
        "M",
        "SPEC-10-ingress-on-vercel.md",
        ["MO-40", "MO-75"],
        ["application/signals/artifacts.py", "adapters/supabase_storage/"],
        "Vercel caps bodies at 4.5 MB; outputs must still reach custody verified.",
        [
            "artifacts:prepare issues a signed upload to a quarantine bucket; commit records digest; drainer verifies and moves into custody (ADR-0024); quarantine cleanup."
        ],
        [
            "A >4.5 MB artifact arrives, is digest-verified and lands in custody; tampered upload rejected."
        ],
    ),
]
ISSUES.extend(NEW)


def amend(iid, **kw):
    for i in ISSUES:
        if i["id"] == iid:
            for k, v in kw.items():
                if k.startswith("add_"):
                    i[k[4:]] = i[k[4:]] + v
                else:
                    i[k] = v
            return
    raise KeyError(iid)


amend(
    "MO-40",
    spec="SPEC-10-ingress-on-vercel.md",
    title="Signal Ingress service, SQL functions and migration 0035",
    paths=[
        "application/signals/",
        "adapters/postgres/ingress.py",
        "interfaces/http/ingress.py",
        "packages/mission-control-db-contract/component/migrations/0035_signal_ingress.sql",
        "interfaces/http/hook_callback.py",
    ],
    work=[
        "Migration 0035 (component 1.4.0): ingress_credential, ingress_session_binding, ingress_inbox (+ pg_notify trigger), ingress_artifact_upload; NOLOGIN role with EXECUTE-only SECURITY DEFINER functions ingress_accept, ingress_gate (intent before allow), ingress_webhook, ingress_artifact_prepare/commit.",
        "Application ingress service and HTTP router for /v1/ingress/{app}/… with tiers run_token, Cursor OIDC (JWKS), standard-webhooks/HMAC, environment-key HMAC with session binding; derived secrets.",
        "Unify the loopback hook callback onto the same handlers.",
    ],
    acceptance=[
        "Per-tier accept/reject, dedupe, size and rate tests; real PostgreSQL tests for every SQL function including gate ordering and token revocation."
    ],
)
amend(
    "MO-43",
    add_work=["Authenticated MCP gains submit, start and intervene (dev MCP compiles only)."],
)
amend(
    "HL-01",
    title="Daytona qualification and tier confirmation",
    problem="Daytona is chosen (R9); its stdin, log streaming, preview-URL headers and egress tier must be confirmed before adapters depend on them.",
    work=[
        "Owner confirms tier (3+ needed for egress allowlists).",
        "One authorized low-cost smoke: create from image, session exec with suppress_input_echo and text-line stdin, log WebSocket streaming, signed preview URL with bearer header pass-through, snapshot/restore, terminate.",
        "Record results in research/daytona.md.",
    ],
    acceptance=[
        "Each SandboxHost method's Daytona behaviour confirmed or its gap recorded with a workaround."
    ],
)
amend(
    "HL-02",
    title="SandboxHost port with Docker (WSL2) and Daytona adapters",
    work=[
        "Port per SPEC-06 §2 and §12.1; Daytona adapter (daytona SDK 0.224.0 async, explicit key/URL/target, kit snapshots per size, TTL reaper, session exec with echo suppressed and adapter-enforced timeouts, labels and orphan sweep).",
        "Docker adapter on WSL2 with TTL reaper, egress-proxy sidecar, committed-image snapshots and the same text-line stdin contract.",
    ],
    acceptance=[
        "Shared SandboxHost conformance tests pass on Docker and Daytona (Daytona run owner-authorized); orphan sweep removes labelled leftovers."
    ],
)
amend(
    "HL-03",
    work=[
        "Gateway per SPEC-06 §12.2: /v1/messages?beta=true (+count_tokens) only; byte-for-byte body and anthropic-* headers; unbuffered SSE with pings; retry-after/x-should-retry passthrough; per-run token → x-api-key; per-run usage and hard 429 on budget.",
        "Sandbox env contract (ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN, CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST=1, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1, CLAUDE_CODE_SKIP_FAST_MODE_NETWORK_ERRORS=1, skipWebFetchPreflight).",
        "Runs on the worker host this sprint; public placement for Daytona via owner-approved tunnel (Vercel Pro is phase 2).",
    ],
)
amend(
    "HL-10",
    add_work=[
        "Own poll/ack/heartbeat loop per SPEC-06 §4.3 (412 = lease lost, ttl_seconds, per-item sessions_token); idempotent tools keyed (session, tool_use_id); worker stays outside the sandbox."
    ],
)
amend(
    "HL-14",
    add_work=[
        "Environment key only (connect scope) in the sandbox; 30 s disconnect retention; 5-minute connect deadline; works on all Daytona tiers (openai/chatgpt egress is essential-listed)."
    ],
)
amend(
    "HL-15",
    add_work=[
        "Use the exported Transport via ExplicitEnvironmentCliTransport spawn injection with a SandboxProcess adapter; set CLAUDE_CONFIG_DIR; restore transcript for cross-host resume (see MO-73); requires Daytona Tier 3+ and a reachable gateway for the Daytona variant."
    ],
    add_deps=["MO-73"],
)
amend(
    "HL-16",
    add_work=[
        "environment/add per SPEC-06 §7 (experimentalApi; wss or loopback; capability-token auth); approvals and hooks stay worker-side; reach Daytona via signed preview URL or a loopback stdio relay; pin identical Codex on both sides and check executorVersion."
    ],
)
amend(
    "LS-01",
    add_work=[
        "Prompt always via stdin file; host auto = native on this machine; Job Object + taskkill /T /F on Windows."
    ],
)
amend(
    "LS-02",
    add_work=[
        "Always pass --permission-mode; --session-id <uuid> up front; inline --json-schema; --allowedTools followed by another flag; parse result subtype/terminal_reason."
    ],
)
amend(
    "LS-03",
    add_work=[
        "--ignore-user-config and explicit -c overrides (owner config defaults to danger-full-access); no -a on exec; --full-auto removed; options before `resume <id> -`; scrub API keys before forced_login_method; launch codex.exe directly; --ephemeral only for single-iteration jobs."
    ],
)
amend(
    "LS-04",
    add_work=[
        "Final report from the last assistant event (result concatenates text); exit codes 0/1/130/143; never --printenv; stdin prompt when no prompt argument."
    ],
)
amend(
    "LS-06",
    add_work=[
        "Windows env allowlist additions (APPDATA, LOCALAPPDATA, SYSTEMROOT, COMSPEC, PATHEXT, WINDIR, PROGRAMDATA, TEMP/TMP, …); scrub CLAUDECODE and CLAUDE_CODE_ENTRYPOINT."
    ],
)
amend(
    "LS-07",
    problem="Remaining live unknowns: Claude exit codes on max-turns/auth failure, Codex Windows sandbox under --ignore-user-config and kill reach, Cursor stdin prompt and read-only shell behaviour, claude -p usage pool after 2026-10-07.",
)
amend(
    "MO-08",
    add_work=[
        "Install in WSL: uv (lock-compatible), Python 3.12, Node LTS, pinned Codex, Claude Code CLI; detect Windows shims leaking via /mnt/c on PATH; lease roots on Linux FS; same-tree rule (run from /mnt/c with a separate venv or checkpointed clone)."
    ],
)
amend("CM-21", deps=["CM-01", "CM-05", "CM-09", "CM-10"])

# ---- Readiness decisions R16-R22 (owner, 2026-10-12, fifth brief) ----
amend(
    "HL-01",
    title="Daytona qualification on the current tier",
    problem="Daytona is chosen (R9) and runs on the current tier (R16); stdin, log streaming, preview-URL headers and the essential-services egress must be confirmed before adapters depend on them.",
    work=[
        "Record the observed tier (dashboard limits page); the design must work on Tier 1/2 (R16). Confirm a sandbox reaches the Vercel project's *.vercel.app host, api.anthropic.com, api.openai.com, *.chatgpt.com, GitHub, PyPI and npm, and that an arbitrary host is blocked.",
        "One authorized low-cost smoke (inside the S4 budget and the $200 free credit): create from image, session exec with suppress_input_echo and text-line stdin, log WebSocket streaming, signed preview URL with bearer header pass-through, snapshot/restore, terminate.",
        "Record results in research/daytona.md.",
    ],
)
amend(
    "HL-03",
    work=[
        "Gateway per SPEC-06 §12.2: /v1/messages?beta=true (+count_tokens) only; byte-for-byte body and anthropic-* headers; unbuffered SSE with pings; retry-after/x-should-retry passthrough; per-run token → x-api-key; per-run usage and hard 429 on budget.",
        "Sandbox env contract (ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN, CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST=1, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1, CLAUDE_CODE_SKIP_FAST_MODE_NETWORK_ERRORS=1, skipWebFetchPreflight).",
        "Two placements sharing one module (R16, R17): the worker host for Docker on WSL2 (host.docker.internal), and gateway routes in the Vercel ingress project served from its *.vercel.app host for Daytona Tier 1/2. On Vercel: per-run token checked in Postgres (ingress_credential, purpose model_gateway); org keys only as Production sensitive env vars; maxDuration 800 s for streams; the 4.5 MB request cap returns a typed 413 with the size; data class internal or lower only.",
    ],
    deps=["MO-11", "HL-02", "MO-74"],
    add_paths=["deployments/ingress-vercel/ (gateway routes; leased from the integrator)"],
    acceptance=[
        "Sentinel test: no org key in any sandbox env or file.",
        "Claude CLI in Docker completes a turn through the worker-host gateway, and through the Vercel gateway from a Daytona sandbox on the current tier.",
        "A request over budget gets the hard 429; usage per run is recorded.",
    ],
)
amend(
    "HL-15",
    work=[
        "Bridge SDK stdio to the CLI in the sandbox (custom transport or relay, resolve Q-S1); Model Gateway for model access; SessionStore mirroring for cross-host resume.",
        "execution_environment.kind sandbox_host; keep in-process kernel hooks and can_use_tool.",
        "Use the exported Transport via ExplicitEnvironmentCliTransport spawn injection with a SandboxProcess adapter; set CLAUDE_CONFIG_DIR; restore transcript for cross-host resume (see MO-73). The Daytona variant uses the Vercel-hosted gateway on *.vercel.app and works on Tier 1/2 (R16).",
    ],
)
amend(
    "MO-67",
    work=[
        "Use namespace mission-control-dev.ih0e7 at us-east-1.aws.api.temporal.io:7233 with TEMPORAL_TARGET=cloud and TEMPORAL_CLOUD_API_KEY (R20); mission-control-prod.ih0e7 is reserved and untouched this sprint.",
        "Document the settings, register search attributes on the namespace, decide versioning promotion permissions; run the S0 probe set on Cloud and record it.",
    ],
)
amend(
    "MO-74",
    work=[
        "Project layout per SPEC-10 §6 (app.py, pyproject/uv.lock, vercel.json fluid/iad1/30s/no trailing slash; gateway routes 800s); vendor_closure script and import-closure test; env var contract.",
        "Deploy to team overtons-projects (Pro, R17), always with --scope overtons-projects because the CLI's current scope is another team; production host is the project's *.vercel.app domain; no custom domain this sprint.",
        "Apply release 1.4.0 (0035-0039, ingress role) to both live projects through LIVE_PLAN.md before production needs it; pre-approved after disposable and local PostgreSQL proofs (R18).",
    ],
    acceptance=[
        "Import-closure test passes; preview build succeeds; production deploy answers health and rejects unauthenticated calls.",
        "Live 1.4.0 qualify-before/apply/verify/qualify-after evidence recorded for both projects.",
    ],
)
for _h in [
    "HL-02",
    "HL-04",
    "HL-07",
    "HL-08",
    "HL-09",
    "HL-10",
    "HL-11",
    "HL-12",
    "HL-13",
    "HL-14",
    "HL-15",
    "HL-16",
]:
    amend(_h, owner="Hosted")

# ---- Sharpening decisions R27-R33 (owner, 2026-10-12, sixth brief) ----
# Remote operation (slice R): thin Temporal worker on AWS ECS Fargate, remote launch route.
# claude_managed first (S2), then codex_agents (S3); S2/S3 no longer wait on the S1 foundations.
# Self-hosted placements and Sandbox Host (S4) are funding-gated.
ISSUES.extend(
    [
        issue(
            "MO-78",
            "Temporal Cloud namespace setup and connection probe",
            "Integrator",
            "A",
            "S",
            "SPEC-11-remote-worker-on-aws.md",
            [],
            [
                "docs/MISSION_CONTROL_LOCAL_API.md",
                "bootstrap/settings.py",
                "scripts/temporal_cloud/",
            ],
            "Temporal Cloud has never been exercised by this code (R20). Both the S0 Cloud run (MO-67) and the AWS worker (MO-77) need the namespace prepared first, and neither should own that setup.",
            [
                "Register the custom search attributes the code uses on mission-control-dev.ih0e7 (Cloud UI or tcld; removal is unsupported, so list them first and get the integrator's sign-off).",
                "Decide and document Worker Deployment versioning on Cloud: TEMPORAL_PROMOTE_ON_START behaviour, build id = package version plus git sha, and the rule of one base worker per (namespace, application).",
                "A read-only connection probe script (no secrets printed): connect with TEMPORAL_TARGET=cloud and the API key, describe the namespace, list search attributes, start and complete one no-op workflow on a probe task queue with a throwaway in-process worker.",
                "Document the exact env contract (TEMPORAL_TARGET, TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, TEMPORAL_CLOUD_API_KEY) in the operator guide.",
            ],
            [
                "The probe completes against mission-control-dev.ih0e7 and its output is recorded; mission-control-prod.ih0e7 is untouched.",
                "Search attributes and the versioning rule are documented; MO-67 and MO-77 reference them instead of repeating setup.",
            ],
        ),
        issue(
            "MO-77",
            "Thin Temporal worker on AWS ECS Fargate (us-east-1)",
            "Integrator",
            "B",
            "M",
            "SPEC-11-remote-worker-on-aws.md",
            ["MO-63", "MO-64", "MO-78"],
            [
                "deployments/worker-aws/",
                "deployments/cloud_runtime/plan.py",
                "deployments/cloud_runtime/Dockerfile",
                "bootstrap/worker.py",
                "docs/MISSION_CONTROL_LOCAL_API.md",
            ],
            "Missions stop progressing when the owner's machine is off. Managed agents remove agent compute, but Temporal Cloud never runs workflow code; one small always-on worker must (R28).",
            [
                "Operator image deployments/worker-aws/Dockerfile extending the reviewed cloud_runtime base with the AI Engineer deployment files (target.toml, release.lock), capability pins and launch bindings; CMD python -m mission_control.bootstrap.worker; linux/amd64; non-root.",
                "One-time infrastructure in us-east-1 per SPEC-11 §4 (always pass --region us-east-1; the CLI default is us-east-2): ECR repo, S3 payload bucket, two IAM roles, egress-only security group, log group, ECS cluster and service (0.5 vCPU / 2 GiB, desiredCount 1, min 0 / max 100 percent), AWS Budgets alert.",
                "deployments/worker-aws/put-secrets.ps1 for the owner to run: reads named keys from mission-control/.env and writes them to Secrets Manager under mission-control/ai-engineer/ without ever echoing values.",
                "deployments/worker-aws/deploy.ps1: build, tag (version + git sha), push to ECR, render the task definition with plan.py (worker-only service, secrets by ARN, AWS_PROFILE empty), register, update the service, wait for stable, tail readiness from CloudWatch. No GitHub dependency.",
                "Queue layout per SPEC-11 §3: the AWS worker serves the base queues and the hosted lane queue mc-ai-engineer-lane-hosted (cursor_cloud, claude_managed, codex_agents) plus the IngressDrainer; the WSL2 worker switches to MISSION_CONTROL_WORKER_ROLE=lane for mc-s0-ai-engineer-lane-wsl once this service is live.",
                "Database connectivity through the Supabase session pooler (IPv4); confirm LISTEN works there, otherwise run the drainer on its 5 s poll.",
            ],
            [
                "The service runs one task in us-east-1 with no inbound rules; readiness passes against Temporal Cloud (mission-control-dev.ih0e7), the AI Engineer Supabase project and the S3 payload bucket.",
                "With the owner's machine powered off, a probe mission admitted earlier runs a hosted lane turn to completion on the AWS worker; frames and payloads land in Postgres and S3.",
                "No secret value appears in the image, task definition, logs, repo or handoff (sentinel check); deploy.ps1 redeploys a new build with no manual console steps.",
                "Measured CPU and memory over a 24 h idle-plus-drill window are recorded, with the monthly cost estimate.",
            ],
        ),
        issue(
            "MO-79",
            "Remote launch-request route on the Signal Ingress",
            "Events",
            "B",
            "M",
            "SPEC-10-ingress-on-vercel.md",
            ["MO-40", "MO-75", "MO-70"],
            [
                "interfaces/http/ingress.py",
                "application/signals/",
                "application/missions/",
                "adapters/postgres/ingress.py",
                "deployments/ingress-vercel/ (route; leased from the integrator)",
                "packages/mission-control-db-contract/component/migrations/0035_signal_ingress.sql (through the MO-40 owner) or slot 0040",
                "interfaces/cli/ (missionctl remote launch)",
            ],
            "The operator API is local-only and SPEC-10 keeps Temporal credentials off Vercel, so nothing outside the owner's machine can start a mission (gap G-R1, decision R29).",
            [
                "POST /v1/ingress/{app}/missions:request authenticated by a minted operator launch credential (ingress_credential purpose mission_request, scoped to app and manifest set, expiring); writes an inbox row of kind mission_request carrying the manifest reference, inputs digest and idempotency key; replies 202 with the request id.",
                "GET /v1/ingress/{app}/missions:request/{id} returns request state (queued, admitted, refused with typed reason) and, once admitted, the mission id and lifecycle state from a read-only SQL view.",
                "The IngressDrainer admits the request by calling the same application admission handler the API uses (data_class, Spawn Grant and preflight checks included); a refusal is recorded, never retried silently.",
                "missionctl remote launch --app <app> --manifest <ref> mints nothing itself: it uses an operator-minted credential (MO-70) and polls the status route.",
                "SQL: add the mission_request kind and purpose to 0035 through the MO-40 owner if 0035 has not merged, otherwise slot 0040 (allocated by the integrator).",
            ],
            [
                "Real PostgreSQL tests: forged, expired, wrong-app and replayed requests rejected; duplicate idempotency key admits once.",
                "A request sent from outside the owner's network is admitted by the AWS worker and its mission id is readable from the status route.",
            ],
        ),
        issue(
            "HL-23",
            "Provider smoke: Managed Agents and Agents API field confirmation",
            "Hosted",
            "A",
            "S",
            "MANAGED-AGENTS-REMOTE-PATH.md",
            [],
            [
                "scripts/provider_smoke/",
                "docs/specs/materialization-observation-2026-10/research/provider-smoke-2026-10.md",
            ],
            "Lane code would otherwise be written against unconfirmed request shapes (MANAGED-AGENTS-REMOTE-PATH §3 sketches), open questions Q-M1 and Q-O2, and an unconfirmed model (gpt-6-luna on the Agents API).",
            [
                "One script per provider (anthropic 1.13.0, openai 3.29.0 pinned), keys from the environment, nothing printed but ids and statuses: create a skill, a vault with one credential, an agent and an environment; start a session with a one-turn read-only prompt; stream; answer one custom/function tool; send a mid-turn user.message (Q-M1); interrupt; read usage; delete the session and archive test resources.",
                "OpenAI: confirm gpt-6-luna is accepted for the Codex harness; if refused, stop and ask the owner (SPRINT drill table). Check whether an AGENTS.md placed in the hosted workspace is honoured (Q-O2).",
                "Record exact working request shapes, ids returned, event names seen and usage in research/provider-smoke-2026-10.md.",
            ],
            [
                "Both smokes complete under $1 each (charged to the S2 and S3 budgets) with usage recorded; every created resource is deleted or archived.",
                "MANAGED-AGENTS-REMOTE-PATH §3 and SPEC-06 are corrected wherever a field differs.",
            ],
        ),
        issue(
            "HL-24",
            "Slice S2: claude_managed cloud end to end, launched remotely",
            "Integrator",
            "C",
            "M",
            "SPRINT.md",
            ["HL-09", "HL-17", "HL-18", "HL-23", "MO-74", "MO-77", "MO-79"],
            [
                "docs/qualification/hosted/claude-managed/",
                "deployments/hosted-packs/ai-engineer/",
            ],
            "Prove claude_managed cloud as the first remote lane (R27) before any other hosted lane qualifies.",
            [
                "Run the S2 definition of done in SPRINT.md: a knowledge mission and an SDLC mission, both requested through the launch route and orchestrated by the AWS worker.",
                "Exercise: provider webhook wake through the ingress, one always_ask approval round trip, interrupt_and_inject, budget-gate pause and resume, mc_publish bundle → verified push → draft PR, usage settled from list_cost, session deleted after custody.",
                "Record transcripts, frames, usage disposition and the describe matrix observed; flip claude_managed cloud to qualified only from this record.",
            ],
            [
                "Both missions accepted by their Completion Contracts within the $10 S2 budget, with the owner's machine not running the base worker.",
                "SPEC-06 §9 matrix for claude_managed cloud updated from evidence.",
            ],
        ),
        issue(
            "HL-25",
            "Slice S3: codex_agents hosted end to end, launched remotely",
            "Integrator",
            "C",
            "M",
            "SPRINT.md",
            ["HL-13", "HL-17", "HL-24"],
            ["docs/qualification/hosted/codex-agents/", "deployments/hosted-packs/ai-engineer/"],
            "Prove codex_agents hosted after claude_managed (R27) on the same remote path.",
            [
                "Run the S3 definition of done in SPRINT.md: the same two missions as S2 on codex_agents hosted.",
                "Exercise: function-tool approval round trip via required_actions, steer and cancel, recovery after killing the AWS task mid-stream (reconcile from items with no duplicate frames), per-turn artifact custody, session DELETE.",
                "Record transcripts, frames, usage disposition; flip codex_agents openai_hosted to qualified only from this record.",
            ],
            [
                "Both missions accepted within the $10 S3 budget; worker-kill recovery shows no duplicate frames.",
                "SPEC-06 §9 matrix for codex_agents hosted updated from evidence.",
            ],
        ),
        issue(
            "HL-21",
            "Hosted lanes: full Cognition Pack and Secret Broker projection",
            "Hosted",
            "C",
            "M",
            "SPEC-06-hosted-api-lanes.md",
            ["HL-07", "HL-11", "MO-30", "MO-11"],
            [
                "adapters/anthropic_managed/prepare.py",
                "adapters/openai_agents/prepare.py",
                "deployments/hosted-packs/",
            ],
            "HL-07 and HL-11 start from checked-in pack files (R30) so S2 and S3 need not wait for the S1 foundations; the general projection must replace them once MO-30 and MO-11 land.",
            [
                "Drive agent, skill, environment and vault sync from the MO-30 projection targets and the Secret Broker provider_vault delivery channel instead of pack files.",
                "Keep digest keys identical so resources created from pack files are reused, not duplicated.",
            ],
            [
                "The S2 and S3 drill missions re-run through the projection with zero new provider resources created when nothing changed.",
            ],
        ),
    ]
)
amend(
    "HL-07",
    title="claude_managed prepare: agents, skills, environments and vaults from pack files",
    wave="B",
    deps=["HL-06", "HL-23"],
    problem="Cognition and environment must be projected through the Managed Agents API. To start S2 before the S1 foundations (R30), the first prepare reads checked-in pack files; HL-21 later swaps in the general projection.",
    work=[
        "Pack files under deployments/hosted-packs/<app>/claude_managed/: agent (model, system overlay, tools with permission policies, MCP servers, skills directories, metadata), environment (packages, limited networking with explicit allowed_hosts including the ingress host), vault credential names (values from the worker env at sync time, never from files).",
        "Sync keyed by digest: agent per materialization digest (optimistic version), skills uploaded by bundle digest, environment per kit digest (new digest means new environment), vault per secret-set digest.",
        "Render repo AGENTS.md into system; record API read-back digests as discovery proof.",
    ],
    acceptance=[
        "Fake-API tests; a live sync creates resources once and reuses them on the second run (owner-authorized, inside the S2 budget).",
    ],
)
amend("HL-08", wave="B")
amend(
    "HL-08",
    add_work=[
        "Read-only knowledge missions may enable multiagent (dynamic workflows and subagents) and user.define_outcome; outcome results are evidence for the Completion Contract, never acceptance (R33). Code missions keep multiagent off.",
    ],
)
amend("HL-09", wave="B")
amend("HL-17", wave="B")
amend("HL-18", wave="B")
amend(
    "HL-11",
    title="codex_agents prepare: saved agents, environment templates, prewarm and vaults from pack files",
    deps=["HL-06", "HL-23"],
    work=[
        "Pack files under deployments/hosted-packs/<app>/codex_agents/: saved agent (instructions append plus inlined repo rules, function tools mc_*, MCP), environment template (setup commands, packages, network allowlist), skills and plugins, vault credential names.",
        "Saved agent per pack digest; environment templates and prewarm with Idempotency-Key; vault credentials from the worker env at sync time.",
    ],
)
amend(
    "HL-20",
    title="Self-hosted placement and Sandbox Host qualification drills (funding-gated)",
    deps=["HL-10", "HL-14", "HL-15", "HL-16"],
    problem="The cloud placements qualify in HL-24 and HL-25. The self-hosted placements and the self-run harnesses on Sandbox Host qualify only when the owner releases slice S4 (R31). Open questions Q-M2, Q-M3, Q-S1 and Q-S2 need these drills.",
)
amend(
    "MO-67",
    deps=["MO-72", "MO-78"],
    work=[
        "Run the S0 probe set on mission-control-dev.ih0e7 using the setup and versioning rule from MO-78 (TEMPORAL_TARGET=cloud, TEMPORAL_CLOUD_API_KEY, R20); mission-control-prod.ih0e7 is untouched this sprint.",
        "If the AWS worker (MO-77) is already serving AI Engineer's base queues, run the S0 Cloud variant with the WSL2 worker in lane role only, so there is one base worker per (namespace, application).",
    ],
)
amend(
    "MO-63",
    add_work=[
        "This role is how the WSL2 worker coexists with the AWS base worker (SPEC-11 §3): it serves only mc-s0-<app>-lane-wsl."
    ],
)
amend(
    "MO-64",
    add_work=[
        "S3 is the payload store whenever the AWS worker is live: S3_BUCKET on the Windows API (profile mission-control) and on the AWS task (task role); AWS_PROFILE must be empty in ECS."
    ],
)
for _h in ["HL-01", "HL-02", "HL-03", "HL-10", "HL-14", "HL-15", "HL-16"]:
    amend(_h, wave="D", funding_gated=True)

SLICES = {
    "F": [
        "MO-01",
        "MO-02",
        "MO-03",
        "MO-04",
        "MO-05",
        "MO-07",
        "HL-04",
        "HL-05",
        "HL-06",
        "CM-10",
        "CM-09",
        "CM-08",
        "CM-18",
        "CM-13",
        "CM-02",
        "CM-01",
        "CM-03",
        "CM-05",
        "CM-07",
        "CM-19",
        "MO-73",
    ],
    "LS": ["LS-01", "LS-02", "LS-03", "LS-04", "LS-05", "LS-06", "LS-07", "LS-08"],
    "S0": [
        "MO-08",
        "MO-43",
        "MO-63",
        "MO-64",
        "MO-65",
        "MO-66",
        "MO-67",
        "MO-68",
        "MO-69",
        "MO-70",
        "MO-71",
        "MO-72",
        "CM-04",
    ],
    "S1": [
        "MO-06",
        "MO-10",
        "MO-11",
        "MO-12",
        "MO-13",
        "MO-14",
        "MO-15",
        "MO-16",
        "MO-20",
        "MO-21",
        "MO-22",
        "MO-30",
        "MO-31",
        "MO-32",
        "MO-33",
        "MO-34",
        "MO-35",
        "MO-40",
        "MO-41",
        "MO-42",
        "MO-44",
        "MO-45",
        "MO-46",
        "MO-47",
        "MO-50",
        "MO-51",
        "MO-52",
        "MO-74",
        "MO-75",
        "MO-76",
    ],
    "R": ["MO-77", "MO-78", "MO-79"],
    "S2": ["HL-07", "HL-08", "HL-09", "HL-17", "HL-18", "HL-19", "HL-23", "HL-24"],
    "S3": ["HL-11", "HL-12", "HL-13", "HL-21", "HL-25"],
    "S4": ["HL-01", "HL-02", "HL-03", "HL-10", "HL-14", "HL-15", "HL-16"],
    "Q": ["HL-20", "CM-21"],
}
DEFERRED = [
    "SC-01",
    "SC-02",
    "SC-03",
    "CM-06",
    "CM-11",
    "CM-12",
    "CM-14",
    "CM-15",
    "CM-16",
    "CM-17",
    "CM-20",
    "CM-22",
    "MO-53",
]
_slice_of = {x: s for s, xs in SLICES.items() for x in xs}
for i in ISSUES:
    if i["id"] in DEFERRED:
        i["sprint"], i["slice"] = "deferred", "-"
    else:
        assert i["id"] in _slice_of, ("unassigned", i["id"])
        i["sprint"], i["slice"] = "in", _slice_of[i["id"]]
_by = {i["id"]: i for i in ISSUES}
for i in ISSUES:
    if i["sprint"] == "in":
        for d in i["deps"]:
            assert _by[d]["sprint"] == "in", ("in-sprint depends on deferred", i["id"], d)
SLICE_DESC = {
    "F": "Foundations and fixes",
    "LS": "Local CLI job skills",
    "S0": "Local harness path",
    "S1": "cursor_cloud end-to-end with materialization and observation",
    "R": "Remote operation: thin Temporal worker on AWS and remote launch",
    "S2": "claude_managed cloud, launched remotely",
    "S3": "codex_agents hosted, launched remotely",
    "S4": "Funding-gated: self-hosted placements and real harnesses on Sandbox Host",
    "Q": "Qualification drills",
}


WAVES = {
    "A": "Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup",
    "B": "S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability",
    "C": "S2 claude_managed drill, then S3 codex_agents; S1 cursor_cloud end to end; full cognition projection; preflight; signals, gates and watchers",
    "D": "Workspaces and fan-out, external signal sources; funding-gated S4 (Daytona, SandboxHost, Model Gateway, self-hosted placements, harnesses on Sandbox Host)",
    "E": "Qualification drills",
}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80].rstrip("-")


ids = {i["id"] for i in ISSUES}
for i in ISSUES:
    for d in i["deps"]:
        assert d in ids, (i["id"], d)
byid = {i["id"]: i for i in ISSUES}
_o = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
for i in ISSUES:
    for d in i["deps"]:
        assert _o[byid[d]["wave"]] <= _o[i["wave"]], ("dep in later wave", i["id"], d)
    i["file"] = f"{i['id']}-{slug(i['title'])}.md"

out = PACKET / "issues"
out.mkdir(exist_ok=True)
for f in out.glob("*.md"):
    f.unlink()
for i in ISSUES:
    md = [
        f"# [{i['id']}] {i['title']}",
        "",
        "Status: ready-for-agent — subject to blockers (not published to Linear)",
        "",
        f"**Owner:** {i['owner']}  ",
        f"**Wave:** {i['wave']} — {WAVES[i['wave']]}  ",
        f"**Size:** {i['size']}  ",
        f"**Sprint:** {i['sprint']}"
        + (f" — slice {i['slice']} ({SLICE_DESC[i['slice']]})" if i["sprint"] == "in" else "")
        + "  ",
        f"**Blocked by:** {', '.join(i['deps']) or 'None'}  ",
    ]
    if i.get("funding_gated"):
        md += ["**Gate:** funding — start only when the owner releases slice S4 (DECISIONS R31)  "]
    md += [
        f"**Specification:** [{i['spec']}](../{i['spec']})",
        "",
        "## Problem",
        "",
        i["problem"],
        "",
        "## Work",
        "",
    ]
    md += [f"- {w}" for w in i["work"]]
    md += [
        "",
        "## Source ownership",
        "",
        "Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.",
        "",
    ]
    md += [f"- `{p}`" for p in i["paths"]]
    md += ["", "## Acceptance", ""] + [f"- [ ] {a}" for a in i["acceptance"]]
    md += [
        "",
        "## Validation and handoff",
        "",
        "Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.",
        "",
        "## Provenance",
        "",
        "- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).",
        f"- Packet: `{P}/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).",
        "- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).",
        "",
    ]
    (out / i["file"]).write_text("\n".join(md), encoding="utf-8")

data = {
    "parent": "Materialization, observation and hosted-lane maturity (2026-10-12)",
    "issues": ISSUES,
    "waves": WAVES,
    "slices": SLICE_DESC,
    "blocking_relations": [[d, i["id"]] for i in ISSUES for d in i["deps"]],
}
(PACKET / "issues.json").write_text(
    json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8"
)

order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
rows = sorted(ISSUES, key=lambda i: (order[i["wave"]], i["id"]))
idx = [
    "---",
    "type: Specification",
    'title: "Materialization-observation issue index and dependency waves"',
    'description: "Generated index of MO, HL, CM, SC and LS issues with owners, sizes, waves and blockers; issues.json is the source; not yet published to Linear."',
    "tags: [mission-control, issues, agents]",
    "---",
    "",
    "# Issue index",
    "",
    f"Generated from `issues.json` ({len(ISSUES)} issues, {len(data['blocking_relations'])} blocking relations). Not published to Linear; publish only with owner authorization (`docs/agents/issue-tracker.md`).",
    "",
    "Prefixes: **MO** environment/cognition/observation/workspaces/remote operation, **HL** hosted API lanes and Sandbox Host, **CM** Cursor maturity, **SC** subscription cloud lanes (experimental), **LS** local CLI job skills.",
    "",
]
inrows = [i for i in rows if i["sprint"] == "in"]
idx += [
    f"In sprint: {len(inrows)} issues. Deferred: {len(rows) - len(inrows)}. Scope is defined in [SPRINT.md](SPRINT.md).",
    "",
]
for w, desc in WAVES.items():
    idx += [
        f"## Wave {w} — {desc}",
        "",
        "| Issue | Slice | Owner | Size | Blocked by |",
        "| --- | --- | --- | --- | --- |",
    ]
    idx += [
        f"| [{i['id']} — {i['title']}](issues/{i['file']}) | {i['slice']} | {i['owner']} | {i['size']} | {', '.join(i['deps']) or 'None'} |"
        for i in inrows
        if i["wave"] == w
    ]
    idx.append("")
idx += [
    "## Deferred (not this sprint)",
    "",
    "| Issue | Owner | Size | Blocked by |",
    "| --- | --- | --- | --- |",
]
idx += [
    f"| [{i['id']} — {i['title']}](issues/{i['file']}) | {i['owner']} | {i['size']} | {', '.join(i['deps']) or 'None'} |"
    for i in rows
    if i["sprint"] == "deferred"
]
idx.append("")
(PACKET / "ISSUES.md").write_text("\n".join(idx), encoding="utf-8")
print(len(ISSUES), "issues;", len(data["blocking_relations"]), "relations")
