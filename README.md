# Research Insight Extractor

**A Generative-AI research assistant for life-sciences literature.** It ingests scientific papers (PDF, scans, JATS XML, PubMed, bioRxiv, internal
repositories), extracts and **verifies** experimental details, and lets researchers explore the literature, ask cited questions and monitor new
publications, with guardrails, model fallback, observability and cost tracking built in.

Built by **Team Friday Forever** for *AI Friday Season 3* (problem statement: *Life Sciences Research Paper Insight Extractor with Generative AI*).

| | |
|---|---|
| **Demo video** | [`docs/media/friday-forever-demo.mp4`](docs/media/friday-forever-demo.mp4): 3.5 min captioned walkthrough of the live app |
| **Slide deck** | [`docs/Friday_Forever_Solution.pptx`](docs/Friday_Forever_Solution.pptx): solution, architecture, tech stack, workflows |
| **Stack** | Python · FastAPI · SQLite · React · LangChain Deep Agents · LiteLLM · Groq (Qwen3 27B → gpt-oss-120b fallback) |

![Knowledge base](docs/media/screenshots/library.png)

## The problem
Pharma R&D teams must track thousands of new papers every month. Reading abstracts and sections by hand is slow, experimental details are buried in
prose, large document sets are hard to query, and knowledge is scattered across public APIs and internal repositories, causing missed insights and
duplicated work. Constraints: respect copyright, integrate public and internal sources, keep proprietary data secure, make every extracted fact traceable,
and fit into existing IT with minimal change.

## What it does

| Capability | Details |
|---|---|
| **Ingest anything** | PDF (text, **OCR for scans**, **tables + figure captions**), JATS XML, text · PubMed · bioRxiv / medRxiv API · internal folder · internal SQL database. The original file is stored in SQLite. |
| **Duplicate blocking** | Rejected by file hash, extracted text, DOI or title (HTTP 409 + toast with a link to the existing paper). A full-text file can *upgrade* an abstract-only record. |
| **Extract & verify** | 12 experimental fields (design, sample size, dose, assays, results, statistics...), section summaries, typed entities and keywords. **Every fact carries a verbatim evidence quote that is checked against the source**; numbers must exist in the text. |
| **Search** | BM25 (SQLite FTS5) fused with local semantic embeddings (`bge-small`): finds paraphrases, not just exact words. |
| **Ask** | Floating chatbot on a **LangChain Deep Agent** (planner + evidence-checker sub-agent). Answers cite `[paper:ID/Section]`; falls back to a plain RAG answer, then to an extractive answer. |
| **Explore** | Charts, concept network, entity browser, cross-paper comparison table with CSV export. |
| **Monitor** | Saved PubMed / bioRxiv searches run on a schedule, auto-ingest new papers and raise alerts. Persistent job queue with retries for bulk work. |
| **Govern** | Input/output guardrails, confidential-paper routing (never sent to the external LLM), audit log, LangSmith tracing. |
| **Measure** | Evaluation benchmark, **Tokenomics** (tokens, cost, latency, quality vs cost trade-offs) and a **Models** tab for the LLM gateway. |

| Explore | Models (gateway & fallback) |
|---|---|
| ![Explore](docs/media/screenshots/explore.png) | ![Models](docs/media/screenshots/models.png) |

| Tokenomics | Guardrails |
|---|---|
| ![Tokenomics](docs/media/screenshots/tokenomics.png) | ![Guardrails](docs/media/screenshots/guardrails.png) |

## Architecture

```mermaid
flowchart LR
  UI["React UI<br/>Library · Explore · Monitor · Models<br/>Tokenomics · Evaluation · Guardrails · Chatbot"] -->|REST /api| API["FastAPI backend"]
  API --> ING["Ingestion<br/>parse · OCR · tables · de-dup"]
  API --> EXT["Extraction<br/>12 fields · entities · evidence check"]
  API --> AG["Research agent<br/>LangChain Deep Agent"]
  API --> SRCH["Search<br/>BM25 + embeddings"]
  API --> JOBS["Job queue + monitor"]
  ING --> DB[("SQLite<br/>files · text · FTS5 · vectors · jobs · logs")]
  EXT --> DB
  AG --> DB
  SRCH --> DB
  JOBS --> DB
  EXT --> GW["LiteLLM gateway<br/>primary → fallback · circuit breaker"]
  AG --> GW
  GW --> Q["Groq: Qwen3 27B (primary)"]
  GW --> G["Groq: gpt-oss-120b (fallback)"]
  ING --> SRC["PubMed · bioRxiv · internal folder / DB"]
  JOBS --> SRC
```

### Document workflow

