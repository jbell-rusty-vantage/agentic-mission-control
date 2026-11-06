"""Signed API, production workflows and real scoped custody with deterministic JSON.

PostgreSQL receipts/RLS, filesystem payload custody, run authority, Deep Agents checkpointer,
Temporal activities, cancellation and terminal results are real. Only cognition is a fixture.
No paid providers or production storage are used.
"""

import asyncio
from hashlib import sha256

import pytest
from temporalio import activity
from temporalio.worker import Replayer
from tests.acceptance.mission_control.test_authenticated_scoped_runtime import (
    admit_and_launch,
    assert_persisted_run_evidence,
    command,
    condition,
    inspect,
    scoped_stack,
    until,
)
from tests.fixtures import rrm009_production_stack as technical
from tests.fixtures.rrm009_production_harness import canonical_evidence
from tests.unit.orchestration.test_goal_schema_completion import OUTPUT, SUMMARY, multi_goal_request

from mission_control.adapters.operations.runtime_ports import FilesystemArtifactPayloadStore
from mission_control.adapters.postgres.context.artifact_bytes import PostgresArtifactBytes
from mission_control.adapters.postgres.workspace_candidate_contents import (
    PostgresWorkspaceCandidateContents,
)
from mission_control.adapters.temporal.boundary_commands import TemporalBoundaryCommandTransport
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.goal_directed import GoalDirectedWorkflow
from mission_control.adapters.temporal.workflows.mission_run import MissionRunWorkflow
from mission_control.adapters.temporal.workflows.operation import MissionOperationWorkflow
from mission_control.adapters.temporal.workflows.stagegraph import StageGraphWorkflow
from mission_control.application.programs.goal_directed import (
    GoalDirectedOperationPreparationService,
)
from mission_control.contracts.identities import parse_request_scope
from mission_control.domain.execution.contracts import CapturedWorkspaceCandidate, WorkspaceOwner

