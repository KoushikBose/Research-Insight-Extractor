"""Tokenomics & trade-offs: what the LLM layer costs, how fast it is, what quality it buys, and what the alternatives would do.

All numbers come from the `llm_calls` log (every gateway / agent call: tokens, latency, status, model, task, paper) joined with
the stored extraction results. Prices come from LiteLLM's price map, can be overridden per model, and models without a known
price are reported as "unpriced" (their cost counts as 0 and is flagged) - nothing is guessed silently.
"""
import json
import time
from collections import defaultdict

import litellm

from .. import db as dbm
from ..config import settings
from . import gateway

DEFAULTS = {"hourly_rate_usd": 60.0, "papers_per_month": 1000, "daily_token_budget": 1_000_000}
EXTRACTION_TASKS = ("summarize_sections", "extract_details")
# safety classifiers / speech / vision-only models are cheap but cannot do this job - keep them out of the what-if table
NOT_FOR_EXTRACTION = ("guard", "whisper", "tts", "embed", "orpheus", "playai", "distil-whisper", "compound")


# ------------------------------------------------------------------ settings & prices
def get_settings() -> dict:
    cur = {**DEFAULTS, **(dbm.get_setting("tokenomics_settings", {}) or {})}
    cur["manual_review_minutes"] = dbm.get_setting("manual_review_minutes", settings.MANUAL_REVIEW_MINUTES)
    return cur


def set_settings(patch: dict) -> dict:
    cur = dbm.get_setting("tokenomics_settings", {}) or {}
    for k in DEFAULTS:
        if k in patch:
            v = float(patch[k])
            if v <= 0:
                raise ValueError(f"{k} must be positive")
            cur[k] = int(v) if k != "hourly_rate_usd" else v
    dbm.set_setting("tokenomics_settings", cur)
    return get_settings()


def _litellm_price(model: str):
    v = litellm.model_cost.get(model) or litellm.model_cost.get(model.split("/", 1)[-1])
    if v and v.get("input_cost_per_token") is not None:
        return v["input_cost_per_token"] * 1e6, (v.get("output_cost_per_token") or 0) * 1e6
    return None


def price_of(model: str) -> dict:
    """USD per 1M tokens: custom override > LiteLLM price map > unpriced."""
    custom = (dbm.get_setting("llm_prices", {}) or {}).get(model)
    if custom:
        return {"in": custom["in"], "out": custom["out"], "source": "custom"}
    p = _litellm_price(model)
    return {"in": p[0], "out": p[1], "source": "litellm"} if p else {"in": None, "out": None, "source": "unpriced"}


def set_price(model: str, in_per_m: float | None, out_per_m: float | None):
    cur = dbm.get_setting("llm_prices", {}) or {}
    if in_per_m is None or out_per_m is None:
        cur.pop(model, None)                       # remove override
    else:
        if in_per_m < 0 or out_per_m < 0:
            raise ValueError("prices must be >= 0")
        cur[model] = {"in": float(in_per_m), "out": float(out_per_m)}
    dbm.set_setting("llm_prices", cur)


def cost_usd(model, pt, ct, price=None):
    p = price or price_of(model)
    if p["in"] is None:
        return None
    return ((pt or 0) * p["in"] + (ct or 0) * p["out"]) / 1e6


def _candidates(seen):
    cands = set(seen) | set(gateway.models().values())
    for k, v in litellm.model_cost.items():
        if k.startswith("groq/") and v.get("mode") == "chat" and v.get("input_cost_per_token") is not None                 and not any(bad in k for bad in NOT_FOR_EXTRACTION):
            cands.add(k)
    return sorted(cands)