```mermaid
flowchart LR
  A["Upload / PubMed / bioRxiv / internal"] --> B["Validate + duplicate check<br/>file hash · text · DOI · title"]
  B --> C["Parse<br/>PDF · OCR · XML"]
  C --> D["Segment + normalise"]
  D --> E["Guardrails<br/>injection · PII · licence"]
  E --> F["Store in SQLite"]
  F --> G["Job queue"]
  G --> H["Extract + verify<br/>LLM via gateway, or local extractive"]
  H --> I["Index<br/>BM25 + embeddings"]
  I --> J["Insights · search · cited chat"]
```

### LLM gateway and fallback
Every LLM call goes through a **LiteLLM** gateway (`backend/app/services/gateway.py`): primary `groq/qwen/qwen3.8-27b`, fallback `groq/openai/gpt-oss-120b`
(both configurable). On any primary failure (rate limit, timeout, retired model, auth, 5xx) the fallback answers **inside the same request**. A circuit breaker
skips a failing primary (30 s after rate limits, 5 min otherwise) and re-probes it with one call. Every attempt is logged to `llm_calls`, and the SQL view
`v_llm_fallbacks` lists each time the fallback served a request together with the failure that caused it. The **Models** tab shows who is serving now.
Optionally run LiteLLM as a standalone proxy: see [`backend/litellm_config.yaml`](backend/litellm_config.yaml).

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite, hand-built SVG charts, toast notifications |
| Backend | Python 3.12, FastAPI, Pydantic, background worker threads |
| Database | SQLite: BLOB file storage, FTS5 full text, embeddings, job queue, audit log, SQL views |
| Agents & LLM | LangChain Deep Agents, LiteLLM, Groq (Qwen3 27B, gpt-oss-120b) |
| Retrieval | SQLite FTS5 + `fastembed` (`BAAI/bge-small-en-v1.5`, ONNX, CPU) |
| Document AI | `pypdf`, `pdfplumber` (tables), `pypdfium2` + RapidOCR (scans), JATS XML parser, lexicon/regex entity extraction |
| Observability | LangSmith tracing, `llm_calls` log, tokenomics, evaluation harness |

## Getting started

