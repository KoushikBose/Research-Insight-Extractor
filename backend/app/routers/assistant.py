import json
import time

from fastapi import APIRouter
from pydantic import BaseModel

from .. import db as dbm
from .. import guardrails as gr
from ..config import settings
from ..eval import runner
from ..services import llm, research_agent

router = APIRouter(prefix="/api", tags=["assistant"])


class ChatBody(BaseModel):
    question: str
    paper_ids: list[int] | None = None


@router.post("/chat")
def chat(body: ChatBody):
    return research_agent.ask(body.question, body.paper_ids)


@router.get("/guardrails")
def get_guardrails():
    return {"config": gr.get_config(), "descriptions": gr.DESCRIPTIONS}


@router.put("/guardrails")
def put_guardrails(patch: dict):
    return {"config": gr.update_config(patch), "descriptions": gr.DESCRIPTIONS}


@router.post("/guardrails/test")
def test_guardrails(body: dict):
    """Dry-run a text through the input guardrails."""
    text = body.get("text", "")
    v = gr.check_query(text)
    return {"allowed": v.allowed, "reason": v.reason, "flags": v.flags,
            "injection_hits": gr.scan_injection(text), "redacted": gr.redact_pii(text)[0]}


@router.post("/eval/run")
def run_eval(use_llm: bool = False):
    rep = runner.run(use_llm)
    gr.load_from_db()  # runner resets config to defaults; restore persisted settings
    with dbm.db() as c:
        c.execute("INSERT INTO eval_runs(ts,report) VALUES(?,?)", (time.time(), json.dumps(rep)))
    return rep


@router.get("/eval/latest")
def latest_eval():
    with dbm.db() as c:
        r = c.execute("SELECT report FROM eval_runs ORDER BY id DESC LIMIT 1").fetchone()
    return json.loads(r["report"]) if r else None


class Feedback(BaseModel):
    paper_id: int | None = None
    kind: str = "extraction"
    rating: int  # 1 = helpful, -1 = not helpful


@router.post("/feedback")
def feedback(f: Feedback):
    dbm.log_event("feedback", f.paper_id, None, {"kind": f.kind, "rating": f.rating})
    return {"ok": True}


@router.get("/metrics/usage")
def usage():
    """Online KPIs: review-time reduction, extraction quality (live grounding), adoption."""
    with dbm.db() as c:
        papers = c.execute("SELECT COUNT(*) n FROM papers").fetchone()["n"]
        ready = c.execute("SELECT COUNT(*) n FROM papers WHERE status='ready'").fetchone()["n"]
        ext = c.execute("SELECT latency_ms, meta FROM events WHERE type='extraction'").fetchall()
        chats = c.execute("SELECT COUNT(*) n FROM events WHERE type='chat'").fetchone()["n"]
        blocked = c.execute("SELECT COUNT(*) n FROM events WHERE type='chat_blocked'").fetchone()["n"]
        views = c.execute("SELECT COUNT(*) n FROM events WHERE type='view'").fetchone()["n"]
        fb = c.execute("SELECT meta FROM events WHERE type='feedback'").fetchall()
    metas = [json.loads(r["meta"]) for r in ext]
    # time-to-insight = upload/parse time + extraction time, measured per paper
    tti = [(r["latency_ms"] or 0) + m.get("ingest_ms", 0) for r, m in zip(ext, metas)]
    gr_rates = [m.get("grounding_rate", 1) for m in metas]
    ratings = [json.loads(r["meta"]).get("rating", 0) for r in fb]
    avg = sum(tti) / len(tti) if tti else 0
    baseline_min = dbm.get_setting("manual_review_minutes", settings.MANUAL_REVIEW_MINUTES)
    manual = baseline_min * 60_000
    return {
        "papers_ingested": papers, "papers_ready": ready, "chat_queries": chats, "chat_blocked": blocked,
        "paper_views": views, "avg_extraction_s": round(avg / 1000, 2),
        "p95_extraction_s": round(runner.M.percentile(tti, 0.95) / 1000, 2),
        "avg_live_grounding_rate": round(sum(gr_rates) / len(gr_rates), 3) if gr_rates else None,
        "manual_review_minutes": baseline_min,
        "review_time_reduction": round(1 - avg / manual, 3) if tti else None,
        "hours_saved_est": round(len(tti) * (manual - avg) / 3_600_000, 2),
        "measured_papers": len(tti),
        "feedback_positive_rate": round(sum(1 for r in ratings if r > 0) / len(ratings), 3) if ratings else None,
        "feedback_count": len(ratings),
        "llm_enabled": llm.llm_available(), "model": settings.GROQ_MODEL if llm.llm_available() else None,
    }
