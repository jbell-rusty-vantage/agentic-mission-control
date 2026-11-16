# Applied bundle source archive

`agent-skills-1.0.0/` preserves source blobs from commit `146c9eb` for the
agent-skill seeds applied to both projects on 2026-10-12. Original repository
relative paths are retained. These are immutable publication inputs, not active
skills or executable project code; formatting tools must not modify them.

`agent-skills-1.0.1/` preserves the three source bundles referenced by seed 1.0.1,
copied byte-for-byte from `5b03afc4f214d335b5ef5dc96ba33100f1fb4d67` before the
Run 2 documentation changes. Author and observe source bundles advance to 0.3.1
in seed 1.0.2. This is offline publication preparation; it does not apply a seed
or upload any bundle.

`agent-skills-1.0.2/` preserves the two source bundles seed 1.0.2 references
(`mission-control-author` and `mission-control-observe` 0.3.1), LF bytes from
`skills/` at Sprint OC `e66377a5`, frozen when seed 1.0.3 shipped
`mission-control-author` 0.3.2 (choose a Model Catalog profile the lane routes;
OC-R7, OVE-201). Seed 1.0.2's bytes are pinned in `FROZEN_BUNDLES`. Uploading the
0.3.2 bytes to the remote custody target and applying 1.0.3 are W0's; nothing
here uploads or applies.

`agent-skills-1.0.3/` preserves the one source bundle seed 1.0.3 references
(`mission-control-author` 0.3.2), LF bytes from `skills/` on Sprint OC, frozen when
seed 1.0.4 shipped the per-application knowledge charter skills
(`biotech-knowledge-charter`, `ai-engineer-knowledge-charter` 0.1.0; OVE-204). Seed
1.0.3's bytes are pinned in `FROZEN_BUNDLES`.

`agent-skills-1.0.4/` preserves the two source bundles seed 1.0.4 references
(`biotech-knowledge-charter` and `ai-engineer-knowledge-charter` 0.1.0), LF bytes
from `skills/` at `b6adfc39`, frozen when seed 1.0.5 shipped the coordinator bundles
regenerated from the guide and the imported method skills (2026-11-16). The AI
Engineer charter left `skills/` with that seed: revision 2 of its id is the copy
imported from the AI Engineer service. Seed 1.0.4's bytes are pinned in
`FROZEN_BUNDLES`.

The frozen seed JSON pins each manifest. `agent_skills.frozen_application_definitions`
rebuilds manifests from these bytes and rejects any mismatch. The bundle publisher
includes all these historical versions and the current successor, deduplicating
unchanged digest paths. Tests compare every applied seed with the recorded live
receipts and fetch historical bundles through the real custody implementation.

`approved-assets-1.0.0/` preserves `.agents/skills/mission-control-coordinator/`, the
source of `skill.mission-control-coordinator` and `prompt.coordinator.propose-workflow`
as `mc.catalog.approved-assets@1.0.0` published them, moved here byte for byte from
`.agents/skills/` at `b6adfc39`. ADR-0033 retired the skill; it is no longer a live
skill for any agent tool. `scripts/promote_coordinator_surface.py` and
`tests/unit/coordinator/test_coordinator_surface_promotion.py` read it here.

## Imported skills

`imported/<source>/<commit7>/<skill>/` holds method skills Mission Control mounts and
does not author: an exact copy of one skill directory of a sibling repository at one
commit. `imported/IMPORTS.json` records each copy: the owning repository, the commit,
the path, the minted identifier (`belllabs`, `<source>/<skill>`), the version, the
one-line description of its frontmatter and every file's sha256, git blob id and size.

| Source | Commit | Skills |
| --- | --- | --- |
| `knowledge-services` | `7bc4aee` | `knowledge-research`, `knowledge-verify` (from `apps/verification-executor/skills/`), `knowledge-acquisition-and-vetting`, `knowledge-verification`, `knowledge-ingest`, `knowledge-db`, `schema-explore` |
| `ai-engineer-service` | `b7e6e21` | `ai-engineer-knowledge-charter`, `content-authoring` |

Mission Control never edits a copy. An update is a new import at a new commit
(`python scripts/skills_import.py --import --source <name> --repo <checkout> --commit
<sha> --path <skill directory>`), which adds a directory and a record; the seed that
publishes it names the record's version (`seeds/agent_skills.py` `IMPORTED_SKILLS`)
and ships as a new seed version. `python scripts/skills_import.py --check` (part of
`make skills-check`, and a unit test) fails when a copy's bytes or file set differ
from its record or a copy has no record; it needs no sibling checkout and no git.
