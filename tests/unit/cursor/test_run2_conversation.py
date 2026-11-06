import json

from mission_control.adapters.cursor.conversation import MAX_EXCERPT_BYTES, conversation_export
from mission_control.adapters.cursor.snapshot import bytes_digest


def test_export_is_bounded_scrubbed_and_attributed():
    raw = conversation_export(
        [{"text": "private-key " + "x" * 50000}],
        session_ref="a",
        run_ref="r",
        source="sdk",
        secrets=("private-key",),
    )
    body = json.loads(raw)
    assert body["disposition"] == "exported" and body["truncated"]
    assert "private-key" not in body["excerpt"]
    assert len(body["excerpt"].encode()) <= MAX_EXCERPT_BYTES
    assert body["excerpt_digest"] == bytes_digest(body["excerpt"].encode())
    assert body["session_ref"] == "a" and body["run_ref"] == "r"


def test_absent_export_explicitly_reports_missing():
    body = json.loads(conversation_export(None, session_ref="a", run_ref=None, source="sdk"))
    assert body["disposition"] == "missing" and body["excerpt"] == ""
