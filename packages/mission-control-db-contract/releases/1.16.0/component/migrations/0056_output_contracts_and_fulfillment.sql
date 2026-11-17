-- Release 1.7.0 (Sprint OC WI-01 / OVE-163; OUTPUT-CONTRACTS §§2-4, ADR-0058): exact named
-- output promises, their output revisions with compare-and-set accepted heads, pinned output
-- sets and members, independent assessments and obligation fulfillment decisions.
-- Immutable facts: obligation revisions, output revisions, sets, members, assessments,
-- fulfillment decisions and association steps (reject_mutation). Mutable pointers, each moved
-- by compare-and-set with a version: the active obligation revision of a run and the accepted
-- head of each deliverable. Every key carries the installation/application/tenant scope and
-- every foreign key stays inside it. The submission act itself is `output_submission` (stable
-- scoped key; same key with other bytes is SUBMISSION_CONFLICT, MCE02). A set's membership
-- digest covers exact members only, never later assessments. A successor revision is recorded
-- pending and the head moves to it only when the host reports its declared boundary as
-- reached; an invocation pins its revisions at start, and every output revision it submits is
-- bound to that pin.

CREATE TABLE mission_control.output_promise_set (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    run_id uuid NOT NULL,
    promise_set jsonb NOT NULL CHECK (jsonb_typeof(promise_set) = 'object'
        AND jsonb_typeof(promise_set -> 'completion') = 'object'),
    promise_set_digest text NOT NULL CHECK (promise_set_digest ~ '^sha256:[0-9a-f]{64}$'),
    configuration_digest text CHECK (
        configuration_digest IS NULL OR configuration_digest ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    PRIMARY KEY (installation_id, application_id, tenant_id, run_id),
    UNIQUE (installation_id, application_id, tenant_id, run_id, promise_set_digest),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE TRIGGER output_promise_set_immutable
    BEFORE UPDATE OR DELETE ON mission_control.output_promise_set
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.output_promise_set IS
    'mc.output_promises.v1: the admitted promise set of a run with its closed completion '
    'expression and declared vocabularies; the only completion fulfillment evaluates.';

CREATE TABLE mission_control.output_obligation_revision (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    obligation_revision_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    obligation_key text NOT NULL CHECK (obligation_key ~ '^[a-z0-9][a-z0-9._:-]{0,199}$'),
    revision integer NOT NULL CHECK (revision >= 1),
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    owner_position text NOT NULL CHECK (owner_position <> '' AND length(owner_position) <= 512),
    form text NOT NULL CHECK (form IN ('text', 'structured', 'file', 'collection', 'reference',
        'code_change', 'effect_receipt', 'control_record')),
    enforcement text NOT NULL CHECK (enforcement IN ('required', 'expected', 'optional')),
    evaluation_scope text NOT NULL CHECK (evaluation_scope IN ('invocation', 'cycle',
        'iteration', 'activation', 'accumulated_stage', 'goal', 'mission')),
    obligation jsonb NOT NULL CHECK (jsonb_typeof(obligation) = 'object'),
    obligation_digest text NOT NULL CHECK (obligation_digest ~ '^sha256:[0-9a-f]{64}$'),
    promise_set_digest text NOT NULL CHECK (promise_set_digest ~ '^sha256:[0-9a-f]{64}$'),
    configuration_digest text CHECK (
        configuration_digest IS NULL OR configuration_digest ~ '^sha256:[0-9a-f]{64}$'),
    proposal jsonb CHECK (proposal IS NULL OR jsonb_typeof(proposal) = 'object'),
    activation_boundary text CHECK (activation_boundary IS NULL OR activation_boundary IN (
        'before_activation', 'between_iterations', 'between_stages', 'before_invocation')),
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    -- Revision 1 is admitted with the configuration; every successor names its governed
    -- proposal (expected prior, actor, reason, delegation, authority) and the safe boundary
    -- kind at which it may become active.
    CHECK ((revision = 1) = (proposal IS NULL AND activation_boundary IS NULL)),
    CHECK (proposal IS NULL OR (proposal ? 'delegation_ref' AND proposal ? 'reason'
        AND proposal ? 'expected_prior_revision')),
    CHECK (obligation ->> 'key' = obligation_key
        AND (obligation ->> 'revision')::integer = revision
        AND obligation ->> 'owner_position' = owner_position
        AND obligation ->> 'enforcement' = enforcement
        AND obligation -> 'contract' ->> 'form' = form),
    UNIQUE (installation_id, application_id, tenant_id, obligation_revision_id),
    UNIQUE (installation_id, application_id, tenant_id, run_id, obligation_key, revision),
    FOREIGN KEY (installation_id, application_id, tenant_id, run_id, promise_set_digest)
        REFERENCES mission_control.output_promise_set (installation_id, application_id,
            tenant_id, run_id, promise_set_digest)
);
CREATE TRIGGER output_obligation_revision_immutable
    BEFORE UPDATE OR DELETE ON mission_control.output_obligation_revision
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.output_obligation_revision IS
    'mc.output_obligation.v2: one immutable revision of a named output promise of a run '
    '(form, enforcement, cardinality, coverage, requirements, pinned contract).';

CREATE TABLE mission_control.output_obligation_head (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    run_id uuid NOT NULL,
    obligation_key text NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    active_revision integer NOT NULL CHECK (active_revision >= 1),
    version bigint NOT NULL CHECK (version >= 1),
    activated_boundary_ref text CHECK (
        activated_boundary_ref IS NULL OR activated_boundary_ref <> ''),
    updated_at timestamptz NOT NULL,
    updated_by_actor_ref text NOT NULL CHECK (updated_by_actor_ref <> ''),
    CHECK ((active_revision = 1) = (activated_boundary_ref IS NULL)),
    PRIMARY KEY (installation_id, application_id, tenant_id, run_id, obligation_key),
    FOREIGN KEY (installation_id, application_id, tenant_id, run_id, obligation_key,
        active_revision)
        REFERENCES mission_control.output_obligation_revision (installation_id, application_id,
            tenant_id, run_id, obligation_key, revision)
);
COMMENT ON TABLE mission_control.output_obligation_head IS
    'mc.output_obligation_head.v1: the active revision of each promise; a pending successor '
    'activates only by compare-and-set to the next revision at a boundary actually reached.';

CREATE FUNCTION mission_control.output_obligation_head_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.active_revision <> 1 OR NEW.version <> 1 THEN
            RAISE EXCEPTION 'a promise head starts at revision 1, version 1'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'output_obligation_head rows are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.installation_id <> OLD.installation_id OR NEW.application_id <> OLD.application_id
       OR NEW.tenant_id <> OLD.tenant_id OR NEW.run_id <> OLD.run_id
       OR NEW.obligation_key <> OLD.obligation_key OR NEW.ordinal <> OLD.ordinal THEN
        RAISE EXCEPTION 'output_obligation_head identity is fixed'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.active_revision <> OLD.active_revision + 1 OR NEW.version <> OLD.version + 1
       OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'a promise head advances to the next revision only'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM mission_control.output_obligation_revision AS successor
        WHERE successor.installation_id = NEW.installation_id
          AND successor.application_id = NEW.application_id
          AND successor.tenant_id = NEW.tenant_id AND successor.run_id = NEW.run_id
          AND successor.obligation_key = NEW.obligation_key
          AND successor.revision = NEW.active_revision
          AND successor.activation_boundary IS NOT NULL
          AND pg_catalog.starts_with(NEW.activated_boundary_ref,
              successor.activation_boundary || ':')
    ) THEN
        RAISE EXCEPTION 'a successor activates only at the boundary kind it declared'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.output_obligation_head_guard() FROM PUBLIC;
CREATE TRIGGER output_obligation_head_guard
    BEFORE INSERT OR UPDATE OR DELETE ON mission_control.output_obligation_head
    FOR EACH ROW EXECUTE FUNCTION mission_control.output_obligation_head_guard();

CREATE TABLE mission_control.output_obligation_pin (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    run_id uuid NOT NULL,
    invocation_ref text NOT NULL CHECK (invocation_ref <> ''),
    obligation_key text NOT NULL,
    revision integer NOT NULL CHECK (revision >= 1),
    pinned_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    PRIMARY KEY (installation_id, application_id, tenant_id, invocation_ref, obligation_key),
    FOREIGN KEY (installation_id, application_id, tenant_id, run_id, obligation_key, revision)
        REFERENCES mission_control.output_obligation_revision (installation_id, application_id,
            tenant_id, run_id, obligation_key, revision)
);
CREATE TRIGGER output_obligation_pin_immutable
    BEFORE UPDATE OR DELETE ON mission_control.output_obligation_pin
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.output_obligation_pin IS
    'mc.output_obligation_pin.v1: the promise revision an invocation pinned at its start; a '
    'later activation never moves it.';

CREATE TABLE mission_control.output_revision (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    output_revision_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    submission_id uuid NOT NULL,
    item_index integer NOT NULL CHECK (item_index >= 0),
    obligation_key text NOT NULL,
    obligation_revision integer NOT NULL CHECK (obligation_revision >= 1),
    deliverable_id text NOT NULL CHECK (deliverable_id ~ '^[a-z0-9][a-z0-9._:-]{0,199}$'),
    revision integer NOT NULL CHECK (revision >= 1),
    form text NOT NULL CHECK (form IN ('text', 'structured', 'file', 'collection', 'reference',
        'code_change', 'effect_receipt', 'control_record')),
    candidate jsonb NOT NULL CHECK (jsonb_typeof(candidate) = 'object'),
    content_digest text NOT NULL CHECK (content_digest ~ '^sha256:[0-9a-f]{64}$'),
    producer_origin_ref text NOT NULL CHECK (producer_origin_ref <> ''),
    caller_origin_ref text NOT NULL CHECK (caller_origin_ref <> ''),
    submitted_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    CHECK (candidate ->> 'deliverable_id' = deliverable_id AND candidate ->> 'form' = form
        AND candidate ->> 'digest' = content_digest),
    UNIQUE (installation_id, application_id, tenant_id, output_revision_id),
    UNIQUE (installation_id, application_id, tenant_id, submission_id, item_index),
    UNIQUE (installation_id, application_id, tenant_id, run_id, obligation_key, deliverable_id,
        revision),
    FOREIGN KEY (installation_id, application_id, tenant_id, submission_id)
        REFERENCES mission_control.output_submission (installation_id, application_id, tenant_id,
            submission_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, run_id, obligation_key,
        obligation_revision)
        REFERENCES mission_control.output_obligation_revision (installation_id, application_id,
            tenant_id, run_id, obligation_key, revision)
);
CREATE TRIGGER output_revision_immutable
    BEFORE UPDATE OR DELETE ON mission_control.output_revision
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.output_revision IS
    'mc.output_revision.v1: one immutable exact output revision offered by a submission act; '
    'drafts never move an accepted head.';

CREATE FUNCTION mission_control.output_revision_scope_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM mission_control.output_submission AS submission
        WHERE submission.installation_id = NEW.installation_id
          AND submission.application_id = NEW.application_id
          AND submission.tenant_id = NEW.tenant_id
          AND submission.submission_id = NEW.submission_id
          AND submission.run_id = NEW.run_id
          AND submission.obligation_id = NEW.obligation_key
          AND EXISTS (
              SELECT 1 FROM mission_control.output_obligation_pin AS pin
              WHERE pin.installation_id = NEW.installation_id
                AND pin.application_id = NEW.application_id
                AND pin.tenant_id = NEW.tenant_id
                AND pin.invocation_ref = submission.invocation_ref
                AND pin.obligation_key = NEW.obligation_key
                AND pin.revision = NEW.obligation_revision)
    ) THEN
        RAISE EXCEPTION 'an output revision belongs to its submission''s run, obligation and '
            'the invocation''s pinned promise revision'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.output_revision_scope_guard() FROM PUBLIC;
