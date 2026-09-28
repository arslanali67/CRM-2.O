-- M32: pg_restore runs with an empty search_path, so the generated content_hash column must call
-- the 3-argument hash schema-qualified. Same result as before; existing approvals stay valid.
CREATE OR REPLACE FUNCTION email_content_hash(to_email text, subject text, body text, cv_version_id bigint)
RETURNS bytea LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN cv_version_id IS NULL THEN public.email_content_hash(to_email, subject, body)
                ELSE sha256(public.email_content_hash(to_email, subject, body) || int8send(cv_version_id)) END
$$;
