"""Source connectors: bioRxiv API, internal SQL database (read-only), plus PubMed (see pubmed.py).

Every connector returns *parsed* paper dicts and goes through ingest.store_paper, so guardrails, de-duplication
(content / DOI / title) and provenance apply uniformly regardless of where a paper comes from.
"""
import re
import sqlite3
from datetime import date, timedelta

import httpx

from . import ingest, pubmed
from .parser import extract_doi

BIORXIV = "https://api.biorxiv.org/details"
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ---------------------------------------------------------------- bioRxiv / medRxiv
def biorxiv_recent(query: str = "", days: int = 7, server: str = "biorxiv", n: int = 10, max_scan: int = 300) -> list[dict]:
    """Recent preprints (bioRxiv has no keyword API, so the date window is scanned and filtered locally)."""
    end, start = date.today(), date.today() - timedelta(days=days)
    terms = [t.lower() for t in re.findall(r"[A-Za-z0-9\-]{3,}", query)]
    out, cursor = [], 0
    while len(out) < n and cursor < max_scan:
        r = httpx.get(f"{BIORXIV}/{server}/{start}/{end}/{cursor}", timeout=30)
        r.raise_for_status()
        coll = r.json().get("collection", [])
        if not coll:
            break
        for it in coll:
            blob = (it.get("title", "") + " " + it.get("abstract", "")).lower()
            if not terms or all(t in blob for t in terms):
                out.append(it)
                if len(out) >= n:
                    break
        cursor += len(coll)
    return out


def biorxiv_to_parsed(it: dict) -> dict:
    return {"title": it.get("title", ""), "authors": [a.strip() for a in it.get("authors", "").split(";") if a.strip()][:15],
            "pub_date": it.get("date", ""), "keywords": [it["category"]] if it.get("category") else [],
            "doi": (it.get("doi") or "").lower(),
            "sections": [{"name": "Abstract", "text": it.get("abstract", "")}] if it.get("abstract") else [],
            "text": it.get("abstract", "")}


def ingest_biorxiv(query="", days=7, server="biorxiv", n=10) -> dict:
    res = {"ingested": [], "duplicates": 0, "errors": 0}
    for it in biorxiv_recent(query, days, server, n):
        try:
            r = ingest.store_paper(biorxiv_to_parsed(it), source=server, source_id=it.get("doi"), license="preprint-open")
            if r.get("duplicate") and not r.get("upgraded"):
                res["duplicates"] += 1
            else:
                res["ingested"].append(r["id"])
        except Exception:
            res["errors"] += 1
    return res


# ---------------------------------------------------------------- internal SQL database
def sql_import(path: str, table: str, title_col: str, text_col: str, doi_col: str = "", date_col: str = "",
               authors_col: str = "", limit: int = 200, confidential: bool = True) -> dict:
    """Import rows from an internal SQLite database (opened read-only). Identifiers are validated, values bound."""
    for ident in (table, title_col, text_col, doi_col, date_col, authors_col):
        if ident and not _IDENT.match(ident):
            raise ValueError(f"invalid identifier: {ident!r}")
    cols = [c for c in (title_col, text_col, doi_col, date_col, authors_col) if c]
    uri = "file:" + path.replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(f"SELECT {', '.join(cols)} FROM {table} LIMIT ?", (int(limit),)).fetchall()
    finally:
        conn.close()
    from .parser import normalize, segment
    res = {"ingested": [], "duplicates": 0, "errors": 0, "rows": len(rows)}
    for r in rows:
        try:
            text = normalize(str(r[text_col] or ""))
            if not text:
                continue
            parsed = {"title": str(r[title_col] or "Untitled"), "authors": [a.strip() for a in str(r[authors_col]).split(";")] if authors_col and r[authors_col] else [],
                      "pub_date": str(r[date_col]) if date_col and r[date_col] else "", "keywords": [],
                      "doi": (str(r[doi_col]).lower() if doi_col and r[doi_col] else extract_doi(text[:6000])),
                      "sections": segment(text) if len(text) > 400 else [{"name": "Abstract", "text": text}], "text": text}
            out = ingest.store_paper(parsed, source="internal_db", source_id=f"{table}", license="internal",
                                     confidential=confidential)
            if out.get("duplicate") and not out.get("upgraded"):
                res["duplicates"] += 1
            else:
                res["ingested"].append(out["id"])
        except Exception:
            res["errors"] += 1
    return res


# ---------------------------------------------------------------- PubMed bulk
def ingest_pubmed(query: str, n: int = 10, sort: str = "relevance") -> dict:
    res = {"ingested": [], "duplicates": 0, "errors": 0}
    for rec in pubmed.search(query, n, sort=sort):
        if not rec["abstract"]:
            continue
        try:
            r = ingest.store_paper(pubmed.to_parsed(rec), source="pubmed", source_id=rec["pmid"], license="abstract-open")
            if r.get("duplicate") and not r.get("upgraded"):
                res["duplicates"] += 1
            else:
                res["ingested"].append(r["id"])
        except Exception:
            res["errors"] += 1
    return res
