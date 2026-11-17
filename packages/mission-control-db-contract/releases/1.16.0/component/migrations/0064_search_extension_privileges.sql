-- Release 1.8.0 (Sprint OC W1 / OVE-169, defect D7): the capability roles that rank capability
-- search, or write its projection, may name the extension objects they use in schema `extensions`.
--
-- Migrations 0022 and 0026 put the projection's `embedding extensions.vector` column and its
-- `extensions.gin_trgm_ops` / `extensions.vector_cosine_ops` indexes in place. The runtime adapter
-- (src/mission_control/adapters/postgres/capability/capability_search_repository.py) casts
-- `$n::extensions.vector`, orders by `OPERATOR(extensions.<=>)` and ranks names with
-- `extensions.word_similarity`. Each of those names is looked up in schema `extensions`, which
-- needs USAGE on the schema. PostgreSQL grants PUBLIC no USAGE on a schema other than `public`,
-- and on Supabase the pre-provisioned `extensions` schema is usable by the platform roles only, so
-- every restricted login (a member of mission_control_runtime) failed with `permission denied for
-- schema extensions` (W1 evidence D7).
--
-- Grant: USAGE on schema `extensions`, nothing else, to exactly the three roles that hold
-- INSERT/UPDATE on `mission_control_search.search_document` and run the ranked branches:
-- mission_control_runtime, mission_control_catalog_writer and mission_control_outbox_worker.
-- No CREATE, no other schema, no object inside `extensions` is altered, and
-- mission_control_readonly keeps reading the projection without naming extension objects.
-- EXECUTE on the extension functions and USAGE on the vector type are PUBLIC by default (the
-- extension scripts do not revoke them); the guard verifies them instead of granting more, so a
-- server that revoked them refuses this release instead of receiving broader grants.
--
-- Schema `extensions` is not owned by this component. The grant lands only when the installing
-- login owns the schema or holds USAGE on it WITH GRANT OPTION; otherwise PostgreSQL reports a
-- warning ("no privileges were granted") and grants nothing. The guard turns that into an error
-- (SQLSTATE 42501), so the release apply rolls back as a whole instead of installing a search
-- that cannot run. The schema's ACL is outside the component fingerprint (owned schemas only); a
-- protected-object snapshot of `extensions` records the change as a grants difference.

GRANT USAGE ON SCHEMA extensions
TO mission_control_runtime, mission_control_catalog_writer, mission_control_outbox_worker;

DO $search_extension_privileges$
DECLARE
    capability_role text;
BEGIN
    FOREACH capability_role IN ARRAY ARRAY[
        'mission_control_runtime',
        'mission_control_catalog_writer',
        'mission_control_outbox_worker'
    ] LOOP
        IF NOT pg_catalog.has_schema_privilege(capability_role, 'extensions', 'USAGE') THEN
            RAISE EXCEPTION USING
                ERRCODE = '42501',
                MESSAGE = pg_catalog.format(
                    'release 1.8.0 (0064): %s holds no USAGE on schema extensions', capability_role
                ),
                HINT = 'The installing login must own schema extensions or hold USAGE on it WITH '
                    'GRANT OPTION; the whole release apply was rolled back.';
        END IF;
        IF NOT pg_catalog.has_type_privilege(capability_role, 'extensions.vector', 'USAGE')
           OR NOT pg_catalog.has_function_privilege(
               capability_role,
               'extensions.cosine_distance(extensions.vector, extensions.vector)',
               'EXECUTE'
           )
           OR NOT pg_catalog.has_function_privilege(
               capability_role, 'extensions.word_similarity(text, text)', 'EXECUTE'
           ) THEN
            RAISE EXCEPTION USING
                ERRCODE = '42501',
                MESSAGE = pg_catalog.format(
                    'release 1.8.0 (0064): %s cannot use extensions.vector, its cosine distance '
                    'or extensions.word_similarity', capability_role
                ),
                HINT = 'Their default PUBLIC privileges were revoked on this server; restore them '
                    'as the extension owner before applying 1.8.0.';
        END IF;
    END LOOP;
END
$search_extension_privileges$;
