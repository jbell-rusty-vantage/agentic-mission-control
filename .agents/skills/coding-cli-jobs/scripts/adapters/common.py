"""Closed option mapping and provider frame parsing."""
import json
import re


REPORT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["status", "summary", "handoff", "blockers"],
    "properties": {
        "status": {"enum": ["done", "continue", "blocked"]},
        "summary": {"type": "string"}, "handoff": {"type": "string"},
        "blockers": {"type": "array", "items": {"type": "string"}},
    },
}


def extract_report(text):
    """Only accept a complete JSON object or a final fenced JSON report."""
    candidates = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text)
    for candidate in [text.strip(), *reversed(candidates)]:
        try:
            value = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    return None


class Frames:
    def __init__(self, cli, auth="subscription"):
        self.cli = cli
        self.auth = auth
        self.session_id = None
        self.model = None
        self.report = None
        self.failure = None
        self.cost = None
        self.tokens = None
        self.terminal = False
        self.context_error = False

    def parse_event(self, event):
        serialized = json.dumps(event).lower()
        if any(marker in serialized for marker in ("context_length_exceeded", "context window exceeded", "compaction failed")):
            self.context_error = True
        kind = event.get("type")
        if kind == "thread.started":
            self.session_id = event.get("thread_id")
        if kind == "system" and event.get("subtype") == "init":
            self.session_id = event.get("session_id")
            self.model = event.get("model")
            source = event.get("apiKeySource")
            bad = (self.cli == "claude" and source in {"ANTHROPIC_API_KEY", "apiKeyHelper", "/login managed key", "api_key"}) or (self.cli == "cursor" and source != "login")
            if self.auth == "subscription" and bad:
                self.failure = "auth_route_mismatch"
        if kind == "assistant":
            message = event.get("message", {})
            self.model = message.get("model", self.model)
            content = message.get("content", [])
            self.report = extract_report("".join(p.get("text", "") for p in content if isinstance(p, dict)))
        if kind == "item.completed" and event.get("item", {}).get("type") == "agent_message":
            self.report = extract_report(event["item"].get("text", ""))
        if kind == "result":
            self.terminal = True
            if self.cli == "claude":
                self.report = event.get("structured_output") or extract_report(event.get("result", ""))
            if event.get("is_error"):
                self.failure = event.get("subtype", "provider_error")
            self.cost = event.get("total_cost_usd", self.cost)
        if kind == "turn.completed":
            self.terminal = True
        if kind in {"error", "turn.failed"}:
            self.failure = "provider_error"
        usage = event.get("usage")
        if isinstance(usage, dict):
            fields = ("input_tokens", "output_tokens") if "input_tokens" in usage else ("inputTokens", "outputTokens")
            if all(isinstance(usage.get(k), int) for k in fields):
                self.tokens = sum(usage[k] for k in fields)

    def final(self):
        return self.report
