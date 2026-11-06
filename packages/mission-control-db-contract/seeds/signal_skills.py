"""Generate additive mc-signals catalog bundles without changing applied agent-skill seeds."""

from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _module(name: str) -> Any:
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"mc_signal_seed_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent_skills = _module("agent_skills")
catalog = _module("generate_catalog_seeds")
SEED_VERSION = "1.0.0"
APP_KEYS = {app: f"mc.app.{app}.signal-skills" for app in agent_skills.APPS}


def source() -> dict[str, Any]:
    from mission_control.domain.capabilities.host_support import LaneProfile, all_profiles

    directory = "skills/mc-signals"
    manifest = json.loads((agent_skills.REPO_ROOT / directory / "manifest.json").read_text("utf-8"))
    support = all_profiles()
    profiles = {"cursor_local", "cursor_cloud", "codex", "claude_cloud", "codex_cloud"}
    return {
        "id": "skill.mc-signals",
        "kind": "skill_bundle",
        "version": manifest["version"],
        "apps": agent_skills.APPS,
        "directory": directory,
        "files": agent_skills.directory_files(directory, lf=True),
        "fields": {
            "source_provenance": {
                "source": "local",
                "locator": f"repo://{directory}",
                "upstream_identity": "skill.mc-signals",
                "upstream_version": manifest["version"],
                "license": "proprietary",
            },
            "host_support": support.model_copy(
                update={
                    "profiles": {
                        LaneProfile(name): support.profiles[LaneProfile(name)] for name in profiles
                    }
                }
            ).model_dump(mode="json"),
            "review_status": "approved",
            "maturity": "experimental",
        },
    }


def bundles() -> dict[str, dict[str, Any]]:
    result = {}
    for app in agent_skills.APPS:
        _, definition = agent_skills.bundle_definition_for(source(), app)
        records = catalog._published_definition_records(
            definition,
            "agent-skill",
            ["skills/mc-signals", "packages/mission-control-db-contract/seeds/signal_skills.py"],
            published_at=datetime(2026, 10, 14, tzinfo=UTC),
        )
        key = f"mc.app.{app}.signal-skills"
        result[f"{app}/{key}-1.0.0.json"] = {
            "format": catalog.SEED_FORMAT,
            "seed_key": key,
            "seed_version": "1.0.0",
            "component_compatibility": catalog.COMPATIBILITY,
            "depends_on": [],
            "actor_ref": catalog.SEED_ACTOR,
            "description": "Reviewed mc-signals skill; provider qualification remains separate.",
            "records": records,
        }
    return result


def application_definitions(application_id: str) -> list[dict[str, Any]]:
    selected = source()
    manifest, definition = agent_skills.bundle_definition_for(selected, application_id)
    return [
        {
            "source": selected,
            "manifest": manifest,
            "definition": definition,
            "pin": agent_skills.definition_pin(definition),
        }
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    for relative, bundle in bundles().items():
        path = agent_skills.SEEDS_ROOT / relative
        content = catalog.encode(bundle)
        if args.write:
            path.write_bytes(content)
        elif not path.is_file() or path.read_bytes() != content:
            print(f"drift: {relative}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
