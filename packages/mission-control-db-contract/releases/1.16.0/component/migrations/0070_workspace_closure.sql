-- 1.12.0 (OVE-204 slice 5): Workspace Closures, the evidence of what an agent could see when an
-- attempt settled. One header per closure (the `mc.workspace_closure.v1` manifest and counts)
-- and one entry per file (raw-byte digest, slot, destination, body state and, for a promoted
-- body, its content-addressed object reference). A closure is an attribute of the unit's result
-- checkpoint point; it is written by the activity before the settlement writes the point, so
-- `point_id` is the deterministic point id and carries no foreign key.
--
-- Rows are append-only: an UPDATE guard refuses changes and no role holds DELETE. The frames
-- expire pass calls the definer `expire_workspace_closures(p_now)`, which deletes the closures
-- of completed runs past `retain_until` (NULL keeps a closure for the mission's evidence life,
-- ADR-0055); entries go with their header (ON DELETE CASCADE). Payload bytes are shared across
-- runs and are not deleted here.

CREATE TABLE mission_control.workspace_closure (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    closure_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    unit_key text NOT NULL CHECK (unit_key ~ '^bl-unit-v1:[0-9a-f]{64}$'),
    execution_generation bigint NOT NULL CHECK (execution_generation >= 1),
    harness_execution_id uuid,
    point_id uuid NOT NULL,
    boundary text NOT NULL
        CHECK (boundary IN ('attempt_settled', 'attempt_failed', 'attempt_cancelled')),
    backend text NOT NULL CHECK (backend IN ('state', 'docker', 'langsmith', 'daytona')),
    manifest jsonb NOT NULL
        CHECK ((jsonb_typeof(manifest) = 'object'
            AND manifest->>'schema_version' = 'mc.workspace_closure.v1') IS TRUE),
    manifest_digest text NOT NULL CHECK (manifest_digest ~ '^sha256:[0-9a-f]{64}$'),
    manifest_object_ref text CHECK (manifest_object_ref IS NULL OR manifest_object_ref <> ''),
    file_count integer NOT NULL CHECK (file_count >= 0),
    total_bytes bigint NOT NULL CHECK (total_bytes >= 0),
    promoted_bytes bigint NOT NULL CHECK (promoted_bytes >= 0 AND promoted_bytes <= total_bytes),
    complete boolean NOT NULL,
    retain_until timestamptz,
    recorded_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    UNIQUE (installation_id, application_id, tenant_id, closure_id),
    UNIQUE (installation_id, application_id, tenant_id, unit_key, execution_generation, point_id,
        boundary),
    FOREIGN KEY (installation_id, application_id, tenant_id, run_id)
        REFERENCES mission_control.mission_run (installation_id, application_id, tenant_id, run_id)
);

CREATE TABLE mission_control.workspace_closure_entry (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    closure_id uuid NOT NULL,
    run_id uuid NOT NULL,
    path text NOT NULL CHECK (path ~ '^/' AND length(path) <= 1024),
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    digest text NOT NULL CHECK (digest ~ '^sha256:[0-9a-f]{64}$'),
    slot text CHECK (slot IS NULL OR slot <> ''),
    destination text NOT NULL
        CHECK (destination IN ('state_channel', 'sandbox_writable', 'sandbox_workdir',
            'sandbox_upload')),
    body_state text NOT NULL
        CHECK (body_state IN ('promoted', 'withheld_cap', 'withheld_sensitive', 'withheld_secret',
            'withheld_input', 'unreadable')),
    object_ref text CHECK (object_ref IS NULL OR object_ref <> ''),
    media_type text CHECK (media_type IS NULL OR media_type <> ''),
    candidate_id text CHECK (candidate_id IS NULL OR candidate_id <> ''),
    CHECK ((body_state = 'promoted') = (object_ref IS NOT NULL)),
    PRIMARY KEY (installation_id, application_id, tenant_id, closure_id, path),
    FOREIGN KEY (installation_id, application_id, tenant_id, closure_id)
        REFERENCES mission_control.workspace_closure (installation_id, application_id, tenant_id,
            closure_id)
        ON DELETE CASCADE
);

CREATE INDEX workspace_closure_run_idx ON mission_control.workspace_closure
    (installation_id, application_id, tenant_id, run_id, recorded_at);
CREATE INDEX workspace_closure_point_idx ON mission_control.workspace_closure
    (installation_id, application_id, tenant_id, point_id);
CREATE INDEX workspace_closure_expiry_idx ON mission_control.workspace_closure
    (installation_id, application_id, tenant_id, retain_until) WHERE retain_until IS NOT NULL;
CREATE INDEX workspace_closure_entry_digest_idx ON mission_control.workspace_closure_entry
    (installation_id, application_id, tenant_id, run_id, digest);

CREATE TRIGGER workspace_closure_immutable
    BEFORE UPDATE ON mission_control.workspace_closure
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
CREATE TRIGGER workspace_closure_entry_immutable
    BEFORE UPDATE ON mission_control.workspace_closure_entry
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();

ALTER TABLE mission_control.workspace_closure ENABLE ROW LEVEL SECURITY;
ALTER TABLE mission_control.workspace_closure FORCE ROW LEVEL SECURITY;
CREATE POLICY workspace_closure_scope ON mission_control.workspace_closure
    USING (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id())
    WITH CHECK (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id());
ALTER TABLE mission_control.workspace_closure_entry ENABLE ROW LEVEL SECURITY;
ALTER TABLE mission_control.workspace_closure_entry FORCE ROW LEVEL SECURITY;
CREATE POLICY workspace_closure_entry_scope ON mission_control.workspace_closure_entry
    USING (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id())
    WITH CHECK (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id());

REVOKE ALL ON mission_control.workspace_closure, mission_control.workspace_closure_entry
    FROM PUBLIC;
GRANT SELECT, INSERT ON mission_control.workspace_closure, mission_control.workspace_closure_entry
    TO mission_control_runtime;
GRANT SELECT ON mission_control.workspace_closure, mission_control.workspace_closure_entry
    TO mission_control_readonly;

-- Retention: the only path that deletes a closure. Scope comes from the transaction context;
-- only completed runs' closures with a passed `retain_until` go.
CREATE FUNCTION mission_control.expire_workspace_closures(
    p_now timestamptz
) RETURNS TABLE (expired_closure_id uuid)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DELETE FROM mission_control.workspace_closure AS c
    USING mission_control.mission_run AS r
    WHERE c.installation_id = mission_control.ctx_installation_id()
      AND c.application_id = mission_control.ctx_application_id()
      AND c.tenant_id = mission_control.ctx_tenant_id()
      AND r.installation_id = c.installation_id
      AND r.application_id = c.application_id
      AND r.tenant_id = c.tenant_id
      AND r.run_id = c.run_id
      AND r.lifecycle = 'completed'
      AND c.retain_until IS NOT NULL
      AND c.retain_until < p_now
    RETURNING c.closure_id
$$;
REVOKE ALL ON FUNCTION mission_control.expire_workspace_closures(timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mission_control.expire_workspace_closures(timestamptz)
TO mission_control_runtime;
