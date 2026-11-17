-- Release 1.7.0 (Sprint OC WI-22 / OVE-183; OUTPUT-CONTRACTS §11, ADR-0004, ADR-0062): bounded
-- durable-transition reactions executed as ordinary admitted operations.
--
-- Three tables and the transactional outbox carry a reaction; nothing here schedules anything:
--
-- 1. `reaction_binding`: a compiled `mc.reaction_descriptor.v1` attached to one run, with a
--    generation that moves forward on every re-attach and detach (stale activations cancel).
-- 2. `reaction_transition`: a captured durable transition, one row per (kind, source). Capture
--    happens inside the transition's own transaction, by the triggers below on the output,
--    assessment, fulfillment, delivery and settlement tables, and only while the run has an
--    armed binding of that kind. The five kinds stay distinct; a provider stop is none of them.
--    A duplicate event is the same row (its id is md5 of kind and source). Its `cause_ref` is
--    host-derived from an authenticated operation identity, never from a caller-supplied
--    field: the submitting operation (output), the producer of the assessed subject
--    (assessment), the deepest reaction producer among the decided set's members
--    (fulfillment), the plan's receiver operation (delivery) and the settled operation
--    (settlement). A source row the capture cannot record is skipped with a visible
--    `reaction_capture_anomaly` row, so capture never fails the source write.
-- 3. `reaction_activation`: one logical reaction per (binding, transition), admitted or refused
--    by its limits (time, recursion, activations, rate, spend) or an unknown cause
--    (`CAUSE_UNKNOWN`, fail closed), with its causal parent, chain
--    root and depth. An admitted activation is inserted with its `mc.reaction.dispatch`
--    `outbox` intent in the same transaction; dispatch moves it (forward only) to `dispatched`
--    with the ordinary operation workflow it started, or `cancelled` when stale or fenced.
--
-- run_id is not a foreign key to mission_run (as in 0056-0058); no foreign key leaves the
-- component and every key carries the installation/application/tenant scope.

CREATE TABLE mission_control.reaction_binding (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    binding_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    reaction_id text NOT NULL CHECK (reaction_id ~ '^[a-z0-9][a-z0-9._:-]{0,127}$'),
    event_kind text NOT NULL CHECK (event_kind IN ('output.submitted', 'assessment.recorded',
        'fulfillment.decided', 'delivery.recorded', 'settlement.settled')),
    event_version integer NOT NULL CHECK (event_version >= 1),
    generation integer NOT NULL CHECK (generation >= 1),
    state text NOT NULL CHECK (state IN ('armed', 'detached')),
    descriptor jsonb NOT NULL CHECK (jsonb_typeof(descriptor) = 'object'
        AND descriptor->>'schema_version' = 'mc.reaction_descriptor.v1'),
    descriptor_digest text NOT NULL CHECK (descriptor_digest ~ '^sha256:[0-9a-f]{64}$'),
    semantic_input_binding_ref text CHECK (
        semantic_input_binding_ref IS NULL OR semantic_input_binding_ref <> ''),
    data_class text CHECK (data_class IS NULL OR data_class IN ('public', 'internal',
        'confidential', 'phi', 'secret')),
    armed_at timestamptz NOT NULL,
    deadline_at timestamptz CHECK (deadline_at IS NULL OR deadline_at > armed_at),
    version bigint NOT NULL CHECK (version >= 1),
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    updated_at timestamptz NOT NULL,
    -- The stored document is the descriptor: its keys agree with the columns.
    CHECK ((descriptor->>'reaction_id' = reaction_id
        AND descriptor->>'event' = event_kind
        AND (descriptor->'version')::integer = event_version) IS TRUE),
    UNIQUE (installation_id, application_id, tenant_id, binding_id),
    UNIQUE (installation_id, application_id, tenant_id, run_id, reaction_id),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE INDEX reaction_binding_armed_idx ON mission_control.reaction_binding
    (installation_id, application_id, tenant_id, run_id, event_kind) WHERE state = 'armed';
COMMENT ON TABLE mission_control.reaction_binding IS
    'mc.reaction_descriptor.v1 attached to one run; the generation moves forward on every '
    're-attach and detach, so activations admitted under another generation are stale.';

CREATE FUNCTION mission_control.reaction_binding_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'mission_control.reaction_binding rows are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (NEW.installation_id, NEW.application_id, NEW.tenant_id, NEW.binding_id, NEW.run_id,
        NEW.reaction_id, NEW.created_at, NEW.created_by_actor_ref)
       IS DISTINCT FROM
       (OLD.installation_id, OLD.application_id, OLD.tenant_id, OLD.binding_id, OLD.run_id,
        OLD.reaction_id, OLD.created_at, OLD.created_by_actor_ref)
       OR NEW.version <> OLD.version + 1
       OR NEW.generation <> OLD.generation + 1 THEN
        RAISE EXCEPTION 'a reaction binding changes only by moving to its next generation'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION mission_control.reaction_binding_guard() FROM PUBLIC;
