"""Reviewed inline hosted configuration plus exact catalog projection, without pack file I/O."""

from __future__ import annotations

import base64
import copy
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from mission_control.adapters.anthropic_managed.pack import (
    ClaudeManagedPack,
    RenderedPack,
    render_pack,
)
from mission_control.adapters.anthropic_managed.pack import (
    McpServer as ManagedMcp,
)
from mission_control.adapters.capabilities.capability_bundles import bundle_digest
from mission_control.adapters.openai_agents.pack import (
    CodexAgentsPack,
    InlineBundle,
    PackDocument,
)
from mission_control.adapters.openai_agents.pack import (
    McpServer as AgentsMcp,
)
from mission_control.adapters.remote_session.host_files import HOST_FILES
from mission_control.application.agentic_components.projections import HostProjectors
from mission_control.application.environments.network import (
    NetworkEnforcement,
    project_network_policy,
)
from mission_control.application.secrets.references import declarations
from mission_control.domain.agentic_components.projection import ResolvedCapability
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.bindings import EnvironmentBinding


def configuration(pack: RenderedPack | CodexAgentsPack) -> dict[str, Any]:
    """Migration helper: serialize an already reviewed pack; unchanged bytes keep resource keys."""
    if isinstance(pack, RenderedPack):
        value = pack.pack.model_dump(mode="json", by_alias=True, exclude={"root", "skill_files"})
        value["skill_files"] = {
            name: [[path, base64.b64encode(content).decode()] for path, content in files]
            for name, files in pack.pack.skill_files.items()
        }
        # Repository rules are already in custody in the rendered system.
        value["rendered_environment_config"] = dict(pack.environment_config)
        value["system_overlay"] = pack.system
        value["agent"]["repository_instructions"] = None
        return value
    return {
        "document": pack.document.model_dump(mode="json"),
        "instructions": pack.instructions,
        "skills": [_bundle_config(item) for item in pack.skills],
        "plugins": [_bundle_config(item) for item in pack.plugins],
    }


def _bundle_config(item: InlineBundle) -> dict[str, Any]:
    return {
        "name": item.name,
        "description": item.description,
        "digest": item.digest,
        "top_directory": item.top_directory,
        "files": [[path, base64.b64encode(body).decode()] for path, body in item.files],
    }


def _files(items: Any) -> tuple[tuple[str, bytes], ...]:
    return tuple((path, base64.b64decode(body, validate=True)) for path, body in items)


