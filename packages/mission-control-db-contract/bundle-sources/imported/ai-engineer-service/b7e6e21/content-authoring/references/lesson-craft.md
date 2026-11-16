# Lesson craft: lessons and activities a learner can run

Rule: a lesson earns its place with one outcome and proves itself by running. Write the check first, the example second, the prose last.

## The five parts of a lesson

1. **One outcome.** A sentence that starts with what the learner does and that another person can check. "Understands streaming" fails. "Reads a stream of updates and names the node each one came from" passes.
2. **A worked example.** A complete, small program or procedure that ran, with its real output and the versions it ran on.
3. **A task the learner performs.** A changed case: the same idea with a different input, version or constraint, so copying the example does not solve it.
4. **A check of the result.** What a correct result contains, stated so the learner can tell done from not done.
5. **Declared assistance.** Say for each task whether it is done with the agent or alone. The agent builds with the learner in the worked example and steps back for the changed case.

A lesson that lacks part 3 or 4 is an explanation. Either give it a task and a check, or fold it into the lesson it serves.

## The activity

The activity is the module's proof. It is where the learner's own work is produced and mastery is shown.

- **One task, in the learner's own environment.** The learner runs it, not you.
- **Evidence that can be fixed.** Ask for outputs with their versions, a project revision, a file set, a deployment or a commit. A submission is frozen; later edits never change it, so a moving link is not evidence.
- **The learner's own words.** Ask for a short explanation that only someone who did the task could write.
- **State what the checker looks for,** in the activity itself.
- **Assistance is declared, not policed.** Each attempt records whether it was independent, assisted or agent-directed. Design the final task for an independent attempt and say so.
- **Answer keys stay hidden.** Bind solutions and hidden checks in the hidden-check or solution role, or as what the work is evaluated with; a release withholds those bindings. Never place them as parts: a placed part ships. They never sit in the body or in Sources and decisions.
- **A task that looks like an assessment grants nothing by looking like one.** A generated task is practice until a maintainer, or an approved policy, accepts it as evidence for a requirement.

The one released activity, as a model:

> Create an old and a new environment. Run the two named checks in both. Paste the output each prints. In three sentences: which change fails loudly, which fails silently, and what would you add to your own code to catch the silent one?
> Evidence the checker looks for: both outputs with their package versions, and an explanation that names the silent change.

## Run it before review

Every lesson example and every activity runs once, as written, before a reviewer sees it. An example edited after its last run counts as not run.

- **Pin the environment.** Record the version range you claim, the exact versions that resolved, the model, the operating system and the date. To show how something behaved in the past, resolve the environment as of that date.
- **Write the expected result before you run.** A difference is a finding. In the first module, the three results that differed from the expectation were the most useful teaching material.
- **Prefer a deterministic setup:** a scripted model and fixed inputs give the same result on every run and cost nothing. Use a live model only where the behaviour needs one, and then record the runs, tokens and cost. A live run never verifies a claim alone.
- **Keep a run record per lesson:** command, exit code, duration, output, tokens, cost and time.
- **Build the page from the run.** Code and output on the page come from the files that ran and their recorded output. Output is never typed by hand.
- **Stay inside the brief's budget** and report the total. Thirteen lessons ran on a small model for about nine cents.
- **Read keys by name from the environment.** No secret appears in a lesson, a file or a run record.

Do the activity yourself the same way, as the learner would, and keep what you produced. If you cannot produce the evidence the activity asks for, the learner cannot either.

## Rules from the "Agents That Act" prototype

Thirteen lessons were run for real on 2026-11-13. These rules state what that record shows. No learner has taken the prototype, so they are rules for honest, runnable lessons, not proof of what teaches best.

1. **Teach the real result, including the wrong one.** The structured-output lesson got a valid shape that contained a wrong import: shape is not truth. The graph lesson got a wrong count. Both stayed in.
2. **Show your own first failure and its fix.** The streaming lesson's first run printed an empty tool result. The lesson shows that, then the fix from the documentation.
3. **Carry a failure forward until a later lesson measures it.** The wrong count returned when the agent was deployed. The final lesson built a small evaluation, rewrote two tool descriptions and moved the score from 2 of 8 to 8 of 8.
4. **Report what happened, not what the documentation promises.** On a small task the deep agent skipped its planning tool and its subagent. The lesson says so.
5. **One running example through the whole module,** fed with data exported from the knowledge base.
6. **Take check answers from the knowledge base,** never from the model under test.
7. **Each lesson is one small hand-written runnable file.** The prototype's were 24 to 59 lines; the deployment lesson was three small files.
8. **Show time and the real system.** The owner found a summary page underwhelming because it lacked how the libraries moved through time, the technical and system design, real class and function usage, and deployment. A technical module carries all four.
9. **Show disagreements between sources.** Four first-party dates disagreed with the registry or the original announcement. The page shows each pair and does not pick a winner silently.
10. **Label what the knowledge base does not hold.** Founders, funding and some definitions carried a "general knowledge" label and went on a list for ingestion.
11. **Record the environment traps you hit.** The deployment lesson needed an extra package on one operating system, and says so.
12. **A prototype says it is a prototype.** A page that ran is an artifact. It becomes a module only when it is drafted as a work, bound, run and reviewed.

## Blocks and media

- A lesson body is a list of typed blocks. Ask the guide for the current block types and what each requires.
- Rich blocks need a text fallback: images, diagrams, video, tables, charts, quizzes, math, interactive and embedded content. Text, callouts, code listings and sections need none. The service refuses a block that lacks a required fallback. A video needs its original, a transcript and captions.
- Blocks keep stable keys across revisions. A learner's note follows its block into the next revision; a note on a removed block does not. When you revise a section, keep its key. When you replace it with something different, give the new block a new key.
- To show something you built, publish the built folder, then embed it with a block bound to the published files.

## Skeleton

```text
Lesson: <verb phrase>
Outcome: You can <do X>, shown by <evidence>.
Before you start: <prerequisite>; <versions and date this ran on>
Worked example (with the agent): <the file that ran>
Output: <what it printed, from the run record>
What happened: <three to six sentences; each fact bound to its claim>
Your turn (alone): <the changed case>
Check: <what a correct result contains>
Open edges: <reports not yet verified that touch this lesson>
```
