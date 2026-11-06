"""Selection Workspace tools on the coordinator and operator MCP servers.

- tool `mission_search(query, facets, lane_profile, limit)` (read-only; `catalog.read`): one
  ranked answer over capabilities, lanes, models, sandbox profiles and Workflow Types, as
  `POST /selection/search` returns it.
- tool `selection_check(draft)` (read-only; `catalog.read`): whether a draft selection would be
  admitted, with typed refusals and what was not checked, as `POST /selection/check`.

The principal's canonical request scope selects the tenant's workspace; neither tool launches.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastmcp import Context, FastMCP

from mission_control.application.selection.workspace import (
    SelectionDraft,
    SelectionSearchRequest,
    SelectionWorkspace,
)
from mission_control.domain.coordinator.errors import CoordinatorDomainError, CoordinatorErrorCode
from mission_control.interfaces.mcp.mission_tools import (
    MissionToolPrincipal,
    PrincipalResolver,
    scope_of,
)

SEARCH_TOOL = "mission_search"
CHECK_TOOL = "selection_check"
# The coordinator principal's `catalog.read`, or the HTTP-shaped `catalog:read` an operator
# token carries.
READ_GRANTS = frozenset({"catalog.read", "catalog:read"})


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
        query: str,
        context: Context,
        facets: list[str] | None = None,
        lane_profile: str | None = None,
        limit: int = 20,
    ) -> dict[str, object]:
        """Search capabilities, lanes (harnesses), models, sandbox profiles and Workflow Types
        at once. Each hit carries the ref a draft pins and why it matched; facets: capability,
        lane, model, sandbox_profile, workflow_type. `lane_profile` narrows capabilities and
        models to that lane."""

        async def invoke(principal: Any) -> object:
            values: dict[str, object] = {"query": query, "limit": limit}
            if facets:
                values["facets"] = facets
            if lane_profile is not None:
                values["lane_profile"] = lane_profile
            return await selection.search(principal, SelectionSearchRequest.model_validate(values))

        return await call(context, principals, invoke)

    @server.tool(name=CHECK_TOOL, annotations={"readOnlyHint": True})
    async def selection_check(draft: dict[str, object], context: Context) -> dict[str, object]:
        """Check a draft selection before writing the manifest: lane_profile, model_profile,
        family, optional data_class, capabilities (pins), sandbox_profile (pin) and
        workflow_type (pin). Returns admissible, typed refusals with draft pointers and what
        was not checked (compile, serving, preflight). Never launches."""

        async def invoke(principal: Any) -> object:
            return await selection.check(principal, SelectionDraft.model_validate(draft))

        return await call(context, principals, invoke)


__all__ = ["CHECK_TOOL", "SEARCH_TOOL", "ScopedSelection", "register_selection_tools"]
