"""Upload the agent-skill and Environment Kit seed bundles' bytes through the FT-A2 custody path.

For one target application, every ``skill_bundle`` and ``hook_script`` row the
``mc.app.<app>.agent-skills`` seed bundle registers (FT-A7) and every ``environment_kit`` row
of ``mc.app.<app>.environment-kits`` (MO-12) is rebuilt from its sources
(``packages/mission-control-db-contract/seeds/agent_skills.py`` and ``environment_kits.py``),
checked against the committed seed JSON (the row's ``bundle_ref`` object prefix and manifest
digest must equal the rebuilt manifest's), and uploaded with ``BundleCustodyService.upload``:
missing objects are written to their digest paths, existing objects are re-read and
compared, nothing is ever overwritten. A second run uploads nothing. Registration is the seed itself
(``mission-db seed-apply``), so this script never writes catalog rows.

    uv run python scripts/seeds_publish_bundles.py --target biotech --storage local:.runtime/bundles
    uv run python scripts/seeds_publish_bundles.py --target ai-engineer --storage supabase \\
        --env-file .scratch/sprint-oc/runtime/ai-engineer/bundle-publisher.env

``--storage supabase`` uses the deployment's publisher credential
(``CAPABILITY_BUNDLE_PUBLISHER_TOKEN``, never the service key) against ``MC_<PLANE>_DB_URL``;
it is the live path and needs an owner-approved target. It requires ``--env-file``: the
generated operator file ``bundle-publisher.env`` of that application (``sprint_oc_runtime_env.py``;
the runtime ``mission-control.env`` carries no publisher token), applied
over the process environment, so the MC ``.env`` (which names the Biotech project) never
selects the project. ``MC_<PLANE>_DB_URL`` must be exactly ``https://<project_ref>.supabase.co`` of
``deployments/<target>/target.toml``, or the script refuses before any request. ``--check``
only verifies the seed JSON against the sources. Output is one JSON report; exit 0 on success,
1 on any drift.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

from mission_control.application.capabilities.bundle_custody import (
    BundleCustodyService,
    BundleObjectStore,
)

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "packages" / "mission-control-db-contract" / "seeds"


def _seed_module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"mc_{name}", SEEDS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed_modules() -> tuple[Any, ...]:
    """The seed sources whose rows carry capability-bundles bytes."""

    return (
        _seed_module("agent_skills"),
        _seed_module("environment_kits"),
        _seed_module("cognition_profiles"),
        _seed_module("signal_skills"),
    )


def committed_bundle_refs(application_id: str) -> dict[str, dict[str, str]]:
    """``uri -> {uri, digest}`` of every bundle_ref the committed seeds register."""

    records = []
    for module in seed_modules():
        for version in getattr(module, "SEED_VERSIONS", (module.SEED_VERSION,)):
            name = f"{module.APP_KEYS[application_id]}-{version}.json"
            bundle = json.loads((SEEDS / application_id / name).read_text(encoding="utf-8"))
            records += bundle["records"]
    refs: dict[str, dict[str, str]] = {}
    for record in records:
        if record["kind"] != "asset_version":
            continue
        definition = record["fields"]["manifest"].get("definition", {})
        bundle_ref = definition.get("bundle_ref")
        if bundle_ref:
            refs[bundle_ref["uri"]] = {
                "uri": bundle_ref["uri"],
                "digest": bundle_ref["digest"],
                "manifest_digest": definition["manifest_digest"],
            }
    return refs


def check_seed(application_id: str) -> list[str]:
    """Drift between the sources and the committed seed JSON (empty when they agree)."""

    committed = committed_bundle_refs(application_id)
    problems: list[str] = []
    expected: set[str] = set()
    entries = [
        entry
        for module in seed_modules()
        for entry in getattr(module, "custody_definitions", module.application_definitions)(
            application_id
        )
    ]
    for entry in entries:
        manifest = entry["manifest"]
        if manifest is None:
            continue
        uri = f"capability-bundles://{manifest.object_prefix}"
        expected.add(uri)
        ref = committed.get(uri)
        if ref is None:
            problems.append(f"{manifest.capability_id}: not in the committed seed")
        elif (ref["uri"], ref["digest"], ref["manifest_digest"]) != (
            uri,
            manifest.digest,
            manifest.digest,
        ):
            problems.append(f"{manifest.capability_id}: seed references a different prefix")
    problems += [f"{name}: committed but not produced" for name in set(committed) - expected]
    return problems


async def publish_application(application_id: str, store: BundleObjectStore) -> dict[str, Any]:
    """Upload every bundle of one application; idempotent (a rerun uploads nothing)."""

    custody = BundleCustodyService(store=store, actor_ref="seed:mission-control-catalog")
    reports: list[dict[str, Any]] = []
    entries = [
        entry
        for module in seed_modules()
        for entry in getattr(module, "custody_definitions", module.application_definitions)(
            application_id
        )
    ]
    for entry in entries:
        manifest = entry["manifest"]
        if manifest is None:
            continue
        report = await custody.upload(manifest, entry["source"]["files"])
        reports.append(
            {
                "capability_id": manifest.capability_id,
                "pin": entry["pin"],
                "manifest_digest": manifest.digest,
                "object_prefix": manifest.object_prefix,
                "computed_hash": manifest.computed_hash,
                "uploaded": list(report.uploaded),
                "verified_existing": list(report.verified_existing),
            }
        )
    return {
        "application_id": application_id,
        "bundles": reports,
        "uploaded_objects": sum(len(item["uploaded"]) for item in reports),
        "verified_objects": sum(len(item["verified_existing"]) for item in reports),
    }


def target_settings(target: str, env_file: Path | None) -> Any:
    """Settings from the application's generated env file, refused unless its project is the
    target's (`deployments/<target>/target.toml` project_ref)."""

    from urllib.parse import urlsplit

    from dotenv import dotenv_values

    if env_file is None:
        raise SystemExit("--storage supabase requires --env-file <generated bundle-publisher.env>")
    if not env_file.is_file():
        raise SystemExit(f"--env-file {env_file} does not exist")
    values = {key: value for key, value in dotenv_values(env_file).items() if value is not None}
    os.environ.update(values)
    from pydantic import ValidationError

    from mission_control.bootstrap.settings import Settings

    # The generated env file is the only source (its own blanks replace what a `.env` would add).
    try:
        settings = Settings(_env_file=None, mission_control_application=target)  # type: ignore[call-arg]
    except ValidationError as error:  # e.g. the project ref disagrees with the URL (rule 3)
        detail = "; ".join(str(item["msg"]) for item in error.errors())
        raise SystemExit(
            f"the database variables do not name the {target} project; refusing to publish: "
            f"{detail}"
        ) from None
    target_toml = ROOT / "deployments" / target / "target.toml"
    ref = tomllib.loads(target_toml.read_text(encoding="utf-8"))["target"]["project_ref"]
    host = (urlsplit(settings.db.url or "").hostname or "").lower()
    if host != f"{ref}.supabase.co":
        raise SystemExit(
            f"{settings.db.env_name('url')} does not name the {target} project ({ref}); "
            "refusing to publish"
        )
    return settings


