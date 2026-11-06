# S0 local harness probe templates

These three mission/v2 documents compile offline against the real common, AI Engineer and
qualification seed catalog. They contain one agent stage and a separate Human REVIEW gate.
The required report uses published `schema.s0-probe-report@1`; schema validity records evidence
shape and does not establish provider identity, acceptance or lane qualification.

## Owner selection before launch

`OWNER-SELECT/s0-fixture`, `OWNER-SELECT-immutable-ref` and `OWNER-SELECT-s0-reviewer` are
conspicuous unresolved template values, not existing resources or environment substitution.
Copy a template into private working material and replace these with an explicitly reviewed
fixture repository path/ref and a reviewer principal/grant. Choose a disposable tracked
repository with instructions and a test; do not use a product checkout without authority.
The compiler does not prove that a path exists, a reviewer is authorized or a host is ready.

Model profiles `claude.default`, `codex.default`, `cursor.default` and host profiles
`worker.linux.default`/`worker.linux.wsl` are deployment reference keys, not observed facts.
Select their actual settings, installed CLI/SDK versions, account and placement in reviewed
launch bindings. Claude uses the existing `claude-sdk-api` auth profile (API billing), Codex
uses `codex-owner-chatgpt`, and Cursor uses `cursor-local-key`; configure those exact profiles
or explicitly reauthor the template. No credential values belong in these files.

Start from the current [versioned bindings example](../../../../deployments/examples/manifest-launch-bindings.multi-provider.codex-0.162.1.example.json)
and [auth profile shapes](../../../../deployments/examples/provider-auth-profiles.example.json).
The examples are shapes containing unresolved owner selections, not admitted bindings.
Use `python -m mission_control.bootstrap.preflight compose-bindings --base <private-base.json>
--selections <reviewed-selections.json> --out <private-resolved.json>
--summary-out <private-identity.json>` and the existing owner preflight procedure. Supply actual
image/runtime/agent-profile/configuration evidence; file digests alone do not prove loading.
Codex ChatGPT requires explicit owner CODEX_HOME, selected worker binary and login readiness;
WSL uses native Linux CLI/Git/home and ext4 worktree roots. Do not copy Windows environments.

## Evidence and operational limits

The exact admitted skill pin in each template comes from a committed production skill seed.
Preserve that immutable source version; delivered, read-back and exercised are separate facts.
Do not swap a newer local skill file into the sealed bundle. Review which admitted tool family
will be allowed and denied on the selected lane. Unsupported required enforcement must refuse
before create; a prompt requesting denial cannot replace a trusted permission method.

An operator supplies external scoped inject/cancel and caller wakeup receipts. Cancellation
may prevent the report/review stage from completing: retain its native receipt as a separate
cancelled-run proof, and use a separately authorized completion run when needed. Nine local
caller/lane combinations and the Temporal Cloud variant remain SPEC-09 acceptance requirements;
these three templates do not replace that matrix or grant its paid execution authority.

Register actual output bytes immutably before worktree cleanup. Review identity/configuration,
skill evidence, tool decisions, control acknowledgements, caller wakeup, usage unknowns and
cleanup liabilities against native receipts. Missing evidence remains unknown/unrun; an agent
cannot attest its way to acceptance. The Human REVIEW gate needs an authorized reviewer and
never sets profile qualification. No automatic publication, deployment or global auth setup.

## Offline verification

`tests/unit/authoring/test_s0_production_manifests.py` builds only `common`, `ai-engineer` and
`qualification` seed directories through `build_catalog`; it adds no test-only schema or tool
rows. Its local helper loads successive committed revisions in exact revision order and
verifies every digest, including current observe 0.3.1 revision 3. It checks zero compile blockers, required schema bindings and existing completion
support, plus missing schema and unsupported hard-pause negatives. Missing schema authority
may remain describable during authoring but is refused at fresh-start materialization.

No actual owner repository/bindings, provider create, model execution, permission enforcement,
WSL process tree, immutable storage registration, inject/cancel, wakeup or cleanup is qualified
by these tests. Follow [MO-71](../../../../docs/specs/archive/materialization-observation-2026-10/issues/MO-71-s0-probe-manifests-for-all-three-local-lanes.md)
and [SPEC-09](../../../../docs/specs/archive/materialization-observation-2026-10/SPEC-09-local-harness-path.md) for the complete acceptance boundary.