CREATE TRIGGER reaction_binding_guard
    BEFORE UPDATE OR DELETE ON mission_control.reaction_binding
    FOR EACH ROW EXECUTE FUNCTION mission_control.reaction_binding_guard();

CREATE TABLE mission_control.reaction_transition (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    transition_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    event_kind text NOT NULL CHECK (event_kind IN ('output.submitted', 'assessment.recorded',
        'fulfillment.decided', 'delivery.recorded', 'settlement.settled')),
    event_version integer NOT NULL CHECK (event_version >= 1),
    source_ref text NOT NULL CHECK (source_ref <> '' AND length(source_ref) <= 512),
    cause_ref text CHECK (cause_ref IS NULL OR (cause_ref <> '' AND length(cause_ref) <= 1024)),
    execution_generation integer CHECK (execution_generation IS NULL OR execution_generation >= 1),
    facts jsonb NOT NULL CHECK (jsonb_typeof(facts) = 'object'
        AND NOT (facts ?| ARRAY['credential', 'token', 'authorization', 'secret', 'content'])),
    captured_at timestamptz NOT NULL,
    admitted_at timestamptz CHECK (admitted_at IS NULL OR admitted_at >= captured_at),
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    -- One row per (kind, source): a duplicate event can never be a second transition.
    CHECK (transition_id = md5('mc.durable_transition|' || event_kind || '|' || source_ref)::uuid),
    UNIQUE (installation_id, application_id, tenant_id, transition_id),
    UNIQUE (installation_id, application_id, tenant_id, event_kind, source_ref),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE INDEX reaction_transition_pending_idx ON mission_control.reaction_transition
    (installation_id, application_id, tenant_id, captured_at) WHERE admitted_at IS NULL;
COMMENT ON TABLE mission_control.reaction_transition IS
    'mc.durable_transition.v1: one captured output, assessment, fulfillment, delivery or '
    'settlement transition of a run with an armed reaction of that kind; admitted once.';

CREATE FUNCTION mission_control.reaction_transition_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'mission_control.reaction_transition rows are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.admitted_at IS NOT NULL OR NEW.admitted_at IS NULL
       OR (NEW.installation_id, NEW.application_id, NEW.tenant_id, NEW.transition_id, NEW.run_id,
           NEW.event_kind, NEW.event_version, NEW.source_ref, NEW.cause_ref,
           NEW.execution_generation, NEW.facts, NEW.captured_at, NEW.created_by_actor_ref)
          IS DISTINCT FROM
          (OLD.installation_id, OLD.application_id, OLD.tenant_id, OLD.transition_id, OLD.run_id,
           OLD.event_kind, OLD.event_version, OLD.source_ref, OLD.cause_ref,
           OLD.execution_generation, OLD.facts, OLD.captured_at, OLD.created_by_actor_ref) THEN
        RAISE EXCEPTION 'a captured transition is immutable and admitted once'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION mission_control.reaction_transition_guard() FROM PUBLIC;
CREATE TRIGGER reaction_transition_guard
    BEFORE UPDATE OR DELETE ON mission_control.reaction_transition
    FOR EACH ROW EXECUTE FUNCTION mission_control.reaction_transition_guard();

CREATE TABLE mission_control.reaction_activation (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    activation_id uuid PRIMARY KEY,
    binding_id uuid NOT NULL,
    binding_generation integer NOT NULL CHECK (binding_generation >= 1),
    run_id uuid NOT NULL,
    reaction_id text NOT NULL CHECK (reaction_id <> ''),
    transition_id uuid NOT NULL,
    event_kind text NOT NULL CHECK (event_kind IN ('output.submitted', 'assessment.recorded',
        'fulfillment.decided', 'delivery.recorded', 'settlement.settled')),
    depth integer NOT NULL CHECK (depth BETWEEN 1 AND 9),
    root_activation_id uuid NOT NULL,
    cause_activation_id uuid,
    run_generation integer CHECK (run_generation IS NULL OR run_generation >= 1),
    state text NOT NULL CHECK (state IN ('admitted', 'dispatched', 'cancelled', 'refused')),
    refusal_code text CHECK (refusal_code IS NULL OR refusal_code IN ('CAUSE_UNKNOWN',
        'TIME_LIMIT', 'RECURSION_LIMIT', 'ACTIVATION_LIMIT', 'RATE_LIMIT', 'SPEND_LIMIT')),
    cancel_reason text CHECK (cancel_reason IS NULL OR cancel_reason ~ '^[a-z][a-z0-9_]{0,63}$'),
    reserved_tokens bigint NOT NULL CHECK (reserved_tokens >= 0),
    operation_ref text NOT NULL,
    workflow_id text CHECK (workflow_id IS NULL OR (workflow_id <> ''
        AND length(workflow_id) <= 512)),
    admitted_at timestamptz NOT NULL,
    dispatched_at timestamptz,
    cancelled_at timestamptz,
    version bigint NOT NULL CHECK (version >= 1),
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    updated_at timestamptz NOT NULL,
    CHECK (operation_ref = 'reaction-' || activation_id::text),
    CHECK ((state = 'refused') = (refusal_code IS NOT NULL)),
    CHECK (state <> 'refused' OR reserved_tokens = 0),
    CHECK ((state = 'cancelled') = (cancel_reason IS NOT NULL AND cancelled_at IS NOT NULL)),
    CHECK ((state = 'dispatched') = (workflow_id IS NOT NULL AND dispatched_at IS NOT NULL)),
    -- Only a caused activation is deeper than one; an uncaused one roots its own chain.
    CHECK ((depth = 1) = (cause_activation_id IS NULL)),
    CHECK (cause_activation_id IS NOT NULL OR root_activation_id = activation_id),
    UNIQUE (installation_id, application_id, tenant_id, activation_id),
    -- One logical reaction per (binding, transition): a duplicate event maps here again.
    UNIQUE (installation_id, application_id, tenant_id, binding_id, transition_id),
    UNIQUE (installation_id, application_id, tenant_id, operation_ref),
    FOREIGN KEY (installation_id, application_id, tenant_id, binding_id)
        REFERENCES mission_control.reaction_binding (installation_id, application_id, tenant_id,
            binding_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, transition_id)
        REFERENCES mission_control.reaction_transition (installation_id, application_id,
            tenant_id, transition_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, cause_activation_id)
        REFERENCES mission_control.reaction_activation (installation_id, application_id,
            tenant_id, activation_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, root_activation_id)
        REFERENCES mission_control.reaction_activation (installation_id, application_id,
            tenant_id, activation_id)
);
CREATE INDEX reaction_activation_ledger_idx ON mission_control.reaction_activation
    (installation_id, application_id, tenant_id, binding_id, admitted_at);
CREATE INDEX reaction_activation_run_idx ON mission_control.reaction_activation
    (installation_id, application_id, tenant_id, run_id, admitted_at);
COMMENT ON TABLE mission_control.reaction_activation IS
    'One logical reaction per (binding, transition): admitted with its mc.reaction.dispatch '
    'outbox intent or refused by a limit; dispatch moves it forward to dispatched or cancelled.';

CREATE FUNCTION mission_control.reaction_activation_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'mission_control.reaction_activation rows are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (NEW.installation_id, NEW.application_id, NEW.tenant_id, NEW.activation_id,
        NEW.binding_id, NEW.binding_generation, NEW.run_id, NEW.reaction_id, NEW.transition_id,
        NEW.event_kind, NEW.depth, NEW.root_activation_id, NEW.cause_activation_id,
        NEW.run_generation, NEW.refusal_code, NEW.reserved_tokens, NEW.operation_ref,
        NEW.admitted_at, NEW.created_at, NEW.created_by_actor_ref)
       IS DISTINCT FROM
       (OLD.installation_id, OLD.application_id, OLD.tenant_id, OLD.activation_id,
        OLD.binding_id, OLD.binding_generation, OLD.run_id, OLD.reaction_id, OLD.transition_id,
        OLD.event_kind, OLD.depth, OLD.root_activation_id, OLD.cause_activation_id,
        OLD.run_generation, OLD.refusal_code, OLD.reserved_tokens, OLD.operation_ref,
        OLD.admitted_at, OLD.created_at, OLD.created_by_actor_ref)
       OR NEW.version <> OLD.version + 1
       OR NOT (OLD.state = 'admitted' AND NEW.state IN ('dispatched', 'cancelled')) THEN
        RAISE EXCEPTION 'a reaction activation only moves from admitted to dispatched or cancelled'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION mission_control.reaction_activation_guard() FROM PUBLIC;
