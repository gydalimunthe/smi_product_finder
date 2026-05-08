import os
import json
from pathlib import Path

from google import genai
from google.genai import types
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from database import init_db, db_context

load_dotenv(Path(__file__).parent / ".env")

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_FILE_SIZE      = 10 * 1024 * 1024
PAGES_DIR          = Path(__file__).parent / "static" / "catalog_pages"
MODEL              = "gemini-2.0-flash"

app = FastAPI(title="Product Finder")
app.mount("/static", StaticFiles(directory="static"), name="static")


def get_client() -> genai.Client:
    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        raise HTTPException(status_code=500, detail="GOOGLE_API_KEY not set")
    return genai.Client(api_key=key)


def ask_gemini(client: genai.Client, image_data: bytes, media_type: str, prompt: str) -> str:
    response = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_bytes(data=image_data, mime_type=media_type),
            prompt,
        ],
    )
    return response.text.strip()


def parse_json(raw: str) -> dict:
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def media_type_for(filename: str) -> str:
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",  ".webp": "image/webp", ".gif": "image/gif",
    }.get(Path(filename or "").suffix.lower(), "image/jpeg")


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def index():
    return FileResponse("static/index.html")

@app.get("/admin")
def admin():
    return FileResponse("static/admin.html")

@app.get("/api/pages")
def list_pages():
    with db_context() as conn:
        rows = conn.execute(
            "SELECT * FROM catalog_pages ORDER BY page_number"
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/identify")
async def identify_product(photo: UploadFile = File(...)):
    ext = Path(photo.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    content = await photo.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Image too large (max 10 MB)")

    media_type = media_type_for(photo.filename or "")
    client     = get_client()

    # ── Get all unique categories from the DB ──────────────────────────────
    with db_context() as conn:
        cat_rows = conn.execute(
            "SELECT DISTINCT category FROM products ORDER BY category"
        ).fetchall()
    categories = [r["category"] for r in cat_rows]

    # ── STEP 1: Classify product category ─────────────────────────────────
    cat_list = "\n".join(f"- {c}" for c in categories)
    step1_prompt = f"""You are a product identification assistant for a Maxweld ironwork warehouse.

Look at this product photo carefully.

Choose the ONE category from the list below that best matches what you see:

{cat_list}

Reply ONLY with valid JSON — no explanation:
{{"category": "<exact category name from the list above>", "confidence": "high"|"medium"|"low"}}"""

    try:
        raw1     = ask_gemini(client, content, media_type, step1_prompt)
        step1    = parse_json(raw1)
        category = step1.get("category", "").strip()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Classification error: {e}")

    # Validate category exists
    if category not in categories:
        # Fuzzy fallback: pick closest by substring
        category = next(
            (c for c in categories if category.lower() in c.lower()
             or c.lower() in category.lower()),
            categories[0],
        )

    # ── STEP 2: Find exact product from category ───────────────────────────
    with db_context() as conn:
        product_rows = conn.execute(
            "SELECT * FROM products WHERE category = ? ORDER BY code",
            (category,),
        ).fetchall()

    if not product_rows:
        return JSONResponse(content={
            "matched": False,
            "message": f"No products found for category '{category}'.",
        })

    # Format product list as compact text for Claude context (RAG)
    product_lines = []
    for p in product_rows:
        parts = [f"Code: {p['code']}"]
        if p["dimensions"]:  parts.append(f"Size: {p['dimensions']}")
        if p["weight"]:      parts.append(f"Weight: {p['weight']}")
        if p["bar_profile"]: parts.append(f"Bar: {p['bar_profile']}")
        if p["paired_with"]: parts.append(f"Pair: {p['paired_with']}")
        product_lines.append(" | ".join(parts))

    product_catalog = "\n".join(product_lines)

    step2_prompt = f"""You are a product identification assistant for a Maxweld ironwork warehouse.

Look at the product in the photo carefully.

Category: {category}

Here are all products in this category from the catalog:
{product_catalog}

Match the product in the photo to the BEST entry in the list above.
Consider shape, size, and style. The code is the bold identifier printed on the catalog page.

Reply ONLY with valid JSON — no explanation:
{{
  "matched": true,
  "product_code": "<exact code from list>",
  "confidence": "high"|"medium"|"low",
  "reason": "<one sentence: specific visual features that matched>"
}}

If nothing matches at all:
{{"matched": false, "reason": "<why>"}}"""

    try:
        raw2   = ask_gemini(client, content, media_type, step2_prompt)
        result = parse_json(raw2)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Identification error: {e}")

    if not result.get("matched"):
        return JSONResponse(content={
            "matched":  False,
            "category": category,
            "reason":   result.get("reason", "No matching product found."),
        })

    # ── Look up full product details ───────────────────────────────────────
    matched_code = result.get("product_code", "").strip()
    with db_context() as conn:
        product = conn.execute(
            "SELECT * FROM products WHERE code = ? AND category = ?",
            (matched_code, category),
        ).fetchone()

        # Fallback: search by code only (category might differ slightly)
        if not product:
            product = conn.execute(
                "SELECT * FROM products WHERE code = ?",
                (matched_code,),
            ).fetchone()

    if not product:
        return JSONResponse(content={
            "matched":  False,
            "category": category,
            "reason":   f"Code {matched_code} not found in database.",
        })

    # ── Build catalog page image URL ───────────────────────────────────────
    pg_num    = product["source_page"]
    image_url = f"/static/catalog_pages/page_{pg_num:02d}.jpg" if pg_num else None

    return {
        "matched":      True,
        "product_code": product["code"],
        "product_name": f"{product['code']} — {product['category']}",
        "category":     product["category"],
        "dimensions":   product["dimensions"],
        "weight":       product["weight"],
        "specs":        product["bar_profile"],
        "paired_with":  product["paired_with"],
        "description":  product["description"],
        "page_number":  pg_num,
        "image_url":    image_url,
        "confidence":   result.get("confidence", "medium"),
        "reason":       result.get("reason", ""),
    }
