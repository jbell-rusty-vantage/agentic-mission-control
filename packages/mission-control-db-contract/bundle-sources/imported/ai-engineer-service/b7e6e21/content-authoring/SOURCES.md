# Sources for the content-authoring skill

Written 2026-11-15 for the integrator and moved here with the skill on 2026-11-16. It is not part of the shipped skill and the guide does not serve it: it names records, code files and database objects that the skill itself must not name. Links were recomputed for this folder. Those that leave this repository point into the BellLabs workspace it is checked out in, which is not part of this repository.

## Integration note, 2026-11-16

The skill was checked against the service source and the database functions when it was integrated. Sections 1 to 6 below are the author's record of 2026-11-15 and are left as written; where they disagree with this note, this note is newer.

Corrected in the skill:

1. **Knowledge reads exist.** Availability said verified claims with their verdicts, source track records, releases needing review and the works a software release affects were database reads with no service tool. They are operations and MCP tools ([operations](../../packages/contracts/src/operations.ts), [knowledge tools](../../apps/mcp/src/tools/knowledge-tools.ts)). Only finding works by the concept they cover still has no service read. This also answers the first half of section 5 row 2 and the seventh item of section 4.
2. **Structure through MCP.** `draft_work` now carries parts, outcomes, requirements with their routes, prerequisites, runtime requirements and statements ([authoring tools](../../apps/mcp/src/tools/authoring-tools.ts)); `inspect_authoring` reads works, a revision and the exposure preview; `request_review` leaves the hand-over note. Section 5 rows 4, 5 and 7 are stale on those points. The worked example was changed to match.
3. **`read_lesson` renders any readable revision** (section 4, fourth item): the read behind it has no check on the kind of work. It returns the title, the body, the block list and the caller's private notes, and does not follow parts.
4. **Who is refused.** The service refuses an agent client for the four human review types, accepting research and deciding a delivery. It does not refuse freezing, opening a distribution, offering or ending an offer by client kind; those need the role and, for freezing and offering, a person's matching review. A request with only the user's session counts as a person, not only an interactive CLI session (section 2 item 6). Availability now says both.
5. **Hidden material is a binding, not a part.** Lesson craft said to bind solutions and hidden checks "as hidden parts". A release withholds a binding in the hidden-check or solution role, or one the work is evaluated with; a placed part always ships.
6. **Fallbacks.** Lesson craft said every block that is not plain text needs a text fallback. Callouts, code listings, sections, the sources panel and snippet references need none.
7. **The transcription case is closed** (section 2 item 5, and the inference "narrowing the transcription case to named readers" in section 6). The service task that integrated the skill states the rule without an exception: an agent never records a human review itself. Review and release now says so and keeps the lab precedent as a record only. If John wants the written-instruction case back, it returns in that file.
8. **Example parameter names** are no longer written as code spans, because the repository test reads a code span as a tool, operation or command name.

Still true after integration: no run record, no submitted-for-review state outside an accepted brief, no feedback operation, no release transition writer, nothing schedules the keep-current reads. New findings: no operation lists the shared workspaces a caller belongs to; no read returns a saved revision's bindings, parts, outcomes, requirements, prerequisites or runtime requirements; and on the lab a statement that names the shared claim it restates is refused with `NOT_FOUND: cited shared claim`, while a claim binding on the same block is accepted.

Section 6 item 1 moved on 2026-11-16: a claim binding anchored to one section of a lesson was saved, read back in the exposure preview and handed over, through MCP and through HTTP, by the consumer evaluation ([script](../../scripts/consumer-surface-eval.ts)). Whether search reads the anchor is still unproven.

Status words used below:

- **accepted**: an owner decision in a review record.
- **lab-proven**: ran on the disposable lab stack; not integrated, not deployed.
- **code**: what the service or the database functions enforce today.
- **direction**: owner direction that approves nothing.
- **proposed**: written in a record as a proposal; not accepted.
- **inference**: my own step from the sources. Each one is listed again in section 6.

