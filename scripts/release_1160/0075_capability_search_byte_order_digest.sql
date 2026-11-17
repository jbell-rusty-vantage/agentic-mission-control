-- Release 1.16.0 (MC-F, 2026-11-16): the capability search source-set digest sorts in byte order.
--
-- `mission_control_search.activate_generation` (0022) recomputes the source-set digest of a
-- generation with `string_agg(... ORDER BY d.asset_kind, d.logical_id, d.revision,
-- d.source_digest)`. Those text keys sorted under the database's default collation. The
-- application computes the expected digest (`projection_source_set_digest`,
-- `application/capabilities/catalog_projection_generation.py`) in Python codepoint order, which
-- is byte order of the UTF-8 encoding. The two agreed only while no two logical ids differed
-- in a way a locale collation reorders: `mc.catalog.agent-capabilities@1.1.0` added
-- `mcp.github.tool.list-issue-fields`, `...list-issues` and `...list-issue-types`, which
-- `en_US.utf8` (the default of the compose PostgreSQL, the CI service container and Supabase
-- projects) orders differently, because it ignores `-` on its first comparison level. On such a
-- database every rebuild failed with `projection generation count or source digest
-- verification failed`; only a database created with a "C" collation could activate.
--
-- This migration replaces the function body only: every text sort key of the digest aggregate
-- carries `COLLATE "C"`, which is byte order on every server and equal to the application's
-- order on a UTF-8 database. `revision` stays an integer key. Every other check, the
-- signature, `SECURITY INVOKER`, `SET search_path = pg_catalog` and the grants are unchanged
-- (CREATE OR REPLACE keeps the owner and ACL; the REVOKE and GRANT below restate them). No
-- table, row or index changes: a generation already active keeps its recorded digest, which
-- the application computed and the old function only accepted when both orders agreed.

CREATE OR REPLACE FUNCTION mission_control_search.activate_generation(
    requested_tenant_scope text,
    requested_generation text,
    requested_expected_count integer,
    requested_expected_digest text
)
RETURNS TABLE (activated_count integer, activated_source_set_digest text)
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $function$
DECLARE
    ctx_installation uuid := mission_control.ctx_installation_id();
    ctx_application text := mission_control.ctx_application_id();
    generation_record mission_control_search.projection_generation%ROWTYPE;
    observed_count integer;
    observed_digest text;
    observed_model_count integer;
    observed_dimension_count integer;
    observed_format_count integer;
