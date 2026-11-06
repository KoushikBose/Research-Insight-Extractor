"""End-to-end feature test (plain asserts, no pytest needed):  python tests/test_features.py
Uses a temporary SQLite DB, generated PDFs (reportlab/PIL), the real job queue and, if reachable, live PubMed/bioRxiv.
"""
import io
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["GROQ_API_KEY"] = ""          # deterministic offline engine
os.environ["LANGSMITH_TRACING"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

RESULTS = []


def check(name, cond, info=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


def make_table_pdf() -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet
    buf, st = io.BytesIO(), getSampleStyleSheet()
    body = ("The objective of this study was to evaluate compound QX-77 in 60 patients. " * 6)
    tbl = Table([["Group", "n", "Dose", "Response"], ["QX-77", "30", "20 mg", "64%"], ["Placebo", "30", "-", "21%"]])
    tbl.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    SimpleDocTemplate(buf, pagesize=A4).build([
        Paragraph("Efficacy of QX-77 in Chronic Inflammatory Disease: A Phase 2 Study", st["Title"]),
        Paragraph("doi: 10.5555/qx77.2025.001", st["Normal"]), Paragraph("Abstract", st["Heading2"]),
        Paragraph(body, st["Normal"]), Paragraph("Results", st["Heading2"]),
        Paragraph("Table 1. Response by treatment group", st["Normal"]), Spacer(1, 8), tbl,
        Paragraph("Figure 1. Response over time in each treatment group", st["Normal"]),
        Paragraph("Conclusion", st["Heading2"]), Paragraph("QX-77 improved response versus placebo (p < 0.01).", st["Normal"])])
    return buf.getvalue()


def make_scanned_pdf() -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1240, 900), "white")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("arial.ttf", 34)
    except Exception:
        f = ImageFont.load_default()
    lines = ["Abstract", "We evaluated drug ZR-90 in forty mice with induced fibrosis.",
             "Methods", "Mice received 5 mg/kg daily for four weeks and collagen was measured by ELISA.",
             "Results", "Collagen decreased by 52 percent compared with vehicle."]
    for i, l in enumerate(lines):
        d.text((60, 60 + i * 80), l, fill="black", font=f)
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


