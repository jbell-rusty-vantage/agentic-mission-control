# Run 2 team handoff: Specs 7–11

Prepared on 2026-10-14 from canonical `platform/mission-control`, main `0a75b6e`.
This is an implementation handoff, not a new specification, spending authorization or
qualification record. Start from the latest verified main after the cleanup/handoff commit;
do not recreate the retired Run 1 integration checkout.

## Approved planning amendments and Codex kickoff (2026-10-14)

The owner approved narrow refinements after this handoff. Read [the approved plan](RUN-2-PLANNING-AMENDMENTS.md), [source-backed OpenAI product resolution](RUN-2-OPENAI-ARCHITECTURE.md) and [the exact Codex agent-team kickoff](RUN-2-AGENT-TEAM-KICKOFF.md). Affected issue files and issues.json carry Run 2 acceptance plans. Remaining counts/deps, immutable releases, deferred features and funding gates are unchanged. This planning approval does not launch implementation or authorize new paid/deploy actions.

Managed budget-gate pause/resume remains blocked by missing production workflow wiring; no qualified/native pause claim follows from the helper methods. OpenAI codex_agents is hosted Agents API, not Agents SDK/Responses. CM-10 cloud unit branches already exist; verify remaining evidence before duplicating implementation. Original packet dispatch/migration allocation prose is historical; this handoff and the approved amendments supersede it for Run 2.

## Read first and establish the base

Read root/scoped AGENTS.md, then [Run 1 report](RUN-1-REPORT.md),
[SPRINT](../SPRINT.md), [DECISIONS](../DECISIONS.md),
[TEAM-WORKSPACE](../TEAM-WORKSPACE.md), [PLAN](../PLAN.md), and each assigned issue.
The packet's kickoff/status paragraphs describe the original baseline; the Run 1 report
supersedes their claims that no implementation or paid calls exist. Issue files are planning
records, not published Linear status. MO-07 owns remaining stale guidance reconciliation.

Verify `git status`, main/origin identity and retained files before starting. Preserve the
existing untracked `issues/bash.exe.stackdump` unless its cleanup receipt explicitly records
its disposition. Create fresh issue branches/worktrees only when useful; write new claims
with the actual base, writable paths and dependency evidence. Old claims are historical.
Use independent implementation and adversarial review owners. The integrator owns shared
contracts, bootstrap composition, deployments, common SQL and release artifacts.

## Exact remaining packet scope

`issues.json` has 97 `sprint: in` entries; Run 1 integrated 49 distinct entries. The remaining
48 divide as follows. This table excludes all `sprint: deferred` entries, even when a spec's
aspirational matrix mentions them. Check current code before implementing: some defects may
already have been addressed incidentally by Run 1; cite that evidence instead of duplicating it.

| Group | In-sprint issues remaining | Notes |
| --- | --- | --- |
| [SPEC-07 Cursor](../SPEC-07-cursor-maturity.md) | CM-01, CM-02, CM-03, CM-04, CM-05, CM-07, CM-08, CM-09, CM-10, CM-13, CM-18, CM-19, CM-21 | 13; lifecycle, accounting, Windows/bridge recovery and qualification |
| [SPEC-08 CLI skills](../SPEC-08-local-cli-skills.md) | LS-01 through LS-08 | 8; independent of Mission Control runtime |
| [SPEC-09 local harness](../SPEC-09-local-harness-path.md) | MO-63 through MO-72 | 10; MO-73 is already integrated in Run 1 |
| [SPEC-10 ingress](../SPEC-10-ingress-on-vercel.md) | MO-74, MO-75, MO-76, MO-79 | 4; MO-40 service/SQL is already integrated |
| [SPEC-11 remote worker](../SPEC-11-remote-worker-on-aws.md) | MO-77, MO-78 | 2; setup/probe before deployment |
| Cross-spec closeout | MO-07; HL-24 and HL-25 | 3; documentation plus the remote S2/S3 drills |
| Funding hold | HL-01, HL-02, HL-03, HL-10, HL-14, HL-15, HL-16, HL-20 | 8; S4 implementation/qualification stays blocked until explicitly released |

The non-funding remainder is 40 issues, including 37 directly under Specs 7–11. Do not quietly
add deferred CM-06, CM-11, CM-12, CM-14, CM-15, CM-16, CM-17, CM-20 or CM-22. Subscription
cloud experiments and every other deferred entry also remain outside the default dispatch.

