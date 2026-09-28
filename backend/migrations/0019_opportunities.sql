-- M19: job opportunity pipeline with a DB-logged, append-only stage history.

CREATE TABLE opportunities (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id         bigint NOT NULL REFERENCES companies (id),
    contact_id         bigint REFERENCES contacts (id),
    inbound_message_id bigint REFERENCES inbound_messages (id),  -- the reply it was created from
    title              text NOT NULL CHECK (length(btrim(title)) > 0),
    stage              text NOT NULL DEFAULT 'new'
        CHECK (stage IN ('new', 'applied', 'screening', 'interviewing', 'offer', 'hired', 'rejected', 'withdrawn')),
    stage_changed_at   timestamptz NOT NULL DEFAULT now(),
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

-- A reply can start at most one opportunity.
CREATE UNIQUE INDEX opportunities_one_per_reply ON opportunities (inbound_message_id) WHERE inbound_message_id IS NOT NULL;
CREATE INDEX opportunities_company ON opportunities (company_id);
CREATE INDEX opportunities_stage ON opportunities (stage);

CREATE TABLE opportunity_stage_history (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    opportunity_id bigint NOT NULL REFERENCES opportunities (id),
    from_stage     text,
    to_stage       text NOT NULL,
    at             timestamptz NOT NULL DEFAULT now(),
    actor          text NOT NULL,
    reason         text NOT NULL DEFAULT ''
);
CREATE INDEX opportunity_stage_history_opp ON opportunity_stage_history (opportunity_id, id);

-- History is append-only.
CREATE FUNCTION opportunity_history_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'opportunity stage history is append-only';
END
$$;

CREATE TRIGGER opportunity_stage_history_no_update_delete
    BEFORE UPDATE OR DELETE ON opportunity_stage_history
    FOR EACH ROW EXECUTE FUNCTION opportunity_history_append_only();

-- Every creation and stage change is recorded, on any code path. The reason comes from the
-- transaction-local setting app.stage_reason (set by the API / by M20's interview recording).
CREATE FUNCTION opportunities_log_stage() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        NEW.stage_changed_at := now();
    END IF;
    INSERT INTO opportunity_stage_history (opportunity_id, from_stage, to_stage, actor, reason)
    VALUES (NEW.id, CASE WHEN TG_OP = 'UPDATE' THEN OLD.stage END, NEW.stage,
            coalesce(nullif(current_setting('app.actor', true), ''), 'system'),
            coalesce(current_setting('app.stage_reason', true), ''));
    RETURN NEW;
END
$$;

CREATE TRIGGER opportunities_log_insert
    AFTER INSERT ON opportunities
    FOR EACH ROW EXECUTE FUNCTION opportunities_log_stage();

CREATE TRIGGER opportunities_log_stage_change
    BEFORE UPDATE ON opportunities
    FOR EACH ROW WHEN (OLD.stage IS DISTINCT FROM NEW.stage)
    EXECUTE FUNCTION opportunities_log_stage();

-- Notes and tasks can be attached to opportunities (M21 anticipated this).
ALTER TABLE notes DROP CONSTRAINT notes_entity_type_check,
    ADD CONSTRAINT notes_entity_type_check CHECK (entity_type IN ('company', 'contact', 'template', 'opportunity'));
ALTER TABLE tasks DROP CONSTRAINT tasks_entity_type_check,
    ADD CONSTRAINT tasks_entity_type_check CHECK (entity_type IN ('company', 'contact', 'template', 'opportunity'));
