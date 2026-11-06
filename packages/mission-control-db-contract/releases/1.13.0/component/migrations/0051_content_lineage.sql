-- Release 1.5.0 (Sprint V SV-13, SP-10 / OC-D80): append-only content lineage.
-- One row per provenance fact about one qualified handle (an artifact, output or report
-- revision) in one of the seven provenance roles. Lineage joins stores only by receipt or
-- effect key and content digest (DP-D14); it holds no foreign key into an application store.
-- Invariants enforced here: the role names its actor kind; adoption never writes a producer
-- fact; a subject has at most one producer fact; rows are never updated or deleted.
CREATE TABLE mission_control.content_lineage (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    lineage_id uuid PRIMARY KEY,
    subject_handle text NOT NULL CHECK (subject_handle <> '' AND length(subject_handle) <= 2048),
    subject_kind text NOT NULL CHECK (subject_kind IN ('artifact', 'output', 'report', 'assertion')),
    subject_digest text CHECK (subject_digest IS NULL OR subject_digest ~ '^sha256:[0-9a-f]{64}$'),
    role text NOT NULL CHECK (role IN (
        'producer', 'caller', 'receipt', 'revision', 'adopter', 'assessor', 'consumer')),
    actor_kind text NOT NULL CHECK (actor_kind IN (
        'origin', 'external', 'receipt', 'revision', 'obligation', 'assessment')),
    actor_ref text NOT NULL CHECK (actor_ref <> ''),
    actor_origin jsonb CHECK (actor_origin IS NULL OR jsonb_typeof(actor_origin) = 'object'),
    run_id uuid,
    knowledge_operation_id uuid,
    effect_key text CHECK (effect_key IS NULL OR effect_key <> ''),
    fact jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(fact) = 'object'),
    recorded_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    -- The seven roles and the only actors that may hold each.
    CHECK (
        (role = 'producer' AND actor_kind IN ('origin', 'external'))
        OR (role IN ('caller', 'consumer') AND actor_kind = 'origin')
        OR (role = 'receipt' AND actor_kind = 'receipt')
        OR (role = 'revision' AND actor_kind = 'revision')
        OR (role = 'adopter' AND actor_kind = 'obligation')
        OR (role = 'assessor' AND actor_kind = 'assessment')
    ),
    -- An origin actor carries the host-authenticated invocation it names.
    CHECK (actor_kind <> 'origin' OR actor_origin IS NOT NULL),
    -- Adopting existing content is never a producer fact (OC-D80).
    CHECK (role <> 'producer' OR fact->>'act' IS DISTINCT FROM 'adoption'),
    UNIQUE (installation_id, application_id, tenant_id, lineage_id),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, knowledge_operation_id)
        REFERENCES mission_control.knowledge_operation_journal
            (installation_id, application_id, tenant_id, knowledge_operation_id)
);
CREATE UNIQUE INDEX content_lineage_one_producer_idx ON mission_control.content_lineage
    (installation_id, application_id, tenant_id, subject_handle) WHERE role = 'producer';
CREATE INDEX content_lineage_subject_idx ON mission_control.content_lineage
    (installation_id, application_id, tenant_id, subject_handle, role, recorded_at);
CREATE INDEX content_lineage_effect_idx ON mission_control.content_lineage
    (installation_id, application_id, tenant_id, effect_key) WHERE effect_key IS NOT NULL;
CREATE INDEX content_lineage_operation_fk_idx ON mission_control.content_lineage
    (installation_id, application_id, tenant_id, knowledge_operation_id)
    WHERE knowledge_operation_id IS NOT NULL;
CREATE TRIGGER content_lineage_immutable
    BEFORE UPDATE OR DELETE ON mission_control.content_lineage
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.content_lineage IS
    'mc.content_lineage.v1: append-only provenance facts in the seven roles '
    '(producer, caller, receipt, revision, adopter, assessor, consumer).';

ALTER TABLE mission_control.content_lineage ENABLE ROW LEVEL SECURITY;
ALTER TABLE mission_control.content_lineage FORCE ROW LEVEL SECURITY;
CREATE POLICY content_lineage_scope ON mission_control.content_lineage
    USING (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id())
    WITH CHECK (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id());

REVOKE ALL ON mission_control.content_lineage FROM PUBLIC;
GRANT SELECT, INSERT ON mission_control.content_lineage TO mission_control_runtime;
GRANT SELECT ON mission_control.content_lineage TO mission_control_readonly;
