-- Release 2.0.0 candidate (Sprint OC WI-13 / OVE-176; OUTPUT-CONTRACTS §9,
-- 00-EXECUTION_PROGRAM_MODEL §5): the durable lineage of recursive composition. Unregistered:
-- the integrator builds and registers this file; tests apply it on top of the newest built
-- release. Authored as 0068 against 1.9.0 (ends at 0067); renumbered 0071 on 2026-11-01 (OVE-206)
-- because built releases 1.10.0-1.12.0 took keys 0068-0070.
--
-- A nested family body (a Stage Graph stage whose node is a Goal Loop or a Stage Graph, or a
-- Goal Loop's executor-phase body) executes as its own child run of the same mission revision.
-- One row per parent unit attempt records that activation: the parent run and the hosting unit
-- (`host_id`, the unit's semantic attempt), the authored structural `position`, the child run,
-- the body's family and depth, the budget ceiling the child was admitted with (never above the
-- unit's reservation) and the digest of the compiled body. The row is written once at
-- activation; it is settled once with the export receipt (`mc.nested_export_receipt.v1`: the
-- child's terminal outcome, the exact exported refs, early exports, missing required exports
-- and actual usage) and nothing else ever changes. A unit attempt activates exactly one child
-- and a child run belongs to exactly one activation.
--
-- Every key carries the installation/application/tenant scope; forced RLS; the runtime role
-- inserts, reads and settles; the read-only role reads.

CREATE TABLE mission_control.nested_activation (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    activation_id uuid PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    parent_run_key text NOT NULL CHECK (parent_run_key <> ''
        AND pg_catalog.length(parent_run_key) <= 512),
    host_id text NOT NULL CHECK (host_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    semantic_attempt_id text NOT NULL CHECK (semantic_attempt_id <> ''
        AND pg_catalog.length(semantic_attempt_id) <= 512),
    position text NOT NULL CHECK (position <> '' AND pg_catalog.length(position) <= 512),
    family text NOT NULL CHECK (family IN ('StageGraph', 'GoalDirected')),
    depth integer NOT NULL CHECK (depth >= 1 AND depth <= 4),
    child_run_key text NOT NULL CHECK (child_run_key <> ''
        AND pg_catalog.length(child_run_key) <= 512),
    budget_ceiling jsonb NOT NULL CHECK (jsonb_typeof(budget_ceiling) = 'object'),
    body_digest text NOT NULL CHECK (body_digest ~ '^sha256:[0-9a-f]{64}$'),
    activated_at timestamptz NOT NULL,
    receipt jsonb CHECK (receipt IS NULL OR (jsonb_typeof(receipt) = 'object'
        AND pg_catalog.octet_length(receipt::text) <= 65536)),
    receipt_digest text CHECK (receipt_digest IS NULL
        OR receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
    settled_at timestamptz,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    CHECK (parent_run_key <> child_run_key),
    CHECK ((receipt IS NULL) = (receipt_digest IS NULL)
        AND (receipt IS NULL) = (settled_at IS NULL)),
    UNIQUE (installation_id, application_id, tenant_id, activation_id),
    UNIQUE (installation_id, application_id, tenant_id, parent_run_key, host_id,
        semantic_attempt_id),
    UNIQUE (installation_id, application_id, tenant_id, child_run_key),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE INDEX nested_activation_parent_idx
    ON mission_control.nested_activation
        (installation_id, application_id, tenant_id, parent_run_key, activated_at);
COMMENT ON TABLE mission_control.nested_activation IS
    'mc.nested_activation.v1: one recursive activation of a nested family body as a child run '
    '(parent unit attempt, position, child run, family, depth, contained budget ceiling, body '
    'digest), settled once with its export receipt; never otherwise changed or deleted.';

-- Settle once: only the receipt, its digest and the settlement time move, from absent to set.
CREATE FUNCTION mission_control.nested_activation_settle_once() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a nested activation is never deleted' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.receipt IS NOT NULL THEN
        RAISE EXCEPTION 'a nested activation settles once' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.receipt IS NULL
        OR (NEW.installation_id, NEW.application_id, NEW.tenant_id, NEW.activation_id,
            NEW.parent_run_key, NEW.host_id, NEW.semantic_attempt_id, NEW.position, NEW.family,
            NEW.depth, NEW.child_run_key, NEW.budget_ceiling, NEW.body_digest, NEW.activated_at,
            NEW.created_at, NEW.created_by_actor_ref)
        IS DISTINCT FROM
           (OLD.installation_id, OLD.application_id, OLD.tenant_id, OLD.activation_id,
            OLD.parent_run_key, OLD.host_id, OLD.semantic_attempt_id, OLD.position, OLD.family,
            OLD.depth, OLD.child_run_key, OLD.budget_ceiling, OLD.body_digest, OLD.activated_at,
            OLD.created_at, OLD.created_by_actor_ref) THEN
        RAISE EXCEPTION 'only the export receipt of a nested activation is recorded later'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.nested_activation_settle_once() FROM PUBLIC;
CREATE TRIGGER nested_activation_settle_once
    BEFORE UPDATE OR DELETE ON mission_control.nested_activation
    FOR EACH ROW EXECUTE FUNCTION mission_control.nested_activation_settle_once();

ALTER TABLE mission_control.nested_activation ENABLE ROW LEVEL SECURITY;
ALTER TABLE mission_control.nested_activation FORCE ROW LEVEL SECURITY;
CREATE POLICY nested_activation_scope
    ON mission_control.nested_activation
    USING (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id())
    WITH CHECK (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id());

REVOKE ALL ON mission_control.nested_activation FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON mission_control.nested_activation TO mission_control_runtime;
GRANT SELECT ON mission_control.nested_activation TO mission_control_readonly;
