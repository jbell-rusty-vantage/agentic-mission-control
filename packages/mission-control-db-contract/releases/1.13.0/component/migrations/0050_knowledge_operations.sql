-- Release 1.5.0 (Sprint V SV-13, design M05 and §5): the host-side knowledge operation journal.
-- Mission Control journals every knowledge operation it dispatches to an application binding
-- before the transmission, then settles it from the binding's receipt. The journal records
-- coordinates and digests only: no credential bytes, no native payload, no verification
-- truth and no foreign key into any application store. States:
--   prepared -> dispatched -> applied | noop | partial | rejected | uncertain
--   prepared -> rejected (refused before transmission); uncertain -> dispatched (retry with
--   identical native bytes and a fresh credential) or a terminal state (receipt lookup).
-- `effect_key` is host-minted, opaque and unique per installation, application and tenant;
-- the same key with a different `bound_effect_digest` is refused (EFFECT_CONFLICT, SQLSTATE
-- MCE01). Every state change appends one immutable `knowledge_operation_transition` row.
CREATE TABLE mission_control.knowledge_operation_journal (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    knowledge_operation_id uuid PRIMARY KEY,
    effect_key text NOT NULL CHECK (effect_key <> '' AND length(effect_key) <= 512),
    semantic_payload_digest text NOT NULL CHECK (semantic_payload_digest ~ '^sha256:[0-9a-f]{64}$'),
    bound_effect_digest text NOT NULL CHECK (bound_effect_digest ~ '^sha256:[0-9a-f]{64}$'),
    originating_origin jsonb NOT NULL CHECK (jsonb_typeof(originating_origin) = 'object'
        AND NOT (originating_origin ?| ARRAY['credential', 'token', 'authorization', 'secret'])),
    current_caller_origin jsonb NOT NULL CHECK (jsonb_typeof(current_caller_origin) = 'object'
        AND NOT (current_caller_origin ?| ARRAY['credential', 'token', 'authorization', 'secret'])),
    mission_id uuid NOT NULL,
    run_id uuid NOT NULL,
    activation_id uuid,
    operation_ref text NOT NULL CHECK (operation_ref <> ''),
    operation_attempt integer NOT NULL CHECK (operation_attempt >= 1),
    execution_generation integer NOT NULL CHECK (execution_generation >= 1),
    unit_key text CHECK (unit_key IS NULL OR unit_key ~ '^bl-unit-v1:[0-9a-f]{64}$'),
    lane_profile text CHECK (lane_profile IS NULL OR lane_profile <> ''),
    capability_pin text NOT NULL CHECK (capability_pin <> ''),
    binding_id text NOT NULL CHECK (binding_id <> ''),
    protocol_version text CHECK (protocol_version IS NULL OR protocol_version <> ''),
    operation_id text CHECK (operation_id IS NULL OR operation_id <> ''),
    dispatch_id uuid,
    envelope_digest text CHECK (envelope_digest IS NULL OR envelope_digest ~ '^sha256:[0-9a-f]{64}$'),
    state text NOT NULL
        CHECK (state IN ('prepared', 'dispatched', 'applied', 'noop', 'partial', 'rejected', 'uncertain')),
    reconciled boolean NOT NULL DEFAULT false,
    terminal_receipt_ref text CHECK (terminal_receipt_ref IS NULL OR terminal_receipt_ref <> ''),
    receipt_digest text CHECK (receipt_digest IS NULL OR receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
    refusal_code text CHECK (refusal_code IS NULL OR refusal_code ~ '^[A-Z][A-Z0-9_]*$'),
    remote_retry_after timestamptz,
    remote_revision text CHECK (remote_revision IS NULL OR remote_revision <> ''),
    version bigint NOT NULL CHECK (version >= 1),
    prepared_at timestamptz NOT NULL,
    dispatched_at timestamptz,
    settled_at timestamptz,
    updated_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    -- A transmitted operation names its dispatch, envelope and protocol.
    CHECK (state IN ('prepared', 'rejected')
        OR (dispatch_id IS NOT NULL AND envelope_digest IS NOT NULL AND protocol_version IS NOT NULL
            AND dispatched_at IS NOT NULL)),
    -- An effect that happened is proven by a receipt; a refusal names its code.
    CHECK (state NOT IN ('applied', 'noop', 'partial') OR terminal_receipt_ref IS NOT NULL),
    CHECK (state <> 'rejected' OR refusal_code IS NOT NULL OR terminal_receipt_ref IS NOT NULL),
    CHECK ((state IN ('applied', 'noop', 'partial', 'rejected')) = (settled_at IS NOT NULL)),
    CHECK (NOT reconciled OR state <> 'prepared'),
    UNIQUE (installation_id, application_id, tenant_id, knowledge_operation_id),
    UNIQUE (installation_id, application_id, tenant_id, effect_key),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE INDEX knowledge_operation_journal_run_idx ON mission_control.knowledge_operation_journal
    (installation_id, application_id, tenant_id, run_id, operation_ref, operation_attempt);
CREATE INDEX knowledge_operation_journal_open_idx ON mission_control.knowledge_operation_journal
    (installation_id, application_id, tenant_id, state, updated_at)
    WHERE state IN ('prepared', 'dispatched', 'uncertain');
COMMENT ON TABLE mission_control.knowledge_operation_journal IS
    'mc.knowledge_operation.v1: host journal of one logical knowledge effect per scoped effect_key; '
    'coordinates and digests only, never credentials, payloads or verification truth.';
COMMENT ON COLUMN mission_control.knowledge_operation_journal.operation_id IS
    'The remote operation handle returned by the application binding; NULL until dispatched.';
COMMENT ON COLUMN mission_control.knowledge_operation_journal.operation_ref IS
    'The Mission Control semantic operation of the invoking attempt (not the remote handle).';

CREATE TABLE mission_control.knowledge_operation_transition (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    knowledge_operation_id uuid NOT NULL,
    transition_version bigint NOT NULL CHECK (transition_version >= 1),
    from_state text
        CHECK (from_state IN ('prepared', 'dispatched', 'applied', 'noop', 'partial', 'rejected', 'uncertain')),
    to_state text NOT NULL
        CHECK (to_state IN ('prepared', 'dispatched', 'applied', 'noop', 'partial', 'rejected', 'uncertain')),
    reconciled boolean NOT NULL,
    dispatch_id uuid,
    envelope_digest text CHECK (envelope_digest IS NULL OR envelope_digest ~ '^sha256:[0-9a-f]{64}$'),
    current_caller_origin jsonb NOT NULL CHECK (jsonb_typeof(current_caller_origin) = 'object'),
    terminal_receipt_ref text,
    refusal_code text,
    recorded_at timestamptz NOT NULL,
    recorded_by_actor_ref text NOT NULL CHECK (recorded_by_actor_ref <> ''),
    PRIMARY KEY (installation_id, application_id, tenant_id, knowledge_operation_id, transition_version),
    FOREIGN KEY (installation_id, application_id, tenant_id, knowledge_operation_id)
        REFERENCES mission_control.knowledge_operation_journal
            (installation_id, application_id, tenant_id, knowledge_operation_id)
);
CREATE TRIGGER knowledge_operation_transition_immutable
    BEFORE UPDATE OR DELETE ON mission_control.knowledge_operation_transition
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.knowledge_operation_transition IS
    'Append-only history of knowledge_operation_journal: one row per journal version.';

-- Guard: identity and digests never change; the originating origin is frozen once the
-- operation leaves `prepared`; states advance only along the legal edges; versions advance
-- by one; nothing deletes a journal row.
CREATE FUNCTION mission_control.knowledge_operation_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'knowledge_operation_journal rows are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.installation_id <> OLD.installation_id OR NEW.application_id <> OLD.application_id
       OR NEW.tenant_id <> OLD.tenant_id OR NEW.knowledge_operation_id <> OLD.knowledge_operation_id
       OR NEW.effect_key <> OLD.effect_key
       OR NEW.semantic_payload_digest <> OLD.semantic_payload_digest
       OR NEW.bound_effect_digest <> OLD.bound_effect_digest
       OR NEW.mission_id <> OLD.mission_id OR NEW.run_id <> OLD.run_id
       OR NEW.activation_id IS DISTINCT FROM OLD.activation_id
       OR NEW.operation_ref <> OLD.operation_ref OR NEW.operation_attempt <> OLD.operation_attempt
       OR NEW.execution_generation <> OLD.execution_generation
       OR NEW.unit_key IS DISTINCT FROM OLD.unit_key
       OR NEW.capability_pin <> OLD.capability_pin OR NEW.binding_id <> OLD.binding_id
       OR NEW.prepared_at <> OLD.prepared_at OR NEW.created_at <> OLD.created_at
       OR NEW.created_by_actor_ref <> OLD.created_by_actor_ref THEN
        RAISE EXCEPTION 'knowledge_operation_journal identity is fixed'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.state <> 'prepared' AND NEW.originating_origin IS DISTINCT FROM OLD.originating_origin THEN
        RAISE EXCEPTION 'knowledge_operation_journal originating origin is frozen after dispatch'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.operation_id IS NOT NULL AND NEW.operation_id IS DISTINCT FROM OLD.operation_id THEN
        RAISE EXCEPTION 'knowledge_operation_journal remote operation handle is fixed once known'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.state <> OLD.state AND NOT (
        (OLD.state = 'prepared' AND NEW.state IN ('dispatched', 'rejected'))
        OR (OLD.state = 'dispatched'
            AND NEW.state IN ('applied', 'noop', 'partial', 'rejected', 'uncertain'))
        OR (OLD.state = 'uncertain'
            AND NEW.state IN ('dispatched', 'applied', 'noop', 'partial', 'rejected'))
    ) THEN
        RAISE EXCEPTION 'illegal knowledge operation transition % -> %', OLD.state, NEW.state
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.state IN ('applied', 'noop', 'partial', 'rejected') AND (
        NEW.terminal_receipt_ref IS DISTINCT FROM OLD.terminal_receipt_ref
        AND OLD.terminal_receipt_ref IS NOT NULL
        OR NEW.receipt_digest IS DISTINCT FROM OLD.receipt_digest AND OLD.receipt_digest IS NOT NULL
        OR NEW.settled_at <> OLD.settled_at
        OR (OLD.reconciled AND NOT NEW.reconciled)
    ) THEN
        RAISE EXCEPTION 'a settled knowledge operation keeps its receipt'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'knowledge_operation_journal version must advance by one'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'knowledge_operation_journal updated_at never moves back'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.knowledge_operation_guard() FROM PUBLIC;
CREATE TRIGGER knowledge_operation_guard
    BEFORE UPDATE OR DELETE ON mission_control.knowledge_operation_journal
    FOR EACH ROW EXECUTE FUNCTION mission_control.knowledge_operation_guard();

-- Same scoped effect key, different bound effect: refused before the row exists.
CREATE FUNCTION mission_control.knowledge_operation_effect_conflict() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $conflict$
BEGIN
    IF NEW.version <> 1 OR NEW.state <> 'prepared' THEN
        RAISE EXCEPTION 'a knowledge operation is journalled as prepared at version 1'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF EXISTS (
        SELECT 1 FROM mission_control.knowledge_operation_journal AS existing
        WHERE existing.installation_id = NEW.installation_id
          AND existing.application_id = NEW.application_id
          AND existing.tenant_id = NEW.tenant_id
          AND existing.effect_key = NEW.effect_key
          AND existing.bound_effect_digest <> NEW.bound_effect_digest
    ) THEN
        RAISE EXCEPTION 'EFFECT_CONFLICT %', NEW.effect_key USING ERRCODE = 'MCE01';
    END IF;
    RETURN NEW;
END
$conflict$;
REVOKE ALL ON FUNCTION mission_control.knowledge_operation_effect_conflict() FROM PUBLIC;
CREATE TRIGGER knowledge_operation_effect_conflict
    BEFORE INSERT ON mission_control.knowledge_operation_journal
    FOR EACH ROW EXECUTE FUNCTION mission_control.knowledge_operation_effect_conflict();

-- Every journal version appends its transition (the first one from NULL).
CREATE FUNCTION mission_control.knowledge_operation_append_transition() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $append$
BEGIN
    INSERT INTO mission_control.knowledge_operation_transition (
        installation_id, application_id, tenant_id, knowledge_operation_id, transition_version,
        from_state, to_state, reconciled, dispatch_id, envelope_digest, current_caller_origin,
        terminal_receipt_ref, refusal_code, recorded_at, recorded_by_actor_ref)
    VALUES (
        NEW.installation_id, NEW.application_id, NEW.tenant_id, NEW.knowledge_operation_id,
        NEW.version, CASE WHEN TG_OP = 'UPDATE' THEN OLD.state END, NEW.state, NEW.reconciled,
        NEW.dispatch_id, NEW.envelope_digest, NEW.current_caller_origin,
        NEW.terminal_receipt_ref, NEW.refusal_code, NEW.updated_at,
        COALESCE(mission_control.ctx_actor_ref(), NEW.created_by_actor_ref));
    RETURN NULL;
END
$append$;
REVOKE ALL ON FUNCTION mission_control.knowledge_operation_append_transition() FROM PUBLIC;
CREATE TRIGGER knowledge_operation_append_transition
    AFTER INSERT OR UPDATE ON mission_control.knowledge_operation_journal
    FOR EACH ROW EXECUTE FUNCTION mission_control.knowledge_operation_append_transition();

-- Race-safe admission: returns the journal row for the scoped key, inserting it when new; a
-- concurrent or earlier row with a different bound effect raises EFFECT_CONFLICT (MCE01).
-- Invoker rights: row security and the caller's grants apply unchanged.
CREATE FUNCTION mission_control.admit_knowledge_operation(candidate jsonb)
RETURNS mission_control.knowledge_operation_journal
LANGUAGE plpgsql SET search_path = pg_catalog AS $admit$
DECLARE
    proposed mission_control.knowledge_operation_journal;
    admitted mission_control.knowledge_operation_journal;
BEGIN
    proposed := jsonb_populate_record(NULL::mission_control.knowledge_operation_journal, candidate);
    INSERT INTO mission_control.knowledge_operation_journal
    SELECT proposed.*
    ON CONFLICT (installation_id, application_id, tenant_id, effect_key) DO NOTHING
    RETURNING * INTO admitted;
    IF FOUND THEN
        RETURN admitted;
    END IF;
    SELECT * INTO admitted FROM mission_control.knowledge_operation_journal AS existing
    WHERE existing.installation_id = proposed.installation_id
      AND existing.application_id = proposed.application_id
      AND existing.tenant_id = proposed.tenant_id
      AND existing.effect_key = proposed.effect_key;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'knowledge operation % is not visible in this scope', proposed.effect_key
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF admitted.bound_effect_digest <> proposed.bound_effect_digest THEN
        RAISE EXCEPTION 'EFFECT_CONFLICT %', proposed.effect_key USING ERRCODE = 'MCE01';
    END IF;
    RETURN admitted;
END
$admit$;
REVOKE ALL ON FUNCTION mission_control.admit_knowledge_operation(jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mission_control.admit_knowledge_operation(jsonb)
TO mission_control_runtime;

DO $policies$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['knowledge_operation_journal', 'knowledge_operation_transition'] LOOP
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

REVOKE ALL ON mission_control.knowledge_operation_journal,
    mission_control.knowledge_operation_transition FROM PUBLIC;
-- The runtime prepares, dispatches and settles; it never rewrites identity (guard) and only
-- appends history (the transition trigger runs with the runtime's rights).
GRANT SELECT, INSERT ON mission_control.knowledge_operation_journal TO mission_control_runtime;
GRANT UPDATE (originating_origin, current_caller_origin, protocol_version, operation_id,
    dispatch_id, envelope_digest, state, reconciled, terminal_receipt_ref, receipt_digest,
    refusal_code, remote_retry_after, remote_revision, version, dispatched_at, settled_at,
    updated_at)
ON mission_control.knowledge_operation_journal TO mission_control_runtime;
GRANT SELECT, INSERT ON mission_control.knowledge_operation_transition TO mission_control_runtime;
GRANT SELECT ON mission_control.knowledge_operation_journal,
    mission_control.knowledge_operation_transition
TO mission_control_readonly;
