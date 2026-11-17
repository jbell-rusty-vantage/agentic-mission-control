-- MO-52: installation/application provider budgets, with no tenant row enumeration.
CREATE TABLE mission_control.placement_reservation (
    harness_execution_id uuid PRIMARY KEY REFERENCES mission_control.harness_execution(harness_execution_id),
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    lane_profile text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    launched_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX placement_reservation_active ON mission_control.placement_reservation
    (installation_id, application_id, lane_profile, active, launched_at);

CREATE FUNCTION mission_control.placement_definer() RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT EXISTS (
        SELECT 1 FROM pg_catalog.pg_namespace n
        JOIN pg_catalog.pg_roles r ON r.oid = n.nspowner
        WHERE n.nspname = 'mission_control' AND r.rolname = CURRENT_USER
    )
$$;
REVOKE ALL ON FUNCTION mission_control.placement_definer() FROM PUBLIC;
ALTER TABLE mission_control.placement_reservation ENABLE ROW LEVEL SECURITY;
ALTER TABLE mission_control.placement_reservation FORCE ROW LEVEL SECURITY;
CREATE POLICY placement_reservation_definer ON mission_control.placement_reservation
    USING (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND mission_control.placement_definer())
    WITH CHECK (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND mission_control.placement_definer());
REVOKE ALL ON mission_control.placement_reservation FROM PUBLIC,
    mission_control_runtime, mission_control_readonly, mission_control_ingress;

CREATE FUNCTION mission_control.placement_reserve(
    p_execution uuid, p_profile text, p_max_active integer, p_launches_per_minute integer
) RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog AS $$
DECLARE
    tenant uuid := mission_control.ctx_tenant_id();
    installation uuid := mission_control.ctx_installation_id();
    application text := mission_control.ctx_application_id();
    current_at timestamptz := pg_catalog.clock_timestamp();
    active_count bigint;
    launch_count bigint;
BEGIN
    IF tenant IS NULL OR installation IS NULL OR application IS NULL
        OR p_max_active IS NULL OR p_max_active NOT BETWEEN 1 AND 1000
        OR (p_launches_per_minute IS NOT NULL AND p_launches_per_minute NOT BETWEEN 1 AND 10000)
    THEN RAISE EXCEPTION 'invalid placement admission context'; END IF;
    IF NOT EXISTS (SELECT 1 FROM mission_control.harness_execution
        WHERE installation_id = installation AND application_id = application AND tenant_id = tenant
        AND harness_execution_id = p_execution AND lane_profile = p_profile)
    THEN RAISE EXCEPTION 'placement harness execution is not admitted in this scope'; END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'placement:' || installation::text || ':' || application || ':' || p_profile, 0));
    IF EXISTS (SELECT 1 FROM mission_control.placement_reservation
        WHERE harness_execution_id = p_execution AND active)
    THEN RETURN true; END IF;
    SELECT count(*) FILTER (WHERE active),
        count(*) FILTER (WHERE launched_at > current_at - interval '1 minute')
    INTO active_count, launch_count FROM mission_control.placement_reservation
    WHERE installation_id = installation AND application_id = application AND lane_profile = p_profile;
    IF active_count >= p_max_active OR
        (p_launches_per_minute IS NOT NULL AND launch_count >= p_launches_per_minute)
    THEN RETURN false; END IF;
    INSERT INTO mission_control.placement_reservation
        (harness_execution_id, installation_id, application_id, tenant_id, lane_profile, active, launched_at)
    VALUES (p_execution, installation, application, tenant, p_profile, true, current_at)
    ON CONFLICT (harness_execution_id) DO UPDATE SET active = true, launched_at = EXCLUDED.launched_at;
    RETURN true;
END
$$;

CREATE FUNCTION mission_control.placement_release(p_execution uuid) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    UPDATE mission_control.placement_reservation SET active = false
    WHERE harness_execution_id = p_execution
        AND installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id();
END
$$;
REVOKE ALL ON FUNCTION mission_control.placement_reserve(uuid,text,integer,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION mission_control.placement_release(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mission_control.placement_reserve(uuid,text,integer,integer)
    TO mission_control_runtime;
GRANT EXECUTE ON FUNCTION mission_control.placement_release(uuid) TO mission_control_runtime;
