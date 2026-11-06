-- Release 1.7.0 (Sprint OC WI-03 / OVE-165; OUTPUT-CONTRACTS §5, ADR-0059/0060): host-recorded
-- exact use decisions.
--
-- `knowledge_use_decision`: the exact use decisions the trusted bridge recorded (replacing
--    the process-memory store `knowledge_apply` resolved): the KS decision ref, plan-level bound
--    digest, processed epoch, native plan and declared use. Immutable; the agent names only the
--    handle and the host re-checks current eligibility through KS before any use.
-- The review/evaluator wait itself is the WI-04 saved-result settlement (`invocation_settlement`,
-- 0058: `waiting` / `review_pending` with the exact pending KS decision refs) plus the standing
-- `output_assessment` that cites the exact KS decision; no second wait table exists.
-- No foreign key leaves the common component.

-- ------------------------------------------------------------------ recorded use decisions

CREATE TABLE mission_control.knowledge_use_decision (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    handle text NOT NULL CHECK (handle <> '' AND length(handle) <= 512),
    binding_id text NOT NULL CHECK (binding_id <> ''),
    use_decision_id text NOT NULL CHECK (use_decision_id <> ''),
    decision_ref jsonb NOT NULL CHECK (jsonb_typeof(decision_ref) = 'object'
        AND decision_ref->>'kind' = 'use_decision' AND decision_ref->>'id' = use_decision_id),
    bound_effect_digest text NOT NULL CHECK (bound_effect_digest ~ '^sha256:[0-9a-f]{64}$'),
    processed_epoch bigint NOT NULL CHECK (processed_epoch >= 0),
    plan jsonb NOT NULL CHECK (jsonb_typeof(plan) = 'object'),
    normalized_values_digest text CHECK (normalized_values_digest IS NULL
        OR normalized_values_digest ~ '^sha256:[0-9a-f]{64}$'),
    proposals_ref text CHECK (proposals_ref IS NULL OR proposals_ref <> ''),
    use_name text CHECK (use_name IS NULL OR use_name <> ''),
    audience text CHECK (audience IS NULL OR audience <> ''),
    recorded_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    CHECK ((use_name IS NULL) = (audience IS NULL)),
    PRIMARY KEY (installation_id, application_id, tenant_id, handle),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE TRIGGER knowledge_use_decision_immutable
    BEFORE UPDATE OR DELETE ON mission_control.knowledge_use_decision
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.knowledge_use_decision IS
    'An exact KS use decision the trusted bridge recorded for one native plan; immutable. The '
    'agent names its handle; current eligibility is re-checked through KS before use.';

DO $policies$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['knowledge_use_decision'] LOOP
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

REVOKE ALL ON mission_control.knowledge_use_decision FROM PUBLIC;
GRANT SELECT, INSERT ON mission_control.knowledge_use_decision TO mission_control_runtime;
GRANT SELECT ON mission_control.knowledge_use_decision TO mission_control_readonly;
