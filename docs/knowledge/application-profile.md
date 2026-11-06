---
type: Concept
category: boundaries
title: The Application Profile
description: "How what may differ per application (knowledge port, Data Class ceiling, output minimums, transfer defaults, hosted session retention, installation defaults) is declared as data in deployments/<app>/application.toml, selected by the installation's application id, validated by the Application Registry and read by the gateway, the manifest compile and the launch author, so the kernel names no application."
tags: [mission-control, applications, resolution, knowledge-services, data-class, implementation]
aliases: [application.toml, Application Registry, per-app profile]
questions:
  - What may differ per application and where is it declared?
  - Which Data Class ceiling and knowledge binding does an application use?
  - Why was my mission refused as application_unknown?
updated: 2026-11-01
---

# The Application Profile

An **Application Profile** (`mc.application_profile.v1`, ADR-0063, OC-R4) is one file per
application, `deployments/<app>/application.toml`, beside the installation identity
`target.toml`. It carries:

- `[knowledge]`: the K01 binding id, the apply contract name and version, the native payload
  layout (`intent_schema_ref`), storage class, write atomicity and readback capability;
- the Data Class ceiling, and the hosted session retention in days, which nothing reads yet: the
  interval in force is the 7-day `DEFAULT_SESSION_RETENTION_POLICY`, because the hosted lane
  composition passes no policy (R7 residual S2b);
- `[outputs]`: the assessment pin and the use classes that need review and human sign-off
  (annex OUTPUT-CONTRACTS §5 minimums; authors may tighten, never weaken);
- `[transfer]`: custody backend, inline byte ceiling, file and binary capability (the last two
  carried into the resolved runtime and not yet read; W2);
- `[workspace]`: Workspace Closure caps and retention (`closure_enabled`, `closure_max_files` 512,
  `closure_max_bytes` 64 MiB, `closure_retention` `"mission"` or at least 30 days;
  `WorkspaceClosureProfile`, `domain/resolution/profiles.py:143`), see [workspace closure](workspace-closure.md);
- `charter_skill`: the knowledge charter skill that compile mounts on every knowledge mission of the
  application (`deployments/ai-engineer/application.toml:41`, seed `mc.app.ai-engineer.agent-skills` 1.0.4;
  tested, local bundle publish only; not mounted in the provenance proof run);
- `[installation]`: operator defaults the settings fall back to (task queue, LangSmith projects,
  capability resource owner). This table is the loader's, not part of the profile type.

The kernel names no application, binding or apply contract as a value; an architecture test
pins it. The values and the source of each non-obvious one are commented in the files.

## Selection and validation

An installation serves one application. Its id selects its file under the deployments root
(`MISSION_CONTROL_DEPLOYMENTS_ROOT`, default `<MISSION_CONTROL_HOME>/deployments`):
`compose_application_registry(root, ids)` loads exactly the named ids, nothing is discovered,
and a missing, invalid or misplaced file fails closed. The API and workers pass their
Application Binding's id; `MISSION_CONTROL_APPLICATION` selects whose `[installation]` defaults
`Settings` and `WORKSPACE_ROOT` use when the environment does not set them.
`ApplicationRegistry.register` refuses a profile below the annex minimums (review of
`official` and `consequential` use, sign-off of `consequential`, in the KS use-class vocabulary).

## Readers

- **Knowledge gateway.** `KnowledgeGateway(knowledge=KnowledgePortBinding)`; `apply_decision`
  takes the contract from the port and builds the payload with the layout the port names
  (`application/knowledge/apply_payload.py`): `plan_with_exact_use` (plan fields with the full
  exact use; the host carries the recorded bound digest) or `intent_envelope`
  (`{schemaVersion: "<name>.<version>", intent, exactUse}`; the host binds the plan bytes and
  refuses a decision that does not bind them). An unknown layout refuses `SCHEMA_UNSUPPORTED`
  before anything is journalled. Knowledge composition takes the binding from the profile.
- **Manifest compile.** `application` is an open id; compile refuses one the installation's
  registry does not hold (`APPLICATION_FORBIDDEN`, reason `application_unknown`).
- **Launch.** The resolver returns the profile's knowledge, output and transfer sides and
  refuses a Data Class above the ceiling. A mission that declares no Data Class is the most
  sensitive class its lane and its application's ceiling admit (`undeclared_data_class`), never
  a fixed stand-in; `AgentConfiguration.data_class_source` (`declared` | `ceiling_default`)
  enters the configuration digest, so the two never seal alike. Hosted agent API lanes still
  refuse an undeclared mission.
- **Where the ceiling binds.** Only at resolution, which today covers Deep Agents nodes; R3 routes
  the other lanes through the resolver. The Application Binding's hosted widening (HL-18) is
  held at or below the ceiling: manifest composition refuses a binding that widens past it.
- **Installation settings.** No neutral queue or capability owner: `TEMPORAL_TASK_QUEUE` /
  `MISSION_CONTROL_WORKSPACE_ROOT` (`.env` applies) or the selected profile supply them, else
  `Settings.task_queue_base` / `workspace_root` raise `InstallationDefaultUnavailable`. The API
  derives its queues from the installation (`TemporalDeployment.queue_base`), as the worker does,
  and both refuse a `MISSION_CONTROL_APPLICATION` other than the binding's.

## Drift

`tests/conformance/applications` checks each profile against a checked-in copy of the KS
backend descriptors (`ks_backend_descriptors.json`, KS commit recorded): the binding is
advertised, the apply contract equals `nativeContract`, storage class and atomicity agree, and
readback is declared only where served. W0 repeated the check against each live `knowledge.describe` (ai-engineer 15/15; see the bundle's section 5.1,
[RELEASE-BUNDLE](../specs/provider-consolidation-2026-10/sprint-oc/release/RELEASE-BUNDLE.md) line 92).

Built / specified / goal: profile loading, registry validation, the readers above and drift conformance are
implemented and tested; the hosted session retention number and the file/binary transfer flags are declared
but unread (S2b, W2); per-application ceilings on lanes other than Deep Agents wait on R3.

## Citations

- Decision: [ADR-0063](../adr/0063-one-resolution-seam-over-declared-lane-model-and-application-registries.md);
  [selection and routing design §6.2-6.3, §9.2](../specs/archive/provider-consolidation-2026-10/specs/SELECTION-AND-ROUTING-DESIGN.md).
- Data: [AI Engineer profile](../../deployments/ai-engineer/application.toml),
  [Biotech profile](../../deployments/biotech/application.toml).
- Code: [loader](../../src/mission_control/bootstrap/application_profiles.py),
  [profile type and minimums](../../src/mission_control/domain/resolution/profiles.py),
  [registry](../../src/mission_control/application/resolution/registries.py),
  [payload layouts](../../src/mission_control/application/knowledge/apply_payload.py),
  [gateway](../../src/mission_control/application/knowledge/gateway.py),
  [Data Class](../../src/mission_control/domain/execution/data_class.py),
  [settings](../../src/mission_control/bootstrap/settings.py).
- Proof: [W0 release bundle](../specs/provider-consolidation-2026-10/sprint-oc/release/RELEASE-BUNDLE.md).
- Tests: [profile conformance](../../tests/conformance/applications/test_application_profiles.py),
  [settings defaults](../../tests/unit/config_api/test_application_defaults.py),
  [undeclared Data Class](../../tests/unit/authoring/test_manifest_launch_resolution.py),
  [gateway](../../tests/unit/knowledge/test_gateway.py),
  [kernel names no application](../../tests/architecture/test_package_boundaries.py).
