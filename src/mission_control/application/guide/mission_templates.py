"""Curated mission templates: complete Mission Manifests with named slots, as package data.

A Coordinator that has only the MCP server cannot read an example file, and what the catalog
lists as Workflow Types are per-manifest lowered definitions, not starting points. A template is
the starting point: one `templates/<id>.mission.tmpl` file whose header (between two `---`
lines) says what it is for, when to use it, what the run produces and which slots it has, and
whose body is a
whole `mission/v2` manifest with each slot written as `{{slot_name}}`. Filling every slot gives
a manifest the compiler accepts (`tests/unit/guide/test_mission_templates.py` fills each one and
compiles it with the real compiler, so a template cannot drift from the compiler).

A template names no application: the application id is a slot. Capabilities are pinned
`<id>@latest`, never by digest, so a template follows the catalog without needing its Search
Projection. One source serves the guide topic `templates`, `template:<id>` and the `template`
facet of the Selection Workspace's search.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any, Final

import yaml

# The templates in the order a Coordinator meets them: the smallest first.
TEMPLATE_IDS: Final[tuple[str, ...]] = (
    "smallest",
    "research-report",
    "staged-review",
    "system-improvement",
)
TEMPLATE_REF_PREFIX: Final = "template:"
_FENCE: Final = "---"
_PACKAGE: Final = "mission_control.application.guide"
_SLOT: Final = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
_HEADER_KEYS: Final = frozenset(
    {"id", "title", "purpose", "use_when", "produces", "slots", "notes"}
)


@dataclass(frozen=True, slots=True)
class TemplateSlot:
    """One named slot: what to write there and one valid value."""

    name: str
    description: str
    example: str


@dataclass(frozen=True, slots=True)
class MissionTemplate:
    id: str
    title: str
    purpose: str
    use_when: str
    produces: str
    slots: tuple[TemplateSlot, ...]
    notes: tuple[str, ...]
    # The manifest with each slot as `{{slot_name}}`.
    manifest: str

    @property
    def ref(self) -> str:
        return f"{TEMPLATE_REF_PREFIX}{self.id}"

    def examples(self) -> dict[str, str]:
        """Every slot's example value: together they fill the template."""

        return {slot.name: slot.example for slot in self.slots}

    def fill(self, values: Mapping[str, str]) -> str:
        """The manifest with every slot replaced; `ValueError` names a slot without a value
        and a value that names no slot."""

        names = {slot.name for slot in self.slots}
        missing = sorted(names - values.keys())
        unknown = sorted(values.keys() - names)
        if missing or unknown:
            raise ValueError(
                f"template {self.id}: slots without a value {missing}; values without a slot "
                f"{unknown}"
            )
        return _SLOT.sub(lambda match: str(values[match.group(1)]), self.manifest)


def parse_template(text: str, *, expected_id: str) -> MissionTemplate:
    """A template file's header and manifest; `ValueError` names what is malformed. The slots
    the header declares are exactly the slots the manifest uses."""

    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != _FENCE:
        raise ValueError(f"mission template {expected_id} has no header")
    try:
        end = lines.index(_FENCE, 1)
    except ValueError:
        raise ValueError(f"mission template {expected_id} header is not closed") from None
    header: Any = yaml.safe_load("\n".join(lines[1:end]))
    if not isinstance(header, dict) or set(header) - _HEADER_KEYS:
        raise ValueError(f"mission template {expected_id} header has unknown keys")
    if header.get("id") != expected_id:
        raise ValueError(f"mission template {expected_id} declares id {header.get('id')}")
    fields = {}
    for name in ("title", "purpose", "use_when", "produces"):
        value = header.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"mission template {expected_id} header needs {name}")
        fields[name] = value.strip()
    declared = header.get("slots")
    if not isinstance(declared, dict) or not declared:
        raise ValueError(f"mission template {expected_id} declares no slots")
    slots = []
    for name, slot in declared.items():
        if (
            not isinstance(slot, dict)
            or set(slot) != {"description", "example"}
            or not all(isinstance(slot[key], str) and slot[key].strip() for key in slot)
        ):
            raise ValueError(
                f"mission template {expected_id} slot {name} is description and example"
            )
        slots.append(TemplateSlot(str(name), slot["description"].strip(), slot["example"].strip()))
    notes = header.get("notes") or []
    if not isinstance(notes, list) or not all(isinstance(note, str) for note in notes):
        raise ValueError(f"mission template {expected_id} notes are a list of sentences")
    manifest = "\n".join(lines[end + 1 :]).strip() + "\n"
    used = set(_SLOT.findall(manifest))
    if used != {slot.name for slot in slots}:
        raise ValueError(
            f"mission template {expected_id} declares slots {sorted(slot.name for slot in slots)} "
            f"but its manifest uses {sorted(used)}"
        )
    return MissionTemplate(
        id=expected_id,
        slots=tuple(slots),
        notes=tuple(note.strip() for note in notes),
        manifest=manifest,
        **fields,
    )


@cache
def load_template(template_id: str) -> MissionTemplate:
    """One template of `templates/`, read once per process (`KeyError` for an unknown id)."""

    if template_id not in TEMPLATE_IDS:
        raise KeyError(template_id)
    source = resources.files(_PACKAGE).joinpath("templates", f"{template_id}.mission.tmpl")
    return parse_template(source.read_text(encoding="utf-8"), expected_id=template_id)


def mission_templates() -> tuple[MissionTemplate, ...]:
    return tuple(load_template(template_id) for template_id in TEMPLATE_IDS)


def template_markdown(template: MissionTemplate) -> str:
    """What `template:<id>` answers with: the header, the slots and the manifest to fill."""

    lines = [
        f"# Template `{template.id}`: {template.title}",
        "",
        template.purpose,
        "",
        f"- Use it when: {template.use_when}",
        f"- The run produces: {template.produces}",
        "",
        "## Slots",
        "",
        "Replace every `{{slot}}` in the manifest with the user's answer, then compile it "
        "(topic `launch`). A slot value is one line of text; a slot that occurs more than once "
        "takes the same value everywhere.",
        "",
        "| Slot | What to write | Example |",
        "| --- | --- | --- |",
        *(f"| `{slot.name}` | {slot.description} | `{slot.example}` |" for slot in template.slots),
    ]
    if template.notes:
        lines += ["", "## Notes", "", *(f"- {note}" for note in template.notes)]
    lines += ["", "## Manifest", "", "```yaml", template.manifest.rstrip("\n"), "```"]
    return "\n".join(lines)


def template_document(template: MissionTemplate) -> dict[str, Any]:
    """The same answer as data: the header fields, the slots and the manifest text."""

    return {
        "id": template.id,
        "title": template.title,
        "purpose": template.purpose,
        "use_when": template.use_when,
        "produces": template.produces,
        "slots": [
            {"name": slot.name, "description": slot.description, "example": slot.example}
            for slot in template.slots
        ],
        "notes": list(template.notes),
        "manifest_yaml": template.manifest,
    }


__all__ = [
    "TEMPLATE_IDS",
    "TEMPLATE_REF_PREFIX",
    "MissionTemplate",
    "TemplateSlot",
    "load_template",
    "mission_templates",
    "parse_template",
    "template_document",
    "template_markdown",
]