Records, short names:
[SERVICE-MODEL](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/EDUCATION-SERVICE/SERVICE-MODEL.md) ·
[SERVICE-SPEC](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/EDUCATION-SERVICE/SERVICE-SPEC.md) ·
[CONSOLIDATED-MODEL](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/FEATURE-CONSOLIDATION/CONSOLIDATED-MODEL.md) ·
[Build 01](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/BUILD-01-COURSE-FOUNDATION.md) ·
[Build 05](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/BUILD-05-CONTENT-AND-PROJECTS.md) ·
[Build 07](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/BUILD-07-RESEARCH-TO-CONTENT.md) ·
[Build 08](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/BUILD-08-KNOWLEDGE-LOOP.md) ·
[loop-4 module](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/BUILD-08-LOOP-4-MODULE.md) ·
[loop-4 selection](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/BUILD-08-LOOP-4-SELECTION.md) ·
[loop-8 handoff](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/NEXT-SESSION-BUILD-08-AFTER-LOOP-8.md) ·
[course README](../../../../aiengineer/ai-engineer-db-contract/scripts/knowledge-lab/course/README.md) ·
[HOLLODECK](../../../../HOLLODECK.md) ·
[NORTH-STAR](../../../../NORTH-STAR.md)

Mechanics, short names:
[operations](../../packages/contracts/src/operations.ts) ·
[payloads](../../packages/contracts/src/payloads.ts) ·
MCP tools ([authoring](../../apps/mcp/src/tools/authoring-tools.ts), [research](../../apps/mcp/src/tools/research-tools.ts), [learning](../../apps/mcp/src/tools/learning-tools.ts), [attempts](../../apps/mcp/src/tools/attempt-tools.ts)) ·
[CLI commands](../../apps/cli/src/commands.ts) ·
[service skill](../../skills/ai-engineer/SKILL.md) ·
[authoring page](../../../../aiengineer/ai-engineer-db-contract/workspace/domains/authoring.md) ·
[curriculum page](../../../../aiengineer/ai-engineer-db-contract/workspace/domains/curriculum.md) ·
[scope](../../../../aiengineer/ai-engineer-db-contract/workspace-scopes/course-authoring.json) ·
[product API](../../../../aiengineer/ai-engineer-db-contract/supabase/migrations/20261105010300_product_api.sql) (`product.exposure`, `product.insert_revision`) ·
[command dispatch](../../../../aiengineer/ai-engineer-db-contract/supabase/migrations/20261108120000_build08_r2_knowledge_continuum.sql) (`product.dispatch_command`) ·
[loop-5 migration](../../../../aiengineer/ai-engineer-db-contract/supabase/migrations/20261113160000_build08_loop5_ranking_rules_revalidation_triage.sql) (`api.releases_needing_review`)

Writing rules followed: [writing-for-agents](../../../../platform/mission-control/.claude/skills/writing-for-agents/SKILL.md).

## 1. Where each rule came from

### SKILL.md

