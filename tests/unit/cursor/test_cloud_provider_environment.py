"""MO-13 on the `cursor_cloud` lane (FIXTURE Cloud and environments APIs, real local git remote).

`prepare` reads the committed `.cursor/environment.json` on the default branch (the one Cursor's
Builds use) before anything is published: a foreign file refuses the launch, an mc-owned file
(the kit's rendering under its marker) is used as is, and `sync` provisions `mc-<kit>-<digest8>`
for the target repository with the binding's secrets by name.
The run branch carries the kit's mission layer for the environment's `start`; the create never
names the environment (Cursor refuses `env.name` with `repos`), so the agent still starts on
the run branch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.cursor.environments import (
    ENVIRONMENT_FILE,
    CursorEnvironmentProvisioner,
)
from mission_control.adapters.cursor.workspace import git
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.application.agentic_components.placement import LaneProjectionError
from mission_control.application.environments.kits import EnvironmentKitCatalog
from mission_control.application.environments.provider_environments import (
    PROVIDER_ENVIRONMENT_REFUSED,
    ProviderEnvironmentService,
)
from mission_control.application.secrets.broker import SecretBroker
from mission_control.domain.authoring.environment_kits import MISSION_SETUP_KIT, MISSION_SETUP_RUN
from tests.fixtures.cursor_cloud import CloudStack, cloud_stack
from tests.fixtures.cursor_controls import started_session
from tests.fixtures.cursor_environments import (
    FakeEnvironmentsApi,
    cursor_environments,
    kit_in_custody,
)
from tests.fixtures.cursor_local import make_repository
from tests.fixtures.environment_kits import StaticDefinitions, kit_document, kit_pin

TOKEN = "mo13-fixture-setup-token-7d1e"
INSTALL = b"#!/usr/bin/env bash\nset -euo pipefail\necho base\n"
MARKER = "mc:envkit.fixture@1"


def remote_with(root: Path, files: dict[str, str], *, default_branch: str = "main") -> Path:
    """A bare `origin` whose default branch commits `files` beside the fixture repository
    (`main`, or a new `default_branch` whose files `main` does not carry)."""

    source = make_repository(root / "source")
    if default_branch != "main":
        git("checkout", "-q", "-b", default_branch, cwd=source)
    for path, content in files.items():
        target = source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    if files:
        git("add", "--all", cwd=source)
        git("-c", "user.name=F", "-c", "user.email=f@localhost", "commit", "-qm", "env", cwd=source)
    bare = root / "remote.git"
    git("clone", "--quiet", "--bare", str(source), str(bare), cwd=root)
    return bare


async def stack_with(
    tmp_path: Path,
    api: FakeEnvironmentsApi,
    *,
    committed: dict[str, str] | None = None,
    strategy: dict[str, Any] | None = None,
    composed: bool = True,
    remote: Path | None = None,
    default_branch: str = "main",
) -> CloudStack:
    document = kit_document(base={"install": "base/install.sh"})
    published, bundles = await kit_in_custody(
        tmp_path / "custody", document, ("base/install.sh", INSTALL)
    )
    provisioner = CursorEnvironmentProvisioner(
        ProviderEnvironmentService(
            cursor_environments(api),
            broker=SecretBroker(environment=WorkerEnvironmentSource({"FIXTURE_TOKEN": TOKEN})),
        ),
        EnvironmentKitCatalog(StaticDefinitions(published), bundles=bundles),
    )
    provider = strategy or {
        "strategy": "sync",
        "kit_pin": kit_pin(published),
        "secret_refs": ["FIXTURE_SETUP_TOKEN=environment:FIXTURE_TOKEN"],
    }
    return cloud_stack(
        tmp_path,
        remote=remote or remote_with(tmp_path, committed or {}, default_branch=default_branch),
        cloud_changes={"provider_environment": provider},
        harness_changes={"environments": provisioner} if composed else None,
    )


def branch_files(stack: CloudStack, branch: str) -> set[str]:
    listed = git("ls-tree", "-r", "--name-only", branch, cwd=stack.remote)
    return set(listed.split())


async def test_sync_provisions_the_kit_environment_and_the_agent_starts_on_the_run_branch(
    tmp_path: Path,
) -> None:
    api = FakeEnvironmentsApi()
    stack = await stack_with(tmp_path, api)
    _heid, handle = await started_session(stack)

    (environment,) = api.environments.values()
    assert environment["name"].startswith("mc-envkit.fixture-")
    assert environment["repos"] == [{"url": str(stack.remote)}]
    config = json.loads(api.history[environment["id"]][0]["environmentJson"])
    assert config["name"] == MARKER
    assert ".mission/setup/run --phase start" in config["start"]
    assert "echo base" in config["install"]
    assert api.secrets[environment["id"]] == {"FIXTURE_SETUP_TOKEN": TOKEN}

    (create,) = stack.api.creates
    assert "env" not in create, "Cursor refuses env.name with repos; the repository resolves it"
    branch = create["repos"][0]["startingRef"]
    assert {MISSION_SETUP_RUN, MISSION_SETUP_KIT} <= branch_files(stack, branch)

    details = handle.native_details
    assert details["provider_environment"] == "sync:created"
    assert details["provider_environment_name"] == environment["name"]
    assert details["provider_environment_secrets"] == "FIXTURE_SETUP_TOKEN"
    assert TOKEN not in json.dumps(details)
    assert TOKEN not in json.dumps(stack.api.creates)


async def test_a_second_mission_with_the_same_kit_reuses_the_environment(tmp_path: Path) -> None:
    api = FakeEnvironmentsApi()
    first = await stack_with(tmp_path / "first", api)
    await started_session(first)
    writes = len(api.writes())
    second = await stack_with(tmp_path / "second", api, remote=first.remote)
    second.operation = second.operation.model_copy(
        update={"identity": second.operation.identity.model_copy(update={"run_id": "run-two"})}
    )
    _heid, handle = await started_session(second)
    assert handle.native_details["provider_environment"] == "sync:reused"
    assert api.writes()[writes:] == [("POST", "/v1/environments")], "no PATCH, no secret PUT"
    assert len(api.environments) == 1


async def test_a_foreign_committed_file_refuses_before_anything_is_published(
    tmp_path: Path,
) -> None:
    api = FakeEnvironmentsApi()
    stack = await stack_with(
        tmp_path, api, committed={ENVIRONMENT_FILE: '{"name": "Biotech backend (Docker Compose)"}'}
    )
    with pytest.raises(LaneProjectionError) as refused:
        await started_session(stack)
    assert refused.value.code == PROVIDER_ENVIRONMENT_REFUSED
    assert "carries no Mission Control kit marker" in str(refused.value)
    assert api.requests == []
    assert stack.api.creates == []
    assert git("branch", "--list", "mc/*", cwd=stack.remote).strip() == ""


async def test_the_default_branch_file_decides_whatever_the_base_ref(tmp_path: Path) -> None:
    """Cursor's Builds use the default branch's file: a foreign one there refuses the launch
    although the run's base ref (`main`) carries none."""

    api = FakeEnvironmentsApi()
    stack = await stack_with(
        tmp_path,
        api,
        committed={ENVIRONMENT_FILE: '{"name": "Biotech backend (Docker Compose)"}'},
        default_branch="trunk",
    )
    assert ENVIRONMENT_FILE not in branch_files(stack, "main")
    with pytest.raises(LaneProjectionError, match="carries no Mission Control kit marker"):
        await started_session(stack)
    assert api.requests == []


