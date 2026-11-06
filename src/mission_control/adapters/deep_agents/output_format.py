"""W1 D16: the JSON Schema a ``provider_native`` structured response sends to Anthropic.

langchain-anthropic 1.5.4 turns a LangChain ``ProviderStrategy`` into
``output_config.format = {"type": "json_schema", "schema": anthropic.transform_schema(schema)}``
(``chat_models._convert_to_anthropic_output_config_format``). ``transform_schema`` (anthropic
0.120.2) normalizes what it can: every object gets ``additionalProperties: false`` and any
keyword outside the supported subset is moved into the description. It does not refuse a
recursive schema, which the API does.

The supported subset (Anthropic structured outputs,
https://platform.claude.com/docs/en/build-with-claude/structured-outputs (its JSON Schema
limitations; the page the ``models.toml`` rows cite as [A-struct]); secondary: the
``claude-api`` skill, ``shared/tool-use-concepts.md``): the basic types, ``enum``,
``const``, ``anyOf``, ``allOf``, ``$ref``/``$defs``, the listed string formats,
``additionalProperties: false`` on every object, ``minItems`` 0 or 1; not recursive schemas,
numerical, string-length or complex array constraints. :func:`anthropic_output_schema` returns
exactly the schema langchain-anthropic would send and refuses one outside that subset, so a
nonconforming node schema fails before any model call instead of as a provider 400.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Final

from langchain_anthropic.chat_models import _convert_to_anthropic_output_config_format
from pydantic import BaseModel

SUPPORTED_KEYWORDS: Final = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "const",
        "anyOf",
        "allOf",
        "$ref",
        "$defs",
        "description",
        "title",
        "format",
        "minItems",
    }
)
SUPPORTED_TYPES: Final = frozenset(
    {"object", "array", "string", "integer", "number", "boolean", "null"}
)
SUPPORTED_FORMATS: Final = frozenset(
    {
        "date-time",
        "time",
        "date",
        "duration",
        "email",
        "hostname",
        "uri",
        "ipv4",
        "ipv6",
        "uuid",
    }
)


# Published complexity limits (structured-outputs page, "Explicit limits"): across all strict
# tool schemas and JSON output schemas of a request, at most 24 optional parameters (each
# property not in `required`) and 16 parameters with union types (`anyOf` or a type array).
OPTIONAL_PARAMETER_LIMIT: Final = 24
UNION_PARAMETER_LIMIT: Final = 16
# Beyond them the API enforces an unpublished compiled-grammar size limit ("Schema is too
# complex for compilation"). W1 D18: the executor observation (30 properties, 23 optional, 1
# union) is inside the published limits and was refused on every request (run 457bd952).
# The MC_* budget below is a heuristic Mission Control chose for itself, NOT an Anthropic limit:
# set well below that one observed failure, it may refuse a schema Anthropic would compile; a
# refused schema binds through `tool_auto` (no grammar) instead. The judge and auditor answers
# (8 and 6 properties, 3 optional, 1 union) are inside it.
MC_PROPERTY_BUDGET: Final = 24
MC_OPTIONAL_BUDGET: Final = 12
MC_UNION_BUDGET: Final = 8


class AnthropicOutputSchemaRefused(ValueError):
    """A ``provider_native`` schema Anthropic structured outputs would refuse."""

    def __init__(self, issues: tuple[str, ...]) -> None:
        super().__init__("; ".join(issues))
        self.issues = issues


def _nodes(schema: Any, pointer: str) -> Iterator[tuple[str, dict[str, Any]]]:
    if not isinstance(schema, dict):
        return
    yield pointer, schema
    for name, child in (schema.get("properties") or {}).items():
        yield from _nodes(child, f"{pointer}/properties/{name}")
    for name, child in (schema.get("$defs") or {}).items():
        yield from _nodes(child, f"{pointer}/$defs/{name}")
    if isinstance(schema.get("items"), dict):
        yield from _nodes(schema["items"], f"{pointer}/items")
    for key in ("anyOf", "allOf"):
        for index, child in enumerate(schema.get(key) or ()):
            yield from _nodes(child, f"{pointer}/{key}/{index}")


def _refs(schema: Any) -> Iterator[str]:
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if isinstance(ref, str):
            yield ref
        for value in schema.values():
            yield from _refs(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from _refs(value)


def _recursive(defs: dict[str, Any]) -> tuple[str, ...]:
    edges = {
        name: {ref.removeprefix("#/$defs/") for ref in _refs(body) if ref.startswith("#/$defs/")}
        for name, body in defs.items()
    }
    cyclic: list[str] = []
    for start in sorted(edges):
        stack, seen = list(edges[start]), set()
        while stack:
            current = stack.pop()
            if current == start:
                cyclic.append(start)
                break
            if current in seen or current not in edges:
                continue
            seen.add(current)
            stack.extend(edges[current])
    return tuple(cyclic)


def output_schema_issues(schema: dict[str, Any]) -> tuple[str, ...]:
    """Why an already transformed schema falls outside the supported subset (empty: none)."""

    issues: list[str] = []
    for pointer, node in _nodes(schema, "#"):
        unknown = sorted(set(node) - SUPPORTED_KEYWORDS)
        if unknown:
            issues.append(f"{pointer}: unsupported keywords {unknown}")
        kind = node.get("type")
        kinds = kind if isinstance(kind, list) else [kind] if kind is not None else []
        if any(item not in SUPPORTED_TYPES for item in kinds):
            issues.append(f"{pointer}: unsupported type {kind!r}")
        if "object" in kinds and node.get("additionalProperties") is not False:
            issues.append(f"{pointer}: an object needs additionalProperties false")
        if "format" in node and node["format"] not in SUPPORTED_FORMATS:
            issues.append(f"{pointer}: unsupported string format {node['format']!r}")
        if "minItems" in node and node["minItems"] not in (0, 1):
            issues.append(f"{pointer}: minItems must be 0 or 1")
    cyclic = _recursive(schema.get("$defs") or {})
    if cyclic:
        issues.append(f"recursive definitions {list(cyclic)} are not supported")
    issues.extend(complexity_issues(schema))
    return tuple(issues)


def complexity(schema: dict[str, Any]) -> tuple[int, int, int]:
    """(properties, optional parameters, union-typed parameters) of a transformed schema,
    counted over every object node (each `$defs` entry once, as the grammar compiles it)."""

    properties = optional = unions = 0
    for _pointer, node in _nodes(schema, "#"):
        declared = node.get("properties")
        if not isinstance(declared, dict):
            continue
        required = set(node.get("required") or ())
        for name, child in declared.items():
            properties += 1
            if name not in required:
                optional += 1
            if isinstance(child, dict) and (
                "anyOf" in child or isinstance(child.get("type"), list)
            ):
                unions += 1
    return properties, optional, unions


def complexity_issues(schema: dict[str, Any]) -> tuple[str, ...]:
    """W1 D18: the published limits and Mission Control's conservative grammar budget."""

    properties, optional, unions = complexity(schema)
    issues: list[str] = []
    if optional > OPTIONAL_PARAMETER_LIMIT:
        issues.append(
            f"{optional} optional parameters (published limit {OPTIONAL_PARAMETER_LIMIT})"
        )
    if unions > UNION_PARAMETER_LIMIT:
        issues.append(f"{unions} union-typed parameters (published limit {UNION_PARAMETER_LIMIT})")
    if properties > MC_PROPERTY_BUDGET or optional > MC_OPTIONAL_BUDGET or unions > MC_UNION_BUDGET:
        issues.append(
            f"schema too complex for a compiled grammar: {properties} properties, {optional} "
            f"optional, {unions} union-typed (Mission Control budget {MC_PROPERTY_BUDGET}/"
            f"{MC_OPTIONAL_BUDGET}/{MC_UNION_BUDGET}, below the W1 D18 failure); bind it through "
            "tool_auto"
        )
    return tuple(issues)


