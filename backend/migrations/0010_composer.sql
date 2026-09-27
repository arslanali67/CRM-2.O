-- M10: optional CV attachment, bound into the approved content hash.

ALTER TABLE outbound_emails ADD COLUMN cv_version_id bigint REFERENCES cv_versions (id);

-- Same hash as before when there is no attachment, so existing approvals stay valid.
CREATE FUNCTION email_content_hash(to_email text, subject text, body text, cv_version_id bigint)
RETURNS bytea LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN cv_version_id IS NULL THEN email_content_hash(to_email, subject, body)
                ELSE sha256(email_content_hash(to_email, subject, body) || int8send(cv_version_id)) END
$$;

ALTER TABLE outbound_emails
    ALTER COLUMN content_hash SET EXPRESSION AS (email_content_hash(to_email, subject, body, cv_version_id));
