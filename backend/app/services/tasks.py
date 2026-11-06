"""Job handlers (registered with the queue by import)."""
from . import connectors, ingest, jobs, monitor


@jobs.register("extract")
def _extract(paper_id: int):
    ingest.run_extraction(paper_id)
    ingest.post_process(paper_id)      # tables + semantic index
    return {"paper_id": paper_id}


def _enqueue_extracts(res):
    for pid in res.get("ingested", []):
        jobs.enqueue("extract", {"paper_id": pid})
    return {**res, "ingested": len(res.get("ingested", []))}


@jobs.register("bulk_pubmed")
def _bulk_pubmed(query: str, n: int = 10):
    return _enqueue_extracts(connectors.ingest_pubmed(query, n))


@jobs.register("bulk_biorxiv")
def _bulk_biorxiv(query: str = "", days: int = 7, server: str = "biorxiv", n: int = 10):
    return _enqueue_extracts(connectors.ingest_biorxiv(query, days, server, n))


@jobs.register("import_sql")
def _import_sql(**kw):
    return _enqueue_extracts(connectors.sql_import(**kw))


@jobs.register("import_folder")
def _import_folder():
    res = ingest.ingest_folder()
    for r in res:
        if r.get("id") and not r.get("duplicate"):
            jobs.enqueue("extract", {"paper_id": r["id"]})
    return {"files": len(res), "new": sum(1 for r in res if r.get("id") and not r.get("duplicate"))}


@jobs.register("monitor_run")
def _monitor(search_id: int):
    return monitor.run_search(search_id)


@jobs.register("post_process")
def _post(paper_id: int):
    ingest.post_process(paper_id)
    return {"paper_id": paper_id}
