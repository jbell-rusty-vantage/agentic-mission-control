-- Release 1.7.0 (Sprint OC WI-02 / OVE-164; OUTPUT-CONTRACTS §6, ADR-0061): one sealed transfer
-- plan per receiver and attempt-specific delivery receipts.
--
-- 1. The Sprint V M04 per-boundary authority is retired in one cutover (its run-wide selection
--    and fixed one-repair rule are removed from the runtime): `context_delivery_outbox`,
--    `context_delivery_receipt`, `context_transfer_plan` and their guard functions are dropped.
--    Their rows were experimental and disposable (OUTPUT-CONTRACTS §1); no reader remains.
-- 2. `transfer_plan`: the one canonical sealed plan of one receiver boundary
--    (`mc.sealed_transfer_plan.v1`): exact members, placements, omissions, aggregate resource
--    plan, selection authority and host-state reference, under its digest. Immutable; one plan per
--    receiver key, so a retry, restart or redelivery reuses it and never resolves today's revision.
-- 3. `transfer_delivery_receipt`: one append-only receipt per realization of a plan; its identity
--    includes the receiver attempt (operation attempt, execution generation, invocation) and the
--    realized backend, and a per-plan sequence orders redeliveries.
-- 4. `transfer_member_delivery`: one row per member of a receipt (placement, path or handle,
--    required and observed digest, probe, readability, current-access reference), so readiness
--    and file realization are queryable without unpacking documents.
-- The Context Packet record (`context_selection`) stays the packer's host-state rendering; a plan
-- references it through `host_state_ref` and is the only record that names what a receiver gets.
-- No foreign key leaves the common component.

-- ------------------------------------------------------------------ 1. retire M04

DROP TABLE mission_control.context_delivery_outbox;
DROP TABLE mission_control.context_delivery_receipt;
DROP TABLE mission_control.context_transfer_plan;
DROP FUNCTION mission_control.context_delivery_outbox_guard();
DROP FUNCTION mission_control.context_delivery_receipt_attempt_guard();
DROP FUNCTION mission_control.context_transfer_plan_guard();

-- ------------------------------------------------------------------ 2. sealed plans

