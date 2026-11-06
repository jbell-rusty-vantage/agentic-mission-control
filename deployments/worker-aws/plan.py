"""Render the exact Run 2 AI Engineer task. Offline by default; no cloud calls."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ACCOUNT = "298199649527"
REGION = "us-east-1"
SERVICE = "mc-worker-ai-engineer"
BUCKET = f"mc-payloads-ai-engineer-{ACCOUNT}-use1"
ENV = {
    "TEMPORAL_TARGET": "cloud",
    "TEMPORAL_ADDRESS": "us-east-1.aws.api.temporal.io:7233",
    "TEMPORAL_NAMESPACE": "mission-control-dev.ih0e7",
    "MISSION_CONTROL_WORKER_ROLE": "base",
    "MISSION_CONTROL_WORKER_APPLICATION_ID": "ai-engineer",
    "MISSION_CONTROL_CATALOG_SCOPE": "mc/01a103c0-9a9e-70f3-9398-eb1573a98324/ai-engineer/catalog",
    "MISSION_CONTROL_LANE_TASK_QUEUES": '["mc-ai-engineer-lane-hosted"]',
    "MISSION_CONTROL_SPLIT_HOST": "true",
    "MISSION_CONTROL_DEPLOYMENT_FILE": "/etc/mission-control/deployment.json",
    "MANIFEST_LAUNCH_BINDINGS_PATH": "/etc/mission-control/launch-bindings.json",
    "CAPABILITY_PINS_PATH": "/etc/mission-control/capability-pins.json",
    "CAPABILITY_BUNDLE_BACKEND": "local",
    "CAPABILITY_BUNDLE_LOCAL_ROOT": "/etc/mission-control/capability-bundles",
    "MISSION_CONTROL_WORKSPACE_ROOT": "/etc/mission-control/assets",
    "COORDINATOR_LAUNCH_ENABLED": "true",
    "MISSION_CONTROL_CLAUDE_MANAGED_LANE": "true",
    "MISSION_CONTROL_CODEX_AGENTS_LANE": "true",
    "MISSION_CONTROL_CLAUDE_LANE": "false",
    "MISSION_CONTROL_CODEX_LANE": "false",
    "TEMPORAL_PROMOTE_ON_START": "false",
    "INGRESS_DRAINER_ENABLED": "true",
    "S3_BUCKET": BUCKET,
    "AWS_REGION": REGION,
    "AWS_PROFILE": "",
}
SECRETS = {
    "MC_AI_ENGINEER_RUNTIME_DSN",
    "MC_AI_ENGINEER_FAMILY_DSN",
    "LANGGRAPH_CHECKPOINT_DATABASE_DIRECT",
    "TEMPORAL_CLOUD_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "CURSOR_API_KEY",
}


def render(
    *,
    image: str,
    binding_digest: str,
    build_id: str,
    secrets: dict[str, str],
    ingress_origin: str,
    manifests: dict[str, str],
) -> dict:
    origin = urlsplit(ingress_origin)
    if (
        origin.scheme != "https"
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.path not in {"", "/"}
        or origin.query
        or origin.fragment
    ):
        raise ValueError("ingress origin must be a credential-free HTTPS origin")
    if (
        not isinstance(manifests, dict)
        or not manifests
        or not all(
            isinstance(ref, str)
            and ref
            and isinstance(path, str)
            and re.fullmatch(r"/etc/mission-control/manifests/[A-Za-z0-9_-]+\.ya?ml", path)
            for ref, path in manifests.items()
        )
    ):
        raise ValueError(
            "trusted manifests must name files under the immutable image manifest directory"
        )
    if not re.fullmatch(
        rf"{ACCOUNT}\.dkr\.ecr\.{REGION}\.amazonaws\.com/mission-control-worker@sha256:[a-f0-9]{{64}}",
        image,
    ):
        raise ValueError("image must be the approved ECR repository and immutable digest")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", binding_digest):
        raise ValueError("exact application binding digest required")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-[a-f0-9]{7,40}", build_id):
        raise ValueError("build id must be package-version plus Git SHA")
    if set(secrets) != SECRETS:
        raise ValueError("exact required secret names must be supplied")
    for name, arn in secrets.items():
        if not re.fullmatch(
            rf"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:mission-control/ai-engineer/{name}-[A-Za-z0-9]{{6}}",
            arn,
        ):
            raise ValueError("secret ARN is outside the exact approved prefix")
    environment = {
        **ENV,
        "TEMPORAL_BUILD_ID": build_id,
        "MISSION_CONTROL_WORKER_BINDING_DIGEST": binding_digest,
        "MISSION_CONTROL_SIGNAL_INGRESS_ORIGIN": ingress_origin.rstrip("/"),
        "INGRESS_MANIFEST_PATHS": json.dumps(manifests, sort_keys=True, separators=(",", ":")),
    }
    return {
        "family": SERVICE,
        "networkMode": "awsvpc",
        "requiresCompatibilities": ["FARGATE"],
        "cpu": "512",
        "memory": "2048",
        "runtimePlatform": {"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"},
        "executionRoleArn": f"arn:aws:iam::{ACCOUNT}:role/{SERVICE}-exec",
        "taskRoleArn": f"arn:aws:iam::{ACCOUNT}:role/{SERVICE}-task",
        "containerDefinitions": [
            {
                "name": "worker",
                "image": image,
                "essential": True,
                "user": "10001:10001",
                "command": ["python", "-m", "mission_control.bootstrap.worker"],
                "portMappings": [],
                "stopTimeout": 120,
                "environment": [
                    {"name": name, "value": value} for name, value in sorted(environment.items())
                ],
                "secrets": [
                    {"name": name, "valueFrom": arn} for name, arn in sorted(secrets.items())
                ],
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": "/mission-control/ai-engineer/worker",
                        "awslogs-region": REGION,
                        "awslogs-stream-prefix": "worker",
                    },
                },
            }
        ],
        "tags": [
            {"key": key, "value": value}
            for key, value in {
                "app": "mission-control",
                "application": "ai-engineer",
                "sprint": "materialization-observation-2026-10",
            }.items()
        ],
    }


def validate_task(task: dict) -> None:
    """Reconstruct the entire allowlisted task before any registration is attempted."""
    try:
        (container,) = task["containerDefinitions"]
        environment = {item["name"]: item["value"] for item in container["environment"]}
        secrets = {item["name"]: item["valueFrom"] for item in container["secrets"]}
        expected = render(
            image=container["image"],
            binding_digest=environment["MISSION_CONTROL_WORKER_BINDING_DIGEST"],
            build_id=environment["TEMPORAL_BUILD_ID"],
            secrets=secrets,
            ingress_origin=environment["MISSION_CONTROL_SIGNAL_INGRESS_ORIGIN"],
            manifests=json.loads(environment["INGRESS_MANIFEST_PATHS"]),
        )
    except (KeyError, TypeError, ValueError):
        raise ValueError("invalid worker task contract") from None
    if task != expected:
        raise ValueError("task differs from the exact reviewed worker contract")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate", type=Path)
    parser.add_argument("--image")
    parser.add_argument("--binding-digest")
    parser.add_argument("--build-id")
    parser.add_argument("--secret-arns", type=Path)
    parser.add_argument("--ingress-origin")
    parser.add_argument("--manifests", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.validate:
        validate_task(json.loads(args.validate.read_text()))
        return
    if not all(
        (
            args.image,
            args.binding_digest,
            args.build_id,
            args.secret_arns,
            args.out,
            args.ingress_origin,
            args.manifests,
        )
    ):
        parser.error(
            "render requires image, binding-digest, build-id, secret-arns, "
            "ingress-origin, manifests and out"
        )
    plan = render(
        image=args.image,
        binding_digest=args.binding_digest,
        build_id=args.build_id,
        secrets=json.loads(args.secret_arns.read_text()),
        ingress_origin=args.ingress_origin,
        manifests=json.loads(args.manifests.read_text()),
    )
    args.out.write_text(json.dumps(plan, indent=2) + "\n")


if __name__ == "__main__":
    main()