def project(
    profile: str,
    config: dict[str, Any],
    rows: tuple[ResolvedCapability, ...],
    *,
    installation_id: str,
    environment: EnvironmentBinding | None = None,
) -> RenderedPack | CodexAgentsPack:
    """Use the MO-30 targets, then the existing renderer's exact digest algorithms."""
    if re.search(r"sk-(?:ant-|proj-|admin-)[A-Za-z0-9_-]{8,}", json.dumps(config)):
        raise ValueError("hosted configuration contains an organization API key")
    selected_secrets = declarations(environment.secret_refs) if environment is not None else ()
    for declaration in selected_secrets:
        if declaration.ref.scheme == "mint":
            raise ValueError(
                "hosted signals use worker-only credentials; sandbox mint declarations unsupported"
            )
        reserved = {
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GITHUB_APP_PRIVATE_KEY",
        }
        if declaration.name.upper() in reserved or declaration.ref.key.upper() in reserved:
            raise ValueError("organization and publication credentials cannot enter a hosted vault")
    config = copy.deepcopy(config)
    if environment is not None and environment.network is not None:
        network = project_network_policy(profile, environment.network)
        if network.enforcement is NetworkEnforcement.UNSUPPORTED:
            raise ValueError("hosted network policy cannot be enforced")
        if profile == "claude_managed":
            if "rendered_environment_config" not in config:
                raise ValueError(
                    "hosted projection requires the reviewed rendered environment snapshot"
                )
            config["rendered_environment_config"]["networking"] = network.settings["networking"]
        else:
            config["document"]["environment"]["network"] = network.settings["network"]
    projection = HostProjectors(HOST_FILES).render(rows, profile, "", telemetry=False)
    if projection.report.skipped_members:
        raise ValueError(
            "hosted capability projection omitted selected behavior: "
            + ", ".join(projection.report.skipped_members)
        )
    skills = projection.send_options.get("hosted_skills", [])
    servers = projection.send_options.get("hosted_mcp_servers", [])
    assert isinstance(skills, list) and isinstance(servers, list)
    if profile == "claude_managed":
        value = dict(config)
        environment_config = value.pop("rendered_environment_config", None)
        if environment_config is not None:
            value["environment"] = {
                **value["environment"],
                "networking": {
                    **value["environment"]["networking"],
                    "include_signal_ingress": False,
                    "allowed_hosts": environment_config["networking"].get(
                        "allowed_hosts", value["environment"]["networking"]["allowed_hosts"]
                    ),
                },
            }
        value["root"] = Path()
        value["skill_files"] = {
            name: _files(files) for name, files in config.get("skill_files", {}).items()
        }
        pack = ClaudeManagedPack.model_validate(value)
        for contents in pack.skill_files.values():
            bundle_digest(contents)
        files = dict(pack.skill_files)
        for item in skills:
            name = item["name"]
            if name in files:
                raise ValueError(f"duplicate projected skill: {name}")
            files[name] = _files([(f["path"], f["content_base64"]) for f in item["files"]])
        mcp = list(pack.agent.mcp_servers)
        for item in servers:
            mcp.append(
                ManagedMcp(name=item["name"], url=item["url"], permission_policy="always_ask")
            )
        agent = pack.agent.model_copy(update={"skills": tuple(files), "mcp_servers": tuple(mcp)})
        rendered = render_pack(
            pack.model_copy(update={"agent": agent, "skill_files": files}),
            installation_id=installation_id,
        )
        if environment_config is not None:
            rendered = replace(
                rendered,
                environment_config=environment_config,
                kit_digest=sha256_digest(
                    {"kit": pack.environment.kit, "config": environment_config}
                ),
            )
        refs = selected_secrets
        if refs and {item.name for item in refs} != {item.name for item in pack.vault.credentials}:
            raise ValueError(
                "selected secret declarations must exactly match the reviewed provider vault names"
            )
        return replace(rendered, secret_declarations=refs)

    if profile != "codex_agents":
        raise ValueError("unsupported hosted projection profile")
    document = PackDocument.model_validate(config["document"])

    def bundles(key: str) -> tuple[InlineBundle, ...]:
        result = []
        for item in config.get(key, []):
            contents = _files(item["files"])
            actual = bundle_digest(contents, require_skill_md=item["top_directory"])
            if actual != item["digest"]:
                raise ValueError("inline bundle bytes differ from their immutable digest")
            result.append(InlineBundle(**{**item, "files": contents}))
        return tuple(result)

    projected = list(bundles("skills"))
    for item in skills:
        inline_files = _files([(f["path"], f["content_base64"]) for f in item["files"]])
        if any(old.name == item["name"] for old in projected):
            raise ValueError(f"duplicate projected skill: {item['name']}")
        digest = bundle_digest(inline_files)
        projected.append(
            InlineBundle(item["name"], item["description"], inline_files, digest, True)
        )
    agents_mcp = (
        *document.agent.mcp_servers,
        *(
            AgentsMcp(
                server_label=item["name"],
                server_url=item["url"],
                allowed_tools=tuple(item["allowed_tools"]),
            )
            for item in servers
        ),
    )
    agents_spec = document.agent.model_copy(update={"mcp_servers": agents_mcp})
    if selected_secrets and {item.name for item in selected_secrets} != {
        item.name for item in document.vault.credentials
    }:
        raise ValueError(
            "selected secret declarations must exactly match the reviewed provider vault names"
        )
    return CodexAgentsPack(
        document.model_copy(update={"agent": agents_spec}),
        config["instructions"],
        tuple(projected),
        bundles("plugins"),
        selected_secrets,
    )


def digest(
    profile: str,
    config: dict[str, Any],
    rows: tuple[ResolvedCapability, ...],
    *,
    installation_id: str,
    environment: EnvironmentBinding | None = None,
) -> str:
    value = project(profile, config, rows, installation_id=installation_id, environment=environment)
    return value.materialization_digest if isinstance(value, RenderedPack) else value.digest
