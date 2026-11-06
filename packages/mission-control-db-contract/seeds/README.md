# Mission Control seed bundles (content)

Format `mission-control-seed/v1` (`src/mission_control_db_contract/schemas/seed-bundle.v1.schema.json`,
enforced by `mission_control_db_contract.seeds`). Bundles are generated from repository
sources by `generate_catalog_seeds.py`; never edit the JSON by hand. A changed source needs
a new seed version, not new bytes under an applied version.

Source paths in bundles dated before 2026-10-23 cite `docs/specs/<packet>/...`; the packets moved to
`docs/specs/archive/<packet>/` (see that folder's README). The strings are corrected at the next version
of each bundle, not in place.

| Directory | Bundle | Content | Apply to |
| --- | --- | --- | --- |
| `common/` | `mc.catalog.workflow-parity@1.0.0` | StageGraph / GoalDirected workflow-family vocabulary (registered blueprint contract, Temporal workflows and activities) | both apps, identical bytes |
| `common/` | `mc.catalog.workflow-parity@1.0.1` | Successor of 1.0.0 (frozen): frozen Human Gate registration snapshot, as asset version 2; never rewrites a 1.0.0 logical key | both apps, identical bytes |
| `common/` | `mc.catalog.workflow-parity@1.0.2` | Current registration including terminal workflow-result materialization, as new asset version 3; depends on frozen 1.0.1 | both apps, identical bytes |
| `common/` | `mc.catalog.runtime-profiles@1.0.0` | runtime persistence descriptor pins; Agent Server graph pins (native persistence unqualified) | both apps, identical bytes |
| `common/` | `mc.catalog.approved-assets@1.0.0` | `skill.mission-control-coordinator`, `prompt.coordinator.propose-workflow` (published-definition r1), canonical `skills/mission-control` manifest | both apps, identical bytes |
| `ai-engineer/` | `mc.app.ai-engineer.artifact-schemas@1.0.0` | D5 SDLC report schemas `schema.sdlc-diagnosis-report@1`, `schema.sdlc-patch-report@1`, `schema.sdlc-review-report@1` (published-definition r1, from `sdlc_report_schemas.py`); additive to `mc.catalog.artifact-schemas@1.0.0`, component `>=1.4.1 <2.0.0` | ai-engineer only |
| `common/` | `mc.catalog.artifact-schemas@1.0.1` | Successor of 1.0.0 (applied bytes untouched, only new logical keys): Sprint OC W2 graph-variant schemas `schema.w2-triage-verdict@1`, `schema.w2-scan-flag@1`, `schema.w2-critique-verdict@1` (WI-08 route and Revisit Region facts, from `graph_route_schemas.py`); depends on 1.0.0 | both apps, identical bytes |
| `biotech/`, `ai-engineer/` | `mc.app.bindings@1.0.0` | app identity from `deployments/<app>/target.toml`, secret reference names only | that app only |
| `qualification/` | `mc.qualification.parity@1.0.0` | OPT-IN synthetic qualification tenant + generic contract-fixture blueprints | disposable / approved qualification only |

Deliberately not seeded: product Workflow Types and implementation bindings (application
owned; none exist in the common kernel), provider/model routes, secrets or DSNs, embeddings
or search projections, missions, runs, receipts, usage, evidence, memberships, actor
bindings, actor grants and capability grants.

## Approved tenant/actor mappings (empty placeholder)

No tenant, actor binding or grant for a real user or service is seeded. When the owner
approves concrete mappings for an app (external tenant ref, issuer/subject, minimal grant),
add a new bundle `mc.app.grants@<version>` under that app's directory depending on
`mc.app.bindings`, record the approval reference in its description, and keep revoked
grants revoked. Until then `approved_tenant_actor_mappings` in each app binding is `[]`.
