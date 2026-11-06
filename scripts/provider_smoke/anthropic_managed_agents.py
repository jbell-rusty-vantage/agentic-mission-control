"""HL-23 Anthropic Managed Agents smoke (paid, under $1 from the S2 budget).

Creates a skill, a vault with one placeholder credential, an agent and a cloud environment;
runs one session (custom tool round trip, a `user.message` sent mid-turn for Q-M1, an interrupt);
reads usage; then deletes or archives everything. Every resource carries `mc_run=run1-HL-23`.
The session budget caps list cost at $0.90. Only ids and statuses are printed; the evidence JSON
(event names, usage, verdicts, no model text) goes to `--record`.

Run from the repository root with the key from the environment and the pinned SDK:

    uv run --no-project --python 3.12 --with anthropic==1.13.0 \\
        python -m scripts.provider_smoke.anthropic_managed_agents --record <path.json>
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from itertools import chain
from typing import TYPE_CHECKING, Any

from scripts.provider_smoke.common import (
    LONG_TURN_PROMPT,
    METADATA,
    MIDTURN_ACK,
    MIDTURN_MESSAGE,
    RUN_LABEL,
    SIGNAL_TOOL,
    SIGNAL_TOOL_DESCRIPTION,
    SIGNAL_TOOL_SCHEMA,
    SKILL_NAME,
    VAULT_VARIABLE_HOST,
    CleanupLedger,
    SmokeRecord,
    mid_turn_delivery,
    placeholder_credential_auth,
    record_path,
    skill_files,
)

if TYPE_CHECKING:
    from anthropic import Anthropic

MODEL = "claude-sonnet-5-5"
SDK = "anthropic==1.13.0"
BUDGET_CENTS = "90"
SESSION_DEADLINE_S = 420.0
READ_ONLY_TOOLS = ("read", "glob", "grep")

SYSTEM = (
    "You are a Mission Control provider smoke agent. Follow the user's steps exactly and "
    "keep answers short."
)
FIRST_PROMPT = (
    f"Step 1: call the {SIGNAL_TOOL} tool with name 'smoke.start' before anything else. "
    "Step 2: after its result arrives, use the glob tool three separate times, on "
    "'/usr/lib/python3*/json/*.py', '/usr/lib/python3*/email/*.py' and "
    "'/usr/lib/python3*/http/*.py'. Step 3: read the first json file you found. "
    "Step 4: answer with the three file counts on one line."
)


def provision(client: Anthropic, record: SmokeRecord, ledger: CleanupLedger) -> dict[str, Any]:
    """Create the skill, vault and credential, agent and environment; register their cleanup."""
    skill = client.skills.create(display_name=SKILL_NAME, files=skill_files())
    record.created("skill", skill.id)
    # Deleting the skill removes its only version; a version cannot be deleted on its own.
    ledger.add("skill", skill.id, "deleted", lambda: client.skills.delete(skill.id))

    vault = client.beta.vaults.create(display_name=f"mc-{RUN_LABEL}-smoke", metadata=METADATA)
    record.created("vault", vault.id)
    ledger.add("vault", vault.id, "deleted", lambda: client.beta.vaults.delete(vault.id))
    credential = client.beta.vaults.credentials.create(
        vault.id,
        display_name="mc-smoke-placeholder",
        auth=placeholder_credential_auth(),
        metadata=METADATA,
    )
    record.created("credential", credential.id)
    ledger.add(
        "credential",
        credential.id,
        "deleted",
        lambda: client.beta.vaults.credentials.delete(credential.id, vault_id=vault.id),
    )

    agent = client.beta.agents.create(
        name=f"mc-{RUN_LABEL}-smoke",
        model=MODEL,
        system=SYSTEM,
        tools=[
            {
                "type": "agent_toolset_20260401",
                "default_config": {"enabled": False},
                "configs": [
                    {"name": name, "enabled": True, "permission_policy": {"type": "always_allow"}}
                    for name in READ_ONLY_TOOLS
                ],
            },
            {
                "type": "custom",
                "name": SIGNAL_TOOL,
                "description": SIGNAL_TOOL_DESCRIPTION,
                "input_schema": SIGNAL_TOOL_SCHEMA,
            },
        ],
        skills=[{"type": "custom", "skill_id": skill.id, "version": skill.latest_version_id}],
        metadata=METADATA,
    )
    record.created("agent", agent.id)
    record.findings["agent_version"] = agent.version
    ledger.add("agent", agent.id, "archived", lambda: client.beta.agents.archive(agent.id))

    environment = client.beta.environments.create(
        name=f"mc-{RUN_LABEL}-smoke",
        config={
            "type": "cloud",
            "networking": {
                "type": "limited",
                # A vault variable's host must be reachable, or the session reports
                # `credential_host_unreachable_error` (observed in the first smoke).
                "allowed_hosts": [VAULT_VARIABLE_HOST],
                "allow_package_managers": False,
                "allow_mcp_servers": False,
            },
        },
        metadata=METADATA,
    )
    record.created("environment", environment.id)
    ledger.add(
        "environment",
        environment.id,
        "deleted",
        lambda: client.beta.environments.delete(environment.id),
    )
    return {"agent": agent, "environment_id": environment.id, "vault_id": vault.id}


@dataclass
class SessionDriver:
    """Drives one session through the smoke script from its event stream.

    Phase `first`: answer `mc_signal`; once the session is running again, send the mid-turn
    message (Q-M1) and wait until it has been consumed and the session is idle. Sending it
    straight after the tool result can race the `requires_action` wait and get a 400.
    Phase `second`: send a long prompt and interrupt it at its first model request. The driver
    is fed both the history and the live stream, so it dedupes on (event id, processed) exactly
    as a lane would on reattach.
    """

    client: Anthropic
    session_id: str
    record: SmokeRecord
    phase: str = "first"
    timeline: list[str] = field(default_factory=list)
    midturn_pending: bool = False
    midturn_event_id: str | None = None
    interrupt_sent: bool = False
    messages_after_interrupt: int = 0
    done: bool = False
    _seen: set[tuple[str, bool]] = field(default_factory=set)

    def handle(self, event: Any) -> None:
        """Apply one event; set `done` when the smoke script is finished."""
        processed = getattr(event, "processed_at", None) is not None
        key = (event.id, processed)
        if key in self._seen:
            return
        self._seen.add(key)
        self.record.saw(event.type)

        if event.type == "agent.custom_tool_use" and self.phase == "first":
            self._answer_signal(event)
        elif event.type == "session.status_running" and self.midturn_pending:
            self._send_midturn()
        elif event.type == "user.message" and event.id == self.midturn_event_id and processed:
            self.timeline.append("processed")
        elif event.type == "agent.message":
            self._on_agent_message(event)
        elif event.type == "agent.tool_use" and getattr(event, "evaluated_permission", "") == "ask":
            self._deny(event.id)
        elif event.type == "span.model_request_start" and self.phase == "second":
            self._interrupt_once()
        elif event.type == "session.error":
            self.record.errors.append(f"session.error: {event.error.type}")
        elif event.type == "session.status_idle":
            self.done = self._on_idle(event.stop_reason.type)
        elif event.type == "session.status_terminated":
            self.done = True

    def _answer_signal(self, event: Any) -> None:
        self.record.findings["custom_tool_name"] = event.name
        self._send(
            {
                "type": "user.custom_tool_result",
                "custom_tool_use_id": event.id,
                "content": [{"type": "text", "text": "ok"}],
            }
        )
        self.midturn_pending = True

    def _send_midturn(self) -> None:
        self.midturn_pending = False
        sent = self._send(
            {"type": "user.message", "content": [{"type": "text", "text": MIDTURN_MESSAGE}]}
        )
        self.midturn_event_id = sent.data[0].id if sent.data else None
        self.timeline.append("sent")
        self.record.status("midturn user.message", self.midturn_event_id or "-", "sent")

    def _on_agent_message(self, event: Any) -> None:
        if self.interrupt_sent:
            self.messages_after_interrupt += 1
        text = "".join(getattr(block, "text", "") for block in event.content)
        if MIDTURN_ACK in text and "turn_end" not in self.timeline:
            self.record.findings["midturn_ack_in_same_turn"] = True

    def _deny(self, tool_use_id: str) -> None:
        """Nothing in the smoke should ask; an unattended run never allows."""
        self._send({"type": "user.tool_confirmation", "tool_use_id": tool_use_id, "result": "deny"})

    def _interrupt_once(self) -> None:
        if not self.interrupt_sent:
            self._send({"type": "user.interrupt"})
            self.interrupt_sent = True
            self.record.status("user.interrupt", self.session_id, "sent")

    def _on_idle(self, stop_reason: str) -> bool:
        self.record.status("session.status_idle", self.session_id, stop_reason)
        if stop_reason == "requires_action":
            return False
        if stop_reason != "end_turn":
            self.record.findings["terminal_stop_reason"] = stop_reason
            return True
        self.timeline.append("turn_end")
        if self.phase == "second":
            self.record.findings["interrupt_stop_reason"] = stop_reason
            self.record.findings["agent_messages_after_interrupt"] = self.messages_after_interrupt
            return True
        if "processed" in self.timeline or "sent" not in self.timeline:
            self.phase = "second"
            self._send(
                {"type": "user.message", "content": [{"type": "text", "text": LONG_TURN_PROMPT}]}
            )
        return False

    def summarize(self) -> None:
        """Write the Q-M1 verdict, also after a failure, so partial paid evidence is kept."""
        self.record.findings["q_m1_timeline"] = self.timeline
        self.record.findings["q_m1_verdict"] = mid_turn_delivery(self.timeline)
        self.record.findings.setdefault("midturn_ack_in_same_turn", False)

    def _send(self, event: dict[str, Any]) -> Any:
        return self.client.beta.sessions.events.send(self.session_id, events=[event])


def run_session(client: Anthropic, record: SmokeRecord, ledger: CleanupLedger, ids: dict) -> None:
    agent = ids["agent"]
    session = client.beta.sessions.create(
        agent={"type": "agent", "id": agent.id, "version": agent.version},
        environment_id=ids["environment_id"],
        vault_ids=[ids["vault_id"]],
        budget={"type": "limit", "max_list_cost": {"amount": BUDGET_CENTS, "currency": "USD"}},
        title=f"mc {RUN_LABEL} smoke",
        metadata=METADATA,
        initial_events=[
            {"type": "user.message", "content": [{"type": "text", "text": FIRST_PROMPT}]}
        ],
    )
    record.created("session", session.id)
    record.status("session", session.id, session.status)
    ledger.add("session", session.id, "deleted", lambda: _end_session(client, session.id))

    driver = SessionDriver(client=client, session_id=session.id, record=record)
    deadline = time.monotonic() + SESSION_DEADLINE_S
    try:
        with client.beta.sessions.events.stream(session.id) as stream:
            # Stream first, then history: events emitted before the stream opened are replayed.
            for event in chain(client.beta.sessions.events.list(session.id), stream):
                driver.handle(event)
                if driver.done or time.monotonic() > deadline:
                    break
        if not driver.done:
            record.errors.append("session deadline reached before the smoke script finished")
    finally:
        driver.summarize()
        _record_usage(client, session.id, record)


def _record_usage(client: Anthropic, session_id: str, record: SmokeRecord) -> None:
    _settle(client, session_id)
    final = client.beta.sessions.retrieve(session_id)
    record.status("session", session_id, final.status)
    record.usage = final.usage.model_dump(mode="json", exclude_none=True)
    if final.usage.list_cost is not None:  # whole cents, list price
        record.findings["list_cost_usd"] = int(final.usage.list_cost.amount) / 100


def _settle(client: Anthropic, session_id: str) -> None:
    """The idle event lands slightly before the queryable status; wait it out before cleanup."""
    for _ in range(20):
        if client.beta.sessions.retrieve(session_id).status != "running":
            return
        time.sleep(0.5)


def _end_session(client: Anthropic, session_id: str) -> None:
    if client.beta.sessions.retrieve(session_id).status == "running":
        client.beta.sessions.events.send(session_id, events=[{"type": "user.interrupt"}])
        _settle(client, session_id)
    client.beta.sessions.delete(session_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--record", type=record_path, required=True, help="evidence JSON output path"
    )
    args = parser.parse_args(argv)

    from anthropic import Anthropic

    client = Anthropic(timeout=120.0, max_retries=0)  # creates are not idempotent
    record = SmokeRecord(provider="anthropic_managed_agents", sdk=SDK, model=MODEL)
    ledger = CleanupLedger(record)
    try:
        run_session(client, record, ledger, provision(client, record, ledger))
    except Exception as exc:  # recorded; cleanup still runs
        record.error("smoke", exc)
    finally:
        ledger.run()
        record.write(args.record)
    return 1 if record.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
