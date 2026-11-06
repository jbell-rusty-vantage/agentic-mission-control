-- mission-control-db-contract: MO-20 Owner Prerequisite store (materialization-observation
-- SPEC-05 section 1; ADR-0047).
--
-- `owner_prerequisite` keeps, per installation scope, one row per human-only prerequisite a
-- lane needs before a mission spawns: the current `mc.owner_prerequisite.v1` definition (steps,
-- generated paste-ready content with its digests, verification method, freshness and the kit
-- pin and network policy digest the content was generated from), the state it has reached and
-- the evidence that set it. Generated content names variables and secret references only; no
-- secret value is ever stored here.
--
-- The typed columns mirror the record for lookups: the definition digest the evidence must
-- cite, the state, the method that set it and the credential expiry a preflight warns about.
-- State follows the method: `unmet` has no evidence, `attested` only from an attestation,
-- `verified` only from api_probe, probe_mission or file_check. A row advances in place under a
-- guard: its identity never changes, versions advance by one, it is never updated back in time
-- and nothing is deleted. Tenant scoped under forced RLS. Additive only.

CREATE TABLE mission_control.owner_prerequisite (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    prerequisite_id text NOT NULL CHECK (
        prerequisite_id ~ '^[a-z][a-z0-9_]{0,63}(\.[a-z0-9][a-z0-9_-]{0,127}){1,3}$'
        AND length(prerequisite_id) <= 256),
    provider text NOT NULL
        CHECK (provider IN ('cursor', 'anthropic', 'openai', 'github', 'mission_control')),
    prerequisite_scope text NOT NULL
        CHECK (prerequisite_scope IN ('account', 'org', 'repo', 'environment', 'host', 'user')),
    definition_digest text NOT NULL CHECK (definition_digest ~ '^sha256:[0-9a-f]{64}$'),
    state text NOT NULL CHECK (state IN ('unmet', 'attested', 'verified')),
    verification_method text
        CHECK (verification_method IN ('api_probe', 'probe_mission', 'file_check', 'attestation')),
    expires_at timestamptz,
    record jsonb NOT NULL CHECK ((jsonb_typeof(record) = 'object'
        AND record->>'schema_version' = 'mc.owner_prerequisite_record.v1'
        AND record->'prerequisite'->>'schema_version' = 'mc.owner_prerequisite.v1'
        AND record->'prerequisite'->>'id' = prerequisite_id
        AND record->'prerequisite'->>'provider' = provider
        AND record->'prerequisite'->>'scope' = prerequisite_scope
        AND record->>'definition_digest' = definition_digest
        AND record->>'state' = state
        AND (record->'evidence'->>'method') IS NOT DISTINCT FROM verification_method)
        IS TRUE),
    version bigint NOT NULL CHECK (version > 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CHECK (updated_at >= created_at),
    CHECK ((state = 'unmet') = (verification_method IS NULL)),
    CHECK (state <> 'attested' OR verification_method = 'attestation'),
    CHECK (state <> 'verified'
        OR verification_method IN ('api_probe', 'probe_mission', 'file_check')),
    CHECK (expires_at IS NULL OR verification_method IS NOT NULL),
    PRIMARY KEY (installation_id, application_id, tenant_id, prerequisite_id),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE INDEX owner_prerequisite_expiry_idx ON mission_control.owner_prerequisite
    (installation_id, application_id, tenant_id, expires_at)
    WHERE expires_at IS NOT NULL;

CREATE FUNCTION mission_control.owner_prerequisite_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'owner prerequisites are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.installation_id IS DISTINCT FROM OLD.installation_id
       OR NEW.application_id IS DISTINCT FROM OLD.application_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.prerequisite_id IS DISTINCT FROM OLD.prerequisite_id
       OR NEW.provider IS DISTINCT FROM OLD.provider
       OR NEW.prerequisite_scope IS DISTINCT FROM OLD.prerequisite_scope
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'an owner prerequisite keeps its identity, provider and scope'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'an owner prerequisite version advances by one'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'an owner prerequisite is never updated back in time'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.owner_prerequisite_guard() FROM PUBLIC;
CREATE TRIGGER owner_prerequisite_guard
    BEFORE UPDATE OR DELETE ON mission_control.owner_prerequisite
    FOR EACH ROW EXECUTE FUNCTION mission_control.owner_prerequisite_guard();

ALTER TABLE mission_control.owner_prerequisite ENABLE ROW LEVEL SECURITY;
ALTER TABLE mission_control.owner_prerequisite FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_prerequisite_scope ON mission_control.owner_prerequisite
    USING (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id())
    WITH CHECK (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id());

REVOKE ALL ON mission_control.owner_prerequisite FROM PUBLIC;
GRANT SELECT, INSERT ON mission_control.owner_prerequisite TO mission_control_runtime;
GRANT UPDATE (definition_digest, state, verification_method, expires_at, record, version,
              updated_at)
ON mission_control.owner_prerequisite TO mission_control_runtime;
GRANT SELECT ON mission_control.owner_prerequisite TO mission_control_readonly;
