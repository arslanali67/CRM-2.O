"""M4: CSV import with the ai_companies preset. Preview and import share one analysis."""
import csv
import io
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb

from app.companies import normalize_domain
from app.deps import audit, get_db, require_owner
from app.email_class import EMAIL_RE, classify_email

router = APIRouter(dependencies=[Depends(require_owner)])

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
REQUIRED_COLUMNS = {"company", "website", "all_emails"}
EXTRA_COLUMNS = ("twitter", "github", "facebook", "instagram", "remote_jobs", "is_ai", "mentions_city", "source")
PLACEHOLDER_DOMAINS = {
    "muster.de", "mustermann.de", "firma.de", "beispiel.de", "company.com", "yourcompany.com", "example.com",
    "example.org", "example.net", "domain.com", "yourdomain.com", "email.com", "test.com",
}
ARTIFACT_RE = re.compile(r"^(u003[ec]|%20)+", re.IGNORECASE)
URL_RE = re.compile(r"^https?://\S+$")
NAME_SPLIT_RE = re.compile(r"\s*(?:,|;|&|\band\b)\s*")


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def clean_email(raw: str) -> tuple[str | None, str | None]:
    """Return (email, None) or (None, reason)."""
    e = ARTIFACT_RE.sub("", raw.strip()).strip().lower()
    if not EMAIL_RE.match(e):
        return None, "malformed address"
    domain = e.split("@", 1)[1]
    tld = domain.rsplit(".", 1)[-1]
    if not tld.isalpha() or len(tld) > 10:
        return None, "malformed domain"
    if domain in PLACEHOLDER_DOMAINS:
        return None, "placeholder address"
    return e, None


def _brand(domain: str) -> str:
    return re.sub(r"[.-]", "", domain.rsplit(".", 1)[0])


def same_brand(email_domain: str, company_domain: str) -> bool:
    """True for the company's domain, its subdomains, or the same brand on another domain."""
    if not company_domain:
        return True
    if email_domain == company_domain or email_domain.endswith("." + company_domain):
        return True
    a, b = _brand(email_domain), _brand(company_domain)
    short, long = sorted((a, b), key=len)
    return len(short) >= 4 and short in long


def split_names(raw: str) -> list[str]:
    return [n for n in (x.strip() for x in NAME_SPLIT_RE.split(raw or "")) if n]


def analyze(conn, text: str, city: str, country: str) -> dict:
    reader = csv.DictReader(io.StringIO(text))
    columns = reader.fieldnames or []
    missing = REQUIRED_COLUMNS - set(columns)
    if missing:
        raise HTTPException(422, f"Not an ai_companies CSV; missing columns: {', '.join(sorted(missing))}")
    raw_rows = list(reader)
    if len(raw_rows) > MAX_ROWS:
        raise HTTPException(413, f"At most {MAX_ROWS} rows per import")

    active_domains = {r["domain"] for r in conn.execute(
        "SELECT domain FROM companies WHERE archived_at IS NULL AND domain <> ''").fetchall()}
    active_names = {r["n"] for r in conn.execute(
        "SELECT lower(name) AS n FROM companies WHERE archived_at IS NULL").fetchall()}
    active_emails = {r["email"] for r in conn.execute(
        "SELECT email FROM contacts WHERE archived_at IS NULL AND email <> ''").fetchall()}
    suppressed_cache: dict[str, bool] = {}

    # ponytail: one query per distinct address; batch with unnest() if imports get large.
    def suppressed(addr: str) -> bool:
        if addr not in suppressed_cache:
            suppressed_cache[addr] = conn.execute("SELECT is_suppressed(%s) AS s", (addr,)).fetchone()["s"]
        return suppressed_cache[addr]

    seen_domains, seen_names, seen_emails = set(), set(), set()
    rows = []
    for line, r in enumerate(raw_rows, start=2):  # line 1 is the header
        r = {k: (v or "").strip() for k, v in r.items() if k is not None}
        out = {"line": line, "company": r["company"], "domain": "", "status": "new", "reason": "",
               "contacts": [], "skipped_emails": [], "raw": r}
        rows.append(out)

        website = r["website"]
        if website and not URL_RE.match(website):
            website = "https://" + website
        try:
            domain = normalize_domain(website)
        except ValueError:
            out.update(status="error", reason=f"invalid website: {r['website']}")
            continue
        out["domain"] = domain
        name = r["company"]
        if not name:
            out.update(status="error", reason="missing company name")
            continue
        if len(name) > 200:
            out.update(status="error", reason="company name longer than 200 characters")
            continue

        key = domain or f"name:{name.lower()}"
        if key in seen_domains or (not domain and name.lower() in seen_names):
            out.update(status="duplicate", reason="repeated in this file")
            continue
        seen_domains.add(key)
        seen_names.add(name.lower())
        if domain in active_domains or (not domain and name.lower() in active_names):
            out.update(status="duplicate", reason="company already exists")
            continue
        if domain and suppressed("probe@" + domain):
            out.update(status="blocked", reason="domain or company is on the do-not-contact list")
            continue

        out["company_row"] = {
            "name": name, "domain": domain, "website": website, "industry": r.get("field", "")[:200],
            "city": city, "country": country,
            "linkedin_url": r.get("linkedin", "") if URL_RE.match(r.get("linkedin", "")) else "",
        }
        for raw_email in r["all_emails"].split(";"):
            if not raw_email.strip():
                continue
            email, why = clean_email(raw_email)
            if email and not same_brand(email.split("@", 1)[1], domain):
                email, why = None, "another company's domain"
            elif email in seen_emails:
                email, why = None, "repeated in this file"
            elif email in active_emails:
                email, why = None, "already a contact"
            elif email and suppressed(email):
                email, why = None, "on the do-not-contact list"
            if email:
                seen_emails.add(email)
                out["contacts"].append({"email": email, "email_class": classify_email(email)})
            else:
                out["skipped_emails"].append({"email": raw_email.strip(), "reason": why})
        for person in split_names(r.get("contact_name", "")):
            if len(person) <= 200:
                out["contacts"].append({"name": person})

    count = lambda s: sum(1 for x in rows if x["status"] == s)  # noqa: E731
    summary = {
        "total": len(rows), "new": count("new"), "duplicate": count("duplicate"), "blocked": count("blocked"),
        "error": count("error"), "contacts": sum(len(x["contacts"]) for x in rows if x["status"] == "new"),
        "skipped_emails": sum(len(x["skipped_emails"]) for x in rows),
    }
    return {"columns": columns, "rows": rows, "summary": summary}


