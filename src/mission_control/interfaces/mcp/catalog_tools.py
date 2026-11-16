"""External discovery, candidate inspection and pinning on the operator MCP server.

The four tools the HTTP catalog routes and `missionctl catalog` already offer, over the same
tenant `CatalogService` and behind the same permissions:

- `pin_capability(query, ...)` (`catalog.read`): exactly one Capability Pin for a query, as
  `POST /catalog/pin`; registered wherever capability search is composed;
- `discover_mcp_servers(query)` and `discover_agent_skills(query)` (`capability.discover`):
  external candidates, recorded as candidates and never as capabilities, as
  `POST /catalog/discover`; registered only where the API composed external discovery;
- `inspect_external_candidate(candidate_id)` (`capability.inspect`): the static, non-installing
  inspection report of one candidate, as `POST /catalog/inspect`; registered only where the
  API composed candidate inspection.

Discovered is not runnable: nothing here publishes, admits or binds a capability. A candidate
becomes selectable only through governed registration into the catalog, and a mission uses a
catalog capability only once `selection_check` and `mission_manifest_compile` admit it.

`search_capabilities` and `get_capability` are not here (`mission_search` and
`mission_describe` answer for them), nor the ticket launch tools: the manifest is the one
launch path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Final
from uuid import uuid4

from fastmcp import Context, FastMCP

from mission_control.application.capabilities.capability_search_repository import (
    CapabilitySearchUnavailable,
)
from mission_control.application.capabilities.catalog import (
    AmbiguousCapability,
    CapabilityNotFound,
    CatalogService,
    PinRequest,
    resolve_pin,
)
from mission_control.application.capabilities.external_candidate_inspection import (
    ExternalCandidateInspectionRequest,
    InspectionAuthorizationError,
    InspectionPrincipal,
)
from mission_control.application.capabilities.external_candidate_repository import (
    ExternalCandidateNotFound,
)
from mission_control.domain.authoring.contracts import DefinitionKind
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.coordinator.errors import CoordinatorDomainError, CoordinatorErrorCode
from mission_control.interfaces.mcp.mission_tools import MissionToolPrincipal, scope_of

PIN_TOOL: Final = "pin_capability"
DISCOVER_MCP_TOOL: Final = "discover_mcp_servers"
DISCOVER_SKILLS_TOOL: Final = "discover_agent_skills"
INSPECT_TOOL: Final = "inspect_external_candidate"
DISCOVERY_TOOL_NAMES: Final = (PIN_TOOL, DISCOVER_MCP_TOOL, DISCOVER_SKILLS_TOOL, INSPECT_TOOL)
READ_PERMISSION: Final = "catalog.read"
DISCOVER_PERMISSION: Final = "capability.discover"
INSPECT_PERMISSION: Final = "capability.inspect"
# The role the HTTP inspect route requests an inspection under.
INSPECTION_ROLE: Final = "coordinator_planner"


def _unavailable(message: str) -> CoordinatorDomainError:
    return CoordinatorDomainError(CoordinatorErrorCode.DEPENDENCY_UNAVAILABLE, message)


def _did_not_answer(what: str, error: RuntimeError) -> CoordinatorDomainError:
    """A registry, the skills index or the subprocess this server would start for it did not
    answer: a dependency of the server, never an empty result."""

    if isinstance(error, NotImplementedError):
        # asyncio raises it bare where the loop has no subprocess support: the selector loop
        # the API runs on Windows (`bootstrap.api.api_loop_factory`).
        return _unavailable(
            f"{what} starts a subprocess and this server's event loop cannot start one (the "
            "selector loop the API uses on Windows); it answers where the API runs on a loop "
            "with subprocess support"
        )
    return _unavailable(f"{what} did not answer ({type(error).__name__}): {error}"[:500])


class ScopedCatalog:
    """Selects the catalog service of the principal's verified tenant scope."""

    def __init__(self, services: Mapping[str, CatalogService]) -> None:
        self._services = dict(services)

    @property
    def pins(self) -> bool:
        return any(service.search is not None for service in self._services.values())

    @property
    def discovers(self) -> bool:
        return any(service.discovery is not None for service in self._services.values())

    @property
    def inspects(self) -> bool:
        return any(service.inspection is not None for service in self._services.values())

    def _service(self, principal: MissionToolPrincipal, permission: str) -> CatalogService:
        service = self._services.get(scope_of(principal, None))
        if service is None or service.request_scope != principal.request_scope:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.FORBIDDEN, message="no catalog for scope"
            )
        if permission not in principal.permissions:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.FORBIDDEN,
                message=f"principal lacks {permission}",
                details={"required": permission},
            )
        return service

    async def pin(
        self,
        principal: MissionToolPrincipal,
        *,
        query: str,
        kinds: list[str] | None,
        host_profiles: list[str] | None,
        side_effect_classes: list[str] | None,
        margin: float | None,
    ) -> dict[str, Any]:
        service = self._service(principal, READ_PERMISSION)
        if service.search is None:
            raise _unavailable("capability search is not composed on this server")
        request = PinRequest.model_validate(
            {
                "query": query,
                "kinds": [DefinitionKind(kind).value for kind in kinds or ()],
                "host_profiles": [LaneProfile(item).value for item in host_profiles or ()],
                "side_effect_classes": list(side_effect_classes or ()),
                **({"margin": margin} if margin is not None else {}),
            }
        )
        try:
            resolution = await resolve_pin(
                service.search, request.search_request(service.catalog_scope), margin=request.margin
            )
        except AmbiguousCapability as error:
            raise CoordinatorDomainError(
                CoordinatorErrorCode.AMBIGUOUS_CAPABILITY,
                str(error),
                details={"candidates": ",".join(item.pin for item in error.candidates)},
            ) from None
        except CapabilityNotFound as error:
            raise CoordinatorDomainError(
                CoordinatorErrorCode.CAPABILITY_NOT_FOUND, str(error)
            ) from None
        except CapabilitySearchUnavailable as error:
            raise _unavailable(str(error)) from None
        return resolution.model_dump(mode="json")

    async def discover(
        self,
        principal: MissionToolPrincipal,
        *,
        source: str,
        query: str,
        limit: int,
        owner: str | None = None,
    ) -> dict[str, Any]:
        service = self._service(principal, DISCOVER_PERMISSION)
        if service.discovery is None:
            raise _unavailable("external capability discovery is not composed on this server")
        try:
            batch = await (
                service.discovery.discover_mcp_servers(query, limit=limit)
                if source == "mcp"
                else service.discovery.discover_agent_skills(query, limit=limit, owner=owner)
            )
        except RuntimeError as error:
            what = "MCP server discovery" if source == "mcp" else "agent-skill discovery"
            raise _did_not_answer(what, error) from None
        return batch.model_dump(mode="json")

    async def inspect(
        self, principal: MissionToolPrincipal, *, candidate_id: str
    ) -> dict[str, Any]:
        service = self._service(principal, INSPECT_PERMISSION)
        if service.inspection is None:
            raise _unavailable("external candidate inspection is not composed on this server")
        try:
            report = await service.inspection.inspect(
                InspectionPrincipal(
                    actor_id=principal.actor_id,
                    tenant_scope=service.request_scope,
                    roles=frozenset({INSPECTION_ROLE}),
                ),
                ExternalCandidateInspectionRequest(
                    candidate_id=candidate_id,
                    correlation_id=str(uuid4()),
                    requested_at=datetime.now(UTC),
                ),
            )
        except ExternalCandidateNotFound:
            raise CoordinatorDomainError(
                CoordinatorErrorCode.NOT_FOUND,
                "no external candidate with that id: discover first and pass a candidate_id "
                "from the answer",
            ) from None
        except InspectionAuthorizationError as error:
            raise CoordinatorDomainError(CoordinatorErrorCode.FORBIDDEN, str(error)) from None
        except RuntimeError as error:
            raise _did_not_answer("candidate inspection", error) from None
        return report.model_dump(mode="json")


