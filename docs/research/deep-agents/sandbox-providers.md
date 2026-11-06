---
type: Research
title: Deep Agents sandbox providers and what Mission Control wires
description: Which sandbox backends deepagents 0.7.5 ships and documents, what a sandbox backend must implement, and which of them Mission Control has a factory for. Daytona is admitted by contract but has no factory.
tags: [mission-control, research, deep-agents, sandbox, daytona, langsmith, docker]
subject: deepagents sandbox backends (BackendProtocol, SandboxBackendProtocol, BaseSandbox) and the providers around them
versions: [deepagents==0.7.5, langgraph==1.2.10, langchain-daytona 0.0.8 (not installed)]
sources:
  - .venv/Lib/site-packages/deepagents/backends/ (installed 0.7.5 source, read 2026-11-01)
  - docs/research/deep-agents/surface-0.7.5.md (section 5, from DEEP-AGENTS-SURFACE-2026-10-22)
  - docs/research/daytona/sandbox-tiers.md
  - src/mission_control/adapters/deep_agents/materializer.py, docker_sandbox.py
observed: 2026-11-01 (source read) and 2026-10-22 (docs sheet)
confidence: high for installed-source and Mission Control facts; medium for provider list (docs, not source); unverified items are marked
used_by: [deep-agents-lane, agent-configuration, workspace-closure, environments]
date: 2026-11-01
---

# Deep Agents sandbox providers

## What deepagents 0.7.5 ships

`deepagents.backends` exports `StateBackend`, `FilesystemBackend`, `LocalShellBackend`, `StoreBackend`,
`CompositeBackend`, `LangSmithSandbox` and `ContextHubBackend` (installed `backends/__init__.py`). Only
`LangSmithSandbox` (`backends/langsmith.py:56`) is a sandbox provider in the package. There is **no
Daytona, Docker, Modal or E2B backend in 0.7.5**; those are separate packages or, for Docker, Mission
Control's own class.

## The contract a sandbox backend implements

- `BackendProtocol`: `ls`, `read`, `grep`, `glob`, `write`, `edit`, `delete`, `upload_files`,
  `download_files`, each with an async twin (`backends/protocol.py`).
- `SandboxBackendProtocol` adds `id` and `execute(command, timeout)`.
- `BaseSandbox` (`backends/sandbox.py:952`) implements every file operation on top of `execute`, so a
  provider only has to supply `execute`, `upload_files`, `download_files` and `id`.
- `FilesystemMiddleware` exposes the `execute` tool only when the backend is a sandbox
  (`FilesystemMiddleware` row of the middleware table in `surface-0.7.5.md`).
- Seeding and retrieval (`upload_files`, `download_files`) use provider-native transfer, separate from the
  agent's tool plane [docs, 2026-10-22].
- Sandbox state is external to LangGraph checkpoints; a restored checkpoint does not restore the sandbox
  [docs, 2026-10-22]. Mission Control therefore captures a workspace closure at attempt end
  ([workspace closure](../../knowledge/workspace-closure.md)).
- Sandboxes do not stop context injection or network exfiltration unless the provider blocks the network
  [docs, 2026-10-22].

## Providers named by the LangChain docs (2026-10-22, not checked against source)

Daytona, Modal, AgentCore (AWS), Runloop, E2B, Vercel, OpenSandbox, Kubernetes, NVIDIA OpenShell, Islo,
Upstash Box, Leap0, Novita, Superserve, LangSmith, and others. Daytona's integration is `langchain-daytona`
0.0.8 with `DaytonaSandbox(sandbox=Daytona().create())` as the `backend` [daytona research, source LC].
`temporalio.contrib.deepagents.TemporalBackend` wraps a filesystem, shell or store backend so each file or
shell operation becomes a `deepagents.backend_op` Activity (`surface-0.7.5.md` section 5); Mission Control
does not use it.

## What Mission Control wires (verified in code)

| Backend (`DeepAgentSandboxComponent.backend`) | Factory | Where registered |
| --- | --- | --- |
| `state` | `StateSandboxFactory` (`materializer.py:282`), in-memory `StateBackend` | `deployment_composition.py:516` |
| `langsmith` | `LangSmithSandboxFactory` (`materializer.py:491`), `SandboxClient.create_sandbox`, deleted on exit | `deployment_composition.py:523` (the `else` branch) |
| `docker` | `DockerSandboxFactory` (`docker_sandbox.py:120`): `--network none`, read-only root, tmpfs, `--cap-drop ALL`, 64 pids | `deployment_composition.py:518` |
| `daytona` | **none** | admitted by `contracts.py:686` and `:1207`, named by closure (`adapters/deep_agents/workspace_closure.py:97`) and redaction (`domain/frames/body.py:41`) |

A `daytona` sandbox profile in a launch bindings file passes the contract and the compile check (the
placement's `sandbox_backends` must list it), but `deployment_composition.py:523` registers the
**LangSmith** factory for any backend that is not `state` or `docker`, and that factory raises
`DeepAgentUnsupportedPlacement("LangSmith factory cannot change placement")` at run time. The manifest option
`provider_options.deep_agents.sandbox_backend` is `Literal["state","docker","langsmith"]`
(`domain/authoring/provider_options.py:83`), so a manifest cannot pin it either.

## What adding a provider needs (derived, not tried)

1. A factory `Callable[[DeepAgentExecutionBinding, ResolvedSecrets], AsyncContextManager[BackendProtocol]]`
   (`materializer.py:115`) that refuses a binding for another backend.
2. A branch in `deployment_composition.py` before the `else`, and a dependency in `pyproject.toml`.
3. The `Literal` in `provider_options.py:83` and any capability-matrix row (`describe.py:153`).
4. Network projection and tier facts in `network.py` ([sandbox tiers](../daytona/sandbox-tiers.md)).
5. A scaffold placement that lists the backend in `sandbox_backends`, and a launch-bindings
   `sandbox_profiles` entry.

Unverified: whether `langchain-daytona` 0.0.8 targets deepagents 0.7.5 (its pin was not read), and the
async behaviour of its `execute`.

## Citations

- Installed source: `deepagents/backends/{protocol,sandbox,langsmith}.py` at 0.7.5.
- [Surface sheet note](surface-0.7.5.md); [Daytona tiers](../daytona/sandbox-tiers.md).
- Code: `src/mission_control/adapters/deep_agents/materializer.py`, `docker_sandbox.py`,
  `src/mission_control/adapters/temporal/deployment_composition.py`.
