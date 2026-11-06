from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db, guardrails
from .config import settings
from .routers import assistant, papers, platform
from .services import gateway, ingest, jobs, llm, monitor, tasks, tracing  # noqa: F401  (tasks registers job handlers)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    guardrails.load_from_db()
    ingest.backfill()
    jobs.start(workers=2)
    monitor.start()
    yield
    monitor.stop()
    jobs.stop()


app = FastAPI(title="Life Sciences Research Insight Extractor", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.include_router(papers.router)
app.include_router(assistant.router)
app.include_router(platform.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_enabled": llm.llm_available(),
            "model": settings.GROQ_MODEL if llm.llm_available() else None,
            "mode": "groq-llm" if llm.llm_available() else "extractive-offline",
            "models": gateway.models(), "gateway": "litellm", "tracing": tracing.status()}
