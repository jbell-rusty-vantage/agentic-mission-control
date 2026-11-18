"""Builders, constants and fakes that other test files import.

Moved from tests/unit/workspaces/test_sandbox_snapshots.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mission_control.application.artifacts.sandbox_snapshots import (
    InMemorySandboxSnapshotRepository,
    InMemorySnapshotPayloadStore,
    SandboxSnapshotService,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.contracts import (
    MaterializedWorkspace,
    ReacquiredRuntimeResources,
    SandboxSnapshotCapture,
    SandboxSnapshotCreateRequest,
    SnapshotCapabilityShape,
    SnapshotCloneRequest,
    SnapshotCreationReason,
    SnapshotRetention,
)
from mission_control.domain.execution.errors import SnapshotAuthorityError

NOW = datetime(2026, 7, 21, 18, 0, tzinfo=UTC)
RUNTIME = sha256_digest("runtime")
IMAGE = sha256_digest("image")
PACKAGE = sha256_digest("packages")
ENVIRONMENT = sha256_digest("environment-without-secret-values")
MOUNTS = sha256_digest("mount-manifest")
WORKSPACE_CONTRACT = sha256_digest("workspace-contract")
ARCHIVE = b"immutable sandbox tar payload"
CAPABILITIES = SnapshotCapabilityShape(
    capabilities=frozenset({"filesystem.read", "filesystem.write"}),
    tool_ids=frozenset({"sandbox.filesystem"}),
    data_scope_refs=frozenset({"source:one"}),
)


class Authority:
    def __init__(self) -> None:
        self.revoked = False
        self.creation_checks = 0
        self.restore_checks = 0

    async def verify_creation(self, request: SandboxSnapshotCreateRequest) -> None:
        self.creation_checks += 1
        if request.snapshot_policy_ref != "snapshot:on-failure@1":
            raise SnapshotAuthorityError("snapshot policy does not admit creation")

    async def verify_restore(self, request, snapshot) -> None:  # type: ignore[no-untyped-def]
        self.restore_checks += 1
        if self.revoked or request.binding_id == snapshot.producer_binding_id:
            raise SnapshotAuthorityError("current binding authority is unavailable")


class Sandbox:
    def __init__(self) -> None:
        self.captures = 0
        self.clones: list[str] = []

    async def capture(self, request: SandboxSnapshotCreateRequest) -> SandboxSnapshotCapture:
        self.captures += 1
        return SandboxSnapshotCapture(
            provider_snapshot_id=f"provider:{request.snapshot_id}",
            filesystem_digest=sha256_digest("filesystem-tree"),
            content_manifest_digest=sha256_digest("filesystem-manifest"),
            payload=ARCHIVE,
        )

    async def clone(self, *, snapshot, payload, request):  # type: ignore[no-untyped-def]
        assert payload == ARCHIVE
        self.clones.append(request.target_workspace_id)
        return MaterializedWorkspace(
            workspace_id=request.target_workspace_id,
            namespace_id=request.target_namespace_id,
            provider=snapshot.provider,
            runtime_digest=request.runtime_digest,
            image_digest=request.image_digest,
            mount_manifest_digest=request.target_mount_manifest_digest,
        )

    async def discard_clone(self, request) -> None:  # type: ignore[no-untyped-def]
        self.clones.remove(request.target_workspace_id)


class Resources:
    async def reacquire(self, request, snapshot):  # type: ignore[no-untyped-def]
        del request, snapshot
        return ReacquiredRuntimeResources(
            secret_names=("OPENAI_API_KEY",),
            credential_names=("aws-role",),
            lease_names=("sandbox-network",),
            mcp_connection_names=("search",),
            socket_names=("runtime-events",),
        )

    async def release(self, request, snapshot, resources) -> None:  # type: ignore[no-untyped-def]
        del request, snapshot, resources


def create_request() -> SandboxSnapshotCreateRequest:
    return SandboxSnapshotCreateRequest(
        snapshot_id="snapshot-1",
        idempotency_key="snapshot:create:one",
        request_scope="tenant:one",
        source_namespace_id="run-workspace:run-1",
        source_workspace_id="workspace-source",
        provider="langsmith-sandbox",
        reason=SnapshotCreationReason.FAILURE,
        producer_binding_id="binding-source",
        snapshot_policy_ref="snapshot:on-failure@1",
        runtime_digest=RUNTIME,
        image_digest=IMAGE,
        package_digest=PACKAGE,
        environment_digest=ENVIRONMENT,
        workspace_contract_digest=WORKSPACE_CONTRACT,
        mount_manifest_digest=MOUNTS,
        capability_shape=CAPABILITIES,
        retention=SnapshotRetention(
            policy_ref="retention:debug-30d@1",
            retain_until=NOW + timedelta(days=30),
        ),
        created_at=NOW,
    )


def clone_request(workspace_id: str, clone_id: str) -> SnapshotCloneRequest:
    return SnapshotCloneRequest(
        snapshot_id="snapshot-1",
        clone_id=clone_id,
        request_scope="tenant:one",
        target_namespace_id="run-workspace:run-2",
        target_workspace_id=workspace_id,
        binding_id=f"binding:{clone_id}",
        runtime_digest=RUNTIME,
        image_digest=IMAGE,
        package_digest=PACKAGE,
        environment_digest=ENVIRONMENT,
        workspace_contract_digest=WORKSPACE_CONTRACT,
        target_mount_manifest_digest=MOUNTS,
        capability_shape=CAPABILITIES,
        requested_at=NOW + timedelta(hours=1),
    )


def service():
    repository = InMemorySandboxSnapshotRepository()
    payloads = InMemorySnapshotPayloadStore()
    sandbox = Sandbox()
    authority = Authority()
    return (
        SandboxSnapshotService(
            snapshots=repository,
            payloads=payloads,
            sandbox=sandbox,
            authority=authority,
            resources=Resources(),
            clock=lambda: NOW + timedelta(hours=1),
        ),
        repository,
        payloads,
        sandbox,
        authority,
    )