def register_catalog_tools(
    server: FastMCP,
    catalog: ScopedCatalog,
    principals: Any,
    *,
    call: Callable[..., Awaitable[dict[str, object]]],
) -> None:
    """Register what the composed catalog services can answer; `call` wraps results in the MCP
    envelope."""

    if catalog.pins:

        @server.tool(name=PIN_TOOL, annotations={"readOnlyHint": True})
        async def pin_capability(
            query: str,
            context: Context,
            kinds: list[str] | None = None,
            host_profiles: list[str] | None = None,
            side_effect_classes: list[str] | None = None,
            margin: float | None = None,
        ) -> dict[str, object]:
            """Resolve a query to exactly one Capability Pin of the catalog, or
            AMBIGUOUS_CAPABILITY with the candidates. `kinds` are catalog kinds (skill,
            mcp_server, tool ...) and `host_profiles` lane profiles. Write the `pin` in a
            manifest as `{pin: <pin>}`."""

            async def invoke(principal: Any) -> object:
                return await catalog.pin(
                    principal,
                    query=query,
                    kinds=kinds,
                    host_profiles=host_profiles,
                    side_effect_classes=side_effect_classes,
                    margin=margin,
                )

            return await call(context, principals, invoke)

    if catalog.discovers:
        open_world = {"readOnlyHint": False, "idempotentHint": False, "openWorldHint": True}

        @server.tool(name=DISCOVER_MCP_TOOL, annotations=open_world)
        async def discover_mcp_servers(
            query: str, context: Context, limit: int = 10
        ) -> dict[str, object]:
            """Search the public MCP registry for servers the catalog lacks. Returns
            `candidates`, recorded as candidates only: a candidate cannot run. Discovered is
            not runnable; inspect one with inspect_external_candidate."""

            async def invoke(principal: Any) -> object:
                return await catalog.discover(principal, source="mcp", query=query, limit=limit)

            return await call(context, principals, invoke)

        @server.tool(name=DISCOVER_SKILLS_TOOL, annotations=open_world)
        async def discover_agent_skills(
            query: str, context: Context, limit: int = 10, owner: str | None = None
        ) -> dict[str, object]:
            """Search the public Agent Skills index for skills the catalog lacks (`owner`
            narrows to one publisher). Returns `candidates`, recorded as candidates only.
            Discovered is not runnable."""

            async def invoke(principal: Any) -> object:
                return await catalog.discover(
                    principal, source="skills", query=query, limit=limit, owner=owner
                )

            return await call(context, principals, invoke)

    if catalog.inspects:

        @server.tool(name=INSPECT_TOOL, annotations={"readOnlyHint": False})
        async def inspect_external_candidate(
            candidate_id: str, context: Context
        ) -> dict[str, object]:
            """Run the static, non-installing inspection of one discovered candidate
            (`candidate_id` from a discover answer) and return its report. It installs and
            admits nothing: a candidate becomes selectable only once it is published to the
            catalog."""

            async def invoke(principal: Any) -> object:
                return await catalog.inspect(principal, candidate_id=candidate_id)

            return await call(context, principals, invoke)


__all__ = [
    "DISCOVERY_TOOL_NAMES",
    "DISCOVER_MCP_TOOL",
    "DISCOVER_SKILLS_TOOL",
    "INSPECT_TOOL",
    "PIN_TOOL",
    "ScopedCatalog",
    "register_catalog_tools",
]
