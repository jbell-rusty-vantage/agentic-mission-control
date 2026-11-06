-- Release 1.8.0 candidate (Sprint OC WI-19 / OVE-182; OUTPUT-CONTRACTS §12, ADR-0040, ADR-0061):
-- coordinator attention as separate delivery observations. Unregistered: the integrator builds
-- MC 1.8.0 and registers this file; tests apply it on top of the built release.
--
-- A sealed coordinator notification is attended only when six facts hold, each recorded on its
-- own: notice (the notification row's `sealed_at`), transport, idle-host wake, model-visible
-- payload, acknowledgment (the row's `acknowledged_at`/`acknowledged_by_actor_ref`, explicit
-- only) and content retrieval. This table holds the four that are not on the notification row:
--
-- - `transport` (server): an HTTP or MCP response carried the notification, or a signed webhook
--   attempt answered (`delivered` on 2xx, else `failed` / `dead_lettered`). A 2xx is transport
--   only: from this release on it never acknowledges the notification. Every delivery carries a
--   fresh delivery nonce inside the delivered payload only; this row keeps its sha256 digest.
-- - `wake` and `visible` (host-attested): accepted only when the host echoes the nonce of a
--   delivered transport of the same notification (`transport_key` names it); a visible report
--   needs an earlier wake report. Host `observed_at` is attested data; `received_at` (server)
--   orders the stages.
-- - `retrieval` (server): an explicit bounded-content retrieval for the notification.
--
-- Rows are immutable and idempotent per (notification, stage, observation_key); every key
-- carries the installation/application/tenant scope; forced RLS; the runtime role inserts and
-- reads only.

CREATE TABLE mission_control.coordinator_delivery_observation (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    observation_id uuid PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
    subscription_id uuid NOT NULL,
    notification_id uuid NOT NULL,
    stage text NOT NULL CHECK (stage IN ('transport', 'wake', 'visible', 'retrieval')),
    observation_key text NOT NULL CHECK (observation_key ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$'),
    channel text NOT NULL CHECK (channel IN ('webhook', 'http', 'mcp', 'mcp_hint',
        'background_task_exit', 'monitor_event', 'session_prompt', 'connected_poll',
        'tool_result', 'task_output', 'retrieve')),
    observer text NOT NULL CHECK (observer IN ('server', 'host')),
    result text NOT NULL CHECK (result IN ('delivered', 'failed', 'dead_lettered', 'observed',
        'refused')),
    notice_digest text NOT NULL CHECK (notice_digest ~ '^sha256:[0-9a-f]{64}$'),
    attempt integer CHECK (attempt IS NULL OR attempt >= 1),
    evidence jsonb NOT NULL CHECK (jsonb_typeof(evidence) = 'object'
        AND NOT (evidence ?| ARRAY['credential', 'token', 'authorization', 'secret', 'password'])
        AND pg_catalog.octet_length(evidence::text) <= 16384),
    delivery_nonce_digest text CHECK (delivery_nonce_digest IS NULL
        OR delivery_nonce_digest ~ '^sha256:[0-9a-f]{64}$'),
    transport_key text CHECK (transport_key IS NULL
        OR transport_key ~ '^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$'),
    observed_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    -- Who records which stage, through which channel family.
    CHECK ((stage IN ('transport', 'retrieval')) = (observer = 'server')),
    CHECK (stage <> 'transport' OR channel IN ('webhook', 'http', 'mcp', 'mcp_hint')),
    CHECK (stage <> 'wake' OR channel IN ('background_task_exit', 'monitor_event',
        'session_prompt', 'connected_poll')),
    CHECK (stage <> 'visible' OR channel IN ('tool_result', 'task_output', 'session_prompt')),
    CHECK (stage <> 'retrieval' OR channel = 'retrieve'),
    -- Host stages are observations; a transport attempt is delivered, failed or dead-lettered;
    -- a retrieval is delivered (content returned) or refused (everything omitted).
    CHECK (stage NOT IN ('wake', 'visible') OR result = 'observed'),
    CHECK (stage <> 'transport' OR result IN ('delivered', 'failed', 'dead_lettered')),
    CHECK (stage <> 'retrieval' OR result IN ('delivered', 'refused')),
    CHECK (channel <> 'webhook' OR attempt IS NOT NULL),
    -- A payload delivery carries a nonce; only a transport keeps one; host stages name the
    -- delivered transport whose nonce they echoed.
    CHECK (stage <> 'transport' OR channel = 'mcp_hint' OR delivery_nonce_digest IS NOT NULL),
    CHECK (stage = 'transport' OR delivery_nonce_digest IS NULL),
    CHECK ((stage IN ('wake', 'visible')) = (transport_key IS NOT NULL)),
    UNIQUE (installation_id, application_id, tenant_id, observation_id),
    UNIQUE (installation_id, application_id, tenant_id, notification_id, stage, observation_key),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, subscription_id)
        REFERENCES mission_control.coordinator_inbox
            (installation_id, application_id, tenant_id, subscription_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, notification_id)
        REFERENCES mission_control.coordinator_notification
            (installation_id, application_id, tenant_id, notification_id)
);
CREATE UNIQUE INDEX coordinator_delivery_observation_nonce_idx
    ON mission_control.coordinator_delivery_observation
        (installation_id, application_id, tenant_id, delivery_nonce_digest)
    WHERE delivery_nonce_digest IS NOT NULL;
CREATE INDEX coordinator_delivery_observation_notice_idx
    ON mission_control.coordinator_delivery_observation
        (installation_id, application_id, tenant_id, subscription_id, notification_id, stage);
COMMENT ON TABLE mission_control.coordinator_delivery_observation IS
    'mc.coordinator_delivery_observation.v1: one transport, idle-host wake, model-visible or '
    'retrieval observation of a sealed coordinator notification; immutable, idempotent per key. '
    'Notice and acknowledgment are the notification row''s own sealed/acknowledged facts.';

-- A host or server observation of one notification belongs to that notification's inbox, and
-- only a sealed (pending or acknowledged) notification can be observed.
CREATE FUNCTION mission_control.coordinator_delivery_observation_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
DECLARE
    v_subscription uuid;
    v_state text;
BEGIN
    SELECT notification.subscription_id, notification.state
      INTO v_subscription, v_state
      FROM mission_control.coordinator_notification AS notification
     WHERE notification.installation_id = NEW.installation_id
       AND notification.application_id = NEW.application_id
       AND notification.tenant_id = NEW.tenant_id
       AND notification.notification_id = NEW.notification_id;
    IF v_subscription IS DISTINCT FROM NEW.subscription_id THEN
        RAISE EXCEPTION 'the observation names another inbox than its notification'
            USING ERRCODE = 'check_violation';
    END IF;
    IF v_state NOT IN ('pending', 'acknowledged') THEN
        RAISE EXCEPTION 'only a sealed notification is observed'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.transport_key IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM mission_control.coordinator_delivery_observation AS t
         WHERE t.installation_id = NEW.installation_id
           AND t.application_id = NEW.application_id AND t.tenant_id = NEW.tenant_id
           AND t.notification_id = NEW.notification_id AND t.stage = 'transport'
           AND t.observation_key = NEW.transport_key AND t.result = 'delivered'
           AND t.received_at <= NEW.received_at) THEN
        RAISE EXCEPTION 'a host stage names a delivered transport of its notification'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.stage = 'visible' AND NOT EXISTS (
        SELECT 1 FROM mission_control.coordinator_delivery_observation AS w
         WHERE w.installation_id = NEW.installation_id
           AND w.application_id = NEW.application_id AND w.tenant_id = NEW.tenant_id
           AND w.notification_id = NEW.notification_id AND w.stage = 'wake'
           AND w.received_at <= NEW.received_at) THEN
        RAISE EXCEPTION 'a visible report follows a wake report'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.coordinator_delivery_observation_guard() FROM PUBLIC;
CREATE TRIGGER coordinator_delivery_observation_guard
    BEFORE INSERT ON mission_control.coordinator_delivery_observation
    FOR EACH ROW EXECUTE FUNCTION mission_control.coordinator_delivery_observation_guard();
CREATE TRIGGER coordinator_delivery_observation_immutable
    BEFORE UPDATE OR DELETE ON mission_control.coordinator_delivery_observation
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();

ALTER TABLE mission_control.coordinator_delivery_observation ENABLE ROW LEVEL SECURITY;
ALTER TABLE mission_control.coordinator_delivery_observation FORCE ROW LEVEL SECURITY;
CREATE POLICY coordinator_delivery_observation_scope
    ON mission_control.coordinator_delivery_observation
    USING (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id())
    WITH CHECK (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id());

REVOKE ALL ON mission_control.coordinator_delivery_observation FROM PUBLIC;
GRANT SELECT, INSERT ON mission_control.coordinator_delivery_observation
TO mission_control_runtime;
GRANT SELECT ON mission_control.coordinator_delivery_observation TO mission_control_readonly;
