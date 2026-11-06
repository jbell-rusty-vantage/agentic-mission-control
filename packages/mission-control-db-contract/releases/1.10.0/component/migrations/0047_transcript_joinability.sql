-- Release 1.4.4 (provider consolidation, P1 deep_agents Stage 1, TRACING-PROPOSAL §P2):
-- joinability of the Transcript's sources, the new frame kinds, the retention classes and
-- the reserved pruning columns. Additive; every previously valid row stays valid.
--
-- 1. mission_event: the unit and the point an event belongs to (NULL before 1.4.4).
--    The immutable trigger forbids UPDATE, not ALTER; writers fill the columns at insert.
ALTER TABLE mission_control.mission_event
    ADD COLUMN IF NOT EXISTS unit_key text
        CHECK (unit_key IS NULL OR unit_key ~ '^bl-unit-v1:[0-9a-f]{64}$'),
    ADD COLUMN IF NOT EXISTS point_ref jsonb
        CHECK (point_ref IS NULL OR jsonb_typeof(point_ref) = 'object');
CREATE INDEX mission_event_run_unit_idx ON mission_control.mission_event
    (installation_id, application_id, tenant_id, run_id, unit_key, seq)
    WHERE unit_key IS NOT NULL;

-- 2. cognition_point: subagent points, the restore level as a column, and the pruning
--    reservation (TR-D17: columns only; no writer this release). The guard trigger of 0045
--    keeps identity fixed and forbids DELETE; it is unchanged.
ALTER TABLE mission_control.cognition_point
    ADD COLUMN IF NOT EXISTS subordinate_ref text
        CHECK (subordinate_ref IS NULL OR subordinate_ref <> ''),
    ADD COLUMN IF NOT EXISTS restore_level text NOT NULL DEFAULT 'R3'
        CHECK (restore_level IN ('R0', 'R1', 'R2', 'R3')),
    ADD COLUMN IF NOT EXISTS pruned_at timestamptz,
    ADD COLUMN IF NOT EXISTS prune_policy text
        CHECK (prune_policy IS NULL OR prune_policy <> '');
GRANT UPDATE (subordinate_ref, restore_level, pruned_at, prune_policy)
    ON mission_control.cognition_point TO mission_control_runtime;

-- 3. provider_frame: the new kinds (`model_request`, `environment_materialized`,
--    `subagent_started`, `subagent_ended`, `progress_note`), the closing rule with
--    `subagent_ended`, and the retention class derived from the kind. The kind rule is the
--    inline column CHECK (auto-named by 0027); the closing rule is an unnamed table CHECK,
--    located through pg_constraint and replaced by a named one.
ALTER TABLE mission_control.provider_frame
    DROP CONSTRAINT provider_frame_kind_check,
    ADD CONSTRAINT provider_frame_kind_check CHECK (kind IN (
        'session_init', 'session_state', 'turn_started', 'message_delta', 'message',
        'thinking_delta', 'tool_call_started', 'tool_call_delta', 'tool_call_completed',
        'tool_call_failed', 'approval_requested', 'approval_resolved', 'hook_invoked',
        'hook_result', 'before_compaction', 'after_compaction', 'usage', 'turn_ended',
        'run_result', 'status', 'error', 'heartbeat', 'unknown',
        'model_request', 'environment_materialized', 'subagent_started', 'subagent_ended',
        'progress_note'));
DO $closing$
DECLARE
    old_name text;
BEGIN
    SELECT conname INTO old_name
    FROM pg_catalog.pg_constraint
    WHERE conrelid = 'mission_control.provider_frame'::regclass
      AND contype = 'c'
      AND pg_catalog.pg_get_constraintdef(oid) LIKE '%closing = (kind%';
    IF old_name IS NULL THEN
        RAISE EXCEPTION 'provider_frame closing rule of 0027 is missing';
    END IF;
    EXECUTE pg_catalog.format(
        'ALTER TABLE mission_control.provider_frame DROP CONSTRAINT %I', old_name);
END
$closing$;
ALTER TABLE mission_control.provider_frame ADD CONSTRAINT provider_frame_closing_rule
    CHECK (closing = (kind IN (
        'tool_call_completed', 'tool_call_failed', 'approval_resolved', 'hook_result',
        'after_compaction', 'usage', 'turn_ended', 'run_result', 'session_state', 'error',
        'subagent_ended')));
