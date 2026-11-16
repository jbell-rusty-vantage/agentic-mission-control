# Evidence binding: how content cites knowledge

Rule: a lesson states a fact only when the knowledge base holds it as verified, and the section that states it is bound to that claim. Everything else the lesson needs is an open edge, a research request or a cut.

A claim becomes verified only through the knowledge service's admission of external evidence. Nothing you write, run or bind makes a claim verified.

## Sort every fact before you write

Read the topic through the knowledge reads the guide lists. Use our own content to learn what is already taught, never as evidence for a fact: inside a course our content leads the search results, and the corpus is what checks it.

| What the knowledge base holds | What the lesson does |
| --- | --- |
| A verified claim | State it. Bind the section to it as support. |
| A verified claim with a qualification | State it with the qualification, in the verified wording. |
| A claim supported by a run or a first-party page, not yet verified | Open edge. Say what supports it and that it is not verified. |
| A disputed or contradicted claim | Teach the dispute: what was claimed, what ran, on which versions. Bind it as a contradiction. |
| A candidate: reported, never checked | Open edge, labelled as a report. |
| Nothing | Request research, or cut. |
| Our own finding, checked only by us | Label it as ours. It is never the only support for a statement. |

Read the best-assessed sources first, and read a source's score together with how many of its claims were checked. A score built on one checked claim tells you little.

## Bind each claim to the section that depends on it

A binding is a typed link from a revision to the thing it depends on. You will use four kinds: the concept the work covers, the software it uses, the claim a section supports or contradicts, and the source location a passage came from.

- **Anchor every claim binding to the block that states the fact.** Bindings piled on the whole module do not say which section depends on which claim. The first released module was bound that way, and a learner's question about its migration section ranked that section third, behind the first section and the title.
- **Bind the software the work uses, and declare the version range you claim and the exact version you ran.** A later release is matched against that range, and a breaking release is listed first.
- **Bind the claim that states the fact.** "The post states that X" is a claim about a post. Bind the restated claim "X". If only the attributed form exists, ask for a restatement; a person confirms it.
- **Say what each source binding is for:** factual support, contrary evidence, an example, a teaching rationale, or background. A source cited for formatting must not read as proof.
- **Record every source you used.** The outcome of the content counts as evidence about its sources: a module that fails learners is a finding about what it was built from, so report it as one.

Check the chain: each reused fact must reach a verified claim or a primary-source location within two hops. A work whose only evidence is another of our works is circular. Bind the claim underneath it instead.

Rights travel with the binding. Each bound source or file carries a usage right. A private copy of a fetched page stops a release beyond the workspace. Cite the original by reference, or tell the reviewer that a licensed snapshot is needed.

## When there is no verified claim

Decide by what the outcome needs.

1. **The learner cannot reach the outcome without it:** request research. Write a research brief that states the question, the plan, the time window, the budget limit and the outputs it must deliver, and propose it. A person accepts it and its budget. Until the claim is verified, the section stays an open edge.
2. **It helps, and the outcome stands without it:** show it as an open edge.
3. **Neither:** cut it.

Three things are never the answer: writing the fact from memory, citing our own lesson or our own run as its proof, and softening the sentence until it no longer sounds like a claim.

Background the knowledge base does not hold at all (a founding date, a definition) may appear only under a visible "general knowledge" label, and goes on your list of ingestion to request. When a first-party statement disagrees with a registry, show both and the difference. Do not correct either silently.

## How open edges reach the learner

Open edges are part of the lesson, not an apology. Give them their own section, after the taught material, and write each one so the learner can act on it:

- the report in one sentence, with a link to where it was made and whether it is still open;
- its state: verified elsewhere, supported but not verified, disputed, not reproduced, or report only;
- what was run, on which versions, and what that does and does not show;
- what the learner should do if they meet it.

"Not reproduced" is not "refuted". Say which conditions the original report had that the run did not.

Close the module with a short "how we know" section: which statements rest on verified claims, which sources stated them, and which statements are our own findings awaiting an outside check. Keep the main lesson concise. Sources, alternatives and the reasons for teaching choices live in an expandable Sources and decisions view. Keep four kinds of evidence apart there: the source is correct, the code runs, the assessment is sound, the learner learned.

## How a changed claim reaches the content

Bindings are what make this work. Three events start it:

1. **A verdict changes on a bound claim.** The release that bound it is listed as needing review.
2. **The software ships a release.** Works that use or cover it are listed, breaking releases first. Only works whose head revision is older than the release appear. The checks behind bound claims become due for a re-run on the new version.
3. **A bound source changes or disappears.** A failed fetch means unavailable or unknown. It is not evidence of a retraction.

Then you do four things, per affected work:

1. Read the change and the sections bound to it.
2. Decide: no change (write the reason), an open-edge update, or a correction to taught material.
3. Draft a new revision. Fix the affected sections, re-run their examples, update the bindings.
4. Hand it to the reviewer with what changed and why.

The old release stays as learners studied it. A changed source marks material for review. It does not justify replacing a lesson, changing a grade or publishing an update.

## Example

Outcome: "migrate a prebuilt agent and name the change that fails silently."

| Fact the lesson wants | Held as | In the lesson |
| --- | --- | --- |
| The new factory has no "prompt" parameter; use "system_prompt" | verified | Stated in the lesson on parameters; that block bound as support |
| The model node is named `model`, not `agent` | verified | Stated in the lesson on streaming; that block bound as support |
| "The parameter was renamed silently" | disputed: the call raises an error | Taught as a dispute, with the run; bound as a contradiction |
| A human-in-the-loop failure under async calls | reported, not reproduced | Open edge: the report, the versions tried, what to record if you hit it |
| The TypeScript equivalents | nothing | Not needed for this outcome in Python: cut, and listed as research to request for the TypeScript variant |
