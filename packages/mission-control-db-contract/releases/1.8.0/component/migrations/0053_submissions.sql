-- Release 1.5.0 (Sprint V SV-13, design M03 / OC-D83): `submit_output` submissions.
-- `output_submission`: one row per submission act of one invocation for one obligation. A
-- tool-call retry carries the same stable `submission_key` and is the same submission (same
-- selection digest, else SUBMISSION_CONFLICT, SQLSTATE MCE02); a revision is a new submission
-- with the next `revision`. The selection (handles, paths and their digests) is frozen; only
-- the assessment advances: pending -> assessed | held | rejected, held -> assessed | rejected.
-- `invocation_finalization`: the one finalization record per invocation. Advanced
-- accumulation and transfer policy fields arrive with the later output-contracts release.
CREATE TABLE mission_control.output_submission (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    submission_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    operation_ref text NOT NULL CHECK (operation_ref <> ''),
    operation_attempt integer NOT NULL CHECK (operation_attempt >= 1),
    execution_generation integer NOT NULL CHECK (execution_generation >= 1),
    unit_key text CHECK (unit_key IS NULL OR unit_key ~ '^bl-unit-v1:[0-9a-f]{64}$'),
    invocation_ref text NOT NULL CHECK (invocation_ref <> ''),
    obligation_id text NOT NULL CHECK (obligation_id <> ''),
    submission_key text NOT NULL CHECK (submission_key <> '' AND length(submission_key) <= 512),
    revision integer NOT NULL CHECK (revision >= 1),
    selection jsonb NOT NULL CHECK (jsonb_typeof(selection) = 'object'),
    selection_digest text NOT NULL CHECK (selection_digest ~ '^sha256:[0-9a-f]{64}$'),
    assessment_state text NOT NULL CHECK (assessment_state IN ('pending', 'assessed', 'held', 'rejected')),
    assessment_ref text CHECK (assessment_ref IS NULL OR assessment_ref <> ''),
    assessment_digest text CHECK (assessment_digest IS NULL OR assessment_digest ~ '^sha256:[0-9a-f]{64}$'),
    assessed_at timestamptz,
    version bigint NOT NULL CHECK (version >= 1),
    submitted_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    -- A decided assessment names the five-guarantee assessment that decided it.
    CHECK ((assessment_state = 'pending') = (assessment_ref IS NULL AND assessed_at IS NULL)),
    UNIQUE (installation_id, application_id, tenant_id, submission_id),
    UNIQUE (installation_id, application_id, tenant_id, invocation_ref, obligation_id, submission_key),
    UNIQUE (installation_id, application_id, tenant_id, invocation_ref, obligation_id, revision),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE INDEX output_submission_run_idx ON mission_control.output_submission
    (installation_id, application_id, tenant_id, run_id, operation_ref, operation_attempt);
COMMENT ON TABLE mission_control.output_submission IS
    'mc.output_submission.v1: one submit_output act per invocation, obligation and stable '
    'submission key; frozen selection, advancing assessment.';

CREATE FUNCTION mission_control.output_submission_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.version <> 1 OR NEW.assessment_state <> 'pending' THEN
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
        (OLD.assessment_state = 'pending' AND NEW.assessment_state IN ('assessed', 'held', 'rejected'))
        OR (OLD.assessment_state = 'held' AND NEW.assessment_state IN ('assessed', 'rejected'))
    ) THEN
        RAISE EXCEPTION 'illegal submission assessment transition % -> %',
            OLD.assessment_state, NEW.assessment_state
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
REVOKE ALL ON FUNCTION mission_control.output_submission_guard() FROM PUBLIC;
CREATE TRIGGER output_submission_guard
    BEFORE INSERT OR UPDATE OR DELETE ON mission_control.output_submission
    FOR EACH ROW EXECUTE FUNCTION mission_control.output_submission_guard();

CREATE TABLE mission_control.invocation_finalization (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    finalization_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    operation_ref text NOT NULL CHECK (operation_ref <> ''),
    operation_attempt integer NOT NULL CHECK (operation_attempt >= 1),
    execution_generation integer NOT NULL CHECK (execution_generation >= 1),
    unit_key text CHECK (unit_key IS NULL OR unit_key ~ '^bl-unit-v1:[0-9a-f]{64}$'),
    invocation_ref text NOT NULL CHECK (invocation_ref <> ''),
    outcome text NOT NULL CHECK (outcome IN ('fulfilled', 'partially_fulfilled', 'unfulfilled', 'refused')),
    submission_ids uuid[] NOT NULL DEFAULT '{}',
    report jsonb NOT NULL CHECK (jsonb_typeof(report) = 'object'),
    report_digest text NOT NULL CHECK (report_digest ~ '^sha256:[0-9a-f]{64}$'),
    finalized_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    UNIQUE (installation_id, application_id, tenant_id, finalization_id),
    UNIQUE (installation_id, application_id, tenant_id, invocation_ref),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE TRIGGER invocation_finalization_immutable
    BEFORE UPDATE OR DELETE ON mission_control.invocation_finalization
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.invocation_finalization IS
    'mc.invocation_finalization.v1: the one finalization report per invocation; append-only.';

DO $policies$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['output_submission', 'invocation_finalization'] LOOP
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

REVOKE ALL ON mission_control.output_submission, mission_control.invocation_finalization FROM PUBLIC;
GRANT SELECT, INSERT ON mission_control.output_submission, mission_control.invocation_finalization
TO mission_control_runtime;
GRANT UPDATE (assessment_state, assessment_ref, assessment_digest, assessed_at, version, updated_at)
ON mission_control.output_submission TO mission_control_runtime;
GRANT SELECT ON mission_control.output_submission, mission_control.invocation_finalization
TO mission_control_readonly;
