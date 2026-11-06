"""Semantic (embedding) search stored in SQLite, fused with BM25 via Reciprocal Rank Fusion.

Embeddings: fastembed (ONNX, BAAI/bge-small-en-v1.5, 384-d, runs on CPU, no torch). Vectors live in the
`chunk_vec` table as float32 BLOBs; cosine similarity is computed with numpy over an in-memory cache.
Everything degrades gracefully to BM25-only if the model cannot be loaded.
"""
import logging
import threading

import numpy as np

from .. import db as dbm

log = logging.getLogger(__name__)
MODEL_NAME = "BAAI/bge-small-en-v1.5"
_model = None
_failed = False
_lock = threading.Lock()
_cache = {"sig": None, "ids": None, "mat": None, "meta": None}


def _get_model():
    global _model, _failed
    if _failed:
        return None
    with _lock:
        if _model is None:
            try:
                from fastembed import TextEmbedding
                _model = TextEmbedding(MODEL_NAME)
            except Exception as e:
                log.warning("Semantic search disabled (embedding model unavailable): %s", e)
                _failed = True
                return None
    return _model


def ready() -> bool:
    return _get_model() is not None


def embed(texts: list[str]) -> np.ndarray:
    m = _get_model()
    if m is None:
        raise RuntimeError("embedding model unavailable")
    v = np.array(list(m.embed(texts)), dtype=np.float32)
    return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)


def index_paper(paper_id: int) -> int:
    """Embed all not-yet-embedded chunks of a paper. Returns number of new vectors."""
    if not ready():
        return 0
    with dbm.db() as c:
        rows = c.execute("SELECT rowid AS rid, section, text FROM chunks_fts WHERE paper_id=? AND rowid NOT IN "
                         "(SELECT chunk_rowid FROM chunk_vec WHERE paper_id=?)", (paper_id, paper_id)).fetchall()
    n = 0
    for i in range(0, len(rows), 32):
        batch = rows[i:i + 32]
        vecs = embed([r["text"] for r in batch])
        with dbm.db() as c:
            c.executemany("INSERT OR REPLACE INTO chunk_vec(chunk_rowid,paper_id,section,vec) VALUES(?,?,?,?)",
                          [(r["rid"], paper_id, r["section"], vecs[j].tobytes()) for j, r in enumerate(batch)])
        n += len(batch)
    return n


def _load():
    with dbm.db() as c:
        sig = tuple(c.execute("SELECT COUNT(*), COALESCE(MAX(chunk_rowid),0) FROM chunk_vec").fetchone())
        if _cache["sig"] == sig:
            return
        rows = c.execute("SELECT v.chunk_rowid, v.paper_id, v.section, v.vec FROM chunk_vec v").fetchall()
    if not rows:
        _cache.update(sig=sig, ids=np.array([]), mat=np.zeros((0, 384), np.float32), meta=[])
        return
    _cache.update(sig=sig, ids=np.array([r[0] for r in rows]),
                  mat=np.vstack([np.frombuffer(r[3], dtype=np.float32) for r in rows]),
                  meta=[(r[1], r[2]) for r in rows])


def search(q: str, limit: int = 8, paper_ids=None, min_score: float = 0.55) -> list[dict]:
    if not ready():
        return []
    _load()
    if not len(_cache["ids"]):
        return []
    qv = embed([q])[0]
    scores = _cache["mat"] @ qv
    mask = np.ones(len(scores), bool)
    if paper_ids:
        allowed = set(paper_ids)
        mask = np.array([m[0] in allowed for m in _cache["meta"]])
    scores = np.where(mask, scores, -1)
    top = np.argsort(-scores)[: limit * 2]
    picks = [(int(_cache["ids"][i]), float(scores[i])) for i in top if scores[i] >= min_score][:limit]
    if not picks:
        return []
    with dbm.db() as c:
        out = []
        for rid, sc in picks:
            r = c.execute("SELECT f.rowid AS rid, f.paper_id, f.section, f.text, p.title FROM chunks_fts f "
                          "JOIN papers p ON p.id=f.paper_id WHERE f.rowid=?", (rid,)).fetchone()
            if r:
                d = dict(r)
                d["score"] = sc
                out.append(d)
    return out


ALPHA = 0.12   # weight of the BM25 rank bonus relative to cosine similarity (0..1)


def fuse(cos: dict, bm25_ranked: list) -> list:
    """Score-aware fusion: cosine similarity + ALPHA/(1+bm25_rank). Keys missing a cosine get the floor value,
    so semantic confidence is kept (rank-only fusion let a weak BM25 hit outvote a strong semantic match)."""
    floor = (min(cos.values()) - 0.05) if cos else 0.0
    keys = set(cos) | set(bm25_ranked)
    bonus = {k: ALPHA / (1 + i) for i, k in enumerate(bm25_ranked)}
    return sorted(keys, key=lambda k: cos.get(k, floor) + bonus.get(k, 0.0), reverse=True)


def hybrid_search(q: str, limit: int = 6, paper_ids=None) -> list[dict]:
    """BM25 + semantic, fused with fuse()."""
    bm = dbm.search_chunks(q, limit=limit * 3, paper_ids=paper_ids)
    sem = search(q, limit=limit * 3, paper_ids=paper_ids)
    if not sem:
        return bm[:limit]
    key = lambda r: r.get("rid") or (r["paper_id"], r["text"][:60])
    rows, via = {}, {}
    for r in bm:
        rows[key(r)] = r; via[key(r)] = "bm25"
    for r in sem:
        rows[key(r)] = {**rows.get(key(r), {}), **r}
        via[key(r)] = "hybrid" if key(r) in via else "semantic"
    order = fuse({key(r): r["score"] for r in sem}, [key(r) for r in bm])[:limit]
    return [{**rows[k], "via": via[k]} for k in order]
