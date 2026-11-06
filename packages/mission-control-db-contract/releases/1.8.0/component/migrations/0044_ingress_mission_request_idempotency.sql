-- MO-79: a launch idempotency key binds the exact stored request body.
-- Additive successor to 0035: preserve its signature, SECURITY DEFINER/search_path,
-- ownership and existing ACL. CREATE OR REPLACE retains the original execute grants.
-- Check digest and payload in both replay paths; the definer API receives a supplied
-- digest, so equal digests alone cannot prove equal bodies for a direct SQL caller. Conflicts
-- never return another body's request id and never update the original inbox receipt.

CREATE OR REPLACE FUNCTION mission_control.ingress_mission_request(
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
    existing_digest text;
    existing_payload jsonb;
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
    SELECT i.ingress_id, i.body_sha256, i.payload
      INTO existing, existing_digest, existing_payload
      FROM mission_control.ingress_inbox AS i
     WHERE i.installation_id = p_installation_id AND i.application_id = p_application_id
       AND i.credential_ref = principal.credential_ref
       AND i.dedupe_space = 'mission_request' AND i.dedupe_key = p_idempotency_key;
    IF FOUND THEN
        IF existing_digest IS DISTINCT FROM p_body_sha256
           OR existing_payload IS DISTINCT FROM p_payload THEN
            RETURN QUERY SELECT 'dedupe_conflict'::text, NULL::uuid;
        ELSE
            RETURN QUERY SELECT 'duplicate'::text, existing;
        END IF;
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
        SELECT i.ingress_id, i.body_sha256, i.payload
          INTO existing, existing_digest, existing_payload
          FROM mission_control.ingress_inbox AS i
         WHERE i.installation_id = p_installation_id AND i.application_id = p_application_id
           AND i.credential_ref = principal.credential_ref
           AND i.dedupe_space = 'mission_request' AND i.dedupe_key = p_idempotency_key;
        IF existing_digest IS DISTINCT FROM p_body_sha256
           OR existing_payload IS DISTINCT FROM p_payload THEN
            RETURN QUERY SELECT 'dedupe_conflict'::text, NULL::uuid;
        ELSE
            RETURN QUERY SELECT 'duplicate'::text, existing;
        END IF;
        RETURN;
    END IF;
    RETURN QUERY SELECT 'accepted'::text, p_ingress_id;
END
$$;
