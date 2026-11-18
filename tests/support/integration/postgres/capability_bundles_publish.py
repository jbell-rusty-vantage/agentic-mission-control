"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_capability_bundles_publish.py.
"""

from __future__ import annotations

SYNTHETIC_STORAGE = """
DO $$ BEGIN CREATE ROLE authenticated NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE SCHEMA storage;
CREATE TABLE storage.buckets (
    id text PRIMARY KEY, name text NOT NULL, public boolean NOT NULL DEFAULT false,
    file_size_limit bigint, allowed_mime_types text[]);
CREATE TABLE storage.objects (
    id bigserial PRIMARY KEY, bucket_id text NOT NULL REFERENCES storage.buckets (id),
    name text NOT NULL, content bytea, UNIQUE (bucket_id, name));
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;
CREATE FUNCTION storage.foldername(name text) RETURNS text[]
    LANGUAGE sql IMMUTABLE AS $f$
    SELECT (string_to_array(name, '/'))[1:array_length(string_to_array(name, '/'), 1) - 1]
    $f$;
GRANT USAGE ON SCHEMA storage TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON storage.objects TO authenticated;
GRANT USAGE, SELECT ON SEQUENCE storage.objects_id_seq TO authenticated;
"""
