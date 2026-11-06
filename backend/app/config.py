import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    # --- LiteLLM gateway: primary -> fallback strategy (LiteLLM "provider/model" ids) ---
    LLM_PRIMARY_MODEL = os.getenv("LLM_PRIMARY_MODEL", "")      # default: groq/<GROQ_MODEL>
    LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "groq/openai/gpt-oss-120b")
    LLM_COOLDOWN_SECONDS = float(os.getenv("LLM_COOLDOWN_SECONDS", "300"))   # circuit-breaker open time
    LLM_FAIL_THRESHOLD = int(os.getenv("LLM_FAIL_THRESHOLD", "2"))           # consecutive failures before opening
    LITELLM_PROXY_URL = os.getenv("LITELLM_PROXY_URL", "")      # optional: route through a standalone LiteLLM proxy
    LITELLM_PROXY_KEY = os.getenv("LITELLM_PROXY_KEY", "")
    NCBI_EMAIL = os.getenv("NCBI_EMAIL", "")
    NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
    DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "app.db"))
    INTERNAL_REPO_DIR = Path(os.getenv("INTERNAL_REPO_DIR", str(BASE_DIR / "data" / "internal_repo")))
    CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")]
    # Baseline used to estimate review-time reduction (minutes a researcher spends per paper manually)
    MANUAL_REVIEW_MINUTES = float(os.getenv("MANUAL_REVIEW_MINUTES", "20"))


settings = Settings()
