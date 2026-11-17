-- Release 1.7.0 (Sprint OC WI-04 / OVE-166; OUTPUT-CONTRACTS §4, ADR-0058): saved provider results
-- and their durable settlement.
--
-- `invocation_settlement` (`mc.invocation_settlement.v1`, the settlement half of
-- `InvocationFinalization@1`): one row per bound operation attempt whose cognition completed.
-- The exact provider result (`saved_result`, its digest and reference) is written before any
-- post-execution assessment, effect or review wait and never changes; the settlement state
-- (`pending` -> `waiting` -> `settled`), its typed wait reason, pending review and effect
-- references, fulfillment and finalization references, next action, recovery owner (the unit's
-- operation workflow), claim fence and stop fence advance by compare-and-set on `version`.
-- The guard keeps identity and saved bytes immutable, makes `settled` terminal, keeps the claim
-- fence monotonic (a fenced-out holder cannot write) and never lifts a stop fence. Lifecycle
-- (the operation settlement), execution outcome, fulfillment (the finalization report) and this
-- settlement stay separate rows. The store checks, in the transaction of every advance and
-- under the unit's advisory lock, that the writer's claim fence is the unit generation's
-- current `attempt.fencing_token` (a fenced-out holder is refused before the new one writes).
-- `invocation_settlement_event` is the append-only durable event log of a saved result: a
-- periodic `review_alarm` while a review holds it, and the `effect_deadline` at which an effect
-- wait becomes an operator incident. No foreign key leaves the common component.

CREATE TABLE mission_control.invocation_settlement (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    settlement_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    binding_id text NOT NULL CHECK (binding_id <> ''),
    operation_ref text NOT NULL CHECK (operation_ref <> ''),
    operation_attempt integer NOT NULL CHECK (operation_attempt >= 1),
    unit_key text NOT NULL CHECK (unit_key <> ''),
    execution_generation integer NOT NULL CHECK (execution_generation >= 1),
    saved_result jsonb NOT NULL CHECK (jsonb_typeof(saved_result) = 'object'
        AND jsonb_typeof(saved_result->'output_text') = 'string'
        AND NOT (saved_result ?| ARRAY['credential', 'token', 'authorization', 'secret'])),
    saved_result_digest text NOT NULL CHECK (saved_result_digest ~ '^sha256:[0-9a-f]{64}$'),
    saved_result_size_bytes integer NOT NULL CHECK (saved_result_size_bytes BETWEEN 2 AND 8388608),
    execution_outcome text NOT NULL CHECK (execution_outcome = 'completed'),
    settlement text NOT NULL CHECK (settlement IN ('pending', 'waiting', 'settled')),
    reason text CHECK (reason IS NULL OR reason IN (
        'review_pending', 'effect_pending', 'settlement_unavailable')),
    pending_reviews text[] NOT NULL DEFAULT '{}' CHECK (cardinality(pending_reviews) <= 256),
    pending_effects text[] NOT NULL DEFAULT '{}' CHECK (cardinality(pending_effects) <= 256),
    fulfillment_refs text[] NOT NULL DEFAULT '{}' CHECK (cardinality(fulfillment_refs) <= 256),
    finalization_ref text CHECK (finalization_ref IS NULL OR finalization_ref <> ''),
    recovery_owner text NOT NULL CHECK (recovery_owner <> ''),
    next_action text CHECK (next_action IS NULL OR next_action IN (
        'settle', 'await_review', 'await_effect', 'retry_settlement')),
    claim_fence integer NOT NULL CHECK (claim_fence >= 1),
    stop_fence text NOT NULL CHECK (stop_fence IN ('none', 'cancelled')),
    waits integer NOT NULL CHECK (waits >= 0),
    version integer NOT NULL CHECK (version >= 1),
    record jsonb NOT NULL CHECK (jsonb_typeof(record) = 'object'
        AND record->>'schema_version' = 'mc.invocation_settlement.v1'),
    saved_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    settled_at timestamptz,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    -- The stored document is the record: its keys agree with the columns.
    CHECK ((record->>'settlement_id' = settlement_id::text
        AND record->>'binding_id' = binding_id
        AND record->>'saved_result_digest' = saved_result_digest
        AND record->>'settlement' = settlement
        AND record->>'stop_fence' = stop_fence
        AND (record->'version')::integer = version
        AND (record->'claim_fence')::integer = claim_fence) IS TRUE),
    -- A settled row is terminal and carries its time; a waiting row names its typed reason.
    CHECK ((settlement = 'settled') = (settled_at IS NOT NULL)),
    CHECK (settlement <> 'settled' OR (reason IS NULL AND next_action IS NULL)),
    CHECK (settlement <> 'waiting' OR (reason IS NOT NULL AND next_action IS NOT NULL)),
    CHECK (reason IS DISTINCT FROM 'review_pending' OR cardinality(pending_reviews) >= 1),
    CHECK (reason IS DISTINCT FROM 'effect_pending' OR cardinality(pending_effects) >= 1),
    UNIQUE (installation_id, application_id, tenant_id, settlement_id),
    UNIQUE (installation_id, application_id, tenant_id, binding_id),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE INDEX invocation_settlement_open_idx ON mission_control.invocation_settlement
    (installation_id, application_id, tenant_id, run_id, settlement)
    WHERE settlement <> 'settled';

CREATE FUNCTION mission_control.invocation_settlement_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a saved provider result is never deleted'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF (NEW.installation_id, NEW.application_id, NEW.tenant_id, NEW.settlement_id, NEW.run_id,
            NEW.binding_id, NEW.operation_ref, NEW.operation_attempt, NEW.unit_key,
            NEW.execution_generation, NEW.saved_result, NEW.saved_result_digest,
            NEW.saved_result_size_bytes, NEW.execution_outcome, NEW.saved_at,
            NEW.created_by_actor_ref)
        IS DISTINCT FROM
       (OLD.installation_id, OLD.application_id, OLD.tenant_id, OLD.settlement_id, OLD.run_id,
            OLD.binding_id, OLD.operation_ref, OLD.operation_attempt, OLD.unit_key,
            OLD.execution_generation, OLD.saved_result, OLD.saved_result_digest,
            OLD.saved_result_size_bytes, OLD.execution_outcome, OLD.saved_at,
            OLD.created_by_actor_ref) THEN
        RAISE EXCEPTION 'a saved provider result and its identity are immutable'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.settlement = 'settled' THEN
        RAISE EXCEPTION 'a settled saved result never changes'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.version <> OLD.version + 1 OR NEW.claim_fence < OLD.claim_fence
            OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'a settlement successor advances by one version under its fence'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.stop_fence = 'cancelled' AND NEW.stop_fence <> 'cancelled' THEN
        RAISE EXCEPTION 'a stop fence is never lifted'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.invocation_settlement_guard() FROM PUBLIC;
