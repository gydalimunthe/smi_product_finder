import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path

DB_PATH   = Path(__file__).parent / "products.db"
SEED_FILE = Path(__file__).parent / "seed_data.json"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_context():
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db_context() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS catalog_pages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                page_number     INTEGER NOT NULL UNIQUE,
                category        TEXT    NOT NULL,
                image_filename  TEXT,
                product_codes   TEXT,
                created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)

    # Auto-seed from seed_data.json if DB is empty and seed file exists
    with db_context() as conn:
        count = conn.execute("SELECT COUNT(*) FROM catalog_pages").fetchone()[0]
        if count == 0 and SEED_FILE.exists():
            data = json.loads(SEED_FILE.read_text())
            for p in data.get("pages", []):
                conn.execute(
                    "INSERT OR IGNORE INTO catalog_pages"
                    " (page_number, category, image_filename, product_codes)"
                    " VALUES (?,?,?,?)",
                    (p["page_number"], p["category"],
                     p["image_filename"], p["product_codes"]),
                )
            print(f"[DB] Seeded {len(data['pages'])} catalog pages from seed_data.json")
