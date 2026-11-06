"""Environment Kit seed definitions (MO-12, ADR-0042, materialization SPEC-01 section 2).

Imported by ``generate_catalog_seeds.py``, ``scripts/seeds_publish_bundles.py`` and tests.

Each starter kit is an ``environment_kit`` bundle: the repository's ``envkits/<name>/kit.json``
(``mc.environment_kit.v1``) and the base-layer files it names, published as a catalog
definition (revision 1) whose bytes live in the private ``capability-bundles`` bucket under the
digest path of its ``mc.capability_bundle_manifest.v1``. Like the agent skills, the manifest
names its application, so the rows ship per application in ``mc.app.<app>.environment-kits``.

``envkit.mission-control-dev`` adopts the repository's Mission Control-owned Cursor Cloud
base layer (``.cursor/environment.json``, ``Dockerfile`` and ``scripts/``; DECISIONS R24) under
their repository paths, so the bundle is that environment's first rendered output.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
KITS_ROOT = REPO_ROOT / "envkits"
ENVIRONMENT_KIT_SEED_TIME = datetime(2026, 10, 13, tzinfo=UTC)
SEED_VERSION = "1.0.0"
APPS = ("biotech", "ai-engineer")
APP_KEYS = {app: f"mc.app.{app}.environment-kits" for app in APPS}
KEY_PREFIX = "environment-kit"

# (kit directory, applications, repository files adopted under their own paths)
KITS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("python-uv", APPS, ()),
    ("node", APPS, ()),
    ("python-uv-node", APPS, ()),
    (
        "mission-control-dev",
        APPS,
        (
            ".cursor/environment.json",
            ".cursor/Dockerfile",
            ".cursor/scripts/cloud-install.sh",
            ".cursor/scripts/cloud-start.sh",
            ".cursor/scripts/cloud-infra.sh",
        ),
    ),
    ("knowledge-research", APPS, ()),
    ("biotech-backend", ("biotech",), ()),
)


def _lf(content: bytes) -> bytes:
    return content.replace(b"\r\n", b"\n")


def kit_files(directory: str, adopted: tuple[str, ...]) -> list[tuple[str, bytes]]:
    """The bundle's files (POSIX relative paths, LF bytes): the kit directory plus the
    repository files it adopts."""

    root = KITS_ROOT / directory
    files = [
        (path.relative_to(root).as_posix(), _lf(path.read_bytes()))
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    ]
    files += [(relative, _lf((REPO_ROOT / relative).read_bytes())) for relative in adopted]
    return sorted(files)


def kit_sources() -> list[dict[str, Any]]:
    """Every seeded kit: id, version, applications, directory and files."""

    sources = []
    for directory, apps, adopted in KITS:
        files = kit_files(directory, adopted)
        kit = json.loads(dict(files)["kit.json"])
        sources.append(
            {
                "id": kit["id"],
                "kind": "environment_kit",
                "version": kit["version"],
                "apps": apps,
                "directory": f"envkits/{directory}",
                "adopted": adopted,
                "files": files,
            }
        )
    return sources


def bundle_definition_for(source: dict[str, Any], application_id: str) -> tuple[Any, Any]:
    """``(manifest, definition)`` of one kit for one application (FT-A2 shapes)."""

    from mission_control.application.capabilities.bundle_custody import bundle_definition
    from mission_control.domain.capabilities.bundles import build_bundle_manifest

    manifest = build_bundle_manifest(
        source["files"],
        application_id=application_id,
        kind="environment_kit",
        capability_id=source["id"],
        version=source["version"],
        executable=frozenset(
            path for path, content in source["files"] if content.startswith(b"#!")
        ),
    )
    locator = f"repo://{source['directory']}"
    definition = bundle_definition(
        manifest,
        source["files"],
        {
            "source_provenance": {
                "source": "local",
                "locator": locator,
                "upstream_identity": source["id"],
                "upstream_version": source["version"],
                "license": "proprietary",
            }
        },
    )
    return manifest, definition


def definition_pin(definition: Any) -> str:
    """The Capability Pin the catalog computes for the published row (revision 1)."""

    from mission_control.domain.authoring.canonical import sha256_digest
    from mission_control.domain.authoring.contracts import ExactDefinitionRef, PublishedDefinition
    from mission_control.domain.capabilities.catalog_entry import capability_pin

    published = PublishedDefinition(
        ref=ExactDefinitionRef(
            kind=definition.kind,
            logical_id=definition.logical_id,
            revision=1,
            digest=sha256_digest(definition),
        ),
        definition=definition,
        published_at=ENVIRONMENT_KIT_SEED_TIME,
        published_by="seed:mission-control-catalog",
    )
    return capability_pin(published).render()


def application_definitions(application_id: str) -> list[dict[str, Any]]:
    """Every seeded kit of one application, in seed order, with its custody facts."""

    entries = []
    for source in kit_sources():
        if application_id not in source["apps"]:
            continue
        manifest, definition = bundle_definition_for(source, application_id)
        entries.append(
            {
                "source": source,
                "manifest": manifest,
                "definition": definition,
                "pin": definition_pin(definition),
            }
        )
    return entries


def bundles(published_records: Any, seed_format: str, compatibility: str, actor: str) -> dict:
    """One seed bundle per application (manifests and object prefixes are per application)."""

    result: dict[str, Any] = {}
    for app in APPS:
        records: list[dict[str, Any]] = []
        entries = application_definitions(app)
        for entry in entries:
            source = entry["source"]
            evidence = [
                "packages/mission-control-db-contract/seeds/environment_kits.py",
                source["directory"],
                *source["adopted"],
                "docs/specs/materialization-observation-2026-10/SPEC-01-environments.md",
            ]
            records += published_records(entry["definition"], KEY_PREFIX, evidence)
        pins = ", ".join(entry["pin"].split("#", 1)[0] for entry in entries)
        result[f"{app}/{APP_KEYS[app]}-{SEED_VERSION}.json"] = {
            "format": seed_format,
            "seed_key": APP_KEYS[app],
            "seed_version": SEED_VERSION,
            "component_compatibility": compatibility,
            "depends_on": [],
            "actor_ref": actor,
            "description": (
                f"Starter Environment Kits admitted in '{app}' (MO-12, ADR-0042): {pins}. Each "
                "row inlines its mc.environment_kit.v1 manifest; bytes live in the "
                "capability-bundles bucket under the manifest's digest path (upload with "
                "scripts/seeds_publish_bundles.py). Rows use the existing 'profile' asset "
                "category and the 0031 host-support profiles; no migration is required."
            ),
            "records": records,
        }
    return result
