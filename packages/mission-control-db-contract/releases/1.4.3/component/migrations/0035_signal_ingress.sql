-- mission-control-db-contract: MO-40 Signal Ingress (materialization-observation SPEC-10
-- section 3, SPEC-04 section 3, R29; ADR-0045 proposed, ADR-0043). Extends 0001, 0003, 0029
-- and 0030. Additive only: no existing table, row, policy or grant changes. Depends on no
-- object created after 0034.
--
-- The public edge verifies callers and records what they sent; it decides nothing beyond a
-- gate answer computed here. It connects as a login that is a member of the NOLOGIN role
-- `mission_control_ingress`, which holds no table grant at all: it may only EXECUTE the
-- SECURITY DEFINER functions below, one call (one round trip, one transaction) per request.
--
-- 1. Role `mission_control_ingress` (guarded like the 0001 capability roles).
-- 2. Tables:
--    - `ingress_credential`: minted credentials by digest only (ADR-0043 `MintedCredential`):
--      purpose `signal_token` (the `run_token` tier, bound to run, unit and generation) or
--      `mission_request` (the operator launch credential, R29, bound to the tenant scope and
--      optionally a manifest set in `context.manifest_refs`), with a fixed 60 s rate window.
--    - `ingress_session_binding`: a provider session bound to one run generation. The
--      `provider_oidc` tier (Cursor `cloud_agent_id`) is bound by the worker at launch; the
--      `environment_key` tier is registered with the run nonce's digest and bound by the
--      first `session.started` signal that presents that nonce.
--    - `ingress_inbox`: append-only accepted messages, drained by the worker (row contract
--      below). An AFTER INSERT trigger notifies `mc_ingress`.
--    - `ingress_artifact_upload`: quarantine upload slots (prepare, then commit).
-- 3. SECURITY DEFINER functions (`SET search_path = pg_catalog`): `ingress_accept`,
--    `ingress_gate`, `ingress_webhook`, `ingress_artifact_prepare`, `ingress_artifact_commit`,
--    `ingress_mission_request` and `ingress_mission_request_status`. Each one binds the
--    transaction scope itself at entry (a caller's own `mc.*` settings never reach its
--    queries) and then from the credential it resolves. The scope stays bound until the
--    caller's transaction ends; the only role that can call these functions holds no table
--    grant, so it can do nothing with it.
--
-- Inbox row contract (consumed by the IngressDrainer, SPEC-10 section 4):
--   * wake: `LISTEN mc_ingress`; payload `{"scope": "mc/<installation>/<application>/<tenant
--     or empty>", "ingress_id": <uuid>, "kind": <kind>}`; poll every 5 s as the fallback;
--   * claim: as `mission_control_runtime` under the binding's scope,
--     `SELECT ... FROM mission_control.ingress_inbox WHERE state = 'pending'
--      ORDER BY received_at, ingress_id FOR UPDATE SKIP LOCKED LIMIT 100`. A provider
--     webhook row has no tenant (`tenant_id IS NULL`, `trust_tier = 'provider_signed'`) until
--     the drainer resolves the provider session; every scope of the application sees it;
--   * kinds: `signal.<type>` and `gate.decision` (frames; `provider_key =
--     ingress:<credential_ref>:<dedupe_space>:<dedupe_key>`, since a key is unique only within
--     its `dedupe_space`), `webhook.<provider>` (wake, reconcile from
--     history; the payload is never trusted), `artifact.committed` (custody), and
--     `mission_request` (admission through the application handler);
--   * settle: only a `pending` row moves, once, to `drained` (`outcome` optional; a
--     `mission_request` records `{"mission_id": ...}`), `rejected` (`outcome.reason`, a typed
--     refusal) or `dead` (after N failures); `drained_at` is set exactly when it leaves
--     `pending`. A failure that is retried only increments `attempts` and sets `last_error`.
--     Nothing else in a row changes and no row is deleted.

-- ---------------------------------------------------------------------------------------
-- section: role
DO $role$
DECLARE
    existing record;
BEGIN
    SELECT rolsuper, rolbypassrls, rolcanlogin, rolcreaterole, rolcreatedb
      INTO existing FROM pg_catalog.pg_roles WHERE rolname = 'mission_control_ingress';
    IF FOUND THEN
        IF existing.rolsuper OR existing.rolbypassrls OR existing.rolcanlogin
           OR existing.rolcreaterole OR existing.rolcreatedb THEN
            RAISE EXCEPTION 'existing role mission_control_ingress is not a restricted NOLOGIN role';
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_catalog.pg_auth_members m
            JOIN pg_catalog.pg_roles r ON r.oid = m.member
            WHERE r.rolname = 'mission_control_ingress'
        ) THEN
            RAISE EXCEPTION 'existing role mission_control_ingress is a member of another role';
        END IF;
    ELSE
        CREATE ROLE mission_control_ingress
            NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END
$role$;
GRANT USAGE ON SCHEMA mission_control TO mission_control_ingress;
-- end section: role

-- ---------------------------------------------------------------------------------------
-- section: tables
CREATE TABLE mission_control.ingress_credential (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    credential_id uuid PRIMARY KEY,
    purpose text NOT NULL CHECK (purpose IN ('signal_token', 'mission_request')),
    credential_hash text NOT NULL UNIQUE CHECK (credential_hash ~ '^sha256:[0-9a-f]{64}$'),
    run_key text CHECK (run_key <> ''),
    unit_key text CHECK (unit_key <> '' AND length(unit_key) <= 512),
    generation integer CHECK (generation >= 1),
    scopes text[] NOT NULL
        CHECK (cardinality(scopes) BETWEEN 1 AND 16 AND array_position(scopes, NULL) IS NULL),
    context jsonb NOT NULL CHECK (jsonb_typeof(context) = 'object'
        AND NOT (context ?| ARRAY['secret', 'secret_value', 'password', 'token'])),
    rate_limit integer NOT NULL CHECK (rate_limit BETWEEN 1 AND 100000),
    rate_window_started_at timestamptz NOT NULL,
    rate_window_count integer NOT NULL CHECK (rate_window_count >= 0),
    issued_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    CHECK (expires_at > issued_at),
    CHECK (revoked_at IS NULL OR revoked_at >= issued_at),
    CHECK ((run_key IS NULL) = (unit_key IS NULL) AND (run_key IS NULL) = (generation IS NULL)),
    CHECK ((purpose = 'signal_token') = (run_key IS NOT NULL)),
    UNIQUE (installation_id, application_id, tenant_id, credential_id),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, run_key)
        REFERENCES mission_control.mission_run (installation_id, application_id, tenant_id, run_key)
);
CREATE INDEX ingress_credential_run_idx ON mission_control.ingress_credential
    (installation_id, application_id, tenant_id, run_key, unit_key, generation)
    WHERE revoked_at IS NULL;

CREATE TABLE mission_control.ingress_session_binding (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    session_binding_id uuid PRIMARY KEY,
    trust_tier text NOT NULL CHECK (trust_tier IN ('provider_oidc', 'environment_key')),
    provider text NOT NULL CHECK (provider ~ '^[a-z][a-z0-9_]{0,63}$'),
    environment_ref text CHECK (environment_ref <> '' AND length(environment_ref) <= 512),
    session_id text CHECK (session_id <> '' AND length(session_id) <= 512),
    nonce_hash text CHECK (nonce_hash ~ '^sha256:[0-9a-f]{64}$'),
    run_key text NOT NULL CHECK (run_key <> ''),
    unit_key text NOT NULL CHECK (unit_key <> '' AND length(unit_key) <= 512),
    generation integer NOT NULL CHECK (generation >= 1),
    context jsonb NOT NULL CHECK (jsonb_typeof(context) = 'object'
        AND NOT (context ?| ARRAY['secret', 'secret_value', 'password', 'token'])),
    rate_limit integer NOT NULL CHECK (rate_limit BETWEEN 1 AND 100000),
    rate_window_started_at timestamptz NOT NULL,
    rate_window_count integer NOT NULL CHECK (rate_window_count >= 0),
    created_at timestamptz NOT NULL,
    bound_at timestamptz,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_by_actor_ref text NOT NULL CHECK (created_by_actor_ref <> ''),
    CHECK (expires_at > created_at),
    CHECK ((session_id IS NULL) = (bound_at IS NULL)),
    CHECK (session_id IS NOT NULL OR nonce_hash IS NOT NULL),
    CHECK (trust_tier <> 'environment_key'
        OR (nonce_hash IS NOT NULL AND environment_ref IS NOT NULL)),
    UNIQUE (installation_id, application_id, provider, session_id),
    UNIQUE (installation_id, application_id, provider, nonce_hash),
    UNIQUE (installation_id, application_id, tenant_id, session_binding_id),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, run_key)
        REFERENCES mission_control.mission_run (installation_id, application_id, tenant_id, run_key)
);
CREATE INDEX ingress_session_binding_run_idx ON mission_control.ingress_session_binding
    (installation_id, application_id, tenant_id, run_key, unit_key, generation)
    WHERE revoked_at IS NULL;

