-- M27: company research. Scraped data (companies / source_detail), AI claims and verified facts stay separate.

-- What was fetched from the company's own site, kept so every claim's evidence stays checkable.
CREATE TABLE page_snapshots (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id  bigint NOT NULL REFERENCES companies (id),
    url         text NOT NULL CHECK (url ~* '^https?://'),
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    status_code int,
    text        text NOT NULL DEFAULT '' CHECK (length(text) <= 200000),
    error       text
);
CREATE INDEX page_snapshots_company ON page_snapshots (company_id, fetched_at DESC);

-- AI output: never a fact until the owner verifies it.
CREATE TABLE ai_claims (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id  bigint NOT NULL REFERENCES companies (id),
    snapshot_id bigint NOT NULL REFERENCES page_snapshots (id),
    category    text NOT NULL CHECK (category IN ('product', 'mission', 'technology', 'hiring', 'location', 'size',
                                                  'funding', 'news', 'other')),
    claim       text NOT NULL CHECK (length(btrim(claim)) BETWEEN 1 AND 300),
    evidence    text NOT NULL CHECK (length(btrim(evidence)) >= 3),
    source_url  text NOT NULL CHECK (source_url ~* '^https?://'),
    model       text NOT NULL,
    status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'verified', 'rejected')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    decided_at  timestamptz
);
CREATE INDEX ai_claims_company ON ai_claims (company_id, status);

-- Owner-confirmed facts: the only company information personalization (M9) may use.
CREATE TABLE verified_facts (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id    bigint NOT NULL REFERENCES companies (id),
    category      text NOT NULL CHECK (category IN ('product', 'mission', 'technology', 'hiring', 'location', 'size',
                                                    'funding', 'news', 'other')),
    fact          text NOT NULL CHECK (length(btrim(fact)) BETWEEN 1 AND 500),
    source        text NOT NULL CHECK (length(btrim(source)) BETWEEN 1 AND 500),  -- URL or where the owner knows it from
    from_claim_id bigint REFERENCES ai_claims (id),
    verified_at   timestamptz NOT NULL DEFAULT now(),
    removed_at    timestamptz
);
CREATE INDEX verified_facts_company ON verified_facts (company_id) WHERE removed_at IS NULL;

-- Only an owner action can create or change a verified fact (the worker and system paths run as 'system').
CREATE FUNCTION verified_facts_owner_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF coalesce(current_setting('app.actor', true), '') <> 'owner' THEN
        RAISE EXCEPTION 'verified facts can only be created or changed by the owner';
    END IF;
    IF TG_OP = 'UPDATE' AND (NEW.company_id, NEW.fact, NEW.source, NEW.category, NEW.from_claim_id, NEW.verified_at)
                            IS DISTINCT FROM (OLD.company_id, OLD.fact, OLD.source, OLD.category, OLD.from_claim_id,
                                              OLD.verified_at) THEN
        RAISE EXCEPTION 'verified facts are immutable; remove it and verify a new one';
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER verified_facts_owner
    BEFORE INSERT OR UPDATE ON verified_facts
    FOR EACH ROW EXECUTE FUNCTION verified_facts_owner_only();
CREATE FUNCTION verified_facts_no_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'verified facts are never deleted; remove them (removed_at) instead';
END
$$;
CREATE TRIGGER verified_facts_no_delete
    BEFORE DELETE ON verified_facts
    FOR EACH ROW EXECUTE FUNCTION verified_facts_no_delete();

-- The single path from research to personalization: verified, not removed, nothing else.
CREATE FUNCTION personalization_facts(company bigint)
RETURNS TABLE (id bigint, category text, fact text, source text, verified_at timestamptz)
LANGUAGE sql STABLE AS $$
    SELECT f.id, f.category, f.fact, f.source, f.verified_at
    FROM public.verified_facts f
    WHERE f.company_id = company AND f.removed_at IS NULL
    ORDER BY f.category, f.id
$$;
