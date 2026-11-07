"""Render reviewable ECS inputs locally; never call AWS or deploy resources."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

SAFE_ENV = frozenset(
    {
        "MISSION_CONTROL_RUNTIME_OPTIONS_FACTORY",
        "MISSION_CONTROL_WORKSPACE_ROOT",
        "MISSION_CONTROL_PREFLIGHT_WORKSPACE_ROOT",
        "MISSION_CONTROL_LOCAL_RUN_PROFILE",
        "CAPABILITY_PINS_PATH",
        "MANIFEST_LAUNCH_BINDINGS_PATH",
        "TEMPORAL_ADDRESS",
        "TEMPORAL_NAMESPACE",
        "LANGSMITH_PROJECT",
        "LANGSMITH_WORKSPACE_ID",
        "LANGSMITH_TRACING",
        "AGENT_SERVER_DEPLOYMENT_ENDPOINT_ID",
        "AGENT_SERVER_DEPLOYMENT_REVISION",
        "LANGGRAPH_RUNTIME_ENABLED",
        "ASYNC_SUBAGENT_SPAWNING_ENABLED",
        "DEEP_AGENT_CHECKPOINTER_DIGESTS",
        "DEEP_AGENT_STORE_DIGESTS",
        "S3_BUCKET",
        "S3_ENDPOINT_URL",
        "S3_FORCE_PATH_STYLE",
        "S3_REGION",
        "BELL_LABS_ENVIRONMENT",
    }
)
DIGEST = r"^sha256:[a-f0-9]{64}$"
FIXED_ENV = frozenset(
    {
        "MISSION_CONTROL_HOME",
        "MISSION_CONTROL_DEPLOYMENT_FILE",
        "TEMPORAL_TARGET",
        "RUN_CONTROL_TEMPORAL_ENABLED",
        "COORDINATOR_LAUNCH_ENABLED",
        "LANGGRAPH_CHECKPOINT_SETUP",
        "LANGGRAPH_CHECKPOINT_SCHEMA",
        "AWS_REGION",
        "MISSION_CONTROL_WORKER_APPLICATION_ID",
        "MISSION_CONTROL_WORKER_BINDING_DIGEST",
        "PATH",
        "PYTHONPATH",
    }
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Task(Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{1,60}$")
    role: Literal["api", "worker"]
    application_id: Literal["biotech", "ai-engineer"] | None = None
    binding_digest: str | None = Field(default=None, pattern=DIGEST)
    runtime_dsn_env: str = Field(pattern=r"^MC_(AIENG|BIOTECH)_DB_RUNTIME_DSN$")
    family_dsn_env: str | None = Field(
        default=None, pattern=r"^MC_(AIENG|BIOTECH)_DB_FAMILY_WRITER_DSN$"
    )
    deployment_file: str = Field(pattern=r"^/etc/mission-control/[a-zA-Z0-9_./-]+\.json$")
    # Pin the separately reviewed public configuration baked into the image.
    configuration_digest: str = Field(pattern=DIGEST)
    execution_role_arn: str
    task_role_arn: str
    cpu: Literal[256, 512, 1024] = 512
    memory: Literal[512, 1024, 2048, 3072, 4096] = 2048
    environment: dict[str, str] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_task(self) -> Task:
        if self.memory < self.cpu * 2 or (self.cpu == 256 and self.memory > 2048):
            raise ValueError("unsupported Fargate CPU/memory combination")
        if set(self.environment) - SAFE_ENV:
            raise ValueError(
                "environment contains unreviewed names; use secret references for secrets"
            )
        if set(self.environment) & set(self.secrets):
            raise ValueError("environment and secret names overlap")
        if set(self.secrets) & (SAFE_ENV | FIXED_ENV):
            raise ValueError("secrets cannot override deployment configuration")
        if ".." in Path(self.deployment_file).parts:
            raise ValueError("deployment file must stay under the configuration directory")
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", name) for name in self.secrets):
            raise ValueError("secret environment names must be uppercase identifiers")
        if not self.environment.get("MISSION_CONTROL_RUNTIME_OPTIONS_FACTORY"):
            raise ValueError("a reviewed runtime-options factory is required")
        if not self.environment.get("TEMPORAL_ADDRESS") or not self.environment.get(
            "TEMPORAL_NAMESPACE"
        ):
            raise ValueError("Temporal Cloud address and namespace must be explicit")
        required = {self.runtime_dsn_env, "TEMPORAL_CLOUD_API_KEY"}
        if self.role == "worker":
            if not self.application_id or not self.binding_digest or not self.family_dsn_env:
                raise ValueError("worker needs exact application, binding, and family writer")
            checkpoint_env = self.runtime_dsn_env.removesuffix("RUNTIME_DSN") + "CHECKPOINT_DSN"
            required.update({self.family_dsn_env, checkpoint_env})
            if not self.environment.get("CAPABILITY_PINS_PATH"):
                raise ValueError("worker requires explicit reviewed capability pins")
        elif self.application_id is not None or self.binding_digest is not None:
            raise ValueError("API does not select a worker application")
        if required - set(self.secrets):
            raise ValueError("required runtime secret references are missing")
        for value in self.environment.values():
            if "://" in value and ("@" in value or "?" in value or "#" in value):
                raise ValueError("credential-bearing URLs are forbidden")
        return self


class Plan(Strict):
    format_version: Literal[1]
    account_id: str = Field(pattern=r"^[0-9]{12}$")
    region: str = Field(pattern=r"^[a-z]{2}-[a-z]+-[1-9]$")
    cluster_arn: str
    image: str = Field(pattern=r"^[^\s]+@sha256:[a-f0-9]{64}$")
    log_group: str = Field(pattern=r"^/[a-zA-Z0-9/_.-]+$")
    subnet_ids: list[str] = Field(min_length=1)
    security_group_ids: list[str] = Field(min_length=1)
    tasks: list[Task] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_plan(self) -> Plan:
        if "OWNER-SELECT:" in self.model_dump_json():
            raise ValueError("operator selections remain unresolved")
        prefix = f"arn:aws:ecs:{self.region}:{self.account_id}:cluster/"
        if not self.cluster_arn.startswith(prefix):
            raise ValueError("cluster must belong to the selected account and region")
        if len({task.name for task in self.tasks}) != len(self.tasks):
            raise ValueError("task names must be unique")
        if sum(task.role == "api" for task in self.tasks) != 1:
            raise ValueError("exactly one shared API is required")
        workers = [task.application_id for task in self.tasks if task.role == "worker"]
        if len(set(workers)) != len(workers):
            raise ValueError("configure one worker service per application")
        for value in self.subnet_ids:
            if not re.fullmatch(r"subnet-[a-f0-9]{8,17}", value):
                raise ValueError("subnets must be existing subnet IDs")
        for value in self.security_group_ids:
            if not re.fullmatch(r"sg-[a-f0-9]{8,17}", value):
                raise ValueError("security groups must be existing IDs")
        for task in self.tasks:
            for role in (task.execution_role_arn, task.task_role_arn):
                if not re.fullmatch(rf"arn:aws:iam::{self.account_id}:role/[\w/+=,.@-]+", role):
                    raise ValueError("roles must belong to the selected account")
            for reference in task.secrets.values():
                pattern = (
                    rf"arn:aws:secretsmanager:{self.region}:{self.account_id}:secret:[\w/+=,.@:-]+"
                )
                if not re.fullmatch(pattern, reference):
                    raise ValueError(
                        "secrets must be Secrets Manager ARNs in this account and region"
                    )
        return self


def render(plan: Plan) -> dict[str, object]:
    definitions: list[dict[str, object]] = []
    services: list[dict[str, object]] = []
    for task in plan.tasks:
        environment = {
            **task.environment,
            "MISSION_CONTROL_DEPLOYMENT_FILE": task.deployment_file,
            "TEMPORAL_TARGET": "cloud",
            "RUN_CONTROL_TEMPORAL_ENABLED": "true",
            "COORDINATOR_LAUNCH_ENABLED": "true",
            "LANGGRAPH_CHECKPOINT_SETUP": "false",
            "LANGGRAPH_CHECKPOINT_SCHEMA": "mission_control_runtime",
            "AWS_REGION": plan.region,
        }
        container: dict[str, object] = {
            "name": task.name,
            "image": plan.image,
            "essential": True,
            "user": "10001:10001",
            "stopTimeout": 60,
            "linuxParameters": {"initProcessEnabled": True},
            "environment": [
                {"name": key, "value": value} for key, value in sorted(environment.items())
            ],
            "secrets": [
                {"name": key, "valueFrom": value} for key, value in sorted(task.secrets.items())
            ],
            "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-region": plan.region,
                    "awslogs-group": plan.log_group,
                    "awslogs-stream-prefix": task.name,
                    "mode": "non-blocking",
                    "max-buffer-size": "5m",
                },
            },
        }
        if task.role == "worker":
            environment["MISSION_CONTROL_WORKER_APPLICATION_ID"] = task.application_id or ""
            environment["MISSION_CONTROL_WORKER_BINDING_DIGEST"] = task.binding_digest or ""
            container["command"] = ["python", "-m", "mission_control.bootstrap.worker"]
        else:
            container["command"] = [
                "uvicorn",
                "mission_control.bootstrap.api:create_app",
                "--factory",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ]
            container["portMappings"] = [{"containerPort": 8000, "protocol": "tcp"}]
            container["healthCheck"] = {
                "command": [
                    "CMD",
                    "python",
                    "-c",
                    "import urllib.request; "
                    "urllib.request.urlopen('http://127.0.0.1:8000/health/live', "
                    "timeout=3).close()",
                ],
                "interval": 30,
                "timeout": 5,
                "retries": 3,
                "startPeriod": 60,
            }
        container["environment"] = [
            {"name": key, "value": value} for key, value in sorted(environment.items())
        ]
        definitions.append(
            {
                "family": task.name,
                "networkMode": "awsvpc",
                "requiresCompatibilities": ["FARGATE"],
                "cpu": str(task.cpu),
                "memory": str(task.memory),
                "runtimePlatform": {"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"},
                "executionRoleArn": task.execution_role_arn,
                "taskRoleArn": task.task_role_arn,
                "containerDefinitions": [container],
                "tags": [{"key": "configuration-digest", "value": task.configuration_digest}],
            }
        )
        services.append(
            {
                "cluster": plan.cluster_arn,
                "serviceName": task.name,
                "taskDefinition": "REVIEW: replace with the exact registered task definition ARN",
                "desiredCount": 0,
                "launchType": "FARGATE",
                "platformVersion": "1.4.0",
                "enableExecuteCommand": False,
                "deploymentConfiguration": {
                    "maximumPercent": 100,
                    "minimumHealthyPercent": 0,
                    "deploymentCircuitBreaker": {"enable": True, "rollback": True},
                },
                "networkConfiguration": {
                    "awsvpcConfiguration": {
                        "subnets": plan.subnet_ids,
                        "securityGroups": plan.security_group_ids,
                        "assignPublicIp": "DISABLED",
                    }
                },
            }
        )
    return {
        "status": "prepared_not_deployed",
        "task_definitions": definitions,
        "service_review_inputs": services,
        "gates": [
            "Owner approval: monthly cap, proof budget, exact resource/security plan",
            "Existing egress, ingress, roles, secret references and log retention verified",
            "Image/configuration digests verified; reviewed assets and runtime options installed",
            "Common release, app auth, checkpoint persistence and Temporal readiness verified",
            "Durable shared object store and provider evidence qualified",
            "Agent Server entitlement, app isolation, native recovery and authentication qualified",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    try:
        plan = Plan.model_validate(tomllib.loads(args.config.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError):
        # Validation errors may contain input values; never echo them into shared logs.
        sys.stderr.write("BLOCKED: invalid deployment plan; validate against plan.py fields.\n")
        return 2
    sys.stdout.write(json.dumps(render(plan), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
