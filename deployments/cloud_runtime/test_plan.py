"""Offline deployment boundaries; no credentials, providers or AWS calls."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

SPEC = importlib.util.spec_from_file_location(
    "cloud_runtime_plan", Path(__file__).with_name("plan.py")
)
assert SPEC is not None and SPEC.loader is not None
planner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = planner
SPEC.loader.exec_module(planner)


def fixture() -> dict:
    role = "arn:aws:iam::123456789012:role/reviewed"
    reference = "arn:aws:secretsmanager:us-east-2:123456789012:secret:reviewed-123456"
    task = {
        "name": "mc-api",
        "role": "api",
        "runtime_dsn_env": "MC_BIOTECH_DB_RUNTIME_DSN",
        "deployment_file": "/etc/mission-control/deployment.json",
        "configuration_digest": "sha256:" + "a" * 64,
        "execution_role_arn": role,
        "task_role_arn": role,
        "environment": {
            "MISSION_CONTROL_RUNTIME_OPTIONS_FACTORY": "reviewed.options:build",
            "TEMPORAL_ADDRESS": "example.tmprl.cloud:7233",
            "TEMPORAL_NAMESPACE": "example",
            "CAPABILITY_PINS_PATH": "/etc/mission-control/pins.json",
        },
        "secrets": {"MC_BIOTECH_DB_RUNTIME_DSN": reference, "TEMPORAL_CLOUD_API_KEY": reference},
    }
    worker = copy.deepcopy(task)
    worker.update(
        {
            "name": "mc-worker",
            "role": "worker",
            "application_id": "biotech",
            "binding_digest": "sha256:" + "b" * 64,
            "family_dsn_env": "MC_BIOTECH_DB_FAMILY_WRITER_DSN",
        }
    )
    worker["secrets"].update(
        {
            "MC_BIOTECH_DB_FAMILY_WRITER_DSN": reference,
            "MC_BIOTECH_DB_CHECKPOINT_DSN": reference,
        }
    )
    return {
        "format_version": 1,
        "account_id": "123456789012",
        "region": "us-east-2",
        "cluster_arn": "arn:aws:ecs:us-east-2:123456789012:cluster/reviewed",
        "image": "example.invalid/mc@sha256:" + "c" * 64,
        "log_group": "/mc/runtime",
        "subnet_ids": ["subnet-0123456789abcdef0"],
        "security_group_ids": ["sg-0123456789abcdef0"],
        "tasks": [task, worker],
    }


def test_render_is_private_inert_and_application_scoped() -> None:
    result = planner.render(planner.Plan.model_validate(fixture()))
    assert result["status"] == "prepared_not_deployed"
    for service in result["service_review_inputs"]:
        assert service["desiredCount"] == 0
        assert (
            service["networkConfiguration"]["awsvpcConfiguration"]["assignPublicIp"] == "DISABLED"
        )
        assert not service["enableExecuteCommand"]
    worker = result["task_definitions"][1]["containerDefinitions"][0]
    env = {item["name"]: item["value"] for item in worker["environment"]}
    assert env["MISSION_CONTROL_WORKER_APPLICATION_ID"] == "biotech"
    assert env["LANGGRAPH_CHECKPOINT_SETUP"] == "false"
    assert env["TEMPORAL_TARGET"] == "cloud"
    assert "MC_BIOTECH_DB_RUNTIME_DSN" not in env
    assert worker["user"] == "10001:10001"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update(image="example.invalid/mc:latest"),
        lambda data: data["tasks"][0]["environment"].update(OPENAI_API_KEY="sensitive-value"),
        lambda data: data["tasks"][0]["environment"].update(
            AGENT_SERVER_ENDPOINT="https://user:pw@host"
        ),
        lambda data: data["tasks"][0]["secrets"].update(
            MC_BIOTECH_DB_RUNTIME_DSN="postgresql://user:pw@host/db"
        ),
        lambda data: data["tasks"][1].update(binding_digest=None),
        lambda data: data["tasks"][1]["secrets"].pop("MC_BIOTECH_DB_CHECKPOINT_DSN"),
        lambda data: data["tasks"][1].update(cpu=1024, memory=512),
        lambda data: data["tasks"][0]["secrets"].update(
            TEMPORAL_TARGET=data["tasks"][0]["secrets"]["MC_BIOTECH_DB_RUNTIME_DSN"]
        ),
        lambda data: data["tasks"][0]["environment"].update(
            TEMPORAL_ADDRESS="OWNER-SELECT: endpoint"
        ),
        lambda data: data["tasks"][1].update(task_role_arn="arn:aws:iam::999999999999:role/wrong"),
        lambda data: data.update(unreviewed_option="ignored?"),
    ],
)
def test_reject_unsafe_or_incomplete_configuration(mutation) -> None:
    data = fixture()
    mutation(data)
    with pytest.raises(ValidationError):
        planner.Plan.model_validate(data)


def test_invalid_input_never_echoes_secrets(tmp_path, monkeypatch, capsys) -> None:
    config = tmp_path / "plan.toml"
    config.write_text('secret = "do-not-echo-this"', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["plan.py", str(config)])
    assert planner.main() == 2
    output = capsys.readouterr()
    assert "do-not-echo-this" not in output.err + output.out


def test_generated_inputs_match_installed_aws_api_shapes() -> None:
    from botocore.session import Session
    from botocore.validate import validate_parameters

    # Loading the bundled service model makes no network/authentication request.
    service = Session().get_service_model("ecs")
    result = planner.render(planner.Plan.model_validate(fixture()))
    for definition in result["task_definitions"]:
        validate_parameters(
            definition, service.operation_model("RegisterTaskDefinition").input_shape
        )
    for inputs in result["service_review_inputs"]:
        validate_parameters(inputs, service.operation_model("CreateService").input_shape)
