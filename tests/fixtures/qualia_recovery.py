"""Reopen only the exact retained local fixture runtime; never rebuild it from exports."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from tests.fixtures.mission_control_common_db import CommonDatabase


def retained_runtime(root: Path, application_id: str = "biotech") -> tuple[CommonDatabase, str]:
    root = root.resolve(strict=True)
    document = json.loads((root / "runtime-recovery.private.json").read_text(encoding="utf-8"))
    if document.get("schema") != "qualia-local-runtime-recovery.v1":
        raise ValueError("unknown retained fixture schema")
    if Path(document["root"]).resolve() != root:
        raise ValueError("retained fixture root mismatch")
    temporal = (root / "temporal.sqlite").resolve(strict=True)
    if Path(document["temporal_database"]).resolve() != temporal:
        raise ValueError("retained Temporal database mismatch")
    if not (root / "payloads").is_dir():
        raise ValueError("retained payload custody is unavailable")
    value = document["database"]
    name = value["name"]
    if not re.fullmatch(r"mct_[a-z0-9]+", name) or value["application_id"] != application_id:
        raise ValueError(f"retained database is not a local {application_id} fixture")
    dsns = [value["owner_dsn"], *value["role_dsns"].values(), document["checkpoint_dsn"]]
    coordinates = set()
    for dsn in dsns:
        parsed = urlsplit(dsn)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.path != "/" + name:
            raise ValueError("retained fixture DSN is outside its local database")
        host = "127.0.0.1" if parsed.hostname == "localhost" else parsed.hostname
        coordinates.add((host, parsed.port or 5432, parsed.path))
    if len(coordinates) != 1:
        raise ValueError("retained fixture DSNs disagree")
    value["installation_id"] = UUID(value["installation_id"])
    value["tenants"] = {key: UUID(identity) for key, identity in value["tenants"].items()}
    return CommonDatabase(**value), document["checkpoint_dsn"]


async def require_completed_source(database: CommonDatabase, run_id: str) -> None:
    """Check actual restricted authority before restarting any retained worker."""
    from mission_control.adapters.postgres.run_control.run_control_repository import (
        PostgresRunControlRepository,
    )

    pool = await database.pool()
    try:
        projection = await PostgresRunControlRepository(pool).get_run(database.scope(), run_id)
        if projection.phase != "terminal" or projection.terminal_outcome != "completed":
            raise ValueError("retained fork source has not completed in canonical authority")
    finally:
        await pool.close()


def retained_fork_manifests(root: Path) -> tuple[str, str]:
    """Use the actually authored pair; current fixture code cannot replace pinned inputs."""
    source = (root / "01-authored-mission.yml").read_text(encoding="utf-8")
    target = json.loads(
        (root / "tavily-fork/01-prepared-manifest.json").read_text(encoding="utf-8")
    )["manifest_yaml"]
    if not isinstance(target, str) or not source.strip() or not target.strip():
        raise ValueError("retained authored fork manifests are unavailable")
    return source, target
