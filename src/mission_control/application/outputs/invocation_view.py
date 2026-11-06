"""Bounded producer projection of host-pinned contracts and persisted output state.

No run/actor input, evaluator payloads, or side effects. Fulfillment is explicitly a recorded
frontier decision, never a claim that current heads were evaluated by this read.
"""

from __future__ import annotations

from typing import Any

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.ports.knowledge import OutputSubmissionStore
from mission_control.application.ports.outputs import OutputContractStore
from mission_control.domain.outputs.contracts import OutputObligation


async def inspect_invocation(
    contracts: OutputContractStore | None,
    submissions: OutputSubmissionStore,
    access: InvocationAccess,
    *,
    position: str | None,
    obligation_key: str | None = None,
) -> dict[str, Any]:
    def refused(code: str, message: str) -> dict[str, Any]:
        return {
            "tool": "submit_output",
            "ok": False,
            "result": None,
            "refusal": {"code": code, "message": message},
        }

    if position is None:
        return refused("POSITION_UNBOUND", "the host must bind an owner position")
    if contracts is None:
        return refused("INVOCATION_UNPINNED", "no named output contract store is bound")
    identity = access.identity()
    pins = await contracts.invocation_pins(identity.scope, identity.invocation_ref)
    owned: list[OutputObligation] = []
    for key in sorted(pins):
        if obligation_key is not None and key != obligation_key:
            continue
        obligation = await contracts.obligation_revision(
            identity.scope, identity.run_id, key, pins[key]
        )
        if obligation is not None and obligation.owner_position == position:
            owned.append(obligation)
    if obligation_key is not None and not owned:
        return refused("OBLIGATION_UNDECLARED", "no owned pinned obligation has that key")
    rows = await submissions.list_for_invocation(identity.scope, identity.invocation_ref)
    accepted = await contracts.accepted_outputs(identity.scope, identity.run_id)
    result: list[dict[str, Any]] = []
    for obligation in owned[:64]:
        latest = max(
            (row for row in rows if row.obligation_id == obligation.key),
            key=lambda row: row.revision,
            default=None,
        )
        heads = [
            {"deliverable_id": item.deliverable_id, "revision_id": item.revision_id}
            for item in accepted
            if item.obligation_key == obligation.key
        ][:64]
        recorded = await contracts.latest_fulfillment(
            identity.scope, identity.run_id, obligation.key, obligation.revision
        )
        fulfillment = None
        if recorded is not None:
            set_id, decision = recorded
            fulfillment = {
                "output_set_id": set_id,
                "disposition": decision.disposition,
                "distinct_count": decision.distinct_count,
                "unmet": [
                    {"code": item.code, "owner": item.owner, "waiting": item.waiting}
                    for item in decision.unmet
                ],
                "meaning": "recorded_frontier_decision; not a fresh evaluation",
            }
        result.append(
            {
                "obligation": obligation.document(),
                "contract_digest": obligation.contract_digest,
                "latest_submission": None
                if latest is None
                else {
                    "submission_id": latest.submission_id,
                    "revision": latest.revision,
                    "mode": latest.selection.get("submit", {}).get("mode", "final"),
                    "assessment_state": latest.assessment_state,
                },
                "accepted_heads": heads,
                "recorded_fulfillment": fulfillment,
            }
        )
    return {
        "tool": "submit_output",
        "ok": True,
        "refusal": None,
        "result": {
            "obligations": result,
            "truncated": len(owned) > 64,
            "fulfillment": "recorded_decisions_only",
            "submission_semantics": (
                "accepted records a draft; promotion and fulfillment are separate"
            ),
        },
    }
