"""Mission Control Telemetry Hook Pack: ``.mission/hooks/signal`` (SPEC-04 section 4).

The Host Projection writes this file verbatim (LF-normalized) into every repository lane's
workspace, next to ``.mission/signal-policy.json``. It runs three ways:

- ``python .mission/hooks/signal hook <key>``: a native hook entry. It reads the hook JSON on
  stdin, keeps only the hooks the policy names (``signals``), and records one ``mc.signal.v1``
  whose ``data`` is a short allowlist of scalar fields (ids, names, statuses; never tool input
  or output). It prints the lane's no-op answer from the policy (``stdout``) and always exits
  0: the pack observes and never blocks an action.
- ``python .mission/hooks/signal emit <type> [message] [--data JSON]``: ``mc-signal``, for
  agents and scripts (``.mission/bin/mc-signal`` runs this).
- ``python .mission/hooks/signal flush``: upload what is spooled.

Every signal is appended to the spool ``.mission/state/signals/spool.jsonl`` with the next
``seq`` of this spool (monotonic from 1, so a gap is detectable) and the dedupe id
``<spool id>-<seq>``. The first signal of a spool is preceded by ``session.started`` and
``materialization.observed`` (digests of the files the policy names, as read from disk here,
and the skill directory listing): a lane without a session-start hook learns of the session
from whichever hook fires first. A gate answers in the lane's own shape, through the
``native_output.py`` its Host Projection places beside this script (OC-R3).

Signals are POSTed to ``MC_SIGNAL_URL`` (the application's ``/v1/ingress/{app}/signals``
route) with ``Authorization: Bearer $MC_SIGNAL_TOKEN`` (the ``run_token`` tier), in batches
of at most 100, with a 2 s timeout. Hooks upload once a batch is full, once the oldest pending
signal is older than the policy's delay, on the first signals of the spool, and always on a
flush hook (``stop``, ``session_end``) or ``mc-signal``; a flush retries with exponential
backoff, any other call makes one attempt and then waits out a growing backoff window. A batch
the ingress refuses for its content (400, 409, 413, 422) is split until the refused signal is
alone, and only that one is skipped (counted in ``state.json``). Any other refusal (an
unreachable ingress, a throttle, a credential not yet or no longer valid) keeps the spool for a
later call. Without a URL or token the signals stay spooled until a later call has them. The
ingress drops duplicates by signal id, so a resend is harmless.

A call waits at most ``LOCK_WAIT_SECONDS`` for the spool lock (an OS file lock, which the
kernel frees when its holder dies) and starts no request after ``UPLOAD_SECONDS``, so a hook
ends within its native timeout; a hook that cannot take the lock drops its signal rather than
risk a repeated ``seq``. ``seq`` is saved before the spool is written, so a writer killed
between the two leaves a gap, never a repeat.

Standard library only, Python 3.8 or newer (so no ``datetime.UTC`` and no ``X | Y`` at
runtime): the workspace's Python runs it without Mission Control installed. It never prints
the token and never forwards environment variables. The spool directory carries its own
``.gitignore`` so an agent's commit never picks the spool up.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

POLICY_PATH = ".mission/signal-policy.json"
RUN_PATH = ".mission/run.json"
# The lane's own gate answer shape (``projections.NATIVE_OUTPUT_SCRIPT``).
NATIVE_OUTPUT_PATH = ".mission/hooks/native_output.py"
# Fail closed (OC-R3): when the lane's answer module cannot be loaded or fails, answer with a
# superset every lane reads as a refusal, with exit 2: the Claude Code `decision: block`, the
# Codex PreToolUse deny (`hookSpecificOutput`) and the Cursor `permission: deny`. The native
# event name follows the Mission Control event where it has one, else `PreToolUse`.
FALLBACK_EVENT = {
    "before_tool": "PreToolUse",
    "before_shell": "PreToolUse",
    "before_mcp": "PreToolUse",
    "before_prompt": "UserPromptSubmit",
    "subagent_start": "SubagentStart",
    "stop": "Stop",
}


def failed_closed(event: str, reason: str) -> dict[str, Any]:
    return {
        "decision": "block",
        "reason": reason,
        "permission": "deny",
        "hookSpecificOutput": {
            "hookEventName": FALLBACK_EVENT.get(event, "PreToolUse"),
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }


STATE_DIR = ".mission/state/signals"
URL_ENV = "MC_SIGNAL_URL"
TOKEN_ENV = "MC_SIGNAL_TOKEN"  # noqa: S105 - an environment variable name, not a secret
SIGNAL_TYPE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_STDIN_BYTES = 1_000_000
MAX_CLI_DATA_BYTES = 65_536
MAX_FIELD_CHARS = 512
MAX_BATCH_SIGNALS = 100
MAX_BATCH_BYTES = 900_000
TIMEOUT_SECONDS = 2.0
FLUSH_ATTEMPTS = 3
BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 60
# Lock wait, upload budget and one request in flight stay under the native hook timeout.
LOCK_WAIT_SECONDS = 5.0
UPLOAD_SECONDS = 5.0
# What the ingress refuses for a batch's content (`invalid_*`, `payload_too_large`,
# `dedupe_conflict`): one signal can cause it, so the batch is split to find that one.
CONTENT_REFUSALS = {400, 409, 413, 422}
# Scalar hook payload fields a signal keeps (Cursor, Claude Code and Codex names).
FIELDS = (
    "hook_event_name",
    "conversation_id",
    "generation_id",
    "session_id",
    "agent_id",
    "agent_type",
    "subagent_type",
    "tool_name",
    "tool_use_id",
    "tool_call_id",
    "status",
    "loop_count",
    "stop_hook_active",
    "trigger",
    "model",
    "cursor_version",
)
# What a synthesized `session.started` keeps from the signal that opened the spool.
SESSION_KEYS = (
    "hook",
    "source",
    "hook_event_name",
    "conversation_id",
    "session_id",
    "cursor_version",
)


def now_iso() -> str:
    # `timezone.utc`: `datetime.UTC` needs Python 3.11.
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")  # noqa: UP017


def _read_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def section(policy: dict[str, Any], key: str) -> dict[str, Any]:
    value = policy.get(key)
    return value if isinstance(value, dict) else {}


def noop_answer(policy: dict[str, Any], key: str) -> str:
    """The lane's no-op answer for a native hook (a Cursor permission hook needs JSON)."""
    answer = section(policy, "stdout").get(key)
    return json.dumps(answer) if isinstance(answer, dict) else ""


