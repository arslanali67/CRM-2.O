-- M15: rule-based reply detection (no AI) and its effects.

ALTER TABLE inbound_messages
    ADD COLUMN extra_headers jsonb NOT NULL DEFAULT '{}',  -- Auto-Submitted, Precedence, X-Autoreply, List-Id, …
    ADD COLUMN dsn           jsonb,                        -- parsed delivery-status report (bounces)
    ADD COLUMN label         text CHECK (label IN ('bounce', 'auto_reply', 'reply', 'unrelated')),
    ADD COLUMN label_rule    text,                         -- which rule matched, for transparency
    ADD COLUMN bounce_type   text CHECK (bounce_type IN ('hard', 'soft')),
    ADD COLUMN labeled_at    timestamptz;

CREATE INDEX inbound_messages_label ON inbound_messages (label);

ALTER TABLE outbound_emails
    ADD COLUMN bounced_at    timestamptz,
    ADD COLUMN bounce_type   text CHECK (bounce_type IN ('hard', 'soft')),
    ADD COLUMN bounce_detail text;
