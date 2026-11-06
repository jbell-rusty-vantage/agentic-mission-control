-- Release 1.5.0 (Sprint V SV-13, design M04/M05): transfer plans, delivery receipts, outbox.
-- `context_transfer_plan`: what must be delivered to the next (dependent) invocation across
-- one boundary: the items with their required byte digests, frozen in `plan` under
-- `plan_digest`, and the budget they must fit. Only its state advances:
-- planned -> delivering -> delivered | blocked, and planned | delivering -> superseded.
-- `context_delivery_receipt`: one append-only receipt per delivered item and receiver:
-- delivered, digest-verified, readable and within budget.
-- `context_delivery_outbox`: the transactional handoff from plan to delivery worker, following
-- the component's outbox conventions (insert by the runtime, lease and acknowledge by the
-- outbox worker; never deleted). Workflow transfer policies arrive with the later
-- output-contracts release.
CREATE TABLE mission_control.context_transfer_plan (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    transfer_plan_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    boundary text NOT NULL CHECK (boundary <> ''),
    source_invocation_ref text CHECK (source_invocation_ref IS NULL OR source_invocation_ref <> ''),
    target_operation_ref text NOT NULL CHECK (target_operation_ref <> ''),
    target_unit_key text CHECK (target_unit_key IS NULL OR target_unit_key ~ '^bl-unit-v1:[0-9a-f]{64}$'),
    plan jsonb NOT NULL CHECK (jsonb_typeof(plan) = 'object'
        AND jsonb_typeof(plan->'items') = 'array'),
    plan_digest text NOT NULL CHECK (plan_digest ~ '^sha256:[0-9a-f]{64}$'),
    required_items integer NOT NULL CHECK (required_items >= 0),
    budget_bytes bigint NOT NULL CHECK (budget_bytes >= 0),
    budget_tokens bigint CHECK (budget_tokens IS NULL OR budget_tokens >= 0),
    state text NOT NULL CHECK (state IN ('planned', 'delivering', 'delivered', 'blocked', 'superseded')),
    blocked_reason text CHECK (blocked_reason IS NULL OR blocked_reason <> ''),
    version bigint NOT NULL CHECK (version >= 1),
    planned_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    CHECK ((state = 'blocked') = (blocked_reason IS NOT NULL)),
    UNIQUE (installation_id, application_id, tenant_id, transfer_plan_id),
    UNIQUE (installation_id, application_id, tenant_id, run_id, boundary, target_operation_ref, plan_digest),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE INDEX context_transfer_plan_target_idx ON mission_control.context_transfer_plan
    (installation_id, application_id, tenant_id, run_id, target_operation_ref, state);
COMMENT ON TABLE mission_control.context_transfer_plan IS
    'mc.context_transfer_plan.v1: the frozen items (required digests) and budget to deliver to '
    'the next invocation across one boundary; only its state advances.';

CREATE FUNCTION mission_control.context_transfer_plan_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'context_transfer_plan rows are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.installation_id <> OLD.installation_id OR NEW.application_id <> OLD.application_id
       OR NEW.tenant_id <> OLD.tenant_id OR NEW.transfer_plan_id <> OLD.transfer_plan_id
       OR NEW.run_id <> OLD.run_id OR NEW.boundary <> OLD.boundary
       OR NEW.source_invocation_ref IS DISTINCT FROM OLD.source_invocation_ref
       OR NEW.target_operation_ref <> OLD.target_operation_ref
       OR NEW.target_unit_key IS DISTINCT FROM OLD.target_unit_key
       OR NEW.plan <> OLD.plan OR NEW.plan_digest <> OLD.plan_digest
       OR NEW.required_items <> OLD.required_items OR NEW.budget_bytes <> OLD.budget_bytes
       OR NEW.budget_tokens IS DISTINCT FROM OLD.budget_tokens
       OR NEW.planned_at <> OLD.planned_at OR NEW.created_at <> OLD.created_at
       OR NEW.created_by_actor_ref <> OLD.created_by_actor_ref THEN
        RAISE EXCEPTION 'context_transfer_plan items and budget are fixed'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.state <> OLD.state AND NOT (
        (OLD.state = 'planned' AND NEW.state IN ('delivering', 'superseded'))
        OR (OLD.state = 'delivering' AND NEW.state IN ('delivered', 'blocked', 'superseded'))
    ) THEN
        RAISE EXCEPTION 'illegal transfer plan transition % -> %', OLD.state, NEW.state
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.version <> OLD.version + 1 OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'context_transfer_plan version must advance by one and time never moves back'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.context_transfer_plan_guard() FROM PUBLIC;
CREATE TRIGGER context_transfer_plan_guard
    BEFORE UPDATE OR DELETE ON mission_control.context_transfer_plan
    FOR EACH ROW EXECUTE FUNCTION mission_control.context_transfer_plan_guard();

CREATE TABLE mission_control.context_delivery_receipt (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    delivery_receipt_id uuid PRIMARY KEY,
    transfer_plan_id uuid NOT NULL,
    receiver_invocation_ref text NOT NULL CHECK (receiver_invocation_ref <> ''),
    item_key text NOT NULL CHECK (item_key <> ''),
    handle text CHECK (handle IS NULL OR handle <> ''),
    delivered_path text CHECK (delivered_path IS NULL OR delivered_path ~ '^/'),
    required_digest text NOT NULL CHECK (required_digest ~ '^sha256:[0-9a-f]{64}$'),
    delivered_digest text CHECK (delivered_digest IS NULL OR delivered_digest ~ '^sha256:[0-9a-f]{64}$'),
    delivered boolean NOT NULL,
    digest_verified boolean GENERATED ALWAYS AS (
        delivered_digest IS NOT NULL AND delivered_digest = required_digest) STORED,
    readable boolean NOT NULL,
    budget_fit boolean NOT NULL,
    byte_count bigint CHECK (byte_count IS NULL OR byte_count >= 0),
    readiness jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(readiness) = 'object'),
    received_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    CHECK (NOT delivered OR delivered_digest IS NOT NULL),
    CHECK (NOT readable OR delivered),
    UNIQUE (installation_id, application_id, tenant_id, delivery_receipt_id),
    UNIQUE (installation_id, application_id, tenant_id, transfer_plan_id, receiver_invocation_ref, item_key),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, transfer_plan_id)
        REFERENCES mission_control.context_transfer_plan
            (installation_id, application_id, tenant_id, transfer_plan_id)
);
CREATE TRIGGER context_delivery_receipt_immutable
    BEFORE UPDATE OR DELETE ON mission_control.context_delivery_receipt
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.context_delivery_receipt IS
    'mc.context_delivery_receipt.v1: one item delivered to one receiver: delivered, '
    'digest-verified, readable, within budget; append-only.';

