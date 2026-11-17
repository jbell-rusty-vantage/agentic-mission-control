"""MO-35 portable cognition profiles; new per-app seeds, never changed applied seeds.

``1.0.0`` (frozen by bytes in ``generate_catalog_seeds.FROZEN_BUNDLES``): the eight
``mc-cognition-*`` skills, four reviewer subagents and the plugins ``plugin.cognition-sdlc``,
``plugin.cognition-knowledge`` and ``plugin.cognition-mixed`` over them
(``application_definitions``).

``1.0.1``: revision 2 of ``plugin.cognition-knowledge`` and ``plugin.cognition-mixed``. Its
knowledge members are the method skills their owning repositories maintain, imported into
bundle custody and published by ``mc.app.<app>.agent-skills`` (``skill.knowledge-research``,
``skill.knowledge-verify``) and the application's knowledge charter
(``skill.<app>-knowledge-charter``), in place of the four eight-line ``mc-cognition-*``
knowledge skills. ``plugin.cognition-sdlc`` stays at revision 1; mixed stays the union of the
SDLC and knowledge families (``successor_definitions``). Frozen by bytes like 1.0.0.

``1.0.2``: revision 3 of ``plugin.cognition-knowledge`` (``capture_definitions``): the
revision 2 members plus the evidence capture server ``mcp.knowledge-capture`` at its revision 2
(``mc.catalog.agent-capabilities@1.2.0``), so the mission that mounts the research method also
mounts the capture tools the method requires. Its host support is its members': supported on
``deep_agents`` only, because the capture server is. ``plugin.cognition-mixed`` stays at
revision 2 and is therefore no longer the exact union of the two families. Frozen by bytes.

``1.0.3``: revision 4 of ``plugin.cognition-knowledge``: the same member shape over the
method skills re-imported at Knowledge Services 1a451fd (``mc.app.<app>.agent-skills@1.0.6``),
the application's charter at its current revision and ``mcp.knowledge-capture`` at revision 3
(``mc.catalog.agent-capabilities@1.3.0``), whose allowlist carries the tools that method names
(``source_prepare_captured``, ``evidence_units``, ``chain_write``).
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_VERSION = "1.0.0"
METHOD_VERSION = "1.0.1"
CAPTURE_SEED_VERSION = "1.0.2"
SEED_VERSION = "1.0.3"
# The agent-skills seed version 1.0.3 depends on (its plugin members are rows of 1.0.6).
SKILLS_SEED_VERSION = "1.0.6"
# Every committed seed version, oldest first; all but the last are frozen.
SEED_VERSIONS = (BASE_VERSION, METHOD_VERSION, CAPTURE_SEED_VERSION, SEED_VERSION)
# Revision 3 of the knowledge plugin (seed 1.0.2): revision 2 plus the capture server.
CAPTURE_REVISION = 3
# Revision 4 (seed 1.0.3): the re-imported method skills and the capture server revision 3.
CHAIN_REVISION = 4
# knowledge plugin revision -> the capture server revision it pins.
CAPTURE_SERVER_REVISIONS = {CAPTURE_REVISION: 2, CHAIN_REVISION: 3}
CHAIN_DESCRIPTION = (
    "Knowledge work method with its evidence tools, from capture to a proposed claim: research "
    "and verification (knowledge-research), evidence capture (knowledge-verify), the "
    "application's knowledge charter and the Knowledge Services capture server "
    "(mcp.knowledge-capture revision 3: capture, read, locate, make a capture quotable, find "
    "quotable units, write one governed step of the verification chain, source and schema "
    "tools), with source-verifier and summarizer subagents. Cognition Profile "
    "cognition/knowledge, revision 4: exact pins. Supported on the deep_agents lane, where the "
    "capture server is. The knowledge tools and the Knowledge Services binding are selected in "
    "the manifest."
)
CAPTURE_DESCRIPTION = (
    "Knowledge work method with its evidence tools: research and verification "
    "(knowledge-research), evidence capture (knowledge-verify), the application's knowledge "
    "charter and the Knowledge Services capture server (mcp.knowledge-capture: capture, "
    "read, locate, source and schema tools), with source-verifier and summarizer subagents. "
    "Cognition Profile cognition/knowledge, revision 3: exact pins. Supported on the "
    "deep_agents lane, where the capture server is. The knowledge tools and the Knowledge "
    "Services binding are selected in the manifest."
)
APPS = ("biotech", "ai-engineer")
APP_KEYS = {app: f"mc.app.{app}.cognition-profiles" for app in APPS}
KEY_PREFIX = "cognition-profile"
SEED_TIME = datetime(2026, 10, 14, tzinfo=UTC)
SDLC_SKILLS = ("tdd", "code-review", "pr", "diagnosing-bugs")
KNOWLEDGE_SKILLS = ("research", "cite-and-verify", "ingest", "knowledge-services")
AGENTS = {
    "reviewer": (
        "Review the diff against the objective. Identify regressions and missing evidence. "
        "Do not edit or publish."
    ),
    "test-runner": (
        "Run the declared verification commands and report exact results. "
        "Do not replace failed checks with weaker checks."
    ),
    "source-verifier": (
        "Check each material claim against its cited source. Report unsupported claims "
        "and source limitations without inventing evidence."
    ),
    "summarizer": (
        "Summarize the verified sources, preserve citations and uncertainty, "
        "and identify contradictory evidence."
    ),
}
PROFILE_MEMBERS = {
    "sdlc": (SDLC_SKILLS, ("reviewer", "test-runner")),
    "knowledge": (KNOWLEDGE_SKILLS, ("source-verifier", "summarizer")),
    "mixed": (SDLC_SKILLS + KNOWLEDGE_SKILLS, tuple(AGENTS)),
}
# Revision 2 of the knowledge family (seed 1.0.1): the method skills every application mounts,
# before its own knowledge charter.
SUCCESSOR_REVISION = 2
METHOD_SKILLS = ("skill.knowledge-research", "skill.knowledge-verify")
# family -> (its `mc-cognition-*` SDLC skills, its reviewer subagents).
SUCCESSOR_MEMBERS = {
    "knowledge": ((), ("source-verifier", "summarizer")),
    "mixed": (SDLC_SKILLS, tuple(AGENTS)),
}
SUCCESSOR_DESCRIPTIONS = {
    "knowledge": (
        "Knowledge work method: research and verification (knowledge-research), evidence "
        "capture (knowledge-verify) and the application's knowledge charter, with "
        "source-verifier and summarizer subagents. Cognition Profile cognition/knowledge, "
        "revision 2: exact pins of the method skills their owning repositories maintain. "
        "The knowledge tools and the Knowledge Services binding are selected in the manifest."
    ),
    "mixed": (
        "SDLC skills (TDD, code review, publication, bug diagnosis) with the knowledge work "
        "method: research and verification (knowledge-research), evidence capture "
        "(knowledge-verify) and the application's knowledge charter, and four reviewer "
        "subagents. Cognition Profile cognition/mixed, revision 2: the union of cognition/sdlc "
        "and cognition/knowledge. The knowledge tools and the Knowledge Services binding are "
        "selected in the manifest."
    ),
}


def _skills() -> Any:
    spec = importlib.util.spec_from_file_location(
        "mc_cognition_skill_helpers", Path(__file__).with_name("agent_skills.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def application_definitions(application_id: str) -> list[dict[str, Any]]:
    """The 1.0.0 definitions with their custody bytes (the applied seed; never changed)."""

    from mission_control.domain.authoring.contracts import (
        PluginDefinition,
        SubagentProfileDefinition,
    )
    from mission_control.domain.capabilities.host_support import all_profiles

    if application_id not in APPS:
        raise ValueError("unknown application")
    helpers = _skills()
    support = all_profiles().model_dump(mode="json")
    entries: list[dict[str, Any]] = []
    for name in SDLC_SKILLS + KNOWLEDGE_SKILLS:
        directory = f"skills/mc-cognition-{name}"
        source = {
            "id": f"skill.mc-cognition-{name}",
            "kind": "skill_bundle",
            "version": "0.1.0",
            "apps": APPS,
            "directory": directory,
            "files": helpers.directory_files(directory, lf=True),
            "fields": {
                "host_support": support,
                "review_status": "approved",
                "maturity": "experimental",
            },
        }
        manifest, definition = helpers.bundle_definition_for(source, application_id)
        entries.append(
            {
                "source": source,
                "manifest": manifest,
                "definition": definition,
                "pin": helpers.definition_pin(definition),
            }
        )
    for name, prompt in AGENTS.items():
        definition = SubagentProfileDefinition.model_validate(
            {
                "logical_id": f"subagent.mc-cognition-{name}",
                "title": f"Cognition {name}",
                "description": prompt,
                "profile": {
                    "name": f"mc-{name}",
                    "description": prompt,
                    "prompt": prompt,
                    "readonly": True,
                },
                "host_support": support,
            }
        )
        entries.append(
            {
                "source": None,
                "manifest": None,
                "definition": definition,
                "pin": helpers.definition_pin(definition),
            }
        )
    pins = {entry["definition"].logical_id: entry["pin"] for entry in entries}
    for family, (skills, agents) in PROFILE_MEMBERS.items():
        members = [
            {"pin": pins[f"skill.mc-cognition-{name}"], "role": "skill"} for name in skills
        ] + [{"pin": pins[f"subagent.mc-cognition-{name}"], "role": "subagent"} for name in agents]
        definition = PluginDefinition.model_validate(
            {
                "logical_id": f"plugin.cognition-{family}",
                "title": f"cognition/{family}",
                "description": (
                    f"Cognition Profile cognition/{family}: portable {family} skills and bounded "
                    "reviewer subagents. Kernel hooks and telemetry are composed by Mission "
                    "Control; repository instructions stay additive. Knowledge work requires "
                    "the application's admitted Knowledge Services MCP pin as an explicit "
                    "manifest extension."
                ),
                "manifest": {"members": members},
                "host_support": support,
            }
        )
        entries.append(
            {
                "source": None,
                "manifest": None,
                "definition": definition,
                "pin": helpers.definition_pin(definition),
            }
        )
    return entries


def charter_skill(application_id: str) -> str:
    """The one knowledge charter an application admits (``charter_skill_id``)."""

    return f"skill.{application_id}-knowledge-charter"


# The agent-skill seed version that was current when 1.0.1 and 1.0.2 shipped: their method
# skill members are that version's rows, rebuilt from its frozen bytes.
METHOD_SKILLS_AS_OF = "1.0.5"


def successor_definitions(
    application_id: str, skills_as_of: str | None = METHOD_SKILLS_AS_OF
) -> list[dict[str, Any]]:
    """Revision 2 of the knowledge and mixed plugins (seed 1.0.1).

    Each entry carries its ``members``: the member's entry (definition, pin, custody source)
    and the seed logical key of the member's row, in member order. Skill members come from the
    agent-skill seeds as they stood at ``skills_as_of`` (``None``: the current rows); the SDLC
    skills and the subagents are the 1.0.0 rows.
    """

    from mission_control.domain.authoring.contracts import PluginDefinition
    from mission_control.domain.capabilities.plugins import PluginManifest

    helpers = _skills()
    base = {
        entry["definition"].logical_id: entry for entry in application_definitions(application_id)
    }
    skills = {
        entry["definition"].logical_id: entry
        for entry in (
            helpers.application_definitions(application_id)
            if skills_as_of is None
            else helpers.definitions_as_of(application_id, skills_as_of)
        )
    }
    skill_keys = (
        helpers.seed_keys(application_id)
        if skills_as_of is None
        else helpers.seed_keys_as_of(application_id, skills_as_of)
    )

    def base_key(logical_id: str) -> str:
        kind = base[logical_id]["definition"].kind.value.replace("_", "-")
        return f"{KEY_PREFIX}:{kind}:{logical_id}/1"

    entries: list[dict[str, Any]] = []
    for family, (sdlc, agents) in SUCCESSOR_MEMBERS.items():
        members: list[tuple[str, dict[str, Any], str]] = []
        for name in sdlc:
            logical_id = f"skill.mc-cognition-{name}"
            members.append(("skill", base[logical_id], base_key(logical_id)))
        for logical_id in (*METHOD_SKILLS, charter_skill(application_id)):
            members.append(("skill", skills[logical_id], skill_keys[logical_id]))
        for name in agents:
            logical_id = f"subagent.mc-cognition-{name}"
            members.append(("subagent", base[logical_id], base_key(logical_id)))
        manifest = PluginManifest.model_validate(
            {"members": [{"pin": entry["pin"], "role": role} for role, entry, _key in members]}
        )
        by_pin = {entry["pin"]: entry["definition"] for _role, entry, _key in members}
        definition = PluginDefinition.model_validate(
            {
                "logical_id": f"plugin.cognition-{family}",
                "title": f"cognition/{family}",
                "description": SUCCESSOR_DESCRIPTIONS[family],
                "manifest": manifest.model_dump(mode="json"),
                # What every member supports: never more than its weakest member declares.
                "host_support": manifest.host_support(
                    lambda pin, by_pin=by_pin: by_pin[pin.render()].host_support
                ).model_dump(mode="json"),
            }
        )
        entries.append(
            {
                "source": None,
                "manifest": None,
                "definition": definition,
                "pin": helpers.definition_pin(definition, SUCCESSOR_REVISION),
                "revision": SUCCESSOR_REVISION,
                "members": [(entry, key) for _role, entry, key in members],
            }
        )
    return entries


def _capabilities() -> Any:
    spec = importlib.util.spec_from_file_location(
        "mc_cognition_capability_helpers", Path(__file__).with_name("agent_capabilities.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture_definitions(
    application_id: str, revision: int = CHAIN_REVISION
) -> list[dict[str, Any]]:
    """The knowledge plugin at ``revision`` 3 (seed 1.0.2) or 4 (seed 1.0.3): the method
    skills, charter and subagents of revision 2's shape, then the capture server at the
    revision it pins between the skills and the subagents. Revision 3's skills are the rows of
    agent-skills 1.0.5 (it reproduces its frozen bytes); revision 4's are the current rows.
    Entries are shaped like :func:`successor_definitions`'s."""

    from mission_control.domain.authoring.contracts import PluginDefinition
    from mission_control.domain.capabilities.plugins import PluginManifest

    helpers = _skills()
    capabilities = _capabilities()
    (prior,) = [
        entry
        for entry in successor_definitions(
            application_id, METHOD_SKILLS_AS_OF if revision == CAPTURE_REVISION else None
        )
        if entry["definition"].logical_id == "plugin.cognition-knowledge"
    ]
    server_revision = CAPTURE_SERVER_REVISIONS[revision]
    server = capabilities.server_definition(capabilities.CAPTURE_REVISIONS[server_revision])
    capture = {
        "source": None,
        "manifest": None,
        "definition": server,
        "pin": capabilities.capture_pin(server_revision),
    }
    capture_key = f"agent-capability:mcp-server:{server.logical_id}/{server_revision}"
    roles = [member.role.value for member in prior["definition"].manifest.members]
    members: list[tuple[str, dict[str, Any], str]] = [
        (role, entry, key) for role, (entry, key) in zip(roles, prior["members"], strict=True)
    ]
    position = max(index for index, (role, _e, _k) in enumerate(members) if role == "skill") + 1
    members.insert(position, ("mcp_server", capture, capture_key))
    manifest = PluginManifest.model_validate(
        {"members": [{"pin": entry["pin"], "role": role} for role, entry, _key in members]}
    )
    by_pin = {entry["pin"]: entry["definition"] for _role, entry, _key in members}
    definition = PluginDefinition.model_validate(
        {
            "logical_id": "plugin.cognition-knowledge",
            "title": "cognition/knowledge",
            "description": CHAIN_DESCRIPTION if revision == CHAIN_REVISION else CAPTURE_DESCRIPTION,
            "manifest": manifest.model_dump(mode="json"),
            # What every member supports: never more than its weakest member declares.
            "host_support": manifest.host_support(
                lambda pin: by_pin[pin.render()].host_support
            ).model_dump(mode="json"),
            "secret_refs": sorted(server.secret_refs),
        }
    )
    return [
        {
            "source": None,
            "manifest": None,
            "definition": definition,
            "pin": helpers.definition_pin(definition, revision),
            "revision": revision,
            "members": [(entry, key) for _role, entry, key in members],
        }
    ]


