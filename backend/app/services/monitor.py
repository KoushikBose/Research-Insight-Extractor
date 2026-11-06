"""Literature monitoring: saved searches run on a schedule, new papers are ingested (optionally) and raised as alerts."""
import logging
import math
import threading
import time

from .. import db as dbm
from . import connectors, ingest, jobs, pubmed

log = logging.getLogger(__name__)
_stop = threading.Event()


def _exists(c, source_id, doi):
    r = c.execute("SELECT id FROM papers WHERE (source_id=? AND source_id IS NOT NULL) OR (doi=? AND doi<>'')",
                  (source_id, doi or "~none~")).fetchone()
    return r["id"] if r else None


def run_search(search_id: int) -> dict:
    with dbm.db() as c:
        s = c.execute("SELECT * FROM saved_searches WHERE id=?", (search_id,)).fetchone()
    if not s:
        return {"error": "saved search not found"}
    s = dict(s)
    if s["source"] == "pubmed":
        items = [{"title": r["title"], "source_id": r["pmid"], "doi": r.get("doi", ""), "parsed": pubmed.to_parsed(r),
                  "ok": bool(r["abstract"])} for r in pubmed.search(s["query"], max(s["max_new"] * 2, 10), sort="date")]
        lic, src = "abstract-open", "pubmed"
    else:  # biorxiv / medrxiv
        days = max(2, math.ceil(s["interval_hours"] / 24) + 1)
        raw = connectors.biorxiv_recent(s["query"], days=days, server=s["source"], n=s["max_new"] * 2)
        items = [{"title": r.get("title", ""), "source_id": r.get("doi"), "doi": (r.get("doi") or "").lower(),
                  "parsed": connectors.biorxiv_to_parsed(r), "ok": bool(r.get("abstract"))} for r in raw]
        lic, src = "preprint-open", s["source"]
    new = 0
    for it in items:
        if new >= s["max_new"] or not it["ok"]:
            continue
        with dbm.db() as c:
            if _exists(c, it["source_id"], it["doi"]):
                continue
        pid, ingested = None, 0
        if s["auto_ingest"]:
            r = ingest.store_paper(it["parsed"], source=src, source_id=it["source_id"], license=lic)
            if r.get("duplicate") and not r.get("upgraded"):
                continue
            pid, ingested = r["id"], 1
            jobs.enqueue("extract", {"paper_id": pid})
        with dbm.db() as c:
            c.execute("INSERT INTO alerts(ts,search_id,paper_id,title,source_id,ingested) VALUES(?,?,?,?,?,?)",
                      (time.time(), search_id, pid, it["title"], it["source_id"], ingested))
        new += 1
    with dbm.db() as c:
        c.execute("UPDATE saved_searches SET last_run=? WHERE id=?", (time.time(), search_id))
    return {"search_id": search_id, "new_papers": new, "scanned": len(items)}


def _scheduler():
    while not _stop.is_set():
        try:
            now = time.time()
            with dbm.db() as c:
                due = c.execute("SELECT id FROM saved_searches WHERE active=1 AND "
                                "(last_run IS NULL OR ? - last_run >= interval_hours*3600)", (now,)).fetchall()
                for r in due:  # mark immediately so the next tick doesn't enqueue it twice
                    c.execute("UPDATE saved_searches SET last_run=? WHERE id=?", (now, r["id"]))
            for r in due:
                jobs.enqueue("monitor_run", {"search_id": r["id"]})
        except Exception as e:
            log.warning("scheduler tick failed: %s", e)
        _stop.wait(30)


def start():
    _stop.clear()
    threading.Thread(target=_scheduler, daemon=True, name="monitor-scheduler").start()


def stop():
    _stop.set()
