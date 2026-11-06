"""Persistent SQLite-backed job queue with worker threads.

Survives restarts (jobs left 'running' are re-queued), retries failed jobs, and lets bulk ingest / monitoring /
connector imports run without blocking API requests.
"""
import json
import logging
import threading
import time

from .. import db as dbm

log = logging.getLogger(__name__)
HANDLERS: dict = {}
_stop = threading.Event()
_threads: list = []
MAX_ATTEMPTS = 2


def register(kind):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


def enqueue(kind: str, payload: dict | None = None) -> int:
    with dbm.db() as c:
        cur = c.execute("INSERT INTO jobs(kind,payload,status,created_at) VALUES(?,?, 'queued', ?)",
                        (kind, json.dumps(payload or {}), time.time()))
        return cur.lastrowid


def _claim():
    with dbm.db() as c:
        r = c.execute("UPDATE jobs SET status='running', started_at=?, attempts=attempts+1 "
                      "WHERE id=(SELECT id FROM jobs WHERE status='queued' ORDER BY id LIMIT 1) AND status='queued' "
                      "RETURNING id, kind, payload, attempts", (time.time(),)).fetchone()
    return dict(r) if r else None


def _finish(job_id, status, result=None, error=None, requeue=False):
    with dbm.db() as c:
        if requeue:
            c.execute("UPDATE jobs SET status='queued', error=? WHERE id=?", (error, job_id))
        else:
            c.execute("UPDATE jobs SET status=?, result=?, error=?, finished_at=? WHERE id=?",
                      (status, json.dumps(result) if result is not None else None, error, time.time(), job_id))


def _worker(n):
    while not _stop.is_set():
        try:
            job = _claim()
        except Exception as e:  # DB busy etc.
            log.warning("job claim failed: %s", e)
            time.sleep(1)
            continue
        if not job:
            time.sleep(0.8)
            continue
        fn = HANDLERS.get(job["kind"])
        try:
            if fn is None:
                raise RuntimeError(f"no handler for job kind {job['kind']!r}")
            res = fn(**json.loads(job["payload"] or "{}"))
            _finish(job["id"], "done", res)
        except Exception as e:
            log.exception("job %s failed", job["id"])
            _finish(job["id"], "error", error=str(e)[:500], requeue=job["attempts"] < MAX_ATTEMPTS)


def start(workers: int = 2):
    with dbm.db() as c:  # crash recovery
        c.execute("UPDATE jobs SET status='queued' WHERE status='running'")
    _stop.clear()
    for i in range(workers):
        t = threading.Thread(target=_worker, args=(i,), daemon=True, name=f"job-worker-{i}")
        t.start()
        _threads.append(t)


def stop():
    _stop.set()


def list_jobs(limit=50):
    with dbm.db() as c:
        rows = c.execute("SELECT id,kind,payload,status,result,error,attempts,created_at,started_at,finished_at "
                         "FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        counts = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status")}
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d["payload"] or "{}")
        d["result"] = json.loads(d["result"]) if d["result"] else None
        out.append(d)
    return {"counts": counts, "jobs": out}
