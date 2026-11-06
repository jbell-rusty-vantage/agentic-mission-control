"""Actual POSIX file integrity/privacy and origin refusal; no network or database."""

import asyncio
import hashlib
import os
from dataclasses import replace
from pathlib import Path

import pytest

from mission_control.adapters.storage.private_file_payloads import (
    PinnedPrivateFile,
    PrivateFilePayloadReader,
)
from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadAddress
from mission_control.application.recovery.terminal_lane_adoption import AdoptionInspectionRefused

pytestmark = pytest.mark.skipif(os.name != "posix", reason="actual owner/mode/NOFOLLOW POSIX proof")


def pinned(tmp_path: Path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    path = private / "result.utf8"
    content = b"synthetic retained bytes"
    path.write_bytes(content)
    path.chmod(0o400)
    address = ArtifactPayloadAddress(
        object_ref="private-local:approved-result",
        content_digest="sha256:" + hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
    )
    pin = PinnedPrivateFile(address, path, private, os.getuid())
    return pin, content


def read(reader, address):
    return asyncio.run(reader.retrieve(address))


def test_actual_private_bytes_read_exactly_without_mutation(tmp_path):
    pin, content = pinned(tmp_path)
    before = pin.path.stat()
    reader = PrivateFilePayloadReader({pin.address.object_ref: pin})
    assert read(reader, pin.address) == content
    assert read(reader, pin.address) == content
    after = pin.path.stat()
    assert (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )


@pytest.mark.parametrize("mutation", ["digest", "size", "reference"])
def test_caller_cannot_change_approved_address(tmp_path, mutation):
    pin, _ = pinned(tmp_path)
    changed = {
        "digest": {"content_digest": "sha256:" + "a" * 64},
        "size": {"size_bytes": pin.address.size_bytes + 1},
        "reference": {"object_ref": "private-local:unapproved"},
    }
    with pytest.raises(AdoptionInspectionRefused, match="not approved"):
        read(
            PrivateFilePayloadReader({pin.address.object_ref: pin}),
            pin.address.model_copy(update=changed[mutation]),
        )


@pytest.mark.parametrize("mutation", ["mode", "directory_mode", "hardlink", "symlink", "bytes"])
def test_changed_private_custody_refuses(tmp_path, mutation):
    pin, content = pinned(tmp_path)
    if mutation == "mode":
        pin.path.chmod(0o600)
    elif mutation == "directory_mode":
        pin.private_root.chmod(0o755)
    elif mutation == "hardlink":
        os.link(pin.path, pin.path.with_name("second-link"))
    elif mutation == "symlink":
        pin.path.rename(pin.path.with_name("original"))
        pin.path.symlink_to(pin.path.with_name("original"))
    else:
        pin.path.chmod(0o600)
        pin.path.write_bytes(b"x" * len(content))
        pin.path.chmod(0o400)
    with pytest.raises(AdoptionInspectionRefused):
        read(PrivateFilePayloadReader({pin.address.object_ref: pin}), pin.address)


def test_symlink_parent_refuses_even_when_target_is_private(tmp_path):
    pin, _ = pinned(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(pin.private_root, target_is_directory=True)
    pin = replace(pin, path=alias / pin.path.name, private_root=alias)
    with pytest.raises(AdoptionInspectionRefused):
        read(PrivateFilePayloadReader({pin.address.object_ref: pin}), pin.address)