BEGIN
    IF ctx_installation IS NULL OR ctx_application IS NULL THEN
        RAISE EXCEPTION 'installation catalog context is required'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT * INTO generation_record
    FROM mission_control_search.projection_generation AS g
    WHERE g.installation_id = ctx_installation
      AND g.application_id = ctx_application
      AND g.tenant_scope = requested_tenant_scope
      AND g.projection_generation = requested_generation
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'projection generation does not exist';
    END IF;
    IF generation_record.state <> 'building' THEN
        RAISE EXCEPTION 'projection generation is not building';
    END IF;
    IF generation_record.expected_count <> requested_expected_count
       OR generation_record.expected_source_set_digest <> requested_expected_digest THEN
        RAISE EXCEPTION 'projection generation expectation changed';
    END IF;

    SELECT
        count(*)::integer,
        'sha256:' || pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(
            coalesce(string_agg(
                d.asset_kind || '|' || d.logical_id || '|' || d.revision::text || '|'
                    || d.source_digest,
                E'\n' ORDER BY d.asset_kind COLLATE "C", d.logical_id COLLATE "C", d.revision,
                    d.source_digest COLLATE "C"
            ), ''), 'UTF8')), 'hex'),
        count(DISTINCT d.embedding_model_id)::integer,
        count(DISTINCT d.embedding_dimensions)::integer,
        count(DISTINCT d.search_document_format_version)::integer
    INTO observed_count, observed_digest, observed_model_count, observed_dimension_count,
        observed_format_count
    FROM mission_control_search.search_document AS d
    WHERE d.installation_id = ctx_installation
      AND d.application_id = ctx_application
      AND d.tenant_scope = requested_tenant_scope
      AND d.projection_generation = requested_generation
      AND d.asset_kind = ANY(generation_record.selected_kinds);

    IF observed_count <> requested_expected_count
       OR observed_digest <> requested_expected_digest THEN
        RAISE EXCEPTION 'projection generation count or source digest verification failed';
    END IF;
    IF observed_count > 0 AND (
        observed_model_count <> 1 OR observed_dimension_count <> 1 OR observed_format_count <> 1
    ) THEN
        RAISE EXCEPTION 'projection generation embedding contract verification failed';
    END IF;
    IF EXISTS (
        SELECT 1 FROM mission_control_search.search_document AS d
        WHERE d.installation_id = ctx_installation
          AND d.application_id = ctx_application
          AND d.tenant_scope = requested_tenant_scope
          AND d.projection_generation = requested_generation
          AND d.asset_kind = ANY(generation_record.selected_kinds)
          AND (d.embedding_model_id <> generation_record.embedding_model_id
               OR d.embedding_dimensions <> generation_record.embedding_dimensions
               OR d.search_document_format_version
                    <> generation_record.search_document_format_version)
    ) THEN
        RAISE EXCEPTION 'projection generation contains incompatible rows';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM mission_control_search.active_generation AS a
        JOIN mission_control_search.projection_generation AS c
          ON c.installation_id = a.installation_id
         AND c.application_id = a.application_id
         AND c.tenant_scope = a.tenant_scope
         AND c.projection_generation = a.projection_generation
        WHERE a.installation_id = ctx_installation
          AND a.application_id = ctx_application
          AND a.tenant_scope = requested_tenant_scope
          AND NOT (a.asset_kind = ANY(generation_record.selected_kinds))
          AND (c.embedding_model_id <> generation_record.embedding_model_id
               OR c.embedding_dimensions <> generation_record.embedding_dimensions
               OR c.search_document_format_version
                    <> generation_record.search_document_format_version)
    ) THEN
        RAISE EXCEPTION 'projection generation is incompatible with another active kind';
    END IF;

    INSERT INTO mission_control_search.active_generation
        (installation_id, application_id, tenant_scope, asset_kind, projection_generation,
         activated_at)
    SELECT ctx_installation, ctx_application, requested_tenant_scope, selected_kind,
           requested_generation, pg_catalog.clock_timestamp()
    FROM unnest(generation_record.selected_kinds) AS selected_kind
    ON CONFLICT (installation_id, application_id, tenant_scope, asset_kind)
    DO UPDATE SET projection_generation = EXCLUDED.projection_generation,
                  activated_at = EXCLUDED.activated_at;

    UPDATE mission_control_search.projection_generation AS g
    SET actual_count = observed_count,
        actual_source_set_digest = observed_digest,
        state = 'active',
        verified_at = pg_catalog.clock_timestamp(),
        activated_at = pg_catalog.clock_timestamp()
    WHERE g.installation_id = ctx_installation
      AND g.application_id = ctx_application
      AND g.tenant_scope = requested_tenant_scope
      AND g.projection_generation = requested_generation;

    UPDATE mission_control_search.projection_generation AS prior
    SET state = 'superseded'
    WHERE prior.installation_id = ctx_installation
      AND prior.application_id = ctx_application
      AND prior.tenant_scope = requested_tenant_scope
      AND prior.projection_generation <> requested_generation
      AND prior.state = 'active'
      AND NOT EXISTS (
          SELECT 1 FROM mission_control_search.active_generation AS a
          WHERE a.installation_id = prior.installation_id
            AND a.application_id = prior.application_id
            AND a.tenant_scope = prior.tenant_scope
            AND a.projection_generation = prior.projection_generation
      );

    RETURN QUERY SELECT observed_count, observed_digest;
END;
$function$;
REVOKE ALL ON FUNCTION mission_control_search.activate_generation(text, text, integer, text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION mission_control_search.activate_generation(text, text, integer, text)
TO mission_control_runtime, mission_control_catalog_writer, mission_control_outbox_worker;