def anthropic_output_schema(schema: type[BaseModel] | dict[str, Any]) -> dict[str, Any]:
    """The exact ``output_config.format.schema`` langchain-anthropic sends for ``schema``.

    Raises :class:`AnthropicOutputSchemaRefused` when it is outside the supported subset."""

    try:
        # The pinned langchain-anthropic's own conversion (private; the version is pinned in
        # uv.lock), so the checked schema is byte for byte the one it sends.
        transformed = _convert_to_anthropic_output_config_format(schema)["schema"]
    except (TypeError, ValueError) as error:
        raise AnthropicOutputSchemaRefused((f"not a JSON schema: {error}",)) from None
    issues = output_schema_issues(transformed)
    if issues:
        raise AnthropicOutputSchemaRefused(issues)
    return transformed


__all__ = [
    "MC_OPTIONAL_BUDGET",
    "MC_PROPERTY_BUDGET",
    "MC_UNION_BUDGET",
    "OPTIONAL_PARAMETER_LIMIT",
    "SUPPORTED_FORMATS",
    "SUPPORTED_KEYWORDS",
    "SUPPORTED_TYPES",
    "UNION_PARAMETER_LIMIT",
    "AnthropicOutputSchemaRefused",
    "anthropic_output_schema",
    "complexity",
    "complexity_issues",
    "output_schema_issues",
]