CREATE TRIGGER output_revision_scope_guard
    BEFORE INSERT ON mission_control.output_revision
    FOR EACH ROW EXECUTE FUNCTION mission_control.output_revision_scope_guard();

CREATE TABLE mission_control.output_accepted_head (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    run_id uuid NOT NULL,
    obligation_key text NOT NULL,
    deliverable_id text NOT NULL,
    output_revision_id uuid NOT NULL,
    generation integer NOT NULL CHECK (generation >= 1),
    version bigint NOT NULL CHECK (version >= 1),
    promoted_at timestamptz NOT NULL,
    promoted_by_actor_ref text NOT NULL CHECK (promoted_by_actor_ref <> ''),
    PRIMARY KEY (installation_id, application_id, tenant_id, run_id, obligation_key,
        deliverable_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, output_revision_id)
        REFERENCES mission_control.output_revision (installation_id, application_id, tenant_id,
            output_revision_id)
);
COMMENT ON TABLE mission_control.output_accepted_head IS
    'mc.output_accepted_head.v1: the accepted revision of one deliverable, moved only by an '
    'expected-head and generation compare-and-set promotion.';

CREATE FUNCTION mission_control.output_accepted_head_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'output_accepted_head rows are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM mission_control.output_revision AS revision
        WHERE revision.installation_id = NEW.installation_id
          AND revision.application_id = NEW.application_id
          AND revision.tenant_id = NEW.tenant_id
          AND revision.output_revision_id = NEW.output_revision_id
          AND revision.run_id = NEW.run_id
          AND revision.obligation_key = NEW.obligation_key
          AND revision.deliverable_id = NEW.deliverable_id
    ) THEN
        RAISE EXCEPTION 'an accepted head names a revision of its own deliverable'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.version <> 1 THEN
            RAISE EXCEPTION 'an accepted head starts at version 1'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.installation_id <> OLD.installation_id OR NEW.application_id <> OLD.application_id
       OR NEW.tenant_id <> OLD.tenant_id OR NEW.run_id <> OLD.run_id
       OR NEW.obligation_key <> OLD.obligation_key OR NEW.deliverable_id <> OLD.deliverable_id THEN
        RAISE EXCEPTION 'output_accepted_head identity is fixed'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.version <> OLD.version + 1 OR NEW.generation < OLD.generation
       OR NEW.promoted_at < OLD.promoted_at THEN
        RAISE EXCEPTION 'an accepted head advances by one version and never to an older generation'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.output_accepted_head_guard() FROM PUBLIC;
