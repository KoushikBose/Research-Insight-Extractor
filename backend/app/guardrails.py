"""Guardrails for the research assistant.

Input side   : upload validation, prompt-injection scan/neutralisation, PII redaction,
               query policy (scope + patient-specific medical advice), confidentiality routing.
Output side  : evidence grounding, numeric consistency, quote-length (copyright) cap,
               citation requirement, medical disclaimer.
Every switch can be toggled at runtime via /api/guardrails (persisted in SQLite).
"""
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

DEFAULTS = {
    "upload_validation": True,
    "prompt_injection": True,
    "pii_redaction": True,
    "query_policy": True,
    "medical_advice_block": True,
    "confidential_local_only": True,   # confidential papers never leave the host (no Groq call)
    "grounding_check": True,
    "numeric_check": True,
    "quote_limit": True,              # copyright: cap verbatim quotes
    "citation_required": True,
    "medical_disclaimer": True,
    "max_upload_mb": 15,
    "max_quote_words": 40,
    "max_query_chars": 1500,
}
DESCRIPTIONS = {
    "upload_validation": "Only PDF/XML/TXT, size-limited, magic-byte sanity check.",
    "prompt_injection": "Detect & neutralise instructions hidden inside papers or user queries.",
    "pii_redaction": "Redact e-mails / phone numbers / IDs before text is sent to the LLM or logged.",
    "query_policy": "Reject empty, oversized or off-scope queries.",
    "medical_advice_block": "Refuse patient-specific diagnosis / dosing advice (research tool only).",
    "confidential_local_only": "Papers flagged confidential are processed locally with the extractive engine.",
    "grounding_check": "Every extracted fact must carry a verbatim evidence quote found in the source.",
    "numeric_check": "Numbers in extracted values must appear in the source text.",
    "quote_limit": "Cap verbatim quotes to respect publisher copyright / licence terms.",
    "citation_required": "Chat answers must cite [paper:ID/Section]; uncited answers are flagged.",
    "medical_disclaimer": "Append a research-use-only disclaimer to chat answers.",
}

_cfg = dict(DEFAULTS)


def get_config():
    return dict(_cfg)


def load_from_db():
    from . import db as dbm
    saved = dbm.get_setting("guardrails", {})
    _cfg.update({k: v for k, v in saved.items() if k in DEFAULTS})


def update_config(patch: dict):
    from . import db as dbm
    for k, v in patch.items():
        if k in DEFAULTS and type(v) is type(DEFAULTS[k]):
            _cfg[k] = v
    dbm.set_setting("guardrails", _cfg)
    return get_config()


def reset_config():
    _cfg.clear()
    _cfg.update(DEFAULTS)


def on(name):
    return bool(_cfg.get(name))


# ----------------------------------------------------------------- input guardrails
ALLOWED_EXT = {".pdf", ".xml", ".txt", ".md"}


def check_upload(filename: str, data: bytes):
    """Returns (ok, reason)."""
    if not on("upload_validation"):
        return True, ""
    name = (filename or "").lower()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if ext not in ALLOWED_EXT:
        return False, f"File type '{ext or 'unknown'}' not allowed. Allowed: {sorted(ALLOWED_EXT)}"
    if len(data) > _cfg["max_upload_mb"] * 1024 * 1024:
        return False, f"File exceeds {_cfg['max_upload_mb']} MB limit"
    if not data:
        return False, "Empty file"
    if ext == ".pdf" and not data.lstrip()[:5] == b"%PDF-":
        return False, "File extension is .pdf but content is not a PDF"
    if ext == ".xml" and b"<" not in data[:2048]:
        return False, "File extension is .xml but content is not XML"
    return True, ""


INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|prompts?|rules)",
    r"disregard (all |any |the )?(previous|prior|above|earlier|system)",
    r"forget (everything|all|your) (above|instructions|rules)",
    r"you are now (a|an|in)\b",
    r"(reveal|show|print|repeat|leak) (me )?(your |the )?(system|hidden|initial) (prompt|instructions)",
    r"\bsystem prompt\b",
    r"act as (a|an) (?!researcher|reviewer)",
    r"do not (follow|obey) (the )?(above|previous|system)",
    r"<\s*/?\s*(system|assistant|instructions?)\s*>",
    r"\bjailbreak\b|\bDAN mode\b",
    r"override (your |the )?(safety|guardrails?|rules)",
    r"(send|post|exfiltrate|upload) .{0,40}(api[_ ]?key|password|secret|token)",
]
_INJ = [re.compile(p, re.I) for p in INJECTION_PATTERNS]


def scan_injection(text: str):
    hits = []
    for rx in _INJ:
        m = rx.search(text or "")
        if m:
            hits.append(m.group(0)[:80])
    return hits