pytestmark = pytest.mark.common_db


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_pending", [False, True, "preparation", "delayed_delivery"])
async def test_signed_goal_named_outputs_delayed_publication_and_cancellation(
    tmp_path, monkeypatch, cancel_pending
):
    original_blueprint = technical.goal_blueprint
    schema_blueprint = multi_goal_request().completion_blueprint

    def blueprint(**kwargs):
        return original_blueprint(**kwargs).model_copy(
            update={
                "output_slots": schema_blueprint.output_slots,
                "schema_criteria": tuple(
                    item.model_copy(update={"obligation_ref": technical.GOAL_OBLIGATION})
                    for item in schema_blueprint.schema_criteria
                ),
            }
        )

    original_answer = technical.TechnicalModel._answer

    def answer(model, messages):
        body = original_answer(model, messages)
        if model.operation_id.endswith("/executor"):
            body.update(
                output_refs=[OUTPUT, SUMMARY],
                output_bindings={
                    "report": [OUTPUT],
                    "summary": [SUMMARY],
                },
            )
        return body

    monkeypatch.setattr(technical, "goal_blueprint", blueprint)
    monkeypatch.setattr(technical.TechnicalModel, "_answer", answer)
    waiting = asyncio.Event()
    release_preparation = asyncio.Event()
    cancel_preparation = cancel_pending in {"preparation", "delayed_delivery"}
    delayed_delivery = cancel_pending == "delayed_delivery"
    release_cancel = asyncio.Event()
    if delayed_delivery:
        original_delivery = TemporalBoundaryCommandTransport._deliver_cancel

        async def delay_cancel(transport, status):
            await release_cancel.wait()
            return await original_delivery(transport, status)

        monkeypatch.setattr(TemporalBoundaryCommandTransport, "_deliver_cancel", delay_cancel)
        original_prepare = GoalDirectedOperationPreparationService.prepare

        async def admitted_verifier(preparer, request):
            dispatch = await original_prepare(preparer, request)
            if request.operation_role == "verifier":
                waiting.set()
                await release_preparation.wait()
            return dispatch

        monkeypatch.setattr(GoalDirectedOperationPreparationService, "prepare", admitted_verifier)
    calls = []
    original_capture = PostgresArtifactBytes.capture
    async with scoped_stack(tmp_path, monkeypatch) as stack:

        async def capture(adapter, source_ref, *, request_scope, max_text_bytes):
            if source_ref not in {OUTPUT, SUMMARY}:
                return await original_capture(
                    adapter,
                    source_ref,
                    request_scope=request_scope,
                    max_text_bytes=max_text_bytes,
                )
            calls.append((request_scope, source_ref))
            assert request_scope == stack.scope
            content = await original_capture(
                adapter,
                source_ref,
                request_scope=request_scope,
                max_text_bytes=max_text_bytes,
            )
            if (
                source_ref == SUMMARY
                and content is None
                and not delayed_delivery
                and activity.in_activity()
                and activity.info().activity_type
                == (
                    "goaldirected.prepare_verifier"
                    if cancel_preparation
                    else "goaldirected.reconcile_operation"
                )
            ):
                waiting.set()
                if cancel_preparation:
                    await release_preparation.wait()
            return content

        monkeypatch.setattr(PostgresArtifactBytes, "capture", capture)
        run_id, root_id = await admit_and_launch(stack, "GoalDirected")

        async def publish(slot, source_ref, raw):
            body = raw.encode()
            candidate = CapturedWorkspaceCandidate(
                namespace_id=f"run/{run_id}",
                workspace_id=f"workspace:{run_id}:fixture",
                output_slot=slot,
                logical_path=f"/work/{slot}.json",
                owner=WorkspaceOwner(kind="run", owner_id=run_id),
                candidate_id=source_ref.removeprefix("workspace-candidate://"),
                content_digest="sha256:" + sha256(body).hexdigest(),
                media_type="application/json",
                size_bytes=len(body),
            )
            await PostgresWorkspaceCandidateContents(
                stack.pool,
                FilesystemArtifactPayloadStore(tmp_path / "payloads"),
                request_scope=stack.scope,
            ).put(candidate, body)

        await publish("report", OUTPUT, '{"count":1}')
        async with asyncio.timeout(180):
            await waiting.wait()
        base = f"/v1/applications/biotech/runs/{run_id}"
        pending = await stack.http.get(base + "/goal-completion-evidence")
        assert pending.status_code == 200, pending.text
        assert pending.json()["decisions"] == []
        state = await inspect(stack, run_id)
        assert not state["projection"]["accepted_output_evidence"]
        assert not state["projection"]["accepted_obligation_evidence"]
        if cancel_pending:
            if cancel_preparation:
                pending_command = asyncio.create_task(command(stack, run_id, "cancel", {}))

                async def delivered():
                    response = await stack.http.get(base + "/commands")
                    return any(
                        receipt["state"] == "delivered"
                        for item in response.json()["commands"]
                        for receipt in item["receipts"]
                    )

                try:
                    if delayed_delivery:
                        await until(
                            lambda: condition(stack, run_id, "phase", "cancelling"), seconds=60
                        )
                    else:
                        await until(delivered, seconds=60)
                finally:
                    release_preparation.set()
                try:
                    if delayed_delivery:
                        verifier_handle = None

                        async def activity_failed_before_cancel_delivery():
                            nonlocal verifier_handle
                            async for execution in stack.client.list_workflows(
                                f"BellLabsRunId = '{run_id}'"
                            ):
                                if (
                                    execution.workflow_type == "mc.operation.v1"
                                    and "verifier" in execution.id
                                ):
                                    verifier_handle = stack.client.get_workflow_handle(execution.id)
                                    history = await verifier_handle.fetch_history()
                                    failed = False
                                    for event in history.events:
                                        if event.HasField("activity_task_failed_event_attributes"):
                                            failure = event.activity_task_failed_event_attributes
                                            assert (
                                                failure.failure.application_failure_info.type
                                                == ("operation_cancellation_pending")
                                            )
                                            failed = True
                                        if failed and event.HasField(
                                            "workflow_task_completed_event_attributes"
                                        ):
                                            return True
                            return False

                        await until(activity_failed_before_cancel_delivery, seconds=60)
                        description = await verifier_handle.describe()
                        print(
                            "PREPARATION CANCEL: verifier after refused execution=",
                            description.status.name,
                            flush=True,
                        )
                        assert description.status.name == "RUNNING", (
                            "execution refusal must wait for cancellation delivery, "
                            "not fail the child"
                        )
                        release_cancel.set()
                    async with asyncio.timeout(60):
                        await pending_command
                except TimeoutError:
                    state = await inspect(stack, run_id)
                    print("PREPARATION CANCEL: phase=", state["phase"], flush=True)
                    async for execution in stack.client.list_workflows(
                        f"BellLabsRunId = '{run_id}'"
                    ):
                        print(
                            "PREPARATION CANCEL:",
                            execution.workflow_type,
                            execution.status,
                            flush=True,
                        )
                    raise
                finally:
                    release_cancel.set()
                    if not pending_command.done():
                        pending_command.cancel()
                        await asyncio.gather(pending_command, return_exceptions=True)
            else:
                await command(stack, run_id, "cancel", {})
            await until(lambda: condition(stack, run_id, "phase", "terminal"))
            await publish("summary", SUMMARY, '{"summary":"late"}')
            expected = "cancelled"
        else:
            await publish("summary", SUMMARY, '{"summary":"qualified"}')
            await until(lambda: condition(stack, run_id, "lifecycle", "completed"), seconds=300)
            expected = "completed"
        await assert_persisted_run_evidence(stack, run_id, expected)
        if delayed_delivery:
            assert not any(item["operation"].endswith("/verifier") for item in stack.model_log), (
                "accepted cancellation must fence verifier cognition"
            )
            rows = await canonical_evidence(stack.owner_pool, run_id, request_scope=stack.scope)
            assert rows["counts"]["operation_intent"] == 2, rows
            # The journal distinguishes a completed claim ('settled') from 'cancelled'.
            assert rows["counts"]["settled_claims"] == 1, rows
            assert rows["counts"]["operation_receipt"] == 2, rows
            assert rows["counts"]["operation_settlement"] == 2, rows
            scope = parse_request_scope(stack.scope)
            claims = await stack.owner_pool.fetch(
                """SELECT status FROM mission_control.operation_claim
                   WHERE installation_id = $1 AND application_id = $2 AND tenant_id = $3
                     AND run_key = $4 ORDER BY status""",
                scope.installation_id,
                scope.application_id,
                scope.tenant_id,
                run_id,
            )
            assert [row["status"] for row in claims] == ["cancelled", "settled"]
        page = await stack.http.get(base + "/goal-completion-evidence")
        assert page.status_code == 200, page.text
        decisions = page.json()["decisions"]
        terminal = await inspect(stack, run_id)
        if cancel_pending:
            assert not terminal["projection"]["accepted_output_evidence"]
            assert not terminal["projection"]["accepted_obligation_evidence"]
            assert all(item["validation"]["status"] != "satisfied" for item in decisions)
        else:
            assert len(decisions) == 2
            for item in decisions:
                validation = item["validation"]
                assert validation["status"] == "satisfied"
                assert {check["output_slot"] for check in validation["checks"]} == {
                    "report",
                    "summary",
                }
                assert len({check["schema_digest"] for check in validation["checks"]}) == 2
            assert len(terminal["projection"]["accepted_output_evidence"]) == 2
            assert terminal["projection"]["accepted_obligation_evidence"]
        assert {ref for _, ref in calls} == {OUTPUT, SUMMARY}
        replayer = Replayer(
            workflows=[
                MissionRunWorkflow,
                MissionOperationWorkflow,
                StageGraphWorkflow,
                GoalDirectedWorkflow,
            ],
            workflow_runner=coordinator_workflow_runner(),
        )
        root_history = await stack.client.get_workflow_handle(root_id).fetch_history()
        await replayer.replay_workflow(root_history)
        families = [
            event.child_workflow_execution_started_event_attributes.workflow_execution.workflow_id
            for event in root_history.events
            if event.HasField("child_workflow_execution_started_event_attributes")
            and event.child_workflow_execution_started_event_attributes.workflow_type.name
            == "belllabs.goal-directed"
        ]
        assert len(families) == 1
        await replayer.replay_workflow(
            await stack.client.get_workflow_handle(families[0]).fetch_history()
        )
        async for execution in stack.client.list_workflows(f"BellLabsRunId = '{run_id}'"):
            if execution.workflow_type == "mc.operation.v1":
                await replayer.replay_workflow(
                    await stack.client.get_workflow_handle(execution.id).fetch_history()
                )
