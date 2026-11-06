# Evaluation Matrix

Run offline benchmark: `python -m app.eval.runner` (add `--llm` for Groq). UI: **Evaluation** tab. Live KPIs: `GET /api/metrics/usage`.

| # | Dimension | Metric | How measured | Target |
|---|---|---|---|---|
| 1 | Parsing | Section segmentation accuracy | detected IMRaD sections ∩ gold / gold | ≥ 90 % |
| 2 | Extraction | **Fact recall** (per field + macro) | gold key-facts present in extracted value (12 fields) | ≥ 80 % |
| 3 | Extraction | Keyword P@10 / recall / F1 | lenient containment vs gold terms | recall ≥ 70 % |
| 4 | Summaries | ROUGE-1 / 2 / L F-score | vs reference summary | R-1 ≥ 0.35 |
| 5 | Faithfulness | **Grounding rate** | fields whose evidence quote is verbatim in source | ≥ 95 % |
| 6 | Faithfulness | **Hallucination rate** | 1 − verified fields (grounding + numeric check) | ≤ 5 % |
| 7 | Faithfulness | Numeric support / fabricated-claim rejection | numbers exist in source; fake quote must fail | 100 % |
| 8 | Retrieval | Recall@1/3, MRR; **paraphrase recall** (BM25 vs semantic vs hybrid); de-duplication accuracy | gold Q→paper pairs; synonym queries; duplicate/non-duplicate pairs | R@3 ≥ 90 %, hybrid paraphrase ≥ 80 %, dedupe ≥ 95 % |
| 9 | Safety | Injection TPR / FPR | labelled malicious vs benign queries; doc-level injection neutralised | TPR ≥ 90 %, FPR ≤ 5 % |
| 10 | Safety | PII redaction recall (49 phone formats + email/SSN/PAN/Aadhaar), **PII false-positive rate** (33 phone-like strings), medical-advice block TPR, upload rejection | labelled cases | recall ≥ 95 %, FP ≤ 2 %, others ≥ 90 % |
| 11 | Performance | Latency p50 / p95 per paper | wall-clock of extraction | p95 ≤ 30 s (LLM) |
| 12 | Business | **Review-time reduction** | 1 − avg processing time / manual baseline (`MANUAL_REVIEW_MINUTES`, default 20) | ≥ 70 % |
| 13 | Business | Hours saved, assistant usage, blocked queries | `events` table | trend ↑ |
| 14 | Adoption / trust | 👍/👎 rate on extractions, paper views, repeat users | `POST /api/feedback` | 👍 ≥ 80 % |

## Recommended extra checks for production
* **LLM-as-judge** (a strong model, ideally from a different family than the one being judged) scoring faithfulness/completeness on 50+ real papers, double-annotated by SMEs.
* Cohen's κ between SME annotators to cap the achievable accuracy.
* Cost per paper (Groq tokens) and rate-limit headroom.
* Regression gate in CI: fail the build if any target in `runner.TARGETS` regresses.

## Baseline result (extractive engine, 6 synthetic papers incl. one JATS XML)
17/17 targets pass. Weakest fields: `key_results` (0.50), `dosage` (0.80), `sample_size` (0.83): the sentence-picking heuristics miss
multi-sentence results. This is the headroom the LLM engine is expected to close; compare with `--llm`.

**Caveat:** the dataset is small and synthetic by design (development testing). The `--llm` benchmark has not been run yet, so LLM accuracy on
real papers is **not measured**; one live run on a sample paper gave 12/12 fields with 11 verified against the source (Qwen3 27B).
