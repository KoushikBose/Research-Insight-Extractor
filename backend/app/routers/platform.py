"""Platform endpoints: job queue, connectors, monitoring, exploration analytics, settings, hybrid search."""
import json
import re
import time
from collections import Counter
from itertools import combinations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db as dbm
from ..config import settings
from ..services import gateway, jobs, monitor, semantic, tokenomics

router = APIRouter(prefix="/api", tags=["platform"])


# ---------------------------------------------------------------- jobs / bulk ingest / connectors
@router.get("/jobs")
def get_jobs(limit: int = 40):
    return jobs.list_jobs(limit)


class BulkPubmed(BaseModel):
    query: str
    n: int = 10


@router.post("/jobs/pubmed-bulk")
def bulk_pubmed(b: BulkPubmed):
    return {"job_id": jobs.enqueue("bulk_pubmed", {"query": b.query, "n": min(b.n, 100)})}


class BioRxiv(BaseModel):
    query: str = ""
    days: int = 7
    server: str = "biorxiv"
    n: int = 10


@router.post("/connectors/biorxiv")
def biorxiv(b: BioRxiv):
    if b.server not in ("biorxiv", "medrxiv"):
        raise HTTPException(400, "server must be biorxiv or medrxiv")
    return {"job_id": jobs.enqueue("bulk_biorxiv", {**b.model_dump(), "n": min(b.n, 100), "days": min(b.days, 60)})}


class SqlImport(BaseModel):
    path: str
    table: str
    title_col: str
    text_col: str
    doi_col: str = ""
    date_col: str = ""
    authors_col: str = ""
    limit: int = 200
    confidential: bool = True


@router.post("/connectors/sql")
def sql_import(b: SqlImport):
    return {"job_id": jobs.enqueue("import_sql", b.model_dump())}


@router.post("/connectors/folder")
def folder():
    return {"job_id": jobs.enqueue("import_folder", {})}


# ---------------------------------------------------------------- monitoring
class SavedSearch(BaseModel):
    name: str
    source: str = "pubmed"            # pubmed | biorxiv | medrxiv
    query: str
    interval_hours: float = 24
    auto_ingest: bool = True
    max_new: int = 10


@router.post("/monitor/searches")
def add_search(s: SavedSearch):
    if s.source not in ("pubmed", "biorxiv", "medrxiv"):
        raise HTTPException(400, "unknown source")
    with dbm.db() as c:
        cur = c.execute("INSERT INTO saved_searches(name,source,query,interval_hours,auto_ingest,max_new,created_at) "
                        "VALUES(?,?,?,?,?,?,?)", (s.name, s.source, s.query, max(s.interval_hours, 0.1),
                                                  int(s.auto_ingest), min(s.max_new, 50), time.time()))
        sid = cur.lastrowid
    return {"id": sid, "job_id": jobs.enqueue("monitor_run", {"search_id": sid})}


@router.get("/monitor/searches")
def list_searches():
    with dbm.db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM saved_searches ORDER BY id DESC")]


@router.delete("/monitor/searches/{sid}")
def del_search(sid: int):
    with dbm.db() as c:
        c.execute("DELETE FROM saved_searches WHERE id=?", (sid,))
    return {"deleted": sid}


@router.post("/monitor/searches/{sid}/run")
def run_search_now(sid: int):
    return {"job_id": jobs.enqueue("monitor_run", {"search_id": sid})}


@router.get("/monitor/alerts")
def alerts(limit: int = 50):
    with dbm.db() as c:
        rows = c.execute("SELECT a.*, s.name AS search_name FROM alerts a LEFT JOIN saved_searches s ON s.id=a.search_id "
                         "ORDER BY a.id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/monitor/alerts/seen")
def alerts_seen():
    with dbm.db() as c:
        c.execute("UPDATE alerts SET seen=1")
    return {"ok": True}


# ---------------------------------------------------------------- hybrid search
@router.get("/search")
def search(q: str, limit: int = 8):
    rows = semantic.hybrid_search(q, limit=limit)
    return {"semantic_enabled": semantic.ready(),
            "results": [{"paper_id": r["paper_id"], "section": r["section"], "title": r["title"],
                         "text": r["text"][:500], "via": r.get("via", "bm25")} for r in rows]}


# ---------------------------------------------------------------- settings
class Baseline(BaseModel):
    manual_review_minutes: float


@router.get("/settings/baseline")
def get_baseline():
    return {"manual_review_minutes": dbm.get_setting("manual_review_minutes", settings.MANUAL_REVIEW_MINUTES)}


@router.put("/settings/baseline")
def put_baseline(b: Baseline):
    if not 1 <= b.manual_review_minutes <= 600:
        raise HTTPException(400, "minutes must be between 1 and 600")
    dbm.set_setting("manual_review_minutes", b.manual_review_minutes)
    return get_baseline()


# ---------------------------------------------------------------- exploration analytics
def _first_int(s):
    m = re.search(r"\d[\d,]*", s or "")
    return int(m.group(0).replace(",", "")) if m else None