CREATE TABLE mission_control.ingress_inbox (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid,
    ingress_id uuid PRIMARY KEY,
    received_at timestamptz NOT NULL,
    trust_tier text NOT NULL CHECK (trust_tier IN ('run_token', 'provider_oidc',
        'environment_key', 'provider_signed', 'launch_token')),
    kind text NOT NULL CHECK (kind ~ '^signal\.[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$'
        OR kind IN ('gate.decision', 'artifact.committed', 'mission_request',
                    'webhook.anthropic', 'webhook.openai', 'webhook.cursor', 'webhook.github')),
    credential_ref text NOT NULL CHECK (credential_ref <> '' AND length(credential_ref) <= 600),
    dedupe_key text NOT NULL CHECK (dedupe_key <> '' AND length(dedupe_key) <= 256),
    -- Each kind of message dedupes in its own space: every signal type shares `signal`, and
    -- any other kind is its own space, so a client's signal id never collides with a gate
    -- decision, a committed artifact or a launch request of the same credential.
    dedupe_space text NOT NULL GENERATED ALWAYS AS (
        CASE WHEN kind LIKE 'signal.%' THEN 'signal' ELSE kind END) STORED,
    body_sha256 text NOT NULL CHECK (body_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    payload jsonb NOT NULL
        CHECK (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 262144),
    seq bigint CHECK (seq >= 0),
    run_key text CHECK (run_key <> ''),
    unit_key text CHECK (unit_key <> '' AND length(unit_key) <= 512),
    generation integer CHECK (generation >= 1),
    state text NOT NULL CHECK (state IN ('pending', 'drained', 'rejected', 'dead')),
    attempts integer NOT NULL CHECK (attempts >= 0),
    drained_at timestamptz,
    outcome jsonb CHECK (outcome IS NULL OR jsonb_typeof(outcome) = 'object'),
    last_error text CHECK (last_error <> '' AND length(last_error) <= 1024),
    CHECK ((state = 'pending') = (drained_at IS NULL)),
    CHECK (state <> 'rejected' OR (outcome IS NOT NULL AND outcome ? 'reason')),
    CHECK ((tenant_id IS NULL) = (trust_tier = 'provider_signed')),
    CHECK ((trust_tier = 'provider_signed') = (kind LIKE 'webhook.%')),
    CHECK ((trust_tier = 'launch_token') = (kind = 'mission_request')),
    CHECK ((run_key IS NULL) = (unit_key IS NULL) AND (run_key IS NULL) = (generation IS NULL)),
    UNIQUE (installation_id, application_id, credential_ref, dedupe_space, dedupe_key),
    FOREIGN KEY (installation_id, application_id)
        REFERENCES mission_control.application_installation (installation_id, application_id),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE INDEX ingress_inbox_pending_idx ON mission_control.ingress_inbox
    (installation_id, application_id, received_at, ingress_id) WHERE state = 'pending';
CREATE INDEX ingress_inbox_tenant_id_fk_idx ON mission_control.ingress_inbox
    (installation_id, application_id, tenant_id);

CREATE TABLE mission_control.ingress_artifact_upload (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    artifact_upload_id uuid PRIMARY KEY,
    credential_ref text NOT NULL CHECK (credential_ref <> '' AND length(credential_ref) <= 600),
    run_key text NOT NULL CHECK (run_key <> ''),
    unit_key text NOT NULL CHECK (unit_key <> '' AND length(unit_key) <= 512),
    generation integer NOT NULL CHECK (generation >= 1),
    artifact_ref text NOT NULL
        CHECK (artifact_ref ~ '^[A-Za-z0-9._/-]+$' AND length(artifact_ref) <= 256),
    declared_sha256 text NOT NULL CHECK (declared_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    size_bytes bigint NOT NULL CHECK (size_bytes BETWEEN 1 AND 5368709120),
    media_type text NOT NULL
        CHECK (media_type ~ '^[a-z]+/[A-Za-z0-9.+-]+$' AND length(media_type) <= 255),
    storage_key text NOT NULL UNIQUE CHECK (storage_key <> '' AND length(storage_key) <= 1024),
    state text NOT NULL
        CHECK (state IN ('prepared', 'committed', 'verified', 'rejected', 'expired')),
    prepared_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    committed_at timestamptz,
    settled_at timestamptz,
    CHECK (expires_at > prepared_at),
    CHECK ((committed_at IS NULL) = (state IN ('prepared', 'expired'))),
    CHECK ((settled_at IS NULL) = (state IN ('prepared', 'committed'))),
    UNIQUE (installation_id, application_id, credential_ref, declared_sha256),
    UNIQUE (installation_id, application_id, tenant_id, artifact_upload_id),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id),
    FOREIGN KEY (installation_id, application_id, tenant_id, run_key)
        REFERENCES mission_control.mission_run (installation_id, application_id, tenant_id, run_key)
);
-- end section: tables

-- ---------------------------------------------------------------------------------------
-- section: guards (insert-only identity; each lifecycle column moves once, forward)
CREATE FUNCTION mission_control.ingress_credential_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ingress credentials are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
        RAISE EXCEPTION 'a revoked ingress credential stays revoked'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['revoked_at', 'rate_window_started_at', 'rate_window_count'])
       IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['revoked_at', 'rate_window_started_at', 'rate_window_count']) THEN
        RAISE EXCEPTION 'an ingress credential is bound to its digest, purpose and binding'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$guard$;

CREATE FUNCTION mission_control.ingress_session_binding_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ingress session bindings are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
        RAISE EXCEPTION 'a revoked ingress session binding stays revoked'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.session_id IS NOT NULL AND (NEW.session_id IS DISTINCT FROM OLD.session_id
                                       OR NEW.bound_at IS DISTINCT FROM OLD.bound_at) THEN
        RAISE EXCEPTION 'a bound provider session never rebinds'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['session_id', 'bound_at', 'revoked_at', 'rate_window_started_at',
                              'rate_window_count'])
       IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['session_id', 'bound_at', 'revoked_at', 'rate_window_started_at',
                              'rate_window_count']) THEN
        RAISE EXCEPTION 'an ingress session binding is bound to its run generation'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$guard$;

CREATE FUNCTION mission_control.ingress_inbox_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ingress inbox rows are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.state <> 'pending' THEN
        RAISE EXCEPTION 'a settled ingress inbox row does not move'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.attempts < OLD.attempts THEN
        RAISE EXCEPTION 'ingress inbox attempts only grow'
            USING ERRCODE = 'restrict_violation';
    END IF;
    -- `dedupe_space` is generated from `kind` after BEFORE triggers run (NEW lacks it here).
    IF (to_jsonb(NEW) - ARRAY['state', 'attempts', 'drained_at', 'outcome', 'last_error',
                              'dedupe_space'])
       IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['state', 'attempts', 'drained_at', 'outcome', 'last_error',
                              'dedupe_space']) THEN
        RAISE EXCEPTION 'an accepted ingress message is immutable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$guard$;