CREATE TRIGGER invocation_settlement_guard
    BEFORE UPDATE OR DELETE ON mission_control.invocation_settlement
    FOR EACH ROW EXECUTE FUNCTION mission_control.invocation_settlement_guard();
COMMENT ON TABLE mission_control.invocation_settlement IS
    'mc.invocation_settlement.v1: one saved provider result (immutable bytes) and its durable '
    'settlement (pending, waiting with typed reason and pending refs, settled), advanced by CAS '
    'under a monotonic claim fence by its recovery owner; a stop fence is never lifted.';

ALTER TABLE mission_control.invocation_settlement ENABLE ROW LEVEL SECURITY;
ALTER TABLE mission_control.invocation_settlement FORCE ROW LEVEL SECURITY;
CREATE POLICY invocation_settlement_scope ON mission_control.invocation_settlement
    USING (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id())
    WITH CHECK (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id());

REVOKE ALL ON mission_control.invocation_settlement FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON mission_control.invocation_settlement TO mission_control_runtime;
GRANT SELECT ON mission_control.invocation_settlement TO mission_control_readonly;

CREATE TABLE mission_control.invocation_settlement_event (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    settlement_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('review_alarm', 'effect_deadline')),
    sequence integer NOT NULL CHECK (sequence >= 0),
    occurred_at timestamptz NOT NULL,
    detail jsonb NOT NULL CHECK (jsonb_typeof(detail) = 'object'),
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    PRIMARY KEY (installation_id, application_id, tenant_id, settlement_id, kind, sequence),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, settlement_id)
        REFERENCES mission_control.invocation_settlement
            (installation_id, application_id, tenant_id, settlement_id)
);
CREATE TRIGGER invocation_settlement_event_immutable
    BEFORE UPDATE OR DELETE ON mission_control.invocation_settlement_event
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.invocation_settlement_event IS
    'Durable events of a saved provider result: a periodic review_alarm while a review holds it '
    'and the effect_deadline at which an effect wait becomes an operator incident; append-only.';
ALTER TABLE mission_control.invocation_settlement_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE mission_control.invocation_settlement_event FORCE ROW LEVEL SECURITY;
CREATE POLICY invocation_settlement_event_scope ON mission_control.invocation_settlement_event
    USING (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id())
    WITH CHECK (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id());
REVOKE ALL ON mission_control.invocation_settlement_event FROM PUBLIC;
GRANT SELECT, INSERT ON mission_control.invocation_settlement_event TO mission_control_runtime;
GRANT SELECT ON mission_control.invocation_settlement_event TO mission_control_readonly;
