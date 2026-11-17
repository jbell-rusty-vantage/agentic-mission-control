---
name: mission-control-author
description: Interview the user and author a Mission Manifest with missionctl - fill a template, record the brief, compile, preflight, submit and start. Use for a new mission, an edit to a manifest, a refused compile or a launch.
---

# Author a mission

A Mission Manifest is the YAML you write; the compiler decides what it means. A mission starts
from the user's words: the interview ends in the manifest's `brief` block, and every node is told
that brief on its purpose card.

Facts come from the server: `missionctl guide TOPIC` for each page named below,
`missionctl describe manifest` for every field and `missionctl describe template:ID` for a
template. The references are those pages as this release rendered them.

## Order of work

1. **Interview.** Look up before you ask (`missionctl search`, `missionctl describe REF`), then
   ask what only the user can decide. Done when the user has confirmed each answer in their own
   words. [interview](references/guide-interview.md)
2. **Start from a template.** `missionctl search --facet template`, then
   `missionctl describe template:ID`. Fill every slot; the brief slots take the user's words
   verbatim. Done when no slot remains. [templates](references/guide-templates.md)
3. **Select.** Lane, Model Profile, sandbox profile and capabilities come from the
   `mission-control-catalog` bundle. Done when `missionctl workspace check DRAFT` admits the
   selection.
4. **Compile.** `missionctl mission compile FILE`, fixing the manifest at each blocker's
   `pointer`. Done when the report has no `blockers` and says `startable: true`.
   [manifest](references/guide-manifest.md), [launch](references/guide-launch.md)
5. **Preflight.** `missionctl preflight FILE`. Relay every unmet owner step as printed.
6. **Stop for approval.** Show the user the brief, the goals, the lane, the model, the budget
   ceiling, the side effects and every warning. Done when the user says yes to this manifest.
7. **Submit.** `missionctl mission submit FILE --request-id UUID`. Keep the `mission_id`, the
   `revision_id` and the `run_id` (or the `chain_id`).
8. **Start**, when the user asked for the start: `missionctl mission start RUN_ID`. Keep the
   `run_id` and the coordinator inbox `subscription_id`, then continue with
   `mission-control-observe`.

## Rules that never bend

- The brief is the user's words: record them, never summarise, correct or translate them. A
  paraphrase the user has not confirmed is a guess.
- The report is evidence. Change the manifest, never the report.
- A node may only narrow the budget, governors and side effects it inherits.
- A manifest names secrets and carries none. `mission.application` is this server's
  application id.
- After submit, a change is a new revision: edit the file and submit again.

## Common mistakes

- Writing a manifest from nothing where a template fits.
- Mission-level `inputs`: the manifest refuses them. An input belongs to a `program` node.
- Free-text `acceptance`: it is a typed expression and only some can start. The manifest page
  has the table.
- Guessing a field: `missionctl describe manifest:SECTION` prints the mapping.
- Reading `ok: true` as launchable: read `startable` and `start_blockers`.
- Submitting to see whether it compiles: compile and preflight commit nothing, submit commits.
- Adding watchers after submit: `controls.watchers` belong to the revision
  (`missionctl describe manifest:WatcherDeclaration`).