## Dispatch waves and dependency joins

Use the exact `deps` in [issues.json](../issues.json) and the issue files; the summary below
keeps [PLAN](../PLAN.md)'s waves while treating integrated Run 1 dependencies as code present,
not automatically qualified live installations.

| Wave | Dispatch now when prerequisites are available | Exit evidence |
| --- | --- | --- |
| A | MO-07; Cursor CM-10, CM-09, CM-08, CM-18, CM-13; LS-01 then LS-02/03/04/05/06; MO-65, MO-66, MO-68, MO-69, MO-70, then MO-71; MO-78 | Offline CLI fixtures, exact auth/version guards, S0 manifests, Cursor defect proofs, dev-namespace connection/search-attribute probe |
| B | Cursor CM-02, CM-03, CM-04, then CM-05/07 and CM-01; LS-07 then LS-08; MO-63/64; MO-72 then MO-67; MO-74/75/79; MO-77 | S0 local drill, split-host custody, lean ingress, durable drainer/launch admission, one AWS base worker and laptop-off evidence |
| C | MO-76; HL-24, then HL-25; finish the carried local S3/HL21 acceptance below | Quarantine-to-custody proof; remote S2 before remote S3; exact configuration/placement receipts |
| D | CM-19; S4 only after explicit funding release | Cancellation robustness; released S4 dependency proofs if authorized |
| E | CM-21; HL-20 only after S4 is released and implemented | Cited qualification records for each exact profile/placement; no blanket qualification flag |

Critical joins:

- MO-69 → MO-71. MO-72 depends on MO-65/66/68/69/70/71 plus integrated MO-08/43/04/05.
  MO-67 requires MO-72 and MO-78.
- CM-04 → CM-05 and CM-07; CM-02 + CM-04 → CM-01. CM-21 requires CM-01/05/09/10.
- Integrated MO-40 → MO-74 and MO-75. MO-75 + MO-70 → MO-79; MO-76 needs MO-40/75.
- MO-63 + MO-64 + MO-78 → MO-77. HL-24 joins MO-74/77/79 with integrated HL-09/17/18/23.
  HL-25 needs HL-13/17 and HL-24. Historical local HL-09 success is not the remote HL-24 drill.
- Funding chain, only after release: HL-01 → HL-02; HL-02 + MO-74 + MO-11 → HL-03;
  HL-10 needs HL-08/02, HL-14 needs HL-12/02, HL-15 needs HL-02/03/MO-73,
  HL-16 needs HL-02; HL-20 joins HL-10/14/15/16.

Suggested ownership: Cursor Runtime, standalone CLI Skills, local-host Environment,
ingress/drainer Events, and remote Hosted/Deployment, with one integrator leasing shared paths.
Begin MO-78 and the three independent offline streams in parallel; do not make deployment
wait for unrelated Cursor enhancements. Integrate small reviewed changes with production wiring.

## Preserve the Run 1 seams

- Temporal is the sole scheduler. Vercel authenticates and writes inbox rows through restricted
  ingress functions; it holds no Temporal credentials and runs no lane or background worker.
  MO-79 must admit through the normal application handler, preserving fresh preflight,
  scope, idempotency and typed refusals. Accepted, delivered and applied remain distinct.
- MO-40 already includes migration 0035, `mission_request` inbox kind and credential purpose.
  MO-75 consumes it with SKIP LOCKED, idempotent frame keys and outbox/wake handling; LISTEN
  uses a session connection and retains the 5-second polling fallback. Do not add another inbox.
- MO-76 uses signed uploads into quarantine; verify bytes/digests before custody. Do not send
  large artifact bodies through Vercel or treat an upload acknowledgement as verified evidence.
- Exactly one base worker per `(namespace, application)`. After MO-77, WSL is lane-only
  (`MISSION_CONTROL_WORKER_ROLE=lane`), serving `mc-s0-ai-engineer-lane-wsl`; AWS serves base
  queues, drainer and `mc-ai-engineer-lane-hosted`. Route from sealed provider bindings, not
  worker-side lane swaps. Both hosts must use the same build when local lanes participate.
