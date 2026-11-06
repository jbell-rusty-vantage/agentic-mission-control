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
    assert any("add missing name" in row["transform"] for row in manifest["provenance"].values())
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
