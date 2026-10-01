"""M3: owner profile, CV versions and the {{my_*}} template variables."""
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from app.deps import audit, get_db, require_owner

router = APIRouter(dependencies=[Depends(require_owner)])

MAX_CV_BYTES = 5 * 1024 * 1024
URL = r"^(https?://\S+)?$"
MONTH = r"\d{4}-(0[1-9]|1[0-2])"


class Experience(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    company: str = Field(min_length=1, max_length=200)
    start: str = Field(pattern=f"^{MONTH}$")
    end: str = Field("", pattern=f"^({MONTH})?$")  # empty = current job
    description: str = Field("", max_length=4000)


class ProfileIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    full_name: str = Field("", max_length=200)
    email: str = Field("", max_length=254, pattern=r"^([^@\s]+@[^@\s]+\.[^@\s]+)?$")
    phone: str = Field("", max_length=50)
    location: str = Field("", max_length=200)
    headline: str = Field("", max_length=200)
    summary: str = Field("", max_length=4000)
    skills: list[str] = Field(default_factory=list, max_length=100)
    experience: list[Experience] = Field(default_factory=list, max_length=50)
    linkedin_url: str = Field("", max_length=500, pattern=URL)
    github_url: str = Field("", max_length=500, pattern=URL)
    portfolio_url: str = Field("", max_length=500, pattern=URL)
    target_roles: list[str] = Field(default_factory=list, max_length=50)
    target_locations: list[str] = Field(default_factory=list, max_length=50)
    work_mode: Literal["remote", "hybrid", "onsite", "any"] = "any"
    availability: str = Field("", max_length=200)


LIST_FIELDS = ("skills", "target_roles", "target_locations")


def resolve_variables(p: dict) -> dict[str, str]:
    """All 16 my_* variables. An empty string means unresolved."""
    current = next((e for e in p["experience"] if not e.get("end")), {})
    names = p["full_name"].split()
    return {
        "my_full_name": p["full_name"],
        "my_first_name": names[0] if names else "",
        "my_email": p["email"],
        "my_phone": p["phone"],
        "my_location": p["location"],
        "my_headline": p["headline"],
        "my_summary": p["summary"],
        "my_skills": ", ".join(p["skills"]),
        "my_top_skills": ", ".join(p["skills"][:3]),
        "my_current_title": current.get("title", ""),
        "my_current_company": current.get("company", ""),
        "my_linkedin": p["linkedin_url"],
        "my_github": p["github_url"],
        "my_portfolio": p["portfolio_url"],
        "my_target_role": p["target_roles"][0] if p["target_roles"] else "",
        "my_availability": p["availability"],
    }


def load_profile(conn) -> dict:
    return conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()


@router.get("/profile")
def get_profile(conn=Depends(get_db, scope="function")):
    p = load_profile(conn)
    p.pop("id")
    return p


@router.put("/profile")
def update_profile(body: ProfileIn, conn=Depends(get_db, scope="function")):
    data = body.model_dump()
    for f in LIST_FIELDS:
        data[f] = [s for s in data[f] if s]
    data["experience"] = Jsonb(data["experience"])
    cols = ", ".join(f"{k} = %({k})s" for k in data)  # keys come from the model, not the client
    conn.execute(f"UPDATE profile SET {cols}, updated_at = now() WHERE id = 1", data)
    audit(conn, "profile.updated", "profile", 1)
    return get_profile(conn)


@router.get("/profile/variables")
def get_variables(conn=Depends(get_db, scope="function")):
    variables = resolve_variables(load_profile(conn))
    has_default_cv = conn.execute("SELECT EXISTS (SELECT 1 FROM cv_versions WHERE is_default)").fetchone()["exists"]
    return {
        "variables": variables,
        "unresolved": [k for k, v in variables.items() if not v],
        "default_cv_set": has_default_cv,
    }


@router.get("/cv")
def list_cvs(conn=Depends(get_db, scope="function")):
    return conn.execute(
        "SELECT id, label, filename, octet_length(content) AS size_bytes, is_default, uploaded_at "
        "FROM cv_versions ORDER BY id DESC"
    ).fetchall()


@router.post("/cv", status_code=201)
async def upload_cv(request: Request, label: str, filename: str = "cv.pdf", conn=Depends(get_db, scope="function")):
    """Raw PDF bytes in the body; label and filename as query parameters."""
    label = label.strip()
    if not 1 <= len(label) <= 100:
        raise HTTPException(400, "Label must be 1–100 characters")
    if int(request.headers.get("content-length") or 0) > MAX_CV_BYTES:
        raise HTTPException(413, "CV must be 5 MB or smaller")
    content = await request.body()
    if len(content) > MAX_CV_BYTES:
        raise HTTPException(413, "CV must be 5 MB or smaller")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(400, "File is not a PDF")
    filename = re.sub(r"[^A-Za-z0-9._ -]", "_", filename)[:120] or "cv.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    row = conn.execute(
        "INSERT INTO cv_versions (label, filename, content, is_default) "
        "VALUES (%s, %s, %s, NOT EXISTS (SELECT 1 FROM cv_versions WHERE is_default)) "
        "RETURNING id, is_default",
        (label, filename, content),
    ).fetchone()
    audit(conn, "cv.uploaded", "cv_version", row["id"], {"label": label, "is_default": row["is_default"]})
    return row


@router.post("/cv/{cv_id}/default")
def set_default_cv(cv_id: int, conn=Depends(get_db, scope="function")):
    if not conn.execute("SELECT 1 FROM cv_versions WHERE id = %s", (cv_id,)).fetchone():
        raise HTTPException(404, "CV version not found")
    conn.execute("UPDATE cv_versions SET is_default = false WHERE is_default AND id <> %s", (cv_id,))
    conn.execute("UPDATE cv_versions SET is_default = true WHERE id = %s", (cv_id,))
    audit(conn, "cv.default_set", "cv_version", cv_id)
    return {"id": cv_id, "is_default": True}


@router.get("/cv/{cv_id}/file")
def download_cv(cv_id: int, conn=Depends(get_db, scope="function")):
    row = conn.execute("SELECT filename, content FROM cv_versions WHERE id = %s", (cv_id,)).fetchone()
    if not row:
        raise HTTPException(404, "CV version not found")
    return Response(
        bytes(row["content"]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{row["filename"]}"'},
    )
