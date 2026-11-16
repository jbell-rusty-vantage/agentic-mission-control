#!/usr/bin/env python3
"""Import a sibling repository's skill into bundle custody, or verify the custody copies.

Mission Control mounts method skills it does not author (the Knowledge Services research and
verification skills, an application's knowledge charter). Each is copied byte for byte from one
commit of its owning repository into
``packages/mission-control-db-contract/bundle-sources/imported/<source>/<commit7>/<skill>/`` and
recorded in ``IMPORTS.json`` beside the copies: the owning repository, the commit, the path, the
minted ``belllabs`` identifier and version, the one-line description of its frontmatter, and each
file's sha256, git blob id and size. The agent-skill seeds publish a copy from that record
(``seeds/agent_skills.py``).

Mission Control never edits a copy. An update is a new import at a new commit: a new directory,
a new record and a new seed version. ``--check`` needs no sibling checkout and no git; CI runs
it (``make skills-check``).

Usage:
  python scripts/skills_import.py --check
  python scripts/skills_import.py --import --source knowledge-services \\
      --repo ../knowledge-services --commit 7bc4aee --path skills/knowledge-research

The version is the skill's declared ``metadata.version`` when it has one, else the commit's UTC
date (``YYYY.MM.DD``), followed by ``-<commit7>``: two commits never share a version.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
CUSTODY: Final = ROOT / "packages" / "mission-control-db-contract" / "bundle-sources" / "imported"
RECORD: Final = CUSTODY / "IMPORTS.json"
SCHEMA: Final = "mc.skill_imports.v1"
SCHEME: Final = "belllabs"
NAME_RULE: Final = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DESCRIPTION_MAX: Final = 1024


def sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def git_blob(content: bytes) -> str:
    """The git blob id of ``content``: what the owning repository's tree lists for the file."""

    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()  # noqa: S324


def load_record() -> dict[str, Any]:
    if not RECORD.is_file():
        return {"schema_version": SCHEMA, "imports": []}
    return dict(json.loads(RECORD.read_bytes()))