async def test_a_missing_secret_is_a_named_lane_refusal(tmp_path: Path) -> None:
    api = FakeEnvironmentsApi()
    published, _bundles = await kit_in_custody(
        tmp_path / "pin",
        kit_document(base={"install": "base/install.sh"}),
        ("base/install.sh", INSTALL),
    )
    stack = await stack_with(
        tmp_path,
        api,
        strategy={
            "strategy": "sync",
            "kit_pin": kit_pin(published),
            "secret_refs": ["FIXTURE_SETUP_TOKEN=environment:FIXTURE_MISSING"],
        },
    )
    with pytest.raises(LaneProjectionError) as refused:
        await started_session(stack)
    assert refused.value.code == PROVIDER_ENVIRONMENT_REFUSED
    assert "FIXTURE_SETUP_TOKEN" in str(refused.value)
    assert api.requests == [] and stack.api.creates == []


async def test_binding_the_committed_file_launches_on_it(tmp_path: Path) -> None:
    api = FakeEnvironmentsApi()
    stack = await stack_with(
        tmp_path,
        api,
        committed={ENVIRONMENT_FILE: '{"name": "Biotech backend (Docker Compose)"}'},
        strategy={"strategy": "bind", "ref": ENVIRONMENT_FILE},
    )
    _heid, handle = await started_session(stack)
    assert handle.native_details["provider_environment"] == "bind:bound"
    assert handle.native_details["provider_environment_file"] == "foreign"
    assert api.requests == []


async def rendered_config(tmp_path: Path) -> str:
    """The kit's rendering for the fixture binding, as a `sync` writes it."""

    api = FakeEnvironmentsApi()
    await started_session(await stack_with(tmp_path, api))
    ((entry,),) = api.history.values()
    config: str = entry["environmentJson"]
    return config


async def test_an_mc_owned_file_is_the_base_layer_and_the_mission_layer_rides_the_branch(
    tmp_path: Path,
) -> None:
    config = await rendered_config(tmp_path / "render")
    api = FakeEnvironmentsApi()
    stack = await stack_with(tmp_path, api, committed={ENVIRONMENT_FILE: config})
    _heid, handle = await started_session(stack)
    assert handle.native_details["provider_environment"] == "sync:repo_file"
    assert handle.native_details["provider_environment_file"] == "mc_owned"
    assert api.requests == [], "a committed mc-owned file shadows any saved environment"
    (create,) = stack.api.creates
    assert MISSION_SETUP_RUN in branch_files(stack, create["repos"][0]["startingRef"])


async def test_the_kit_marker_over_stale_content_is_foreign(tmp_path: Path) -> None:
    api = FakeEnvironmentsApi()
    stale = json.dumps({"name": MARKER, "install": "echo stale", "egressMode": "allow_all"})
    stack = await stack_with(tmp_path, api, committed={ENVIRONMENT_FILE: stale})
    with pytest.raises(LaneProjectionError, match="is not the kit's rendering") as refused:
        await started_session(stack)
    assert refused.value.code == PROVIDER_ENVIRONMENT_REFUSED
    assert api.requests == [] and stack.api.creates == []


async def test_a_strategy_without_an_environments_api_is_refused(tmp_path: Path) -> None:
    stack = await stack_with(tmp_path, FakeEnvironmentsApi(), composed=False)
    with pytest.raises(LaneProjectionError, match="no environments API is composed"):
        await started_session(stack)
    assert stack.api.creates == []
