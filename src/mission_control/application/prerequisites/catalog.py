"""Human account and host prerequisites (SPEC-05 Â§3 and SPEC-06 Â§10).

Generated environment steps are supplied separately by the binding's kit generator.
Optional trace export and funding-gated self-hosted setup never block hosted launches.
"""

from __future__ import annotations

from datetime import timedelta

from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.prerequisites import (
    Freshness,
    LaneBlock,
    OwnerPrerequisite,
    PrerequisiteScope,
    Verification,
    VerificationMethod,
)

# Identifier, provider, scope, title, owner instructions, verification method.
_ITEMS = {
    "C1": (
        "cursor",
        "account",
        "Enable cloud spending",
        "Open Cursor Dashboard â†’ Cloud Agents and accept the spend-limit prompt.",
        "probe_mission",
    ),
    "C2": (
        "cursor",
        "account",
        "Enable Privacy Mode",
        "Select Privacy Mode (not Legacy) in Cursor Dashboard â†’ Cloud Agents.",
        "probe_mission",
    ),
    "C3": (
        "cursor",
        "repo",
        "Grant Cursor repository access",
        (
            "Install the Cursor GitHub app on every selected repository and connect your Git "
            "account."
        ),
        "api_probe",
    ),
    "C4": (
        "cursor",
        "account",
        "Store the Cursor API credential",
        (
            "Create a key in Cursor Dashboard â†’ API Keys and store it in the Secret Broker as "
            "secret:cursor/api_key. Do not paste it into this command."
        ),
        "api_probe",
    ),
    "C5": (
        "cursor",
        "account",
        "Verify per-run environment delivery",
        (
            "Verify launch envVars support for this Cursor account with the bounded environment "
            "probe."
        ),
        "probe_mission",
    ),
    "C7": (
        "cursor",
        "repo",
        "Resolve environment.json ownership",
        (
            "Remove a foreign .cursor/environment.json or explicitly bind it. An MC-owned file "
            "must match the selected kit and policy."
        ),
        "file_check",
    ),
    "C9": (
        "cursor",
        "host",
        "Sign in on the Cursor worker",
        (
            "Sign in to the pinned Cursor CLI on the worker and verify workspace cleanup "
            "preserves the repository root."
        ),
        "file_check",
    ),
    "A1": (
        "anthropic",
        "account",
        "Enable Claude cloud access",
        (
            "Confirm the account's Claude cloud plan and that its organization permits cloud "
            "sessions."
        ),
        "api_probe",
    ),
    "A2": (
        "anthropic",
        "org",
        "Enable remote sessions",
        (
            "For Team or Enterprise, have the organization owner enable remote sessions and "
            "Routines; otherwise attest that this does not apply."
        ),
        "attestation",
    ),
    "A3": (
        "anthropic",
        "repo",
        "Connect Claude repositories",
        "Install the Claude GitHub App on every selected repository or complete /web-setup.",
        "api_probe",
    ),
    "A7": (
        "anthropic",
        "account",
        "Configure routine-trigger credentials",
        (
            "If using routine-trigger launches, create the routine and store its trigger token "
            "in the broker; otherwise attest that this path is unused."
        ),
        "attestation",
    ),
    "A8": (
        "anthropic",
        "host",
        "Prepare the Claude worker",
        (
            "Install the pinned Claude CLI in WSL2 and complete setup-token or interactive "
            "login on that worker."
        ),
        "file_check",
    ),
    "X1": (
        "openai",
        "account",
        "Enable Codex Cloud",
        (
            "Confirm the ChatGPT plan permits Codex Cloud and the Enterprise administrator has "
            "enabled it when applicable."
        ),
        "api_probe",
    ),
    "X2": (
        "openai",
        "repo",
        "Connect Codex repositories",
        (
            "Connect GitHub.com to ChatGPT and select each repository; verify with codex cloud "
            "list --json."
        ),
        "api_probe",
    ),
    "X4": (
        "openai",
        "host",
        "Sign in to Codex on the worker",
        (
            "Run codex login --device-auth on the worker and keep auth.json refreshed. Never "
            "paste its contents here."
        ),
        "file_check",
    ),
    "X6": (
        "openai",
        "host",
        "Prepare the Codex worker",
        "Install the pinned Codex CLI in the WSL2 worker environment.",
        "file_check",
    ),
    "MA1": (
        "anthropic",
        "account",
        "Configure Managed Agents access and limits",
        (
            "Select the Anthropic Console organization/workspace, set spend limits, and store "
            "ANTHROPIC_API_KEY in the Secret Broker; verify GET /v1/agents."
        ),
        "api_probe",
    ),
    "MA2": (
        "anthropic",
        "environment",
        "Register the Managed Agents webhook",
        (
            "Register the generated Anthropic webhook URL in Console and store its signing "
            "secret in the broker."
        ),
        "probe_mission",
    ),
    "MA4": (
        "github",
        "repo",
        "Provide scoped read-only repository credentials",
        (
            "Create a fine-grained read-only GitHub token for each selected repository and "
            "store it in the broker. Only publication: agent may require a write token."
        ),
        "api_probe",
    ),
    "MA5": (
        "anthropic",
        "account",
        "Grant MCP OAuth access",
        (
            "Complete interactive OAuth grants for selected OAuth MCP servers. Attest not "
            "applicable only when the pack selects none."
        ),
        "api_probe",
    ),
    "OA2": (
        "openai",
        "environment",
        "Register the Agents API webhook",
        ("Register the generated OpenAI webhook URL and store its signing secret in the broker."),
        "probe_mission",
    ),
    "OA1": (
        "openai",
        "account",
        "Configure Agents API access and limits",
        (
            "Use a dedicated OpenAI project with a spend limit. Store its restricted Agents, "
            "Responses, Vaults and Traces API key in the broker."
        ),
        "api_probe",
    ),
    "M1": (
        "mission_control",
        "environment",
        "Verify Signal Ingress",
        (
            "Configure the application Signal Ingress and verify a signed readiness signal "
            "reaches its durable inbox."
        ),
        "probe_mission",
    ),
    "M2": (
        "github",
        "account",
        "Configure publication credentials",
        (
            "Configure the Mission Control GitHub App or owner gh credential for governed "
            "branch preparation and publication."
        ),
        "api_probe",
    ),
    "M3": (
        "mission_control",
        "repo",
        "Configure the application knowledge repository",
        (
            "Select the application-owned knowledge repository and verify read/write access for "
            "its publication service."
        ),
        "api_probe",
    ),
    "M4": (
        "mission_control",
        "host",
        "Initialize the Secret Broker",
        (
            "Store required credentials in the local Secret Broker; verify required names "
            "without printing values."
        ),
        "file_check",
    ),
}

