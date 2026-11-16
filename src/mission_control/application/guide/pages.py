"""The guide's judgment pages: Markdown package data with a small frontmatter.

A page says what to do and why; it restates no fact a registry holds. Its frontmatter is three
`key: value` lines (`id`, `title`, `summary`). Its body names operations as `{op:<id>}`
(`operations.py`) and marks where the service puts the section it generates from the registries
with one `{{generated}}` line (a page without the marker gets the section appended); a second
generated section of the same page is marked `{{generated:<name>}}`.

`pages/` holds the start page (`index`) and the topics; `tools/` holds the field notes of the
tools whose request is an object too large for a tool listing (`tool_docs.py`). The mission
templates are package data of their own (`templates/`, `mission_templates.py`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Final

INDEX: Final = "index"
# The topics in the order a Coordinator meets them.
TOPIC_IDS: Final[tuple[str, ...]] = (
    "interview",
    "workflows",
    "templates",
    "manifest",
    "lanes",
    "models",
    "capabilities",
    "launch",
    "observe",
    "control",
)
GENERATED_MARKER: Final = "{{generated}}"
_FENCE: Final = "---"
_PACKAGE: Final = "mission_control.application.guide"


@dataclass(frozen=True, slots=True)
class PageSource:
    id: str
    title: str
    summary: str
    body: str


def parse_page(text: str, *, expected_id: str) -> PageSource:
    """A page file's frontmatter and body; `ValueError` names what is malformed."""

    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != _FENCE:
        raise ValueError(f"guide page {expected_id} has no frontmatter")
    try:
        end = lines.index(_FENCE, 1)
    except ValueError:
        raise ValueError(f"guide page {expected_id} frontmatter is not closed") from None
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        if not separator or not key.strip() or not value.strip():
            raise ValueError(f"guide page {expected_id} frontmatter line is not `key: value`")
        fields[key.strip()] = value.strip()
    if set(fields) != {"id", "title", "summary"}:
        raise ValueError(f"guide page {expected_id} frontmatter is exactly id, title, summary")
    if fields["id"] != expected_id:
        raise ValueError(f"guide page {expected_id} declares id {fields['id']}")
    return PageSource(
        id=fields["id"],
        title=fields["title"],
        summary=fields["summary"],
        body="\n".join(lines[end + 1 :]).strip(),
    )


@cache
def load_page(directory: str, page_id: str) -> PageSource:
    """One page of `pages/` or `tools/`, read once per process."""

    source = resources.files(_PACKAGE).joinpath(directory, f"{page_id}.md")
    return parse_page(source.read_text(encoding="utf-8"), expected_id=page_id)


def insert_generated(body: str, generated: str, named: Mapping[str, str] | None = None) -> str:
    """`body` with the generated section at its marker, or appended; an empty section leaves
    no blank marker behind. A page with more than one generated section marks each further
    one `{{generated:<name>}}`, filled from `named`."""

    section = generated.strip()
    if GENERATED_MARKER in body:
        merged = body.replace(GENERATED_MARKER, section)
    else:
        merged = f"{body}\n\n{section}" if section else body
    for name, text in (named or {}).items():
        merged = merged.replace(f"{{{{generated:{name}}}}}", text.strip())
    return re.sub(r"\n{3,}", "\n\n", merged).strip()


__all__ = [
    "GENERATED_MARKER",
    "INDEX",
    "TOPIC_IDS",
    "PageSource",
    "insert_generated",
    "load_page",
    "parse_page",
]
