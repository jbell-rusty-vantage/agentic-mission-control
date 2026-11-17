"""docs/tools/trace.py: the provenance chain from answers files, specs, commits and Linear."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

REAL_ROOT = Path(__file__).resolve().parents[3]
TOOL = REAL_ROOT / "docs" / "tools" / "trace.py"

ANSWERS = """---
type: Interview Answers
title: "T, sitting I"
id: T-S1
family: T
harness_session: codex:abc
idea: ID-1
interview: ../SPEC.md#decisions
sitting: "I"
date: 2026-11-17
status: final
---

## Decisions

| ID | Source | Question | Answer | Date | What it changes | Becomes | Folded |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T-D1 | ID-1 | Build it? | "yes, build it" | 2026-11-17 | builds | OVE-9 | [spec](../SPEC.md#a) |
| T-D2 | ID-1 | Where? | "here" | 2026-11-17 | here | spec SPEC.md §2 | n/a |
"""

SPEC = """---
type: Specification
title: "The spec"
status: accepted
decisions: [T-D1, T-D2]
linear: [OVE-9]
---

# The spec
"""


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("trace_tool", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def commit(root: Path, message: str, date: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    write(
        root / "log.txt",
        (root / "log.txt").read_text() + message if (root / "log.txt").exists() else message,
    )
    run = [
        "git",
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "-c",
        "commit.gpgsign=false",
    ]
    subprocess.run([*run, "add", "-A"], cwd=root, check=True, env=env)
    subprocess.run([*run, "commit", "-q", "-m", message], cwd=root, check=True, env=env)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> dict[str, str]:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    write(
        tmp_path / "docs/knowledge/goals.md",
        '# Goals\n\n## Goal: deployment\n\n<a id="SDLC"></a>x\n',
    )
    write(tmp_path / "docs/adr/0001-one.md", "# ADR-0001 One\n")
    write(tmp_path / "docs/specs/p/SPEC.md", SPEC)
    write(tmp_path / "docs/specs/p/answers/T-SITTING-I-ANSWERS.md", ANSWERS)
    return {
        "legacy": commit(tmp_path, "chore: old work", "2026-11-01T10:00:00+00:00"),
        "good": commit(
            tmp_path,
            "feat(x): build it\n\nRefs: OVE-9, T-S1\nDecisions: T-D1\nDocs: none test",
            "2026-11-18T10:00:00+00:00",
        ),
        "bare": commit(tmp_path, "fix(x): no trailer", "2026-11-18T11:00:00+00:00"),
    }


@pytest.fixture
def tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo: dict[str, str]) -> ModuleType:
    module = load_tool()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    return module


def snapshot(tool: ModuleType, good_sha: str, *, completion: bool = True) -> None:
    comments = (
        [
            f"## Completion\n\nCommits: mission-control@{good_sha[:8]}\nChecks: tests passed\n"
            "Evidence: none (unit)\nLevel: tested\nVerified-by: self"
        ]
        if completion
        else []
    )
    tool.write_snapshot(
        [
            {
                "identifier": "OVE-9",
                "title": "Build the thing",
                "url": "https://linear.example/OVE-9",
                "description": "Goal: platform/mission-control/goals#SDLC\n\nBody.\n\n"
                "## Provenance\n\n"
                "Session: T-S1\nDecisions: T-D1\nSpec: mission-control:docs/specs/p/SPEC.md#a\n",
                "created_at": "2026-11-17T12:00:00Z",
                "completed_at": "2026-11-18T12:00:00Z",
                "state": "Done",
                "state_type": "completed",
                "parent": "OVE-1",
                "comments": comments,
            }
        ],
        source="test",
        complete=True,
    )


def test_trailers_are_the_last_paragraph_only() -> None:
    tool = load_tool()
    assert tool.parse_trailers("feat: x\n\nRefs: OVE-1\nDecisions: AS-D2") == {
        "refs": ["OVE-1"],
        "decisions": ["AS-D2"],
    }
    assert tool.parse_trailers("feat: x\n\nRefs: OVE-1\nnot a trailer") == {}
    assert tool.parse_trailers("feat: x (OVE-3)") == {}
    info = tool.commit_refs("feat: x (OVE-3)", {"refs": ["AS-S3, B08-S29"]})
    assert info["refs"] == ["AS-S3", "B08-S29", "OVE-3"]


def test_a_commit_message_without_refs_is_a_gap_and_a_resolvable_one_is_not(
    tool: ModuleType,
) -> None:
    graph = tool.load()
    assert tool.message_problems(graph, "feat: x\n\nbody")[0].startswith("this commit: no Refs:")
    assert tool.message_problems(graph, "feat: x\n\nRefs: T-S1\nDecisions: T-D1") == []
    assert tool.message_problems(graph, "chore: y\n\nRefs: none formatting only") == []
    unknown = tool.message_problems(graph, "feat: x\n\nRefs: T-S9")
    assert "T-S9 does not resolve" in unknown[0]
    assert tool.message_problems(graph, "Merge branch 'x'") == []
    assert "names no id" in tool.message_problems(graph, "feat: x\n\nRefs: soon")[0]


def test_check_flags_new_gaps_and_never_legacy_commits(
    tool: ModuleType, repo: dict[str, str]
) -> None:
    snapshot(tool, repo["good"])
    problems = tool.check_all(tool.load(), None)
    assert len(problems) == 1 and problems[0].startswith(f"commit {repo['bare'][:8]}")
    assert tool.check_all(tool.load(), f"{repo['good']}..{repo['bare']}") == problems


def test_a_completed_issue_needs_a_completion_comment(
    tool: ModuleType, repo: dict[str, str]
) -> None:
    snapshot(tool, repo["good"], completion=False)
    problems = tool.check_all(tool.load(), None)
    assert any("OVE-9: completed without a `## Completion`" in p for p in problems)


def test_an_unknown_goal_anchor_and_missing_session_fields_are_gaps(
    tool: ModuleType, tmp_path: Path
) -> None:
    write(
        tmp_path / "docs/specs/p/answers/U-ANSWERS.md",
        "---\ntype: Interview Answers\ninterview: ../SPEC.md\n"
        "date: 2026-11-18\nstatus: open\n---\n",
    )
    graph = tool.load()
    assert not tool.goal_resolves(graph, "platform/mission-control/goals#nowhere")
    assert tool.goal_resolves(graph, "platform/mission-control/goals#goal-deployment")
    assert tool.goal_resolves(graph, "IG1")
    fields = [p for p in tool.check_all(graph, None) if "U-ANSWERS" in p]
    assert len(fields) == 3


def test_show_prints_the_whole_chain(
    tool: ModuleType, repo: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    snapshot(tool, repo["good"])
    assert tool.show("T-S1", as_json=False) == 0
    out = capsys.readouterr().out
    for expected in (
        "T-S1",
        'owner: "yes, build it"',
        "docs/specs/p/SPEC.md",
        "OVE-9  [Done]  Build the thing",
        "completion: Commits mission-control@",
        "Level tested",
        "feat(x): build it",
    ):
        assert expected in out
    assert "chore: old work" not in out and "OVE-1" in out  # the parent is shown, not walked
    assert tool.show(repo["good"][:8], as_json=True) == 0
    chain = json.loads(capsys.readouterr().out)
    assert {"OVE-9", "T-S1", "T-D1"} <= set(chain["nodes"])
    assert tool.show("NOPE-S1", as_json=False) == 3


def test_build_writes_the_trace_and_coverage(
    tool: ModuleType, repo: dict[str, str], tmp_path: Path
) -> None:
    snapshot(tool, repo["good"])
    assert tool.build() == 0
    trace = json.loads((tmp_path / ".sdlc/trace/trace.json").read_text(encoding="utf-8"))
    stats = trace["summary"]
    assert stats["commits_since_cutover"] == 2 and stats["with_refs"] == 1
    assert stats["reaching_an_issue"] == 1 and stats["legacy_commits"] == 1
    assert "## Gaps (1)" in (tmp_path / ".sdlc/trace/COVERAGE.md").read_text(encoding="utf-8")


def test_warn_mode_reports_and_block_mode_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    tool = load_tool()
    assert tool.report(["x: gap"], "warn") == 0
    assert tool.report(["x: gap"], "block") == 1
    assert tool.report([], "block") == 0
    assert "trace [warn]: x: gap" in capsys.readouterr().err
