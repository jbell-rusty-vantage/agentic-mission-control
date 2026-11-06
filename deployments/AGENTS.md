<!-- BEGIN:sdlc-module id=deployments -->
# Deployment inputs
Per-application and per-environment deployment inputs, not code. Holds application.toml, models.toml, target.toml and release.lock.json per application, plus the cloud runtime plan, hosted packs, cognition profiles, Vercel ingress and examples.
Entrypoints:
- biotech/
- ai-engineer/
- ingress-vercel/
- cloud_runtime/
- worker-aws/
- cognition-profiles/
- examples/
- hosted-packs/
Tests: deployments/cloud_runtime/test_plan.py
Invariants:
- release.lock.json and hosted-pack files are LF-pinned; their digests hash LF bytes.
- No secrets or private runtime receipts.
Explained by (docs/knowledge): applications, deployment, application-profile, database-component, model-catalog
Decided by (docs/adr): ADR-0002, ADR-0003, ADR-0009, ADR-0017, ADR-0063
Verify: uv run pytest deployments/cloud_runtime/test_plan.py; make preflight (read-only installation check)
<!-- END:sdlc-module -->
