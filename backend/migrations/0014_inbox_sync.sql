-- M14: read-only inbox sync. Only outreach-relevant messages are stored; each exactly once.

CREATE TABLE inbound_messages (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    gmail_msgid       text NOT NULL UNIQUE,   -- stable across folders: the idempotency key
    gmail_thrid       text,
    mailbox           text NOT NULL CHECK (mailbox IN ('all', 'spam')),
    uid               bigint,
    uidvalidity       bigint,
    message_id        text NOT NULL DEFAULT '',
    in_reply_to       text NOT NULL DEFAULT '',
    refs              text NOT NULL DEFAULT '',  -- References header
    from_email        text NOT NULL,
    from_name         text NOT NULL DEFAULT '',
    to_emails         text NOT NULL DEFAULT '',
    subject           text NOT NULL DEFAULT '',
    sent_date         timestamptz,              -- Date header
    received_at       timestamptz,              -- IMAP INTERNALDATE
    body_text         text NOT NULL DEFAULT '',
    body_truncated    boolean NOT NULL DEFAULT false,
    attachment_names  text[] NOT NULL DEFAULT '{}',  -- names only, never contents
    relevance         text NOT NULL CHECK (relevance IN ('reply_header', 'thread', 'bounce', 'contact', 'company_domain')),
    outbound_email_id bigint REFERENCES outbound_emails (id),
    company_id        bigint REFERENCES companies (id),
    contact_id        bigint REFERENCES contacts (id),
    fetched_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX inbound_messages_thread ON inbound_messages (gmail_thrid);
CREATE INDEX inbound_messages_company ON inbound_messages (company_id);
CREATE INDEX inbound_messages_received ON inbound_messages (received_at DESC);

CREATE TABLE mailbox_sync (
    mailbox        text PRIMARY KEY CHECK (mailbox IN ('all', 'spam')),
    imap_name      text,
    uidvalidity    bigint,
    last_uid       bigint NOT NULL DEFAULT 0,
    last_sync_at   timestamptz,
    last_ok        boolean,
    last_error     text,
    last_rescan_at timestamptz,
    seen_count     bigint NOT NULL DEFAULT 0,   -- headers examined
    stored_count   bigint NOT NULL DEFAULT 0    -- relevant messages stored
);
