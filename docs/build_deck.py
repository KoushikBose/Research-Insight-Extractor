"""Builds docs/Friday_Forever_Solution.pptx  (python docs/build_deck.py).  Diagrams are native, editable PowerPoint shapes."""
import json
import math
import sys
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

# Employee IDs are private: they are NOT in this repository. `--with-ids` reads them from the git-ignored docs/team_ids.json
# ({"Full Name": "id", ...}) and writes Friday_Forever_Solution_with_ids.pptx (also git-ignored). Default output has names only.
SHOW_IDS = "--with-ids" in sys.argv
_IDS_FILE = Path(__file__).parent / "team_ids.json"
IDS = json.loads(_IDS_FILE.read_text(encoding="utf-8")) if _IDS_FILE.exists() else {}
if SHOW_IDS and not IDS:
    sys.exit("--with-ids needs docs/team_ids.json")
OUT = Path(__file__).parent / ("Friday_Forever_Solution_with_ids.pptx" if SHOW_IDS else "Friday_Forever_Solution.pptx")
NAVY, INDIGO, TEAL, AMBER, ROSE, GREEN = "0F172A", "4F46E5", "0D9488", "D97706", "DB2777", "15803D"
INK, GREY, LIGHT, WHITE, LINE = "1E293B", "64748B", "F1F5F9", "FFFFFF", "CBD5E1"
TINT = {INDIGO: "EEF2FF", TEAL: "CCFBF1", AMBER: "FEF3C7", ROSE: "FCE7F3", GREEN: "DCFCE7", GREY: "E2E8F0", NAVY: "E2E8F0"}
FONT = "Calibri"

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]
TEAM = ["Koushik Bose", "Prasanta Mallick", "Rupa Roy Chowdhury", "Uddipta Bhatia", "Sourav Sarkar", "Pretam Paul"]


def rgb(h):
    return RGBColor.from_string(h)


def _runs(tf, paras, size, color, bold, align):
    """paras: str | list of (text | (text, {size,bold,color,italic}))"""
    if isinstance(paras, str):
        paras = [paras]
    for i, p in enumerate(paras):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align
        text, o = (p, {}) if isinstance(p, str) else p
        r = para.add_run()
        r.text = text
        f = r.font
        f.name, f.size = FONT, Pt(o.get("size", size))
        f.bold, f.italic = o.get("bold", bold), o.get("italic", False)
        f.color.rgb = rgb(o.get("color", color))
        if o.get("space"):
            para.space_before = Pt(o["space"])


def box(s, x, y, w, h, text="", fill=WHITE, line=LINE, size=13, color=INK, bold=False, shape=MSO_SHAPE.ROUNDED_RECTANGLE,
        align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE, lw=1.0, radius=0.08, dash=False):
    sh = s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        sh.adjustments[0] = radius
    sh.shadow.inherit = False
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid()
        sh.fill.fore_color.rgb = rgb(fill)
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = rgb(line)
        sh.line.width = Pt(lw)
        if dash:
            sh.line.dash_style = 4
    tf = sh.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.1)
    tf.margin_top = tf.margin_bottom = Inches(0.05)
    tf.vertical_anchor = anchor
    if text != "":
        _runs(tf, text, size, color, bold, align)
    return sh


