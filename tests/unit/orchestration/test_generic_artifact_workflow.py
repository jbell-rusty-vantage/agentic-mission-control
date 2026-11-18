from __future__ import annotations

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from mission_control.adapters.temporal.artifact_workflow import GenericArtifactWorkflow
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner


@activity.defn(name="operation.execute")
async def complete_operation(payload: dict) -> dict:
    return {
        "binding_id": "binding:temporal-test",
        "semantic_attempt_key": "run:operation:test:attempt:1",
        "status": "completed",
        "output_text": "candidate captured",
        "structured_output": None,
        "output_refs": ["candidate:test"],
        "usage": {"amounts": {}, "pending_external_amounts": {}},
        "failure_code": None,
        "failure_message": None,
    }


@activity.defn(name="artifact.promote")
async def promote_artifact(payload: dict) -> dict:
    assert payload["binding_id"] == "binding:temporal-test"
    return {
        "artifact_id": "artifact:temporal-test",
        "content_digest": "sha256:" + "a" * 64,
        "object_ref": "s3://test/artifact",
        "metadata_revision": 4,
        "manifest_revision": 3,
        "durable_reference": "artifact://tenant/run/artifact",
        "status": "admitted",
    }


async def test_generic_temporal_workflow_promotes_only_after_operation(
    workflow_env: WorkflowEnvironment,
) -> None:
    async with Worker(
        workflow_env.client,
        task_queue="generic-artifact-test",
        workflows=[GenericArtifactWorkflow],
        workflow_runner=coordinator_workflow_runner(),
        activities=[complete_operation, promote_artifact],
    ):
        result = await workflow_env.client.execute_workflow(
            GenericArtifactWorkflow.run,
            {
                "request_scope": "tenant",
                "operation": {"ignored": "by fake"},
                "promotion": {"logical_path": "/workspace/output/report.md"},
            },
            id="generic-artifact-test",
            task_queue="generic-artifact-test",
        )

    assert result["operation"]["status"] == "completed"
    assert result["artifact"]["status"] == "admitted"