CREATE FUNCTION mission_control.ingress_artifact_upload_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ingress artifact uploads are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NOT ((OLD.state = 'prepared' AND NEW.state IN ('prepared', 'committed', 'expired'))
            OR (OLD.state = 'committed' AND NEW.state IN ('committed', 'verified', 'rejected'))) THEN
        RAISE EXCEPTION 'ingress artifact upload % cannot move to %', OLD.state, NEW.state
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (OLD.committed_at IS NOT NULL AND NEW.committed_at IS DISTINCT FROM OLD.committed_at)
       OR (to_jsonb(NEW) - ARRAY['state', 'committed_at', 'settled_at'])
          IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['state', 'committed_at', 'settled_at']) THEN
        RAISE EXCEPTION 'an ingress artifact upload is bound to its declared digest'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$guard$;

DO $guards$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['ingress_credential', 'ingress_session_binding',
            'ingress_inbox', 'ingress_artifact_upload'] LOOP
        EXECUTE pg_catalog.format(
            'REVOKE ALL ON FUNCTION mission_control.%I() FROM PUBLIC', table_name || '_guard');
        EXECUTE pg_catalog.format(
            'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON mission_control.%I '
            'FOR EACH ROW EXECUTE FUNCTION mission_control.%I()',
            table_name || '_guard', table_name, table_name || '_guard');
    END LOOP;
END
$guards$;

-- Wake-up only: the scope and identity of the new row, never its payload (0032 idiom).
CREATE FUNCTION mission_control.notify_ingress() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    PERFORM pg_notify('mc_ingress', json_build_object(
        'scope', 'mc/' || NEW.installation_id || '/' || NEW.application_id || '/'
                 || COALESCE(NEW.tenant_id::text, ''),
        'ingress_id', NEW.ingress_id,
        'kind', NEW.kind)::text);
    RETURN NULL;
END;
$$;
REVOKE ALL ON FUNCTION mission_control.notify_ingress() FROM PUBLIC;
CREATE TRIGGER ingress_inbox_notify
    AFTER INSERT ON mission_control.ingress_inbox
    FOR EACH ROW EXECUTE FUNCTION mission_control.notify_ingress();
-- end section: guards

-- ---------------------------------------------------------------------------------------
-- section: row-level security and grants
-- Standard tenant scope for every role. The definer functions resolve a credential or
-- session before they know its tenant, so the owner of the `mission_control` schema (the
-- migration principal, which owns these functions) may also read and write rows of the
-- bound installation and application across tenants. No other role satisfies that policy.
CREATE FUNCTION mission_control.ingress_definer() RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT EXISTS (
        SELECT 1 FROM pg_catalog.pg_namespace n
        JOIN pg_catalog.pg_roles r ON r.oid = n.nspowner
        WHERE n.nspname = 'mission_control' AND r.rolname = CURRENT_USER
    )
$$;
REVOKE ALL ON FUNCTION mission_control.ingress_definer() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mission_control.ingress_definer()
    TO mission_control_runtime, mission_control_readonly;

DO $policies$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['ingress_credential', 'ingress_session_binding',
            'ingress_inbox', 'ingress_artifact_upload'] LOOP
        EXECUTE pg_catalog.format(
            'ALTER TABLE mission_control.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE pg_catalog.format(
            'ALTER TABLE mission_control.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE pg_catalog.format(
            'CREATE POLICY %I ON mission_control.%I '
            'USING (installation_id = mission_control.ctx_installation_id() '
            'AND application_id = mission_control.ctx_application_id() '
            'AND mission_control.ingress_definer()) '
            'WITH CHECK (installation_id = mission_control.ctx_installation_id() '
            'AND application_id = mission_control.ctx_application_id() '
            'AND mission_control.ingress_definer())',
            table_name || '_definer', table_name);
        EXECUTE pg_catalog.format('REVOKE ALL ON mission_control.%I FROM PUBLIC', table_name);
    END LOOP;
    FOREACH table_name IN ARRAY ARRAY['ingress_credential', 'ingress_session_binding',
            'ingress_artifact_upload'] LOOP
        EXECUTE pg_catalog.format(
            'CREATE POLICY %I ON mission_control.%I '
            'USING (installation_id = mission_control.ctx_installation_id() '
            'AND application_id = mission_control.ctx_application_id() '
            'AND tenant_id = mission_control.ctx_tenant_id()) '
            'WITH CHECK (installation_id = mission_control.ctx_installation_id() '
            'AND application_id = mission_control.ctx_application_id() '
            'AND tenant_id = mission_control.ctx_tenant_id())',
            table_name || '_scope', table_name);
    END LOOP;
END
$policies$;
-- An unresolved provider webhook has no tenant yet: every scope of its application sees it.
CREATE POLICY ingress_inbox_scope ON mission_control.ingress_inbox
    USING (installation_id = mission_control.ctx_installation_id()
           AND application_id = mission_control.ctx_application_id()
           AND (tenant_id = mission_control.ctx_tenant_id() OR tenant_id IS NULL))
    WITH CHECK (installation_id = mission_control.ctx_installation_id()
           AND application_id = mission_control.ctx_application_id()
           AND (tenant_id = mission_control.ctx_tenant_id() OR tenant_id IS NULL));

-- The worker mints, binds and revokes; the drainer settles inbox rows and the custody
-- activity settles uploads. Inbox rows and upload slots are written only by the functions.
GRANT SELECT, INSERT ON mission_control.ingress_credential TO mission_control_runtime;
GRANT UPDATE (revoked_at) ON mission_control.ingress_credential TO mission_control_runtime;
GRANT SELECT, INSERT ON mission_control.ingress_session_binding TO mission_control_runtime;
GRANT UPDATE (revoked_at) ON mission_control.ingress_session_binding TO mission_control_runtime;
GRANT SELECT ON mission_control.ingress_inbox TO mission_control_runtime;
GRANT UPDATE (state, attempts, drained_at, outcome, last_error)
    ON mission_control.ingress_inbox TO mission_control_runtime;
GRANT SELECT ON mission_control.ingress_artifact_upload TO mission_control_runtime;
GRANT UPDATE (state, settled_at)
    ON mission_control.ingress_artifact_upload TO mission_control_runtime;
GRANT SELECT ON mission_control.ingress_inbox, mission_control.ingress_artifact_upload
    TO mission_control_readonly;
-- end section: row-level security and grants

-- ---------------------------------------------------------------------------------------
-- section: internal helpers (not callable by any login; the definer functions run them)
CREATE FUNCTION mission_control.ingress_bind_scope(
    p_installation_id uuid, p_application_id text, p_tenant_id uuid
) RETURNS void
LANGUAGE plpgsql VOLATILE AS $$
BEGIN
    PERFORM pg_catalog.set_config('mc.installation_id', p_installation_id::text, true),
            pg_catalog.set_config('mc.application_id', p_application_id, true),
            pg_catalog.set_config('mc.tenant_id', COALESCE(p_tenant_id::text, ''), true);
END
$$;
ALTER FUNCTION mission_control.ingress_bind_scope(uuid, text, uuid) SET search_path = pg_catalog;

-- The principal a credential names, and whether it is usable now. `p_credential` is the
-- token digest (`run_token`, `launch_token`) or the provider session id (`provider_oidc`,
-- `environment_key`). An `environment_key` session that is not bound yet is bound here when
-- the caller presents the digest of the run nonce registered for that environment.
CREATE FUNCTION mission_control.ingress_principal(
    p_installation_id uuid, p_application_id text, p_tier text, p_credential text,
    p_provider text, p_environment_ref text, p_nonce_hash text, p_now timestamptz
) RETURNS TABLE (
    outcome text, tenant_id uuid, principal_id uuid, credential_ref text, purpose text,
    scopes text[], run_key text, unit_key text, generation integer, context jsonb
)
LANGUAGE plpgsql VOLATILE AS $$
#variable_conflict use_column
DECLARE
    found_credential mission_control.ingress_credential%ROWTYPE;
    found_binding mission_control.ingress_session_binding%ROWTYPE;
    wanted text;
