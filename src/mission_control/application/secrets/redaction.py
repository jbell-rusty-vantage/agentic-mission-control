"""Exact-match redaction of broker-resolved values (SPEC-01 section 4; ADR-0043).

Every value the Secret Broker resolves or mints in this process joins one `SecretValueRegistry`.
Three consumers read it:

* frames: `LaneTurnService` adds the registry's values to each `FrameWriter`, so a delivered
  value is redacted before a frame is digested, excerpted or stored (transcripts render from
  those frames);
* logs: `install_log_redaction` wraps the logging record factory, so a record from any logger,
  through any handler, has the values replaced in its message, arguments and traceback;
* receipts: `redact_receipt` replaces them in a JSON-like receipt; a receipt writer applies it
  before persisting (no persisted receipt exists yet: the Materialization Receipt is unbuilt).

Matching is exact (no shape guessing), longest value first, for values of at least
`MIN_SECRET_CHARS` characters (shorter ones would mangle ordinary text). The existing
pattern-based redaction still applies on top, and minted tokens are also redacted by their
`mct_` prefix.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Iterable
from typing import Any, Final

from mission_control.application.secrets.minting import TOKEN_PATTERN
from mission_control.domain.frames.body import REDACTED, redact_value

MIN_SECRET_CHARS: Final = 6


class SecretValueRegistry:
    """The values resolved or minted in this process (thread-safe; values are never listed
    anywhere but to the redactors)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: frozenset[str] = frozenset()
        self._pattern: re.Pattern[str] | None = None

    def add(self, values: Iterable[str]) -> None:
        fresh = {value for value in values if len(value) >= MIN_SECRET_CHARS}
        with self._lock:
            if fresh <= self._values:
                return
            self._values = self._values | fresh
            ordered = sorted(self._values, key=len, reverse=True)
            self._pattern = re.compile("|".join(re.escape(value) for value in ordered))

    def values(self) -> tuple[str, ...]:
        return tuple(self._values)

    def redact(self, text: str) -> str:
        pattern = self._pattern
        if pattern is not None:
            text = pattern.sub(REDACTED, text)
        return TOKEN_PATTERN.sub(REDACTED, text)

    def __repr__(self) -> str:
        return f"SecretValueRegistry({len(self._values)} values)"


def redact_receipt(receipt: Any, registry: SecretValueRegistry) -> Any:
    """A JSON-like receipt with every registered value replaced (the frame redactor, so the
    credential patterns and minted tokens are replaced too)."""

    return redact_value(receipt, registry.values())[0]


def install_log_redaction(registry: SecretValueRegistry) -> None:
    """Redact `registry`'s values from every log record this process creates. One factory
    wraps the previous record factory and serves every registry installed (idempotent)."""

    current = logging.getLogRecordFactory()
    if isinstance(current, _RedactingRecordFactory):
        if not any(item is registry for item in current.registries):
            current.registries.append(registry)
        return
    logging.setLogRecordFactory(_RedactingRecordFactory(current, [registry]))


class _RedactingRecordFactory:
    def __init__(
        self, base: Callable[..., logging.LogRecord], registries: list[SecretValueRegistry]
    ) -> None:
        self.base = base
        self.registries = registries

    def _redact(self, text: str) -> str:
        for registry in self.registries:
            text = registry.redact(text)
        return text

    def __call__(self, *args: Any, **kwargs: Any) -> logging.LogRecord:
        record = self.base(*args, **kwargs)
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            message = str(record.msg)
        record.msg, record.args = self._redact(message), ()
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = self._redact(logging.Formatter().formatException(record.exc_info))
        if record.stack_info:
            record.stack_info = self._redact(record.stack_info)
        return record


__all__ = [
    "MIN_SECRET_CHARS",
    "SecretValueRegistry",
    "install_log_redaction",
    "redact_receipt",
]