-- Generated from the kind, so no backfill and no conflict with the immutable trigger.
ALTER TABLE mission_control.provider_frame
    ADD COLUMN IF NOT EXISTS retention_class text GENERATED ALWAYS AS (
        CASE WHEN kind IN ('message_delta', 'thinking_delta', 'tool_call_delta', 'heartbeat', 'status')
             THEN 'delta' ELSE 'step' END) STORED;
CREATE INDEX provider_frame_delta_expiry_idx ON mission_control.provider_frame
    (installation_id, application_id, tenant_id, observed_at)
    WHERE retention_class = 'delta';

-- 4. frame_retention_policy: `retain_days` now governs the delta class; step frames live for
--    the mission's evidence life unless `step_retain_days` is set (TR-D1); `prune_mode` is
--    reserved for the pruning session (TR-D17).
ALTER TABLE mission_control.frame_retention_policy
    ADD COLUMN IF NOT EXISTS step_retain_days integer
        CHECK (step_retain_days IS NULL OR step_retain_days >= 30),
    ADD COLUMN IF NOT EXISTS prune_mode text NOT NULL DEFAULT 'delete'
        CHECK (prune_mode IN ('delete', 'tombstone'));

-- The expiry function keeps its signature (the retention job calls it) and is narrowed to the
-- delta class: a step frame is never deleted by the delta clock. Deltas never close, so the
-- returned flag is always false; `p_keep_closing` is honoured for compatibility.
CREATE OR REPLACE FUNCTION mission_control.expire_provider_frames(
    p_cutoff timestamptz, p_keep_closing boolean
) RETURNS TABLE (expired_closing boolean)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DELETE FROM mission_control.provider_frame AS f
    WHERE f.installation_id = mission_control.ctx_installation_id()
      AND f.application_id = mission_control.ctx_application_id()
      AND f.tenant_id = mission_control.ctx_tenant_id()
      AND f.retention_class = 'delta'
      AND f.observed_at < p_cutoff
      AND (NOT f.closing OR NOT p_keep_closing)
    RETURNING f.closing
$$;
-- Step frames expire only when the application set `step_retain_days`, only for terminal
-- runs, and (TR-D17, later) never for pinned points: until pins exist the caller passes the
-- cutoff the policy yields and the function restricts itself to completed runs.
CREATE FUNCTION mission_control.expire_step_provider_frames(
    p_cutoff timestamptz
) RETURNS TABLE (expired_frame_id uuid)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $$
    DELETE FROM mission_control.provider_frame AS f
    USING mission_control.mission_run AS r
    WHERE f.installation_id = mission_control.ctx_installation_id()
      AND f.application_id = mission_control.ctx_application_id()
      AND f.tenant_id = mission_control.ctx_tenant_id()
      AND r.installation_id = f.installation_id
      AND r.application_id = f.application_id
      AND r.tenant_id = f.tenant_id
      AND r.run_id = f.run_id
      AND r.lifecycle = 'completed'
      AND f.retention_class = 'step'
      AND f.observed_at < p_cutoff
    RETURNING f.frame_id
$$;
REVOKE ALL ON FUNCTION mission_control.expire_step_provider_frames(timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mission_control.expire_step_provider_frames(timestamptz)
TO mission_control_runtime;

-- 5. mission_run: the runtime fills the Temporal ids once at launch (F-T4-2). The runtime
--    role already holds table UPDATE from 0010; the column grant documents the intent.
GRANT UPDATE (temporal_workflow_id, temporal_run_id)
    ON mission_control.mission_run TO mission_control_runtime;

-- 6. completion tables (0003): the family writer inserts decisions and candidates inside the
--    family transaction; the runtime inserts candidates at settlement; readers read. No grant
--    existed before 1.4.4 (verified against 0003 and 0012).
GRANT SELECT, INSERT ON mission_control.completion_candidate, mission_control.completion_decision
TO mission_control_runtime, mission_control_family_writer;
-- The candidate names its activation by key; the family writer resolves the id in the same
-- transaction (0012 granted activation reads to the runtime and readonly roles only).
GRANT SELECT ON mission_control.activation TO mission_control_family_writer;
GRANT SELECT ON mission_control.completion_candidate, mission_control.completion_decision
TO mission_control_readonly;
