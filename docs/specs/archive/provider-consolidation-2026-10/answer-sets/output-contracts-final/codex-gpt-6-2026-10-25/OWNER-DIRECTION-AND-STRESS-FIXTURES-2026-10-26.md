---
type: Owner Direction
title: "Fast-path implementation mandate and three post-sprint stress fixtures"
description: "Exact owner steering on disposable data, direct implementation, the final specification session, Generation Lab, Qualia Life, AI model retrieval, evaluation loops and later product architecture."
tags: [mission-control, owner-direction, fixtures, evaluation, handoff]
date: 2026-10-26
status: recorded
---

# Owner direction and post-sprint stress fixtures

This direction follows OC-D176 and is recorded as OC-D177–181 in [ANSWERS](ANSWERS.md).
The user now requests a **final specification/issue synthesis handoff**, not another interview
round and not execution of these missions in this chat. The [new session instruction](FINAL-SPEC-AND-ISSUE-SYNTHESIS-HANDOFF-2026-10-26.md)
replaces older resume/questioning instructions. The original quotes below are the source;
operational interpretations are explicitly separate.

## 1. Owner's complete message, verbatim

> Alright I want to run GPT 6 Extra High on the final specifications and issues.
>
> I purposefully want a kind of destructive strategy regarding implementation. No trying to save historical data. I don't want extra caution related to files and imports and behavior. I want to slice through and achieve the system.
>
> We have no real users. We have no automations in production. We are trying to get coordinator agent , mission control and its knowledge services connection to high quality functionality.
>
> Go through this information:
>
> Fixture # 1.
>
> - A Goal Directed workflow that doesn't stop until it has found and stored every single Diagnostic test and biomarker tested by Generation Lab. Agent skills: (ALl the tavily skills, All the firecrawl skills, the vercel agent browser skill) You do not have to actual ingest into the biotech database. You don't have to provide all the knowledge services skills. Just use those external provider agent skills. Have the model output reports and ingestion intent artifacts . Let's give the Deep Agent a general subagent, a vercel agent browser skill async subagent that can complete browser control tasks.
>
> Fixture # 2.
>
> A Complex Stage Graph whose purpose is to find every single current supplement product that qualia life sells and the compounds inside of them, finds 3 of the most important case studies/trials sponsored or connected to qualia life that concerns their products, trademarked compounds in their product, or compounds in their product. I want a report per product and that report should contain foundational information about all the ingredients. Applicable stages must use the evidence verification process and agent skill and we need that evidence provenance attached to the reports.
>
> Agent skills , mcp servers , objectives and output contracts are per stage. Distribute these skills and mcp servers throughout the stage graph
>
> Tavily skills
> Firecrawl skills
> Vercel agent browser skills (Very good to put as dedicated browser control subagent)
>
> pubmed (mcp server)
> Clinicaltrials (mcp server)
> knowledge services evidence, ingestion, research biotech
>
> Fixture 3 Another complex stage graph much like the one above but for ai engineer. The mission is to find up to 50 models open source and closed source preferably from 2025-2026 and their scores on major benchmarks . I then want entity information (models, benchmarks things like that) and their relationships ingested and then I want a retrieval experiment run for choosing models and routing models per a use case. So a use case is given to an llm agent who will then retrieve from our ai engineer database and choose some number of ranked models for the job . The ranking is performed across a few dimensions which may or may not be encoded in benchmark scores or aggregate metrics from someone (say Epoch AI)
>
> These fixtures are meant to stress our system , expose gaps and incentivize any additions.
>
> In addition to running these fixtures this is when we start EVALUATION AND FEEDBACK LOOPS. Evaluation of the mission work.
>
> ** IMPORTANT BIGGER PICTURE GOAL AND SEQUENCE INFO **
> These fixtures are going to run AFTER the fixture checkpoints that should be outlined in one of the ANSWERS.md . They are real tests after this sprint. AFTER THESE FIXTURES we are going to architect the content types and features of the ai engineer education services and the biotech knowledge and recommendation services FULLY. It is totally fine to produce reports and ingestion that don't end up as final parts of our released services. It's all in the pursuit of the final product.
>
> ------------------
>
> Now I want you to create a final instruction for a GPT 6 Astra Extra High Session. I need you to accumulate all the various ANSWERS.md and any other document derivatives that have stemmed from the 4 or so interviews I have conducted. The agent's mission is to coalesce everything into final specifications and issues. I am adamant about directness and efficiency. I want these issues to permit the agents to work unimpeded and get the functionalities up and running. Migrations made. Code added and mutated. Checkpoints ran.
>
> Documentation updates (AGENTS.md, OKF docs) and clean code updates should run effectively for every major commit.
>
> The agent I provide the instruction to needs to explore, reason, synthesize and then create all the specs and issues for an agent team. I will use codex or claude code . I don't know yet. An agent team generally.
>
> Fast path.
>
> Make sure you work hard to accumulate all the answers and context so this spec and issue creator agent knows exactly where everything is !

