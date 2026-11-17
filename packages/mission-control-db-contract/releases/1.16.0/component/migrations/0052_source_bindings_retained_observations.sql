-- Release 1.5.0 (Sprint V SV-13, design M04/M05): what an invocation was given and what it read.
-- `context_source_binding`: the exact qualified report/assertion handles one invocation was
-- bound to, each with its exact revision and digest, frozen when its context was resolved.
-- `retained_read_observation`: each read the invocation actually made of a bound (or
-- discovered) handle, the digest it observed, whether that digest matched and whether the
-- content was readable. Both are append-only evidence for the first dependent invocation;
-- neither is verification truth nor a foreign key into an application store.
CREATE TABLE mission_control.context_source_binding (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    source_binding_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    operation_ref text NOT NULL CHECK (operation_ref <> ''),
    operation_attempt integer NOT NULL CHECK (operation_attempt >= 1),
    execution_generation integer NOT NULL CHECK (execution_generation >= 1),
    unit_key text CHECK (unit_key IS NULL OR unit_key ~ '^bl-unit-v1:[0-9a-f]{64}$'),
    invocation_ref text NOT NULL CHECK (invocation_ref <> ''),
    binding_pin text NOT NULL CHECK (binding_pin <> ''),
    handle text NOT NULL CHECK (handle <> '' AND length(handle) <= 2048),
    handle_kind text NOT NULL CHECK (handle_kind IN ('report', 'assertion', 'assertion_set')),
    native_kind text NOT NULL CHECK (native_kind <> ''),
    exact_revision text NOT NULL CHECK (exact_revision <> ''),
    content_digest text NOT NULL CHECK (content_digest ~ '^sha256:[0-9a-f]{64}$'),
    resolution_ref text CHECK (resolution_ref IS NULL OR resolution_ref <> ''),
    bound_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    UNIQUE (installation_id, application_id, tenant_id, source_binding_id),
    UNIQUE (installation_id, application_id, tenant_id, invocation_ref, handle),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE INDEX context_source_binding_run_idx ON mission_control.context_source_binding
    (installation_id, application_id, tenant_id, run_id, operation_ref, operation_attempt);
CREATE TRIGGER context_source_binding_immutable
    BEFORE UPDATE OR DELETE ON mission_control.context_source_binding
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.context_source_binding IS
    'mc.context_source_binding.v1: exact qualified handles (revision and digest) one invocation '
    'was given; append-only.';

CREATE TABLE mission_control.retained_read_observation (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    observation_id uuid PRIMARY KEY,
    source_binding_id uuid,
    run_id uuid NOT NULL,
    invocation_ref text NOT NULL CHECK (invocation_ref <> ''),
    handle text NOT NULL CHECK (handle <> '' AND length(handle) <= 2048),
    read_observation_ref text NOT NULL CHECK (read_observation_ref <> ''),
    retained_ref text CHECK (retained_ref IS NULL OR retained_ref <> ''),
    expected_digest text CHECK (expected_digest IS NULL OR expected_digest ~ '^sha256:[0-9a-f]{64}$'),
    observed_digest text CHECK (observed_digest IS NULL OR observed_digest ~ '^sha256:[0-9a-f]{64}$'),
    digest_verified boolean GENERATED ALWAYS AS (
        expected_digest IS NOT NULL AND observed_digest IS NOT NULL
        AND observed_digest = expected_digest) STORED,
    readable boolean NOT NULL,
    byte_count bigint CHECK (byte_count IS NULL OR byte_count >= 0),
    consistency jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(consistency) = 'object'),
    observed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    -- Content that was read has an observed digest.
    CHECK (NOT readable OR observed_digest IS NOT NULL),
    UNIQUE (installation_id, application_id, tenant_id, observation_id),
    UNIQUE (installation_id, application_id, tenant_id, invocation_ref, read_observation_ref),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, source_binding_id)
        REFERENCES mission_control.context_source_binding
            (installation_id, application_id, tenant_id, source_binding_id)
);
CREATE INDEX retained_read_observation_binding_fk_idx ON mission_control.retained_read_observation
    (installation_id, application_id, tenant_id, source_binding_id)
    WHERE source_binding_id IS NOT NULL;
CREATE INDEX retained_read_observation_invocation_idx ON mission_control.retained_read_observation
    (installation_id, application_id, tenant_id, invocation_ref, observed_at);
CREATE TRIGGER retained_read_observation_immutable
    BEFORE UPDATE OR DELETE ON mission_control.retained_read_observation
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.retained_read_observation IS
    'mc.retained_read_observation.v1: what one invocation actually read, digest-verified, with '
    'its readable flag; append-only.';

DO $policies$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['context_source_binding', 'retained_read_observation'] LOOP
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

REVOKE ALL ON mission_control.context_source_binding, mission_control.retained_read_observation
FROM PUBLIC;
GRANT SELECT, INSERT ON mission_control.context_source_binding,
    mission_control.retained_read_observation
TO mission_control_runtime;
GRANT SELECT ON mission_control.context_source_binding, mission_control.retained_read_observation
TO mission_control_readonly;