_LANES = {
    "cursor_cloud": (
        "C1",
        "C2",
        "C3",
        "C4",
        "C5",
        "C7",
        "M1",
        "M2",
        "M3",
        "M4",
    ),
    "cursor_local": (
        "C9",
        "M4",
    ),
    "claude_agent_sdk": (
        "A8",
        "M4",
    ),
    "codex": (
        "X4",
        "X6",
        "M4",
    ),
    "claude_cloud": (
        "A1",
        "A2",
        "A3",
        "A7",
        "M1",
        "M2",
        "M3",
        "M4",
    ),
    "codex_cloud": (
        "X1",
        "X2",
        "M1",
        "M2",
        "M3",
        "M4",
    ),
    "claude_managed": (
        "MA1",
        "MA2",
        "MA4",
        "MA5",
        "M1",
        "M2",
        "M3",
        "M4",
    ),
    "codex_agents": (
        "OA1",
        "OA2",
        "MA4",
        "M1",
        "M2",
        "M3",
        "M4",
    ),
}


def account_prerequisites(profile: LaneProfile) -> tuple[OwnerPrerequisite, ...]:
    """Return stable, lane-scoped records; evidence never crosses provider lanes."""
    result = []
    for code in _LANES.get(profile.value, ()):
        provider, scope, title, step, method = _ITEMS[code]
        result.append(
            OwnerPrerequisite.model_validate(
                {
                    "id": f"{profile.value}.owner.{code.lower()}",
                    "provider": provider,
                    "scope": PrerequisiteScope(scope),
                    "title": f"{code}: {title}",
                    "why": "This owner-controlled prerequisite must be satisfied before launch.",
                    "blocks": (LaneBlock(lane=profile),),
                    "steps": (step,),
                    "verify": Verification(
                        method=VerificationMethod(method),
                        probe=None if method == "attestation" else f"prerequisite:{code.lower()}",
                    ),
                    "freshness": Freshness(revalidate_after=timedelta(days=30)),
                }
            )
        )
    return tuple(result)
