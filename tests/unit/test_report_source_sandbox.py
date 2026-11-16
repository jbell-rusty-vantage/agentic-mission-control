"""Portable fixture packaging must preserve identity and avoid implicit capability grants."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def package(tmp_path, monkeypatch):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "sandbox_fixture", scripts / "report_source_sandbox.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = tmp_path / "context"
    context.mkdir()
    (context / "manifest.json").write_text("{}", encoding="utf-8")
    # The two entity task pages come from the AI Engineer contract checkout the script is
    # pointed at. This test packages stand-in pages: it proves the inventory, the digests and
    # the custody of the Knowledge Services skills, not that repository's current text.
    tasks = tmp_path / "ai-engineer-db-contract" / "workspace" / "tasks"
    tasks.mkdir(parents=True)
    for name in ("find-entity-by-identifier.md", "what-do-we-know-about-entity.md"):
        (tasks / name).write_text(f"# {name}\n\nFIXTURE task page.\n", encoding="utf-8")
    monkeypatch.setenv(module.AIDB_CHECKOUT_ENV, str(tasks.parents[1]))
    monkeypatch.setattr(
        module,
        "verify_context",
        lambda _: {"profile": "report-source-foundation-ai-engineer.v1", "selected": []},
    )
    out = tmp_path / "out"
    manifest = module.prepare(context, out)
    return module, context, out, manifest


def test_deterministic_exact_inventory_and_fresh_output(package, tmp_path):
    module, context, out, manifest = package
    assert module.prepare(context, tmp_path / "second") == manifest
    assert module.verify(out, expected_digest=manifest["digest"]) == manifest
    assert len(manifest["skills"]) == 6
    assert manifest["qualified"] is False
    # The Knowledge Services skills come from this repository's custody copies (exact imports
    # at one commit), never from a sibling checkout, and enter the sandbox unchanged.
    custody = "/packages/mission-control-db-contract/bundle-sources/imported/knowledge-services/"
    for name in module.CANONICAL:
        rows = [
            row
            for destination, row in manifest["provenance"].items()
            if destination.startswith(f"sandbox/skills/{name}/")
            and "/workspace/tasks/" not in destination
        ]
        assert rows and all(custody in row["source"] for row in rows), name
        assert {row["transform"] for row in rows} == {"none"}, name
    tasks = {
        destination: row
        for destination, row in manifest["provenance"].items()
        if "/workspace/tasks/" in destination
    }
    assert len(tasks) == 2
    assert all(
        row["source"].startswith("aiengineer/ai-engineer-db-contract/workspace/tasks/")
        for row in tasks.values()
    )
    with pytest.raises(ValueError, match="fresh"):
        module.prepare(context, out)
    with pytest.raises(ValueError, match="pinned"):
        module.verify(out, expected_digest="sha256:wrong")


def test_changed_or_extra_skill_bytes_refuse(package):
    module, _, out, manifest = package
    target = out / next(iter(manifest["files"]))
    original = target.read_bytes()
    target.write_bytes(original + b"\nchanged")
    with pytest.raises(ValueError, match="file digest"):
        module.verify(out)
    target.write_bytes(original)
    (out / "untracked-instruction.md").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError, match="inventory"):
        module.verify(out)
