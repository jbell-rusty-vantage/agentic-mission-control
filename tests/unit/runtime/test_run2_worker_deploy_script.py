# ruff: noqa: E501
"""Execute the real PowerShell deployment script with a hermetic AWS function."""

import json
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PLAN = runpy.run_path(str(ROOT / "deployments/worker-aws/plan.py"))
SERVICE = runpy.run_path(str(ROOT / "deployments/worker-aws/service.py"))
GROUP = "sg-" + "a" * 17
TASK_ARN = "arn:aws:ecs:us-east-1:298199649527:task-definition/mc-worker-ai-engineer:1"
MUTATIONS = {"ecs register-task-definition", "ecs create-service", "ecs update-service"}

MOCK = r"""
param([string]$Fixture, [string]$Calls, [string]$Task, [string]$Deploy,
      [string]$Python, [string]$Group, [switch]$Create)
$ErrorActionPreference = 'Stop'
$global:MockFixture = Get-Content -LiteralPath $Fixture -Raw | ConvertFrom-Json
$global:MockCalls = $Calls
$global:MockLists = 0
function global:aws {
    $action = "$($args[0]) $($args[1])"
    $record = $action
    if ($action -eq 'ecs update-service') {
        $position = [Array]::IndexOf($args, '--desired-count')
        $record += " desired=$($args[$position + 1])"
    }
    if ($action -eq 'ecs wait') {
        $record += " $($args[2])"
        if ($args[2] -eq 'tasks-stopped') {
            $position = [Array]::IndexOf($args, '--tasks')
            $record += " $($args[$position + 1].Split('/')[-1])"
        }
    }
    Add-Content -LiteralPath $global:MockCalls -Value $record
    $global:LASTEXITCODE = 0
    switch ($action) {
        'sts get-caller-identity' { $global:MockFixture.identity | ConvertTo-Json -Depth 20; return }
        'ecs describe-services' { $global:MockFixture.services | ConvertTo-Json -Depth 20; return }
        'ec2 describe-security-groups' { $global:MockFixture.groups | ConvertTo-Json -Depth 20; return }
        'ec2 describe-subnets' { $global:MockFixture.subnets | ConvertTo-Json -Depth 20; return }
        'ecs register-task-definition' { $global:MockFixture.taskArn; return }
        'ecs list-tasks' {
            $global:MockLists += 1
            $name = if ($global:MockLists -le 2) { 'old-task' } else { 'late-task' }
            @{taskArns=@("arn:aws:ecs:us-east-1:298199649527:task/mission-control/$name")} | ConvertTo-Json
            return
        }
        'ecs create-service' {
            $index = [Array]::IndexOf($args, '--cli-input-json')
            if ($index -lt 0) { throw 'create must use rendered JSON' }
            $plan = Get-Content -LiteralPath ($args[$index + 1].Substring(7)) -Raw | ConvertFrom-Json
            $plan | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath ($global:MockCalls + '.create.json')
            if ($global:MockFixture.failure -eq 'uncertain_create') { $global:LASTEXITCODE = 1; return }
            'arn:aws:ecs:us-east-1:298199649527:service/mission-control/mc-worker-ai-engineer'; return
        }
        'ecs update-service' { 'arn:aws:ecs:us-east-1:298199649527:service/mission-control/mc-worker-ai-engineer'; return }
        'ecs wait' {
            if ($args[2] -eq 'tasks-stopped' -and $global:MockFixture.failure -eq 'stop_wait_failed') {
                $global:LASTEXITCODE = 1
            }
            return
        }
        default { throw "Unexpected mocked AWS action: $action" }
    }
}
try {
    & $Deploy -TaskDefinition $Task -Python $Python -SecurityGroupId $Group -CreateService:$Create -Apply
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""


def fixture(create, drift):
    network = SERVICE["render"](TASK_ARN, GROUP)["networkConfiguration"]
    service = {
        "serviceName": SERVICE["SERVICE"],
        "serviceArn": "arn:aws:ecs:us-east-1:298199649527:service/mission-control/mc-worker-ai-engineer",
        "clusterArn": "arn:aws:ecs:us-east-1:298199649527:cluster/mission-control",
        "status": "ACTIVE",
        "desiredCount": 1,
        "runningCount": 1,
        "pendingCount": 0,
        "launchType": "FARGATE",
        "schedulingStrategy": "REPLICA",
        "deploymentController": {"type": "ECS"},
        "enableExecuteCommand": False,
        "loadBalancers": [],
        "serviceRegistries": [],
        "networkConfiguration": network,
        "deployments": [{"status": "PRIMARY", "rolloutState": "COMPLETED"}],
    }
    group = {
        "GroupId": GROUP,
        "GroupName": "mc-worker-egress-only",
        "VpcId": SERVICE["VPC_ID"],
        "IpPermissions": [],
        "IpPermissionsEgress": [{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
    }
    subnets = [
        {
            "SubnetId": subnet,
            "VpcId": SERVICE["VPC_ID"],
            "State": "available",
            "DefaultForAz": True,
            "MapPublicIpOnLaunch": True,
        }
        for subnet in SERVICE["SUBNETS"]
    ]
    if drift == "network":
        group["VpcId"] = "vpc-unapproved"
    elif drift == "group":
        group["IpPermissions"] = [{"IpProtocol": "-1"}]
    elif drift == "subnet":
        subnets[0]["MapPublicIpOnLaunch"] = False
    elif drift == "exec":
        service["enableExecuteCommand"] = True
    elif drift == "lb":
        service["loadBalancers"] = [{"targetGroupArn": "unapproved"}]
    elif drift == "controller":
        service["deploymentController"] = {"type": "EXTERNAL"}
    elif drift == "desired":
        service["desiredCount"] = 2
    elif drift == "running":
        service["runningCount"] = 2
    elif drift == "pending":
        service["pendingCount"] = 1
    # A first-create request cannot adopt an already existing service, including drifted ones.
    absent = create and drift not in {"exec", "lb", "controller", "desired", "running", "pending"}
    return {
        "identity": {"Account": "298199649527"},
        "services": {
            "services": [] if absent else [service],
            "failures": [{"reason": "MISSING"}] if absent else [],
        },
        "groups": {"SecurityGroups": [group]},
        "subnets": {"Subnets": subnets},
        "taskArn": TASK_ARN,
        "failure": drift,
    }


def execute(tmp_path, create, drift=None):
    pwsh = shutil.which("pwsh")
    assert pwsh, "PowerShell is required to exercise the actual deploy script"
    task = PLAN["render"](
        image="298199649527.dkr.ecr.us-east-1.amazonaws.com/mission-control-worker@sha256:"
        + "a" * 64,
        binding_digest="sha256:" + "b" * 64,
        build_id="0.1.0-abcdef1",
        secrets={
            name: f"arn:aws:secretsmanager:us-east-1:298199649527:secret:mission-control/ai-engineer/{name}-Abcd12"
            for name in PLAN["SECRETS"]
        },
        ingress_origin="https://fixture.invalid",
        manifests={"probe": "/etc/mission-control/manifests/probe.yaml"},
    )
    wrapper, fixtures, task_path, calls = (
        tmp_path / name for name in ("mock.ps1", "fixture.json", "task.json", "calls.txt")
    )
    wrapper.write_text(MOCK, encoding="utf-8")
    fixtures.write_text(json.dumps(fixture(create, drift)), encoding="utf-8")
    task_path.write_text(json.dumps(task), encoding="utf-8")
    command = [
        pwsh,
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(wrapper),
        "-Fixture",
        str(fixtures),
        "-Calls",
        str(calls),
        "-Task",
        str(task_path),
        "-Deploy",
        str(ROOT / "deployments/worker-aws/deploy.ps1"),
        "-Python",
        sys.executable,
        "-Group",
        GROUP,
    ]
    if create:
        command.append("-Create")
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=30, check=False
    )
    actions = calls.read_text(encoding="utf-8-sig").splitlines() if calls.exists() else []
    return result, actions, calls


@pytest.mark.parametrize("create", [True, False])
@pytest.mark.parametrize(
    "drift",
    ["network", "group", "subnet", "exec", "lb", "controller", "desired", "running", "pending"],
)
def test_drift_refuses_before_any_mutation(tmp_path, create, drift):
    result, actions, _ = execute(tmp_path, create, drift)
    assert result.returncode != 0, result.stdout + result.stderr
    assert not any(action.startswith(tuple(MUTATIONS)) for action in actions)


@pytest.mark.parametrize("create", [True, False])
def test_exact_first_create_and_update_execute_real_plan_renderer(tmp_path, create):
    result, actions, calls = execute(tmp_path, create)
    assert result.returncode == 0, result.stdout + result.stderr
    prefix = [
        "sts get-caller-identity",
        "ecs describe-services",
        "ec2 describe-security-groups",
        "ec2 describe-subnets",
        "ecs register-task-definition",
    ]
    expected = (
        ["ecs create-service"]
        if create
        else [
            "ecs list-tasks",
            "ecs list-tasks",
            "ecs update-service desired=0",
            "ecs wait services-stable",
            "ecs list-tasks",
            "ecs list-tasks",
            "ecs wait tasks-stopped late-task",
            "ecs wait tasks-stopped old-task",
            "ecs update-service desired=1",
        ]
    )
    assert actions == prefix + expected + ["ecs wait services-stable"]
    if create:
        actual = json.loads(Path(str(calls) + ".create.json").read_text(encoding="utf-8-sig"))
        assert actual == SERVICE["render"](TASK_ARN, GROUP)


def test_uncertain_create_is_not_retried_or_updated(tmp_path):
    result, actions, _ = execute(tmp_path, True, "uncertain_create")
    assert result.returncode != 0
    assert actions.count("ecs create-service") == 1
    assert not any(action.startswith("ecs update-service") for action in actions)
    assert "ecs wait services-stable" not in actions


def test_failed_old_task_wait_never_starts_replacement(tmp_path):
    result, actions, _ = execute(tmp_path, False, "stop_wait_failed")
    assert result.returncode != 0
    assert "ecs update-service desired=0" in actions
    assert any(action.startswith("ecs wait tasks-stopped") for action in actions)
    assert "ecs update-service desired=1" not in actions


@pytest.mark.parametrize(
    "key",
    ["CAPABILITY_BUNDLE_BACKEND", "CAPABILITY_BUNDLE_LOCAL_ROOT", "MISSION_CONTROL_CATALOG_SCOPE"],
)
def test_operator_public_environment_is_fixed_and_validated(key):
    task = PLAN["render"](
        image="298199649527.dkr.ecr.us-east-1.amazonaws.com/mission-control-worker@sha256:"
        + "a" * 64,
        binding_digest="sha256:" + "b" * 64,
        build_id="0.1.0-abcdef1",
        secrets={
            name: f"arn:aws:secretsmanager:us-east-1:298199649527:secret:mission-control/ai-engineer/{name}-Abcd12"
            for name in PLAN["SECRETS"]
        },
        ingress_origin="https://fixture.invalid",
        manifests={"probe": "/etc/mission-control/manifests/probe.yaml"},
    )
    PLAN["validate_task"](task)
    environment = task["containerDefinitions"][0]["environment"]
    assert {item["name"]: item["value"] for item in environment}[key] == {
        "CAPABILITY_BUNDLE_BACKEND": "local",
        "CAPABILITY_BUNDLE_LOCAL_ROOT": "/etc/mission-control/capability-bundles",
        "MISSION_CONTROL_CATALOG_SCOPE": "mc/01a103c0-9a9e-70f3-9398-eb1573a98324/ai-engineer/catalog",
    }[key]
    next(item for item in environment if item["name"] == key)["value"] = "unreviewed"
    with pytest.raises(ValueError, match="exact reviewed worker contract"):
        PLAN["validate_task"](task)
