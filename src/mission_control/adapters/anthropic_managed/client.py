"""Anthropic Managed Agents client: agents, environments, skills, vaults, sessions and events.

A thin `httpx.AsyncClient` adapter over the resources `claude_managed` prepare creates once and
reuses by id (SPEC-06 section 4.1), and over the sessions and session events the lane drives
(section 4.2). Paths, headers and bodies follow the pinned `anthropic` 1.13.0 source and the
shapes HL-23 sent live (research/provider-smoke-2026-10.md section 2.1):

- Managed Agents endpoints (`/v1/agents`, `/v1/environments`, `/v1/vaults` and credentials)
  carry `anthropic-beta: managed-agents-2026-04-01` and the SDK's `?beta=true` query;
- the Skills API (`/v1/skills`) is a stable namespace with no beta header; a skill is created
  from a multipart upload of `files[]` (each `<dir>/<path>`) plus `display_name`;
- lists page with an opaque `page` cursor answered by `next_page`;
- agents are updated with an optional optimistic `version` (a mismatch is `409`), archived and
  never deleted; environments, skills, vaults and credentials are deleted;
- session events carry an `id` and a `processed_at`, but no sequence number and no
  `created_at`: the event list is ordered by `processed_at`, its `created_at[...]` filters
  compare against `processed_at`, and array filters use brackets (`types[]`) as the SDK's
  query string does; the SSE stream (`/events/stream`) delivers only events after it connects
  and has no `Last-Event-ID` resume.

No create takes an idempotency key, so this client never retries: prepare reconciles a lost
create by listing and matching metadata (or, for skills, the display name). Errors map through
the Remote Session Lane base's typed table (ADR-0052); messages name the operation and status
only, never the API key, a request body or provider prose.

Tests drive it through `httpx.MockTransport`; nothing here calls the network by itself.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, Final

import httpx
from pydantic import SecretStr

from mission_control.adapters.remote_session.errors import (
    STANDARD_ERROR_RULES,
    ErrorRule,
    RemoteSessionError,
    raise_for_response,
)
from mission_control.adapters.remote_session.sse import SseEvent
from mission_control.adapters.remote_session.stream import StreamOpened, open_event_stream

API_BASE: Final = "https://api.anthropic.com"
API_VERSION: Final = "2023-06-01"
MANAGED_AGENTS_BETA: Final = "managed-agents-2026-04-01"

JsonObject = dict[str, Any]


class ManagedAgentsError(RemoteSessionError):
    """The Managed Agents API refused a control-plane request."""


class AgentVersionConflict(ManagedAgentsError):
    """`409` on an agent update: its `version` moved since it was read (another writer)."""


MANAGED_AGENTS_ERRORS: Final[tuple[ErrorRule, ...]] = STANDARD_ERROR_RULES
_AGENT_UPDATE_ERRORS: Final[tuple[ErrorRule, ...]] = (
    ErrorRule(409, AgentVersionConflict, "the agent version changed since it was read"),
    *MANAGED_AGENTS_ERRORS,
)


def _raise(
    response: httpx.Response,
    operation: str,
    rules: Sequence[ErrorRule] = MANAGED_AGENTS_ERRORS,
) -> None:
    raise_for_response(response, operation, rules, fallback=ManagedAgentsError)


def _object(response: httpx.Response) -> JsonObject:
    body = response.json()
    if not isinstance(body, dict):
        raise ManagedAgentsError(
            f"{response.request.method} {response.request.url.path}: not an object"
        )
    return body


class ManagedAgentsClient:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        base_url: str = API_BASE,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 60,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"x-api-key": api_key.get_secret_value(), "anthropic-version": API_VERSION},
            transport=transport,
            timeout=timeout_s,
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- agents -----------------------------------------------------------------------------------

    async def list_agents(self) -> list[JsonObject]:
        return await self._list("/v1/agents", "list agents")

    async def retrieve_agent(self, agent_id: str) -> JsonObject:
        return await self._beta("GET", f"/v1/agents/{agent_id}", "retrieve agent")

    async def create_agent(self, body: Mapping[str, Any]) -> JsonObject:
        return await self._beta("POST", "/v1/agents", "create agent", body)

    async def update_agent(self, agent_id: str, body: Mapping[str, Any]) -> JsonObject:
        """A full replacement of the given fields; `body["version"]` makes it optimistic."""

        return await self._beta(
            "POST", f"/v1/agents/{agent_id}", "update agent", body, rules=_AGENT_UPDATE_ERRORS
        )

    async def archive_agent(self, agent_id: str) -> JsonObject:
        return await self._beta("POST", f"/v1/agents/{agent_id}/archive", "archive agent")

    # -- environments -----------------------------------------------------------------------------

    async def list_environments(self) -> list[JsonObject]:
        return await self._list("/v1/environments", "list environments")

    async def retrieve_environment(self, environment_id: str) -> JsonObject:
        return await self._beta("GET", f"/v1/environments/{environment_id}", "retrieve environment")

    async def create_environment(self, body: Mapping[str, Any]) -> JsonObject:
        return await self._beta("POST", "/v1/environments", "create environment", body)

    async def delete_environment(self, environment_id: str) -> None:
        await self._beta("DELETE", f"/v1/environments/{environment_id}", "delete environment")

    # -- skills (stable namespace, no beta header) ------------------------------------------------

    async def list_skills(self) -> list[JsonObject]:
        return await self._list(
            "/v1/skills", "list skills", beta=False, params={"source": "custom"}
        )

    async def retrieve_skill(self, skill_id: str) -> JsonObject:
        response = await self._client.get(f"/v1/skills/{skill_id}")
        _raise(response, "retrieve skill")
        return _object(response)

    async def create_skill(
        self, display_name: str, files: Sequence[tuple[str, bytes]]
    ) -> JsonObject:
        """Upload one skill directory: `files` are `(<dir>/<relative path>, content)` pairs."""

        response = await self._client.post(
            "/v1/skills",
            data={"display_name": display_name},
            files=[("files[]", (path, content, _media_type(path))) for path, content in files],
        )
        _raise(response, "create skill")
        return _object(response)

    async def delete_skill(self, skill_id: str) -> None:
        response = await self._client.delete(f"/v1/skills/{skill_id}")
        _raise(response, "delete skill")

    # -- vaults and credentials -------------------------------------------------------------------

    async def list_vaults(self) -> list[JsonObject]:
        return await self._list("/v1/vaults", "list vaults")

    async def retrieve_vault(self, vault_id: str) -> JsonObject:
        return await self._beta("GET", f"/v1/vaults/{vault_id}", "retrieve vault")

    async def create_vault(self, body: Mapping[str, Any]) -> JsonObject:
        return await self._beta("POST", "/v1/vaults", "create vault", body)

    async def delete_vault(self, vault_id: str) -> None:
        await self._beta("DELETE", f"/v1/vaults/{vault_id}", "delete vault")

    async def list_credentials(self, vault_id: str) -> list[JsonObject]:
        return await self._list(f"/v1/vaults/{vault_id}/credentials", "list credentials")

    async def retrieve_credential(self, vault_id: str, credential_id: str) -> JsonObject:
        return await self._beta(
            "GET", f"/v1/vaults/{vault_id}/credentials/{credential_id}", "retrieve credential"
        )

    async def validate_mcp_oauth(self, vault_id: str, credential_id: str) -> JsonObject:
        return await self._beta(
            "POST",
            f"/v1/vaults/{vault_id}/credentials/{credential_id}/mcp_oauth_validate",
            "validate MCP OAuth",
        )

    async def create_credential(self, vault_id: str, body: Mapping[str, Any]) -> JsonObject:
        return await self._beta(
            "POST", f"/v1/vaults/{vault_id}/credentials", "create credential", body
        )

    async def update_credential(
        self, vault_id: str, credential_id: str, body: Mapping[str, Any]
    ) -> JsonObject:
        return await self._beta(
            "POST",
            f"/v1/vaults/{vault_id}/credentials/{credential_id}",
            "update credential",
            body,
        )

    async def delete_credential(self, vault_id: str, credential_id: str) -> None:
        await self._beta(
            "DELETE", f"/v1/vaults/{vault_id}/credentials/{credential_id}", "delete credential"
        )

    # -- sessions ---------------------------------------------------------------------------------

    async def create_session(self, body: Mapping[str, Any]) -> JsonObject:
        return await self._beta("POST", "/v1/sessions", "create session", body)

    async def list_sessions(self, *, agent_id: str) -> list[JsonObject]:
        """The agent's sessions, archived ones included (a reconciled create may be one)."""

        return await self._list(
            "/v1/sessions",
            "list sessions",
            params={"agent_id": agent_id, "include_archived": "true"},
        )

    async def retrieve_session(self, session_id: str) -> JsonObject:
        return await self._beta("GET", f"/v1/sessions/{session_id}", "retrieve session")

    async def update_session(self, session_id: str, body: Mapping[str, Any]) -> JsonObject:
        return await self._beta("POST", f"/v1/sessions/{session_id}", "update session", body)

    async def archive_session(self, session_id: str) -> JsonObject:
        return await self._beta("POST", f"/v1/sessions/{session_id}/archive", "archive session")

    async def delete_session(self, session_id: str) -> None:
        await self._beta("DELETE", f"/v1/sessions/{session_id}", "delete session")

    async def session_files(self, session_id: str) -> list[JsonObject]:
        result: list[JsonObject] = []
        query = {"scope_id": session_id, "beta": "true", "limit": "100"}
        while True:
            response = await self._client.get(
                "/v1/files",
                params=query,
                headers={"anthropic-beta": f"files-api-2025-04-14,{MANAGED_AGENTS_BETA}"},
            )
            _raise(response, "list session files")
            page = _object(response)
            result.extend(item for item in page.get("data") or [] if isinstance(item, dict))
            if not page.get("has_more"):
                return result
            cursor = page.get("last_id")
            if not isinstance(cursor, str) or not cursor or cursor == query.get("after_id"):
                raise ValueError("session files returned an invalid page cursor")
            query["after_id"] = cursor

    async def download_file(self, file_id: str, *, max_bytes: int = 32 * 1024 * 1024) -> bytes:
        content = bytearray()
        async with self._client.stream(
            "GET",
            f"/v1/files/{file_id}/content",
            params={"beta": "true"},
            headers={"anthropic-beta": f"files-api-2025-04-14,{MANAGED_AGENTS_BETA}"},
        ) as response:
            if not response.is_success:
                await response.aread()
                _raise(response, "download session file")
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise ValueError("session file exceeds the custody size limit")
        return bytes(content)

    async def delete_file(self, file_id: str) -> None:
        response = await self._client.delete(
            f"/v1/files/{file_id}",
            params={"beta": "true"},
            headers={"anthropic-beta": f"files-api-2025-04-14,{MANAGED_AGENTS_BETA}"},
        )
        _raise(response, "delete session file")

    # -- session events ---------------------------------------------------------------------------

    async def send_events(
        self, session_id: str, events: Sequence[Mapping[str, Any]]
    ) -> list[JsonObject]:
        """Send events in order; returns the provider's echo of each (with its `id`)."""

        sent = await self._beta(
            "POST",
            f"/v1/sessions/{session_id}/events",
            "send session events",
            {"events": [dict(event) for event in events]},
        )
        return [item for item in sent.get("data") or () if isinstance(item, dict)]

    def list_events(
        self,
        session_id: str,
        *,
        types: Sequence[str] = (),
        processed_from: str | None = None,
        processed_before: str | None = None,
        newest_first: bool = False,
        limit: int | None = None,
    ) -> AsyncIterator[JsonObject]:
        """The session's persisted events in `processed_at` order: from `processed_from`
        (inclusive) and before `processed_before` (exclusive) when given; `limit` reads one
        page of at most that many."""

        params: dict[str, Any] = {"order": "desc" if newest_first else "asc"}
        if types:
            params["types[]"] = list(types)
        if processed_from is not None:
            params["created_at[gte]"] = processed_from
        if processed_before is not None:
            params["created_at[lt]"] = processed_before
        if limit is not None:
            params["limit"] = str(limit)
        return self._pages(
            f"/v1/sessions/{session_id}/events",
            "list session events",
            beta=True,
            params=params,
            single_page=limit is not None,
        )

    def stream_events(self, session_id: str) -> AsyncIterator[SseEvent | StreamOpened]:
        """The live session stream, led by the `StreamOpened` marker."""

        return open_event_stream(
            self._client,
            f"/v1/sessions/{session_id}/events/stream",
            operation="stream session events",
            rules=MANAGED_AGENTS_ERRORS,
            fallback=ManagedAgentsError,
            params={"beta": "true"},
            headers={"anthropic-beta": MANAGED_AGENTS_BETA},
        )

    # -- transport --------------------------------------------------------------------------------

    async def _beta(
        self,
        method: str,
        path: str,
        operation: str,
        body: Mapping[str, Any] | None = None,
        *,
        rules: Sequence[ErrorRule] = MANAGED_AGENTS_ERRORS,
    ) -> JsonObject:
        response = await self._client.request(
            method,
            path,
            params={"beta": "true"},
            headers={"anthropic-beta": MANAGED_AGENTS_BETA},
            json=dict(body) if body is not None else None,
        )
        _raise(response, operation, rules)
        return _object(response) if response.content else {}

    async def _pages(
        self,
        path: str,
        operation: str,
        *,
        beta: bool,
        params: Mapping[str, Any],
        single_page: bool = False,
    ) -> AsyncIterator[JsonObject]:
        query = {**params, **({"beta": "true"} if beta else {})}
        headers = {"anthropic-beta": MANAGED_AGENTS_BETA} if beta else None
        while True:
            response = await self._client.get(path, params=query, headers=headers)
            _raise(response, operation)
            page = _object(response)
            for item in page.get("data") or ():
                if isinstance(item, dict):
                    yield item
            next_page = page.get("next_page")
            if single_page or not next_page:
                return
            query = {**query, "page": str(next_page)}

    async def _list(
        self,
        path: str,
        operation: str,
        *,
        beta: bool = True,
        params: Mapping[str, str] | None = None,
    ) -> list[JsonObject]:
        return [item async for item in self._pages(path, operation, beta=beta, params=params or {})]


def _media_type(path: str) -> str:
    return "text/markdown" if path.endswith(".md") else "application/octet-stream"


__all__ = [
    "API_BASE",
    "API_VERSION",
    "MANAGED_AGENTS_BETA",
    "MANAGED_AGENTS_ERRORS",
    "AgentVersionConflict",
    "JsonObject",
    "ManagedAgentsClient",
    "ManagedAgentsError",
]
