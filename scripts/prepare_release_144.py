"""Prepare the additive component release 1.4.4; build it with `mission-db release-build`.

1.4.4 (provider consolidation, P1 deep_agents Stage 1 of the tracing work) adds to the
byte-identical 1.4.3 prefix the three migrations authored in `scripts/release_144/`:

- `0047_transcript_joinability.sql`: `mission_event.unit_key` and `point_ref`;
  `cognition_point.subordinate_ref`, `restore_level`, `pruned_at`, `prune_policy`; the new
  provider frame kinds (`model_request`, `environment_materialized`, `subagent_started`,
  `subagent_ended`, `progress_note`), the closing rule with `subagent_ended` and the generated
  `retention_class`; `frame_retention_policy.step_retain_days` and `prune_mode`; the expiry
  function narrowed to the delta class and the step-frame expiry function; the
  `mission_run.temporal_*` column grant; the completion table grants.
- `0048_transcript_entry.sql`: `mission_control.transcript_entry` and
  `mission_control.transcript_projection_state`, the persisted Transcript projection.
- `0049_frame_body_refs.sql`: the `frame-body://` reference scheme documented on the columns.

No lane-describe migration: nothing in `mc.lane_describe` changes. The destination is a
fresh directory (the canonical one is `releases/1.4.4`); nothing in 1.4.3 or earlier is
rewritten and no manifest is produced here. Build afterwards:

    .venv/Scripts/mission-db.exe release-build \\
        --component-root packages/mission-control-db-contract/releases/1.4.4/component \\
        --admin-dsn-env MCDB_RELEASE_ADMIN_DSN
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages/mission-control-db-contract"
BASE = PACKAGE / "releases/1.4.3"
CANONICAL = PACKAGE / "releases/1.4.4"
VERSION = "1.4.4"
MIGRATIONS = (
    "0047_transcript_joinability.sql",
    "0048_transcript_entry.sql",
    "0049_frame_body_refs.sql",
)


def frozen_inputs() -> tuple[dict, dict]:
    """Verify the built 1.4.3 inputs against its manifest before copying them."""

    component = BASE / "component"
    manifest = json.loads((component / "manifest.json").read_bytes())
    if manifest["component_version"] != "1.4.3":
        raise ValueError("the base release is not the built 1.4.3")
    expected = {item["path"]: item["sha256"] for item in manifest["ordered_migrations"]}
    actual = {}
    for path in (component / "migrations").iterdir():
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise ValueError("frozen migrations must be regular files")
        actual[path.relative_to(component).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    if actual != expected:
        raise ValueError("frozen migration set or bytes differ from release 1.4.3")
    spec = json.loads((component / "release-spec.json").read_bytes())
    descriptor = manifest["runtime_descriptor"]
    descriptor_path = component / descriptor["path"]
    if hashlib.sha256(descriptor_path.read_bytes()).hexdigest() != descriptor["sha256"]:
        raise ValueError("frozen runtime descriptor bytes differ")
    return manifest, spec


def prepare(destination: Path) -> Path:
    destination = destination.resolve()
    package = PACKAGE.resolve()
    if (
        destination == package or package in destination.parents
    ) and destination != CANONICAL.resolve():
        raise ValueError("only releases/1.4.4 is an allowed destination inside the package")
    if destination.exists():
        raise FileExistsError(destination)
    manifest, spec = frozen_inputs()
    sources = {
        name: (ROOT / "scripts/release_144" / name).read_bytes().decode("utf-8")
        for name in MIGRATIONS
    }
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
    for name, sql in sources.items():
        (component / "migrations" / name).write_text(sql, encoding="utf-8", newline="\n")
    return component


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=CANONICAL)
    args = parser.parse_args()
    print(json.dumps({"component_root": str(prepare(args.out)), "state": "unbuilt"}))


if __name__ == "__main__":
    main()
