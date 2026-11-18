"""A duplicate bounded probe reuses its typed Temporal result and never creates a new run."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from mission_control.application.prerequisites.bootstrap_probe import (
    bootstrap_identity,
    bounded_probe_request,
)
from mission_control.bootstrap.owner_probe import InstalledBootstrapProbe
from mission_control.bootstrap.settings import Settings
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationWorkflowResult
from mission_control.domain.policies.contracts import CommandStatus, RunPhase
from tests.support.unit.prerequisites.owner_bootstrap import probe_template


class AcceptedStart:
    """Run-control rows recording that the probe's own start command was accepted."""

    async def get_command_result(
        self, request_scope: str, run_id: str, idempotency_issuer: str, command_id: str
    ) -> SimpleNamespace | None:
        if idempotency_issuer != "owner-bootstrap":
            return None
        return SimpleNamespace(status=CommandStatus.ACCEPTED)


def probe(runs, temporal, **seams) -> InstalledBootstrapProbe:
    return InstalledBootstrapProbe(
        None,
        Settings(_env_file=None, temporal_task_queue="mc"),
        None,
        runs,
        None,
        command_results=AcceptedStart(),
        temporal=temporal,
        **seams,
    )


async def test_duplicate_dispatch_reuses_result_with_explicit_type_and_current_run_revision():
    plan, template = probe_template()
    request = bounded_probe_request(plan, template)
    runs = AsyncMock()
    runs.get_run.return_value = SimpleNamespace(phase=RunPhase.ACTIVE, version=2)
    handle = SimpleNamespace(
        result=AsyncMock(return_value=SimpleNamespace(disposition="completed"))
    )
    temporal = SimpleNamespace(
        start_workflow=AsyncMock(side_effect=WorkflowAlreadyStartedError("existing", "operation")),
        get_workflow_handle=lambda identity, **kwargs: handle,
    )
    captured = []

    def existing(identity, **kwargs):
        captured.append((identity, kwargs))
        return handle

    temporal.get_workflow_handle = existing
    port = probe(runs, temporal)
    identity = await port.start(plan, request)
    assert identity == "owner-bootstrap-" + bootstrap_identity(plan)
    assert captured == [(identity, {"result_type": OperationWorkflowResult})]
    sent = temporal.start_workflow.call_args.args[1]
    assert sent.operation.run_control_revision == 2
    assert ProviderExecutionBinding.carried_by(
        sent.operation
    ) == ProviderExecutionBinding.carried_by(template)
    assert (
        temporal.start_workflow.call_args.kwargs["id_reuse_policy"]
        == WorkflowIDReusePolicy.REJECT_DUPLICATE
    )
    runs.execute.assert_not_awaited()


async def test_workflow_failure_is_sanitized_and_client_timeout_precedes_server():
    import pytest
    from temporalio.client import WorkflowFailureError

    plan, template = probe_template()
    runs = AsyncMock()
    runs.get_run.return_value = SimpleNamespace(phase=RunPhase.ACTIVE, version=2)
    handle = SimpleNamespace(
        result=AsyncMock(
            side_effect=WorkflowFailureError(
                cause=RuntimeError("private-provider-body"),
            )
        ),
        cancel=AsyncMock(),
    )
    temporal = SimpleNamespace(start_workflow=AsyncMock(return_value=handle))
    port = probe(runs, temporal)
    with pytest.raises(ValueError, match="workflow failed") as failure:
        await port.start(plan, bounded_probe_request(plan, template))
    assert "private-provider-body" not in str(failure.value)
    handle.cancel.assert_not_awaited()  # Already closed; no claim of provider cleanup.


async def test_client_timeout_requests_cancel_and_waits_for_bounded_cleanup():
    import pytest

    plan, template = probe_template()
    runs = AsyncMock()
    runs.get_run.return_value = SimpleNamespace(phase=RunPhase.ACTIVE, version=2)
    handle = SimpleNamespace(result=AsyncMock(), cancel=AsyncMock())
    temporal = SimpleNamespace(start_workflow=AsyncMock(return_value=handle))
    waits = []

    async def wait_for(awaitable, timeout):  # noqa: ASYNC109
        waits.append(timeout)
        awaitable.close()
        if len(waits) == 1:
            raise TimeoutError
        return SimpleNamespace(disposition="cancelled")

    # The client-side result bound is network timing: an injected wait that times out once.
    port = probe(runs, temporal, wait_for=wait_for)
    with pytest.raises(ValueError, match="cancellation requested"):
        await port.start(plan, bounded_probe_request(plan, template))
    assert waits == [plan.timeout_seconds + 5, 20]
    assert (
        waits[0] + waits[1]
        < temporal.start_workflow.call_args.kwargs["execution_timeout"].total_seconds()
    )
    handle.cancel.assert_awaited_once()
