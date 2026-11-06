"""MO-11 acceptance: a sentinel secret appears in no commit, frame, log or binding.

A sentinel value lives only in the owner's secret-store file. One `cursor_cloud` turn (FIXTURE
Cloud Agents API, a real local git remote) resolves it through the Secret Broker as the
binding's launch `envVars`, and the fake agent echoes it in its own output. Afterwards every
output is grepped: the run branch's commits, the persisted frames and the transcript rendered
from them, every log record the run produced, a receipt, and the bindings. The only place the
value may appear is the create request's `envVars`, the channel that asked for it.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterable, Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from mission_control.adapters.cursor import scm
from mission_control.adapters.cursor.workspace import git
from mission_control.adapters.operations.runtime_ports import SecretEnvVarsResolver
from mission_control.adapters.remote_session.sse import SseEvent
from mission_control.adapters.secrets.sources import SecretStoreFile, WorkerEnvironmentSource
from mission_control.application.frames.transcript import merge
from mission_control.application.secrets.broker import SecretBroker
from mission_control.application.secrets.redaction import install_log_redaction, redact_receipt
from mission_control.application.secrets.references import SecretDeclaration
from mission_control.domain.execution.bindings import EnvironmentBinding
from mission_control.domain.frames.render import to_jsonl
from tests.fixtures.cursor_cloud import cloud_stack
from tests.fixtures.lane_turns import lane_stack
from tests.unit.cursor.support import frames_of, signals, turn

SENTINEL = "mo11-sentinel-9d2f7a41c3"
PROFILE = "cursor_cloud"


@pytest.fixture
def captured_logs() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    level, factory = root.level, logging.getLogRecordFactory()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield stream
    finally:
        root.removeHandler(handler)
        root.setLevel(level)
        logging.setLogRecordFactory(factory)


def _echoing(events: Iterable[SseEvent]) -> list[SseEvent]:
    """The fixture stream with the agent echoing the variable it was given."""

    return [
        replace(event, data=json.dumps({"text": f"MC_SENTINEL is {SENTINEL}; continuing"}))
        if event.event == "assistant"
        else event
        for event in events
    ]


async def test_a_sentinel_secret_appears_in_no_commit_frame_log_or_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured_logs: io.StringIO
) -> None:
    store = tmp_path / "owner" / "secret-store.json"
    store.parent.mkdir()
    store.write_text(json.dumps({"MC_SENTINEL": SENTINEL}), encoding="utf-8")
    broker = SecretBroker(environment=WorkerEnvironmentSource({}), store=SecretStoreFile(store))
    install_log_redaction(broker.registry)
    scanned: list[tuple[str, ...]] = []
    original_scan = scm.scan_commit

    def recording_scan(
        files: Iterable[tuple[str, bytes]], *, message: str = "", secret_values: Iterable[str] = ()
    ) -> None:
        scanned.append(tuple(secret_values))
        original_scan(files, message=message, secret_values=secret_values)

    monkeypatch.setattr(scm, "scan_commit", recording_scan)

    stack = cloud_stack(
        tmp_path,
        cloud_changes={"env_vars_ref": "vault:MC_SENTINEL", "client_agent_id": False},
        env_resolver=SecretEnvVarsResolver(broker),
    )
    stack.api.events = _echoing(stack.api.events)
    lanes = lane_stack(stack.harness, operation=stack.operation, redaction=broker.registry)
    result = await lanes.service.turn(turn(stack, PROFILE), signals(lanes, stack, PROFILE))
    await stack.client.aclose()
    assert result.done
    logging.getLogger("mission_control.mo11").warning("delivered %s to the agent", SENTINEL)

    # The one channel that asked for it: the keyed create's launch envVars.
    (create,) = stack.api.creates
    assert create["envVars"] == {"MC_SENTINEL": SENTINEL}

    # Commits: Mission Control's commit was scanned against the value, and no commit on the
    # remote (Mission Control's or the agent's branch) carries it.
    # Each scan holds the values resolved for this run (its envVars), not the process's.
    assert scanned and all(values == (SENTINEL,) for values in scanned)
    history = git("log", "--all", "-p", "--format=%H %s%n%b", cwd=stack.remote)
    assert "mc/" in git("branch", "--list", "mc/*", cwd=stack.remote)
    assert SENTINEL not in history

    # Frames, and the transcript rendered from them in a process that holds no secret.
    frames = frames_of(lanes, stack, PROFILE)
    echoed = [frame for frame in frames if frame.raw_kind == "assistant"]
    assert echoed and all(
        any(item.pattern == "configured_secret" for item in frame.redactions) for frame in echoed
    )
    assert all(SENTINEL not in frame.model_dump_json() for frame in frames)
    transcript = to_jsonl(item.entry for item in merge("run", (), frames))
    assert "[REDACTED]" in transcript and SENTINEL not in transcript

    # Logs: every record this process created during the run.
    assert "delivered [REDACTED] to the agent" in captured_logs.getvalue()
    assert SENTINEL not in captured_logs.getvalue()

    # Receipts and bindings carry names only.
    receipt = redact_receipt(
        {"probe": f"MC_SENTINEL={SENTINEL}", "names": ["MC_SENTINEL"]}, broker.registry
    )
    assert SENTINEL not in json.dumps(receipt)
    declaration = SecretDeclaration.parse("MC_SENTINEL=secret:MC_SENTINEL")
    environment = EnvironmentBinding(
        kind="local_workspace", host_profile="worker", secret_refs=(declaration.binding_entry,)
    )
    for binding in (stack.operation, environment, result):
        assert SENTINEL not in binding.model_dump_json()
