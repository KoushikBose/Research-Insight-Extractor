"""LiteLLM gateway: one place for every LLM call, with a primary -> fallback strategy.

    primary  : Groq Qwen3 (27B)        (LLM_PRIMARY_MODEL, default groq/<GROQ_MODEL> = groq/qwen/qwen3.8-27b)
    fallback : Groq gpt-oss-120b       (LLM_FALLBACK_MODEL, default groq/openai/gpt-oss-120b)

Strategy
  * every request tries the primary first; ANY failure (rate limit, retired model, auth, timeout, 5xx, ...) moves
    on to the fallback within the same request, so callers never see the primary's outage;
  * circuit breaker: after LLM_FAIL_THRESHOLD consecutive primary failures the primary is skipped for
    LLM_COOLDOWN_SECONDS (no more 90 s timeouts on a dead model); afterwards a single probe call re-tests it;
  * every attempt (ok / error / skipped) is written to `llm_calls`; the SQL view `v_llm_fallbacks` lists each time
    the fallback served a request together with the primary failure that triggered it;
  * the LangChain Deep Agent gets the same behaviour via `ModelFallbackMiddleware` + `LogHandler`.
Optionally set LITELLM_PROXY_URL to route calls through a standalone LiteLLM proxy (see litellm_config.yaml).
"""
import logging
import os
import re
import threading
import time

os.environ.setdefault("LITELLM_LOG", "ERROR")
os.environ.setdefault("LITELLM_TELEMETRY", "False")
import litellm  # noqa: E402
from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402

from .. import db as dbm  # noqa: E402
from ..config import settings  # noqa: E402
from . import tracing  # noqa: E402

litellm.drop_params = True            # silently drop params a given model does not support
litellm.suppress_debug_info = True
log = logging.getLogger(__name__)
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)

_lock = threading.Lock()
_state: dict = {}                     # model -> {fails, cool_until, last_error, last_error_type, last_ok, last_error_ts}
_force_primary_down = False           # demo / test switch (UI: "simulate primary outage")
RATE_LIMIT_COOLDOWN = 30.0           # seconds the primary is skipped after rate-limit errors (vs LLM_COOLDOWN_SECONDS for hard failures)
TEST_PARAMS: dict = {}                # tests only: model -> extra litellm kwargs (e.g. mock_response)


class GatewayError(RuntimeError):
    def __init__(self, msg, attempts):
        super().__init__(msg)
        self.attempts = attempts


# ------------------------------------------------------------------ configuration
def models() -> dict:
    try:
        ov = dbm.get_setting("llm_models", {}) or {}
    except Exception:
        ov = {}
    primary = ov.get("primary") or settings.LLM_PRIMARY_MODEL or f"groq/{settings.GROQ_MODEL}"
    return {"primary": primary, "fallback": ov.get("fallback") or settings.LLM_FALLBACK_MODEL}


def set_models(primary: str | None = None, fallback: str | None = None) -> dict:
    cur = dbm.get_setting("llm_models", {}) or {}
    if primary:
        cur["primary"] = primary
    if fallback:
        cur["fallback"] = fallback
    dbm.set_setting("llm_models", cur)
    return models()


def available() -> bool:
    return bool(settings.GROQ_API_KEY or settings.LITELLM_PROXY_URL)


def role_of(model: str | None) -> str:
    m = models()
    return "primary" if model == m["primary"] else "fallback" if model == m["fallback"] else "other"


def short(model: str | None) -> str:
    return (model or "").split("/", 1)[-1] if (model or "").startswith("groq/") else (model or "")


def _call_params(model: str, role: str) -> dict:
    p = {"model": model, "temperature": 0, "timeout": 90, "num_retries": 0 if role == "primary" else 1}
    if settings.LITELLM_PROXY_URL:                      # route through the standalone gateway
        p.update(model="openai/" + short(model), api_base=settings.LITELLM_PROXY_URL,
                 api_key=settings.LITELLM_PROXY_KEY or "sk-anything")
    elif model.startswith("groq/"):
        p["api_key"] = settings.GROQ_API_KEY
    if "gpt-oss" in model:
        p["reasoning_effort"] = "low"                    # keep the reasoning model fast & terse for extraction
    p.update(TEST_PARAMS.get(model, {}))
    return p


