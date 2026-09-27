-- M8: email templates with immutable, numbered versions.

CREATE TABLE templates (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        text NOT NULL CHECK (length(btrim(name)) > 0),
    created_at  timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz
);

CREATE UNIQUE INDEX templates_active_name ON templates (lower(name)) WHERE archived_at IS NULL;

CREATE TABLE template_versions (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    template_id bigint NOT NULL REFERENCES templates (id),
    version     int NOT NULL CHECK (version > 0),
    subject     text NOT NULL CHECK (length(btrim(subject)) > 0),
    body        text NOT NULL CHECK (length(btrim(body)) > 0),
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (template_id, version)
);

-- Versions are immutable: edits create a new version, nothing is changed or deleted.
CREATE FUNCTION template_versions_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'template versions are immutable; save a new version instead';
END
$$;

CREATE TRIGGER template_versions_no_edit_delete
    BEFORE UPDATE OR DELETE ON template_versions
    FOR EACH ROW EXECUTE FUNCTION template_versions_immutable();

CREATE TRIGGER template_versions_no_truncate
    BEFORE TRUNCATE ON template_versions
    FOR EACH STATEMENT EXECUTE FUNCTION template_versions_immutable();
