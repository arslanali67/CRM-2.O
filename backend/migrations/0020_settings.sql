-- M29: settings. AI on/off + model, notification kinds, and the approved ranges for limits.

ALTER TABLE app_settings
    ADD COLUMN ai_enabled   boolean NOT NULL DEFAULT true,
    ADD COLUMN ai_model     text CHECK (ai_model ~ '^[a-z0-9][a-z0-9.\-]{1,80}$'),  -- NULL = GEMINI_MODEL default
    ADD COLUMN notify_kinds text[] NOT NULL DEFAULT ARRAY['reply', 'auto_reply', 'bounce', 'sending', 'system']
        CHECK (notify_kinds <@ ARRAY['reply', 'auto_reply', 'bounce', 'sending', 'system']);

ALTER TABLE app_settings
    DROP CONSTRAINT app_settings_daily_cap_check,
    ADD CONSTRAINT app_settings_daily_cap_check CHECK (daily_cap BETWEEN 1 AND 100),
    DROP CONSTRAINT app_settings_min_gap_seconds_check,
    ADD CONSTRAINT app_settings_min_gap_seconds_check CHECK (min_gap_seconds BETWEEN 30 AND 3600),
    DROP CONSTRAINT app_settings_recipient_cooldown_days_check,
    ADD CONSTRAINT app_settings_recipient_cooldown_days_check CHECK (recipient_cooldown_days BETWEEN 0 AND 365),
    DROP CONSTRAINT app_settings_company_cooldown_days_check,
    ADD CONSTRAINT app_settings_company_cooldown_days_check CHECK (company_cooldown_days BETWEEN 0 AND 365),
    DROP CONSTRAINT app_settings_approval_max_age_days_check,
    ADD CONSTRAINT app_settings_approval_max_age_days_check CHECK (approval_max_age_days BETWEEN 1 AND 30);

-- Whether a notification kind is switched on (read live on every event).
CREATE FUNCTION notify_enabled(kind text) RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT coalesce((SELECT kind = ANY(notify_kinds) FROM app_settings WHERE id = 1), true)
$$;

-- The M17 notification functions, now respecting the enabled kinds. Bodies otherwise unchanged.
CREATE OR REPLACE FUNCTION notify_inbound() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    who text := coalesce(nullif(NEW.from_name, ''), NEW.from_email);
BEGIN
    IF NOT notify_enabled(NEW.label) THEN
        RETURN NULL;
    END IF;
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

CREATE OR REPLACE FUNCTION notify_ai() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'ok' THEN
        UPDATE notifications
        SET priority = notification_priority(NEW.label),
            title = split_part(title, ' · ', 1) || ' · ' || replace(NEW.label, '_', ' '),
            body = coalesce(nullif(NEW.summary, ''), body),
            updated_at = now()
        WHERE kind = 'reply' AND source_type = 'inbound_message' AND source_id = NEW.inbound_message_id::text;
    ELSIF NEW.status = 'error' AND NEW.attempts >= 3 AND notify_enabled('system') THEN
        INSERT INTO notifications (kind, source_type, source_id, priority, title, body, link, company_id)
        SELECT 'ai_failed', 'ai_analysis', NEW.id::text, 'normal', 'AI analysis failed after 3 attempts',
               coalesce(NEW.error, ''), '/inbox', m.company_id
        FROM inbound_messages m WHERE m.id = NEW.inbound_message_id
        ON CONFLICT ON CONSTRAINT one_notification_per_event DO NOTHING;
    END IF;
    RETURN NULL;
END
$$;

CREATE OR REPLACE FUNCTION notify_outbound() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    ctx jsonb := coalesce(nullif(current_setting('app.status_context', true), ''), '{}')::jsonb;
BEGIN
    IF NOT notify_enabled('sending') THEN
        RETURN NULL;
    END IF;
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

CREATE OR REPLACE FUNCTION notify_sync() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT notify_enabled('system') THEN
        RETURN NULL;
    END IF;
    INSERT INTO notifications (kind, source_type, source_id, priority, title, body, link)
    VALUES ('sync_failing', 'mailbox', NEW.mailbox || '@' || NEW.failing_since, 'normal',
            'Inbox sync is failing (' || coalesce(NEW.imap_name, NEW.mailbox) || ')',
            coalesce(NEW.last_error, ''), '/inbox')
    ON CONFLICT ON CONSTRAINT one_notification_per_event DO NOTHING;
    RETURN NULL;
END
$$;