## 2. Implementation mandate — interpretation

The objective is working coordinator-agent + MC + KS functionality. This is a pre-user,
pre-production-automation system. Existing experimental data/history is disposable. Plan direct
replacement of obsolete implementations, files, imports, schemas, contracts and behavior. Include
necessary migrations, regeneration, clean rebuilds and application cutovers in the owning work item.
Do not spend the sprint on data rescue, dual implementations, deprecation periods, compatibility
aliases or gradual behavior preservation merely because old code exists. If an integration branch
is needed for an inseparable cutover, use it and prove the integrated result.

Keep the existing ownership boundaries and the functional correctness properties the owner chose.
Permission to replace old data does not eliminate exact selection, truthful fulfillment, runtime
recovery, evidence provenance or native-effect correctness in the new system. Preserve the interview
record and unrelated user work; they are inputs to the task, not obsolete runtime data. Identify
the intended development/test targets before resetting them, then proceed within this mandate
without repeatedly asking for routine migration/refactor approval.

This handoff session writes instructions and decision records. The next session researches and
publishes final specifications/issues and an implementation-team packet. Implementation teams then
execute that packet; the three named stress missions belong after the sprint checkpoints.

## 3. Required sequence

1. Coalesce all four substantive interview records and their revisions into final specs, architecture,
   actual tracker issues, dependencies, team assignments and proof criteria.
2. Build the runtime/service/schema work and run the **existing W0–W5 checkpoints**, with real
   functional review, necessary repairs and reruns. OC-D128 permits bounded qualification before
   the full general-use gate; keep first-use prerequisites and final all-family/Deep Agents gate.
3. **After those checkpoints and this sprint**, run the three stress fixtures below, with mission-work
   evaluation and feedback loops as part of this phase. They do not replace W1's report,
   W2's exact transfer or other intermediate checkpoints. Their findings can require further
   additions and repairs; the final issue pack must make that work possible.
4. Use the resulting evidence to fully architect AI Engineer education content types/features and
   Biotech knowledge/recommendation services. That full product architecture is subsequent work.
   Experimental reports and ingested records need not survive into the released products.

