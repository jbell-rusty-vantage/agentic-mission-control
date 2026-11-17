# Structure: what each unit is for

Rule: give every outcome the smallest unit that can hold it, and give every unit one purpose. If you cannot say a unit's purpose in one sentence, split it or delete it.

Every unit below except the artifact is a *work*: a stable identity with fixed revisions. Saving never edits a revision; it adds one.

## The units

| Unit | It is | It is not | Size |
| --- | --- | --- | --- |
| Course | The map: outcomes, what completion requires, the routes that satisfy each requirement, prerequisites, and the modules in order. The thing a learner enrols in. | A folder of lessons. Finished because the map is drawn. | A map plus one complete module is enough to start. Later modules stay honest map entries until built. |
| Module | One capability the learner demonstrates at its end. The unit you hand to a reviewer. | A summary of a topic. A page of findings. | The lessons one capability needs, plus the activity that proves it. |
| Lesson | One outcome, taught through one worked example that ran. Its blocks have stable keys, so a note or a binding can point at one section. | A chapter. A home for a second outcome. | One runnable example. |
| Activity | The task the learner performs, and the evidence a checker looks for. Where mastery is shown. | Reading. A quiz that only looks rigorous. | One task, one stated result. |
| Artifact | Stored bytes: a file, a built site or a deployment, with a digest, a usage right and a rights basis. A block shows it. | A work. A lesson. Evidence that anyone learned. | Whatever the block needs. Its rights decide whether it can ship. |

Sizes seen so far, as reference points and not limits: the one released module has seven sections and one activity; the prototype module has thirteen lessons, twelve of them one runnable file of 24 to 59 lines and one a three-file deployment. Size by outcome. When a lesson needs a second example to make its point, it is two lessons.

Other kinds you will meet: a *track* groups modules inside a course; a *challenge* is a bounded task; a *project* is sustained work with milestones; a *snippet* is one block shared by several lessons. Ask the guide for the current list of kinds.

## Choosing the unit

1. It has its own outcome and its own example: a lesson.
2. The learner is checked on it: an activity, placed inside the module it proves.
3. Two lessons need the same block: a snippet. Two modules need the same lesson: place the same lesson in both.
4. It is bytes someone opens (a page, a notebook, a site): an artifact, shown by a block, with a text fallback beside it.
5. It only explains how the module was built: it belongs in the brief or in Sources and decisions, not in a lesson.

A module may carry its teaching text directly as sections, or contain lessons. Use separate lessons when a section has its own outcome and its own runnable example. Then one lesson can be revised, re-run and bound to its claims without touching the rest.

## How they nest

A parent places an exact revision of a child at a position, as recommended or optional. The same child may be placed twice; each placement keeps its own identity, so the record shows which one a learner attempted.

Three consequences decide how you work:

- **Bottom-up.** A parent pins the child revision it was saved with. After you revise a lesson, the module still points at the old revision until you revise the module. Save children first, parents last, and repeat up to the root.
- **What is not placed does not ship.** A release contains the root revision and what it places, uses or requires. The first released module had its activity saved as a separate work, so the activity was outside the release and needed its own review. Place the activity in the module.
- **Name it and bind it.** A block that shows another work (a component, an embedded challenge, a milestone) must also bind that work. A reference in the block's content alone is missing from the release.

Parents and prerequisites cannot loop. The service refuses a containment the model does not allow; read the error and the guide instead of guessing the hierarchy.

## What an advanced curriculum adds

A single module needs an outcome and an activity. A course adds four things at the course or track level:

- **Outcomes.** What the learner can do, with the rule for the evidence that proves it. An outcome may be aligned to a competency.
- **Requirements.** What completion needs: an outcome shown, or a mandatory activity done. Keep four things distinct: required outcomes, mandatory activities, recommended practice, optional exploration. Optional practice never lowers official completion.
- **Routes.** The ways a learner may satisfy one requirement (next section).
- **Prerequisites.** One revision needs another first, as recommended or required, with a written reason.

Write the evidence rule on the outcome, not only inside your activity. Then an alternative task can be judged against the same rule.

Across modules, state each course outcome once, name the module whose activity proves it, and let later modules require it as a prerequisite. A module that depends on an outcome no earlier module proves has a missing prerequisite: add a bridge or cut the dependency.

## Alternative routes

Each requirement lists its routes. In plain words they are: the standard activity, prior work, testing out, an approved alternative, an eligible generated task, and the learner's own project.

- You propose a route and its evidence rule. A maintainer approves it. An unapproved route grants nothing.
- A challenge the learner designs is practice until a maintainer, or an approved policy, accepts it as equivalent to a required outcome.
- A learner's custom project counts through a short proposal mapped to outcomes and approved by the course owner.
- Generated tasks stay practice until validated as equivalent evidence.

Author consequence: for each requirement, write the standard activity first, then say which other routes you think are fair and why. Leave the approval state as proposed.

## Releases and adoption, as an author sees them

- A reviewer freezes a release of an exact root revision. A release is offered in a distribution. Learners enrol in a course's distribution and adopt an offered release.
- Enrolment needs a course at the root. A module released alone can be offered and read; it cannot be enrolled in.
- A new release moves nobody. Each learner keeps the release they studied, and their earlier evidence, until they adopt the next one. A learner may opt in to compatible updates.
- Two teacher modes exist: a course the teacher maintains while learners keep their own progress, and a course a learner may adapt. Adaptation needs offer terms that permit it, and an adapted copy keeps its link to the source.

Author consequence: with every revision of released work, write for the reviewer what changed, whether it changes teaching presentation or a requirement, and for each requirement whether a learner's progress carries, needs reassessment or no longer applies. Presentation changes and requirement changes have different effects on learners; never fold one into the other.

## Who creates, and where

The same works are created in the web app and in an agent harness. Students and teachers create courses in the web app first, and the same creation works in their harness. Build nothing that lives on one surface only: an artifact that exists as a local path is not yet part of the course; register or publish it.

A course starts as a map and one complete module. The author studies that module while the rest is generated in batches the author can steer. Do not generate a whole course in one pass.

## The two courses in view

- **Comparative agent orchestration** (first): beginner to advanced, several frameworks and providers, production considerations throughout, Python and TypeScript both first-class, an evolving research-and-ingestion agent project, and completion that includes a real deployment and operating work. Which frameworks and tasks it shows is chosen through research, sample modules and the owner's feedback, not by you.
- **Ages 9 to 15** (next): the same technical ambition. Access, tooling and trials for that audience must be settled before it is offered. No structural rule for it is accepted yet: ask the author before you simplify, split or re-order for age.
