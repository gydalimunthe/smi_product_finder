import os
import uuid
import base64
import json
from pathlib import Path

import aiofiles
from dotenv import load_dotenv
from openai import OpenAI
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from database import init_db, db_context

load_dotenv(Path(__file__).parent / ".env")

UPLOAD_DIR   = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_FILE_SIZE      = 10 * 1024 * 1024  # 10 MB
GROQ_MODEL         = "meta-llama/llama-4-scout-17b-16e-instruct"
GROQ_BASE_URL      = "https://api.groq.com/openai/v1"

app = FastAPI(title="Product Finder")
app.mount("/static",  StaticFiles(directory="static"),  name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


def get_client() -> OpenAI:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set in .env")
    return OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)


def call_vision(client: OpenAI, image_bytes: bytes, prompt: str) -> str:
    b64 = base64.standard_b64encode(image_bytes).decode()
    r = client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": prompt},
            ],
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


@app.on_event("startup")
def startup():
    init_db()


# ── Pages ──────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/admin")
def admin():
    return FileResponse("static/admin.html")


# ── Products API ───────────────────────────────────────────────────────────────

@app.get("/api/products")
def list_products():
    with db_context() as conn:
        rows = conn.execute("""
            SELECT p.*, pi.filename AS primary_image
            FROM products p
            LEFT JOIN product_images pi
                   ON pi.product_id = p.id AND pi.is_primary = 1
            ORDER BY p.name
        """).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/products/{product_id}")
def get_product(product_id: int):
    with db_context() as conn:
        product = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        images = conn.execute(
            "SELECT * FROM product_images WHERE product_id = ? ORDER BY is_primary DESC",
            (product_id,),
        ).fetchall()
    return {**dict(product), "images": [dict(i) for i in images]}


@app.post("/api/products")
async def create_product(
    name: str = Form(...),
    specs: str = Form(""),
    weight: str = Form(""),
    category: str = Form(""),
    notes: str = Form(""),
    images: list[UploadFile] = File(default=[]),
):
    if not name.strip():
        raise HTTPException(status_code=400, detail="Product name is required")

    saved_files = []
    for img in images:
        if not img.filename:
            continue
        ext = Path(img.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")
        content = await img.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="Image too large (max 10 MB)")
        filename = f"{uuid.uuid4().hex}{ext}"
        async with aiofiles.open(UPLOAD_DIR / filename, "wb") as f:
            await f.write(content)
        saved_files.append(filename)

    with db_context() as conn:
        cur = conn.execute(
            "INSERT INTO products (name, specs, weight, category, notes) VALUES (?,?,?,?,?)",
            (name.strip(), specs, weight, category, notes),
        )
        pid = cur.lastrowid
        for i, fname in enumerate(saved_files):
            conn.execute(
                "INSERT INTO product_images (product_id, filename, is_primary) VALUES (?,?,?)",
                (pid, fname, 1 if i == 0 else 0),
            )
    return {"id": pid, "message": "Product created"}


@app.put("/api/products/{product_id}")
async def update_product(
    product_id: int,
    name: str = Form(...),
    specs: str = Form(""),
    weight: str = Form(""),
    category: str = Form(""),
    notes: str = Form(""),
    new_images: list[UploadFile] = File(default=[]),
):
    with db_context() as conn:
        if not conn.execute("SELECT id FROM products WHERE id=?", (product_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Product not found")
        conn.execute(
            "UPDATE products SET name=?, specs=?, weight=?, category=?, notes=? WHERE id=?",
            (name.strip(), specs, weight, category, notes, product_id),
        )
        for img in new_images:
            if not img.filename:
                continue
            ext = Path(img.filename).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                continue
            content = await img.read()
            if len(content) > MAX_FILE_SIZE:
                continue
            filename = f"{uuid.uuid4().hex}{ext}"
            async with aiofiles.open(UPLOAD_DIR / filename, "wb") as f:
                await f.write(content)
            has_primary = conn.execute(
                "SELECT id FROM product_images WHERE product_id=? AND is_primary=1",
                (product_id,),
            ).fetchone()
            conn.execute(
                "INSERT INTO product_images (product_id, filename, is_primary) VALUES (?,?,?)",
                (product_id, filename, 0 if has_primary else 1),
            )
    return {"message": "Product updated"}


@app.delete("/api/products/{product_id}")
def delete_product(product_id: int):
    with db_context() as conn:
        images = conn.execute(
            "SELECT filename FROM product_images WHERE product_id=?", (product_id,)
        ).fetchall()
        conn.execute("DELETE FROM products WHERE id=?", (product_id,))
    for row in images:
        p = UPLOAD_DIR / row["filename"]
        if p.exists():
            p.unlink()
    return {"message": "Product deleted"}


@app.delete("/api/products/{product_id}/images/{image_id}")
def delete_image(product_id: int, image_id: int):
    with db_context() as conn:
        row = conn.execute(
            "SELECT filename, is_primary FROM product_images WHERE id=? AND product_id=?",
            (image_id, product_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Image not found")
        conn.execute("DELETE FROM product_images WHERE id=?", (image_id,))
        if row["is_primary"]:
            nxt = conn.execute(
                "SELECT id FROM product_images WHERE product_id=? LIMIT 1", (product_id,)
            ).fetchone()
            if nxt:
                conn.execute("UPDATE product_images SET is_primary=1 WHERE id=?", (nxt["id"],))
    p = UPLOAD_DIR / row["filename"]
    if p.exists():
        p.unlink()
    return {"message": "Image deleted"}


# ── Product Identification ─────────────────────────────────────────────────────

@app.post("/api/identify")
async def identify_product(photo: UploadFile = File(...)):
    ext = Path(photo.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    content = await photo.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Image too large (max 10 MB)")

    with db_context() as conn:
        products = conn.execute(
            "SELECT id, name, specs, weight, category FROM products ORDER BY name"
        ).fetchall()

    if not products:
        return JSONResponse(status_code=200, content={
            "matched": False,
            "message": "No products in catalog yet. Ask an admin to add products first.",
        })

    catalog_lines = []
    for p in products:
        line = f"- ID {p['id']}: {p['name']}"
        if p["category"]: line += f" | Category: {p['category']}"
        if p["specs"]:    line += f" | Specs: {p['specs']}"
        if p["weight"]:   line += f" | Weight: {p['weight']}"
        catalog_lines.append(line)

    prompt = f"""You are a product identification assistant for a warehouse/shop.

Product catalog:
{chr(10).join(catalog_lines)}

Look carefully at the image and match it to the best product in the catalog above.
Return ONLY a JSON object — no markdown, no explanation.

If matched:
{{
  "matched": true,
  "product_id": <integer ID from catalog>,
  "confidence": "high" | "medium" | "low",
  "reason": "<brief explanation>"
}}

If NOT in catalog:
{{
  "matched": false,
  "description": "<what you see in the image>",
  "reason": "<why it doesn't match any catalog item>"
}}"""

    try:
        client = get_client()
        raw    = call_vision(client, content, prompt)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Groq API error: {e}")

    try:
        result = parse_json(raw)
    except json.JSONDecodeError:
        return JSONResponse(status_code=200, content={
            "matched": False,
            "message": "Could not parse AI response",
            "raw": raw,
        })

    if result.get("matched") and result.get("product_id"):
        pid = result["product_id"]
        with db_context() as conn:
            product = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            imgs    = conn.execute(
                "SELECT * FROM product_images WHERE product_id=? ORDER BY is_primary DESC",
                (pid,),
            ).fetchall()
        if product:
            result["product"] = {**dict(product), "images": [dict(i) for i in imgs]}

    return result