The W0–W5 authority is [CONTRACTS §11](CONTRACTS.md#11-real-fixtures-and-the-general-use-gate),
from OC-D106/107/128–131. Earlier Sprint V W0–W6 labels are a different sequence.

## 4. Stress fixture contracts — owner requirements and engineering completion criteria

The goals/capabilities below are selected by the owner. Concrete entity schemas, rubrics, resource
limits and metric thresholds are fixture-authoring work, not fabricated owner answers. Do not
research the live companies/models as part of this handoff. The implementation/fixture team verifies
current upstream skills and services before executing them.

### F1 — Generation Lab exhaustive discovery through GoalDirected

**Required:** find and store every diagnostic test and biomarker tested by Generation Lab; produce
reports and ingestion-intent artifacts. Do not require application to the Biotech database. Provide
all Tavily skills and all Firecrawl skills plus the Vercel agent-browser skill, a general
subagent and a dedicated **asynchronous interactive browser-control subagent**. This fixture does
not require the full KS skill bundle. Inventory and pin the upstream skill collections; any
unavailable capability is an explicit gap, not permission to silently narrow the requested set.

**Implementation/proof interpretation:** the Goal Loop accumulates exact distinct discoveries and
their test↔biomarker relationships, source evidence, aliases and unresolved gaps. Store its outputs
as actual retrievable artifacts under the output contracts; an ingestion intent is not an applied
ingestion receipt. The verifier assesses the accumulated current set and explicit discovery-closure
criteria, not just the last response. The mission must not accept a convenient partial list as
“every single.” If the evidence/capabilities/resources cannot establish closure, retain progress in
an actionable resumable state rather than report success. This does not create unlimited spend or
remove admitted runtime controls. Do not silently change the owner's discovery population to only
one page, one test category or a fixed number.

Prove real interactive browser delegation, asynchronous status/join/cancellation and returned usable
outputs; a seeded skill name or single-page text tool is insufficient. Prove continuation/current-set
retention, report/intents fulfillment and the independence of artifact creation from native ingestion.

### F2 — Qualia Life products, ingredients and connected studies

**Required:** a complex Biotech Stage Graph discovers every current supplement product, all compounds
inside each product, and three of the most important qualifying sponsored/connected case studies or trials concerning a
product, trademarked compound or included compound. Produce a report for each product with foundational
information about every ingredient. Applicable stages must use the evidence-verification process/skill
and attach its provenance to the reports.

Skills, MCP servers, objectives and output contracts are **per stage**. Distribute Tavily, Firecrawl,
Vercel browser (prefer a dedicated browser subagent), PubMed MCP, ClinicalTrials MCP and KS evidence,
ingestion and Biotech research capabilities according to each stage's task. Do not give every stage
one undifferentiated tool bundle or infer tool parity from a catalog label.

**Implementation/proof interpretation:** freeze a dated product inventory, preserve product/formula
revisions and exact ingredient links, deduplicate shared ingredient research without losing per-product
coverage, and close grouped product reports independently when their required inputs are complete.
Retain evidence and source dates for compound identities and foundational claims. Study selection uses
an explicit importance rubric and evidence for the exact connection: sponsorship, product, trademarked
ingredient or ordinary compound are different relationships. Fewer qualifying studies remains a visible
shortfall, not invented evidence. KS verification findings/use status/provenance must reach the actual
final reports. Specify required intent/apply behavior per stage; the owner did not require every F2
artifact to be natively ingested simply by listing ingestion skills.

Prove exact data joins, collections/coverage, staged capability grants, browser handoffs, report
assessment and graph context at realistic scale. Check source corrections, unavailable studies,
duplicate ingredients and one failing product without silently discarding independent successes.

### F3 — AI model/benchmark ingestion and use-case retrieval/routing

**Required:** a complex AI Engineer Stage Graph researches **up to 50** open-source and closed-source
models, preferably from 2025–2026, with scores on major benchmarks. Ingest model/benchmark entities
and relationships into the AI Engineer database. Then give a use case to an LLM agent that retrieves
from that database and ranks some number of models for the job across several use-case dimensions.
Those dimensions may be represented by benchmark scores, third-party aggregate metrics, other
evidence or explicit judgments.
Epoch AI is an example source, not a mandated provider dependency.

**Implementation/proof interpretation:** preserve exact model/version identities, openness/licensing
facts, benchmark versions, score units, evaluation settings, observation/source dates and provenance.
Keep missing or incomparable scores explicit. Do not turn “up to 50” into “exactly 50” or the preferred
date range into an unrequested absolute filter. Native ingestion must produce actual committed
entities/relationships and required readback, not just intent artifacts. The ranking agent must
actually retrieve from the ingested database; supplying its full answers directly in the prompt does
not prove retrieval. Record retrieved candidates/evidence, use-case dimensions, rationale, uncertainty,
ranked choices and routing outcome. Non-benchmark dimensions need their own evidence or explicitly
identified judgment. Inspect lineage from the final recommendation to retrieval and native records.

Provide a reproducible retrieval/ranking experiment with defined use cases and an independent
evaluation method. Check relevant-candidate recall, evidence support, ranking usefulness and routing
constraints separately; exact metric choices belong to experiment design. A completed database query
or a fluent ranking is insufficient functional evidence.

## 5. Mission-work evaluation and feedback loops

The stress phase starts explicit evaluation of **the mission's work**, beyond transport tests and
beyond per-claim evidence verification. Plan an issue-owned loop that defines criteria, runs a
versioned fixture, retains outputs/Transcript/tool and resource evidence, obtains independent
assessment, classifies gaps, repairs the owning layer and reruns. Track mission/fixture/configuration/
schema/model/skill versions and link each fix to before/after evidence.

Assess task coverage, factual/evidence quality, useful output structure, agent/tool/subagent behavior,
context transfer, cost/latency and recovery. For F3 add retrieval/ranking/routing quality. Distinguish
task failure, unavailable source/tool, contract mismatch, system defect and evaluator uncertainty.
The same producer's self-declared success is not the sole evaluator. Improvements may change code,
migrations, capabilities, prompts, contracts or workflow design where evidence warrants. Retain prior
failing cases for regression and avoid tuning only to the demonstrated example. Keep eval publication
and scientific/KS use authority distinct.

The final spec session must create concrete post-sprint fixture/evaluation/repair-loop work items
with dependencies on the sprint gate. Do not mark these as fulfilled by existing W0–W5 proof.

## 6. Quality at every major commit

The implementation packet must require a clean-code review and documentation update at each major
commit/integration milestone, with relevant lint/type/test checks and updated AGENTS navigation, OKF
concepts/logs, contract/ADR/operator/schema docs as affected. Run the owning generators and checks.
Fix review findings before declaring that milestone complete; rerun checks after repairs.

The quality-checkpoints tool is useful infrastructure, not evidence that this requirement already
runs: its automatic trigger is turn-end and it may skip changes. The team coordinator must explicitly
run or verify both clean-code and documentation work at every major commit. Use an available reviewed
automation or a direct review agent; do not make implementation wait on installing a new framework.
No quality automation was installed or modified by this handoff session.
