"""M5: companies and contacts CRUD. Delete = archive; nothing is hard-deleted."""
import re
from contextlib import contextmanager
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from psycopg import errors
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.deps import audit, get_db, require_owner
from app.email_class import EMAIL_RE, classify_email

router = APIRouter(dependencies=[Depends(require_owner)])

URL = r"^(https?://\S+)?$"
DOMAIN_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
EMAIL_CLASSES = ("careers", "personal", "generic", "unsuitable")


def normalize_domain(value: str) -> str:
    """'https://www.Acme.de/jobs' -> 'acme.de'. Empty stays empty."""
    d = value.strip().lower()
    d = re.sub(r"^[a-z][a-z0-9+.-]*://", "", d)
    d = re.split(r"[/?#:]", d, maxsplit=1)[0].rstrip(".")
    d = d.removeprefix("www.")
    if d and not DOMAIN_RE.match(d):
        raise ValueError(f"not a valid domain: {value!r}")
    return d


class CompanyIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    domain: str = Field("", max_length=253)
    website: str = Field("", max_length=500, pattern=URL)
    industry: str = Field("", max_length=200)
    city: str = Field("", max_length=200)
    country: str = Field("", max_length=200)
    description: str = Field("", max_length=4000)
    linkedin_url: str = Field("", max_length=500, pattern=URL)

    @field_validator("domain")
    @classmethod
    def _domain(cls, v: str) -> str:
        return normalize_domain(v)

    @model_validator(mode="after")
    def _domain_from_website(self):
        if not self.domain and self.website:
            self.domain = normalize_domain(self.website)
        return self


class ContactIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field("", max_length=200)
    email: str = Field("", max_length=254)
    role: str = Field("", max_length=200)
    phone: str = Field("", max_length=50)
    linkedin_url: str = Field("", max_length=500, pattern=URL)
    email_class: Literal["auto", "careers", "personal", "generic", "unsuitable"] = "auto"

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.lower()
        if v and not EMAIL_RE.match(v):
            raise ValueError("not a valid email address")
        return v

    @model_validator(mode="after")
    def _name_or_email(self):
        if not (self.name or self.email):
            raise ValueError("a contact needs a name or an email")
        return self


@contextmanager
def conflict_as_409(message: str):
    try:
        yield
    except errors.UniqueViolation:
        raise HTTPException(409, message) from None


def contact_row(body: ContactIn) -> dict:
    data = body.model_dump()
    chosen = data.pop("email_class")
    if not data["email"]:
        data["email_class"], data["email_class_manual"] = None, False
    elif chosen == "auto":
        data["email_class"], data["email_class_manual"] = classify_email(data["email"]), False
    else:
        data["email_class"], data["email_class_manual"] = chosen, True
    return data


ENTITY = {"companies": "company", "contacts": "contact"}