CREATE TRIGGER reaction_activation_guard
    BEFORE UPDATE OR DELETE ON mission_control.reaction_activation
    FOR EACH ROW EXECUTE FUNCTION mission_control.reaction_activation_guard();

-- ---------------------------------------------------------------- truncation

CREATE FUNCTION mission_control.reaction_truncate_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    RAISE EXCEPTION 'mission_control.% is never truncated', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$;
REVOKE ALL ON FUNCTION mission_control.reaction_truncate_guard() FROM PUBLIC;

-- ---------------------------------------------------------------- capture

-- A transition of an armed run the capture skipped (a guarded skip, never an exception block):
-- the source write commits and the skipped transition and its reason stay visible.
CREATE TABLE mission_control.reaction_capture_anomaly (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    anomaly_id uuid PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    run_id uuid,
    event_kind text NOT NULL CHECK (event_kind <> '' AND length(event_kind) <= 64),
    source_ref text NOT NULL CHECK (length(source_ref) <= 512),
    reason text NOT NULL CHECK (reason IN ('source_invalid', 'facts_invalid')),
    recorded_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
COMMENT ON TABLE mission_control.reaction_capture_anomaly IS
    'A source transition of an armed run the reaction capture could not record (guarded skip): '
    'the source write still commits; the skipped transition and its reason stay visible.';
CREATE TRIGGER reaction_capture_anomaly_immutable
    BEFORE UPDATE OR DELETE ON mission_control.reaction_capture_anomaly
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();

-- Whether a run has an armed binding of a kind: the first question of every capture.
CREATE FUNCTION mission_control.reaction_armed(
    p_installation_id uuid, p_application_id text, p_tenant_id uuid, p_run_id uuid, p_kind text
) RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT p_run_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM mission_control.reaction_binding AS binding
        WHERE binding.installation_id = p_installation_id
          AND binding.application_id = p_application_id
          AND binding.tenant_id = p_tenant_id
          AND binding.run_id = p_run_id
          AND binding.event_kind = p_kind
          AND binding.state = 'armed')
