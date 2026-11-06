# Run 1 completion and integration report

**Specs 1–6 implementation is integrated. Local validation repairs are complete; external schema and live qualification blockers are recorded below. Main delivery is recorded in the final section.**

Scope is the 49 issues in [the Run 1 plan](RUN-1-SPECS-01-06-PROMPT.md), covering Specs 1–6 plus HL-23 and MO-40. The owner's recovery instruction authorizes merging and pushing main. No live Supabase migration or cloud deployment is included.

## Issue integration ledger

Original heads retain branch provenance; evidence links point to commits present in the integrated history. Additional integration fixes and executed checks are recorded below. Local issue files remain planning records rather than tracker status updates. “Merged” means code integration, not automatic live lane qualification.

| Issue | Status | Implementation branch | Original head | Integrated evidence |
| --- | --- | --- | --- | --- |
| MO-01 | Merged | `mo/mo-01-bundle-custody-composition` | `40613b2` | [code/tests](https://github.com/Overton77/mission-control/commit/40613b26d1c72cf2299303d1fe7b9502d2b70218) |
| HL-05 | Merged | `mo/hl-05-lane-conformance-suite` | `6380d37` | [code/tests](https://github.com/Overton77/mission-control/commit/6380d37ebfc71d1c36df8b97820d1e9ecb820684) |
| HL-06 | Merged | `mo/hl-06-hosted-profile-vocabulary` | `d32e8ba` | [code/tests](https://github.com/Overton77/mission-control/commit/d32e8ba86c653ab7edec31de6e77e4f7548eac7a) |
| MO-04 | Merged | `mo/mo-04-child-env-allowlist` | `9829880` | [code/tests](https://github.com/Overton77/mission-control/commit/982988095f87ea18f27aaca272fe6b10144f852b) |
| MO-05 | Merged | `mo/mo-05-local-lanes-workspace-allocator` | `919954c` | [code/tests](https://github.com/Overton77/mission-control/commit/919954ce23dd3b94f79a2703fe99dc3f578a8f71) |
| MO-06 | Merged | `mo/mo-06-cursor-cloud-env-lease` | `f0d1a65` | [code/tests](https://github.com/Overton77/mission-control/commit/f0d1a659663de79e7702f26a7a0ea1d609af02d3) |
| MO-03 | Merged; live/owner boundary below | `mo/mo-03-codex-kernel-hooks-trust` | `c8f46f4` | [code/tests](https://github.com/Overton77/mission-control/commit/c8f46f470171d01c851c724b21c7355f3cb33918) |
| MO-73 | Merged; live/owner boundary below | `mo/mo-73-claude-sessionstore-restore` | `ca6755c` | [code/tests](https://github.com/Overton77/mission-control/commit/ca6755c9652f36cb111ba7a325951c28b99ad04f) |
| MO-02 | Merged | `mo/mo-02-instruction-layering-config-merge` | `996bdc4` | [code/tests](https://github.com/Overton77/mission-control/commit/996bdc425f191255a220212be86cc7c6e3545600) |
| MO-08 | Merged; live/owner boundary below | `mo/mo-08-wsl2-worker-runbook-preflight` | `9798ba7` | [code/tests](https://github.com/Overton77/mission-control/commit/9798ba7d210be7a0d66759fed8ccecd042e2e420) |
| HL-04 | Merged | `mo/hl-04-remote-session-lane-base` | `b544338` | [code/tests](https://github.com/Overton77/mission-control/commit/b544338d08db8ef0beb22357aa03b50e6fb59850) |
| HL-23 | Merged | `mo/hl-23-provider-smoke` | `276d2cb` | [code/tests](https://github.com/Overton77/mission-control/commit/276d2cbb68014f2d6ca09e8c431b5fa2ec3de644) |
| MO-10 | Merged | `mo/mo-10-mission-v2-environment-additions` | `1b48a39` | [code/tests](https://github.com/Overton77/mission-control/commit/1b48a39e618a7f60677dd1b41feb936af2c8f63a) |
| MO-16 | Merged | `mo/mo-16-environment-preparation-records` | `9bd9f02` | [code/tests](https://github.com/Overton77/mission-control/commit/9bd9f027627bb1d3095a65c4bab987d58cde2fa5) |
| HL-18 | Merged | `mo/hl-18-data-class-retention` | `61644d6` | [code/tests](https://github.com/Overton77/mission-control/commit/61644d6319505fd95dfa301656318e7a65f637e6) |
| MO-11 | Merged | `mo/mo-11-secret-broker` | `c457fe3` | [code/tests](https://github.com/Overton77/mission-control/commit/c457fe3721d0617cfab45e20579f3cc21447339d) |
| MO-12 | Merged | `mo/mo-12-environment-kits` | `0839f5d` | [code/tests](https://github.com/Overton77/mission-control/commit/0839f5d75305f71fbb0e721b365e1d6f4958bc50) |
| MO-14 | Merged | `mo/mo-14-git-write-path` | `b0da47b` | [code/tests](https://github.com/Overton77/mission-control/commit/b0da47bea3fd9003fa2b95c70239e50168fe3140) |
| MO-15 | Merged | `mo/mo-15-network-policy` | `03f326b` | [code/tests](https://github.com/Overton77/mission-control/commit/03f326b87b7ad8588f7e550f8896a26a1d9730a4) |
| MO-13 | Merged; live/owner boundary below | `mo/mo-13-cursor-environments-rest-adapter` | `b1e49f0` | [code/tests](https://github.com/Overton77/mission-control/commit/b1e49f0449416f74c53ab809e475f4b8c1579b92) |
| MO-40 | Merged | `mo/mo-40-signal-ingress` | `4c340f1` | [code/tests](https://github.com/Overton77/mission-control/commit/4c340f13d74583e6eb5c18c6e592f434cbe368f2) |
| MO-43 | Merged | `mo/mo-43-wake-channels` | `39e08e7` | [code/tests](https://github.com/Overton77/mission-control/commit/39e08e77159ef17254cdfe5c03c9d52e788a358e) |
| HL-17 | Merged | `mo/hl-17-provider-webhooks-wake-signals` | `afb5cf9` | [code/tests](https://github.com/Overton77/mission-control/commit/afb5cf965981defcd951028402067a6c8b71f0fb) |
| HL-07 | Merged | `mo/hl-07-claude-managed-prepare` | `6bc5de0` | [code/tests](https://github.com/Overton77/mission-control/commit/6bc5de0a3df8904225ca5d57c52fda1f01a4d054) |
| HL-08 | Merged | `mo/hl-08-claude-managed-session-lifecycle` | `0775fea` | [code/tests](https://github.com/Overton77/mission-control/commit/0775fea7c48d447840d79796b18fea35e61079c0) |
| HL-09 | Merged; local live approval/publication passed | `mo/hl-09-managed-approvals-publication` | `4e978a1` | [code/tests](https://github.com/Overton77/mission-control/commit/63a15440964bf152a01efac88b721a3d5542c663) |
| MO-21 | Merged | `mo/mo-21-preflight` | `3238f1f` | [code/tests](https://github.com/Overton77/mission-control/commit/3238f1fde4fb7f00f424344fa265d79d910c34f6) |
| MO-20 | Merged | `mo/mo-20-owner-prerequisite-store` | `3ed289b` | [code/tests](https://github.com/Overton77/mission-control/commit/3ed289b8155f41efe8950584c6184758dc75e5d1) |
| MO-22 | Merged | `mo/mo-22-setup-wizard` | `6c5aa76` | [code/tests](https://github.com/Overton77/mission-control/commit/6c5aa7621c74a3ac54ba9fb2d79b624bc269608b) |
| MO-30 | Merged | `mo/mo-30-cognition-projection` | `a80d915` | [code/tests](https://github.com/Overton77/mission-control/commit/a80d9150f3af72219c87ac96e86d22a588023541) |
| MO-32 | Merged | `mo/mo-32-portable-plugin-expansion` | `86e3318` | [code/tests](https://github.com/Overton77/mission-control/commit/86e3318824dc8aa29068bab2702e2e4387a65b00) |
| MO-33 | Merged | `mo/mo-33-ambient-cognition` | `34843e4` | [code/tests](https://github.com/Overton77/mission-control/commit/34843e410f85a962fa6bc1e6ecb4729fe0c973ff) |
| MO-35 | Merged | `mo/mo-35-cognition-profiles` | `0916dff` | [code/tests](https://github.com/Overton77/mission-control/commit/0916dff1ed2b4f2e55f4bd4152f35dfb6a29bfcc) |
| HL-19 | Merged | `mo/hl-19-trusted-owner-probes` | `00aec0a` | [code/tests](https://github.com/Overton77/mission-control/commit/00aec0a5844cd78fb7ce462c30b48798ceae49da) |
| MO-31 | Merged; live/owner boundary below | `mo/mo-31-hook-mapping-cursor-binding-v2` | `6fc3b0d` | [code/tests](https://github.com/Overton77/mission-control/commit/6fc3b0d0011a653f3e2a24e7271ee64ca42cbfc0) |
| MO-34 | Merged; live/owner boundary below | `mo/mo-34-discovery-proof-per-lane` | `1ed159a` | [code/tests](https://github.com/Overton77/mission-control/commit/1ed159a975c2719b6c378d4cfa9cdab56cb65d6b) |
| MO-41 | Merged | `mo/mo-41-telemetry-hook-pack-signal-emit` | `c9de62c` | [code/tests](https://github.com/Overton77/mission-control/commit/c9de62cb0c3a94ed4768a4943498c9ca04228932) |
| MO-42 | Merged | `mo/mo-42-gate-hooks` | `f3d98ee` | [code/tests](https://github.com/Overton77/mission-control/commit/f3d98ee031beffd53a68a491392ef89f50db5df0) |
| MO-44 | Merged | `mo/mo-44-watchers` | `6b6be48` | [code/tests](https://github.com/Overton77/mission-control/commit/6b6be483c50c2f6e5ad37ed46721e15f775b603c) |
| HL-11 | Merged | `mo/hl-11-codex-agents-prepare` | `853db6d` | [code/tests](https://github.com/Overton77/mission-control/commit/853db6d75b7824a79b86015c9e82af2966b95d25) |
| HL-12 | Merged; live/owner boundary below | `mo/hl-12-codex-agents-session-lifecycle` | `91ca831` | [code/tests](https://github.com/Overton77/mission-control/commit/1c32b0da1e71f1d44684ba90cae0fbc85fb46f61) |
| HL-13 | Merged; live acceptance blocked | `mo/hl-13-agents-function-tools` | `42cdab6` | [code/tests](https://github.com/Overton77/mission-control/commit/95c6c7071ab7a74e75fa6fe2331d0d7682c5cc4a) |
| HL-21 | Merged; controlled live projection passed, owner binding acceptance blocked | `mo/hl-21-hosted-projection-composition` | `f94b1b9` | [code/tests](https://github.com/Overton77/mission-control/commit/4e105bdd3510d807b9df8db6456fc08e293a92c2) |
| MO-50 | Merged | `mo/mo-50-cloud-branch-inputs` | `6b75d38` | [code/tests](https://github.com/Overton77/mission-control/commit/6b75d383e52d441e31cc3a464a930b6b6177f25a) |
| MO-51 | Merged | `mo/mo-51-knowledge-workspaces` | `9f71a03` | [code/tests](https://github.com/Overton77/mission-control/commit/9f71a03391329d13bf6a87dbdfd32aa2069cebf6) |
| MO-52 | Merged | `mo/mo-52-placement-admission` | `30b0709` | [code/tests](https://github.com/Overton77/mission-control/commit/30b0709984b58f13378ba2b00b202d52e0be3850) |
| MO-45 | Merged | `mo/mo-45-external-signals` | `27e579a` | [code/tests](https://github.com/Overton77/mission-control/commit/27e579ac88a5862962daa10293c36d38452e26b3) |
| MO-46 | Merged | `mo/mo-46-watcher-library` | `6d61de6` | [code/tests](https://github.com/Overton77/mission-control/commit/6d61de622d52b6be1e7bbe71cbd72c2a0c5f640b) |
| MO-47 | Merged | `mo/mo-47-observe-skills` | `f7f88f1` | [code/tests](https://github.com/Overton77/mission-control/commit/ca9cdaba8fc652e7f88d3f93db189ee7937eed98) |

## Recovery and integration fixes

- Recovered the existing L0–L3 branches and retained original worktrees and ignored receipts. Linear was inspected read-only; the local MO/HL issue packet was never published there. No tracker completion claim is inferred from old Linear issues.
- Completed plugin expansion, ambient cognition, cognition profiles, cloud branches, knowledge workspaces, owner preflight/setup, synchronous remote gates, and durable provider capacity with fresh lane preference selection.
- Preserved immutable migrations 0033 and 0036. The current implemented lane describes move forward in 0040; 0041 adds installation/application provider capacity. Slot 0039 remains unused because watchers reuse existing persistence.
- Restored all applied catalog seed bytes against both live 1.3.0 receipts (11 bundles per application). Agent skills 1.0.1 and approved-assets 1.0.2 are additive successors; archived original bundles remain fetchable. Catalog/custody/watcher checks: 28 passed.
- Built additive component 1.4.0 with 34 migrations. The live 1.3 predecessor is `sha256:3154fa8d...`, proven by recorded attestations and an immutable-prefix rebuild; an unreleased working-tree 1.3 fingerprint was rejected during recovery.
- Restored 15 historical SQL files to their exact archived CRLF bytes and pinned Git attributes; these retired SQL files are never applied.
- Added bounded owner-probe bootstrap, MA5 selected-MCP OAuth verification and exact readonly credential-source evidence. Generic runtime snapshots dispatch by their closed contract; fresh prerequisite review resolves the exact admitted semantic template reference and rejects provider operations that bypass authored manifests.
- Completed HL13 governed function tools, durable approval waits, artifact custody, scoped bundle publication and mission PR comments. Production hosted composition rechecks exact readonly credential evidence. Current-turn artifacts require bounded inline bytes because the pinned provider API cannot download them mid-turn; path-only requests fail explicitly. Native Codex shell/file gates remain unsupported.
- Fixed Windows cloud-branch path length while retaining the canonical run-specific mission branch prefix and governed write scope.
- Owner attestations cannot satisfy a declared trusted probe. Probes pin scope/definition and real provider or durable receipt evidence; receipt re-verification retains the original freshness deadline. Repository alias changes invalidate old evidence.
- Refreshed public manifest schemas, deterministic compile snapshots and native Codex projection discovery evidence. The Codex recording uses a closed loopback model endpoint and performs no paid model request.
- Recovery live drills exposed and repaired canonical runtime-unit Git branch encoding, empty instruction-only dispatch, session-scoped Files API beta headers and pagination, the approval context's effective-configuration digest, late approvals on quiet provider streams, and the exact OpenAI root-turn Items endpoint (the session-wide route rejects a turn_id query). Two real restricted-PostgreSQL approval tests distinguish the effective configuration digest from the provider-binding digest. Completed root-turn setup evidence can carry Codex readiness across turns only with exact configuration/binding/setup seals.
- Final hosted follow-up `1c6b045` adds a ten-second native-index visibility barrier and narrowly scoped first-turn action recovery. Thirty-nine focused units and two-module typing passed before integration. Retained live runners default to skipped, require explicit authorization for paid inference, assert actual native allow plus durable approval, and fail if cleanup fails.
- Legacy integration fixtures now carry their actual disposable Application Binding. Deterministic provider doubles explicitly opt into labelled synthetic owner evidence persisted under each declared verification method and definition digest; installation, kit, network and launch guards remain production checks. These fixtures do not establish live owner verification or provider qualification.

## Validation

Validation disposition: repaired local checks are recorded below, with original broad failures retained alongside focused passing reruns. Six missing-schema cases and specified live acceptance remain blocked; the aggregate suite is not represented as fully green. The final generated 1.4.0 manifest is `sha256:7ba8ec65917f99e8d16feb5c93835fe2495d82dee942327d06c33ee23b3b84d1`; schema fingerprint `sha256:b3e35a34c99bbcfbe48a02333737940dc917d073154491d962bb764e9f0ee1ce`; contract digest `sha256:f1caa3c55bfa6f9fec827615bcac919a93f1d905a2c7e8178143c24ee4a2f0a4`. Each count identifies its executed selection; overlapping runs are not summed into a synthetic full-suite result.

- HL13: 92 focused hosted/lifecycle/shared tests passed, including real local Git bundle upload → durable human review → exact mission branch publication. These prove local effects, not paid-provider qualification.
- Root HL19: 58 prerequisite units; later 7 setup/receipt checks including 2 real PostgreSQL tests passed. Mypy on 10 changed modules passed.
- MO52: real PostgreSQL concurrent cross-tenant capacity test, real Temporal capacity wait, placement/preference tests and authoritative typing passed.
- MO45: 2 real PostgreSQL/Temporal tests, 31 focused units, 110 watcher/architecture regressions passed.
- Final source follow-up at `1c6b045`: **419 passed, 3 skipped in 104.65s** across all lane conformance and Managed Agents, Codex Agents and shared remote-session units, plus the opt-in runner modules. The skips verify that the paid/control-plane runners remain disabled by default. Full mypy passed for **774 source files**. A subsequent test-only correction `8b083b4` derives expected provider IDs from the durable approval task instead of an optional diagnostic snapshot; its hooks passed. No later production source changes were made.
- Earlier integrated lane conformance plus Managed Agents, Codex Agents and shared remote-session regressions: **407 passed in 97.44s**, with no skips or failures, at `e197ba8`. This includes the effective-configuration approval seal and both quiet-stream/custody fixes.
- Exact OpenAI root-turn Items endpoint follow-up: **218 passed in 83.19s** at `1e41b21` (`tests/unit/openai_agents` and `tests/conformance/lanes`), with no skips or failures.
- Architecture checks: **12 passed in 21.54s** at `1e41b21`. Final independent ledger review verified all 49 required issues appear exactly once and all linked integrated evidence commits are ancestors of the integration head.
- Full source typing: **774 files passed** at `e197ba8`, repeated successfully at final source head `1c6b045`. Repository-wide pre-commit checks all passed, including Ruff lint/formatting, ty, deptry and lock consistency; repeated successfully at final test head `8b083b4`, after the acceptance and hosted follow-ups. The full source gates include the recovered hosted fixes through `745706f`; authoritative typing was repeated successfully after the exact-turn Items fix at `1e41b21`.
- Integrated prerequisites/effects/OpenAI selection: **167 passed**. Public manifest schemas, all 15 skill manifests, all 168 seed definitions, and OKF structure also passed. The final documentation link check covered 391 files with zero broken links; OKF contains 45 valid concepts. Latest full Ruff lint/format check passed for 1,735 files.
- Independent real two-project qualification: 34 passed. Immutable predecessor upgrades from 1.0/1.1/1.2/1.3 to 1.4: all 4 passed. Final database-package run: **70 passed in 206.10s**, including all predecessor upgrade cases, against the final hosted-describe 1.4.0 release on two dedicated disposable PostgreSQL clusters. The earlier package failures were repaired.
- MO47: seven real offline watcher CLI compiles passed; two-run wait/inspect/filtered-replay/ack recipe passed in 100.47s with real PostgreSQL/Temporal; original wake-channel acceptance also passed.
- Integration fixture follow-ups: **10 PostgreSQL custody/prerequisite tests passed in 110.21s**, and **2 Cursor PostgreSQL tests passed in 300.90s**. Host memory pressure caused an earlier interrupted attempt; its partial output is not counted.
- Broad integration sweep: **596 passed, 43 failed, 13 skipped** in 1,985.37s. All 43 failed node IDs subsequently passed in disjoint focused reruns: 10 custody/prerequisite, 2 Cursor and **31 runtime cases in 631.18s**. The latter cover manifest chains, all MP20 provider combinations, human decisions, instructions, cancellation, budget attribution, MP22 and RRM cancellation/replay. The frozen lineage fixture clock required disabling automatic Temporal time skipping while awaiting real cancellation. The original broad result is retained rather than rewritten after reruns.
- Full acceptance sweep at `745706f`: **19 passed, 1 failed, 0 skipped** in 846.21s. The asynchronous hosted-child settlement case correctly failed because its deterministic parent fixture omitted the required stage output. The child and parent operation had completed without an operation failure. The fixture now emits the existing typed stage record (`719c404`); the failed completion case plus both child-cancellation variants subsequently **passed: 3 tests in 149.39s**, with the already-passing artifact case deselected. No production settlement rule changed. This is a repaired focused rerun, not a fresh full acceptance sweep. All other acceptance modules passed, including forced worker loss/replay, child cancellation, manifest lifecycle, real two-run watcher observation and wake-channel CLI behavior.
- Bootstrap real PostgreSQL/Temporal and timeout follow-up: **4 passed** at `6951664`; paid-provider qualification is not claimed.
- Combined unit/architecture/conformance recovery-final run: **4,336 passed, 11 failed, 21 skipped, 2 expected failures** in 669.37s. Six failures require the absent authoritative Biotech SDL; four stale hosted projection expectations and one missing managed approval conformance fixture were repaired in `1542a3b`. The integrated follow-up (projection files, session controls and both hosted harnesses) passed **83 tests**; the agent expanded selection passed **215 tests**, including all lane conformance. These overlap and are not added to the broad count.
- Historical unit/architecture/conformance round 2: 4,278 passed, 20 failed, 21 skipped, 2 expected failures. Superseded by the 4,336-pass run and focused repairs above; retained only as recovery evidence.
- Earlier broad run: 4,191 passed, 32 failed, 21 skipped, 2 expected failures. Superseded by later checks; retained only as recovery evidence.

## Reproduction commands and unrun checks

Run from the repository with the documented disposable PostgreSQL/Temporal services and explicit offline tracing configuration. Secret-bearing environment setup and raw receipts remain local and ignored.

- Static gates: `uv run --no-sync mypy`, `uv run --no-sync prek run --all-files`, `uv run --no-sync ruff check .`, `uv run --no-sync ruff format --check .`.
- Broad offline selection: `uv run --no-sync pytest tests/unit tests/architecture tests/conformance -q`; six missing-SDL failures mean the aggregate `make check`/`make ci` cannot be represented as fully green.
- Final hosted selection: `uv run --no-sync pytest tests/conformance tests/unit/anthropic_managed tests/unit/openai_agents tests/unit/remote_session -q`.
- Persistence: `uv run --no-sync pytest -c packages/mission-control-db-contract/pyproject.toml packages/mission-control-db-contract/tests -q`, with two isolated administrator DSNs. Reviewer qualification uses `tests/qualification/two_project`.
- Runtime: `uv run --no-sync pytest tests/integration -q`, followed by the exact 43 failed node IDs in three disjoint selections; acceptance uses `tests/acceptance/mission_control`.
- Controlled live projection, without inference: `MC_HL21_PROJECTION_LIVE=1 MC_HL21_EVIDENCE_DIR=<ignored-dir> uv run --no-sync pytest tests/integration/openai_agents/test_projection_live.py -q` (shell-appropriate environment assignment). The separate `test_function_tools_live.py` requires `MC_HL13_LIVE=1`, a finite explicitly authorized `MC_PAID_BUDGET_USD` no greater than 10, an ignored `MC_HL13_EVIDENCE` destination, provider credentials and the disposable database DSN. Its corrected final form has **not** been rerun with paid inference.
- Docs: `python docs/tools/check_links.py`, `python docs/tools/validate_okf.py`, and `python docs/tools/agents_docs_index.py --check`.

The broad offline run's 21 skips cover unconfigured persistent Agent Server fixtures, an unavailable Python 3.8–3.10 compatibility interpreter and a sibling-workspace Skill fixture. Its two expected failures are the pre-existing Stage 0–2 reference harness authority gap. The broad integration run's 13 skips are explicit live-provider/CLI opt-ins and WSL-only recovery; individual authorized hosted evidence is recorded separately below. These are not counted as passes.

## Live and owner boundaries

- Local Codex/Claude production qualification remains dependent on owner WSL/login and exact host evidence. Windows recordings and fake conformance do not qualify a Linux production lane.
- Cursor repository access blocked the historical live discovery drill; no SCM authorization or provider-side receipt is fabricated.
- MO31's full Mission 3 deterministic-executor fixture depends on work outside this run.
- Provider webhook registration, public ingress deployment and the MO75 inbox drainer remain Run 2. Signed fixture delivery proves ingress handling; it does not claim a live registered webhook.
- The authoritative Biotech `biotech-meta/docs/schema/current_biotech_schema.graphql` file is absent in the canonical domain workspace. Six existing schema tests require it. Relocation inventories confirm the exact 107,632-byte file with SHA-256 `86b5e0b5d11d203bd75b69b4507b0aad97d5df2495d3897ca64272068ea5f112` and owning repository head `638aef572383062401b341802adcf01521136ff7`, but contain no source bytes. The canonical repository is missing and its old junction points there. The checked Knowledge Services Git history has no matching blob; available SDLs differ. A read-only lookup of the recorded `Overton77/biotech-meta` remote also returned repository not found under the configured Git credentials. Restore that exact file or the owning repository object store from an external retained source, then run `uv run --no-sync pytest tests/unit/schema -q`. No substitute schema or weakened assertion is committed.
- Owner-probe bootstrap: actual CLI help/rejection and a real PostgreSQL/Temporal dispatch proof passed. The latter exercises the real operation workflow, lane service and lineage, one technical attempt/session, duplicate reuse, archived session/deletion order and released capacity. Provider transport is a fixture; paid bootstrap and ingress qualification remain unrun. The isolated run control record stays ACTIVE because an operation result does not authorize mission acceptance; terminalizing that record requires normal governed reconciliation. Cancellation is requested before the hard Temporal timeout and failures are sanitized.
- Knowledge Services requires an actual admitted MCP capability. No endpoint/schema is invented.

## Budgets and provider evidence

Recovery S2 retries have consumed **$0.17 in recorded provider cost through the passing HL-09 retry**, under the original S2 $10 authorization, using claude-sonnet-5-5. Each retry is capped at $0.50. The HL-09 drill passed with real native approval, env.prepared, a provider-created Git bundle, exact admitted branch publication and the governed PR gateway; three durable Human Tasks were resolved. Its session/environment were deleted and agent archived. The passing attempt cost $0.02. After that passing result, five bounded single-root gpt-6-luna S3 attempts were made, each with an admitted 4,000-token budget, no vaults or network hosts, and no model substitution. None proved the approval round trip: the last attempt ended after 284.52s without a durable Human Task, while native readback showed the exact root mc_request_approval call waiting in requires_action. Dispatch was still waiting for turn-list reconciliation before cancellation; successful HTTP responses did not establish timely turn visibility. Every created session, agent and template was deleted. Native usage remained null, so actual S3 tokens and cost are **unknown**, not zero or measured as within budget. No further inference retries were made. A narrow first-turn recovery now checks the unique pending action against an exact root-turn retrieval in the same session; ambiguous, old, child and later-turn cases remain fail-closed, with offline regression coverage. That follow-up was not rerun with paid inference. The smallest next step is to rerun the strengthened opt-in proof with an explicit finite allowance and confirm exact native allow output plus accepted durable review; a completed workflow alone cannot prove an accepted approval. A local bare Git destination and PR-host fixture prove scoped publication and gateway routing, not live GitHub or AWS qualification. Historical evidence records Cursor S1 about $0.03; Managed Agents S2 at most $0.21 before recovery; OpenAI smoke about $0.04 estimated with unsettled/cancelled-turn costs unknown. Historical figures are prior run records, not fresh billing reconciliation. No paid calls were made during the initial recovery and offline integration checks.

## Provider answers and spec corrections

The [provider smoke record](../research/provider-smoke-2026-10.md) remains the source for exact observed wire shapes. Q-M1 steering is consumed at the next model-request boundary in the running turn; sending during its idle custom-tool wait is refused. Q-M3 session list_cost includes runtime and uses whole cents. Q-O2 AGENTS.md is available only after the hosted environment connects, so critical instructions stay inline. Q-M2 self-hosted tool wait and Q-O3 vault placeholders for Git HTTPS remain unproven; Q-O4 spend_control is absent from the pinned SDK model and is not assumed supported. Q-M4 queued-message behavior across interrupt remains open. Native Codex shell/file approvals and settled cost remain unsupported/unknown, respectively.

HL-21 controlled live projection used a nonempty harmless skill through the production projector on both APIs: **2 live checks passed in 29.58s**, without inference. Managed Agents created one skill, environment and agent on the first sync; Codex Agents created one template and agent. The second sync created zero resources for either API. The Managed agent was archived, its environment and skill deleted, and both Codex resources deleted. Two earlier probe-skill leftovers were discovered, deleted, and a list readback confirmed zero before the final run. Both initial prepare/readback and an unchanged-input second sync passed with zero newly created resources on the second sync. The OpenAI check exposed native list-index lag after a successful create; prepare now waits for exact-ID immutable readback visibility within a bounded window. A fixture metadata mismatch (missing skill description) was corrected to match its actual archive manifest. This proves controlled projection and resource reuse; it does not prove the full owner-selected catalog, Secret Broker credentials, normal deployment bindings or a completed S3 approval drill. Those bindings remain unconfigured locally. The smallest next step is to supply the reviewed ManifestLaunchBindings and admitted catalog/credential evidence, then run the documented live acceptance against that exact configuration. Remote AWS drills remain excluded.

## Architecture decisions

The sprint ADRs remain proposed as recorded in their source files (0042–0050, 0052–0053); integration does not silently mark them owner-accepted.

## Run 2 handoff

Vercel ingress, provider webhook registration, MO75 draining, AWS/Temporal Cloud, self-hosted/funding-gated lanes, desktop/browser paths and HL24/25 remote drills remain excluded. Release 1.4.0 must be explicitly reviewed and applied to live projects in Run 2; repository merge does not migrate them. Keep exact placement qualification, cost unknowns and session retention/custody evidence visible.

## Main delivery

Release 1.4.0 is built and its final database package checks passed. On 2026-10-14, the canonical main checkout was fast-forwarded from `146c9eb50ce45a9c28f1f0db667dfe2ee53e2ad1` to `1b0f625c08e423a79435c35673429202948bffcf` and pushed to origin. A subsequent `git ls-remote` readback confirmed both `refs/heads/main` and `refs/heads/mo/run1-integration` at that exact commit. This delivery-receipt documentation commit follows that verified push. All 49 implementation entries are integrated. The original untracked stackdump, retained worktrees and ignored receipts were preserved. No live database migration, cloud deployment or Linear publication was performed. The schema and qualification blockers above remain explicit; merging does not resolve them.

## Worktree cleanup and next-team handoff (2026-10-14)

After the owner requested cleanup, all 62 registered worktrees and 92 local branches were
audited. The 61 secondary worktrees were clean. Twelve non-ancestor heads contained already
integrated cherry-picks; patch/range comparisons found no missing code or tests. An ancestry-only
merge `d9e570c` preserved the exact delivered tree while making every original local head an
ancestor of main. This audit did not reapply stale issue patches or alter production code.

Removed all **61 secondary worktrees, 91 redundant local branches and 37 merged remote
branches**. Only the canonical main checkout and main branch remain. A verified local Git
bundle preserves the original refs; 137 non-cache local/loose files were copied with matching
SHA-256 hashes before removal. The original canonical untracked stackdump and private Run 1
receipts were preserved. Reproducible dependency environments and caches were removed.

Recovery custody is under ignored `.scratch/worktree-cleanup-2026-10-14/`, including
`pre-cleanup.bundle`, `preserved-files-manifest.json`, `unmatched-audit.md`,
`ancestry-receipt.json` and `cleanup-receipt.json`. No secrets or receipt payloads were committed.
See the [Specs 7–11 team handoff](RUN-2-HANDOFF.md) for exact next scope/dependency waves,
authorization boundaries, release/proof constraints, known blockers and recovery instructions.