def fetch(conn, table: str, row_id: int) -> dict:
    row = conn.execute(f"SELECT * FROM {table} WHERE id = %s", (row_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"{ENTITY[table].capitalize()} not found")
    return row


def set_archived(conn, table: str, row_id: int, archived: bool, message: str) -> dict:
    fetch(conn, table, row_id)
    with conflict_as_409(message):
        row = conn.execute(
            f"UPDATE {table} SET archived_at = {'now()' if archived else 'NULL'}, updated_at = now() "
            "WHERE id = %s RETURNING *",
            (row_id,),
        ).fetchone()
    audit(conn, f"{ENTITY[table]}.{'archived' if archived else 'restored'}", ENTITY[table], row_id)
    return row


def assignments(data: dict) -> str:
    return ", ".join(f"{k} = %({k})s" for k in data)  # keys come from the model, not the client


# ---- companies ----

@router.get("/companies")
def list_companies(archived: bool = False, conn=Depends(get_db, scope="function")):
    return conn.execute(
        "SELECT c.*, count(ct.id) FILTER (WHERE ct.archived_at IS NULL) AS contact_count "
        "FROM companies c LEFT JOIN contacts ct ON ct.company_id = c.id "
        "WHERE (c.archived_at IS NOT NULL) = %s GROUP BY c.id ORDER BY lower(c.name), c.id",
        (archived,),
    ).fetchall()


@router.post("/companies", status_code=201)
def create_company(body: CompanyIn, conn=Depends(get_db, scope="function")):
    data = body.model_dump()
    with conflict_as_409(f"An active company already uses the domain {data['domain']}"):
        row = conn.execute(
            f"INSERT INTO companies ({', '.join(data)}) VALUES ({', '.join(f'%({k})s' for k in data)}) RETURNING *",
            data,
        ).fetchone()
    audit(conn, "company.created", "company", row["id"], {"name": row["name"], "domain": row["domain"]})
    return row


@router.get("/companies/{company_id}")
def get_company(company_id: int, conn=Depends(get_db, scope="function")):
    company = fetch(conn, "companies", company_id)
    block = conn.execute(
        "SELECT id, reason FROM suppressions WHERE kind = 'company' AND company_id = %s AND lifted_at IS NULL",
        (company_id,),
    ).fetchone()
    company["block"] = block
    company["contacts"] = conn.execute(
        "SELECT *, (%s OR (email <> '' AND is_suppressed(email))) AS suppressed FROM contacts "
        "WHERE company_id = %s ORDER BY archived_at IS NOT NULL, lower(name), id",
        (block is not None, company_id),
    ).fetchall()
    return company


@router.put("/companies/{company_id}")
def update_company(company_id: int, body: CompanyIn, conn=Depends(get_db, scope="function")):
    fetch(conn, "companies", company_id)
    data = body.model_dump()
    with conflict_as_409(f"An active company already uses the domain {data['domain']}"):
        row = conn.execute(
            f"UPDATE companies SET {assignments(data)}, updated_at = now() WHERE id = %(id)s RETURNING *",
            {**data, "id": company_id},
        ).fetchone()
    audit(conn, "company.updated", "company", company_id)
    return row


@router.post("/companies/{company_id}/archive")
def archive_company(company_id: int, conn=Depends(get_db, scope="function")):
    return set_archived(conn, "companies", company_id, True, "")


@router.post("/companies/{company_id}/restore")
def restore_company(company_id: int, conn=Depends(get_db, scope="function")):
    return set_archived(conn, "companies", company_id, False,
                        "Another active company now uses this domain; archive or change it first")


# ---- contacts ----

@router.post("/companies/{company_id}/contacts", status_code=201)
def create_contact(company_id: int, body: ContactIn, conn=Depends(get_db, scope="function")):
    fetch(conn, "companies", company_id)
    data = {**contact_row(body), "company_id": company_id}
    with conflict_as_409(f"An active contact already uses {data['email']}"):
        row = conn.execute(
            f"INSERT INTO contacts ({', '.join(data)}) VALUES ({', '.join(f'%({k})s' for k in data)}) RETURNING *",
            data,
        ).fetchone()
    audit(conn, "contact.created", "contact", row["id"], {"company_id": company_id, "email_class": row["email_class"]})
    return row


@router.put("/contacts/{contact_id}")
def update_contact(contact_id: int, body: ContactIn, conn=Depends(get_db, scope="function")):
    fetch(conn, "contacts", contact_id)
    data = contact_row(body)
    with conflict_as_409(f"An active contact already uses {data['email']}"):
        row = conn.execute(
            f"UPDATE contacts SET {assignments(data)}, updated_at = now() WHERE id = %(id)s RETURNING *",
            {**data, "id": contact_id},
        ).fetchone()
    audit(conn, "contact.updated", "contact", contact_id, {"email_class": row["email_class"],
                                                           "manual": row["email_class_manual"]})
    return row


@router.post("/contacts/{contact_id}/archive")
def archive_contact(contact_id: int, conn=Depends(get_db, scope="function")):
    return set_archived(conn, "contacts", contact_id, True, "")


@router.post("/contacts/{contact_id}/restore")
def restore_contact(contact_id: int, conn=Depends(get_db, scope="function")):
    return set_archived(conn, "contacts", contact_id, False,
                        "Another active contact now uses this email; archive or change it first")
