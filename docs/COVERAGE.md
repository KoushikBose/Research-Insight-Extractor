# Problem-Statement Coverage Analysis (v2 – after optimisation)

Source: *AI Friday Season 3 – Life Sciences Research Paper Insight Extractor with Generative AI*.
Scoring: ✅ implemented & tested = 1 · 🟡 partial / built but unverified = 0.5 · ❌ missing = 0.
Challenge % = average of its checklist (same checklist as v1 so the numbers are comparable).
Constraint / data / expectation % remain judgement estimates.
"Tested" = exercised by the automated suites in `backend/tests` (91 checks) or `python -m app.eval.runner` (17 targets), mostly offline.
**LLM path:** extraction and the Deep-Agent chat have run live on Groq (Qwen3 27B primary, gpt-oss-120b fallback), but **LLM accuracy on real papers is not measured** (`--llm` benchmark not run).

## 1. Current challenge → Business/delivery impact

| # | Current challenge | Business / delivery impact | v1 | **Coverage % (v2)** |
|---|---|---|---|---|
| 1 | High volume and complexity of scientific literature | Slow literature review, potentially missed insights | 71 % | **93 %** |
| 2 | Limited tools for automated extraction of experimental details | Inefficient knowledge synthesis & data integration | 57 % | **93 %** |
| 3 | Difficulty navigating & querying large document sets | Reduced research productivity & collaboration | 58 % | **92 %** |
| 4 | Fragmented access to external & internal knowledge sources | Inconsistent information, duplicated efforts | 71 % | **93 %** |
| | **Average** | | 64 % | **93 %** |

### Checklist detail

**1 – Volume & complexity (6.5 / 7 = 93 %)**
✅ multi-format ingest (PDF/XML/TXT, now with OCR) · ✅ segmentation + normalisation (better titles/DOI) · ✅ per-section summaries ·
✅ keyword/entity highlighting · 🟡 throughput: persistent job queue (2 workers, retries, crash-recovery) + bulk PubMed/bioRxiv/DB/folder
ingest, tested at tens of papers – **not load-tested at thousands/month** · ✅ literature monitor (saved searches, scheduler, auto-ingest, alerts) ·
✅ review-time reduction measured from real per-paper timings against a user-set baseline.

**2 – Experimental-detail extraction (6.5 / 7 = 93 %)**
✅ 12 structured fields · ✅ verbatim evidence + grounding/numeric verification · ✅ typed entities (gene/protein, drug, dose, disease,
assay, model) – *lexicon + pattern based, not a trained NER* · ✅ tables (pdfplumber) **and** figure captions – *supplementary files not handled; only ruled tables detected* ·
🟡 accuracy validation: harness on **6 synthetic papers** (incl. JATS XML), 17 targets; LLM engine unmeasured; no real SME gold set ·
✅ JSON export (+ CSV comparison export) · ✅ OCR fallback for scanned PDFs (RapidOCR; tested on a clean synthetic scan only).

**3 – Navigation & querying (5.5 / 6 = 92 %)**
✅ BM25 retrieval · ✅ cited conversational Q&A (floating chatbot) · 🟡 Deep-Agent multi-step reasoning (runs live and answers, but citation compliance varies: some answers are flagged `uncited_answer`) ·
✅ library filter by title / keyword / entity · ✅ visual exploration (Explore tab: year/source/keyword/entity charts, concept network,
cross-paper comparison with CSV) · ✅ semantic search (local bge-small embeddings, score-aware hybrid with BM25; synonym-query recall@1 BM25 0.67 → hybrid 1.0 on 6 queries).

**4 – Fragmented sources (6.5 / 7 = 93 %)**
✅ PubMed · ✅ bioRxiv/medRxiv API (live-tested) · ✅ internal repository folder · 🟡 internal systems: read-only SQLite connector
(validated identifiers, confidential by default) – **no SharePoint / ELN / REST connectors** · ✅ one unified, source-tagged KB ·
✅ de-duplication by content hash → DOI → normalised title, with in-place upgrade of abstract-only records when full text arrives · ✅ provenance (source, audit log).

## 2. Remaining weak spots (be aware before relying on the 93 %)
* Each challenge sits only 2–3 points above 90 %; **one 🟡 → ❌ would drop it below**. The three 🟡 items are: scale, accuracy validation, Deep-Agent.
* Checklist is our own; a stricter reviewer may add items (e.g. supplementary data, role-based access, real NER).
* All accuracy numbers come from synthetic papers written by us; expect lower numbers on real literature.
* Constraints still weak: no authentication / roles, no encryption at rest, original PDFs are served regardless of licence.
* Visualisation is hand-built SVG/CSS (no interactive zoom, no time-series of results).

## 3. To move from "covered" to "proven"
1. Run `python -m app.eval.runner --llm` and score real-paper accuracy, plus tighten Deep-Agent citation behaviour (turns two 🟡 into measured results).
2. 30–50 real, SME-annotated papers as the gold set.
3. Load test: 1–5k papers through the queue (consider Postgres + pgvector beyond ~100k chunks; current vector search is in-memory numpy).
4. Auth + roles + encryption at rest; licence-aware file serving.
5. SharePoint/ELN/REST connectors behind the existing connector interface.
