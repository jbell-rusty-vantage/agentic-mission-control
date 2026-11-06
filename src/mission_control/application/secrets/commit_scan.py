"""Pre-commit scan of Mission Control's own commits onto mission branches (SPEC-01 section 4).

Before Mission Control commits files to a mission branch (the projection, the Context Packet,
continuation files and every other mission-layer file), the commit's paths, contents and message
are scanned for any value the broker resolved for the run and for any minted token. A match
refuses the commit; the error names the path, never the value. Values shorter than
`MIN_SECRET_CHARS` are not matched (they would refuse ordinary text).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

from mission_control.application.secrets.minting import TOKEN_PATTERN
from mission_control.application.secrets.redaction import MIN_SECRET_CHARS

COMMIT_MESSAGE: Final = "<commit message>"
COMMIT_PATH: Final = "<a file path>"
_TOKEN_BYTES: Final = re.compile(TOKEN_PATTERN.pattern.encode("ascii"))


class SecretInCommit(ValueError):
    """A commit would carry a secret value; nothing was committed."""

    def __init__(self, location: str) -> None:
        super().__init__(f"refused to commit a secret value in {location}")
        self.location = location


def scan_commit(
    files: Iterable[tuple[str, bytes]],
    *,
    message: str = "",
    secret_values: Iterable[str] = (),
) -> None:
    """Raise `SecretInCommit` for the first path, content or message carrying a value."""

    needles = tuple(
        {value.encode("utf-8") for value in secret_values if len(value) >= MIN_SECRET_CHARS}
    )

    def carries(content: bytes) -> bool:
        return any(needle in content for needle in needles) or bool(_TOKEN_BYTES.search(content))

    if carries(message.encode("utf-8")):
        raise SecretInCommit(COMMIT_MESSAGE)
    for path, content in files:
        if carries(path.encode("utf-8")):
            raise SecretInCommit(COMMIT_PATH)
        if carries(content):
            raise SecretInCommit(path)


__all__ = ["SecretInCommit", "scan_commit"]
