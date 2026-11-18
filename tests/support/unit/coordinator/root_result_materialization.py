"""Builders, constants and fakes that other test files import.

Moved from tests/unit/coordinator/test_root_result_materialization.py.
"""

from mission_control.domain.programs.contracts import BellLabsRunInput

SCOPE = "mc/00000000-0000-0000-0000-000000000001/biotech/00000000-0000-0000-0000-000000000002"
DIGEST = "sha256:" + "a" * 64


def root(family="StageGraph"):
    return BellLabsRunInput(
        schema_version="mc.mission_run.v1",
        run_id="run-1",
        request_scope=SCOPE,
        effective_configuration_digest=DIGEST,
        workflow_type_digest=DIGEST,
        family=family,
        family_task_queue="family-queue",
        family_input={
            "run_id": "run-1",
            "request_scope": SCOPE,
            "effective_configuration_digest": DIGEST,
            "workflow_type_digest": DIGEST,
        },
    )
