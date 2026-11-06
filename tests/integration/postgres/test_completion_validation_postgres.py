"""Actual validator-to-family-journal proof across closed PostgreSQL pools.

Artifact custody is deterministic fixture bytes; lifecycle, budgets, family decisions,
receipts, digests and RLS use the real common component and restricted database roles.
"""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from mission_control.adapters.postgres.orchestration.completion_evidence import (
    PostgresCompletionEvidenceReader,
)
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.application.execution.service import FamilyAdmissionRegistry, RunControlService
from mission_control.application.programs.completion_validation import ArtifactPublicationPending
from mission_control.application.programs.service import (
    StageGraphDecisionService,
    register_stagegraph_family_mutations,
)
from mission_control.domain.authoring.canonical import sha256_digest
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db as common_db
from tests.unit.orchestration.test_artifact_schema_validation import Custody, captured
from tests.unit.orchestration.test_completion_validation_service import OUTPUT, prepared
from tests.unit.run_control.test_atomic_family_admission import admission_policies
from tests.unit.run_control.test_run_control import ConfigurationVerifier

pytestmark = pytest.mark.common_db


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", ["artifact://nonexistent", "workspace-candidate://other-tenant"])
async def test_unbound_artifact_never_becomes_accepted_even_after_replay(common_db, extra):
    pool = await common_db.pool()
    writer = await common_db.pool("mission_control_family_writer")
    try:
        fixture = await prepared(
            PostgresRunControlRepository(pool, family_writer_pool=writer), common_db.scope()
        )
        candidate = replace(
            fixture.result,
            observation=replace(
                fixture.result.observation,
                operation_result={
                    "output_refs": [OUTPUT, extra],
                    "output_bindings": {"report": [OUTPUT]},
                    "obligation_refs": ["goal"],
                },
            ),
        )
        decided = await fixture.service.decide_result(candidate)
        assert decided.proposal.decision.value == "reject"
        assert fixture.custody.calls == []
        before = await fixture.run_control.get_run(common_db.scope(), candidate.run_id)
        assert not before.accepted_output_evidence
        assert not before.accepted_obligation_evidence
        _, restarted = recompose(pool, writer, Custody(None))
        assert await restarted.decide_result(candidate) == decided
        assert await fixture.run_control.get_run(common_db.scope(), candidate.run_id) == before
    finally:
        await pool.close()
        await writer.close()


def recompose(pool, writer, custody):
    repository = PostgresRunControlRepository(pool, family_writer_pool=writer)
    registry = FamilyAdmissionRegistry()
    register_stagegraph_family_mutations(registry)
    control = RunControlService(
        repository, ConfigurationVerifier(frozenset({"goal"})), admission_policies(), registry
    )
    return control, StageGraphDecisionService(control, repository, artifacts=custody)


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [True, False])
async def test_validation_pending_restart_commit_and_lost_response_replay(
    common_db: CommonDatabase, valid: bool
):
    scope = common_db.scope()
    pool = await common_db.pool()
    writer = await common_db.pool("mission_control_family_writer")
    try:
        fixture = await prepared(
            PostgresRunControlRepository(pool, family_writer_pool=writer), scope
        )
        request = fixture.result
        before = await fixture.run_control.get_run(scope, request.run_id)
        fixture.custody.content = None
        with pytest.raises(ArtifactPublicationPending):
            await fixture.service.decide_result(request)
        assert await fixture.run_control.get_run(scope, request.run_id) == before
        assert (
            await PostgresCompletionEvidenceReader(pool).list(scope, request.run_id)
        ).decisions == ()
    finally:
        await pool.close()
        await writer.close()

    pool = await common_db.pool()
    writer = await common_db.pool("mission_control_family_writer")
    try:
        custody = Custody(
            captured('{"count":1}' if valid else '{"count":"wrong"}', source_ref=OUTPUT)
        )
        control, service = recompose(pool, writer, custody)
        # An interrupted capture cannot commit acceptance or a partially written check.
        original_capture = custody.capture
        custody.capture = AsyncMock(side_effect=RuntimeError("interrupted validator"))
        with pytest.raises(RuntimeError, match="interrupted validator"):
            await service.decide_result(request)
        assert await control.get_run(scope, request.run_id) == before
        custody.capture = original_capture
        decided = await service.decide_result(request)
        assert decided.accepted
        assert decided.proposal.decision.value == ("admit" if valid else "reject")
        page = await PostgresCompletionEvidenceReader(pool).list(scope, request.run_id)
        assert len(page.decisions) == 1
        validation = page.decisions[0].validation
        assert validation.status == ("satisfied" if valid else "unsatisfied")
        assert validation.checks[0].artifact_digest == custody.content.content_digest
        assert validation.criteria[0].status == validation.status
        settled = await control.get_run(scope, request.run_id)
        assert bool(settled.accepted_output_evidence) == valid
        if valid:
            assert settled.accepted_obligation_evidence[0].evidence_digest == sha256_digest(
                validation
            )
    finally:
        await pool.close()
        await writer.close()

    pool = await common_db.pool()
    writer = await common_db.pool("mission_control_family_writer")
    try:
        missing = Custody(None)
        control, service = recompose(pool, writer, missing)
        assert await service.decide_result(request) == decided
        assert missing.calls == []
        assert await control.get_run(scope, request.run_id) == settled
        assert await PostgresCompletionEvidenceReader(pool).list(scope, request.run_id) == page
        changed = replace(
            request, observation=replace(request.observation, operation_result={"output_refs": []})
        )
        with pytest.raises(ValueError, match="reused with different request content"):
            await service.decide_result(changed)
        assert missing.calls == []
        assert (
            await PostgresCompletionEvidenceReader(pool).list(
                common_db.scope("tenant-2"), request.run_id
            )
        ).decisions == ()
    finally:
        await pool.close()
        await writer.close()
