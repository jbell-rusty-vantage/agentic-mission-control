"""docs/tools/check_links.py: links inside the repository always resolve; a link that leaves it
is checked when its neighbour is present and counted, never failed, in a lone checkout."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

TOOL = Path(__file__).resolve().parents[3] / "docs" / "tools" / "check_links.py"


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_links_under_test", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module while it executes
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def repository(tmp_path: Path) -> Path:
    """`<workspace>/platform/repo` with one guide that links inside and outside itself."""

    root = tmp_path / "workspace" / "platform" / "repo"
    write(root / "docs" / "present.md", "# Present\n\n## A section\n")
    write(
        root / "docs" / "guide.md",
        "\n".join(
            (
                "[inside](present.md#a-section)",
                "[sibling](../../sibling/README.md#start)",
                "[workspace](../../../docs/navigation/MAP.md)",
                "[workspace file](../../../AGENTS.md)",
                "",
            )
        ),
    )
    return root


def reasons(report: dict[str, object], key: str) -> list[tuple[str, str]]:
    return [(item["target"], item["reason"]) for item in report[key]]  # type: ignore[union-attr]


def test_a_lone_checkout_counts_the_links_that_leave_it_and_fails_none(
    tool: ModuleType, tmp_path: Path
) -> None:
    root = repository(tmp_path)
    report = tool.run(root=root)
    assert report["files_checked"] == 2 and report["broken_count"] == 0
    assert reasons(report, "outside_unchecked") == [
        ("../../sibling/README.md#start", "outside this repository"),
        ("../../../docs/navigation/MAP.md", "outside this repository"),
        ("../../../AGENTS.md", "outside this repository"),
    ]


def test_a_missing_target_inside_the_repository_is_always_broken(
    tool: ModuleType, tmp_path: Path
) -> None:
    root = repository(tmp_path)
    write(root / "docs" / "stale.md", "[gone](absent.md)\n[anchor](present.md#no-such)\n")
    report = tool.run(root=root)
    assert reasons(report, "broken") == [
        ("absent.md", "missing target"),
        ("present.md#no-such", "missing anchor"),
    ]
    assert report["outside_unchecked_count"] == 3


def test_a_neighbour_that_is_present_is_checked_like_any_other_target(
    tool: ModuleType, tmp_path: Path
) -> None:
    root = repository(tmp_path)
    workspace = tmp_path / "workspace"
    # The sibling checkout and the workspace documents exist; one file and one anchor do not.
    write(workspace / "platform" / "sibling" / "README.md", "# Other heading\n")
    write(workspace / "docs" / "navigation" / "OTHER.md", "# Other\n")
    write(workspace / "AGENTS.md", "# Workspace\n")
    report = tool.run(root=root)
    assert reasons(report, "broken") == [
        ("../../sibling/README.md#start", "missing anchor"),
        ("../../../docs/navigation/MAP.md", "missing target"),
    ]
    assert report["outside_unchecked_count"] == 0


def test_the_command_reports_what_it_could_not_check_and_still_passes(
    tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    root = repository(tmp_path)
    run = tool.run
    monkeypatch.setattr(
        tool, "run", lambda *, check_anchors=True: run(check_anchors=check_anchors, root=root)
    )
    assert tool.main([]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-2].startswith("not checked: 3 links to files outside this repository")
    assert lines[-1] == "checked 2 files; broken links: 0"
    write(root / "docs" / "stale.md", "[gone](absent.md)\n")
    assert tool.main([]) == 1