def sanitize_document(text: str):
    """Neutralise injection lines inside an *untrusted paper*. Returns (clean_text, findings)."""
    if not on("prompt_injection"):
        return text, []
    findings, out = [], []
    for line in text.split("\n"):
        hits = scan_injection(line)
        if hits:
            findings.extend(hits)
            out.append("[REMOVED: possible instruction injection]")
        else:
            out.append(line)
    return "\n".join(out), findings


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_AADHAAR_SPACED = re.compile(r"(?<![\w+/-])[2-9]\d{3}[\s-]\d{4}[\s-]\d{4}(?!\d)")
_AADHAAR_BARE = re.compile(r"(?<![\w+.,/-])[2-9]\d{11}(?![\d.,]\d)")
_YEAR = re.compile(r"(?:19|20)\d\d$")

# ---- phone numbers -------------------------------------------------------------------------------------------
# Several layout-specific patterns (every country writes numbers differently) + a validation step, so that phone-like
# text - DOIs, dates, versions, decimals, page ranges, chart axes - is left alone. Anything written after
# "Phone:", "Mobile:", "Contact:" ... is also caught, whatever its layout.
_START = r"(?<![\w.+,/-])"                # not glued to a word, decimal, sign, list or URL/DOI path
_END = r"(?!\w|[.,]\d)"                   # not followed by a word char or by ".5" / ",5"
# international, written with + or 00 and any grouping:  +44 20 7946 0958 · +91 (98765) 43210 · 0091 9876543210 · +65-6123-4567
_P_INTL = re.compile(r"(?<![\w+./])(?:\+|00)\s?\d{1,3}(?:[\s.-]?\(?\d{1,5}\)?){2,6}" + _END)
# India mobile: 10 digits starting 6-9, optional 0 / 91 prefix, ANY grouping:  98765 43210 · 98 76 54 32 10 · 09876543210
_P_IN_MOBILE = re.compile(_START + r"(?:(?:0|91)[\s-]?)?[6-9](?:[\s-]?\d){9}" + _END)
# trunk-prefix numbers with separators (India STD, UK, EU):  033 2345 6789 · 020 7946 0958 · 07911 123456
_P_TRUNK = re.compile(_START + r"0\d{1,4}[\s-]\d{3,4}[\s-]?\d{3,4}" + _END)
# India toll-free:  1800 123 4567 · 1800-103-4567
_P_TOLLFREE = re.compile(_START + r"1800[\s-]?\d{3}[\s-]?\d{3,4}" + _END)
# North America:  (415) 555-0134 · 415.555.0134 · 415 555 0134 · 1-800-555-0199   (bare 10 digits only with a context word)
_P_NANP = re.compile(_START + r"(?:\+?1[\s.-]?)?\(?[2-9]\d{2}\)?[\s.-]?[2-9]\d{2}[\s.-]?\d{4}" + _END)
# context: whatever number-ish text follows tel / phone / mobile / call / contact / whatsapp / fax / hotline ...
_P_CONTEXT = re.compile(r"(?i)\b(?:tel(?:ephone)?|phone|mobile|mob|cell|call|contact|whats\s?app|fax|ph|hotline|helpline|toll[\s-]?free|landline|sms)\b"
                        r"\.?(?:\s*(?:no|number|num|#))?\.?(?:\s+(?:is|at|on))?\s*[:–-]?\s*((?:\+|00)?\(?\d[\d\s().-]{4,18}\d)")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _intl_ok(g: str) -> bool:
    g = g.strip()
    if g.startswith("00") and "." in g:          # "0047 0.0014 0.0001" is a table of decimals, not a 00-prefixed number
        return False
    d = _digits(g)
    d = d[2:] if g.startswith("00") else d
    return 8 <= len(d) <= 15


def _in_mobile_ok(g: str) -> bool:
    groups = [x for x in re.split(r"[\s-]+", g.strip()) if x]
    if len(groups) > 1 and groups[0] in ("0", "91"):
        groups = groups[1:]
    return len(groups) == 1 or all(len(x) >= 2 for x in groups)    # rejects chart axes like "6 7 8 9 10 11 12"


def _nanp_ok(m) -> bool:
    g = m.group(0).strip()
    if re.search(r"[\s.()-]", g) or g.startswith("+"):
        return True
    # bare 10 digits: fine on their own, but not right after another number ("146, 2247622484" = journal pages)
    return not re.search(r"\d[,;]?\s*$", m.string[max(0, m.start() - 12): m.start()])


def _redact_phones(text: str):
    n = 0

    def make(valid):
        def f(m):
            nonlocal n
            if valid(m):
                n += 1
                return "[PHONE]"
            return m.group(0)
        return f

    for rx, valid in ((_P_INTL, lambda m: _intl_ok(m.group(0))), (_P_IN_MOBILE, lambda m: _in_mobile_ok(m.group(0))),
                      (_P_TRUNK, lambda m: 10 <= len(_digits(m.group(0))) <= 11),
                      (_P_TOLLFREE, lambda m: 10 <= len(_digits(m.group(0))) <= 11), (_P_NANP, _nanp_ok)):
        text = rx.sub(make(valid), text)

    def ctx(m):
        nonlocal n
        num = m.group(1)
        if 7 <= len(_digits(num)) <= 15:
            n += 1
            return m.group(0)[: m.start(1) - m.start(0)] + "[PHONE]"
        return m.group(0)

    return _P_CONTEXT.sub(ctx, text), n


