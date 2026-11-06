---
type: Decision Record
title: "Model-driven SDLC steps run through a provider adapter on the owner's subscriptions, Cursor first"
description: "Accepted 2026-11-01 (AS-D10, AS-D17): the propose and review steps run through one adapter with two implementations, the Cursor CLI (default, model grok-4.7-high, CURSOR_API_KEY, the plan's included pool) and the Claude Code CLI (subscription login locally, a setup-token OAuth token in CI); on pull requests GitHub Actions run the same CLI and Bugbot reviews; Cursor Automations are not used."
tags: [mission-control, adr, accepted, documentation, sdlc, providers]
status: accepted
source: answers AS-D10, AS-D17; interview facts F14, F15, F16; SPEC-01 §8
---

# Model-driven SDLC steps run through a provider adapter on the owner's subscriptions, Cursor first

**Status: accepted 2026-11-01.**

## Context

The owner wants the model-driven steps billed to subscriptions rather than API keys, and chose
Cursor: "I want to use my Cursor subscription completely and use Cursor Grok 4.7 their best
model", while keeping the ability "to choose which provider I am using so just set it up with
claude code and cursor and use cursor at first." Verified on 2026-11-01: the Cursor CLI on the host
offers `grok-4.7-low|medium|high|xhigh`; Cursor models draw on the plan's included pool while
third-party models bill prepaid credit; Claude Code supports a one-year subscription token for CI.

## Decision

One adapter interface (`run(task, inputs)`), two implementations selected by `.sdlc/config.json`
`provider.default` or `SDLC_PROVIDER`. Cursor: `agent -p … --model grok-4.7-high --force --trust`,
writes limited by `.cursor/cli.json`, capped by wall clock. Claude: `claude -p …` with turns,
estimated spend and tools caps, `ANTHROPIC_API_KEY` unset, never `--bare`. On pull requests the
GitHub job runs the same CLI with the key as a repository secret, and Bugbot reviews; Cursor
Automations are not adopted because they would be a second orchestration path. Both adapters
record session, model, duration and cost into `provenance.json` and the PR body.

## Consequences

Hooks, CI and cloud sessions share one code path per provider. Switching provider is a config
change. Spend is bounded differently per provider and reported per run.
