"""HL-23 OpenAI Agents API smoke (paid, under $1 from the S3 budget).

Creates a skill, a vault with one placeholder credential and a saved `gpt-6-luna` agent; runs
one `openai_hosted` session whose workspace holds an AGENTS.md canary. Turn one answers the
`mc_signal` function call and is steered by a mid-turn message (Q-M1 analogue); turn two asks for
the canary with no tool use (Q-O2); turn three is cancelled. Then it reads the item history and
usage and deletes everything. Every resource that accepts metadata carries `mc_run=run1-HL-23`.
If the Agents API refuses `gpt-6-luna` the smoke stops (exit 2) and records the exact error:
no other model is substituted. Only ids and statuses are printed; the evidence JSON goes to
`--record`.

Run from the repository root with the key from the environment and the pinned SDK:

    uv run --no-project --python 3.12 --with openai==3.29.0 \\
        python -m scripts.provider_smoke.openai_agents_api --record <path.json>
"""

from __future__ import annotations

import argparse
import base64
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from scripts.provider_smoke.common import (
    AGENTS_MD_CANARY,
    LONG_TURN_PROMPT,
    METADATA,
    MIDTURN_ACK,
    MIDTURN_MESSAGE,
    RUN_LABEL,
    SIGNAL_TOOL,
    SIGNAL_TOOL_DESCRIPTION,
    SIGNAL_TOOL_SCHEMA,
    VAULT_VARIABLE_HOST,
    CleanupLedger,
    SmokeRecord,
    agents_md_verdict,
    gpt_6_luna_cost_usd,
    mid_turn_delivery,
    placeholder_credential_auth,
    record_path,
    retry_on_conflict,
    skill_files,
)

if TYPE_CHECKING:
    from openai import OpenAI

MODEL = "gpt-6-luna"
SDK = "openai==3.29.0"
SESSION_DEADLINE_S = 420.0
EXIT_MODEL_REFUSED = 2

INSTRUCTIONS = "You are a Mission Control provider smoke agent. Keep answers short."
# The canary lives only in the workspace AGENTS.md, never in the instructions or the prompt.
AGENTS_MD = (
    "# Project rules\n\n"
    f"The project canary phrase is {AGENTS_MD_CANARY}. Quote it whenever you are asked for "
    "the canary phrase.\n"
)
FIRST_PROMPT = (
    f"Step 1: call the {SIGNAL_TOOL} function with name 'smoke.start'. Step 2: run "
    "`ls -a /workspace` and reply with the file names it lists."
)
CANARY_PROMPT = (
    "Without running any command and without reading any file, answer from what is already in "
    "your context: what is the project canary phrase? Reply UNKNOWN if you do not have one."
)


class ModelRefusedError(RuntimeError):
    """The Agents API refused the configured model; the owner must decide what happens next."""


def is_model_refusal(message: str) -> bool:
    """Conservative: any error naming the model stops the smoke for an owner decision."""
    lowered = message.lower()
    return MODEL in lowered or "model" in lowered


def provision(client: OpenAI, record: SmokeRecord, ledger: CleanupLedger) -> dict[str, str]:
    """Create the skill, vault and credential and the saved agent; register their cleanup."""
    skill = client.skills.create(files=skill_files())
    record.created("skill", skill.id)
    record.findings["skill_versions"] = {
        "default": skill.default_version,
        "latest": skill.latest_version,
    }
    ledger.add("skill", skill.id, "deleted", lambda: client.skills.delete(skill.id))

    vault = client.beta.agents.vaults.create(name=f"mc-{RUN_LABEL}-smoke", metadata=METADATA)
    record.created("vault", vault.id)
    ledger.add("vault", vault.id, "deleted", lambda: client.beta.agents.vaults.delete(vault.id))
    credential = client.beta.agents.vaults.credentials.create(
        vault.id,
        name="mc-smoke-placeholder",
        auth=placeholder_credential_auth(),
        metadata=METADATA,
    )
    record.created("credential", credential.id)
    ledger.add(
        "credential",
        credential.id,
        "deleted",
        lambda: client.beta.agents.vaults.credentials.delete(credential.id, vault_id=vault.id),
    )

    try:
        agent = client.beta.agents.create(
            model=MODEL,
            name=f"mc-{RUN_LABEL}-smoke",
            instructions=INSTRUCTIONS,
            tools=[
                {
                    "type": "function",
                    "name": SIGNAL_TOOL,
                    "description": SIGNAL_TOOL_DESCRIPTION,
                    "parameters": SIGNAL_TOOL_SCHEMA,
                }
            ],
            multi_agent={"enabled": False},
            metadata=METADATA,
        )
    except Exception as exc:
        if is_model_refusal(str(exc)):
            record.findings["model_accepted"] = False
            raise ModelRefusedError(str(exc)) from exc
        raise
    record.created("agent", agent.id)
    ledger.add("agent", agent.id, "deleted", lambda: client.beta.agents.delete(agent.id))
    return {"agent_id": agent.id, "vault_id": vault.id, "skill_id": skill.id}


