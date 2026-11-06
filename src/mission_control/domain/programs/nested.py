"""Recursive composition at runtime: activation, exact export and control lineage (OVE-176).

A compiled :class:`~mission_control.domain.authoring.nested_bodies.NestedBody` executes as its own
child run of the same mission revision: its own run control, family state, budget account,
governors and journal (00-EXECUTION_PROGRAM_MODEL §5.2 "Every activation receives a
system-execution identity, lifecycle, local governor counters, allocated budget ..."). The parent
family admits the hosting unit exactly as it admits an operation (the unit's reservation is the
body's allocated budget) and then, instead of an operation child, starts the child run's root as a
Temporal child workflow.

Pure rules only:

- identity: :func:`nested_request_id` is deterministic in the parent run, the host unit and the
  unit's semantic attempt, so a restart or replay activates the same child run, and a revisit or
  retry (a new semantic attempt) activates a new one;
- budget containment: :func:`contained_ceiling` never lets a child spend more than the parent unit
  reserved for it;
- exact export: :func:`project_exports` carries only the body's declared exports, only accepted
  revisions, and accepts the composite only when its final projection holds every required export;
  an early export of an incomplete composite is visible lineage, never a parent output;
- terminal reflection: :func:`child_terminal` maps the child's own outcome; the parent unit result
  (:func:`stage_result`) mirrors it (``completed`` / ``failed`` / ``cancelled``);
- control lineage: :data:`PROPAGATED_CONTROLS` are the parent controls a hosted body receives
  through its own run control (cancel, pause, resume); never a raw Temporal cancel.

Extension point (WI-14 Swarm, WI-15 Evaluator Optimizer): a family that hosts N member bodies or
producer/evaluator rounds activates each with its own host id (``member:<n>``,
``round:<r>:producer``) through the same request, projection and control vocabulary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.nested_bodies import NestedBody, NestedExport
from mission_control.domain.programs.contracts import BellLabsRunInput

NESTED_ISSUER: Final = "mc.nested-body"
NESTED_EXPORT_SCHEMA: Final = "mc.nested_export_receipt.v1"
PROPAGATED_CONTROLS: Final = frozenset({"cancel", "pause", "resume"})
# The spend dimensions a hosting unit reserves for its body; governor counters (iterations,
# attempts, concurrency) are the child's own and are not spend.
SPEND_DIMENSIONS: Final = frozenset(
    {"tokens.total", "tool.calls.total", "currency.estimated_micros", "time.elapsed_ms"}
)

NestedOutcome = Literal[
    "accepted", "not_accepted", "cancelled", "execution_failed", "governor_exhausted"
]
ChildEnd = Literal["returned", "failed", "cancelled", "terminated", "timed_out"]
ParentFamily = Literal["StageGraph", "GoalDirected"]
ControlKind = Literal["cancel", "pause", "resume"]


def nested_request_id(parent_run_id: str, host_id: str, semantic_attempt_id: str) -> str:
    """The child run's admission request id: one per parent unit attempt (bounded length)."""

    digest = sha256_digest(
        {"parent": parent_run_id, "host": host_id, "attempt": semantic_attempt_id}
    )
    return f"nested:{digest.removeprefix('sha256:')[:40]}"


def contained_ceiling(
    reservation: Mapping[str, int], configured: Mapping[str, int]
) -> dict[str, int]:
    """The child's hard caps: never more spend than the parent unit reserved for it.

    A spend dimension the parent reserved bounds the child at ``min(configured, reserved)``; a
    spend dimension it did not reserve is capped at zero (no uncharged spend). The child's own
    governor counters keep their compiled ceilings. Negative amounts never pass.
    """

    if any(amount < 0 for amount in reservation.values()):
        raise ValueError("a parent reservation is never negative")
    ceiling = {name: max(amount, 0) for name, amount in configured.items()}
    for name in SPEND_DIMENSIONS & set(ceiling):
        ceiling[name] = min(ceiling[name], reservation.get(name, 0))
    for name in SPEND_DIMENSIONS & set(reservation):
        ceiling.setdefault(name, reservation[name])
    return ceiling


