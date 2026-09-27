-- M2: outbound emails with DB-enforced approval, append-only audit log.

-- convert_to() is marked STABLE, but converting to a fixed target encoding
-- is deterministic, so wrapping it as IMMUTABLE is safe for a generated column.
CREATE FUNCTION email_content_hash(to_email text, subject text, body text)
RETURNS bytea LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT sha256(convert_to(to_email || E'\x1f' || subject || E'\x1f' || body, 'UTF8'))
$$;

CREATE TABLE outbound_emails (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    to_email              text NOT NULL CHECK (to_email ~ '^[^@\s]+@[^@\s]+$'),
    subject               text NOT NULL,
    body                  text NOT NULL,
    status                text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'approved', 'queued', 'sending', 'sent', 'failed', 'cancelled')),
    content_hash          bytea GENERATED ALWAYS AS (email_content_hash(to_email, subject, body)) STORED,
    approved_at           timestamptz,
    approved_content_hash bytea,
    sent_at               timestamptz,
    provider_message_id   text,
    idempotency_key       uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    created_at            timestamptz NOT NULL DEFAULT now(),

    -- Nothing can be approved, queued, sent or in flight unless it was approved
    -- for exactly its current content. Editing after approval requires going back to draft.
    CONSTRAINT no_send_without_approval CHECK (
        status NOT IN ('approved', 'queued', 'sending', 'sent')
        OR (approved_at IS NOT NULL AND approved_content_hash = content_hash)
    ),
    CONSTRAINT sent_requires_sent_at CHECK (status <> 'sent' OR sent_at IS NOT NULL)
);

-- At most one in-flight email per recipient.
CREATE UNIQUE INDEX outbound_emails_one_in_flight_per_recipient
    ON outbound_emails (lower(to_email))
    WHERE status IN ('approved', 'queued', 'sending');

CREATE UNIQUE INDEX outbound_emails_provider_message_id
    ON outbound_emails (provider_message_id)
    WHERE provider_message_id IS NOT NULL;

CREATE TABLE audit_log (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    actor       text NOT NULL,
    action      text NOT NULL,
    entity_type text,
    entity_id   bigint,
    data        jsonb NOT NULL DEFAULT '{}'
);

-- ponytail: the table owner can still disable these triggers; M30 can switch the
-- app to a non-owner role if that matters.
CREATE FUNCTION audit_log_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END
$$;

CREATE TRIGGER audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();

CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only();
