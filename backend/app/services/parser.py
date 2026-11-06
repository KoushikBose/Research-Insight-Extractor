"""Parsing + normalisation of PDF / JATS-XML / plain-text papers, OCR fallback, table extraction, segmentation."""
import io
import re
import xml.etree.ElementTree as ET

CANON = {
    "abstract": "Abstract", "summary": "Abstract",
    "introduction": "Introduction", "background": "Introduction",
    "materials and methods": "Methods", "methods": "Methods", "methodology": "Methods",
    "experimental": "Methods", "experimental section": "Methods", "patients and methods": "Methods",
    "results": "Results", "results and discussion": "Results", "findings": "Results",
    "discussion": "Discussion",
    "conclusion": "Conclusion", "conclusions": "Conclusion",
    "references": "References", "acknowledgements": "Acknowledgements", "acknowledgments": "Acknowledgements",
}
_HEAD = re.compile(
    r"^\s*(?:\d+[.)]?\s*|[IVX]+[.)]\s*)?(abstract|summary|introduction|background|materials and methods|"
    r"patients and methods|methods|methodology|experimental(?: section)?|results and discussion|results|findings|"
    r"discussion|conclusions?|references|acknowledg(?:e)?ments?)\s*[:.]?\s*$", re.I)

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)
_BAD_TITLE = re.compile(r"(preprint|\bdoi\b|copyright|license|licence|https?:|www\.|all rights reserved|"
                        r"^(authors?|keywords?|published|date|abstract)\b|microsoft word|untitled)", re.I)


def normalize(text: str) -> str:
    text = text.replace("\r", "\n").replace("­", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)           # de-hyphenate line breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_doi(text: str) -> str:
    m = DOI_RE.search(text or "")
    if not m:
        return ""
    doi = re.split(r"(?i)doi:|https?:|www\.", m.group(1))[0]          # PDFs often glue the next word onto the DOI
    return doi.rstrip(".,;:)]}>").lower()


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def ocr_pdf(data: bytes, max_pages: int = 25) -> str:
    """OCR fallback for scanned PDFs (pypdfium2 renders pages, RapidOCR reads them; pure-pip, no Tesseract)."""
    import numpy as np
    import pypdfium2 as pdfium
    from rapidocr_onnxruntime import RapidOCR
    engine, pdf, out = RapidOCR(), pdfium.PdfDocument(data), []
    for i in range(min(len(pdf), max_pages)):
        img = pdf[i].render(scale=2).to_pil().convert("RGB")
        res, _ = engine(np.array(img))
        if res:
            out.append("\n".join(r[1] for r in res))
    return "\n\n".join(out)


def parse_pdf(data: bytes) -> dict:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    ocr_used = False
    if len(text.strip()) < 200:  # scanned / image-only PDF
        try:
            text, ocr_used = ocr_pdf(data), True
        except Exception:  # OCR engine unavailable - keep whatever text exists
            pass
    meta = reader.metadata or {}
    out = guess_metadata(normalize(text))
    mt = (getattr(meta, "title", None) or "").strip()
    if mt and len(mt) >= 15 and not _BAD_TITLE.search(mt):
        out["title"] = mt
    out["ocr"] = ocr_used
    return out


def extract_tables(data: bytes, max_pages: int = 40, max_tables: int = 30) -> list[dict]:
    """Tables from a text-based PDF via pdfplumber. Returns [{page, idx, caption, rows}]."""
    import pdfplumber
    found = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for pno, page in enumerate(pdf.pages[:max_pages], start=1):
            try:
                tables = page.extract_tables()
            except Exception:
                continue
            for i, t in enumerate(tables):
                rows = [[(c or "").replace("\n", " ").strip() for c in r] for r in t if r and any(c for c in r)]
                if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                    m = re.search(r"(Table\s+\d+[^\n]{0,120})", page.extract_text() or "")
                    found.append({"page": pno, "idx": i, "caption": m.group(1).strip() if m else f"Table (p.{pno})",
                                  "rows": rows[:60]})
                    if len(found) >= max_tables:
                        return found
    return found


_FIG = re.compile(r"^\s*((?:Supplementary\s+|Extended\s+Data\s+)?Fig(?:ure)?\.?\s*S?\d+[A-Za-z]?)\s*[.:|–-]\s*(\S[^\n]{8,400})",
                  re.I | re.M)


