"""MO-11: exact-match redaction of broker-resolved values in logs, receipts and frames, and the
pre-commit scan of Mission Control's commits to mission branches."""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from mission_control.adapters.cursor.scm import GitBranchPublisher
from mission_control.adapters.cursor.workspace import git
from mission_control.application.secrets.commit_scan import (
    COMMIT_MESSAGE,
    COMMIT_PATH,
    SecretInCommit,
    scan_commit,
)
from mission_control.application.secrets.redaction import (
    SecretValueRegistry,
    install_log_redaction,
    redact_receipt,
)
from mission_control.domain.frames.body import REDACTED, frame_body
from tests.fixtures.cursor_cloud import make_remote

SECRET = "mo11-redaction-sentinel-4c1e"
LONGER = SECRET + "-and-more"
TOKEN = "mct_" + "A1b2C3d4" * 5 + "xyz"


@pytest.fixture
def registry() -> Iterator[SecretValueRegistry]:
    registry = SecretValueRegistry()
    registry.add((SECRET, LONGER, "short"))
    factory = logging.getLogRecordFactory()
    try:
        yield registry
    finally:
        logging.setLogRecordFactory(factory)


def test_the_registry_replaces_values_longest_first_and_skips_short_ones(
    registry: SecretValueRegistry,
) -> None:
    text = f"a={SECRET} b={LONGER} c=short d={TOKEN}"
    assert registry.redact(text) == f"a={REDACTED} b={REDACTED} c=short d={REDACTED}"
    assert SECRET not in repr(registry)


def test_every_log_record_is_redacted_whatever_its_logger_or_handler(
    registry: SecretValueRegistry,
) -> None:
    other = SecretValueRegistry()
    other.add(("another-composition-value",))
    install_log_redaction(registry)
    factory = logging.getLogRecordFactory()
    install_log_redaction(registry)
    install_log_redaction(other)
    assert logging.getLogRecordFactory() is factory, "one factory serves every registry"
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("mission_control.tests.mo11")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info("resolved %s for %s", SECRET, "FIRECRAWL_API_KEY")
        logger.info("and %s", "another-composition-value")
        logger.warning(f"inline {LONGER} and token {TOKEN}")  # noqa: G004 - values in the message
        try:
            raise RuntimeError(f"provider echoed {SECRET}")
        except RuntimeError:
            logger.exception("delivery failed")
    finally:
        logger.removeHandler(handler)
    written = stream.getvalue()
    assert "resolved [REDACTED] for FIRECRAWL_API_KEY" in written
    assert "RuntimeError: provider echoed [REDACTED]" in written
    assert SECRET not in written and TOKEN not in written
    assert "another-composition-value" not in written


def test_receipts_and_frames_redact_registered_values(registry: SecretValueRegistry) -> None:
    receipt = {"secrets": ["FIRECRAWL_API_KEY"], "probe": {"stdout": f"key={SECRET}"}}
    assert redact_receipt(receipt, registry) == {
        "secrets": ["FIRECRAWL_API_KEY"],
        "probe": {"stdout": f"key={REDACTED}"},
    }
    body = frame_body({"text": f"echo {SECRET} {TOKEN}"}, secret_values=registry.values())
    assert SECRET not in body.excerpt and TOKEN not in body.excerpt
    assert {item.pattern for item in body.redactions} == {"configured_secret", "minted_token"}


def test_the_commit_scan_refuses_contents_paths_messages_and_minted_tokens() -> None:
    clean = [("README.md", b"mission notes"), (".mission/setup/run", b"#!/bin/sh\n")]
    scan_commit(clean, message="mission control: setup", secret_values=(SECRET, "short"))

    cases = [
        ([("notes.md", f"key={SECRET}".encode())], "", "notes.md"),
        ([(f"leak-{SECRET}.txt", b"x")], "", COMMIT_PATH),
        (clean, f"commit {SECRET}", COMMIT_MESSAGE),
        ([("config.json", TOKEN.encode())], "", "config.json"),
    ]
    for files, message, location in cases:
        with pytest.raises(SecretInCommit) as refused:
            scan_commit(files, message=message, secret_values=(SECRET,))
        assert refused.value.location == location
        assert SECRET not in str(refused.value) and TOKEN not in str(refused.value)


async def test_a_mission_branch_commit_carrying_a_secret_is_never_pushed(tmp_path: Path) -> None:
    remote = make_remote(tmp_path)
    publisher = GitBranchPublisher(tmp_path / "mirrors")
    with pytest.raises(SecretInCommit, match="context.md"):
        await publisher.publish(
            repository=str(remote),
            base_ref="main",
            branch="mc/run-leak",
            files=[(".mission/context.md", f"token {SECRET}".encode())],
            secret_values=(SECRET,),
        )
    assert git("ls-remote", "--heads", str(remote), "mc/run-leak", cwd=tmp_path).strip() == ""

    published = await publisher.publish(
        repository=str(remote),
        base_ref="main",
        branch="mc/run-clean",
        files=[(".mission/context.md", b"clean context")],
        secret_values=(SECRET,),
    )
    with pytest.raises(SecretInCommit, match="continuation.md"):
        await publisher.commit_files(
            repository=str(remote),
            branch="mc/run-clean",
            files=[("continuation.md", SECRET.encode())],
            message="mission control: continuation t-1",
            secret_values=(SECRET,),
        )
    head = git("ls-remote", "--heads", str(remote), "mc/run-clean", cwd=tmp_path).split()[0]
    assert head == published.head