@dataclass
class SessionDriver:
    """Drives one session from its live stream (the Agents API has no replay cursor).

    Turn `first`: answer `mc_signal`, steer with the mid-turn message (Q-M1 analogue), list the
    workspace (which also brings the hosted environment up). Turn `canary`: ask for the AGENTS.md
    canary with no tool use (Q-O2). Turn `long`: send a long prompt and cancel it.
    """

    client: OpenAI
    session_id: str
    record: SmokeRecord
    phase: str = "first"
    timeline: list[str] = field(default_factory=list)
    answered_calls: set[str] = field(default_factory=set)
    agents_md_listed: bool = False
    canary_in_answer: bool = False
    canary_turn_commands: int = 0
    turn_ids: list[str] = field(default_factory=list)
    cancel_sent: bool = False
    done: bool = False

    def start(self) -> None:
        self._message(FIRST_PROMPT)

    def handle(self, event: Any) -> None:
        self.record.saw(event.type)
        if event.type == "agent.session.requires_action":
            self._answer_calls(event.session.required_actions)
        elif event.type == "agent.session.turn.created":
            self.turn_ids.append(event.turn_id)
        elif event.type == "agent.session.turn.in_progress" and self.phase == "long":
            self._cancel_once()
        elif event.type == "agent.session.turn.item.done":
            self._on_item(event.item)
        elif event.type == "agent.session.turn.completed":
            self.timeline.append("turn_end")
            self.record.status("turn", event.turn_id, event.turn.status)
            self.record.findings["model_accepted"] = True
        elif event.type == "agent.session.turn.cancelled":
            self.record.status("turn", event.turn_id, event.turn.status)
            self.record.findings["cancelled_turn_status"] = event.turn.status
            self.done = True
        elif event.type == "agent.session.turn.failed":
            error = event.turn.error
            self._on_failure(error.code if error else None, error.message if error else "")
        elif event.type == "error":
            self._on_failure(event.error.code, event.error.message)
        elif event.type == "agent.session.failed":
            self._on_failure(None, event.session.error or "")
        elif event.type == "agent.session.idle":
            self._on_idle()

    def _answer_calls(self, actions: list[Any]) -> None:
        for action in actions:
            if action.type != "function_call" or action.call_id in self.answered_calls:
                continue
            self.answered_calls.add(action.call_id)
            self.record.findings["function_call_name"] = action.name
            self._send(
                {
                    "type": "agent.session.input.tool_result",
                    "turn_id": action.turn_id,
                    "call_id": action.call_id,
                    "success": True,
                    "output": "ok",
                }
            )
            if self.phase == "first" and "sent" not in self.timeline:
                self._steer()

    def _steer(self) -> None:
        try:
            self._message(MIDTURN_MESSAGE)
        except Exception as exc:  # e.g. active_turn_not_steerable is itself a finding
            self.record.findings["steer_rejected"] = f"{type(exc).__name__}: {exc}"
            return
        self.timeline.append("sent")
        self.record.status("midturn input.message", self.session_id, "sent")

    def _on_item(self, item: Any) -> None:
        if item.type == "command_execution":
            if self.phase == "canary":
                self.canary_turn_commands += 1
            if "AGENTS.md" in (item.output or ""):
                self.agents_md_listed = True
        elif item.type == "message" and getattr(item, "role", None) == "assistant":
            text = _text(item)
            if self.phase == "canary" and AGENTS_MD_CANARY in text:
                self.canary_in_answer = True
            if MIDTURN_ACK in text and "processed" not in self.timeline:
                self.timeline.append("processed")

    def _cancel_once(self) -> None:
        """Cancel the long turn; a cancel racing the turn start gets 409 and is retried."""
        if not self.cancel_sent:
            retry_on_conflict(lambda: self._send({"type": "agent.session.input.cancel"}))
            self.cancel_sent = True
            self.record.status("input.cancel", self.session_id, "sent")

    def _on_failure(self, code: str | None, message: str) -> None:
        self.record.errors.append(f"{code}: {message}")
        if self.phase == "first" and is_model_refusal(message):
            self.record.findings["model_accepted"] = False
        self.done = True

    def _on_idle(self) -> None:
        self.record.status("session", self.session_id, "idle")
        if self.phase == "first":
            self.phase = "canary"
            self._message(CANARY_PROMPT)
        elif self.phase == "canary":
            self.phase = "long"
            self._message(LONG_TURN_PROMPT)
        else:
            self.done = True

    def summarize(self) -> None:
        """Write the verdicts, also after a failure, so partial paid evidence is kept."""
        findings = self.record.findings
        findings["q_m1_timeline"] = self.timeline
        findings["q_m1_verdict"] = mid_turn_delivery(self.timeline)
        findings["turns_created"] = len(self.turn_ids)
        findings["agents_md_listed"] = self.agents_md_listed
        findings["q_o2_verdict"] = agents_md_verdict(
            canary_in_answer=self.canary_in_answer, commands_run=self.canary_turn_commands
        )

    def _message(self, text: str) -> None:
        self._send({"type": "agent.session.input.message", "input": [_user_message(text)]})

    def _send(self, event: dict[str, Any]) -> None:
        self.client.beta.agents.sessions.events.create(
            self.session_id, events=[event], idempotency_key=str(uuid.uuid4())
        )


