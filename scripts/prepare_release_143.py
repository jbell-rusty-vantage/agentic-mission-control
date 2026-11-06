"""Prepare the additive component release 1.4.3; build it with `mission-db release-build`.

1.4.3 (provider consolidation, P1 deep_agents turn 4) adds to the byte-identical 1.4.2 prefix:

- `0045_cognition_points.sql`: the `cognition_point` table (`mc.cognition_point.v1`),
  `session_turn.point_ref`, `activity_attempt_observation.task_queue` and the
  `agent_session.checkpoint_namespace` grant (authored in `scripts/release_143/`).
- `0046_lane_describe_subagent_fields.sql`: every lane describe gains `subagents.fields`
  (the per-lane subagent field table compile enforces) and the Deep Agents describe its
  `time_travel` levels; generated from `DECLARED_LANE_MATRICES` by
  `packages/mission-control-db-contract/scripts/lane_describe_refresh.py::render_successor_section`,
  each revision conditional on the exact describe 1.4.2 persisted.

The destination is a fresh directory (the canonical one is `releases/1.4.3`); nothing in
1.4.2 or earlier is rewritten and no manifest is produced here. Build afterwards:

    .venv/Scripts/mission-db.exe release-build \\
        --component-root packages/mission-control-db-contract/releases/1.4.3/component \\
        --admin-dsn-env MCDB_RELEASE_ADMIN_DSN
"""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages/mission-control-db-contract"
BASE = PACKAGE / "releases/1.4.2"
CANONICAL = PACKAGE / "releases/1.4.3"
VERSION = "1.4.3"
POINTS_MIGRATION = "0045_cognition_points.sql"
DESCRIBE_MIGRATION = "0046_lane_describe_subagent_fields.sql"
QUALIFIED_PROFILES = ("deep_agents",)


def frozen_inputs() -> tuple[dict, dict]:
    """Verify the built 1.4.2 inputs against its manifest before copying them."""

    component = BASE / "component"
    manifest = json.loads((component / "manifest.json").read_bytes())
    if manifest["component_version"] != "1.4.2":
        raise ValueError("the base release is not the built 1.4.2")
    expected = {item["path"]: item["sha256"] for item in manifest["ordered_migrations"]}
    actual = {}
    for path in (component / "migrations").iterdir():
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise ValueError("frozen migrations must be regular files")
        actual[path.relative_to(component).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    if actual != expected:
        raise ValueError("frozen migration set or bytes differ from release 1.4.2")
    spec = json.loads((component / "release-spec.json").read_bytes())
    descriptor = manifest["runtime_descriptor"]
    descriptor_path = component / descriptor["path"]
    if hashlib.sha256(descriptor_path.read_bytes()).hexdigest() != descriptor["sha256"]:
        raise ValueError("frozen runtime descriptor bytes differ")
    return manifest, spec


def describe_sql() -> str:
    generator = runpy.run_path(str(PACKAGE / "scripts/lane_describe_refresh.py"))
    documents = generator["declared_documents"]()
    prior = generator["persisted_documents"](BASE / "component/migrations")
    profiles = tuple(profile for profile in documents if documents[profile] != prior.get(profile))
    if set(profiles) != set(documents):
        unchanged = sorted(set(documents) - set(profiles))
        raise ValueError(f"every lane describe must move in 1.4.3; unchanged: {unchanged}")
    return generator["render_successor_section"](
        label=f"release {VERSION}: subagent fields and time travel on every lane describe",
        documents=documents,
        prior=prior,
        profiles=profiles,
        qualified_profiles=QUALIFIED_PROFILES,
    )


def prepare(destination: Path) -> Path:
    destination = destination.resolve()
    package = PACKAGE.resolve()
    if (
        destination == package or package in destination.parents
    ) and destination != CANONICAL.resolve():
        raise ValueError("only releases/1.4.3 is an allowed destination inside the package")
    if destination.exists():
        raise FileExistsError(destination)
    manifest, spec = frozen_inputs()
    points = (ROOT / "scripts/release_143" / POINTS_MIGRATION).read_bytes().decode("utf-8")
    describe = describe_sql()
    component = destination / "component"
    shutil.copytree(BASE / "component/migrations", component / "migrations")
    shutil.copytree(BASE / "runtime", destination / "runtime")
    spec["component_version"] = VERSION
    fingerprint = manifest["schema_fingerprint"]
    if fingerprint not in spec["compatible_previous_fingerprints"]:
        spec["compatible_previous_fingerprints"].append(fingerprint)
    (component / "release-spec.json").write_text(
        json.dumps(spec, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    (component / "migrations" / POINTS_MIGRATION).write_text(points, encoding="utf-8", newline="\n")
    (component / "migrations" / DESCRIBE_MIGRATION).write_text(
        describe, encoding="utf-8", newline="\n"
    )
    return component


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=CANONICAL)
    args = parser.parse_args()
    print(json.dumps({"component_root": str(prepare(args.out)), "state": "unbuilt"}))


if __name__ == "__main__":
    main()