def extract_figures(data: bytes, max_pages: int = 60, max_figs: int = 40) -> list[dict]:
    """Figure captions (incl. supplementary figures) with page numbers - the text of figures is what is searchable."""
    import pdfplumber
    found, seen = [], set()
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for pno, page in enumerate(pdf.pages[:max_pages], start=1):
            for m in _FIG.finditer(page.extract_text() or ""):
                label = re.sub(r"\s+", " ", m.group(1)).strip()
                key = (label.lower(), m.group(2)[:40].lower())
                if key in seen:
                    continue
                seen.add(key)
                found.append({"page": pno, "label": label, "caption": m.group(2).strip()})
                if len(found) >= max_figs:
                    return found
    return found


def parse_text(data: bytes) -> dict:
    return guess_metadata(normalize(data.decode("utf-8", errors="replace")))


def parse_xml(data: bytes) -> dict:
    """JATS (PubMed Central / bioRxiv) article XML."""
    root = ET.fromstring(data)

    def txt(el):
        return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""

    title = txt(root.find(".//article-title"))
    authors = []
    for c in root.findall(".//contrib[@contrib-type='author']"):
        sur, giv = txt(c.find(".//surname")), txt(c.find(".//given-names"))
        if sur:
            authors.append(f"{giv} {sur}".strip())
    y, m, d = (txt(root.find(f".//pub-date/{t}")) for t in ("year", "month", "day"))
    date = "-".join(x.zfill(2) if i else x for i, x in enumerate([y, m, d]) if x)
    kws = [txt(k) for k in root.findall(".//kwd")]
    doi = txt(root.find(".//article-id[@pub-id-type='doi']")).lower()
    sections = []
    ab = root.find(".//abstract")
    if ab is not None:
        sections.append({"name": "Abstract", "text": normalize(txt(ab))})
    for sec in root.findall(".//body/sec"):
        name = CANON.get(txt(sec.find("title")).lower().strip(), txt(sec.find("title")) or "Body")
        paras = [txt(p) for p in sec.findall(".//p")]
        sections.append({"name": name, "text": normalize("\n".join(paras))})
    return {"title": title, "authors": authors, "pub_date": date, "keywords": kws, "sections": sections,
            "doi": doi, "text": "\n\n".join(s["text"] for s in sections)}


def pick_title(lines):
    for l in lines[:20]:
        if l.lower().startswith("title:"):
            return l[6:].strip()
    cands = [l for l in lines[:25] if 20 <= len(l) <= 250 and len(l.split()) >= 4 and not _BAD_TITLE.search(l)
             and not re.match(r"^[\W\d]+$", l)]
    return cands[0] if cands else (lines[0][:250] if lines else "")


def guess_metadata(text: str) -> dict:
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    title = pick_title(lines)
    authors, keywords, date = [], [], ""
    for l in lines[:25]:
        if re.match(r"^authors?\s*:", l, re.I):
            authors = [a.strip() for a in re.split(r"[;,]", l.split(":", 1)[1]) if a.strip()]
        elif re.match(r"^key\s?words?\s*:", l, re.I):
            keywords = [k.strip() for k in re.split(r"[;,]", l.split(":", 1)[1]) if k.strip()]
        elif re.match(r"^(published|date)\s*:", l, re.I):
            m = re.search(r"(19|20)\d{2}(-\d{2}(-\d{2})?)?", l)
            date = m.group(0) if m else ""
    return {"title": title, "authors": authors, "pub_date": date, "keywords": keywords,
            "sections": segment(text), "text": text, "doi": extract_doi(text[:6000])}


def segment(text: str):
    """Split plain text into canonical IMRaD sections using heading detection."""
    sections, cur_name, cur = [], None, []
    preamble = []
    for line in text.split("\n"):
        m = _HEAD.match(line)
        if m:
            if cur_name is not None:
                sections.append({"name": cur_name, "text": "\n".join(cur).strip()})
            cur_name, cur = CANON.get(m.group(1).lower(), m.group(1).title()), []
        elif cur_name is None:
            preamble.append(line)
        else:
            cur.append(line)
    if cur_name is not None:
        sections.append({"name": cur_name, "text": "\n".join(cur).strip()})
    if not sections:
        return [{"name": "Full Text", "text": text.strip()}]
    pre = "\n".join(preamble).strip()
    if pre and len(pre.split()) > 30:
        sections.insert(0, {"name": "Front Matter", "text": pre})
    return [s for s in sections if s["text"]]


def parse_any(filename: str, data: bytes) -> dict:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else "txt"
    if ext == "pdf":
        return parse_pdf(data)
    if ext == "xml":
        return parse_xml(data)
    return parse_text(data)