def current_profiles(application_id: str) -> list[dict[str, Any]]:
    """The three Cognition Profiles a manifest selects today: each plugin at its latest
    revision, with the entries of its members."""

    from mission_control.domain.authoring.contracts import PluginDefinition

    base = application_definitions(application_id)
    by_pin = {entry["pin"]: entry for entry in base}
    successors = {
        entry["definition"].logical_id: entry
        for entry in (
            *successor_definitions(application_id),
            *capture_definitions(application_id),
        )
    }
    profiles = []
    for entry in base:
        definition = entry["definition"]
        if not isinstance(definition, PluginDefinition):
            continue
        if definition.logical_id in successors:
            profiles.append(successors[definition.logical_id])
            continue
        members = [(by_pin[member.pin.render()], "") for member in definition.manifest.members]
        profiles.append({**entry, "revision": 1, "members": members})
    return profiles


def bundles(
    published_records: Any, seed_format: str, compatibility: str, actor: str
) -> dict[str, Any]:
    """Seed 1.0.3: revision 4 of the knowledge plugin and its member rows. 1.0.0, 1.0.1 and
    1.0.2 are frozen bytes."""

    helpers = _skills()
    capabilities = _capabilities()
    result = {}
    for app in APPS:
        records: list[dict[str, Any]] = []
        for entry in capture_definitions(app, CHAIN_REVISION):
            definition = entry["definition"]
            key = f"{KEY_PREFIX}:plugin:{definition.logical_id}/{entry['revision']}"
            records += published_records(
                definition,
                KEY_PREFIX,
                [
                    "packages/mission-control-db-contract/seeds/cognition_profiles.py",
                    "packages/mission-control-db-contract/seeds/agent_capabilities.py",
                    capabilities.RESEARCH_NOTE,
                ],
                revision=entry["revision"],
            )
            for position, (member, (_entry, member_key)) in enumerate(
                zip(definition.manifest.members, entry["members"], strict=True)
            ):
                records.append(
                    {
                        "kind": "capability_plugin_member",
                        "logical_key": f"{key}:member:{position}",
                        "fields": {
                            "plugin": key,
                            "member": member_key,
                            "position": position,
                            "role": member.role.value,
                            "optional": False,
                        },
                    }
                )
        result[f"{app}/{APP_KEYS[app]}-{SEED_VERSION}.json"] = {
            "format": seed_format,
            "seed_key": APP_KEYS[app],
            "seed_version": SEED_VERSION,
            "component_compatibility": compatibility,
            "depends_on": [
                {"seed_key": APP_KEYS[app], "seed_version": CAPTURE_SEED_VERSION},
                # 1.0.3 was released against agent-skills 1.0.6 (later skill seeds add rows).
                {"seed_key": helpers.APP_KEYS[app], "seed_version": SKILLS_SEED_VERSION},
                {
                    "seed_key": capabilities.COMMON_KEY,
                    "seed_version": capabilities.CAPTURE_R3_SEED_VERSION,
                },
            ],
            "actor_ref": actor,
            "description": (
                "Revision 4 of cognition/knowledge: the method skills skill.knowledge-research "
                "and skill.knowledge-verify re-imported at Knowledge Services 1a451fd, "
                f"{charter_skill(app)}, the source-verifier and summarizer subagents and the "
                "evidence capture server mcp.knowledge-capture at its revision 3 (the chain "
                "tools allowlisted), by exact pin. Its host support is the intersection of its "
                "members': supported on deep_agents, unqualified on the other worker-hosted "
                "lane profiles, unsupported on cursor_cloud. cognition/mixed stays at revision "
                f"2, cognition/sdlc at revision 1, and every {BASE_VERSION}, {METHOD_VERSION} "
                f"and {CAPTURE_SEED_VERSION} record is unchanged."
            ),
            "records": records,
        }
    return result
