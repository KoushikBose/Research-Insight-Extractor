# Guardrail Options

All switches live in `backend/app/guardrails.py`, are persisted in SQLite and toggled at runtime
(`PUT /api/guardrails`, **Guardrails** tab). Each has a test in the evaluation suite.

## Input guardrails
| Guardrail | Behaviour |
|---|---|
| Upload validation | extension allow-list (PDF/XML/TXT/MD), size cap, magic-byte check |
| Prompt-injection defence | regex scan on user queries (block) and on paper text (offending lines replaced by `[REMOVED…]`); LLM prompts also label document text as untrusted data |
| PII redaction | e-mail, SSN, Aadhaar, PAN and phone numbers in any common international layout (US, India incl. toll-free, UK, EU, APAC, Gulf, Africa, LatAm) are masked before text goes to the LLM or into logs; a validation step keeps DOIs, dates, page ranges, decimals and chart axes untouched (tested on 49 phone formats and 33 look-alikes) |
| Duplicate blocking | uploads are rejected (HTTP 409 + toast with a link to the existing paper) when the file hash, extracted text, DOI or title already exists; a full-text file may still upgrade an abstract-only record |
| Query policy | empty / oversized questions rejected |
| Medical-advice block | patient-specific "should I take / my dose / diagnose me" requests refused |
| Confidential routing | papers flagged *confidential* (and everything from the internal repo) are never sent to Groq; extractive engine used, whole-KB chat excludes them |
| Copyright / licence | per-paper licence tag; verbatim quotes capped at N words; PubMed = abstract-only |

## Output guardrails
| Guardrail | Behaviour |
|---|---|
| Evidence grounding | every extracted value needs a verbatim quote found in the source (normalised, 3-gram coverage ≥ 85 %), else flagged **unverified** |
| Numeric consistency | numbers in a value must appear in the source |
| Keyword filter | LLM keywords kept only if they occur in the paper |
| Citation required | chat answers must contain `[paper:ID/Section]`; citations to papers never retrieved are replaced with `[invalid-citation]` and flagged |
| Medical disclaimer | research-use-only footer on assistant answers |
| Schema/JSON repair | one automatic repair retry; falls back to extractive engine on failure |

## Governance & traceability
`audit_log` records ingest/extract/delete with mode, model and flags; `/api/papers/{id}/export` returns insights with evidence.

## Upgrades worth considering
* A dedicated safety classifier (e.g. Llama Guard) as a second pass on queries/answers.
* NER-based PII (Microsoft Presidio) instead of regex.
* Authentication + per-team access control on confidential papers; encrypt the SQLite file at rest.
* Rate limiting per user; max agent recursion/tool-call budget (a recursion limit of 40 is already set).