@router.get("/explore")
def explore():
    with dbm.db() as c:
        rows = c.execute("SELECT p.id,p.title,p.pub_date,p.source,p.doi,p.confidential,i.data FROM papers p "
                         "LEFT JOIN insights i ON i.paper_id=p.id").fetchall()
    years, sources, kw, ent_by_type = Counter(), Counter(), Counter(), {}
    per_paper_terms, compare = {}, []
    for r in rows:
        sources[r["source"]] += 1
        y = (r["pub_date"] or "")[:4]
        if y.isdigit():
            years[y] += 1
        if not r["data"]:
            continue
        d = json.loads(r["data"])
        terms = set()
        for k in d.get("keywords", [])[:12]:
            kw[k.lower()] += 1
            terms.add(k.lower())
        for t, items in (d.get("entities") or {}).items():
            cnt = ent_by_type.setdefault(t, Counter())
            for e in items:
                cnt[e["text"]] += 1
                if t in ("gene_protein", "drug_compound", "disease"):
                    terms.add(e["text"].lower())
        per_paper_terms[r["id"]] = terms
        det = d.get("details", {})
        v = lambda f: (det.get(f) or {}).get("value", "")
        compare.append({"id": r["id"], "title": r["title"], "year": y, "source": r["source"],
                        "design": v("study_design"), "population": v("population_or_model"),
                        "sample_size": v("sample_size"), "n": _first_int(v("sample_size")),
                        "dosage": v("dosage"), "key_results": v("key_results"), "statistics": v("statistics"),
                        "conclusion": v("conclusion"), "grounding": d.get("guardrail", {}).get("grounding_rate")})
    # keyword/entity co-occurrence network over the most frequent terms
    freq = Counter(t for terms in per_paper_terms.values() for t in terms)
    nodes = [t for t, _ in freq.most_common(18)]
    edges = Counter()
    for terms in per_paper_terms.values():
        for a, b in combinations(sorted(set(nodes) & terms), 2):
            edges[(a, b)] += 1
    return {
        "totals": {"papers": len(rows), "analysed": len(per_paper_terms)},
        "papers_per_year": sorted(years.items()),
        "sources": sources.most_common(),
        "top_keywords": kw.most_common(12),
        "entities": {t: c.most_common(8) for t, c in ent_by_type.items()},
        "network": {"nodes": [{"id": n, "count": freq[n]} for n in nodes],
                    "edges": [{"a": a, "b": b, "w": w} for (a, b), w in edges.most_common(60)]},
        "compare": compare,
    }


# ---------------------------------------------------------------- LLM gateway (LiteLLM) status & control
@router.get("/llm/status")
def llm_status():
    """Which model is primary / fallback, their health, who served recent calls, and every fallback event."""
    return gateway.status()


class LlmConfig(BaseModel):
    primary: str | None = None
    fallback: str | None = None


_MODEL_ID = re.compile(r"^[A-Za-z0-9_.:/\-]{3,120}$")


@router.put("/llm/config")
def llm_config(c: LlmConfig):
    for v in (c.primary, c.fallback):
        if v and not _MODEL_ID.match(v):
            raise HTTPException(400, "model ids look like 'provider/model', e.g. groq/openai/gpt-oss-120b")
    gateway.set_models(c.primary, c.fallback)
    gateway.reset_circuit()
    return gateway.status()


class LlmTest(BaseModel):
    target: str = "chain"      # chain | primary | fallback


@router.post("/llm/test")
def llm_test(t: LlmTest):
    """Send a tiny prompt through the chain (or a single model) to verify connectivity and see the fallback in action."""
    if t.target not in ("chain", "primary", "fallback"):
        raise HTTPException(400, "target must be chain, primary or fallback")
    if not gateway.available():
        raise HTTPException(400, "No LLM credentials configured (set GROQ_API_KEY or LITELLM_PROXY_URL)")
    t0 = time.time()
    try:
        r = gateway.chat("Reply with the single word: pong", "ping", task="health_check", only=None if t.target == "chain" else t.target)
        return {"ok": True, "model": r["model"], "role": r["role"], "fallback_used": r["fallback_used"], "attempts": r["attempts"],
                "reply": r["text"][:80], "latency_ms": round((time.time() - t0) * 1000)}
    except gateway.GatewayError as e:
        return {"ok": False, "error": str(e), "attempts": e.attempts, "latency_ms": round((time.time() - t0) * 1000)}


class Outage(BaseModel):
    on: bool


@router.post("/llm/simulate-outage")
def llm_simulate(o: Outage):
    """Demo switch: make the primary model fail so you can watch the fallback take over (and the SQL view fill up)."""
    gateway.set_primary_outage(o.on)
    return {"simulated_primary_outage": gateway.primary_outage_simulated()}


@router.post("/llm/reset-circuit")
def llm_reset():
    gateway.reset_circuit()
    return {"ok": True}


@router.get("/llm/fallbacks")
def llm_fallbacks(limit: int = 100):
    """Rows of the SQL view v_llm_fallbacks."""
    with dbm.db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM v_llm_fallbacks ORDER BY id DESC LIMIT ?", (min(limit, 500),))]


# ---------------------------------------------------------------- tokenomics & trade-offs
@router.get("/tokenomics")
def get_tokenomics(days: int = 7):
    return tokenomics.report(max(1, min(days, 90)))


class TokSettings(BaseModel):
    hourly_rate_usd: float | None = None
    papers_per_month: float | None = None
    daily_token_budget: float | None = None
    manual_review_minutes: float | None = None


@router.put("/tokenomics/settings")
def put_tok_settings(b: TokSettings):
    patch = {k: v for k, v in b.model_dump().items() if v is not None and k != "manual_review_minutes"}
    try:
        tokenomics.set_settings(patch)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if b.manual_review_minutes is not None:
        if not 1 <= b.manual_review_minutes <= 600:
            raise HTTPException(400, "manual_review_minutes must be between 1 and 600")
        dbm.set_setting("manual_review_minutes", b.manual_review_minutes)
    return tokenomics.get_settings()


class PriceBody(BaseModel):
    model: str
    price_in: float | None = None     # USD per 1M input tokens;  both None = remove the override
    price_out: float | None = None


@router.put("/tokenomics/price")
def put_price(b: PriceBody):
    if not _MODEL_ID.match(b.model):
        raise HTTPException(400, "invalid model id")
    try:
        tokenomics.set_price(b.model, b.price_in, b.price_out)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return tokenomics.price_of(b.model)
