"""Builders, constants and fakes that other test files import.

Moved from tests/unit/authoring/test_manifest_interfaces.py.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from mission_control.adapters.storage.control_plane_payloads import InMemoryPayloadStore
from mission_control.application.authoring.manifest_service import (
    ManifestCompileService,
    ManifestProgramCompiler,
    MissionManifestService,
    require_any,
)
from mission_control.application.authoring.manifest_submit import (
    START_GRANTS,
    SUBMIT_GRANTS,
    ManifestBlocked,
    ManifestIdempotencyConflict,
    ManifestStartReceipt,
    ManifestSubmissionReceipt,
    SubmitRequest,
    SubmittedMission,
)
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.authoring.manifest import ManifestErrorCode, ManifestIssue
from mission_control.domain.policies.contracts import ActorContext
from mission_control.interfaces.mcp.coordinator_server import CoordinatorPrincipal
from tests.support.ids import SCOPE
from tests.support.manifests.seeded_catalog import fast_track_catalog

MISSION_ID = UUID("01920000-0000-7000-8000-00000000a001")
REVISION_ID = UUID("01920000-0000-7000-8000-00000000a002")


def receipt(request_id: str, *, unchanged: bool = False) -> ManifestSubmissionReceipt:
    return ManifestSubmissionReceipt(
        request_id=request_id,
        manifest_digest="sha256:" + "a" * 64,
        unchanged=unchanged,
        missions=(
            SubmittedMission(
                mission_key="minimal-sweep",
                mission_id=MISSION_ID,
                revision_id=REVISION_ID,
                revision_no=1,
                family="StageGraph",
                effective_configuration_digest="sha256:" + "b" * 64,
                run_id="run-1",
            ),
        ),
    )


class FakeLifecycle:
    """Grants are enforced exactly as ``ManifestSubmitService`` enforces them."""

    request_scope = SCOPE

    def __init__(self) -> None:
        self.submitted: dict[str, str] = {}
        self.started: list[tuple[str, dict[str, Any] | None]] = []

    async def submit(self, request: SubmitRequest) -> tuple[ManifestSubmissionReceipt, bool]:
        require_any(request.actor.permissions, SUBMIT_GRANTS, "manifest submit")
        if "BLOCK" in request.manifest_yaml:
            raise ManifestBlocked(
                None,
                (
                    ManifestIssue(
                        code=ManifestErrorCode.INVALID_DEFINITION,
                        pointer="/mission",
                        message="blocked",
                    ),
                ),
            )
        key = str(request.request_id)
        prior = self.submitted.get(key)
        if prior is not None:
            if prior != request.manifest_yaml:
                raise ManifestIdempotencyConflict("conflict")
            return receipt(key), True
        self.submitted[key] = request.manifest_yaml
        return receipt(key, unchanged="UNCHANGED" in request.manifest_yaml), False

    async def start(
        self, run_id: str, actor: ActorContext, *, family_input: dict[str, Any] | None = None
    ) -> ManifestStartReceipt:
        require_any(actor.permissions, START_GRANTS, "run start")
        self.started.append((run_id, family_input))
        return ManifestStartReceipt(
            run_id=run_id,
            mission_id=MISSION_ID,
            family="StageGraph",
            workflow_id=f"wf:{run_id}",
            semantic_input_binding_ref="semantic-input:x",
            accepted_run_version=1,
        )

    async def head_run(self, mission_id: Any) -> str | None:
        return "run-1" if mission_id == MISSION_ID else None


async def manifests(lifecycle: FakeLifecycle) -> MissionManifestService:
    definitions, search = await fast_track_catalog()
    return MissionManifestService(
        compiler=ManifestCompileService(
            definitions=definitions,
            search=search,
            programs=ManifestProgramCompiler(
                definitions, ExtensionRegistry(), InMemoryPayloadStore()
            ),
        ),
        request_scope=SCOPE,
        lifecycle=lifecycle,  # type: ignore[arg-type]
    )


def principal(permissions: frozenset[str]) -> CoordinatorPrincipal:
    return CoordinatorPrincipal(
        actor_id="coordinator",
        tenant_scope=SCOPE,
        roles=frozenset(),
        permissions=permissions,
        request_scope=SCOPE,
    )