BEGIN
    IF p_tier IN ('run_token', 'launch_token') THEN
        wanted := CASE p_tier WHEN 'run_token' THEN 'signal_token' ELSE 'mission_request' END;
        SELECT * INTO found_credential FROM mission_control.ingress_credential AS c
         WHERE c.installation_id = p_installation_id AND c.application_id = p_application_id
           AND c.credential_hash = p_credential;
        IF NOT FOUND THEN
            RETURN QUERY SELECT 'unknown'::text, NULL::uuid, NULL::uuid, NULL::text, NULL::text,
                NULL::text[], NULL::text, NULL::text, NULL::integer, NULL::jsonb;
            RETURN;
        END IF;
        RETURN QUERY SELECT
            CASE
                WHEN found_credential.purpose <> wanted THEN 'wrong_purpose'
                WHEN found_credential.revoked_at IS NOT NULL THEN 'revoked'
                WHEN found_credential.expires_at <= p_now THEN 'expired'
                ELSE 'ok'
            END,
            found_credential.tenant_id, found_credential.credential_id,
            'credential:' || found_credential.credential_id::text, found_credential.purpose,
            found_credential.scopes, found_credential.run_key, found_credential.unit_key,
            found_credential.generation, found_credential.context;
        RETURN;
    END IF;
    IF p_tier NOT IN ('provider_oidc', 'environment_key') OR p_provider IS NULL
       OR p_credential IS NULL THEN
        RETURN QUERY SELECT 'tier_not_allowed'::text, NULL::uuid, NULL::uuid, NULL::text,
            NULL::text, NULL::text[], NULL::text, NULL::text, NULL::integer, NULL::jsonb;
        RETURN;
    END IF;
    SELECT * INTO found_binding FROM mission_control.ingress_session_binding AS b
     WHERE b.installation_id = p_installation_id AND b.application_id = p_application_id
       AND b.provider = p_provider AND b.session_id = p_credential;
    IF NOT FOUND AND p_tier = 'environment_key' AND p_nonce_hash IS NOT NULL THEN
        UPDATE mission_control.ingress_session_binding AS b
           SET session_id = p_credential, bound_at = p_now
         WHERE b.installation_id = p_installation_id AND b.application_id = p_application_id
           AND b.provider = p_provider AND b.nonce_hash = p_nonce_hash
           AND b.trust_tier = 'environment_key' AND b.session_id IS NULL
           AND b.environment_ref = p_environment_ref
           AND b.revoked_at IS NULL AND b.expires_at > p_now
        RETURNING b.* INTO found_binding;
    END IF;
    IF found_binding.session_binding_id IS NULL THEN
        RETURN QUERY SELECT 'unbound_session'::text, NULL::uuid, NULL::uuid, NULL::text,
            NULL::text, NULL::text[], NULL::text, NULL::text, NULL::integer, NULL::jsonb;
        RETURN;
    END IF;
    RETURN QUERY SELECT
        CASE
            WHEN found_binding.trust_tier <> p_tier THEN 'wrong_tier'
            WHEN p_tier = 'environment_key'
                 AND found_binding.environment_ref IS DISTINCT FROM p_environment_ref
                THEN 'wrong_environment'
            WHEN found_binding.revoked_at IS NOT NULL THEN 'revoked'
            WHEN found_binding.expires_at <= p_now THEN 'expired'
            ELSE 'ok'
        END,
        found_binding.tenant_id, found_binding.session_binding_id,
        'session:' || found_binding.session_binding_id::text, NULL::text,
        ARRAY['signal:write']::text[], found_binding.run_key, found_binding.unit_key,
        found_binding.generation, found_binding.context;
END
$$;
ALTER FUNCTION mission_control.ingress_principal(
    uuid, text, text, text, text, text, text, timestamptz) SET search_path = pg_catalog;

-- Take `p_count` requests from the principal's fixed 60 s window; false when over its limit.
CREATE FUNCTION mission_control.ingress_take_rate(
    p_tier text, p_principal_id uuid, p_count integer, p_now timestamptz
) RETURNS boolean
LANGUAGE plpgsql VOLATILE AS $$
BEGIN
    IF p_tier IN ('run_token', 'launch_token') THEN
        UPDATE mission_control.ingress_credential AS c
           SET rate_window_started_at = CASE
                   WHEN c.rate_window_started_at <= p_now - interval '60 seconds' THEN p_now
                   ELSE c.rate_window_started_at END,
               rate_window_count = CASE
                   WHEN c.rate_window_started_at <= p_now - interval '60 seconds' THEN p_count
                   ELSE c.rate_window_count + p_count END
         WHERE c.credential_id = p_principal_id
           AND CASE WHEN c.rate_window_started_at <= p_now - interval '60 seconds' THEN p_count
                    ELSE c.rate_window_count + p_count END <= c.rate_limit;
    ELSE
        UPDATE mission_control.ingress_session_binding AS b
           SET rate_window_started_at = CASE
                   WHEN b.rate_window_started_at <= p_now - interval '60 seconds' THEN p_now
                   ELSE b.rate_window_started_at END,
               rate_window_count = CASE
                   WHEN b.rate_window_started_at <= p_now - interval '60 seconds' THEN p_count
                   ELSE b.rate_window_count + p_count END
         WHERE b.session_binding_id = p_principal_id
           AND CASE WHEN b.rate_window_started_at <= p_now - interval '60 seconds' THEN p_count
                    ELSE b.rate_window_count + p_count END <= b.rate_limit;
    END IF;
    RETURN FOUND;
END
$$;
ALTER FUNCTION mission_control.ingress_take_rate(text, uuid, integer, timestamptz)
    SET search_path = pg_catalog;

