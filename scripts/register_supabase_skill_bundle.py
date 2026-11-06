"""Operator-only: stage a reviewed directory, verify bytes, and register its exact pin.

Uses only ``--env-file`` (the generated ``bundle-publisher.env``): SUPABASE_URL of the application's
own project (refused otherwise), the publisher credential CAPABILITY_BUNDLE_PUBLISHER_TOKEN (never
the service key), CAPABILITY_BUNDLE_NAMESPACE, MISSION_CONTROL_CATALOG_SCOPE and the application
PostgreSQL settings. Does not apply migrations, amend deployment pins,
execute scripts, delete orphan objects, or obtain credentials from request arguments.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import cast

import asyncpg
import httpx

from mission_control.adapters.capabilities.capability_bundles import BundleError, bytes_digest
from mission_control.adapters.capabilities.capability_pins import PinnedExactRef, PinnedSkill
from mission_control.adapters.postgres.capability_bundles import PostgresCapabilityBundleAdmissions
from mission_control.adapters.supabase_storage.bundles import configured_supabase_bundle_store
from mission_control.bootstrap.settings import Settings
from mission_control.domain.authoring.contracts import DefinitionKind


def operator_settings(env_file: Path) -> Settings:
    """Settings from the application's generated `bundle-publisher.env`, refused unless its
    SUPABASE_URL is the project of the application it names (`seeds_publish_bundles.py`)."""

    from dotenv import dotenv_values

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from seeds_publish_bundles import target_settings  # type: ignore[import-not-found]

    if not env_file.is_file():
        raise SystemExit(f"--env-file {env_file} does not exist")
    application = dotenv_values(env_file).get("MISSION_CONTROL_APPLICATION") or ""
    if application not in {"biotech", "ai-engineer"}:
        raise SystemExit("--env-file names no MISSION_CONTROL_APPLICATION (biotech or ai-engineer)")
    return cast(Settings, target_settings(application, env_file))


async def register(args: argparse.Namespace) -> PinnedSkill:
    settings = operator_settings(args.env_file)
    if not settings.mission_control_catalog_scope or not settings.capability_bundle_namespace:
        raise BundleError("trusted catalog scope and storage namespace must be configured")
    ref = PinnedExactRef(
        kind=DefinitionKind.SKILL,
        logical_id=args.asset_id,
        revision=args.version,
        digest=args.definition_digest,
    )
    with httpx.Client(timeout=30, follow_redirects=False) as http:
        reader = configured_supabase_bundle_store(
            settings, http_client=http, credential="publisher"
        )
        manifest = await asyncio.to_thread(
            reader.stage, args.directory, asset_id=ref.logical_id, version=ref.revision
        )
        _, files = await asyncio.to_thread(reader.load, manifest.digest)
        pin = PinnedSkill(
            ref=ref,
            skill_name=args.skill_name,
            source_locator="capability-bundles://" + manifest.digest,
            bundle_digest=manifest.bundle_digest,
            skill_md_digest=bytes_digest(dict(files)["SKILL.md"]),
            digest_format="bytes_v1",
            mount_root="/skills/" + args.skill_name,
        )
        pool = await asyncpg.create_pool(settings.application_postgres_dsn, min_size=1, max_size=1)
        try:
            await PostgresCapabilityBundleAdmissions(
                pool,
                catalog_scope=settings.mission_control_catalog_scope,
                storage_namespace=settings.capability_bundle_namespace,
            ).register(pin, reader=reader)
        finally:
            await pool.close()
    return pin


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--version", required=True, type=int)
    parser.add_argument("--skill-name", required=True)
    parser.add_argument("--definition-digest", required=True)
    parser.add_argument(
        "--env-file",
        required=True,
        type=Path,
        help="the generated bundle-publisher.env (publisher credential, the application project)",
    )
    args = parser.parse_args()
    try:
        pin = asyncio.run(register(args))
    except Exception as error:
        # SDK/DB connection exception strings can include deployment endpoints/details.
        raise SystemExit(
            f"Bundle registration failed ({type(error).__name__}); staged objects are retained. "
            "Registration outcome may require retry with the same pin. No version was overwritten."
        ) from None
    print(pin.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
