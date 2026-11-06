"""docs/tools/program_ledger.py: link-safe moves, the central archive, strict checks."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from types import ModuleType

import pytest

REAL_ROOT = Path(__file__).resolve().parents[3]
TOOL = REAL_ROOT / "docs" / "tools" / "program_ledger.py"
DATE = "2026-10-23"


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("program_ledger", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = load_tool()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    template = tmp_path / module.TEMPLATE
    template.parent.mkdir(parents=True)
    shutil.copy(REAL_ROOT / module.TEMPLATE, template)
    return module


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


LEDGER = """# Ledger

## Specs

| ID | Item | Status | Linear | Progress |
| --- | --- | --- | --- | --- |
| SP-01 | [Brief](BRIEF.md) | done | - | x |
| SP-02 | [Stage](providers/lane/STAGE.md) | done | OVE-12 | x |
| SP-03 | [Readme](README.md) | active | - | x |
| SP-04 | [Other](providers/lane/OTHER.md) | active | - | x |
"""


@pytest.fixture
def program(tool: ModuleType, tmp_path: Path) -> Path:
    root = tmp_path / "docs" / "specs" / "prog"
    write(root / "LEDGER.md", LEDGER)
    write(
        root / "README.md",
        "# R\n\nSee [brief](BRIEF.md) and [stage](providers/lane/STAGE.md#goal).\n"
        "Fixtures: [dir](fixtures/).\n",
    )
    write(root / "fixtures" / "a.yml", "a: 1\n")
    write(
        root / "BRIEF.md",
        "---\ntype: Spec\ntitle: Brief\n---\n\n# Brief\n\nBack to [R](README.md).\n",
    )
    write(
        root / "providers" / "lane" / "STAGE.md",
        "---\ntype: Spec\ntitle: Stage\n---\n\n# Stage\n\n## Goal\n\n"
        "Read [the brief](../../BRIEF.md) and [sibling](OTHER.md).\n"
        "Code `[x](BRIEF.md)` stays.\n\n```text\n[y](BRIEF.md)\n```\n\n"
        "Mentioned as providers/lane/STAGE.md in prose.\n",
    )
    write(root / "providers" / "lane" / "OTHER.md", "# Other\n\nSee [stage](STAGE.md).\n")
    return root


def test_archive_goes_to_the_central_archive_and_rewrites_links(
    tool: ModuleType, program: Path
) -> None:
    source = program / "providers" / "lane" / "STAGE.md"
    assert tool.archive(program, source, "sessions", "stage done", DATE, False) == 0

    moved = program.parent / "archive" / "prog" / "sessions" / "STAGE.md"
    assert moved.is_file() and not source.exists()
    text = read(moved)
    assert "status: archived" in text and f"archived: {DATE}" in text
    assert "archived_from: providers/lane/STAGE.md" in text
    assert "[ledger](../../../prog/LEDGER.md)" in text
    assert "[the brief](../../../prog/BRIEF.md)" in text
    assert "[sibling](../../../prog/providers/lane/OTHER.md)" in text
    assert "`[x](BRIEF.md)`" in text and "[y](BRIEF.md)" in text  # code is never rewritten
    assert "docs/specs/archive/prog/sessions/STAGE.md in prose" in text

    assert "(../archive/prog/sessions/STAGE.md#goal)" in read(program / "README.md")
    other = read(program / "providers" / "lane" / "OTHER.md")
    assert "(../../../archive/prog/sessions/STAGE.md)" in other
    assert "(../archive/prog/sessions/STAGE.md)" in read(program / "LEDGER.md")


def test_archiving_a_root_file_does_not_double_the_path(tool: ModuleType, program: Path) -> None:
    assert tool.archive(program, program / "BRIEF.md", "specs", "", DATE, False) == 0
    readme = read(program / "README.md")
    assert "(../archive/prog/specs/BRIEF.md)" in readme and "specs/archive/prog" not in readme


def test_dry_run_changes_nothing(tool: ModuleType, program: Path, tmp_path: Path) -> None:
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert tool.archive(program, program / "BRIEF.md", "specs", "", DATE, True) == 0
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_archive_refuses_bad_requests(tool: ModuleType, program: Path) -> None:
    assert tool.archive(program, program / "BRIEF.md", "nonsense", "", DATE, False) == 2
    assert tool.archive(program, program / "LEDGER.md", "docs", "", DATE, False) == 2
    assert (
        tool.archive(program, program / "providers" / "lane" / "x.txt", "docs", "", DATE, False)
        == 2
    )


def test_check_requires_status_to_follow_location(tool: ModuleType, program: Path) -> None:
    assert tool.check(program) == 0
    assert tool.archive(program, program / "BRIEF.md", "specs", "", DATE, False) == 0
    assert tool.check(program) == 1  # the row still says done but the file is archived
    ledger = program / "LEDGER.md"
    ledger.write_text(
        read(ledger).replace("| done | - | x |", "| archived | - | x |", 1), encoding="utf-8"
    )
    assert tool.check(program) == 0


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("| done | OVE-12 |", "| wip | OVE-12 |"),
        ("| done | OVE-12 |", "| done | OVE-x |"),
        ("[Brief](BRIEF.md)", "[Brief](GONE.md)"),
    ],
)
def test_check_rejects_bad_rows(tool: ModuleType, program: Path, old: str, new: str) -> None:
    ledger = program / "LEDGER.md"
    ledger.write_text(read(ledger).replace(old, new, 1), encoding="utf-8", newline="\n")
    assert tool.check(program) == 1


def test_check_requires_every_document_in_the_ledger(tool: ModuleType, program: Path) -> None:
    write(program / "NEW.md", "# New\n")
    assert tool.check(program) == 1


def test_archive_adds_frontmatter_to_a_document_without_any(
    tool: ModuleType, program: Path
) -> None:
    bare = write(program / "BARE.md", "# Bare\n\nNo front matter.\n")
    assert tool.archive(program, bare, "docs", "obsolete", DATE, False) == 0
    text = read(program.parent / "archive" / "prog" / "docs" / "BARE.md")
    assert text.startswith("---\nstatus: archived\n")
    assert 'archived_reason: "obsolete"' in text and "# Bare" in text


def test_move_keeps_links_to_a_folder(tool: ModuleType, program: Path, tmp_path: Path) -> None:
    dest = tmp_path / "tests" / "fixtures" / "prog"
    assert tool.move(program / "fixtures", dest, False) == 0
    assert (dest / "a.yml").is_file() and not (program / "fixtures").exists()
    assert "(../../../tests/fixtures/prog)" in read(program / "README.md").replace("/)", ")")


def test_archive_program_moves_everything_and_indexes_it(tool: ModuleType, program: Path) -> None:
    index = write(
        program.parent / "archive" / "README.md",
        "# Archive\n\n| Program | Archived | Why |\n| --- | --- | --- |\n"
        "<!-- archived-programs:end -->\n",
    )
    assert tool.archive_program(program, "finished", DATE, False) == 0
    moved = program.parent / "archive" / "prog"
    assert (moved / "providers" / "lane" / "STAGE.md").is_file() and not program.exists()
    readme = read(moved / "README.md")
    assert "status: archived" in readme and "[archive index](../README.md)" in readme
    assert "[the brief](../../BRIEF.md)" in read(moved / "providers" / "lane" / "STAGE.md")
    assert "| [prog](prog/README.md) | 2026-10-23 | finished |" in read(index)


def test_archive_program_refuses_other_folders(
    tool: ModuleType, program: Path, tmp_path: Path
) -> None:
    assert tool.archive_program(tmp_path / "docs", "", DATE, False) == 2


def interview(program: Path) -> Path:
    return write(program / "INTERVIEW-X-2026-10-23.md", "# Interview\n")


def test_new_answers_scaffolds_from_the_template(tool: ModuleType, program: Path) -> None:
    instruction = interview(program)
    assert tool.new_answers("DEEP-AGENTS", "I", instruction, program, DATE) == 0
    created = program / "answers" / "DEEP-AGENTS-SITTING-I-2026-10-23-ANSWERS.md"
    text = read(created)
    assert "type: Interview Answers" in text and "interview: ../INTERVIEW-X-2026-10-23.md" in text
    assert "{{" not in text
    assert tool.new_answers("DEEP-AGENTS", "I", instruction, program, DATE) == 2  # never overwrites


def answers_file(program: Path, status: str, row: str) -> Path:
    interview(program)
    return write(
        program / "answers" / "A-ANSWERS.md",
        "---\ntype: Interview Answers\ninterview: ../INTERVIEW-X-2026-10-23.md\n"
        f"status: {status}\n---\n\n"
        "## Decisions\n\n| ID | Question | Answer | Date | What it changes | Becomes | Folded |\n"
        f"| --- | --- | --- | --- | --- | --- | --- |\n{row}\n",
    )


def ledger_with_answers(program: Path) -> None:
    ledger = program / "LEDGER.md"
    ledger.write_text(
        read(ledger)
        + "| SP-05 | [Instruction](INTERVIEW-X-2026-10-23.md) | open | - | x |\n"
        + "| SP-06 | [Answers](answers/A-ANSWERS.md) | open | - | x |\n",
        encoding="utf-8",
        newline="\n",
    )


def test_open_answers_may_be_incomplete_final_ones_may_not(tool: ModuleType, program: Path) -> None:
    ledger_with_answers(program)
    answers_file(program, "open", "| D1 | q | a | 2026-10-23 | c | | |")
    assert tool.check(program) == 0
    answers_file(program, "final", "| D1 | q | a | 2026-10-23 | c | OVE-3 | n/a |")
    assert tool.check(program) == 0
    answers_file(program, "final", "| D1 | q | a | 2026-10-23 | c | ADR-0058 | |")
    assert tool.check(program) == 1


def test_answers_must_resolve_their_interview(tool: ModuleType, program: Path) -> None:
    ledger_with_answers(program)
    path = answers_file(program, "open", "| D1 | q | a | d | c | | |")
    path.write_text(
        read(path).replace("../INTERVIEW-X-2026-10-23.md", "../GONE.md"), encoding="utf-8"
    )
    assert tool.check(program) == 1
