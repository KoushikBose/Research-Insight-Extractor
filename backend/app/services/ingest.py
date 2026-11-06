"""Ingestion: parse -> normalise -> guardrails -> de-duplicate -> store -> index -> (queued job) extract."""
import hashlib
import json
import sqlite3
import time

from .. import db as dbm
from .. import guardrails as gr
from . import extractor
from .parser import extract_doi, norm_title, parse_any

RESTRICTED_LICENSES = {"unknown", "all-rights-reserved", "subscription"}
MIME = {"pdf": "application/pdf", "xml": "application/xml", "txt": "text/plain", "md": "text/markdown"}


class IngestError(ValueError):
    pass


class DuplicateError(IngestError):
    """The document is already in the knowledge base. Carries the existing paper so the UI can link to it."""

    def __init__(self, existing_id: int, matched_by: str, title: str = ""):
        self.existing_id, self.matched_by, self.title = existing_id, matched_by, title
        how = {"file": "identical file", "content": "identical text", "doi": "same DOI", "title": "same title"}.get(matched_by, matched_by)
        super().__init__(f"Duplicate document: this paper is already in the library ({how}) as #{existing_id}"
                         + (f" “{title[:80]}”" if title else "") + ".")

    def detail(self) -> dict:
        return {"code": "duplicate", "message": str(self), "existing_id": self.existing_id,
                "matched_by": self.matched_by, "title": self.title}


def file_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def find_by_file_hash(sha: str):
    with dbm.db() as c:
        r = c.execute("SELECT p.id, p.title FROM files f JOIN papers p ON p.id=f.paper_id WHERE f.file_hash=? LIMIT 1",
                      (sha,)).fetchone()
    return dict(r) if r else None


def _find_dup(c, h, doi, tnorm):
    """Content hash -> DOI -> normalised title. Returns (paper_id, matched_by)."""
    r = c.execute("SELECT id FROM papers WHERE content_hash=?", (h,)).fetchone()
    if r:
        return r["id"], "content"
    if doi:
        r = c.execute("SELECT id FROM papers WHERE doi=?", (doi,)).fetchone()
        if r:
            return r["id"], "doi"
    if tnorm and len(tnorm.split()) >= 5:
        r = c.execute("SELECT id FROM papers WHERE title_norm=?", (tnorm,)).fetchone()
        if r:
            return r["id"], "title"
    return None, None


def _put_file(c, pid, raw, filename):
    if raw is None:
        return
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    c.execute("INSERT OR REPLACE INTO files(paper_id,filename,mime,size,data,file_hash) VALUES(?,?,?,?,?,?)",
              (pid, filename, MIME.get(ext, "application/octet-stream"), len(raw), sqlite3.Binary(raw), file_sha256(raw)))


def _put_sections(c, pid, clean):
    for i, s in enumerate(clean):
        c.execute("INSERT INTO sections(paper_id,name,ord,text) VALUES(?,?,?,?)", (pid, s["name"], i, s["text"]))
        dbm.index_section(c, pid, s["name"], s["text"])


