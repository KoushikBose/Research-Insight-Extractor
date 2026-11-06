"""PubMed E-utilities client (public API). Only abstracts/metadata are fetched (open to all)."""
import re
import xml.etree.ElementTree as ET

import httpx

from ..config import settings

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _params(extra):
    p = {"tool": "insight-extractor", **extra}
    if settings.NCBI_EMAIL:
        p["email"] = settings.NCBI_EMAIL
    if settings.NCBI_API_KEY:
        p["api_key"] = settings.NCBI_API_KEY
    return p


def _txt(el):
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def fetch(pmids: list[str]) -> list[dict]:
    if not pmids:
        return []
    r = httpx.get(f"{BASE}/efetch.fcgi", params=_params({"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}),
                  timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for art in root.findall(".//PubmedArticle"):
        pmid = _txt(art.find(".//PMID"))
        abstract_parts = []
        for a in art.findall(".//Abstract/AbstractText"):
            label = a.get("Label")
            abstract_parts.append(f"{label.title()}: {_txt(a)}" if label else _txt(a))
        authors = [f"{_txt(a.find('ForeName'))} {_txt(a.find('LastName'))}".strip()
                   for a in art.findall(".//Author") if a.find("LastName") is not None][:12]
        y = _txt(art.find(".//PubDate/Year")) or _txt(art.find(".//PubDate/MedlineDate"))[:4]
        kws = [_txt(k) for k in art.findall(".//Keyword")] or [_txt(m.find("DescriptorName"))
                                                               for m in art.findall(".//MeshHeading")][:8]
        doi = next((_txt(i).lower() for i in art.findall(".//ArticleId") if i.get("IdType") == "doi"), "")
        out.append({"pmid": pmid, "doi": doi, "title": _txt(art.find(".//ArticleTitle")), "authors": authors,
                    "pub_date": y, "keywords": kws, "journal": _txt(art.find(".//Journal/Title")),
                    "abstract": "\n".join(abstract_parts)})
    return out


def search(query: str, n: int = 10, sort: str = "relevance") -> list[dict]:
    r = httpx.get(f"{BASE}/esearch.fcgi", params=_params({"db": "pubmed", "term": query, "retmax": n,
                                                          "retmode": "json", "sort": sort}), timeout=30)
    r.raise_for_status()
    ids = r.json()["esearchresult"].get("idlist", [])
    return fetch(ids)


def to_parsed(rec: dict) -> dict:
    return {"title": rec["title"], "authors": rec["authors"], "pub_date": rec["pub_date"],
            "keywords": rec["keywords"], "doi": rec.get("doi", ""),
            "sections": [{"name": "Abstract", "text": rec["abstract"]}] if rec["abstract"] else [],
            "text": rec["abstract"]}