CREATE TRIGGER output_accepted_head_guard
    BEFORE INSERT OR UPDATE OR DELETE ON mission_control.output_accepted_head
    FOR EACH ROW EXECUTE FUNCTION mission_control.output_accepted_head_guard();

CREATE TABLE mission_control.output_set (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    output_set_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    revision integer NOT NULL CHECK (revision >= 1),
    obligation_refs jsonb NOT NULL CHECK (jsonb_typeof(obligation_refs) = 'array'),
    membership_digest text NOT NULL CHECK (membership_digest ~ '^sha256:[0-9a-f]{64}$'),
    prior_set_id uuid,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    CHECK ((revision = 1) = (prior_set_id IS NULL)),
    UNIQUE (installation_id, application_id, tenant_id, output_set_id),
    UNIQUE (installation_id, application_id, tenant_id, run_id, revision),
    FOREIGN KEY (installation_id, application_id, tenant_id, prior_set_id)
        REFERENCES mission_control.output_set (installation_id, application_id, tenant_id,
            output_set_id),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE TRIGGER output_set_immutable
    BEFORE UPDATE OR DELETE ON mission_control.output_set
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.output_set IS
    'mc.output_set.v1: one pinned frontier (current accepted set); its membership digest '
    'covers the pinned promise revisions and exact members, never assessments.';

CREATE TABLE mission_control.output_set_member (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    output_set_id uuid NOT NULL,
    output_revision_id uuid NOT NULL,
    obligation_key text NOT NULL,
    deliverable_id text NOT NULL,
    content_digest text NOT NULL CHECK (content_digest ~ '^sha256:[0-9a-f]{64}$'),
    PRIMARY KEY (installation_id, application_id, tenant_id, output_set_id, output_revision_id),
    UNIQUE (installation_id, application_id, tenant_id, output_set_id, obligation_key,
        deliverable_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, output_set_id)
        REFERENCES mission_control.output_set (installation_id, application_id, tenant_id,
            output_set_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, output_revision_id)
        REFERENCES mission_control.output_revision (installation_id, application_id, tenant_id,
            output_revision_id)
);
CREATE TRIGGER output_set_member_immutable
    BEFORE UPDATE OR DELETE ON mission_control.output_set_member
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.output_set_member IS
    'mc.output_set_member.v1: one exact member of a pinned output set.';

CREATE FUNCTION mission_control.output_set_member_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM mission_control.output_revision AS revision
        JOIN mission_control.output_set AS pinned
          ON pinned.installation_id = revision.installation_id
         AND pinned.application_id = revision.application_id
         AND pinned.tenant_id = revision.tenant_id
         AND pinned.run_id = revision.run_id
        WHERE revision.installation_id = NEW.installation_id
          AND revision.application_id = NEW.application_id
          AND revision.tenant_id = NEW.tenant_id
          AND revision.output_revision_id = NEW.output_revision_id
          AND revision.obligation_key = NEW.obligation_key
          AND revision.deliverable_id = NEW.deliverable_id
          AND revision.content_digest = NEW.content_digest
          AND pinned.output_set_id = NEW.output_set_id
    ) THEN
        RAISE EXCEPTION 'a set member is the exact revision of the set''s run it names'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.output_set_member_guard() FROM PUBLIC;
