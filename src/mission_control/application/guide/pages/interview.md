---
id: interview
title: Interview the user before a mission
summary: Look up what exists, ask what only the user can decide, write the brief, map it to the manifest.
---
The interview is the question-asking part of authoring. It ends when the user has confirmed a brief and you have written it as a Mission Manifest draft. No interview record is persisted yet: the brief travels as the manifest, so the manifest must carry the user's words.

## 1. Look up before you ask

Search what this server already has with {op:search}, list a kind with {op:list_kind}, and read one hit with {op:describe}. Then ask only what you could not find and what only the user can decide: the outcome, the bar for done, the money, the side effects.

## 2. Ask by purpose

Every mission: What outcome do you want, and why does it matter? How will we know it is done, and who judges? What may the run read? What may it change outside its own workspace? What is the ceiling on money, tokens and time? Who reviews before anything irreversible?

- Research: which question, which sources count as evidence, how recent, and the form of the answer (report, claim table, source list).
- Building content: for whom, in which form and length, from which approved material, and who signs off.
- Improving the system: which behaviour is wrong today, how to observe it, what must keep working, where the change lands (repository, branch) and who merges it.

Record each answer in the user's own words and quote them into the `description` fields. A paraphrase the user has not confirmed is a guess.

## 3. The brief, and where each part goes

| Brief | Manifest field under `mission` |
| --- | --- |
| Purpose | `title`, `description` |
| Goal | `goals[].description`, `goals[].importance` |
| Success criteria | `goals[].criteria[]`: `description`, `evidence`, `acceptance` (`assessment`, `human: review_accept` or `schema`) |
| Inputs | `inputs[]` of a `program` node (`name` with `artifact`, `value` or `from`); `environment.workspace.context` |
| Outputs promised | `outputs[]` of a `program` node (`name`, `form`, `schema`, `requirements`) |
| Budget | `environment.budget` (`usd`, `tokens`, `wall_clock`, `tool_calls`) and `environment.governors` (`depth`, `fan_out`, `iterations`, `rounds`, `patience`, `transfers`) |
| Side effects allowed | `environment.side_effects`: `read_only`, `workspace_write`, `external_write_reversible`, `external_write_irreversible`, `spend` |
| Lane and model | `environment.lane`, `environment.model.profile` (topics `lanes`, `models`) |
| Capabilities | `environment.capabilities[]` (`pin`, or `search` with `kind` and `as`), `agents`, `hooks`, `plugins` (topic `capabilities`) |
| Review gates | a `program` node with `behavior: human_gate` and `task` (`kind`, `prompt`, `reviewers`) |
| Route | `program.behavior`: `stage_graph` with `nodes`, or `goal_loop` with `objective` and `action_space` (topic `workflows`) |

{{generated}}

## 4. Before you launch

Check the selection with {op:check}. Compile with {op:compile} until the report has no blockers, then run {op:preflight}. Show the user the brief, the warnings and the budget ceiling, and stop for their approval before {op:submit} and {op:start} (topic `launch`).
