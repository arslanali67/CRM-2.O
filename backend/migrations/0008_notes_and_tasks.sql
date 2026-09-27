-- M21: notes on entities and follow-up tasks for the owner. Tasks never send anything:
-- there is deliberately no link from tasks to outbound_emails.

CREATE TABLE notes (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_type text NOT NULL CHECK (entity_type IN ('company', 'contact', 'template')),
    entity_id   bigint NOT NULL,
    body        text NOT NULL CHECK (length(btrim(body)) > 0),
    created_at  timestamptz NOT NULL DEFAULT now(),
    edited_at   timestamptz,
    deleted_at  timestamptz
);

CREATE INDEX notes_entity ON notes (entity_type, entity_id) WHERE deleted_at IS NULL;

CREATE TABLE tasks (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title       text NOT NULL CHECK (length(btrim(title)) > 0),
    details     text NOT NULL DEFAULT '',
    due_date    date,  -- calendar date only; "today" comes from the owner's browser
    entity_type text CHECK (entity_type IN ('company', 'contact', 'template')),
    entity_id   bigint,
    done_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    deleted_at  timestamptz,
    CONSTRAINT task_link_complete CHECK ((entity_type IS NULL) = (entity_id IS NULL))
);

CREATE INDEX tasks_open_due ON tasks (due_date) WHERE done_at IS NULL AND deleted_at IS NULL;
CREATE INDEX tasks_entity ON tasks (entity_type, entity_id) WHERE deleted_at IS NULL;
