-- Release 1.9.0 (Sprint OC W1 / OVE-169, defect D22): the durable handle table records every
-- knowledge operation Mission Control receives a K01 handle for, including the trusted
-- assessment operations.
--
-- Release 1.6.0 (0055) created `knowledge_operation_handle` before the trusted judgment path
-- (Sprint OC WI-03) existed, so its operation check names only knowledge.read, knowledge.apply,
-- report.register, report.assess, report.derive and verify.claims. The trusted bridge records a
-- handle for every assessment operation it dispatches (`KnowledgeGateway.trusted`): KS accepted
-- the live auditor census (`report.observe`) and answered a handle, and recording it failed with
-- `knowledge_operation_handle_operation_check` (W1 session 6, runs 042beb7a and 29a1eae9), so no
-- KS-accepted observation, seal, decision, review or resolution could be stored.
--
-- The new check is the exact set of operations whose handle Mission Control records, derived
-- from the code that writes this table (`application/knowledge/gateway.py`):
--   * `_effect` records the handle of an effectful operation that answers one:
--     knowledge.apply, report.register (`EFFECTFUL_OPERATIONS`);
--   * `_handle_operation` records the non-effect handle operations
--     (`NON_EFFECT_HANDLE_OPERATIONS` = `HANDLE_OPERATIONS` minus the effects, plus
--     knowledge.read): report.assess, report.derive, verify.claims, report.observe, report.seal,
--     report.decide, report.review, decision.resolve, knowledge.read;
--   * `trusted` records knowledge.read (the evaluator's `evaluation-context-read`) and every
--     `ASSESSMENT_CONTRACTS` operation: report.observe, report.seal, report.decide,
--     report.review, decision.resolve.
-- This equals the KS protocol's `HANDLE_OPERATIONS` plus its two receipt-or-handle effects
-- (knowledge-operation-protocol `envelope.ts`). The four control operations (knowledge.describe,
-- operation.get, operation.cancel, receipt.get) never answer a handle and stay refused.
--
-- Additive to stored data: the new set is a strict superset, so every existing row satisfies it
-- and the constraint is validated in place. The effect-key rule (an effect's handle names its
-- effect key, a non-effect handle names none), the guard trigger, row security and grants are
-- unchanged.

ALTER TABLE mission_control.knowledge_operation_handle
    DROP CONSTRAINT knowledge_operation_handle_operation_check;
ALTER TABLE mission_control.knowledge_operation_handle
    ADD CONSTRAINT knowledge_operation_handle_operation_check CHECK (operation IN (
        'knowledge.read', 'knowledge.apply', 'report.register', 'report.assess',
        'report.derive', 'verify.claims', 'report.observe', 'report.seal', 'report.decide',
        'report.review', 'decision.resolve'));
