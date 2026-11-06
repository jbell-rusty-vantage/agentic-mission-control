-- Bounded normalized lifecycle facts survive raw-body excerpt truncation/retention.
-- This is not a second raw provider body: writers allowlist scalar status facts.
-- Existing immutable frames retain the empty default; never infer missing facts.
ALTER TABLE mission_control.provider_frame
    ADD COLUMN lifecycle_body jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD CONSTRAINT provider_frame_lifecycle_body_object
        CHECK (jsonb_typeof(lifecycle_body) = 'object'),
    ADD CONSTRAINT provider_frame_lifecycle_body_size
        CHECK (octet_length(lifecycle_body::text) <= 4096);
