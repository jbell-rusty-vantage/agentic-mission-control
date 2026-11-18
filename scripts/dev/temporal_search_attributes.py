"""Register and list the Mission Control Search Attributes on a Temporal namespace (FT-G7).

`make temporal-up` runs this after the compose server and its namespace job are up. The
registration is the operator-service path the workers verify at startup
(`register_belllabs_search_attributes`): idempotent, a same-typed existing attribute is
accepted, a conflicting type fails. The readiness listing prints every declared attribute
with its registered type, so the operator sees `mc_mission_id`, `mc_run_id`, `mc_lane`,
`mc_phase` and `ForkedFromRunId` beside the BellLabs core.

Usage::

    uv run python scripts/dev/temporal_search_attributes.py [--address 127.0.0.1:7233]
        [--namespace default] [--check-only] [--timeout 120]

It connects only to the address given (default: the local development server); it never
reads TEMPORAL_CLOUD_API_KEY and never touches Temporal Cloud.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys

from temporalio.api.enums.v1 import IndexedValueType
from temporalio.api.operatorservice.v1 import ListSearchAttributesRequest
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
from temporalio.client import Client

from mission_control.adapters.temporal.client import TemporalConnection, connect_temporal
from mission_control.adapters.temporal.search_attributes import (
    SearchAttributeRegistrationError,
    register_belllabs_search_attributes,
    verify_belllabs_search_attributes,
)
from mission_control.domain.programs.search_attributes import BELLLABS_SEARCH_ATTRIBUTES


async def _ready_client(address: str, namespace: str, within_seconds: float) -> Client:
    async with asyncio.timeout(within_seconds):
        while True:
            try:
                client = await connect_temporal(
                    TemporalConnection(target="local", address=address, namespace=namespace)
                )
                await client.workflow_service.describe_namespace(
                    DescribeNamespaceRequest(namespace=namespace)
                )
                return client
            except Exception:  # server or namespace job still starting
                await asyncio.sleep(2)


async def _register(client: Client, namespace: str, within_seconds: float) -> tuple[str, ...]:
    """Register, retrying while a just-created namespace is not yet visible to the operator
    service (the server's namespace cache refreshes every few seconds). A type conflict is
    final and is raised at once."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + within_seconds
    while True:
        try:
            return await register_belllabs_search_attributes(client, namespace)
        except SearchAttributeRegistrationError as error:
            if "conflicting type" in str(error) or loop.time() >= deadline:
                raise
            print(f"registration not accepted yet, retrying: {error}", file=sys.stderr)
            await asyncio.sleep(2)


async def _verified(client: Client, namespace: str, within_seconds: float) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + within_seconds
    while True:
        try:
            await verify_belllabs_search_attributes(client, namespace)
            return
        except SearchAttributeRegistrationError:
            if loop.time() >= deadline:
                raise
            await asyncio.sleep(2)


async def _main(args: argparse.Namespace) -> int:
    client = await _ready_client(args.address, args.namespace, args.timeout)
    if not args.check_only:
        try:
            added = await _register(client, args.namespace, args.timeout)
        except SearchAttributeRegistrationError as error:
            print(f"registration failed: {error}", file=sys.stderr)
            return 1
        print(f"registered: {', '.join(added) if added else 'none (all present)'}")
        # Newly added attributes become visible after the same cache refresh.
        with contextlib.suppress(SearchAttributeRegistrationError):  # reported below, per attribute
            await _verified(client, args.namespace, args.timeout)
    response = await client.operator_service.list_search_attributes(
        ListSearchAttributesRequest(namespace=args.namespace)
    )
    registered = dict(response.custom_attributes)
    for name, kind in BELLLABS_SEARCH_ATTRIBUTES.items():
        actual = registered.get(name)
        label = IndexedValueType.Name(actual) if actual is not None else "MISSING"
        print(f"{name:32} declared={kind:13} registered={label}")
    try:
        await verify_belllabs_search_attributes(client, args.namespace)
    except SearchAttributeRegistrationError as error:
        print(f"not ready: {error}", file=sys.stderr)
        return 1
    print(f"ready: {len(BELLLABS_SEARCH_ATTRIBUTES)} Search Attributes on {args.namespace}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--address", default="127.0.0.1:7233")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--check-only", action="store_true")
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
