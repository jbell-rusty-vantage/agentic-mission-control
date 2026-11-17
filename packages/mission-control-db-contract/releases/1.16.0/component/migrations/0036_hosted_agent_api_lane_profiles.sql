-- mission-control-db-contract: HL-06 hosted agent API lane profiles (materialization-observation
-- SPEC-06 sections 1, 8 and 9; ADR-0050 proposed, amending ADR-0035; extends 0027, 0030, 0031).
--
-- The Lane Profile vocabulary grows from seven to nine: `claude_managed` (Anthropic Managed
-- Agents) on the existing `claude` lane and `codex_agents` (the OpenAI Agents API running the
-- Codex harness) on the existing `codex` lane, both placed `cloud` (the provider runs the
-- agent loop). Their `lane_profile` rows are `mc.lane_describe.v2` stubs: every control and
-- feature is `unqualified`, nothing is qualified, and only a recorded live drill in a later
-- release can change that (HL-24, HL-25). `execution_binding` admits their typed
-- `mc.execution_binding.v2` documents like the other `claude`/`codex` profiles. The mission
-- Data Class needs no SQL: it travels in the persisted manifest bytes under their digest.
-- Additive only: no existing row or column changes; every widened CHECK still admits every
-- row it admitted before.

-- ---------------------------------------------------------------------------------------
-- lane_profile: seed the two profiles (lanes `claude`/`codex` and the v2 shape are already
-- admitted by 0031). The describe literals are DECLARED_LANE_MATRICES
-- (src/mission_control/application/execution/harness/describe.py) serialized exactly as
-- 0030/0031 serialized theirs (sorted keys, compact separators); a unit test holds the SQL to
-- the code. As in 0031, FORCE is lifted only around the seed so a non-superuser migration
-- principal (the table owner) can insert; the table ends forced exactly as 0031 left it.
ALTER TABLE mission_control.lane_profile NO FORCE ROW LEVEL SECURITY;

INSERT INTO mission_control.lane_profile
    (lane_profile, lane, placement, describe, qualified, qualified_at, qualification_ref)
VALUES
    ('claude_managed', 'claude', 'cloud',
     '{"approval_modes":["workflow_gate","provider_permission","governed_effect"],"compaction_control":"unqualified","controls":{"cancel_turn":"unqualified","end_session":"unqualified","fork":"unqualified","observe":"unqualified","pause":"unqualified","prepare":"unqualified","reattach":"unqualified","send_turn":"unqualified","snapshot":"unqualified","start":"unqualified","usage":"unqualified"},"delivery_semantics":{"cancel":"turn_boundary_guaranteed","fork":"emulated","hard_pause":"unsupported","interrupt_and_inject":"cancel_and_replace","pause":"unsupported","queue_instruction":"wait_then_send","request_continuation":"emulated","resume":"wait_then_send"},"enforcement_coverage":{"file":"unqualified","mcp":"unqualified","shell":"unqualified"},"features":{"approval_suspension":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"cancel":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"configuration_materialization":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"continuation":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"environment_selection":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"follow_up":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"launch":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"observe":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"output_custody":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"status":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"subordinate_lineage":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"usage":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null}},"hooks":{"events_supported":[],"fail_closed":false,"mechanism":"none"},"identity":{"cursor":"event_created_at_and_id","effect_ref":"tool_use_event_id","session_ref":"session_id","turn_ref":"user_message_event_id"},"instruction_channel":["agent.system","skills"],"lane":"claude","lane_profile":"claude_managed","placement":"cloud","qualified":false,"schema_version":"mc.lane_describe.v2","subagents":{"file":null,"inline":null,"readonly_supported_inline":false},"subordinate_visibility":"unqualified","usage":{"cost":"settled","tokens":"settled"},"versions":{"agent_toolset":"agent_toolset_20260401","anthropic_sdk":"1.13.0","managed_agents_beta":"managed-agents-2026-04-01"}}'::jsonb,
     false, NULL, NULL),
    ('codex_agents', 'codex', 'cloud',
     '{"approval_modes":["workflow_gate","governed_effect"],"compaction_control":"unqualified","controls":{"cancel_turn":"unqualified","end_session":"unqualified","fork":"unqualified","observe":"unqualified","pause":"unqualified","prepare":"unqualified","reattach":"unqualified","send_turn":"unqualified","snapshot":"unqualified","start":"unqualified","usage":"unqualified"},"delivery_semantics":{"cancel":"turn_boundary_guaranteed","fork":"emulated","hard_pause":"unsupported","interrupt_and_inject":"cooperative_inject","pause":"unsupported","queue_instruction":"wait_then_send","request_continuation":"emulated","resume":"wait_then_send"},"enforcement_coverage":{"file":"unsupported","mcp":"unqualified","shell":"unsupported"},"features":{"approval_suspension":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"cancel":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"configuration_materialization":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"continuation":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"environment_selection":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"follow_up":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"launch":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"observe":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"output_custody":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"status":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"subordinate_lineage":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null},"usage":{"account_enabled":"unknown","deployment_digest":null,"evidence_ref":null,"implemented":false,"os":null,"provider_scope":null,"qualified":false,"qualified_at":null,"sdk_language":null,"sdk_version":null,"status":"unqualified","transport":null}},"hooks":{"events_supported":[],"fail_closed":false,"mechanism":"none"},"identity":{"cursor":"item_id","effect_ref":"call_id","session_ref":"session_id","turn_ref":"turn_id"},"instruction_channel":["instructions","AGENTS.md"],"lane":"codex","lane_profile":"codex_agents","placement":"cloud","qualified":false,"schema_version":"mc.lane_describe.v2","subagents":{"file":null,"inline":null,"readonly_supported_inline":false},"subordinate_visibility":"unqualified","usage":{"cost":"estimated","tokens":"settled_per_turn"},"versions":{"agents_api":"beta","openai_sdk":"3.29.0"}}'::jsonb,
     false, NULL, NULL);

