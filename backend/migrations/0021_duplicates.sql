-- M7: duplicate management. Merges keep an exact snapshot so they can be undone.

CREATE TABLE company_merges (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    survivor_id bigint NOT NULL REFERENCES companies (id),
    merged_id   bigint NOT NULL REFERENCES companies (id),
    snapshot    jsonb NOT NULL,  -- moved row ids per table, survivor fields filled, carried-over block
    merged_at   timestamptz NOT NULL DEFAULT now(),
    undone_at   timestamptz,
    CHECK (survivor_id <> merged_id)
);
CREATE INDEX company_merges_survivor ON company_merges (survivor_id);
CREATE INDEX company_merges_merged ON company_merges (merged_id);

-- Pairs the owner marked "not a duplicate" (stored with the lower id first).
CREATE TABLE duplicate_dismissals (
    company_a    bigint NOT NULL REFERENCES companies (id),
    company_b    bigint NOT NULL REFERENCES companies (id),
    dismissed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company_a, company_b),
    CHECK (company_a < company_b)
);

-- Main domain: the last two labels (ponytail: naive; co.uk-style suffixes need a public-suffix list).
CREATE FUNCTION main_domain(d text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN d = '' THEN '' ELSE array_to_string((string_to_array(d, '.'))[
        greatest(array_length(string_to_array(d, '.'), 1) - 1, 1):], '.') END
$$;

-- LinkedIn URL without scheme, www., query or trailing slash.
CREATE FUNCTION linkedin_key(u text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT rtrim(regexp_replace(split_part(lower(btrim(u)), '?', 1), '^(https?://)?(www\.)?', ''), '/')
$$;

CREATE INDEX companies_main_domain ON companies (main_domain(domain)) WHERE archived_at IS NULL AND domain <> '';
CREATE INDEX companies_linkedin_key ON companies (linkedin_key(linkedin_url))
    WHERE archived_at IS NULL AND linkedin_url <> '';

-- Name without legal form or punctuation ("Acme GmbH & Co. KG" -> "acme"); name matches pair on its first word.
CREATE FUNCTION name_key(n text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT array_to_string(ARRAY(
        SELECT w FROM unnest(string_to_array(regexp_replace(lower(n), '[^a-z0-9äöüß]+', ' ', 'g'), ' '))
                      WITH ORDINALITY AS t(w, i)
        WHERE w <> '' AND w <> ALL ('{gmbh,ag,ug,se,kg,ohg,gbr,mbh,co,inc,llc,ltd,limited,corp,plc,bv,sa,sas,srl,haftungsbeschränkt}')
        ORDER BY i), ' ')
$$;

CREATE INDEX companies_name_first_word ON companies (split_part(name_key(name), ' ', 1)) WHERE archived_at IS NULL;
