---
id: capabilities
title: The capability catalog
summary: The catalog kinds with live counts, and how to list, search, read and pin a capability.
---
A capability is an installed, digest-pinned, admitted asset a mission may bind. The catalog below is this application's; nothing outside it can run.

{{generated}}

## List, search, read, pin

- List a kind by name with {op:list_kind}; page with {op:list_next_page}. Name any kind from the table. A listing reads the published definitions directly, so it is complete.
- Search by meaning with {op:search}. `catalog_search_mode` says who ranked the catalog hits: `hybrid` or `lexical` is the catalog's own search; `definition_scan` is a plain scan of names and descriptions because the search index is not built. Read `notes`: it names every facet that was scanned.
- Read one hit with {op:describe} and the hit's `ref`: its kind, description, the lanes that support it, the capabilities it requires and the names of the secrets it needs.
- Pin it: a hit's `ref` is its Capability Pin (`<id>@<version>#sha256:<digest>`). Write it in the manifest as `{pin: <ref>}`, or write `{search: "...", kind: <kind>, as: <alias>}` and let compile resolve it: `resolution.resolved` then names the pin and the `search_mode` that answered. {op:pin} resolves a query to exactly one pin, or names the candidates when it is ambiguous. A manifest `kind` is `skill_bundle` for the catalog kind `skill`; the other kinds keep their catalog names.

In a manifest, skill bundles, MCP servers, MCP tools and tools go under `environment.capabilities`; subagent profiles under `environment.agents`; hook scripts under `environment.hooks` with their `events`; plugins under `environment.plugins`; a sandbox profile in `environment.sandbox.profile`; a watcher under `controls.watchers` (`mission/v2`).

## Discovered is not runnable

A hit says the definition is published. It runs only when {op:check} admits it on your lane (the capability's host support marks the lane `supported`, the lane supports its item kind, and it fits the Workflow Type's authority ceiling) and {op:compile} resolves it without a blocker. Secrets are named, never carried: the installation resolves them, and {op:preflight} lists the owner setup that is still missing.

## What the catalog lacks

Where this server composes external discovery ({op:whoami}: `server.external_discovery` is `composed`; otherwise these calls do not exist here), {op:discover_mcp} and {op:discover_skills} search public registries and {op:inspect_candidate} runs a static, non-installing inspection of one result (`server.external_discovery_prerequisite`, where present, names what one of them still needs here). Each result is a candidate, recorded as such: it cannot be pinned, bound or run. It becomes a capability only when the installation's owner publishes it to the catalog; tell the user what you found and let them decide.
