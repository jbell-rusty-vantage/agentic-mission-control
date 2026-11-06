-- Release 1.4.4 (TRACING-PROPOSAL §P2, TR-D10): the persisted Transcript projection.
-- One row per entry (`mc.transcript_entry.v2`) of a run, cursor-addressable and
-- point-addressable, replaced per run by the `transcript.project` activity under the
-- advisory lock the search projection uses, refreshed at every settlement through the
-- outbox and on demand. A read view, never state: the mission events and provider frames
-- stay authoritative and the on-demand view serves live tails.
CREATE TABLE mission_control.transcript_entry (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    run_id uuid NOT NULL,
    cursor text NOT NULL CHECK (cursor ~ '^tc1:'),
    entry_seq bigint NOT NULL CHECK (entry_seq >= 1),
    unit_key text CHECK (unit_key IS NULL OR unit_key ~ '^bl-unit-v1:[0-9a-f]{64}$'),
    activation_id uuid,
    point_id uuid,
    parent_point_id uuid,
    node_key text CHECK (node_key IS NULL OR node_key <> ''),
    iteration bigint CHECK (iteration IS NULL OR iteration >= 0),
    cycle bigint CHECK (cycle IS NULL OR cycle >= 0),
    session_generation bigint CHECK (session_generation IS NULL OR session_generation >= 1),
    subordinate_ref text CHECK (subordinate_ref IS NULL OR subordinate_ref <> ''),
    source text NOT NULL
        CHECK (source IN ('mission_event', 'provider_frame', 'artifact', 'human', 'command')),
    kind text NOT NULL CHECK (kind <> ''),
    role text NOT NULL CHECK (role <> ''),
    canonical boolean NOT NULL,
    at timestamptz NOT NULL,
    body_state text NOT NULL
        CHECK (body_state IN ('inline', 'excerpt', 'artifact', 'expired', 'pruned')),
    entry jsonb NOT NULL CHECK (jsonb_typeof(entry) = 'object'
        AND entry->>'schema_version' = 'mc.transcript_entry.v2'),
    projected_at timestamptz NOT NULL,
    projection_version integer NOT NULL CHECK (projection_version >= 1),
    PRIMARY KEY (installation_id, application_id, tenant_id, run_id, cursor),
    UNIQUE (installation_id, application_id, tenant_id, run_id, entry_seq),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, run_id)
        REFERENCES mission_control.mission_run (installation_id, application_id, tenant_id, run_id)
);
CREATE INDEX transcript_entry_point_idx ON mission_control.transcript_entry
    (installation_id, application_id, tenant_id, run_id, point_id, entry_seq)
    WHERE point_id IS NOT NULL;
CREATE INDEX transcript_entry_unit_idx ON mission_control.transcript_entry
    (installation_id, application_id, tenant_id, run_id, unit_key, entry_seq)
    WHERE unit_key IS NOT NULL;

-- Where the projection stands per run: a repeated trigger is idempotent, and a reader
-- compares these marks with the live sources to decide between the table and the view.
CREATE TABLE mission_control.transcript_projection_state (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    run_id uuid NOT NULL,
    projected_through_seq bigint NOT NULL CHECK (projected_through_seq >= 0),
    projected_through_frame jsonb
        CHECK (projected_through_frame IS NULL OR jsonb_typeof(projected_through_frame) = 'object'),
    entry_count bigint NOT NULL DEFAULT 0 CHECK (entry_count >= 0),
    projection_version integer NOT NULL CHECK (projection_version >= 1),
    projected_at timestamptz NOT NULL,
    PRIMARY KEY (installation_id, application_id, tenant_id, run_id),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, run_id)
        REFERENCES mission_control.mission_run (installation_id, application_id, tenant_id, run_id)
);

DO $policies$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['transcript_entry', 'transcript_projection_state'] LOOP
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

REVOKE ALL ON mission_control.transcript_entry, mission_control.transcript_projection_state
FROM PUBLIC;
-- The projection replaces a run's rows (insert and delete, never update) and advances the
-- state row; readers read. The outbox worker releases the trigger but never writes entries.
GRANT SELECT, INSERT, DELETE ON mission_control.transcript_entry TO mission_control_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON mission_control.transcript_projection_state
TO mission_control_runtime;
GRANT SELECT ON mission_control.transcript_entry, mission_control.transcript_projection_state
TO mission_control_readonly;
