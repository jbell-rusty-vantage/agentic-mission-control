-- mission-control-db-contract: MO-16 environment preparation records and readiness levels
-- (materialization-observation SPEC-01 section 8; the deferred item C15).
--
-- `environment_readiness_level` is the readiness ladder as reference data, seeded here like
-- `lane_profile` (0030): declared, rendered, delivered, prepared, discovered, exercised, each
-- with its rank. Every role may read it, none may write it.
--
-- `environment_preparation` persists `mc.environment_preparation.v1`: what one harness
-- execution generation's environment preparation proved against its sealed binding (kit pin,
-- policy digests, delivery channels, secret names and channels, receipt digest, the readiness
-- level with a timestamp per level, omissions and degradations). The typed columns mirror the
-- record for lookups (by run and by the declaration digest the manifest Validation Report and
-- start receipt cite). A row advances in place under a guard: its identity never changes, the
-- readiness never regresses, a recorded receipt never changes, versions advance by one and
-- nothing is deleted. Tenant scoped under forced RLS. Additive only.

CREATE TABLE mission_control.environment_readiness_level (
    readiness text PRIMARY KEY CHECK (readiness ~ '^[a-z]{1,32}$'),
    rank smallint NOT NULL UNIQUE CHECK (rank >= 0)
);

INSERT INTO mission_control.environment_readiness_level (readiness, rank)
VALUES
    ('declared', 0),
    ('rendered', 1),
    ('delivered', 2),
    ('prepared', 3),
    ('discovered', 4),
    ('exercised', 5);

ALTER TABLE mission_control.environment_readiness_level ENABLE ROW LEVEL SECURITY;
ALTER TABLE mission_control.environment_readiness_level FORCE ROW LEVEL SECURITY;
CREATE POLICY environment_readiness_level_read ON mission_control.environment_readiness_level
    FOR SELECT USING (true);
CREATE TRIGGER environment_readiness_level_immutable
    BEFORE UPDATE OR DELETE ON mission_control.environment_readiness_level
    FOR EACH ROW EXECUTE FUNCTION mission_control.reject_mutation();
REVOKE ALL ON mission_control.environment_readiness_level FROM PUBLIC;
GRANT SELECT ON mission_control.environment_readiness_level
    TO mission_control_runtime, mission_control_family_writer, mission_control_readonly;

CREATE TABLE mission_control.environment_preparation (
    installation_id uuid NOT NULL,
    application_id text NOT NULL,
    tenant_id uuid NOT NULL,
    preparation_id uuid PRIMARY KEY,
    run_key text NOT NULL CHECK (run_key <> '' AND length(run_key) <= 512),
    harness_execution_id uuid NOT NULL,
    generation bigint NOT NULL CHECK (generation > 0),
    lane_profile text NOT NULL REFERENCES mission_control.lane_profile (lane_profile),
    binding_digest text NOT NULL CHECK (binding_digest ~ '^sha256:[0-9a-f]{64}$'),
    declaration_digest text NOT NULL CHECK (declaration_digest ~ '^sha256:[0-9a-f]{64}$'),
    readiness text NOT NULL
        REFERENCES mission_control.environment_readiness_level (readiness),
    receipt_digest text CHECK (receipt_digest ~ '^sha256:[0-9a-f]{64}$'),
    record jsonb NOT NULL CHECK ((jsonb_typeof(record) = 'object'
        AND record->>'schema_version' = 'mc.environment_preparation.v1'
        AND record->>'preparation_id' = preparation_id::text
        AND record->>'run_key' = run_key
        AND record->>'harness_execution_id' = harness_execution_id::text
        AND (record->>'generation')::bigint = generation
        AND record->>'lane_profile' = lane_profile
        AND record->>'binding_digest' = binding_digest
        AND record->>'declaration_digest' = declaration_digest
        AND record->>'readiness' = readiness
        AND (record->>'receipt_digest') IS NOT DISTINCT FROM receipt_digest) IS TRUE),
    version bigint NOT NULL CHECK (version > 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CHECK (updated_at >= created_at),
    UNIQUE (installation_id, application_id, tenant_id, harness_execution_id, generation),
    FOREIGN KEY (installation_id, application_id, tenant_id)
        REFERENCES mission_control.tenant (installation_id, application_id, tenant_id)
);
CREATE INDEX environment_preparation_run_idx ON mission_control.environment_preparation
    (installation_id, application_id, tenant_id, run_key, declaration_digest);

CREATE FUNCTION mission_control.environment_preparation_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $guard$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'environment preparation records are never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.preparation_id IS DISTINCT FROM OLD.preparation_id
       OR NEW.installation_id IS DISTINCT FROM OLD.installation_id
       OR NEW.application_id IS DISTINCT FROM OLD.application_id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.run_key IS DISTINCT FROM OLD.run_key
       OR NEW.harness_execution_id IS DISTINCT FROM OLD.harness_execution_id
       OR NEW.generation IS DISTINCT FROM OLD.generation
       OR NEW.lane_profile IS DISTINCT FROM OLD.lane_profile
       OR NEW.binding_digest IS DISTINCT FROM OLD.binding_digest
       OR NEW.declaration_digest IS DISTINCT FROM OLD.declaration_digest
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'an environment preparation is bound to its attempt and declaration'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (SELECT rank FROM mission_control.environment_readiness_level
        WHERE readiness = NEW.readiness)
       < (SELECT rank FROM mission_control.environment_readiness_level
          WHERE readiness = OLD.readiness) THEN
        RAISE EXCEPTION 'environment readiness never regresses'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.receipt_digest IS NOT NULL
       AND NEW.receipt_digest IS DISTINCT FROM OLD.receipt_digest THEN
        RAISE EXCEPTION 'an environment preparation receipt is immutable'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'an environment preparation version advances by one'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'an environment preparation is never updated back in time'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$guard$;
REVOKE ALL ON FUNCTION mission_control.environment_preparation_guard() FROM PUBLIC;
CREATE TRIGGER environment_preparation_guard
    BEFORE UPDATE OR DELETE ON mission_control.environment_preparation
    FOR EACH ROW EXECUTE FUNCTION mission_control.environment_preparation_guard();

ALTER TABLE mission_control.environment_preparation ENABLE ROW LEVEL SECURITY;
ALTER TABLE mission_control.environment_preparation FORCE ROW LEVEL SECURITY;
CREATE POLICY environment_preparation_scope ON mission_control.environment_preparation
    USING (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id())
    WITH CHECK (installation_id = mission_control.ctx_installation_id()
        AND application_id = mission_control.ctx_application_id()
        AND tenant_id = mission_control.ctx_tenant_id());

REVOKE ALL ON mission_control.environment_preparation FROM PUBLIC;
GRANT SELECT, INSERT ON mission_control.environment_preparation TO mission_control_runtime;
GRANT UPDATE (readiness, receipt_digest, record, version, updated_at)
ON mission_control.environment_preparation TO mission_control_runtime;
GRANT SELECT ON mission_control.environment_preparation TO mission_control_readonly;
