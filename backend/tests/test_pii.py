"""PII / phone-number guardrail tests:  python tests/test_pii.py"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import guardrails as gr  # noqa: E402
from app.eval.pii_cases import MULTI, OTHER, PHONES, SAFE  # noqa: E402

gr.reset_config()
OK = []


def check(name, cond, info=""):
    OK.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


def red(t):
    return gr.redact_pii(t)[0]


missed = [t for t in PHONES if "[PHONE]" not in red(t)]
check(f"all {len(PHONES)} phone formats are redacted (US, India, UK, EU, APAC, Gulf, Africa, LatAm)", not missed, missed)
leaked = [t for t in PHONES if re.search(r"\d{4,}", red(t))]
check("no digits of a phone number leak after redaction", not leaked, [(t, red(t)) for t in leaked][:3])
for text, n in MULTI:
    check("two numbers in one sentence are both redacted", red(text).count("[PHONE]") == n, red(text))
bad = [(t, tag) for t, tag in OTHER if tag not in red(t)]
check("email / SSN / PAN / Aadhaar still redacted", not bad, bad)
changed = [(t, red(t)) for t in SAFE if red(t) != t]
check(f"{len(SAFE)} phone-like but harmless strings (DOIs, dates, page ranges, tables, axes, IDs) are untouched", not changed, changed)
check("redaction count is returned", gr.redact_pii("Call +91 98765 43210 or jane@corp.com")[1] == 2)

# end-to-end through the query guardrail used by the chatbot
v = gr.check_query("What is the dose? Call me on +91 98765 43210")
check("chat query: allowed, number redacted and flagged", v.allowed and "[PHONE]" in v.query and "98765" not in v.query and any(f.startswith("pii_redacted") for f in v.flags), (v.query, v.flags))
v = gr.check_query("Which assay was used in the CRISPR screen of 4 cell lines (n = 36)?")
check("chat query: normal scientific question is not altered", v.allowed and "[PHONE]" not in v.query and not v.flags, v.flags)

# switch off -> nothing redacted
gr.update_config.__globals__["_cfg"]["pii_redaction"] = False
check("guardrail can be switched off", red("Call +91 98765 43210") == "Call +91 98765 43210")
gr.reset_config()

print(f"\n{OK.count(True)}/{len(OK)} checks passed")
sys.exit(0 if all(OK) else 1)
