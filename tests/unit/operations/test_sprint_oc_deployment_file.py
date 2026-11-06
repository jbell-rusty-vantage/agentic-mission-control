"""OVE-169: the operator deployment file and bearer for the local W1 topology.

The written file must load through the real ``load_deployment`` (sealed binding digest, relative
JWKS), name the generator's secret refs and a per-application Temporal namespace, and the minted
operator bearer must authenticate through the real ``MissionTokenVerifier`` for the minted tenant.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from mission_control.adapters.auth.jwt import MissionTokenVerifier
from mission_control.bootstrap.api import load_deployment
from mission_control.domain.policies.stop_fence import immediate_cancel_permissions
from mission_control.domain.programs.human_gate import HumanGateSpec, is_reviewer

ROOT = Path(__file__).resolve().parents[3]
TENANT = "7f3e2d1c-0b9a-4876-9543-210fedcba987"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "sprint_oc_deployment_file", ROOT / "scripts" / "sprint_oc_deployment_file.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


script = _module()


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    (repo / ".gitignore").write_text("runtime/\n", encoding="utf-8")
    mc = tmp_path / "mc"
    for app in ("biotech", "ai-engineer"):
        shutil.copytree(ROOT / "deployments" / app, mc / "deployments" / app)
    out = repo / "runtime" / "biotech"
    out.mkdir(parents=True)
    (out / "minted.env").write_text(f"KNOWLEDGE_VERIFICATION_TENANT_ID={TENANT}\n", "utf-8")
    return {"repo": repo, "mc": mc, "out": out}


def _run(world: dict[str, Path], *extra: str) -> tuple[int, dict]:
    base = ["--app", "biotech", "--mc-root", str(world["mc"]), "--out", str(world["out"])]
    return script.run([*base, *extra])


def test_deployment_loads_and_the_operator_bearer_authenticates(world: dict[str, Path]) -> None:
    code, summary = _run(world, "--component-version", "1.7.0")
    assert code == 0, summary
    assert summary["database_secret_ref"] == "MC_BIOTECH_RUNTIME_DSN"
    assert summary["family_writer_secret_ref"] == "MC_BIOTECH_FAMILY_WRITER_DSN"
    assert summary["temporal"]["namespace"] == "mc-biotech"
    assert summary["installation_id"] == "01a103c0-9a9e-7a95-961b-29dda83c842b"
    deployment = load_deployment(world["out"] / "deployment.json")
    (item,) = deployment.applications
    binding = item.authentication.binding
    assert binding.binding_digest == summary["binding_digest"]
    assert binding.required_component_version == "1.7.0"
    assert item.temporal is not None and item.temporal.queue_base == "biotech-research-ingestion"
    private = json.loads((world["out"] / "operator-issuer.jwk.json").read_text("utf-8"))
    public = (world["out"] / "operator-jwks.json").read_text("utf-8")
    assert private["d"] not in public  # the public JWKS never carries the private scalar

    # Rerun: the same key, the same binding digest.
    again_code, again = _run(world, "--component-version", "1.7.0")
    assert again_code == 0 and again["binding_digest"] == summary["binding_digest"]
    assert again["operator"]["kid"] == summary["operator"]["kid"]

    code, minted = _run(world, "token", "--ttl-minutes", "5")
    assert code == 0 and minted["subject"] == script.OPERATOR_SUBJECT
    bearer = (world["out"] / "operator-token.txt").read_text("utf-8").strip()
    verifier = MissionTokenVerifier((item.authentication,))
    actor = verifier.authenticate("biotech", bearer)
    assert str(actor.identity.tenant_id) == TENANT
    assert "workflow.launch" in actor.actor.permissions
    # W1 D2: the operator may review an exact KS use decision.
    assert "knowledge.review" in actor.actor.permissions
    # W1 stuck cancels: the operator may cancel immediately even while work is active or the
    # run is already cancelling (the Stop Fence's admin requirement).
    for phase in ("active", "waiting", "cancelling", "paused"):
        assert immediate_cancel_permissions(phase) <= actor.actor.permissions

    # W1 review S4: a distinct reviewer principal (never the launcher) with review, no launch.
    code, reviewer = _run(world, "token", "--role", "reviewer", "--ttl-minutes", "5")
    assert code == 0 and reviewer["subject"] == script.REVIEWER_SUBJECT
    assert reviewer["token_file"].endswith("reviewer-token.txt")
    review_bearer = (world["out"] / "reviewer-token.txt").read_text("utf-8").strip()
    assert review_bearer != bearer
    reviewing = verifier.authenticate("biotech", review_bearer)
    assert reviewing.actor.actor_id == script.REVIEWER_ACTOR != actor.actor.actor_id
    assert "knowledge.review" in reviewing.actor.permissions
    assert not {"workflow.launch", "workflow_run.start", "workflow_run.admit"} & set(
        reviewing.actor.permissions
    )
    # Loop iter-1 L1-04: the reviewer (never the operator) resolves the loop fixtures' human
    # gates, which name `reviewers: [owner]` (E4b gate: operator 403, reviewer 200).
    gates = _experiment_loop_gate_reviewers()
    assert gates == {"owner"}
    for name in gates:
        gate = HumanGateSpec(gate_key="review", prompt="Review", reviewers=(name,))
        assert is_reviewer(gate, reviewing.actor.actor_id, reviewing.actor.permissions)
        assert not is_reviewer(gate, actor.actor.actor_id, actor.actor.permissions)


def _experiment_loop_gate_reviewers() -> set[str]:
    import yaml

    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "reviewers" and isinstance(value, list):
                    found.update(str(item) for item in value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    root = Path(__file__).resolve().parents[2] / "fixtures" / "manifests" / "experiment-loop"
    for path in sorted(root.glob("*.mission.yml")):
        walk(yaml.safe_load(path.read_text("utf-8")))
    return found


def test_refusals_name_the_missing_input(world: dict[str, Path]) -> None:
    code, summary = _run(world)
    assert code == 2 and summary["code"] == "COMPONENT_VERSION_REQUIRED"
    (world["out"] / "minted.env").unlink()
    code, summary = _run(world, "--component-version", "1.7.0")
    assert code == 2 and summary["code"] == "TENANT_MISSING"
    outside = world["repo"].parent / "not-ignored" / "biotech"
    outside.mkdir(parents=True)
    base = ["--app", "biotech", "--mc-root", str(world["mc"]), "--out", str(outside)]
    code, summary = script.run([*base, "--tenant", TENANT, "--component-version", "1.7.0"])
    assert code == 2 and summary["code"].startswith("OUTPUT_NOT")


def test_the_local_operator_factory_loads_through_the_reviewed_hook(world: dict[str, Path]) -> None:
    from mission_control.bootstrap.api import load_runtime_options

    code, _summary = _run(world, "--component-version", "1.7.0")
    assert code == 0
    deployment = load_deployment(world["out"] / "deployment.json")
    options = load_runtime_options(
        deployment, "mission_control.bootstrap.local_operator:runtime_options"
    )
    assert options is not None and set(options) == {"biotech"}
    assert options["biotech"].family_admissions is not None
    assert options["biotech"].artifact_payloads is not None


def test_reviewer_grant_prints_the_ks_command_naming_no_secret(world: dict[str, Path]) -> None:
    """W1 confirm review S1: the reviewer's live KS grant is a scripted step (KS
    `knowledge-verify grant-reviewer`); the argv names the DSN variable, never a value."""

    code, printed = _run(world, "reviewer-grant", "--uses", "report_consumption")
    assert code == 0 and printed["status"] == "command"
    argv = printed["argv"]
    assert argv[0] == "node" and argv[1].startswith("--env-file=")
    assert argv[1].endswith("ks-executor.env") and argv[3] == "grant-reviewer"
    flags = dict(zip(argv[4::2], argv[5::2], strict=True))
    assert flags == {
        "--database-url-env": "KS_BIOTECH_COMPONENT_DSN",
        "--tenant": TENANT,
        "--reviewer": script.REVIEWER_ACTOR,
        "--granted-by": script.OPERATOR_ACTOR,
        "--uses": "report_consumption",
        "--audiences": "internal",
        "--report-kinds": "evidence_report",
    }
    assert "postgresql://" not in " ".join(argv)


def test_reviewer_grant_defaults_to_the_w1_fixture_scope_never_a_wildcard(
    world: dict[str, Path], tmp_path: Path
) -> None:
    """W1 round 3 (least privilege): the fixture task's exact use, audience and report kind."""

    def scope(*extra: str) -> dict[str, str]:
        code, printed = _run(world, "reviewer-grant", *extra)
        assert code == 0, printed
        argv = printed["argv"]
        return dict(zip(argv[4::2], argv[5::2], strict=False))

    flags = scope()
    assert (flags["--uses"], flags["--audiences"], flags["--report-kinds"]) == (
        "label_reference.ingredients",
        "internal",
        "evidence_report",
    )
    assert "*" not in " ".join(flags.values())
    pack = tmp_path / "pack.json"
    pack.write_text(
        json.dumps({"task": {"use": "label_reference.ingredients", "audience": "official"}}),
        encoding="utf-8",
    )
    assert scope("--pack", str(pack))["--audiences"] == "official"
    code, refused = _run(world, "reviewer-grant", "--audiences", "*")
    assert code == 2 and refused["code"] == "SCOPE_WILDCARD_REFUSED"
    code, wide = _run(world, "reviewer-grant", "--audiences", "*", "--allow-wildcard")
    assert code == 0 and wide["argv"][-1] == "--allow-wildcard"
