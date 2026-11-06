"""The canonical compile fixtures every lane's `compile` is checked against (ADR-0063, R0).

Eight configuration items (design §10): a skill bundle, a stdio MCP server with a tool subset,
a remote MCP server, an inherit child, a seeded child, an async child, a hook script on three
events and an environment kit; and one model pin per vendor. Pins are the exact test-catalog
pins used by the projection fixtures (`tests/fixtures/projections/*/_projection.json`); the
environment kit has no catalog row, so its digest is the digest of its fixture content.
"""

from __future__ import annotations

from typing import Final

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.capabilities.hooks import HookEvent
from mission_control.domain.resolution.configuration import (
    AgentConfiguration,
    ConfigurationItem,
    ModelPin,
    Vendor,
)
from tests.fixtures.models import checked_in_catalog

_KIT_CONTENT: Final = {"kit": "python-uv", "version": "1.0.0", "tools": ["python3.12", "uv"]}
KIT_PIN: Final = f"kit.python-uv@1.0.0#{sha256_digest(_KIT_CONTENT)}"

CANONICAL_ITEMS: Final[tuple[ConfigurationItem, ...]] = (
    ConfigurationItem.create(
        kind="skill_bundle",
        name="agent-browser-skill",
        pin=(
            "skill.agent-browser@0.38.2#sha256:"
            "9c53c074d7ac6a2728b638ac1f376c5fa9eb8f71603017c3ea638c2fd40548df"
        ),
        required=False,
    ),
    ConfigurationItem.create(
        kind="mcp_server",
        name="browser",
        pin=(
            "mcp.agent-browser@0.38.2#sha256:"
            "c01113dab94c0ed749a6086d3de01b1baf49f0f6c926e43ae642af798deac473"
        ),
        required=False,
        config={"transport": "stdio", "tools": ["open", "snapshot"]},
    ),
    ConfigurationItem.create(
        kind="mcp_server",
        name="firecrawl",
        pin=(
            "mcp.firecrawl@3.28.2#sha256:"
            "702a4da344e2103ebc7ccc9d6a0990b6da82fbb73a422eeea16faa5c50f33838"
        ),
        required=False,
        config={"transport": "streamable_http"},
    ),
    ConfigurationItem.create(
        kind="subagent_profile",
        name="summarizer",
        pin=(
            "subagent.summarizer@1.0.0#sha256:"
            "d479f1971015ef0493532f5c5aae2445f16ba23102a584f4ab8c0c3c49d4f7d5"
        ),
        required=False,
        config={"child": "inherit"},
    ),
    ConfigurationItem.create(
        kind="subagent_profile",
        name="verifier",
        pin=(
            "subagent.verifier@1.0.0#sha256:"
            "88c9eae68eb300b2971a2bec9e5a26ff4179fd661d6b7d861e4c6557b9aaee14"
        ),
        required=False,
        config={"child": "seeded", "seed": ["browser"]},
    ),
    ConfigurationItem.create(
        kind="subagent_profile",
        name="async-verifier",
        pin=(
            "subagent.verifier@1.0.0#sha256:"
            "88c9eae68eb300b2971a2bec9e5a26ff4179fd661d6b7d861e4c6557b9aaee14"
        ),
        required=False,
        config={"child": "async"},
    ),
    ConfigurationItem.create(
        kind="hook_script",
        name="policy",
        pin=(
            "hook.mc-policy-template@1.0.0#sha256:"
            "0648298b48be031996277ae472115a46e7964d2ac3882e61b84351f3c3f8a547"
        ),
        required=False,
        config={
            "events": [
                HookEvent.BEFORE_TOOL.value,
                HookEvent.AFTER_TOOL.value,
                HookEvent.STOP.value,
            ]
        },
    ),
    ConfigurationItem.create(
        kind="environment_kit",
        name="python-uv",
        pin=KIT_PIN,
        required=False,
        config=_KIT_CONTENT,
    ),
)

# One pin per vendor from the checked-in Model Catalog (`deployments/biotech/models.toml`, OC-R6).
VENDOR_PINS: Final[dict[Vendor, ModelPin]] = {
    "anthropic": checked_in_catalog().get("producer.default").pin(),
    "openai": checked_in_catalog().get("judge.default").pin(),
}

INSTRUCTIONS_REF: Final = sha256_digest({"fixture": "canonical-instructions"})


def canonical_agent(
    lane_profile: str,
    *,
    vendor: Vendor = "anthropic",
    items: tuple[ConfigurationItem, ...] = CANONICAL_ITEMS,
    required: frozenset[str] = frozenset(),
) -> AgentConfiguration:
    """The canonical agent for `lane_profile`; items named in `required` are `required`."""

    chosen = tuple(
        item.model_copy(update={"required": item.name in required}) if required else item
        for item in items
    )
    return AgentConfiguration.create(
        lane_profile=lane_profile,
        node_ref="fixture/stage/produce",
        instructions_ref=INSTRUCTIONS_REF,
        model=VENDOR_PINS[vendor],
        items=chosen,
        budgets={"max_tokens": 50_000, "max_cost_usd": 0.5},
        data_class="internal",
        data_class_source="declared",
    )


__all__ = ["CANONICAL_ITEMS", "INSTRUCTIONS_REF", "KIT_PIN", "VENDOR_PINS", "canonical_agent"]
