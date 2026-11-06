"""MO-35 portable cognition profiles; new per-app seeds, never changed applied seeds."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SEED_VERSION = "1.0.0"
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


def _skills() -> Any:
    spec = importlib.util.spec_from_file_location(
        "mc_cognition_skill_helpers", Path(__file__).with_name("agent_skills.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def application_definitions(application_id: str) -> list[dict[str, Any]]:
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


def bundles(
    published_records: Any, seed_format: str, compatibility: str, actor: str
) -> dict[str, Any]:
    from mission_control.domain.authoring.contracts import PluginDefinition
    from mission_control.domain.capabilities.pins import CapabilityPin

    result = {}
    for app in APPS:
        entries = application_definitions(app)
        records = []
        keys = {}
        for entry in entries:
            definition = entry["definition"]
            kind = definition.kind.value.replace("_", "-")
            keys[definition.logical_id] = f"{KEY_PREFIX}:{kind}:{definition.logical_id}/1"
        for entry in entries:
            definition = entry["definition"]
            evidence = [
                "docs/specs/materialization-observation-2026-10/SPEC-02-cognition.md",
                "packages/mission-control-db-contract/seeds/cognition_profiles.py",
            ]
            if entry["source"] is not None:
                evidence.append(entry["source"]["directory"])
            records += published_records(definition, KEY_PREFIX, evidence)
            if isinstance(definition, PluginDefinition):
                for position, member in enumerate(definition.manifest.members):
                    member_id = CapabilityPin.parse(member.pin.render()).capability_id
                    records.append(
                        {
                            "kind": "capability_plugin_member",
                            "logical_key": f"{keys[definition.logical_id]}:member:{position}",
                            "fields": {
                                "plugin": keys[definition.logical_id],
                                "member": keys[member_id],
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
            "depends_on": [{"seed_key": "mc.storage.capability-bundles", "seed_version": "1.0.0"}],
            "actor_ref": actor,
            "description": (
                "Portable cognition/sdlc, cognition/knowledge and cognition/mixed defaults. "
                "Exact constituent pins; hosted support remains unqualified. "
                "Application Knowledge Services binding is required separately."
            ),
            "records": records,
        }
    return result
