-- M26: links the safety checks need, and the settings they read. Sending is OFF by default.

ALTER TABLE outbound_emails
    ADD COLUMN contact_id          bigint REFERENCES contacts (id),
    ADD COLUMN company_id          bigint REFERENCES companies (id),
    ADD COLUMN template_version_id bigint REFERENCES template_versions (id),
    ADD COLUMN cancel_reason       text;

CREATE INDEX outbound_emails_sent_at ON outbound_emails (sent_at) WHERE status = 'sent';
CREATE INDEX outbound_emails_sent_to ON outbound_emails (lower(to_email), sent_at) WHERE status = 'sent';
CREATE INDEX outbound_emails_sent_company ON outbound_emails (company_id, sent_at) WHERE status = 'sent';

CREATE TABLE app_settings (
    id                      int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    sending_enabled         boolean NOT NULL DEFAULT false,
    daily_cap               int NOT NULL DEFAULT 20 CHECK (daily_cap BETWEEN 1 AND 200),
    min_gap_seconds         int NOT NULL DEFAULT 90 CHECK (min_gap_seconds >= 30),
    recipient_cooldown_days int NOT NULL DEFAULT 30 CHECK (recipient_cooldown_days >= 0),
    company_cooldown_days   int NOT NULL DEFAULT 14 CHECK (company_cooldown_days >= 0),
    approval_max_age_days   int NOT NULL DEFAULT 7 CHECK (approval_max_age_days >= 1),
    updated_at              timestamptz NOT NULL DEFAULT now()
);
INSERT INTO app_settings DEFAULT VALUES;