REVOKE ALL ON FUNCTION mission_control.ingress_bind_scope(uuid, text, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION mission_control.ingress_principal(
    uuid, text, text, text, text, text, text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION mission_control.ingress_take_rate(text, uuid, integer, timestamptz)
    FROM PUBLIC;
-- end section: internal helpers

-- ---------------------------------------------------------------------------------------
-- section: ingress functions (the only surface of `mission_control_ingress`)

-- Signals (`run_token`, `provider_oidc`, `environment_key`). `p_items` is a JSON array of 1 to
-- 100 objects `{ingress_id, kind, dedupe_key, body_sha256, payload, seq}`; the edge has
-- already redacted and size-checked each payload. A payload over 256 KiB as stored (jsonb
-- text) is `payload_too_large`. A repeat of `(credential, dedupe_key)` among signals is a
-- duplicate, never an error. Outcome `accepted` or a typed rejection.
CREATE FUNCTION mission_control.ingress_accept(
    p_installation_id uuid, p_application_id text, p_tier text, p_credential text,
    p_provider text, p_environment_ref text, p_nonce_hash text, p_items jsonb
) RETURNS TABLE (outcome text, accepted integer, duplicates integer)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog
AS $$
#variable_conflict use_column
DECLARE
    now_at timestamptz := pg_catalog.clock_timestamp();
    principal record;
    item jsonb;
    total integer;
    inserted integer := 0;
BEGIN
    IF p_tier NOT IN ('run_token', 'provider_oidc', 'environment_key') THEN
        RETURN QUERY SELECT 'tier_not_allowed'::text, 0, 0;
        RETURN;
    END IF;
    IF jsonb_typeof(p_items) IS DISTINCT FROM 'array'
       OR jsonb_array_length(p_items) NOT BETWEEN 1 AND 100 THEN
        RETURN QUERY SELECT 'invalid_batch'::text, 0, 0;
        RETURN;
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(p_items) LOOP
        IF jsonb_typeof(item) = 'object' AND jsonb_typeof(item->'payload') = 'object'
           AND octet_length((item->'payload')::text) > 262144 THEN
            RETURN QUERY SELECT 'payload_too_large'::text, 0, 0;
            RETURN;
        END IF;
        IF jsonb_typeof(item) IS DISTINCT FROM 'object'
           OR NOT COALESCE(item->>'kind' ~ '^signal\.[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$', false)
           OR length(COALESCE(item->>'dedupe_key', '')) NOT BETWEEN 1 AND 256
           OR NOT COALESCE(item->>'body_sha256' ~ '^sha256:[0-9a-f]{64}$', false)
           OR jsonb_typeof(item->'payload') IS DISTINCT FROM 'object'
           OR NOT COALESCE(item->>'ingress_id' ~ '^[0-9a-f-]{36}$', false)
           OR (item ? 'seq' AND jsonb_typeof(item->'seq') <> 'null'
               AND NOT COALESCE(item->>'seq' ~ '^[0-9]{1,18}$', false)) THEN
            RETURN QUERY SELECT 'invalid_item'::text, 0, 0;
            RETURN;
        END IF;
    END LOOP;
    PERFORM mission_control.ingress_bind_scope(p_installation_id, p_application_id, NULL);
    SELECT * INTO principal FROM mission_control.ingress_principal(
        p_installation_id, p_application_id, p_tier, p_credential, p_provider,
        p_environment_ref, p_nonce_hash, now_at);
    IF principal.outcome <> 'ok' THEN
        RETURN QUERY SELECT principal.outcome, 0, 0;
        RETURN;
    END IF;
    IF NOT 'signal:write' = ANY (principal.scopes) THEN
        RETURN QUERY SELECT 'insufficient_scope'::text, 0, 0;
        RETURN;
    END IF;
    PERFORM mission_control.ingress_bind_scope(
        p_installation_id, p_application_id, principal.tenant_id);
    total := jsonb_array_length(p_items);
    IF NOT mission_control.ingress_take_rate(p_tier, principal.principal_id, total, now_at) THEN
        RETURN QUERY SELECT 'rate_limited'::text, 0, 0;
        RETURN;
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(p_items) LOOP
        INSERT INTO mission_control.ingress_inbox (
            installation_id, application_id, tenant_id, ingress_id, received_at, trust_tier,
            kind, credential_ref, dedupe_key, body_sha256, payload, seq, run_key, unit_key,
            generation, state, attempts
        ) VALUES (
            p_installation_id, p_application_id, principal.tenant_id,
            (item->>'ingress_id')::uuid, pg_catalog.clock_timestamp(), p_tier, item->>'kind',
            principal.credential_ref, item->>'dedupe_key', item->>'body_sha256',
            item->'payload', (item->>'seq')::bigint, principal.run_key, principal.unit_key,
            principal.generation, 'pending', 0
        ) ON CONFLICT (installation_id, application_id, credential_ref, dedupe_space, dedupe_key)
            DO NOTHING;
        IF FOUND THEN
            inserted := inserted + 1;
        END IF;
    END LOOP;
    RETURN QUERY SELECT 'accepted'::text, inserted, total - inserted;
END
$$;

-- Synchronous gate (`run_token`, `provider_oidc`). In one transaction, under the same per-run
-- advisory lock and admission ledger as the loopback Kernel Hook: the credential check (a
-- revoked credential answers `stop`; its decisions are recorded only within its rate window,
-- so a revoked token cannot write past its limit), the Stop Fence of (run, generation)
-- (`stop`), the binding's `disallowed_tools` (`deny`), the gate context (`deny` unless it
-- names a harness execution and a registered lane profile), the Operation Intent keyed on the
-- effect ref written BEFORE `allow`, and the `gate.decision` inbox row. A repeated
-- `p_dedupe_key` (serialized by the lock, so a concurrent repeat too) answers the recorded
-- decision only for the same body; a different body under a recorded key is
-- `dedupe_conflict`, so a reused id never carries one effect's answer to another. Outcome
-- `decided` with a decision, or a typed rejection.
CREATE FUNCTION mission_control.ingress_gate(
    p_installation_id uuid, p_application_id text, p_tier text, p_credential text,
    p_provider text, p_ingress_id uuid, p_dedupe_key text, p_hook_event text,
    p_effect_ref text, p_effect_kind text, p_tool text, p_input_digest text,
    p_body_sha256 text
) RETURNS TABLE (outcome text, decision text, reason text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog
AS $$
#variable_conflict use_column
DECLARE
    now_at timestamptz := pg_catalog.clock_timestamp();
    principal record;
    recorded_body text;
    recorded jsonb;
    run_uuid uuid;
    fence_id uuid;
    prior_decision text;
    answer text;
    why text;
    tools jsonb;
BEGIN
    IF p_tier NOT IN ('run_token', 'provider_oidc') THEN
        RETURN QUERY SELECT 'tier_not_allowed'::text, NULL::text, NULL::text;
        RETURN;
    END IF;
    IF length(COALESCE(p_dedupe_key, '')) NOT BETWEEN 1 AND 256
       OR length(COALESCE(p_effect_ref, '')) NOT BETWEEN 1 AND 512
       OR p_effect_kind IS NULL
       OR p_effect_kind NOT IN ('shell', 'mcp', 'file', 'task', 'model', 'other')
       OR length(COALESCE(p_hook_event, '')) NOT BETWEEN 1 AND 64
       OR NOT COALESCE(p_input_digest ~ '^sha256:[0-9a-f]{64}$', false)
       OR NOT COALESCE(p_body_sha256 ~ '^sha256:[0-9a-f]{64}$', false)
       OR length(COALESCE(p_tool, '')) > 256 THEN
        RETURN QUERY SELECT 'invalid_item'::text, NULL::text, NULL::text;
        RETURN;
    END IF;
    PERFORM mission_control.ingress_bind_scope(p_installation_id, p_application_id, NULL);
    SELECT * INTO principal FROM mission_control.ingress_principal(
        p_installation_id, p_application_id, p_tier, p_credential, p_provider, NULL, NULL,
        now_at);
    IF principal.outcome NOT IN ('ok', 'revoked') THEN
        RETURN QUERY SELECT principal.outcome, NULL::text, NULL::text;
        RETURN;
    END IF;
    IF NOT 'signal:write' = ANY (principal.scopes) THEN
        RETURN QUERY SELECT 'insufficient_scope'::text, NULL::text, NULL::text;
        RETURN;
    END IF;
    PERFORM mission_control.ingress_bind_scope(
        p_installation_id, p_application_id, principal.tenant_id);
    -- Same lock key and ledger as PostgresStopFenceRepository (0029 section F3). A credential
    -- binds one run, so every call with this dedupe key queues here behind the first.
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'mc.stop_fence:mc/' || p_installation_id::text || '/' || p_application_id || '/'
        || principal.tenant_id::text || ':' || principal.run_key, 0));
    SELECT i.body_sha256, i.payload INTO recorded_body, recorded
      FROM mission_control.ingress_inbox AS i
     WHERE i.installation_id = p_installation_id AND i.application_id = p_application_id
       AND i.credential_ref = principal.credential_ref
       AND i.dedupe_space = 'gate.decision' AND i.dedupe_key = p_dedupe_key;
    IF FOUND THEN
        IF recorded_body <> p_body_sha256
           OR recorded->>'effect_ref' IS DISTINCT FROM p_effect_ref THEN
            RETURN QUERY SELECT 'dedupe_conflict'::text, NULL::text, NULL::text;
            RETURN;
        END IF;
        RETURN QUERY SELECT 'decided'::text, recorded->>'decision', recorded->>'reason';
        RETURN;
    END IF;
    IF principal.outcome = 'revoked' THEN
        IF NOT mission_control.ingress_take_rate(p_tier, principal.principal_id, 1, now_at) THEN
            RETURN QUERY SELECT 'decided'::text, 'stop'::text, 'credential_revoked'::text;
            RETURN;
        END IF;
        answer := 'stop';
        why := 'credential_revoked';
    ELSE
        IF NOT mission_control.ingress_take_rate(p_tier, principal.principal_id, 1, now_at) THEN
            RETURN QUERY SELECT 'rate_limited'::text, NULL::text, NULL::text;
            RETURN;
        END IF;
        SELECT r.run_id INTO run_uuid FROM mission_control.mission_run AS r
         WHERE r.installation_id = p_installation_id AND r.application_id = p_application_id
           AND r.tenant_id = principal.tenant_id AND r.run_key = principal.run_key;
        SELECT a.decision INTO prior_decision
          FROM mission_control.stop_fence_effect_admission AS a
         WHERE a.installation_id = p_installation_id AND a.application_id = p_application_id
           AND a.tenant_id = principal.tenant_id AND a.run_id = run_uuid
           AND a.generation = principal.generation AND a.effect_ref = p_effect_ref;
        IF prior_decision IS NULL THEN
            SELECT f.stop_fence_id INTO fence_id FROM mission_control.stop_fence AS f
             WHERE f.installation_id = p_installation_id
               AND f.application_id = p_application_id
               AND f.tenant_id = principal.tenant_id AND f.run_id = run_uuid
               AND f.generation >= principal.generation
             ORDER BY f.generation DESC LIMIT 1;
            prior_decision := CASE WHEN fence_id IS NULL THEN 'allow' ELSE 'deny' END;
            INSERT INTO mission_control.stop_fence_effect_admission (
                installation_id, application_id, tenant_id, effect_admission_id, run_id,
                run_key, generation, effect_ref, effect_kind, lane_profile, decision,
                reason_code, stop_fence_id, decided_at, created_by_actor_ref
            ) VALUES (
                p_installation_id, p_application_id, principal.tenant_id, p_ingress_id,
                run_uuid, principal.run_key, principal.generation, p_effect_ref, p_effect_kind,
                COALESCE(principal.context->>'lane_profile', 'unknown'), prior_decision,
                CASE WHEN prior_decision = 'deny' THEN 'STOP_FENCED' END,
                fence_id, now_at, 'mission-control-ingress/gate'
            );
        END IF;
        tools := COALESCE(principal.context->'disallowed_tools', '[]'::jsonb);
        IF prior_decision = 'deny' THEN
            answer := 'stop';
            why := 'stop_fenced';
        ELSIF jsonb_typeof(tools) = 'array' AND EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(tools) AS t(name)
             WHERE lower(t.name) = lower(COALESCE(p_tool, ''))
                OR (p_effect_kind IN ('shell', 'mcp') AND lower(t.name) = p_effect_kind)
        ) THEN
            answer := 'deny';
            why := 'disallowed_tool';
        ELSIF NOT COALESCE(principal.context->>'harness_execution_id'
                           ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', false)
              OR NOT EXISTS (
                  SELECT 1 FROM mission_control.lane_profile AS l
                   WHERE l.lane_profile = principal.context->>'lane_profile') THEN
            answer := 'deny';
            why := 'gate_context_missing';
        ELSE
            -- The Operation Intent precedes the answer: no `allow` without it.
            INSERT INTO mission_control.hook_effect_intent (
                installation_id, application_id, tenant_id, intent_id, run_key, generation,
                harness_execution_id, effect_ref, effect_kind, hook_event, lane_profile,
                input_digest, recorded_at
            ) VALUES (
                p_installation_id, p_application_id, principal.tenant_id, p_ingress_id,
                principal.run_key, principal.generation,
                (principal.context->>'harness_execution_id')::uuid, p_effect_ref,
                p_effect_kind, p_hook_event, principal.context->>'lane_profile',
                p_input_digest, pg_catalog.clock_timestamp()
            ) ON CONFLICT (installation_id, application_id, tenant_id, run_key, generation,
                           effect_ref) DO NOTHING;
            answer := 'allow';
            why := NULL;
        END IF;
    END IF;
    INSERT INTO mission_control.ingress_inbox (
        installation_id, application_id, tenant_id, ingress_id, received_at, trust_tier, kind,
        credential_ref, dedupe_key, body_sha256, payload, seq, run_key, unit_key, generation,
        state, attempts
    ) VALUES (
        p_installation_id, p_application_id, principal.tenant_id, p_ingress_id,
        pg_catalog.clock_timestamp(), p_tier, 'gate.decision', principal.credential_ref,
        p_dedupe_key, p_body_sha256,
        jsonb_build_object('decision', answer, 'reason', why, 'hook_event', p_hook_event,
            'effect_ref', p_effect_ref, 'effect_kind', p_effect_kind, 'tool', p_tool,
            'input_digest', p_input_digest),
        NULL, principal.run_key, principal.unit_key, principal.generation, 'pending', 0
    );
    RETURN QUERY SELECT 'decided'::text, answer, why;
END
$$;

-- Provider webhooks (`provider_signed`; the edge verified the signature). Wake-ups only: the
-- row has no tenant or run until the drainer resolves the provider session. A repeated
-- delivery id is a duplicate. Outcome `accepted`, `duplicate` or a typed rejection
-- (`payload_too_large` over 256 KiB as stored).
CREATE FUNCTION mission_control.ingress_webhook(
    p_installation_id uuid, p_application_id text, p_provider text, p_route_ref text,
    p_ingress_id uuid, p_delivery_id text, p_body_sha256 text, p_payload jsonb
) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF p_provider IS NULL OR p_provider NOT IN ('anthropic', 'openai', 'cursor', 'github') THEN
        RETURN 'unknown_provider';
    END IF;
    IF (p_provider = 'cursor') <> (p_route_ref IS NOT NULL)
       OR length(COALESCE(p_route_ref, 'x')) NOT BETWEEN 1 AND 256
       OR length(COALESCE(p_delivery_id, '')) NOT BETWEEN 1 AND 256
       OR NOT COALESCE(p_body_sha256 ~ '^sha256:[0-9a-f]{64}$', false)
       OR jsonb_typeof(p_payload) IS DISTINCT FROM 'object' THEN
        RETURN 'invalid_item';
    END IF;
    IF octet_length(p_payload::text) > 262144 THEN
        RETURN 'payload_too_large';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM mission_control.application_installation AS a
         WHERE a.installation_id = p_installation_id AND a.application_id = p_application_id
           AND a.state = 'active'
    ) THEN
        RETURN 'unknown_installation';
    END IF;
    PERFORM mission_control.ingress_bind_scope(p_installation_id, p_application_id, NULL);
    INSERT INTO mission_control.ingress_inbox (
        installation_id, application_id, tenant_id, ingress_id, received_at, trust_tier, kind,
        credential_ref, dedupe_key, body_sha256, payload, seq, run_key, unit_key, generation,
        state, attempts
    ) VALUES (
        p_installation_id, p_application_id, NULL, p_ingress_id, pg_catalog.clock_timestamp(),
        'provider_signed', 'webhook.' || p_provider,
        'webhook:' || p_provider || COALESCE(':' || p_route_ref, ''), p_delivery_id,
        p_body_sha256, p_payload, NULL, NULL, NULL, NULL, 'pending', 0
    ) ON CONFLICT (installation_id, application_id, credential_ref, dedupe_space, dedupe_key)
        DO NOTHING;
    RETURN CASE WHEN FOUND THEN 'accepted' ELSE 'duplicate' END;
