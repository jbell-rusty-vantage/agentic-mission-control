"""docs/tools/agents_docs_index.py: module registry, generated module blocks and their budgets."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

REAL_ROOT = Path(__file__).resolve().parents[3]
TOOL = REAL_ROOT / "docs" / "tools" / "agents_docs_index.py"


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("agents_docs_index_under_test", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def entry(**fields: object) -> dict[str, object]:
    base: dict[str, object] = {"title": "Title", "purpose": "Does one thing. Then another."}
    base.update(fields)
    return base


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[tuple[ModuleType, Path]]:
    tool = load_tool()
    tool.configure(tmp_path)
    write(tmp_path / "src/mission_control/__init__.py", '"""Package."""\n')
    write(tmp_path / "src/mission_control/domain/__init__.py", '"""Pure rules."""\n')
    write(
        tmp_path / "src/mission_control/domain/rules.py",
        '"""Decide the next step (ADR-0001). More detail follows."""\n',
    )
    write(
        tmp_path / "src/mission_control/adapters/foo/__init__.py",
        '"""Foo adapter."""\nfrom mission_control.domain import rules\n',
    )
    write(tmp_path / "src/mission_control/adapters/foo/client.py", '"""Talks to foo."""\n')
    write(tmp_path / "tests/unit/foo/test_foo.py", "def test_foo():\n    pass\n")
    write(
        tmp_path / "docs/knowledge/rules.md",
        "---\ntype: Concept\n---\n# Rules\n\nBody.\n\n## Citations\n\n"
        "- Code: [rules](../../src/mission_control/domain/rules.py)\n"
        "- ADR: [one](../adr/0001-first.md)\n",
    )
    write(tmp_path / "docs/adr/0001-first.md", "# First\n")
    modules = {
        "version": 1,
        "modules": [
            entry(
                id="domain",
                path="src/mission_control/domain",
                invariants=["Pure."],
                verify=["make test-arch"],
            ),
            entry(
                id="adapters.foo",
                path="src/mission_control/adapters/foo",
                tests=["tests/unit/foo"],
                pin_first=1,
            ),
        ],
    }
    write(tmp_path / ".sdlc/modules.json", json.dumps(modules))
    yield tool, tmp_path
    tool.configure(REAL_ROOT)


def build(tool: ModuleType):
    modules, problems = tool.load_modules()
    assert problems == []
    return modules, tool.build_context(modules)


def by_id(modules, module_id: str):
    return next(m for m in modules if m.id == module_id)


def test_new_file_holds_only_the_block_with_derived_sections(repo) -> None:
    tool, _root = repo
    modules, ctx = build(tool)
    domain = by_id(modules, "domain")
    text = tool.render_module_file(domain, ctx, None)
    assert text.startswith("<!-- BEGIN:sdlc-module id=domain -->\n# Title\n")
    assert text.endswith("<!-- END:sdlc-module -->\n")
    assert "- rules.py — Decide the next step" in text
    assert "Explained by (docs/knowledge): rules" in text
    assert "Decided by (docs/adr): ADR-0001" in text
    assert "Used by: adapters.foo" in text
    assert "Verify: make test-arch" in text
    foo = tool.render_module_file(by_id(modules, "adapters.foo"), ctx, None)
    assert "Depends on: domain" in foo
    assert "Tests: tests/unit/foo" in foo


def test_hand_written_text_is_preserved_byte_for_byte(repo) -> None:
    tool, _root = repo
    modules, ctx = build(tool)
    domain = by_id(modules, "domain")
    prefix = "# Hand written\r\n\r\nKeep\tthis — exactly.\r\n"
    suffix = "\r\nTrailing hand-written note.\r\n"
    appended = tool.render_module_file(domain, ctx, prefix)
    assert appended.startswith(prefix)
    assert "\r\n<!-- BEGIN:sdlc-module id=domain -->\r\n## Title\r\n" in appended
    assert "\n" not in appended.replace("\r\n", "")
    refreshed = tool.render_module_file(domain, ctx, appended + suffix.lstrip("\r\n"))
    head, _, tail = refreshed.partition("<!-- END:sdlc-module -->")
    assert head.startswith(prefix)
    assert tail == "\r\n" + suffix.lstrip("\r\n")

    changed = replace(domain, purpose="Changed.")
    again = tool.render_module_file(changed, ctx, refreshed)
    assert again.startswith(prefix)
    assert again.endswith(tail)
    assert "Changed." in again and "Does one thing" not in again


def test_block_generation_is_idempotent(repo) -> None:
    tool, _root = repo
    modules, ctx = build(tool)
    for module in modules:
        first = tool.render_module_file(module, ctx, "# Existing\n")
        assert tool.render_module_file(module, ctx, first) == first
        assert tool.render_module_file(module, ctx, None) == tool.render_module_file(
            module, ctx, tool.render_module_file(module, ctx, None)
        )


def test_block_over_budget_is_a_failure_and_long_hand_text_a_warning(repo) -> None:
    tool, _root = repo
    modules, ctx = build(tool)
    domain = by_id(modules, "domain")
    huge = replace(domain, purpose="Word " * 700)
    text = tool.render_module_file(huge, ctx, None)
    failures, warnings = tool.module_budget_report(huge, text)
    assert any("block is" in f and "budget 2048" in f for f in failures)
    assert warnings == []

    fine = tool.render_module_file(domain, ctx, "x" * 3000 + "\n")
    failures, warnings = tool.module_budget_report(domain, fine)
    assert failures == []
    assert any("hand-written text" in w and "budget 2048" in w for w in warnings)


def test_missing_paths_fail_the_check(repo, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    tool, root = repo
    registry = json.loads((root / ".sdlc/modules.json").read_text(encoding="utf-8"))
    registry["modules"].append(
        entry(id="ghost", path="src/mission_control/ghost", tests=["tests/unit/nope"])
    )
    (root / ".sdlc/modules.json").write_text(json.dumps(registry), encoding="utf-8")
    _, problems = tool.load_modules()
    assert any("path src/mission_control/ghost does not exist" in p for p in problems)
    assert any("test path tests/unit/nope does not exist" in p for p in problems)
    monkeypatch.setattr(sys, "argv", ["agents_docs_index.py", "--check"])
    assert tool.main() == 1
    assert "ghost" in capsys.readouterr().err


def test_depth_and_map_line_rules(repo) -> None:
    tool, root = repo
    write(root / "src/mission_control/adapters/foo/deep/inner/__init__.py", "")
    registry = json.loads((root / ".sdlc/modules.json").read_text(encoding="utf-8"))
    registry["modules"].append(
        entry(id="too.deep", path="src/mission_control/adapters/foo/deep/inner")
    )
    registry["modules"].append(
        entry(id="long", path="tests/unit/foo", purpose="L" * (tool.MAP_LINE_MAX + 1))
    )
    (root / ".sdlc/modules.json").write_text(json.dumps(registry), encoding="utf-8")
    _, problems = tool.load_modules()
    assert any("too.deep" in p and "deeper than two levels" in p for p in problems)
    assert any("long" in p and "first purpose sentence" in p for p in problems)


def test_code_map_is_pinned_then_by_path_without_repeating_the_target(repo) -> None:
    tool, _root = repo
    modules, _ = build(tool)
    lines = tool.code_map_lines(modules)
    assert lines == [
        "src/mission_control/adapters/foo — Does one thing",
        "src/mission_control/domain — Does one thing",
    ]
    assert tool.first_sentence("A b (c). D e.") == "A b (c)"
    assert tool.first_sentence("mc.v1 stays whole. Next.") == "mc.v1 stays whole"
