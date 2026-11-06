"""Plan the exact dev namespace's additive attributes; applying needs the reviewed plan."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path

from temporalio.api.cloud.cloudservice.v1 import GetNamespaceRequest, UpdateNamespaceRequest
from temporalio.api.cloud.namespace.v1 import Namespace, NamespaceSpec
from temporalio.api.cloud.resource.v1 import ResourceState
from temporalio.client import CloudOperationsClient

from mission_control.adapters.temporal.cloud_namespace import (
    CLOUD_API_VERSION,
    cloud_search_attributes,
)
from mission_control.domain.programs.search_attributes import BELLLABS_SEARCH_ATTRIBUTES

NAMESPACE = "mission-control-dev.ih0e7"
REGION = "aws-us-east-1"
KINDS = {"keyword": 2, "int": 3, "keyword_list": 7}


def plan(namespace: Namespace) -> dict:
    if (
        namespace.namespace != NAMESPACE
        or namespace.active_region != REGION
        or namespace.state != ResourceState.RESOURCE_STATE_ACTIVE
        or not namespace.resource_version
    ):
        raise ValueError("namespace target, active region/state or resource version differs")
    registered = cloud_search_attributes(namespace.spec)
    additions = {}
    for name, kind in BELLLABS_SEARCH_ATTRIBUTES.items():
        if name in registered and registered[name] != KINDS[kind]:
            raise ValueError("existing search attribute has a conflicting type")
        if name not in registered:
            additions[name] = kind
    return {
        "namespace": NAMESPACE,
        "region": REGION,
        "api_version": CLOUD_API_VERSION,
        "resource_version": namespace.resource_version,
        "spec_sha256": hashlib.sha256(
            namespace.spec.SerializeToString(deterministic=True)
        ).hexdigest(),
        "additions": dict(sorted(additions.items())),
    }


def updated_spec(namespace: Namespace, reviewed: dict) -> NamespaceSpec:
    if plan(namespace) != reviewed:
        raise ValueError("namespace changed since the plan was reviewed; replan before applying")
    result = NamespaceSpec()
    result.CopyFrom(namespace.spec)
    for name, kind in reviewed["additions"].items():
        result.search_attributes[name] = KINDS[kind]
    return result


async def run(path: Path, *, apply: bool) -> dict:
    key = os.environ.get("TEMPORAL_CLOUD_API_KEY", "").strip()
    if not key:
        raise ValueError("Temporal Cloud credential is absent")
    client = await CloudOperationsClient.connect(api_key=key, version=CLOUD_API_VERSION)
    response = await client.cloud_service.get_namespace(GetNamespaceRequest(namespace=NAMESPACE))
    proposal = plan(response.namespace)
    if not apply:
        # Do not overwrite a previously reviewed plan.
        with path.open("x", encoding="utf-8") as output:
            json.dump(proposal, output, indent=2)
        return proposal
    reviewed = json.loads(await asyncio.to_thread(path.read_text, "utf-8"))
    spec = updated_spec(response.namespace, reviewed)
    if not reviewed["additions"]:
        return {"namespace": NAMESPACE, "state": "already_configured"}
    result = await client.cloud_service.update_namespace(
        UpdateNamespaceRequest(
            namespace=NAMESPACE, resource_version=reviewed["resource_version"], spec=spec
        )
    )
    return {
        "namespace": NAMESPACE,
        "state": "submitted_readback_required",
        "async_operation_id": result.async_operation.id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = asyncio.run(asyncio.wait_for(run(args.plan, apply=args.apply), timeout=30))
    except Exception as error:
        print(json.dumps({"state": "blocked", "error_type": type(error).__name__}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
