"""The lane's governed in-turn model retry: unsent transport failures only (W1 D40).

The model clients are built with `max_retries=0` (`materializer.py`): every paid attempt is
observed, and the SDK never re-sends a request that may already have been billed. That left no
retry at all inside a turn, so a connection that failed before the request reached the
provider (nothing sent, nothing billed) failed the whole unit (live: session 12, run e947fa8e).

This is the recovery ladder's L1 rung (FAULT-TOLERANCE-PROPOSAL section 6.2), built only for
the `transient_transport` fault this defect needs: the stock `ModelRetryMiddleware` (a
`wrap_model_call` middleware, so no graph node, step or checkpoint numbering moves) with

- `retry_on` = `unsent_transport_failure`: a connect, connect-timeout, pool, proxy or refused
  failure anywhere in the cause chain; never a timeout or transport failure after the request
  was sent, never an SDK error of unknown cause, never a provider answer (a 429/529 belongs to
  the durable capacity wait, L4);
- `on_failure="error"`: an exhausted retry raises, so the turn fails typed
  (`transient_transport`) instead of the error text becoming the model's answer;
- a small bound (2 retries, 1 s doubling, at most 20 s, jittered).

It sits innermost in the lane's stack, inside the fence and budget stops, so a fenced or
exhausted turn is never retried.
"""

from __future__ import annotations

import logging
from typing import Final

from langchain.agents.middleware import ModelRetryMiddleware

logger = logging.getLogger(__name__)

TRANSIENT_TRANSPORT: Final = "transient_transport"
# httpx/httpcore transport failures before the request reached the provider (nothing to bill)
# and after it was fully sent (the provider may have processed and billed it). W1 fix G S3.
UNSENT_TRANSPORT: Final = frozenset(
    {"ConnectError", "ConnectTimeout", "PoolTimeout", "ProxyError", "UnsupportedProtocol"}
)
SENT_TRANSPORT: Final = frozenset(
    {"ReadTimeout", "WriteTimeout", "ReadError", "RemoteProtocolError"}
)
MAX_CAUSES: Final = 8


def causes(error: BaseException) -> list[BaseException]:
    """`error` and its cause/context chain, bounded and cycle-safe."""

    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in chain and len(chain) < MAX_CAUSES:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def unsent_transport_failure(error: BaseException) -> bool:
    """Whether a failed model call provably never reached the provider (W1 D40).

    The first transport fact in the cause chain decides: an httpx/httpcore unsent class or a
    refused connection is unsent; a sent class is not. A builtin `ConnectionResetError` or
    `ConnectionAbortedError` may follow a sent request, so only a refusal counts. Nothing else
    is unsent, so the retry errs toward less spend.
    """

    for item in causes(error):
        root = type(item).__module__.split(".", 1)[0]
        if root in {"httpx", "httpcore"}:
            name = type(item).__name__
            if name in UNSENT_TRANSPORT:
                return True
            if name in SENT_TRANSPORT:
                return False
        elif isinstance(item, ConnectionRefusedError):
            return True
        elif isinstance(item, ConnectionError):
            return False
    return False


def _retry_on(error: Exception) -> bool:
    unsent = unsent_transport_failure(error)
    if unsent:
        # The Transcript carries no retry frame yet (FT-3); the worker log names it.
        logger.warning(
            "model call failed before reaching the provider; retrying: %s", type(error).__name__
        )
    return unsent


class GovernedModelRetryMiddleware(ModelRetryMiddleware):
    """L1: retry a model call only when it failed before reaching the provider."""

    def __init__(
        self,
        *,
        max_retries: int = 2,
        initial_delay: float = 1.0,
        max_delay: float = 20.0,
    ) -> None:
        super().__init__(
            max_retries=max_retries,
            retry_on=_retry_on,
            on_failure="error",
            backoff_factor=2.0,
            initial_delay=initial_delay,
            max_delay=max_delay,
            jitter=True,
        )

    @property
    def name(self) -> str:
        return "BellLabsUnsentTransportRetry"


__all__ = [
    "SENT_TRANSPORT",
    "TRANSIENT_TRANSPORT",
    "UNSENT_TRANSPORT",
    "GovernedModelRetryMiddleware",
    "causes",
    "unsent_transport_failure",
]
