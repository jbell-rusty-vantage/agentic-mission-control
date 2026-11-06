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

The frozen seed JSON pins each manifest. `agent_skills.frozen_application_definitions`
rebuilds manifests from these bytes and rejects any mismatch. The bundle publisher
includes all these historical versions and the current successor, deduplicating
unchanged digest paths. Tests compare every applied seed with the recorded live
receipts and fetch historical bundles through the real custody implementation.
