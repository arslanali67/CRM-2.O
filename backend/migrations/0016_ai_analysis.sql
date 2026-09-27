-- M16: AI analysis of replies. Every stored field carries a verbatim, code-verified evidence quote.

CREATE TABLE ai_analyses (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    inbound_message_id bigint NOT NULL UNIQUE REFERENCES inbound_messages (id),
    status             text NOT NULL CHECK (status IN ('ok', 'unverified', 'error')),
    model              text NOT NULL,
    prompt_version     int NOT NULL,
    label              text CHECK (label IN ('interview_request', 'interested', 'needs_info', 'scheduling',
                                             'application_redirect', 'referral', 'keep_on_file', 'not_hiring',
                                             'rejection', 'offer', 'unsubscribe_request', 'other')),
    label_evidence     text,
    summary            text,
    extracted          jsonb NOT NULL DEFAULT '{}',  -- dates, links, documents, contacts: verified only
    dropped            jsonb NOT NULL DEFAULT '[]',  -- what the model returned but could not be verified
    error              text,
    attempts           int NOT NULL DEFAULT 1,
    analysed_at        timestamptz NOT NULL DEFAULT now(),
    -- 'ok' means the label itself is backed by a verified quote.
    CONSTRAINT ok_has_verified_label CHECK (status <> 'ok' OR (label IS NOT NULL AND label_evidence IS NOT NULL))
);
