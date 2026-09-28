-- M31 (found by safety case S3): a NULL approved_content_hash made the approval check evaluate to NULL,
-- which a CHECK constraint treats as passing. A send state now needs a non-NULL hash equal to the content.
ALTER TABLE outbound_emails
    DROP CONSTRAINT no_send_without_approval,
    ADD CONSTRAINT no_send_without_approval CHECK (
        status NOT IN ('approved', 'queued', 'sending', 'sent')
        OR (approved_at IS NOT NULL AND approved_content_hash IS NOT NULL
            AND approved_content_hash = content_hash)
    );
