import sqlite3
import json
import os
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
            CREATE TABLE IF NOT EXISTS products (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                specs       TEXT,
                weight      TEXT,
                category    TEXT,
                notes       TEXT,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS product_images (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                filename    TEXT NOT NULL,
                is_primary  INTEGER DEFAULT 0,
                uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)

    # Auto-seed from seed_data.json if DB is empty and seed file exists
    with db_context() as conn:
        count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count == 0 and SEED_FILE.exists():
            data = json.loads(SEED_FILE.read_text())
            for p in data.get("products", []):
                conn.execute(
                    "INSERT INTO products (id, name, specs, weight, category, notes, created_at) VALUES (?,?,?,?,?,?,?)",
                    (p["id"], p["name"], p.get("specs",""), p.get("weight",""),
                     p.get("category",""), p.get("notes",""), p.get("created_at","")),
                )
            for i in data.get("images", []):
                conn.execute(
                    "INSERT INTO product_images (id, product_id, filename, is_primary) VALUES (?,?,?,?)",
                    (i["id"], i["product_id"], i["filename"], i.get("is_primary", 0)),
                )
            print(f"[DB] Seeded {len(data['products'])} products from seed_data.json")
