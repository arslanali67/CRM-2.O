-- M12: bookkeeping for exactly-once sending and recovery.

ALTER TABLE outbound_emails
    ADD COLUMN send_started_at timestamptz,  -- set when the email enters 'sending'; drives recovery timing
    ADD COLUMN failure_reason  text;         -- why an email ended in 'failed'
