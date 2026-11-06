"""Placeholder provider templates are found through the exact admitted reference."""

import json
from dataclasses import asdict
from datetime import UTC, datetime

import pytest

from mission_control.adapters.postgres.control_plane.manifest_submission import (
    PostgresManifestSubmissionRepository,
)
from mission_control.adapters.postgres.documents import PostgresDocumentStore
from mission_control.application.execution.run_launch import RunLaunchRequest
from mission_control.application.prerequisites.preflight import (
    PrerequisitePreflight,
    PrerequisitesUnmet,
    StoredPrerequisiteLaunchGuard,
)
from mission_control.application.prerequisites.service import InMemoryOwnerPrerequisiteRepository
from mission_control.domain.execution.contracts import OperationAttemptIdentity
from mission_control.domain.programs.contracts import StageGraphRunInput
from tests.fixtures.managed_lane import managed_binding, managed_operation
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.unit.run_control.test_run_launch import _input

pytestmark = pytest.mark.common_db


@pytest.mark.parametrize("contract", ["stagegraph.template/1", "goal.template/1"])
async def test_placeholder_provider_template_never_evades_generic_guard(
    common_db: CommonDatabase,  # noqa: F811
    contract,
):
    pool = await common_db.pool("mission_control_runtime")
    try:
        admitted = await admit_unit_attempt(pool, common_db, start=False)
        scope = common_db.scope()
        projection = await admitted.run_control.get_run(scope, admitted.run_key)
        reference = "semantic-input:actual-admitted-reference"
        operation = managed_operation(managed_binding("sha256:" + "1" * 64)).model_copy(
            update={
                "request_scope": scope,
                "identity": OperationAttemptIdentity(
                    run_id="template-placeholder", operation_id="provider", operation_attempt=1
                ),
            }
        )
        await PostgresDocumentStore(pool).put(
            request_scope=scope,
            contract=contract,
            identity=json.dumps([reference, "executor"]),
            payload=operation.model_dump(mode="json"),
            recorded_at=datetime.now(UTC),
        )
        repository = PostgresManifestSubmissionRepository(pool)
        assert await repository.runtime_templates(scope, "other-reference") == ()
        guard = StoredPrerequisiteLaunchGuard(
            repository.run_subscriptions,
            PrerequisitePreflight(InMemoryOwnerPrerequisiteRepository()),
            runtime_templates=repository.runtime_templates,
        )
        values = _input(admitted.run_key)
        values.update(
            request_scope=scope,
            effective_configuration_digest=projection.effective_configuration_digest,
            semantic_input_binding_ref=reference,
        )
        workflow = StageGraphRunInput(**values)
        launch = RunLaunchRequest(
            request_scope=scope,
            run_id=admitted.run_key,
            family="StageGraph",
            stagegraph=asdict(workflow),
        )
        with pytest.raises(PrerequisitesUnmet, match="owner prerequisites"):
            await guard.require_launch(launch, workflow)
    finally:
        await pool.close()