# ------------------------------------------------------------------ circuit breaker
def _circuit_remaining(model: str) -> float:
    with _lock:
        st = _state.get(model)
        if not st or not st.get("cool_until"):
            return 0.0
        left = st["cool_until"] - time.time()
        if left > 0:
            return left
        st["cool_until"] = 0.0                           # half-open: allow exactly one probe, re-open on 1 more failure
        st["fails"] = max(settings.LLM_FAIL_THRESHOLD - 1, 0)
        return 0.0


def _record_ok(model):
    with _lock:
        st = _state.setdefault(model, {})
        st.update(fails=0, cool_until=0.0, last_ok=time.time())


def _record_fail(model, role, etype, err):
    with _lock:
        st = _state.setdefault(model, {})
        st["fails"] = st.get("fails", 0) + 1
        st.update(last_error=str(err)[:300], last_error_type=etype, last_error_ts=time.time())
        if role == "primary" and st["fails"] >= settings.LLM_FAIL_THRESHOLD:
            # a 429 clears in seconds; a retired / broken model needs the long cooldown
            cool = min(settings.LLM_COOLDOWN_SECONDS, RATE_LIMIT_COOLDOWN) if etype == "rate_limit" else settings.LLM_COOLDOWN_SECONDS
            st["cool_until"] = time.time() + cool


def reset_circuit():
    with _lock:
        _state.clear()


def circuit_open_for(role="primary") -> float:
    return _circuit_remaining(models()[role])


def set_primary_outage(on: bool):
    global _force_primary_down
    _force_primary_down = bool(on)
    if not on:
        reset_circuit()
    return _force_primary_down


def primary_outage_simulated() -> bool:
    return _force_primary_down


def classify(exc: Exception) -> str:
    text = str(exc).lower()
    if "invalid api key" in text or "invalid_api_key" in text or "incorrect api key" in text:
        return "auth"                                   # providers often wrap a 401 in a generic BadRequestError
    if "decommissioned" in text or "model_not_found" in text or "does not exist" in text:
        return "model_not_found"
    for name, label in (("RateLimitError", "rate_limit"), ("AuthenticationError", "auth"), ("NotFoundError", "model_not_found"),
                        ("Timeout", "timeout"), ("APIConnectionError", "connection"), ("ServiceUnavailableError", "server_error"),
                        ("InternalServerError", "server_error"), ("ContextWindowExceededError", "context_length"),
                        ("BadRequestError", "bad_request")):
        cls = getattr(litellm, name, None)
        if cls and isinstance(exc, cls):
            return label
    return "simulated" if "simulated" in str(exc).lower() else "other"


# ------------------------------------------------------------------ logging
def log_call(task, role, model, status, error_type=None, error=None, latency_ms=None, pt=None, ct=None,
             fallback_from=None, paper_id=None):
    try:
        with dbm.db() as c:
            c.execute("INSERT INTO llm_calls(ts,task,role,model,status,error_type,error,latency_ms,prompt_tokens,"
                      "completion_tokens,fallback_from,paper_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (time.time(), task, role, model, status, error_type, (error or "")[:500], latency_ms, pt, ct,
                       fallback_from, paper_id))
    except Exception as e:  # observability must never break a request
        log.warning("could not log llm call: %s", e)


# ------------------------------------------------------------------ direct completions
@tracing.traceable(name="litellm_completion", run_type="llm", process_inputs=lambda i: {"model": i.get("model"), "role": i.get("role")})
def _complete(model: str, messages: list, role: str):
    return litellm.completion(messages=messages, **_call_params(model, role))