def uncontained(reservation: Mapping[str, int], ceiling: Mapping[str, int]) -> tuple[str, ...]:
    """Spend dimensions on which the child could spend more than the parent reserved."""

    return tuple(
        sorted(
            name
            for name in SPEND_DIMENSIONS & set(ceiling)
            if ceiling[name] > reservation.get(name, 0)
        )
    )


def capped_usage(consumed: Mapping[str, int], ceiling: Mapping[str, int]) -> dict[str, int]:
    """The child's spend charged to the parent unit: its spend dimensions, within its
    admitted ceiling (equal to what it consumed whenever the ceiling held)."""

    return {
        name: min(amount, ceiling.get(name, amount))
        for name, amount in sorted(consumed.items())
        if name in SPEND_DIMENSIONS and amount > 0
    }


@dataclass(frozen=True)
class NestedActivationRequest:
    """The parent unit's request to activate its nested body (the ``nested_program.activate``
    activity input). ``parent_reservation`` is what the parent admitted for the unit."""

    request_scope: str
    parent_run_id: str
    parent_family: ParentFamily
    host_id: str
    semantic_attempt_id: str
    parent_reservation_id: str
    parent_reservation: dict[str, int]
    body: NestedBody
    parent_execution_epoch: int
    child_task_queue: str
    occurred_at: datetime
    correlation_id: str = ""

    @property
    def request_id(self) -> str:
        return nested_request_id(self.parent_run_id, self.host_id, self.semantic_attempt_id)


@dataclass(frozen=True)
class NestedActivation:
    """The admitted child run and its root input, or a typed refusal (nothing started)."""

    activated: bool
    child_run_id: str = ""
    child_root: BellLabsRunInput | None = None
    budget_ceiling: dict[str, int] = field(default_factory=dict)
    reason_code: str = ""
    detail: str = ""

    @property
    def child_workflow_id(self) -> str:
        return self.child_root.workflow_id if self.child_root is not None else ""


@dataclass(frozen=True)
class ExportedOutput:
    output: str
    source: str
    timing: Literal["final", "early"]
    refs: tuple[str, ...]


@dataclass(frozen=True)
class NestedProjection:
    """The export receipt of one nested activation (``mc.nested_export_receipt.v1``)."""

    child_run_id: str
    position: str
    outcome: NestedOutcome
    composite_accepted: bool
    exports: tuple[ExportedOutput, ...] = ()
    early_exports: tuple[ExportedOutput, ...] = ()
    missing_required: tuple[str, ...] = ()
    actual_usage: dict[str, int] = field(default_factory=dict)
    cause: str = ""
    # The parent's own submitted revisions each adopted export became (``adopt_into`` names
    # the parent obligation); parent assessment and fulfillment decide them unchanged.
    adopted: tuple[str, ...] = ()

    @property
    def output_refs(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(ref for item in self.exports for ref in item.refs))

    def receipt(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "schema": NESTED_EXPORT_SCHEMA,
            "child_run_id": self.child_run_id,
            "position": self.position,
            "outcome": self.outcome,
            "composite_accepted": self.composite_accepted,
            "exports": [_exported(item) for item in self.exports],
            "early_exports": [_exported(item) for item in self.early_exports],
            "missing_required": list(self.missing_required),
            "actual_usage": dict(sorted(self.actual_usage.items())),
            "cause": self.cause,
        }
        if self.adopted:
            body["adopted"] = list(self.adopted)
        return {**body, "receipt_digest": sha256_digest(body)}


def _exported(item: ExportedOutput) -> dict[str, Any]:
    return {
        "output": item.output,
        "source": item.source,
        "timing": item.timing,
        "refs": list(item.refs),
    }


@dataclass(frozen=True)
class ChildTerminal:
    """How the child run ended, from its own family result (or its root's failure)."""

    outcome: NestedOutcome
    cause: str = ""
    # Refs the child family accepted, by body obligation source (`<node>.<output>`) when the
    # family result names them per stage; the authoritative accepted heads override these.
    family_refs: dict[str, tuple[str, ...]] = field(default_factory=dict)