END
$$;

-- A quarantine upload slot for one declared digest (`run_token`, `provider_oidc`). The
-- storage key is `<application>/<run uuid>/<sha256 hex>/<artifact upload uuid>`, so another
-- unit or generation of the run gets its own slot for the same bytes; the edge signs an
-- upload URL for it. Preparing the same digest again with the same credential, including
-- concurrently, returns the same slot. Outcome `prepared`, `duplicate` (already committed or
-- expired) or a typed rejection.
CREATE FUNCTION mission_control.ingress_artifact_prepare(
    p_installation_id uuid, p_application_id text, p_tier text, p_credential text,
    p_provider text, p_artifact_upload_id uuid, p_artifact_ref text, p_sha256 text,
    p_size_bytes bigint, p_media_type text, p_ttl_seconds integer
) RETURNS TABLE (outcome text, artifact_upload_id uuid, storage_key text, expires_at timestamptz)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog
AS $$
#variable_conflict use_column
DECLARE
    now_at timestamptz := pg_catalog.clock_timestamp();
    principal record;
    slot mission_control.ingress_artifact_upload%ROWTYPE;
    run_uuid uuid;
BEGIN
    IF p_tier NOT IN ('run_token', 'provider_oidc') THEN
        RETURN QUERY SELECT 'tier_not_allowed'::text, NULL::uuid, NULL::text, NULL::timestamptz;
        RETURN;
    END IF;
    IF NOT COALESCE(p_artifact_ref ~ '^[A-Za-z0-9._/-]+$', false)
       OR length(p_artifact_ref) > 256
       OR NOT COALESCE(p_sha256 ~ '^sha256:[0-9a-f]{64}$', false)
       OR p_size_bytes IS NULL OR p_size_bytes NOT BETWEEN 1 AND 5368709120
       OR NOT COALESCE(p_media_type ~ '^[a-z]+/[A-Za-z0-9.+-]+$', false)
       OR length(p_media_type) > 255
       OR p_ttl_seconds IS NULL OR p_ttl_seconds NOT BETWEEN 60 AND 3600 THEN
        RETURN QUERY SELECT 'invalid_item'::text, NULL::uuid, NULL::text, NULL::timestamptz;
        RETURN;
    END IF;
    PERFORM mission_control.ingress_bind_scope(p_installation_id, p_application_id, NULL);
    SELECT * INTO principal FROM mission_control.ingress_principal(
        p_installation_id, p_application_id, p_tier, p_credential, p_provider, NULL, NULL,
        now_at);
    IF principal.outcome <> 'ok' THEN
        RETURN QUERY SELECT principal.outcome, NULL::uuid, NULL::text, NULL::timestamptz;
        RETURN;
    END IF;
    IF NOT 'signal:write' = ANY (principal.scopes) THEN
        RETURN QUERY SELECT 'insufficient_scope'::text, NULL::uuid, NULL::text,
            NULL::timestamptz;
        RETURN;
    END IF;
    PERFORM mission_control.ingress_bind_scope(
        p_installation_id, p_application_id, principal.tenant_id);
    SELECT * INTO slot FROM mission_control.ingress_artifact_upload AS u
     WHERE u.installation_id = p_installation_id AND u.application_id = p_application_id
       AND u.credential_ref = principal.credential_ref AND u.declared_sha256 = p_sha256;
    IF FOUND THEN
        RETURN QUERY SELECT
            CASE WHEN slot.state = 'prepared' AND slot.expires_at > now_at THEN 'prepared'
                 ELSE 'duplicate' END,
            slot.artifact_upload_id, slot.storage_key, slot.expires_at;
        RETURN;
    END IF;
    IF NOT mission_control.ingress_take_rate(p_tier, principal.principal_id, 1, now_at) THEN
        RETURN QUERY SELECT 'rate_limited'::text, NULL::uuid, NULL::text, NULL::timestamptz;
        RETURN;
    END IF;
    SELECT r.run_id INTO run_uuid FROM mission_control.mission_run AS r
     WHERE r.installation_id = p_installation_id AND r.application_id = p_application_id
       AND r.tenant_id = principal.tenant_id AND r.run_key = principal.run_key;
    INSERT INTO mission_control.ingress_artifact_upload (
        installation_id, application_id, tenant_id, artifact_upload_id, credential_ref,
        run_key, unit_key, generation, artifact_ref, declared_sha256, size_bytes, media_type,
        storage_key, state, prepared_at, expires_at
    ) VALUES (
        p_installation_id, p_application_id, principal.tenant_id, p_artifact_upload_id,
        principal.credential_ref, principal.run_key, principal.unit_key, principal.generation,
        p_artifact_ref, p_sha256, p_size_bytes, p_media_type,
        p_application_id || '/' || run_uuid::text || '/' || substr(p_sha256, 8) || '/'
            || p_artifact_upload_id::text,
        'prepared', now_at, now_at + make_interval(secs => p_ttl_seconds)
    ) ON CONFLICT (installation_id, application_id, credential_ref, declared_sha256) DO NOTHING
    RETURNING * INTO slot;
    IF NOT FOUND THEN
        -- A concurrent call prepared the same digest first: answer its slot.
        SELECT * INTO slot FROM mission_control.ingress_artifact_upload AS u
         WHERE u.installation_id = p_installation_id AND u.application_id = p_application_id
           AND u.credential_ref = principal.credential_ref AND u.declared_sha256 = p_sha256;
    END IF;
    RETURN QUERY SELECT 'prepared'::text, slot.artifact_upload_id, slot.storage_key,
        slot.expires_at;
