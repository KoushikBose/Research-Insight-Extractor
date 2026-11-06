"""LiteLLM gateway + fallback tests (no network, no real key):  python tests/test_gateway.py
Uses LiteLLM's built-in mock_response to simulate a failing primary and a healthy fallback."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "g.db")
os.environ["GROQ_API_KEY"] = "test-key-not-real"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LLM_FAIL_THRESHOLD"] = "2"

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import extractor, gateway, research_agent  # noqa: E402

P, F = "groq/llama-3.2-test-primary", "groq/openai/gpt-oss-120b"
RESULTS = []


def check(name, cond, info=""):
    RESULTS.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


def rows(sql, *a):
    with db.db() as c:
        return [dict(r) for r in c.execute(sql, a)]


with TestClient(app) as client:        # starts lifespan (init_db, view creation, workers)
    gateway.set_models(P, F)
    gateway.reset_circuit()
    gateway.TEST_PARAMS[P] = {"mock_response": "litellm.RateLimitError"}
    gateway.TEST_PARAMS[F] = {"mock_response": "FALLBACK_OK"}

    check("configured models: primary Llama, fallback gpt-oss-120b", gateway.models() == {"primary": P, "fallback": F})
    check("default fallback is groq/openai/gpt-oss-120b", F == "groq/openai/gpt-oss-120b")

    check("classify: wrapped 401 -> auth, retired model -> model_not_found",
          gateway.classify(Exception('GroqException - {"error":{"message":"Invalid API Key"}}')) == "auth"
          and gateway.classify(Exception("The model `llama-3.2-x` has been decommissioned")) == "model_not_found")

    # 1) primary fails -> fallback answers inside the same request
    r = gateway.chat("sys", "hello", task="t1")
    check("fallback answers when primary rate-limited", r["text"] == "FALLBACK_OK" and r["role"] == "fallback" and r["fallback_used"], r["attempts"])
    log = rows("SELECT role,status,error_type,fallback_from FROM llm_calls WHERE task='t1' ORDER BY id")
    check("both attempts logged (primary error + fallback ok)", [(x["role"], x["status"]) for x in log] == [("primary", "error"), ("fallback", "ok")]
          and log[0]["error_type"] == "rate_limit" and log[1]["fallback_from"] == P, log)
    v = rows("SELECT * FROM v_llm_fallbacks WHERE task='t1'")
    check("SQL view v_llm_fallbacks has the event with reason", len(v) == 1 and v[0]["reason_type"] == "rate_limit"
          and v[0]["primary_model"] == P and v[0]["fallback_model"] == F and v[0]["trigger"] == "primary call failed", v)

    # 2) circuit breaker opens after threshold failures
    gateway.chat("sys", "again", task="t2")           # 2nd consecutive failure -> circuit opens
    check("circuit opens after 2 consecutive primary failures", gateway.circuit_open_for() > 0, gateway.circuit_open_for())
    r = gateway.chat("sys", "third", task="t3")
    log = rows("SELECT role,status,error_type FROM llm_calls WHERE task='t3' ORDER BY id")
    check("while open, primary is skipped (no wasted call) and fallback serves", r["fallback_used"] and (log[0]["role"], log[0]["status"], log[0]["error_type"]) == ("primary", "skipped", "cooldown"), log)
    v = rows("SELECT trigger FROM v_llm_fallbacks WHERE task='t3'")
    check("view marks the trigger as 'circuit open'", v and v[0]["trigger"].startswith("circuit open"), v)

    # 3) status for the UI
    st = client.get("/api/llm/status").json()
    check("status: primary in cooldown, fallback healthy", st["primary"]["state"] == "cooldown" and st["fallback"]["state"] == "healthy", (st["primary"]["state"], st["fallback"]["state"]))
    check("status: fallback events + rate + per-model stats", st["fallback_events_total"] >= 3 and st["stats_24h"]["fallback_rate"] > 0
          and {x["role"] for x in st["stats_24h"]["by_model"]} >= {"primary", "fallback"} and st["currently_serving"]["role"] == "fallback")
    check("status: gateway is litellm", st["gateway"]["type"] == "litellm" and st["gateway"]["version"])

    # 4) recovery: cooldown expires, primary is probed and takes over again
    gateway._state[P]["cool_until"] = time.time() - 1
    gateway.TEST_PARAMS[P] = {"mock_response": "PRIMARY_OK"}
    before = len(rows("SELECT id FROM v_llm_fallbacks"))
    r = gateway.chat("sys", "recover", task="t4")
    check("primary recovers after cooldown (probe succeeds) and serves again", r["role"] == "primary" and r["text"] == "PRIMARY_OK" and not r["fallback_used"])
    check("no new fallback event after recovery", len(rows("SELECT id FROM v_llm_fallbacks")) == before)
    check("status shows primary healthy again", client.get("/api/llm/status").json()["primary"]["state"] == "healthy")

    # 5) simulated outage switch
    check("simulate-outage endpoint on", client.post("/api/llm/simulate-outage", json={"on": True}).json()["simulated_primary_outage"])
    r = gateway.chat("sys", "outage", task="t5")
    log = rows("SELECT error_type FROM llm_calls WHERE task='t5' AND role='primary'")
    check("simulated outage forces fallback, reason=simulated", r["fallback_used"] and log[0]["error_type"] == "simulated", log)
    client.post("/api/llm/simulate-outage", json={"on": False})
    r = gateway.chat("sys", "back", task="t6")
    check("outage switch off -> primary again", r["role"] == "primary")

    # 6) every model failing
    gateway.TEST_PARAMS[P] = {"mock_response": "litellm.RateLimitError"}
    gateway.TEST_PARAMS[F] = {"mock_response": "litellm.InternalServerError"}
    gateway.reset_circuit()
    try:
        gateway.chat("sys", "doom", task="t7")
        check("GatewayError when both models fail", False)
    except gateway.GatewayError as e:
        check("GatewayError when both models fail (2 attempts reported)", len(e.attempts) == 2, str(e)[:120])

    # 7) health-check endpoint & single-model tests
    gateway.reset_circuit()
    gateway.TEST_PARAMS[P] = {"mock_response": "litellm.RateLimitError"}
    gateway.TEST_PARAMS[F] = {"mock_response": "FALLBACK_OK"}
    t = client.post("/api/llm/test", json={"target": "chain"}).json()
    check("/api/llm/test chain -> fallback_used", t["ok"] and t["fallback_used"], t)
    t = client.post("/api/llm/test", json={"target": "primary"}).json()
    check("/api/llm/test primary only -> reports failure, no fallback", (not t["ok"]) and len(t["attempts"]) == 1, t)
    t = client.post("/api/llm/test", json={"target": "fallback"}).json()
    check("/api/llm/test fallback only -> ok", t["ok"] and t["model"] == F, t)
    check("config validation rejects bad model id", client.put("/api/llm/config", json={"fallback": "bad id; drop"}).status_code == 400)
    check("/api/llm/fallbacks lists view rows", len(client.get("/api/llm/fallbacks").json()) >= 3)

    # 8) extractor integration: LLM engine served by the fallback is flagged
    gateway.reset_circuit()
    gateway.TEST_PARAMS[F] = {"mock_response": '{"overall":"O","sections":{"Abstract":"s"},"fields":{"objective":{"value":"aim","evidence":"The objective of this study"}},"keywords":["ELISA"]}'}
    secs = [{"name": "Abstract", "text": "The objective of this study was to test X in 10 mice."}, {"name": "Methods", "text": "ELISA was used."}]
    res = extractor.extract_from_sections(secs, [], use_llm=True)
    check("extraction runs on LLM engine via fallback and reports it", res["mode"] == "llm" and res["fallback_used"] and res["model"] == F, (res["mode"], res["model"]))
    tasks = {x["task"] for x in rows("SELECT DISTINCT task FROM llm_calls")}
    check("tasks are labelled in the log", {"summarize_sections", "extract_details"} <= tasks, tasks)

    # 9) Deep Agent: LangChain ModelFallbackMiddleware switches models, calls logged
    gateway.reset_circuit()
    gateway.TEST_PARAMS[P] = {"mock_response": "litellm.RateLimitError"}
    gateway.TEST_PARAMS[F] = {"mock_response": "AGENT_FALLBACK_OK"}
    try:
        text, model, fb = research_agent._run_deep_agent("what dose was used?")
        check("deep agent answers via fallback model", "AGENT_FALLBACK_OK" in text and model == F and fb, (text[:60], model, fb))
        v = rows("SELECT * FROM v_llm_fallbacks WHERE task='assistant'")
        check("deep-agent fallback appears in the SQL view", len(v) >= 1 and v[0]["fallback_model"] == F, v[:1])
    except Exception as e:
        check("deep agent fallback", False, repr(e)[:300])

failed = RESULTS.count(False)
print(f"\n{len(RESULTS) - failed}/{len(RESULTS)} checks passed")
sys.exit(1 if failed else 0)
