-- Release 1.4.3 (provider consolidation, P1 deep_agents turn 4): the cognition coordinate.
-- One `cognition_point` row per observable point of a unit generation (a LangGraph root
-- checkpoint on the Deep Agents lane; a session cursor, thread item or workspace snapshot on
-- the other lanes), relating the Temporal activity attempt that wrote it, the session turn and
-- frame range it covers, and the redacted facts of the state at that point
-- (`mc.cognition_point.v1`). Written by the lane adapter at settlement, enriched by the frame
-- writer, re-derived by the reconciler, and seeded by a fork. Never deleted by the runtime.
-- Also: `session_turn.point_ref` (the turn's result point), `activity_attempt_observation.task_queue`
-- (the queue the attempt ran on) and the runtime grant to fill `agent_session.checkpoint_namespace`.

CREATE TABLE mission_control.cognition_point (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    point_id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    unit_key text NOT NULL CHECK (unit_key ~ '^bl-unit-v1:[0-9a-f]{64}$'),
    execution_generation bigint NOT NULL CHECK (execution_generation >= 1),
    -- Denormalized unit location so a coordinator filters by stage, iteration and cycle:
    -- node_key is the stage id or the goal role; iteration is the workflow cycle ordinal or
    -- the goal iteration; cycle is the stage cycle ordinal (0 for Goal Directed).
    family text NOT NULL CHECK (family IN ('stage_graph', 'goal_directed')),
    node_key text NOT NULL CHECK (node_key <> ''),
    iteration bigint NOT NULL CHECK (iteration >= 0),
    cycle bigint NOT NULL CHECK (cycle >= 0),
    session_generation bigint CHECK (session_generation IS NULL OR session_generation >= 1),
    lane_profile text NOT NULL REFERENCES mission_control.lane_profile (lane_profile),
    point_kind text NOT NULL
        CHECK (point_kind IN ('checkpoint', 'session_cursor', 'thread_item', 'workspace_snapshot')),
    point_locator text NOT NULL CHECK (point_locator <> '' AND length(point_locator) <= 1024),
    point_ref jsonb NOT NULL CHECK (jsonb_typeof(point_ref) = 'object'),
    parent_point_id uuid,
    -- A point whose predecessor lives in another thread or run (a session rollover, a fork
    -- seed): the coordinate it continues from, when no row in this run is its parent.
    parent_coordinate jsonb CHECK (parent_coordinate IS NULL OR jsonb_typeof(parent_coordinate) = 'object'),
    ordinal bigint,
    source text CHECK (source IS NULL OR (source <> '' AND length(source) <= 64)),
    roles text[] NOT NULL DEFAULT '{}'::text[],
    harness_execution_id uuid,
    turn_id uuid,
    turn_no bigint CHECK (turn_no IS NULL OR turn_no > 0),
    activity_attempt_observation_id uuid,
    temporal_workflow_id text CHECK (temporal_workflow_id IS NULL OR temporal_workflow_id <> ''),
    temporal_run_id text CHECK (temporal_run_id IS NULL OR temporal_run_id <> ''),
    temporal_activity_id text CHECK (temporal_activity_id IS NULL OR temporal_activity_id <> ''),
    activity_attempt bigint CHECK (activity_attempt IS NULL OR activity_attempt >= 1),
    task_queue text CHECK (task_queue IS NULL OR task_queue <> ''),
    frame_from_ordinal bigint CHECK (frame_from_ordinal IS NULL OR frame_from_ordinal > 0),
    frame_to_ordinal bigint CHECK (frame_to_ordinal IS NULL OR frame_to_ordinal > 0),
    message_count integer CHECK (message_count IS NULL OR message_count >= 0),
    channel_facts jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(channel_facts) = 'object'),
    files_digest text CHECK (files_digest IS NULL OR files_digest ~ '^sha256:[0-9a-f]{64}$'),
    usage_delta jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(usage_delta) = 'object'),
    budget_snapshot jsonb CHECK (budget_snapshot IS NULL OR jsonb_typeof(budget_snapshot) = 'object'),
    workspace_checkpoint_ref text CHECK (workspace_checkpoint_ref IS NULL OR workspace_checkpoint_ref <> ''),
    seedable boolean NOT NULL DEFAULT false,
    written_by text NOT NULL CHECK (written_by IN ('adapter', 'frame_writer', 'reconciler', 'fork_seed')),
    record jsonb NOT NULL CHECK ((jsonb_typeof(record) = 'object'
        AND record->>'schema_version' = 'mc.cognition_point.v1') IS TRUE),
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    recorded_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    CHECK (updated_at >= created_at),
    CHECK (frame_from_ordinal IS NULL OR frame_to_ordinal IS NULL OR frame_to_ordinal >= frame_from_ordinal),
    UNIQUE (installation_id, application_id, tenant_id, point_id),
    UNIQUE (installation_id, application_id, tenant_id, unit_key, execution_generation, point_kind, point_locator),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, run_id)
        REFERENCES mission_control.mission_run (installation_id, application_id, tenant_id, run_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, parent_point_id)
        REFERENCES mission_control.cognition_point (installation_id, application_id, tenant_id, point_id)
);

