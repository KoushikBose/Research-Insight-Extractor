"""Print how data is stored in SQLite.  Usage: python scripts/inspect_db.py"""
import sqlite3, sys
from pathlib import Path
db = Path(__file__).resolve().parent.parent / "data" / "app.db"
c = sqlite3.connect(db); c.row_factory = sqlite3.Row
print("DB file:", db, f"({db.stat().st_size/1024:.0f} KB)\n")
for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'chunks_fts_%' ORDER BY name"):
    n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    cols = [r[1] + ("(BLOB)" if r[2] == "BLOB" else "") for r in c.execute(f"PRAGMA table_info({t})")]
    print(f"== {t}  rows={n}\n   columns: {', '.join(cols)}")
print("\n-- papers + stored original file")
for r in c.execute("SELECT p.id,substr(p.title,1,45) title,p.source,p.status,f.filename,f.mime,f.size,hex(substr(f.data,1,8)) first_bytes "
                   "FROM papers p LEFT JOIN files f ON f.paper_id=p.id"):
    print(dict(r))
print("\n-- sections")
for r in c.execute("SELECT paper_id,name,length(text) chars FROM sections ORDER BY paper_id,ord LIMIT 15"):
    print(dict(r))
