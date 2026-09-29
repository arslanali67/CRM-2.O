"""M27: verified facts. Only owner actions create them (DB trigger checks app.actor = 'owner'); they are read only
through personalization_facts(), the single path to personalization (M9)."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.deps import audit, get_db, require_owner
from app.research import CATEGORIES, company_or_404

router = APIRouter(dependencies=[Depends(require_owner)])

Category = Literal[CATEGORIES]


class VerifyIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    fact: str | None = Field(None, max_length=500)  # optional rewording; default = the claim as written
    category: Category | None = None


class FactIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    fact: str = Field(min_length=1, max_length=500)
    category: Category = "other"
    source: str = Field(min_length=1, max_length=500)  # a URL or where the owner knows it from


@router.get("/companies/{company_id}/facts")
def facts(company_id: int, conn=Depends(get_db)):
    company_or_404(conn, company_id)
    return conn.execute("SELECT * FROM personalization_facts(%s)", (company_id,)).fetchall()


@router.post("/claims/{claim_id}/verify", status_code=201)
def verify(claim_id: int, body: VerifyIn, conn=Depends(get_db)):
    c = conn.execute("UPDATE ai_claims SET status = 'verified', decided_at = now() WHERE id = %s AND status = 'open' "
                     "RETURNING *", (claim_id,)).fetchone()
    if not c:
        raise HTTPException(409, "Claim not found or already decided")
    f = conn.execute("INSERT INTO verified_facts (company_id, category, fact, source, from_claim_id) "
                     "VALUES (%s, %s, %s, %s, %s) RETURNING *",
                     (c["company_id"], body.category or c["category"], body.fact or c["claim"], c["source_url"],
                      claim_id)).fetchone()
    audit(conn, "fact.verified", "company", c["company_id"],
          {"fact_id": f["id"], "fact": f["fact"], "claim_id": claim_id, "reworded": bool(body.fact)})
    return f


@router.post("/companies/{company_id}/facts", status_code=201)
def add(company_id: int, body: FactIn, conn=Depends(get_db)):
    company_or_404(conn, company_id)
    f = conn.execute("INSERT INTO verified_facts (company_id, category, fact, source) VALUES (%s, %s, %s, %s) "
                     "RETURNING *", (company_id, body.category, body.fact, body.source)).fetchone()
    audit(conn, "fact.added", "company", company_id, {"fact_id": f["id"], "fact": body.fact, "source": body.source})
    return f


@router.post("/facts/{fact_id}/remove")
def remove(fact_id: int, conn=Depends(get_db)):
    f = conn.execute("UPDATE verified_facts SET removed_at = now() WHERE id = %s AND removed_at IS NULL "
                     "RETURNING company_id, fact", (fact_id,)).fetchone()
    if not f:
        raise HTTPException(404, "Fact not found")
    audit(conn, "fact.removed", "company", f["company_id"], {"fact_id": fact_id, "fact": f["fact"]})
    return {"ok": True}
