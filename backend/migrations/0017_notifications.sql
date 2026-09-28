-- M17: in-app notifications, created by the database so every event yields exactly one.

CREATE TABLE notifications (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind        text NOT NULL CHECK (kind IN ('reply', 'auto_reply', 'bounce', 'send_failed', 'send_cancelled',
                                              'sync_failing', 'ai_failed')),
    source_type text NOT NULL CHECK (source_type IN ('inbound_message', 'outbound_email', 'mailbox', 'ai_analysis')),
    source_id   text NOT NULL,
    priority    text NOT NULL CHECK (priority IN ('high', 'normal', 'low')),
    title       text NOT NULL,
    body        text NOT NULL DEFAULT '',
    link        text NOT NULL,
    company_id  bigint REFERENCES companies (id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    read_at     timestamptz,
    CONSTRAINT one_notification_per_event UNIQUE (kind, source_type, source_id)
);

CREATE INDEX notifications_recent ON notifications (created_at DESC);
CREATE INDEX notifications_unread ON notifications (created_at DESC) WHERE read_at IS NULL;

-- Priority by AI classification (M16 labels).
CREATE FUNCTION notification_priority(ai_label text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN ai_label IN ('offer', 'interview_request', 'scheduling', 'needs_info') THEN 'high'
        WHEN ai_label IN ('interested', 'referral', 'application_redirect', 'unsubscribe_request') THEN 'normal'
        ELSE 'low' END
$$;

-- 1. Inbound messages labelled reply / auto_reply / bounce (M15). Unrelated mail never notifies.
CREATE FUNCTION notify_inbound() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    who text := coalesce(nullif(NEW.from_name, ''), NEW.from_email);
BEGIN
    INSERT INTO notifications (kind, source_type, source_id, priority, title, body, link, company_id)
    VALUES (
        NEW.label, 'inbound_message', NEW.id::text,
        CASE NEW.label WHEN 'reply' THEN 'normal' WHEN 'auto_reply' THEN 'low'
                       ELSE CASE WHEN NEW.bounce_type = 'hard' THEN 'normal' ELSE 'low' END END,
        CASE NEW.label WHEN 'reply' THEN 'Reply from ' || who
                       WHEN 'auto_reply' THEN 'Auto-reply from ' || who
                       ELSE initcap(coalesce(NEW.bounce_type, 'soft')) || ' bounce: ' || NEW.subject END,
        NEW.subject,
        '/threads/' || coalesce(NEW.gmail_thrid, 'in-' || NEW.id) || '#in-' || NEW.id,
        NEW.company_id)
    ON CONFLICT ON CONSTRAINT one_notification_per_event DO NOTHING;
    RETURN NULL;
END
$$;

CREATE TRIGGER inbound_messages_notify
    AFTER UPDATE OF label ON inbound_messages
    FOR EACH ROW WHEN (NEW.label IS DISTINCT FROM OLD.label AND NEW.label IN ('reply', 'auto_reply', 'bounce'))
    EXECUTE FUNCTION notify_inbound();

-- 2. AI analysis (M16): a verified label re-prioritises the SAME reply notification; giving up after
--    all retries is its own event.
CREATE FUNCTION notify_ai() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'ok' THEN
        UPDATE notifications
        SET priority = notification_priority(NEW.label),
            title = split_part(title, ' · ', 1) || ' · ' || replace(NEW.label, '_', ' '),
            body = coalesce(nullif(NEW.summary, ''), body),
            updated_at = now()
        WHERE kind = 'reply' AND source_type = 'inbound_message' AND source_id = NEW.inbound_message_id::text;
    ELSIF NEW.status = 'error' AND NEW.attempts >= 3 THEN
        INSERT INTO notifications (kind, source_type, source_id, priority, title, body, link, company_id)
        SELECT 'ai_failed', 'ai_analysis', NEW.id::text, 'normal', 'AI analysis failed after 3 attempts',
               coalesce(NEW.error, ''), '/inbox', m.company_id
        FROM inbound_messages m WHERE m.id = NEW.inbound_message_id
        ON CONFLICT ON CONSTRAINT one_notification_per_event DO NOTHING;
    END IF;
    RETURN NULL;
END
$$;

CREATE TRIGGER ai_analyses_notify
    AFTER INSERT OR UPDATE ON ai_analyses
    FOR EACH ROW EXECUTE FUNCTION notify_ai();

-- 3. Sending problems: failed, or cancelled by send-time safety checks / because the company replied.
--    (Cancellations the owner caused - discard, a new block - do not notify.)
CREATE FUNCTION notify_outbound() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    ctx jsonb := coalesce(nullif(current_setting('app.status_context', true), ''), '{}')::jsonb;
BEGIN
    IF NEW.status = 'failed' THEN
        INSERT INTO notifications (kind, source_type, source_id, priority, title, body, link, company_id)
        VALUES ('send_failed', 'outbound_email', NEW.id::text, 'normal', 'Email to ' || NEW.to_email || ' failed',
                coalesce(NEW.failure_reason, ''), '/outbox/' || NEW.id, NEW.company_id)
        ON CONFLICT ON CONSTRAINT one_notification_per_event DO NOTHING;
    ELSIF NEW.status = 'cancelled' AND ctx->>'reason' IN ('safety_checks', 'company_replied') THEN
        INSERT INTO notifications (kind, source_type, source_id, priority, title, body, link, company_id)
        VALUES ('send_cancelled', 'outbound_email', NEW.id::text, 'normal',
                'Email to ' || NEW.to_email || ' was not sent',
                coalesce(NEW.cancel_reason, ''), '/outbox/' || NEW.id, NEW.company_id)
        ON CONFLICT ON CONSTRAINT one_notification_per_event DO NOTHING;
    END IF;
    RETURN NULL;
END
$$;

CREATE TRIGGER outbound_emails_notify
    AFTER UPDATE OF status ON outbound_emails
    FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status AND NEW.status IN ('failed', 'cancelled'))
    EXECUTE FUNCTION notify_outbound();

-- 4. Inbox sync failing 3 runs in a row: one notification per failing streak.
ALTER TABLE mailbox_sync
    ADD COLUMN consecutive_failures int NOT NULL DEFAULT 0,
    ADD COLUMN failing_since timestamptz;

CREATE FUNCTION notify_sync() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO notifications (kind, source_type, source_id, priority, title, body, link)
    VALUES ('sync_failing', 'mailbox', NEW.mailbox || '@' || NEW.failing_since, 'normal',
            'Inbox sync is failing (' || coalesce(NEW.imap_name, NEW.mailbox) || ')',
            coalesce(NEW.last_error, ''), '/inbox')
    ON CONFLICT ON CONSTRAINT one_notification_per_event DO NOTHING;
    RETURN NULL;
END
$$;

CREATE TRIGGER mailbox_sync_notify
    AFTER INSERT OR UPDATE ON mailbox_sync
    FOR EACH ROW WHEN (NEW.consecutive_failures >= 3 AND NEW.failing_since IS NOT NULL)
    EXECUTE FUNCTION notify_sync();
