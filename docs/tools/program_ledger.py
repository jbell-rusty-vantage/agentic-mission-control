#!/usr/bin/env python3
"""Keep a program's LEDGER.md honest, and move or archive documents without breaking links.

A *program* is a folder such as ``docs/specs/provider-consolidation-2026-10`` that holds a
``LEDGER.md`` (the pointer and progress register), live documents and an ``answers/`` folder for
interview answers. Finished work goes to the ONE central archive, ``docs/specs/archive/``:
single documents to ``docs/specs/archive/<program>/<kind>/``, whole finished programs to
``docs/specs/archive/<program>/``. Convention: ``docs/agents/program-workspace.md``.

Usage:
  python docs/tools/program_ledger.py check [--program docs/specs/<program>]
  python docs/tools/program_ledger.py archive <file> --kind sessions --reason "Stage 3 done"
  python docs/tools/program_ledger.py archive-program docs/specs/<program> --reason "..."
  python docs/tools/program_ledger.py move <src> <dest>        # any file or folder, links follow
  python docs/tools/program_ledger.py new-answers --topic DEEP-AGENTS --sitting I \\
      --interview docs/specs/<program>/OWNER-INTERVIEW-<date>.md

Every moving command takes ``--dry-run``. They ``git mv`` tracked files, rewrite every relative
Markdown link to or from a moved file and every repository-relative path written in prose, and
list non-Markdown files (code, tests, JSON) that still mention an old path so you can fix them.

``check`` fails when a ledger row points at a missing file, when a Markdown file of the program is
not in the ledger, when a status is unknown, when a row's status disagrees with the file's
location (archived or not), when a Linear cell is neither ``-`` nor ``OVE-<n>``, or when an
answers file is malformed (no resolvable ``interview:``; ``status: final`` with a decision that
has no ``Becomes`` or ``Folded`` entry).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote, unquote

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROGRAM = REPO_ROOT / "docs" / "specs" / "provider-consolidation-2026-10"
LEDGER = "LEDGER.md"
ANSWERS_DIR = "answers"
TEMPLATE = Path("docs") / "agents" / "templates" / "interview-answers.template"

KINDS = (
    "proposals",
    "docs",
    "specs",
    "issues",
    "interview-instructions",
    "interview-answers",
    "sessions",
)
STATUSES = ("planned", "draft", "open", "accepted", "active", "parked", "done", "archived")
LINEAR_CELL = re.compile(r"^(?:-|—|OVE-\d+(?:\s*,\s*OVE-\d+)*)$")
EMPTY_CELL = re.compile(r"^(?:|-|—|tbd|\?)$", re.IGNORECASE)

EXCLUDED_DIRS = {
    ".git", ".venv", ".venv-wsl", "venv", "node_modules", "__pycache__", ".scratch", ".tmp",
    ".uv-cache", ".tmp-cleanup-unit", ".tmp-worker-poll-20261003", ".mypy_cache", ".ruff_cache",
    ".pytest_cache", ".worktrees", "app",
}  # fmt: skip
CODE_ROOTS = (
    "src", "tests", "deployments", "scripts", "packages", "integrations", "skills", ".agents",
    ".cursor", ".claude", "docs",
)  # fmt: skip
CODE_SUFFIXES = {".py", ".json", ".yml", ".yaml", ".toml", ".mdc", ".sh", ".txt", ".ps1"}
LINK = re.compile(r"(\]\()(<[^>]+>|[^)\s]+)((?:\s+\"[^\"]*\")?\))")
REFDEF = re.compile(r"^(\s{0,3}\[[^\]]+\]:\s*)(\S+)(.*)$")
INLINE_CODE = re.compile(r"`[^`\n]*`")


def archive_root() -> Path:
    return REPO_ROOT / "docs" / "specs" / "archive"


def eol_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def read(path: Path) -> tuple[str, str]:
    raw = path.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n"), eol_of(raw)


def write(path: Path, text: str, eol: str) -> None:
    path.write_bytes(text.replace("\n", eol).encode("utf-8"))


def rel_repo(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def walk_files():
    """Yield repository files, skipping caches and private scratch."""
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        here = Path(dirpath)
        for name in filenames:
            yield here / name


def markdown_corpus() -> list[Path]:
    """Every Markdown file whose relative links may point into a moved path."""
    found: list[Path] = []
    for path in walk_files():
        if path.suffix != ".md":
            continue
        rel = path.relative_to(REPO_ROOT).parts
        in_scope = rel[:1] in {("docs",), ("tests",), (".agents",)}
        if in_scope or path.name == "AGENTS.md" or (len(rel) == 1 and path.name == "README.md"):
            found.append(path)
    return found


def split_target(target: str) -> tuple[str, str]:
    target = target.strip("<>")
    path, sep, frag = target.partition("#")
    return unquote(path), (sep + frag if sep else "")


def is_relative_file_target(path: str) -> bool:
    return (
        bool(path) and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", path) and not path.startswith("/")
    )


def rel_posix(target: Path, start: Path) -> str:
    return Path(os.path.relpath(target, start)).as_posix()


def translate(path: Path, mapping: dict[Path, Path], dirs: list[tuple[Path, Path]]) -> Path:
    """Where ``path`` lives after the move: a moved file, or anything under a moved folder."""
    if path in mapping:
        return mapping[path]
    for old, new in dirs:
        if path == old or old in path.parents:
            return new / path.relative_to(old)
    return path


def rewrite_links(
    text: str,
    old_home: Path,
    new_home: Path,
    mapping: dict[Path, Path],
    dirs: list[tuple[Path, Path]] | None = None,
) -> str:
    """Re-point relative links. ``old_home`` / ``new_home`` are the directories the text lived in
    before / after; ``mapping`` sends moved absolute paths to their new absolute paths."""
    out: list[str] = []
    in_fence = False

    def fix(target: str) -> str:
        path, frag = split_target(target)
        if not is_relative_file_target(path):
            return target
        resolved = Path(os.path.normpath(old_home / path))
        moved = translate(resolved, mapping, dirs or [])
        if moved == resolved and old_home == new_home:
            return target
        return quote(rel_posix(moved, new_home), safe="/._-~()") + frag

    for line in text.split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            out.append(line)
        elif in_fence:
            out.append(line)
        else:
            out.append(rewrite_line(line, fix))
    return "\n".join(out)


def rewrite_line(line: str, fix: Callable[[str], str]) -> str:
    """Re-point the links of one line, leaving inline code spans untouched."""
    masks: list[str] = []

    def mask(match: re.Match[str]) -> str:
        masks.append(match.group(0))
        return f"\x00{len(masks) - 1}\x00"

    masked = INLINE_CODE.sub(mask, line)
    masked = LINK.sub(lambda m: f"{m.group(1)}{fix(m.group(2))}{m.group(3)}", masked)
    ref = REFDEF.match(masked)
    if ref:
        masked = f"{ref.group(1)}{fix(ref.group(2))}{ref.group(3)}"
    return re.sub(r"\x00(\d+)\x00", lambda m: masks[int(m.group(1))], masked)


def stamp_frontmatter(text: str, fields: dict[str, str], banner: str) -> str:
    lines = text.split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        block = "\n".join(f"{k}: {v}" for k, v in fields.items())
        return f"---\n{block}\n---\n\n{banner}\n\n{text}"
    end = lines.index("---", 1)
    head = [ln for ln in lines[1:end] if ln.split(":", 1)[0].strip() not in fields]
    head += [f"{k}: {v}" for k, v in fields.items()]
    body = lines[end + 1 :]
    while body and not body[0].strip():
        body.pop(0)
    return "\n".join(["---", *head, "---", "", banner, "", *body])


def tracked_files() -> set[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=False
    )
    names = result.stdout.decode("utf-8", "replace").split("\0")
    return {(REPO_ROOT / n).resolve() for n in names if n}


def plan(src: Path, dest: Path) -> dict[Path, Path]:
    """Map every file under ``src`` (or ``src`` itself) to its place under ``dest``."""
    if src.is_file():
        return {src: dest}
    return {
        f: dest / f.relative_to(src)
        for f in sorted(src.rglob("*"))
        if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc"
    }


def path_pairs(mapping: dict[Path, Path], src: Path, dest: Path) -> list[tuple[str, str]]:
    """Repository-relative path strings written in prose, longest first."""
    pairs = [(rel_repo(a), rel_repo(b)) for a, b in mapping.items()]
    if src.is_dir():
        pairs.append((rel_repo(src), rel_repo(dest)))
    return sorted(pairs, key=lambda p: -len(p[0]))


def relocate(
    src: Path,
    dest: Path,
    dry: bool,
    stamp: Callable[[Path, str], str] | None = None,
    extra_pairs: list[tuple[str, str]] | None = None,
) -> int:
    """Move ``src`` to ``dest`` and keep every Markdown link and written path pointing at it."""
    src, dest = src.resolve(), dest.resolve()
    if not src.exists():
        print(f"{src} does not exist", file=sys.stderr)
        return 2
    if dest.exists() and (src.is_file() or dest.is_file()):
        print(f"{rel_repo(dest)} already exists", file=sys.stderr)
        return 2
    mapping = plan(src, dest)
    if not mapping:
        print("nothing to move", file=sys.stderr)
        return 2
    clash = [b for b in mapping.values() if b.exists()]
    if clash:
        print(f"{rel_repo(clash[0])} already exists (and {len(clash) - 1} more)", file=sys.stderr)
        return 2
    pairs = path_pairs(mapping, src, dest) + (extra_pairs or [])
    dirs = [(src, dest)] if src.is_dir() else []
    changed: list[str] = []
    for doc in markdown_corpus():
        doc = doc.resolve()
        text, eol = read(doc)
        new = rewrite_links(text, doc.parent, mapping.get(doc, doc).parent, mapping, dirs)
        for old_text, new_text in pairs:
            new = re.sub(rf"(?<![\w/.-]){re.escape(old_text)}", new_text, new)
        if stamp and doc in mapping:
            new = stamp(doc, new)
        if new != text:
            changed.append(rel_repo(doc))
            if not dry:
                write(doc, new, eol)
    verb = "would move" if dry else "moved"
    print(f"{verb} {rel_repo(src)} -> {rel_repo(dest)} ({len(mapping)} file(s))")
    for name in changed:
        print(f"  rewrote {name}")
    if dry:
        report_code_references(pairs, set(mapping))
        return 0
    tracked = tracked_files()
    for a, b in mapping.items():
        b.parent.mkdir(parents=True, exist_ok=True)
        if a in tracked:
            subprocess.run(["git", "mv", str(a), str(b)], cwd=REPO_ROOT, check=True)
        else:
            shutil.move(str(a), str(b))
    if src.is_dir():
        shutil.rmtree(src, ignore_errors=True)
    report_code_references(pairs, set(mapping.values()))
    return 0


def report_code_references(pairs: list[tuple[str, str]], skip: set[Path]) -> None:
    """List non-Markdown files that still mention an old path (they are not rewritten)."""
    hits: dict[str, int] = {}
    tracked = tracked_files()
    for path in walk_files():
        rel = path.relative_to(REPO_ROOT).parts
        if rel[0] not in CODE_ROOTS or path.suffix not in CODE_SUFFIXES:
            continue
        if path.resolve() in skip or path.resolve() not in tracked:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        count = sum(len(re.findall(rf"(?<![\w/.-]){re.escape(old)}", text)) for old, _ in pairs)
        if count:
            hits[rel_repo(path)] = count
    if hits:
        print("still mention an old path (update by hand):")
        for name, count in sorted(hits.items()):
            print(f"  {name} ({count})")


# ------------------------------------------------------------------------------ commands


def archive_stamp(date: str, reason: str, origin: str, tail: str) -> Callable[[Path, str], str]:
    def stamp(_doc: Path, text: str) -> str:
        banner = f"> **Archived {date}** ({reason}). Kept for provenance; {tail}"
        fields = {
            "status": "archived",
            "archived": date,
            "archived_from": origin,
            "archived_reason": json.dumps(reason),
        }
        return stamp_frontmatter(text, fields, banner)

    return stamp


def archive(program: Path, source: Path, kind: str, reason: str, date: str, dry: bool) -> int:
    source = source.resolve()
    if kind not in KINDS:
        print(f"unknown kind {kind!r}; one of {', '.join(KINDS)}", file=sys.stderr)
        return 2
    if program not in source.parents:
        print(f"{source} is not a document of {program}", file=sys.stderr)
        return 2
    if source.name == LEDGER or source.suffix != ".md":
        print("only Markdown documents other than the ledger can be archived", file=sys.stderr)
        return 2
    dest = archive_root() / program.name / kind / source.name
    origin = source.relative_to(program).as_posix()
    reason_text = reason or "completed"
    ledger = program / LEDGER
    tail = f"see the [ledger]({rel_posix(ledger, dest.parent)}) for what replaced it."
    stamp = archive_stamp(date, reason_text, origin, tail)
    extra = [(origin, rel_repo(dest))] if "/" in origin else []
    code = relocate(source, dest, dry, stamp, extra)
    if code == 0 and not dry:
        print("next: set the ledger row Status to 'archived', then run check")
    return code


ARCHIVE_ROWS_END = "<!-- archived-programs:end -->"


def archive_program(folder: Path, reason: str, date: str, dry: bool) -> int:
    folder = folder.resolve()
    if not folder.is_dir() or folder.parent != REPO_ROOT / "docs" / "specs":
        print(f"{folder} is not a program folder directly under docs/specs", file=sys.stderr)
        return 2
    dest = archive_root() / folder.name
    reason_text = reason or "completed"
    index = archive_root() / "README.md"
    readme = folder / "README.md"
    stamp = None
    if readme.is_file():
        tail = "see the [archive index](../README.md)."
        banner_stamp = archive_stamp(date, reason_text, rel_repo(folder), tail)

        def stamp(doc: Path, text: str) -> str:
            return banner_stamp(doc, text) if doc == readme.resolve() else text

    code = relocate(folder, dest, dry, stamp)
    if code == 0 and not dry and index.is_file():
        text, eol = read(index)
        row = f"| [{folder.name}]({folder.name}/README.md) | {date} | {reason_text} |"
        if f"]({folder.name}/" not in text and ARCHIVE_ROWS_END in text:
            write(index, text.replace(ARCHIVE_ROWS_END, f"{row}\n{ARCHIVE_ROWS_END}", 1), eol)
            print(f"added a row to {rel_repo(index)}")
    return code


def move(src: Path, dest: Path, dry: bool) -> int:
    return relocate(src, dest, dry)


def new_answers(topic: str, sitting: str, interview: Path, program: Path, date: str) -> int:
    template = REPO_ROOT / TEMPLATE
    interview = interview.resolve()
    if not interview.is_file():
        print(f"{interview} does not exist", file=sys.stderr)
        return 2
    name = f"{topic.upper()}-SITTING-{sitting.upper()}-{date}-ANSWERS.md"
    dest = program / ANSWERS_DIR / name
    if dest.exists():
        print(f"{rel_repo(dest)} already exists", file=sys.stderr)
        return 2
    text = template.read_text(encoding="utf-8").replace("\r\n", "\n")
    for key, value in {
        "{{TOPIC}}": topic,
        "{{SITTING}}": sitting,
        "{{DATE}}": date,
        "{{INTERVIEW}}": rel_posix(interview, dest.parent),
        "{{INTERVIEW_NAME}}": interview.name,
    }.items():
        text = text.replace(key, value)
    dest.parent.mkdir(parents=True, exist_ok=True)
    write(dest, text, "\n")
    link = rel_posix(dest, program)
    print(f"created {rel_repo(dest)}")
    print(
        "add to the ledger (Interview answers):\n"
        f"| IA-NN | [{topic} sitting {sitting}: answers]({link}) | open | - | "
        "Filled during the sitting. |"
    )
    return 0


# ---------------------------------------------------------------------------------- check


def ledger_rows(text: str) -> list[dict[str, str]]:
    rows = []
    section = ""
    for number, line in enumerate(text.split("\n"), start=1):
        if line.startswith("## "):
            section = line[3:].strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or set(cells[0]) <= {"-", " ", ":"} or cells[0].lower() == "id":
            continue
        link = LINK.search(cells[1])
        rows.append(
            {
                "line": str(number),
                "section": section,
                "id": cells[0],
                "item": cells[1],
                "target": split_target(link.group(2))[0] if link else "",
                "status": cells[2].strip("` ").lower(),
                "linear": cells[3].strip("` "),
            }
        )
    return rows


def frontmatter(text: str) -> dict[str, str]:
    lines = text.split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        return {}
    out = {}
    for line in lines[1 : lines.index("---", 1)]:
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip().strip("\"'")
    return out


def check_answers(path: Path, problems: list[str], label: str) -> None:
    text, _ = read(path)
    meta = frontmatter(text)
    if meta.get("type") != "Interview Answers":
        problems.append(f"{label}: front matter type must be 'Interview Answers'")
    target = meta.get("interview", "")
    if not target or not (path.parent / split_target(target)[0]).is_file():
        problems.append(f"{label}: interview: {target!r} does not resolve to a file")
    if meta.get("status") not in {"open", "final", "archived"}:
        problems.append(f"{label}: status must be open, final or archived")
    if meta.get("status") != "final":
        return
    header: list[str] = []
    in_decisions = False
    for line in text.split("\n"):
        if line.startswith("## "):
            in_decisions = line[3:].strip().lower() == "decisions"
            header = []
        if not (in_decisions and line.startswith("|")):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if set(cells[0]) <= {"-", " ", ":"}:
            continue
        if not header:
            header = [c.lower() for c in cells]
            continue
        row = dict(zip(header, cells, strict=False))
        for column in ("becomes", "folded"):
            if EMPTY_CELL.match(row.get(column, "")):
                problems.append(f"{label}: final, but decision {cells[0]} has no {column!r} entry")


def check(program: Path) -> int:
    ledger = program / LEDGER
    if not ledger.is_file():
        print(f"{ledger} does not exist", file=sys.stderr)
        return 1
    archived_dir = archive_root() / program.name
    problems: list[str] = []
    text, _ = read(ledger)
    rows = ledger_rows(text)
    if not rows:
        problems.append("the ledger has no rows")
    linked: set[Path] = set()
    ids: set[str] = set()
    for row in rows:
        where = f"{LEDGER}:{row['line']} {row['id']}"
        if row["id"] in ids:
            problems.append(f"{where}: duplicate id")
        ids.add(row["id"])
        if row["status"] not in STATUSES:
            problems.append(
                f"{where}: status {row['status']!r} is not one of {', '.join(STATUSES)}"
            )
        if not LINEAR_CELL.match(row["linear"]):
            problems.append(f"{where}: Linear cell {row['linear']!r} must be '-' or OVE-<n>")
        if not row["target"]:
            if row["status"] != "planned":
                problems.append(f"{where}: only a 'planned' row may have no link")
            continue
        target = Path(os.path.normpath(program / row["target"]))
        linked.add(target)
        if not target.is_file():
            problems.append(f"{where}: {row['target']} does not exist")
            continue
        if (target.parent == archived_dir or archived_dir in target.parents) != (
            row["status"] == "archived"
        ):
            problems.append(f"{where}: status {row['status']!r} disagrees with the file's location")
    for path in sorted(program.rglob("*.md")):
        if path.name == LEDGER and path.parent == program:
            continue
        if Path(os.path.normpath(path)) not in linked:
            problems.append(f"{path.relative_to(program).as_posix()}: not listed in {LEDGER}")
    if archived_dir.is_dir():
        for path in sorted(archived_dir.rglob("*.md")):
            rel = path.relative_to(archived_dir)
            if rel.parts[0] in KINDS:
                if len(rel.parts) != 2:
                    problems.append(
                        f"archive/{program.name}/{rel.as_posix()}: kind folders are flat"
                    )
                if Path(os.path.normpath(path)) not in linked:
                    problems.append(
                        f"archive/{program.name}/{rel.as_posix()}: not listed in {LEDGER}"
                    )
    answer_files = (
        list((program / ANSWERS_DIR).glob("*.md")) if (program / ANSWERS_DIR).is_dir() else []
    )
    if (archived_dir / "interview-answers").is_dir():
        answer_files += list((archived_dir / "interview-answers").glob("*.md"))
    for path in answer_files:
        check_answers(path, problems, path.name)
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"{len(rows)} ledger rows, {len(problems)} problem(s)")
    return 1 if problems else 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    today = dt.datetime.now(dt.UTC).date().isoformat()
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check")
    p_check.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    p_arch = sub.add_parser("archive")
    p_arch.add_argument("file", type=Path)
    p_arch.add_argument("--kind", required=True, choices=KINDS)
    p_arch.add_argument("--reason", default="")
    p_arch.add_argument("--date", default=today)
    p_arch.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    p_arch.add_argument("--dry-run", action="store_true")
    p_prog = sub.add_parser("archive-program")
    p_prog.add_argument("folder", type=Path)
    p_prog.add_argument("--reason", default="")
    p_prog.add_argument("--date", default=today)
    p_prog.add_argument("--dry-run", action="store_true")
    p_move = sub.add_parser("move")
    p_move.add_argument("src", type=Path)
    p_move.add_argument("dest", type=Path)
    p_move.add_argument("--dry-run", action="store_true")
    p_ans = sub.add_parser("new-answers")
    p_ans.add_argument("--topic", required=True)
    p_ans.add_argument("--sitting", required=True)
    p_ans.add_argument("--interview", type=Path, required=True)
    p_ans.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    p_ans.add_argument("--date", default=today)
    args = parser.parse_args()

    def absolute(p: Path) -> Path:
        return p if p.is_absolute() else Path.cwd() / p

    if args.command == "check":
        return check(absolute(args.program).resolve())
    if args.command == "archive":
        program = absolute(args.program).resolve()
        return archive(
            program, absolute(args.file), args.kind, args.reason, args.date, args.dry_run
        )
    if args.command == "archive-program":
        return archive_program(absolute(args.folder), args.reason, args.date, args.dry_run)
    if args.command == "move":
        return move(absolute(args.src), absolute(args.dest), args.dry_run)
    return new_answers(
        args.topic,
        args.sitting,
        absolute(args.interview),
        absolute(args.program).resolve(),
        args.date,
    )


if __name__ == "__main__":
    sys.exit(main())
