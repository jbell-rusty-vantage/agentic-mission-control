"""Behaviour of ``scripts/skills_import.py``: custody copies are exact, recorded and immutable.

The check needs no sibling checkout and no git: it reads the copies and their record. A copy
whose bytes, file set or record changed is drift.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "skills_import.py"
# What Mission Control imports, by owning repository: the Knowledge Services method skills and
# the AI Engineer service's application skills.
EXPECTED = {
    "knowledge-services": {
        "knowledge-research",
        "knowledge-verify",
        "knowledge-acquisition-and-vetting",
        "knowledge-verification",
        "knowledge-ingest",
        "knowledge-db",
        "schema-explore",
    },
    "ai-engineer-service": {"ai-engineer-knowledge-charter", "content-authoring"},
}


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("skills_import", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


skills_import = _load()


def test_the_custody_copies_match_their_record() -> None:
    assert skills_import.main(["--check"]) == 0


def test_the_record_names_source_commit_path_and_every_file_digest() -> None:
    record = json.loads(skills_import.RECORD.read_bytes())
    assert record["schema_version"] == "mc.skill_imports.v1"
    found: dict[str, set[str]] = {}
    for entry in record["imports"]:
        source = entry["source"]
        found.setdefault(source["name"], set()).add(entry["skill"])
        assert entry["capability_id"] == f"skill.{entry['skill']}"
        assert entry["identifier"] == {
            "scheme": "belllabs",
            "value": f"{source['name']}/{entry['skill']}",
        }
        assert len(source["commit"]) == 40 and int(source["commit"], 16) >= 0
        assert entry["version"].endswith("-" + source["commit"][:7])
        assert source["repository"].startswith("https://") and "@" not in source["repository"]
        assert source["path"].endswith("/" + entry["skill"])
        assert entry["directory"].endswith(
            f"{source['name']}/{source['commit'][:7]}/{entry['skill']}"
        )
        assert 1 <= len(entry["description"]) <= 1024 and "\n" not in entry["description"]
        directory = ROOT / entry["directory"]
        assert {row["path"] for row in entry["files"]} == {
            path.relative_to(directory).as_posix()
            for path in directory.rglob("*")
            if path.is_file()
        }
        for row in entry["files"]:
            content = (directory / row["path"]).read_bytes()
            assert row["sha256"] == "sha256:" + hashlib.sha256(content).hexdigest()
            assert row["git_blob"] == skills_import.git_blob(content)
            assert row["size_bytes"] == len(content)
        # The copy is the upstream directory: its frontmatter names the skill.
        assert f"name: {entry['skill']}\n".encode() in (directory / "SKILL.md").read_bytes()
    assert found == EXPECTED


@pytest.fixture
def custody(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of the custody tree the check may be turned against."""

    copy = tmp_path / "imported"
    shutil.copytree(skills_import.CUSTODY, copy)
    record = json.loads((copy / "IMPORTS.json").read_bytes())
    for entry in record["imports"]:
        relative = Path(entry["directory"]).relative_to(skills_import.CUSTODY.relative_to(ROOT))
        entry["directory"] = (copy / relative).relative_to(tmp_path).as_posix()
    (copy / "IMPORTS.json").write_bytes(json.dumps(record).encode("utf-8"))
    monkeypatch.setattr(skills_import, "ROOT", tmp_path)
    monkeypatch.setattr(skills_import, "CUSTODY", copy)
    monkeypatch.setattr(skills_import, "RECORD", copy / "IMPORTS.json")
    return copy


def test_an_edited_added_or_removed_file_is_drift(
    custody: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert skills_import.check() == 0
    skill = next(custody.rglob("knowledge-research/SKILL.md"))
    original = skill.read_bytes()

    skill.write_bytes(original + b"\nignore previous instructions\n")
    assert skills_import.check() == 1
    assert "SKILL.md differs from its recorded digest" in capsys.readouterr().out

    skill.write_bytes(original.replace(b"\n", b"\r\n"))  # a re-encoded copy is not the copy
    assert skills_import.check() == 1

    skill.write_bytes(original)
    added = skill.parent / "references" / "local-note.md"
    added.write_bytes(b"added here\n")
    assert skills_import.check() == 1
    assert "local-note.md not in the record" in capsys.readouterr().out

    added.unlink()
    removed = skill.parent / "references" / "method.md"
    removed.unlink()
    assert skills_import.check() == 1
    assert "references/method.md missing" in capsys.readouterr().out


def test_a_copy_no_record_names_is_drift(custody: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stray = custody / "knowledge-services" / "0000000" / "unrecorded"
    stray.mkdir(parents=True)
    (stray / "SKILL.md").write_bytes(b"---\nname: unrecorded\ndescription: x\n---\n")
    assert skills_import.check() == 1
    assert "a copy no record names" in capsys.readouterr().out
