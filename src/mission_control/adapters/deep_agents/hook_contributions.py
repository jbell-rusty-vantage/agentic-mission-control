"""Hook context contributions on the Deep Agents lane (Sprint OC WI-17; ADR-0062).

:class:`DeepAgentCandidateWorkspace` is the receiver's actual backend as the host reads and
installs through it: a sandbox's upload/download, or the ``files`` channel of the text-only
``StateBackend`` (written through LangGraph's send, read back fresh; durable only once the step
commits, so its installs are confirmed at the next boundary). :class:`FenceGrantCheck` refuses
every contribution of a stop-fenced run. The attempt's sealed transfer plan is remembered per
backend when :func:`~mission_control.adapters.deep_agents.transfer.materialize_transfer`
delivers it, so ``transfer_input`` reads verify against the plan's exact digests.
"""

from __future__ import annotations

import logging
import weakref
from collections.abc import Awaitable, Callable

from deepagents.backends.protocol import BackendProtocol
from deepagents.backends.state import StateBackend
from langgraph.config import get_stream_writer

from mission_control.application.context.hook_contributions import CurrentGrantPort
from mission_control.domain.context.contributions import CandidateOrigin, ContributionRefusal
from mission_control.domain.context.transfer import SealedTransferPlan

_LOG = logging.getLogger(__name__)
PLAN_UNATTACHED_EVENT = "mc.hook_transfer_plan_unattached"

# Sealed plans delivered to a live backend, keyed by the backend's *identity* (never by value
# equality, so two equal-valued backends never share a plan). Each entry holds a weak reference
# to its backend: a lookup answers only for that very object, and the entry is dropped when the
# backend is collected (`weakref.finalize`) or when the attempt's stack closes. A backend that
# cannot be weakly referenced gets no plan; that is logged and emitted, and its transfer reads
# refuse READ_UNAVAILABLE.
_PLANS: dict[int, tuple[weakref.ref[BackendProtocol], SealedTransferPlan]] = {}


def remember_transfer_plan(backend: BackendProtocol, plan: SealedTransferPlan) -> bool:
    """Attach ``plan`` to ``backend``; ``False`` (logged and emitted) when it cannot be."""

    key = id(backend)
    try:
        reference = weakref.ref(backend)
        weakref.finalize(backend, _PLANS.pop, key, None)
    except TypeError:
        _LOG.warning(
            "transfer plan %s not attached to backend %s: it cannot be weakly referenced; "
            "hook transfer_input reads refuse READ_UNAVAILABLE",
            plan.plan_id,
            type(backend).__name__,
        )
        _emit_unattached(plan, backend)
        return False
    _PLANS[key] = (reference, plan)
    return True


def _emit_unattached(plan: SealedTransferPlan, backend: BackendProtocol) -> None:
    try:
        writer = get_stream_writer()
    except (RuntimeError, LookupError):
        return
    writer(
        {
            "type": PLAN_UNATTACHED_EVENT,
            "id": f"hook-plan-unattached:{plan.plan_id}",
            "plan_id": plan.plan_id,
            "backend": type(backend).__name__,
            "code": "TRANSFER_PLAN_UNATTACHED",
        }
    )


def forget_transfer_plan(backend: BackendProtocol) -> None:
    entry = _PLANS.get(id(backend))
    if entry is not None and entry[0]() is backend:
        _PLANS.pop(id(backend), None)


def transfer_plan_for(backend: BackendProtocol) -> SealedTransferPlan | None:
    entry = _PLANS.get(id(backend))
    if entry is None or entry[0]() is not backend:
        return None
    return entry[1]


class DeepAgentCandidateWorkspace:
    """What the agent's own file tools read is what the host reads and installs."""

    def __init__(self, backend: BackendProtocol) -> None:
        self.backend = backend

    @property
    def realized_backend(self) -> str:
        if isinstance(self.backend, StateBackend):
            return "deep_agents:state"
        return f"deep_agents:{type(self.backend).__name__}"

    @property
    def read_probe(self) -> str:
        return "state_files_read" if isinstance(self.backend, StateBackend) else "backend_read"

    @property
    def durable_on_write(self) -> bool:
        return not isinstance(self.backend, StateBackend)

    async def read(self, path: str) -> bytes | None:
        responses = await self.backend.adownload_files([path])
        if not responses or responses[0].error or responses[0].content is None:
            return None
        return responses[0].content

    async def write(self, path: str, content: bytes) -> None:
        responses = await self.backend.aupload_files([(path, content)])
        if not responses or any(item.error for item in responses):
            raise OSError(f"the backend refused the candidate at {path}")


class FenceGrantCheck(CurrentGrantPort):
    """Current authority at install time: a stop-fenced run contributes nothing more."""

    def __init__(self, fenced: Callable[[], Awaitable[str | None]]) -> None:
        self._fenced = fenced

    async def check(self, origin: CandidateOrigin) -> ContributionRefusal | None:
        reason = await self._fenced()
        if reason is None:
            return None
        return ContributionRefusal(
            code="GENERATION_FENCED",
            hook_id=origin.hook_id,
            message="the run is stop-fenced; no contribution is installed",
        )


__all__ = [
    "PLAN_UNATTACHED_EVENT",
    "DeepAgentCandidateWorkspace",
    "FenceGrantCheck",
    "forget_transfer_plan",
    "remember_transfer_plan",
    "transfer_plan_for",
]
