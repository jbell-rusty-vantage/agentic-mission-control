"""Fail-closed fixture context composition without databases or model calls."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "report_source_context",
    Path(__file__).resolve().parents[2] / "scripts/report_source_context.py",
)
assert SPEC and SPEC.loader
context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(context)


def bundle(tmp_path, monkeypatch, *, budget=10000):
    root = tmp_path / "workspace"
    shared = root / context.KS / "record.ts"
    shared.parent.mkdir(parents=True)
    shared.write_text('import { z } from "zod";\nexport const Record = z.string();\n')
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "format": "mc-report-source-context-profile.v1",
                "id": "test.v1",
                "application": "ai-engineer",
                "task_scope": "compare",
                "audience": "reviewer",
                "use": "report",
                "report_kind": "evidence_report@1.0.0",
                "qualifier_profile": "engineering.v2",
                "authority": "read-only",
                "shared_contracts": ["record.ts"],
                "navigation_cards": ["tasks/read.md"],
                "max_context_bytes": budget,
            }
        )
    )

    def domain(workspace, profile, out):
        card = out / "domain/tasks/read.md"
        card.parent.mkdir(parents=True)
        card.write_text("Read only. [omitted](../native.md)\n")
        return {
            "retained_vocabularies": 12,
            "selection": {"omitted": {"relations": 10}},
            "closure": "navigation-only",
        }

    monkeypatch.setattr(context, "_domain", domain)
    return root, profile


def test_repeatable_bytes_and_explicit_navigation_omissions(tmp_path, monkeypatch):
    root, profile = bundle(tmp_path, monkeypatch)
    first = context.materialize_context(root, profile, tmp_path / "one")
    second = context.materialize_context(root, profile, tmp_path / "two")
    assert first == second
    assert first["navigation_omissions"][0]["target"] == "domain/native.md"
    assert first["external_dependencies"] == ["zod"]
    assert context.verify_context(tmp_path / "one", first["manifest_digest"]) == first


@pytest.mark.parametrize("mutation", ["tamper", "missing", "extra", "manifest"])
def test_modified_bundle_refused(tmp_path, monkeypatch, mutation):
    root, profile = bundle(tmp_path, monkeypatch)
    out = tmp_path / "out"
    manifest = context.materialize_context(root, profile, out)
    if mutation == "tamper":
        (out / "context.txt").write_text("different")
    elif mutation == "missing":
        (out / "shared/record.ts").unlink()
    elif mutation == "extra":
        (out / "extra.txt").write_text("unselected")
    else:
        (out / "manifest.json").write_text(
            (out / "manifest.json").read_text().replace('"test.v1"', '"other.v1"')
        )
    with pytest.raises(ValueError):
        context.verify_context(out, manifest["manifest_digest"])


def test_byte_cap_is_enforced_and_existing_output_preserved(tmp_path, monkeypatch):
    root, profile = bundle(tmp_path, monkeypatch, budget=1)
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="byte budget"):
        context.materialize_context(root, profile, out)
    with pytest.raises(ValueError, match="fresh"):
        context.materialize_context(root, profile, out)


def test_missing_dependency_and_path_escape_fail_closed(tmp_path):
    (tmp_path / "record.ts").write_text('import { X } from "./missing.js";')
    with pytest.raises(FileNotFoundError):
        context.contract_closure(tmp_path, ["record.ts"])
    with pytest.raises(ValueError, match="escapes"):
        context.confined(tmp_path, "../outside")


def test_materializer_failure_is_not_a_context(tmp_path, monkeypatch):
    class Failed:
        returncode = 2
        stderr = "canonical source unavailable"

    monkeypatch.setattr(context.subprocess, "run", lambda *args, **kwargs: Failed())
    with pytest.raises(RuntimeError, match="canonical source unavailable"):
        context._run(["node", "materializer"], tmp_path)
