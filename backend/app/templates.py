"""M8: email templates with immutable versions, strict variables and preview."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.companies import conflict_as_409, fetch
from app.deps import audit, get_db, require_owner
from app.leads import best_recipients
from app.profile import load_profile, resolve_variables
from app.templating import (COMPANY_VARIABLES, CONTACT_VARIABLES, MY_VARIABLES, RenderError, problems,
                            render_strict)

router = APIRouter(dependencies=[Depends(require_owner)])


class VersionIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)

    @model_validator(mode="after")
    def _strict(self):
        found = [f"subject: {p}" for p in problems(self.subject)] + [f"body: {p}" for p in problems(self.body)]
        if found:
            raise ValueError("; ".join(found))
        return self


class TemplateIn(VersionIn):
    name: str = Field(min_length=1, max_length=200)


class RenameIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)


class PreviewIn(BaseModel):
    company_id: int
    contact_id: int | None = None  # default: the company's best recipient (M6)
    version: int | None = None     # default: current version


def variable_values(conn, company_id: int, contact_id: int | None = None) -> tuple[dict[str, str], dict | None]:
    """All 26 variables for one company and recipient. Empty string = no value."""
    company = fetch(conn, "companies", company_id)
    if contact_id is None:
        contact = best_recipients(conn, [company_id]).get(company_id)
        contact = conn.execute("SELECT * FROM contacts WHERE id = %s", (contact["contact_id"],)).fetchone() if contact else None
    else:
        contact = conn.execute("SELECT * FROM contacts WHERE id = %s AND company_id = %s",
                               (contact_id, company_id)).fetchone()
        if not contact:
            raise HTTPException(404, "Contact not found at this company")
    values = resolve_variables(load_profile(conn))
    values.update({f"company_{k}": company[k] for k in ("name", "domain", "website", "city", "country", "industry")})
    name = (contact or {}).get("name", "")
    values.update({
        "contact_name": name,
        "contact_first_name": name.split()[0] if name.split() else "",
        "contact_role": (contact or {}).get("role", ""),
        "contact_email": (contact or {}).get("email", ""),
    })
    return values, contact


def current_versions_sql(where: str) -> str:
    return (
        "SELECT t.*, v.version, v.subject, v.created_at AS version_created_at FROM templates t "
        "JOIN LATERAL (SELECT * FROM template_versions WHERE template_id = t.id ORDER BY version DESC LIMIT 1) v ON true "
        f"WHERE {where}"
    )


@router.get("/templates/variables")
def list_variables():
    return {"my": MY_VARIABLES, "company": COMPANY_VARIABLES, "contact": CONTACT_VARIABLES}


@router.get("/templates")
def list_templates(archived: bool = False, conn=Depends(get_db)):
    return conn.execute(current_versions_sql("(t.archived_at IS NOT NULL) = %s") + " ORDER BY lower(t.name), t.id",
                        (archived,)).fetchall()


@router.post("/templates", status_code=201)
def create_template(body: TemplateIn, conn=Depends(get_db)):
    with conflict_as_409(f"An active template is already named {body.name!r}"):
        t = conn.execute("INSERT INTO templates (name) VALUES (%s) RETURNING *", (body.name,)).fetchone()
    conn.execute("INSERT INTO template_versions (template_id, version, subject, body) VALUES (%s, 1, %s, %s)",
                 (t["id"], body.subject, body.body))
    audit(conn, "template.created", "template", t["id"], {"name": body.name, "version": 1})
    return get_template(t["id"], conn)


@router.get("/templates/{template_id}")
def get_template(template_id: int, conn=Depends(get_db)):
    t = conn.execute("SELECT * FROM templates WHERE id = %s", (template_id,)).fetchone()
    if not t:
        raise HTTPException(404, "Template not found")
    t["versions"] = conn.execute(
        "SELECT * FROM template_versions WHERE template_id = %s ORDER BY version DESC", (template_id,)).fetchall()
    return t


@router.post("/templates/{template_id}/versions")
def save_version(template_id: int, body: VersionIn, conn=Depends(get_db)):
    """Editing = a new immutable version. Saving identical content creates nothing."""
    current = get_template(template_id, conn)["versions"][0]
    if (current["subject"], current["body"]) == (body.subject, body.body):
        return {"created": False, "version": current["version"]}
    version = current["version"] + 1
    conn.execute("INSERT INTO template_versions (template_id, version, subject, body) VALUES (%s, %s, %s, %s)",
                 (template_id, version, body.subject, body.body))
    audit(conn, "template.version_created", "template", template_id, {"version": version})
    return {"created": True, "version": version}


@router.put("/templates/{template_id}")
def rename_template(template_id: int, body: RenameIn, conn=Depends(get_db)):
    get_template(template_id, conn)
    with conflict_as_409(f"An active template is already named {body.name!r}"):
        conn.execute("UPDATE templates SET name = %s WHERE id = %s", (body.name, template_id))
    audit(conn, "template.renamed", "template", template_id, {"name": body.name})
    return get_template(template_id, conn)


@router.post("/templates/{template_id}/archive")
def archive_template(template_id: int, conn=Depends(get_db)):
    get_template(template_id, conn)
    conn.execute("UPDATE templates SET archived_at = now() WHERE id = %s", (template_id,))
    audit(conn, "template.archived", "template", template_id)
    return {"archived": template_id}


@router.post("/templates/{template_id}/restore")
def restore_template(template_id: int, conn=Depends(get_db)):
    get_template(template_id, conn)
    with conflict_as_409("Another active template now uses this name; rename it first"):
        conn.execute("UPDATE templates SET archived_at = NULL WHERE id = %s", (template_id,))
    audit(conn, "template.restored", "template", template_id)
    return {"restored": template_id}


@router.post("/templates/{template_id}/preview")
def preview(template_id: int, body: PreviewIn, conn=Depends(get_db)):
    """Render against a real lead. ok=False lists every unresolved variable; nothing is blank."""
    versions = get_template(template_id, conn)["versions"]
    v = versions[0] if body.version is None else next((x for x in versions if x["version"] == body.version), None)
    if not v:
        raise HTTPException(404, "Version not found")
    values, contact = variable_values(conn, body.company_id, body.contact_id)
    recipient = {k: contact[k] for k in ("id", "name", "email", "email_class")} if contact else None
    try:
        return {"ok": True, "version": v["version"], "recipient": recipient,
                **render_strict(v["subject"], v["body"], values)}
    except RenderError as e:
        return {"ok": False, "version": v["version"], "recipient": recipient, "unresolved": e.unresolved}
