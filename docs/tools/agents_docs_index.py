#!/usr/bin/env python3
"""Generate the blocks of the root AGENTS.md, the module AGENTS.md files and the knowledge index.

AGENTS.md is mostly hand-written; three marked blocks are generated from
`docs/agents/index-notes.toml` (the generator's config), the concept frontmatter (`category`,
`title`, `questions[0]`), the module registry `.sdlc/modules.json` and the program ledgers. The
grammar is DOC-02 of the Agentic SDLC program with the accepted edits G1-G16:

  <!-- BEGIN:sdlc-infra -->      infrastructure pointer and the most used commands
  <!-- BEGIN:sdlc v= src= -->    repository guide, knowledge by category, code map, skills, verify
  <!-- BEGIN:sdlc-programs -->   active programs: ledger link, next step, optional record link

The root `## Code map` is one line per `.sdlc/modules.json` entry: `<path> - <first sentence of
purpose>` (G4, the target is implied), ordered by `pin_first` then path.

Every `modules.json` entry also gets `<path>/AGENTS.md` with one generated block (G5, G6):

  <!-- BEGIN:sdlc-module id=<id> -->
  title, purpose, Entrypoints (module docstring first lines), Tests, Invariants,
  Explained by (concepts whose Citations link into the path), Decided by (ADRs those concepts
  cite or whose text links into the path), Depends on / Used by (imports between registered
  modules), Verify, Program
  <!-- END:sdlc-module -->

Text above the marker (and below the end marker) is preserved byte for byte, including its line
endings; a file without a marker gets the block appended. The block is at most 2 KiB; hand-written
text in a module file should stay within 2 KiB (a warning, not a failure). Link ownership: a link
or import belongs to the registered module with the longest path prefix, so unregistered
sub-packages belong to the nearest registered parent.

`docs/knowledge/index.md` is generated whole: one section per category (anchor `#<category>`),
one line per concept. The tool refuses to build while a concept lacks `category` or `questions`,
while a nested module guide is not registered in `.sdlc/modules.json`, while a registered path or
test path is missing, or while an active program ledger is missing from the programs block.

Usage:
  python docs/tools/agents_docs_index.py          # rewrite blocks, module guides, knowledge index
  python docs/tools/agents_docs_index.py --check  # exit 1 when a block, index or budget is off
  python docs/tools/agents_docs_index.py --print  # print the generated AGENTS.md
  python docs/tools/agents_docs_index.py --print-module <id>  # print one module block
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_MD = REPO_ROOT / "AGENTS.md"
CONFIG = REPO_ROOT / "docs" / "agents" / "index-notes.toml"
KNOWLEDGE = REPO_ROOT / "docs" / "knowledge"
KNOWLEDGE_INDEX = KNOWLEDGE / "index.md"
SPECS = REPO_ROOT / "docs" / "specs"
ADR_DIR = REPO_ROOT / "docs" / "adr"
MODULES_JSON = REPO_ROOT / ".sdlc" / "modules.json"
VERSION = "0.2.0"
CATEGORIES = (
    "boundaries",
    "surfaces",
    "domain-model",
    "persistence",
    "execution",
    "qualification",
    "operations",
    "decisions",
    "goals",
)
RESERVED = {"index", "log"}
BUDGETS = {
    "whole": 14336,
    "sdlc": 8192,
    "infra": 400,
    "programs": 1024,
    "handwritten": 4096,
    "module": 2048,
    "module_handwritten": 2048,
}
MAP_LINE_MAX = 80
LIST_CAP = 6
EXPLAINED_CAP = 6
DECIDED_CAP = 5
ENTRY_DESC_MAX = 84
ALSO_MAX = 300
MAX_ENTRY_LINES = 10

INFRA_BEGIN, INFRA_END = "<!-- BEGIN:sdlc-infra -->", "<!-- END:sdlc-infra -->"
PROGRAMS_BEGIN, PROGRAMS_END = "<!-- BEGIN:sdlc-programs -->", "<!-- END:sdlc-programs -->"
SDLC_BEGIN = re.compile(r"<!-- BEGIN:sdlc v=\S+ src=\S+ -->")
SDLC_END = "<!-- END:sdlc -->"
MODULE_BEGIN = re.compile(r"<!-- BEGIN:sdlc-module id=(\S+) -->")
MODULE_END = "<!-- END:sdlc-module -->"
LINK = re.compile(r"\]\(([^)\s]+?)(?:#[^)\s]*)?\)")
ADR_FILE = re.compile(r"^(\d{4})-")
SKIP_DIRS = {"__pycache__", "node_modules", ".venv", "dist", "build"}
LISTED_SUFFIXES = {".py", ".toml", ".json", ".env", ".yml", ".yaml"}


def configure(root: Path) -> None:
    """Point every path at another repository root (tests build a small tree under tmp_path)."""
    global REPO_ROOT, AGENTS_MD, CONFIG, KNOWLEDGE, KNOWLEDGE_INDEX, SPECS, ADR_DIR, MODULES_JSON
    REPO_ROOT = root
    AGENTS_MD = root / "AGENTS.md"
    CONFIG = root / "docs" / "agents" / "index-notes.toml"
    KNOWLEDGE = root / "docs" / "knowledge"
    KNOWLEDGE_INDEX = KNOWLEDGE / "index.md"
    SPECS = root / "docs" / "specs"
    ADR_DIR = root / "docs" / "adr"
    MODULES_JSON = root / ".sdlc" / "modules.json"


@dataclass(frozen=True)
class Concept:
    slug: str
    category: str
    title: str
    description: str
    question: str


def _frontmatter(text: str) -> tuple[dict[str, object], str]:
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta: dict[str, object] = {}
    key = ""
    for line in text[4:end].splitlines():
        if line and not line.startswith(" ") and ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            meta[key] = value.strip().strip("'\"")
        elif key and line.lstrip().startswith("- "):
            current = meta.get(key)
            items = current if isinstance(current, list) else []
            items.append(line.lstrip()[2:].strip().strip("'\""))
            meta[key] = items
    return meta, text[end + 5 :]


def load_concepts() -> list[Concept]:
    concepts: list[Concept] = []
    problems: list[str] = []
    for file in sorted(KNOWLEDGE.glob("*.md")):
        if file.stem in RESERVED:
            continue
        meta, _ = _frontmatter(file.read_text(encoding="utf-8", errors="replace"))
        category = str(meta.get("category", ""))
        questions = meta.get("questions")
        if category not in CATEGORIES:
            problems.append(f"{file.name}: category {category!r} is not one of the nine")
        if not isinstance(questions, list) or not questions:
            problems.append(f"{file.name}: no questions")
            continue
        concepts.append(
            Concept(
                slug=file.stem,
                category=category,
                title=str(meta.get("title", file.stem)),
                description=str(meta.get("description", "")),
                question=questions[0],
            )
        )
    if problems:
        raise SystemExit("concept frontmatter incomplete:\n  " + "\n  ".join(problems))
    return concepts


def load_config() -> dict:
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))


def subsystem_guides(root: Path) -> list[Path]:
    """Find guidance without descending into worktrees, caches or projected fixtures."""
    found = []
    for directory, children, files in os.walk(root, topdown=True, followlinks=False):
        parent = Path(directory)
        children[:] = [
            name
            for name in children
            if not name.startswith(".")
            and name not in {"node_modules", "app", "fixtures"}
            and not (parent / name).is_symlink()
            and not getattr(parent / name, "is_junction", lambda: False)()
        ]
        if "AGENTS.md" in files:
            found.append(parent / "AGENTS.md")
    return sorted(found)


def module_dirs() -> list[str]:
    skip = {REPO_ROOT / "AGENTS.md", REPO_ROOT / "docs" / "AGENTS.md"}
    return [
        str(p.parent.relative_to(REPO_ROOT)).replace("\\", "/")
        for p in subsystem_guides(REPO_ROOT)
        if p not in skip
    ]


def _line(text: str) -> str:
    return " ".join(str(text).split())


def render_infra(cfg: dict) -> str:
    infra = cfg["infra"]
    return "\n".join([INFRA_BEGIN, _line(infra["pointer"]), _line(infra["commands"]), INFRA_END])


def _knowledge_lines(concepts: list[Concept], cfg: dict, collapsed: set[str]) -> list[str]:
    pins: dict[str, list[str]] = cfg.get("pins", {})
    lines: list[str] = []
    for category in CATEGORIES:
        members = [c for c in concepts if c.category == category]
        order = {slug: i for i, slug in enumerate(pins.get(category, []))}
        members.sort(key=lambda c: (order.get(c.slug, len(order)), c.slug))
        lines.append(f"{category}:")
        if category in collapsed:
            pinned = [c for c in members if c.slug in order]
            rest = [c for c in members if c.slug not in order]
            lines.extend(f"- {c.slug} — {c.question}" for c in pinned)
            names = ", ".join(c.slug for c in rest)
            lines.append(f"- more (questions in docs/knowledge/index.md#{category}): {names}")
        else:
            lines.extend(f"- {c.slug} — {c.question}" for c in members)
    return lines


def render_sdlc(cfg: dict, concepts: list[Concept], modules: list[Module]) -> str:
    registered = {m.path for m in modules}
    missing = [d for d in module_dirs() if d not in registered]
    if missing:
        raise SystemExit(
            f"nested guides without an entry in {MODULES_JSON.name}: {', '.join(missing)}"
        )
    digest_input = (
        CONFIG.read_text(encoding="utf-8")
        + MODULES_JSON.read_text(encoding="utf-8")
        + "".join(f"{c.slug}|{c.category}|{c.question}\n" for c in concepts)
    )
    src = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:12]
    header = f"<!-- BEGIN:sdlc v={VERSION} src={src} -->"

    def build(collapsed: set[str]) -> str:
        out = [header, "## Repository guide", _line(cfg["repository"]["guide"]), ""]
        out += [f"## Knowledge (docs/knowledge, {len(CATEGORIES)} categories)"]
        out += _knowledge_lines(concepts, cfg, collapsed)
        out += [
            _line(cfg["repository"]["search"]),
            "",
            "## Code map (read the closest guide before editing)",
        ]
        out += code_map_lines(modules)
        out += ["", "## Skills", _line(cfg["skills"]["line"]), _line(cfg["skills"]["tracker"]), ""]
        out += ["## Verify", _line(cfg["verify"]["code"]), _line(cfg["verify"]["docs"]), SDLC_END]
        return "\n".join(out)

    collapsed: set[str] = set()
    block = build(collapsed)
    sizes = {c: sum(1 for k in concepts if k.category == c) for c in CATEGORIES}
    for category in sorted(CATEGORIES, key=lambda c: -sizes[c]):
        if len(block.encode("utf-8")) <= BUDGETS["sdlc"]:
            break
        collapsed.add(category)
        block = build(collapsed)
    return block


def ledger_programs() -> list[str]:
    return sorted(
        d.name
        for d in SPECS.iterdir()
        if d.is_dir() and d.name != "archive" and (d / "LEDGER.md").is_file()
    )


def render_programs(cfg: dict) -> str:
    listed = {p["path"]: p for p in cfg["programs"]}
    parked = set(cfg.get("parked", {}).get("paths", []))
    missing = [
        p
        for p in ledger_programs()
        if f"docs/specs/{p}" not in listed and f"docs/specs/{p}" not in parked
    ]
    if missing:
        raise SystemExit(f"program ledgers missing from {CONFIG.name}: {', '.join(missing)}")
    lines = [PROGRAMS_BEGIN]
    for p in cfg["programs"]:
        record = f"; record: [{p['record_name']}]({p['record']})" if p.get("record") else ""
        lines.append(f"- [{p['name']}]({p['path']}/LEDGER.md) — next: {_line(p['next'])}{record}")
    if cfg.get("parked", {}).get("line"):
        lines.append(_line(cfg["parked"]["line"]))
    lines.append(PROGRAMS_END)
    return "\n".join(lines)


def render_knowledge_index(cfg: dict, concepts: list[Concept]) -> str:
    out = ["---", 'okf_version: "0.1"', "---", "", "# Mission Control knowledge", ""]
    out += [_line(cfg["knowledge_index"]["intro"]), ""]
    out += [_line(cfg["knowledge_index"]["rules"]), ""]
    pins = cfg.get("pins", {})
    blurbs = cfg["knowledge_index"]["categories"]
    for category in CATEGORIES:
        members = [c for c in concepts if c.category == category]
        order = {slug: i for i, slug in enumerate(pins.get(category, []))}
        members.sort(key=lambda c: (order.get(c.slug, len(order)), c.slug))
        out += [f"## {category}", "", _line(blurbs[category]), ""]
        out += [f"- [{c.slug}]({c.slug}.md) — {c.question}" for c in members]
        out.append("")
    out += ["The update history is [log](log.md).", ""]
    return "\n".join(out)


def _replace_between(text: str, begin: str | re.Pattern[str], end: str, block: str) -> str:
    if isinstance(begin, str):
        start = text.find(begin)
    else:
        m = begin.search(text)
        start = m.start() if m else -1
    stop = text.find(end)
    if start == -1 or stop == -1:
        raise SystemExit(f"AGENTS.md lacks the markers for {end}")
    return text[:start] + block + text[stop + len(end) :]


def build_agents(text: str, cfg: dict, concepts: list[Concept], modules: list[Module]) -> str:
    text = _replace_between(text, INFRA_BEGIN, INFRA_END, render_infra(cfg))
    text = _replace_between(text, SDLC_BEGIN, SDLC_END, render_sdlc(cfg, concepts, modules))
    return _replace_between(text, PROGRAMS_BEGIN, PROGRAMS_END, render_programs(cfg))


def budget_report(text: str) -> list[str]:
    problems: list[str] = []

    def size(a: str | re.Pattern[str], b: str) -> int:
        start = text.find(a) if isinstance(a, str) else (m.start() if (m := a.search(text)) else -1)
        stop = text.find(b) + len(b)
        return len(text[start:stop].encode("utf-8")) if start != -1 and stop > start else 0

    parts = {
        "infra": size(INFRA_BEGIN, INFRA_END),
        "sdlc": size(SDLC_BEGIN, SDLC_END),
        "programs": size(PROGRAMS_BEGIN, PROGRAMS_END),
    }
    total = len(text.encode("utf-8"))
    hand = total - sum(parts.values())
    for name, value in parts.items():
        if value > BUDGETS[name]:
            problems.append(f"{name} block is {value} bytes, budget {BUDGETS[name]}")
    if total > BUDGETS["whole"]:
        problems.append(f"AGENTS.md is {total} bytes, budget {BUDGETS['whole']}")
    if hand > BUDGETS["handwritten"]:
        problems.append(f"hand-written text is {hand} bytes, budget {BUDGETS['handwritten']}")
    return problems


# ---------------------------------------------------------------------------------------------
# Module registry (.sdlc/modules.json) and the generated module blocks
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Module:
    id: str
    title: str
    path: str
    purpose: str
    pin_first: int | None = None
    pin_files: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    verify: tuple[str, ...] = ()
    program: str = ""
    invariants: tuple[str, ...] = ()


def first_sentence(text: str) -> str:
    """The first sentence of a purpose: up to the first full stop followed by a space or the end."""
    flat = _line(text)
    match = re.search(r"(?<=[A-Za-z0-9)\]])\.(?:\s|$)", flat)
    return (flat[: match.start()] if match else flat).rstrip(".")


def _depth_below_package(path: str) -> int | None:
    prefix = "src/mission_control/"
    if path.startswith(prefix):
        return len(path[len(prefix) :].split("/"))
    return None


def load_modules() -> tuple[list[Module], list[str]]:
    """Read `.sdlc/modules.json`; return the modules and every problem found (never raises)."""
    problems: list[str] = []
    if not MODULES_JSON.is_file():
        return [], [f"{MODULES_JSON.relative_to(REPO_ROOT).as_posix()} is missing"]
    try:
        raw = json.loads(MODULES_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [], [f"{MODULES_JSON.name} is not valid JSON: {error}"]
    modules: list[Module] = []
    ids: set[str] = set()
    paths: set[str] = set()
    for entry in raw.get("modules", []):
        label = str(entry.get("id", "?"))
        absent = [k for k in ("id", "title", "path", "purpose") if not entry.get(k)]
        if absent:
            problems.append(f"module {label}: missing {', '.join(absent)}")
            continue
        module = Module(
            id=entry["id"],
            title=entry["title"],
            path=entry["path"].strip("/"),
            purpose=_line(entry["purpose"]),
            pin_first=entry.get("pin_first"),
            pin_files=tuple(entry.get("pin_files", ())),
            tests=tuple(entry.get("tests", ())),
            verify=tuple(entry.get("verify", ())),
            program=entry.get("program", ""),
            invariants=tuple(entry.get("invariants", ())),
        )
        modules.append(module)
        if module.id in ids:
            problems.append(f"module {module.id}: duplicate id")
        if module.path in paths:
            problems.append(f"module {module.id}: duplicate path {module.path}")
        ids.add(module.id)
        paths.add(module.path)
        if not (REPO_ROOT / module.path).is_dir():
            problems.append(f"module {module.id}: path {module.path} does not exist")
        depth = _depth_below_package(module.path)
        if depth is not None and depth > 2:
            problems.append(f"module {module.id}: {module.path} is deeper than two levels")
        if len(module.invariants) > 3:
            problems.append(f"module {module.id}: more than three invariants")
        if len(first_sentence(module.purpose)) > MAP_LINE_MAX:
            problems.append(
                f"module {module.id}: first purpose sentence is over {MAP_LINE_MAX} characters"
            )
        for test in module.tests:
            if not (REPO_ROOT / test).exists():
                problems.append(f"module {module.id}: test path {test} does not exist")
        if module.program and not (REPO_ROOT / module.program).exists():
            problems.append(f"module {module.id}: program {module.program} does not exist")
        for name in module.pin_files:
            if not (REPO_ROOT / module.path / name).exists():
                problems.append(f"module {module.id}: pin_files entry {name} does not exist")
    return modules, problems


def sorted_modules(modules: list[Module]) -> list[Module]:
    return sorted(
        modules, key=lambda m: (m.pin_first if m.pin_first is not None else 10**6, m.path)
    )


def code_map_lines(modules: list[Module]) -> list[str]:
    return [f"{m.path} — {first_sentence(m.purpose)}" for m in sorted_modules(modules)]


def _under(path: str, base: str) -> bool:
    return path == base or path.startswith(base + "/")


def owner_of(path: str, modules: list[Module]) -> Module | None:
    """The registered module with the longest path prefix of `path`."""
    best: Module | None = None
    for module in modules:
        if _under(path, module.path) and (best is None or len(module.path) > len(best.path)):
            best = module
    return best


def _links(text: str, source: Path) -> list[str]:
    """Repository-relative targets of the Markdown links in `text` (external links dropped)."""
    found: list[str] = []
    for raw in LINK.findall(text):
        if "://" in raw or raw.startswith(("mailto:", "#", "/")):
            continue
        target = Path(os.path.normpath(source.parent / raw))
        try:
            found.append(target.relative_to(REPO_ROOT).as_posix())
        except ValueError:
            continue
    return found


def _citations(text: str) -> str:
    """The `## Citations` section of a concept (the whole text when it has none)."""
    text = text.replace("\r\n", "\n")
    match = re.search(r"^## Citations\s*$", text, re.MULTILINE)
    if not match:
        return text
    rest = text[match.end() :]
    following = re.search(r"^## ", rest, re.MULTILINE)
    return rest[: following.start()] if following else rest


def _adr_id(path: str) -> str | None:
    if not path.startswith("docs/adr/"):
        return None
    match = ADR_FILE.match(path.rsplit("/", 1)[-1])
    return f"ADR-{match.group(1)}" if match else None


@dataclass
class Context:
    modules: list[Module]
    concept_links: dict[str, Counter[str]] = field(default_factory=dict)
    adr_links: dict[str, Counter[str]] = field(default_factory=dict)
    cites: Counter[str] = field(default_factory=Counter)
    edges: dict[str, Counter[str]] = field(default_factory=dict)


def _import_edges(modules: list[Module]) -> dict[str, Counter[str]]:
    """Import statements between registered modules under src/mission_control (any depth)."""
    src = REPO_ROOT / "src"
    package = src / "mission_control"
    edges: dict[str, Counter[str]] = {}
    if not package.is_dir():
        return edges
    inside = [m for m in modules if _under(m.path, "src/mission_control")]
    for file in sorted(package.rglob("*.py")):
        if "__pycache__" in file.parts:
            continue
        rel = file.relative_to(REPO_ROOT).as_posix()
        source = owner_of(rel, inside)
        if source is None:
            continue
        try:
            tree = ast.parse(file.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        pkg = list(file.relative_to(src).parts[:-1])
        for node in ast.walk(tree):
            candidates: list[list[str]] = []
            if isinstance(node, ast.Import):
                candidates = [alias.name.split(".") for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = pkg[: len(pkg) - (node.level - 1)] if node.level else []
                head = base + (node.module.split(".") if node.module else [])
                candidates = [head, *([*head, alias.name] for alias in node.names)]
            best: Module | None = None
            for parts in candidates:
                if not parts or parts[0] != "mission_control":
                    continue
                target = owner_of("src/" + "/".join(parts), inside)
                if target is not None and (best is None or len(target.path) > len(best.path)):
                    best = target
            if best is None or best is source:
                continue
            if _under(best.path, source.path) or _under(source.path, best.path):
                continue
            edges.setdefault(source.id, Counter())[best.id] += 1
    return edges


def build_context(modules: list[Module]) -> Context:
    ctx = Context(modules=modules)
    if KNOWLEDGE.is_dir():
        for file in sorted(KNOWLEDGE.glob("*.md")):
            if file.stem in RESERVED:
                continue
            text = file.read_text(encoding="utf-8", errors="replace")
            ctx.concept_links[file.stem] = Counter(_links(_citations(text), file))
            for target in _links(text, file):
                ctx.cites[target] += 1
    if ADR_DIR.is_dir():
        for file in sorted(ADR_DIR.glob("*.md")):
            adr = _adr_id(file.relative_to(REPO_ROOT).as_posix())
            if adr:
                text = file.read_text(encoding="utf-8", errors="replace")
                ctx.adr_links[adr] = Counter(_links(text, file))
    ctx.edges = _import_edges(modules)
    return ctx


def _ranked(scores: Counter[str], cap: int) -> list[str]:
    return [name for name, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:cap]]


def explained_by(module: Module, ctx: Context) -> list[str]:
    """Concepts whose Citations link into the module: its own files first, else its subtree."""
    direct: Counter[str] = Counter()
    subtree: Counter[str] = Counter()
    for slug, links in ctx.concept_links.items():
        for target, count in links.items():
            if _under(target, module.path):
                subtree[slug] += count
                if owner_of(target, ctx.modules) is module:
                    direct[slug] += count
    return _ranked(direct or subtree, EXPLAINED_CAP)


def decided_by(module: Module, concepts: list[str], ctx: Context) -> list[str]:
    scores: Counter[str] = Counter()
    for slug in concepts:
        for target in ctx.concept_links.get(slug, ()):
            adr = _adr_id(target)
            if adr:
                scores[adr] += 1
    for adr, links in ctx.adr_links.items():
        if any(_under(t, module.path) and owner_of(t, ctx.modules) is module for t in links):
            scores[adr] += 1
    return _ranked(scores, DECIDED_CAP)


def _module_doc(path: Path) -> str:
    """First sentence of a module docstring (a package uses __init__.py), parentheses dropped."""
    file = path / "__init__.py" if path.is_dir() else path
    if file.suffix != ".py" or not file.is_file():
        return ""
    try:
        doc = ast.get_docstring(ast.parse(file.read_text(encoding="utf-8", errors="replace")))
    except SyntaxError:
        return ""
    if not doc:
        return ""
    paragraph = _line(doc.strip().split("\n\n", 1)[0]).replace(chr(0xFFFD), "").replace("`", "")
    cut = re.search(r"(?<=[A-Za-z0-9)\]])\.(?:\s|$)", paragraph)
    sentence = paragraph[: cut.start()] if cut else paragraph
    plain = _line(re.sub(r"\([^)]*\)", "", sentence))
    plain = re.sub(r"\s+([;,:])", r"\1", plain).strip(" ;:,")
    text = plain or _line(sentence)
    if len(text) > ENTRY_DESC_MAX:
        text = text[: ENTRY_DESC_MAX - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return text


def _tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*.py") if "__pycache__" not in f.parts)


def entrypoints(module: Module, ctx: Context) -> list[tuple[str, str]]:
    """(name, description) pairs ordered by pin_files, then citations, then size, then name."""
    base = REPO_ROOT / module.path
    pinned = {name: i for i, name in enumerate(module.pin_files)}
    items: list[tuple[tuple[int, int, int, str], str, str]] = []
    for child in sorted(base.iterdir(), key=lambda p: p.name):
        name = child.name
        if name.startswith(".") or name in SKIP_DIRS or name.endswith(".egg-info"):
            continue
        if child.is_dir():
            label = name + "/"
        elif child.suffix in LISTED_SUFFIXES and name not in {"__init__.py", "__main__.py"}:
            label = name
        else:
            continue
        rel = child.relative_to(REPO_ROOT).as_posix()
        cited = sum(n for target, n in ctx.cites.items() if _under(target, rel))
        key = (pinned.get(name, len(pinned)), -cited, -_tree_size(child), name)
        items.append((key, label, _module_doc(child)))
    items.sort(key=lambda item: item[0])
    return [(label, doc) for _, label, doc in items]


def _names(ids: Counter[str]) -> str:
    ranked = sorted(ids.items(), key=lambda kv: (-kv[1], kv[0]))
    shown = [name for name, _ in ranked[:LIST_CAP]]
    extra = len(ranked) - len(shown)
    return ", ".join(shown) + (f" (+{extra})" if extra > 0 else "")


def render_module_block(module: Module, ctx: Context, level: int = 1) -> str:
    """The generated block for one module, LF line endings, at most BUDGETS['module'] bytes."""
    concepts = explained_by(module, ctx)
    adrs = decided_by(module, concepts, ctx)
    depends = ctx.edges.get(module.id, Counter())
    used_by: Counter[str] = Counter()
    for source, targets in ctx.edges.items():
        if module.id in targets:
            used_by[source] = targets[module.id]
    tail: list[str] = []
    if module.tests:
        tail.append("Tests: " + ", ".join(module.tests))
    if module.invariants:
        tail.append("Invariants:")
        tail.extend(f"- {_line(line)}" for line in module.invariants)
    if concepts:
        tail.append("Explained by (docs/knowledge): " + ", ".join(concepts))
    if adrs:
        tail.append("Decided by (docs/adr): " + ", ".join(adrs))
    graph = []
    if depends:
        graph.append("Depends on: " + _names(depends))
    if used_by:
        graph.append("Used by: " + _names(used_by))
    if graph:
        tail.append(" · ".join(graph))
    if module.verify:
        tail.append("Verify: " + "; ".join(_line(v) for v in module.verify))
    if module.program:
        tail.append("Program: " + module.program)
    head = [
        f"<!-- BEGIN:sdlc-module id={module.id} -->",
        f"{'#' * level} {module.title}",
        module.purpose,
    ]
    entries = entrypoints(module, ctx)

    def names_line(prefix: str, names: list[str]) -> str:
        joined = ""
        for index, name in enumerate(names):
            candidate = (joined + ", " if joined else "") + name
            if len((prefix + candidate).encode("utf-8")) > ALSO_MAX:
                joined += f" (+{len(names) - index})"
                break
            joined = candidate
        return prefix + joined

    def build(count: int) -> str:
        shown = entries[:count]
        rest = [name for name, _ in entries[count:]]
        lines = list(head)
        if shown:
            lines.append("Entrypoints:")
            lines.extend(f"- {name} — {doc}" if doc else f"- {name}" for name, doc in shown)
            if rest:
                lines.append(names_line("Also: ", rest))
        elif rest:
            lines.append(names_line("Entrypoints: ", rest))
        lines.extend(tail)
        lines.append(MODULE_END)
        return "\n".join(lines)

    for count in range(min(len(entries), MAX_ENTRY_LINES), -1, -1):
        block = build(count)
        if len(block.encode("utf-8")) <= BUDGETS["module"]:
            return block
    return build(0)


def _split_module_file(existing: str) -> tuple[str, str] | None:
    """(text before the begin marker, text after the end marker) or None when no block."""
    begin = MODULE_BEGIN.search(existing)
    if not begin:
        return None
    end = existing.find(MODULE_END, begin.end())
    if end == -1:
        return None
    return existing[: begin.start()], existing[end + len(MODULE_END) :]


def render_module_file(module: Module, ctx: Context, existing: str | None) -> str:
    """The module AGENTS.md: hand-written text preserved, the generated block inserted."""
    if existing is None:
        return render_module_block(module, ctx, 1) + "\n"
    newline = "\r\n" if "\r\n" in existing else "\n"
    parts = _split_module_file(existing)
    if parts is not None:
        before, after = parts
        level = 2 if before.strip() else 1
        block = render_module_block(module, ctx, level).replace("\n", newline)
        return before + block + after
    block = render_module_block(module, ctx, 2).replace("\n", newline)
    body = existing if existing.endswith("\n") or not existing else existing + newline
    return body + newline + block + newline


def module_file(module: Module) -> Path:
    return REPO_ROOT / module.path / "AGENTS.md"


def read_module_file(module: Module) -> str | None:
    path = module_file(module)
    return path.read_bytes().decode("utf-8") if path.is_file() else None


def module_budget_report(module: Module, text: str) -> tuple[list[str], list[str]]:
    """(failures, warnings) for one generated module file."""
    failures: list[str] = []
    warnings: list[str] = []
    rel = f"{module.path}/AGENTS.md"
    parts = _split_module_file(text)
    if parts is None:
        return [f"{rel} has no sdlc-module block"], warnings
    begin = MODULE_BEGIN.search(text)
    assert begin is not None
    end = text.find(MODULE_END, begin.end()) + len(MODULE_END)
    block = len(text[begin.start() : end].replace("\r\n", "\n").encode("utf-8"))
    hand = len((parts[0] + parts[1]).encode("utf-8"))
    if block > BUDGETS["module"]:
        failures.append(f"{rel} block is {block} bytes, budget {BUDGETS['module']}")
    if hand > BUDGETS["module_handwritten"]:
        warnings.append(
            f"{rel} hand-written text is {hand} bytes, budget {BUDGETS['module_handwritten']}"
        )
    return failures, warnings


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--print", dest="print_only", action="store_true")
    parser.add_argument("--print-module", metavar="ID")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    modules, problems = load_modules()
    if problems:
        for problem in problems:
            print(f"modules: {problem}", file=sys.stderr)
        return 1
    cfg = load_config()
    concepts = load_concepts()
    ctx = build_context(modules)
    current = AGENTS_MD.read_text(encoding="utf-8").replace("\r\n", "\n")
    updated = build_agents(current, cfg, concepts, modules)
    index = render_knowledge_index(cfg, concepts)
    module_texts = {m.id: render_module_file(m, ctx, read_module_file(m)) for m in modules}
    if args.print_module:
        wanted = [m for m in modules if m.id == args.print_module]
        if not wanted:
            print(f"unknown module id {args.print_module}", file=sys.stderr)
            return 1
        print(render_module_block(wanted[0], ctx, 1))
        return 0
    if args.print_only:
        print(updated)
        return 0

    failures: list[str] = []
    warnings: list[str] = []
    for module in modules:
        bad, warn = module_budget_report(module, module_texts[module.id])
        failures += bad
        warnings += warn

    if args.check:
        stale = []
        if updated != current:
            stale.append("AGENTS.md generated blocks")
        existing = (
            KNOWLEDGE_INDEX.read_text(encoding="utf-8").replace("\r\n", "\n")
            if KNOWLEDGE_INDEX.is_file()
            else ""
        )
        if existing != index:
            stale.append("docs/knowledge/index.md")
        stale += [
            f"{m.path}/AGENTS.md" for m in modules if read_module_file(m) != module_texts[m.id]
        ]
        failures += budget_report(current)
        if stale:
            print(
                f"stale: {', '.join(stale)}; run python docs/tools/agents_docs_index.py",
                file=sys.stderr,
            )
        for failure in failures:
            print(f"budget: {failure}", file=sys.stderr)
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        if stale or failures:
            return 1
        print(
            f"AGENTS.md blocks, {len(modules)} module guides and docs/knowledge/index.md "
            "are current, within budget"
        )
        return 0

    AGENTS_MD.write_text(updated, encoding="utf-8", newline="\n")
    KNOWLEDGE_INDEX.write_text(index, encoding="utf-8", newline="\n")
    created = changed = 0
    for module in modules:
        before = read_module_file(module)
        if before == module_texts[module.id]:
            continue
        module_file(module).write_bytes(module_texts[module.id].encode("utf-8"))
        if before is None:
            created += 1
        else:
            changed += 1
    print(
        f"AGENTS.md updated ({len(updated.encode('utf-8'))} bytes); knowledge index rewritten; "
        f"module guides: {created} created, {changed} updated, "
        f"{len(modules) - created - changed} unchanged"
    )
    failures += budget_report(updated)
    for failure in failures:
        print(f"budget: {failure}", file=sys.stderr)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
