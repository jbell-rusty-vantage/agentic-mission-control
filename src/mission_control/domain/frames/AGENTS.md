<!-- BEGIN:sdlc-module id=domain.frames -->
# Provider frames and transcript rules
Provider Frames, closing facts, usage and Transcript renderers. A Provider Frame is the lane-neutral record of what a provider said; the renderers emit JSONL for agents and Markdown for humans.
Entrypoints:
- render.py — Pure Transcript renderers: JSONL for agents and Markdown for humans
- contracts.py — Provider frames: the lane-neutral record of what a provider said
- transcript.py — mc.transcript_entry.v2: one line of a run's materialized Transcript
- run_query.py — The bounded run-list filter grammar and its Temporal Visibility translation
- usage.py — Usage reports with dispositions
- facts.py — Frame facts: what closing provider frames establish, and the mission events they…
- body.py — Frame body handling: canonical JSON, secret redaction, digest and bounded excerpt
- lifecycle.py — Bounded, non-text lifecycle evidence retained when a native body exceeds its excerpt
Tests: tests/unit/frames
Invariants:
- Frame bodies are canonical JSON with secrets redacted and a bounded excerpt.
Explained by (docs/knowledge): provider-frames-and-transcript
Decided by (docs/adr): ADR-0055, ADR-0028, ADR-0054, ADR-0056
Depends on: contracts, domain.programs · Used by: application, adapters, adapters.codex, adapters.postgres, adapters.claude, adapters.deep_agents (+7)
Verify: uv run pytest tests/unit/frames
<!-- END:sdlc-module -->
