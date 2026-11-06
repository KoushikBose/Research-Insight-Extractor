"""Lexicon + pattern based biomedical entity extraction (no model download, deterministic, fast).

Types: gene_protein, drug_compound, dose, disease, assay, model_organism.
Precision is moderate by design (lexicons are small); the LLM keyword pass complements it.
"""
import re
from collections import Counter

ASSAYS = ["ELISA", "qPCR", "RT-PCR", "PCR", "western blot", "flow cytometry", "MRI", "HPLC", "mass spectrometry",
          "RNA-seq", "next-generation sequencing", "sequencing", "immunohistochemistry", "immunofluorescence", "microscopy",
          "Morris water maze", "patch clamp", "annexin V", "luciferase assay", "CRISPR screen", "MAGeCK", "ANOVA",
          "Student's t-test", "Cochran-Mantel-Haenszel", "Kaplan-Meier", "log-rank"]
DISEASES = ["rheumatoid arthritis", "arthritis", "alzheimer's disease", "alzheimer", "parkinson's disease", "cancer",
            "carcinoma", "adenocarcinoma", "pancreatic ductal adenocarcinoma", "leukemia", "lymphoma", "melanoma", "glioma",
            "diabetes", "hypertension", "asthma", "sepsis", "obesity", "fibrosis", "stroke", "tumor", "tumour",
            "neuroinflammation", "infection", "covid-19", "malaria", "tuberculosis", "autoimmune disease"]
MODELS = ["5xFAD", "C57BL/6", "BALB/c", "NOD/SCID", "mice", "mouse", "rats", "rat", "zebrafish", "xenograft",
          "cell line", "cell lines", "patients", "participants", "volunteers", "HeLa", "HEK293", "PANC-1", "MIA PaCa-2",
          "AsPC-1", "HPAF-II", "A549", "MCF-7", "Jurkat", "HepG2", "U2OS"]
STOP_UPPER = set("""PDF DNA RNA USA THE AND FOR NOT BUT ARE WAS CI SD SE AUC ROC FDA WHO II III IV VI VII VIII IX XI
CC BY NC ND SA ELISA PCR MRI HPLC ANOVA RCT FIG TABLE RA ACR20 ACR50 ACR70 DOI NIH GMP ICU BMI""".split())

_DOSE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:mg/kg|mg|µg|μg|ug|mL|ml|nM|µM|μM|mM|g/kg|IU)\b")
_COMPOUND = re.compile(r"\b[A-Z]{1,3}-\d{2,4}\b")
_DRUG_SUFFIX = re.compile(r"\b[A-Za-z]{3,}(?:mab|nib|statin|vir|cillin|formin|zumab|ciclib|parib|tinib|sartan)\b")
_GENE = re.compile(r"\b[A-Z][A-Z0-9]{1,7}(?:-\d{1,2})?\b")
_DIS_SUFFIX = re.compile(r"\b[a-z]{4,}(?:itis|oma|pathy|aemia|emia)\b")


def _count_lex(text, lex, ci=True):
    out = Counter()
    low = text.lower()
    for term in sorted(lex, key=len, reverse=True):
        n = len(re.findall(r"(?<![\w-])" + re.escape(term.lower() if ci else term) + r"(?![\w])", low if ci else text))
        if n:
            out[term] += n
    return out


# Boilerplate printed on PDFs (licence lines, URLs, DOIs, preprint banners) that is not scientific content.
_URL = re.compile(r"(?:https?://|www\.)\S+|\bdoi:\s*\S+|\b10\.\d{4,9}/\S+", re.I)
JUNK = {"https", "http", "doi", "org", "www", "com", "preprint", "biorxiv", "medrxiv", "copyright", "license", "licence", "author", "authors",
        "funder", "peer", "reviewed", "certified", "international", "creative", "commons", "available", "perpetuity", "granted", "holder",
        "cc", "by", "nc", "nd", "sa", "cc-by", "cc-by-nc", "cc-by-nc-nd", "cc-by-nd", "cc-by-sa", "cc-", "et al", "fig", "figure", "table"}
_LICENCE = re.compile(r"^(?:cc|by|nc|nd|sa)(?:[-\s](?:cc|by|nc|nd|sa))*-?$", re.I)


_BOILER = re.compile(r"[^.\n]*(?:made available under|all rights reserved|in perpetuity|certified by peer review|copyright holder|creative commons|"
                     r"not peer.reviewed|preprint \(which)[^.\n]*[.\n]?", re.I)


def strip_boilerplate(text: str) -> str:
    """Remove URLs, DOIs and licence / preprint-banner sentences before mining terms from a paper."""
    return _BOILER.sub(" ", _URL.sub(" ", text))


def is_junk(term: str) -> bool:
    t = (term or "").strip().lower()
    words = [w for w in re.split(r"[\s-]+", t) if w]
    return (len(t) < 2 or t in JUNK or bool(_LICENCE.match(t)) or t.startswith(("http", "www.")) or "doi.org" in t
            or (bool(words) and all(w in JUNK for w in words)))


def clean_terms(terms):
    return [t for t in terms if not is_junk(t)]


def extract_entities(text: str, top: int = 12) -> dict:
    text = strip_boilerplate(text)
    drugs = Counter(m.group(0) for m in _COMPOUND.finditer(text))
    drugs.update(m.group(0).lower() for m in _DRUG_SUFFIX.finditer(text))
    taken = set(drugs)
    assays = _count_lex(text, ASSAYS)
    diseases = _count_lex(text, DISEASES)
    diseases.update(m.group(0) for m in _DIS_SUFFIX.finditer(text))
    models = _count_lex(text, MODELS)
    skip = STOP_UPPER | {a.upper() for a in ASSAYS}
    genes = Counter()
    for m in _GENE.finditer(text):
        t = m.group(0)
        if t in skip or t in taken or _COMPOUND.fullmatch(t) or t.isdigit():
            continue
        if any(t in d for d in drugs):      # fragment of a compound code (e.g. ZX of ZX-114)
            continue
        genes[t] += 1
    genes = Counter({k: v for k, v in genes.items() if v >= 2 or "-" in k or any(c.isdigit() for c in k)})
    doses = Counter(m.group(0).replace("  ", " ") for m in _DOSE.finditer(text))
    pack = lambda c: [{"text": k, "count": v} for k, v in c.most_common(top + 6) if not is_junk(k)][:top]
    return {"gene_protein": pack(genes), "drug_compound": pack(drugs), "dose": pack(doses),
            "disease": pack(diseases), "assay": pack(assays), "model_organism": pack(models)}


def flat_names(ents: dict) -> list[str]:
    return [e["text"] for v in ents.values() for e in v]
