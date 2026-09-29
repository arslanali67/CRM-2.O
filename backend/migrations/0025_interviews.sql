-- M20: interviews on opportunities, zone-safe times, in-app reminders exactly once.

CREATE TABLE interviews (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    opportunity_id   bigint NOT NULL REFERENCES opportunities (id),
    title            text NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 200),
    starts_at        timestamptz NOT NULL,          -- the exact moment (UTC)
    time_zone        text NOT NULL CHECK (time_zone ~ '^[A-Za-z]+(/[A-Za-z0-9_+-]+)*$'),  -- IANA zone agreed in
    duration_minutes int NOT NULL DEFAULT 60 CHECK (duration_minutes BETWEEN 5 AND 600),
    kind             text NOT NULL DEFAULT 'video' CHECK (kind IN ('video', 'phone', 'onsite')),
    location         text NOT NULL DEFAULT '' CHECK (location !~* '^\s*(javascript|data|vbscript|file):'),
    interviewers     text NOT NULL DEFAULT '',
    notes            text NOT NULL DEFAULT '',
    status           text NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'done', 'cancelled')),
    outcome          text NOT NULL DEFAULT '',
    sequence         int NOT NULL DEFAULT 0,        -- .ics SEQUENCE: bumped on every edit
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX interviews_opportunity ON interviews (opportunity_id, starts_at);
CREATE INDEX interviews_upcoming ON interviews (starts_at) WHERE status = 'scheduled';

-- Notes and tasks can be attached to interviews.
ALTER TABLE notes DROP CONSTRAINT notes_entity_type_check,
    ADD CONSTRAINT notes_entity_type_check
        CHECK (entity_type IN ('company', 'contact', 'template', 'opportunity', 'interview'));
ALTER TABLE tasks DROP CONSTRAINT tasks_entity_type_check,
    ADD CONSTRAINT tasks_entity_type_check
        CHECK (entity_type IN ('company', 'contact', 'template', 'opportunity', 'interview'));

-- Reminders are notifications of kind 'interview', switchable in Settings (on by default).
ALTER TABLE notifications DROP CONSTRAINT notifications_kind_check,
    ADD CONSTRAINT notifications_kind_check CHECK (kind IN ('reply', 'auto_reply', 'bounce', 'send_failed',
                                                            'send_cancelled', 'sync_failing', 'ai_failed', 'interview')),
    DROP CONSTRAINT notifications_source_type_check,
    ADD CONSTRAINT notifications_source_type_check
        CHECK (source_type IN ('inbound_message', 'outbound_email', 'mailbox', 'ai_analysis', 'interview'));

ALTER TABLE app_settings DROP CONSTRAINT app_settings_notify_kinds_check,
    ADD CONSTRAINT app_settings_notify_kinds_check
        CHECK (notify_kinds <@ ARRAY['reply', 'auto_reply', 'bounce', 'sending', 'system', 'interview']),
    ALTER COLUMN notify_kinds SET DEFAULT ARRAY['reply', 'auto_reply', 'bounce', 'sending', 'system', 'interview'];
UPDATE app_settings SET notify_kinds = notify_kinds || ARRAY['interview'] WHERE NOT 'interview' = ANY(notify_kinds);

-- Due reminders: 24 h before (only while more than 1 h remains) and 1 h before; never for past, done or
-- cancelled interviews. The source id includes the start time, so a rescheduled interview reminds again.
-- Exactly once per (interview, reminder, start time) through the one_notification_per_event constraint.
CREATE FUNCTION interview_reminders() RETURNS int LANGUAGE plpgsql AS $$
DECLARE
    n int;
BEGIN
    IF NOT notify_enabled('interview') THEN
        RETURN 0;
    END IF;
    INSERT INTO notifications (kind, source_type, source_id, priority, title, body, link, company_id)
    SELECT 'interview', 'interview', i.id || ':' || r.tag || ':' || extract(epoch FROM i.starts_at)::bigint,
           'high',
           CASE r.tag WHEN '24h' THEN 'Interview tomorrow: ' ELSE 'Interview in 1 hour: ' END || i.title,
           c.name || ' · ' || to_char(i.starts_at AT TIME ZONE i.time_zone, 'Dy DD Mon HH24:MI') || ' ' || i.time_zone,
           '/opportunities/' || o.id || '#interview-' || i.id, o.company_id
    FROM interviews i
    JOIN opportunities o ON o.id = i.opportunity_id
    JOIN companies c ON c.id = o.company_id
    CROSS JOIN (VALUES ('24h', interval '24 hours'), ('1h', interval '1 hour')) AS r (tag, lead)
    WHERE i.status = 'scheduled'
      AND now() < i.starts_at
      AND now() >= i.starts_at - r.lead
      AND (r.tag = '1h' OR now() < i.starts_at - interval '1 hour')
    ON CONFLICT ON CONSTRAINT one_notification_per_event DO NOTHING;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END
$$;