CREATE TRIGGER output_set_member_guard
    BEFORE INSERT ON mission_control.output_set_member
    FOR EACH ROW EXECUTE FUNCTION mission_control.output_set_member_guard();

CREATE TABLE mission_control.output_assessment (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    assessment_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    recorded_seq bigint GENERATED ALWAYS AS IDENTITY,
    subject_kind text NOT NULL CHECK (subject_kind IN ('output_revision', 'output_set', 'member')),
    subject_ref text NOT NULL CHECK (subject_ref <> '' AND length(subject_ref) <= 2048),
    output_revision_id uuid,
    output_set_id uuid,
    subject_digest text NOT NULL CHECK (subject_digest ~ '^sha256:[0-9a-f]{64}$'),
    requirement_results jsonb NOT NULL CHECK (
        jsonb_typeof(requirement_results) = 'object' AND requirement_results <> '{}'::jsonb),
    result text NOT NULL CHECK (result IN ('pass', 'fail', 'review', 'unavailable')),
    assessor_origin_ref text NOT NULL CHECK (assessor_origin_ref <> ''),
    method_pin text NOT NULL CHECK (method_pin <> ''),
    policy_pin text NOT NULL CHECK (policy_pin <> ''),
    evidence_refs jsonb NOT NULL CHECK (jsonb_typeof(evidence_refs) = 'array'),
    findings jsonb NOT NULL CHECK (jsonb_typeof(findings) = 'array'),
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    supersedes uuid,
    -- revision and member subjects name the exact revision (for a member, the index listing
    -- it); a set subject names the pinned set.
    CHECK ((subject_kind IN ('output_revision', 'member')) = (output_revision_id IS NOT NULL)),
    CHECK ((subject_kind = 'output_set') = (output_set_id IS NOT NULL)),
    UNIQUE (installation_id, application_id, tenant_id, assessment_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, output_revision_id)
        REFERENCES mission_control.output_revision (installation_id, application_id, tenant_id,
            output_revision_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, output_set_id)
        REFERENCES mission_control.output_set (installation_id, application_id, tenant_id,
            output_set_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, supersedes)
        REFERENCES mission_control.output_assessment (installation_id, application_id,
            tenant_id, assessment_id),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE INDEX output_assessment_run_idx ON mission_control.output_assessment
    (installation_id, application_id, tenant_id, run_id, recorded_seq);
CREATE TRIGGER output_assessment_immutable
    BEFORE UPDATE OR DELETE ON mission_control.output_assessment
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.output_assessment IS
    'mc.output_assessment.v1: one immutable independent judgment bound to an exact subject '
    'digest (revision, pinned set or nested member).';

CREATE FUNCTION mission_control.output_assessment_subject_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF NEW.subject_kind IN ('output_revision', 'member') AND NOT EXISTS (
        SELECT 1 FROM mission_control.output_revision AS revision
        WHERE revision.installation_id = NEW.installation_id
          AND revision.application_id = NEW.application_id
          AND revision.tenant_id = NEW.tenant_id
          AND revision.output_revision_id = NEW.output_revision_id
          AND revision.run_id = NEW.run_id
          AND revision.producer_origin_ref <> NEW.assessor_origin_ref
          AND (
              (NEW.subject_kind = 'output_revision'
               AND revision.content_digest = NEW.subject_digest
               AND NEW.subject_ref = revision.output_revision_id::text)
              OR (NEW.subject_kind = 'member' AND pg_catalog.jsonb_path_exists(
                  revision.candidate, '$.value.** ? (@.ref == $ref && @.digest == $digest)',
                  pg_catalog.jsonb_build_object('ref', NEW.subject_ref,
                      'digest', NEW.subject_digest)))
          )
    ) THEN
        RAISE EXCEPTION 'an assessment binds an exact revision (or a member its index lists) of '
            'its run and is never made by the producer'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.subject_kind = 'output_set' AND (NOT EXISTS (
        SELECT 1 FROM mission_control.output_set AS pinned
        WHERE pinned.installation_id = NEW.installation_id
          AND pinned.application_id = NEW.application_id
          AND pinned.tenant_id = NEW.tenant_id
          AND pinned.output_set_id = NEW.output_set_id
          AND pinned.run_id = NEW.run_id
          AND pinned.membership_digest = NEW.subject_digest
          AND NEW.subject_ref = pinned.output_set_id::text
    ) OR EXISTS (
        SELECT 1 FROM mission_control.output_set_member AS member
        JOIN mission_control.output_revision AS revision
          ON revision.installation_id = member.installation_id
         AND revision.application_id = member.application_id
         AND revision.tenant_id = member.tenant_id
         AND revision.output_revision_id = member.output_revision_id
        WHERE member.installation_id = NEW.installation_id
          AND member.application_id = NEW.application_id
          AND member.tenant_id = NEW.tenant_id
          AND member.output_set_id = NEW.output_set_id
          AND revision.producer_origin_ref = NEW.assessor_origin_ref
    )) THEN
        RAISE EXCEPTION 'a set assessment binds the exact membership digest of its run and is '
            'never made by a producer of a member'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.supersedes IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM mission_control.output_assessment AS earlier
        WHERE earlier.installation_id = NEW.installation_id
          AND earlier.application_id = NEW.application_id
          AND earlier.tenant_id = NEW.tenant_id
          AND earlier.assessment_id = NEW.supersedes
          AND earlier.subject_kind = NEW.subject_kind
          AND earlier.subject_ref = NEW.subject_ref
          AND earlier.subject_digest = NEW.subject_digest
    ) THEN
        RAISE EXCEPTION 'an assessment supersedes only an earlier judgment of the same subject'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.output_assessment_subject_guard() FROM PUBLIC;
