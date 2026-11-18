"""Builders, constants and fakes that other test files import.

Moved from tests/integration/claude/test_claude_live_qualification.py.
"""

from __future__ import annotations

import os
from typing import Any

from mission_control.application.agentic_components.materialization import projection_digest
from mission_control.application.agentic_components.placement import operating_contract
from mission_control.application.execution.auth_admission import AuthAdmission
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.execution.contracts import OperationExecutionRequest
from tests.unit.claude.fixtures import PROFILE, base_operation, claude_binding, claude_operation


def _rows() -> tuple[Any, ...]:
    from tests.fixtures.projections.rows import skill_row

    # One skill only: no hook script, no MCP server and no executable is projected.
    return (skill_row(),)


def _operation(admission: AuthAdmission, *, key: str) -> OperationExecutionRequest:
    base = base_operation()
    digest = projection_digest(
        HOST_PROJECTORS.render(_rows(), PROFILE, operating_contract(base), None)
    )
    binding = claude_binding(
        materialization_digest=digest,
        model={
            "profile": "frontier.default",
            "model_id": os.environ.get("MC_CLAUDE_DRILL_MODEL", "claude-sonnet-4-5"),
        },
        auth={"profile": admission.profile_id, "billing_mode": admission.billing_mode},
        provider_options={
            "provider": PROFILE,
            "permission_mode": "default",
            # Bash is not pre-allowed: its call must reach `can_use_tool`.
            "allowed_tools": ["Read", "Task"],
            "max_turns": 8,
        },
    )
    operation = claude_operation(binding=binding)
    payload = operation.model_dump(mode="python")
    identity = payload["identity"]
    payload["identity"] = {**dict(identity), "operation_id": f"claude-drill-{key}"}
    payload["idempotency_key"] = f"claude-drill:{key}"
    return OperationExecutionRequest.model_validate(payload)