def rejected_csv(columns: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["line", *columns, "import_status", "import_reason"])
    for x in rows:
        if x["status"] != "new":
            w.writerow([x["line"], *(x["raw"].get(c, "") for c in columns), x["status"], x["reason"]])
    return buf.getvalue()


async def read_csv(request: Request) -> str:
    if int(request.headers.get("content-length") or 0) > MAX_BYTES:
        raise HTTPException(413, "CSV must be 5 MB or smaller")
    raw = await request.body()
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "CSV must be 5 MB or smaller")
    if not raw.strip():
        raise HTTPException(422, "The file is empty")
    return decode(raw)


def public(result: dict) -> dict:
    rows = [{k: v for k, v in x.items() if k not in ("raw", "company_row")} for x in result["rows"]]
    return {"summary": result["summary"], "rows": rows, "rejected_csv": rejected_csv(result["columns"], result["rows"])}


@router.post("/imports/preview")
async def preview(request: Request, filename: str, city: str = "", country: str = "", conn=Depends(get_db, scope="function")):
    """Analyse the CSV (raw body) without writing anything."""
    return public(analyze(conn, await read_csv(request), city.strip()[:200], country.strip()[:200]))


@router.post("/imports", status_code=201)
async def run_import(request: Request, filename: str, city: str = "", country: str = "", conn=Depends(get_db, scope="function")):
    """Re-analyse the same CSV against the current data and import the new rows."""
    filename = filename.strip()[:200] or "import.csv"
    result = analyze(conn, await read_csv(request), city.strip()[:200], country.strip()[:200])
    for x in result["rows"]:
        if x["status"] != "new":
            continue
        detail = {"file": filename, "row": x["line"],
                  "scraped": {c: x["raw"][c] for c in EXTRA_COLUMNS if x["raw"].get(c)}}
        company_id = conn.execute(
            "INSERT INTO companies (name, domain, website, industry, city, country, linkedin_url, source, source_detail) "
            "VALUES (%(name)s, %(domain)s, %(website)s, %(industry)s, %(city)s, %(country)s, %(linkedin_url)s, "
            "'csv_import', %(detail)s) RETURNING id",
            {**x["company_row"], "detail": Jsonb(detail)},
        ).fetchone()["id"]
        for c in x["contacts"]:
            conn.execute(
                "INSERT INTO contacts (company_id, name, email, email_class, source, source_detail) "
                "VALUES (%s, %s, %s, %s, 'csv_import', %s)",
                (company_id, c.get("name", ""), c.get("email", ""), c.get("email_class"),
                 Jsonb({"file": filename, "row": x["line"]})),
            )
    audit(conn, "import.completed", "import", None, {"file": filename, "city": city, "country": country,
                                                     **result["summary"]})
    return public(result)