CREATE TABLE mission_control.transfer_plan (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    transfer_plan_id uuid PRIMARY KEY,
    receiver_key text NOT NULL CHECK (receiver_key ~ '^sha256:[0-9a-f]{64}$'),
    run_id uuid NOT NULL,
    receiver_operation_ref text NOT NULL CHECK (receiver_operation_ref <> ''),
    receiver_position text NOT NULL CHECK (receiver_position <> ''),
    boundary text NOT NULL CHECK (boundary IN (
        'first_invocation', 'next_iteration', 'dependent_stage', 'evaluator', 'repair',
        'nested_export', 'linked_mission', 'continuation', 'repair_fork')),
    isolation text NOT NULL CHECK (isolation IN ('shared', 'independent_evaluator')),
    configuration_ref text NOT NULL CHECK (configuration_ref <> ''),
    selection_authority_ref text NOT NULL CHECK (selection_authority_ref ~ '^sha256:[0-9a-f]{64}$'),
    host_state_ref text CHECK (host_state_ref IS NULL OR host_state_ref <> ''),
    profile_pin text NOT NULL CHECK (profile_pin <> ''),
    plan jsonb NOT NULL CHECK (jsonb_typeof(plan) = 'object'
        AND plan->>'schema_version' = 'mc.sealed_transfer_plan.v1'
        AND jsonb_typeof(plan->'exact_sources') = 'array'
        AND jsonb_typeof(plan->'placements') = 'array'
        AND jsonb_typeof(plan->'resource_plan') = 'object'),
    plan_digest text NOT NULL CHECK (plan_digest ~ '^sha256:[0-9a-f]{64}$'),
    member_count integer NOT NULL CHECK (member_count >= 0),
    total_tokens bigint NOT NULL CHECK (total_tokens >= 0),
    context_window_tokens bigint NOT NULL CHECK (context_window_tokens >= 1),
    file_bytes bigint NOT NULL CHECK (file_bytes >= 0),
    sealed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    -- The stored document is the plan: its keys agree with the columns.
    CHECK ((plan->>'plan_id' = transfer_plan_id::text
        AND plan->>'digest' = plan_digest
        AND plan->>'receiver_key' = receiver_key
        AND plan->>'boundary' = boundary
        AND plan->>'selection_authority_ref' = selection_authority_ref
        AND jsonb_array_length(plan->'exact_sources') = member_count) IS TRUE),
    -- The accounting columns are the plan document's own resource plan.
    CHECK ((total_tokens = (plan->'resource_plan'->>'total_tokens')::bigint
        AND context_window_tokens = (plan->'resource_plan'->'bounds'->>'window_tokens')::bigint
        AND file_bytes = (plan->'resource_plan'->>'file_bytes')::bigint) IS TRUE),
    -- A sealed plan always fits its receiver's window.
    CHECK (total_tokens <= context_window_tokens),
    -- An evaluator boundary is always independent.
    CHECK (boundary <> 'evaluator' OR isolation = 'independent_evaluator'),
    UNIQUE (installation_id, application_id, tenant_id, transfer_plan_id),
    UNIQUE (installation_id, application_id, tenant_id, transfer_plan_id, plan_digest),
    UNIQUE (installation_id, application_id, tenant_id, receiver_key),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE INDEX transfer_plan_run_idx ON mission_control.transfer_plan
    (installation_id, application_id, tenant_id, run_id, receiver_operation_ref);
CREATE TRIGGER transfer_plan_immutable
    BEFORE UPDATE OR DELETE ON mission_control.transfer_plan
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.transfer_plan IS
    'mc.sealed_transfer_plan.v1: the one sealed transfer authority of a receiver boundary '
    '(exact members, placements, omissions, aggregate resources); immutable, one per receiver.';

-- ------------------------------------------------------------------ 3. attempt receipts

CREATE TABLE mission_control.transfer_delivery_receipt (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    delivery_receipt_id uuid PRIMARY KEY,
    transfer_plan_id uuid NOT NULL,
    plan_digest text NOT NULL CHECK (plan_digest ~ '^sha256:[0-9a-f]{64}$'),
    sequence integer NOT NULL CHECK (sequence >= 1),
    operation_attempt integer NOT NULL CHECK (operation_attempt >= 1),
    execution_generation integer NOT NULL CHECK (execution_generation >= 1),
    receiver_invocation_ref text NOT NULL CHECK (receiver_invocation_ref <> ''),
    realized_backend text NOT NULL CHECK (realized_backend <> ''),
    result text NOT NULL CHECK (result IN ('ready', 'refused', 'waiting')),
    total_tokens bigint NOT NULL CHECK (total_tokens >= 0),
    headroom_tokens bigint NOT NULL,
    receipt jsonb NOT NULL CHECK (jsonb_typeof(receipt) = 'object'
        AND receipt->>'schema_version' = 'mc.transfer_delivery_receipt.v1'
        AND NOT (receipt ?| ARRAY['credential', 'token', 'authorization', 'secret'])),
    correlation_id text NOT NULL CHECK (correlation_id <> ''),
    received_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    CHECK ((receipt->>'receipt_id' = delivery_receipt_id::text
        AND receipt->>'plan_id' = transfer_plan_id::text
        AND receipt->>'plan_digest' = plan_digest
        AND receipt->>'result' = result
        AND receipt->>'realized_backend' = realized_backend
        AND (receipt->'sequence')::integer = sequence) IS TRUE),
    -- Ready needs aggregate feasibility as measured for this attempt.
    CHECK (result <> 'ready' OR headroom_tokens >= 0),
    UNIQUE (installation_id, application_id, tenant_id, delivery_receipt_id),
    UNIQUE (installation_id, application_id, tenant_id, transfer_plan_id, sequence),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id),
    -- A receipt realizes exactly the sealed plan digest it names.
    FOREIGN KEY (installation_id, application_id, tenant_id, transfer_plan_id, plan_digest)
        REFERENCES mission_control.transfer_plan
            (installation_id, application_id, tenant_id, transfer_plan_id, plan_digest)
);
CREATE INDEX transfer_delivery_receipt_attempt_idx ON mission_control.transfer_delivery_receipt
    (installation_id, application_id, tenant_id, transfer_plan_id, operation_attempt,
     execution_generation, realized_backend);