CREATE TRIGGER output_assessment_subject_guard
    BEFORE INSERT ON mission_control.output_assessment
    FOR EACH ROW EXECUTE FUNCTION mission_control.output_assessment_subject_guard();

CREATE TABLE mission_control.obligation_fulfillment (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    fulfillment_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    output_set_id uuid NOT NULL,
    obligation_key text NOT NULL,
    obligation_revision integer NOT NULL CHECK (obligation_revision >= 1),
    enforcement text NOT NULL CHECK (enforcement IN ('required', 'expected', 'optional')),
    disposition text NOT NULL CHECK (disposition IN ('fulfilled', 'unfulfilled', 'blocked',
        'not_applicable')),
    distinct_count integer NOT NULL CHECK (distinct_count >= 0),
    decision jsonb NOT NULL CHECK (jsonb_typeof(decision) = 'object'),
    decision_digest text NOT NULL CHECK (decision_digest ~ '^sha256:[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    UNIQUE (installation_id, application_id, tenant_id, fulfillment_id),
    UNIQUE (installation_id, application_id, tenant_id, output_set_id, obligation_key,
        decision_digest),
    FOREIGN KEY (installation_id, application_id, tenant_id, output_set_id)
        REFERENCES mission_control.output_set (installation_id, application_id, tenant_id,
            output_set_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, run_id, obligation_key,
        obligation_revision)
        REFERENCES mission_control.output_obligation_revision (installation_id, application_id,
            tenant_id, run_id, obligation_key, revision)
);
CREATE TRIGGER obligation_fulfillment_immutable
    BEFORE UPDATE OR DELETE ON mission_control.obligation_fulfillment
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.obligation_fulfillment IS
    'mc.obligation_fulfillment.v1: one immutable decision for a declared promise at a pinned '
    'set (fulfilled, unfulfilled, blocked or not_applicable, with what is unmet).';

CREATE FUNCTION mission_control.obligation_fulfillment_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM mission_control.output_set AS pinned
        WHERE pinned.installation_id = NEW.installation_id
          AND pinned.application_id = NEW.application_id
          AND pinned.tenant_id = NEW.tenant_id
          AND pinned.output_set_id = NEW.output_set_id
          AND pinned.run_id = NEW.run_id
          AND pinned.obligation_refs @> pg_catalog.jsonb_build_array(
              pg_catalog.jsonb_build_array(NEW.obligation_key, NEW.obligation_revision))
    ) THEN
        RAISE EXCEPTION 'a fulfillment decides a promise revision the set pinned, in its run'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.obligation_fulfillment_guard() FROM PUBLIC;
