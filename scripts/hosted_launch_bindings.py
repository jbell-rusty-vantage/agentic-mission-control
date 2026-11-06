"""Write the W1 launch bindings with the two hosted lanes (`mc.manifest_launch_bindings.v2`, F2-G2).

Reads an existing W1 bindings file (`mc.manifest_launch_bindings.v1`, Deep Agents only, written by
`scripts/sprint_oc_w1_bindings.py`), keeps every Deep Agents, model, sandbox and capability entry
byte-for-byte, and adds `providers.claude_managed` and `providers.codex_agents`, each a
`ProviderLaneBinding` derived only from checked-in deployment facts:

* `hosted_projection`: the reviewed pack (`deployments/hosted-packs/<app>/<profile>/`) serialized
  by `adapters/remote_session/projection.configuration`, so the worker's `HostedProjectionSource`
  and the API's launch digest re-render exactly that pack (unchanged bytes keep provider keys);
* `task_queue`, model id, tool placement and data class: the pack's own fields;
* `pins`: `required_pins(profile)`, the lane's declared versions;
* `host_profiles`: one `provider_hosted` environment, `environment_ref` = the pack's knowledge
  environment name, `expected_revision` = the pack's environment digest (Managed: `kit_digest`;
  Agents API: `template_digest`);
* `workspace.provider`: the lane's declared `provider_scope`; `environment_digest` as above;
* `agent_profile_ref`: an exact ref whose digest is the digest of the reviewed `hosted_projection`
  (the hosted agent definition the session is created from); it is carried on the request, not
  resolved against a catalog row;
* tracing, sensitive-data and snapshot policy refs: the W1 file's own `deep_agents` refs.

Operator choices (flags, defaults shown in `--help`, reported on stdout): the Managed Agents
per-session `max_list_cost` cap, the lane session budgets, and the Managed rendering inputs. The
claude_managed pack renders the target repository's `AGENTS.md` into `system`; a knowledge mission
has no target repository, so by default the AI Engineer rules the codex_agents pack already
inlines (`codex_agents/repo-rules.md`, "inlined from its AGENTS.md") are rendered. The pack's
`include_signal_ingress` adds a Signal Ingress host to the sandbox egress; hosted `mc_signal` is a
custom tool the worker answers (`adapters/remote_session/signals.py`), so without
`--signal-ingress-host` no host is added (reported as `signal_ingress_host: null`).

No `repository_commits` are written: the fixtures are repository-less knowledge missions, so the
codex_agents projection also drops the pack's read-only `GITHUB_TOKEN` vault credential (see
`_agents`; reported as `codex_agents.vault_credentials: []`). Nothing
here is secret; no provider is contacted. Usage (from the worktree, writing into the canonical
checkout's git-ignored runtime directory):

    uv run --no-sync python scripts/hosted_launch_bindings.py \\
        --source <mc>/.scratch/sprint-oc/runtime/ai-engineer/w1-launch-bindings-iter2.json \\
        --out-dir <mc>/.scratch/sprint-oc/runtime/ai-engineer
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from mission_control.adapters.anthropic_managed.describe import CLAUDE_MANAGED_DESCRIBE
from mission_control.adapters.anthropic_managed.pack import RenderedPack, render_pack
from mission_control.adapters.anthropic_managed.pack import load_pack as load_managed
from mission_control.adapters.openai_agents.describe import CODEX_AGENTS_DESCRIBE
from mission_control.adapters.openai_agents.pack import load_pack as load_agents
from mission_control.adapters.remote_session.projection import configuration, project
from mission_control.application.authoring.manifest_launch_inputs import ManifestLaunchBindings
from mission_control.application.authoring.provider_launch import (
    LAUNCH_BINDINGS_SCHEMA_V2,
    required_pins,
)
from mission_control.domain.authoring.canonical import sha256_digest

ROOT: Final = Path(__file__).resolve().parents[1]
OUT_NAME: Final = "w1-launch-bindings-hosted.json"
MAIN_RUNTIME: Final = Path(
    "C:/Users/Pinda/Proyectos/BellLabs/platform/mission-control/.scratch/sprint-oc/runtime/ai-engineer"
)
ZERO: Final = "sha256:" + "0" * 64
MODEL_PROFILE: Final = "hosted.default"
ENVIRONMENT_REF: Final = "ai-engineer-knowledge"
PROVIDER: Final = {"claude_managed": "anthropic", "codex_agents": "openai"}
SCOPE: Final = {
    "claude_managed": CLAUDE_MANAGED_DESCRIBE.features["launch"].provider_scope,
    "codex_agents": CODEX_AGENTS_DESCRIBE.features["launch"].provider_scope,
}


def _pack_dir(root: Path, app: str, profile: str) -> Path:
    return root / "deployments" / "hosted-packs" / app / profile


def _managed(root: Path, app: str, instructions_root: Path | None, ingress: str | None) -> Any:
    pack = load_managed(_pack_dir(root, app, "claude_managed"))
    if ingress is None:
        networking = pack.environment.networking.model_copy(
            update={"include_signal_ingress": False}
        )
        pack = pack.model_copy(
            update={"environment": pack.environment.model_copy(update={"networking": networking})}
        )
    with tempfile.TemporaryDirectory() as scratch:
        repo = instructions_root
        if repo is None:
            repo = Path(scratch)
            rules = (_pack_dir(root, app, "codex_agents") / "repo-rules.md").read_text("utf-8")
            (repo / "AGENTS.md").write_text(rules, encoding="utf-8")
        # installation_id only enters the secret-set digest, which `configuration` omits.
        return render_pack(
            pack, installation_id="digest-only", repo_root=repo, ingress_host=ingress
        )


def _agents(root: Path, app: str) -> Any:
    """The codex_agents pack without its repository vault credential.

    The pack's `GITHUB_TOKEN` (api.github.com) is a read-only repository token: with it the
    worker's `HostedProjectionSource` demands a fresh per-binding read-only repository proof
    (`bootstrap/hosted_readonly.py`, which refuses a binding without `repo_url`), so a
    repository-less knowledge mission could never start, and its source variable is not in the
    W1 worker environment. These bindings serve repository-less missions only.
    """

    pack = load_agents(_pack_dir(root, app, "codex_agents"))
    document = pack.document.model_copy(
        update={"vault": pack.document.vault.model_copy(update={"credentials": ()})}
    )
    return replace(pack, document=document)


def _lane(
    profile: str,
    *,
    model_id: str,
    task_queue: str,
    environment_revision: str,
    projection: dict[str, Any],
    options: dict[str, Any],
    budgets: dict[str, int],
    policies: dict[str, str],
) -> dict[str, Any]:
    provider = PROVIDER[profile]
    return {
        "task_queue": task_queue,
        "model_profiles": {MODEL_PROFILE: {"profile": MODEL_PROFILE, "model_id": model_id}},
        "auth_profiles": {f"{profile}.api": {"profile": f"{profile}.api", "billing_mode": "api"}},
        "host_profiles": {
            ENVIRONMENT_REF: {
                "kind": "provider_hosted",
                "provider": provider,
                "environment_ref": ENVIRONMENT_REF,
                "expected_revision": environment_revision,
                "timeout_ceiling_s": budgets["wall_clock_s"],
            }
        },
        "pins": dict(required_pins(profile)),
        "provider_options": {"provider": profile, **options},
        "budgets": budgets,
        "agent_profile_ref": {
            "kind": "agent_profile",
            "logical_id": f"agent-profile.{ENVIRONMENT_REF}.{profile.replace('_', '-')}",
            "revision": 1,
            "digest": sha256_digest(projection),
        },
        **policies,
        "workspace": {
            "provider": SCOPE[profile],
            "runtime_digest": ZERO,
            "image_digest": ZERO,
            "package_digest": ZERO,
            "environment_digest": environment_revision,
            "network_policy": "allowlisted",
        },
        "hosted_projection": projection,
    }


def build(
    source: dict[str, Any],
    *,
    root: Path = ROOT,
    app: str = "ai-engineer",
    instructions_root: Path | None = None,
    signal_ingress_host: str | None = None,
    max_list_cost_minor_units: int = 100,
    budgets: dict[str, int] | None = None,
) -> dict[str, Any]:
    """The v2 document: `source` unchanged plus the two hosted provider entries."""

    if source.get("schema_version") != "mc.manifest_launch_bindings.v1" or source.get("providers"):
        raise SystemExit("SOURCE_NOT_W1_V1: expected a Deep Agents only v1 bindings file")
    budgets = budgets or {"max_turns": 4, "max_segments": 16, "wall_clock_s": 3600}
    scaffold = source["deep_agents"]
    policies = {
        key: scaffold[key]
        for key in ("tracing_policy_ref", "sensitive_data_policy_ref", "snapshot_policy_ref")
    }
    managed = _managed(root, app, instructions_root, signal_ingress_host)
    agents = _agents(root, app)
    if managed.pack.identity.task_queue != agents.document.task_queue:
        raise SystemExit("HOSTED_QUEUE_MISMATCH: the two packs name different task queues")
    providers = {
        "claude_managed": _lane(
            "claude_managed",
            model_id=managed.pack.agent.model,
            task_queue=managed.pack.identity.task_queue,
            environment_revision=managed.kit_digest,
            projection=configuration(managed),
            options={
                "tool_placement": managed.pack.identity.placement,
                "max_list_cost_minor_units": max_list_cost_minor_units,
            },
            budgets=budgets,
            policies=policies,
        ),
        "codex_agents": _lane(
            "codex_agents",
            model_id=agents.document.agent.model,
            task_queue=agents.document.task_queue,
            environment_revision=agents.template_digest,
            projection=configuration(agents),
            options={"tool_placement": agents.document.tool_placement},
            budgets=budgets,
            policies=policies,
        ),
    }
    document = {**source, "schema_version": LAUNCH_BINDINGS_SCHEMA_V2, "providers": providers}
    loaded = ManifestLaunchBindings.model_validate(document)
    assert loaded.providers is not None
    # The inline projection must re-render the reviewed pack exactly (no catalog rows).
    for profile, expected in (
        ("claude_managed", managed.materialization_digest),
        ("codex_agents", agents.digest),
    ):
        lane = loaded.providers.lane(profile)
        assert lane is not None and lane.hosted_projection is not None
        rendered = project(profile, lane.hosted_projection, (), installation_id="digest-only")
        actual = (
            rendered.materialization_digest
            if isinstance(rendered, RenderedPack)
            else rendered.digest
        )
        if actual != expected:
            raise SystemExit(f"PROJECTION_DRIFT: {profile} {actual} != {expected}")
    return document


def summary(document: dict[str, Any], out: Path, ingress: str | None) -> dict[str, Any]:
    providers = document["providers"]
    return {
        "out": str(out),
        "schema_version": document["schema_version"],
        "kept": sorted(key for key in document if key not in {"providers", "schema_version"}),
        "signal_ingress_host": ingress,
        "providers": {
            profile: {
                "task_queue": lane["task_queue"],
                "model": lane["model_profiles"][MODEL_PROFILE]["model_id"],
                "pins": lane["pins"],
                "provider_options": lane["provider_options"],
                "budgets": lane["budgets"],
                "environment": lane["host_profiles"][ENVIRONMENT_REF],
                "agent_profile_ref": lane["agent_profile_ref"]["digest"],
                "vault_credentials": [
                    item["name"]
                    for item in (
                        lane["hosted_projection"].get("vault")
                        or lane["hosted_projection"]["document"]["vault"]
                    )["credentials"]
                ],
            }
            for profile, lane in providers.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source", type=Path, default=MAIN_RUNTIME / "w1-launch-bindings-iter2.json"
    )
    parser.add_argument("--out-dir", type=Path, default=MAIN_RUNTIME)
    parser.add_argument("--app", default="ai-engineer", choices=("ai-engineer",))
    parser.add_argument(
        "--managed-instructions-root",
        type=Path,
        help="a directory whose AGENTS.md claude_managed renders into system "
        "(default: the codex_agents pack's repo-rules.md)",
    )
    parser.add_argument("--signal-ingress-host", help="add this host to Managed sandbox egress")
    parser.add_argument(
        "--managed-max-list-cost-cents",
        type=int,
        default=100,
        help="Managed Agents per-session budget.max_list_cost in USD cents (default 100)",
    )
    parser.add_argument("--max-turns", type=int, default=4)
    parser.add_argument("--max-segments", type=int, default=16)
    parser.add_argument("--wall-clock-s", type=int, default=3600)
    options = parser.parse_args()
    source = json.loads(options.source.read_text(encoding="utf-8"))
    document = build(
        source,
        app=options.app,
        instructions_root=options.managed_instructions_root,
        signal_ingress_host=options.signal_ingress_host,
        max_list_cost_minor_units=options.managed_max_list_cost_cents,
        budgets={
            "max_turns": options.max_turns,
            "max_segments": options.max_segments,
            "wall_clock_s": options.wall_clock_s,
        },
    )
    out = options.out_dir / OUT_NAME
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary(document, out, options.signal_ingress_host), indent=2))


if __name__ == "__main__":
    main()
