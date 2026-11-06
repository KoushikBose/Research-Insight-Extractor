import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import db as dbm
from ..services import ingest, jobs, pubmed

router = APIRouter(prefix="/api", tags=["papers"])


def _queue(r: dict):
    """Queue AI extraction for new papers (and for papers upgraded to full text)."""
    if r.get("id") and (not r.get("duplicate") or r.get("upgraded")):
        r["job_id"] = jobs.enqueue("extract", {"paper_id": r["id"]})
    return r


@router.post("/papers/upload")
async def upload(file: UploadFile = File(...), confidential: bool = Form(False), license: str = Form("unknown")):
    data = await file.read()
    try:
        r = ingest.ingest_file(file.filename or "upload.txt", data, confidential, license)
    except ingest.DuplicateError as e:
        dbm.log_event("duplicate_blocked", e.existing_id, None, {"matched_by": e.matched_by, "file": file.filename})
        raise HTTPException(409, e.detail())          # Conflict: UI shows a toast with a link to the existing paper
    except ingest.IngestError as e:
        raise HTTPException(400, str(e))
    return _queue(r)


@router.get("/papers/check-hash")
def check_hash(sha256: str):
    """Pre-upload check: does the library already hold this exact file? (browser sends the SHA-256, not the file)"""
    hit = ingest.find_by_file_hash(sha256.lower())
    if not hit:
        return {"duplicate": False}
    return {"duplicate": True, "existing_id": hit["id"], "title": hit["title"], "matched_by": "file",
            "message": f"Duplicate document: this exact file is already in the library as #{hit['id']} “{hit['title'][:80]}”."}


@router.post("/ingest/folder")
def ingest_internal_folder():
    """Pull everything from the internal repository folder (treated as confidential)."""
    res = ingest.ingest_folder()
    for r in res:
        if r.get("id"):
            _queue(r)
    return res


@router.get("/pubmed/search")
def pubmed_search(q: str, n: int = 8):
    try:
        return pubmed.search(q, min(n, 20))
    except Exception as e:
        raise HTTPException(502, f"PubMed request failed: {e}")


class PubmedIngest(BaseModel):
    pmid: str


@router.post("/pubmed/ingest")
def pubmed_ingest(body: PubmedIngest):
    try:
        recs = pubmed.fetch([body.pmid])
    except Exception as e:
        raise HTTPException(502, f"PubMed request failed: {e}")
    if not recs or not recs[0]["abstract"]:
        raise HTTPException(404, "PMID not found or has no abstract")
    r = ingest.store_paper(pubmed.to_parsed(recs[0]), source="pubmed", source_id=body.pmid, license="abstract-open")
    return _queue(r)


@router.get("/papers")
def list_papers(q: str = ""):
    """Filter matches title, keywords and extracted entities (genes, drugs, diseases, assays...)."""
    sql = ("SELECT p.id,p.title,p.authors,p.pub_date,p.keywords,p.source,p.license,p.confidential,p.status,p.flags,"
           "p.created_at,p.doi,(f.paper_id IS NOT NULL) AS has_file, "
           "substr(json_extract(i.data,'$.summary'),1,260) AS summary, json_extract(i.data,'$.guardrail.grounding_rate') AS grounding, "
           "json_extract(i.data,'$.model_label') AS model_label, json_extract(i.data,'$.fallback_used') AS fallback_used, "
           "json_extract(i.data,'$.mode') AS mode, f.size AS file_size FROM papers p "
           "LEFT JOIN files f ON f.paper_id=p.id LEFT JOIN insights i ON i.paper_id=p.id ")
    args = []
    if q:
        sql += "WHERE p.title LIKE ? OR p.keywords LIKE ? OR i.data LIKE ? "
        args = [f"%{q}%"] * 3
    sql += "ORDER BY p.id DESC"
    with dbm.db() as c:
        rows = c.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("authors", "keywords", "flags"):
            d[k] = json.loads(d[k] or "[]")
        d["confidential"] = bool(d["confidential"])
        out.append(d)
    return out


@router.get("/papers/{pid}")
def get_paper(pid: int):
    p = ingest.load_paper(pid)
    if not p:
        raise HTTPException(404, "Paper not found")
    dbm.log_event("view", pid)
    return p


@router.get("/papers/{pid}/file")
def download_file(pid: int):
    """Return the original uploaded file stored in SQLite."""
    with dbm.db() as c:
        r = c.execute("SELECT filename,mime,data FROM files WHERE paper_id=?", (pid,)).fetchone()
    if not r:
        raise HTTPException(404, "No original file stored for this paper")
    return Response(content=bytes(r["data"]), media_type=r["mime"],
                    headers={"Content-Disposition": f'inline; filename="{r["filename"]}"'})


@router.post("/papers/{pid}/extract")
def re_extract(pid: int):
    if not ingest.load_paper(pid):
        raise HTTPException(404, "Paper not found")
    return {"status": "queued", "job_id": jobs.enqueue("extract", {"paper_id": pid})}


@router.delete("/papers/{pid}")
def delete_paper(pid: int):
    with dbm.db() as c:
        c.execute("DELETE FROM chunks_fts WHERE paper_id=?", (pid,))
        c.execute("DELETE FROM chunk_vec WHERE paper_id=?", (pid,))
        c.execute("DELETE FROM papers WHERE id=?", (pid,))
    dbm.audit(pid, "delete")
    return {"deleted": pid}


@router.get("/papers/{pid}/export")
def export(pid: int):
    p = ingest.load_paper(pid)
    if not p:
        raise HTTPException(404, "Paper not found")
    return {"id": pid, "title": p["title"], "doi": p.get("doi"), "source": p["source"], "source_id": p["source_id"],
            "insights": p["insights"], "tables": p["tables"], "figures": p["figures"],
            "provenance": "Each detail carries verbatim evidence + grounding status"}


@router.get("/papers/{pid}/audit")
def audit_trail(pid: int):
    with dbm.db() as c:
        rows = c.execute("SELECT ts,action,detail FROM audit_log WHERE paper_id=? ORDER BY id DESC", (pid,)).fetchall()
    return [dict(r) for r in rows]