CREATE TABLE mission_control.context_delivery_outbox (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    delivery_outbox_id uuid PRIMARY KEY,
    transfer_plan_id uuid NOT NULL,
    delivery_key text NOT NULL CHECK (delivery_key <> ''),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    delivery_state text NOT NULL CHECK (delivery_state IN ('pending', 'leased', 'delivered', 'dead')),
    lease_owner text CHECK (lease_owner <> ''),
    lease_expires_at timestamptz,
    attempts integer NOT NULL CHECK (attempts >= 0),
    next_attempt_at timestamptz NOT NULL,
    delivered_at timestamptz,
    version bigint NOT NULL CHECK (version >= 1),
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    CHECK ((delivery_state = 'leased') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)),
    CHECK ((delivery_state = 'delivered') = (delivered_at IS NOT NULL)),
    UNIQUE (installation_id, application_id, tenant_id, delivery_outbox_id),
    UNIQUE (installation_id, application_id, tenant_id, delivery_key),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, transfer_plan_id)
        REFERENCES mission_control.context_transfer_plan
            (installation_id, application_id, tenant_id, transfer_plan_id)
);
CREATE INDEX context_delivery_outbox_plan_fk_idx ON mission_control.context_delivery_outbox
    (installation_id, application_id, tenant_id, transfer_plan_id);
CREATE INDEX context_delivery_outbox_due_idx ON mission_control.context_delivery_outbox
    (delivery_state, next_attempt_at) WHERE delivery_state IN ('pending', 'leased');
COMMENT ON TABLE mission_control.context_delivery_outbox IS
    'Transactional delivery handoff for context_transfer_plan; leased and acknowledged by the '
    'outbox worker, never deleted.';

CREATE FUNCTION mission_control.context_delivery_outbox_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'context_delivery_outbox rows are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.delivery_outbox_id <> OLD.delivery_outbox_id OR NEW.transfer_plan_id <> OLD.transfer_plan_id
       OR NEW.delivery_key <> OLD.delivery_key OR NEW.payload <> OLD.payload
       OR NEW.installation_id <> OLD.installation_id OR NEW.application_id <> OLD.application_id
       OR NEW.tenant_id <> OLD.tenant_id OR NEW.created_at <> OLD.created_at
       OR NEW.created_by_actor_ref <> OLD.created_by_actor_ref THEN
        RAISE EXCEPTION 'context_delivery_outbox identity and payload are fixed'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.delivery_state IN ('delivered', 'dead') AND NEW.delivery_state <> OLD.delivery_state THEN
        RAISE EXCEPTION 'a finished delivery stays finished'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'context_delivery_outbox version must advance by one'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.context_delivery_outbox_guard() FROM PUBLIC;
CREATE TRIGGER context_delivery_outbox_guard
    BEFORE UPDATE OR DELETE ON mission_control.context_delivery_outbox
    FOR EACH ROW EXECUTE FUNCTION mission_control.context_delivery_outbox_guard();

DO $policies$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'context_transfer_plan', 'context_delivery_receipt', 'context_delivery_outbox'
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

REVOKE ALL ON mission_control.context_transfer_plan, mission_control.context_delivery_receipt,
    mission_control.context_delivery_outbox FROM PUBLIC;
GRANT SELECT, INSERT ON mission_control.context_transfer_plan,
    mission_control.context_delivery_receipt, mission_control.context_delivery_outbox
TO mission_control_runtime;
GRANT UPDATE (state, blocked_reason, version, updated_at)
ON mission_control.context_transfer_plan TO mission_control_runtime;
-- Delivery relay: claim, lease and acknowledge only (as for mission_control.outbox).
GRANT SELECT ON mission_control.context_delivery_outbox TO mission_control_outbox_worker;
GRANT UPDATE (delivery_state, lease_owner, lease_expires_at, attempts, next_attempt_at,
    delivered_at, version)
ON mission_control.context_delivery_outbox TO mission_control_outbox_worker;
GRANT SELECT ON mission_control.context_transfer_plan, mission_control.context_delivery_receipt,
    mission_control.context_delivery_outbox
TO mission_control_readonly;