CREATE TRIGGER obligation_fulfillment_guard
    BEFORE INSERT ON mission_control.obligation_fulfillment
    FOR EACH ROW EXECUTE FUNCTION mission_control.obligation_fulfillment_guard();

CREATE TABLE mission_control.obligation_association_step (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    run_id uuid NOT NULL,
    invocation_ref text NOT NULL CHECK (invocation_ref <> ''),
    obligation_key text NOT NULL,
    step text NOT NULL CHECK (step IN ('reminder', 'auto_associated', 'repair_requested',
        'blocked')),
    detail jsonb NOT NULL CHECK (jsonb_typeof(detail) = 'object'),
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    PRIMARY KEY (installation_id, application_id, tenant_id, invocation_ref, obligation_key,
        step),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE TRIGGER obligation_association_step_immutable
    BEFORE UPDATE OR DELETE ON mission_control.obligation_association_step
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
COMMENT ON TABLE mission_control.obligation_association_step IS
    'mc.obligation_association_step.v1: one reminder, one auto-association or ambiguity '
    'repair, then block, at most once each per invocation and promise.';

-- The finalization report counts verdicts over host-declared obligations only.
ALTER TABLE mission_control.invocation_finalization
    DROP CONSTRAINT invocation_finalization_outcome_basis_check,
    ADD CONSTRAINT invocation_finalization_outcome_basis_check CHECK (outcome_basis IN (
        'submission_coverage', 'declared_obligations', 'no_declared_obligations', 'assessed',
        'attempt_failed')),
    ALTER COLUMN outcome_basis SET DEFAULT 'declared_obligations';
COMMENT ON COLUMN mission_control.invocation_finalization.outcome_basis IS
    'declared_obligations (verdicts over host-declared promises), no_declared_obligations, '
    'assessed (every declared promise has a verdict) or attempt_failed; submission_coverage '
    'remains readable on rows written before 1.7.0 and is no longer written.';

DO $policies$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['output_promise_set', 'output_obligation_revision',
        'output_obligation_head', 'output_obligation_pin', 'output_revision', 'output_accepted_head', 'output_set', 'output_set_member',
        'output_assessment', 'obligation_fulfillment', 'obligation_association_step'] LOOP
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
        EXECUTE pg_catalog.format('REVOKE ALL ON mission_control.%I FROM PUBLIC', table_name);
        EXECUTE pg_catalog.format(
            'GRANT SELECT, INSERT ON mission_control.%I TO mission_control_runtime', table_name);
        EXECUTE pg_catalog.format(
            'GRANT SELECT ON mission_control.%I TO mission_control_readonly', table_name);
    END LOOP;
END
$policies$;
GRANT UPDATE (active_revision, version, activated_boundary_ref, updated_at, updated_by_actor_ref)
ON mission_control.output_obligation_head TO mission_control_runtime;
GRANT UPDATE (output_revision_id, generation, version, promoted_at, promoted_by_actor_ref)
ON mission_control.output_accepted_head TO mission_control_runtime;
