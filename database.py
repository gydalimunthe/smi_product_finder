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

            CREATE TABLE IF NOT EXISTS products (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                code        TEXT    NOT NULL,
                category    TEXT    NOT NULL,
                dimensions  TEXT,
                weight      TEXT,
                bar_profile TEXT,
                paired_with TEXT,
                description TEXT,
                source_page INTEGER,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_products_category
                ON products(category);
            CREATE INDEX IF NOT EXISTS idx_products_code
                ON products(code);
        """)

    # Seed from seed_data.json if DB is empty
    with db_context() as conn:
        page_count    = conn.execute("SELECT COUNT(*) FROM catalog_pages").fetchone()[0]
        product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]

        if not SEED_FILE.exists():
            return

        data = json.loads(SEED_FILE.read_text())

        if page_count == 0:
            for p in data.get("pages", []):
                conn.execute(
                    "INSERT OR IGNORE INTO catalog_pages"
                    " (page_number, category, image_filename, product_codes)"
                    " VALUES (?,?,?,?)",
                    (p["page_number"], p["category"],
                     p["image_filename"], p["product_codes"]),
                )
            print(f"[DB] Seeded {len(data.get('pages', []))} catalog pages")

        if product_count == 0:
            for p in data.get("products", []):
                conn.execute(
                    "INSERT INTO products"
                    " (code, category, dimensions, weight, bar_profile,"
                    "  paired_with, description, source_page)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (p["code"], p["category"], p.get("dimensions"),
                     p.get("weight"), p.get("bar_profile"),
                     p.get("paired_with"), p.get("description"),
                     p.get("source_page")),
                )
            print(f"[DB] Seeded {len(data.get('products', []))} products")