END
$$;

-- The client finished its upload: the slot is committed and an `artifact.committed` inbox
-- row asks the worker to verify the digest and move the object into custody. Committing
-- again answers the same row. Outcome `committed`, `duplicate` or a typed rejection.
CREATE FUNCTION mission_control.ingress_artifact_commit(
    p_installation_id uuid, p_application_id text, p_tier text, p_credential text,
    p_provider text, p_ingress_id uuid, p_artifact_upload_id uuid
) RETURNS TABLE (outcome text, ingress_id uuid)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog
AS $$
#variable_conflict use_column
DECLARE
    now_at timestamptz := pg_catalog.clock_timestamp();
    principal record;
    slot mission_control.ingress_artifact_upload%ROWTYPE;
    existing uuid;
    committed jsonb;
BEGIN
    IF p_tier NOT IN ('run_token', 'provider_oidc') THEN
        RETURN QUERY SELECT 'tier_not_allowed'::text, NULL::uuid;
        RETURN;
    END IF;
    PERFORM mission_control.ingress_bind_scope(p_installation_id, p_application_id, NULL);
    SELECT * INTO principal FROM mission_control.ingress_principal(
        p_installation_id, p_application_id, p_tier, p_credential, p_provider, NULL, NULL,
        now_at);
    IF principal.outcome <> 'ok' THEN
        RETURN QUERY SELECT principal.outcome, NULL::uuid;
        RETURN;
    END IF;
    PERFORM mission_control.ingress_bind_scope(
        p_installation_id, p_application_id, principal.tenant_id);
    SELECT * INTO slot FROM mission_control.ingress_artifact_upload AS u
     WHERE u.installation_id = p_installation_id AND u.application_id = p_application_id
       AND u.artifact_upload_id = p_artifact_upload_id
       AND u.credential_ref = principal.credential_ref
       FOR UPDATE;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'not_found'::text, NULL::uuid;
        RETURN;
    END IF;
    IF slot.state <> 'prepared' THEN
        SELECT i.ingress_id INTO existing FROM mission_control.ingress_inbox AS i
         WHERE i.installation_id = p_installation_id AND i.application_id = p_application_id
           AND i.credential_ref = principal.credential_ref
           AND i.dedupe_space = 'artifact.committed'
           AND i.dedupe_key = 'artifact:' || slot.artifact_upload_id::text;
        RETURN QUERY SELECT
            CASE WHEN existing IS NULL THEN 'expired_upload' ELSE 'duplicate' END, existing;
        RETURN;
    END IF;
    IF slot.expires_at <= now_at THEN
        RETURN QUERY SELECT 'expired_upload'::text, NULL::uuid;
        RETURN;
    END IF;
    UPDATE mission_control.ingress_artifact_upload AS u
       SET state = 'committed', committed_at = now_at
     WHERE u.artifact_upload_id = slot.artifact_upload_id;
    committed := jsonb_build_object(
        'artifact_upload_id', slot.artifact_upload_id, 'artifact_ref', slot.artifact_ref,
        'sha256', slot.declared_sha256, 'size_bytes', slot.size_bytes,
        'media_type', slot.media_type, 'storage_key', slot.storage_key);
    INSERT INTO mission_control.ingress_inbox (
        installation_id, application_id, tenant_id, ingress_id, received_at, trust_tier, kind,
        credential_ref, dedupe_key, body_sha256, payload, seq, run_key, unit_key, generation,
        state, attempts
    ) VALUES (
        p_installation_id, p_application_id, principal.tenant_id, p_ingress_id,
        pg_catalog.clock_timestamp(), p_tier, 'artifact.committed', principal.credential_ref,
        'artifact:' || slot.artifact_upload_id::text,
        'sha256:' || encode(pg_catalog.sha256(convert_to(committed::text, 'UTF8')), 'hex'),
        committed, NULL, slot.run_key, slot.unit_key, slot.generation, 'pending', 0
    );
    RETURN QUERY SELECT 'committed'::text, p_ingress_id;
END
$$;

