"""Selection Workspace tools on the coordinator and operator MCP servers.

- tool `mission_search(query, facets, kinds, lane_profile, limit, offset, include_lowered)`
  (read-only; `catalog.read`): one ranked answer over capabilities, lanes, models, sandbox
  profiles, Workflow Types and mission templates, or without a query a listing of them by
  name, as `POST /selection/search` returns it.
- tool `selection_check(draft)` (read-only; `catalog.read`): whether a draft selection would be
  admitted, with typed refusals and what was not checked, as `POST /selection/check`.

The principal's canonical request scope selects the tenant's workspace; neither tool launches.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import ValidationError

from mission_control.application.selection.workspace import (
    FACETS,
    SelectionDraft,
    SelectionSearchRequest,
    SelectionWorkspace,
)
from mission_control.domain.authoring.contracts import DefinitionKind
from mission_control.domain.coordinator.errors import CoordinatorDomainError, CoordinatorErrorCode
from mission_control.interfaces.mcp.mission_tools import (
    MissionToolPrincipal,
    PrincipalResolver,
    ShapeOf,
    scope_of,
)

SEARCH_TOOL = "mission_search"
CHECK_TOOL = "selection_check"
# One permission name on every transport (HTTP, CLI, MCP): `catalog.read`.
READ_GRANTS = frozenset({"catalog.read"})


class ScopedSelection:
    """Selects the Selection Workspace of the principal's verified tenant scope."""

    def __init__(self, workspaces: Mapping[str, SelectionWorkspace]) -> None:
        self._workspaces = dict(workspaces)

    def workspace(self, principal: MissionToolPrincipal) -> SelectionWorkspace:
        if not frozenset(principal.permissions) & READ_GRANTS:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.FORBIDDEN, message="principal lacks catalog read"
            )
        workspace = self._workspaces.get(scope_of(principal, None))
        if workspace is None:
            raise CoordinatorDomainError(
                code=CoordinatorErrorCode.FORBIDDEN, message="no selection workspace for scope"
            )
        return workspace

    async def search(
        self, principal: MissionToolPrincipal, request: SelectionSearchRequest
    ) -> dict[str, object]:
        result = await self.workspace(principal).search(request)
        return result.model_dump(mode="json")

    async def check(
        self, principal: MissionToolPrincipal, draft: SelectionDraft
    ) -> dict[str, object]:
        result = await self.workspace(principal).check(draft)
        return result.model_dump(mode="json")


def search_request(values: Mapping[str, object]) -> SelectionSearchRequest:
    """The search request, or an `INVALID_ARGUMENT` that names the facets and kinds."""

    try:
        return SelectionSearchRequest.model_validate(dict(values))
    except ValidationError:
        raise CoordinatorDomainError(
            CoordinatorErrorCode.INVALID_ARGUMENT,
            f"invalid search arguments: facets are {', '.join(FACETS)}; kinds are catalog "
            f"kinds ({', '.join(kind.value for kind in DefinitionKind)}); limit is 1 to 100 "
            "and offset is 0 or more",
        ) from None


def register_selection_tools(
    server: FastMCP,
    selection: ScopedSelection,
    principals: PrincipalResolver,
    *,
    call: Any,
) -> None:
    """The two read-only tools; ``call`` wraps results in the MCP envelope."""

    @server.tool(name=SEARCH_TOOL, annotations={"readOnlyHint": True})
    async def mission_search(
        context: Context,
        query: str | None = None,
        facets: list[str] | None = None,
        kinds: list[str] | None = None,
        lane_profile: str | None = None,
        limit: int = 20,
        offset: int = 0,
        include_lowered: bool = False,
    ) -> dict[str, object]:
        """Search or list what a mission selects or starts from. With `query`, one ranked
        answer; without it, a listing by name (`limit`, `offset`, `total`). `facets`:
        capability, lane (harness), model, sandbox_profile, workflow_type, template. `kinds`:
        catalog kinds for the capability facet (skill, mcp_server, hook_script ...).
        `lane_profile` narrows capabilities and models to that lane. `include_lowered` adds
        per-manifest definitions. A hit's `ref` is what a draft pins and mission_describe
        reads."""

        async def invoke(principal: Any) -> object:
            values: dict[str, object] = {"query": query or "", "limit": limit, "offset": offset}
            if facets:
                values["facets"] = facets
            if kinds:
                values["kinds"] = kinds
            if lane_profile is not None:
                values["lane_profile"] = lane_profile
            if include_lowered:
                values["include_lowered"] = True
            return await selection.search(principal, search_request(values))

        return await call(context, principals, invoke)

    @server.tool(name=CHECK_TOOL, annotations={"readOnlyHint": True})
    async def selection_check(
        draft: Annotated[dict[str, object], ShapeOf(SelectionDraft)], context: Context
    ) -> dict[str, object]:
        """Check a draft selection before writing the manifest: lane_profile, model_profile,
        family, optional data_class, capabilities (pins), sandbox_profile (a bound profile's
        name or a pin) and workflow_type (pin). Returns admissible, typed refusals with draft
        pointers and what was not checked (compile, serving, preflight). Never launches."""

        async def invoke(principal: Any) -> object:
            return await selection.check(principal, SelectionDraft.model_validate(draft))

        return await call(context, principals, invoke)


__all__ = [
    "CHECK_TOOL",
    "SEARCH_TOOL",
    "ScopedSelection",
    "register_selection_tools",
    "search_request",
]