CREATE INDEX cognition_point_run_location_idx
    ON mission_control.cognition_point
    (installation_id, application_id, tenant_id, run_id, family, node_key, iteration, cycle, ordinal);
CREATE INDEX cognition_point_unit_idx
    ON mission_control.cognition_point
    (installation_id, application_id, tenant_id, unit_key, execution_generation, ordinal);
CREATE INDEX cognition_point_run_recorded_idx
    ON mission_control.cognition_point
    (installation_id, application_id, tenant_id, run_id, recorded_at);

-- Guard: the point's identity never changes, versions advance by one, time never moves
-- back, and nothing deletes a point (retention is a later, governed job).
CREATE FUNCTION mission_control.cognition_point_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'cognition_point rows are never deleted'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.point_id <> OLD.point_id OR NEW.run_id <> OLD.run_id OR NEW.unit_key <> OLD.unit_key
       OR NEW.execution_generation <> OLD.execution_generation OR NEW.point_kind <> OLD.point_kind
       OR NEW.point_locator <> OLD.point_locator OR NEW.point_ref <> OLD.point_ref
       OR NEW.lane_profile <> OLD.lane_profile OR NEW.family <> OLD.family
       OR NEW.node_key <> OLD.node_key OR NEW.iteration <> OLD.iteration OR NEW.cycle <> OLD.cycle
       OR NEW.created_at <> OLD.created_at OR NEW.created_by_actor_ref <> OLD.created_by_actor_ref THEN
        RAISE EXCEPTION 'cognition_point identity is fixed'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'cognition_point version must advance by one'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'cognition_point updated_at never moves back'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.cognition_point_guard() FROM PUBLIC;
CREATE TRIGGER cognition_point_guard
    BEFORE UPDATE OR DELETE ON mission_control.cognition_point
    FOR EACH ROW EXECUTE FUNCTION mission_control.cognition_point_guard();

ALTER TABLE mission_control.cognition_point ENABLE ROW LEVEL SECURITY;
ALTER TABLE mission_control.cognition_point FORCE ROW LEVEL SECURITY;
CREATE POLICY cognition_point_scope ON mission_control.cognition_point
    USING (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id())
    WITH CHECK (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id());

REVOKE ALL ON mission_control.cognition_point FROM PUBLIC;
GRANT SELECT, INSERT ON mission_control.cognition_point TO mission_control_runtime;
GRANT UPDATE (parent_point_id, parent_coordinate, roles, harness_execution_id, turn_id, turn_no,
    activity_attempt_observation_id, temporal_workflow_id, temporal_run_id, temporal_activity_id,
    activity_attempt, task_queue, frame_from_ordinal, frame_to_ordinal, message_count,
    channel_facts, files_digest, usage_delta, budget_snapshot, workspace_checkpoint_ref,
    seedable, written_by, record, version, updated_at)
ON mission_control.cognition_point TO mission_control_runtime;
GRANT SELECT ON mission_control.cognition_point TO mission_control_readonly;

-- The session turn's result point, the attempt's task queue, and the session's checkpoint
-- namespace column the frame writer now fills (additive; NULL before 1.4.3).
ALTER TABLE mission_control.session_turn
    ADD COLUMN IF NOT EXISTS point_ref jsonb
        CHECK (point_ref IS NULL OR jsonb_typeof(point_ref) = 'object');
ALTER TABLE mission_control.activity_attempt_observation
    ADD COLUMN IF NOT EXISTS task_queue text CHECK (task_queue IS NULL OR task_queue <> '');
GRANT UPDATE (checkpoint_namespace) ON mission_control.agent_session TO mission_control_runtime;
