"""missionctl: a thin authenticated client, never a second lifecycle authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid4

import httpx

from mission_control.contracts.json import parse_json_object
from mission_control.domain.capabilities.bundles import build_bundle_manifest, skipped
from mission_control.interfaces.cli.exits import exit_status
from mission_control.interfaces.cli.knowledge import add_knowledge_parsers, run_knowledge
from mission_control.interfaces.cli.outputs import add_output_parsers, run_outputs
from mission_control.interfaces.cli.selection import add_selection_parsers, run_selection
from mission_control.interfaces.cli.setup import add_setup_parsers, run_setup
from mission_control.interfaces.cli.token import add_token_parser, run_token
from mission_control.interfaces.cli.wait import add_wait_parsers, run_inbox, run_wait

_BUNDLE_PREFIXES = {"skill_bundle": "skill", "hook_script": "hook", "subagent_profile": "subagent"}


def strict_object(path: str) -> dict[str, Any]:
    return parse_json_object(Path(path).read_text(encoding="utf-8"))


class MissionClient:
    def __init__(self, client: httpx.Client, application_id: str) -> None:
        if not application_id or application_id in {".", ".."}:
            raise ValueError("application id must be a nonempty identifier")
        self.client = client
        self.prefix = f"/v1/applications/{quote(application_id, safe='')}"

    def inspection(self, run_id: str) -> httpx.Response:
        return self.client.get(f"{self.prefix}/runs/{self._id(run_id)}/inspection")

    def prerequisite(
        self, action: str, body: dict[str, Any], target: str | None = None
    ) -> httpx.Response:
        path = f"{self.prefix}/prerequisites"
        if target is not None:
            path += f"/{self._id(target)}"
        return self.client.post(f"{path}:{action}", json=body)

    def command(self, run_id: str, body: dict[str, Any]) -> httpx.Response:
        return self.client.post(
            f"{self.prefix}/runs/{self._id(run_id)}/commands",
            json=body,
            headers={"Idempotency-Key": str(body.get("request_id", ""))},
        )

    def commands(self, run_id: str) -> httpx.Response:
        return self.client.get(f"{self.prefix}/runs/{self._id(run_id)}/commands")

    def manifest(
        self, verb: str, body: dict[str, Any], *, notify: str | None = None
    ) -> httpx.Response:
        """FT-E2/E3: ``POST /missions:compile``, ``missions:submit`` and ``missions:start``."""

        return self.client.post(
            f"{self.prefix}/missions:{verb}", json=body, params=_notify_params(notify)
        )

    def chain(self, chain_id: str) -> httpx.Response:
        """FT-D2: the ``mc.chain.v1`` projection with each member's run."""

        return self.client.get(f"{self.prefix}/chains/{self._id(chain_id)}")

    def admit(self, body: dict[str, Any]) -> httpx.Response:
        return self.client.post(
            f"{self.prefix}/run-requests",
            json=body,
            headers={"Idempotency-Key": str(body.get("request_id", ""))},
        )

    def runtime_action(
        self, run_id: str, action: str, body: dict[str, Any], *, notify: str | None = None
    ) -> httpx.Response:
        suffix = {
            "snapshot": "snapshots",
            "fork": "forks",
            "reconcile": "reconcile-unit",
            "start": "launch",
        }[action]
        headers = {"Idempotency-Key": str(body["request_id"])} if "request_id" in body else {}
        return self.client.post(
            f"{self.prefix}/runs/{self._id(run_id)}/{suffix}",
            json=body,
            headers=headers,
            params=_notify_params(notify),
        )

    def catalog(self, action: str, body: dict[str, Any] | None = None) -> httpx.Response:
        if action == "list":
            return self.client.get(f"{self.prefix}/catalog/definitions")
        if action == "components":
            return self.client.post(f"{self.prefix}/catalog/components/search", json=body)
        if action not in {"resolve", "search", "discover", "inspect", "pin", "render"}:
            raise ValueError("unknown catalog action")
        return self.client.post(f"{self.prefix}/catalog/{action}", json=body)

    def lanes(self, profile: str | None = None) -> httpx.Response:
        """FT-G1: `lane list` and `lane describe PROFILE`."""

        if profile is None:
            return self.client.get(f"{self.prefix}/lanes")
        return self.client.get(f"{self.prefix}/lanes/{self._id(profile)}")

    def models(self, profile: str | None = None) -> httpx.Response:
        """OC-R6 (OC-D201): `model list` and `model describe PROFILE`: the Model Catalog with
        each lane's route verdict for the profile's vendor."""

        if profile is None:
            return self.client.get(f"{self.prefix}/models")
        return self.client.get(f"{self.prefix}/models/{self._id(profile)}")

    def selection(self, action: str, body: dict[str, Any]) -> httpx.Response:
        """`search` and `workspace check`: the Selection Workspace routes."""

        if action not in {"search", "check"}:
            raise ValueError("unknown selection action")
        return self.client.post(f"{self.prefix}/selection/{action}", json=body)

    def catalog_pin(self, pin: str) -> httpx.Response:
        """FT-A8: inspect one Capability Pin (body, host support, members)."""
        return self.client.get(f"{self.prefix}/catalog/pins/{quote(pin, safe='')}")

    def publish(self, phase: str, body: dict[str, Any]) -> httpx.Response:
        if phase not in {"prepare", "complete"}:
            raise ValueError("unknown publish phase")
        return self.client.post(f"{self.prefix}/catalog/publish:{phase}", json=body)

    def points(self, run_id: str, params: dict[str, Any]) -> httpx.Response:
        """P1 turn 4: `run points RUN [filters]` over `mc.cognition_point.v1`."""

        return self.client.get(f"{self.prefix}/runs/{self._id(run_id)}/points", params=params)

    def reconcile_points(self, run_id: str, body: dict[str, Any]) -> httpx.Response:
        """1.4.4 (TR-D6): `run points RUN --reconcile` -> `mc.points_reconciliation.v1`."""

        return self.client.post(
            f"{self.prefix}/runs/{self._id(run_id)}/points:reconcile", json=body
        )

    def point(self, run_id: str, point_id: str) -> httpx.Response:
        """1.4.4 (P5.1): one `mc.cognition_point.v1` row, for `run fork --point ID`."""

        return self.client.get(f"{self.prefix}/runs/{self._id(run_id)}/points/{self._id(point_id)}")

    def state_as_of(self, run_id: str, point_id: str) -> httpx.Response:
        """P1 turn 4: `run state-as-of RUN --point ID` (`mc.state_as_of.v1`)."""

        return self.client.get(
            f"{self.prefix}/runs/{self._id(run_id)}/points/{self._id(point_id)}/state-as-of"
        )

    def closure(self, run_id: str, point_id: str) -> httpx.Response:
        """OVE-204 slice 5: `run closure RUN --point ID` (`mc.workspace_closure.v1`)."""

        return self.client.get(
            f"{self.prefix}/runs/{self._id(run_id)}/points/{self._id(point_id)}/closure"
        )

    def closures(self, run_id: str) -> httpx.Response:
        """OVE-204 slice 5: `run closure RUN --list` (the run's closure summaries)."""

        return self.client.get(f"{self.prefix}/runs/{self._id(run_id)}/closures")

    def artifact(self, run_id: str, ref: str) -> httpx.Response:
        """1.4.4 (TR-D3): `run artifact RUN REF --out FILE`; the reference travels
        URL-encoded in the path and the bytes come back verified against its digest."""

        return self.client.get(
            f"{self.prefix}/runs/{self._id(run_id)}/artifacts/{quote(ref, safe='')}"
        )

    def replay(self, run_id: str, point_id: str, params: dict[str, Any]) -> httpx.Response:
        """1.4.4 (P4.3): `run replay RUN --point ID --dry-run` (`mc.replay_report.v1`)."""

        return self.client.get(
            f"{self.prefix}/runs/{self._id(run_id)}/points/{self._id(point_id)}/replay",
            params=params,
        )

    def transcript(self, run_id: str, params: dict[str, Any], *, markdown: bool) -> httpx.Response:
        return self.client.get(
            f"{self.prefix}/runs/{self._id(run_id)}/transcript",
            params=params,
            headers={"Accept": "text/markdown" if markdown else "application/x-ndjson"},
        )

    def checkpoints(
        self, run_id: str, checkpoint_id: str | None = None, *, full: bool = False
    ) -> httpx.Response:
        """FT-B4: `run checkpoint RUN_ID --list|--get ID [--full]`."""

        base = f"{self.prefix}/runs/{self._id(run_id)}/checkpoints"
        if checkpoint_id is None:
            return self.client.get(base)
        return self.client.get(
            f"{base}/{self._id(checkpoint_id)}", params={"full": "true"} if full else None
        )

    def run_list(self, query: str | None, limit: int | None = None) -> httpx.Response:
        """FT-C4: `run list [--query FILTER]`."""

        params: dict[str, Any] = {}
        if query:
            params["query"] = query
        if limit is not None:
            params["limit"] = limit
        return self.client.get(f"{self.prefix}/runs", params=params)

    def transcript_search(self, run_id: str, text: str, limit: int) -> httpx.Response:
        """FT-C4: `run search RUN_ID --query TEXT`."""

        return self.client.get(
            f"{self.prefix}/runs/{self._id(run_id)}/transcript/search",
            params={"q": text, "limit": limit},
        )

    def frames_tail_url(self, run_id: str) -> str:
        return f"{self.prefix}/runs/{self._id(run_id)}/frames/tail"

    def subscriptions(
        self, action: str, body: dict[str, Any] | None, target: str | None
    ) -> httpx.Response:
        if action == "create":
            return self.client.post(f"{self.prefix}/subscriptions", json=body)
        if action == "list":
            return self.client.get(f"{self.prefix}/subscriptions")
        if action == "close" and target:
            return self.client.delete(f"{self.prefix}/subscriptions/{self._id(target)}")
        raise ValueError("subscribe close needs a subscription id")

    def events_path(self, mission_id: str) -> str:
        return f"{self.prefix}/missions/{self._id(mission_id)}/events"

    def inboxes(self, target: str, target_id: str) -> httpx.Response:
        """SPEC-04 §6: the caller's open coordinator inboxes over a mission or run."""

        return self.client.get(
            f"{self.prefix}/coordinator-inboxes",
            params={"target": target, "target_id": target_id},
        )

    def create_inbox(self, body: dict[str, Any]) -> httpx.Response:
        return self.client.post(f"{self.prefix}/coordinator-inboxes", json=body)

    def inbox_notifications(
        self, subscription_id: str, params: dict[str, Any], *, timeout: float
    ) -> httpx.Response:
        """Pending notifications; ``params["wait"]`` makes it the server-side long-poll."""

        return self.client.get(
            f"{self.prefix}/coordinator-inboxes/{self._id(subscription_id)}/notifications",
            params=params,
            timeout=timeout,
        )

    def ack_inbox(self, subscription_id: str, body: dict[str, Any]) -> httpx.Response:
        return self.client.post(
            f"{self.prefix}/coordinator-inboxes/{self._id(subscription_id)}/acks", json=body
        )

    def _notice(self, subscription_id: str, notification_id: str) -> str:
        return (
            f"{self.prefix}/coordinator-inboxes/{self._id(subscription_id)}"
            f"/notifications/{self._id(notification_id)}"
        )

    def observe_inbox(
        self, subscription_id: str, notification_id: str, body: dict[str, Any]
    ) -> httpx.Response:
        """WI-19: the host's wake or model-visible report for one notice."""

        return self.client.post(
            f"{self._notice(subscription_id, notification_id)}/observations", json=body
        )

    def inbox_content(
        self, subscription_id: str, notification_id: str, body: dict[str, Any]
    ) -> httpx.Response:
        return self.client.post(
            f"{self._notice(subscription_id, notification_id)}/content", json=body
        )

    def inbox_attention(self, subscription_id: str, params: dict[str, Any]) -> httpx.Response:
        return self.client.get(
            f"{self.prefix}/coordinator-inboxes/{self._id(subscription_id)}/attention",
            params=params,
        )

    def outputs_read(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """WI-19: the read-only output, fulfillment and transfer inspection routes."""

        return self.client.get(f"{self.prefix}/{path}", params=params or {})

    def knowledge_review(self, run_id: str, body: dict[str, Any]) -> httpx.Response:
        """W1 D2: an operator review of one exact KS use decision."""

        return self.client.post(
            f"{self.prefix}/runs/{self._id(run_id)}/knowledge-reviews", json=body
        )

    def quoted(self, value: str) -> str:
        return self._id(value)

    @staticmethod
    def _id(value: str) -> str:
        if not value or value in {".", ".."}:
            raise ValueError("run id must be a nonempty identifier")
        return quote(value, safe="")


def _notify_params(notify: str | None) -> dict[str, str] | None:
    """`--notify none` on a launch: skip auto-subscribing the launcher's inbox (SPEC-04 §6)."""

    return {"notify": notify} if notify else None


def read_bundle_directory(directory: Path) -> list[tuple[str, bytes]]:
    """Regular files under ``directory`` (no links), skipping ``.git`` and ``node_modules``."""
    root = directory.resolve()
    if not root.is_dir():
        raise ValueError(f"bundle directory not found: {directory}")
    files: list[tuple[str, bytes]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if skipped(relative):
            continue
        if path.is_symlink():
            raise ValueError(f"bundle directories cannot contain links: {relative}")
        if path.is_file():
            files.append((relative, path.read_bytes()))
    if not files:
        raise ValueError("bundle directory is empty")
    return files


def publish_bundle(
    client: MissionClient,
    storage: httpx.Client,
    application: str,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], int]:
    """`catalog publish`: hash, signed-URL upload of missing objects, register proposed."""
    directory = Path(args.dir)
    files = read_bundle_directory(directory)
    kind = str(args.kind)
    capability_id = getattr(args, "capability_id", None) or (
        f"{_BUNDLE_PREFIXES[kind]}.{directory.resolve().name}"
    )
    manifest = build_bundle_manifest(
        files,
        application_id=application,
        kind=kind,  # type: ignore[arg-type]
        capability_id=capability_id,
        version=getattr(args, "version", None) or "1",
        executable=frozenset(path for path, content in files if content.startswith(b"#!")),
    )
    definition = (
        strict_object(args.definition_file) if getattr(args, "definition_file", None) else {}
    )
    body = {"manifest": manifest.model_dump(mode="json"), "definition": definition}
    prepared = client.publish("prepare", body)
    if exit_status(prepared.status_code):
        return _json(prepared), exit_status(prepared.status_code)
    plan = prepared.json()
    contents = dict(files)
    prefix = str(plan["object_prefix"]) + "/"
    for upload in plan.get("uploads", []):
        relative = str(upload["path"]).removeprefix(prefix)
        url = urlsplit(str(upload["url"]))
        if (
            url.username
            or url.password
            or not (
                url.scheme == "https"
                or (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"})
            )
        ):
            raise ValueError("signed upload URLs must be HTTPS (HTTP only for loopback)")
        response = storage.put(
            str(upload["url"]),
            files={"file": (relative.rsplit("/", 1)[-1], contents[relative])},
            headers={"x-upsert": "false", "cache-control": "max-age=3600"},
        )
        if response.status_code not in {200, 201, 409}:
            return {"error": "bundle_upload_failed", "path": relative}, 5
    completed = client.publish("complete", body)
    return _json(completed), exit_status(completed.status_code)


def catalog_flags_body(args: argparse.Namespace) -> dict[str, Any]:
    """Build a search or pin body from flags (``tenant_scope`` defaults on the server)."""
    query = getattr(args, "query", None)
    if not query:
        raise ValueError("--query or --request-file is required")
    body: dict[str, Any] = {"query": query}
    if getattr(args, "kinds", None):
        body["kinds"] = list(args.kinds)
    if getattr(args, "hosts", None):
        body["host_profiles"] = list(args.hosts)
    if getattr(args, "side_effects", None):
        body["side_effect_classes"] = list(args.side_effects)
    if getattr(args, "limit", None) is not None:
        body["limit"] = args.limit
    if getattr(args, "margin", None) is not None:
        body["margin"] = args.margin
    return body


def catalog_response(
    client: MissionClient, args: argparse.Namespace, body: dict[str, Any] | None
) -> httpx.Response:
    action = args.action
    if action in {"search", "pin"} and body is None:
        body = catalog_flags_body(args)
    if action == "inspect" and body is None:
        if not getattr(args, "pin", None):
            raise ValueError("catalog inspect needs --pin or --request-file")
        return client.catalog_pin(args.pin)
    if action == "render":
        body = {"pin": args.pin, "host": args.host}
    return client.catalog(action, body)


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {"error": "non-JSON service response", "status": response.status_code}
    return payload if isinstance(payload, dict) else {"result": payload}


def subscription_body(args: argparse.Namespace) -> dict[str, Any]:
    run_id, mission_id = getattr(args, "run", None), getattr(args, "mission", None)
    if (run_id is None) == (mission_id is None):
        raise ValueError("subscribe needs exactly one of --run or --mission")
    if not getattr(args, "webhook", None) or not getattr(args, "secret_ref", None):
        raise ValueError("subscribe needs --webhook URL and --secret-ref provider:KEY")
    events = [item for item in getattr(args, "events", "").split(",") if item]
    if not events:
        raise ValueError("subscribe needs --events a,b")
    body: dict[str, Any] = {
        "target": "run" if run_id else "mission",
        "target_id": run_id or mission_id,
        "events": events,
        "channel": {"kind": "webhook", "url": args.webhook, "secret_ref": args.secret_ref},
    }
    if getattr(args, "node_keys", None):
        body["node_keys"] = [item for item in args.node_keys.split(",") if item]
    if getattr(args, "after_seq", None) is not None:
        body["after_seq"] = args.after_seq
    return body


MAILBOX_FILE_FIELDS = frozenset(
    {
        "kind",
        "boundary",
        "text",
        "content",
        "content_ref",
        "content_digest",
        "media_type",
        "size_bytes",
        "expand",
        "node_key",
        "deadline",
        "reason",
        "request_id",
    }
)


def mailbox_payload(path: str, args: argparse.Namespace) -> tuple[str, dict[str, Any], str, str]:
    """`command queue --file`: a JSON object (`text` or `content`, `boundary`, `node_key`,
    `expand`, `deadline`, `reason`, `request_id`) or any other file read as instruction text.

    Returns (kind, payload, reason, request_id). Flags override nothing the file states.
    """

    raw = Path(path).read_text(encoding="utf-8")
    spec: dict[str, Any] | None = None
    if raw.lstrip().startswith("{"):
        spec = parse_json_object(raw)
        unknown = set(spec) - MAILBOX_FILE_FIELDS
        if unknown:
            raise ValueError(f"unknown queue file fields: {sorted(unknown)}")
    spec = spec or {"text": raw}
    inject = getattr(args, "action", None) == "inject"
    default_kind = (
        "interrupt_and_inject"
        if inject
        else ("add_context" if getattr(args, "add_context", False) else "queue_instruction")
    )
    kind = str(spec.get("kind") or default_kind)
    allowed = {"interrupt_and_inject"} if inject else {"queue_instruction", "add_context"}
    if kind not in allowed:
        raise ValueError(f"this command sends {' or '.join(sorted(allowed))}")
    if "content" in spec:
        content = spec["content"]
    elif "text" in spec:
        content = {"text": spec["text"]}
        if "media_type" in spec:
            content["media_type"] = spec["media_type"]
    elif "content_ref" in spec:
        content = {
            "artifact_ref": spec["content_ref"],
            "content_digest": spec.get("content_digest"),
            "media_type": spec.get("media_type", "text/markdown"),
            "size_bytes": spec.get("size_bytes", 0),
        }
    else:
        raise ValueError("a queue file needs text, content or content_ref")
    payload: dict[str, Any] = {"content": content}
    if not inject:
        # An injected item rides the replacement turn; it has no boundary or deadline.
        payload["boundary"] = spec.get("boundary") or args.boundary
        if spec.get("deadline"):
            payload["deadline"] = spec["deadline"]
    node_key = spec.get("node_key") or args.node_key
    if node_key:
        payload["node_key"] = node_key
    if kind == "add_context":
        payload["expand"] = spec.get("expand") or args.expand
    reason = str(spec.get("reason") or args.reason)
    request_id = str(spec.get("request_id") or args.request_id or uuid.uuid4())
    return kind, payload, reason, request_id


def instruction_content(path: str) -> dict[str, Any]:
    """An instruction file: JSON `content` / `text` / `content_ref`, or plain text."""

    raw = Path(path).read_text(encoding="utf-8")
    if not raw.lstrip().startswith("{"):
        return {"text": raw}
    spec = parse_json_object(raw)
    if "content" in spec:
        content = spec["content"]
        if not isinstance(content, dict):
            raise ValueError("instruction content must be an object")
        return content
    if "text" in spec:
        return {
            "text": spec["text"],
            **({"media_type": spec["media_type"]} if "media_type" in spec else {}),
        }
    if "content_ref" in spec:
        return {
            "artifact_ref": spec["content_ref"],
            "content_digest": spec.get("content_digest"),
            "media_type": spec.get("media_type", "text/markdown"),
            "size_bytes": spec.get("size_bytes", 0),
        }
    raise ValueError("an instruction file needs text, content or content_ref")


def fork_body(args: argparse.Namespace, body: dict[str, Any] | None) -> dict[str, Any]:
    """`run fork`: the request file (if any) plus the FT-F4 flags; flags fill what it omits."""

    fork = dict(body or {})
    fork.setdefault("schema_version", "mc.runtime_fork.v1")
    fork.setdefault("request_id", args.fork_request_id or str(uuid.uuid4()))
    if args.from_snapshot:
        fork["snapshot_id"] = args.from_snapshot
    if args.instruction_file:
        fork["instruction"] = instruction_content(args.instruction_file)
    if getattr(args, "inject_file", None):
        fork["message"] = instruction_content(args.inject_file)
    if getattr(args, "at", None):
        fork["at"] = parse_fork_at(args.at)
    if getattr(args, "frontier", None):
        fork["invalidation_frontier"] = sorted(
            {*fork.get("invalidation_frontier", ()), *args.frontier}
        )
    if getattr(args, "frontier_policy", None):
        fork["frontier_policy"] = args.frontier_policy
    if args.sponsorship_ref:
        fork["sponsorship_ref"] = args.sponsorship_ref
    if args.approval_refs:
        fork["approval_refs"] = list(args.approval_refs)
    if args.reason:
        fork["reason"] = args.reason
    for item in getattr(args, "baseline_reservations", None) or ():
        # Tracing Stage 2 (F-S2-10): the derived run's baseline hold; its launch input must
        # carry the same reservation (`run_launch` refuses `budget_mismatch` otherwise).
        # Tracing Stage 3 (owner, 2026-10-22: "default to source"): without the flag the
        # server holds the source run's admitted baseline; each flag overrides one dimension.
        dimension, separator, amount = item.partition("=")
        if not separator or not dimension or not amount.strip().isdigit():
            raise ValueError("--baseline-reservation takes DIMENSION=AMOUNT")
        fork.setdefault("baseline_reservations", {})[dimension] = int(amount)
    fork.setdefault("reason", "forked by missionctl")
    if "sponsorship_ref" not in fork:
        raise ValueError("run fork needs --sponsorship-ref (or a request file naming it)")
    return fork


def parse_fork_at(text: str) -> dict[str, Any]:
    """`--at stage:S2,cycle:2` or `--at iteration:3,session:1` -> the request's `at`."""

    fields: dict[str, Any] = {}
    for part in text.split(","):
        name, _separator, value = part.strip().partition(":")
        name = name.strip().lower()
        if not _separator or not value.strip():
            raise ValueError(f"--at expects `name:value` pairs, got {part!r}")
        if name == "stage":
            fields["stage"] = value.strip()
        elif name in {"cycle", "iteration"}:
            fields[name] = int(value)
        elif name in {"session", "session_generation"}:
            fields["session_generation"] = int(value)
        else:
            raise ValueError(f"--at does not know {name!r} (stage, cycle, iteration, session)")
    if ("stage" in fields) == ("iteration" in fields):
        raise ValueError("--at names a stage with its cycle, or an iteration")
    if "stage" in fields and "cycle" not in fields:
        raise ValueError("--at stage:S needs cycle:N")
    return fields


def fork_point_fields(
    client: MissionClient, args: argparse.Namespace, body: dict[str, Any]
) -> dict[str, Any]:
    """`run fork --point ID`: the point's unit and key become the `cognitive_seed`; `at` is
    derived from the point's location when the caller gave none (P5.1)."""

    response = client.point(args.run_id, args.point_id)
    if response.status_code >= 300:
        raise ValueError(f"point lookup failed with HTTP {response.status_code}: {response.text}")
    point = _json(response)
    coordinate = point["coordinate"]
    fork = dict(body)
    # A Deep Agents checkpoint point keeps the checkpoint-key form (P5.1); every other lane's
    # point travels as the point union itself (cross-provider control, 2026-11-05).
    if coordinate["point"].get("kind", "checkpoint") == "checkpoint":
        fork["cognitive_seed"] = {
            "unit_key": coordinate["unit_key"],
            "checkpoint": coordinate["point"]["key"],
        }
    else:
        fork["cognitive_seed"] = {"unit_key": coordinate["unit_key"], "point": coordinate["point"]}
    if "at" not in fork:
        location = point.get("location") or {}
        if location.get("family") == "stage_graph":
            fork["at"] = {"stage": location["node_key"], "cycle": int(location.get("cycle") or 0)}
        elif location.get("family") == "goal_directed":
            fork["at"] = {
                "iteration": int(location["iteration"]),
                "session_generation": int(location.get("session_generation") or 1),
            }
    return fork


def queue_command_body(client: MissionClient, args: argparse.Namespace) -> dict[str, Any]:
    """Bind the queued command to the Run's current version and Generation (read first)."""

    kind, payload, reason, request_id = mailbox_payload(args.file, args)
    inspection = client.inspection(args.run_id)
    if inspection.status_code >= 300:
        raise ValueError(f"run inspection failed with HTTP {inspection.status_code}")
    current = _json(inspection)
    return {
        "schema_version": "mc.command.v1",
        "request_id": request_id,
        "expected_version": current["version"],
        "expected_generation": current["execution_generation"],
        "target": {"kind": "run", "id": args.run_id},
        "kind": kind,
        "payload": payload,
        "reason": reason,
    }


def cancel_command_body(client: MissionClient, args: argparse.Namespace) -> dict[str, Any]:
    """`command cancel RUN --urgency immediate`: a `cancel` bound to the Run's current version
    and Generation (read first). `immediate` persists the Stop Fence before the cancel path
    (SPEC-06 scenario 3); `normal` cancels at the next safe boundary."""

    inspection = client.inspection(args.run_id)
    if inspection.status_code >= 300:
        raise ValueError(f"run inspection failed with HTTP {inspection.status_code}")
    current = _json(inspection)
    request_id = getattr(args, "request_id", None)
    return {
        "schema_version": "mc.command.v1",
        "request_id": str(UUID(request_id) if request_id else uuid4()),
        "expected_version": current["version"],
        "expected_generation": current["execution_generation"],
        "target": {"kind": "run", "id": args.run_id},
        "kind": "cancel",
        "payload": {"urgency": args.urgency},
        "reason": args.reason,
    }


def watch_events(transport: httpx.Client, client: MissionClient, args: argparse.Namespace) -> int:
    """Print each mission event as one JSON line; exit 6 on resync_required."""

    params: dict[str, Any] = {}
    if getattr(args, "after_seq", None) is not None:
        params["after_seq"] = args.after_seq
    if getattr(args, "types", None):
        params["types"] = args.types
    limit = getattr(args, "max_events", None)
    seen = 0
    with transport.stream(
        "GET", client.events_path(args.mission_id), params=params, timeout=None
    ) as response:
        if response.status_code >= 300:
            response.read()
            print(json.dumps({"error": "events_unavailable", "status": response.status_code}))
            return exit_status(response.status_code)
        event = ""
        for line in response.iter_lines():
            if line.startswith("event: "):
                event = line[len("event: ") :]
            elif line.startswith("data: ") and event in {"mission_event", "resync_required"}:
                print(line[len("data: ") :], flush=True)
                if event == "resync_required":
                    return 6
                seen += 1
                if limit is not None and seen >= limit:
                    return 0
    return 0


WAIT_POLL_SECONDS = 0.5


def inspection_wait_state(result: object) -> tuple[object, ...]:
    """What `run inspect --wait` watches: lifecycle, phase and the terminal outcome."""

    if not isinstance(result, dict):
        return (None, None, None)
    return (result.get("lifecycle"), result.get("phase"), result.get("execution_outcome"))


TRANSCRIPT_NEXT_CURSOR = "x-transcript-next-cursor"
TRANSCRIPT_HAS_MORE = "x-transcript-has-more"
DEFAULT_FOLLOW_SECONDS = 60.0
# Tracing Stage 3 (R4-F11, R4-F12): the routes' page caps; the CLI pages up to `--limit`.
TRANSCRIPT_PAGE_LIMIT = 5_000
POINTS_PAGE_LIMIT = 500


def _transcript_params(
    args: argparse.Namespace, since: str | None, *, limit: int | None = None
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": min(limit or args.limit, TRANSCRIPT_PAGE_LIMIT)}
    # 1.4.4 (P4.2): `--by LEVEL`, `--point ID` and `--unit KEY` travel as query parameters;
    # the server renders one JSONL line (or Markdown heading) per group when `by` is set.
    for name in ("activation", "node", "kinds", "subordinate", "by", "point", "unit"):
        value = getattr(args, name, None)
        if value:
            params[name] = value
    if since:
        params["since"] = since
    if args.canonical_only:
        params["canonical_only"] = "true"
    if args.full:
        params["full"] = "true"
    return params


def _transcript_error(response: httpx.Response) -> int:
    try:
        detail = response.json().get("detail", {})
    except ValueError:
        detail = {}
    code = detail.get("code") if isinstance(detail, dict) else None
    print(json.dumps({"error": code or "transcript_failed", "status": response.status_code}))
    if code == "CURSOR_EXPIRED":
        return 2
    return exit_status(response.status_code) or 5


def _write_utf8(text: str) -> None:
    """Transcripts carry ✓ and other non-ASCII text; never depend on the console code page."""

    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    else:
        sys.stdout.write(text)
        sys.stdout.flush()


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError:
        return {"error": "non-JSON service response", "status": response.status_code}
    return value if isinstance(value, dict) else {"result": value}


def run_list(client: MissionClient, args: argparse.Namespace) -> int:
    """`run list`: one line per run (or the JSON page with `--json`)."""

    response = client.run_list(getattr(args, "query", None), getattr(args, "limit", None))
    result = _json_object(response)
    status = exit_status(response.status_code)
    if status or getattr(args, "json", False):
        print(json.dumps(result, allow_nan=False))
        return status
    rows: list[dict[str, Any]] = [row for row in result.get("rows", []) if isinstance(row, dict)]
    for row in rows:
        print(
            "\t".join(
                (
                    str(row.get("run_id")),
                    str(row.get("lifecycle")),
                    str(row.get("terminal_outcome") or "-"),
                    ",".join(row.get("lanes") or ()) or "-",
                    ",".join(row.get("phases") or ()) or "-",
                    str(row.get("mission_id") or "-"),
                )
            )
        )
    dropped = result.get("dropped_missing_from_ledger") or 0
    if dropped:
        print(json.dumps({"dropped_missing_from_ledger": dropped}), file=sys.stderr)
    return 0


def run_search(client: MissionClient, args: argparse.Namespace) -> int:
    """`run search RUN_ID --query TEXT`: ranked entries with the cursor `--since` opens."""

    response = client.transcript_search(args.run_id, args.query, args.limit)
    result = _json_object(response)
    status = exit_status(response.status_code)
    if status or getattr(args, "json", False):
        print(json.dumps(result, allow_nan=False, ensure_ascii=False))
        return status
    hits: list[dict[str, Any]] = [hit for hit in result.get("hits", []) if isinstance(hit, dict)]
    lines = [
        "\t".join(
            (
                f"{hit.get('rank', 0):.4f}",
                str(hit.get("open_cursor") or "-"),
                str(hit["entry"].get("cursor")),
                str(hit["entry"].get("kind")),
                str(hit["entry"].get("title")),
            )
        )
        for hit in hits
    ]
    _write_utf8("".join(line + "\n" for line in lines))
    return 0


def run_points(client: MissionClient, args: argparse.Namespace) -> int:
    """`run points`: up to `--limit` `mc.cognition_point.v1` rows as one JSON page with the
    next cursor, read in pages of at most the route's 500 (Tracing Stage 3, R4-F12);
    `--reconcile` re-derives the run's missing points instead and prints the outcome."""

    if getattr(args, "reconcile", False):
        body: dict[str, Any] = {}
        if getattr(args, "unit_key", None) is not None:
            body["unit_key"] = args.unit_key
        response = client.reconcile_points(args.run_id, body)
        print(json.dumps(_json_object(response), indent=2))
        return exit_status(response.status_code)
    params: dict[str, Any] = {}
    for name, key in (
        ("unit_key", "unit_key"),
        ("generation", "generation"),
        ("node", "node"),
        ("iteration", "iteration"),
        ("cycle", "cycle"),
        ("session_generation", "session_generation"),
        ("kind", "kind"),
        ("role", "role"),
        ("cursor", "cursor"),
    ):
        value = getattr(args, name, None)
        if value is not None:
            params[key] = value
    if args.seedable:
        params["seedable"] = "true"
    remaining = args.limit
    entries: list[Any] = []
    while True:
        params["limit"] = max(1, min(remaining, POINTS_PAGE_LIMIT))
        response = client.points(args.run_id, params)
        page = _json_object(response)
        if exit_status(response.status_code):
            print(json.dumps(page, indent=2))
            return exit_status(response.status_code)
        listed = page.get("entries")
        rows: list[Any] = listed if isinstance(listed, list) else []
        entries.extend(rows)
        remaining -= len(rows)
        cursor = page.get("next_cursor")
        if not cursor or not rows or remaining <= 0:
            break
        params["cursor"] = cursor
    print(json.dumps({**page, "entries": entries}, indent=2))
    return 0


def run_state_as_of(client: MissionClient, args: argparse.Namespace) -> int:
    """`run state-as-of`: the graph state at one point (`mc.state_as_of.v1`)."""

    response = client.state_as_of(args.run_id, args.point_id)
    _write_utf8(json.dumps(_json_object(response), indent=2, ensure_ascii=False) + "\n")
    return exit_status(response.status_code)


def run_closure(client: MissionClient, args: argparse.Namespace) -> int:
    """`run closure RUN --point ID` (OVE-204 slice 5): the point's Workspace Closure; with
    `--list`, every closure of the run (oldest first; the newest is the mission end's).
    A promoted body's `body_ref` downloads with `run artifact RUN REF --out FILE`."""

    if args.list_closures:
        response = client.closures(args.run_id)
    elif args.point_id:
        response = client.closure(args.run_id, args.point_id)
    else:
        print(json.dumps({"error": "run closure needs --point ID or --list"}), file=sys.stderr)
        return 2
    _write_utf8(json.dumps(_json_object(response), indent=2, ensure_ascii=False) + "\n")
    return exit_status(response.status_code)


def run_artifact(client: MissionClient, args: argparse.Namespace) -> int:
    """`run artifact RUN REF --out FILE` (1.4.4, TR-D3): write the verified bytes of a
    `frame-body://` or `artifact://` reference to FILE and print its receipt."""

    response = client.artifact(args.run_id, args.ref)
    if exit_status(response.status_code):
        print(json.dumps(_json_object(response), indent=2))
        return exit_status(response.status_code)
    content = response.content
    Path(args.out).write_bytes(content)
    receipt = {
        "ref": args.ref,
        "bytes": len(content),
        "media_type": response.headers.get("content-type", "application/octet-stream"),
        "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
        "out": str(args.out),
    }
    print(json.dumps(receipt, indent=2))
    return 0


def run_replay(client: MissionClient, args: argparse.Namespace) -> int:
    """`run replay RUN --point ID --dry-run [--call INDEX] [--include-batch] [--out FILE]`
    (1.4.4, P4.3): the step's model input reconstructed from the Transcript and compared
    with the recorded digests (`mc.replay_report.v1`). A paid replay is not available."""

    if not getattr(args, "dry_run", False):
        print(json.dumps({"error": "paid_replay_not_available"}))
        return 2
    params: dict[str, Any] = {}
    if getattr(args, "call_index", None) is not None:
        params["call_index"] = args.call_index
    if getattr(args, "include_batch", False) or getattr(args, "out", None):
        params["include_batch"] = "true"
    response = client.replay(args.run_id, args.point_id, params)
    report = _json_object(response)
    out = getattr(args, "out", None)
    if out and not exit_status(response.status_code):
        Path(out).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        report = {key: value for key, value in report.items() if key != "batch"}
        report["out"] = str(out)
    _write_utf8(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return exit_status(response.status_code)


def _without_markdown_header(text: str) -> str:
    """A later page's Markdown without the title and legend the first page printed."""

    lines = text.split("\n")
    for index, line in enumerate(lines):
        if line.startswith("_Legend:"):
            return "\n".join(lines[index + 1 :])
    return text


def run_transcript(client: MissionClient, args: argparse.Namespace, wait: float | None) -> int:
    """`run transcript`: print entries (JSONL or Markdown); `--follow` tails new entries.

    Tracing Stage 3 (R4-F11): a page the server marks `X-Transcript-Has-More` is followed by
    the next one, up to `--limit` entries in all (pages of at most the route's 5 000); with
    `--follow` a page that has more is fetched again at once instead of after the poll.
    """

    markdown = args.format == "md"
    since = args.since
    deadline = time.monotonic() + (wait or DEFAULT_FOLLOW_SECONDS)
    first = True
    unread = args.limit
    while True:
        response = client.transcript(
            args.run_id, _transcript_params(args, since, limit=unread), markdown=markdown
        )
        if response.status_code != 200:
            return _transcript_error(response)
        text = response.text
        next_cursor = response.headers.get(TRANSCRIPT_NEXT_CURSOR) or since
        has_more = response.headers.get(TRANSCRIPT_HAS_MORE) == "true" and next_cursor != since
        # Follow prints only pages that advanced the cursor (Markdown always has a header).
        if text and (first or next_cursor != since):
            _write_utf8(text if first or not markdown else _without_markdown_header(text))
        first = False
        since = next_cursor
        if not args.follow:
            # The server fills a page before it says there is more.
            unread -= min(unread, TRANSCRIPT_PAGE_LIMIT)
            if has_more and unread > 0:
                continue
            return 0
        if has_more:
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(json.dumps({"error": "wait_timeout", "next_cursor": since}), file=sys.stderr)
            return 6
        time.sleep(min(1.0, remaining))


def run_frames_tail(client: MissionClient, args: argparse.Namespace, wait: float | None) -> int:
    """`run frames --tail`: the non-canonical SSE tail, printed as JSON lines."""

    seconds = wait or DEFAULT_FOLLOW_SECONDS
    params: dict[str, Any] = {"timeout": seconds}
    if args.after:
        params["after"] = args.after
    with client.client.stream(
        "GET", client.frames_tail_url(args.run_id), params=params, timeout=seconds + 30
    ) as response:
        if response.status_code != 200:
            response.read()
            return _transcript_error(response)
        event = ""
        for line in response.iter_lines():
            if line.startswith("event: "):
                event = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data = json.loads(line.removeprefix("data: "))
                print(json.dumps({"event": event, **data}, ensure_ascii=False))
                if event == "end":
                    return 6 if data.get("reason") == "timeout" and args.until_end else 0
    return 0


def contract_schema_texts() -> dict[str, str]:
    """Generated JSON Schemas committed under ``src/mission_control/contracts/schemas``."""

    from mission_control.domain.authoring.manifest import (
        MANIFEST_SCHEMA_ID,
        manifest_json_schema_text,
    )
    from mission_control.domain.composition.chain import chain_contract_schemas

    texts = {MANIFEST_SCHEMA_ID: manifest_json_schema_text()}
    for name, schema in chain_contract_schemas().items():
        texts[name] = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    return texts


def mission_local(args: argparse.Namespace) -> int:
    """Manifest verbs that need no service: JSON Schema export and the structural compile.

    ``compile`` validates shape, inheritance and chain links offline and persists nothing;
    catalog search-to-pin resolution (FT-E2) is reported as deferred.
    """

    try:
        if args.action == "schema":
            text = contract_schema_texts()[getattr(args, "contract", "mc.mission_manifest.v1")]
            if getattr(args, "out", None):
                Path(args.out).write_text(text, encoding="utf-8", newline="\n")
            else:
                sys.stdout.write(text)
            return 0
        from mission_control.application.chains.service import ManifestStructureService

        report = ManifestStructureService().compile(Path(args.file).read_text(encoding="utf-8"))
        if getattr(args, "json", False):
            print(report.model_dump_json(by_alias=True))
        else:
            print(json.dumps(report.model_dump(mode="json", by_alias=True), indent=2))
        return 0 if report.ok else 2
    except OSError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


def _add_notify(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--notify",
        choices=("inbox", "none"),
        help="launcher inbox (default inbox: `missionctl wait --run` wakes you)",
    )


def lane_async_graphs(args: argparse.Namespace) -> int:
    """`lane async-graphs`: the served Agent Server graphs as a launch-bindings block.

    Mints a scope claim from the deployment credential (named by environment variable, never
    printed), reads `GET /belllabs/async-subagents/served-graphs`, and prints a
    `deep_agents_async_graphs` block keyed by the subagent profile names given with
    `--name` (default: one entry per served graph, keyed by its graph id), so the operator
    pastes exact identities into `mc.manifest_launch_bindings` instead of copying digests.
    """

    from mission_control.adapters.agent_server.async_subagents.auth import (
        SCOPE_HEADER,
        mint_scope_claim,
    )

    secret = os.environ.get(args.credential_env, "")
    if not secret:
        print(
            json.dumps({"error": f"{args.credential_env} is not set in this environment"}),
            file=sys.stderr,
        )
        return 2
    claim = mint_scope_claim(secret, args.scope)
    url = args.agent_server.rstrip("/") + "/belllabs/async-subagents/served-graphs"
    headers = {
        "Authorization": f"Bearer {claim}",
        SCOPE_HEADER.decode("ascii"): args.scope,
        "x-auth-scheme": "langsmith",
    }
    response = httpx.get(url, headers=headers, timeout=30.0)
    if response.status_code != 200:
        print(
            json.dumps({"error": response.status_code, "body": response.text[:500]}),
            file=sys.stderr,
        )
        return 1
    graphs = response.json().get("graphs", [])
    selected = getattr(args, "graph", None)
    if selected:
        # OVE-184: the server may serve the sealed-child graph beside a static one.
        graphs = [graph for graph in graphs if graph.get("graph_id") == selected]
    budget: dict[str, int] = {}
    for item in getattr(args, "budget", None) or ():
        dimension, _, amount = item.partition("=")
        budget[dimension] = int(amount)
    names = getattr(args, "names", None) or [graph["graph_id"] for graph in graphs]
    block = {}
    for name, graph in zip(names, graphs, strict=False):
        block[name] = {
            "graph_id": graph["graph_id"],
            "graph_revision": graph["graph_revision"],
            "graph_binding_digest": graph["graph_binding_digest"],
            "agent_protocol_url": args.agent_server.rstrip("/"),
            "deployment_credential_ref": f"environment:{args.credential_env}",
            "objective_schema_ref": "schema:async-objective@1",
            "result_schema_ref": "schema:async-result@1",
            "result_admission_policy_ref": args.policy,
            "default_budget_limits": budget or {"tokens.total": 20_000},
        }
        if graph.get("binding_mode") == "sealed_child":
            # The child's own sealed binding reaches the server per run (OVE-184).
            block[name]["binding_mode"] = "sealed_child"
    _write_utf8(json.dumps({"deep_agents_async_graphs": block, "served": graphs}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    # Common options at every depth allow flags before or after subcommands.
    common = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    common.add_argument("--application")
    common.add_argument("--url")
    common.add_argument("--json", action="store_true")
    common.add_argument("--wait", type=float)
    parser = argparse.ArgumentParser(prog="missionctl", parents=[common])
    groups = parser.add_subparsers(dest="group", required=True)
    add_token_parser(groups)
    preflight = groups.add_parser("preflight", parents=[common])
    preflight.add_argument("file")
    preflight.set_defaults(action="preflight")
    add_setup_parsers(groups, common)
    run = groups.add_parser("run", parents=[common])
    run_commands = run.add_subparsers(dest="action", required=True)
    inspect = run_commands.add_parser("inspect", parents=[common])
    inspect.add_argument("run_id")
    admission = run_commands.add_parser("admit", parents=[common])
    admission.add_argument("--request-file", required=True)
    for action in ("snapshot", "reconcile", "start"):
        operation = run_commands.add_parser(action, parents=[common])
        operation.add_argument("run_id")
        operation.add_argument("--request-file", required=True)
        if action == "start":
            _add_notify(operation)
    # FT-F4: fork from a Snapshot (default: the latest safe one) with a queued instruction.
    fork = run_commands.add_parser("fork", parents=[common])
    fork.add_argument("run_id")
    fork.add_argument("--request-file")
    fork.add_argument("--from-snapshot", dest="from_snapshot")
    fork.add_argument("--instruction-file", dest="instruction_file")
    # 1.4.4 (P5.1): the precise fork.
    fork.add_argument(
        "--at",
        help="the position to resume at: `stage:S2,cycle:2` or `iteration:3[,session:1]` "
        "(derived from --point when omitted)",
    )
    fork.add_argument(
        "--point", dest="point_id", help="the cognition point to seed from (its unit and key)"
    )
    fork.add_argument(
        "--inject",
        dest="inject_file",
        help="the message file (text or JSON content) delivered to the seed head, or to the "
        "mailbox without a seed",
    )
    fork.add_argument(
        "--frontier", action="append", dest="frontier", help="an invalidated stage (repeatable)"
    )
    fork.add_argument("--frontier-policy", dest="frontier_policy", choices=("close", "strict"))
    fork.add_argument("--sponsorship-ref", dest="sponsorship_ref")
    fork.add_argument("--approval-ref", dest="approval_refs", action="append")
    fork.add_argument("--reason")
    fork.add_argument("--request-id", dest="fork_request_id")
    fork.add_argument(
        "--baseline-reservation",
        dest="baseline_reservations",
        action="append",
        help=(
            "override one dimension of the derived run's baseline hold, DIMENSION=AMOUNT "
            "(repeatable); by default the fork holds the source run's admitted baseline"
        ),
    )
    # SPEC-03 (C3): the run transcript and the non-canonical frame tail.
    transcript = run_commands.add_parser("transcript", parents=[common])
    transcript.add_argument("run_id")
    transcript.add_argument("--format", choices=("jsonl", "md"), default="jsonl")
    transcript.add_argument("--since")
    transcript.add_argument("--activation")
    transcript.add_argument("--node")
    transcript.add_argument("--kinds", help="comma-separated entry kinds")
    transcript.add_argument("--canonical-only", action="store_true")
    transcript.add_argument("--subordinate")
    transcript.add_argument("--limit", type=int, default=500)
    transcript.add_argument("--follow", action="store_true")
    transcript.add_argument("--full", action="store_true")
    # 1.4.4 (P4.2): grouping levels and the point/unit restrictions.
    transcript.add_argument(
        "--by",
        choices=("step", "turn", "attempt", "stage", "iteration", "mission"),
        help="group entries at one level (one JSONL line or Markdown heading per group)",
    )
    transcript.add_argument("--point", help="only this point's entries and its children's")
    transcript.add_argument("--unit", help="only this unit key's entries")
    frames = run_commands.add_parser("frames", parents=[common])
    frames.add_argument("run_id")
    frames.add_argument("--tail", action="store_true", required=True)
    frames.add_argument("--after")
    frames.add_argument("--until-end", action="store_true", help="exit 6 when the tail times out")
    # SPEC-03 (C4): run list over Temporal Visibility and transcript search.
    listing_runs = run_commands.add_parser("list", parents=[common])
    listing_runs.add_argument("--query", help="e.g. \"lane='deep_agents' AND phase='executing'\"")
    listing_runs.add_argument("--limit", type=int)
    search = run_commands.add_parser("search", parents=[common])
    search.add_argument("run_id")
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=20)
    # SPEC-02 (B4): sealed continuation checkpoints of a run.
    checkpoint = run_commands.add_parser("checkpoint", parents=[common])
    checkpoint.add_argument("run_id")
    checkpoint_mode = checkpoint.add_mutually_exclusive_group(required=True)
    checkpoint_mode.add_argument("--list", action="store_true", dest="list_checkpoints")
    checkpoint_mode.add_argument("--get", dest="checkpoint_id")
    checkpoint.add_argument("--full", action="store_true", help="bodies above 4 KiB unredacted")
    # P1 turn 4: the cognition coordinate (points of a run, state as of one point).
    points = run_commands.add_parser("points", parents=[common])
    points.add_argument("run_id")
    points.add_argument("--unit-key", dest="unit_key")
    points.add_argument("--generation", type=int)
    points.add_argument("--node", help="stage id or goal role (executor, verifier)")
    points.add_argument("--iteration", type=int, help="goal iteration or workflow cycle")
    points.add_argument("--cycle", type=int, help="stage cycle ordinal")
    points.add_argument("--session-generation", dest="session_generation", type=int)
    points.add_argument(
        "--kind", choices=("checkpoint", "session_cursor", "thread_item", "workspace_snapshot")
    )
    points.add_argument("--role")
    points.add_argument("--seedable", action="store_true")
    points.add_argument("--limit", type=int, default=100)
    points.add_argument("--cursor")
    points.add_argument(
        "--reconcile",
        action="store_true",
        help="re-derive the run's missing points and frame ranges (optionally one --unit-key)",
    )
    state_as_of = run_commands.add_parser("state-as-of", parents=[common])
    state_as_of.add_argument("run_id")
    state_as_of.add_argument("--point", required=True, dest="point_id")
    # 1.4.4 (tracing Stage 1, WP-TR-3): artifact download and the dry-run replay.
    artifact = run_commands.add_parser("artifact", parents=[common])
    artifact.add_argument("run_id")
    artifact.add_argument("ref", help="a frame-body://, closure-body:// or artifact:// reference")
    # OVE-204 slice 5: the Workspace Closure of a point, or every closure of the run.
    closure = run_commands.add_parser("closure", parents=[common])
    closure.add_argument("run_id")
    closure.add_argument("--point", dest="point_id", default=None)
    closure.add_argument("--list", dest="list_closures", action="store_true")
    artifact.add_argument("--out", required=True, help="file that receives the bytes")
    replay = run_commands.add_parser("replay", parents=[common])
    replay.add_argument("run_id")
    replay.add_argument("--point", required=True, dest="point_id")
    replay.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="reconstruct the step's model input from the Transcript (required; no model call)",
    )
    replay.add_argument("--call", type=int, dest="call_index", help="model call index in the step")
    replay.add_argument("--include-batch", action="store_true", dest="include_batch")
    replay.add_argument("--out", help="file that receives the whole report, batch included")
    command = groups.add_parser("command", parents=[common])
    commands = command.add_subparsers(dest="action", required=True)
    send = commands.add_parser("send", parents=[common])
    send.add_argument("run_id")
    send.add_argument("--request-file", required=True)
    listing = commands.add_parser("list", parents=[common])
    listing.add_argument("run_id")
    # FT-F1: queue an instruction (or, with --add-context, context) for the next boundary.
    queue = commands.add_parser("queue", parents=[common])
    queue.add_argument("run_id")
    queue.add_argument("--file", required=True)
    queue.add_argument("--add-context", action="store_true")
    queue.add_argument("--boundary", choices=("next_turn", "next_iteration"), default="next_turn")
    queue.add_argument("--node-key")
    queue.add_argument(
        "--expand", choices=("inline", "reference", "materialize", "auto"), default="auto"
    )
    queue.add_argument("--reason", default="queued by missionctl")
    queue.add_argument("--request-id")
    # FT-F2: interrupt the running turn and continue with the injected content.
    inject = commands.add_parser("inject", parents=[common])
    inject.add_argument("run_id")
    inject.add_argument("--file", required=True)
    inject.add_argument("--node-key")
    inject.add_argument("--reason", default="injected by missionctl")
    inject.add_argument("--request-id")
    # SPEC-06 scenario 3: cancel now (Stop Fence first) or at the next safe boundary.
    cancel = commands.add_parser("cancel", parents=[common])
    cancel.add_argument("run_id")
    cancel.add_argument("--urgency", choices=("normal", "immediate"), default="normal")
    cancel.add_argument("--reason", default="cancelled by missionctl")
    cancel.add_argument("--request-id")
    mission = groups.add_parser("mission", parents=[common])
    mission_commands = mission.add_subparsers(dest="action", required=True)
    schema = mission_commands.add_parser("schema", parents=[common])
    schema.add_argument("--out")
    schema.add_argument(
        "--contract",
        choices=("mc.mission_manifest.v1", "mc.chain.v1", "mc.chain_link.v1"),
        default="mc.mission_manifest.v1",
    )
    compile_ = mission_commands.add_parser("compile", parents=[common])
    compile_.add_argument("file")
    compile_.add_argument(
        "--offline",
        action="store_true",
        help="structure-only compile without the service (no catalog resolution)",
    )
    submit = mission_commands.add_parser("submit", parents=[common])
    submit.add_argument("file")
    submit.add_argument("--request-id", dest="request_id_arg")
    mission_start = mission_commands.add_parser("start", parents=[common])
    mission_start.add_argument("run_id")
    mission_start.add_argument(
        "--request-file", help="family input JSON (when the deployment does not author it)"
    )
    _add_notify(mission_start)
    # FT-D2: Mission Chains (read-only; members are cancelled individually in v1).
    chain = groups.add_parser("chain", parents=[common])
    chain_commands = chain.add_subparsers(dest="action", required=True)
    chain_inspect = chain_commands.add_parser("inspect", parents=[common])
    chain_inspect.add_argument("chain_id")
    subscribe = groups.add_parser("subscribe", parents=[common])
    subscribe.add_argument("action", nargs="?", choices=("create", "list", "close"))
    subscribe.add_argument("subscription_id", nargs="?")
    subscribe.add_argument("--run")
    subscribe.add_argument("--mission")
    subscribe.add_argument("--webhook")
    subscribe.add_argument("--secret-ref")
    subscribe.add_argument("--events", default="")
    subscribe.add_argument("--node-keys")
    subscribe.add_argument("--after-seq", type=int)
    events = groups.add_parser("events", parents=[common])
    events_commands = events.add_subparsers(dest="action", required=True)
    watch = events_commands.add_parser("watch", parents=[common])
    watch.add_argument("mission_id")
    watch.add_argument("--after-seq", type=int)
    watch.add_argument("--types")
    watch.add_argument("--max-events", type=int)
    catalog = groups.add_parser("catalog", parents=[common])
    catalog_commands = catalog.add_subparsers(dest="action", required=True)
    catalog_commands.add_parser("list", parents=[common])
    for action in ("resolve", "discover", "components"):
        operation = catalog_commands.add_parser(action, parents=[common])
        operation.add_argument("--request-file", required=True)
    lane = groups.add_parser("lane", parents=[common])
    lane_commands = lane.add_subparsers(dest="action", required=True)
    lane_commands.add_parser("list", parents=[common])
    lane_describe = lane_commands.add_parser("describe", parents=[common])
    lane_describe.add_argument("lane_profile")
    # OC-R6 (OC-D201): choose a model profile; the lane must route its vendor.
    model = groups.add_parser("model", parents=[common])
    model_commands = model.add_subparsers(dest="action", required=True)
    model_commands.add_parser("list", parents=[common])
    model_describe = model_commands.add_parser("describe", parents=[common])
    model_describe.add_argument("model_profile")
    # P1 WP-S2: read the served Agent Server graphs with a scope claim and print the
    # `deep_agents_async_graphs` block the launch bindings need (no hand-copied digests).
    async_graphs = lane_commands.add_parser("async-graphs", parents=[common])
    async_graphs.add_argument("--agent-server", required=True, dest="agent_server")
    async_graphs.add_argument("--scope", required=True)
    async_graphs.add_argument("--name", action="append", dest="names")
    async_graphs.add_argument(
        "--credential-env", default="BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN", dest="credential_env"
    )
    async_graphs.add_argument(
        "--policy", default="policy:async-result:technical-child@1", dest="policy"
    )
    async_graphs.add_argument("--budget", action="append", dest="budget")
    async_graphs.add_argument("--graph", dest="graph")
    # FT-A8: search and pin take flags (or a request file); inspect takes --pin or a file.
    for action in ("search", "pin"):
        operation = catalog_commands.add_parser(action, parents=[common])
        operation.add_argument("--request-file")
        operation.add_argument("--query")
        operation.add_argument("--kind", action="append", dest="kinds")
        operation.add_argument("--host", action="append", dest="hosts")
        operation.add_argument("--side-effect", action="append", dest="side_effects")
        operation.add_argument("--limit", type=int)
        if action == "pin":
            operation.add_argument("--margin", type=float)
    inspect_catalog = catalog_commands.add_parser("inspect", parents=[common])
    inspect_catalog.add_argument("--request-file")
    inspect_catalog.add_argument("--pin")
    render = catalog_commands.add_parser("render", parents=[common])
    render.add_argument("--pin", required=True)
    render.add_argument("--host", required=True)
    publish = catalog_commands.add_parser("publish", parents=[common])
    publish.add_argument("--dir", required=True)
    publish.add_argument(
        "--kind", required=True, choices=("skill_bundle", "hook_script", "subagent_profile")
    )
    publish.add_argument("--capability-id", dest="capability_id")
    publish.add_argument("--version")
    publish.add_argument("--definition-file", dest="definition_file")
    # SPEC-04 §6: wake channels over the coordinator inbox.
    add_wait_parsers(groups, common)
    # WI-19: exact output, fulfillment and transfer inspection.
    add_output_parsers(groups, common)
    # W1 D2: an operator review of an exact KS use decision.
    add_knowledge_parsers(groups, common)
    # The Selection Workspace: one faceted search; a read-only check of a draft selection.
    add_selection_parsers(groups, common)
    args = parser.parse_args(argv)
    if args.group == "token":
        return run_token(args)
    if args.group == "mission" and (args.action == "schema" or getattr(args, "offline", False)):
        return mission_local(args)
    if args.group == "lane" and args.action == "async-graphs":
        return lane_async_graphs(args)
    application = getattr(args, "application", os.environ.get("MISSION_CONTROL_APPLICATION_ID"))
    base_url = getattr(args, "url", os.environ.get("MISSION_CONTROL_URL", "http://127.0.0.1:8000"))
    token = os.environ.get("MISSION_CONTROL_TOKEN")
    deadline_seconds = getattr(args, "wait", None)
    try:
        if not application or not token:
            raise ValueError("application and MISSION_CONTROL_TOKEN are required")
        parsed_url = urlsplit(base_url)
        if parsed_url.username or parsed_url.password or parsed_url.query or parsed_url.fragment:
            raise ValueError("API URL must not contain credentials, query, or fragment")
        if parsed_url.scheme != "https" and not (
            parsed_url.scheme == "http" and parsed_url.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("API URL must use HTTPS (HTTP is allowed only for loopback)")
        if deadline_seconds is not None and not 0 < deadline_seconds <= 3600:
            raise ValueError("--wait must be greater than zero and at most 3600 seconds")
        if deadline_seconds is not None and not (
            (args.group == "run" and args.action in {"inspect", "transcript", "frames"})
            or (args.group == "chain" and args.action == "inspect")
            or (args.group == "mission" and args.action == "start")
            or args.group == "wait"
        ):
            raise ValueError(
                "--wait is supported on wait, run inspect, transcript, frames and chain "
                "inspect; command admission is not completion"
            )
        body = strict_object(args.request_file) if getattr(args, "request_file", None) else None
        if args.group == "run" and args.action == "fork":
            body = fork_body(args, body)
        if args.group == "catalog" and args.action == "publish":
            with (
                httpx.Client(
                    base_url=base_url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=30,
                    follow_redirects=False,
                ) as transport,
                # Storage uploads carry only the signed URL token, never the API bearer.
                httpx.Client(timeout=120, follow_redirects=False) as storage,
            ):
                result, status = publish_bundle(
                    MissionClient(transport, application), storage, application, args
                )
            print(json.dumps(result, allow_nan=False))
            return status
        if args.group == "subscribe":
            args.action = args.action or "create"
        if args.group == "preflight":
            body = {"manifest_yaml": Path(args.file).read_text(encoding="utf-8")}
        if args.group == "mission" and args.action == "compile":
            body = {"manifest_yaml": Path(args.file).read_text(encoding="utf-8")}
        if args.group == "mission" and args.action == "submit":
            body = {
                "manifest_yaml": Path(args.file).read_text(encoding="utf-8"),
                "request_id": str(UUID(args.request_id_arg) if args.request_id_arg else uuid4()),
            }
        if args.group == "mission" and args.action == "start":
            body = {"run_id": args.run_id, "family_input": body}
        if args.group == "subscribe" and args.action == "create":
            body = subscription_body(args)
        with httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
            follow_redirects=False,
        ) as transport:
            client = MissionClient(transport, application)
            if args.group == "run" and args.action == "fork" and getattr(args, "point_id", None):
                body = fork_point_fields(client, args, body or {})
            if args.group in {"setup", "prereq"}:
                return run_setup(client, args, application=application, url=base_url)
            if args.group == "command" and args.action in {"queue", "inject"}:
                body = queue_command_body(client, args)
            if args.group == "command" and args.action == "cancel":
                body = cancel_command_body(client, args)
            if args.group == "run" and args.action == "transcript":
                return run_transcript(client, args, deadline_seconds)
            if args.group == "run" and args.action == "points":
                return run_points(client, args)
            if args.group == "run" and args.action == "state-as-of":
                return run_state_as_of(client, args)
            if args.group == "run" and args.action == "artifact":
                return run_artifact(client, args)
            if args.group == "run" and args.action == "closure":
                return run_closure(client, args)
            if args.group == "run" and args.action == "replay":
                return run_replay(client, args)
            if args.group == "run" and args.action == "frames":
                return run_frames_tail(client, args, deadline_seconds)
            if args.group == "run" and args.action == "list":
                return run_list(client, args)
            if args.group == "run" and args.action == "search":
                return run_search(client, args)
            if args.group == "wait":
                return run_wait(client, args, deadline_seconds)
            if args.group == "inbox":
                return run_inbox(client, args)
            if args.group == "outputs":
                return run_outputs(client, args)
            if args.group == "knowledge":
                return run_knowledge(client, args)
            if args.group in {"search", "workspace"}:
                return run_selection(client, args)
            deadline = time.monotonic() + (deadline_seconds or 0)
            started = False
            # FT-F6: `run inspect --wait` returns early on a lifecycle, phase or terminal
            # change from the first observation (polled well under a second apart).
            initial: tuple[object, ...] | None = None
            while True:
                if deadline_seconds is not None:
                    transport.timeout = httpx.Timeout(
                        max(0.001, min(30, deadline - time.monotonic()))
                    )
                if args.group == "events":
                    return watch_events(transport, client, args)
                if args.group == "catalog":
                    response = catalog_response(client, args, body)
                elif args.group == "lane":
                    response = client.lanes(getattr(args, "lane_profile", None))
                elif args.group == "model":
                    response = client.models(getattr(args, "model_profile", None))
                elif args.group == "subscribe":
                    response = client.subscriptions(
                        args.action, body, getattr(args, "subscription_id", None)
                    )
                elif args.group == "run" and args.action == "checkpoint":
                    response = client.checkpoints(
                        args.run_id,
                        getattr(args, "checkpoint_id", None),
                        full=getattr(args, "full", False),
                    )
                elif args.group == "chain":
                    response = client.chain(args.chain_id)
                elif args.group == "mission" and args.action == "start" and started:
                    response = client.inspection(args.run_id)
                elif args.group == "preflight" and body is not None:
                    response = client.manifest("preflight", body)
                elif args.group == "mission" and body is not None:
                    response = client.manifest(
                        args.action, body, notify=getattr(args, "notify", None)
                    )
                    started = args.action == "start" and response.status_code == 202
                elif args.action == "inspect":
                    response = client.inspection(args.run_id)
                elif args.action == "admit" and body is not None:
                    response = client.admit(body)
                elif args.group == "run" and body is not None:
                    response = client.runtime_action(
                        args.run_id, args.action, body, notify=getattr(args, "notify", None)
                    )
                elif body is not None:
                    response = client.command(args.run_id, body)
                else:
                    response = client.commands(args.run_id)
                try:
                    result = response.json()
                except ValueError:
                    result = {"error": "non-JSON service response", "status": response.status_code}
                status = exit_status(response.status_code)
                if status or deadline_seconds is None:
                    print(json.dumps(result, allow_nan=False))
                    return status
                if isinstance(result, dict) and result.get("lifecycle") == "completed":
                    print(json.dumps(result, allow_nan=False))
                    return 0 if result.get("execution_outcome") == "completed" else 6
                chain_state = result.get("chain") if isinstance(result, dict) else None
                if isinstance(chain_state, dict) and chain_state.get("lifecycle") == "completed":
                    print(json.dumps(result, allow_nan=False))
                    return 0 if chain_state.get("terminal_outcome") == "accepted" else 6
                observed = inspection_wait_state(result)
                if initial is None:
                    initial = observed
                elif observed != initial:
                    print(json.dumps(result, allow_nan=False))
                    return 0
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    print(json.dumps({"error": "wait_timeout", "inspection": result}))
                    return 6
                time.sleep(min(WAIT_POLL_SECONDS, remaining))
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    except httpx.HTTPError:
        # Do not echo request URLs/headers or accidentally disclose credentials.
        print(json.dumps({"error": "service_unavailable"}), file=sys.stderr)
        return 5
