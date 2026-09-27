-- M13: Gmail's own IDs for each sent email (fetched read-only from Gmail Sent after sending).

ALTER TABLE outbound_emails
    ADD COLUMN gmail_msgid    text,         -- X-GM-MSGID (64-bit, kept as text)
    ADD COLUMN gmail_thrid    text,         -- X-GM-THRID: the conversation replies will join (M14/M15)
    ADD COLUMN ids_checked_at timestamptz;  -- last lookup attempt, for throttled retries

CREATE INDEX outbound_emails_gmail_thrid ON outbound_emails (gmail_thrid) WHERE gmail_thrid IS NOT NULL;
