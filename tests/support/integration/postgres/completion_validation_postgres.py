"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_completion_validation_postgres.py.
"""

from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.application.execution.service import FamilyAdmissionRegistry, RunControlService
from mission_control.application.programs.service import (
    StageGraphDecisionService,
    register_stagegraph_family_mutations,
)
from tests.support.run_control import ConfigurationVerifier
from tests.support.unit.run_control.atomic_family_admission import admission_policies


def recompose(pool, writer, custody):
    repository = PostgresRunControlRepository(pool, family_writer_pool=writer)
    registry = FamilyAdmissionRegistry()
    register_stagegraph_family_mutations(registry)
    control = RunControlService(
        repository, ConfigurationVerifier(frozenset({"goal"})), admission_policies(), registry
    )
    return control, StageGraphDecisionService(control, repository, artifacts=custody)