- Use separate WSL and Windows environments, Linux lease roots and actual CLI auth probes.
  Never sync Linux packages into the Windows `.venv`. S0 Cloud either precedes AWS base-worker
  activation or uses the local worker in lane role. Shared payloads require actual S3 custody
  or proven matching roots; no split-host filesystem fiction.
- SPEC-08 jobs live under `.agents/skills/`, have no `mission_control` import/dependency,
  and use their documented local auth guards. They are separate from catalog `skills/` bundles.
- Owner verification stays exact to scope, definition, freshness, credential source, ERC and
  selected provider binding. Attestation cannot satisfy a declared API/file/probe mission.
  Never substitute static fixture evidence into production or export organization keys to a
  provider vault/sandbox. The effective configuration approval seal differs from provider digest.
- Runtime-unit branch identities, scoped write grants, output/evidence channel selection,
  projection refusal for unsupported behavior, and durable capacity reservations must survive
  Cursor/remote changes. Completion of an operation does not authorize mission acceptance.

## Release and immutable history

Common component **1.4.0 is built, locally proven, and not applied live**. Its manifest SHA-256
is `7ba8ec65917f99e8d16feb5c93835fe2495d82dee942327d06c33ee23b3b84d1`;
schema fingerprint is `b3e35a34c99bbcfbe48a02333737940dc917d073154491d962bb764e9f0ee1ce`;
contract digest is `f1caa3c55bfa6f9fec827615bcac919a93f1d905a2c7e8178143c24ee4a2f0a4`.
It contains 34 migrations. Preserve applied migration and seed bytes, especially 0033/0036,
the verified live 1.3 predecessor, and archived CRLF SQL. 0040 moves lane descriptions forward;
0041 adds provider capacity. 0039 was unused because watchers reused persistence: that is not
permission to rewrite or allocate it independently. Read package AGENTS and have the integrator
allocate any additive migration/release work. Keep old skill/capability revisions fetchable.

Only the integrator applies 1.4.0 live through the reviewed
[Live Plan](../../mc-surfaces-2026-10/docs/qualification/two-project/LIVE_PLAN.md), retaining its local proof and
attestation requirements. Verify actual live version/fingerprint first; Run 1's main merge
and cleanup did not migrate either Supabase project. A new generated artifact needs fresh
identity/proofs; never silently replace the reviewed immutable artifact.

## Carry acceptance honestly

The [Run 1 report](RUN-1-REPORT.md) is the receipt index and authority for executed results.
No full green aggregate is claimed. Relevant completed checks include 419 passed/3 explicit
opt-in skips for the final hosted source selection, mypy on 774 source files, 70 database-package
checks, and disjoint focused reruns covering all 43 earlier integration failures. The parent
hosted-child acceptance fixture was repaired and its focused rerun is recorded there; retain
its original broad failure instead of inventing a fresh all-acceptance sweep.

- **Local S2:** real HL-09 native approval/publication passed. Git publication used a local bare
  destination and a PR-host fixture; this is not live GitHub or remote AWS qualification.
- **Local S3:** five bounded gpt-6-luna attempts did not prove accepted approval/recovery; native
  usage/cost stayed unknown. All created sessions/agents/templates were deleted. The corrected
  first-turn/index-visibility source and strengthened runner passed offline checks but were not
  rerun with paid inference. Next: reconcile unknown spend with the owner and run the explicit
  finite-allowance opt-in proof, requiring durable accepted review, exact native `allow`, one
  session/input, no duplicate frames and complete cleanup. Do not restart blind paid retries.
- **HL21:** both controlled nonempty skill projections passed live control-plane reuse checks
  with zero resources created on unchanged second sync and recorded cleanup. Full owner-selected
  catalog, Secret Broker credentials and normal deployment bindings remain unconfigured. Supply
  reviewed ManifestLaunchBindings and exact admitted catalog/credential evidence before claiming
  full acceptance. The retained runner's controlled projection is narrower than this claim.
- **Local/Cursor discovery:** WSL/login/host qualification and Cursor repository access remain
  owner boundaries. MO31's full Mission 3 deterministic-executor fixture depends on later work.
  Qualify the exact placement; fake providers and Windows recordings do not qualify Linux lanes.
- **Bootstrap:** actual CLI refusal/help and offline-provider real PostgreSQL/Temporal dispatch,
  duplicate reuse, archived session and released capacity passed. Paid bootstrap/ingress proof
  remains unrun. Its isolated run-control record stays ACTIVE; use governed reconciliation if a
  terminal run record is needed, rather than inventing mission acceptance.

