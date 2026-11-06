-- Release 1.6.0 (Sprint V SV-16 / SV-15 reopened, design §4, §8, §9; Checkpoint A schema-fit
-- rows for 0050, 0053 and 0054). Four changes, all additive to stored data:
--
-- 1. `knowledge_operation_handle`: the durable remote handle of every knowledge operation the
--    binding answers with a handle (`report.assess`, `report.derive`, `verify.claims`,
--    `knowledge.read`, and an effect's `knowledge.apply`/`report.register` handle), with the
--    K01 status (queued, running, waiting_review, cancelling and the six terminal states), the
--    remote revision (monotonic: a stale poll never regresses a handle), the first idempotent
--    `cancel_request_id`, the pending review, result and unresolved effects. A restart finds an
--    invocation's open handles here, so a stop during review still reaches the binding.
-- 2. `output_submission` gains the independent assessment handoff: `assessing` (pending ->
--    assessing -> assessed | held | rejected), `assessment_operation_id`, `assessment_binding`
--    and `assessment_requested_at`, fixed once the assessment starts.
-- 3. `invocation_finalization.outcome_basis`: `submission_coverage` (a submission exists for
--    every obligation), `assessed` (every assessment reached a service verdict) or
--    `attempt_failed` (the attempt failed; its outstanding effects were reconciled first).
-- 4. `context_delivery_receipt` gains `attempt` (1, or 2 for the one repair) and a generated
--    `outcome_code`; receipts are recorded only while their plan is delivering, a repair follows
--    a failed first attempt, a plan becomes `delivered` only when every required item has a
--    delivered, digest-verified, readable, in-budget receipt, and `blocked` only after a failed
--    repair attempt.
-- 5. `knowledge_operation_journal.recovery_authority_ref` (and on each transition): the host
--    recovery grant under which a later attempt re-dispatched an uncertain effect (effect
--    scope, the exact effect key and bound digest), recorded with the dispatch it authorized.
-- No foreign key leaves the common component.

-- ------------------------------------------------------------------ 1. durable handles

CREATE FUNCTION mission_control.knowledge_operation_state_reachable(from_state text, to_state text)
RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $reachable$
    WITH RECURSIVE edge(source, target) AS (
        VALUES
            ('queued', 'running'), ('queued', 'cancelling'), ('queued', 'cancelled'),
            ('queued', 'failed'), ('queued', 'rejected'),
            ('running', 'waiting_review'), ('running', 'cancelling'), ('running', 'succeeded'),
            ('running', 'partial'), ('running', 'held'), ('running', 'rejected'),
            ('running', 'failed'),
            ('waiting_review', 'running'), ('waiting_review', 'cancelling'),
            ('waiting_review', 'held'), ('waiting_review', 'rejected'),
            ('waiting_review', 'succeeded'), ('waiting_review', 'partial'),
            ('waiting_review', 'failed'),
            ('cancelling', 'cancelled'), ('cancelling', 'succeeded'), ('cancelling', 'partial'),
            ('cancelling', 'held'), ('cancelling', 'rejected'), ('cancelling', 'failed')
    ), walk(state) AS (
        SELECT edge.target FROM edge WHERE edge.source = from_state
        UNION
        SELECT edge.target FROM edge JOIN walk ON edge.source = walk.state
    )
    SELECT EXISTS (SELECT 1 FROM walk WHERE walk.state = to_state)
$reachable$;
REVOKE ALL ON FUNCTION mission_control.knowledge_operation_state_reachable(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mission_control.knowledge_operation_state_reachable(text, text)
TO mission_control_runtime, mission_control_readonly;
COMMENT ON FUNCTION mission_control.knowledge_operation_state_reachable(text, text) IS
    'A forward path of K01 ks.knowledge_operation.v2 operation-state edges leads from one state '
    'to the other (a poller observes statuses, not every edge).';

CREATE TABLE mission_control.knowledge_operation_handle (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    handle_id uuid PRIMARY KEY,
    binding_id text NOT NULL CHECK (binding_id <> ''),
    operation text NOT NULL CHECK (operation IN (
        'knowledge.read', 'knowledge.apply', 'report.register', 'report.assess',
        'report.derive', 'verify.claims')),
    request_id text NOT NULL CHECK (request_id <> '' AND length(request_id) <= 200),
    remote_operation_id text NOT NULL CHECK (remote_operation_id <> '' AND length(remote_operation_id) <= 200),
    protocol_version text NOT NULL CHECK (protocol_version = 'ks.knowledge_operation.v2'),
    handle jsonb NOT NULL CHECK (jsonb_typeof(handle) = 'object'
        AND handle->>'operationId' = remote_operation_id
        AND NOT (handle ?| ARRAY['credential', 'token', 'authorization', 'secret'])),
    effect_key text CHECK (effect_key IS NULL OR (effect_key <> '' AND length(effect_key) <= 512)),
    subject_ref text CHECK (subject_ref IS NULL OR (subject_ref <> '' AND length(subject_ref) <= 2048)),
    mission_id uuid NOT NULL,
    run_id uuid NOT NULL,
    activation_id uuid,
    operation_ref text NOT NULL CHECK (operation_ref <> ''),
    operation_attempt integer NOT NULL CHECK (operation_attempt >= 1),
    execution_generation integer NOT NULL CHECK (execution_generation >= 1),
    unit_key text CHECK (unit_key IS NULL OR unit_key ~ '^bl-unit-v1:[0-9a-f]{64}$'),
    lane_profile text CHECK (lane_profile IS NULL OR lane_profile <> ''),
    invocation_ref text NOT NULL CHECK (invocation_ref <> ''),
    caller_origin jsonb NOT NULL CHECK (jsonb_typeof(caller_origin) = 'object'
        AND NOT (caller_origin ?| ARRAY['credential', 'token', 'authorization', 'secret'])),
    state text NOT NULL CHECK (state IN (
        'queued', 'running', 'waiting_review', 'cancelling', 'succeeded', 'partial', 'held',
        'rejected', 'failed', 'cancelled')),
    remote_revision bigint NOT NULL CHECK (remote_revision >= 0),
    cancel_request_id text CHECK (cancel_request_id IS NULL OR (cancel_request_id <> '' AND length(cancel_request_id) <= 200)),
    pending_review_ref text CHECK (pending_review_ref IS NULL OR pending_review_ref <> ''),
    result_ref jsonb CHECK (result_ref IS NULL OR jsonb_typeof(result_ref) = 'object'),
    error_code text CHECK (error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]*$'),
    unresolved_effects jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(unresolved_effects) = 'array'),
    version bigint NOT NULL CHECK (version >= 1),
    recorded_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    -- An effect's handle names its effect key; a non-effect handle names none.
    CHECK ((operation IN ('knowledge.apply', 'report.register')) = (effect_key IS NOT NULL)),
    -- The K01 status rules the binding enforces, kept for the stored copy.
    CHECK (state <> 'waiting_review' OR pending_review_ref IS NOT NULL),
    CHECK (state NOT IN ('cancelling', 'cancelled') OR cancel_request_id IS NOT NULL),
    CHECK (state <> 'failed' OR error_code IS NOT NULL),
    UNIQUE (installation_id, application_id, tenant_id, handle_id),
    UNIQUE (installation_id, application_id, tenant_id, binding_id, remote_operation_id),
    UNIQUE (installation_id, application_id, tenant_id, binding_id, operation, request_id),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE INDEX knowledge_operation_handle_open_idx ON mission_control.knowledge_operation_handle
    (installation_id, application_id, tenant_id, invocation_ref)
    WHERE state IN ('queued', 'running', 'waiting_review', 'cancelling');
CREATE INDEX knowledge_operation_handle_run_idx ON mission_control.knowledge_operation_handle
    (installation_id, application_id, tenant_id, run_id, operation_ref, operation_attempt);
COMMENT ON TABLE mission_control.knowledge_operation_handle IS
    'mc.knowledge_operation_handle.v1: the durable remote handle of one knowledge operation '
    '(K01 handle, status, monotonic remote revision, first cancel request id, pending review, '
    'result and unresolved effects); coordinates and references only, never credentials.';

CREATE FUNCTION mission_control.knowledge_operation_handle_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.version <> 1 OR NEW.state <> 'queued' OR NEW.remote_revision <> 0
           OR NEW.cancel_request_id IS NOT NULL THEN
            RAISE EXCEPTION 'a knowledge operation handle is recorded queued at version 1'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'knowledge_operation_handle rows are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.installation_id <> OLD.installation_id OR NEW.application_id <> OLD.application_id
       OR NEW.tenant_id <> OLD.tenant_id OR NEW.handle_id <> OLD.handle_id
       OR NEW.binding_id <> OLD.binding_id OR NEW.operation <> OLD.operation
       OR NEW.request_id <> OLD.request_id OR NEW.remote_operation_id <> OLD.remote_operation_id
       OR NEW.protocol_version <> OLD.protocol_version OR NEW.handle <> OLD.handle
       OR NEW.effect_key IS DISTINCT FROM OLD.effect_key
       OR NEW.subject_ref IS DISTINCT FROM OLD.subject_ref
       OR NEW.mission_id <> OLD.mission_id OR NEW.run_id <> OLD.run_id
       OR NEW.activation_id IS DISTINCT FROM OLD.activation_id
       OR NEW.operation_ref <> OLD.operation_ref OR NEW.operation_attempt <> OLD.operation_attempt
       OR NEW.execution_generation <> OLD.execution_generation
       OR NEW.unit_key IS DISTINCT FROM OLD.unit_key
       OR NEW.lane_profile IS DISTINCT FROM OLD.lane_profile
       OR NEW.invocation_ref <> OLD.invocation_ref OR NEW.caller_origin <> OLD.caller_origin
       OR NEW.recorded_at <> OLD.recorded_at OR NEW.created_at <> OLD.created_at
       OR NEW.created_by_actor_ref <> OLD.created_by_actor_ref THEN
        RAISE EXCEPTION 'knowledge_operation_handle identity is fixed'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.cancel_request_id IS NOT NULL
       AND NEW.cancel_request_id IS DISTINCT FROM OLD.cancel_request_id THEN
        RAISE EXCEPTION 'the first cancel request id is kept (idempotent cancellation)'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.state IN ('succeeded', 'partial', 'held', 'rejected', 'failed', 'cancelled') AND (
        NEW.state <> OLD.state OR NEW.remote_revision <> OLD.remote_revision
        OR NEW.result_ref IS DISTINCT FROM OLD.result_ref
        OR NEW.error_code IS DISTINCT FROM OLD.error_code
        OR NEW.cancel_request_id IS DISTINCT FROM OLD.cancel_request_id
    ) THEN
        RAISE EXCEPTION 'a terminal knowledge operation handle keeps its outcome'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.state <> OLD.state
       AND NOT mission_control.knowledge_operation_state_reachable(OLD.state, NEW.state) THEN
        RAISE EXCEPTION 'illegal knowledge operation handle transition % -> %', OLD.state, NEW.state
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    -- An observed status always carries a newer remote revision; only recording the cancel
    -- request id keeps the revision.
    IF (NEW.state <> OLD.state OR NEW.result_ref IS DISTINCT FROM OLD.result_ref
        OR NEW.error_code IS DISTINCT FROM OLD.error_code
        OR NEW.pending_review_ref IS DISTINCT FROM OLD.pending_review_ref
        OR NEW.unresolved_effects <> OLD.unresolved_effects)
       AND NEW.remote_revision <= OLD.remote_revision THEN
        RAISE EXCEPTION 'a knowledge operation handle only observes newer remote revisions'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.remote_revision < OLD.remote_revision THEN
        RAISE EXCEPTION 'a knowledge operation handle never regresses its remote revision'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.version <> OLD.version + 1 OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'knowledge_operation_handle version must advance by one and time never moves back'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.knowledge_operation_handle_guard() FROM PUBLIC;
CREATE TRIGGER knowledge_operation_handle_guard
    BEFORE INSERT OR UPDATE OR DELETE ON mission_control.knowledge_operation_handle
    FOR EACH ROW EXECUTE FUNCTION mission_control.knowledge_operation_handle_guard();

ALTER TABLE mission_control.knowledge_operation_handle ENABLE ROW LEVEL SECURITY;
ALTER TABLE mission_control.knowledge_operation_handle FORCE ROW LEVEL SECURITY;
CREATE POLICY knowledge_operation_handle_scope ON mission_control.knowledge_operation_handle
    USING (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id())
    WITH CHECK (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id());
REVOKE ALL ON mission_control.knowledge_operation_handle FROM PUBLIC;
GRANT SELECT, INSERT ON mission_control.knowledge_operation_handle TO mission_control_runtime;
GRANT UPDATE (state, remote_revision, cancel_request_id, pending_review_ref, result_ref,
    error_code, unresolved_effects, version, updated_at)
ON mission_control.knowledge_operation_handle TO mission_control_runtime;
GRANT SELECT ON mission_control.knowledge_operation_handle TO mission_control_readonly;

-- ------------------------------------------------------------------ 2. assessment handoff

ALTER TABLE mission_control.output_submission
    ADD COLUMN assessment_operation_id text
        CHECK (assessment_operation_id IS NULL OR (assessment_operation_id <> '' AND length(assessment_operation_id) <= 200)),
    ADD COLUMN assessment_binding text
        CHECK (assessment_binding IS NULL OR assessment_binding <> ''),
    ADD COLUMN assessment_requested_at timestamptz;
ALTER TABLE mission_control.output_submission
    DROP CONSTRAINT output_submission_assessment_state_check,
    ADD CONSTRAINT output_submission_assessment_state_check CHECK (
        assessment_state IN ('pending', 'assessing', 'assessed', 'held', 'rejected')),
    DROP CONSTRAINT output_submission_check,
    ADD CONSTRAINT output_submission_assessment_decided_check CHECK (
        (assessment_state IN ('pending', 'assessing')) = (assessment_ref IS NULL AND assessed_at IS NULL)),
    ADD CONSTRAINT output_submission_assessment_handle_check CHECK (
        (assessment_operation_id IS NULL) = (assessment_binding IS NULL)
        AND (assessment_operation_id IS NULL) = (assessment_requested_at IS NULL)
        AND (assessment_state <> 'assessing' OR assessment_operation_id IS NOT NULL));
COMMENT ON COLUMN mission_control.output_submission.assessment_operation_id IS
    'The remote operation id of the independent report.assess the host started for this '
    'submission (knowledge_operation_handle.remote_operation_id under assessment_binding).';

CREATE OR REPLACE FUNCTION mission_control.output_submission_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.version <> 1 OR NEW.assessment_state <> 'pending'
           OR NEW.assessment_operation_id IS NOT NULL THEN
            RAISE EXCEPTION 'a submission is recorded pending at version 1'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF EXISTS (
            SELECT 1 FROM mission_control.output_submission AS existing
            WHERE existing.installation_id = NEW.installation_id
              AND existing.application_id = NEW.application_id
              AND existing.tenant_id = NEW.tenant_id
              AND existing.invocation_ref = NEW.invocation_ref
              AND existing.obligation_id = NEW.obligation_id
              AND existing.submission_key = NEW.submission_key
              AND existing.selection_digest <> NEW.selection_digest
        ) THEN
            RAISE EXCEPTION 'SUBMISSION_CONFLICT %', NEW.submission_key USING ERRCODE = 'MCE02';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'output_submission rows are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.installation_id <> OLD.installation_id OR NEW.application_id <> OLD.application_id
       OR NEW.tenant_id <> OLD.tenant_id OR NEW.submission_id <> OLD.submission_id
       OR NEW.run_id <> OLD.run_id OR NEW.operation_ref <> OLD.operation_ref
       OR NEW.operation_attempt <> OLD.operation_attempt
       OR NEW.execution_generation <> OLD.execution_generation
       OR NEW.unit_key IS DISTINCT FROM OLD.unit_key OR NEW.invocation_ref <> OLD.invocation_ref
       OR NEW.obligation_id <> OLD.obligation_id OR NEW.submission_key <> OLD.submission_key
       OR NEW.revision <> OLD.revision OR NEW.selection <> OLD.selection
       OR NEW.selection_digest <> OLD.selection_digest OR NEW.submitted_at <> OLD.submitted_at
       OR NEW.created_at <> OLD.created_at OR NEW.created_by_actor_ref <> OLD.created_by_actor_ref THEN
        RAISE EXCEPTION 'output_submission identity and selection are fixed'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.assessment_state <> OLD.assessment_state AND NOT (
        (OLD.assessment_state = 'pending'
            AND NEW.assessment_state IN ('assessing', 'assessed', 'held', 'rejected'))
        OR (OLD.assessment_state = 'assessing'
            AND NEW.assessment_state IN ('assessed', 'held', 'rejected'))
        OR (OLD.assessment_state = 'held' AND NEW.assessment_state IN ('assessed', 'rejected'))
    ) THEN
        RAISE EXCEPTION 'illegal submission assessment transition % -> %',
            OLD.assessment_state, NEW.assessment_state
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    -- The independent assessment handle is named when the assessment starts and kept.
    IF OLD.assessment_operation_id IS NOT NULL AND (
        NEW.assessment_operation_id IS DISTINCT FROM OLD.assessment_operation_id
        OR NEW.assessment_binding IS DISTINCT FROM OLD.assessment_binding
        OR NEW.assessment_requested_at IS DISTINCT FROM OLD.assessment_requested_at
    ) THEN
        RAISE EXCEPTION 'a submission keeps the assessment handle it started'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.assessment_operation_id IS NULL AND NEW.assessment_operation_id IS NOT NULL
       AND NOT (OLD.assessment_state = 'pending' AND NEW.assessment_state = 'assessing') THEN
        RAISE EXCEPTION 'an assessment handle is named only when the assessment starts'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.assessment_state IN ('assessed', 'rejected') AND (
        NEW.assessment_ref IS DISTINCT FROM OLD.assessment_ref
        OR NEW.assessment_digest IS DISTINCT FROM OLD.assessment_digest
        OR NEW.assessed_at IS DISTINCT FROM OLD.assessed_at
    ) THEN
        RAISE EXCEPTION 'a decided submission keeps its assessment'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.version <> OLD.version + 1 OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'output_submission version must advance by one and time never moves back'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$;

GRANT UPDATE (assessment_operation_id, assessment_binding, assessment_requested_at)
ON mission_control.output_submission TO mission_control_runtime;

-- ------------------------------------------------------------------ 3. finalization basis

ALTER TABLE mission_control.invocation_finalization
    ADD COLUMN outcome_basis text NOT NULL DEFAULT 'submission_coverage'
        CHECK (outcome_basis IN ('submission_coverage', 'assessed', 'attempt_failed'));
COMMENT ON COLUMN mission_control.invocation_finalization.outcome_basis IS
    'What the outcome measures: submission_coverage (a submission exists for each obligation), '
    'assessed (every selected report reached a service verdict: succeeded, held, rejected) or '
    'attempt_failed (the attempt failed after reconciling its outstanding effects).';

-- ------------------------------------------------------------------ 4. delivery attempts

ALTER TABLE mission_control.context_delivery_receipt
    ADD COLUMN attempt integer NOT NULL DEFAULT 1 CHECK (attempt IN (1, 2)),
    ADD COLUMN outcome_code text GENERATED ALWAYS AS (
        CASE
            WHEN NOT delivered THEN 'missing'
            WHEN delivered_digest IS DISTINCT FROM required_digest THEN 'digest_mismatch'
            WHEN NOT readable THEN 'unreadable'
            WHEN NOT budget_fit THEN 'over_budget'
            ELSE 'delivered'
        END) STORED;
ALTER TABLE mission_control.context_delivery_receipt
    DROP CONSTRAINT context_delivery_receipt_installation_id_application_id_te_key1,
    ADD CONSTRAINT context_delivery_receipt_attempt_key UNIQUE (
        installation_id, application_id, tenant_id, transfer_plan_id, receiver_invocation_ref,
        item_key, attempt);
COMMENT ON COLUMN mission_control.context_delivery_receipt.attempt IS
    '1 for the delivery, 2 for its one repair; a second failure blocks the plan.';

CREATE FUNCTION mission_control.context_delivery_receipt_attempt_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM mission_control.context_transfer_plan AS plan
        WHERE plan.installation_id = NEW.installation_id
          AND plan.application_id = NEW.application_id
          AND plan.tenant_id = NEW.tenant_id
          AND plan.transfer_plan_id = NEW.transfer_plan_id
          AND plan.state = 'delivering'
    ) THEN
        RAISE EXCEPTION 'delivery receipts are recorded while their plan is delivering'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.attempt = 2 AND NOT EXISTS (
        SELECT 1 FROM mission_control.context_delivery_receipt AS first
        WHERE first.installation_id = NEW.installation_id
          AND first.application_id = NEW.application_id
          AND first.tenant_id = NEW.tenant_id
          AND first.transfer_plan_id = NEW.transfer_plan_id
          AND first.receiver_invocation_ref = NEW.receiver_invocation_ref
          AND first.item_key = NEW.item_key
          AND first.attempt = 1
          AND first.outcome_code <> 'delivered'
    ) THEN
        RAISE EXCEPTION 'a repair attempt follows a failed first attempt of the same item'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.context_delivery_receipt_attempt_guard() FROM PUBLIC;
CREATE TRIGGER context_delivery_receipt_attempt_guard
    BEFORE INSERT ON mission_control.context_delivery_receipt
    FOR EACH ROW EXECUTE FUNCTION mission_control.context_delivery_receipt_attempt_guard();

CREATE OR REPLACE FUNCTION mission_control.context_transfer_plan_guard() RETURNS trigger
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
    -- Readiness: delivered only when every required item has a delivered, digest-verified,
    -- readable, in-budget receipt (at its first attempt or its one repair).
    IF NEW.state = 'delivered' AND OLD.state <> 'delivered' AND (
        (SELECT count(DISTINCT receipt.item_key)
           FROM mission_control.context_delivery_receipt AS receipt
          WHERE receipt.installation_id = NEW.installation_id
            AND receipt.application_id = NEW.application_id
            AND receipt.tenant_id = NEW.tenant_id
            AND receipt.transfer_plan_id = NEW.transfer_plan_id
            AND receipt.outcome_code = 'delivered') < NEW.required_items
        OR EXISTS (
            SELECT 1 FROM jsonb_array_elements(NEW.plan->'items') AS item(document)
            WHERE COALESCE((item.document->>'required')::boolean, true)
              AND NOT EXISTS (
                  SELECT 1 FROM mission_control.context_delivery_receipt AS receipt
                  WHERE receipt.installation_id = NEW.installation_id
                    AND receipt.application_id = NEW.application_id
                    AND receipt.tenant_id = NEW.tenant_id
                    AND receipt.transfer_plan_id = NEW.transfer_plan_id
                    AND receipt.item_key = item.document->>'item_key'
                    AND receipt.outcome_code = 'delivered'))
    ) THEN
        RAISE EXCEPTION 'a transfer plan is delivered only with a verified receipt for every required item'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.state = 'blocked' AND OLD.state <> 'blocked' AND NOT EXISTS (
        SELECT 1 FROM mission_control.context_delivery_receipt AS receipt
        WHERE receipt.installation_id = NEW.installation_id
          AND receipt.application_id = NEW.application_id
          AND receipt.tenant_id = NEW.tenant_id
          AND receipt.transfer_plan_id = NEW.transfer_plan_id
          AND receipt.attempt = 2
          AND receipt.outcome_code <> 'delivered'
    ) THEN
        RAISE EXCEPTION 'a transfer plan blocks only after its repair attempt failed'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.version <> OLD.version + 1 OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'context_transfer_plan version must advance by one and time never moves back'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$;

-- ------------------------------------------------------------------ 5. recovery authority

ALTER TABLE mission_control.knowledge_operation_journal
    ADD COLUMN recovery_authority_ref text
        CHECK (recovery_authority_ref IS NULL OR (recovery_authority_ref <> ''
            AND length(recovery_authority_ref) <= 512));
COMMENT ON COLUMN mission_control.knowledge_operation_journal.recovery_authority_ref IS
    'The host recovery grant (effect scope: this exact effect key and bound digest) under which '
    'the latest dispatch was sent by a later attempt; NULL for the originating attempt.';
GRANT UPDATE (recovery_authority_ref) ON mission_control.knowledge_operation_journal
    TO mission_control_runtime;
ALTER TABLE mission_control.knowledge_operation_transition
    ADD COLUMN recovery_authority_ref text
        CHECK (recovery_authority_ref IS NULL OR recovery_authority_ref <> '');
CREATE OR REPLACE FUNCTION mission_control.knowledge_operation_append_transition() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $append$
BEGIN
    INSERT INTO mission_control.knowledge_operation_transition (
        installation_id, application_id, tenant_id, knowledge_operation_id, transition_version,
        from_state, to_state, reconciled, dispatch_id, envelope_digest, current_caller_origin,
        terminal_receipt_ref, refusal_code, recorded_at, recorded_by_actor_ref,
        recovery_authority_ref)
    VALUES (
        NEW.installation_id, NEW.application_id, NEW.tenant_id, NEW.knowledge_operation_id,
        NEW.version, CASE WHEN TG_OP = 'UPDATE' THEN OLD.state END, NEW.state, NEW.reconciled,
        NEW.dispatch_id, NEW.envelope_digest, NEW.current_caller_origin,
        NEW.terminal_receipt_ref, NEW.refusal_code, NEW.updated_at,
        COALESCE(mission_control.ctx_actor_ref(), NEW.created_by_actor_ref),
        NEW.recovery_authority_ref);
    RETURN NULL;
END
$append$;
REVOKE ALL ON FUNCTION mission_control.knowledge_operation_append_transition() FROM PUBLIC;
