-- M30: no line breaks in anything that becomes an email header (header injection).
-- to_email already excludes whitespace (0001). Subjects are checked where they are stored.
ALTER TABLE outbound_emails ADD CONSTRAINT subject_single_line CHECK (subject !~ '[\r\n]');
ALTER TABLE template_versions ADD CONSTRAINT subject_single_line CHECK (subject !~ '[\r\n]');