CREATE TRIGGER transfer_delivery_receipt_immutable
    BEFORE UPDATE OR DELETE ON mission_control.transfer_delivery_receipt
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.transfer_delivery_receipt IS
    'mc.transfer_delivery_receipt.v1: one realization of a sealed plan by one receiver attempt '
    'on one realized backend; appended, never rewritten (redelivery appends).';

CREATE TABLE mission_control.transfer_member_delivery (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    delivery_receipt_id uuid NOT NULL,
    member_key text NOT NULL CHECK (member_key <> ''),
    source_ref text NOT NULL CHECK (source_ref <> ''),
    placement text NOT NULL CHECK (placement IN ('inline', 'file', 'handle')),
    path_or_handle text NOT NULL CHECK (path_or_handle <> ''),
    required_digest text NOT NULL CHECK (required_digest ~ '^sha256:[0-9a-f]{64}$'),
    observed_digest text CHECK (observed_digest IS NULL OR observed_digest ~ '^sha256:[0-9a-f]{64}$'),
    size_bytes bigint CHECK (size_bytes IS NULL OR size_bytes >= 0),
    probe text NOT NULL CHECK (probe IN (
        'backend_read', 'state_files_read', 'prompt', 'retrieval_capability')),
    readable boolean NOT NULL,
    access_ok boolean NOT NULL,
    access_ref text CHECK (access_ref IS NULL OR access_ref <> ''),
    code text CHECK (code IS NULL OR code ~ '^[A-Z][A-Z0-9_]*$'),
    digest_verified boolean GENERATED ALWAYS AS (
        observed_digest IS NOT NULL AND observed_digest = required_digest) STORED,
    created_at timestamptz NOT NULL,
    -- A file is readable only through the receiving backend's read (a sandbox read, or the
    -- text-only backend's files channel), never by storage readback.
    CHECK (placement <> 'file' OR probe IN ('backend_read', 'state_files_read')),
    CHECK (NOT readable OR placement = 'handle' OR observed_digest IS NOT NULL),
    PRIMARY KEY (installation_id, application_id, tenant_id, delivery_receipt_id, member_key),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, delivery_receipt_id)
        REFERENCES mission_control.transfer_delivery_receipt
            (installation_id, application_id, tenant_id, delivery_receipt_id)
);
CREATE INDEX transfer_member_delivery_source_idx ON mission_control.transfer_member_delivery
    (installation_id, application_id, tenant_id, source_ref)
    WHERE placement = 'file' AND readable AND access_ok;
CREATE TRIGGER transfer_member_delivery_immutable
    BEFORE UPDATE OR DELETE ON mission_control.transfer_member_delivery
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();

-- Members are written with their receipt, in the receipt's own transaction: nothing is ever
-- appended to an earlier receipt.
CREATE FUNCTION mission_control.transfer_member_delivery_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM mission_control.transfer_delivery_receipt AS receipt
        WHERE receipt.installation_id = NEW.installation_id
          AND receipt.application_id = NEW.application_id
          AND receipt.tenant_id = NEW.tenant_id
          AND receipt.delivery_receipt_id = NEW.delivery_receipt_id
          -- now() is the transaction start: only a receipt created in this transaction.
          AND receipt.created_at = now()
    ) THEN
        RAISE EXCEPTION 'transfer members are recorded only with their receipt'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.transfer_member_delivery_guard() FROM PUBLIC;
CREATE TRIGGER transfer_member_delivery_guard
    BEFORE INSERT ON mission_control.transfer_member_delivery
    FOR EACH ROW EXECUTE FUNCTION mission_control.transfer_member_delivery_guard();
COMMENT ON TABLE mission_control.transfer_member_delivery IS
    'One member of a transfer delivery receipt: placement, path or handle, required and observed '
    'digest, actual backend probe, readability and current access; append-only.';

DO $policies$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'transfer_plan', 'transfer_delivery_receipt', 'transfer_member_delivery'
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

REVOKE ALL ON mission_control.transfer_plan, mission_control.transfer_delivery_receipt,
    mission_control.transfer_member_delivery FROM PUBLIC;
GRANT SELECT, INSERT ON mission_control.transfer_plan, mission_control.transfer_delivery_receipt,
    mission_control.transfer_member_delivery
TO mission_control_runtime;
GRANT SELECT ON mission_control.transfer_plan, mission_control.transfer_delivery_receipt,
    mission_control.transfer_member_delivery
TO mission_control_readonly;