def open_store(storage: str, target: str = "", env_file: Path | None = None) -> BundleObjectStore:
    if storage.startswith("local:"):
        from mission_control.adapters.capabilities.local_bundle_store import (
            FilesystemBundleObjectStore,
        )

        return FilesystemBundleObjectStore(Path(storage.removeprefix("local:")))
    if storage == "supabase":
        import httpx

        from mission_control.adapters.supabase_storage.bundles import (
            configured_supabase_bundle_custody,
        )

        return configured_supabase_bundle_custody(
            target_settings(target, env_file),
            http_client=httpx.Client(timeout=120, follow_redirects=False),
            credential="publisher",
        )
    raise SystemExit("--storage is local:<directory> or supabase")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=("biotech", "ai-engineer"))
    parser.add_argument("--storage", default=None)
    parser.add_argument("--check", action="store_true", help="verify the seed JSON only")
    parser.add_argument(
        "--env-file", type=Path, help="the generated bundle-publisher.env (with --storage supabase)"
    )
    args = parser.parse_args(argv)
    problems = check_seed(args.target)
    result: dict[str, Any] = {"application_id": args.target, "seed_drift": problems}
    if not problems and not args.check:
        if args.storage is None:
            raise SystemExit("--storage is required unless --check")
        store = open_store(args.storage, args.target, args.env_file)
        result.update(asyncio.run(publish_application(args.target, store)))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
