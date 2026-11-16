"""IP-008: the pin file's two further forms of MCP server, and the worker's launch check.

A remote Streamable HTTP server is pinned by its bound tools and credential name and connected
at the endpoint the deployment supplies; a stdio executable that is not a node module is pinned
by absolute path and the sha256 of its bytes. The node-module form is unchanged. Every refusal
names the pin and the fact that failed.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from mission_control.adapters.capabilities.capability_pins import (
    CapabilityPinError,
    CapabilityPins,
    PinnedExecutableMCPServer,
    PinnedRemoteMCPServer,
    pinned_mcp_component,
)
from mission_control.adapters.operations.runtime_ports import PinnedCapabilityAssetVerifier
from mission_control.application.authoring.manifest_launch_inputs import (
    CapabilityComponentBinding,
    ManifestLaunchBindings,
)
from mission_control.bootstrap.manifests import resolve_pinned_capabilities, served_components
from mission_control.bootstrap.settings import PROJECT_ROOT, get_settings
from mission_control.domain.authoring.contracts import SecretRef
from mission_control.domain.execution.contracts import DeepAgentMCPToolComponent
from tests.fixtures.lane_bindings import lane_fields

PINS = PROJECT_ROOT / "infra" / "capability-pins" / "research-capabilities.json"
ENDPOINT = "http://127.0.0.1:4310/mcp"
A, B, C, D = ("sha256:" + digit * 64 for digit in "abcd")


def _ref(logical_id: str, digest: str) -> dict[str, Any]:
    return {"kind": "mcp_server", "logical_id": logical_id, "revision": 1, "digest": digest}


def _remote(**changes: Any) -> PinnedRemoteMCPServer:
    values: dict[str, Any] = {
        "server_id": "mcp.capture",
        "server_name": "capture",
        "ref": _ref("mcp.capture", A),
        "source": "example/executor@0.1.0",
        "schema_digest": B,
        "credential_env": "CAPTURE_TOKEN",
        "tool_filter": "allowlist",
        "tools": [
            {"tool_name": "capture_source", "schema_digest": C},
            {"tool_name": "read_capture", "schema_digest": D},
        ],
    }
    values.update(changes)
    return PinnedRemoteMCPServer.model_validate(values)


def _executable(path: Path, **changes: Any) -> PinnedExecutableMCPServer:
    values: dict[str, Any] = {
        "server_id": "mcp.repos",
        "server_name": "repos",
        "ref": _ref("mcp.repos", B),
        "package_name": "repos-mcp-server",
        "package_version": "2.1.0",
        "command": str(path),
        "command_digest": "sha256:" + sha256(path.read_bytes()).hexdigest(),
        "arguments": ["stdio", "--read-only", "--toolsets=repos,issues"],
        "schema_digest": C,
        "credential_envs": ["REPOS_TOKEN"],
        "tools": [{"tool_name": "get_file_contents", "schema_digest": D}],
    }
    values.update(changes)
    return PinnedExecutableMCPServer.model_validate(values)


def _binding(*components: Any, children: tuple[Any, ...] = ()) -> Any:
    return SimpleNamespace(
        **lane_fields(SimpleNamespace(mcp_servers=components, sync_subagents=children))
    )


@pytest.fixture
def binary(tmp_path: Path) -> Path:
    path = tmp_path / "bin" / "repos-mcp-server.exe"
    path.parent.mkdir()
    path.write_bytes(b"\x7fELF reviewed server build")
    return path


# --- the remote form ------------------------------------------------------------------------


def test_a_remote_pin_is_the_component_at_the_deployments_endpoint() -> None:
    pin = _remote()
    component = pin.component(endpoint=ENDPOINT)

    assert (component.transport, component.endpoint) == ("streamable_http", ENDPOINT)
    assert component.command is None and component.arguments == ()
    assert component.credential_refs == (SecretRef(provider="environment", key="CAPTURE_TOKEN"),)
    assert component.tool_filter == "allowlist"
    assert [tool.tool_name for tool in component.tools] == ["capture_source", "read_capture"]
    assert _remote(credential_env=None).component(endpoint=ENDPOINT).credential_refs == ()


@pytest.mark.parametrize(
    "endpoint",
    [None, "", "ftp://host/mcp", "http:///mcp", "https://user:secret@host/mcp", "http://h/mcp#x"],
)
def test_a_remote_pin_refuses_a_missing_or_malformed_endpoint(endpoint: str | None) -> None:
    with pytest.raises(CapabilityPinError, match="mcp.capture") as refused:
        _remote().component(endpoint=endpoint)
    assert "secret" not in str(refused.value)


def test_the_worker_connects_a_remote_server_only_as_pinned() -> None:
    pin = _remote()
    pins = CapabilityPins(remote_mcp_servers=(pin,))
    verifier = PinnedCapabilityAssetVerifier(pins, mcp_endpoints={"mcp.capture": ENDPOINT})
    exact = pin.component(endpoint=ENDPOINT)

    verifier.verify_launch(_binding(exact))

    wrong_digest = exact.model_copy(
        update={
            "tools": (
                exact.tools[0],
                DeepAgentMCPToolComponent(tool_name="read_capture", schema_digest=A),
            )
        }
    )
    with pytest.raises(ValueError) as refused:
        verifier.verify_launch(_binding(wrong_digest))
    message = str(refused.value)
    assert "differs from its pin mcp.capture" in message
    assert f"tool read_capture is bound at schema digest {A}, pinned at {D}" in message

    extra = exact.model_copy(
        update={
            "tools": (
                *exact.tools,
                DeepAgentMCPToolComponent(tool_name="ingest_apply", schema_digest=A),
            )
        }
    )
    with pytest.raises(ValueError, match="ingest_apply are bound but not pinned"):
        verifier.verify_launch(_binding(extra))
    with pytest.raises(ValueError, match="pinned tool.s. read_capture are not bound"):
        verifier.verify_launch(_binding(exact.model_copy(update={"tools": exact.tools[:1]})))
    with pytest.raises(ValueError, match="tool filter is exact, pinned allowlist"):
        verifier.verify_launch(_binding(exact.model_copy(update={"tool_filter": "exact"})))
    elsewhere = exact.model_copy(update={"endpoint": "https://elsewhere.example/mcp"})
    with pytest.raises(ValueError, match="endpoint differ") as redirected:
        verifier.verify_launch(_binding(elsewhere))
    assert "elsewhere.example" not in str(redirected.value)
    with pytest.raises(ValueError, match="credential refs differ"):
        verifier.verify_launch(_binding(exact.model_copy(update={"credential_refs": ()})))


def test_a_remote_pin_without_a_deployment_endpoint_is_refused_by_the_worker() -> None:
    pin = _remote()
    exact = pin.component(endpoint=ENDPOINT)
    verifier = PinnedCapabilityAssetVerifier(CapabilityPins(remote_mcp_servers=(pin,)))

    with pytest.raises(ValueError, match="no endpoint in this deployment") as refused:
        verifier.verify_launch(_binding(exact))
    assert "MCP_SERVER_ENDPOINTS['mcp.capture']" in str(refused.value)


def test_a_loosened_exact_pin_is_refused() -> None:
    pin = _remote(tool_filter="exact")
    verifier = PinnedCapabilityAssetVerifier(
        CapabilityPins(remote_mcp_servers=(pin,)), mcp_endpoints={"mcp.capture": ENDPOINT}
    )
    exact = pin.component(endpoint=ENDPOINT)
    assert exact.tool_filter == "exact"
    verifier.verify_launch(_binding(exact))
    with pytest.raises(ValueError, match="tool filter is allowlist, pinned exact"):
        verifier.verify_launch(_binding(exact.model_copy(update={"tool_filter": "allowlist"})))


# --- the executable form --------------------------------------------------------------------


def test_an_executable_pin_is_verified_by_digest_before_every_launch(binary: Path) -> None:
    pin = _executable(binary)
    verifier = PinnedCapabilityAssetVerifier(CapabilityPins(executable_mcp_servers=(pin,)))
    exact = pin.component()

    assert (exact.transport, exact.command) == ("stdio", str(binary))
    # Arguments are a list handed to the process as-is: nothing is joined into a shell line.
    assert exact.arguments == ("stdio", "--read-only", "--toolsets=repos,issues")
    assert exact.credential_refs == (SecretRef(provider="environment", key="REPOS_TOKEN"),)
    verifier.verify_launch(_binding(exact))

    with pytest.raises(ValueError, match="arguments differ"):
        verifier.verify_launch(
            _binding(exact.model_copy(update={"arguments": ("stdio", "--toolsets=all")}))
        )
    with pytest.raises(ValueError, match="command differ"):
        verifier.verify_launch(
            _binding(exact.model_copy(update={"command": str(binary.with_name("other.exe"))}))
        )

    pinned_digest = pin.command_digest
    binary.write_bytes(b"\x7fELF another build")
    observed = "sha256:" + sha256(binary.read_bytes()).hexdigest()
    with pytest.raises(ValueError) as refused:
        verifier.verify_launch(_binding(exact))
    message = str(refused.value)
    assert "pinned MCP executable mcp.repos" in message
    assert observed in message and pinned_digest in message

    binary.unlink()
    with pytest.raises(ValueError, match="mcp.repos is unavailable"):
        verifier.verify_launch(_binding(exact))


def test_an_executable_pin_needs_an_absolute_command(binary: Path) -> None:
    for command in ("repos-mcp-server", "bin/repos-mcp-server", "./server", "cmd /c server"):
        with pytest.raises(ValidationError, match="absolute command path"):
            _executable(binary, command=command)
    with pytest.raises(ValidationError):
        _executable(binary, credential_envs=["lower_case"])
    with pytest.raises(ValidationError, match="credential twice"):
        _executable(binary, credential_envs=["TOKEN", "TOKEN"])
    # Both host spellings of an absolute path are admitted by the file format.
    _executable(binary, command="/opt/mcp/github-mcp-server")
    _executable(binary, command="C:\\tools\\github-mcp-server.exe")


# --- the pin file and its readers -----------------------------------------------------------


def test_the_committed_pin_file_reads_unchanged_and_the_node_form_is_untouched() -> None:
    pins = CapabilityPins.load(PINS)
    assert pins.remote_mcp_servers == () and pins.executable_mcp_servers == ()
    assert {server.server_id for server in pins.all_mcp_servers} == {"mcp.firecrawl", "mcp.tavily"}
    assert "remote_mcp_servers" not in pins.disclosure()
    with pytest.raises(CapabilityPinError, match="requires the deployment's node"):
        pinned_mcp_component(pins.pinned_mcp_server("mcp.tavily"), node_executable=None)


def test_every_form_is_served_disclosed_and_named_once(binary: Path, tmp_path: Path) -> None:
    remote, executable = _remote(), _executable(binary)
    pins = CapabilityPins(remote_mcp_servers=(remote,), executable_mcp_servers=(executable,))

    assert pins.mcp_schema_digests() == {"mcp.capture": B, "mcp.repos": C}
    assert served_components(pins, get_settings()).mcp_servers == {A, B}
    disclosure = pins.disclosure()
    assert disclosure["remote_mcp_servers"][0]["credential_ref"] == "environment:CAPTURE_TOKEN"  # type: ignore[index]
    assert disclosure["remote_mcp_servers"][0]["endpoint"].startswith("deployment:")  # type: ignore[index]
    assert disclosure["executable_mcp_servers"][0]["command_digest"] == executable.command_digest  # type: ignore[index]

    path = tmp_path / "pins.json"
    document = pins.model_dump(mode="json")
    path.write_text(json.dumps(document), encoding="utf-8")
    assert CapabilityPins.load(path) == pins
    document["executable_mcp_servers"][0]["server_id"] = "mcp.capture"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CapabilityPinError, match="an MCP server twice"):
        CapabilityPins.load(path)


def test_the_launch_author_resolves_a_pinned_remote_server_at_the_deployment_endpoint() -> None:
    pin = _remote()
    pins = CapabilityPins(remote_mcp_servers=(pin,))
    scaffold = ManifestLaunchBindings.model_construct(
        capabilities={
            "mcp.capture": CapabilityComponentBinding(
                catalog_digest=D, kind="mcp_server", pinned="mcp.capture"
            )
        }
    )

    resolved = resolve_pinned_capabilities(
        scaffold, pins, node_executable=None, mcp_endpoints={"mcp.capture": ENDPOINT}
    )

    component = resolved.capabilities["mcp.capture"].mcp_server
    assert component == pin.component(endpoint=ENDPOINT)
    with pytest.raises(ValueError, match="mcp.capture: .*no endpoint in this deployment"):
        resolve_pinned_capabilities(scaffold, pins, node_executable=None)


def test_a_childs_seeded_server_is_held_to_the_pins_too(binary: Path) -> None:
    pin = _executable(binary)
    verifier = PinnedCapabilityAssetVerifier(CapabilityPins(executable_mcp_servers=(pin,)))
    seeded = pin.component(attachment_target="agent.subagent.reviewer")

    verifier.verify_launch(_binding(children=(SimpleNamespace(seeded_mcp_servers=(seeded,)),)))

    unpinned = seeded.model_copy(
        update={"ref": seeded.ref.model_copy(update={"digest": "sha256:" + "7" * 64})}
    )
    with pytest.raises(ValueError, match="repos is not pinned"):
        verifier.verify_launch(
            _binding(children=(SimpleNamespace(seeded_mcp_servers=(unpinned,)),))
        )
