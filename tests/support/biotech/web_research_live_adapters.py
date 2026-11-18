"""Builders, constants and fakes that other test files import.

Moved from integrations/biotech/tests/web_research/test_web_research_live_adapters.py.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from biotech_mission_adapters.adapters.infrastructure.web_research_runtime import (
    BrowserSubprocessRequest,
    BrowserSubprocessResult,
)
from biotech_mission_adapters.domain.coordinator.web_research_runtime import (
    ReviewedRuntimeArtifactBinding,
)
from mission_control.domain.authoring.contracts import DefinitionKind, ExactDefinitionRef


def exact_ref(kind: DefinitionKind, logical_id: str, digit: str) -> ExactDefinitionRef:
    return ExactDefinitionRef(
        kind=kind,
        logical_id=logical_id,
        revision=2,
        digest="sha256:" + digit * 64,
    )


BROWSER_REF = exact_ref(
    DefinitionKind.SKILL,
    "skill.agent-browser",
    "3",
)
FIRECRAWL_RUNTIME = ReviewedRuntimeArtifactBinding(
    package_name="firecrawl-mcp",
    package_version="3.22.4",
    module_locator="workspace://.tools/reviewed/firecrawl/dist/index.js",
    module_digest="sha256:69e305ec3cf14ddbfe62a7c509e218a9ec4b44c82604bffa023159130769498b",
    tools_snapshot_digest="sha256:b00747ddea6305fc08efcdd9fcaddcd69f62f0c3a59e2901d045475600c53bf2",
)
TAVILY_RUNTIME = ReviewedRuntimeArtifactBinding(
    package_name="tavily-mcp",
    package_version="0.2.21",
    module_locator="workspace://.tools/node_modules/tavily-mcp/build/index.js",
    module_digest="sha256:60d2f3d0553f4879225990fd42e43265244ef5ac6d02799f6bafa5aef2d2d05e",
    tools_snapshot_digest="sha256:65d256e03f0e82bb425b089cecf372f91f4c33b0c32fd2a94421475f2a9c922d",
)
BROWSER_RUNTIME = ReviewedRuntimeArtifactBinding(
    package_name="agent-browser",
    package_version="0.33.0",
    module_locator="workspace://.tools/node_modules/agent-browser/bin/agent-browser.js",
    module_digest="sha256:8e382f4a5ba22f45e1e0339abfe5a55ed95a19540b16a69ee3faf31c8dc8216a",
)


class FakeBrowserRunner:
    def __init__(self) -> None:
        self.requests: list[BrowserSubprocessRequest] = []

    async def run(
        self,
        request: BrowserSubprocessRequest,
    ) -> BrowserSubprocessResult:
        self.requests.append(request)
        command = request.arguments[-1]
        if "screenshot" in request.arguments:
            screenshot = Path(request.arguments[-1])
            await asyncio.to_thread(
                screenshot.write_bytes,
                b"\x89PNG\r\n\x1a\nsafe-screenshot",
            )
            payload: object = {"success": True}
        elif command == "url":
            payload = {"data": {"value": "https://upgrade.example/technology"}}
        elif command == "title":
            payload = {"data": {"value": "Upgrade Labs technology"}}
        elif "innerText?.slice(0, 4000)" in command:
            payload = {"data": {"value": "Public rendered evidence"}}
        else:
            payload = {"success": True}
        return BrowserSubprocessResult(
            exit_code=0,
            stdout=json.dumps(payload).encode(),
            stderr=b"",
        )


class FakeScreenshots:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def store(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return "belllabs://browser-evidence/screenshots/verified-1"