| Rule | Source | Status |
| --- | --- | --- |
| Content ends in the learner's own work and demonstrated mastery | HOLLODECK, "What the student experiences"; [root AGENTS](../../../../AGENTS.md), education preview direction | direction |
| Every factual statement traces to verified knowledge; traceability is the required experience | SERVICE-MODEL §4; Build 08 §12.3 (circularity rule, accepted as R2.1 in §12.9) | accepted |
| Verified only through Knowledge Services admission of external evidence | [Build 08 §23](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/BUILD-08-KNOWLEDGE-LOOP.md#s23) row 4 (keep the gate, D-55); NORTH-STAR §3 rule 5 | accepted |
| What we generate is labelled ours and never grades itself | NORTH-STAR §3 rule 5; Build 08 §23 row 5 (D-61) | accepted |
| Loop order: interview and pre-research, brief, build, use and critique, revision | SERVICE-MODEL §3; SERVICE-SPEC §6 "Discovery, build, use and revision" (EDU-D65–D68) | accepted |
| Brief is a `brief` work; the interview is a conversation | Build 07 §3 "Reuse"; [Build 08 §22.8](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/BUILD-08-KNOWLEDGE-LOOP.md#s22) | lab-proven |
| Interview turns verbatim; agent turns carry the retrieval used; nothing invented for the owner | Build 08 §22.8; loop-4 selection §5 | lab-proven |
| Design backwards from the evidence of mastery; changed case | task brief for this skill; HOLLODECK capture field "Mastery prompt"; Build 01 R1.1 ("transfer to a changed input") | direction and proposed |
| Map plus one complete module, then steerable batches | SERVICE-MODEL §2 and §6; SERVICE-SPEC §6 (EDU-D38, EDU-D41) | accepted |
| Run every lesson before review | [Build 08 §26](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/BUILD-08-KNOWLEDGE-LOOP.md#s26); course README | lab-proven (prototype) |
| Agents propose, people review; release needs a human review of the exact closure | service skill "Rules"; command dispatch (`review_revision`, `freeze_release`); Build 08 §22.8 and §23 row 7 | code, accepted |
| A changed claim opens a review, not an update | SERVICE-MODEL §2 "Keep material current" (EDU-D43–D47); SERVICE-SPEC §6 "A changed source identifies potentially affected material" | accepted; the SERVICE-SPEC sentence is proposed |
| Availability lists | operations, payloads, MCP tools, CLI commands, command dispatch, all read 2026-11-15 | code |

### references/structure.md

| Rule | Source | Status |
| --- | --- | --- |
| Works with fixed revisions; a save adds a revision against the expected head | authoring page; command dispatch (`revise_work`) | code, lab-proven (Builds 04–06) |
| What may contain what; exact child revisions at a position, recommended or optional | product API (`product.insert_revision`, parts); curriculum page | code |
| A course is a map of outcomes, requirements, routes, prerequisites | SERVICE-MODEL §2 "Take a course" (EDU-D19–D25); Build 01 R1 schema accepted 2026-11-05 | accepted |
| Later modules are honest map entries | Build 01 R1.1 | proposed text inside an accepted schema recommendation |
| Module = the unit handed to review; one module released so far | Build 08 §23 row 7, [§27](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/BUILD-08-KNOWLEDGE-LOOP.md#s27) row 9 | accepted (lab release) |
| Sizes | loop-4 module (seven sections, one activity); the lesson files beside the course README (24 to 59 lines); no record sets a limit | observation, inference |
| Challenge, project, artifact "is not" wording | SERVICE-SPEC §4 "Proposed" paragraph; Build 05 accepted answers C1, C5, C7 | proposed plus accepted |
| Artifact carries a digest, usage right and rights basis | CONSOLIDATED-MODEL §3; payloads; product API (`register_artifact`) | accepted, code |
| Bottom-up; what is not placed does not ship | product API (`product.exposure` closure); loop-4 module header ("the activity ... is a separate work, not in release 1") | code, lab-proven |
| A block that shows another work must also bind it | Build 05 finding F-16 | lab-proven |
| Required outcomes, mandatory activities, recommended practice, optional exploration stay distinct; optional practice never lowers completion | SERVICE-SPEC §4 "Proposed composition rules"; SERVICE-MODEL §5 (EDU-D20, EDU-D28) | proposed plus accepted |
| Routes; proposed until a maintainer approves | curriculum page; product API (options); Build 05 C5, C7 | code, accepted |
| Enrolment needs a course root; adoption is explicit; studied release kept | command dispatch (`enroll`, `adopt_release`); SERVICE-MODEL §5 "Publishing and adoption" | code, accepted |
| Two teacher modes | SERVICE-SPEC §6 (EDU-D39, EDU-D40) | accepted |
| Web first, harness equal | root AGENTS standing rule (EDU-D30–D35); SERVICE-MODEL §1 | accepted |
| The two courses | SERVICE-MODEL §6 | accepted |
| "Write the evidence rule on the outcome"; "missing prerequisite: add a bridge or cut" | from the outcome and prerequisite model | inference |

### references/evidence-binding.md

| Rule | Source | Status |
| --- | --- | --- |
| The fact-state table | Build 08 [§22.4](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/BUILD-08-KNOWLEDGE-LOOP.md#s22) (verdict kinds), [§24](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/BUILD-08-KNOWLEDGE-LOOP.md#s24) (contradicted claims stay visible), [§28.1](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/BUILD-08-KNOWLEDGE-LOOP.md#s28) (qualified restatements) | lab-proven; the "assert only verified" line is the task brief's rule |
| Read the best-assessed sources first; record the sources used; outcomes are evidence about sources | [NORTH-STAR §3 rule 4](../../../../NORTH-STAR.md#taste) | direction |
| Score needs a minimum of checked claims | Build 08 §23 row 6 (D-69) | accepted |
| Bind each claim to its section | Build 08 §28.3 Q4 and [§29.4](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/reviews/BUILD-08-KNOWLEDGE-LOOP.md#s29) (RV14 gap); [loop-8 handoff §2](../../../../platform/ai-engineer-research-2026-11-02/10-review-workspace/NEXT-SESSION-BUILD-08-AFTER-LOOP-8.md#s2) candidate N | open item; the fix is proposed |
| Four binding kinds (covers, uses, supports or contradicts, source) | loop-4 selection §8; [loop4_product.py](../../../../aiengineer/ai-engineer-db-contract/scripts/knowledge-lab/loop4_product.py) | lab-proven |
| Declared version range and resolved version; breaking first; only older heads | workspace task page "Which of our modules does a new software release affect?"; Build 08 §22.5 Q11 | lab-proven; the task page is model-assisted and unreviewed |
| Bind the restated claim, not the attributed one | Build 08 §28.1 (D-80) | lab-proven, awaiting John's review of loop 7 |
| Purpose of each source binding | SERVICE-SPEC §6 "Sources, research, rationale and learning content" | proposed |
| Two-hop chain; circular works | Build 08 §12.3, accepted in §12.9 | accepted |
| A private copy blocks a wider release | Build 07 finding F-30; product API (`product.exposure`) | lab-proven, code |
| No verified claim: research, open edge or cut | task brief; research request path from Build 07 §7 | accepted mechanics |
| General-knowledge label; discrepancies shown | Build 08 §26 "Knowledge used, and its limits" | lab-proven (prototype) |
| Open-edge entry shape; "not reproduced is not refuted"; how-we-know section | loop-4 module §6 and §7; Build 08 §22.4 (P9) | lab-proven, released |
| Concise main view; Sources and decisions; four kinds of evidence | SERVICE-MODEL §4 (EDU-D70) | accepted |
| Verdict change flags the release | Build 08 §24.6; loop-5 migration | lab-proven (one synthetic contradiction) |
| Failed fetch is not a retraction | Build 01 R1.4 keeping-current test | proposed (planned test) |

### references/lesson-craft.md

| Rule | Source | Status |
| --- | --- | --- |
| Five parts of a lesson | task brief; outcomes and evidence rules (curriculum page); Build 01 R1.1 ("worked example, practice, observable criteria and transfer") | accepted model, proposed pedagogy |
| The agent builds with the learner, then steps back | HOLLODECK "What the student experiences"; SERVICE-MODEL §2 "Get continuing assistance" | direction, accepted |
| Declared assistance facets; frozen submissions; fixed evidence | service skill; `start_attempt` and `submit_attempt` tool descriptions; SERVICE-MODEL §5 | code, accepted |
| Hidden checks and solutions withheld | product API (`product.exposure`); Build 05 J9 | code, lab-proven |
| Generated task is practice until accepted | SERVICE-SPEC §5 (EDU-D20, EDU-D28); Build 05 C7 | accepted |
| The released activity | loop-4 module, "Activity" | released (lab). I removed the answer from the visible criteria; see section 2, item 8 |
| Expected result before the run; differences are the best material | Build 08 §22.4, last paragraph | lab-proven |
| Deterministic setup; a live run never verifies alone | loop-4 module §2; Build 08 §22.4 (P12) | lab-proven |
| Run record fields; page built from the run | [run_course.py](../../../../aiengineer/ai-engineer-db-contract/scripts/knowledge-lab/course/run_course.py); course README; Build 08 §26 | lab-proven (prototype) |
| Prototype rules 1 to 12 | Build 08 §26 table and paragraphs, row by row | lab-proven (prototype); no learner evidence |
| Block rules, fallbacks, stable keys | Build 05 "Results" J9; service skill | lab-proven |
| "Do the activity yourself"; "an example edited after its last run counts as not run" | from the run-before-review rule | inference |

### references/review-and-release.md

| Rule | Source | Status |
| --- | --- | --- |
| Stage table; ceilings and channels; publisher grant | command dispatch (`review_revision`, `freeze_release`, `open_distribution`, `offer_release`); payloads | code, lab-proven (Builds 04–06) |
| Private by default; three separate acts | SERVICE-SPEC §6 "Creator releases and official publication" (EDU-D61); SERVICE-MODEL §5 | accepted |
| People-only acts | command dispatch; the summaries in operations; Build 07 §7 "What J10 proves" | code, lab-proven |
| The narrow transcription case | Build 08 §23 row 7 and §27 row 9 (John's written instruction, quoted in the review note) | lab precedent; narrowing to named readers is inference |
| Exposure states and blocker dispositions | product API (`product.exposure`); payloads (`freeze_release`) | code |
| Approval does not carry to a new revision | Build 01 R1.4 ("Official publication approval must not carry over"); `freeze_release` checks the closure digest | code |
| Old passages retired on revision | Build 08 §22.8 ("revision 1's passages were retired from search") | lab-proven |
| Feedback rules | SERVICE-MODEL §3; SERVICE-SPEC §6 (EDU-D68) | accepted |
| Hand-over contents; "then stop" | assembled from the review requirements above | inference |

## 2. Contradictions, and which source I followed

1. **Who may record a runtime review.** The workspace task page for release impact says agents may record `runtime_review` events. The command dispatch refuses agents for `release_review`, `official_publication`, `transition_review` and `runtime_review`. Followed the code. The task page is marked model-assisted and unreviewed.
2. **Is the first module verified?** The loop-4 module body says nothing in it is verified. Its header, added later, says 13 of its claims are verified, and Build 08 §28 counts 27. Followed the newest record. Consequence used in the skill: content states its verification state as of a date and is revised when that changes; release 1 is stale on this point.
3. **Is the module released?** Build 08 §22.8 says it is not released; §23 (later the same day) records release 1 at ceiling `named` on John's written instruction. Followed §23. "Agents That Act" (§26) is a prototype artifact and is not released.
4. **"No `block_key`".** Build 08 §28.3 says module bindings are per revision with no block key, and the loop-8 handoff proposes per-section bindings as new work. The binding structure already carries a block anchor (payloads; the `annotate_lesson_block` tool uses it). So the limit is how the module was written, not a missing field. Whether search's evidence channel reads the anchor is unproven. The skill states the judgment and leaves the mechanism to the tool description.
5. **Agents never record human reviews, yet one did on instruction.** The service skill says agents never record human reviews. Build 08 §23 and §27 record a human release review written by the agent under a lab author account on John's written instruction. Followed the strict rule, and kept the precedent as one narrow, written-instruction case limited to what the precedent covered. John should confirm whether that case stays in production guidance.
6. **A CLI session counts as a person.** The command dispatch treats an interactive CLI client as human; MCP and harness grants act as agents. An agent driving the CLI would pass the human check. Followed the stricter reading (rule 2) and stated the fact once, in Availability.
7. **Drafts and search.** The workspace task page for concept coverage says drafts are not searchable. Build 08 §22.3 indexed the draft module's passages privately to its workspace. Followed Build 08: a draft can be indexed for its workspace by the platform worker; it is "ours, tier 1" only after release (§24).
8. **Visible answer in the released activity.** The released activity's visible criteria name the answer ("the `agent` to `model` node rename"). The exposure rules withhold hidden checks and solutions. Followed the exposure rule: the quoted model in lesson-craft says "names the silent change" and the answer goes in a hidden check.
9. **Assert only verified facts, but the released module taught unverified ones.** At loop 4 no claim was verified, and the module taught probe-supported claims with a disclaimer. The task brief's rule is stricter, and 27 claims are verified now. Followed the stricter rule: supported-but-unverified material is an open edge.
10. **Which module is "the first complete module".** Build 01 R1.1 proposes "From a source to a defensible bounded decision"; the module actually built and released is the migration module; root AGENTS calls "Agents That Act" a prototype module. The skill designs no course, so no choice was needed. The worked example follows the released module.
11. **Work kinds.** The task brief says a dataset is a work kind made like the others. `create_work` refuses datasets (they have their own operations), and the catalog has 23 kinds. The skill tells the agent to ask the guide for the kinds.

## 3. Not yet accepted

Nothing below is a rule in the skill. If John accepts one, the named file changes.

From [Education research lab evidence base](../../../../docs/education-research-lab/reports/Education%20research%20lab%20evidence%20base.md) (P1 to P20, thirteen decisions pending):

- **P1** (delayed, unassisted changed-case performance as the north star; three signals per mastery claim): would turn "design backwards" into a fixed assessment shape. Changes lesson-craft and SKILL.md step 3.
- **P2** (route each input to the records it may change): changes "keep current" in evidence-binding.
- **P4** (strong authored path, guidance faded by measured prior knowledge): adds a fading rule to lesson-craft and a path rule to structure.
- **P9, P12** (prior-knowledge diagnostic and first expedition; living learner brief): change step 1 and how prerequisites are written.
- **P15** (teach-back and rubric peer review to earn a mastery claim): changes the activity section.
- **P17** (ages 9 to 15: project-centred, moderated, age-banded interaction): adds youth rules to structure.

From [Learning taxonomies techniques and platforms](../../../../docs/education-research-lab/reports/Learning%20taxonomies%20techniques%20and%20platforms.md) (T1 to T13):

- **[T1](../../../../docs/education-research-lab/reports/Learning%20taxonomies%20techniques%20and%20platforms.md#t1)** (each mastery claim as a task with four typed fields on three or four levels): replaces the free-form outcome sentence.
- **[T3](../../../../docs/education-research-lab/reports/Learning%20taxonomies%20techniques%20and%20platforms.md#t3)** (techniques sorted into defaults, options to test, exclusions): would give lesson-craft its default techniques.
- **[T4](../../../../docs/education-research-lab/reports/Learning%20taxonomies%20techniques%20and%20platforms.md#t4), [T5](../../../../docs/education-research-lab/reports/Learning%20taxonomies%20techniques%20and%20platforms.md#t5)** (unassisted work verified at secured points; assisted work as its own evidence stream): change "declared assistance" from a declaration into a design constraint.
- **[T6](../../../../docs/education-research-lab/reports/Learning%20taxonomies%20techniques%20and%20platforms.md#t6)** (the deployed project as the application layer, with no mastery credit of its own): changes how projects sit in a course.
- **[T7](../../../../docs/education-research-lab/reports/Learning%20taxonomies%20techniques%20and%20platforms.md#t7)** (fresh variant on demand; predict then test): changes the changed-case task.
- **[T9](../../../../docs/education-research-lab/reports/Learning%20taxonomies%20techniques%20and%20platforms.md#t9)** (an evidence card for every teaching choice): changes Sources and decisions.
- **[T12](../../../../docs/education-research-lab/reports/Learning%20taxonomies%20techniques%20and%20platforms.md#t12)** (guardrails for ages 9 to 15 with an adult owner): youth rules.

Also not accepted:

- **Candidate N** in the loop-8 handoff §2 (module revision 2 with per-section claim bindings). Until it runs, per-section binding is a judgment with an untested mechanism.
- **Build 08 loops 7 and 8** await John's review, including D-80 (restated claims) and the handoff's recommendation to add P16 to the module's open edges.
- **HOLLODECK** is direction only. The skill takes two phrases from it: the learner's own work and demonstrated mastery, and the changed case.
- **SERVICE-SPEC "Proposed" paragraphs.** Used where marked "proposed" in section 1.
- **Build 01 R1.1 and R1.4 prose** (first-module description, planned tests). The schema was accepted; the prose was a recommendation.

## 4. Facts I could not confirm

- Whether search's evidence channel reads a block-anchored binding, so that per-section binding fixes the ranking gap.
- Any accepted size limit for a lesson, module or course.
- John's reaction to the "Agents That Act" prototype (Build 08 §26 names it as the next proof; none is recorded).
- Whether `read_lesson` renders a module or an activity, or only lessons.
- Whether a course-content output has ever been delivered against a research brief. The validator accepts the form; no lab run used it.
- Which review types an agent may record. The code lists four people-only types and leaves the rest open; no run used another.
- The names of the service's guide, schema-navigation and knowledge-read tools. They were in flight on 2026-11-15, so the skill names none.
- Whether the web app renders the Sources and decisions block.

## 5. Steps with no operation or tool today

| Step | Gap |
| --- | --- |
| 1 Brief | `create_thread` and `append_message` have no MCP tool. No interview surface on web or harness. |
| 2 Orient | No service operation reads verified claims, verdicts, source track records, works authored by concept, or the due-lists. The `course-authoring` scope lists no evidence queries. |
| 4 Structure | `draft_work` cannot set parts, outcomes, requirements, routes, prerequisites, runtime requirements or statements. No MCP tool returns a workspace id, lists works or reads a non-lesson revision. |
| 5 Draft | No MCP path creates a statement in a revision. `cite_evidence` can support only a dataset value or a statement that already exists. |
| 6 Run | No operation stores a run record or marks a revision as run. No author dry-run of an activity; `start_attempt` is a learner operation. |
| 7 Review | `preview_exposure` has no MCP tool. No submitted-for-review state outside an accepted brief. No feedback operation: the `feedback` event kind exists and nothing writes it. Indexing and retiring passages are worker-only. |
| 8 Keep current | Release-impact and releases-needing-review are database reads only, and nothing schedules them. No operation writes a release transition or per-requirement carry-forward, so learner progress across releases cannot be recorded. |

## 6. Weakest parts of the method

1. **Per-section claim binding.** Never exercised on a module. The one released module is bound at revision level, the ranking gap it caused is still open, and the fix is an unapproved candidate.
2. **Lesson craft as pedagogy.** The rules come from one prototype no learner has taken and John has not reviewed in the record. The five-part lesson shape rests on the accepted outcome model, a Build 01 recommendation and the Hollodeck direction, not on learner evidence. Sizes are observations.
3. **Keep current.** The verdict-change flag is lab-tested with one synthetic contradiction. No scheduler runs it, no second release of any work exists, and release transitions have no writer.

Inferences to check, gathered from section 1: sizes; "write the evidence rule on the outcome"; "missing prerequisite: add a bridge or cut"; "do the activity yourself"; "an example edited after its last run counts as not run"; the hand-over contents; narrowing the transcription case to named readers; separate lessons as a way to get per-claim granularity.
