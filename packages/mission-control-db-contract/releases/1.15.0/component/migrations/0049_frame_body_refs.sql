-- Release 1.4.4 (TRACING-PROPOSAL §P2, TR-D3): the frame-body reference scheme.
-- Nothing structural: `provider_frame.body_artifact_ref` exists since 0027. A promoted frame
-- body is the canonical body bytes staged in the content-addressed payload store and
-- referenced as
--
--     frame-body://sha256:<hex>?bytes=<n>&type=<media>
--
-- where `<hex>` is the body digest the frame row already carries, `<n>` its byte length and
-- `<media>` its media type. The body is evidence of a frame, already registered by the frame
-- row (digest, bytes, media type); it is not a governed artifact and writes no
-- `artifact_metadata_revision` row. It is read by the granted body reader under
-- `workflow.result.read` within the run's scope, and the bytes are verified against the
-- digest on every read. The governed `artifact://` path stays for artifacts the agent submits.
COMMENT ON COLUMN mission_control.provider_frame.body_artifact_ref IS
    'Promoted full body: frame-body://sha256:<hex>?bytes=<n>&type=<media> over the '
    'content-addressed payload store (1.4.4), or a governed artifact:// reference.';
COMMENT ON COLUMN mission_control.provider_frame.retention_class IS
    'delta (message_delta, thinking_delta, tool_call_delta, heartbeat, status) expires by '
    'frame_retention_policy.retain_days; step frames live for the mission''s evidence life '
    'unless step_retain_days is set.';
COMMENT ON COLUMN mission_control.frame_retention_policy.step_retain_days IS
    'Days a step-class frame of a terminal run is kept; NULL keeps it for the mission''s '
    'evidence life.';
COMMENT ON COLUMN mission_control.frame_retention_policy.prune_mode IS
    'Reserved (TR-D17): delete removes the frame row; tombstone keeps the row and removes the '
    'promoted body.';
COMMENT ON COLUMN mission_control.cognition_point.restore_level IS
    'How much of the point the lane can restore (R3 native lineage ... R0 nothing); lowered '
    'in place when the saver prunes.';
