-- M24: every outbound email status change is logged by the database, on every code path.

CREATE INDEX audit_log_entity ON audit_log (entity_type, entity_id, id);

-- Actor: per-event context (app.status_context->>'actor'), else the connection's
-- app.actor ('owner' for API requests), else 'system'.
-- Extra context keys (e.g. reason, suppression_id) are merged into the event data.
CREATE FUNCTION outbound_emails_log_status() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    ctx jsonb := coalesce(nullif(current_setting('app.status_context', true), ''), '{}')::jsonb;
BEGIN
    INSERT INTO audit_log (actor, action, entity_type, entity_id, data)
    VALUES (
        coalesce(ctx->>'actor', nullif(current_setting('app.actor', true), ''), 'system'),
        'outbound_email.' || CASE WHEN TG_OP = 'INSERT' AND NEW.status = 'draft' THEN 'created' ELSE NEW.status END,
        'outbound_email',
        NEW.id,
        jsonb_build_object(
            'from', CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.status END,
            'to', NEW.status,
            'to_email', lower(NEW.to_email)
        ) || (ctx - 'actor')
    );
    RETURN NULL;
END
$$;

CREATE TRIGGER outbound_emails_log_insert
    AFTER INSERT ON outbound_emails
    FOR EACH ROW EXECUTE FUNCTION outbound_emails_log_status();

CREATE TRIGGER outbound_emails_log_status_change
    AFTER UPDATE ON outbound_emails
    FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status)
    EXECUTE FUNCTION outbound_emails_log_status();

-- M25 auto-cancel now logs through the trigger above (one row per cancellation,
-- actor 'system', with the suppression that caused it) instead of its own insert.
CREATE OR REPLACE FUNCTION suppressions_cancel_pending() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM set_config(
        'app.status_context',
        jsonb_build_object('actor', 'system', 'reason', 'do_not_contact', 'suppression_id', NEW.id)::text,
        true
    );
    UPDATE outbound_emails SET status = 'cancelled'
    WHERE status IN ('approved', 'queued') AND is_suppressed(to_email);
    PERFORM set_config('app.status_context', '', true);
    RETURN NULL;
END
$$;
