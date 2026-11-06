"""W1 D27: role separation of the knowledge tools (OUTPUT-CONTRACTS, ADR-0058).

An independent evaluator (the GoalDirected verifier) is bound to the producer's owner position,
so position ownership alone never refused it a producer act: in run 9cc17684 the verifier
re-submitted the producer's report as revision 2 and triggered a second assessment and review.
It may read and verify; it never registers, applies or submits for the promises it evaluates
(its verdict is its structured observation). The launch author leaves these tools out of the
verifier's agent configuration and the toolset refuses them for an evaluator invocation.
"""

from __future__ import annotations

from typing import Final

# The producer's acts, by knowledge tool name.
PRODUCER_TOOLS: Final = frozenset({"report_register", "knowledge_apply", "submit_output"})
# The same tools as catalog capabilities (seed `mc.catalog.knowledge-tools`).
PRODUCER_TOOL_CAPABILITIES: Final = frozenset(
    {"tool.knowledge-report-register", "tool.knowledge-apply", "tool.knowledge-submit-output"}
)

__all__ = ["PRODUCER_TOOLS", "PRODUCER_TOOL_CAPABILITIES"]
