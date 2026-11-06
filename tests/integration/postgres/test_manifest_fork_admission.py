"""Real F1+manifest policy+restricted PostgreSQL fork admission, with no provider/Temporal.

The snapshot is a technical immutable input; this test proves admission provenance, not
source execution or cognition seeding (those are covered by canonical root fixtures).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from mission_control.application.authoring.manifest_fork_admission import (
    ManifestForkAdmissionProvenance,
)
from mission_control.application.recovery.run_forks import ForkCommand, compile_fork_admission
from mission_control.domain.policies.contracts import DecisionStatus
from mission_control.domain.policies.forks import RunSnapshotManifest, snapshot_id_for
from tests.fixtures.run_forks import technical_snapshot
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.integration.postgres.test_manifest_submit import (
    MINIMAL,
    OWNER,
    Stack,
)
from tests.integration.postgres.test_manifest_submit import (
    request as submit_request,
)
from tests.integration.postgres.test_manifest_submit import (
    stack as stack,
)

pytestmark = pytest.mark.common_db


@pytest.mark.parametrize("variant", ["minimal", "qualia_shared"])
async def test_submitted_configuration_forks_through_real_admission_contract(
    stack: Stack, tmp_path, variant
):
    manifest = MINIMAL.read_text(encoding="utf-8")
    source_manifest = manifest
    if variant == "minimal":
        lifecycle = await stack.build()
    else:
        from mission_control.adapters.postgres.control_plane.definition_repository import (
            PostgresDefinitionRepository,
        )
        from mission_control.adapters.postgres.control_plane.manifest_submission import (
            PostgresManifestSubmissionRepository,
        )
        from mission_control.adapters.postgres.run_control.run_control_repository import (
            PostgresRunControlRepository,
        )
        from mission_control.application.authoring.manifest_service import ManifestCompileService
        from mission_control.application.authoring.manifest_submit import (
            ManifestSubmitService,
            register_manifest_admission_policies,
        )
        from mission_control.application.authoring.service import ControlPlaneService
        from mission_control.application.execution.service import (
            AdmissionPolicyRegistry,
            F1RunConfigurationVerifier,
            RunControlService,
        )
        from tests.fixtures.mission_control_common_db import catalog_scope
        from tests.fixtures.qualia_fork_contract import QualiaForkPrograms
        from tests.unit.test_qualia_fork_contract import fixture

        definitions, payloads, extensions, _, _, texts = await fixture(tmp_path)
        catalog = PostgresDefinitionRepository(stack.pool, catalog_scope=catalog_scope("biotech"))
        programs = QualiaForkPrograms(catalog, extensions, payloads)
        compiler = ManifestCompileService(definitions=definitions, search=None, programs=programs)
        await programs.prepare(
            compiler,
            texts,
            request_scope=stack.scope,
            actor_id=OWNER.actor_id,
            at=datetime.now(UTC),
        )
        policies = AdmissionPolicyRegistry()
        register_manifest_admission_policies(policies)
        stack.run_control = RunControlService(
            PostgresRunControlRepository(stack.pool),
            F1RunConfigurationVerifier(ControlPlaneService(catalog, extensions, payloads)),
            policies,
        )
        stack.submissions = PostgresManifestSubmissionRepository(stack.pool)
        lifecycle = ManifestSubmitService(
            compiler=compiler,
            programs=programs,
            run_control=stack.run_control,
            submissions=stack.submissions,
            request_scope=stack.scope,
        )
        source_manifest, manifest = texts
    source_receipt, _ = await lifecycle.submit(submit_request(source_manifest))
    receipt = source_receipt
    if manifest != source_manifest:
        receipt, _ = await lifecycle.submit(submit_request(manifest))
    (mission,) = receipt.missions
    assert mission.run_id
    origin = await stack.run_control.get_run(stack.scope, mission.run_id)
    source_run = await stack.run_control.get_run(stack.scope, source_receipt.missions[0].run_id)
    assert source_run.workflow_type_ref == origin.workflow_type_ref
    template = technical_snapshot(source_run.run_id, request_scope=stack.scope)
    values = template.model_dump(mode="python", exclude={"snapshot_digest"})
    source_budget = await stack.run_control.get_budget(stack.scope, source_run.run_id)
    values.update(
        budget_frontier=template.budget_frontier.model_copy(
            update={"limits": source_budget.limits, "account_id": source_budget.account_id}
        ),
        request_scope=stack.scope,
        source_run_id=source_run.run_id,
        projection_version=origin.version,
        snapshot_id=snapshot_id_for(
            stack.scope, source_run.run_id, source_run.version, template.boundary_ref
        ),
        effective_configuration_digest=source_run.effective_configuration_digest,
        workflow_type_ref=source_run.workflow_type_ref,
        input_manifest=source_run.input_manifest,
        reuse_candidates=(),
    )
    snapshot = RunSnapshotManifest.create(**values)
    command = ForkCommand(
        request_scope=stack.scope,
        source_run_id=source_run.run_id,
        request_id=str(uuid4()),
        idempotency_key=str(uuid4()),
        snapshot_id=snapshot.snapshot_id,
        snapshot_digest=snapshot.snapshot_digest,
        sponsorship_ref="sponsorship:test",
        actor=OWNER,
        reason="actual manifest fork admission proof",
        requested_at=datetime.now(UTC),
    )
    target = compile_fork_admission(
        snapshot,
        command,
        patch_digest="sha256:" + "a" * 64,
        effective_configuration_digest=origin.effective_configuration_digest,
        input_manifest=origin.input_manifest,
    )
    # Exact reproduction of the prior actual 409: F1 passes; manifest policy refuses.
    rejected = await stack.run_control.admit(target)
    assert rejected.status == DecisionStatus.REJECTED
    assert "only through a Mission Manifest submit" in rejected.reason
    provenance = ManifestForkAdmissionProvenance(
        stack.submissions,
        stack.run_control,
        stack.run_control._configuration_verifier._control_plane,
    )
    evidence = await provenance.evidence(target)
    repeated, replayed = await lifecycle.submit(submit_request(manifest))
    assert repeated.unchanged and not replayed and repeated.missions[0].run_id == origin.run_id
    assert (
        len(
            await stack.submissions.submitted_configurations(
                stack.scope, origin.effective_configuration_digest
            )
        )
        == 1
    )
    assert await provenance.evidence(target) == evidence
    assert evidence[0] == f"manifest:{receipt.manifest_digest}"
    target = target.model_copy(
        update={
            "request_id": str(uuid4()),
            "admission_evidence_refs": (*target.admission_evidence_refs, *evidence),
        }
    )
    admitted = await stack.run_control.admit(target)
    assert admitted.status == DecisionStatus.ACCEPTED and admitted.run_id != origin.run_id
    derived = await stack.run_control.get_run(stack.scope, admitted.run_id)
    assert derived.workflow_type_ref == origin.workflow_type_ref
    assert derived.effective_configuration_digest == origin.effective_configuration_digest
    assert (await stack.run_control.get_run(stack.scope, origin.run_id)) == origin
    transitions = await stack.run_control.list_transitions(stack.scope, admitted.run_id)
    assert set(evidence) <= set(transitions[0].evidence_refs)
    assert not await stack.submissions.submitted_configurations(
        stack.db.scope("tenant-2"), origin.effective_configuration_digest
    )
