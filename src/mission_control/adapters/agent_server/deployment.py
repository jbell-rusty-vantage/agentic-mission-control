"""Server-selected graph topology for the single Agent Server deployment config."""

from __future__ import annotations

import os
from collections.abc import Mapping
from uuid import UUID, uuid5

from langgraph_sdk import Auth

from mission_control.domain.execution.async_subagent_reconciliation import (
    SEALED_BINDING_DIGEST_KEY,
    sealed_child_assistant_id,
)

GRAPH_NAMESPACE = UUID("6ba7b821-9dad-11d1-80b4-00c04fd430c8")
CHILD_GRAPH = "belllabs_async_technical_child"
# OVE-184: the generic graph that materializes a sealed child binding per run.
SEALED_CHILD_GRAPH = "belllabs_async_child"
QUALIFICATION_GRAPHS = frozenset(
    {"block_c_qualification", "block_c_qualification_n1", "block_c_wait"}
)
PROFILES = {
    "runtime": frozenset({CHILD_GRAPH, SEALED_CHILD_GRAPH}),
    "qualification": QUALIFICATION_GRAPHS,
    "qualification_n1": frozenset({"block_c_qualification_n1"}),
}


def profile() -> str:
    value = os.environ.get("MISSION_CONTROL_AGENT_SERVER_PROFILE", "runtime")
    if value not in PROFILES:
        raise RuntimeError("unknown Mission Control Agent Server profile")
    return value


def allowed_graphs() -> frozenset[str]:
    return PROFILES[profile()]


def require_graph(graph_id: str) -> None:
    if graph_id not in allowed_graphs():
        raise Auth.exceptions.HTTPException(
            status_code=403, detail=f"graph {graph_id} disabled by Agent Server profile"
        )


def require_assistant(
    assistant_id: object,
    *,
    request_scopes: frozenset[str] = frozenset(),
    metadata: Mapping[str, object] | None = None,
) -> None:
    # Pinned langgraph-api 0.12.0 graph.register_graph uses uuid5(NAMESPACE_GRAPH,
    # graph_id), with the exact vendor graph namespace pinned above.
    if static_assistant(assistant_id):
        return
    if str(assistant_id) == sealed_assistant(request_scopes, metadata):
        return
    raise Auth.exceptions.HTTPException(
        status_code=403, detail="assistant disabled by Agent Server profile"
    )


def static_assistant(assistant_id: object) -> bool:
    """A served graph's id or its deployment default assistant (system topology)."""

    allowed = {str(uuid5(GRAPH_NAMESPACE, item)) for item in allowed_graphs()}
    allowed.update(allowed_graphs())
    return str(assistant_id) in allowed


def sealed_assistant(
    request_scopes: frozenset[str], metadata: Mapping[str, object] | None
) -> str | None:
    """The one sealed-child assistant the caller may name (OVE-184), else ``None``.

    It is recomputed from the caller's single verified scope and the binding digest the
    request names, so a caller can create or run only its own scope's assistant of that exact
    binding, and only while the sealed-child graph is served.
    """

    digest = (metadata or {}).get(SEALED_BINDING_DIGEST_KEY)
    if (
        SEALED_CHILD_GRAPH not in allowed_graphs()
        or len(request_scopes) != 1
        or not isinstance(digest, str)
    ):
        return None
    return sealed_child_assistant_id(next(iter(request_scopes)), digest)
