-- M9: AI personalization. Each draft keeps the AI sentences it received and the verified facts they cite,
-- so the preview can show every claim's source before the owner approves.
ALTER TABLE outbound_emails ADD COLUMN personalization jsonb NOT NULL DEFAULT '{}';
