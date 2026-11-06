"""Foundation renderer boundaries; canonical materialization is tested separately."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from mission_control.application.chains.service import ManifestStructureService


@pytest.fixture
def renderer(monkeypatch):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "foundation_renderer", scripts / "report_source_foundation.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("app", ["ai-engineer", "biotech"])
@pytest.mark.parametrize("shape", ["repair", "transfer"])
def test_separate_shapes_compile_and_never_admit_native_writes(
    renderer, tmp_path, monkeypatch, app, shape
):
    context = tmp_path / "context"
    context.mkdir()
    (context / "context.txt").write_text(
        "Selected operational report/source contracts.\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        renderer, "verify_context", lambda _: {"profile": f"report-source-foundation-{app}.v1"}
    )
    out = tmp_path / "fixture"
    evidence = renderer.render_fixture(app=app, shape=shape, context_dir=context, output=out)
    text = (out / "mission.yml").read_text(encoding="utf-8")
    rendered = (
        text.replace("__PACK__", "{}")
        .replace("__PRODUCER__", "producer.default")
        .replace("__CONSUMER__", "producer.fallback")
    )
    compiled = ManifestStructureService().compile(rendered)
    assert compiled.ok, compiled.blockers
    mission = yaml.safe_load(text)["mission"]
    assert mission["program"]["behavior"] == ("goal_loop" if shape == "repair" else "stage_graph")
    assert mission["environment"]["governors"]["iterations"] == (3 if shape == "repair" else 1)
    assert evidence["qualified"] is False
    assert evidence["local_replay_scope"]["source_count"] == (2 if app == "ai-engineer" else 1)
    assert evidence["local_replay_scope"]["search_admitted"] is False
    if shape == "repair":
        instruction = mission["goals"][0]["description"]
        assert "increment revision by one" in instruction
        assert 'supersedes={"handle": previous_handle, "digest": previous_digest}' in instruction
        assert '"revision":1' not in instruction
        assert "Stop; never repeat" not in instruction
    assert "Selected operational report/source contracts." in text
    assert not any("native" in c["pin"] for c in mission["environment"]["capabilities"])
    with pytest.raises(ValueError, match="fresh"):
        renderer.render_fixture(app=app, shape=shape, context_dir=context, output=out)


def test_context_failure_and_wrong_domain_do_not_create_fixture(renderer, tmp_path, monkeypatch):
    out = tmp_path / "fixture"
    monkeypatch.setattr(
        renderer, "verify_context", lambda _: {"profile": "report-source-foundation-biotech.v1"}
    )
    with pytest.raises(ValueError, match="another application"):
        renderer.render_fixture(app="ai-engineer", shape="repair", context_dir=tmp_path, output=out)
    assert not out.exists()

    def refuse(_):
        raise ValueError("manifest digest mismatch")

    monkeypatch.setattr(renderer, "verify_context", refuse)
    with pytest.raises(ValueError, match="digest"):
        renderer.render_fixture(app="biotech", shape="transfer", context_dir=tmp_path, output=out)
    assert not out.exists()
