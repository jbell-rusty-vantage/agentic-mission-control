"""One authentication entrypoint; scoped credentials never choose server topology."""

from typing import Any

from langgraph_sdk import Auth

from mission_control.adapters.agent_server import auth as runtime_auth
from mission_control.adapters.agent_server.async_subagents import auth as subordinate_auth
from mission_control.adapters.agent_server.block_c_qualification import auth as qualification_auth
from mission_control.adapters.agent_server.context import principal_from_auth_user
from mission_control.adapters.agent_server.deployment import (
    SEALED_CHILD_GRAPH,
    profile,
    require_assistant,
    sealed_assistant,
    static_assistant,
)
from mission_control.domain.execution.async_subagent_reconciliation import (
    SEALED_BINDING_DIGEST_KEY,
    SEALED_CONTRACT_DIGEST_KEY,
)

auth = Auth()


@auth.authenticate
async def authenticate(headers: dict[bytes, bytes]) -> Auth.types.MinimalUserDict:
    if profile() != "runtime":
        return await qualification_auth.authenticate(headers)
    authorization = headers.get(b"authorization", b"").lower()
    if authorization.startswith(b"bearer bl1."):
        user = await subordinate_auth.authenticate(headers)
        user["permissions"] = (*user["permissions"], "credential:subordinate")
        return user
    return await runtime_auth.authenticate(headers)


def subordinate(ctx: Auth.types.AuthContext) -> bool:
    return "credential:subordinate" in (getattr(ctx.user, "permissions", ()) or ())


@auth.on
async def default_deny(ctx: Auth.types.AuthContext, value: Any) -> bool:
    return await runtime_auth.default_deny(ctx, value)


def _scopes(ctx: Auth.types.AuthContext) -> frozenset[str]:
    return principal_from_auth_user(ctx.user).request_scopes


def _metadata(value: dict[str, Any]) -> dict[str, Any]:
    metadata = value.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


@auth.on.threads
async def threads(ctx: Auth.types.AuthContext, value: dict[str, Any]) -> dict[str, str]:
    # Native Agent Protocol emits runs as threads/create_run (including inmem).
    if str(ctx.action).lower().endswith("create_run"):
        require_assistant(
            value.get("assistant_id"), request_scopes=_scopes(ctx), metadata=_metadata(value)
        )
    return await runtime_auth.authorize_threads(ctx, value)


@auth.on(resources="runs")
async def runs(ctx: Auth.types.AuthContext, value: dict[str, Any]) -> dict[str, str]:
    if "create" in str(ctx.action).lower():
        require_assistant(
            value.get("assistant_id"), request_scopes=_scopes(ctx), metadata=_metadata(value)
        )
    return await runtime_auth.authorize_runs(ctx, value)


@auth.on.assistants
async def assistants(ctx: Auth.types.AuthContext, value: dict[str, Any]) -> dict[str, str]:
    action = str(getattr(ctx, "action", "")).lower().rsplit(".", maxsplit=1)[-1]
    if subordinate(ctx):
        scopes = _scopes(ctx)
        if action == "create":
            # OVE-184: a parent creates exactly its own scope's assistant of one sealed child
            # binding, on the sealed-child graph, configured with that binding's digest.
            return sealed_assistant_create(value, scopes)
        if action not in {"read", "search"} or len(scopes) != 1:
            raise Auth.exceptions.HTTPException(status_code=403, detail="assistant denied")
        if action == "read" and static_assistant(value.get("assistant_id")):
            # Deployment topology (a served graph's default assistant) carries no scope
            # metadata; it stays readable exactly as before (review B1).
            return {}
        # A subordinate reads only its own scope's assistants. The server applies this filter
        # to the assistant's metadata on every read, including the ownership check it makes
        # before running a non-system assistant (pinned langgraph-api 0.12.0 inmem runtime).
        return {"request_scope": next(iter(scopes))}
    if value.get("assistant_id") is not None:
        require_assistant(
            value["assistant_id"], request_scopes=_scopes(ctx), metadata=_metadata(value)
        )
    return await runtime_auth.authorize_assistants(ctx, value)


def sealed_assistant_create(value: dict[str, Any], scopes: frozenset[str]) -> dict[str, str]:
    metadata = _metadata(value)
    config = value.get("config")
    configurable = config.get("configurable") if isinstance(config, dict) else None
    expected = sealed_assistant(scopes, metadata)
    if (
        expected is None
        or value.get("graph_id") != SEALED_CHILD_GRAPH
        or str(value.get("assistant_id")) != expected
        or not isinstance(configurable, dict)
        or configurable.get(SEALED_BINDING_DIGEST_KEY) != metadata.get(SEALED_BINDING_DIGEST_KEY)
        or not configurable.get(SEALED_CONTRACT_DIGEST_KEY)
        or configurable.get(SEALED_CONTRACT_DIGEST_KEY) != metadata.get(SEALED_CONTRACT_DIGEST_KEY)
    ):
        raise Auth.exceptions.HTTPException(
            status_code=403, detail="only the caller's sealed child assistant may be created"
        )
    [scope] = scopes
    metadata["request_scope"] = scope
    return {"request_scope": scope}


@auth.on.store()
async def store(ctx: Auth.types.AuthContext, value: dict[str, Any]) -> bool:
    if subordinate(ctx) or profile() != "runtime":
        return await subordinate_auth.deny_store(ctx, value)
    return await runtime_auth.authorize_store(ctx, value)


@auth.on.crons
async def crons(ctx: Auth.types.AuthContext, value: Any) -> bool:
    return await runtime_auth.deny_crons(ctx, value)
