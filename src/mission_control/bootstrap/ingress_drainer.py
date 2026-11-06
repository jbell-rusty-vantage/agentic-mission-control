"""Worker ingress composition over existing scoped manifest and frame services.

Requires a separate claim pool. Trusted manifests and grants are deployment inputs;
no request may select a filesystem path, actor, provider route or runtime pool.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg

from mission_control.adapters.auth.jwt import ApplicationAuthentication
from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.ingress_drainer import (
    PostgresIngressDrainStore,
    PostgresUploadAuthority,
)
from mission_control.adapters.postgres.lanes.execution_state import PostgresLaneExecutionStateStore
from mission_control.adapters.postgres.run_control.canonical import SCOPE, begin
from mission_control.application.authoring.manifest_service import MissionManifestService
from mission_control.application.authoring.manifest_submit import ManifestSubmitService
from mission_control.application.frames.writer import FrameWriter
from mission_control.application.signals.drainer import (
    DrainDeferred,
    DrainItem,
    DrainRejected,
    IngressDrainer,
    write_signal,
)
from mission_control.application.signals.launch import RemoteMissionLauncher, ResolvedLaunch
from mission_control.contracts.identities import (
    mission_operation_id,
    mission_root_id,
    parse_request_scope,
)
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.history_reconciliation import HistoryDeferred, HistoryRequest
from mission_control.domain.execution.lanes import CursorExecutionBinding
from mission_control.domain.policies.contracts import ActorContext


class ProductionLaunchResolver:
    def __init__(
        self,
        pool: asyncpg.Pool,
        authentication: ApplicationAuthentication,
        services: Mapping[str, MissionManifestService],
        manifests: Mapping[str, str],
    ) -> None:
        self._pool, self._authentication = pool, authentication
        self._services, self._manifests = services, manifests

    async def resolve(self, item: DrainItem) -> ResolvedLaunch:
        if item.request_scope is None or not item.credential_ref.startswith("credential:"):
            raise DrainRejected("invalid_launch_credential")
        scope = parse_request_scope(item.request_scope)
        binding = self._authentication.binding
        if (
            scope.installation_id != binding.installation_id
            or scope.application_id != binding.application_id
        ):
            raise DrainRejected("cross_scope_launch")
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, item.request_scope)
            row = await connection.fetchrow(
                f"""SELECT purpose, scopes, context, expires_at, revoked_at, created_by_actor_ref
                FROM mission_control.ingress_credential
                WHERE {SCOPE} AND credential_id=$4""",
                *args,
                UUID(item.credential_ref.removeprefix("credential:")),
            )
        if (
            row is None
            or row["purpose"] != "mission_request"
            or "mission:request" not in row["scopes"]
        ):
            raise DrainRejected("invalid_launch_credential")
        if row["revoked_at"] is not None or row["expires_at"] <= datetime.now(UTC):
            raise DrainRejected("expired_or_revoked_launch")
        context = json.loads(row["context"]) if isinstance(row["context"], str) else row["context"]
        ref = item.payload.get("manifest_ref")
        if (
            not isinstance(ref, str)
            or ref not in context.get("manifest_refs", [])
            or ref not in self._manifests
        ):
            raise DrainRejected("manifest_not_allowed")

        grant = next(
            (
                g
                for g in self._authentication.grants
                if g.actor_id == row["created_by_actor_ref"] and scope.tenant_id in g.tenant_ids
            ),
            None,
        )
        if grant is None:
            raise DrainRejected("launch_actor_grant_missing")
        service = self._services.get(item.request_scope)
        if service is None or not isinstance(service.lifecycle, ManifestSubmitService):
            raise DrainRejected("launch_service_unavailable")
        return ResolvedLaunch(
            service.lifecycle,
            ActorContext(
                actor_id=grant.actor_id,
                permissions=grant.permissions,
                authority_refs=grant.authority_refs,
            ),
            bind_remote_inputs(self._manifests[ref], item.payload.get("inputs", {})),
            grant.sponsorship_refs,
            grant.approval_refs,
        )

    async def preflight(self, launch: ResolvedLaunch) -> None:
        service = self._services[launch.lifecycle.request_scope]
        report = await service.preflight(
            launch.manifest_yaml,
            actor_id=launch.actor.actor_id,
            permissions=launch.actor.permissions,
        )
        if not report.ready:
            raise DrainRejected("launch_prerequisites_unmet")


class ProductionIngressEffects:
    def __init__(
        self,
        pool: asyncpg.Pool,
        launcher: RemoteMissionLauncher,
        client: Any,
        request_scopes: tuple[str, ...],
        artifact_custody: Any = None,
    ) -> None:
        self._pool, self._launcher = pool, launcher
        self._client, self._scopes = client, request_scopes
        self._custody = artifact_custody
        self._frames = PostgresFrameRepository(pool)
        self._states = PostgresLaneExecutionStateStore(pool)

    async def persist(self, item: DrainItem) -> Mapping[str, Any]:
        if item.kind == "mission_request":
            return await self._launcher.admit(item)
        if item.kind.startswith("webhook."):
            request = self._stored_history_request(item)
            if request is None:
                request = await self._webhook_binding(item)

                async def enqueue() -> None:
                    await self._states.request_history(request)

                raise DrainDeferred(
                    {
                        "reason": "native_history_pending",
                        "reconciliation_request": request.model_dump(mode="json"),
                    },
                    after_commit=enqueue,
                )
            try:
                journal = await self._states.request_history(request)
            except HistoryDeferred:
                raise DrainDeferred(item.outcome) from None
            except ValueError:
                raise DrainRejected("webhook_stale_generation") from None
            if not journal.covers(request):
                raise DrainDeferred(item.outcome)
            receipt = journal.receipt_for(request)
            assert receipt is not None
            return {
                "reconciliation_request": request.model_dump(mode="json"),
                "reconciliation_applied": True,
                "persisted_cursor": receipt.persisted_cursor,
            }
        if item.kind == "artifact.committed":
            if self._custody is None or item.request_scope is None or item.generation is None:
                raise DrainRejected("artifact_registration_unconfigured")
            authority = PostgresUploadAuthority(self._pool, item.request_scope)
            upload = await authority.load(item)
            service = self._custody(authority)
            address = await service.verify(
                upload, request_scope=item.request_scope, generation=item.generation
            )
            return {
                "artifact_upload_id": str(upload.upload_id),
                "digest": address.content_digest,
                "custody_state": "registered",
                "artifact_version": 1,
            }
        if item.request_scope is None or item.run_key is None or item.generation is None:
            raise DrainRejected("unbound_signal")
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, item.request_scope)
            # Resolve accepted row scope/run/unit against current persisted execution identity.
            rows = await connection.fetch(
                """SELECT h.harness_execution_id FROM mission_control.harness_execution h
                JOIN mission_control.attempt a ON a.attempt_id=h.attempt_id
                JOIN mission_control.activation n ON n.activation_id=a.activation_id
                JOIN mission_control.mission_run r ON r.run_id=h.run_id
                WHERE h.installation_id=$1 AND h.application_id=$2 AND h.tenant_id=$3
                  AND r.run_key=$4 AND n.activation_key=$5 AND h.generation=$6
                  AND h.lifecycle='live'""",
                *args,
                item.run_key,
                item.unit_key,
                item.generation,
            )
        if len(rows) != 1:
            raise DrainRejected("stale_or_ambiguous_execution")
        handle = await self._frames.existing_execution(
            item.request_scope, item.run_key, rows[0]["harness_execution_id"], item.generation
        )
        if handle is None:
            raise DrainRejected("stale_generation")
        return await write_signal(item, FrameWriter(self._frames, handle))

    def _stored_history_request(self, item: DrainItem) -> HistoryRequest | None:
        raw = item.outcome.get("reconciliation_request")
        if raw is None:
            return None
        try:
            request = HistoryRequest.model_validate(raw)
        except ValueError:
            raise DrainRejected("webhook_receipt_invalid") from None
        profiles = {
            "webhook.anthropic": "claude_managed",
            "webhook.openai": "codex_agents",
            "webhook.cursor": "cursor_cloud",
        }
        if (
            request.ingress_id != item.ingress_id
            or request.received_at != item.received_at
            or request.request_scope not in self._scopes
            or request.lane_profile != profiles.get(item.kind)
        ):
            raise DrainRejected("webhook_receipt_invalid")
        return request

    async def _webhook_binding(self, item: DrainItem) -> HistoryRequest:
        provider = item.kind.removeprefix("webhook.")
        profiles = {
            "anthropic": "claude_managed",
            "openai": "codex_agents",
            "cursor": "cursor_cloud",
        }
        if provider not in profiles:
            raise DrainRejected("webhook_route_unconfigured")
        resource = item.payload.get("resource_ref")
        if provider == "cursor":
            source = item.payload.get("source_signal", {})
            resource = source.get("data", {}).get("id") if isinstance(source, dict) else None
        if not isinstance(resource, str):
            raise DrainRejected("webhook_session_missing")
        matches = []
        for scope in self._scopes:
            async with self._pool.acquire() as connection, connection.transaction():
                args = await begin(connection, scope)
                row = await connection.fetchrow(
                    f"""SELECT session_binding_id, run_key, generation, context
                    FROM mission_control.ingress_session_binding WHERE {SCOPE}
                    AND provider=$4 AND session_id=$5 AND revoked_at IS NULL
                    AND expires_at>clock_timestamp()""",
                    *args,
                    provider,
                    resource,
                )
            if row is None:
                continue
            context = (
                json.loads(row["context"]) if isinstance(row["context"], str) else row["context"]
            )
            if context.get("product") != profiles[provider] or not context.get("pins"):
                raise DrainRejected("webhook_product_version_unbound")
            try:
                execution = UUID(context["harness_execution_id"])
                workflow = context["operation_workflow_id"]
            except (ValueError, KeyError, TypeError):
                raise DrainRejected("webhook_execution_unbound") from None
            handle = await self._frames.existing_execution(
                scope, row["run_key"], execution, row["generation"]
            )
            if (
                handle is None
                or handle.native_session_ref != resource
                or handle.lane_profile != profiles[provider]
            ):
                raise DrainRejected("webhook_stale_generation")
            if not isinstance(workflow, str) or not workflow.startswith(
                mission_root_id(scope, row["run_key"]) + "/operation/"
            ):
                raise DrainRejected("webhook_execution_unbound")
            state = await self._states.load(scope, execution)
            if state is None or state.native_session_ref != resource:
                raise DrainRejected("webhook_stale_generation")
            if state.native_turn_ref is None:
                raise DrainDeferred({"reason": "native_turn_pending"})
            matches.append(
                HistoryRequest(
                    request_scope=scope,
                    run_id=row["run_key"],
                    harness_execution_id=execution,
                    generation=row["generation"],
                    lane_profile=profiles[provider],
                    session_binding_id=row["session_binding_id"],
                    workflow_id=workflow,
                    native_session_ref=resource,
                    native_turn_ref=state.native_turn_ref,
                    ingress_id=item.ingress_id,
                    received_at=item.received_at,
                )
            )
        if len(matches) != 1:
            raise DrainRejected("webhook_session_unbound")
        return matches[0]

    async def wake(self, item: DrainItem) -> None:
        if item.kind in {"mission_request", "artifact.committed"}:
            return  # Normal manifest start already uses governed Temporal admission.
        if item.kind.startswith("webhook."):
            request = self._stored_history_request(item)
            if request is None:
                raise DrainRejected("webhook_receipt_missing")
            state = await self._states.load(request.request_scope, request.harness_execution_id)
            if (
                state is None
                or state.history_reconciliation is None
                or not state.history_reconciliation.covers(request)
            ):
                raise DrainDeferred(item.outcome)
            workflow = request.workflow_id
        else:
            if item.request_scope is None or item.run_key is None:
                raise DrainRejected("unbound_signal")
            async with self._pool.acquire() as connection, connection.transaction():
                args = await begin(connection, item.request_scope)
                rows = await connection.fetch(
                    f"""SELECT semantic_attempt_key
                    FROM mission_control.operation_claim WHERE {SCOPE}
                    AND run_key=$4 AND unit_key=$5
                    AND status IN ('claimed','executing','reconciliation_required')""",
                    *args,
                    item.run_key,
                    item.unit_key,
                )
            if len(rows) != 1:
                raise DrainRejected("operation_wake_unbound")
            workflow = mission_operation_id(
                item.request_scope, item.run_key, rows[0]["semantic_attempt_key"]
            )
        # Pure hint: the operation resumes its ordinary persisted/native reconciliation.
        await self._client.get_workflow_handle(workflow).signal(
            "ingress_wake", str(item.ingress_id)
        )


def compose_ingress_drainer(
    *,
    claim_pool: asyncpg.Pool,
    runtime_pool: asyncpg.Pool,
    request_scope: str,
    authentication: ApplicationAuthentication,
    manifest_services: Mapping[str, MissionManifestService],
    manifests: Mapping[str, str],
    temporal_client: Any,
    artifact_custody: Any = None,
) -> IngressDrainer:
    if claim_pool is runtime_pool:
        raise ValueError("ingress claims require a separate pool from runtime effects")
    resolver = ProductionLaunchResolver(runtime_pool, authentication, manifest_services, manifests)
    return IngressDrainer(
        PostgresIngressDrainStore(claim_pool, request_scope),
        ProductionIngressEffects(
            runtime_pool,
            RemoteMissionLauncher(resolver),
            temporal_client,
            tuple(manifest_services),
            artifact_custody,
        ),
    )


class ProductionSessionRegistrar:
    """Registers hosted native sessions from the admitted operation, never webhook fields."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def __call__(
        self, operation: Any, identity: Any, generation: int, native_session_ref: str
    ) -> None:
        from datetime import timedelta
        from uuid import NAMESPACE_URL, uuid5

        from mission_control.adapters.postgres.ingress import PostgresSessionBindings
        from mission_control.application.signals.contracts import TrustTier
        from mission_control.application.signals.ports import SessionBinding

        profile = identity.lane_profile
        providers = {
            "claude_managed": "anthropic",
            "codex_agents": "openai",
            "cursor_cloud": "cursor",
        }
        provider = providers.get(profile)
        if provider is None:
            return
        binding = ProviderExecutionBinding.carried_by(
            operation
        ) or CursorExecutionBinding.carried_by(operation)
        if binding is None or not binding.pins:
            raise ValueError("hosted session registration requires exact provider pins")
        context = {
            "product": profile,
            "pins": dict(binding.pins),
            "binding_digest": binding.binding_digest,
            "harness_execution_id": str(identity.harness_execution_id),
            "operation_workflow_id": mission_operation_id(
                identity.request_scope, identity.run_key, operation.identity.semantic_key
            ),
        }
        record = SessionBinding(
            request_scope=identity.request_scope,
            tier=TrustTier.PROVIDER_OIDC,
            provider=provider,
            run_key=identity.run_key,
            unit_key=identity.activation_key,
            generation=generation,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            session_id=native_session_ref,
            context=context,
        )
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, identity.request_scope)
            prior = await connection.fetchrow(
                f"""SELECT run_key, unit_key, generation, context
                FROM mission_control.ingress_session_binding WHERE {SCOPE}
                AND provider=$4 AND session_id=$5 AND revoked_at IS NULL""",
                *args,
                provider,
                native_session_ref,
            )
        if prior is not None:
            data = (
                json.loads(prior["context"])
                if isinstance(prior["context"], str)
                else prior["context"]
            )
            if (prior["run_key"], prior["unit_key"], prior["generation"], data) != (
                identity.run_key,
                identity.activation_key,
                generation,
                context,
            ):
                raise ValueError("native session already belongs to a different execution binding")
            return
        await PostgresSessionBindings(self._pool).register(
            record,
            uuid5(NAMESPACE_URL, f"{identity.request_scope}/{provider}/{native_session_ref}"),
        )


def bind_remote_inputs(manifest_yaml: str, inputs: Mapping[str, Any]) -> str:
    """Only declared root literal input slots can receive remote values.

    References, artifacts, schema pins, capabilities and nested program nodes are preserved.
    Chains require explicit per-mission authoring; ambiguous name broadcast is refused.
    """
    if not inputs:
        return manifest_yaml
    from mission_control.domain.authoring.manifest import (
        canonical_manifest_bytes,
        load_manifest_yaml,
    )
    from mission_control.domain.authoring.manifest_v2 import parse_manifest_any

    document = load_manifest_yaml(manifest_yaml)
    mission = document.get("mission")
    if not isinstance(mission, dict):
        raise DrainRejected("remote_chain_inputs_ambiguous")
    program = mission.get("program", {})
    slots = program.get("inputs", []) if isinstance(program, dict) else []
    declared = {slot.get("name"): slot for slot in slots if isinstance(slot, dict)}
    for name, value in inputs.items():
        slot = declared.get(name)
        if slot is None or "value" not in slot or "from" in slot or "artifact" in slot:
            raise DrainRejected("remote_input_not_declared")
        slot["value"] = value
    parse_manifest_any(document)
    return canonical_manifest_bytes(document).decode("utf-8")