-- A remote launch request (R29; `launch_token`, purpose `mission_request`, scope
-- `mission:request`). The idempotency key is the dedupe key, so a repeat answers the first
-- request id. When the credential's context lists `manifest_refs`, the manifest must be one
-- of them. The drainer admits it through the application's admission handler. Outcome
-- `accepted`, `duplicate` (including a concurrent repeat) or a typed rejection.
CREATE FUNCTION mission_control.ingress_mission_request(
    p_installation_id uuid, p_application_id text, p_credential text, p_ingress_id uuid,
    p_idempotency_key text, p_manifest_ref text, p_body_sha256 text, p_payload jsonb
) RETURNS TABLE (outcome text, request_id uuid)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog
AS $$
#variable_conflict use_column
DECLARE
    now_at timestamptz := pg_catalog.clock_timestamp();
    principal record;
    existing uuid;
    allowed jsonb;
BEGIN
    IF length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 256
       OR length(COALESCE(p_manifest_ref, '')) NOT BETWEEN 1 AND 512
       OR NOT COALESCE(p_body_sha256 ~ '^sha256:[0-9a-f]{64}$', false)
       OR jsonb_typeof(p_payload) IS DISTINCT FROM 'object'
       OR p_payload->>'manifest_ref' IS DISTINCT FROM p_manifest_ref THEN
        RETURN QUERY SELECT 'invalid_item'::text, NULL::uuid;
        RETURN;
    END IF;
    IF octet_length(p_payload::text) > 262144 THEN
        RETURN QUERY SELECT 'payload_too_large'::text, NULL::uuid;
        RETURN;
    END IF;
    PERFORM mission_control.ingress_bind_scope(p_installation_id, p_application_id, NULL);
    SELECT * INTO principal FROM mission_control.ingress_principal(
        p_installation_id, p_application_id, 'launch_token', p_credential, NULL, NULL, NULL,
        now_at);
    IF principal.outcome <> 'ok' THEN
        RETURN QUERY SELECT principal.outcome, NULL::uuid;
        RETURN;
    END IF;
    IF NOT 'mission:request' = ANY (principal.scopes) THEN
        RETURN QUERY SELECT 'insufficient_scope'::text, NULL::uuid;
        RETURN;
    END IF;
    allowed := principal.context->'manifest_refs';
    IF allowed IS NOT NULL AND NOT (jsonb_typeof(allowed) = 'array'
                                    AND allowed ? p_manifest_ref) THEN
        RETURN QUERY SELECT 'manifest_not_allowed'::text, NULL::uuid;
        RETURN;
    END IF;
    PERFORM mission_control.ingress_bind_scope(
        p_installation_id, p_application_id, principal.tenant_id);
    SELECT i.ingress_id INTO existing FROM mission_control.ingress_inbox AS i
     WHERE i.installation_id = p_installation_id AND i.application_id = p_application_id
       AND i.credential_ref = principal.credential_ref
       AND i.dedupe_space = 'mission_request' AND i.dedupe_key = p_idempotency_key;
    IF FOUND THEN
        RETURN QUERY SELECT 'duplicate'::text, existing;
        RETURN;
    END IF;
    IF NOT mission_control.ingress_take_rate('launch_token', principal.principal_id, 1, now_at)
    THEN
        RETURN QUERY SELECT 'rate_limited'::text, NULL::uuid;
        RETURN;
    END IF;
    INSERT INTO mission_control.ingress_inbox (
        installation_id, application_id, tenant_id, ingress_id, received_at, trust_tier, kind,
        credential_ref, dedupe_key, body_sha256, payload, seq, run_key, unit_key, generation,
        state, attempts
    ) VALUES (
        p_installation_id, p_application_id, principal.tenant_id, p_ingress_id,
        pg_catalog.clock_timestamp(), 'launch_token', 'mission_request',
        principal.credential_ref, p_idempotency_key, p_body_sha256, p_payload, NULL, NULL,
        NULL, NULL, 'pending', 0
    ) ON CONFLICT (installation_id, application_id, credential_ref, dedupe_space, dedupe_key)
        DO NOTHING;
    IF NOT FOUND THEN
        -- A concurrent request with the same idempotency key was recorded first.
        SELECT i.ingress_id INTO existing FROM mission_control.ingress_inbox AS i
         WHERE i.installation_id = p_installation_id AND i.application_id = p_application_id
           AND i.credential_ref = principal.credential_ref
           AND i.dedupe_space = 'mission_request' AND i.dedupe_key = p_idempotency_key;
        RETURN QUERY SELECT 'duplicate'::text, existing;
        RETURN;
    END IF;
    RETURN QUERY SELECT 'accepted'::text, p_ingress_id;
END
$$;

-- The state of a launch request, readable only with the credential that made it: `queued`
-- (pending), `admitted` (drained with `outcome.mission_id`, plus the mission's lifecycle) or
-- `refused` (rejected or dead, with the typed reason). Outcome `found` or a typed rejection.
CREATE FUNCTION mission_control.ingress_mission_request_status(
    p_installation_id uuid, p_application_id text, p_credential text, p_request_id uuid
) RETURNS TABLE (outcome text, state text, mission_id uuid, reason text, lifecycle text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog
AS $$
#variable_conflict use_column
DECLARE
    principal record;
    launch mission_control.ingress_inbox%ROWTYPE;
    admitted uuid;
BEGIN
    PERFORM mission_control.ingress_bind_scope(p_installation_id, p_application_id, NULL);
    SELECT * INTO principal FROM mission_control.ingress_principal(
        p_installation_id, p_application_id, 'launch_token', p_credential, NULL, NULL, NULL,
        pg_catalog.clock_timestamp());
    IF principal.outcome <> 'ok' THEN
        RETURN QUERY SELECT principal.outcome, NULL::text, NULL::uuid, NULL::text, NULL::text;
        RETURN;
    END IF;
    PERFORM mission_control.ingress_bind_scope(
        p_installation_id, p_application_id, principal.tenant_id);
    SELECT * INTO launch FROM mission_control.ingress_inbox AS i
     WHERE i.installation_id = p_installation_id AND i.application_id = p_application_id
       AND i.ingress_id = p_request_id AND i.kind = 'mission_request'
       AND i.credential_ref = principal.credential_ref;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'not_found'::text, NULL::text, NULL::uuid, NULL::text, NULL::text;
        RETURN;
    END IF;
    IF launch.state = 'pending' THEN
        RETURN QUERY SELECT 'found'::text, 'queued'::text, NULL::uuid, NULL::text, NULL::text;
    ELSIF launch.state = 'drained' AND launch.outcome ? 'mission_id' THEN
        admitted := (launch.outcome->>'mission_id')::uuid;
        RETURN QUERY SELECT 'found'::text, 'admitted'::text, admitted, NULL::text,
            (SELECT m.lifecycle FROM mission_control.mission AS m
              WHERE m.installation_id = p_installation_id
                AND m.application_id = p_application_id
                AND m.tenant_id = principal.tenant_id AND m.mission_id = admitted);
    ELSE
        RETURN QUERY SELECT 'found'::text, 'refused'::text, NULL::uuid,
            COALESCE(launch.outcome->>'reason',
                     CASE WHEN launch.state = 'dead' THEN 'undeliverable'
                          ELSE 'not_admitted' END),
            NULL::text;
    END IF;
END
$$;

DO $grants$
DECLARE
    signature text;
BEGIN
    FOREACH signature IN ARRAY ARRAY[
        'ingress_accept(uuid, text, text, text, text, text, text, jsonb)',
        'ingress_gate(uuid, text, text, text, text, uuid, text, text, text, text, text, text, '
            || 'text)',
        'ingress_webhook(uuid, text, text, text, uuid, text, text, jsonb)',
        'ingress_artifact_prepare(uuid, text, text, text, text, uuid, text, text, bigint, text, '
            || 'integer)',
        'ingress_artifact_commit(uuid, text, text, text, text, uuid, uuid)',
        'ingress_mission_request(uuid, text, text, uuid, text, text, text, jsonb)',
        'ingress_mission_request_status(uuid, text, text, uuid)'
    ] LOOP
        EXECUTE 'REVOKE ALL ON FUNCTION mission_control.' || signature || ' FROM PUBLIC';
        EXECUTE 'GRANT EXECUTE ON FUNCTION mission_control.' || signature
            || ' TO mission_control_ingress';
    END LOOP;
END
$grants$;
-- end section: ingress functions
