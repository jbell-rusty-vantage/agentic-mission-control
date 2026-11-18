"""The RRM-009 qualification MCP server with a large deterministic tool result (FX-TR-STEP).

The same single tool as `mission_control.adapters.agent_server.qualification.wp_cp_040_mcp`
(`lookup_binding_marker(code: str) -> str`, the same name, description and input schema, so
the exact binding's `MCP_TOOL_SCHEMA_DIGEST` is unchanged), but the result is the marker
line the scripted cognition asserts (`MCP-BOUND::{code}::EXACT`) followed by deterministic
padding lines up to at least `PAYLOAD_MIN_BYTES` (12 KiB): one tool result over the 8 KiB
excerpt cap of the frame writer, so the Transcript's `--full` read has a body to resolve
(TRACING-PROPOSAL §P3.3, §P9 FX-TR-STEP).

Launched by the worker as a stdio subprocess (`sys.executable <this file>`), registered by
the fixture binding (`rrm009_production_stack.tracing_mcp_server`); importable too, so the
proofs compute the expected payload with `marker_payload`. No `tests.*` import: the server
process starts from any working directory.
"""

from __future__ import annotations

PAYLOAD_MIN_BYTES = 12 * 1024
PADDING_LINE = "RRM009-PAD {index:05d}: deterministic filler for the over-cap tool result"
LAST_LINE_PREFIX = "RRM009-PAD-END"


def marker_payload(code: str) -> str:
    """The marker line, padding lines to at least `PAYLOAD_MIN_BYTES`, and a closing line."""

    lines = [f"MCP-BOUND::{code}::EXACT"]
    size = len(lines[0]) + 1
    index = 0
    while size < PAYLOAD_MIN_BYTES:
        line = PADDING_LINE.format(index=index)
        lines.append(line)
        size += len(line) + 1
        index += 1
    lines.append(f"{LAST_LINE_PREFIX} lines={index}")
    return "\n".join(lines)


def main() -> None:
    from fastmcp import FastMCP

    server = FastMCP(
        "belllabs-rrm009-tracing",
        instructions="One deterministic read-only qualification surface with a large result.",
    )

    @server.tool(
        name="lookup_binding_marker",
        description="Return the exact BellLabs qualification marker for a binding code.",
    )
    def lookup_binding_marker(code: str) -> str:
        """Return a deterministic marker without network or mutable discovery."""

        return marker_payload(code)

    server.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
