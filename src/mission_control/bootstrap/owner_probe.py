"""Operator CLI: run one reviewed bounded bootstrap probe on real installed workers.

python -m mission_control.bootstrap.owner_probe --plan PATH --application-binding PATH
checks the plan without contacting a provider. Add --execute --paid-budget-usd 1
only after reviewing the pinned, already admitted isolated mission and its budget.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import asyncpg
from temporalio.client import Client, WorkflowFailureError
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from mission_control.adapters.postgres.connections import create_application_postgres_pool
from mission_control.adapters.postgres.control_plane.definition_repository import (
    PostgresDefinitionRepository,
)
from mission_control.adapters.postgres.prerequisites import PostgresOwnerPrerequisiteRepository
from mission_control.adapters.postgres.run_control.run_control_repository import (
    PostgresRunControlRepository,
)
from mission_control.adapters.storage.control_plane_payloads import (
    S3PayloadStore,
    UnavailablePayloadStore,
)
from mission_control.adapters.temporal.coordinator_runtime import coordinator_task_queues
from mission_control.adapters.temporal.workflows.operation import OperationWorkflow
from mission_control.application.authoring.manifest_launch_inputs import (
    ManifestLaunchInputAuthor,
    binding_ref,
)
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.execution.service import (
    AdmissionPolicyRegistry,
    F1RunConfigurationVerifier,
    RunControlService,
)
from mission_control.application.installations.registry import ApplicationBinding
from mission_control.application.prerequisites.bootstrap_probe import (
    BootstrapProbePlan,
    BootstrapProbeService,
    bootstrap_identity,
    bounded_probe_request,
)
from mission_control.application.prerequisites.probes import (
    OwnerProbeBinding,
    OwnerProbeConfiguration,
)
from mission_control.application.prerequisites.service import OwnerPrerequisiteService
from mission_control.bootstrap.common_installation import inspect_common_installation
from mission_control.bootstrap.manifests import compose_manifest_launch_inputs
from mission_control.bootstrap.prerequisites import InstallationOwnerProbes
from mission_control.bootstrap.settings import Settings
from mission_control.contracts.identities import parse_request_scope
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.extensions import ExtensionRegistry
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    OperationWorkflowRequest,
    OperationWorkflowResult,
)
from mission_control.domain.policies.contracts import (
    ActorContext,
    CommandStatus,
    LifecycleCommand,
    RunPhase,
    StartAction,
)


class InstalledBootstrapProbe:
    def __init__(
        self,
        pool: asyncpg.Pool,
        settings: Settings,
        application: ApplicationBinding,
        run_control: RunControlService,
        author: ManifestLaunchInputAuthor,
    ):
        self._pool, self._settings, self._application = pool, settings, application
        self._runs, self._author = run_control, author

    async def describe(
        self, scope: str, run_id: str, key: str, prerequisite_id: str, purpose: str
    ) -> dict[str, object]:
        parsed = parse_request_scope(scope)
        if (
            parsed.installation_id != self._application.installation_id
            or parsed.application_id != self._application.application_id
        ):
            raise ValueError("probe is outside the trusted application installation")
        await inspect_common_installation(self._pool, self._application)
        templates = await self._author.bind(scope, run_id, family="StageGraph")
        if len(templates) != 1 or key not in templates:
            raise ValueError(
                "bootstrap requires an isolated one-operation admitted StageGraph mission"
            )
        template = templates[key]
        record = await PostgresOwnerPrerequisiteRepository(self._pool).get(scope, prerequisite_id)
        provider = ProviderExecutionBinding.carried_by(template)
        if record is None or provider is None:
            raise ValueError("run preflight first to register the current prerequisite")
        plan = BootstrapProbePlan.model_validate(
            {
                "request_scope": scope,
                "run_id": run_id,
                "semantic_input_binding_ref": binding_ref(run_id),
                "operation_request_key": key,
                "template_digest": sha256_digest(template),
                "configuration_digest": template.effective_configuration_digest,
                "provider_binding_digest": provider.binding_digest,
                "purpose": purpose,
                "prerequisite_id": prerequisite_id,
                "prerequisite_digest": record.definition_digest,
                "max_cost_micros": template.budget_limits.get("currency.estimated_micros", 0),
                "timeout_seconds": template.budget_limits.get("time.elapsed_ms", 0) // 1000,
            }
        )
        bounded_probe_request(plan, template)
        binding = OwnerProbeBinding.model_validate(
            {
                "request_scope": scope,
                "prerequisite_id": prerequisite_id,
                "definition_digest": record.definition_digest,
                "operation": purpose,
                "run_key": run_id,
                "binding_digest": plan.configuration_digest,
                "provider_binding_digest": plan.provider_binding_digest,
            }
        )
        return {
            "plan": plan.model_dump(mode="json"),
            "verification_binding": binding.model_dump(mode="json", exclude_none=True),
            "standing": "review_required_no_provider_call",
        }

    async def load(self, plan: BootstrapProbePlan) -> OperationExecutionRequest:
        scope = parse_request_scope(plan.request_scope)
        if (
            scope.installation_id != self._application.installation_id
            or scope.application_id != self._application.application_id
        ):
            raise ValueError("probe plan is outside the trusted application installation")
        await inspect_common_installation(self._pool, self._application)
        projection = await self._runs.get_run(plan.request_scope, plan.run_id)
        if projection.effective_configuration_digest != plan.configuration_digest:
            raise ValueError("the admitted run has another configuration")
        if plan.semantic_input_binding_ref != binding_ref(plan.run_id):
            raise ValueError("probe must use the admitted run's canonical template binding")
        if self._settings.mission_control_owner_probes_path is None:
            raise ValueError("trusted owner probe bindings must be configured first")
        configuration = OwnerProbeConfiguration.load(
            self._settings.mission_control_owner_probes_path
        )
        matches = [
            item
            for item in configuration.bindings
            if item.request_scope == plan.request_scope
            and item.prerequisite_id == plan.prerequisite_id
        ]
        if (
            len(matches) != 1
            or matches[0].definition_digest != plan.prerequisite_digest
            or matches[0].run_key != plan.run_id
            or matches[0].binding_digest != plan.configuration_digest
            or matches[0].operation != plan.purpose
        ):
            raise ValueError(
                "trusted verification binding does not match the reviewed bootstrap plan"
            )
        record = await PostgresOwnerPrerequisiteRepository(self._pool).get(
            plan.request_scope, plan.prerequisite_id
        )
        allowed = {
            "signed_webhook": {
                "prerequisite:ma2",
                "prerequisite:oa2",
                "missions/probes/claude-managed-webhook@1",
                "missions/probes/codex-agents-webhook@1",
            },
            "signal_receipt": {"prerequisite:m1"},
        }
        if (
            record is None
            or record.definition_digest != plan.prerequisite_digest
            or record.prerequisite.verify.probe not in allowed[plan.purpose]
        ):
            raise ValueError("bootstrap purpose does not prove the current prerequisite")
        templates = await self._author.bind(plan.request_scope, plan.run_id, family="StageGraph")
        if len(templates) != 1 or plan.operation_request_key not in templates:
            raise ValueError(
                "bootstrap requires an isolated one-operation admitted StageGraph mission"
            )
        return templates[plan.operation_request_key]

    async def start(self, plan: BootstrapProbePlan, request: OperationWorkflowRequest) -> str:
        command_id = "owner-bootstrap:" + bootstrap_identity(plan)
        projection = await self._runs.get_run(plan.request_scope, plan.run_id)
        command = LifecycleCommand(
            command_id=command_id,
            idempotency_issuer="owner-bootstrap",
            request_scope=plan.request_scope,
            run_id=plan.run_id,
            expected_run_version=projection.version,
            actor=ActorContext(
                actor_id="operator:owner-bootstrap", permissions=frozenset({"workflow_run.start"})
            ),
            action=StartAction(),
            reason="explicit bounded owner prerequisite bootstrap probe",
            evidence_refs=(sha256_digest(plan),),
            occurred_at=datetime.now(UTC),
            correlation_id=command_id,
        )
        if projection.phase is RunPhase.PENDING:
            started = await self._runs.execute(command)
            if started.status is not CommandStatus.ACCEPTED:
                raise ValueError("the governed lifecycle refused the isolated probe start")
        else:
            prior = await PostgresRunControlRepository(self._pool).get_command_result(
                plan.request_scope, plan.run_id, "owner-bootstrap", command_id
            )
            if prior is None or prior.status is not CommandStatus.ACCEPTED:
                raise ValueError("bootstrap cannot take over a run started by another route")
        current = await self._runs.get_run(plan.request_scope, plan.run_id)
        request = request.model_copy(
            update={
                "operation": request.operation.model_copy(
                    update={
                        "run_control_revision": current.version,
                        "requested_at": datetime.now(UTC),
                    }
                )
            }
        )
        client = await Client.connect(
            self._settings.temporal_address, namespace=self._settings.temporal_namespace
        )
        workflow_id = "owner-bootstrap-" + bootstrap_identity(plan)
        try:
            handle = await client.start_workflow(
                OperationWorkflow.run,
                request,
                id=workflow_id,
                # OC-R4: a local technical surface with no installation `temporal` section;
                # TEMPORAL_TASK_QUEUE or the selected profile names the queue (typed if unset).
                task_queue=coordinator_task_queues(self._settings.task_queue_base).stagegraph,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                execution_timeout=timedelta(seconds=plan.timeout_seconds + 30),
            )
        except WorkflowAlreadyStartedError:
            handle = client.get_workflow_handle(workflow_id, result_type=OperationWorkflowResult)
        try:
            completed = await asyncio.wait_for(handle.result(), timeout=plan.timeout_seconds + 5)
        except TimeoutError:
            await handle.cancel()
            # Give the workflow cancellation path time to settle/end the provider before
            # the server hard execution bound; never claim cleanup from a cancel request.
            with suppress(Exception):
                await asyncio.wait_for(handle.result(), timeout=20)
            raise ValueError(
                "bounded probe timed out; cancellation requested; inspect cleanup before retry"
            ) from None
        except WorkflowFailureError:
            raise ValueError(
                "bounded probe workflow failed; inspect operation settlement and cleanup"
            ) from None
        if completed.disposition != "completed":
            raise ValueError("bounded probe did not complete; no verification evidence recorded")
        return workflow_id

    async def prove(self, plan: BootstrapProbePlan, request: OperationWorkflowRequest) -> str:
        repository = PostgresOwnerPrerequisiteRepository(self._pool)
        record = await repository.get(plan.request_scope, plan.prerequisite_id)
        if record is None or record.definition_digest != plan.prerequisite_digest:
            raise ValueError("prerequisite changed during the probe; refresh setup")
        proof = await InstallationOwnerProbes(self._settings, self._pool).verify(
            plan.request_scope, record
        )
        await OwnerPrerequisiteService(repository).verify(
            plan.request_scope,
            plan.prerequisite_id,
            method=proof.method,
            evidence_ref=proof.evidence_ref,
            expires_at=proof.expires_at,
            definition_digest=plan.prerequisite_digest,
        )
        return proof.evidence_ref


async def run(args: argparse.Namespace) -> dict[str, object]:
    settings = Settings()
    application_text = await asyncio.to_thread(
        Path(args.application_binding).read_text, encoding="utf-8"
    )
    application = ApplicationBinding.model_validate_json(application_text)
    pool = await create_application_postgres_pool(settings)
    try:
        catalog = ControlPlaneService(
            PostgresDefinitionRepository(
                pool,
                catalog_scope=f"mc/{application.installation_id}/{application.application_id}/catalog",
            ),
            ExtensionRegistry(),
            S3PayloadStore(settings, settings.s3_bucket)
            if settings.s3_bucket
            else UnavailablePayloadStore(),
        )
        runs = RunControlService(
            PostgresRunControlRepository(pool),
            F1RunConfigurationVerifier(catalog),
            AdmissionPolicyRegistry(),
        )
        author = compose_manifest_launch_inputs(
            pool,
            settings=settings,
            application_id=application.application_id,
            run_control=runs,
            control_plane=catalog,
        )
        if author is None:
            raise ValueError("production manifest launch bindings must be configured")
        port = InstalledBootstrapProbe(pool, settings, application, runs, author)
        if args.describe:
            if not all(
                (
                    args.request_scope,
                    args.run_id,
                    args.operation_key,
                    args.prerequisite_id,
                    args.purpose,
                )
            ):
                raise ValueError(
                    "describe needs scope, admitted run, operation key, prerequisite and purpose"
                )
            return await port.describe(
                args.request_scope,
                args.run_id,
                args.operation_key,
                args.prerequisite_id,
                args.purpose,
            )
        if not args.plan:
            raise ValueError("a reviewed --plan is required")
        plan_text = await asyncio.to_thread(Path(args.plan).read_text, encoding="utf-8")
        plan = BootstrapProbePlan.model_validate_json(plan_text)
        if not args.execute:
            bounded_probe_request(plan, await port.load(plan))
            return {
                "standing": "reviewed_no_provider_call",
                "template_digest": plan.template_digest,
            }
        paid = Decimal(args.paid_budget_usd or "0")
        if not paid.is_finite() or paid <= 0 or paid > 1:
            raise ValueError("explicit finite --paid-budget-usd between zero and one is required")
        result = await BootstrapProbeService(port).run(
            plan, paid_budget_micros=int(paid * 1_000_000)
        )
        return dict(result)
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan")
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--request-scope")
    parser.add_argument("--run-id")
    parser.add_argument("--operation-key")
    parser.add_argument("--prerequisite-id")
    parser.add_argument("--purpose", choices=("signed_webhook", "signal_receipt"))
    parser.add_argument("--application-binding", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--paid-budget-usd")
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
    except Exception as error:
        # Provider/DB exceptions can contain private response bodies or connection strings.
        parser.exit(
            2,
            f"owner bootstrap refused ({type(error).__name__}); "
            "inspect trusted local diagnostics\n",
        )
    sys.stdout.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
