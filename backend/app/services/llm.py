"""Thin LLM facade. All calls go through the LiteLLM gateway (primary -> fallback, see gateway.py)."""
import json
import re

from ..config import settings  # noqa: F401  (re-exported for callers)
from . import gateway


def llm_available() -> bool:
    return gateway.available()


def invoke(system: str, user: str, task: str = "llm", paper_id: int | None = None) -> tuple[str, str]:
    """Returns (text, model_used). Falls back automatically; raises gateway.GatewayError if every model failed."""
    r = gateway.chat(system, user, task=task, paper_id=paper_id)
    return r["text"], r["model"]


def parse_json(text: str):
    if not text:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1:
        return None
    try:
        return json.loads(text[s:e + 1])
    except json.JSONDecodeError:
        return None


def complete_json(system: str, user: str, task: str = "llm", paper_id: int | None = None):
    text, model = invoke(system, user, task, paper_id)
    data = parse_json(text)
    if data is None:  # one repair attempt
        text, model = invoke(system, user + "\n\nReturn ONLY valid minified JSON. No prose.", task, paper_id)
        data = parse_json(text)
    return data, model
