"""Exact dev namespace probe. Default is read-only; no-op execution is separately opted in."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import timedelta
from uuid import uuid4

from temporalio import workflow
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
from temporalio.client import Client
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from mission_control.adapters.temporal.cloud_namespace import registered_cloud_search_attributes
from mission_control.adapters.temporal.search_attributes import verify_belllabs_search_attributes
from mission_control.domain.programs.search_attributes import BELLLABS_SEARCH_ATTRIBUTES

ADDRESS = "us-east-1.aws.api.temporal.io:7233"
NAMESPACE = "mission-control-dev.ih0e7"


@workflow.defn(name="mc.run2.namespace_probe.v1")
class NamespaceProbe:
    @workflow.run
    async def run(self) -> str:
        return "completed"


async def probe(*, execute_noop: bool = False) -> dict:
    if (
        os.environ.get("TEMPORAL_TARGET") != "cloud"
        or os.environ.get("TEMPORAL_ADDRESS") != ADDRESS
        or os.environ.get("TEMPORAL_NAMESPACE") != NAMESPACE
    ):
        raise ValueError("probe requires the exact approved dev target/address/namespace")
    key = os.environ.get("TEMPORAL_CLOUD_API_KEY")
    if not key:
        raise ValueError("Temporal Cloud credential is absent")
    client = await Client.connect(ADDRESS, namespace=NAMESPACE, api_key=key, tls=True)
    described = await client.workflow_service.describe_namespace(
        DescribeNamespaceRequest(namespace=NAMESPACE)
    )
    attributes = await registered_cloud_search_attributes(key, NAMESPACE)
    result = {
        "namespace": described.namespace_info.name,
        "address": ADDRESS,
        "search_attributes": dict(sorted(attributes.items())),
        "missing_search_attributes": sorted(set(BELLLABS_SEARCH_ATTRIBUTES) - set(attributes)),
        "noop": "unrun",
        "qualification": "connection only",
    }
    if execute_noop:
        await verify_belllabs_search_attributes(client, NAMESPACE, cloud_api_key=key)
        identity = "run2-probe-" + uuid4().hex
        async with Worker(
            client,
            task_queue=identity,
            workflows=[NamespaceProbe],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result["noop"] = await client.execute_workflow(
                NamespaceProbe.run,
                id=identity,
                task_queue=identity,
                execution_timeout=timedelta(seconds=60),
            )
        result["workflow_id"] = identity
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute-noop", action="store_true", help="authorized finite namespace write"
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(probe(execute_noop=args.execute_noop))
    except Exception as error:
        print(json.dumps({"state": "blocked", "error_type": type(error).__name__}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
