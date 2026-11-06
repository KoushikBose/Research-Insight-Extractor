"""Tokenomics tests (mocked LLM, known token counts so the arithmetic can be verified):  python tests/test_tokenomics.py
LiteLLM's mock_response reports 10 prompt + 20 completion tokens per call."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["GROQ_API_KEY"] = "test-key-not-real"
os.environ["LANGSMITH_TRACING"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import gateway, ingest, tokenomics  # noqa: E402

P, F = "groq/llama-3.2-test-primary", "groq/openai/gpt-oss-120b"
OK = []


def check(name, cond, info=""):
    OK.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


JSON = '{"overall":"O","sections":{"Abstract":"s"},"fields":{"objective":{"value":"aim","evidence":"The objective of this study"}},"keywords":["ELISA"]}'

with TestClient(app) as c:
    gateway.set_models(P, F)
    gateway.reset_circuit()
    gateway.TEST_PARAMS[P] = {"mock_response": "litellm.RateLimitError"}
    gateway.TEST_PARAMS[F] = {"mock_response": JSON}

    # prices
    pf = tokenomics.price_of(F)
    check("price of gpt-oss-120b comes from LiteLLM's map ($0.15 in / $0.60 out per 1M)", (pf["in"], pf["out"], pf["source"]) == (0.15, 0.6, "litellm"), pf)
    check("unknown model is 'unpriced' (not guessed)", tokenomics.price_of(P)["source"] == "unpriced")
    tokenomics.set_price(P, 0.9, 0.9)
    check("custom price override works", tokenomics.price_of(P) == {"in": 0.9, "out": 0.9, "source": "custom"})
    tokenomics.set_price(P, None, None)
    check("override can be removed", tokenomics.price_of(P)["source"] == "unpriced")

    # a paper whose extraction goes primary(fail) -> fallback, tagged with paper_id
    pid = ingest.store_paper({"title": "Tokenomics test paper about enzyme assays in mice", "authors": [], "pub_date": "2025", "keywords": [], "doi": "",
                              "sections": [{"name": "Abstract", "text": "The objective of this study was to test X in 10 mice."},
                                           {"name": "Methods", "text": "ELISA was used."}]}, source="upload")["id"]
    ingest.run_extraction(pid)
    r = tokenomics.report(7)
    pp = r["per_paper"]
    # 2 LLM calls per paper (summaries + details) x (10 prompt, 20 completion)
    check("per-paper tokens attributed (2 calls x 10/20)", (pp["papers_measured"], pp["avg_prompt_tokens"], pp["avg_completion_tokens"]) == (1, 20, 40), pp)
    exp = (20 * 0.15 + 40 * 0.60) / 1e6
    check("per-paper cost arithmetic = (20*0.15 + 40*0.60)/1e6", abs(pp["avg_llm_cost_usd"] - round(exp, 6)) < 1e-9, (pp["avg_llm_cost_usd"], exp))
    check("totals add up", r["totals"]["total_tokens"] == 60 and r["totals"]["calls_ok"] == 2, r["totals"])
    check("manual-vs-AI economics present", pp["manual_cost_usd"] == 20.0 and pp["savings_per_paper_usd"] > 19.9 and pp["cost_ratio_x"] > 1000, pp)
    check("monthly projection = per-paper x papers/month", r["monthly"]["llm_cost_usd"] == round(pp["avg_llm_cost_usd"] * 1000, 2) and r["monthly"]["hours_saved"] > 300, r["monthly"])
    check("by_task has both extraction tasks", {t["task"] for t in r["by_task"]} >= {"summarize_sections", "extract_details"})
    fb = next(m for m in r["by_model"] if m["model"] == F)
    check("by_model: fallback served, $/1k computed, tokens/sec sane (None when mocked latency is 0 ms)", fb["calls_ok"] == 2
          and abs(fb["cost_per_1k_tokens"] - 0.00045) < 1e-9 and (fb["tokens_per_sec"] is None or fb["tokens_per_sec"] > 0), fb)
    pm = next(m for m in r["by_model"] if m["model"] == P)
    check("failed primary attempts counted with error rate 100%", pm["errors"] == 2 and pm["error_rate"] == 1.0 and not pm["priced"], pm)
    check("warning raised for the unpriced primary", any("No price known" in w for w in r["warnings"]), r["warnings"])

    # fallback tax
    ft = r["fallback_tax"]
    check("fallback tax: calls, wasted latency, no hypothetical cost while primary unpriced",
          ft["fallback_calls"] == 2 and ft["failed_primary_attempts"] == 2 and ft["cost_delta_usd"] is None and not ft["primary_price_known"], ft)
    tokenomics.set_price(P, 0.9, 0.9)
    ft = tokenomics.report(7)["fallback_tax"]
    hyp = 60 * 0.9 / 1e6
    check("fallback tax: cost vs 'primary had served' (priced at $0.9/M)", ft["primary_price_known"] and abs(ft["cost_delta_usd"] - round(2.7e-5 - hyp, 6)) < 1e-9, ft)

    # quality / trade-off table
    q = {x["engine"]: x for x in r["quality_tradeoff"]}
    check("quality-vs-cost table lists the LLM engine with cost and field coverage", F in q and q[F]["avg_cost_usd"] > 0 and 0 < q[F]["avg_field_coverage"] <= 1, q.get(F))

    # scenarios
    sc = r["scenarios"]
    check("what-if table: priced models only, sorted by cost, includes the one in use", sc and F in {s["model"] for s in sc}
          and [s["cost_per_paper_usd"] for s in sc] == sorted(s["cost_per_paper_usd"] for s in sc), [(s["model"], s["cost_per_paper_usd"]) for s in sc][:4])
    check("budget tracks today's tokens", r["budget"]["used_today"] == 60, r["budget"])

    # API
    api = c.get("/api/tokenomics?days=7").json()
    check("GET /api/tokenomics returns the report", api["totals"]["total_tokens"] >= 60 and len(api["daily"]) == 7)
    check("PUT settings validated", c.put("/api/tokenomics/settings", json={"hourly_rate_usd": -5}).status_code == 400)
    s = c.put("/api/tokenomics/settings", json={"hourly_rate_usd": 100, "papers_per_month": 2000, "manual_review_minutes": 30}).json()
    check("PUT settings applied (rate, volume, manual minutes)", (s["hourly_rate_usd"], s["papers_per_month"], s["manual_review_minutes"]) == (100.0, 2000, 30))
    r2 = c.get("/api/tokenomics").json()
    check("economics recompute with new settings", r2["per_paper"]["manual_cost_usd"] == 50.0 and r2["monthly"]["papers_per_month"] == 2000, r2["per_paper"]["manual_cost_usd"])
    check("PUT price endpoint", c.put("/api/tokenomics/price", json={"model": "groq/my-model", "price_in": 1, "price_out": 2}).json()["source"] == "custom")
    check("PUT price rejects bad ids", c.put("/api/tokenomics/price", json={"model": "bad id!", "price_in": 1, "price_out": 2}).status_code == 400)

print(f"\n{OK.count(True)}/{len(OK)} checks passed")
sys.exit(0 if all(OK) else 1)