$$;

-- The authenticated operation that produced an output revision: its submission's operation,
-- which the host takes from the invocation's authenticated origin.
CREATE FUNCTION mission_control.reaction_revision_cause(
    p_installation_id uuid, p_application_id text, p_tenant_id uuid, p_revision uuid
) RETURNS text
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT submission.operation_ref
      FROM mission_control.output_revision AS revision
      JOIN mission_control.output_submission AS submission
        ON submission.installation_id = revision.installation_id
       AND submission.application_id = revision.application_id
       AND submission.tenant_id = revision.tenant_id
       AND submission.submission_id = revision.submission_id
     WHERE revision.installation_id = p_installation_id
       AND revision.application_id = p_application_id
       AND revision.tenant_id = p_tenant_id
       AND revision.output_revision_id = p_revision
$$;

-- The cause of a decision over an output set: the producing operation of the member made by
-- the deepest reaction activation (a chain through a set keeps its depth), else any member's
-- producing operation (a producer that is no reaction roots no chain).
CREATE FUNCTION mission_control.reaction_set_cause(
    p_installation_id uuid, p_application_id text, p_tenant_id uuid, p_set uuid
) RETURNS text
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT submission.operation_ref
      FROM mission_control.output_set_member AS member
      JOIN mission_control.output_revision AS revision
        ON revision.installation_id = member.installation_id
       AND revision.application_id = member.application_id
       AND revision.tenant_id = member.tenant_id
       AND revision.output_revision_id = member.output_revision_id
      JOIN mission_control.output_submission AS submission
        ON submission.installation_id = revision.installation_id
       AND submission.application_id = revision.application_id
       AND submission.tenant_id = revision.tenant_id
       AND submission.submission_id = revision.submission_id
      LEFT JOIN mission_control.reaction_activation AS activation
        ON activation.installation_id = submission.installation_id
       AND activation.application_id = submission.application_id
       AND activation.tenant_id = submission.tenant_id
       AND activation.operation_ref = submission.operation_ref
     WHERE member.installation_id = p_installation_id
       AND member.application_id = p_application_id
       AND member.tenant_id = p_tenant_id
       AND member.output_set_id = p_set
     ORDER BY activation.depth DESC NULLS LAST, submission.operation_ref
     LIMIT 1