def label(s, x, y, w, h, text, size=13, color=INK, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    return box(s, x, y, w, h, text, fill=None, line=None, size=size, color=color, bold=bold, align=align, anchor=anchor)


def arrow(s, x1, y1, x2, y2, color=GREY, w=2.0, head=True, dash=False):
    c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = rgb(color)
    c.line.width = Pt(w)
    ln = c.line._get_or_add_ln()
    if dash:
        d = etree.SubElement(ln, qn("a:prstDash"))
        d.set("val", "dash")
    if head:
        t = etree.SubElement(ln, qn("a:tailEnd"))
        t.set("type", "triangle")
        t.set("w", "med")
        t.set("len", "med")
    return c


def new_slide(title=None, subtitle=None, dark=False, notes=""):
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = rgb(NAVY if dark else "F8FAFC")
    if title:
        box(s, 0.45, 0.42, 0.09, 0.62, "", fill=INDIGO, line=None, shape=MSO_SHAPE.RECTANGLE)
        label(s, 0.7, 0.32, 12.0, 0.6, title, size=28, bold=True, color=NAVY)
        if subtitle:
            label(s, 0.7, 0.88, 12.0, 0.4, subtitle, size=14, color=GREY)
    if not dark:
        label(s, 0.45, 7.08, 6, 0.3, "Team Friday Forever  ·  AI Friday Season 3", size=10, color=GREY)
        label(s, 12.2, 7.08, 0.7, 0.3, str(len(prs.slides)), size=10, color=GREY, align=PP_ALIGN.RIGHT)
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    return s


def card(s, x, y, w, h, head, body, accent=INDIGO, hsize=15, bsize=12):
    box(s, x, y, w, h, "", fill=WHITE, line=LINE)
    box(s, x, y, 0.09, h, "", fill=accent, line=None, shape=MSO_SHAPE.RECTANGLE)
    label(s, x + 0.2, y + 0.08, w - 0.3, 0.4, head, size=hsize, bold=True, color=accent)
    label(s, x + 0.2, y + 0.5, w - 0.3, h - 0.55, body, size=bsize, color=INK)


def step(s, x, y, w, h, n, head, body, accent=INDIGO, bsize=11):
    box(s, x, y, w, h, "", fill=WHITE, line=accent, lw=1.5)
    c = box(s, x + 0.08, y + 0.08, 0.34, 0.34, str(n), fill=accent, line=None, shape=MSO_SHAPE.OVAL, color=WHITE, size=11, bold=True,
            align=PP_ALIGN.CENTER)
    c.text_frame.margin_left = c.text_frame.margin_right = c.text_frame.margin_top = c.text_frame.margin_bottom = 0
    label(s, x + 0.46, y + 0.06, w - 0.5, 0.42, head, size=13, bold=True, color=accent, anchor=MSO_ANCHOR.MIDDLE)
    label(s, x + 0.1, y + 0.52, w - 0.2, h - 0.55, body, size=bsize, color=INK)


# =========================================================== 1. Title
s = new_slide(dark=True, notes="Team Friday Forever - Life Sciences Research Paper Insight Extractor with Generative AI, built for TCS AI Friday Season 3. "
              "Context: pharma R&D teams must track thousands of new papers every month (from the problem statement). Our pipeline turns papers from PubMed, "
              "bioRxiv and internal repositories into verified, searchable experimental insight. The example card is real output for one of our sample papers.")
SLATE, CARD = "334155", "1E293B"


def helix(s, cx, y0, y1, amp=0.42, step=0.17, period=2.4):
    """Decorative DNA double helix (vertical) made of native circles and rungs."""
    n = int((y1 - y0) / step)
    for i in range(n + 1):
        y = y0 + i * step
        d = amp * math.sin(2 * math.pi * (y - y0) / period)
        a, b = cx + d, cx - d
        depth = math.cos(2 * math.pi * (y - y0) / period)          # fake 3D: nodes in front are larger / brighter
        if abs(d) > 0.06:
            arrow(s, a, y, b, y, color=SLATE, w=1.25, head=False)
        for px, col in ((a, "6366F1"), (b, "14B8A6")):
            r = 0.055 + 0.03 * (depth if px == a else -depth)
            box(s, px - r, y - r, 2 * r, 2 * r, "", fill=col, line=None, shape=MSO_SHAPE.OVAL)


# --- background motif + accents
box(s, 0, 0, 0.25, 7.5, "", fill=INDIGO, line=None, shape=MSO_SHAPE.RECTANGLE)
helix(s, 12.3, 0.35, 7.15)
for k, (hx, hy, hr) in enumerate([(11.25, 1.95, 0.38), (11.62, 2.62, 0.2)]):      # molecule-style hexagons
    box(s, hx - hr, hy - hr, 2 * hr, 2 * hr, "", fill=None, line=TEAL, shape=MSO_SHAPE.HEXAGON, lw=1.5)

# --- header: event + title
box(s, 0.8, 0.55, 5.6, 0.42, "TCS   ·   AI FRIDAY   ·   SEASON 3", fill=CARD, line=INDIGO, size=13, bold=True, color="A5B4FC", align=PP_ALIGN.CENTER, radius=0.5)
label(s, 0.8, 1.1, 10.4, 1.7, "Life Sciences Research Paper\nInsight Extractor with Generative AI", size=38, bold=True, color=WHITE)
label(s, 0.8, 2.55, 10.4, 0.75, "Pharma R&D teams must track thousands of new papers every month. We turn them into verified, searchable experimental insight.",
      size=16, color="CBD5E1")

# --- pipeline infographic: papers -> GenAI engine -> verified insight
label(s, 0.8, 3.32, 3.0, 0.3, "SOURCES", size=11, bold=True, color="64748B")
for i, (h, b, c) in enumerate([("PubMed", "public API", TEAL), ("bioRxiv / medRxiv", "preprints", AMBER), ("Internal repository", "PDF · XML · scans · DB", ROSE)]):
    y = 3.65 + i * 0.62
    box(s, 0.8, y, 2.65, 0.52, "", fill=CARD, line=c, lw=1.25)
    box(s, 0.9, y + 0.09, 0.3, 0.34, "", fill=c, line=None, shape=MSO_SHAPE.FOLDED_CORNER)
    label(s, 1.28, y + 0.02, 2.1, 0.5, [(h, {"bold": True, "size": 12, "color": WHITE}), (b, {"size": 9.5, "color": "94A3B8"})], anchor=MSO_ANCHOR.MIDDLE)
arrow(s, 3.5, 4.55, 4.0, 4.55, color="94A3B8", w=3)
box(s, 4.12, 3.58, 2.28, 2.28, "", fill=None, line=AMBER, shape=MSO_SHAPE.OVAL, lw=1.25, dash=True)
box(s, 4.3, 3.76, 1.92, 1.92, [("GenAI", {"bold": True, "size": 20, "color": WHITE}), ("engine", {"bold": True, "size": 20, "color": WHITE}),
                              ("Deep Agent · LiteLLM", {"size": 9.5, "color": "C7D2FE", "space": 4})],
    fill=INDIGO, line=None, shape=MSO_SHAPE.OVAL, align=PP_ALIGN.CENTER)
arrow(s, 6.45, 4.55, 6.95, 4.55, color="94A3B8", w=3)
label(s, 7.05, 3.32, 3.9, 0.3, "VERIFIED INSIGHT   (sample paper, real output)", size=11, bold=True, color="64748B")
box(s, 7.05, 3.65, 4.05, 1.86, "", fill=CARD, line=TEAL, lw=1.5)
for i, (k, v, ok) in enumerate([("Sample size", "36 mice", True), ("Dose", "10 mg/kg", True), ("Result", "Aβ42 ↓ 37%,  p = 0.003", True), ("Evidence", "verbatim quote checked", True)]):
    y = 3.75 + i * 0.44
    label(s, 7.17, y, 1.3, 0.4, k, size=11, color="94A3B8", anchor=MSO_ANCHOR.MIDDLE)
    label(s, 8.4, y, 2.6, 0.4, v, size=13, bold=True, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)
    tick = box(s, 10.8, y + 0.08, 0.24, 0.24, "✓", fill=GREEN, line=None, shape=MSO_SHAPE.OVAL, size=9, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    tick.text_frame.margin_left = tick.text_frame.margin_right = tick.text_frame.margin_top = tick.text_frame.margin_bottom = 0
label(s, 3.46, 5.9, 3.6, 0.3, "ingest · extract · verify · explore · ask", size=10.5, color="94A3B8", align=PP_ALIGN.CENTER)

# --- stats strip
for i, (big, small, c) in enumerate([("1000s", "papers a month to track\n(problem statement)", ROSE), ("4", "source types: upload, PubMed,\npreprints, internal DB", TEAL),
                                     ("12", "experimental fields per paper,\neach evidence-checked", AMBER), ("≈ 4 s", "LLM time per paper\n(measured; manual: ~20 min assumed)", INDIGO)]):
    x = 0.8 + i * 2.62
    box(s, x, 6.2, 2.5, 0.95, "", fill=CARD, line=SLATE)
    box(s, x, 6.2, 0.08, 0.95, "", fill=c, line=None, shape=MSO_SHAPE.RECTANGLE)
    label(s, x + 0.15, 6.22, 1.0, 0.9, big, size=22, bold=True, color=c, anchor=MSO_ANCHOR.MIDDLE)
    label(s, x + 1.12, 6.22, 1.35, 0.9, small, size=8.5, color="CBD5E1", anchor=MSO_ANCHOR.MIDDLE)
box(s, 8.4, 0.55, 2.7, 0.42, "Team  Friday Forever", fill=INDIGO, line=None, size=14, bold=True, color=WHITE, align=PP_ALIGN.CENTER, radius=0.5)

# =========================================================== 2. Introduction / team
s = new_slide("Introduction", "Who we are and what we built",
              notes="Introduce Team Friday Forever and the six members. One line on the product: end-to-end research insight assistant.")
box(s, 0.6, 1.55, 5.6, 1.1, "Team  Friday Forever", fill=INDIGO, line=None, size=30, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
label(s, 0.6, 2.95, 5.6, 3.8, [
    ("Our solution in one line", {"bold": True, "size": 16, "color": INDIGO}),
    ("A web application that turns a flood of research papers into structured, evidence-backed insight, "
     "searchable knowledge and cited answers, with guardrails, observability and cost tracking built in.", {"size": 15, "space": 4}),
    ("Built for", {"bold": True, "size": 16, "color": INDIGO, "space": 14}),
    ("Principal investigators, research associates and data scientists in a pharmaceutical R&D organisation.", {"size": 15, "space": 4}),
], size=15)
rows = len(TEAM) + 1
COLS = ["#", "Employee ID", "Team member"] if SHOW_IDS else ["#", "Team member"]
tbl = s.shapes.add_table(rows, len(COLS), Inches(6.8), Inches(1.55), Inches(6.0), Inches(0.62 * rows)).table
for c, w in enumerate([0.6, 1.9, 3.5] if SHOW_IDS else [0.8, 5.2]):
    tbl.columns[c].width = Inches(w)
for c, h in enumerate(COLS):
    cell = tbl.cell(0, c)
    cell.fill.solid(); cell.fill.fore_color.rgb = rgb(NAVY)
    cell.text_frame.text = h
    r = cell.text_frame.paragraphs[0].runs[0]; r.font.size, r.font.bold, r.font.name = Pt(14), True, FONT
    r.font.color.rgb = rgb(WHITE)
for i, name in enumerate(TEAM, start=1):
    for c, v in enumerate([str(i), IDS[name], name] if SHOW_IDS else [str(i), name]):
        cell = tbl.cell(i, c)
        cell.fill.solid(); cell.fill.fore_color.rgb = rgb(WHITE if i % 2 else "EEF2FF")
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.text_frame.text = v
        r = cell.text_frame.paragraphs[0].runs[0]
        r.font.size, r.font.name, r.font.bold = Pt(16), FONT, c == len(COLS) - 1
        r.font.color.rgb = rgb(INK)

# =========================================================== 3. Problem
s = new_slide("The problem", "Pharma R&D teams cannot keep up with the literature",
              notes="Four challenges from the problem statement and the business impact each one causes.")
pairs = [("High volume and complexity of scientific literature", "Slow literature review, potentially missed insights"),
         ("Limited tools for automated extraction of experimental details", "Inefficient knowledge synthesis and data integration"),
         ("Difficulty navigating and querying large document sets", "Reduced research productivity and collaboration"),
         ("Fragmented access to external and internal knowledge sources", "Inconsistent information and duplicated efforts")]
label(s, 0.6, 1.4, 5.6, 0.35, "CURRENT CHALLENGE", size=12, bold=True, color=GREY)
label(s, 7.1, 1.4, 5.6, 0.35, "BUSINESS / DELIVERY IMPACT", size=12, bold=True, color=GREY)
for i, (a, b) in enumerate(pairs):
    y = 1.8 + i * 1.12
    box(s, 0.6, y, 5.9, 0.95, a, fill=WHITE, line=INDIGO, size=15, color=INK, lw=1.5)
    arrow(s, 6.55, y + 0.475, 7.05, y + 0.475, color=ROSE, w=2.5)
    box(s, 7.1, y, 5.65, 0.95, b, fill="FCE7F3", line=ROSE, size=15, color=INK, lw=1.5)
label(s, 0.6, 6.3, 12.15, 0.7, "Constraints:  copyright & data-use compliance  ·  public APIs (PubMed) + internal sources  ·  secure handling of proprietary data  "
      "·  traceability of extracted facts  ·  minimal change to existing IT", size=13, color=INK)

# =========================================================== 4. Solution overview
s = new_slide("Our solution", "From papers to verified insight, in one application",
              notes="Six capabilities. Emphasise that every extracted fact carries a verbatim evidence quote that is checked against the source.")
caps = [("1  Ingest anything", "PDF (with OCR for scans), JATS XML, text · PubMed · bioRxiv/medRxiv · internal folder and database · duplicate detection by file, text, DOI and title", INDIGO),
        ("2  Extract & verify", "12 experimental fields, summaries, typed entities, tables and figure captions. Each fact carries a verbatim evidence quote that is checked against the source", TEAL),
        ("3  Explore", "Charts, concept network and a cross-paper comparison table with CSV export. Keyword highlighting and entity filters in every paper", AMBER),
        ("4  Ask", "Floating chatbot powered by a LangChain Deep Agent. Hybrid keyword + semantic search. Every answer is cited back to paper and section", ROSE),
        ("5  Monitor & scale", "Saved PubMed / bioRxiv searches run on a schedule, auto-ingest new papers and raise alerts. Persistent job queue for bulk work", GREEN),
        ("6  Govern & measure", "Input/output guardrails, LiteLLM gateway with model fallback, LangSmith tracing, tokenomics and an evaluation matrix", NAVY)]
for i, (h, b, c) in enumerate(caps):
    card(s, 0.6 + (i % 3) * 4.1, 1.5 + (i // 3) * 2.7, 3.9, 2.5, h, b, accent=c, bsize=13)

# =========================================================== 5. Architecture
s = new_slide("Solution architecture", "Single deployable: React UI  +  FastAPI  +  SQLite  +  an LLM gateway",
              notes="Walk left to right: browser UI, FastAPI services, SQLite for everything (files, text, vectors, jobs, logs), and external services behind a LiteLLM gateway. Guardrails apply across all services.")
# left: UI
box(s, 0.45, 1.5, 2.35, 3.3, "", fill=WHITE, line=INDIGO, lw=1.5)
label(s, 0.55, 1.55, 2.2, 0.35, "React UI (Vite)", size=14, bold=True, color=INDIGO)
label(s, 0.55, 1.95, 2.2, 2.8, ["Library & upload", "Explore (charts, network)", "Monitor & alerts", "Models (fallback view)", "Tokenomics",
                                "Evaluation · Guardrails", "Floating chatbot"], size=12)
# middle: FastAPI
box(s, 3.2, 1.5, 5.9, 3.3, "", fill="EEF2FF", line=INDIGO, lw=1.5)
label(s, 3.3, 1.53, 5.7, 0.35, "FastAPI backend (Python)", size=14, bold=True, color=INDIGO)
mods = [("Ingestion", "parse · OCR · tables · de-dup", TEAL), ("Extraction", "12 fields · entities · evidence check", TEAL),
        ("Research agent", "LangChain Deep Agent + sub-agent", ROSE), ("Search", "BM25 (FTS5) + embeddings", AMBER),
        ("Job queue & monitor", "workers · retries · schedules", GREEN), ("Analytics", "explore · tokenomics · eval", GREY)]
for i, (h, b, c) in enumerate(mods):
    x, y = 3.35 + (i % 2) * 2.85, 1.95 + (i // 2) * 0.93
    box(s, x, y, 2.75, 0.84, [(h, {"bold": True, "size": 12, "color": c}), (b, {"size": 10.5})], fill=WHITE, line=c, anchor=MSO_ANCHOR.MIDDLE)
# guardrails bar
box(s, 3.2, 4.92, 5.9, 0.5, "Guardrails (cross-cutting): upload checks · prompt-injection · PII redaction · grounding · citations · confidential routing",
    fill="FEE2E2", line="B91C1C", size=11, color="7F1D1D", bold=True, align=PP_ALIGN.CENTER)
# SQLite
box(s, 3.2, 5.55, 5.9, 1.4, "", fill=WHITE, line=NAVY, lw=1.5)
label(s, 3.3, 5.56, 5.7, 0.38, "SQLite (single file)", size=13, bold=True, color=NAVY)
chips = ["papers", "sections", "files (BLOB)", "insights", "FTS5 index", "embeddings", "jobs", "llm_calls", "fallbacks view"]
for i, ch in enumerate(chips):
    box(s, 3.28 + (i % 5) * 1.14, 5.92 + (i // 5) * 0.48, 1.1, 0.4, ch, fill=LIGHT, line=LINE, size=9, align=PP_ALIGN.CENTER, radius=0.2)
# right: external
box(s, 9.65, 1.5, 3.25, 1.05, [("LiteLLM gateway", {"bold": True, "size": 13, "color": AMBER}), ("primary → fallback · circuit breaker", {"size": 11})],
    fill="FEF3C7", line=AMBER, lw=1.5)
box(s, 9.65, 2.65, 1.55, 0.78, [("Qwen3 27B", {"bold": True, "size": 11}), ("primary", {"size": 10})], fill=WHITE, line=AMBER, align=PP_ALIGN.CENTER)
box(s, 11.35, 2.65, 1.55, 0.78, [("gpt-oss-120b", {"bold": True, "size": 11}), ("fallback", {"size": 10})], fill=WHITE, line=AMBER, align=PP_ALIGN.CENTER, dash=True)
label(s, 9.65, 3.42, 3.25, 0.3, "served by Groq", size=10, color=GREY, align=PP_ALIGN.CENTER)
box(s, 9.65, 3.8, 3.25, 1.0, [("External & internal sources", {"bold": True, "size": 12, "color": TEAL}), ("PubMed · bioRxiv/medRxiv APIs\ninternal folder · internal database", {"size": 10.5})],
    fill=WHITE, line=TEAL, lw=1.5)
box(s, 9.65, 4.92, 3.25, 0.5, "LangSmith: traces of every LLM / agent run", fill=WHITE, line=GREY, size=11, color=INK, align=PP_ALIGN.CENTER)
label(s, 9.65, 5.6, 3.25, 1.3, "Local-only processing for papers flagged confidential: they never reach the external LLM.", size=11, color=GREY)
# arrows
arrow(s, 2.8, 3.15, 3.2, 3.15, color=INDIGO, w=2.5)
arrow(s, 9.1, 2.0, 9.65, 2.0, color=AMBER, w=2.5)
arrow(s, 9.1, 4.3, 9.65, 4.3, color=TEAL, w=2.5)
arrow(s, 6.15, 4.8, 6.15, 4.92, color=NAVY, w=2.0)
arrow(s, 6.15, 5.42, 6.15, 5.55, color=NAVY, w=2.0)

# =========================================================== 6. Workflow: ingestion -> insight
s = new_slide("Workflow: from document to insight", "Every document passes the same governed pipeline",
              notes="Ten steps. Stress step 2 (duplicate checks save OCR time) and step 5 (guardrails sanitise untrusted text). Step 8 verifies each extracted fact against the source quote.")
w, gap, x0 = 2.3, 0.16, 0.45
r1 = [("Sources", "Upload · PubMed · bioRxiv · internal folder/DB", INDIGO), ("Validate & de-dup", "type, size · SHA-256 file hash · DOI · title · text", INDIGO),
      ("Parse", "PDF text · OCR for scans · JATS XML · tables · figures", TEAL), ("Segment & clean", "Abstract · Methods · Results · Discussion", TEAL),
      ("Guardrails", "neutralise prompt-injection · PII redaction · licence flags", ROSE)]
r2 = [("Store in SQLite", "metadata · sections · original file (BLOB)", NAVY), ("Job queue", "background workers · retries · crash recovery", GREEN),
      ("Extract & verify", "LLM via gateway (or local extractive) · evidence quote check", AMBER), ("Index", "BM25 (FTS5) + semantic embeddings · entities · tables", AMBER),
      ("Insight", "summary · 12 fields · charts · cited chat · alerts", GREEN)]
for row, y in ((r1, 1.65), (r2, 4.15)):
    for i, (h, b, c) in enumerate(row):
        n = i + 1 + (0 if row is r1 else 5)
        step(s, x0 + i * (w + gap), y, w, 1.95, n, h, b, accent=c, bsize=12)
        if i < 4:
            arrow(s, x0 + i * (w + gap) + w, y + 0.97, x0 + (i + 1) * (w + gap), y + 0.97, color=GREY, w=2.25)
xe = x0 + 4 * (w + gap) + w / 2
arrow(s, xe, 3.6, xe, 3.88, color=GREY, w=2.25, head=False)
arrow(s, xe, 3.88, x0 + w / 2, 3.88, color=GREY, w=2.25, head=False)
arrow(s, x0 + w / 2, 3.88, x0 + w / 2, 4.15, color=GREY, w=2.25)
label(s, 0.45, 6.35, 12.4, 0.6, "Rejected duplicates return a clear toast with a link to the existing paper; the same-file check runs before any parsing or OCR.", size=12, color=GREY)

# =========================================================== 7. Workflow: question answering
s = new_slide("Workflow: asking questions", "A LangChain Deep Agent plans, retrieves, verifies, then answers with citations",
              notes="The agent plans with todos, calls tools, then delegates to an evidence-checker sub-agent. Output guardrails drop invented citations and add a research-use disclaimer.")
w, gap, x0 = 1.95, 0.22, 0.4
qs = [("Question", "floating chatbot, scoped to one paper or all", INDIGO), ("Input checks", "injection · PII · off-scope · no patient advice", ROSE),
      ("Plan", "Deep Agent writes a short plan and picks tools", TEAL), ("Retrieve", "hybrid search · section reader · PubMed lookup", TEAL),
      ("Verify", "evidence-checker sub-agent re-reads cited sections", AMBER), ("Answer", "citations [paper:ID/Section] · output guardrails", GREEN)]
for i, (h, b, c) in enumerate(qs):
    step(s, x0 + i * (w + gap), 1.8, w, 2.35, i + 1, h, b, accent=c, bsize=12)
    if i < 5:
        arrow(s, x0 + i * (w + gap) + w, 2.97, x0 + (i + 1) * (w + gap), 2.97, color=GREY, w=2.25)
card(s, 0.4, 4.6, 4.0, 2.2, "Answers are grounded", "Every claim must cite a retrieved passage. Citations to papers that were never retrieved are replaced and flagged. A research-use-only note is appended.", accent=GREEN, bsize=12)
card(s, 4.65, 4.6, 4.0, 2.2, "Never fails silently", "Deep Agent → plain retrieval-augmented answer → extractive answer from top passages. The chat shows which engine and model answered.", accent=AMBER, bsize=12)
card(s, 8.9, 4.6, 4.0, 2.2, "Confidential papers stay local", "If a selected paper is confidential, the external LLM is not called: the answer is built locally from the passages.", accent=ROSE, bsize=12)

# =========================================================== 8. LLM gateway & fallback
s = new_slide("LLM gateway & fallback strategy", "LiteLLM in front of Groq: a retired or failing model never breaks the app",
              notes="Primary is Qwen3 27B; we replaced Llama 3.2 because Groq has retired it (model_not_found). Fallback is gpt-oss-120b. In live use the fallback absorbs primary failures and rate limits inside the same request.")
box(s, 0.5, 2.7, 1.9, 1.2, "Request\n(extract · chat)", fill=WHITE, line=INDIGO, lw=1.5, size=14, bold=True, align=PP_ALIGN.CENTER)
box(s, 3.3, 1.75, 3.0, 1.35, [("Primary", {"bold": True, "size": 12, "color": INDIGO}), ("Qwen3 27B (Groq)", {"bold": True, "size": 15}), ("tried first on every request", {"size": 11})],
    fill="EEF2FF", line=INDIGO, lw=2, align=PP_ALIGN.CENTER)
box(s, 3.3, 3.95, 3.0, 1.35, [("Fallback", {"bold": True, "size": 12, "color": AMBER}), ("gpt-oss-120b (Groq)", {"bold": True, "size": 15}), ("answers in the same request", {"size": 11})],
    fill="FEF3C7", line=AMBER, lw=2, align=PP_ALIGN.CENTER, dash=True)
box(s, 7.25, 2.7, 1.9, 1.2, "Response\n+ model used", fill=WHITE, line=GREEN, lw=1.5, size=14, bold=True, align=PP_ALIGN.CENTER)
arrow(s, 2.4, 3.3, 3.3, 2.45, color=INDIGO, w=2.5)
arrow(s, 6.3, 2.45, 7.25, 3.15, color=GREEN, w=2.5)
arrow(s, 4.8, 3.1, 4.8, 3.95, color=ROSE, w=2.5)
label(s, 4.9, 3.3, 2.2, 0.5, "error · rate limit ·\ntimeout · retired model", size=10.5, color=ROSE)
arrow(s, 6.3, 4.6, 8.2, 3.9, color=AMBER, w=2.5)
box(s, 0.5, 5.65, 8.65, 1.25, [("Circuit breaker", {"bold": True, "size": 13, "color": INDIGO}),
    ("After 2 consecutive primary failures the primary is skipped for 5 minutes (no more wasted calls), then re-probed with a single request.", {"size": 12})],
    fill=WHITE, line=LINE, anchor=MSO_ANCHOR.MIDDLE)
card(s, 9.5, 1.5, 3.4, 1.7, "Every attempt is logged", "Table llm_calls: model, task, tokens, latency, status, error type, paper.", accent=INDIGO, bsize=12)
card(s, 9.5, 3.4, 3.4, 1.75, "SQL view v_llm_fallbacks", "One row per request served by the fallback, with the primary failure that triggered it.", accent=AMBER, bsize=12)
card(s, 9.5, 5.35, 3.4, 1.55, "Models tab in the UI", "Primary vs fallback health, who is serving now, fallback events.", accent=GREEN, bsize=12)

# =========================================================== 9. Tech stack
s = new_slide("Technology stack", "Python backend, React frontend, SQLite everywhere, open tooling around the LLM",
              notes="Each layer and why it was chosen. SQLite keeps the footprint minimal: files, FTS5 search, vectors, jobs and logs live in one file.")
stack = [("Frontend", "React 18 · Vite · hand-built SVG charts · toast notifications", INDIGO),
         ("Backend", "Python · FastAPI · Pydantic · persistent worker threads", TEAL),
         ("Database", "SQLite: BLOB file storage · FTS5 full-text · embeddings · job queue · audit log · SQL views", NAVY),
         ("Agents & LLM", "LangChain Deep Agents (planner + evidence-checker sub-agent) · LiteLLM gateway · Groq: Qwen3 27B, gpt-oss-120b", AMBER),
         ("Retrieval", "BM25 (SQLite FTS5) + semantic search with local embeddings (fastembed, bge-small) fused by score", ROSE),
         ("Document AI", "pypdf · pdfplumber (tables) · RapidOCR + pypdfium2 (scans) · JATS XML · regex & lexicon entity extraction", GREEN),
         ("External APIs", "PubMed E-utilities · bioRxiv / medRxiv API · internal SQLite database connector", TEAL),
         ("Observability", "LangSmith tracing · llm_calls log · tokenomics · evaluation harness", INDIGO)]
for i, (h, b, c) in enumerate(stack):
    card(s, 0.6 + (i % 2) * 6.15, 1.45 + (i // 2) * 1.37, 6.0, 1.25, h, b, accent=c, hsize=14, bsize=12)

# =========================================================== 10. Guardrails
s = new_slide("Guardrails & governance", "Safety is configurable at runtime and tested",
              notes="All guardrails can be toggled from the Guardrails tab. The evaluation matrix measures them: detection rates and false positives.")
card(s, 0.6, 1.5, 4.0, 3.5, "Input guardrails",
     "• Upload validation: type, size, magic bytes\n• Duplicate document blocking\n• Prompt-injection detection in questions and in papers\n• PII redaction before LLM calls and logs\n• No patient-specific medical advice\n• Confidential papers never leave the host", accent=ROSE, bsize=13)
card(s, 4.85, 1.5, 4.0, 3.5, "Output guardrails",
     "• Every extracted fact needs a verbatim evidence quote found in the source\n• Numbers must exist in the source text\n• Citations required; invented citations removed\n• Quote-length cap for copyright\n• Research-use disclaimer", accent=GREEN, bsize=13)
card(s, 9.1, 1.5, 3.8, 3.5, "Traceability",
     "• Audit log per paper: ingest, extract, upgrade\n• Provenance: source, DOI, licence\n• Original file kept in SQLite\n• LangSmith traces\n• Export with evidence", accent=INDIGO, bsize=13)
box(s, 0.6, 5.3, 12.3, 1.45, [("Measured on the evaluation set", {"bold": True, "size": 14, "color": INDIGO}),
    ("Injection detection 100% (6/6), false positives 0% (0/6), PII redaction 4/4, medical-advice block 4/4, bad uploads rejected 4/4, fabricated quote rejected. "
     "Small labelled sets: a smoke test, not a certification.", {"size": 13})], fill=WHITE, line=LINE, anchor=MSO_ANCHOR.MIDDLE)

# =========================================================== 11. Evaluation & results
s = new_slide("Evaluation & results", "A built-in benchmark plus automated tests",
              notes="All numbers here were measured. The benchmark uses 6 synthetic papers and the offline extractive engine; the live LLM run covers a single paper. State this openly.")
tiles = [("16 / 16", "benchmark targets pass\n(6 synthetic papers, offline engine)", GREEN),
         ("82", "automated checks pass\n(30 features · 28 gateway · 24 tokenomics)", INDIGO),
         ("12 / 12", "fields extracted live by Qwen3 27B;\n11 verified, 1 flagged", AMBER),
         ("≈ $0.002", "average LLM cost per paper, ~4 s\n(~3,400 tokens; Qwen $0.005, gpt-oss $0.001)", ROSE)]
for i, (big, small, c) in enumerate(tiles):
    x = 0.6 + i * 3.1
    box(s, x, 1.5, 2.95, 1.9, "", fill=WHITE, line=c, lw=2)
    label(s, x + 0.1, 1.6, 2.75, 0.8, big, size=32, bold=True, color=c, align=PP_ALIGN.CENTER)
    label(s, x + 0.1, 2.5, 2.75, 0.9, small, size=12, color=INK, align=PP_ALIGN.CENTER)
label(s, 0.6, 3.62, 6, 0.42, "Evaluation matrix", size=16, bold=True, color=INDIGO)
label(s, 0.6, 4.1, 6.2, 2.85, ["Parsing: section segmentation accuracy", "Extraction: fact recall (12 fields), entity recall, keyword F1",
                                "Summaries: ROUGE-1 / 2 / L", "Faithfulness: grounding rate, hallucination rate, numeric support",
                                "Retrieval: recall@k, MRR, paraphrase recall (keyword vs semantic vs hybrid)", "De-duplication accuracy",
                                "Guardrails: injection TPR/FPR, PII, advice block", "Performance: latency p50/p95, review-time reduction"], size=12.5)
card(s, 7.1, 3.65, 5.8, 3.2, "How to read these results",
     "• Benchmark data is synthetic and small by design (development testing)\n• Hybrid search fixed a real weakness: paraphrase queries 0.67 → 1.0\n• LLM accuracy on real papers is not yet measured; the next step is a larger SME-annotated gold set\n• Run it yourself: python -m app.eval.runner [--llm]", accent=AMBER, bsize=12.5)

# =========================================================== 12. Business impact & tokenomics
s = new_slide("Business impact & tokenomics", "Cost, speed and trade-offs are measured inside the app",
              notes="Assumptions drive the saving: 20 minutes manual review, $60 per hour, 1,000 papers per month. All three are editable in the Tokenomics tab. The saving excludes human QA, infrastructure and engineering.")
label(s, 0.6, 1.42, 6.4, 0.42, "Illustrative economics (editable assumptions)", size=16, bold=True, color=INDIGO)
rows_ = [("", "Manual review", "With AI extraction"), ("Time per paper", "20 min", "≈ 4 s of LLM time"), ("Cost per paper", "$20.00 (at $60/h)", "≈ $0.002 (measured)"),
         ("1,000 papers / month", "$20,000 · 333 h", "≈ $2-5 of LLM cost")]
t = s.shapes.add_table(len(rows_), 3, Inches(0.6), Inches(1.9), Inches(6.6), Inches(2.2)).table
for r, row in enumerate(rows_):
    for c, v in enumerate(row):
        cell = t.cell(r, c)
        cell.fill.solid(); cell.fill.fore_color.rgb = rgb(NAVY if r == 0 else (WHITE if r % 2 else "EEF2FF"))
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.text_frame.text = v
        run = cell.text_frame.paragraphs[0].runs[0] if cell.text_frame.paragraphs[0].runs else None
        if run:
            run.font.size, run.font.name, run.font.bold = Pt(14), FONT, (r == 0 or c == 0)
            run.font.color.rgb = rgb(WHITE if r == 0 else INK)
label(s, 0.6, 4.2, 6.6, 0.9, "Excludes human QA of the AI output, infrastructure and engineering cost: treat the saving as an upper bound.", size=12, color=GREY)
card(s, 0.6, 5.05, 6.6, 1.8, "Problem-statement coverage (self-assessed)",
     "Challenge-by-challenge checklist: 93% average across the four challenges (all above 90%). Remaining gaps: LLM accuracy on real papers, load at thousands of papers per month, authentication.", accent=GREEN, bsize=12)
card(s, 7.6, 1.45, 5.3, 2.35, "What the Tokenomics tab shows",
     "• Tokens, cost, latency and tokens/second per model and task\n• Quality vs cost vs speed per engine\n• What-if: same workload on other models\n• Daily token budget", accent=INDIGO, bsize=12.5)
card(s, 7.6, 4.0, 5.3, 2.85, "Trade-offs made visible",
     "• Cost of resilience: time lost on failed primary calls vs money saved by the circuit breaker\n• Cheaper models vs verified-field quality\n• Prices from LiteLLM's price map, editable; unknown prices are flagged, never guessed", accent=AMBER, bsize=12.5)

# =========================================================== 13. Limitations & roadmap
s = new_slide("Honest limits & roadmap", "What is proven today and what comes next",
              notes="Be transparent: the accuracy figures come from synthetic data; the LLM extraction has only been run live on a few papers.")
card(s, 0.6, 1.5, 6.0, 5.35, "Known limitations",
     "• Accuracy is validated on synthetic papers; real-paper accuracy of the LLM engine still to be measured\n• Qwen3 on Groq can hit rate limits under bursts; the fallback absorbs them, but sustained load needs a higher tier\n• Entities come from lexicons, not a trained biomedical NER\n• Only ruled tables are detected; supplementary files not handled\n• Not load-tested at thousands of papers per month\n• No login or roles yet; PDFs are stored unencrypted", accent=ROSE, bsize=13)
card(s, 6.9, 1.5, 6.0, 5.35, "Roadmap",
     "1. SME-annotated gold set (30-50 real papers) and LLM-as-judge scoring\n2. Authentication, roles, per-paper access and encryption at rest\n3. Licence-aware file serving\n4. Connectors: SharePoint, ELN, REST; scale beyond SQLite with Postgres + pgvector\n5. Biomedical NER and richer visualisation\n6. Model routing by task: cheap model for summaries, stronger one for extraction", accent=GREEN, bsize=13)

# =========================================================== 14. Thank you
s = new_slide(dark=True, notes="Close with the team and invite questions.")
box(s, 0, 0, 0.25, 7.5, "", fill=INDIGO, line=None, shape=MSO_SHAPE.RECTANGLE)
label(s, 0.9, 1.3, 11, 1.0, "Thank you", size=48, bold=True, color=WHITE)
label(s, 0.9, 2.35, 11, 0.6, "Team Friday Forever  ·  AI Friday Season 3", size=20, color="A5B4FC")
for i, name in enumerate(TEAM):
    x, y = 0.9 + (i % 3) * 4.0, 3.7 + (i // 3) * 1.2
    lines = [(name, {"bold": True, "size": 18, "color": WHITE})] + ([(IDS[name], {"size": 13, "color": "A5B4FC"})] if SHOW_IDS else [])
    box(s, x, y, 3.8, 0.95, lines, fill="1E293B", line="334155", align=PP_ALIGN.LEFT)
label(s, 0.9, 6.5, 11, 0.5, "Questions?", size=18, color="CBD5E1")

prs.save(OUT)

# ------------------------------------------------------------------ layout self-check (no renderer available)
EMU = 914400
problems = []
for n, sl in enumerate(prs.slides, start=1):
    for sh in sl.shapes:
        x, y, w, h = sh.left / EMU, sh.top / EMU, sh.width / EMU, sh.height / EMU
        if x < -0.01 or y < -0.01 or x + w > 13.34 or y + h > 7.51:
            problems.append(f"slide {n}: shape outside slide ({x:.2f},{y:.2f},{w:.2f},{h:.2f})")
        if sh.has_text_frame and sh.text_frame.text.strip() and h > 0.05:
            need = 0.12
            for p in sh.text_frame.paragraphs:
                txt = "".join(r.text for r in p.runs)
                size = (p.runs[0].font.size.pt if p.runs and p.runs[0].font.size else 12)
                for seg in txt.split("\n"):
                    cpl = max((w - 0.2) * 72 / (size * 0.50), 1)
                    need += max(math.ceil(len(seg) / cpl), 1) * size * 1.2 / 72
                need += (p.space_before.pt / 72 if p.space_before else 0)
            if need > h + 0.02 and sh.shape_type != 19:
                problems.append(f"slide {n}: text may overflow ({need:.2f}in needed, {h:.2f}in box): {sh.text_frame.text[:50]!r}")
print(f"saved {OUT}  ({len(prs.slides)} slides)")
print("layout check:", "OK" if not problems else "")
for p in problems:
    print("  -", p.encode("ascii", "replace").decode())