def store_paper(parsed: dict, source: str, source_id=None, license="unknown", confidential=False,
                raw: bytes | None = None, filename: str | None = None) -> dict:
    sections = [s for s in parsed["sections"] if s["text"].strip()]
    if not sections:
        raise IngestError("No extractable text found (scanned PDF without a working OCR engine?).")
    flags = []
    clean = []
    for s in sections:
        txt, found = gr.sanitize_document(s["text"])
        if found:
            flags.append(f"injection_in_{s['name']}:{len(found)}")
        clean.append({"name": s["name"], "text": txt})
    if license in RESTRICTED_LICENSES and gr.on("quote_limit"):
        flags.append("restricted_license:quotes_capped")
    if parsed.get("ocr"):
        flags.append("ocr_used")
    full = "\n".join(s["text"] for s in clean)
    h = hashlib.sha256(full.encode()).hexdigest()
    doi = (parsed.get("doi") or extract_doi(full[:6000])).lower()
    tnorm = norm_title(parsed.get("title"))
    with dbm.db() as c:
        dup, how = _find_dup(c, h, doi, tnorm)
        if dup:
            old_len = c.execute("SELECT COALESCE(SUM(LENGTH(text)),0) n FROM sections WHERE paper_id=?", (dup,)).fetchone()["n"]
            if how != "content" and len(full) > 2 * old_len:
                # Same paper arriving with much richer text (e.g. full PDF after a PubMed abstract): upgrade in place.
                for t in ("sections", "insights", "paper_tables", "paper_figures", "chunk_vec"):
                    c.execute(f"DELETE FROM {t} WHERE paper_id=?", (dup,))
                c.execute("DELETE FROM chunks_fts WHERE paper_id=?", (dup,))
                c.execute("UPDATE papers SET content_hash=?, status='ingested', source=?, source_id=?, "
                          "doi=COALESCE(NULLIF(doi,''),?), flags=? WHERE id=?",
                          (h, source, source_id, doi, json.dumps(flags), dup))
                _put_sections(c, dup, clean)
                _put_file(c, dup, raw, filename)
                c.execute("INSERT INTO audit_log(ts,paper_id,action,detail) VALUES(?,?,?,?)",
                          (time.time(), dup, "upgrade", f"matched_by={how}; replaced abstract-only text with full text"))
                return {"id": dup, "duplicate": True, "upgraded": True, "matched_by": how}
            attached = False
            if raw is not None and not c.execute("SELECT 1 FROM files WHERE paper_id=?", (dup,)).fetchone():
                _put_file(c, dup, raw, filename)
                attached = True
            if doi and not c.execute("SELECT doi FROM papers WHERE id=?", (dup,)).fetchone()["doi"]:
                c.execute("UPDATE papers SET doi=? WHERE id=?", (doi, dup))
            return {"id": dup, "duplicate": True, "file_attached": attached, "matched_by": how}
        cur = c.execute(
            "INSERT INTO papers(title,authors,pub_date,keywords,source,source_id,license,confidential,content_hash,"
            "status,flags,created_at,doi,title_norm) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (parsed.get("title") or "Untitled", json.dumps(parsed.get("authors", [])), parsed.get("pub_date", ""),
             json.dumps(parsed.get("keywords", [])), source, source_id, license, int(confidential), h,
             "ingested", json.dumps(flags), time.time(), doi, tnorm))
        pid = cur.lastrowid
        _put_file(c, pid, raw, filename)
        _put_sections(c, pid, clean)
    dbm.audit(pid, "ingest", f"source={source} confidential={confidential} flags={flags}")
    return {"id": pid, "duplicate": False, "flags": flags}


def ingest_file(filename: str, data: bytes, confidential=False, license="unknown", source="upload") -> dict:
    t0 = time.time()
    ok, reason = gr.check_upload(filename, data)
    if not ok:
        raise IngestError(reason)
    # 1) exact same file already stored -> reject before spending time on parsing / OCR
    same = find_by_file_hash(file_sha256(data))
    if same:
        raise DuplicateError(same["id"], "file", same["title"])
    try:
        parsed = parse_any(filename, data)
    except Exception as e:
        raise IngestError(f"Could not parse {filename}: {e}")
    r = store_paper(parsed, source=source, source_id=filename, license=license, confidential=confidential,
                    raw=data, filename=filename)
    # 2) same paper by text / DOI / title -> reject, unless it enriched the record (full text upgrade, or the
    #    existing paper had no original file and this upload supplied it)
    if r.get("duplicate") and not r.get("upgraded") and not r.get("file_attached"):
        with dbm.db() as c:
            row = c.execute("SELECT title FROM papers WHERE id=?", (r["id"],)).fetchone()
        raise DuplicateError(r["id"], r.get("matched_by", "content"), row["title"] if row else "")
    with dbm.db() as c:
        c.execute("UPDATE papers SET ingest_ms=? WHERE id=?", ((time.time() - t0) * 1000, r["id"]))
    return r


def ingest_folder() -> list:
    from ..config import settings
    results = []
    for p in sorted(settings.INTERNAL_REPO_DIR.glob("*")):
        if p.suffix.lower() in gr.ALLOWED_EXT:
            try:
                r = ingest_file(p.name, p.read_bytes(), confidential=True, license="internal", source="internal_repo")
                results.append({"file": p.name, **r})
            except IngestError as e:
                results.append({"file": p.name, "error": str(e)})
    return results


