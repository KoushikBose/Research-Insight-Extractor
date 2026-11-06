"""LangSmith tracing.

* LangChain / Deep Agent / ChatGroq calls are traced automatically once LANGSMITH_TRACING=true.
* Pipeline entry points (extraction, assistant) are wrapped with @traceable so each paper / question is ONE
  trace with the LLM + tool calls nested underneath.
* Privacy: confidential papers never reach the LLM (so nothing is traced from them); pipeline inputs are
  logged as metadata only, user questions are PII-redacted, and LANGSMITH_HIDE_INPUTS/OUTPUTS=true hides
  prompts and completions entirely.
"""
import logging
import os

from .. import config  # noqa: F401  (loads .env into os.environ before LangSmith reads it)

log = logging.getLogger(__name__)


def _setup() -> bool:
    # tolerate the common typo LANGSMIT_API_KEY
    key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMIT_API_KEY")
    if key:
        os.environ["LANGSMITH_API_KEY"] = key
        os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_PROJECT", "research-insight-extractor")
    on = bool(key) and os.getenv("LANGSMITH_TRACING", "").lower() in ("1", "true", "yes")
    if not on:
        os.environ["LANGSMITH_TRACING"] = "false"
    return on


ENABLED = _setup()

try:
    from langsmith import traceable as _traceable
    from langsmith import get_current_run_tree
except Exception:  # langsmith not installed -> no-op decorator
    _traceable = None
    get_current_run_tree = lambda: None  # noqa: E731
    ENABLED = False


def traceable(**kw):
    if _traceable is None:
        return lambda f: f
    return _traceable(**kw)


def add_metadata(**meta):
    """Attach metadata to the current trace (no-op when tracing is off)."""
    try:
        rt = get_current_run_tree()
        if rt is not None:
            rt.add_metadata(meta)
    except Exception:  # never let observability break the app
        pass


def status() -> dict:
    return {"enabled": ENABLED, "project": os.getenv("LANGSMITH_PROJECT") if ENABLED else None}
