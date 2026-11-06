"""Anthropic Managed Agents adapter for the `claude_managed` lane profile (SPEC-06 section 4).

- `client`: the control-plane HTTP client (agents, environments, skills, vaults);
- `pack`: checked-in pack files (R30) and the digests resources are keyed by;
- `prepare`: the digest-keyed sync that creates resources once and reuses them.

Importing this package imports no provider SDK.
"""