def wait_jobs(c, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        cnt = c.get("/api/jobs").json()["counts"]
        if not cnt.get("queued") and not cnt.get("running"):
            return True
        time.sleep(1)
    return False


with TestClient(app) as c:
    # ---------- OCR (scanned PDF) ----------
    r = c.post("/api/papers/upload", files={"file": ("scan.pdf", make_scanned_pdf())})
    check("OCR: scanned PDF accepted", r.status_code == 200, r.text[:150])
    scan_id = r.json().get("id")
    # ---------- Tables ----------
    qx_bytes = make_table_pdf()
    r = c.post("/api/papers/upload", files={"file": ("qx77.pdf", qx_bytes)})
    check("PDF with table accepted", r.status_code == 200, r.text[:150])
    qx_id = r.json()["id"]
    # ---------- Duplicate upload restriction ----------
    import hashlib
    r = c.post("/api/papers/upload", files={"file": ("renamed_copy.pdf", qx_bytes)})
    d = r.json().get("detail", {})
    check("duplicate (identical file, different name) rejected with 409", r.status_code == 409 and d.get("code") == "duplicate"
          and d.get("existing_id") == qx_id and d.get("matched_by") == "file", r.text[:200])
    r = c.post("/api/papers/upload", files={"file": ("qx77_reexport.pdf", make_table_pdf())})
    check("duplicate (re-exported PDF, same text/DOI) rejected with 409", r.status_code == 409 and r.json()["detail"]["existing_id"] == qx_id
          and r.json()["detail"]["matched_by"] in ("content", "doi", "title"), r.text[:200])
    h = c.get("/api/papers/check-hash", params={"sha256": hashlib.sha256(qx_bytes).hexdigest()}).json()
    check("pre-upload hash check finds the existing paper", h["duplicate"] and h["existing_id"] == qx_id, h)
    check("pre-upload hash check passes unknown file", not c.get("/api/papers/check-hash", params={"sha256": "0" * 64}).json()["duplicate"])
    check("only one copy stored after duplicate attempts", sum(1 for x in c.get("/api/papers").json() if "QX-77" in x["title"]) == 1)
    check("title picked from PDF text (not '1')", "QX-77" in c.get(f"/api/papers/{qx_id}").json()["title"],
          c.get(f"/api/papers/{qx_id}").json()["title"])
    check("DOI extracted", c.get(f"/api/papers/{qx_id}").json()["doi"] == "10.5555/qx77.2025.001")
    # ---------- Job queue ----------
    check("job queue drained", wait_jobs(c))
    p = c.get(f"/api/papers/{qx_id}").json()
    check("extraction completed via queue", p["status"] == "ready", p["status"])
    check("table extracted from PDF", len(p["tables"]) >= 1 and "QX-77" in str(p["tables"][0]["rows"]),
          f"{len(p['tables'])} tables")
    check("figure caption extracted from PDF", any("Response over time" in f["caption"] for f in p["figures"]),
          [f["label"] for f in p["figures"]])
    ents = p["insights"]["entities"]
    check("entities: drug/dose/disease typed", any(e["text"] == "QX-77" for e in ents["drug_compound"])
          and any("20 mg" in e["text"] for e in ents["dose"]), str({k: [e['text'] for e in v][:3] for k, v in ents.items()}))
    s = c.get(f"/api/papers/{scan_id}").json()
    check("OCR text recovered", s["status"] == "ready" and "ocr_used" in s["flags"]
          and "ZR-90" in " ".join(x["text"] for x in s["sections"]), s["flags"])
    check("OCR sections segmented", {"Abstract", "Methods", "Results"} <= {x["name"] for x in s["sections"]},
          [x["name"] for x in s["sections"]])

    # ---------- De-duplication: DOI / title / upgrade ----------
    abstract_only = {"title": "Efficacy of QX-77 in Chronic Inflammatory Disease: A Phase 2 Study", "authors": [],
                     "pub_date": "2025", "keywords": [], "doi": "10.5555/qx77.2025.001",
                     "sections": [{"name": "Abstract", "text": "Short abstract about QX-77."}]}
    from app.services import ingest
    r = ingest.store_paper(abstract_only, source="pubmed", source_id="999")
    check("dedupe by DOI (abstract-only vs existing full text)", r["duplicate"] and r["matched_by"] == "doi", r)
    pm = {"title": "A Completely Different Paper About Mitochondrial Dynamics In Neurons", "authors": [], "pub_date": "2024",
          "keywords": [], "doi": "10.7777/mito.1", "sections": [{"name": "Abstract", "text": "Mitochondria fuse and divide."}]}
    r1 = ingest.store_paper(pm, source="pubmed", source_id="111")
    full = dict(pm, sections=[{"name": "Abstract", "text": "Mitochondria fuse and divide. " * 3},
                              {"name": "Results", "text": "Fission was increased in neurons treated with compound. " * 20}])
    r2 = ingest.store_paper(full, source="upload", source_id="mito.txt")
    check("abstract-only paper upgraded in place by full text", r2.get("upgraded") and r2["id"] == r1["id"], r2)
    dup = ingest.store_paper(dict(pm, doi=""), source="pubmed", source_id="222")
    check("dedupe by normalised title", dup["duplicate"], dup)

    # ---------- Semantic search ----------
    ingest.post_process(qx_id)
    ingest.post_process(r1["id"])
    res = c.get("/api/search", params={"q": "medicine for swollen joints and long-term immune disorders"}).json()
    check("semantic model loaded", res["semantic_enabled"])
    check("semantic search returns related paper for a synonym query (no shared keywords)",
          res["results"] and res["results"][0]["paper_id"] == qx_id, [(x["paper_id"], x["via"]) for x in res["results"]][:3])

    # ---------- SQL connector ----------
    src = os.path.join(tempfile.mkdtemp(), "internal.db")
    sc = sqlite3.connect(src)
    sc.execute("CREATE TABLE reports(title TEXT, body TEXT, doi TEXT)")
    for i in range(3):
        sc.execute("INSERT INTO reports VALUES(?,?,?)", (f"Internal stability study of formulation F-{i}0{i} in dogs",
                                                         f"Formulation F-{i}0{i} was stable at 25C for {6+i} months in beagles. " * 12, f"10.9999/int.{i}"))
    sc.commit(); sc.close()
    r = c.post("/api/connectors/sql", json={"path": src, "table": "reports", "title_col": "title", "text_col": "body",
                                            "doi_col": "doi"})
    check("SQL connector job queued", r.status_code == 200)
    bad = c.post("/api/connectors/sql", json={"path": src, "table": "reports; DROP TABLE x", "title_col": "title", "text_col": "body"})
    wait_jobs(c)
    jobs = c.get("/api/jobs").json()["jobs"]
    sqljob = next(j for j in jobs if j["kind"] == "import_sql" and j["status"] == "done" and j["result"]["ingested"])
    check("SQL connector ingested 3 internal rows (confidential, source=internal_db)", sqljob["result"]["ingested"] == 3, sqljob["result"])
    bad_job = [j for j in jobs if j["kind"] == "import_sql" and j["status"] == "error"]
    check("SQL connector rejects injected identifier", bad_job and "invalid identifier" in (bad_job[0]["error"] or ""))
    rows = c.get("/api/papers").json()
    check("internal DB papers marked confidential", all(x["confidential"] for x in rows if x["source"] == "internal_db") and
          any(x["source"] == "internal_db" for x in rows))

    # ---------- Explore analytics ----------
    ex = c.get("/api/explore").json()
    check("explore: compare table + network + entities", len(ex["compare"]) >= 3 and ex["network"]["nodes"] and ex["entities"],
          f"{len(ex['compare'])} papers, {len(ex['network']['nodes'])} nodes")

    # ---------- Monitoring (live APIs; skipped if offline) ----------
    try:
        import httpx
        httpx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi", timeout=10)
        online = True
    except Exception:
        online = False
    if online:
        r = c.post("/api/monitor/searches", json={"name": "JAK1 watch", "source": "pubmed", "query": "JAK1 inhibitor rheumatoid arthritis",
                                                  "interval_hours": 24, "max_new": 3})
        wait_jobs(c, 300)
        al = c.get("/api/monitor/alerts").json()
        check("monitor: saved PubMed search produced alerts + ingested papers", len(al) >= 1 and any(a["ingested"] for a in al), f"{len(al)} alerts")
        r = c.post("/api/connectors/biorxiv", json={"query": "", "days": 3, "n": 3})
        wait_jobs(c, 300)
        bj = next(j for j in c.get("/api/jobs").json()["jobs"] if j["kind"] == "bulk_biorxiv")
        check("bioRxiv API connector", bj["status"] == "done" and bj["result"]["ingested"] >= 1, bj["result"] or bj["error"])
        r = c.post("/api/jobs/pubmed-bulk", json={"query": "CRISPR screen pancreatic cancer", "n": 5})
        wait_jobs(c, 300)
        pj = next(j for j in c.get("/api/jobs").json()["jobs"] if j["kind"] == "bulk_pubmed")
        check("bulk PubMed ingest via queue", pj["status"] == "done", pj["result"] or pj["error"])
    else:
        print("SKIP live PubMed/bioRxiv tests (offline)")

    # ---------- Baseline / time-to-insight ----------
    c.put("/api/settings/baseline", json={"manual_review_minutes": 30})
    u = c.get("/api/metrics/usage").json()
    check("review-time reduction measured from real timings + custom baseline",
          u["manual_review_minutes"] == 30 and u["review_time_reduction"] is not None and u["measured_papers"] >= 2, u)

failed = [n for n, ok in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
sys.exit(1 if failed else 0)