ALTER TABLE mission_control.lane_profile FORCE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------------------
-- execution_binding: the two profiles carry `mc.execution_binding.v2`, always bound.
ALTER TABLE mission_control.execution_binding
    DROP CONSTRAINT execution_binding_lane_binding_shape,
    ADD CONSTRAINT execution_binding_lane_binding_shape CHECK (lane_binding IS NULL OR (
        jsonb_typeof(lane_binding) = 'object'
        AND (lane_profile NOT IN ('cursor_local', 'cursor_cloud')
            OR (lane_binding->>'schema_version' = 'mc.cursor_binding.v1'
                AND lane_binding->>'lane_profile' = lane_profile))
        AND (lane_profile NOT IN ('claude_agent_sdk', 'codex', 'claude_cloud', 'codex_cloud',
                                  'claude_managed', 'codex_agents')
            OR (lane_binding->>'schema_version' = 'mc.execution_binding.v2'
                AND lane_binding->>'lane_profile' = lane_profile
                AND lane_binding->>'binding_digest' ~ '^sha256:[0-9a-f]{64}$')))),
    DROP CONSTRAINT execution_binding_cursor_lane_binding,
    ADD CONSTRAINT execution_binding_cursor_lane_binding
        CHECK (lane_profile NOT IN ('cursor_local', 'cursor_cloud',
                                    'claude_agent_sdk', 'codex', 'claude_cloud', 'codex_cloud',
                                    'claude_managed', 'codex_agents')
               OR lane_binding IS NOT NULL);

-- ---------------------------------------------------------------------------------------
-- Native identity, frames and continuation records (0027, widened by 0031).
ALTER TABLE mission_control.harness_execution
    DROP CONSTRAINT harness_execution_lane_profile_check,
    ADD CONSTRAINT harness_execution_lane_profile_check
        CHECK (lane_profile IN ('deep_agents', 'cursor_local', 'cursor_cloud',
                                'claude_agent_sdk', 'codex', 'claude_cloud', 'codex_cloud',
                                'claude_managed', 'codex_agents'));
ALTER TABLE mission_control.provider_frame
    DROP CONSTRAINT provider_frame_lane_profile_check,
    ADD CONSTRAINT provider_frame_lane_profile_check
        CHECK (lane_profile IN ('deep_agents', 'cursor_local', 'cursor_cloud',
                                'claude_agent_sdk', 'codex', 'claude_cloud', 'codex_cloud',
                                'claude_managed', 'codex_agents'));
ALTER TABLE mission_control.continuation_transfer
    DROP CONSTRAINT continuation_transfer_lane_profile_check,
    ADD CONSTRAINT continuation_transfer_lane_profile_check
        CHECK (lane_profile IN ('deep_agents', 'cursor_local', 'cursor_cloud',
                                'claude_agent_sdk', 'codex', 'claude_cloud', 'codex_cloud',
                                'claude_managed', 'codex_agents'));

-- Search documents (0026, widened by 0031) may declare host support for the two profiles.
ALTER TABLE mission_control_search.search_document
    DROP CONSTRAINT search_document_host_profiles_known,
    ADD CONSTRAINT search_document_host_profiles_known CHECK (
        host_profiles <@ ARRAY['deep_agents', 'cursor_local', 'cursor_cloud',
                               'claude_agent_sdk', 'codex', 'claude_cloud', 'codex_cloud',
                               'claude_managed', 'codex_agents']::text[]
    );

-- Published capability rows (0025, widened by 0031) declare host support per profile; the
-- validator behind `asset_version_host_support_check` admits the two profiles. Same body
-- otherwise, same grants (CREATE OR REPLACE keeps them); every previously valid document
-- stays valid.
CREATE OR REPLACE FUNCTION mission_control.capability_host_support_valid(document jsonb)
RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path = pg_catalog AS $$
    SELECT document->>'schema_version' = 'mc.capability_host_support.v1'
       AND jsonb_typeof(document->'profiles') = 'object'
       AND NOT EXISTS (
           SELECT 1
             FROM jsonb_each(document->'profiles') AS profile(lane, entry)
            WHERE profile.lane NOT IN
                      ('deep_agents', 'cursor_local', 'cursor_cloud', 'claude_agent_sdk', 'codex',
                       'claude_cloud', 'codex_cloud', 'claude_managed', 'codex_agents')
               OR jsonb_typeof(profile.entry) <> 'object'
               OR coalesce(profile.entry->>'status', '') NOT IN
                      ('supported', 'unsupported', 'unqualified')
               OR (profile.entry ? 'overlay'
                   AND jsonb_typeof(profile.entry->'overlay') <> 'object'))
$$;
