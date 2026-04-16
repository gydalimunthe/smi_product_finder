"""
One-time setup script:
  1. Converts each Maxweld catalog PDF → JPEG (stored in static/catalog_pages/)
  2. Extracts product codes per page (for AI context)
  3. Writes seed_data.json  (pages format)
  4. Rebuilds products.db   (catalog_pages table)

Run: python3 setup_pages.py
"""

import json
import re
import sqlite3
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium

PDF_DIR    = Path("/Users/Rafikaaa_ND/Downloads/maxweld_catalog_first4rows")
PROJECT    = Path(__file__).parent
PAGES_DIR  = PROJECT / "static" / "catalog_pages"
THUMBS_DIR = PROJECT / "static" / "catalog_thumbs"
SEED_FILE  = PROJECT / "seed_data.json"
DB_PATH    = PROJECT / "products.db"

PAGES_DIR.mkdir(parents=True, exist_ok=True)
THUMBS_DIR.mkdir(parents=True, exist_ok=True)

# ── Correct category per page ───────────────────────────────────────────────
CATEGORY_MAP = {
    1:  "Forged Flower Panel Designs",
    2:  "Forged Flower Panel Designs",
    3:  "Forged Flower Panel Designs",
    4:  "Forged Flower Door Panel Designs",
    5:  "Forged Flower Designs",
    6:  "Forged Flower Grape Designs",
    7:  "Forged Scroll Designs",
    8:  "Forged Scroll Tops",
    9:  "Forged Steel Scrolls",
    10: "Forged Scrolls",
    11: "Forged Scrolls Baroque End with Line",
    12: "Forged Tapered End Scrolls",
    13: "Forged Snub End Scrolls",
    14: "Hammered Steel Scrolls",
    15: "Tubing Scrolls",
    16: "Tubing Scrolls",
    17: "Forged Scrolls with Leaves",
    18: "Forged Baluster",
    19: "Forged Baluster",
    20: "Forged Baluster",
    21: "Forged Baluster & Post",
    22: "Forged Baluster",
    23: "Pressed Steel Accessory",
    24: "Forged Steel Accessory",
    25: "Forged Steel Leaves",
    26: "Cast Steel Leaves",
    27: "Cast Steel Leaves",
    28: "Cast Steel Accessory",
    29: "Steel Grapes, Leaves & Balls",
    30: "Aluminum Casting Designs",
    31: "Cast Steel Spears & Knuckles",
    32: "Cast Iron Spears",
    33: "Cast Iron Knuckles",
    34: "Cast Iron Cap & Shoe",
    35: "Cast Iron Accessory",
    36: "Welding Hinge Heavy Duty",
    37: "Welding Tabs",
    38: "Tubing Rings, Rollers & Accessories",
    39: "Wheels & Lock Boxes",
    40: "Sleeve Anchors & Wedge Anchors",
    41: "Abrasive Cut Off Wheels & Hardware",
    42: "Hardware & Accessories",
    43: "Rubber Caster with Cast Iron Core",
    44: "Casters",
    45: "Single-Sided Locks",
    46: "Kiaset Type Locks & Code Locks",
    47: "LKPS Stainless Steel Lever Entrance Lock",
    48: "Handrail Components",
    49: "Galvanized V-Track & Steel Cap Rail",
    50: "Welding Supply",
}

# Product code regex — keep L/R and suffix letters
CODE_RE = re.compile(
    r'\b((?:DR|[A-Z]{1,3})?\d{3,5}[A-F]?(?:\s*L/?R)?)\b'
)
JUNK = {"11099", "91733", "626", "444", "1500", "1509"}


def extract_codes(text: str) -> list[str]:
    seen, out = set(), []
    for m in CODE_RE.finditer(text):
        c = m.group(1).strip()
        if c in seen or c.lower() in JUNK or re.match(r'^\d{6,}$', c):
            continue
        seen.add(c)
        out.append(c)
    return out


def make_thumbnail(src: Path, dst: Path, max_width: int = 220):
    from PIL import Image
    img = Image.open(src)
    img.thumbnail((max_width, max_width * 2), Image.LANCZOS)
    img.save(dst, "JPEG", quality=65, optimize=True)


def pdf_to_jpeg(pdf_path: Path, out_path: Path, scale: float = 2.0):
    """Render the first (only) page of a PDF to JPEG."""
    doc  = pdfium.PdfDocument(str(pdf_path))
    page = doc[0]
    bm   = page.render(scale=scale, rotation=0)
    img  = bm.to_pil()
    img.save(str(out_path), "JPEG", quality=88, optimize=True)
    doc.close()


def main():
    pdf_files = sorted(PDF_DIR.glob("p*.pdf"))
    print(f"Found {len(pdf_files)} PDFs in {PDF_DIR}\n")

    pages = []
    for pdf_path in pdf_files:
        num = int(re.search(r'p(\d+)', pdf_path.stem).group(1))
        category = CATEGORY_MAP.get(num, "Ironwork Components")

        # Extract product codes for AI context
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        codes = extract_codes(text)

        # Render PDF → JPEG
        img_name = f"page_{num:02d}.jpg"
        img_path = PAGES_DIR / img_name
        pdf_to_jpeg(pdf_path, img_path, scale=2.0)
        size_kb  = img_path.stat().st_size // 1024

        # Also generate thumbnail
        thumb_path = THUMBS_DIR / img_name
        make_thumbnail(img_path, thumb_path)

        print(f"  p{num:02d}  {category:<45s} {len(codes):3d} codes  {size_kb} KB")

        pages.append({
            "page_number":    num,
            "category":       category,
            "image_filename": img_name,
            "product_codes":  ", ".join(codes),
        })

    # ── seed_data.json ────────────────────────────────────────────────────
    seed = {"pages": pages}
    SEED_FILE.write_text(json.dumps(seed, indent=2, ensure_ascii=False))
    print(f"\nseed_data.json → {len(pages)} pages")

    # ── Rebuild products.db ───────────────────────────────────────────────
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
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
    for p in pages:
        conn.execute(
            "INSERT INTO catalog_pages (page_number, category, image_filename, product_codes)"
            " VALUES (?,?,?,?)",
            (p["page_number"], p["category"], p["image_filename"], p["product_codes"]),
        )
    conn.commit()
    conn.close()
    print(f"products.db      → {len(pages)} rows in catalog_pages")
    print(f"\nImages saved to: {PAGES_DIR}")


if __name__ == "__main__":
    main()
