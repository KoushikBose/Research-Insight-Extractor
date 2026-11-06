"""SQLite persistence (stdlib sqlite3) with FTS5 for retrieval over paper sections."""
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT, authors TEXT, pub_date TEXT, keywords TEXT DEFAULT '[]',
  source TEXT, source_id TEXT, license TEXT DEFAULT 'unknown',
  confidential INTEGER DEFAULT 0, content_hash TEXT UNIQUE,
  status TEXT DEFAULT 'ingested', error TEXT, flags TEXT DEFAULT '[]',
  created_at REAL
);
CREATE TABLE IF NOT EXISTS sections(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
  name TEXT, ord INTEGER, text TEXT
);
CREATE TABLE IF NOT EXISTS files(
  paper_id INTEGER PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
  filename TEXT, mime TEXT, size INTEGER, data BLOB
);
CREATE TABLE IF NOT EXISTS insights(
  paper_id INTEGER PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
  data TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, paper_id INTEGER, action TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, type TEXT, paper_id INTEGER,
  latency_ms REAL, meta TEXT
);
CREATE TABLE IF NOT EXISTS settings_kv(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS eval_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, report TEXT);
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, payload TEXT, status TEXT DEFAULT 'queued',
  result TEXT, error TEXT, attempts INTEGER DEFAULT 0, created_at REAL, started_at REAL, finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS saved_searches(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, source TEXT, query TEXT, interval_hours REAL DEFAULT 24,
  auto_ingest INTEGER DEFAULT 1, max_new INTEGER DEFAULT 10, active INTEGER DEFAULT 1, last_run REAL, created_at REAL
);
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, search_id INTEGER, paper_id INTEGER, title TEXT,
  source_id TEXT, ingested INTEGER DEFAULT 0, seen INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS paper_tables(
  id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
  page INTEGER, idx INTEGER, caption TEXT, rows TEXT
);
CREATE TABLE IF NOT EXISTS paper_figures(
  id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
  page INTEGER, label TEXT, caption TEXT
);
CREATE TABLE IF NOT EXISTS llm_calls(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, task TEXT, role TEXT, model TEXT, status TEXT,
  error_type TEXT, error TEXT, latency_ms REAL, prompt_tokens INTEGER, completion_tokens INTEGER,
  fallback_from TEXT, paper_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_llm_ts ON llm_calls(ts);
CREATE TABLE IF NOT EXISTS chunk_vec(
  chunk_rowid INTEGER PRIMARY KEY, paper_id INTEGER, section TEXT, vec BLOB
);
CREATE INDEX IF NOT EXISTS idx_vec_paper ON chunk_vec(paper_id);
"""

# One row per successful call that was served by the FALLBACK model, with the primary failure that caused it.
FALLBACK_VIEW = """
CREATE VIEW v_llm_fallbacks AS
SELECT f.id, f.ts, f.task, f.paper_id,
       f.fallback_from AS primary_model, f.model AS fallback_model,
       COALESCE(p.error_type, 'unknown') AS reason_type,
       COALESCE(p.error, '') AS reason,
       CASE WHEN p.status = 'skipped' THEN 'circuit open (primary in cooldown)' ELSE 'primary call failed' END AS trigger,
       f.latency_ms, f.prompt_tokens, f.completion_tokens
FROM llm_calls f
LEFT JOIN llm_calls p ON p.id = (
    SELECT p2.id FROM llm_calls p2
    WHERE p2.role = 'primary' AND p2.status IN ('error', 'skipped') AND p2.task IS f.task
      AND p2.id < f.id AND p2.ts >= f.ts - 180 ORDER BY p2.id DESC LIMIT 1)
WHERE f.role = 'fallback' AND f.status = 'ok'
"""

MIGRATIONS = [("papers", "doi", "TEXT"), ("papers", "title_norm", "TEXT"), ("papers", "ingest_ms", "REAL"),
              ("files", "file_hash", "TEXT")]

FTS = "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(paper_id UNINDEXED, section UNINDEXED, text)"
_fts_ok = True


def _connect():
    Path(settings.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    global _fts_ok
    with db() as c:
        c.executescript(SCHEMA)
        try:
            c.execute(FTS)
        except sqlite3.OperationalError:
            _fts_ok = False
        c.execute("DROP VIEW IF EXISTS v_llm_fallbacks")      # re-created on every start so definition changes apply
        c.execute(FALLBACK_VIEW)
        for table, col, typ in MIGRATIONS:  # lightweight migrations for pre-existing databases
            cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        c.execute("CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_papers_title ON papers(title_norm)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_files_hash ON files(file_hash)")


def audit(paper_id, action, detail=""):
    with db() as c:
        c.execute("INSERT INTO audit_log(ts,paper_id,action,detail) VALUES(?,?,?,?)",
                  (time.time(), paper_id, action, str(detail)[:2000]))


def log_event(type_, paper_id=None, latency_ms=None, meta=None):
    with db() as c:
        c.execute("INSERT INTO events(ts,type,paper_id,latency_ms,meta) VALUES(?,?,?,?,?)",
                  (time.time(), type_, paper_id, latency_ms, json.dumps(meta or {})))


def index_section(conn, paper_id, name, text):
    if not _fts_ok:
        return
    # chunk long sections so retrieval returns focused passages
    for chunk in chunk_text(text):
        conn.execute("INSERT INTO chunks_fts(paper_id,section,text) VALUES(?,?,?)", (paper_id, name, chunk))


def chunk_text(text, size=900, overlap=150):
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        i += size - overlap
    return out


def fts_query(q: str) -> str:
    toks = [t for t in re.findall(r"[A-Za-z0-9\-]{2,}", q) if t.lower() not in _STOP]
    return " OR ".join(f'"{t}"' for t in toks[:12])


_STOP = set("the a an of in on for and or to is are was were what which who how does do did with by from that this these those as at be it its".split())


def search_chunks(q: str, limit=6, paper_ids=None):
    """BM25-ranked passages. Falls back to LIKE if FTS5 is unavailable."""
    match = fts_query(q)
    if not match:
        return []
    with db() as c:
        if _fts_ok:
            sql = ("SELECT f.rowid AS rid, f.paper_id, f.section, f.text, p.title, bm25(chunks_fts) AS score "
                   "FROM chunks_fts f JOIN papers p ON p.id=f.paper_id WHERE chunks_fts MATCH ? ")
            args = [match]
            if paper_ids:
                sql += f"AND f.paper_id IN ({','.join('?' * len(paper_ids))}) "
                args += list(paper_ids)
            sql += "ORDER BY score LIMIT ?"
            args.append(limit)
            rows = c.execute(sql, args).fetchall()
        else:
            like = f"%{q.split()[0]}%" if q.split() else "%"
            rows = c.execute("SELECT s.paper_id, s.name AS section, s.text, p.title, 0 AS score FROM sections s "
                             "JOIN papers p ON p.id=s.paper_id WHERE s.text LIKE ? LIMIT ?", (like, limit)).fetchall()
    return [dict(r) for r in rows]


def get_setting(key, default=None):
    with db() as c:
        r = c.execute("SELECT value FROM settings_kv WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def set_setting(key, value):
    with db() as c:
        c.execute("INSERT INTO settings_kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, json.dumps(value)))
