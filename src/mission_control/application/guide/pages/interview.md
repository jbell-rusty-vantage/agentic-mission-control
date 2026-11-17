---
id: interview
title: Interview the user before a mission
summary: Look up what exists, ask what only the user can decide, record the brief in the manifest, map the rest to its fields.
---
The interview is the question-asking part of authoring. It ends when the user has confirmed a brief and you have written it into the Mission Manifest draft (section 3).

## 1. Look up before you ask

Search what this server already has with {op:search}, list a kind with {op:list_kind}, and read one hit with {op:describe}. Then ask only what you could not find and only the user can decide: the outcome, the bar for done, the money, the side effects.

## 2. Ask by purpose

Every mission: What outcome do you want, and why does it matter? How will we know it is done, and who judges? What may the run read? What may it change outside its own workspace? What is the ceiling on money, tokens and time? Who reviews before anything irreversible?

- Research: which question, which sources count as evidence, how recent, and the form of the answer (report, claim table, source list).
- Building content: for whom, in which form and length, from which approved material, and who signs off.
- Improving the system: which behaviour is wrong today, how to observe it, what must keep working, where the change lands (repository, branch) and who merges it.

Record each answer in the user's own words. A paraphrase the user has not confirmed is a guess.

## 3. The brief, and where each part goes

The interview ends in the `brief` block under `mission`. The user's words go there verbatim: do not summarise, correct or translate them.

```yaml
brief:
  purpose: research
  request: >-
    The request, exactly as the user wrote it.
  answers:
    - question: What you asked.
      answer: >-
        What the user answered.
  done_means: >-
    What the user said finished looks like.
  out_of_scope:
    - What the user ruled out.
```

{{generated:brief}}

Then map the rest. Start from a template (topic `templates`): its slots are the answers below. Every goal, objective, criterion, node and program has a `key`, a slug you choose.

| Brief | Manifest field under `mission` |
| --- | --- |
| Mission | `key`, `title`, `description` |
| Goal | `goals[]`: `key`, `description`, `importance` (`primary`, `secondary` or `optional`), `objectives[]` (`key`, `description`) |
| Success criteria | `goals[].criteria[]`: `key`, `description` (the node owing the evidence is told it), `evidence` (a list of output names), `acceptance` (a typed expression such as `human: review_accept`; topic `manifest` says which can start) |
| Inputs | `inputs[]` of a `program` node (`name` with `artifact`, `value` or `from`); `environment.workspace.context` |
| Outputs promised | `outputs[]` of a `program` node: `name`, then `form` (`text` for prose) or a `schema`; `requirements`; delivered only via `submit_output` (topic `manifest`) |
| Budget | `environment.budget` (`usd`, `tokens`, `wall_clock`, `tool_calls`) and `environment.governors` (`depth`, `fan_out`, `iterations`, `rounds`, `patience`, `transfers`); both are required |
| Side effects allowed | `environment.side_effects`: `read_only`, `workspace_write`, `external_write_reversible`, `external_write_irreversible`, `spend` |
| Lane and model | `environment.lane`, `environment.model.profile`, and `environment.sandbox.profile` where the lane requires a sandbox (topics `lanes`, `models`, `manifest`) |
| Capabilities | `environment.capabilities[]` (`pin`, or `search` with `kind` and `as`), `agents`, `hooks`, `plugins` (topic `capabilities`) |
| Work | a `program` node with `behavior: agent_executor`: `key`, `objectives` (goal or objective keys) and its `instruction` (the task alone) |
| Review gates | a `program` node with `behavior: human_gate`: `key` and `task` (`kind`, `prompt`, `reviewers`) |
| Route | `program`: `key` and `behavior`, `stage_graph` with `objectives` and `nodes`, or `goal_loop` with `objective` and `action_space` (aliases that name a capability, agent, plugin or node) (topic `workflows`) |

{{generated}}

## 4. Before you launch

Check the selection with {op:check}. Compile with {op:compile} until the report has no blockers, then run {op:preflight}. Show the user the brief, the warnings and the budget ceiling, and stop for their approval before {op:submit} and {op:start} (topic `launch`).
