"""Builders, constants and fakes that other test files import.

Moved from tests/unit/workspaces/test_goal_role_slot_ownership.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef
from mission_control.domain.execution.contracts import (
    WorkspaceMaterializationRequest,
    WorkspaceOwner,
    WorkspaceOwnerKind,
    WorkspaceSlotBinding,
)
from mission_control.domain.programs.runtime_units import goal_unit_workspace_root
from tests.fixtures.checkpoint_lineage import goal_unit

NAMESPACE = "run/run-1"


def _goal_request(workspace_id: str, iteration: int, role: str) -> WorkspaceMaterializationRequest:
    """The request the GoalDirected preparer derives: the compiled `/work` slot rebased
    under the unit's role root, owned by the iteration's executor or verifier."""

    unit = goal_unit(
        request_scope="tenant-1",
        run_id="run-1",
        operation_id=f"goal-iteration/{iteration}/{role}",
        goal_iteration=iteration,
        role=role,  # type: ignore[arg-type]
    )
    root = goal_unit_workspace_root(unit)
    assert root == f"/goal/{iteration}/{role}"
    return _request(
        workspace_id,
        f"{root}/work",
        WorkspaceOwner(
            kind=(
                WorkspaceOwnerKind.ITERATION if role == "executor" else WorkspaceOwnerKind.EVALUATOR
            ),
            owner_id=f"goal-iteration/{iteration}/{role}",
        ),
    )


def _request(
    workspace_id: str, path: str, owner: WorkspaceOwner
) -> WorkspaceMaterializationRequest:
    return WorkspaceMaterializationRequest(
        namespace_id=NAMESPACE,
        workspace_id=workspace_id,
        provider="conformance-filesystem",
        template_ref=ExactDefinitionRef(
            kind=DefinitionKind.WORKSPACE_TEMPLATE,
            logical_id="goal-workspace",
            revision=1,
            digest=sha256_digest("goal-workspace@1"),
        ),
        workflow_contract_digest=sha256_digest("goal-workspace-contract"),
        slots=(
            WorkspaceSlotBinding(
                slot_name="work", logical_path=path, access="exclusive_write", owner=owner
            ),
        ),
        runtime_digest=sha256_digest("runtime"),
        image_digest=sha256_digest("image"),
        created_at=datetime(2026, 10, 2, tzinfo=UTC),
    )


def _rebound(
    request: WorkspaceMaterializationRequest, minutes: int = 5
) -> WorkspaceMaterializationRequest:
    """The same materialization under a later operation attempt's binding (`bound_at`)."""

    return request.model_copy(
        update={"created_at": request.created_at + timedelta(minutes=minutes)}
    )
