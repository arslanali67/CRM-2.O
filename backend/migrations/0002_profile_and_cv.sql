-- M3: owner profile (single row) and immutable PDF CV versions.

CREATE TABLE profile (
    id               int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    full_name        text NOT NULL DEFAULT '',
    email            text NOT NULL DEFAULT '',
    phone            text NOT NULL DEFAULT '',
    location         text NOT NULL DEFAULT '',
    headline         text NOT NULL DEFAULT '',
    summary          text NOT NULL DEFAULT '',
    skills           text[] NOT NULL DEFAULT '{}',
    experience       jsonb NOT NULL DEFAULT '[]',
    linkedin_url     text NOT NULL DEFAULT '',
    github_url       text NOT NULL DEFAULT '',
    portfolio_url    text NOT NULL DEFAULT '',
    target_roles     text[] NOT NULL DEFAULT '{}',
    target_locations text[] NOT NULL DEFAULT '{}',
    work_mode        text NOT NULL DEFAULT 'any' CHECK (work_mode IN ('remote', 'hybrid', 'onsite', 'any')),
    availability     text NOT NULL DEFAULT '',
    updated_at       timestamptz NOT NULL DEFAULT now()
);
INSERT INTO profile DEFAULT VALUES;

CREATE TABLE cv_versions (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    label       text NOT NULL CHECK (length(btrim(label)) > 0),
    filename    text NOT NULL,
    content     bytea NOT NULL CHECK (
        octet_length(content) <= 5 * 1024 * 1024
        AND substring(content FROM 1 FOR 5) = '%PDF-'::bytea
    ),
    is_default  boolean NOT NULL DEFAULT false,
    uploaded_at timestamptz NOT NULL DEFAULT now()
);

-- At most one default CV.
CREATE UNIQUE INDEX cv_versions_one_default ON cv_versions (is_default) WHERE is_default;

-- Versions are immutable; only the default flag may change.
CREATE FUNCTION cv_versions_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.label IS DISTINCT FROM OLD.label
       OR NEW.filename IS DISTINCT FROM OLD.filename
       OR NEW.content IS DISTINCT FROM OLD.content
       OR NEW.uploaded_at IS DISTINCT FROM OLD.uploaded_at THEN
        RAISE EXCEPTION 'cv_versions are immutable; upload a new version instead';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER cv_versions_no_edit
    BEFORE UPDATE ON cv_versions
    FOR EACH ROW EXECUTE FUNCTION cv_versions_immutable();