def _aadhaar_spaced(m):
    groups = re.split(r"[\s-]", m.group(0))
    return m.group(0) if all(_YEAR.match(g) for g in groups) else "[AADHAAR]"     # "2024 2025 2026" is not an ID


def redact_pii(text: str):
    if not on("pii_redaction") or not text:
        return text, 0
    n = 0
    text, k = _EMAIL.subn("[EMAIL]", text); n += k
    before = text
    text = _AADHAAR_SPACED.sub(_aadhaar_spaced, text); n += text.count("[AADHAAR]") - before.count("[AADHAAR]")
    text, k = _redact_phones(text); n += k
    text, k = _AADHAAR_BARE.subn("[AADHAAR]", text); n += k
    text, k = _SSN.subn("[SSN]", text); n += k
    text, k = _PAN.subn("[PAN]", text); n += k
    return text, n


_ADVICE = re.compile(
    r"\b(should i (take|use|stop|start)|my (dose|dosage|symptoms|diagnosis|prescription)|diagnose (me|my)|"
    r"what (dose|dosage) should (i|my)|am i (sick|ill|dying)|can i (take|combine)|prescribe (me|for me))\b", re.I)


@dataclass
class QueryVerdict:
    allowed: bool
    query: str
    reason: str = ""
    flags: list = field(default_factory=list)


def check_query(q: str) -> QueryVerdict:
    q = (q or "").strip()
    flags = []
    if on("query_policy"):
        if not q:
            return QueryVerdict(False, q, "Empty question", ["empty"])
        if len(q) > _cfg["max_query_chars"]:
            return QueryVerdict(False, q[:200], f"Question longer than {_cfg['max_query_chars']} characters", ["too_long"])
    if on("prompt_injection"):
        hits = scan_injection(q)
        if hits:
            return QueryVerdict(False, q, "Possible prompt-injection detected in the question", ["injection"])
    if on("medical_advice_block") and _ADVICE.search(q):
        return QueryVerdict(False, q, "This assistant summarises published research and cannot give patient-specific "
                                      "medical advice. Please consult a qualified clinician.", ["medical_advice"])
    if on("pii_redaction"):
        q, n = redact_pii(q)
        if n:
            flags.append(f"pii_redacted:{n}")
    return QueryVerdict(True, q, "", flags)


# ---------------------------------------------------------------- output guardrails
def _norm(s: str) -> str:
    s = (s or "").lower().replace(" ", " ").replace(" ", " ")
    s = re.sub(r"[‐-―]", "-", s)
    s = re.sub(r"[^a-z0-9%.<>=\-/ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def verify_grounding(evidence: str, source: str, min_cov=0.85) -> bool:
    """True if the evidence quote is (near-)verbatim present in the source text."""
    ev, src = _norm(evidence), _norm(source)
    if not ev:
        return False
    if ev in src:
        return True
    words = ev.split()
    if len(words) < 4:
        return False
    grams = {" ".join(words[i:i + 3]) for i in range(len(words) - 2)}
    cov = sum(1 for g in grams if g in src) / len(grams)
    return cov >= min_cov


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def numbers_supported(value: str, source: str) -> bool:
    src = _norm(source)
    nums = _NUM.findall(value or "")
    return all(n.replace(",", "") in src.replace(",", "") for n in nums)


def cap_quote(text: str) -> str:
    if not on("quote_limit"):
        return text
    w = text.split()
    lim = _cfg["max_quote_words"]
    return text if len(w) <= lim else " ".join(w[:lim]) + " …"


CITE = re.compile(r"\[paper:(\d+)/([^\]]+)\]")
DISCLAIMER = ("\n\n_Research-use only: generated from published literature; not medical advice. "
              "Verify against the cited source before relying on it._")


def validate_answer(answer: str, allowed_paper_ids=None):
    """Returns (answer, flags). Drops citations to papers that were never retrieved."""
    flags = []
    cites = CITE.findall(answer or "")
    if allowed_paper_ids is not None:
        bad = [c for c in cites if int(c[0]) not in set(allowed_paper_ids)]
        if bad:
            flags.append("hallucinated_citation")
            for pid, sec in bad:
                answer = answer.replace(f"[paper:{pid}/{sec}]", "[invalid-citation]")
    if on("citation_required") and not CITE.search(answer or ""):
        flags.append("uncited_answer")
    if on("medical_disclaimer"):
        answer += DISCLAIMER
    return answer, flags