**Prerequisites:** Python 3.12, Node.js 18+, a [Groq API key](https://console.groq.com) (optional: without a key the app runs in offline *extractive* mode).

```powershell
git clone https://github.com/KoushikBose/Research-Insight-Extractor.git
cd Research-Insight-Extractor

# 1) backend  (http://localhost:8000, Swagger UI at /docs)
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env            # then put your GROQ_API_KEY in .env
.venv\Scripts\uvicorn app.main:app --port 8000

# 2) frontend  (new terminal, http://localhost:5173)
cd frontend
npm install
npm run dev
```
On macOS / Linux use `source .venv/bin/activate` and `cp`. The first semantic search downloads a ~130 MB embedding model once.
Behind a corporate proxy that re-signs HTTPS, `pip-system-certs` (already in `requirements.txt`) makes Python trust the OS certificate store.

Try it: open http://localhost:5173, upload the sample papers in [`backend/app/eval/dataset/papers/`](backend/app/eval/dataset/papers/), open one, then ask the chatbot a question.

### Configuration (`backend/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | – | Groq credentials. Empty = offline extractive mode |
| `GROQ_MODEL` / `LLM_PRIMARY_MODEL` | `qwen/qwen3.8-27b` | Primary model |
| `LLM_FALLBACK_MODEL` | `groq/openai/gpt-oss-120b` | Fallback model |
| `LLM_FAIL_THRESHOLD` / `LLM_COOLDOWN_SECONDS` | `2` / `300` | Circuit-breaker settings |
| `LITELLM_PROXY_URL` | – | Route through a standalone LiteLLM proxy (optional) |
| `LANGSMITH_API_KEY`, `LANGSMITH_TRACING`, `LANGSMITH_PROJECT` | – | LangSmith tracing (optional). Set `LANGSMITH_HIDE_INPUTS=true` to keep paper text out of traces |
| `NCBI_EMAIL`, `NCBI_API_KEY` | – | Polite / higher-rate PubMed access |
| `MANUAL_REVIEW_MINUTES` | `20` | Baseline for the review-time-saved metric (also editable in the UI) |
| `DB_PATH`, `INTERNAL_REPO_DIR` | `backend/data/…` | SQLite file and internal-repository folder |

`.env` and the SQLite database are git-ignored. **Never commit API keys.**

## Guardrails
Input: upload validation, duplicate blocking, prompt-injection detection (questions *and* papers), PII redaction (e-mail, Aadhaar, PAN, SSN and phone numbers in any
common international layout), no patient-specific medical advice, confidential papers processed locally. Output: evidence grounding, numeric consistency,
required citations, quote-length cap, research-use disclaimer. Every control can be toggled at runtime in the **Guardrails** tab.
Details: [`docs/GUARDRAILS.md`](docs/GUARDRAILS.md).

## Testing and evaluation

```powershell
cd backend
.venv\Scripts\pip install -r requirements-dev.txt          # reportlab + pillow for the PDF/OCR fixtures
.venv\Scripts\python tests\test_features.py                # ingestion, OCR, tables, de-dup, search, queue, connectors, monitor
.venv\Scripts\python tests\test_gateway.py                 # LiteLLM gateway, fallback, circuit breaker, SQL view, Deep Agent failover
.venv\Scripts\python tests\test_tokenomics.py              # cost / token arithmetic
.venv\Scripts\python tests\test_pii.py                     # phone / PII redaction and false positives
.venv\Scripts\python -m app.eval.runner                    # benchmark (add --llm for the LLM engine)
```

| Result (measured) | |
|---|---|
| Automated checks | 91 across the four suites, all passing (LLM calls are mocked with LiteLLM's `mock_response`) |
| Benchmark | 17 / 17 targets on 6 synthetic gold papers (offline extractive engine) |
| Live run, sample paper | Qwen3 27B filled 12 / 12 fields, 11 verified against the source |
| Cost and speed | about 3,400 tokens, ~4 s and ~$0.002 per paper on average (Qwen ≈ $0.005, gpt-oss-120b ≈ $0.001; LiteLLM price map) |

**Caveat:** the benchmark data is synthetic and small by design, and the `--llm` benchmark has not been run, so LLM accuracy on real papers is **not yet measured**.
See [`docs/EVALUATION.md`](docs/EVALUATION.md) (metric matrix) and [`docs/COVERAGE.md`](docs/COVERAGE.md) (coverage of the problem statement, self-assessed).

## API overview
Interactive docs at `http://localhost:8000/docs`. Main groups: `/api/papers` (upload, list, file, extract, export, audit, `check-hash`), `/api/pubmed`, `/api/search`,
`/api/chat`, `/api/explore`, `/api/jobs`, `/api/connectors` (bioRxiv, SQL, folder), `/api/monitor`, `/api/llm` (status, config, test, simulate-outage, fallbacks),
`/api/tokenomics`, `/api/guardrails`, `/api/eval`, `/api/metrics/usage`, `/api/health`.

## Project structure
```
backend/
  app/
    main.py, config.py, db.py, guardrails.py
    routers/    papers.py · assistant.py · platform.py
    services/   parser · ingest · extractor · entities · semantic · research_agent
                gateway · llm · tokenomics · jobs · monitor · connectors · pubmed · tracing
    eval/       runner · metrics · pii_cases · dataset/ (synthetic papers + gold annotations)
  tests/        test_features · test_gateway · test_tokenomics · test_pii
  litellm_config.yaml   requirements.txt   requirements-dev.txt   .env.example
frontend/src/   App.jsx · api.js · toast.js · components/ (Library, KnowledgeBase, PaperView, Chat, Explore, Monitor, Models, Tokenomics, Evaluation, Guardrails, ...)
docs/           EVALUATION · GUARDRAILS · COVERAGE · slide deck · record_demo.py · build_deck.py · media/
```

## Known limitations and roadmap
* LLM extraction accuracy on real papers is unmeasured; the evaluation set is synthetic and small. Next: 30–50 SME-annotated papers and LLM-as-judge scoring.
* Entity and keyword extraction is lexicon / pattern based (not a trained biomedical NER) and is noisy on non-biomedical text.
* Only ruled tables are detected; supplementary files are not handled; OCR is tested on clean scans only.
* Not load-tested at thousands of papers per month (SQLite + in-process workers; consider Postgres + pgvector at scale).
* No authentication, roles or encryption at rest yet; original PDFs are served regardless of licence. Do not expose the API publicly as is.
* Qwen3 on Groq can rate-limit under bursts (the fallback absorbs this); the daily token budget is informational, not enforced.

## Data and privacy
The bundled papers in `backend/app/eval/dataset/` are **synthetic**. PubMed and bioRxiv content is fetched at runtime and is not redistributed in this repository.
Confidential papers are never sent to the external LLM. This tool summarises published research; it is **not medical advice**.

## Team
**Friday Forever**: Koushik Bose · Prasanta Mallick · Rupa Roy Chowdhury · Uddipta Bhatia · Sourav Sarkar · Pretam Paul

## Licence
No licence has been chosen yet; until one is added, all rights are reserved by the authors.