def chat(system: str, user: str, task: str = "llm", paper_id: int | None = None, only: str | None = None) -> dict:
    """Run a chat completion through the primary -> fallback chain.
    Returns {text, model, role, fallback_used, attempts}. Raises GatewayError if every model failed.
    `only` ('primary'|'fallback') tests a single model without fallback (UI health checks)."""
    m = models()
    chain = [(r, m[r]) for r in ("primary", "fallback") if only in (None, r)]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    attempts = []
    for role, model in chain:
        fb_from = m["primary"] if role == "fallback" else None
        if role == "primary" and only is None:
            left = _circuit_remaining(model)
            if left > 0:
                msg = f"circuit open: {int(left)}s of cooldown left after repeated failures"
                log_call(task, role, model, "skipped", "cooldown", msg, paper_id=paper_id)
                attempts.append({"model": model, "role": role, "status": "skipped", "error": msg})
                continue
        t0 = time.time()
        try:
            if role == "primary" and _force_primary_down:
                raise RuntimeError("simulated primary outage (test mode)")
            resp = _complete(model, messages, role)
            text = _THINK.sub("", resp.choices[0].message.content or "").strip()    # reasoning models may inline <think> blocks
            usage = getattr(resp, "usage", None)
            _record_ok(model)
            log_call(task, role, model, "ok", latency_ms=(time.time() - t0) * 1000, fallback_from=fb_from,
                     pt=getattr(usage, "prompt_tokens", None), ct=getattr(usage, "completion_tokens", None), paper_id=paper_id)
            attempts.append({"model": model, "role": role, "status": "ok"})
            if role == "fallback":
                log.warning("LLM fallback in use for task=%s: %s answered instead of %s", task, model, m["primary"])
            return {"text": text, "model": model, "role": role, "fallback_used": role == "fallback", "attempts": attempts}
        except Exception as e:
            et = classify(e)
            _record_fail(model, role, et, e)
            log_call(task, role, model, "error", et, str(e), (time.time() - t0) * 1000, fallback_from=fb_from, paper_id=paper_id)
            attempts.append({"model": model, "role": role, "status": "error", "error_type": et, "error": str(e)[:200]})
    raise GatewayError("All models failed: " + "; ".join(f"{short(a['model'])}: {a.get('error_type') or a['status']}" for a in attempts), attempts)


# ------------------------------------------------------------------ LangChain (Deep Agent) integration
def _lc_model(model: str, role: str):
    from langchain_litellm import ChatLiteLLM
    p = _call_params(model, role)
    extra = {k: v for k, v in p.items() if k not in ("model", "temperature", "timeout", "num_retries", "api_key", "api_base")}
    if role == "primary" and _force_primary_down:       # demo switch on the agent path (LiteLLM-native simulated failure)
        extra["mock_response"] = "litellm.InternalServerError"
    return ChatLiteLLM(model=p["model"], temperature=0, api_key=p.get("api_key"), api_base=p.get("api_base"),
                       request_timeout=p["timeout"], max_retries=p["num_retries"], model_kwargs=extra)


def agent_models():
    """(first, second, primary_skipped). Honours the circuit breaker so a dead primary is not tried first."""
    m = models()
    primary_model = _lc_model(m["primary"], "primary")
    fallback_model = _lc_model(m["fallback"], "fallback")
    if _circuit_remaining(m["primary"]) > 0:
        return fallback_model, None, True
    return primary_model, fallback_model, False


class LogHandler(BaseCallbackHandler):
    """Logs every LLM call made inside a LangChain / Deep Agent run into llm_calls and the circuit breaker."""
    raise_error = False

    def __init__(self, task="assistant", paper_id=None):
        self.task, self.paper_id, self.runs = task, paper_id, {}
        self.last_model, self.fallback_used, self.calls = None, False, []

    def on_chat_model_start(self, serialized, messages, *, run_id, invocation_params=None, metadata=None, **kw):
        model = (invocation_params or {}).get("model") or (metadata or {}).get("ls_model_name")
        self.runs[run_id] = (model, time.time())

    on_llm_start = lambda self, serialized, prompts, *, run_id, invocation_params=None, metadata=None, **kw: self.on_chat_model_start(  # noqa: E731
        serialized, prompts, run_id=run_id, invocation_params=invocation_params, metadata=metadata)

    def on_llm_end(self, response, *, run_id, **kw):
        model, t0 = self.runs.pop(run_id, (None, time.time()))
        role = role_of(model)
        usage = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
        _record_ok(model) if model else None
        log_call(self.task, role, model, "ok", latency_ms=(time.time() - t0) * 1000,
                 fallback_from=models()["primary"] if role == "fallback" else None, paper_id=self.paper_id,
                 pt=usage.get("prompt_tokens"), ct=usage.get("completion_tokens"))
        self.last_model = model
        self.fallback_used = self.fallback_used or role == "fallback"
        self.calls.append((model, role, "ok"))

    def on_llm_error(self, error, *, run_id, **kw):
        model, t0 = self.runs.pop(run_id, (None, time.time()))
        role, et = role_of(model), classify(error)
        if model:
            _record_fail(model, role, et, error)
        log_call(self.task, role, model, "error", et, str(error), (time.time() - t0) * 1000,
                 fallback_from=models()["primary"] if role == "fallback" else None, paper_id=self.paper_id)
        self.calls.append((model, role, "error"))


