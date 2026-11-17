-- Release 1.4.1: append immutable Cursor cost observations to runtime_document.
-- Preserve all ten existing contracts and every other constraint, policy, trigger and grant.
DO $cursor_cost_contract$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = 'mission_control.runtime_document'::regclass
          AND conname = 'runtime_document_contract_check' AND contype = 'c'
          AND convalidated
          AND pg_catalog.pg_get_constraintdef(oid, true) = 'CHECK (contract = ANY (ARRAY[''goal.revision/1''::text, ''goal.iteration/1''::text, ''goal.handoff/1''::text, ''goal.verification/1''::text, ''goal.template/1''::text, ''stagegraph.template/1''::text, ''operation.binding/1''::text, ''operation.binding-index/1''::text, ''operation.settlement/1''::text, ''operation.claim/1''::text]))'
    ) THEN
        RAISE EXCEPTION 'runtime_document contract constraint differs from release 1.4.0'
            USING ERRCODE = 'data_exception';
    END IF;
END
$cursor_cost_contract$;
ALTER TABLE mission_control.runtime_document
    DROP CONSTRAINT runtime_document_contract_check,
    ADD CONSTRAINT runtime_document_contract_check CHECK (contract IN (
        'goal.revision/1',
        'goal.iteration/1',
        'goal.handoff/1',
        'goal.verification/1',
        'goal.template/1',
        'stagegraph.template/1',
        'operation.binding/1',
        'operation.binding-index/1',
        'operation.settlement/1',
        'operation.claim/1',
        'mc.cursor-cost-observation/1'
    ));