def load_paper(paper_id: int):
    with dbm.db() as c:
        p = c.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
        if not p:
            return None
        secs = c.execute("SELECT name,text FROM sections WHERE paper_id=? ORDER BY ord", (paper_id,)).fetchall()
        ins = c.execute("SELECT data,created_at FROM insights WHERE paper_id=?", (paper_id,)).fetchone()
        f = c.execute("SELECT filename,mime,size FROM files WHERE paper_id=?", (paper_id,)).fetchone()
        tabs = c.execute("SELECT page,idx,caption,rows FROM paper_tables WHERE paper_id=? ORDER BY page,idx",
                         (paper_id,)).fetchall()
        figs = c.execute("SELECT page,label,caption FROM paper_figures WHERE paper_id=? ORDER BY page,id",
                         (paper_id,)).fetchall()
    paper = dict(p)
    paper["file"] = dict(f) if f else None
    for k in ("authors", "keywords", "flags"):
        paper[k] = json.loads(paper[k] or "[]")
    paper["confidential"] = bool(paper["confidential"])
    paper.pop("content_hash", None)
    paper["sections"] = [dict(s) for s in secs]
    paper["tables"] = [{**dict(t), "rows": json.loads(t["rows"])} for t in tabs]
    paper["figures"] = [dict(f) for f in figs]
    paper["insights"] = json.loads(ins["data"]) if ins else None
    return paper


def run_extraction(paper_id: int):
    """LLM/extractive insight extraction. Called from the job queue."""
    paper = load_paper(paper_id)
    if not paper:
        return
    with dbm.db() as c:
        c.execute("UPDATE papers SET status='extracting', error=NULL WHERE id=?", (paper_id,))
    try:
        # confidentiality routing: proprietary papers never go to the external LLM
        use_llm = not (paper["confidential"] and gr.on("confidential_local_only"))
        t0 = time.time()
        res = extractor.extract_from_sections(paper["sections"], paper["keywords"], use_llm=use_llm, paper_id=paper_id)
        if not use_llm:
            res["guardrail"]["flags"].append("confidential:processed_locally")
        with dbm.db() as c:
            c.execute("INSERT INTO insights(paper_id,data,created_at) VALUES(?,?,?) "
                      "ON CONFLICT(paper_id) DO UPDATE SET data=excluded.data, created_at=excluded.created_at",
                      (paper_id, json.dumps(res), time.time()))
            c.execute("UPDATE papers SET status='ready', keywords=? WHERE id=?",
                      (json.dumps(res["keywords"]), paper_id))
        ext_ms = (time.time() - t0) * 1000
        dbm.log_event("extraction", paper_id, ext_ms,
                      {"mode": res["mode"], "grounding_rate": res["guardrail"]["grounding_rate"],
                       "ingest_ms": paper.get("ingest_ms") or 0, "pages_or_chars": sum(len(s["text"]) for s in paper["sections"])})
        dbm.audit(paper_id, "extract", f"mode={res['mode']} model={res['model']} flags={res['guardrail']['flags']}")
    except Exception as e:
        with dbm.db() as c:
            c.execute("UPDATE papers SET status='error', error=? WHERE id=?", (str(e)[:500], paper_id))
        dbm.audit(paper_id, "extract_error", str(e))


