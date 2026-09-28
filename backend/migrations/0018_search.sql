-- M22: fast "contains" search (trigram indexes) and indexes for the new Leads filters.
-- pg_trgm ships with PostgreSQL itself; no extra package.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX companies_name_trgm ON companies USING gin (lower(name) gin_trgm_ops);
CREATE INDEX companies_domain_trgm ON companies USING gin (domain gin_trgm_ops);
CREATE INDEX contacts_name_trgm ON contacts USING gin (lower(name) gin_trgm_ops);
CREATE INDEX contacts_email_trgm ON contacts USING gin (email gin_trgm_ops);
CREATE INDEX outbound_emails_subject_trgm ON outbound_emails USING gin (lower(subject) gin_trgm_ops);
CREATE INDEX outbound_emails_to_trgm ON outbound_emails USING gin (lower(to_email) gin_trgm_ops);
CREATE INDEX inbound_messages_subject_trgm ON inbound_messages USING gin (lower(subject) gin_trgm_ops);
CREATE INDEX inbound_messages_sender_trgm ON inbound_messages USING gin (lower(from_email || ' ' || from_name) gin_trgm_ops);
CREATE INDEX templates_name_trgm ON templates USING gin (lower(name) gin_trgm_ops);
CREATE INDEX notes_body_trgm ON notes USING gin (lower(body) gin_trgm_ops);

-- Leads filters: reply status / last reply, template used.
CREATE INDEX inbound_messages_company_label ON inbound_messages (company_id, label, received_at);
CREATE INDEX outbound_emails_template_version ON outbound_emails (template_version_id) WHERE template_version_id IS NOT NULL;
CREATE INDEX companies_created ON companies (created_at);
CREATE INDEX ai_analyses_label ON ai_analyses (label, inbound_message_id) WHERE status = 'ok';