$$;

-- Records one transition of an armed run. Runs as the invoking role inside the transition's
-- own transaction and row-level scope; a duplicate is a no-op. Every constraint of
-- reaction_transition a source row could miss is checked here first: such a row is skipped
-- with a reaction_capture_anomaly row, so the capture never fails the source write and
-- swallows nothing.
CREATE FUNCTION mission_control.capture_reaction_transition(
    p_installation_id uuid, p_application_id text, p_tenant_id uuid, p_run_id uuid,
    p_kind text, p_source_ref text, p_cause_ref text, p_generation integer, p_facts jsonb
) RETURNS void
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE
    v_actor text := coalesce(nullif(current_setting('mc.actor_ref', true), ''),
        'mission-control:reaction-capture');
    v_reason text;
BEGIN
    IF p_source_ref IS NULL OR p_source_ref = '' OR length(p_source_ref) > 512 THEN
        v_reason := 'source_invalid';
    ELSIF p_facts IS NULL OR jsonb_typeof(p_facts) <> 'object'
          OR p_facts ?| ARRAY['credential', 'token', 'authorization', 'secret', 'content'] THEN
        v_reason := 'facts_invalid';
    END IF;
    IF v_reason IS NOT NULL THEN
        INSERT INTO mission_control.reaction_capture_anomaly (
            installation_id, application_id, tenant_id, run_id, event_kind, source_ref, reason,
            recorded_at, created_by_actor_ref
        ) VALUES (
            p_installation_id, p_application_id, p_tenant_id, p_run_id, p_kind,
            left(coalesce(p_source_ref, ''), 512), v_reason, clock_timestamp(), v_actor
        );
        RETURN;
    END IF;
    INSERT INTO mission_control.reaction_transition (
        installation_id, application_id, tenant_id, transition_id, run_id, event_kind,
        event_version, source_ref, cause_ref, execution_generation, facts, captured_at,
        admitted_at, created_by_actor_ref
    ) VALUES (
        p_installation_id, p_application_id, p_tenant_id,
        md5('mc.durable_transition|' || p_kind || '|' || p_source_ref)::uuid, p_run_id, p_kind,
        1, p_source_ref, nullif(left(p_cause_ref, 1024), ''),
        CASE WHEN p_generation >= 1 THEN p_generation END, p_facts,
        clock_timestamp(), NULL, v_actor
    ) ON CONFLICT DO NOTHING;
END;
$$;

CREATE FUNCTION mission_control.capture_output_submitted() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE
    v_operation text;
    v_generation integer;
BEGIN
    IF NOT mission_control.reaction_armed(NEW.installation_id, NEW.application_id,
            NEW.tenant_id, NEW.run_id, 'output.submitted') THEN
        RETURN NULL;
    END IF;
    SELECT submission.operation_ref, submission.execution_generation
      INTO v_operation, v_generation
      FROM mission_control.output_submission AS submission
     WHERE submission.installation_id = NEW.installation_id
       AND submission.application_id = NEW.application_id
       AND submission.tenant_id = NEW.tenant_id
       AND submission.submission_id = NEW.submission_id;
    PERFORM mission_control.capture_reaction_transition(
        NEW.installation_id, NEW.application_id, NEW.tenant_id, NEW.run_id, 'output.submitted',
        NEW.output_revision_id::text, v_operation, v_generation,
        jsonb_build_object('obligation_key', NEW.obligation_key,
            'deliverable_id', NEW.deliverable_id, 'revision', NEW.revision, 'form', NEW.form,
            'content_digest', NEW.content_digest));
    RETURN NULL;
END;
$$;

-- The assessor's origin arrives with the assessment, so it is never a cause: the cause is the
-- authenticated producer of the assessed subject.
CREATE FUNCTION mission_control.capture_assessment_recorded() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE
    v_cause text;
