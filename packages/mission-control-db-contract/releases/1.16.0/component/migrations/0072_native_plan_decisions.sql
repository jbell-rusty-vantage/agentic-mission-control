-- Release 2.0.0 candidate (Sprint OC W1 native write; OUTPUT-CONTRACTS §5, ADR-0059/0060):
-- plan-level use decisions recorded inside the invocation that applies them. Unregistered;
-- authored as 0069 against 1.9.0, renumbered 0072 on 2026-11-01 (OVE-206) because built releases
-- 1.10.0-1.12.0 took keys 0068-0070.
--
-- A native write's KS decision binds the exact native digest of the applying invocation (the
-- AIDB plan binds the originating origin; the gateway accepts only that originator), so the host
-- derives, previews, decides, records and applies inside ONE invocation, or, when the decision
-- waits on a qualified review, in that same invocation's saved-result settlement pass (same
-- origin identity). The recorded decision therefore names:
--   subject_ref    the exact report revision it decides over (`<report handle>#<digest>`);
--   invocation_ref the invocation whose origin the decision's bound digest binds (the only one
--                  that may apply it, from its own tool call or its settlement pass);
--   decision_digest the exact KS decision record digest (its resolution names it exactly).
-- All three are nullable (decisions recorded before this release keep NULL) and immutable with the
-- row (the 0059 reject_mutation trigger still forbids UPDATE and DELETE).
--
-- The read-only KS `knowledge.plan_preview` answers in the same call and records no handle, so
-- the handle operation check is unchanged.

ALTER TABLE mission_control.knowledge_use_decision
    ADD COLUMN subject_ref text CHECK (subject_ref IS NULL
        OR (subject_ref <> '' AND length(subject_ref) <= 2048)),
    ADD COLUMN invocation_ref text CHECK (invocation_ref IS NULL
        OR (invocation_ref <> '' AND length(invocation_ref) <= 512)),
    ADD COLUMN decision_digest text CHECK (decision_digest IS NULL
        OR decision_digest ~ '^sha256:[0-9a-f]{64}$'),
    ADD CONSTRAINT knowledge_use_decision_native_columns CHECK (
        (subject_ref IS NULL) = (invocation_ref IS NULL)
        AND (subject_ref IS NULL) = (decision_digest IS NULL));

CREATE INDEX knowledge_use_decision_subject_idx ON mission_control.knowledge_use_decision
    (installation_id, application_id, tenant_id, subject_ref) WHERE subject_ref IS NOT NULL;
CREATE INDEX knowledge_use_decision_invocation_idx ON mission_control.knowledge_use_decision
    (installation_id, application_id, tenant_id, invocation_ref) WHERE invocation_ref IS NOT NULL;
