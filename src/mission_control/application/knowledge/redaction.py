"""Redaction of text that crosses to a model, a log or an inspection surface (W1 D11/D20).

Credential-shaped strings (DSNs, bearer tokens, provider keys, ``key=value`` secrets) and absolute
local paths are replaced by ``<redacted>``; the text is then cut to a limit. One helper for the
toolset's refusal documents and the trusted path's surfaced KS issues.
"""

from __future__ import annotations

import re
from typing import Final

_SECRET_PATTERNS: Final = (
    # Any DSN or URL with userinfo (scheme://user:pass@host), and Postgres DSNs whole.
    re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@\S+", re.IGNORECASE),
    re.compile(r"postgres(?:ql)?://\S+", re.IGNORECASE),
    re.compile(r"bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bsb_(?:secret|publishable)_[A-Za-z0-9_-]{8,}"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    # key=value and key: "value" secrets (password, secret, token, api key, credential ...);
    # an unquoted `key: text` stays, so a field-path issue (`limits.tokens: Expected ...`) reads.
    re.compile(
        r"\b[a-z0-9_]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|credential"
        r"|private[_-]?key)[a-z0-9_]*\s*(?:=\s*[\"']?|:\s*[\"'])[^\s\"',;]+",
        re.IGNORECASE,
    ),
    # Absolute local file paths: a Windows drive or UNC root, and POSIX home or system roots.
    re.compile(r"(?:\b[A-Za-z]:[\\/]|\\\\)[^\s\"'<>|]+"),
    re.compile(r"(?<![\w:/])/(?:home|Users|root|etc|var|tmp|opt|srv|mnt)/[^\s\"'<>]+"),
)


def redacted(text: str, limit: int) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("<redacted>", text)
    return text[:limit]


__all__ = ["redacted"]
