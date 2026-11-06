"""Render first-service creation for the owner-selected default VPC; no AWS calls."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ACCOUNT = "298199649527"
REGION = "us-east-1"
SERVICE = "mc-worker-ai-engineer"
VPC_ID = "vpc-04db3b23ff1cee487"
SUBNETS = (
    "subnet-070333667ef52535d",
    "subnet-0efe52bd60be362ea",
    "subnet-0eb0cdfbe77ed7327",
    "subnet-088e18d96815df31d",
    "subnet-0a6434aad9d46d724",
    "subnet-018b0b7eb2bab137c",
)


def render(task_definition: str, security_group: str) -> dict:
    if not re.fullmatch(
        rf"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/{SERVICE}:[1-9][0-9]*",
        task_definition,
    ):
        raise ValueError("exact account, region and worker task revision required")
    if not re.fullmatch(r"sg-[a-f0-9]{17}", security_group):
        raise ValueError("reviewed worker security group required")
    return {
        "cluster": "mission-control",
        "serviceName": SERVICE,
        "taskDefinition": task_definition,
        "desiredCount": 1,
        "launchType": "FARGATE",
        "availabilityZoneRebalancing": "DISABLED",
        "enableExecuteCommand": False,
        "deploymentConfiguration": {
            "minimumHealthyPercent": 0,
            "maximumPercent": 100,
            "deploymentCircuitBreaker": {"enable": True, "rollback": True},
        },
        "networkConfiguration": {
            "awsvpcConfiguration": {
                "subnets": list(SUBNETS),
                "securityGroups": [security_group],
                "assignPublicIp": "ENABLED",
            }
        },
        "tags": [
            {"key": "app", "value": "mission-control"},
            {"key": "application", "value": "ai-engineer"},
            {"key": "sprint", "value": "materialization-observation-2026-10"},
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-definition", required=True)
    parser.add_argument("--security-group", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.write_text(
        json.dumps(render(args.task_definition, args.security_group), indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
