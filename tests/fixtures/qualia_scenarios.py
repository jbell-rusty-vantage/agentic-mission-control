"""Observed live controls and prepared-configuration fork over ordinary public handlers."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx
from tests.fixtures.manifest_runtime import AUTHOR
from tests.fixtures.qualia_controls import (
    collect_control_receipts,
    fork_prepared_stage,
    send_stage_command,
)

from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.application.authoring.manifest_submit import SubmitRequest
from mission_control.application.frames.body_refs import parse_frame_body_ref
from mission_control.contracts.identities import mission_root_id
from mission_control.domain.execution.contracts import (
    DeepAgentExecutionBinding,
    OperationExecutionBinding,
)


def _save(root: Path, filename: str, value: Any) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / filename).write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")


async def _get(http: httpx.AsyncClient, path: str, **params: Any) -> dict[str, Any]:
    response = await http.get(path, params=params)
    response.raise_for_status()
    return response.json()


def _require_unstarted(inspection: dict[str, Any]) -> None:
    assert inspection["phase"] == "pending", "prepared template run started executing"
    assert inspection["projection"].get("execution_target") is None, (
        "prepared template run acquired an execution target"
    )


async def _artifact(
    http: httpx.AsyncClient,
    base: str,
    ref: str,
    cache: dict[str, bytes],
    *,
    digest: str | None = None,
    size: int | None = None,
) -> dict[str, Any]:
    """Read only through the scoped public route and verify the referenced bytes ourselves."""
    if ref.startswith("frame-body://"):
        expected = parse_frame_body_ref(ref)
        assert digest is None or expected.digest == digest, "message reference digest mismatch"
        assert size is None or expected.bytes == size, "message reference byte count mismatch"
        digest, size = expected.digest, expected.bytes
    assert digest is not None and size is not None, "artifact lacks an exact digest/byte count"
    key = f"{base}|{ref}"
    if key not in cache:
        response = await http.get(f"{base}/artifacts/{quote(ref, safe='')}")
        response.raise_for_status()
        cache[key] = response.content
    raw = cache[key]
    actual = "sha256:" + hashlib.sha256(raw).hexdigest()
    assert actual == digest and len(raw) == size, "scoped artifact digest/byte count mismatch"
    text = raw.decode("utf-8")
    try:
        body = json.loads(text)
    except ValueError:
        body = text
    return {"ref": ref, "digest": actual, "bytes": len(raw), "verified": True, "body": body}


async def _frame_document(
    http: httpx.AsyncClient,
    base: str,
    entry: dict[str, Any],
    cache: dict[str, bytes],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    refs, descriptor = entry.get("refs", {}), entry.get("body", {})
    ref = refs.get("artifact_ref") or descriptor.get("artifact_ref")
    observed = None
    if ref:
        observed = await _artifact(
            http,
            base,
            ref,
            cache,
            digest=refs.get("body_digest"),
            size=descriptor.get("bytes"),
        )
        document = observed["body"]
    else:
        document = json.loads(entry["body_excerpt"])
    assert isinstance(document, dict), "observed frame body is not an object"
    return document, observed


async def _model_messages(
    http: httpx.AsyncClient,
    base: str,
    entries: list[dict[str, Any]],
    cache: dict[str, bytes],
) -> list[dict[str, Any]]:
    proof = []
    for entry in entries:
        document, frame_read = await _frame_document(http, base, entry, cache)
        messages = []
        for part in [document.get("system"), *(document.get("messages") or [])]:
            if not isinstance(part, dict):
                continue
            if part.get("ref"):
                messages.append(
                    await _artifact(
                        http,
                        base,
                        part["ref"],
                        cache,
                        digest=part.get("digest"),
                        size=part.get("bytes"),
                    )
                )
            elif "body" in part:
                # A capture format that carries a body directly is still model input, rather
                # than arbitrary frame metadata; current Deep Agents captures use refs.
                messages.append({"body": part["body"], "source": "inline model-request part"})
        proof.append(
            {
                "node_key": entry.get("node_key"),
                "frame_id": entry.get("refs", {}).get("frame_id"),
                "frame_read": frame_read,
                "messages": messages,
            }
        )
    return proof


async def _entries(
    http: httpx.AsyncClient, path: str, *, cursor_parameter: str = "cursor", **params: Any
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    while True:
        page = await _get(http, path, **params)
        page_entries = page.get("entries", [])
        entries.extend(page_entries)
        cursor = page.get("next_cursor")
        # Transcript next_cursor is also a resumable live-tail watermark. Its presence
        # does not imply another page; the service explicitly reports has_more=False.
        if page.get("has_more") is False:
            return entries
        if not cursor:
            assert page.get("has_more") is not True, "public evidence page lacks its next cursor"
            return entries
        if not page_entries and page.get("has_more") is not True:
            return entries
        if cursor in seen:
            raise AssertionError("public evidence pagination repeated its cursor")
        seen.add(cursor)
        params[cursor_parameter] = cursor


def _applied(commands: dict[str, Any], command_id: str, *, injected: bool) -> bool:
    statuses = [
        row for row in commands.get("commands", []) if row["command"]["command_id"] == command_id
    ]
    if not statuses:
        return False
    assert len(statuses) == 1, "ambiguous command identity"
    receipts = statuses[0]["receipts"]
    state = receipts[-1]["state"]
    if state in {"rejected", "expired", "failed"}:
        raise AssertionError(f"live control ended {state}: {command_id}")
    reports = [row["delivery_report"] for row in receipts if row.get("delivery_report")]
    delivered = [report for report in reports if report.get("observed_outcome") == "delivered"]
    if state != "applied" or not delivered:
        return False
    if injected:
        assert any(report["delivered_semantics"] == "cancel_and_replace" for report in delivered)
        assert any(
            report.get("native_refs", {}).get("cancelled_turn_ref")
            and report.get("native_refs", {}).get("replacement_turn_ref")
            for report in delivered
        ), "injection lacks the actual cancelled/replacement turn refs"
    return True


async def _fork_materialization(
    stack: Any,
    derived: str,
    stage: str,
    skill_prefix: str = "qualia",
    required_tools: frozenset[str] = frozenset({"tavily_search", "tavily_extract"}),
) -> list[dict[str, Any]]:
    """Inspect actual saved bindings; no replacement or reconstructed provider pins."""
    scope = stack.database.scope("tenant-1")
    async with stack.worker_pool.acquire() as connection, connection.transaction():
        args = await mc.begin(connection, scope)
        rows = await connection.fetch(
            "SELECT payload FROM mission_control.runtime_document WHERE "
            "installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
            "AND contract='operation.binding/1' AND payload->>'run_id'=$4",
            *args,
            derived,
        )
    evidence = []
    for row in rows:
        bound = OperationExecutionBinding.model_validate(mc.load(row["payload"]))
        unit = bound.runtime_unit
        if unit is None or getattr(unit.location, "stage_id", None) != stage:
            continue
        deep = DeepAgentExecutionBinding.carried_by(bound)
        assert deep is not None, "forked research stage did not execute Deep Agents"
        assert bound.lane_binding is not None
        skills = {skill.skill_name for skill in deep.skills}
        tools = {tool.tool_name for tool in deep.tools}
        assert f"{skill_prefix}-tavily-research" in skills
        assert f"{skill_prefix}-firecrawl-research" not in skills
        assert required_tools <= tools, (required_tools, tools)
        assert not {"firecrawl_search", "firecrawl_scrape"} & tools
        evidence.append(
            {
                "binding_id": bound.binding_id,
                "unit_key": unit.unit_key,
                "skills": sorted(skills),
                "tools": sorted(tools),
                "lane_binding_digest": bound.lane_binding.digest,
            }
        )
    assert evidence, "no actual saved binding for the forked stage"
    return evidence


async def controller(
    stack: Any,
    control_http: httpx.AsyncClient,
    run_id: str,
    interventions: Any,
    root: Path,
    *,
    timeout_seconds: float = 180,
    queued: str = "formulations",
    interrupted: str = "studies",
    marker_prefix: str = "QUALIA",
) -> dict[str, Any]:
    """Run once as a concurrent task after admission; fail unless both controls truly apply."""
    application = stack.database.application_id
    base = f"/v1/applications/{application}/runs/{run_id}"
    records: list[dict[str, Any]] = []
    markers = {key: f"{marker_prefix}-{key.upper()}-{uuid4().hex}" for key in (queued, interrupted)}
    result: dict[str, Any] = {"run_id": run_id, "markers": markers, "result": "started"}
    accepted: dict[str, Any] = {}
    artifact_cache: dict[str, bytes] = {}

    async def send(position: str) -> None:
        await interventions.entered.setdefault(position, asyncio.Event()).wait()
        live = interventions.started[position]
        assert live.run_id == run_id and live.position == position
        text = (
            f"Operator directive {markers[position]}: preserve this exact marker in your "
            "output details.control_directive, distinguish company marketing from study findings, "
            "and retain unfavorable or null evidence. Continue using the actual source tools."
        )
        receipt = await send_stage_command(
            control_http,
            application_id=application,
            run_id=run_id,
            node_key=position,
            text=text,
            kind="queue_instruction" if position == queued else "interrupt_and_inject",
            records=records,
        )
        assert receipt["admission"]["status"] == "accepted", receipt
        accepted[position] = receipt
        if position == interrupted:
            # Keep the original tool blocked until the actual interrupt cancels it.
            # Releasing earlier would turn disruption proof into an ordinary next-turn note.
            await interventions.cancelled.setdefault(position, asyncio.Event()).wait()
        interventions.release(position)

    try:
        async with asyncio.timeout(timeout_seconds):
            async with asyncio.TaskGroup() as group:
                for position in markers:
                    group.create_task(send(position))
            while True:
                commands = await collect_control_receipts(
                    control_http, application_id=application, run_id=run_id, records=records
                )
                applied = all(
                    _applied(
                        commands,
                        accepted[position]["admission"]["command_id"],
                        injected=position == interrupted,
                    )
                    for position in markers
                )
                requests = await _entries(
                    control_http,
                    f"{base}/transcript",
                    cursor_parameter="since",
                    format="json",
                    kinds="model_request",
                    full=True,
                    limit=500,
                )
                message_proof = await _model_messages(control_http, base, requests, artifact_cache)
                visible = {
                    position: any(
                        row.get("node_key") == position
                        and any(
                            marker in json.dumps(message["body"]) for message in row["messages"]
                        )
                        for row in message_proof
                    )
                    for position, marker in markers.items()
                }
                if applied and all(visible.values()):
                    result.update(
                        result="passed",
                        commands=commands,
                        model_visible_markers=visible,
                        model_requests=requests,
                        verified_model_messages=message_proof,
                    )
                    return result
                state = await _get(control_http, f"{base}/inspection")
                if state["phase"] == "terminal":
                    raise AssertionError(
                        "mission ended without both applied/model-visible controls"
                    )
                await asyncio.sleep(0.5)
    except BaseException as error:
        result.update(result="failed", error={"type": type(error).__name__, "message": str(error)})
        raise
    finally:
        for position in markers:
            interventions.release(position)
        result.update(requests=records, checkpoint_events=interventions.records)
        _save(root, "live-controls.json", result)


async def fork_from_completed_stage(
    stack: Any,
    control_http: httpx.AsyncClient,
    source_run_id: str,
    prepared_lifecycle: Any,
    prepared_manifest: str,
    root: Path,
    *,
    stage: str = "studies",
    timeout_seconds: float = 1800,
    skill_prefix: str = "qualia",
    marker_prefix: str = "QUALIA",
    required_tools: frozenset[str] = frozenset({"tavily_search", "tavily_extract"}),
) -> dict[str, Any]:
    """Freeze a new exact ERC, fork a settled source cursor, launch and await ordinary root."""
    application = stack.database.application_id
    base = f"/v1/applications/{application}/runs"
    records: list[dict[str, Any]] = []
    result: dict[str, Any] = {"source_run_id": source_run_id, "result": "started"}
    _save(root, "01-prepared-manifest.json", {"manifest_yaml": prepared_manifest})
    try:
        source = await _get(control_http, f"{base}/{source_run_id}/inspection")
        assert source["phase"] == "terminal" and source.get("execution_outcome") == "completed"
        points = await _entries(
            control_http,
            f"{base}/{source_run_id}/points",
            node=stage,
            role="result",
            kind="checkpoint",
            seedable=True,
            limit=500,
        )
        seed = None
        for candidate in sorted(points, key=lambda point: point.get("ordinal") or 0, reverse=True):
            if candidate["coordinate"]["point"]["key"].get("checkpoint_ns", ""):
                continue  # only the stage's root cognition; never a child tool/subagent cursor
            state = await _get(
                control_http, f"{base}/{source_run_id}/points/{candidate['point_id']}/state-as-of"
            )
            if not state["state"].get("pending_tasks") and not state["state"].get("interrupts"):
                seed = candidate
                result["source_state_as_of"] = state
                break
        assert seed is not None, (
            "no completed safe seedable root checkpoint for the requested stage"
        )
        snapshot_response = await control_http.post(
            f"{base}/{source_run_id}/snapshots", json={"expected_version": source["version"]}
        )
        snapshot_response.raise_for_status()
        snapshot = snapshot_response.json()["snapshot"]
        receipt, _ = await prepared_lifecycle.submit(
            SubmitRequest(
                manifest_yaml=prepared_manifest,
                request_id=uuid4(),
                actor=AUTHOR,
                sponsorship_refs=frozenset({"sponsorship:test"}),
            )
        )
        (mission,) = receipt.missions
        assert mission.family == "StageGraph" and mission.run_id is not None
        # The same ordinary author used by ManifestSubmitService.start, without launching
        # the preparation run. The derived run alone executes this newly pinned manifest.
        author = prepared_lifecycle._launch_inputs
        assert author is not None
        prepared = await author.family_input(
            request_scope=stack.database.scope("tenant-1"),
            run_id=mission.run_id,
            family="StageGraph",
            initial_goal=None,
        )
        prepared_state = await _get(control_http, f"{base}/{mission.run_id}/inspection")
        result["prepared_run_before_fork"] = prepared_state
        _require_unstarted(prepared_state)
        assert prepared["semantic_input_binding_ref"] == f"semantic-input:manifest:{mission.run_id}"
        marker = f"{marker_prefix}-FORK-TAVILY-{uuid4().hex}"
        plan = await fork_prepared_stage(
            control_http,
            application_id=application,
            source_run_id=source_run_id,
            snapshot=snapshot,
            point=seed,
            prepared_family_input=prepared,
            prepared_input_manifest=prepared_state["projection"]["input_manifest"],
            prepared_binding_ref=prepared["semantic_input_binding_ref"],
            instruction=(
                f"Operator fork directive {marker}: use the newly materialized Tavily research "
                "skill/tools to independently reassess study limitations. Preserve the marker "
                "in details.control_directive. Prior Firecrawl messages are historical source "
                "context; use only current admitted tools and fresh captured evidence."
            ),
            sponsorship_ref="sponsorship:test",
            approval_refs=["approval:test"],
            records=records,
        )
        result.update(
            plan=plan,
            seed_point=seed,
            snapshot=snapshot,
            prepared_run_id=mission.run_id,
            prepared_family_input=prepared,
            fork_marker=marker,
        )
        _save(root, "fork-plan.json", result)
        launched = await control_http.post(plan["launch_path"], json=plan["launch_body"])
        launched.raise_for_status()
        result["launch_receipt"] = launched.json()
        derived = plan["fork"]["receipt"]["target_run_id"]
        async with asyncio.timeout(timeout_seconds):
            while True:
                for stop in (root / "stop-requested.txt", root.parent / "stop-requested.txt"):
                    if stop.exists():
                        raise RuntimeError(
                            "Fixture stopped for repair: " + stop.read_text(encoding="utf-8")[:2000]
                        )
                state = await _get(control_http, f"{base}/{derived}/inspection")
                if state["phase"] == "terminal":
                    break
                await asyncio.sleep(0.5)
            root_handle = stack.client.get_workflow_handle(
                mission_root_id(stack.database.scope("tenant-1"), derived)
            )
            assert (await root_handle.describe()).workflow_type == "mc.mission_run.v1"
            result["root_result"] = await root_handle.result()
        assert state.get("execution_outcome") == "completed", state
        prepared_after = await _get(control_http, f"{base}/{mission.run_id}/inspection")
        prepared_points = await _entries(control_http, f"{base}/{mission.run_id}/points", limit=500)
        result.update(prepared_run_after_fork=prepared_after, prepared_run_points=prepared_points)
        _require_unstarted(prepared_after)
        assert not prepared_points, "prepared template run acquired cognition points"
        assert prepared_after["version"] == prepared_state["version"], (
            "prepared template run changed while the derived run executed"
        )
        assert (
            prepared_after["projection"]["input_manifest"]
            == prepared_state["projection"]["input_manifest"]
        )
        assert (
            prepared_after["projection"]["effective_configuration_digest"]
            == prepared_state["projection"]["effective_configuration_digest"]
        )
        fork_receipt = plan["fork"]["receipt"]
        assert not fork_receipt.get("reused_units"), "changed ERC silently reused source work"
        seeds = await _entries(
            control_http,
            f"{base}/{derived}/points",
            node=stage,
            role="fork_seed",
            kind="checkpoint",
            limit=500,
        )
        assert any(point.get("parent_coordinate") == seed["coordinate"] for point in seeds), (
            "derived fork seed has no exact source checkpoint lineage"
        )
        requests = await _entries(
            control_http,
            f"{base}/{derived}/transcript",
            cursor_parameter="since",
            format="json",
            node=stage,
            kinds="model_request",
            full=True,
            limit=20,
        )
        artifact_cache: dict[str, bytes] = {}
        derived_base = f"{base}/{derived}"
        message_proof = await _model_messages(control_http, derived_base, requests, artifact_cache)
        assert any(
            marker in json.dumps(message["body"])
            for row in message_proof
            for message in row["messages"]
        ), "fork message absent from model input"
        materials = await _entries(
            control_http,
            f"{base}/{derived}/transcript",
            cursor_parameter="since",
            format="json",
            node=stage,
            kinds="environment_materialized",
            full=True,
            limit=20,
        )
        observed = [
            (await _frame_document(control_http, derived_base, row, artifact_cache))[0]
            for row in materials
        ]
        assert any(
            any(
                skill.get("name") == f"{skill_prefix}-tavily-research"
                for skill in row.get("skills", [])
            )
            and any(
                f"/{skill_prefix}-tavily-research/SKILL.md" in item["path"]
                for item in [
                    *row.get("files", []),
                    *row.get("state_files", []),
                    *row.get("sandbox_files", []),
                ]
            )
            for row in observed
        ), "Tavily skill has no observed actual materialization"
        result.update(
            fork_seed_points=seeds,
            model_requests=requests,
            verified_model_messages=message_proof,
            materialization_frames=materials,
            exact_capability_bindings=await _fork_materialization(
                stack, derived, stage, skill_prefix, required_tools
            ),
        )
        result.update(result="passed", derived_run_id=derived, terminal=state)
        return result
    except BaseException as error:
        result.update(result="failed", error={"type": type(error).__name__, "message": str(error)})
        raise
    finally:
        result["public_requests"] = records
        _save(root, "fork-scenario.json", result)
