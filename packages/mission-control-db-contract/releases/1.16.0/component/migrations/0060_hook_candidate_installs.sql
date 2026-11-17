-- Release 1.7.0 (Sprint OC WI-17 / OVE-180; OUTPUT-CONTRACTS §11, ADR-0062): durable install
-- records of host-validated hook candidates.
--
-- A hook stages an attributed candidate file; the host installs it into the receiver's workspace
-- only at a safe boundary, after policy, current-authority and version checks. Two append-only
-- tables make that installation exactly-once across a same-path race and a crash:
--
-- 1. `context_candidate_install`: the claim of one receiver path (run, receiver operation,
--    receiver attempt, execution generation, target path) by one attributed candidate (origin = the hook invocation, digest, custody
--    reference of the staged bytes). Unique per receiver path, so of two racing candidates one
--    claims and the other refuses; a retry of the same candidate in the same attempt finds its
--    own claim, while a new attempt (a fresh workspace) is a new receiver and installs anew.
-- 2. `context_candidate_install_outcome`: the one installation of a claim, observed through the
--    receiving backend with the candidate's exact digest. Unique per claim, so a crash after the
--    write or after the outcome is recorded once, never installed twice.
--
-- Host-owned state (`/.mission/...`) and the sealed input mounts (`/inputs/...`) can never be a
-- target. An install record is not a submission, an accepted head or a transfer delivery
-- receipt: nothing here can fulfill an output obligation. No foreign key leaves the component.

CREATE TABLE mission_control.context_candidate_install (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    install_id uuid PRIMARY KEY,
    run_id text NOT NULL CHECK (run_id <> ''),
    receiver_operation_ref text NOT NULL CHECK (receiver_operation_ref <> ''),
    receiver_attempt integer NOT NULL CHECK (receiver_attempt >= 1),
    target_path text NOT NULL CHECK (
        target_path ~ '^/.*[^/]$'
        AND strpos(target_path, chr(92)) = 0
        AND target_path !~ '(^|/)\.\.?(/|$)'
        AND target_path !~ '//'
        AND lower(target_path) <> '/.mission' AND lower(target_path) NOT LIKE '/.mission/%'
        AND lower(target_path) <> '/inputs' AND lower(target_path) NOT LIKE '/inputs/%'
        AND length(target_path) <= 512),
    candidate_id uuid NOT NULL,
    candidate_digest text NOT NULL CHECK (candidate_digest ~ '^sha256:[0-9a-f]{64}$'),
    size_bytes integer NOT NULL CHECK (size_bytes BETWEEN 0 AND 65536),
    custody_ref text NOT NULL CHECK (custody_ref <> ''),
    hook_id text NOT NULL CHECK (hook_id <> ''),
    hook_event text NOT NULL CHECK (hook_event IN (
        'after_model', 'after_tool', 'after_tool_failure', 'after_shell', 'after_file_edit',
        'after_compaction', 'subagent_stop', 'stop', 'session_end')),
    candidate jsonb NOT NULL CHECK (jsonb_typeof(candidate) = 'object'
        AND jsonb_typeof(candidate->'origin') = 'object'
        AND NOT (candidate ?| ARRAY['credential', 'token', 'authorization', 'secret', 'content'])),
    workspace_generation integer NOT NULL CHECK (workspace_generation >= 1),
    boundary text NOT NULL CHECK (boundary <> ''),
    claimed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    -- The stored document is the attributed candidate: its keys agree with the columns.
    CHECK ((candidate->>'candidate_id' = candidate_id::text
        AND candidate->>'digest' = candidate_digest
        AND candidate->>'path' = target_path
        AND (candidate->'size_bytes')::integer = size_bytes
        AND candidate->'origin'->>'hook_id' = hook_id
        AND candidate->'origin'->>'event' = hook_event) IS TRUE),
    UNIQUE (installation_id, application_id, tenant_id, install_id),
    UNIQUE (installation_id, application_id, tenant_id, install_id, candidate_id, candidate_digest),
    -- One candidate per receiver attempt path: the same-path race has exactly one winner.
    UNIQUE (installation_id, application_id, tenant_id, run_id, receiver_operation_ref,
        receiver_attempt, workspace_generation, target_path),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE INDEX context_candidate_install_receiver_idx ON mission_control.context_candidate_install
    (installation_id, application_id, tenant_id, run_id, receiver_operation_ref, receiver_attempt,
     workspace_generation, claimed_at);
CREATE TRIGGER context_candidate_install_immutable
    BEFORE UPDATE OR DELETE ON mission_control.context_candidate_install
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.context_candidate_install IS
    'mc.hook_candidate_install.v1 claim: one receiver path claimed by one attributed hook '
    'candidate (origin, digest, custody); immutable, unique per (run, receiver, attempt, '
    'generation, path).';

CREATE TABLE mission_control.context_candidate_install_outcome (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    install_id uuid PRIMARY KEY,
    candidate_id uuid NOT NULL,
    candidate_digest text NOT NULL CHECK (candidate_digest ~ '^sha256:[0-9a-f]{64}$'),
    observed_digest text NOT NULL CHECK (observed_digest ~ '^sha256:[0-9a-f]{64}$'),
    realized_backend text NOT NULL CHECK (realized_backend <> ''),
    probe text NOT NULL CHECK (probe IN ('backend_read', 'state_files_read')),
    recovered boolean NOT NULL,
    installed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    -- Installed means read back through the receiving backend with the candidate's bytes.
    CHECK (observed_digest = candidate_digest),
    UNIQUE (installation_id, application_id, tenant_id, install_id),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id),
    -- An outcome installs exactly the claimed candidate and digest.
    FOREIGN KEY (installation_id, application_id, tenant_id, install_id, candidate_id,
            candidate_digest)
        REFERENCES mission_control.context_candidate_install
            (installation_id, application_id, tenant_id, install_id, candidate_id,
             candidate_digest)
);
CREATE TRIGGER context_candidate_install_outcome_immutable
    BEFORE UPDATE OR DELETE ON mission_control.context_candidate_install_outcome
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.context_candidate_install_outcome IS
    'The one installation of a hook candidate claim, read back through the receiving backend '
    'with the exact digest; immutable, once per claim (crash recovery records it once).';

DO $policies$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'context_candidate_install', 'context_candidate_install_outcome'
    ] LOOP
        EXECUTE pg_catalog.format('ALTER TABLE mission_control.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE pg_catalog.format('ALTER TABLE mission_control.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE pg_catalog.format(
            'CREATE POLICY %I ON mission_control.%I '
            'USING (installation_id = mission_control.ctx_installation_id() '
            'AND application_id = mission_control.ctx_application_id() '
            'AND tenant_id = mission_control.ctx_tenant_id()) '
            'WITH CHECK (installation_id = mission_control.ctx_installation_id() '
            'AND application_id = mission_control.ctx_application_id() '
            'AND tenant_id = mission_control.ctx_tenant_id())',
            table_name || '_scope', table_name);
    END LOOP;
END
$policies$;

REVOKE ALL ON mission_control.context_candidate_install,
    mission_control.context_candidate_install_outcome FROM PUBLIC;
GRANT SELECT, INSERT ON mission_control.context_candidate_install,
    mission_control.context_candidate_install_outcome
TO mission_control_runtime;
GRANT SELECT ON mission_control.context_candidate_install,
    mission_control.context_candidate_install_outcome
TO mission_control_readonly;