# ------------------------------------------------------------------ report
def report(days: int = 7) -> dict:
    now = time.time()
    since = now - days * 86400
    st = get_settings()
    with dbm.db() as c:
        calls = [dict(r) for r in c.execute("SELECT * FROM llm_calls WHERE ts >= ? ORDER BY id", (since,))]
        ins = [dict(r) for r in c.execute("SELECT i.paper_id, i.data FROM insights i")]
    seen_models = {x["model"] for x in calls if x["model"]}
    pr = {m: price_of(m) for m in _candidates(seen_models)}
    ok = [x for x in calls if x["status"] == "ok"]

    def priced(x):
        return cost_usd(x["model"], x["prompt_tokens"], x["completion_tokens"], pr.get(x["model"]))

    # ---- totals & by model
    by_model, unpriced = {}, set()
    for x in calls:
        key = (x["model"], x["role"])
        m = by_model.setdefault(key, {"model": x["model"], "role": x["role"], "ok": 0, "errors": 0, "skipped": 0, "pt": 0, "ct": 0,
                                      "cost": 0.0, "lat": 0.0, "lat_ct": 0.0})
        if x["status"] == "ok":
            m["ok"] += 1
            m["pt"] += x["prompt_tokens"] or 0
            m["ct"] += x["completion_tokens"] or 0
            m["lat"] += x["latency_ms"] or 0
            if x["completion_tokens"]:
                m["lat_ct"] += x["latency_ms"] or 0
            c_ = priced(x)
            if c_ is None:
                unpriced.add(x["model"])
            else:
                m["cost"] += c_
        elif x["status"] == "error":
            m["errors"] += 1
        else:
            m["skipped"] += 1
    models_out = []
    for m in by_model.values():
        attempts = m["ok"] + m["errors"]
        tps = (m["ct"] / (m["lat_ct"] / 1000)) if m["lat_ct"] else None
        tot = m["pt"] + m["ct"]
        models_out.append({
            "model": m["model"], "role": m["role"], "calls_ok": m["ok"], "errors": m["errors"], "skipped": m["skipped"],
            "prompt_tokens": m["pt"], "completion_tokens": m["ct"], "total_tokens": tot, "cost_usd": round(m["cost"], 6),
            "avg_latency_ms": round(m["lat"] / m["ok"]) if m["ok"] else None, "tokens_per_sec": round(tps, 1) if tps else None,
            "cost_per_1k_tokens": round(m["cost"] / tot * 1000, 6) if tot and (pr.get(m["model"]) or price_of(m["model"]))["in"] is not None else None,
            "error_rate": round(m["errors"] / attempts, 3) if attempts else 0.0, "priced": (pr.get(m["model"]) or price_of(m["model"]))["in"] is not None,
            "price": pr.get(m["model"]) or price_of(m["model"])})
    models_out.sort(key=lambda r: -r["total_tokens"])
    pt = sum(m["prompt_tokens"] for m in models_out)
    ct = sum(m["completion_tokens"] for m in models_out)
    totals = {"calls_ok": len(ok), "calls_error": sum(1 for x in calls if x["status"] == "error"),
              "calls_skipped": sum(1 for x in calls if x["status"] == "skipped"), "prompt_tokens": pt, "completion_tokens": ct,
              "total_tokens": pt + ct, "cost_usd": round(sum(m["cost_usd"] for m in models_out), 6),
              "avg_latency_ms": round(sum(x["latency_ms"] or 0 for x in ok) / len(ok)) if ok else None,
              "output_input_ratio": round(ct / pt, 2) if pt else None}

    # ---- by task
    tasks = defaultdict(lambda: {"calls": 0, "pt": 0, "ct": 0, "cost": 0.0, "lat": 0.0, "errors": 0, "fallback": 0})
    for x in calls:
        t = tasks[x["task"] or "?"]
        if x["status"] == "ok":
            t["calls"] += 1; t["pt"] += x["prompt_tokens"] or 0; t["ct"] += x["completion_tokens"] or 0
            t["lat"] += x["latency_ms"] or 0; t["cost"] += priced(x) or 0
            t["fallback"] += x["role"] == "fallback"
        elif x["status"] == "error":
            t["errors"] += 1
    by_task = sorted(({"task": k, "calls": v["calls"], "prompt_tokens": v["pt"], "completion_tokens": v["ct"],
                       "cost_usd": round(v["cost"], 6), "avg_latency_ms": round(v["lat"] / v["calls"]) if v["calls"] else None,
                       "errors": v["errors"], "fallback_calls": v["fallback"]} for k, v in tasks.items()),
                     key=lambda r: -(r["prompt_tokens"] + r["completion_tokens"]))

    # ---- daily series
    daily = {}
    for i in range(days):
        d = time.strftime("%Y-%m-%d", time.localtime(now - (days - 1 - i) * 86400))
        daily[d] = {"day": d, "tokens": 0, "cost_usd": 0.0, "calls": 0, "fallback_calls": 0}
    for x in ok:
        d = daily.get(time.strftime("%Y-%m-%d", time.localtime(x["ts"])))
        if d:
            d["tokens"] += (x["prompt_tokens"] or 0) + (x["completion_tokens"] or 0)
            d["cost_usd"] += priced(x) or 0
            d["calls"] += 1
            d["fallback_calls"] += x["role"] == "fallback"
    daily = [{**d, "cost_usd": round(d["cost_usd"], 6)} for d in daily.values()]

    # ---- per paper economics (extraction tasks tagged with paper_id)
    pp = defaultdict(lambda: {"tokens": 0, "pt": 0, "ct": 0, "cost": 0.0, "lat": 0.0, "calls": 0})
    for x in ok:
        if x["paper_id"] and x["task"] in EXTRACTION_TASKS:
            p = pp[x["paper_id"]]
            p["pt"] += x["prompt_tokens"] or 0; p["ct"] += x["completion_tokens"] or 0
            p["cost"] += priced(x) or 0; p["lat"] += x["latency_ms"] or 0; p["calls"] += 1
    n = len(pp)
    avg = lambda k: (sum(v[k] for v in pp.values()) / n) if n else 0
    avg_pt, avg_ct, avg_cost, avg_lat_s = avg("pt"), avg("ct"), avg("cost"), avg("lat") / 1000
    manual_min = st["manual_review_minutes"]
    manual_cost = manual_min / 60 * st["hourly_rate_usd"]
    per_paper = {"papers_measured": n, "avg_prompt_tokens": round(avg_pt), "avg_completion_tokens": round(avg_ct),
                 "avg_total_tokens": round(avg_pt + avg_ct), "avg_llm_cost_usd": round(avg_cost, 6),
                 "avg_llm_latency_s": round(avg_lat_s, 1), "avg_calls": round(avg("calls"), 1),
                 "manual_review_minutes": manual_min, "manual_cost_usd": round(manual_cost, 2),
                 "savings_per_paper_usd": round(manual_cost - avg_cost, 2) if n else None,
                 "cost_ratio_x": round(manual_cost / avg_cost) if n and avg_cost > 0 else None,
                 "minutes_saved_per_paper": round(manual_min - avg_lat_s / 60, 1) if n else None}
    ppm = st["papers_per_month"]
    monthly = {"papers_per_month": ppm, "llm_cost_usd": round(avg_cost * ppm, 2), "tokens": round((avg_pt + avg_ct) * ppm),
               "manual_cost_usd": round(manual_cost * ppm), "net_savings_usd": round((manual_cost - avg_cost) * ppm) if n else None,
               "hours_saved": round(ppm * (manual_min * 60 - avg_lat_s) / 3600) if n else None}

    # ---- fallback tax: what the resilience strategy costs in time and money
    m_ = gateway.models()
    fb_ok = [x for x in ok if x["role"] == "fallback"]
    primary_price = pr.get(m_["primary"]) or price_of(m_["primary"])
    fb_actual = sum(priced(x) or 0 for x in fb_ok)
    hyp = sum((cost_usd(m_["primary"], x["prompt_tokens"], x["completion_tokens"], primary_price) or 0) for x in fb_ok) \
        if primary_price["in"] is not None else None
    failed_primary = [x for x in calls if x["role"] == "primary" and x["status"] == "error"]
    fallback_tax = {"fallback_calls": len(fb_ok), "share_of_calls": round(len(fb_ok) / len(ok), 3) if ok else 0.0,
                    "fallback_tokens": sum((x["prompt_tokens"] or 0) + (x["completion_tokens"] or 0) for x in fb_ok),
                    "fallback_cost_usd": round(fb_actual, 6),
                    "cost_if_primary_had_served_usd": round(hyp, 6) if hyp is not None else None,
                    "cost_delta_usd": round(fb_actual - hyp, 6) if hyp is not None else None,
                    "primary_price_known": primary_price["in"] is not None,
                    "failed_primary_attempts": len(failed_primary),
                    "latency_wasted_on_failed_primary_ms": round(sum(x["latency_ms"] or 0 for x in failed_primary)),
                    "primary_calls_skipped_by_circuit": sum(1 for x in calls if x["role"] == "primary" and x["status"] == "skipped")}

    # ---- quality vs cost vs speed, per engine that actually produced extractions
    q = defaultdict(lambda: {"papers": 0, "ground": 0.0, "verified": 0.0, "coverage": 0.0, "lat": 0.0, "cost": 0.0})
    for r in ins:
        try:
            d = json.loads(r["data"])
        except Exception:
            continue
        label = d.get("model") if d.get("mode") == "llm" and d.get("model") else "extractive (no LLM)"
        det = list((d.get("details") or {}).values())
        with_val = [x for x in det if x.get("value")]
        e = q[label]
        e["papers"] += 1
        e["ground"] += (d.get("guardrail") or {}).get("grounding_rate", 0)
        e["verified"] += (sum(1 for x in with_val if x.get("status") == "verified") / len(with_val)) if with_val else 0
        e["coverage"] += len(with_val) / max(len(det), 1)
        e["lat"] += d.get("latency_ms") or 0
        e["cost"] += pp.get(r["paper_id"], {}).get("cost", 0.0)
    quality = sorted(({"engine": k, "papers": v["papers"], "avg_grounding": round(v["ground"] / v["papers"], 3),
                       "avg_verified_fields": round(v["verified"] / v["papers"], 3), "avg_field_coverage": round(v["coverage"] / v["papers"], 3),
                       "avg_latency_s": round(v["lat"] / v["papers"] / 1000, 1), "avg_cost_usd": round(v["cost"] / v["papers"], 6)}
                      for k, v in q.items()), key=lambda r: -r["papers"])

    # ---- what-if: same token volume, different model
    scen = []
    tps = {m["model"]: m["tokens_per_sec"] for m in models_out if m["tokens_per_sec"]}
    for model in _candidates(seen_models):
        p = pr.get(model) or price_of(model)
        if p["in"] is None:
            continue
        per_paper_cost = (avg_pt * p["in"] + avg_ct * p["out"]) / 1e6 if n else None
        scen.append({"model": model, "price_in": p["in"], "price_out": p["out"], "price_source": p["source"],
                     "cost_per_paper_usd": round(per_paper_cost, 6) if per_paper_cost is not None else None,
                     "monthly_cost_usd": round(per_paper_cost * ppm, 2) if per_paper_cost is not None else None,
                     "est_latency_s_per_paper": round(avg_ct / tps[model], 1) if n and model in tps else None,
                     "observed": model in seen_models, "role": gateway.role_of(model)})
    scen.sort(key=lambda r: (r["cost_per_paper_usd"] is None, r["cost_per_paper_usd"] or 0))

    # ---- daily budget
    start_of_day = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
    used = sum((x["prompt_tokens"] or 0) + (x["completion_tokens"] or 0) for x in ok if x["ts"] >= start_of_day)
    budget = {"daily_limit": st["daily_token_budget"], "used_today": used, "pct": round(used / st["daily_token_budget"] * 100, 1)}

    warnings = []
    unpriced |= {m for m in seen_models if (pr.get(m) or price_of(m))["in"] is None}
    if unpriced:
        warnings.append(f"No price known for: {', '.join(sorted(gateway.short(m) for m in unpriced))} - its cost is counted as $0 and cost comparisons "
                        "involving it are unavailable. Set a custom price below.")
    if not ok:
        warnings.append("No successful LLM calls in this window yet - ingest or re-extract a paper, or use Models -> Test full chain.")
    if n == 0 and ok:
        warnings.append("No paper-level calls recorded in this window (extractions run before this feature are not attributed to papers).")
    return {"window_days": days, "settings": st, "totals": totals, "by_model": models_out, "by_task": by_task, "daily": daily,
            "per_paper": per_paper, "monthly": monthly, "fallback_tax": fallback_tax, "quality_tradeoff": quality,
            "scenarios": scen, "budget": budget, "prices": [{"model": m, **p} for m, p in pr.items() if p["in"] is not None or m in seen_models],
            "warnings": warnings}
