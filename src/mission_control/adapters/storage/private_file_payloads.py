"""Read only explicitly pinned owner-private POSIX files; no path from a request.

This operator-composition adapter can read retained R1 custody on its original
Linux host. It neither registers an artifact nor copies/stages/changes any file.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadAddress
from mission_control.application.recovery.terminal_lane_adoption import AdoptionInspectionRefused

MAX_PRIVATE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class PinnedPrivateFile:
    address: ArtifactPayloadAddress
    path: Path
    private_root: Path
    owner_uid: int


def need(value: object, reason: str) -> None:
    if not value:
        raise AdoptionInspectionRefused(reason)


def _posix_capability(name: str) -> Any:
    """Require the host capability; never substitute weaker Windows flags."""
    need(os.name == "posix", "private custody requires its original POSIX host")
    return getattr(os, name)


class PrivateFilePayloadReader:
    def __init__(self, approved: Mapping[str, PinnedPrivateFile]) -> None:
        need(os.name == "posix", "private custody requires its original POSIX host")
        self._approved = dict(approved)
        for reference, pin in self._approved.items():
            need(reference == pin.address.object_ref, "private reference mapping differs")
            need(
                pin.path.is_absolute()
                and pin.private_root.is_absolute()
                and ".." not in pin.path.parts
                and ".." not in pin.private_root.parts
                and pin.private_root in pin.path.parents
                and pin.owner_uid == _posix_capability("getuid")()
                and 0 < pin.address.size_bytes <= MAX_PRIVATE_BYTES,
                "private file pin is outside approved host bounds",
            )

    async def retrieve(self, address: ArtifactPayloadAddress) -> bytes:
        pin = self._approved.get(address.object_ref)
        need(pin is not None and pin.address == address, "private payload address is not approved")
        assert pin is not None
        # A cancelled caller can leave a bounded read finishing, never a mutation.
        return await asyncio.to_thread(self._read, pin)

    @staticmethod
    def _read(pin: PinnedPrivateFile) -> bytes:
        deadline = time.monotonic() + 2
        # These capabilities are mandatory on the original POSIX host. getattr
        # keeps this intentionally POSIX-only adapter importable/type-checkable
        # on Windows; missing capabilities raise rather than weakening flags.
        directory_flags = (
            os.O_RDONLY | _posix_capability("O_DIRECTORY") | _posix_capability("O_NOFOLLOW")
        )
        directory = os.open(pin.path.anchor, directory_flags)
        descriptor: int | None = None
        try:
            traversed = Path(pin.path.anchor)
            for component in pin.path.parent.parts[1:]:
                need(time.monotonic() < deadline, "private read deadline")
                following = os.open(component, directory_flags, dir_fd=directory)
                os.close(directory)
                directory = following
                traversed /= component
                metadata = os.fstat(directory)
                if traversed == pin.private_root or pin.private_root in traversed.parents:
                    need(
                        metadata.st_uid == pin.owner_uid
                        and stat.S_IMODE(metadata.st_mode) == 0o700,
                        "private directory owner or mode differs",
                    )
                else:
                    # Sticky /tmp can contain an exclusively owned0700 fixture root.
                    need(
                        not metadata.st_mode & 0o022 or metadata.st_mode & stat.S_ISVTX,
                        "writable non-sticky custody ancestor",
                    )
            descriptor = os.open(
                pin.path.name,
                os.O_RDONLY | _posix_capability("O_NOFOLLOW") | _posix_capability("O_NONBLOCK"),
                dir_fd=directory,
            )
            before = os.fstat(descriptor)
            need(
                stat.S_ISREG(before.st_mode)
                and before.st_uid == pin.owner_uid
                and before.st_nlink == 1
                and stat.S_IMODE(before.st_mode) == 0o400
                and before.st_size == pin.address.size_bytes,
                "private file identity, mode or size differs",
            )
            chunks: list[bytes] = []
            size = 0
            while True:
                need(time.monotonic() < deadline, "private read deadline")
                part = os.read(descriptor, min(65536, pin.address.size_bytes + 1 - size))
                if not part:
                    break
                chunks.append(part)
                size += len(part)
                need(size <= pin.address.size_bytes, "private read exceeds pinned size")
            after = os.fstat(descriptor)
            current = os.stat(pin.path.name, dir_fd=directory, follow_symlinks=False)
            need(
                (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                )
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                and (current.st_dev, current.st_ino) == (after.st_dev, after.st_ino)
                and after.st_nlink == 1,
                "private file changed during read",
            )
            content = b"".join(chunks)
            need(
                len(content) == pin.address.size_bytes
                and "sha256:" + hashlib.sha256(content).hexdigest() == pin.address.content_digest,
                "private file digest differs",
            )
            return content
        except OSError:
            raise AdoptionInspectionRefused("private file custody could not be verified") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory)