# ------------------------------------------------------------------ status for the UI
def status() -> dict:
    m = models()
    now = time.time()

    def card(role):
        model = m[role]
        with _lock:
            st = dict(_state.get(model, {}))
        left = max((st.get("cool_until") or 0) - now, 0)
        if role == "primary" and _force_primary_down:
            state = "outage (simulated)"
        elif left > 0:
            state = "cooldown"
        elif st.get("fails", 0) > 0:
            state = "degraded"
        elif st.get("last_ok"):
            state = "healthy"
        else:
            state = "unknown"
        return {"role": role, "model": model, "label": short(model), "state": state, "consecutive_failures": st.get("fails", 0),
                "cooldown_left_s": round(left), "last_ok": st.get("last_ok"), "last_error": st.get("last_error"),
                "last_error_type": st.get("last_error_type")}

    with dbm.db() as c:
        by_model = [dict(r) for r in c.execute(
            "SELECT model, role, COUNT(*) AS calls, SUM(status='ok') AS ok, SUM(status='error') AS errors, "
            "SUM(status='skipped') AS skipped, ROUND(AVG(CASE WHEN status='ok' THEN latency_ms END),0) AS avg_latency_ms, "
            "COALESCE(SUM(prompt_tokens),0)+COALESCE(SUM(completion_tokens),0) AS tokens "
            "FROM llm_calls WHERE ts >= ? GROUP BY model, role ORDER BY calls DESC", (now - 86400,))]
        served = c.execute("SELECT COUNT(*) n, SUM(role='fallback') fb FROM llm_calls WHERE status='ok' AND ts >= ?",
                           (now - 86400,)).fetchone()
        fallbacks = [dict(r) for r in c.execute("SELECT * FROM v_llm_fallbacks ORDER BY id DESC LIMIT 25")]
        recent = [dict(r) for r in c.execute("SELECT * FROM llm_calls ORDER BY id DESC LIMIT 20")]
        last_ok = c.execute("SELECT model, role, ts FROM llm_calls WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
        n_fb_total = c.execute("SELECT COUNT(*) n FROM v_llm_fallbacks").fetchone()["n"]
    n = served["n"] or 0
    return {
        "gateway": {"type": "litellm", "version": _litellm_version(),
                    "mode": "proxy" if settings.LITELLM_PROXY_URL else "in-process", "proxy_url": settings.LITELLM_PROXY_URL or None,
                    "llm_enabled": available(), "cooldown_seconds": settings.LLM_COOLDOWN_SECONDS,
                    "fail_threshold": settings.LLM_FAIL_THRESHOLD},
        "primary": card("primary"), "fallback": card("fallback"),
        "currently_serving": dict(last_ok) if last_ok else None,
        "simulated_primary_outage": _force_primary_down,
        "stats_24h": {"served_calls": n, "served_by_fallback": served["fb"] or 0,
                      "fallback_rate": round((served["fb"] or 0) / n, 3) if n else 0.0, "by_model": by_model},
        "fallback_events_total": n_fb_total, "fallback_events": fallbacks, "recent_calls": recent,
    }


def _litellm_version():
    try:
        import importlib.metadata as md
        return md.version("litellm")
    except Exception:
        return None
