"""The `codex_agents` lane: the OpenAI Agents API running the Codex harness (SPEC-06 section 5;
ADR-0050).

- `pack`: the checked-in `codex_agents` pack files and their digests (DECISIONS R30; HL-11);
- `client`: the Agents API prepare resources over `httpx` (saved agents, environment
  templates, prewarm, vaults and credentials);
- `prepare`: the digest-keyed sync that creates each resource once and reuses it.

Importing this package imports no provider SDK.
"""