BEGIN
    IF NOT mission_control.reaction_armed(NEW.installation_id, NEW.application_id,
            NEW.tenant_id, NEW.run_id, 'assessment.recorded') THEN
        RETURN NULL;
    END IF;
    IF NEW.output_revision_id IS NOT NULL THEN
        v_cause := mission_control.reaction_revision_cause(NEW.installation_id,
            NEW.application_id, NEW.tenant_id, NEW.output_revision_id);
    ELSIF NEW.output_set_id IS NOT NULL THEN
        v_cause := mission_control.reaction_set_cause(NEW.installation_id,
            NEW.application_id, NEW.tenant_id, NEW.output_set_id);
    END IF;
    PERFORM mission_control.capture_reaction_transition(
        NEW.installation_id, NEW.application_id, NEW.tenant_id, NEW.run_id,
        'assessment.recorded', NEW.assessment_id::text, v_cause, NULL,
        jsonb_build_object('subject_kind', NEW.subject_kind,
            'subject_ref', left(NEW.subject_ref, 512), 'result', NEW.result,
            'method_pin', left(NEW.method_pin, 512), 'policy_pin', left(NEW.policy_pin, 512)));
    RETURN NULL;
END;
$$;

-- A fulfillment is a host decision over a pinned set: its cause is the set's producers.
CREATE FUNCTION mission_control.capture_fulfillment_decided() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF NOT mission_control.reaction_armed(NEW.installation_id, NEW.application_id,
            NEW.tenant_id, NEW.run_id, 'fulfillment.decided') THEN
        RETURN NULL;
    END IF;
    PERFORM mission_control.capture_reaction_transition(
        NEW.installation_id, NEW.application_id, NEW.tenant_id, NEW.run_id,
        'fulfillment.decided', NEW.fulfillment_id::text,
        mission_control.reaction_set_cause(NEW.installation_id, NEW.application_id,
            NEW.tenant_id, NEW.output_set_id), NULL,
        jsonb_build_object('obligation_key', NEW.obligation_key,
            'obligation_revision', NEW.obligation_revision, 'enforcement', NEW.enforcement,
            'disposition', NEW.disposition, 'distinct_count', NEW.distinct_count));
    RETURN NULL;
END;
$$;

-- The run is the plan's, so the plan is read first and the armed check follows at once.
CREATE FUNCTION mission_control.capture_delivery_recorded() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE
    v_run uuid;
    v_operation text;
BEGIN
    SELECT plan.run_id, plan.receiver_operation_ref INTO v_run, v_operation
      FROM mission_control.transfer_plan AS plan
     WHERE plan.installation_id = NEW.installation_id
       AND plan.application_id = NEW.application_id
       AND plan.tenant_id = NEW.tenant_id
       AND plan.transfer_plan_id = NEW.transfer_plan_id;
    IF NOT mission_control.reaction_armed(NEW.installation_id, NEW.application_id,
            NEW.tenant_id, v_run, 'delivery.recorded') THEN
        RETURN NULL;
    END IF;
    PERFORM mission_control.capture_reaction_transition(
        NEW.installation_id, NEW.application_id, NEW.tenant_id, v_run, 'delivery.recorded',
        NEW.delivery_receipt_id::text, v_operation, NEW.execution_generation,
        jsonb_build_object('transfer_plan_id', NEW.transfer_plan_id::text,
            'result', NEW.result, 'operation_attempt', NEW.operation_attempt,
            'receiver_invocation_ref', left(NEW.receiver_invocation_ref, 512)));
    RETURN NULL;
END;
$$;

-- A saved result is a settlement transition only when it becomes `settled`, once.
CREATE FUNCTION mission_control.capture_settlement_settled() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF NEW.settlement <> 'settled'
       OR (TG_OP = 'UPDATE' AND OLD.settlement IS NOT DISTINCT FROM 'settled')
       OR NOT mission_control.reaction_armed(NEW.installation_id, NEW.application_id,
            NEW.tenant_id, NEW.run_id, 'settlement.settled') THEN
        RETURN NULL;
    END IF;
    PERFORM mission_control.capture_reaction_transition(
        NEW.installation_id, NEW.application_id, NEW.tenant_id, NEW.run_id,
        'settlement.settled', NEW.settlement_id::text, NEW.operation_ref,
        NEW.execution_generation,
        jsonb_build_object('binding_id', left(NEW.binding_id, 512), 'unit_key',
            left(NEW.unit_key, 512), 'execution_outcome', NEW.execution_outcome));
    RETURN NULL;
