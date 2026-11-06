"""`signal_emit`: the MCP mirror of `mc-signal` (SPEC-04 section 4.1; ADR-0045).

An agent that prefers tools to the `mc-signal` command calls `signal_emit(type, message?,
data?, signal_id?)` on the Mission Control signals server, mounted on the Signal Ingress at
`/v1/ingress/{application_id}/mcp` (Streamable HTTP, stateless, JSON responses) by
:func:`mount_signal_tools`. It authenticates exactly as the hooks do: the request's own
`Authorization: Bearer` run token or Cursor OIDC JWT, verified by the application's
`SignalIngressService`. The tool builds one `mc.signal.v1` and makes the same service call
`POST signals` makes, so verification, redaction, size caps, dedupe on `signal_id` and the
run binding stay the ingress's. The `environment_key` tier signs the raw HTTP body and so
cannot call a tool; it uses the command.

This is deliberately not a tool of the operator surface (`operator_server.py`): that surface
takes the operator's bearer token, which never enters an environment. A signal is evidence,
never authority; the tool's answer is a receipt, never an instruction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.http import StarletteWithLifespan
from pydantic import ValidationError

from mission_control.application.signals.contracts import IngressRejected, Signal
from mission_control.application.signals.service import SignalIngressService, rejection
from mission_control.contracts.identities import uuid7

SIGNAL_EMIT_TOOL: Final = "signal_emit"
SIGNAL_MCP_PATH: Final = "/v1/ingress/{application_id}/mcp"
MAX_MESSAGE_CHARS: Final = 4000


def _refused(error: IngressRejected) -> dict[str, Any]:
    return {"ok": False, "error": {"code": error.code, "status": error.status_code}}


def register_signal_tools(server: FastMCP, services: Mapping[str, SignalIngressService]) -> None:
    """Register `signal_emit` over one ingress service per application id."""

    @server.tool(
        name=SIGNAL_EMIT_TOOL,
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def signal_emit(
        type: str,  # noqa: A002 - the signal field's wire name
        message: str | None = None,
        data: dict[str, Any] | None = None,
        signal_id: str | None = None,
    ) -> dict[str, Any]:
        """Report a milestone, blocker, needed input, ready artifact or progress to Mission
        Control (skill mc-signals). `type` is lowercase words joined by dots or underscores
        (`milestone`, `blocked`, `needs_input`, `artifact.ready`, `progress`); `message` is one
        short sentence; `data` holds facts a watcher can match on. Pass the same `signal_id`
        to retry without a duplicate. Never put secrets in a signal."""

        request = get_http_request()
        service = services.get(str(request.path_params.get("application_id", "")))
        if service is None:
            return _refused(rejection("unknown_application"))
        fields = dict(data or {})
        if message is not None:
            fields["message"] = message[:MAX_MESSAGE_CHARS]
        fields.setdefault("source", "mcp")
        try:
            signal = Signal(signal_id=signal_id or f"mcp-{uuid7().hex}", type=type, data=fields)
        except ValidationError:
            return _refused(rejection("invalid_item"))
        try:
            receipt = await service.signals(
                signal.model_dump_json(exclude_none=True).encode(), request.headers
            )
        except IngressRejected as error:
            return _refused(error)
        return {"ok": True, "signal_id": signal.signal_id, **receipt.model_dump(mode="json")}


def create_signal_server(services: Iterable[SignalIngressService]) -> FastMCP:
    server = FastMCP(
        "Mission Control signals",
        instructions=(
            "Report to Mission Control from inside a mission workspace with signal_emit. "
            "Signals are evidence for the coordinator and watchers; nobody answers them."
        ),
        mask_error_details=True,
        strict_input_validation=True,
    )
    register_signal_tools(server, {service.application_id: service for service in services})
    return server


def mount_signal_tools(
    app: FastAPI, services: Iterable[SignalIngressService]
) -> StarletteWithLifespan:
    """Mount the signals server on an ingress app; the caller enters the returned app's
    lifespan (FastMCP's session manager) for as long as `app` serves."""

    mcp = create_signal_server(services).http_app(
        path="/", transport="streamable-http", stateless_http=True, json_response=True
    )
    app.mount(SIGNAL_MCP_PATH, mcp)
    return mcp


__all__ = [
    "SIGNAL_EMIT_TOOL",
    "SIGNAL_MCP_PATH",
    "create_signal_server",
    "mount_signal_tools",
    "register_signal_tools",
]
