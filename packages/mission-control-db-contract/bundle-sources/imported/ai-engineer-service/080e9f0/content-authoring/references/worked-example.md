# Worked example: one module, from brief to submitted for review

The module teaches a developer to migrate a prebuilt ReAct agent to the current agent factory. It belongs to the comparative agent-orchestration course. It follows the one module released so far and applies this skill where that module fell short: claims are bound to the sections that depend on them, the text is split into lessons with one outcome each, and the activity is placed inside the module.

Operation and tool names are the ones confirmed in SKILL.md under Availability. Arguments are left out on purpose: read each tool's description, or `aieng_describe` for an operation. Ids, versions and counts are illustrative.

## 1. Brief

The author says: "I want a module that takes someone who followed a 2025 tutorial and gets their agent running on today's packages."

That is a topic, not an outcome, so the agent interviews before drafting. The author confirms:

| Item | Confirmed |
| --- | --- |
| Audience | A developer who has built one tool-calling agent in Python |
| Outcome | Given a tutorial script written for the prebuilt agent, the learner migrates it and names the change that fails silently |
| Prerequisite | The tool-calling lesson; creating a Python environment |
| The learner builds | Their own migrated script, plus a check that catches the silent change |
| Bounds | Model spend up to one dollar; stop and ask if a needed fact is not verified |

- `draft_work` with kind `brief`: the table above, plus the research details the tool description asks for (question, plan, time window, budget limit, and one course-content output).
- `propose_research` on that revision returns the problems to fix, or valid.
- The author accepts it with `accept_research`. Only a person can.
- `create_thread` and `append_message` record the interview: the author's turns word for word, each agent proposal with the retrieval it rested on.

## 2. Orient

The agent asks the guide for the reads, then sorts every fact the outcome needs.

| Fact | Held as | Sorted |
| --- | --- | --- |
| The new factory has no "prompt" parameter; "system_prompt" replaces it | verified | Teach |
| The model node is `model`; the prebuilt emitted `agent` | verified | Teach |
| Unpinned, the installer can resolve mixed major versions and exit with success | verified | Teach |
| "The parameter was renamed silently" | disputed: the call raises an error | Teach as a dispute |
| A human-in-the-loop failure under async calls | reported, not reproduced | Open edge |
| The TypeScript equivalents | nothing | Missing |

`inspect_authoring` lists the workspace's works (`list_works` on the other transports). No read finds works by the concept they cover yet, so the agent reads the titles and opens the candidates. If a module already teaches this outcome, the job is a revision of that work, not a new one. Here none does.

The TypeScript facts are missing and this outcome does not need them. The agent cuts them and lists a research request for the TypeScript variant.

## 3. Design backwards

The activity is written first:

> You are given `tutorial_agent.py`, written in October 2025. Make it run on today's packages. Paste its output from the old and the new environment, with package versions. In three sentences: which change failed loudly, which failed silently, and what did you add so the silent one cannot pass unnoticed again?
> A correct result has both outputs with versions, a script that runs, and an explanation that names the silent change. Do this alone.

Which change is the silent one is the answer. It goes in a hidden check, not in the text above.

To do that task the learner must know three things and nothing else. Each becomes a lesson.

## 4. Structure

```text
Module: Migrate a prebuilt ReAct agent              outcome: the one in the brief
  Lesson 1: Call the new factory                    outcome: replace the call and its prompt argument
  Lesson 2: Read the stream after migrating         outcome: name the node each update came from
  Lesson 3: Read what the installer resolved        outcome: say which versions were installed, and why
  Activity: Migrate the tutorial script             mandatory; proves the module outcome
```

