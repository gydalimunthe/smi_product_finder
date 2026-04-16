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
MAX_FILE_SIZE      = 10 * 1024 * 1024   # 10 MB
GROQ_MODEL         = "meta-llama/llama-4-scout-17b-16e-instruct"
GROQ_BASE_URL      = "https://api.groq.com/openai/v1"
PAGES_DIR          = Path(__file__).parent / "static" / "catalog_pages"

app = FastAPI(title="Product Finder")
app.mount("/static", StaticFiles(directory="static"), name="static")


def get_client() -> OpenAI:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set")
    return OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)


def b64_image(data: bytes, mime: str) -> dict:
    """Return an image_url content block."""
    b64 = base64.standard_b64encode(data).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def call_vision(client: OpenAI, content_blocks: list, prompt: str, max_tokens: int = 400) -> str:
    r = client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=max_tokens,
        messages=[{
            "role": "user",
            "content": content_blocks + [{"type": "text", "text": prompt}],
        }],
    )
    return r.choices[0].message.content.strip()


def parse_json(raw: str) -> dict:
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


def mime_for(filename: str) -> str:
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
    }.get(Path(filename or "").suffix.lower(), "image/jpeg")


@app.on_event("startup")
def startup():
    init_db()


# ── Pages ──────────────────────────────────────────────────────────────────

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


# ── Identify ───────────────────────────────────────────────────────────────

@app.post("/api/identify")
async def identify_product(photo: UploadFile = File(...)):
    ext = Path(photo.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    content = await photo.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Image too large (max 10 MB)")

    # Load catalog page list
    with db_context() as conn:
        pages = conn.execute(
            "SELECT page_number, category, image_filename, product_codes"
            " FROM catalog_pages ORDER BY page_number"
        ).fetchall()

    if not pages:
        return JSONResponse(status_code=200, content={
            "matched": False, "message": "Catalog not loaded.",
        })

    mime          = mime_for(photo.filename or "")
    worker_block  = b64_image(content, mime)

    try:
        client = get_client()
    except HTTPException:
        raise

    # ── STEP 1: Find the best matching catalog page ─────────────────────────
    catalog_text = "\n".join(
        f"Page {p['page_number']} — {p['category']}: {(p['product_codes'] or '')[:200]}"
        for p in pages
    )

    step1_prompt = f"""You are a product identification assistant for a Maxweld ironwork warehouse.

Look at the uploaded product photo carefully.
Below are 50 catalog pages with their category and product codes.
Find the ONE page number that most likely contains this product.

{catalog_text}

Reply ONLY with valid JSON (no markdown):
{{"page": <int 1-50>, "confidence": "high"|"medium"|"low"}}"""

    try:
        raw1 = call_vision(client, [worker_block], step1_prompt, max_tokens=60)
        step1 = parse_json(raw1)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Step 1 error: {e}")

    page_num = step1.get("page")
    if not page_num:
        return JSONResponse(status_code=200, content={"matched": False,
            "message": "Could not identify a matching catalog page."})

    matched_page = next((p for p in pages if p["page_number"] == page_num), None)
    if not matched_page:
        return JSONResponse(status_code=200, content={"matched": False,
            "message": f"Page {page_num} not found in catalog."})

    # ── STEP 2: Read catalog page image → identify exact product ───────────
    catalog_img_path = PAGES_DIR / matched_page["image_filename"]
    if not catalog_img_path.exists():
        return JSONResponse(status_code=200, content={"matched": False,
            "message": f"Catalog image for page {page_num} not found."})

    catalog_img_bytes = catalog_img_path.read_bytes()
    catalog_block     = b64_image(catalog_img_bytes, "image/jpeg")

    step2_prompt = f"""You are a product identification assistant for a Maxweld ironwork warehouse.

You have two images:
  IMAGE 1 — A photo taken by a warehouse worker of a product they want to identify.
  IMAGE 2 — Page {page_num} of the Maxweld catalog (category: {matched_page['category']}).

Study both images carefully. Find the product in the catalog page that best matches the worker's photo.

Read the product details exactly as printed on the catalog page and return ONLY valid JSON:

If you can identify the product:
{{
  "matched": true,
  "product_code": "<exact code as printed, e.g. 6182 or 5413A or DR11>",
  "product_name": "<code + short description, e.g. '6182 Forged Flower Panel'>",
  "dimensions":   "<size as printed, e.g. 24\\" x 28-3/4\\" or R 22\\">",
  "weight":       "<weight as printed, e.g. 21.5 Lbs>",
  "specs":        "<material/rod size as printed, e.g. 5/16\\"x5/8\\" or Sq.1/2\\">",
  "confidence":   "high"|"medium"|"low",
  "reason":       "<one sentence: what visual features matched>"
}}

If no product on that page matches:
{{"matched": false, "reason": "<why no match>"}}"""

    try:
        raw2   = call_vision(client, [worker_block, catalog_block], step2_prompt, max_tokens=300)
        result = parse_json(raw2)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Step 2 error: {e}")

    # Attach page info to the result
    result["page_number"] = page_num
    result["category"]    = matched_page["category"]
    result["image_url"]   = f"/static/catalog_pages/{matched_page['image_filename']}"

    # If step 2 says no match but step 1 was confident, still show the page
    if not result.get("matched"):
        result["matched"]  = False
        result["page_number"] = page_num
        result["category"]    = matched_page["category"]
        result["image_url"]   = f"/static/catalog_pages/{matched_page['image_filename']}"

    return result
