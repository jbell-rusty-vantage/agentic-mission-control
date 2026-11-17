"""IP-013: the pin writer's research rows (Context7, GitHub, the knowledge capture server).

Each row is written from the catalog seed row and from what is on the host. No server is
started and nothing is downloaded: the tool lister and the binary's `--version` reader are
fakes, and an absent artifact is reported as not pinned with its reason.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from langchain_core.tools import BaseTool, StructuredTool

import mission_control.adapters.capabilities.capability_pins as capability_pins
from mission_control.adapters.capabilities.capability_pins import (
    CapabilityPins,
    PinnedExecutableMCPServer,
    PinnedMCPServer,
    PinnedRemoteMCPServer,
)
from mission_control.adapters.operations.runtime_ports import PinnedCapabilityAssetVerifier
from mission_control.bootstrap.settings import PROJECT_ROOT
from tests.fixtures.lane_bindings import lane_fields

PINS = PROJECT_ROOT / "infra" / "capability-pins" / "research-capabilities.json"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "mcp"
# The capture server's newest revision (3) was captured into its own fixture.
CAPTURE_FIXTURE = "mcp.knowledge-capture.1a451fd.tools.json"
ENDPOINT = "http://127.0.0.1:4310/mcp"
VERSION_LINE = (
    "Version: 2.1.0, Commit: 4bcdcdf8d7beee98c9448e73e257308280924cc4, "
    "Build Date: 2026-11-03T11:04:46Z"
)


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "pin_research_capabilities_rows", PROJECT_ROOT / "scripts" / "pin_research_capabilities.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rows(tool: ModuleType) -> dict[str, Any]:
    return dict(tool.catalog_rows())


def _names(server_id: str, fixture: str | None = None) -> list[str]:
    """The tools the server's captured fixture lists (the newest revision's own fixture)."""

    name = fixture or f"{server_id}.tools.json"
    document = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return [item["name"] for item in document["tools"]]


def _tools(names: Sequence[str]) -> list[BaseTool]:
    return [
        StructuredTool.from_function(func=lambda query: query, name=name, description=name)
        for name in names
    ]


class Lister:
    """Lists the given tool names and records the connection it was asked for."""

    def __init__(self, names: Sequence[str]) -> None:
        self.names = list(names)
        self.connections: list[Mapping[str, Any]] = []

    async def __call__(self, connection: Mapping[str, Any]) -> Sequence[BaseTool]:
        self.connections.append(connection)
        return _tools(self.names)


async def _never(connection: Mapping[str, Any]) -> Sequence[BaseTool]:
    raise AssertionError("no server is started for a row that cannot be pinned")


# --- mcp.knowledge-capture: the remote form -------------------------------------------------


async def test_the_capture_row_pins_the_catalog_allowlist_of_a_server_that_lists_more(
    tool: ModuleType, rows: dict[str, Any]
) -> None:
    listed = _names("mcp.knowledge-capture", CAPTURE_FIXTURE)
    lister = Lister(listed)

    pin = await tool.pin_knowledge_capture(
        ENDPOINT, rows["mcp.knowledge-capture"], credential_env=None, lister=lister
    )

    assert isinstance(pin, PinnedRemoteMCPServer)
    assert len(listed) == 42 and len(pin.tools) == 23
    assert {item.tool_name for item in pin.tools} == set(
        rows["mcp.knowledge-capture"].tool_allowlist
    )
    assert not {"ingest_apply", "db_sql_readonly"} & {item.tool_name for item in pin.tools}
    assert pin.tool_filter == "allowlist" and pin.credential_env is None
    # The endpoint was read from, and is nowhere in the pin.
    assert lister.connections == [
        {"transport": "streamable_http", "url": ENDPOINT, "headers": None}
    ]
    assert "127.0.0.1" not in pin.model_dump_json()
    assert (
        pin.source.startswith("git:") and "1a451fde077b3b29b990cb5170018421e7765d96" in pin.source
    )
    # What the writer pins is what the worker admits at the deployment's endpoint.
    component = pin.component(endpoint=ENDPOINT)
    assert component.tool_filter == "allowlist" and len(component.tools) == 23
    PinnedCapabilityAssetVerifier(
        CapabilityPins(remote_mcp_servers=(pin,)),
        mcp_endpoints={"mcp.knowledge-capture": ENDPOINT},
    ).verify_launch(
        SimpleNamespace(**lane_fields(SimpleNamespace(mcp_servers=(component,))))  # type: ignore[arg-type]
    )


async def test_the_capture_row_is_not_pinned_without_an_endpoint_a_token_or_a_listed_tool(
    tool: ModuleType, rows: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    row = rows["mcp.knowledge-capture"]
    monkeypatch.delenv("VERIFY_EXECUTOR_TOKEN", raising=False)

    missing = await tool.pin_knowledge_capture(None, row, credential_env=None, lister=_never)
    assert isinstance(missing, tool.NotPinned) and "no endpoint" in missing.reason

    no_token = await tool.pin_knowledge_capture(
        ENDPOINT, row, credential_env="VERIFY_EXECUTOR_TOKEN", lister=_never
    )
    assert isinstance(no_token, tool.NotPinned)
    assert "VERIFY_EXECUTOR_TOKEN is required" in no_token.reason

    fewer = [
        name
        for name in _names("mcp.knowledge-capture", CAPTURE_FIXTURE)
        if name != "verify_locate_quote"
    ]
    narrowed = await tool.pin_knowledge_capture(
        ENDPOINT, row, credential_env=None, lister=Lister(fewer)
    )
    assert isinstance(narrowed, tool.NotPinned) and "verify_locate_quote" in narrowed.reason

    monkeypatch.setenv("VERIFY_EXECUTOR_TOKEN", "executor-token-value")
    lister = Lister(_names("mcp.knowledge-capture", CAPTURE_FIXTURE))
    pinned = await tool.pin_knowledge_capture(
        ENDPOINT, row, credential_env="VERIFY_EXECUTOR_TOKEN", lister=lister
    )
    assert isinstance(pinned, PinnedRemoteMCPServer)
    assert pinned.credential_env == "VERIFY_EXECUTOR_TOKEN"
    assert lister.connections[0]["headers"] == {"Authorization": "Bearer executor-token-value"}
    assert "executor-token-value" not in pinned.model_dump_json()


# --- mcp.github: the executable form --------------------------------------------------------


async def test_the_github_row_pins_the_named_binary_by_digest_with_the_catalog_arguments(
    tool: ModuleType, rows: dict[str, Any], tmp_path: Path
) -> None:
    binary = tmp_path / "github-mcp-server.exe"
    binary.write_bytes(b"MZ reviewed release build")
    lister = Lister(_names("mcp.github"))

    pin = await tool.pin_github(
        binary, rows["mcp.github"], lister=lister, version_reader=lambda _path: VERSION_LINE
    )

    assert isinstance(pin, PinnedExecutableMCPServer)
    assert pin.command == str(binary)
    assert pin.command_digest == "sha256:" + sha256(binary.read_bytes()).hexdigest()
    assert pin.arguments == ("stdio", "--read-only", "--toolsets=repos,issues,pull_requests")
    assert (pin.package_name, pin.package_version) == ("github-mcp-server", "2.1.0")
    assert pin.credential_envs == ("GITHUB_PERSONAL_ACCESS_TOKEN",)
    assert pin.tool_filter == "exact" and len(pin.tools) == 22
    (connection,) = lister.connections
    assert connection["command"] == str(binary)
    assert connection["args"] == ["stdio", "--read-only", "--toolsets=repos,issues,pull_requests"]


async def test_the_github_row_is_not_pinned_when_the_binary_is_absent_or_another_build(
    tool: ModuleType, rows: dict[str, Any], tmp_path: Path
) -> None:
    row = rows["mcp.github"]

    unnamed = await tool.pin_github(None, row, lister=_never, version_reader=lambda _path: "")
    assert isinstance(unnamed, tool.NotPinned) and "nothing is downloaded" in unnamed.reason

    absent = await tool.pin_github(
        tmp_path / "missing.exe", row, lister=_never, version_reader=lambda _path: VERSION_LINE
    )
    assert isinstance(absent, tool.NotPinned) and "not an absolute path to a file" in absent.reason

    binary = tmp_path / "github-mcp-server.exe"
    binary.write_bytes(b"MZ another build")
    other = await tool.pin_github(
        binary, row, lister=_never, version_reader=lambda _path: "Version: 2.0.0, Commit: abc"
    )
    assert isinstance(other, tool.NotPinned) and "version 2.1.0" in other.reason

    # A token whose scopes hide tools lists fewer than the catalog row names: not pinned.
    fewer = await tool.pin_github(
        binary,
        row,
        lister=Lister(_names("mcp.github")[:-1]),
        version_reader=lambda _path: VERSION_LINE,
    )
    assert isinstance(fewer, tool.NotPinned) and "differ from its catalog row" in fewer.reason


# --- mcp.context7: the node-module form -----------------------------------------------------


def _install_context7(root: Path, version: str) -> Path:
    package = root / ".tools" / "node_modules" / "@upstash" / "context7-mcp"
    (package / "dist").mkdir(parents=True)
    (package / "dist" / "index.js").write_bytes(b"// context7 entry module")
    (package / "package.json").write_text(
        json.dumps({"name": "@upstash/context7-mcp", "version": version}), encoding="utf-8"
    )
    return package / "dist" / "index.js"


async def test_the_context7_row_pins_the_installed_module_at_the_catalog_version(
    tool: ModuleType, rows: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capability_pins, "workspace_root", lambda: tmp_path)
    node = tmp_path / "node.exe"
    node.write_bytes(b"node")
    row = rows["mcp.context7"]

    absent = await tool.pin_context7(node, row, lister=_never)
    assert isinstance(absent, tool.NotPinned)
    assert "@upstash/context7-mcp@4.7.0 is not installed" in absent.reason

    module = _install_context7(tmp_path, "4.7.0")
    lister = Lister(_names("mcp.context7"))
    pin = await tool.pin_context7(node, row, lister=lister)

    assert isinstance(pin, PinnedMCPServer)
    assert (pin.package_name, pin.package_version) == ("@upstash/context7-mcp", "4.7.0")
    assert pin.module_digest == "sha256:" + sha256(module.read_bytes()).hexdigest()
    assert [item.tool_name for item in pin.tools] == ["query-docs", "resolve-library-id"]
    assert pin.credential_env is None
    assert pin.verify_module() == module.resolve()


async def test_the_context7_row_is_not_pinned_at_another_version(
    tool: ModuleType, rows: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capability_pins, "workspace_root", lambda: tmp_path)
    _install_context7(tmp_path, "4.8.0")
    node = tmp_path / "node.exe"
    node.write_bytes(b"node")

    other = await tool.pin_context7(node, rows["mcp.context7"], lister=_never)

    assert isinstance(other, tool.NotPinned)
    assert "not the catalog's @upstash/context7-mcp@4.7.0" in other.reason


# --- the file ------------------------------------------------------------------------------


async def test_add_research_changes_only_the_research_rows_and_reports_the_rest(
    tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capability_pins, "workspace_root", lambda: tmp_path)
    monkeypatch.delenv("VERIFY_EXECUTOR_TOKEN", raising=False)
    output = tmp_path / "pins.json"
    output.write_bytes(PINS.read_bytes())
    before = json.loads(output.read_text(encoding="utf-8"))
    args = argparse.Namespace(
        node=None,
        github_mcp_server=None,
        knowledge_capture_endpoint=ENDPOINT,
        knowledge_capture_credential_env="none",
        context7_credential_env=None,
    )

    pinned, not_pinned = await tool.research_rows(
        args,
        lister=Lister(_names("mcp.knowledge-capture", CAPTURE_FIXTURE)),
        version_reader=lambda _path: "",
    )
    tool.add_research_rows(output, pinned)

    assert [row.server_id for row in pinned] == ["mcp.knowledge-capture"]
    assert {item.server_id for item in not_pinned} == {"mcp.context7", "mcp.github"}
    report = tool.research_report(pinned, not_pinned)
    assert report["pinned"]["mcp.knowledge-capture"]["form"] == "remote_mcp_servers"
    assert set(report["not_pinned"]) == {"mcp.context7", "mcp.github"}
    after = json.loads(output.read_text(encoding="utf-8"))
    assert {key: value for key, value in after.items() if key != "remote_mcp_servers"} == before
    assert b"\r" not in output.read_bytes()
    pins = CapabilityPins.load(output)
    assert [server.server_id for server in pins.remote_mcp_servers] == ["mcp.knowledge-capture"]
    # Writing the same rows again replaces them instead of naming a server twice.
    tool.add_research_rows(output, pinned)
    assert CapabilityPins.load(output) == pins