def _refs(value: object) -> tuple[str, ...]:
    if isinstance(value, list | tuple):
        return tuple(str(item) for item in value)
    return ()


def child_terminal(
    family: Literal["StageGraph", "GoalDirected"],
    end: ChildEnd,
    result: Mapping[str, Any] | None,
    *,
    cause: str = "",
) -> ChildTerminal:
    """Map a child root's end to the shared Terminal Outcome (00-EXECUTION_PROGRAM_MODEL §6.3).

    A Stage Graph result names its accepted output refs per stage (``output_refs``: stage id ->
    the latest accepted instance's refs); a Goal Loop result promotes ``output_refs`` in its
    terminalization proposal (complete, or partial on ``partial_or_fail``).
    """

    if end == "cancelled":
        return ChildTerminal("cancelled", cause or "cancelled")
    if end == "timed_out":
        return ChildTerminal("governor_exhausted", cause or "timed_out")
    if end != "returned" or result is None:
        return ChildTerminal("execution_failed", cause or end)
    if family == "StageGraph":
        completion = result.get("completion_proposal") or {}
        # The family reports each stage's latest accepted instance, keyed by stage id.
        by_stage = {
            str(stage): _refs(refs) for stage, refs in (result.get("output_refs") or {}).items()
        }
        if completion.get("cancelled"):
            return ChildTerminal("cancelled", "cancelled", by_stage)
        if completion.get("failed") or not completion.get("required_obligations_accepted"):
            unmet = ",".join(str(item) for item in completion.get("unmet_reasons") or ())
            outcome: NestedOutcome = "governor_exhausted" if unmet else "not_accepted"
            return ChildTerminal(outcome, unmet or "not_accepted", by_stage)
        return ChildTerminal("accepted", "", by_stage)
    if result.get("status") == "cancelled":
        return ChildTerminal("cancelled", "cancelled")
    proposal = result.get("terminalization_proposal") or {}
    promoted = _refs(proposal.get("output_refs"))
    proposed = proposal.get("proposed_outcome")
    if proposed == "complete":
        return ChildTerminal("accepted", "", {"*": promoted})
    convergence = result.get("convergence_proposal") or {}
    reason = str(convergence.get("reason") or proposed or "not_accepted")
    outcome = (
        "governor_exhausted"
        if reason in {"iteration_limit", "hard_budget_exhausted"}
        else ("not_accepted")
    )
    return ChildTerminal(outcome, reason, {"*": promoted} if proposed == "partial_or_fail" else {})


def _family_source_refs(terminal: ChildTerminal, source: str) -> tuple[str, ...]:
    if "*" in terminal.family_refs:
        return terminal.family_refs["*"]
    return terminal.family_refs.get(source.partition(".")[0], ())


def project_exports(
    body: NestedBody,
    child_run_id: str,
    terminal: ChildTerminal,
    accepted: Mapping[str, tuple[str, ...]] | None = None,
    *,
    actual_usage: Mapping[str, int] | None = None,
) -> NestedProjection:
    """The exact export of one nested activation.

    ``accepted`` is the child run's accepted output revisions by obligation key (the body's
    accepted heads); without it (a body that promises no named outputs) the refs come from the
    child family's own accepted results. Only declared exports cross; internal outputs never do.
    The composite is accepted only when the child was accepted and every required final export
    holds accepted refs. When it is not, early exports with accepted refs are reported for
    explicit partial use and nothing becomes a parent output.
    """

    def refs(item: NestedExport) -> tuple[str, ...]:
        if accepted is not None:
            return tuple(accepted.get(item.source, ()))
        return _family_source_refs(terminal, item.source)

    exported = tuple(
        ExportedOutput(item.output, item.source, item.timing, refs(item)) for item in body.exports
    )
    missing = tuple(
        item.output
        for item, out in zip(body.exports, exported, strict=True)
        if item.required and not out.refs
    )
    accepted_composite = terminal.outcome == "accepted" and not missing
    usage = {name: amount for name, amount in (actual_usage or {}).items() if amount > 0}
    if accepted_composite:
        return NestedProjection(
            child_run_id=child_run_id,
            position=body.position,
            outcome="accepted",
            composite_accepted=True,
            exports=tuple(item for item in exported if item.refs),
            actual_usage=usage,
        )
    return NestedProjection(
        child_run_id=child_run_id,
        position=body.position,
        outcome="not_accepted" if terminal.outcome == "accepted" else terminal.outcome,
        composite_accepted=False,
        early_exports=tuple(item for item in exported if item.timing == "early" and item.refs),
        missing_required=missing if terminal.outcome == "accepted" else (),
        actual_usage=usage,
        cause=terminal.cause or ("missing_required_exports" if missing else ""),
    )