END;
$$;

-- Only mission_control_runtime writes the five source tables (0056-0058 grant INSERT/UPDATE
-- on them to no other role), so only it executes what the triggers call. A trigger function
-- needs no EXECUTE when it fires; the functions it calls do.
DO $capture$
DECLARE
    signature text;
BEGIN
    FOREACH signature IN ARRAY ARRAY[
        'capture_output_submitted()', 'capture_assessment_recorded()',
        'capture_fulfillment_decided()', 'capture_delivery_recorded()',
        'capture_settlement_settled()',
        'reaction_armed(uuid, text, uuid, uuid, text)',
        'reaction_revision_cause(uuid, text, uuid, uuid)',
        'reaction_set_cause(uuid, text, uuid, uuid)',
        'capture_reaction_transition(uuid, text, uuid, uuid, text, text, text, integer, jsonb)'
    ] LOOP
        EXECUTE 'REVOKE ALL ON FUNCTION mission_control.' || signature || ' FROM PUBLIC';
    END LOOP;
END
$capture$;
GRANT EXECUTE ON FUNCTION
    mission_control.reaction_armed(uuid, text, uuid, uuid, text),
    mission_control.reaction_revision_cause(uuid, text, uuid, uuid),
    mission_control.reaction_set_cause(uuid, text, uuid, uuid),
    mission_control.capture_reaction_transition(
        uuid, text, uuid, uuid, text, text, text, integer, jsonb)
TO mission_control_runtime;

CREATE TRIGGER output_revision_reaction_capture
    AFTER INSERT ON mission_control.output_revision
    FOR EACH ROW EXECUTE FUNCTION mission_control.capture_output_submitted();
CREATE TRIGGER output_assessment_reaction_capture
    AFTER INSERT ON mission_control.output_assessment
    FOR EACH ROW EXECUTE FUNCTION mission_control.capture_assessment_recorded();
CREATE TRIGGER obligation_fulfillment_reaction_capture
    AFTER INSERT ON mission_control.obligation_fulfillment
    FOR EACH ROW EXECUTE FUNCTION mission_control.capture_fulfillment_decided();
CREATE TRIGGER transfer_delivery_receipt_reaction_capture
    AFTER INSERT ON mission_control.transfer_delivery_receipt
    FOR EACH ROW EXECUTE FUNCTION mission_control.capture_delivery_recorded();
CREATE TRIGGER invocation_settlement_reaction_capture
    AFTER INSERT OR UPDATE OF settlement ON mission_control.invocation_settlement
    FOR EACH ROW EXECUTE FUNCTION mission_control.capture_settlement_settled();

DO $truncate$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'reaction_binding', 'reaction_transition', 'reaction_activation',
        'reaction_capture_anomaly'
    ] LOOP
        EXECUTE pg_catalog.format(
            'CREATE TRIGGER %I BEFORE TRUNCATE ON mission_control.%I '
            'FOR EACH STATEMENT EXECUTE FUNCTION mission_control.reaction_truncate_guard()',
            table_name || '_no_truncate', table_name);
    END LOOP;
END
$truncate$;

-- ---------------------------------------------------------------- scope and grants

DO $policies$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'reaction_binding', 'reaction_transition', 'reaction_activation',
        'reaction_capture_anomaly'
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

REVOKE ALL ON mission_control.reaction_binding, mission_control.reaction_transition,
    mission_control.reaction_activation, mission_control.reaction_capture_anomaly FROM PUBLIC;
GRANT SELECT, INSERT ON mission_control.reaction_binding, mission_control.reaction_transition,
    mission_control.reaction_activation, mission_control.reaction_capture_anomaly
TO mission_control_runtime;
GRANT UPDATE (event_kind, event_version, generation, state, descriptor, descriptor_digest,
    semantic_input_binding_ref, data_class, armed_at, deadline_at, version, updated_at)
ON mission_control.reaction_binding TO mission_control_runtime;
GRANT UPDATE (admitted_at) ON mission_control.reaction_transition TO mission_control_runtime;
GRANT UPDATE (state, cancel_reason, workflow_id, dispatched_at, cancelled_at, version, updated_at)
ON mission_control.reaction_activation TO mission_control_runtime;
GRANT SELECT ON mission_control.reaction_binding, mission_control.reaction_transition,
    mission_control.reaction_activation, mission_control.reaction_capture_anomaly
TO mission_control_readonly;
