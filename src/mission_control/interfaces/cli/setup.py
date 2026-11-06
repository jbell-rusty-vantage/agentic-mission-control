"""Render the repository wizard pattern; credentials remain in provider/broker UIs."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Protocol

import httpx

from mission_control.application.prerequisites.setup import SetupPlan
from mission_control.domain.prerequisites import PasteStep, PrerequisiteStanding
from mission_control.interfaces.cli.exits import exit_status

_PORTALS = {
    "cursor": "https://cursor.com/dashboard",
    "anthropic": "https://platform.claude.com",
    "openai": "https://platform.openai.com",
}


class SetupClient(Protocol):
    def prerequisite(
        self, action: str, body: dict[str, Any], target: str | None = None
    ) -> httpx.Response: ...


def render_wizard(plan: SetupPlan, *, application: str, url: str, manifest: str | None) -> str:
    """Every server string is a shell literal. The copied helper library is unchanged."""
    library = Path(__file__).with_name("wizard_library.sh").read_text(encoding="utf-8")
    q = shlex.quote
    command = f"missionctl --application {q(application)} --url {q(url)}"
    items = [
        item for item in plan.items if item.assessment.standing is not PrerequisiteStanding.MET
    ]
    lines = [
        library,
        "# STAGES: generated from the scoped setup report.",
        f"TOTAL_STAGES={len(items)}",
        'banner "Mission Control owner setup"',
        'say "Enter credentials only in provider pages or the local Secret Broker."',
    ]
    for item in items:
        prerequisite = item.prerequisite
        lines.append(f"stage {q(prerequisite.title)}")
        portal = _PORTALS.get(prerequisite.provider)
        if prerequisite.id.startswith("claude_cloud."):
            portal = "https://claude.ai/code"
        elif prerequisite.id.startswith("codex_cloud."):
            portal = "https://chatgpt.com/codex"
        if portal:
            lines.append(f"open_url {q(portal)}")
        contents = {content.ref: content for content in prerequisite.generated}
        for step in prerequisite.steps:
            if isinstance(step, PasteStep):
                lines.extend(
                    (
                        f"step {q('Paste into ' + step.paste)}",
                        f"say {q(contents[step.content_ref].content)}",
                    )
                )
            else:
                lines.append(f"step {q(step)}")
        attest = (
            f"{command} prereq attest {q(prerequisite.id)} "
            f"--definition-digest {q(prerequisite.digest)} --json"
        )
        needs_identifier = any(
            isinstance(step, str) and "Record the public identifier" in step
            for step in prerequisite.steps
        )
        lines.extend(('if confirm "Have you completed these owner steps?"; then',))
        if needs_identifier:
            lines.extend(
                (
                    '  OWNER_ENV_ID=""',
                    '  ask OWNER_ENV_ID "Public provider environment ID (never a credential):"',
                    f'  if [[ -z "$OWNER_ENV_ID" ]] || ! {attest} --value "$OWNER_ENV_ID"; '
                    f"then SKIPPED+=({q(prerequisite.id)}); fi",
                )
            )
        else:
            lines.append(f"  if ! {attest}; then SKIPPED+=({q(prerequisite.id)}); fi")
        if prerequisite.verify.method.verifies:
            verify = (
                f"{command} prereq verify {q(prerequisite.id)} "
                f"--definition-digest {q(prerequisite.digest)} --json"
            )
            lines.append(f"  if ! {verify}; then SKIPPED+=({q(prerequisite.id + ' probe')}); fi")
        lines.extend(("else", f"  SKIPPED+=({q(prerequisite.id)})", "fi"))
    for blocker in plan.blockers:
        lines.extend((f"warn {q(blocker)}", f"SKIPPED+=({q(blocker)})"))
    lines.extend(
        (
            "if (( ${#SKIPPED[@]} )); then",
            '  warn "Setup still has pending items:"',
            '  for pending in "${SKIPPED[@]}"; do note "$pending"; done',
            "  exit 2",
            "fi",
        )
    )
    if manifest:
        lines.append(f"{command} preflight {q(str(Path(manifest).resolve()))} --json")
    lines.extend(("finish", ""))
    return "\n".join(lines)


def add_setup_parsers(groups: Any, common: argparse.ArgumentParser) -> None:
    setup = groups.add_parser("setup", parents=[common])
    setup.add_argument("target", help="provider or lane profile")
    setup.add_argument("--manifest", help="use this manifest's exact generated environment steps")
    setup.add_argument("--script", help="write a reviewable bash wizard without running it")
    setup.set_defaults(action="setup")
    prereq = groups.add_parser("prereq", parents=[common])
    actions = prereq.add_subparsers(dest="action", required=True)
    for name in ("attest", "verify"):
        action = actions.add_parser(name, parents=[common])
        action.add_argument("prerequisite_id")
        action.add_argument("--definition-digest", required=True)
        if name == "attest":
            action.add_argument("--value", help="public environment identifier, never a credential")
            action.add_argument("--expires-at", help="UTC ISO8601 credential expiry, when known")


def run_setup(client: SetupClient, args: argparse.Namespace, *, application: str, url: str) -> int:
    if args.group == "prereq":
        body = {"definition_digest": args.definition_digest}
        for name in ("value", "expires_at"):
            if getattr(args, name, None) is not None:
                body[name] = getattr(args, name)
        response = client.prerequisite(args.action, body, args.prerequisite_id)
        print(json.dumps(response.json()))
        return exit_status(response.status_code)
    body = {"target": args.target}
    if args.manifest:
        body["manifest_yaml"] = Path(args.manifest).read_text(encoding="utf-8")
    response = client.prerequisite("setup", body)
    if not response.is_success:
        print(json.dumps(response.json()))
        return exit_status(response.status_code)
    plan = SetupPlan.model_validate(response.json())
    if getattr(args, "json", False):
        print(plan.model_dump_json())
        return 0 if plan.ready else 2
    script = render_wizard(plan, application=application, url=url, manifest=args.manifest)
    if args.script:
        path = Path(args.script)
        # Generated procedures may contain repository identities; owner-only file permissions.
        with path.open("x", encoding="utf-8", newline="\n") as output:
            output.write(script)
        path.chmod(0o700)
        print(f"Run: bash {shlex.quote(str(path.resolve()))}")
        return 0
    if not sys.stdin.isatty():
        raise ValueError("interactive setup needs a terminal; use --script PATH or --json")
    bash = shutil.which("bash")
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if os.name == "nt" and git_bash.is_file():
        bash = str(git_bash)
    if not bash:
        raise ValueError("bash is required; use --script PATH to generate the procedure")
    with tempfile.TemporaryDirectory(prefix="mc-owner-setup-") as directory:
        path = Path(directory) / "setup.sh"
        path.write_text(script, encoding="utf-8", newline="\n")
        path.chmod(0o700)
        return subprocess.run([bash, str(path)], check=False).returncode