def stage_result(
    projection: NestedProjection, *, accepted_obligation_refs: tuple[str, ...] = ()
) -> tuple[Literal["completed", "failed", "cancelled"], dict[str, Any]]:
    """The observation a Stage Graph host stage reports for its nested activation.

    Accepted: the stage completes with exactly the exported refs as its outputs. Cancelled:
    the stage is cancelled. Anything else fails the stage; early exports stay in the receipt
    (lineage for explicit partial use), never in ``output_refs``.
    """

    payload: dict[str, Any] = {"nested": projection.receipt()}
    if projection.composite_accepted:
        payload["output_refs"] = list(projection.output_refs)
        if accepted_obligation_refs:
            payload["obligation_refs"] = list(accepted_obligation_refs)
        return "completed", payload
    if projection.outcome == "cancelled":
        return "cancelled", payload
    return "failed", payload


def executor_result(
    projection: NestedProjection,
) -> tuple[Literal["completed", "failed", "cancelled"], dict[str, Any]]:
    """The observation a Goal Loop executor phase reports for its nested body.

    The executor completes whenever the body ran to a governed end: accepted with exactly the
    exported refs, or not accepted (the iteration's execution result then fails, and the Goal
    Loop's convergence policy decides the next iteration, as for any failed attempt). A
    cancelled body cancels the executor; an infrastructure failure fails it.
    """

    payload: dict[str, Any] = {"nested": projection.receipt()}
    if projection.composite_accepted:
        payload["output_refs"] = list(projection.output_refs)
        return "completed", payload
    if projection.outcome == "cancelled":
        return "cancelled", payload
    if projection.outcome == "execution_failed":
        return "failed", payload
    return "completed", payload


@dataclass(frozen=True)
class NestedSettlementRequest:
    """The ``nested_program.settle`` input: how the child root ended, for the export receipt
    and the parent unit's reservation settlement (the child's actual usage, released rest)."""

    request_scope: str
    parent_run_id: str
    host_id: str
    semantic_attempt_id: str
    parent_reservation_id: str
    body: NestedBody
    child_run_id: str
    end: ChildEnd
    family_result: dict[str, Any] | None
    occurred_at: datetime
    cause: str = ""
    correlation_id: str = ""
    # False when the child run was admitted but its root never started (cancelled first): the
    # settlement then closes the admitted child run as well.
    child_started: bool = True
    # The hosting unit's invocation (the parent unit attempt adoption submits for).
    operation_id: str = ""
    operation_attempt: int = 1
    execution_generation: int = 1


@dataclass(frozen=True)
class NestedSettlement:
    projection: NestedProjection
    settled_run_version: int = 0
    reason_code: str = ""


@dataclass(frozen=True)
class NestedControlRequest:
    """Propagate one parent control to a hosted child run through its own run control."""

    request_scope: str
    parent_run_id: str
    host_id: str
    child_run_id: str
    kind: ControlKind
    command_ref: str
    reason: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        if self.kind not in PROPAGATED_CONTROLS:
            raise ValueError(f"{self.kind} is not propagated to a nested body")


@dataclass(frozen=True)
class NestedControlReceipt:
    delivered: bool
    status: str = ""
    reason_code: str = ""
