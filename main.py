import os
import base64
import json
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from database import init_db, db_context

load_dotenv(Path(__file__).parent / ".env")

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_FILE_SIZE      = 10 * 1024 * 1024
GROQ_MODEL         = "meta-llama/llama-4-scout-17b-16e-instruct"
GROQ_BASE_URL      = "https://api.groq.com/openai/v1"
PAGES_DIR          = Path(__file__).parent / "static" / "catalog_pages"
THUMBS_DIR         = Path(__file__).parent / "static" / "catalog_thumbs"

app = FastAPI(title="Product Finder")
app.mount("/static", StaticFiles(directory="static"), name="static")


def get_client() -> OpenAI:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set")
    return OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)


def img_block(data: bytes, mime: str) -> dict:
    b64 = base64.standard_b64encode(data).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def call_vision(client: OpenAI, blocks: list, prompt: str, max_tokens: int = 200) -> str:
    r = client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": blocks + [{"type": "text", "text": prompt}]}],
    )
    return r.choices[0].message.content.strip()


def parse_json(raw: str) -> dict:
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def mime_for(filename: str) -> str:
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
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

    with db_context() as conn:
        pages = conn.execute(
            "SELECT page_number, category, image_filename"
            " FROM catalog_pages ORDER BY page_number"
        ).fetchall()

    if not pages:
        return JSONResponse(content={"matched": False, "message": "Catalog not loaded."})

    mime         = mime_for(photo.filename or "")
    worker_block = img_block(content, mime)

    try:
        client = get_client()
    except HTTPException:
        raise

    # ── STEP 1: Visual scan — worker photo + ALL 50 thumbnails ─────────────
    # Build image blocks: worker photo first, then all 50 thumbnails in order
    step1_blocks = [worker_block]

    page_list_text = []
    for p in pages:
        thumb_path = THUMBS_DIR / p["image_filename"]
        if thumb_path.exists():
            step1_blocks.append(img_block(thumb_path.read_bytes(), "image/jpeg"))
            page_list_text.append(
                f"Thumbnail {p['page_number']}: {p['category']}"
            )

    step1_prompt = f"""You are a product identification assistant for a Maxweld ironwork warehouse catalog.

The FIRST image is a photo taken by a warehouse worker of a product they want to identify.
The REMAINING images are thumbnails of catalog pages 1–50, in order.

Here is what each thumbnail page covers:
{chr(10).join(page_list_text)}

Study the worker's photo carefully. Look at the shape, style, silhouette, and type of the item.
Then scan the catalog thumbnails to find which page visually contains that same type of product.

Return ONLY valid JSON — no markdown, no explanation:
{{"pages": [<top 3 page numbers most likely to contain this product, best first>], "confidence": "high"|"medium"|"low"}}"""

    try:
        raw1   = call_vision(client, step1_blocks, step1_prompt, max_tokens=80)
        step1  = parse_json(raw1)
        candidates = step1.get("pages", [])[:3]   # up to 3 candidate pages
        confidence = step1.get("confidence", "medium")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Step 1 error: {e}")

    if not candidates:
        return JSONResponse(content={"matched": False,
            "message": "Could not identify a matching catalog page."})

    # ── STEP 2: Read full-res page → identify exact product ────────────────
    # Try candidates in order; stop at the first confident match
    best_result = None

    for page_num in candidates:
        matched_page = next((p for p in pages if p["page_number"] == page_num), None)
        if not matched_page:
            continue

        full_img_path = PAGES_DIR / matched_page["image_filename"]
        if not full_img_path.exists():
            continue

        catalog_block = img_block(full_img_path.read_bytes(), "image/jpeg")

        step2_prompt = f"""You have two images:
  IMAGE 1 — A warehouse worker's photo of a product to identify.
  IMAGE 2 — Page {page_num} of the Maxweld catalog ({matched_page['category']}).

Carefully compare the product in IMAGE 1 against every item shown on the catalog page in IMAGE 2.
Look for matching shape, silhouette, scroll style, proportions, and design details.

If you find a match, return ONLY valid JSON:
{{
  "matched": true,
  "product_code": "<exact bold code from the page, e.g. 6182 or 5413A or DR11>",
  "product_name": "<code + brief description, e.g. '6182 Forged Flower Panel'>",
  "dimensions":   "<size exactly as printed>",
  "weight":       "<weight exactly as printed, e.g. 21.5 Lbs>",
  "specs":        "<rod/material size as printed, e.g. 5/16\\"x5/8\\" or Sq.1/2\\">",
  "confidence":   "high"|"medium"|"low",
  "reason":       "<one sentence: specific visual features that matched>"
}}

If no product on this page matches the photo, return:
{{"matched": false}}"""

        try:
            raw2   = call_vision(client, [worker_block, catalog_block], step2_prompt, max_tokens=300)
            result = parse_json(raw2)
        except Exception:
            continue   # try next candidate page

        if result.get("matched"):
            result["page_number"] = page_num
            result["category"]    = matched_page["category"]
            result["image_url"]   = f"/static/catalog_pages/{matched_page['image_filename']}"
            best_result = result
            break   # found a confident match

    # If no step 2 match, fall back to showing the top candidate page
    if not best_result:
        fb_num  = candidates[0]
        fb_page = next((p for p in pages if p["page_number"] == fb_num), None)
        return JSONResponse(content={
            "matched":      False,
            "page_number":  fb_num,
            "category":     fb_page["category"] if fb_page else "",
            "image_url":    f"/static/catalog_pages/{fb_page['image_filename']}" if fb_page else "",
            "reason":       "Product type found in catalog but could not pin exact item — check the page below.",
        })

    return best_result
