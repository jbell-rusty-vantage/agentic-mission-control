"""The capability search source-set digest is byte ordered on both sides (MC-F, component 1.16.0).

The application computes the expected digest in Python codepoint order; the component's
`activate_generation` recomputes it with `string_agg(... ORDER BY ...)`. Until 0075 the text keys
sorted under the database's default collation, and on `en_US.utf8` (compose, CI, Supabase) the
seeded GitHub tool ids below sort differently, so no rebuild could activate. These checks need no
database: they pin the Python order and require `COLLATE "C"` on every text sort key of every
ordered aggregate in the newest built release's effective function definitions.
"""

from __future__ import annotations

import hashlib
import inspect
import re
from pathlib import Path

from mission_control.adapters.postgres.capability.capability_search_repository import (
    PostgresCatalogSearchRepository,
)
from mission_control.application.capabilities.catalog_projection_generation import (
    projection_source_set_digest,
)
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef

ROOT = Path(__file__).resolve().parents[3]
RELEASES = ROOT / "packages" / "mission-control-db-contract" / "releases"
# `mc.catalog.agent-capabilities@1.1.0`: a locale collation ignores `-` on its first level.
GITHUB_IDS = (
    "mcp.github.tool.list-issue-fields",
    "mcp.github.tool.list-issues",
    "mcp.github.tool.list-issue-types",
)
DIGEST = "sha256:" + "a" * 64
# Integer sort keys need no collation.
INTEGER_KEYS = frozenset({"d.revision"})
_FUNCTION = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+([a-z_]+\.[a-z_]+)\s*\(.*?\bAS\s+(\$[a-z_]*\$)(.*?)\2",
    re.IGNORECASE | re.DOTALL,
)
_AGGREGATE = re.compile(r"\b(string_agg|array_agg|json_agg|jsonb_agg)\s*\(", re.IGNORECASE)


def _refs(ids: tuple[str, ...]) -> tuple[ExactDefinitionRef, ...]:
    return tuple(
        ExactDefinitionRef(kind=DefinitionKind.MCP_TOOL, logical_id=item, revision=1, digest=DIGEST)
        for item in ids
    )


def _material_digest(ids: list[str]) -> str:
    lines = "\n".join(f"mcp_tool|{item}|1|{DIGEST}" for item in ids)
    return "sha256:" + hashlib.sha256(lines.encode("utf-8")).hexdigest()


def _locale_like(value: str) -> str:
    """A first-level approximation of `en_US.utf8`: punctuation is ignored."""

    return value.replace("-", "")


def newest_built_release() -> Path:
    built = [
        path
        for path in RELEASES.iterdir()
        if path.is_dir()
        and (path / "component" / "manifest.json").is_file()
        and all(part.isdigit() for part in path.name.split("."))
    ]
    return max(built, key=lambda item: tuple(int(part) for part in item.name.split(".")))


def effective_functions(release: Path) -> dict[str, tuple[str, str]]:
    """name -> (migration file, body) of the LAST definition of each function in the release."""

    functions: dict[str, tuple[str, str]] = {}
    for path in sorted((release / "component" / "migrations").glob("*.sql")):
        for match in _FUNCTION.finditer(path.read_text(encoding="utf-8")):
            functions[match.group(1).lower()] = (path.name, match.group(3))
    return functions


def ordered_aggregate_keys(body: str) -> list[list[str]]:
    """The ORDER BY keys of every ordered aggregate call in ``body``."""

    found: list[list[str]] = []
    for match in _AGGREGATE.finditer(body):
        depth, start = 1, match.end()
        index = start
        while depth and index < len(body):
            depth += {"(": 1, ")": -1}.get(body[index], 0)
            index += 1
        call = body[start : index - 1]
        order = re.search(r"\bORDER\s+BY\b(.*)$", call, re.IGNORECASE | re.DOTALL)
        if order is None:
            continue
        keys, depth, current = [], 0, ""
        for char in order.group(1):
            depth += {"(": 1, ")": -1}.get(char, 0)
            if char == "," and depth == 0:
                keys.append(" ".join(current.split()))
                current = ""
            else:
                current += char
        keys.append(" ".join(current.split()))
        found.append(keys)
    return found


def test_the_application_digest_is_codepoint_ordered_and_differs_from_locale_order() -> None:
    byte_order = sorted(GITHUB_IDS, key=lambda item: item.encode("utf-8"))
    assert byte_order == [
        "mcp.github.tool.list-issue-fields",
        "mcp.github.tool.list-issue-types",
        "mcp.github.tool.list-issues",
    ]
    locale_order = sorted(GITHUB_IDS, key=_locale_like)
    assert locale_order != byte_order  # the order that broke activation on en_US.utf8
    digest = projection_source_set_digest(_refs(GITHUB_IDS))
    assert digest == _material_digest(byte_order)
    assert digest != _material_digest(locale_order)
    # The input order never matters, only the byte order of the keys.
    assert projection_source_set_digest(_refs(tuple(reversed(GITHUB_IDS)))) == digest
    # Python codepoint order is UTF-8 byte order, which is what COLLATE "C" sorts by.
    sample = ["z", "é", "a-b", "ab", "a_b", "A", "ä", "😀"]
    assert sorted(sample) == sorted(sample, key=lambda item: item.encode("utf-8"))


def test_activate_generation_sorts_every_text_key_in_byte_order() -> None:
    release = newest_built_release()
    functions = effective_functions(release)
    migration, body = functions["mission_control_search.activate_generation"]
    assert migration == "0075_capability_search_byte_order_digest.sql", release.name
    (keys,) = ordered_aggregate_keys(body)
    assert keys == [
        'd.asset_kind COLLATE "C"',
        'd.logical_id COLLATE "C"',
        "d.revision",
        'd.source_digest COLLATE "C"',
    ]


def test_every_ordered_aggregate_of_the_newest_release_sorts_text_in_byte_order() -> None:
    """A digest or fingerprint built from database-ordered text must not depend on the
    installation's collation: every non-integer key carries COLLATE "C"."""

    offenders = []
    for name, (migration, body) in effective_functions(newest_built_release()).items():
        for keys in ordered_aggregate_keys(body):
            for key in keys:
                if key not in INTEGER_KEYS and 'COLLATE "C"' not in key:
                    offenders.append(f"{migration}:{name}: {key}")
    assert offenders == []


def test_the_generation_rows_are_read_in_byte_order() -> None:
    source = inspect.getsource(PostgresCatalogSearchRepository.list_generation)
    order = re.search(r"ORDER BY(.*?)\"\"\"", source, re.DOTALL)
    assert order is not None
    assert " ".join(order.group(1).split()) == (
        'asset_kind COLLATE "C", logical_id COLLATE "C", revision, source_digest COLLATE "C"'
    )
