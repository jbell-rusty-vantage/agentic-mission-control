"""Offline evidence pagination, missing-body and credential handling regressions."""

import hashlib
import importlib.util
import json
from pathlib import Path

import httpx

SPEC = importlib.util.spec_from_file_location(
    "overnight_evidence", Path(__file__).resolve().parents[2] / "scripts/overnight_evidence.py"
)
assert SPEC and SPEC.loader
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def transcript_entry(**updates):
    row = {
        "cursor": "tc1:000000000001:00000000000000000:000000000000:00000000",
        "run_id": "run",
        "at": "2026-10-29T00:00:00Z",
        "source": "provider_frame",
        "kind": "tool_result",
        "title": "capture",
        "role": "tool",
        "canonical": False,
        "body_excerpt": "short",
        "body": {"state": "inline"},
    }
    row.update(updates)
    return row


def test_export_follows_cursor_and_fetches_granted_body(tmp_path):
    calls = []

    def handle(request):
        calls.append(str(request.url))
        path = request.url.path
        if "/artifacts/" in path:
            return httpx.Response(200, content=b'{"answer":"full", "api_key":"hidden"}')
        if path.endswith("/transcript"):
            if request.url.params.get("since"):
                return httpx.Response(200, json={"entries": [], "has_more": False})
            return httpx.Response(
                200,
                json={
                    "entries": [
                        transcript_entry(
                            body={"state": "artifact", "artifact_ref": "artifact://body"},
                            usage={
                                "dimensions": {
                                    "input_tokens": {"value": 12, "disposition": "settled"}
                                }
                            },
                        )
                    ],
                    "has_more": True,
                },
                headers={"X-Transcript-Next-Cursor": "second"},
            )
        return httpx.Response(200, json={})

    client = httpx.Client(
        base_url="http://local/v1/applications/test", transport=httpx.MockTransport(handle)
    )
    gaps = exporter.export_run(client, "run", tmp_path)
    assert any("since=second" in call for call in calls)
    text = (tmp_path / "04-bodies/000000.txt").read_text()
    assert "full" in text and "hidden" not in text
    assert any("redaction" in gap for gap in gaps)
    lines = (tmp_path / "04-workflow-transcript.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["usage"]["dimensions"]["input_tokens"]["value"] == 12
    assert "missing" in (tmp_path / "03-materialized/INDEX.md").read_text()


def test_repeated_cursor_and_unavailable_body_are_explicit(tmp_path):
    def handle(request):
        if request.url.path.endswith("/transcript"):
            return httpx.Response(
                200,
                json={
                    "entries": [transcript_entry(body={"state": "expired"})],
                    "next_cursor": "same",
                    "has_more": True,
                },
            )
        return httpx.Response(503, json={"detail": "unavailable"})

    client = httpx.Client(base_url="http://local", transport=httpx.MockTransport(handle))
    gaps = exporter.export_run(client, "run", tmp_path)
    assert any("repeated cursor" in gap for gap in gaps)
    assert any("missing/truncated" in gap for gap in gaps)
    assert any("HTTP 503" in gap for gap in gaps)


def test_fixture_observations_preserve_output_digest_and_reject_wrong_bytes(tmp_path):
    client = httpx.Client(
        base_url="http://local",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    text = "exact report\r\n"
    digest = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    gaps = exporter.export_run(
        client,
        "run",
        tmp_path,
        observed_config={
            "model": "scripted",
            "input_tokens": 3,
            "token_budget": 10,
            "api_key": "secret",
        },
        materializations=[{"source": "actual-binding", "skill_digest": "sha256:observed"}],
        output_bodies=[
            {"content": text, "digest": digest, "revision_id": "one"},
            {"content": "wrong", "digest": digest, "revision_id": "two"},
        ],
    )
    assert (tmp_path / "05-outputs/body-0000.txt").read_bytes() == text.encode()
    assert not (tmp_path / "05-outputs/body-0001.txt").exists()
    assert any("digest mismatch" in gap for gap in gaps)
    config = json.loads((tmp_path / "02-effective-run-config.json").read_text())
    assert config["snapshot"]["api_key"] == "<redacted>"
    assert config["snapshot"]["input_tokens"] == 3
    assert config["snapshot"]["token_budget"] == 10
    assert "body-0000.txt" in (tmp_path / "05-outputs/INDEX.md").read_text()


def test_credentials_are_redacted_without_removing_metrics():
    result = exporter.redact(
        {
            "apiKey": "private",
            "database_url": "postgresql://operator:private@localhost/db",
            "token_budget": 20,
            "input_tokens": 12,
            "max_output_tokens": 2,
        }
    )
    assert result["apiKey"] == "<redacted>"
    assert "private" not in result["database_url"]
    assert result["token_budget"] == 20
    assert result["input_tokens"] == 12


def test_tail_cursor_is_resume_watermark_and_raw_frame_recovers_excerpt(tmp_path):
    calls = []
    full = "complete original frame"
    digest = "sha256:" + hashlib.sha256(full.encode()).hexdigest()

    def handle(request):
        if request.url.path.endswith("/transcript"):
            calls.append(request)
            return httpx.Response(
                200,
                json={
                    "entries": [
                        transcript_entry(
                            refs={"frame_id": "frame-one"},
                            body={"state": "excerpt"},
                            body_excerpt="complete",
                        )
                    ],
                    "has_more": False,
                    "next_cursor": "resume-tail",
                },
            )
        return httpx.Response(200, json={})

    client = httpx.Client(base_url="http://local", transport=httpx.MockTransport(handle))
    gaps = exporter.export_run(
        client,
        "run",
        tmp_path,
        observed_frames=[
            {
                "frame_id": "frame-one",
                "body": full,
                "body_digest": digest,
                "body_bytes": len(full.encode()),
            }
        ],
    )
    assert len(calls) == 1
    assert not any("repeated cursor" in gap or "missing/truncated" in gap for gap in gaps)
    assert (tmp_path / "04-bodies/000000.txt").read_text() == full
    assert (tmp_path / "06-evidence/body-recovery-000000.json").exists()
