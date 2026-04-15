"""
Bulk-import product photos from product_catalog/ into the database.

Steps per image:
  1. Convert HEIC → JPEG (sips, macOS built-in)
  2. Resize to max 1600px on the longest side
  3. Call Groq Vision (Llama 4 Scout) → extract name, code, weight, specs, category
  4. Save image to uploads/ and insert into products + product_images tables

Run:  python3 import_catalog.py
"""

import os
import sys
import uuid
import base64
import json
import shutil
import subprocess
import time
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv
from database import init_db, db_context

load_dotenv(Path(__file__).parent / ".env")

CATALOG_DIR = Path(__file__).parent / "product_catalog"
UPLOAD_DIR  = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

GROQ_MODEL    = "meta-llama/llama-4-scout-17b-16e-instruct"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

API_KEY = os.getenv("GROQ_API_KEY")
if not API_KEY:
    sys.exit("ERROR: GROQ_API_KEY not set in .env")

client = OpenAI(api_key=API_KEY, base_url=GROQ_BASE_URL)

EXTRACT_PROMPT = """You are analyzing a warehouse/shop product photo.

Look carefully — read ALL visible text on labels, packaging, stickers, tags, or the product itself.

Return ONLY a JSON object (no markdown, no explanation):
{
  "name": "<product name — brand + model/type if visible, else describe what it is>",
  "code": "<product code, SKU, part number, or barcode number if visible — else empty string>",
  "weight": "<weight shown on product/packaging e.g. '450g', '2.3kg' — else empty string>",
  "category": "<best category: Safety, Electrical, Plumbing, Tools, Hardware, Adhesives, Fasteners, etc.>",
  "specs": "<key specs: size, material, voltage, rating, color, quantity, certification — concise>"
}

If text is partially visible or blurry, do your best. If a field truly can't be determined, use empty string."""


def heic_to_jpeg(heic_path: Path, out_path: Path, max_px: int = 1600) -> bool:
    result = subprocess.run(
        ["sips", "-s", "format", "jpeg", "-Z", str(max_px), str(heic_path), "--out", str(out_path)],
        capture_output=True, text=True,
    )
    return result.returncode == 0 and out_path.exists()


def analyze_image(jpeg_path: Path) -> dict:
    b64  = base64.standard_b64encode(jpeg_path.read_bytes()).decode()
    r = client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": EXTRACT_PROMPT},
            ],
        }],
    )
    raw = r.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


def already_imported(original_filename: str) -> bool:
    with db_context() as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE notes LIKE ?",
            (f"%[src:{original_filename}]%",)
        ).fetchone()
    return row is not None


def import_image(heic_path: Path, index: int, total: int):
    src_name = heic_path.name
    print(f"\n[{index}/{total}] {src_name}")

    if already_imported(src_name):
        print("  → already imported, skipping")
        return

    tmp_jpg = Path(f"/tmp/pf_{uuid.uuid4().hex}.jpg")
    if not heic_to_jpeg(heic_path, tmp_jpg):
        print("  ✗ HEIC conversion failed")
        return
    print(f"  ✓ converted ({tmp_jpg.stat().st_size // 1024} KB)")

    try:
        info = analyze_image(tmp_jpg)
    except json.JSONDecodeError as e:
        print(f"  ✗ JSON parse error: {e}")
        tmp_jpg.unlink(missing_ok=True)
        return
    except Exception as e:
        print(f"  ✗ API error: {e}")
        tmp_jpg.unlink(missing_ok=True)
        return

    name     = (info.get("name")     or "").strip() or src_name
    code     = (info.get("code")     or "").strip()
    weight   = (info.get("weight")   or "").strip()
    category = (info.get("category") or "").strip()
    specs    = (info.get("specs")    or "").strip()

    display_name = f"[{code}] {name}" if code else name
    notes = f"[src:{src_name}]"

    print(f"  → {display_name}")
    if weight:   print(f"     weight:   {weight}")
    if category: print(f"     category: {category}")
    if specs:    print(f"     specs:    {specs[:80]}")

    dest_filename = f"{uuid.uuid4().hex}.jpg"
    shutil.copy2(tmp_jpg, UPLOAD_DIR / dest_filename)
    tmp_jpg.unlink(missing_ok=True)

    with db_context() as conn:
        cur = conn.execute(
            "INSERT INTO products (name, specs, weight, category, notes) VALUES (?,?,?,?,?)",
            (display_name, specs, weight, category, notes),
        )
        pid = cur.lastrowid
        conn.execute(
            "INSERT INTO product_images (product_id, filename, is_primary) VALUES (?,?,1)",
            (pid, dest_filename),
        )
    print(f"  ✓ saved as product #{pid}")


def main():
    init_db()

    heic_files = sorted(CATALOG_DIR.glob("*.HEIC")) + sorted(CATALOG_DIR.glob("*.heic"))
    if not heic_files:
        print("No .HEIC files found in product_catalog/")
        return

    total = len(heic_files)
    print(f"Found {total} images. Importing with Groq ({GROQ_MODEL})...\n")

    failed = []
    for i, path in enumerate(heic_files, 1):
        try:
            import_image(path, i, total)
        except Exception as e:
            print(f"  ✗ unexpected error: {e}")
            failed.append(path.name)
        if i < total:
            time.sleep(0.3)

    print(f"\n{'='*50}")
    print(f"Done. {total - len(failed)} imported, {len(failed)} failed.")
    if failed:
        print("Failed:", ", ".join(failed))


if __name__ == "__main__":
    main()
