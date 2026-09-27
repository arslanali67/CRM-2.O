-- M25: do-not-contact list, enforced by the database on every path into a send state.

CREATE TABLE suppressions (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind        text NOT NULL CHECK (kind IN ('email', 'domain', 'company')),
    email       text CHECK (email = lower(email) AND email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    domain      text CHECK (domain ~ '^[a-z0-9-]+(\.[a-z0-9-]+)+$'),
    company_id  bigint REFERENCES companies (id),
    reason      text NOT NULL CHECK (length(btrim(reason)) > 0),
    created_at  timestamptz NOT NULL DEFAULT now(),
    lifted_at   timestamptz,
    lift_reason text,
    CONSTRAINT one_target_matching_kind CHECK (
        (kind = 'email') = (email IS NOT NULL)
        AND (kind = 'domain') = (domain IS NOT NULL)
        AND (kind = 'company') = (company_id IS NOT NULL)
    ),
    CONSTRAINT lift_needs_reason CHECK (
        (lifted_at IS NULL) = (lift_reason IS NULL) AND (lift_reason IS NULL OR length(btrim(lift_reason)) > 0)
    )
);

-- At most one active block per target.
CREATE UNIQUE INDEX suppressions_active_email ON suppressions (email) WHERE lifted_at IS NULL AND kind = 'email';
CREATE UNIQUE INDEX suppressions_active_domain ON suppressions (domain) WHERE lifted_at IS NULL AND kind = 'domain';
CREATE UNIQUE INDEX suppressions_active_company ON suppressions (company_id) WHERE lifted_at IS NULL AND kind = 'company';

-- Blocks are never deleted or edited; the only allowed change is lifting once.
CREATE FUNCTION suppressions_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION 'suppressions cannot be deleted; lift them instead';
    END IF;
    IF OLD.lifted_at IS NOT NULL THEN
        RAISE EXCEPTION 'suppression % is already lifted', OLD.id;
    END IF;
    IF (NEW.kind, NEW.email, NEW.domain, NEW.company_id, NEW.reason, NEW.created_at)
       IS DISTINCT FROM (OLD.kind, OLD.email, OLD.domain, OLD.company_id, OLD.reason, OLD.created_at) THEN
        RAISE EXCEPTION 'suppressions are immutable; only lifting is allowed';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER suppressions_no_edit_delete
    BEFORE UPDATE OR DELETE ON suppressions
    FOR EACH ROW EXECUTE FUNCTION suppressions_guard();

CREATE TRIGGER suppressions_no_truncate
    BEFORE TRUNCATE ON suppressions
    FOR EACH STATEMENT EXECUTE FUNCTION suppressions_guard();

-- True if any active block covers this address. Domain blocks include subdomains;
-- company blocks cover the company's domain and every contact stored under it.
CREATE FUNCTION is_suppressed(addr text) RETURNS boolean LANGUAGE sql STABLE AS $$
    WITH a AS (
        SELECT lower(btrim(addr)) AS email, split_part(lower(btrim(addr)), '@', 2) AS dom
    )
    SELECT EXISTS (
        SELECT 1
        FROM suppressions s, a
        WHERE s.lifted_at IS NULL
          AND (
              s.email = a.email
              OR a.dom = s.domain OR a.dom LIKE '%.' || s.domain
              OR (s.company_id IS NOT NULL AND (
                     EXISTS (SELECT 1 FROM companies c
                             WHERE c.id = s.company_id AND c.domain <> ''
                               AND (a.dom = c.domain OR a.dom LIKE '%.' || c.domain))
                  OR EXISTS (SELECT 1 FROM contacts ct
                             WHERE ct.company_id = s.company_id AND ct.email = a.email)
              ))
          )
    )
$$;

-- Nothing addressed to a blocked recipient can enter a send state, on any code path.
CREATE FUNCTION outbound_emails_block_suppressed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status IN ('approved', 'queued', 'sending') AND is_suppressed(NEW.to_email) THEN
        RAISE EXCEPTION 'recipient % is on the do-not-contact list', NEW.to_email
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER outbound_emails_do_not_contact
    BEFORE INSERT OR UPDATE ON outbound_emails
    FOR EACH ROW EXECUTE FUNCTION outbound_emails_block_suppressed();

-- A new block cancels pending (approved/queued) emails it covers, and audits each one.
CREATE FUNCTION suppressions_cancel_pending() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    WITH cancelled AS (
        UPDATE outbound_emails SET status = 'cancelled'
        WHERE status IN ('approved', 'queued') AND is_suppressed(to_email)
        RETURNING id, to_email
    )
    INSERT INTO audit_log (actor, action, entity_type, entity_id, data)
    SELECT 'system', 'outbound_email.cancelled', 'outbound_email', id,
           jsonb_build_object('reason', 'do_not_contact', 'suppression_id', NEW.id, 'to_email', to_email)
    FROM cancelled;
    RETURN NULL;
END
$$;

CREATE TRIGGER suppressions_cancel_pending_emails
    AFTER INSERT ON suppressions
    FOR EACH ROW EXECUTE FUNCTION suppressions_cancel_pending();