Six schema tests need the missing authoritative Biotech SDL: exactly **107,632 bytes**, SHA-256
`86b5e0b5d11d203bd75b69b4507b0aad97d5df2495d3897ca64272068ea5f112`, from owning
`biotech-meta` head `638aef572383062401b341802adcf01521136ff7`. Local inventories prove identity,
not recovery; canonical source/Git objects are absent, and the recorded remote returned repository
not found under configured credentials. No alternate nearby SDL matches. Restore the exact source
or owning object store, then run `tests/unit/schema`; do not weaken assertions or use private AWS
retrieval without authorization. This is a domain input blocker, not a reason to disable the gate.

## Authorization and owner inputs

This handoff and obsolete-worktree cleanup authorization grant no new cloud spend, S4 release,
webhook registration or secret-write authority. Carry the bounded decisions in
[TEAM-WORKSPACE](../TEAM-WORKSPACE.md#authorization-boundaries-from-the-owner-as-of-2026-10-12)
and DECISIONS R18/R20/R22/R27–R33; check their prerequisites against current state.

- Historical limits: $10 per slice; `claude-sonnet-5-5`, `gpt-6-luna`, Cursor Auto/Grok 4.7;
  AWS account/region/resources and **$40/month** exactly as SPEC-11 §4. The CLI default is
  us-east-2, but this deployment requires explicit `--region us-east-1` on every AWS command. Unknown S3 cost is not
  zero and does not reset the slice allowance. Run 1 recorded S2 recovery cost is $0.17; older
  receipts and unsettled usage require reconciliation before representing remaining funds.
- Remote work targets AI Engineer first. A hosted Biotech application or PHI allowance requires
  a separate owner decision. Temporal Cloud dev is `mission-control-dev.ih0e7`; prod remains
  reserved and requires explicit approval. No substitute model or larger AWS service is implied.
- Owner inputs still to verify: AW2 secret-write script, AW3 restricted local S3 profile,
  AW4 knowledge-repository privacy, read-only repository credential evidence, current GitHub App
  installation and provider-specific prerequisites. Never print `.env`, keys or receipt payloads.
- Provider webhook registration, creating the GitHub App, ECS Exec, spending beyond a slice,
  changing model/region/account/size, production namespace use, S4 start and Linear publication
  retain their explicit at-the-time approval boundaries. The previous main merge authorization
  is not a blanket authorization for a future Run 2 merge.

## Verification and evidence workflow

Start offline, with one heavy test process at a time on this host. Run 1 experienced severe
paging; do not hide interrupted runs or combine overlapping counts. Use deterministic provider
fixtures until a live gate is deliberately entered. Keep paid runners default-off.

1. Run focused contract/unit/conformance checks for each change, then authoritative mypy,
   Ruff/ty/deptry and the relevant broader gates. Existing commands and exact prior selections
   are listed in the Run 1 report; do not describe `make check` as passing while SDL cases fail.
2. Persistence claims need disposable real PostgreSQL; scheduling/recovery claims need actual
   Temporal with isolated UUID queues. Never point destructive fixtures at live databases.
3. For ingress prove restricted-role SQL, replay/idempotency, scope isolation, authentication,
   gate latency and cold-start import closure. For remote prove logs, exact build/queues, matching
   release/bindings, laptop-off admission, wake/recovery and cleanup, including cost disposition.
4. For each issue produce a handoff with integrated commit, acceptance-to-evidence mapping,
   commands/results, blockers/smallest next step, resource IDs and retention/cleanup disposition.
   Keep raw receipts ignored; public docs contain only sanitized summaries and digests.
5. Before release, rerun relevant checks on the actual final source/artifact, validate docs/index,
   and distinguish integrated code, completed acceptance and placement qualification explicitly.

## Local service starting point

At cleanup, local listeners were present on 55433 (Run 1 disposable PostgreSQL), 55432
(application PostgreSQL), 7233 (Temporal) and 16379 (Redis). This is a listener snapshot,
not a fresh health or schema qualification; verify the actual process, credentials and target
before running tests. The dedicated package-proof clusters on 55501/55502 were stopped after
their 70-test proof and had no listeners. Recreate/start isolated package fixtures as needed.
Do not repurpose the application database as a disposable fixture or remove database volumes
as part of branch/worktree housekeeping. This cleanup did not stop or mutate those services.

## Local receipt custody and cleanup receipt

The integrator audited obsolete worktrees/branches before cleanup. Do not operate on, restore or recreate
an old checkout merely because a historical receipt names it. Branch cleanup does not erase the
integrated commits linked in the Run 1 ledger.

Cleanup custody is under canonical `.scratch/worktree-cleanup-2026-10-14/`:

- `pre-cleanup.bundle` preserves Git refs/objects. Its verified SHA-256 is
  `e982dff92d8d0febf641b79cb1bcd1ef83ed840a59d889f63699b06b402a3949`.
- `preserved-files-manifest.json` inventories 137 non-cache ignored/loose files (about 1.81 MB),
  copied with SHA verification to `preserved-files/<old-worktree-name>/...`.
  Resolve former issue/integration `.scratch` log paths through that manifest; do not rely on
  old absolute worktree paths after cleanup.
- Completed cleanup: **61 secondary worktrees, 91 local branches and 37 remote branches
  removed**. Only the canonical checkout and `main` remain locally and on origin. All secondary
  worktrees were clean. Twelve cherry-picked branch heads were audited for equivalent changes;
  no omitted code/tests were found. An ancestry-only merge `d9e570c` made every original local
  head reachable from main while preserving the exact delivered file tree. Do not replay old
  issue-branch patches onto main. `unmatched-audit.md` and `ancestry-receipt.json` retain the audit.
- `cleanup-receipt.json` records final counts and Git/remote readback. Dependency environments
  and caches were removed; all inventoried non-cache local files were preserved and verified.

The canonical `.scratch/materialization-observation-2026-10/` receipt directory is unchanged.
Venvs/caches are reproducible and are not receipt custody. Rebuild from canonical rather than
following a removed worktree's environment junction:

```powershell
# From platform/mission-control; uses the reviewed lock and optional test/package groups.
uv sync --frozen --group biotech --group dbcontract
```

Use the repository's pinned Python/runtime tooling. In WSL use a separate Linux environment
as SPEC-09 requires; do not overwrite the Windows `.venv`. Re-run relevant checks after rebuild.
The bundle and receipt archive stay ignored/private; a future recovery should verify the bundle
and manifest hashes before extracting a specifically needed commit or file. For Git recovery,
`git bundle list-heads .scratch/worktree-cleanup-2026-10-14/pre-cleanup.bundle` lists the saved
refs; fetch only the required ref into a fresh `recovery/*` branch. For logs, copy the selected
`preserved-files/` entry after comparing its SHA-256 with `preserved-files-manifest.json`.
The retained bundle is local; it is not uploaded to GitHub, and receipt files must stay private.

Historical receipt roots now map to this archive or the retained canonical directory:

- Canonical `platform/mission-control/.scratch/materialization-observation-2026-10/` holds local
  environment setup, claims/handoffs and receipts; treat setup scripts as secret-bearing inputs,
  source silently only when their intended disposable target has been checked.
- Former `platform/.worktrees/mc-run1/integration/.scratch/codex-final-checks/` broad/focused
  regression logs map through `preserved-files-manifest.json`, normally beneath
  `preserved-files/integration/.scratch/codex-final-checks/`. Other issue-worktree paid-provider,
  package and bootstrap receipts likewise use their recorded old-worktree-name prefix.
- The referenced relocation inventory is outside the repositories at
  `C:/Users/Pinda/Proyectos/internal/relocation-backups/belllabs-organization-20261009/`.
  Its `repositories-*.json` and Biotech JSONL inventories establish the missing SDL hash/length;
  it is not an independent full backup of the removed domain source.

Cleanup is complete. The original untracked
`docs/specs/archive/materialization-observation-2026-10/issues/bash.exe.stackdump` remains in the
canonical checkout, unchanged. The archive and the canonical Run 1 private receipts remain
ignored. Git deletion used normal merged-branch checks locally and exact-head conditional
remote deletion, so concurrent unmerged work was not discarded. Final main/origin readback is
recorded in the private cleanup receipt; this handoff and its public navigation are committed
on main. No provider, database or cloud deployment state was changed by this cleanup.
