-- M6: lead stages on companies (DB-logged) and the compose list handed to the composer (M10).

ALTER TABLE companies
    ADD COLUMN stage text NOT NULL DEFAULT 'new'
        CHECK (stage IN ('new', 'qualified', 'contacted', 'replied', 'closed', 'on_hold')),
    ADD COLUMN stage_changed_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN close_reason text,
    ADD CONSTRAINT closed_iff_close_reason CHECK (
        (stage = 'closed') = (close_reason IS NOT NULL AND btrim(close_reason) <> '')
    );

CREATE INDEX companies_stage ON companies (stage) WHERE archived_at IS NULL;

-- Every stage change is logged, on any code path.
CREATE FUNCTION companies_log_stage() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.stage_changed_at := now();
    INSERT INTO audit_log (actor, action, entity_type, entity_id, data)
    VALUES (
        coalesce(nullif(current_setting('app.actor', true), ''), 'system'),
        'company.stage_changed', 'company', NEW.id,
        jsonb_build_object('from', OLD.stage, 'to', NEW.stage)
            || CASE WHEN NEW.stage = 'closed' THEN jsonb_build_object('close_reason', NEW.close_reason) ELSE '{}' END
    );
    RETURN NEW;
END
$$;

CREATE TRIGGER companies_stage_change
    BEFORE UPDATE ON companies
    FOR EACH ROW WHEN (OLD.stage IS DISTINCT FROM NEW.stage)
    EXECUTE FUNCTION companies_log_stage();

-- Companies selected for outreach. The recipient is picked live (see app/leads.py),
-- so later blocks or contact changes are always reflected.
CREATE TABLE compose_list (
    company_id bigint PRIMARY KEY REFERENCES companies (id),
    added_at   timestamptz NOT NULL DEFAULT now()
);
