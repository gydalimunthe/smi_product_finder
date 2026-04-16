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

app = FastAPI(title="Product Finder")
app.mount("/static",  StaticFiles(directory="static"),  name="static")


def get_client() -> OpenAI:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set")
    return OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)


def call_vision(client: OpenAI, image_bytes: bytes, mime: str, prompt: str) -> str:
    b64 = base64.standard_b64encode(image_bytes).decode()
    r = client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=256,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return r.choices[0].message.content.strip()


def parse_json(raw: str) -> dict:
    """Strip markdown fences if present, then parse JSON."""
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


def mime_for(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",  ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/jpeg")


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


# ── Catalog API ────────────────────────────────────────────────────────────

@app.get("/api/pages")
def list_pages():
    """Return all 50 catalog pages (for admin / browse)."""
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

    # Load catalog pages from DB
    with db_context() as conn:
        pages = conn.execute(
            "SELECT page_number, category, image_filename, product_codes"
            " FROM catalog_pages ORDER BY page_number"
        ).fetchall()

    if not pages:
        return JSONResponse(status_code=200, content={
            "matched": False,
            "message": "Catalog not loaded. Contact admin.",
        })

    # Build compact catalog context for the AI
    catalog_lines = []
    for p in pages:
        codes = (p["product_codes"] or "")[:300]
        catalog_lines.append(
            f"Page {p['page_number']} — {p['category']}: {codes}"
        )
    catalog_text = "\n".join(catalog_lines)

    prompt = f"""You are a product identification assistant for a Maxweld ironwork warehouse.

Study the uploaded product photo carefully — look at shape, style, and type.

Below are 50 catalog pages. Each line shows the page number, category, and product codes on that page.
Find the ONE page that best matches the product in the photo:

{catalog_text}

Reply ONLY with valid JSON (no markdown):
If matched:   {{"matched":true,"page":<int>,"confidence":"high"|"medium"|"low","reason":"<one sentence>"}}
If not found: {{"matched":false,"reason":"<why no match>"}}"""

    try:
        client = get_client()
        mime   = mime_for(photo.filename or "")
        raw    = call_vision(client, content, mime, prompt)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Groq API error: {e}")

    try:
        result = parse_json(raw)
    except json.JSONDecodeError:
        return JSONResponse(status_code=200, content={
            "matched": False,
            "message": "Could not parse AI response.",
            "raw": raw,
        })

    if result.get("matched") and result.get("page"):
        pg = next((p for p in pages if p["page_number"] == result["page"]), None)
        if pg:
            result["category"]      = pg["category"]
            result["image_url"]     = f"/static/catalog_pages/{pg['image_filename']}"
            result["product_codes"] = pg["product_codes"]
            result["page_number"]   = pg["page_number"]

    return result