The module states the outcome and its evidence rule, makes the activity a requirement, and names the tool-calling lesson as a recommended prerequisite. The agent proposes one alternative route, prior work (the learner's own already-migrated project), and leaves it as proposed.

## 5. Draft, children first

1. `draft_work` with kind `lesson`, three times. Each body follows the lesson skeleton. Each lesson carries bindings: the concept it covers, the library it uses, and each claim it supports, anchored to the block that states that fact. In lesson 1, a callout block teaches the dispute and is bound to the disputed claim as a contradiction.
2. `draft_work` with kind `activity`. The hidden check is bound as hidden.
3. `draft_work` with kind `module` (`create_work` through the API or `aieng command`). The module's body holds a short introduction, the open-edges section and the how-we-know section. The same call places the three lessons and the activity at their exact revisions, and carries the outcome, the requirement with its proposed route, the prerequisite, and the version range claimed with the versions resolved.
4. Read back: `inspect_authoring` for each lesson, the activity and the module, then its exposure preview for what the module places and binds. Availability says what no read returns.

Check: every factual block shows its binding. The open edge shows the report, its link, the versions tried and what to do on meeting it.

## 6. Run it

The agent writes the expected result of each lesson, then runs each one in two environments: one resolved as of October 2025, one current. The model is scripted, so runs repeat and cost nothing.

| Unit | Expected | Ran |
| --- | --- | --- |
| Lesson 1 | The old argument raises an error | As expected |
| Lesson 2 | A filter on the old node name finds nothing | As expected: it prints nothing and raises nothing. The lesson shows the empty output. |
| Lesson 3 | The unpinned install exits with success while one package is held a major version back | As expected, in the old environment |
| Activity | The agent, working as the learner, can produce the evidence | Differed: the tutorial script stopped on an import that has moved to another package |

The difference is the useful part. The moved import is a verified claim the design missed. Lesson 1 gains a block that states it, bound to that claim, and its example runs again. That edit is a new lesson revision, saved with `draft_work`. The module still pins the old one, so a new module revision places the new lesson revision (`draft_work` on the module; `revise_work` on the other transports). The activity runs again and now produces both outputs and the explanation.

Four run records exist. The lesson pages are built from the files that ran and their recorded output.

## 7. Prepare the review and stop

1. `inspect_authoring` for the exposure of the module's root revision (`preview_exposure`), at the ceiling the author intends (named readers). The result: the module, its three lessons, the activity and the prerequisite lesson included; the claims included; sources by reference; the hidden check withheld; and one blocker, a vendor page bound as a private copy.
2. The agent proposes: ship that page as a reference to the original address. Reason: the lesson quotes one line and links to the page.
3. `request_review` with the module revision, that ceiling, the brief's course-content output and the hand-over below as its note. It leaves the note in a workspace conversation tied to the revision and delivers the revision against that output (`append_message` and `deliver_output` on the other transports). It records no review.
4. The hand-over:

```text
Submitted for review: module "Migrate a prebuilt ReAct agent"
Root revision <id>. Places lessons 1 to 3 and the activity at revisions <ids>.
Outcome: migrate the tutorial script and name the silent change. Proven by the activity (mandatory).
Runs: 3 lessons and the activity on <date>; old environment as of 2025-10-16, current environment <versions>; scripted model; 0 of 1 dollar spent.
Evidence: 4 verified claims, each bound to the block that states it. 1 dispute taught. 1 open edge (reported, not reproduced). Nothing labelled general knowledge. Research requested: the TypeScript variant.
Exposure at named readers: closure <digest>. 1 blocker: vendor page held as a private copy. Proposed: reference to the original.
Gaps: no learner has taken it. Lesson 3 ran on one operating system.
```

The agent stops here. The author decides the delivery (`decide_delivery`), records the release review (`review_revision`), and freezes and offers the release (`freeze_release`, `open_distribution`, `offer_release`).

## 8. Later: a claim moves

A new release of the library ships. `inspect_knowledge` for what is due, given that release, lists this module (`list_due`), because its head revision is older than the release. The checks behind its bound claims are re-run on the new version.

- **Verdicts unchanged:** the agent reports "no change" for the module, with that reason. Nothing is revised.
- **A verdict changes on a bound claim** (say the installer no longer resolves mixed versions): the release is listed as needing review. The agent drafts a new revision of lesson 3 that states the behaviour by version, re-runs it in both environments and binds the block to the restated claim. It revises the module to place that revision, writes the change note (presentation only; progress carries on every requirement) and hands over. The first release stays as its learners studied it.
