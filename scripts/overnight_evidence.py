"""Read-only, authenticated fixture evidence export. No qualification inference.

The supplied client must already be bound to the application API and operator identity.
Raw observations are retained beside readable indexes; absent evidence stays absent.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from mission_control.domain.frames.body import SECRET_KEYS, redact_text
from mission_control.domain.frames.render import to_jsonl, to_markdown
from mission_control.domain.frames.transcript import TranscriptCursor, TranscriptEntry

SECRET_KEY = re.compile(
    r"(?:^|_)(?:token|access_token|refresh_token|api_key|secret|password|dsn|authorization|credentials?)$",
    re.IGNORECASE,
)


def redact(value: Any) -> Any:
    """Redact credential fields without removing input_tokens/token_budget metrics."""
    if isinstance(value, dict):
        return {
            k: "<redacted>"
            if SECRET_KEY.search(k.replace("-", "_")) or k.lower().replace("-", "_") in SECRET_KEYS
            else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)[0]
    return value


def observe_mission_event(run: str, record: dict[str, Any]) -> dict[str, Any]:
    """Retain a scoped durable event, with hashes of canonical JSON projections.

    ``record`` must come from the run-scoped mission_event reader. These are not
    original provider bytes: PostgreSQL stores the envelope as JSONB, and the
    transcript projects its nested payload, excluding execution/source/usage.
    """
    envelope = record["payload"]
    if isinstance(envelope, str):
        envelope = json.loads(envelope)
    if not isinstance(envelope, dict):
        raise ValueError("mission_event envelope must be an object")
    payload = envelope.get("payload")
    payload = payload if isinstance(payload, dict) else envelope
    body = {
        key: value for key, value in payload.items() if key not in {"execution", "source", "usage"}
    }

    def canonical(value: Any) -> bytes:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
        ).encode("utf-8")

    raw_envelope, raw_body = canonical(envelope), canonical(body)
    return {
        "source": "mission_control.mission_event",
        "run_id": run,
        "event_id": str(record["event_id"]),
        "event_type": record["event_type"],
        "seq": record["seq"],
        "recorded_at": str(record["recorded_at"]),
        "envelope": envelope,
        "envelope_canonical_digest": "sha256:" + hashlib.sha256(raw_envelope).hexdigest(),
        "body_digest": "sha256:" + hashlib.sha256(raw_body).hexdigest(),
        "body_bytes": len(raw_body),
    }


def recover_mission_event(
    run: str, entry: dict[str, Any], observations: list[dict[str, Any]]
) -> tuple[str, dict[str, Any]] | None:
    """Check exact canonical-event identity and projection; never use a native frame."""
    event_id = entry.get("refs", {}).get("event_id")
    candidates = [row for row in observations if row.get("event_id") == event_id]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError("duplicate scoped mission_event observation")
    row = candidates[0]
    if (
        not event_id
        or entry.get("canonical") is not True
        or entry.get("source") != "mission_event"
        or row.get("source") != "mission_control.mission_event"
        or entry.get("run_id") != run
        or row.get("run_id") != run
        or row.get("event_type") != entry.get("kind")
        or row.get("seq") != TranscriptCursor.decode(entry["cursor"]).seq
    ):
        raise ValueError("scoped mission_event identity mismatch")
    checked = observe_mission_event(run, {**row, "payload": row.get("envelope")})
    if any(
        checked[key] != row.get(key)
        for key in ("envelope_canonical_digest", "body_digest", "body_bytes")
    ):
        raise ValueError("scoped mission_event envelope/body digest or size mismatch")
    envelope = checked["envelope"]
    payload = envelope.get("payload")
    payload = payload if isinstance(payload, dict) else envelope
    body = {
        key: value for key, value in payload.items() if key not in {"execution", "source", "usage"}
    }
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    source = payload.get("source")
    native_ref = source.get("native_event_ref") if isinstance(source, dict) else None
    if native_ref != entry.get("refs", {}).get("native_event_ref"):
        raise ValueError("scoped mission_event native reference mismatch")
    if len(text.encode("utf-8")) != entry.get("body", {}).get("bytes"):
        raise ValueError("scoped mission_event transcript body size mismatch")
    excerpt = entry.get("body_excerpt")
    if not isinstance(excerpt, str) or not excerpt or not text.startswith(excerpt):
        raise ValueError("scoped mission_event transcript prefix mismatch")
    return text, {
        "source": "canonical projection of scoped durable mission_event",
        "event_id": event_id,
        "run_id": run,
        "event_type": row["event_type"],
        "digest": checked["body_digest"],
        "bytes": checked["body_bytes"],
        "envelope_canonical_digest": checked["envelope_canonical_digest"],
        "digest_verification": (
            "canonical JSON projection before export redaction; not provider bytes"
        ),
        "transcript_projection_state": entry.get("body", {}).get("state"),
        "durable_event_observation": checked,
    }


def export_run(
    client: httpx.Client,
    run: str,
    destination: Path,
    *,
    observed_config: dict[str, Any] | None = None,
    materializations: list[dict[str, Any]] | None = None,
    output_bodies: list[dict[str, Any]] | None = None,
    authored_config: dict[str, Any] | None = None,
    observed_frames: list[dict[str, Any]] | None = None,
    observed_events: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Collect before fixture teardown; return explicit gaps, including HTTP failures.

    Optional snapshots must be actual fixture observations, including their source and
    run/unit identities. Output rows carry ``content`` (UTF-8 str/bytes), ``digest``
    (sha256:<hex>) and caller-supplied producer/slot/revision/status/read provenance.
    This function checks body bytes, not the trustworthiness of supplied provenance.
    """
    destination.mkdir(parents=True, exist_ok=True)
    gaps: list[str] = []
    observations: dict[str, list[Any]] = {}
    observed_config = redact(observed_config)
    authored_config = redact(authored_config)
    materializations = redact(materializations)
    authorization = client.headers.get("authorization", "")
    bearer = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""

    def safe_text(text: str) -> str:
        text = redact_text(text, (bearer,) if bearer else ())[0]
        if bearer:
            text = text.replace(bearer, "<redacted>")
        try:
            value = json.loads(text)
        except ValueError:
            return text
        cleaned = redact(value)
        return json.dumps(cleaned, ensure_ascii=False, indent=2) if cleaned != value else text

    def write(name: str, value: Any) -> None:
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            safe_text(json.dumps(redact(value), indent=2, ensure_ascii=False)), encoding="utf-8"
        )

    def collect(name: str, path: str, *, transcript: bool = False) -> list[Any]:
        pages: list[Any] = []
        params: dict[str, Any] = {"format": "json", "full": "true"} if transcript else {}
        seen: set[str] = set()
        request_index = 0
        while True:
            try:
                response = client.get(path, params=params)
                body = response.json()
            except (httpx.RequestError, ValueError) as exc:
                gaps.append(f"{name}: {type(exc).__name__}")
                break
            write(
                f"06-evidence/{name}.{request_index:04d}.json",
                {"status": response.status_code, "body": body},
            )
            request_index += 1
            if response.status_code != 200:
                gaps.append(f"{name}: HTTP {response.status_code}")
                # Full-body service can be absent while ordinary transcript is available.
                if transcript and params.get("full") == "true":
                    params["full"] = "false"
                    continue
                break
            pages.append(body)
            # Transcript next_cursor is also a resume watermark on the last page.
            # Only has_more promises another page; an unchanged tail is not truncation.
            if transcript and body.get("has_more") is False:
                break
            cursor = body.get("next_cursor") or response.headers.get("X-Transcript-Next-Cursor")
            parameter = "since" if transcript else "cursor"
            if body.get("next_after_family_version") is not None:
                cursor, parameter = body["next_after_family_version"], "after_family_version"
            if cursor is None or cursor == "":
                if body.get("has_more"):
                    gaps.append(f"{name}: has_more without cursor")
                break
            if str(cursor) in seen:
                gaps.append(f"{name}: repeated cursor; incomplete")
                break
            seen.add(str(cursor))
            params[parameter] = cursor
        observations[name] = pages
        return pages

    prefix = f"/runs/{quote(run, safe='')}"
    for name in (
        "inspection",
        "completion-evidence",
        "goal-completion-evidence",
        "evidence",
        "points",
        "commands",
        "output-events",
        "transfer-plans",
        "outputs",
    ):
        collect(name, f"{prefix}/{name}")
    for page in observations.get("transfer-plans", []):
        for plan in page.get("transfer_plans", []):
            plan_id = plan["plan_id"]
            collect(
                f"plan-{hashlib.sha256(plan_id.encode()).hexdigest()[:16]}",
                f"/transfer-plans/{quote(plan_id, safe='')}",
            )
    revisions: list[dict[str, Any]] = []
    for page in observations.get("outputs", []):
        for obligation in page.get("obligations", []):
            key = obligation["obligation_key"]
            history = collect(
                f"revisions-{hashlib.sha256(key.encode()).hexdigest()[:16]}",
                f"{prefix}/outputs/{quote(key, safe='')}/revisions",
            )
            revisions.extend(row for part in history for row in part.get("revisions", []))
    pages = collect("transcript", f"{prefix}/transcript", transcript=True)
    entries = [redact(row) for page in pages for row in page.get("entries", [])]
    models = []
    for row in entries:
        try:
            models.append(TranscriptEntry.model_validate(row))
        except ValidationError:
            gaps.append(
                "Invalid transcript entry; retained in raw page, excluded from canonical renderer"
            )
    (destination / "04-workflow-transcript.jsonl").write_text(
        to_jsonl(models, secret_values=(bearer,) if bearer else ()),
        encoding="utf-8",
    )
    lines = [
        to_markdown(models, run_id=run, secret_values=(bearer,) if bearer else ()),
        "",
        "## Complete body sidecars",
        "",
    ]
    bodies = destination / "04-bodies"
    bodies.mkdir(exist_ok=True)
    for index, entry in enumerate(entries):
        body = entry.get("body", {})
        ref = body.get("artifact_ref") or entry.get("refs", {}).get("artifact_ref")
        text = entry.get("body_excerpt")
        state = body.get("state")
        filename = f"04-bodies/{index:06d}.txt"
        missing = state in {"excerpt", "expired", "pruned"} or bool(body.get("truncated"))
        if (
            missing
            and state not in {"expired", "pruned"}
            and entry.get("canonical") is True
            and entry.get("source") == "mission_event"
        ):
            try:
                recovered = recover_mission_event(run, entry, observed_events or [])
            except (KeyError, TypeError, ValueError) as exc:
                gaps.append(f"entry {index}: canonical event recovery refused: {exc}")
            else:
                if recovered is not None:
                    text, proof = recovered
                    missing = False
                    write(f"06-evidence/body-recovery-{index:06d}.json", proof)
        if (
            missing
            and state not in {"expired", "pruned"}
            and entry.get("source") == "provider_frame"
            and entry.get("canonical") is False
        ):
            frame_id = entry.get("refs", {}).get("frame_id")
            for frame in observed_frames or []:
                if frame.get("frame_id") != frame_id or not isinstance(frame.get("body"), str):
                    continue
                raw = frame["body"].encode("utf-8")
                digest = "sha256:" + hashlib.sha256(raw).hexdigest()
                if digest == frame.get("body_digest") and len(raw) == frame.get("body_bytes"):
                    text, missing = frame["body"], False
                    write(
                        f"06-evidence/body-recovery-{index:06d}.json",
                        {
                            "source": frame.get("body_recovery", {}).get(
                                "source", "fixture-observed original provider frame"
                            ),
                            "frame_id": frame_id,
                            "digest": digest,
                            "bytes": len(raw),
                            "transcript_projection_state": state,
                            "digest_verification": "pre-redaction original bytes",
                            "recovery_provenance": frame.get("body_recovery"),
                        },
                    )
                else:
                    gaps.append(f"entry {index}: original frame body digest/size mismatch")
                break
        if ref and state not in {"expired", "pruned"}:
            # Never follow arbitrary URLs: the granted reader binds reference to this run.
            try:
                response = client.get(f"{prefix}/artifacts/{quote(ref, safe='')}")
                if response.status_code == 200:
                    text = response.content.decode("utf-8")
                    missing = False
                else:
                    gaps.append(f"entry {index}: body HTTP {response.status_code}")
                    missing = True
            except (httpx.RequestError, UnicodeDecodeError) as exc:
                gaps.append(f"entry {index}: body {type(exc).__name__}")
                missing = True
        if text is not None:
            cleaned_text = safe_text(text)
            if cleaned_text != text:
                gaps.append(f"entry {index}: credential redaction changed body bytes")
            text = cleaned_text
            (destination / filename).write_text(text, encoding="utf-8", newline="")
        else:
            missing = True
        if missing:
            gaps.append(f"entry {index}: missing/truncated body ({state})")
        identity = {
            k: entry.get(k)
            for k in ("at", "role", "unit_key", "node_key", "iteration", "attempt_no", "point_id")
        }
        lines.extend(
            [
                f"- Entry {index + 1}: `{json.dumps(identity)}`; "
                f"missing/truncated={missing}; "
                + (f"[complete body]({filename})" if text is not None else "body unavailable")
            ]
        )
    (destination / "04-workflow-transcript.md").write_text("\n".join(lines), encoding="utf-8")
    write("05-outputs/revisions.json", revisions)
    (destination / "05-outputs/INDEX.md").write_text(
        "# Observed output revisions\n\n[Exact revision metadata](revisions.json)\n\n"
        + "\n".join(
            f"- {r.get('obligation_key')}: revision {r.get('revision_id')}, "
            f"digest {r.get('content_digest')}, accepted={r.get('accepted')}"
            for r in revisions
        )
        + "\n\nRevision inspection provides metadata. "
        "Exact body exports are listed below when available.\n",
        encoding="utf-8",
    )
    if observed_config is None:
        gaps.append("Full effective configuration snapshot not exposed by these collected routes.")
    if not materializations:
        gaps.append(
            "Actual materialization manifests/files require fixture-supplied observed receipts."
        )
    if not output_bodies:
        gaps.append(
            "Output report body retrieval requires an authorized content retrieval binding."
        )
    write(
        "02-effective-run-config.json",
        {
            "status": "fixture_observation" if observed_config else "missing",
            "snapshot": observed_config,
            "observed_inspection": observations.get("inspection", []),
        },
    )
    for filename, text in (
        (
            "02-effective-run-config.md",
            "Full effective configuration missing; see inspection observations in JSON.",
        ),
        (
            "03-materialized/INDEX.md",
            "Materialization evidence missing. "
            "Authored configuration is not proof of actual bindings.",
        ),
    ):
        path = destination / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    if observed_config is not None:
        version = hashlib.sha256(
            json.dumps(observed_config, sort_keys=True).encode("utf-8")
        ).hexdigest()
        version_file = f"02-effective-versions/{version}.json"
        write(version_file, observed_config)
        (destination / "02-effective-run-config.md").write_text(
            "# Fixture-observed effective configuration\n\n"
            "See [full snapshot](02-effective-run-config.json). "
            "This observation is fixture-supplied.\n"
            "\n"
            + "\n".join(
                f"- {key}: `{json.dumps(redact(value), ensure_ascii=True)}`"
                for key, value in observed_config.items()
            )
            + f"\n\n[Retained effective version]({version_file})\n",
            encoding="utf-8",
        )
    if materializations:
        write("03-materialized/observations.json", materializations)
        (destination / "03-materialized/INDEX.md").write_text(
            "# Fixture-observed materialization\n\n[Actual observations](observations.json)\n\n"
            "Comparison uses matching field names only; absent fields are missing evidence.\n\n"
            + "\n".join(
                f"- Observation {index}, field {key}: "
                f"authored={json.dumps(redact((authored_config or {}).get(key, 'MISSING')))}; "
                f"effective={json.dumps(redact((observed_config or {}).get(key, 'MISSING')))}; "
                f"materialized={json.dumps(redact(value))}; "
                f"effective match={(observed_config or {}).get(key, object()) == value}"
                for index, row in enumerate(materializations)
                for key, value in row.items()
            ),
            encoding="utf-8",
        )
    body_index = []
    for index, output in enumerate(output_bodies or []):
        content = output["content"]
        data = content.encode("utf-8") if isinstance(content, str) else content
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        if digest != output["digest"]:
            gaps.append(f"output {index}: digest mismatch; body not exported")
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            gaps.append(f"output {index}: non-UTF-8 body; readable export unavailable")
            continue
        cleaned = safe_text(text)
        changed = cleaned != text
        if changed:
            gaps.append(f"output {index}: credential redaction changed body bytes")
        filename = f"05-outputs/body-{index:04d}.txt"
        (destination / filename).write_text(cleaned, encoding="utf-8", newline="")
        metadata = {k: v for k, v in output.items() if k != "content"}
        metadata.update(file=filename, digest_verified=True, redacted=changed)
        body_index.append(metadata)
    write("05-outputs/body-index.json", body_index)
    with (destination / "05-outputs/INDEX.md").open("a", encoding="utf-8") as stream:
        stream.write("\n[Fixture-read exact bodies and digest checks](body-index.json)\n")
        for row in body_index:
            filename = Path(row["file"]).name
            stream.write(
                f"\n- [{row.get('revision_id', 'unknown revision')}]({filename}): "
                f"producer={row.get('producer', 'MISSING')}, slot={row.get('slot', 'MISSING')}, "
                f"status={row.get('status', 'MISSING')}, digest={row['digest']}, "
                f"redacted={row['redacted']}\n"
            )
    (destination / "README.md").write_text(
        f"# Run {run}\n\nObserved API export; no qualification claim.\n\nMissing evidence:\n\n"
        + "\n".join(f"- {gap}" for gap in gaps),
        encoding="utf-8",
    )
    (destination / "07-validation.md").write_text(
        "# Export validation\n\nIndependent workflow acceptance remains unrun.\n\n"
        + "\n".join(f"- {gap}" for gap in gaps),
        encoding="utf-8",
    )
    return gaps
