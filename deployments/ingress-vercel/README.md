# Signal ingress deployment

Run `python deployments/ingress-vercel/scripts/vendor_closure.py` from the repository root.
The generated closure is ignored; review its digest manifest before the Vercel build.
The project uses the existing asyncpg ingress adapter with statement caching disabled for
transaction pooling. It does not install the Mission Control runtime distribution.
The closure validator checks third-party imports against this project's lock; PyYAML
is required by the shared manifest contracts even though the edge does not author missions.

Production-only configuration: `MC_INGRESS_DSN` (restricted ingress login),
`MC_INGRESS_INSTALLATION_ID`, `MC_INGRESS_APPLICATION_ID`, and the exact credential-free
HTTPS `MC_INGRESS_ORIGIN` (also the Cursor OIDC audience). Optional quarantine uploads
require all of `MC_INGRESS_STORAGE_URL`, `MC_INGRESS_QUARANTINE_BUCKET`, and
`MC_INGRESS_STORAGE_KEY`. Optional signing configuration:
`MC_INGRESS_ENVIRONMENT_MASTER`, `MC_INGRESS_CURSOR_MASTER`, and
`MC_INGRESS_ANTHROPIC_WEBHOOK_SECRET`, `MC_INGRESS_OPENAI_WEBHOOK_SECRET`,
`MC_INGRESS_GITHUB_WEBHOOK_SECRET`. Configure secrets as sensitive values in Production;
preview startup refuses to use them. Do not connect the Supabase Marketplace integration.

Deploy only after verifying the installation's pinned fingerprint and restricted functions,
reviewing the generated closure, and confirming the exact current deployment authority.
Use team `overtons-projects`, region `iad1`, and the production `*.vercel.app` hostname.
AI Engineer is now verified at 1.4.2. Its dedicated ingress login and four production
variables are provisioned. Bundle the trusted public Supabase CA as
`certs/supabase-root.pem`; the deployed DSN uses `sslmode=verify-full` and
`sslrootcert=/var/task/certs/supabase-root.pem`. The reviewed PEM SHA256 is
`700723581420dd1ac98fd7e9ac529f0ef210eadcaf87fc868a3ad7d114c2f3b7`.
Do not copy credentials or `.env` files into the deployment source.
The repaired Run 2 deployment is live at `https://mission-control-ingress.vercel.app`:
startup/liveness and unauthenticated request refusal passed. These checks do not
qualify accepted launches, callbacks, latency or artifact custody.
Provider webhook registration requires its separate owner approval. No provider webhook,
upload, or accepted launch request can approve a mission or publish an artifact.

Source closure checks are offline evidence. The live size, cold start, p99 gate latency,
provider delivery and restricted-role PostgreSQL proofs remain separate checks.
