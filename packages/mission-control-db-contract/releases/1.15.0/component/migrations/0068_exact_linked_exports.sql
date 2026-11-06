-- Exact same-application export snapshots and immutable receiving policy (OC WI-16).
-- Existing links keep their stored explicit cancellation policy and empty transfer policy.
ALTER TABLE mission_control.chain_link
    ADD COLUMN transfer_policy jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(transfer_policy) = 'object');
COMMENT ON COLUMN mission_control.chain_link.transfer_policy IS
    'Immutable receiving purpose, exact selector, placement and coverage policy; empty means legacy packet only.';
ALTER TABLE mission_control.chain_link
    DROP CONSTRAINT chain_link_on_upstream_cancel_check,
    ADD CONSTRAINT chain_link_on_upstream_cancel_check CHECK (
        on_upstream_cancel IN ('cancel_downstream', 'detach', 'continue'));

CREATE OR REPLACE FUNCTION mission_control.chain_link_transition_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'mission_control.chain_link rows are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (NEW.installation_id, NEW.application_id, NEW.tenant_id, NEW.link_id, NEW.chain_id,
        NEW.link_key, NEW.from_mission_key, NEW.to_mission_key, NEW.from_mission_id,
        NEW.to_mission_id, NEW.kind, NEW.bindings, NEW.release_condition,
        NEW.on_upstream_cancel, NEW.on_upstream_not_accepted, NEW.created_at,
        NEW.created_by_actor_ref, NEW.transfer_policy)
       IS DISTINCT FROM
       (OLD.installation_id, OLD.application_id, OLD.tenant_id, OLD.link_id, OLD.chain_id,
        OLD.link_key, OLD.from_mission_key, OLD.to_mission_key, OLD.from_mission_id,
        OLD.to_mission_id, OLD.kind, OLD.bindings, OLD.release_condition,
        OLD.on_upstream_cancel, OLD.on_upstream_not_accepted, OLD.created_at,
        OLD.created_by_actor_ref, OLD.transfer_policy)
       OR NEW.version <> OLD.version + 1
       OR NOT (
           (OLD.state = 'armed' AND NEW.state IN ('released', 'blocked', 'detached', 'cancelled'))
           OR (OLD.state = 'released' AND NEW.state = 'detached')
           -- FT-D2: a link released before its consumer could start (another incoming link
           -- still armed) records the admitted run and packet once, when the last incoming
           -- link releases; nothing else changes.
           OR (OLD.state = 'released' AND NEW.state = 'released'
               AND OLD.released_run_id IS NULL AND NEW.released_run_id IS NOT NULL
               AND NEW.released_at IS NOT DISTINCT FROM OLD.released_at
               AND (OLD.packet_ref IS NULL OR NEW.packet_ref IS NOT DISTINCT FROM OLD.packet_ref)
               AND (OLD.packet_digest IS NULL
                    OR NEW.packet_digest IS NOT DISTINCT FROM OLD.packet_digest))
       )
       OR (OLD.state = 'released' AND NEW.state = 'detached'
           AND (NEW.released_run_id, NEW.released_at, NEW.packet_ref, NEW.packet_digest)
           IS DISTINCT FROM (OLD.released_run_id, OLD.released_at, OLD.packet_ref,
           OLD.packet_digest)) THEN
        RAISE EXCEPTION 'chain links only accept one forward state transition'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION mission_control.chain_link_transition_guard() FROM PUBLIC;

DO $linked_export_contract$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = 'mission_control.runtime_document'::regclass
          AND conname = 'runtime_document_contract_check' AND contype = 'c'
          AND convalidated
          AND pg_catalog.pg_get_constraintdef(oid, true) = 'CHECK (contract = ANY (ARRAY[''goal.revision/1''::text, ''goal.iteration/1''::text, ''goal.handoff/1''::text, ''goal.verification/1''::text, ''goal.template/1''::text, ''stagegraph.template/1''::text, ''operation.binding/1''::text, ''operation.binding-index/1''::text, ''operation.settlement/1''::text, ''operation.claim/1''::text, ''mc.cursor-cost-observation/1''::text]))'
    ) THEN
        RAISE EXCEPTION 'runtime_document contract constraint differs from release 1.9.0'
            USING ERRCODE = 'data_exception';
    END IF;
END
$linked_export_contract$;
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
        'mc.cursor-cost-observation/1',
        'linked.export/1'
    ));

CREATE INDEX runtime_document_linked_receiver_idx
    ON mission_control.runtime_document
    (installation_id, application_id, tenant_id,
     (payload->>'receiver_run_id'), (payload->>'receiver_position'))
    WHERE contract = 'linked.export/1';
COMMENT ON INDEX mission_control.runtime_document_linked_receiver_idx IS
    'Exact released exports for one receiver run and canonical program position.';