def post_process(paper_id: int):
    """Tables (PDF) + semantic index. Failures here never fail the paper."""
    from . import parser, semantic
    try:
        with dbm.db() as c:
            f = c.execute("SELECT mime,data FROM files WHERE paper_id=?", (paper_id,)).fetchone()
            has_tables = c.execute("SELECT 1 FROM paper_tables WHERE paper_id=?", (paper_id,)).fetchone()
        if f and f["mime"] == "application/pdf" and not has_tables:
            tabs = parser.extract_tables(bytes(f["data"]))
            with dbm.db() as c:
                for t in tabs:
                    c.execute("INSERT INTO paper_tables(paper_id,page,idx,caption,rows) VALUES(?,?,?,?,?)",
                              (paper_id, t["page"], t["idx"], t["caption"], json.dumps(t["rows"])))
                    flat = t["caption"] + "\n" + "\n".join(" | ".join(r) for r in t["rows"])
                    dbm.index_section(c, paper_id, "Table", flat[:4000])
            if tabs:
                dbm.audit(paper_id, "tables", f"{len(tabs)} table(s) extracted")
        with dbm.db() as c:
            has_figs = c.execute("SELECT 1 FROM paper_figures WHERE paper_id=?", (paper_id,)).fetchone()
        if f and f["mime"] == "application/pdf" and not has_figs:
            figs = parser.extract_figures(bytes(f["data"]))
            with dbm.db() as c:
                for g in figs:
                    c.execute("INSERT INTO paper_figures(paper_id,page,label,caption) VALUES(?,?,?,?)",
                              (paper_id, g["page"], g["label"], g["caption"]))
                if figs:
                    dbm.index_section(c, paper_id, "Figures", "\n".join(f"{g['label']}. {g['caption']}" for g in figs)[:6000])
            if figs:
                dbm.audit(paper_id, "figures", f"{len(figs)} figure caption(s) extracted")
    except Exception as e:
        dbm.audit(paper_id, "tables_error", str(e))
    try:
        n = semantic.index_paper(paper_id)
        if n:
            dbm.audit(paper_id, "semantic_index", f"{n} chunk embeddings")
    except Exception as e:
        dbm.audit(paper_id, "semantic_error", str(e))


def backfill():
    """Upgrade rows created before DOI/title de-dup, entities and semantic search existed (no LLM calls)."""
    from . import jobs
    from .entities import extract_entities
    with dbm.db() as c:
        c.execute("UPDATE papers SET doi = rtrim(substr(doi, 1, instr(lower(doi), 'doi:') - 1), '.,;:') WHERE instr(lower(doi), 'doi:') > 1")
        for r in c.execute("SELECT paper_id, data FROM files WHERE file_hash IS NULL").fetchall():
            c.execute("UPDATE files SET file_hash=? WHERE paper_id=?", (file_sha256(bytes(r["data"])), r["paper_id"]))
        todo = c.execute("SELECT id,title FROM papers WHERE title_norm IS NULL").fetchall()
        for r in todo:
            text = " ".join(x["text"] for x in c.execute("SELECT text FROM sections WHERE paper_id=? ORDER BY ord", (r["id"],)))
            c.execute("UPDATE papers SET title_norm=?, doi=COALESCE(NULLIF(doi,''),?) WHERE id=?",
                      (norm_title(r["title"]), extract_doi(text[:6000]), r["id"]))
        from .entities import clean_terms, is_junk
        for r in c.execute("SELECT i.paper_id, i.data FROM insights i").fetchall():      # drop licence / URL junk stored by older runs
            d = json.loads(r["data"])
            kw = clean_terms(d.get("keywords", []))
            ents = {t: [e for e in v if not is_junk(e["text"])] for t, v in (d.get("entities") or {}).items()}
            if kw != d.get("keywords") or ents != d.get("entities"):
                d["keywords"], d["entities"] = kw, ents
                c.execute("UPDATE insights SET data=? WHERE paper_id=?", (json.dumps(d), r["paper_id"]))
                c.execute("UPDATE papers SET keywords=? WHERE id=?", (json.dumps(kw), r["paper_id"]))
        missing = c.execute("SELECT i.paper_id, i.data FROM insights i").fetchall()
        for r in missing:
            d = json.loads(r["data"])
            if "entities" not in d:
                text = " ".join(x["text"] for x in c.execute("SELECT text FROM sections WHERE paper_id=?", (r["paper_id"],)))
                d["entities"] = extract_entities(text)
                c.execute("UPDATE insights SET data=? WHERE paper_id=?", (json.dumps(d), r["paper_id"]))
        unindexed = c.execute("SELECT p.id FROM papers p WHERE p.status='ready' AND NOT EXISTS "
                              "(SELECT 1 FROM chunk_vec v WHERE v.paper_id=p.id)").fetchall()
    for r in unindexed:
        jobs.enqueue("post_process", {"paper_id": r["id"]})
    return {"keys": len(todo), "entities": len(missing), "to_index": len(unindexed)}
