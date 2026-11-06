"""Secret Broker adapters (SPEC-01 section 4; ADR-0043).

- `sources`: the worker environment, a secret-store file outside every repository, the owner's
  keyring and Supabase Vault;
- `minted`: a process-local minted credential store (digests only);
- `vaults`: Anthropic and OpenAI vault credentials as provider secret stores.

Cursor's environment and team secrets are in `adapters/cursor/secrets.py`. Importing this
package imports no provider SDK.
"""
