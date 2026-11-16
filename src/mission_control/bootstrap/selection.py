"""Composition of the Selection Workspace (`application/selection/workspace.py`).

The workspace reads what the API process already holds for one application: the describe-only
Lane Registry (`bootstrap/lanes.describe_only_registry`), the Model Catalog
(`deployments/<app>/models.toml`), the Application Profile (`deployments/<app>/application.toml`)
and the tenant's catalog service. Its admission is the resolution seam's own
`RuntimeResolver.admit` over those registries, so a check answers exactly as the seam would at
steps 1 and 2. Nothing here compiles a lane. Beside the catalog it hands the workspace the
curated mission templates (`application/guide/mission_templates.py`) and the sandbox profiles
the deployment's launch bindings bind.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mission_control.adapters.deep_agents.compile import deep_agents_lane
from mission_control.adapters.deep_agents.describe import SANDBOX_BACKEND_FACTS
from mission_control.application.authoring.manifest_launch_inputs import ManifestLaunchBindings
from mission_control.application.capabilities.catalog import CatalogService
from mission_control.application.guide.mission_templates import mission_templates
from mission_control.application.resolution.registries import (
    ApplicationRegistry,
    LaneRegistry,
    ModelCatalog,
)
from mission_control.application.resolution.resolver import RuntimeResolver
from mission_control.application.selection.workspace import (
    SANDBOX_REF_PREFIX,
    SelectionWorkspace,
    WorkspaceEntry,
)
from mission_control.bootstrap.application_profiles import compose_application_registry
from mission_control.bootstrap.lanes import (
    SESSION_LANES,
    describe_only_registry,
    settings_bound_lanes,
)
from mission_control.bootstrap.model_profiles import compose_model_catalog
from mission_control.bootstrap.settings import Settings


def bound_sandbox_profiles(settings: Settings) -> dict[str, str] | None:
    """The sandbox profiles this deployment's launch bindings bind, name -> one line: the
    names a manifest writes in `environment.sandbox.profile`, which the Deep Agents lane
    resolves against the same file at launch. `None` where the process reads no launch
    bindings (it launches nothing, so it cannot say which profiles are bound)."""

    details = bound_sandbox_details(settings)
    if details is None:
        return None
    return {name: str(facts["summary"]) for name, facts in details.items()}


def bound_sandbox_details(settings: Settings) -> dict[str, dict[str, Any]] | None:
    """Each bound sandbox profile as its launch binding declares it, name -> facts: the
    backend and what that backend gives a node (`SANDBOX_BACKEND_FACTS`), the idle lifetime,
    the pinned sandbox definition, the secrets it names, and the other profiles that bind the
    same sandbox. `summary` is the one line the listings show. `None` where the process reads
    no launch bindings."""

    path = settings.manifest_launch_bindings_path
    if path is None:
        return None
    try:
        bindings = ManifestLaunchBindings.load(path)
    except ValueError:
        # The launch composition reports an unreadable bindings file; the guide does not.
        return None
    components = dict(sorted(bindings.sandbox_profiles.items()))
    details: dict[str, dict[str, Any]] = {}
    for name, component in components.items():
        backend = SANDBOX_BACKEND_FACTS.get(component.backend, {})
        twins = [
            other
            for other, twin in components.items()
            if other != name
            and (twin.ref.digest, twin.backend, twin.runtime_digest, twin.snapshot_ref)
            == (
                component.ref.digest,
                component.backend,
                component.runtime_digest,
                component.snapshot_ref,
            )
        ]
        definition = f"{component.ref.logical_id}@{component.ref.revision}"
        summary = (
            f"`{component.backend}` backend: {backend.get('suits', 'see its describe')}; "
            f"execution: {backend.get('execution', 'undeclared')}; network: "
            f"{backend.get('network', 'undeclared')}"
        )
        if twins:
            summary += f"; binds the same sandbox as {', '.join(f'`{twin}`' for twin in twins)}"
        details[name] = {
            "summary": summary,
            "backend": component.backend,
            **{key: backend[key] for key in ("execution", "network", "files", "suits") if backend},
            "idle_ttl_seconds": component.idle_ttl_seconds,
            "definition": definition,
            "definition_digest": component.ref.digest,
            "runtime_digest": component.runtime_digest,
            "starts_from_snapshot": component.snapshot_ref is not None,
            "secret_names": [str(ref.key) for ref in component.credential_refs],
            "same_binding_as": twins,
        }
    return details


def compose_selection_workspace(
    *,
    application_id: str,
    lanes: LaneRegistry,
    models: ModelCatalog,
    applications: ApplicationRegistry,
    catalog: CatalogService | None,
    sandbox_profiles: Mapping[str, str] | None = None,
) -> SelectionWorkspace:
    """One application's workspace over registries the caller composed (fails closed on none).
    It lists the curated mission templates and the deployment's bound sandbox profiles
    (`bound_sandbox_profiles`) beside the catalog."""

    return SelectionWorkspace(
        application_id=application_id,
        lanes=lanes,
        models=models,
        applications=applications,
        admission=RuntimeResolver(
            lanes, applications, models, allow_unqualified_lanes=lanes.allow_unqualified
        ),
        catalog_scope=catalog.catalog_scope if catalog is not None else None,
        search=catalog.search if catalog is not None else None,
        definitions=catalog.definitions if catalog is not None else None,
        templates=tuple(
            WorkspaceEntry(ref=template.ref, title=template.title, summary=template.purpose)
            for template in mission_templates()
        ),
        sandbox_profiles=tuple(
            WorkspaceEntry(ref=f"{SANDBOX_REF_PREFIX}{name}", title=name, summary=summary)
            for name, summary in (sandbox_profiles or {}).items()
        ),
    )


def compose_settings_selection_workspace(
    settings: Settings, application_id: str, catalog: CatalogService | None
) -> SelectionWorkspace:
    """The same workspace from process settings, for a process without the API's registries
    (the development coordinator MCP server). It mirrors the API's lane composition: the bound
    lanes describe-only, each with its package registration."""

    return compose_selection_workspace(
        application_id=application_id,
        lanes=describe_only_registry(
            bound=settings_bound_lanes(settings),
            allow_unqualified=settings.allow_unqualified_lanes,
            registrations=(deep_agents_lane(None), *SESSION_LANES.values()),
        ),
        models=compose_model_catalog(settings.deployments_root, application_id),
        applications=compose_application_registry(settings.deployments_root, (application_id,)),
        catalog=catalog,
        sandbox_profiles=bound_sandbox_profiles(settings),
    )


__all__ = [
    "bound_sandbox_details",
    "bound_sandbox_profiles",
    "compose_selection_workspace",
    "compose_settings_selection_workspace",
]
