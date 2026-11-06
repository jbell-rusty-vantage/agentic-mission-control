---
type: Concept
category: operations
title: Owner probe bootstrap
description: "Explicit bounded operator probes and exact credential verification before normal hosted mission admission."
tags: [mission-control, prerequisites, providers, implementation]
aliases: [owner probe, credential verification, probe bootstrap, bounded probe]
questions:
  - How do I verify hosted credentials with a bounded probe?
  - What does the owner probe spend?
  - Which probes exist and which are paid?
updated: 2026-11-01
---

# Owner probe bootstrap

Some prerequisites need a real session and ingress delivery before an ordinary mission may
launch. The operator-only `python -m mission_control.bootstrap.owner_probe` module starts one
isolated, already-admitted StageGraph operation. It leaves the normal manifest/direct-run and
chain prerequisite guards intact. It never creates receipts or labels a lane qualified.

Submit an isolated one-operation probe manifest without starting it. Its admitted limits must
be positive and at most USD 1, 4,000 tokens, eight tool calls and 120 seconds. The sealed provider
binding allows at most three turns and one segment; Managed Agents also needs a provider
`max_list_cost` no larger than that paid cap. The OpenAI limit remains a Mission Control budget
and bounded dispatch duration, not a claimed provider-side hard spend cap. No delegates,
additional MCP/tool bindings or operation secret references are admitted by this bootstrap.

First freeze and inspect the actual admitted template without contacting a provider:

```powershell
python -m mission_control.bootstrap.owner_probe --describe `
  --application-binding <reviewed-binding.json> --request-scope <canonical-scope> `
  --run-id <admitted-run> --operation-key <template-key> `
  --prerequisite-id <current-scoped-id> --purpose signal_receipt
```

Use `signed_webhook` for the provider webhook prerequisite. The output contains a `plan` and
its matching `verification_binding`, containing identifiers and digests only. Save the plan
outside Git and append the reviewed verification binding to `MISSION_CONTROL_OWNER_PROBES_PATH`.
The plan pins the exact template, ERC and provider execution binding. Receipt verification's
`binding_digest` is the actual stored preparation/HEID binding digest, currently the ERC for
the hosted API lanes; it is distinct from `provider_binding_digest`.

Review the plan, then run the same command with `--plan <plan.json>` instead of `--describe`.
That checks configuration without a provider call. Execution additionally requires both
`--execute` and an explicit finite `--paid-budget-usd` at least the plan's cap and no more than
one dollar. Workers must already serve the configured StageGraph coordinator and sealed
provider activity queues, with the existing reviewed provider projection and ingress setup.

The standalone probe does not run a family coordinator or accept mission completion. After
its operation settles, the isolated run-control record remains `ACTIVE`; that status does not
mean a provider session or capacity reservation remains active. Use the existing governed
cancellation/reconciliation procedure if a terminal run record is needed; bootstrap does not
invent obligation evidence or a terminalization proposal. A timeout requests workflow
cancellation before its server execution bound and allows bounded cleanup time. A cancellation
request or failed workflow is never proof that provider cleanup completed; inspect its state.

The operation follows the existing actual worker lifecycle: HEID admission, preparation,
native session, persisted frames and cleanup. The final trusted check requires real correlated
preparation/ingress evidence; a completed text response alone never verifies a prerequisite.
Webhook delivery can arrive later. Retrying the same scoped run/template uses the same workflow
ID with duplicate reuse forbidden; another prerequisite can consume that same actual run without
buying another execution. After a timeout, inspect cancellation and cleanup before proceeding.

For MA5, preflight derives OAuth applicability from the exact selected catalog definitions.
It omits MA5 only when that trusted selection proves no OAuth is needed. Seed-pack MCP URLs
without matching selected catalog authentication metadata remain blocked. Selected OAuth MCP
servers require exact vault/credential/server bindings and a provider `mcp_oauth_validate` result
with `status: valid`. Provider response bodies and refresh credentials never enter evidence.

A hosted repository credential additionally needs current verified MA4 evidence for its exact
Broker source, scope, AuthPin/account, repository URL/ref/commit, ERC and provider binding. The
evidence includes the stable reviewed probe-configuration digest. Changing the source or sealed
context invalidates custody permission; a source name containing “readonly” grants nothing.
Organization API credentials cannot be published into the repository vault.

Built / specified / goal: the bootstrap and its bounded limits are implemented and tested with a fixture provider; no paid probe has
run and no profile is thereby qualified ([owner prerequisites](owner-prerequisites.md), [qualification](qualification.md)).

## Citations

- [Bootstrap CLI](../../src/mission_control/bootstrap/owner_probe.py) and
  [bounded request](../../src/mission_control/application/prerequisites/bootstrap_probe.py).
- [Exact readonly proof](../../src/mission_control/bootstrap/hosted_readonly.py).
- Anthropic [credential retrieval](https://platform.claude.com/docs/en/api/beta/vaults/credentials/retrieve)
  and [OAuth validation](https://platform.claude.com/docs/en/api/beta/vaults/credentials/mcp_oauth_validate).
- `tests/unit/prerequisites/test_bootstrap_dispatch.py`, `test_owner_bootstrap.py`,
  `test_oauth.py`, `test_hosted_readonly.py`; real PostgreSQL
  `tests/integration/postgres/test_hosted_readonly_probe.py`. These tests use synthetic provider
  responses and do not establish paid-provider qualification.

The offline-provider runtime test `tests/integration/temporal/test_owner_bootstrap_runtime.py`
runs actual PostgreSQL and Temporal with isolated queues. It proves standalone dispatch,
recorded unit admission, archived fixture session, released PostgreSQL placement capacity and
duplicate reuse. Its provider transport and governed operation boundary are fixtures; it does
not prove paid ingress, real provider behavior or mission acceptance.