def _scalar(value: Any) -> Any:
    if isinstance(value, str):
        return value[:MAX_FIELD_CHARS]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return None


def hook_data(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The allowlisted scalar fields of a native hook payload (untrusted, kept short)."""
    data: dict[str, Any] = {"hook": key}
    for field in FIELDS:
        value = _scalar(payload.get(field))
        if value is not None:
            data[field] = value
    return data


def _digest(path: Path) -> str | None:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def materialization(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    """What this environment reads from disk: the policy's files and its skill directories."""
    declared = section(policy, "materialization")
    files = {str(path): _digest(root / str(path)) for path in declared.get("files") or ()}
    skills: list[str] = []
    skill_root = declared.get("skills")
    if isinstance(skill_root, str) and (root / skill_root).is_dir():
        skills = sorted(
            entry.name for entry in (root / skill_root).iterdir() if (entry / "SKILL.md").is_file()
        )
    return {"files": files, "skills": skills}


def _try_lock(handle: IO[bytes]) -> bool:
    try:
        if sys.platform == "win32":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    # `flock` is released when the handle closes.


class Spool:
    """The per-session spool and its upload cursor, under ``.mission/state/signals``."""

    def __init__(self, root: Path, policy: dict[str, Any]) -> None:
        self.root = root
        self.policy = policy
        self.directory = root / STATE_DIR
        self.spool = self.directory / "spool.jsonl"
        self.state_file = self.directory / "state.json"
        self.lock = self.directory / "spool.lock"

    @contextmanager
    def locked(self) -> Iterator[dict[str, Any]]:
        """Hold the spool lock, yielding the state saved on exit.

        The lock is an OS file lock: the kernel frees it when its holder dies, and it is never
        taken from a live holder. A caller that waits ``LOCK_WAIT_SECONDS`` in vain raises
        ``TimeoutError``.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        ignore = self.directory / ".gitignore"
        if not ignore.is_file():
            ignore.write_text("*\n", encoding="utf-8")
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        with self.lock.open("a+b") as handle:
            while not _try_lock(handle):
                if time.monotonic() > deadline:
                    raise TimeoutError("the signal spool stayed locked")
                time.sleep(0.02)
            try:
                state = _read_json(self.state_file) or {
                    "spool_id": uuid.uuid4().hex[:16],
                    "seq": 0,
                    "sent": 0,
                    "failures": 0,
                    "retry_at": 0.0,
                }
                try:
                    yield state
                finally:
                    self.save(state)
            finally:
                with suppress(OSError):
                    _unlock(handle)

    def save(self, state: dict[str, Any]) -> None:
        temporary = self.state_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        temporary.replace(self.state_file)

    def append(
        self, state: dict[str, Any], signals: list[tuple[str, dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        """Spool ``signals`` (type, data); the first ones of a spool open the session."""
        if state["seq"] == 0:
            opened = signals[0][0] == "session.started"
            first = signals[0][1]
            started = first if opened else {k: first[k] for k in SESSION_KEYS if k in first}
            session = {
                "lane_profile": self.policy.get("lane_profile"),
                **started,
                **_nonce(self.root),
            }
            observed = materialization(self.root, self.policy)
            signals = [
                ("session.started", session),
                ("materialization.observed", observed),
                *signals[1 if opened else 0 :],
            ]
        records = []
        for kind, data in signals:
            state["seq"] += 1
            records.append(
                {
                    "signal_id": f"{state['spool_id']}-{state['seq']}",
                    "type": kind,
                    "seq": state["seq"],
                    "occurred_at": now_iso(),
                    "data": data,
                }
            )
        # The numbers are saved before the spool is written: a writer killed in between leaves
        # a gap the ingress can see, never a repeated `seq`.
        self.save(state)
        lines = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
        with self.spool.open("a+b") as handle:
            end = handle.seek(0, os.SEEK_END)
            if end:
                handle.seek(end - 1)
                if handle.read(1) != b"\n":
                    # A writer killed mid-line: end that line so this one still parses.
                    lines = "\n" + lines
            handle.write(lines.encode("utf-8"))
        return records

    def pending(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.spool.is_file():
            return []
        records = []
        with self.spool.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                seq = record.get("seq") if isinstance(record, dict) else None
                if isinstance(seq, int) and seq > state["sent"]:
                    records.append(record)
        return records


def _nonce(root: Path) -> dict[str, Any]:
    """The run nonce an ``environment_key`` session presents once (the ingress hashes it)."""
    nonce = _read_json(root / RUN_PATH).get("run_nonce")
    return {"run_nonce": nonce} if isinstance(nonce, str) and nonce else {}


def _batches(records: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    size = 0
    for record in records:
        length = len(json.dumps(record))
        if batch and (len(batch) == MAX_BATCH_SIGNALS or size + length > MAX_BATCH_BYTES):
            yield batch
            batch, size = [], 0
        batch.append(record)
        size += length
    if batch:
        yield batch


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        # A redirect must never forward a run's bearer to another destination.
        return None


def post(url: str, token: str, batch: list[dict[str, Any]]) -> int:
    """POST one batch; the HTTP status, or 0 when the ingress could not be reached."""
    target = urllib.parse.urlsplit(url)
    if (
        target.username is not None
        or target.password is not None
        or target.fragment
        or not target.hostname
        or not (
            target.scheme == "https"
            or (target.scheme == "http" and target.hostname in LOOPBACK_HOSTS)
        )
    ):
        return 0
    body = json.dumps({"signals": batch}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    handlers: list[urllib.request.BaseHandler] = [_NoRedirects()]
    if urllib.parse.urlsplit(url).hostname in LOOPBACK_HOSTS:
        # A loopback ingress (the worker's mount) is never reached through a proxy.
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)
    except (OSError, ValueError):
        return 0


def _transient(status: int) -> bool:
    return status == 0 or status >= 500 or status in {408, 429}


def send(
    url: str, token: str, batch: list[dict[str, Any]], *, attempts: int, deadline: float
) -> int | None:
    """POST ``batch``, retrying a transient failure; None when no time was left to try."""
    status = None
    for attempt in range(attempts):
        if time.monotonic() >= deadline:
            break
        status = post(url, token, batch)
        if not _transient(status):
            break
        if attempt + 1 < attempts:
            time.sleep(min(0.25 * 2**attempt, max(0.0, deadline - time.monotonic())))
    return status


def upload(
    pending: list[dict[str, Any]], state: dict[str, Any], *, flush: bool, deadline: float
) -> bool:
    """Send ``pending`` in order until ``deadline``; True when nothing is left to send."""
    url, token = os.environ.get(URL_ENV), os.environ.get(TOKEN_ENV)
    if not url or not token:
        return False
    if not flush and time.time() < float(state.get("retry_at", 0.0)):
        return False
    queue = list(_batches(pending))
    while queue:
        batch = queue.pop(0)
        status = send(url, token, batch, attempts=FLUSH_ATTEMPTS if flush else 1, deadline=deadline)
        if status is None:
            return False  # Out of time: the rest waits for the next call.
        if status in CONTENT_REFUSALS and len(batch) > 1:
            middle = len(batch) // 2
            queue[:0] = [batch[:middle], batch[middle:]]
            continue
        if 200 <= status < 300 or status in CONTENT_REFUSALS:
            state["sent"] = int(batch[-1]["seq"])
            state["failures"], state["retry_at"] = 0, 0.0
            if status in CONTENT_REFUSALS:
                state["rejected"] = int(state.get("rejected", 0)) + 1
                state["last_error"] = status
            continue
        # Unreachable, throttled or not (yet) authorized: kept, and tried after a backoff.
        state["failures"] = int(state.get("failures", 0)) + 1
        backoff = BACKOFF_SECONDS * 2 ** (state["failures"] - 1)
        state["retry_at"] = time.time() + min(MAX_BACKOFF_SECONDS, backoff)
        state["last_error"] = status
        return False
    return True


def _due(policy: dict[str, Any], pending: list[dict[str, Any]]) -> bool:
    batch = section(policy, "batch")
    if len(pending) >= int(batch.get("max_signals", 20)):
        return True
    oldest = pending[0].get("occurred_at") if pending else None
    if not isinstance(oldest, str):
        return False
    try:
        age = time.time() - datetime.fromisoformat(oldest.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return True
    return age >= float(batch.get("max_delay_seconds", 30))


def record(
    root: Path,
    policy: dict[str, Any],
    signals: list[tuple[str, dict[str, Any]]],
    *,
    flush: bool,
) -> tuple[list[dict[str, Any]], bool]:
    """Spool ``signals`` and upload when due; the records and whether all were delivered."""
    spool = Spool(root, policy)
    with spool.locked() as state:
        opening = state["seq"] == 0
        records = spool.append(state, signals) if signals else []
        pending = spool.pending(state)
        delivered = not pending
        if pending and (flush or opening or _due(policy, pending)):
            deadline = time.monotonic() + UPLOAD_SECONDS
            delivered = upload(pending, state, flush=flush, deadline=deadline)
    return records, delivered


def hook(root: Path, policy: dict[str, Any], key: str, raw: str) -> str:
    """Record one native hook; the lane's no-op answer for it."""
    kind = section(policy, "signals").get(key)
    if isinstance(kind, str) and SIGNAL_TYPE.fullmatch(kind):
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except (ValueError, RecursionError):
            payload = {}
        data = hook_data(key, payload if isinstance(payload, dict) else {})
        record(root, policy, [(kind, data)], flush=key in (policy.get("flush") or ()))
    return noop_answer(policy, key)


def emit(root: Path, policy: dict[str, Any], argv: list[str]) -> tuple[str, int]:
    """``mc-signal <type> [message] [--data JSON]``: one agent signal, uploaded at once."""
    args = list(argv)
    data: dict[str, Any] = {}
    if "--data" in args:
        index = args.index("--data")
        if index + 1 >= len(args) or len(args[index + 1].encode()) > MAX_CLI_DATA_BYTES:
            return "mc-signal: --data needs a JSON object of at most 64 KiB", 2
        try:
            loaded = json.loads(args[index + 1])
        except ValueError:
            loaded = None
        if not isinstance(loaded, dict):
            return "mc-signal: --data must be a JSON object", 2
        data = loaded
        del args[index : index + 2]
    if not args or len(args) > 2 or not SIGNAL_TYPE.fullmatch(args[0]) or len(args[0]) > 128:
        return "usage: mc-signal <type> [message] [--data '<json object>']", 2
    if len(args) == 2:
        data["message"] = args[1][:4000]
    data.setdefault("source", "cli")
    records, delivered = record(root, policy, [(args[0], data)], flush=True)
    last = records[-1]
    receipt = {"signal_id": last["signal_id"], "seq": last["seq"], "delivered": delivered}
    return json.dumps(receipt), 0


def native_gate_output(root: Path, lane: str, decision: str, reason: str) -> dict[str, Any]:
    """The gate answer in the lane's own shape: its Host Projection places the lane package's
    ``hook_output.py`` beside this script as ``native_output.py`` (OC-R3)."""
    location = root / NATIVE_OUTPUT_PATH
    # Never leave a `__pycache__` in the workspace's `.mission/hooks`.
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("mc_native_output", location)
    if spec is None or spec.loader is None:
        raise ImportError(f"no native output module at {NATIVE_OUTPUT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    answer: dict[str, Any] = module.native_gate_output(lane, decision, reason)
    return answer


def gate(
    root: Path, policy: dict[str, Any], key: str, raw: str, *, lane_profile: str | None = None
) -> str:
    """Ask the ingress synchronously; transport failure uses the declared closed policy."""
    lane = lane_profile if lane_profile is not None else str(policy.get("lane_profile", ""))
    declared = section(policy, "gates").get(key)
    fail_closed = not isinstance(declared, dict) or declared.get("fail_closed", True) is not False
    decision, reason = ("deny", "gate_unavailable") if fail_closed else ("allow", "")
    with suppress(Exception):
        hook(root, policy, key, raw)
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("hook payload must be an object")
        tool = str(payload.get("tool_name") or payload.get("toolName") or "unknown")[:256]
        native_id = (
            payload.get("tool_use_id")
            or payload.get("tool_call_id")
            or payload.get("call_id")
            or uuid.uuid4().hex
        )
        effect = hashlib.sha256(f"{key}:{native_id}".encode()).hexdigest()
        tool_input = payload.get("tool_input", payload.get("input", {}))
        input_digest = hashlib.sha256(json.dumps(tool_input, sort_keys=True).encode()).hexdigest()
        kind = (
            "shell"
            if key == "before_shell" or tool.lower() in {"bash", "shell", "execute"}
            else (
                "mcp"
                if key == "before_mcp" or tool.lower().startswith("mcp")
                else "file"
                if tool.lower() in {"edit", "write", "apply_patch"}
                else "other"
            )
        )
        request_body = {
            "schema_version": "mc.signal_gate.v1",
            "signal_id": "gate-" + effect,
            "hook_event": key,
            "effect_ref": "gate:" + effect,
            "effect_kind": kind,
            "tool": tool,
            "tool_input": {"native_input_digest": input_digest},
        }
        url, token = os.getenv("MC_SIGNAL_URL", ""), os.getenv("MC_SIGNAL_TOKEN", "")
        target = urllib.parse.urlsplit(url)
        if (
            not token
            or target.username is not None
            or target.password is not None
            or target.fragment
            or not target.hostname
            or not (
                target.scheme == "https"
                or (target.scheme == "http" and target.hostname in LOOPBACK_HOSTS)
            )
        ):
            raise ValueError("a gate requires the configured secure ingress and credential")
        request = urllib.request.Request(
            urllib.parse.urlunsplit(target._replace(query="gate=1")),
            data=json.dumps(request_body).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        handlers: list[urllib.request.BaseHandler] = [_NoRedirects()]
        if target.hostname in LOOPBACK_HOSTS:
            handlers.append(urllib.request.ProxyHandler({}))
        with urllib.request.build_opener(*handlers).open(
            request, timeout=TIMEOUT_SECONDS
        ) as response:
            answer = json.loads(response.read(8192))
        if not isinstance(answer, dict) or answer.get("decision") not in {"allow", "deny", "stop"}:
            raise ValueError("invalid gate answer")
        decision = answer["decision"]
        reason = str(answer.get("reason") or "denied by Mission Control")[:512]
    except Exception:
        # Native decision JSON is emitted even on malformed input, timeout or failed auth.
        pass
    return json.dumps(native_gate_output(root, lane, decision, reason))


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[2]
    policy = _read_json(root / POLICY_PATH)
    command = argv[1] if len(argv) > 1 else ""
    if command == "gate" and len(argv) == 4:
        try:
            answer = gate(
                root, policy, argv[3], sys.stdin.read(MAX_STDIN_BYTES), lane_profile=argv[2]
            )
        except Exception:
            try:
                answer = json.dumps(native_gate_output(root, argv[2], "deny", "gate_failed"))
            except Exception as error:  # no usable answer module: fail closed
                sys.stderr.write(f"mc signal gate: native output failed: {type(error).__name__}\n")
                sys.stdout.write(json.dumps(failed_closed(argv[3], "gate_failed")) + "\n")
                return 2
        sys.stdout.write(answer + "\n")
        return 0
    if command == "hook" and len(argv) == 3:
        try:
            raw = sys.stdin.read(MAX_STDIN_BYTES)
            answer = hook(root, policy, argv[2], raw)
        except Exception as error:
            # Observation never blocks the action it observes, whatever went wrong.
            sys.stderr.write(f"mc signal hook failed: {type(error).__name__}\n")
            answer = noop_answer(policy, argv[2])
        if answer:
            sys.stdout.write(answer + "\n")
        return 0
    if command == "emit":
        try:
            text, code = emit(root, policy, argv[2:])
        except (OSError, ValueError) as error:
            text, code = f"mc-signal: nothing was recorded ({type(error).__name__})", 1
        (sys.stdout if code == 0 else sys.stderr).write(text + "\n")
        return code
    if command == "flush" and len(argv) == 2:
        try:
            _records, delivered = record(root, policy, [], flush=True)
        except (OSError, ValueError):
            delivered = False
        return 0 if delivered else 1
    sys.stderr.write("usage: signal hook <key> | emit <type> [message] [--data JSON] | flush\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
