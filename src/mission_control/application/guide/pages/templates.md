---
id: templates
title: Mission templates
summary: The curated manifests to start from, what each is for, and how to fill one.
---
A template is a whole Mission Manifest with named slots. Start from one; write a manifest from nothing only when no template fits (topic `manifest`).

{{generated}}

## Fill one

1. Read it with {op:describe_template}: its slots, its notes and the manifest.
2. Replace every slot with the user's answer from the interview (topic `interview`). Take `application_id` from the start page, `model_profile` from topic `models`, `sandbox_profile` from topic `manifest` and, to review the result yourself, `reviewer` from {op:whoami} (`actor_id`).
3. Change what the brief needs changed: the budget, the governors, the capabilities (topic `capabilities`). Keep the keys consistent (topic `manifest`).
4. Compile until the report has no blockers and says `startable: true` (topic `launch`).

List the templates with {op:list_templates}. A template pins each capability at its latest admitted revision (`<id>@latest`): its instructions rely on those exact tools, so it names them. Write `{search: "...", kind: <kind>, as: <alias>}` instead where the user wants whatever does the job on this installation (topic `capabilities`).
