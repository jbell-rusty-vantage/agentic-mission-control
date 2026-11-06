import json

from adapters.common import REPORT_SCHEMA


def build_argv(job, session_id=None, windows=False):
    args = ["-p", "--output-format", "stream-json", "--verbose",
            "--permission-mode", {"read-only": "dontAsk", "edit": "acceptEdits", "full": "bypassPermissions"}[job["permissions"]],
            "--permission-prompts", "none", "--setting-sources", "project",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--json-schema", json.dumps(job.get("output_schema") or REPORT_SCHEMA)]
    if job["permissions"] != "full":
        tools = ["Read", "Grep", "Glob"]
        if job["permissions"] == "edit":
            tools += ["Edit", "Write"] + [f"Bash({c})" for c in job["allow_commands"]]
        args += ["--allowedTools", ",".join(tools)]
    args += ["--max-turns", str(job["budget"]["max_turns_per_iteration"])]
    if job["budget"]["max_usd"] is not None:
        args += ["--max-budget-usd", str(job["budget"]["max_usd"])]
    model = job["model"]
    if model["name"]:
        args += ["--model", model["name"]]
    if model["effort"]:
        args += ["--effort", model["effort"]]
    if session_id:
        args += ["--resume", session_id]
    else:
        args += ["--session-id", job["new_session_id"]]
    return args
