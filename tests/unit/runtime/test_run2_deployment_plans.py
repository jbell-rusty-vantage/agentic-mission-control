"""Reviewable deployment plans refuse broader authority before cloud mutation."""

import copy
import json
import runpy
from pathlib import Path

import pytest

from tests.fixtures.isolated_settings import isolated_settings

ROOT = Path(__file__).resolve().parents[3]
PLAN = runpy.run_path(str(ROOT / "deployments/worker-aws/plan.py"))
SERVICE = runpy.run_path(str(ROOT / "deployments/worker-aws/service.py"))


def render():
    return PLAN["render"](
        image=f"{PLAN['ACCOUNT']}.dkr.ecr.us-east-1.amazonaws.com/mission-control-worker@sha256:"
        + "a" * 64,
        binding_digest="sha256:" + "b" * 64,
        build_id="0.1.0-abcdef1",
        secrets={
            name: f"arn:aws:secretsmanager:us-east-1:{PLAN['ACCOUNT']}:"
            f"secret:mission-control/ai-engineer/{name}-Abcd12"
            for name in PLAN["SECRETS"]
        },
        ingress_origin="https://fixture.invalid",
        manifests={"probe": "/etc/mission-control/manifests/probe.yaml"},
    )


def test_task_roundtrip_has_usable_trusted_manifest_registry():
    task = render()
    PLAN["validate_task"](task)
    environment = {
        item["name"]: item["value"] for item in task["containerDefinitions"][0]["environment"]
    }
    settings = isolated_settings(
        ingress_manifest_paths=json.loads(environment["INGRESS_MANIFEST_PATHS"]),
        mission_control_signal_ingress_origin=environment["MISSION_CONTROL_SIGNAL_INGRESS_ORIGIN"],
    )
    assert str(settings.ingress_manifest_paths["probe"]).replace("\\", "/") == (
        "/etc/mission-control/manifests/probe.yaml"
    )
    assert settings.mission_control_signal_ingress_origin == "https://fixture.invalid"
    assert task["containerDefinitions"][0]["portMappings"] == []


@pytest.mark.parametrize("mutation", ["cpu", "image", "secret", "extra_env", "manifest_escape"])
def test_changed_authority_is_rejected(mutation):
    task = copy.deepcopy(render())
    container = task["containerDefinitions"][0]
    if mutation == "cpu":
        task["cpu"] = "4096"
    elif mutation == "image":
        container["image"] = container["image"].replace("us-east-1", "eu-west-1")
    elif mutation == "secret":
        container["secrets"][0]["valueFrom"] += "wrong"
    elif mutation == "extra_env":
        container["environment"].append({"name": "AWS_ACCESS_KEY_ID", "value": "fixture"})
    else:
        for item in container["environment"]:
            if item["name"] == "INGRESS_MANIFEST_PATHS":
                item["value"] = json.dumps({"probe": "/etc/mission-control/manifests/../secret"})
    with pytest.raises(ValueError):
        PLAN["validate_task"](task)


def test_first_service_uses_selected_network_and_one_base_worker():
    arn = "arn:aws:ecs:us-east-1:298199649527:task-definition/mc-worker-ai-engineer:1"
    plan = SERVICE["render"](arn, "sg-" + "a" * 17)
    assert plan["desiredCount"] == 1
    assert plan["enableExecuteCommand"] is False
    assert plan["availabilityZoneRebalancing"] == "DISABLED"
    assert plan["deploymentConfiguration"]["maximumPercent"] == 100
    assert plan["deploymentConfiguration"]["minimumHealthyPercent"] == 0
    network = plan["networkConfiguration"]["awsvpcConfiguration"]
    assert network["subnets"] == list(SERVICE["SUBNETS"])
    assert len(network["subnets"]) == 6
    assert network["assignPublicIp"] == "ENABLED"
    assert "loadBalancers" not in plan
    for changed in (
        arn.replace("us-east-1", "us-east-2"),
        arn.replace("298199649527", "111111111111"),
        arn.replace("mc-worker-ai-engineer", "other-worker"),
        arn.removesuffix(":1"),
    ):
        with pytest.raises(ValueError):
            SERVICE["render"](changed, "sg-" + "a" * 17)