def _text(item: Any) -> str:
    return "".join(getattr(part, "text", "") for part in item.content)


def _user_message(text: str) -> dict[str, Any]:
    return {"role": "user", "content": [{"type": "input_text", "text": text}]}


def run_session(client: OpenAI, record: SmokeRecord, ledger: CleanupLedger, ids: dict) -> None:
    agents_md = base64.b64encode(AGENTS_MD.encode()).decode()
    session = client.beta.agents.sessions.create(
        agent_id=ids["agent_id"],
        environment={
            "type": "openai_hosted",
            "container_size": "small",
            "network": {"access": "restricted", "allowed_domains": [VAULT_VARIABLE_HOST]},
            "files": [{"type": "inline", "path": "/workspace/AGENTS.md", "data": agents_md}],
            "skills": [{"type": "skill_reference", "skill_id": ids["skill_id"]}],
        },
        vault_ids=[ids["vault_id"]],
        metadata=METADATA,
    )
    started = time.monotonic()
    record.created("session", session.id)
    record.status("session", session.id, session.status)
    ledger.add("session", session.id, "deleted", lambda: _delete_session(client, session.id))

    driver = SessionDriver(client=client, session_id=session.id, record=record)
    deadline = started + SESSION_DEADLINE_S
    try:
        with client.beta.agents.sessions.events.stream(session.id) as stream:
            driver.start()  # stream first: the session is idle until this message arrives
            for event in stream:
                driver.handle(event)
                if driver.done or time.monotonic() > deadline:
                    break
        if not driver.done:
            record.errors.append("session deadline reached before the smoke script finished")
    finally:
        driver.summarize()
        _audit_history(client, session.id, record, driver.turn_ids[:1])
        _record_usage(client, session.id, record, started)


def _audit_history(
    client: OpenAI, session_id: str, record: SmokeRecord, first_turn: list[str]
) -> None:
    """Items and turns are the durable history: where the steer landed and per-turn usage."""
    items = list(client.beta.agents.sessions.items.list(session_id, order="asc"))
    record.findings["item_sequence"] = [
        ":".join(filter(None, (item.type, getattr(item, "role", None)))) for item in items
    ]
    for index, item in enumerate(items):
        if item.type == "message" and item.role == "user" and MIDTURN_ACK in _text(item):
            record.findings["steer_item_in_first_turn"] = [item.turn_id] == first_turn
            record.findings["steer_item_before_final_answer"] = any(
                later.type == "message" and later.phase == "final_answer"
                for later in items[index + 1 :]
                if later.turn_id == item.turn_id
            )
    turns = client.beta.agents.sessions.turns.list(session_id, order="asc")
    record.findings["turn_usage"] = {
        turn.id: turn.usage.model_dump(mode="json") if turn.usage else None for turn in turns
    }


def _record_usage(client: OpenAI, session_id: str, record: SmokeRecord, started: float) -> None:
    """Estimate cost from session usage, or from the per-turn usage when the session's is null.

    Usage is best-effort on the Agents API: turns without usage stay unknown and are counted.
    """
    final = client.beta.agents.sessions.retrieve(session_id)
    record.status("session", session_id, final.status)
    if final.usage is not None:
        record.usage = final.usage.model_dump(mode="json")
        known = [record.usage]
    else:
        turn_usage = record.findings.get("turn_usage", {})
        known = [usage for usage in turn_usage.values() if usage]
        record.findings["usage_source"] = "turns"
        record.findings["turns_with_unknown_usage"] = len(turn_usage) - len(known)
    record.findings["estimated_cost_usd"] = gpt_6_luna_cost_usd(
        input_tokens=sum(usage["input_tokens"] for usage in known),
        cached_tokens=sum(usage["input_tokens_details"]["cached_tokens"] for usage in known),
        output_tokens=sum(usage["output_tokens"] for usage in known),
        container_minutes=(time.monotonic() - started) / 60,
    )


def _delete_session(client: OpenAI, session_id: str) -> None:
    """Deletion can return 409 while setup or execution finishes; retry briefly."""
    retry_on_conflict(lambda: client.beta.agents.sessions.delete(session_id), delay_s=2.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--record", type=record_path, required=True, help="evidence JSON output path"
    )
    args = parser.parse_args(argv)

    from openai import OpenAI

    client = OpenAI(timeout=120.0, max_retries=0)  # creates are not idempotent
    record = SmokeRecord(provider="openai_agents_api", sdk=SDK, model=MODEL)
    ledger = CleanupLedger(record)
    try:
        run_session(client, record, ledger, provision(client, record, ledger))
    except Exception as exc:  # recorded; cleanup still runs
        record.error("smoke", exc)
    finally:
        ledger.run()
        record.write(args.record)
    if record.findings.get("model_accepted") is False:
        return EXIT_MODEL_REFUSED
    return 1 if record.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
