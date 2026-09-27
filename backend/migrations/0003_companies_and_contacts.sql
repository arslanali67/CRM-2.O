-- M5: companies and contacts with provenance, archive instead of delete, email classes.

CREATE TABLE companies (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          text NOT NULL CHECK (length(btrim(name)) > 0),
    domain        text NOT NULL DEFAULT '' CHECK (domain = '' OR domain ~ '^[a-z0-9-]+(\.[a-z0-9-]+)+$'),
    website       text NOT NULL DEFAULT '',
    industry      text NOT NULL DEFAULT '',
    city          text NOT NULL DEFAULT '',
    country       text NOT NULL DEFAULT '',
    description   text NOT NULL DEFAULT '',
    linkedin_url  text NOT NULL DEFAULT '',
    source        text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'csv_import')),
    source_detail jsonb NOT NULL DEFAULT '{}',
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    archived_at   timestamptz
);

-- No two active companies share a domain.
CREATE UNIQUE INDEX companies_active_domain ON companies (domain)
    WHERE domain <> '' AND archived_at IS NULL;

CREATE TABLE contacts (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id         bigint NOT NULL REFERENCES companies (id),
    name               text NOT NULL DEFAULT '',
    email              text NOT NULL DEFAULT '' CHECK (email = lower(email)),
    role               text NOT NULL DEFAULT '',
    phone              text NOT NULL DEFAULT '',
    linkedin_url       text NOT NULL DEFAULT '',
    email_class        text CHECK (email_class IN ('careers', 'personal', 'generic', 'unsuitable')),
    email_class_manual boolean NOT NULL DEFAULT false,
    source             text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'csv_import')),
    source_detail      jsonb NOT NULL DEFAULT '{}',
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    archived_at        timestamptz,
    CONSTRAINT contact_has_name_or_email CHECK (btrim(name) <> '' OR email <> ''),
    CONSTRAINT email_class_iff_email CHECK ((email = '') = (email_class IS NULL))
);

CREATE INDEX contacts_company_id ON contacts (company_id);

-- No two active contacts share an email.
CREATE UNIQUE INDEX contacts_active_email ON contacts (email)
    WHERE email <> '' AND archived_at IS NULL;