def copy_files(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def file_rows(files: dict[str, bytes]) -> list[dict[str, Any]]:
    return [
        {
            "path": path,
            "sha256": sha256(content),
            "git_blob": git_blob(content),
            "size_bytes": len(content),
        }
        for path, content in sorted(files.items())
    ]


# -- check ---------------------------------------------------------------------------------------


def check() -> int:
    """Every custody copy is exactly what its record says, and nothing else is in custody."""

    record = load_record()
    problems: list[str] = []
    if record.get("schema_version") != SCHEMA:
        problems.append(f"{RECORD.name}: schema_version is not {SCHEMA}")
    named: set[Path] = set()
    seen: set[tuple[str, str]] = set()
    for entry in record.get("imports", []):
        label = f"{entry['source']['name']}@{entry['source']['commit'][:7]}/{entry['skill']}"
        directory = ROOT / entry["directory"]
        named.add(directory)
        key = (entry["capability_id"], entry["version"])
        if key in seen:
            problems.append(f"{label}: {key[0]}@{key[1]} is recorded twice")
        seen.add(key)
        if not directory.is_dir():
            problems.append(f"{label}: {entry['directory']} is missing")
            continue
        if file_rows(copy_files(directory)) != entry["files"]:
            recorded = {row["path"]: row for row in entry["files"]}
            actual = {row["path"]: row for row in file_rows(copy_files(directory))}
            for path in sorted(set(recorded) | set(actual)):
                if recorded.get(path) != actual.get(path):
                    state = (
                        "not in the record"
                        if path not in recorded
                        else "missing"
                        if path not in actual
                        else "differs from its recorded digest"
                    )
                    problems.append(f"{label}: {path} {state}")
        elif directory.joinpath("SKILL.md").is_file():
            print(f"ok       {label} ({len(entry['files'])} files, {entry['version']})")
        if (
            not NAME_RULE.match(entry["skill"])
            or entry["capability_id"] != f"skill.{entry['skill']}"
        ):
            problems.append(f"{label}: capability id and skill name disagree")
    if CUSTODY.is_dir():
        for skill_md in sorted(CUSTODY.rglob("SKILL.md")):
            if skill_md.parent not in named:
                stray = skill_md.parent.relative_to(ROOT).as_posix()
                problems.append(f"{stray}: a copy no record names")
    for problem in problems:
        print(f"DRIFT    {problem}")
    return 1 if problems else 0


# -- import --------------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def _repository_url(repo: Path, given: str | None) -> str:
    url = given or _git(repo, "remote", "get-url", "origin").decode("utf-8").strip()
    url = re.sub(r"^(https?://)[^/@]+@", r"\1", url).removesuffix(".git")
    if not url.startswith("https://"):
        raise SystemExit(f"--repository must be an https URL without credentials, got {url!r}")
    return url


def _frontmatter(skill_md: bytes) -> dict[str, Any]:
    import yaml

    text = skill_md.decode("utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        raise SystemExit("SKILL.md has no frontmatter block")
    loaded = yaml.safe_load(text[4 : text.index("\n---", 4)])
    if not isinstance(loaded, dict):
        raise SystemExit("SKILL.md frontmatter is not a mapping")
    return loaded


def import_skill(source: str, repo: Path, commit: str, path: str, repository: str | None) -> dict:
    """Copy one skill directory at one commit into custody and return its record."""

    full = _git(repo, "rev-parse", f"{commit}^{{commit}}").decode().strip()
    committed = datetime.fromisoformat(
        _git(repo, "show", "-s", "--format=%cI", full).decode().strip()
    ).astimezone(UTC)
    listing = _git(repo, "ls-tree", "-r", "-z", "--name-only", full, "--", path).decode("utf-8")
    names = [name for name in listing.split("\0") if name]
    if not names:
        raise SystemExit(f"{path} holds no file at {full[:7]}")
    prefix = path.rstrip("/") + "/"
    files = {
        name.removeprefix(prefix): _git(repo, "cat-file", "blob", f"{full}:{name}")
        for name in names
    }
    if "SKILL.md" not in files:
        raise SystemExit(f"{path} has no SKILL.md at {full[:7]}")
    frontmatter = _frontmatter(files["SKILL.md"])
    skill = str(frontmatter.get("name", ""))
    if skill != Path(path).name or not NAME_RULE.match(skill):
        raise SystemExit(f"frontmatter name {skill!r} is not the directory name of {path}")
    description = " ".join(str(frontmatter.get("description", "")).split())
    if not 1 <= len(description) <= DESCRIPTION_MAX:
        raise SystemExit(f"{skill}: description must hold 1 to {DESCRIPTION_MAX} characters")
    declared = (frontmatter.get("metadata") or {}).get("version")
    version = f"{declared or committed.strftime('%Y.%m.%d')}-{full[:7]}"
    directory = CUSTODY / source / full[:7] / skill
    if directory.exists() and copy_files(directory) != files:
        raise SystemExit(
            f"{directory.relative_to(ROOT).as_posix()} exists with other bytes; a copy is "
            "never edited: import another commit"
        )
    for relative, content in files.items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {
        "skill": skill,
        "capability_id": f"skill.{skill}",
        "identifier": {"scheme": SCHEME, "value": f"{source}/{skill}"},
        "version": version,
        "description": description,
        "license": str(frontmatter.get("license", "proprietary")).lower(),
        "source": {
            "name": source,
            "repository": _repository_url(repo, repository),
            "commit": full,
            "committed_at": committed.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "path": path.rstrip("/"),
        },
        "directory": directory.relative_to(ROOT).as_posix(),
        "files": file_rows(files),
    }


def write_record(record: dict[str, Any]) -> None:
    record["imports"].sort(
        key=lambda item: (item["source"]["name"], item["source"]["commit"], item["skill"])
    )
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    RECORD.write_bytes((json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="verify the copies; exit 1 on drift")
    mode.add_argument("--import", dest="do_import", action="store_true", help="copy at a commit")
    parser.add_argument("--source", help="the owning repository's short name (custody directory)")
    parser.add_argument("--repo", type=Path, help="a checkout of the owning repository")
    parser.add_argument("--commit", help="the commit to copy from")
    parser.add_argument("--path", action="append", default=[], help="skill directory (repeatable)")
    parser.add_argument("--repository", help="the owning repository's https URL (default: origin)")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    if not (args.source and args.repo and args.commit and args.path):
        parser.error("--import needs --source, --repo, --commit and at least one --path")
    if not NAME_RULE.match(args.source):
        parser.error("--source is a lower-case slug")
    record = load_record()
    for path in args.path:
        entry = import_skill(args.source, args.repo, args.commit, path, args.repository)
        record["imports"] = [
            item
            for item in record["imports"]
            if (item["capability_id"], item["version"])
            != (entry["capability_id"], entry["version"])
        ] + [entry]
        print(f"imported {entry['capability_id']}@{entry['version']} ({len(entry['files'])} files)")
    write_record(record)
    return check()


if __name__ == "__main__":
    sys.exit(main())
