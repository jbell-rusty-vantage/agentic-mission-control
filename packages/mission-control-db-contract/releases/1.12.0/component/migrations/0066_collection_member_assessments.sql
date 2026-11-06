-- Release 1.9.0 candidate (Sprint OC WI-07 / OVE-170; OUTPUT-CONTRACTS §§2, 4, 8, ADR-0058):
-- independent per-member assessments of an exact collection manifest.
--
-- 0056 lets an assessment bind a `member` subject only when its revision lists the exact
-- (ref, digest) somewhere under `candidate.value` (an index with nested guarantees). A
-- collection revision lists its members in `candidate.members` (`CandidateRef.members`), so a
-- member assessment of a report collection was refused by the guard. This migration replaces
-- the guard function body only: a `member` subject is also accepted when the revision's form is
-- `collection` and its `candidate.members` array names that exact ref and digest. Every other
-- rule is unchanged: the revision belongs to the assessment's run, the assessor is never the
-- producer, a revision subject binds its exact digest, a set subject binds its exact membership
-- digest and no member producer, and a supersession names an earlier judgment of the same
-- subject. One member's assessment never stands for another (each binds its own ref and
-- digest); fulfillment applies the authored aggregate rule over the standing member judgments.
--
-- No table, column, index, trigger or grant changes; the trigger created by 0056 keeps calling
-- this function, which keeps its owner, `SET search_path = pg_catalog` and revoked PUBLIC
-- EXECUTE. Existing assessment rows are unaffected (the guard runs before insert only).

CREATE OR REPLACE FUNCTION mission_control.output_assessment_subject_guard() RETURNS trigger
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
              OR (NEW.subject_kind = 'member' AND revision.form = 'collection'
                  AND pg_catalog.jsonb_path_exists(
                  revision.candidate, '$.members[*] ? (@.ref == $ref && @.digest == $digest)',
                  pg_catalog.jsonb_build_object('ref', NEW.subject_ref,
                      'digest', NEW.subject_digest)))
          )
    ) THEN
        RAISE EXCEPTION 'an assessment binds an exact revision (or a member its index or '
            'collection lists) of its run and is never made by the producer'
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
