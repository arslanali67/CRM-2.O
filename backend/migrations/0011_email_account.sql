-- M11: the single sending/receiving Gmail account. The app password is stored only encrypted.

CREATE TABLE email_account (
    id                 int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    email_address      text NOT NULL CHECK (email_address = lower(email_address)
                                            AND email_address ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    display_name       text NOT NULL DEFAULT '',
    smtp_host          text NOT NULL DEFAULT 'smtp.gmail.com',
    smtp_port          int NOT NULL DEFAULT 465,
    imap_host          text NOT NULL DEFAULT 'imap.gmail.com',
    imap_port          int NOT NULL DEFAULT 993,
    password_encrypted bytea,  -- Fernet token; NULL after disconnect
    connected_at       timestamptz,
    last_test_at       timestamptz,
    last_test_ok       boolean,
    last_test_detail   jsonb NOT NULL DEFAULT '{}'
);
