import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

from app.pipeline import run_generation_pipeline, build_codex_prompt_package
from app.generator import generate_descriptions, apply_legacy_inline_styles, normalize_product_metadata, normalize_description_html
from app.exporter import export_results
from app.config import HOST, PORT
from app.validator import validate_generated_content
from app.json_utils import parse_llm_json
from app.logger import logger
from app.batch import (
    BatchError,
    approve_products,
    build_report_csv,
    create_batch,
    decode_upload,
    get_batch,
    get_product,
    init_db,
    list_batches,
    list_products,
    recover_interrupted_jobs,
    save_product,
    start_generation,
    start_publish,
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    recover_interrupted_jobs()
    yield


app = FastAPI(title="graszki.pl - Generator Opisów Produktów", lifespan=lifespan)

# Resolve template & static paths
WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

# Create directories if they do not exist
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Setup templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Pydantic schemas for requests
class GenerateRequest(BaseModel):
    product_name: str
    original_title: Optional[str] = ""
    publisher: Optional[str] = ""
    is_preorder: Optional[bool] = False
    release_date_note: Optional[str] = ""
    category: Optional[str] = ""
    target_audience: Optional[str] = ""
    official_link: Optional[str] = ""
    manual_link: Optional[str] = ""
    tone_preference: Optional[str] = "sales"
    api_key: Optional[str] = ""
    api_provider: Optional[str] = ""
    api_base_url: Optional[str] = ""
    api_model: Optional[str] = ""

class SaveEditRequest(BaseModel):
    product_name: str
    original_title: str
    is_preorder: bool
    release_date_note: str
    short_description: str
    seo_title: str
    meta_description: str
    tags: List[str]
    extended_description_html: str
    box_contents: List[str]
    additional_info: Dict[str, str]
    sources: List[Dict[str, Any]]
    warnings: List[str]

class RegenerateRequest(BaseModel):
    product_name: str
    original_title: Optional[str] = ""
    is_preorder: Optional[bool] = False
    release_date_note: Optional[str] = ""
    category: Optional[str] = ""
    target_audience: Optional[str] = ""
    official_link: Optional[str] = ""
    manual_link: Optional[str] = ""
    tone_preference: str # standard, sales, neutral, family, short
    resolved_facts: Dict[str, Any]
    api_key: Optional[str] = ""
    api_provider: Optional[str] = ""
    api_base_url: Optional[str] = ""
    api_model: Optional[str] = ""

class ImportCodexResultRequest(BaseModel):
    response_text: str

class BatchImportRequest(BaseModel):
    sky_csv_base64: str
    rebel_csv_base64: Optional[str] = None
    name: Optional[str] = ""

class BatchGenerateRequest(BaseModel):
    mode: str = "pilot"
    limit: int = 50

class BatchProductSaveRequest(BaseModel):
    content: Dict[str, Any]
    approved: bool = False

class BatchApproveRequest(BaseModel):
    product_ids: List[str]

class BatchDangerousActionRequest(BaseModel):
    confirmation: str

def normalize_product_output(data: Dict[str, Any]) -> Dict[str, Any]:
    additional_info = data.get("additional_info") or {}
    if not isinstance(additional_info, dict):
        additional_info = {}

    sources = data.get("sources") or []
    if not isinstance(sources, list):
        sources = []

    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",") if tag.strip()]

    box_contents = data.get("box_contents") or []
    if isinstance(box_contents, str):
        box_contents = [item.strip() for item in box_contents.splitlines() if item.strip()]

    warnings = data.get("warnings") or []
    if isinstance(warnings, str):
        warnings = [warnings]

    html_content = normalize_description_html(
        data.get("extended_description_html", ""),
        box_contents=box_contents,
        is_preorder=bool(data.get("is_preorder", False)),
        release_date_note=data.get("release_date_note", ""),
        game_name=data.get("product_name", ""),
    )

    normalized = {
        "product_name": data.get("product_name", ""),
        "original_title": data.get("original_title", ""),
        "is_preorder": bool(data.get("is_preorder", False)),
        "release_date_note": data.get("release_date_note", ""),
        "short_description": data.get("short_description", ""),
        "seo_title": data.get("seo_title", ""),
        "meta_description": data.get("meta_description", ""),
        "tags": tags,
        "extended_description_html": apply_legacy_inline_styles(html_content),
        "box_contents": box_contents,
        "additional_info": {
            "publisher": additional_info.get("publisher", ""),
            "designer": additional_info.get("designer", ""),
            "illustrator": additional_info.get("illustrator", ""),
            "edition_language": additional_info.get("edition_language") or "polski",
            "manual_language": additional_info.get("manual_language") or "polski",
            "players": additional_info.get("players", ""),
            "age": additional_info.get("age", ""),
            "play_time": additional_info.get("play_time", ""),
            "instruction_pdf": additional_info.get("instruction_pdf", ""),
        },
        "sources": sources,
        "warnings": warnings,
    }
    return normalize_product_metadata(normalized)

@app.get("/", response_class=HTMLResponse)
async def read_index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/batches")
def api_list_batches():
    return {"items": list_batches()}

@app.post("/api/batches/import")
def api_import_batch(payload: BatchImportRequest):
    try:
        sky_raw = decode_upload(payload.sky_csv_base64)
        rebel_raw = decode_upload(payload.rebel_csv_base64) if payload.rebel_csv_base64 else None
        return create_batch(sky_raw, rebel_raw, payload.name or "")
    except BatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.get("/api/batches/{batch_id}")
def api_get_batch(batch_id: str):
    try:
        return get_batch(batch_id)
    except BatchError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.get("/api/batches/{batch_id}/products")
def api_list_batch_products(batch_id: str, status: str = "", limit: int = 200, offset: int = 0):
    try:
        return list_products(batch_id, status, limit, offset)
    except BatchError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.get("/api/batches/{batch_id}/report.csv")
def api_batch_report(batch_id: str):
    try:
        report = build_report_csv(batch_id)
        return Response(
            content="\ufeff" + report,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="batch-{batch_id}.csv"'},
        )
    except BatchError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.get("/api/batches/{batch_id}/products/{product_id}")
def api_get_batch_product(batch_id: str, product_id: str):
    try:
        return get_product(batch_id, product_id)
    except BatchError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@app.post("/api/batches/{batch_id}/generate")
def api_generate_batch(batch_id: str, payload: BatchGenerateRequest):
    try:
        return start_generation(batch_id, payload.mode, payload.limit)
    except BatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@app.put("/api/batches/{batch_id}/products/{product_id}")
def api_save_batch_product(batch_id: str, product_id: str, payload: BatchProductSaveRequest):
    try:
        return save_product(batch_id, product_id, payload.content, payload.approved)
    except BatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/batches/{batch_id}/approve")
def api_approve_batch_products(batch_id: str, payload: BatchApproveRequest):
    try:
        return {"updated": approve_products(batch_id, payload.product_ids)}
    except BatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/batches/{batch_id}/publish")
def api_publish_batch(batch_id: str, payload: BatchDangerousActionRequest):
    if payload.confirmation != batch_id:
        raise HTTPException(status_code=400, detail="Potwierdzenie nie zgadza się z ID partii.")
    try:
        return start_publish(batch_id)
    except BatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@app.post("/api/batches/{batch_id}/rollback")
def api_rollback_batch(batch_id: str, payload: BatchDangerousActionRequest):
    if payload.confirmation != batch_id:
        raise HTTPException(status_code=400, detail="Potwierdzenie nie zgadza się z ID partii.")
    try:
        return start_publish(batch_id, rollback=True)
    except BatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@app.post("/api/generate")
async def api_generate(payload: GenerateRequest):
    try:
        user_inputs = payload.model_dump()
        result = run_generation_pipeline(user_inputs)
        return result
    except Exception as e:
        logger.exception("Error during API generate")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/codex-prompt")
async def api_codex_prompt(payload: GenerateRequest):
    try:
        user_inputs = payload.model_dump()
        return build_codex_prompt_package(user_inputs)
    except Exception as e:
        logger.exception("Error during Codex prompt build")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/import-codex-result")
async def api_import_codex_result(payload: ImportCodexResultRequest):
    try:
        parsed = parse_llm_json(payload.response_text)
        product_data = normalize_product_output(parsed)
        if not product_data["product_name"]:
            raise ValueError("Wynik Codexa nie zawiera pola product_name.")

        fact_sources = {
            "players": "codex_import",
            "age": "codex_import",
            "play_time": "codex_import",
        }
        validation_warnings = validate_generated_content(
            short_desc=product_data.get("short_description", ""),
            meta_desc=product_data.get("meta_description", ""),
            seo_title=product_data.get("seo_title", ""),
            html_desc=product_data.get("extended_description_html", ""),
            is_preorder=product_data.get("is_preorder", False),
            additional_info=product_data.get("additional_info", {}),
            fact_sources=fact_sources,
            box_contents=product_data.get("box_contents", []),
        )
        product_data["warnings"] = list(dict.fromkeys(product_data.get("warnings", []) + validation_warnings))

        export_results(product_data)
        return product_data
    except Exception as e:
        logger.exception("Error during Codex result import")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/save-manual-edit")
async def api_save_manual_edit(payload: SaveEditRequest):
    try:
        product_data = payload.model_dump()
        normalize_product_metadata(product_data)
        product_data["extended_description_html"] = normalize_description_html(
            product_data.get("extended_description_html", ""),
            box_contents=product_data.get("box_contents", []),
            is_preorder=product_data.get("is_preorder", False),
            release_date_note=product_data.get("release_date_note", ""),
            game_name=product_data.get("product_name", ""),
        )
        slug = export_results(product_data)
        return {"status": "success", "slug": slug, "message": "Poprawiona wersja została zapisana."}
    except Exception as e:
        logger.exception("Error during API save manual edit")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/regenerate")
async def api_regenerate(payload: RegenerateRequest):
    """
    Regenerates the description and metadata without scraping websites again,
    using the facts that were already resolved.
    """
    try:
        resolved_facts = payload.resolved_facts
        user_inputs = {
            "product_name": payload.product_name,
            "original_title": payload.original_title,
            "is_preorder": payload.is_preorder,
            "release_date_note": payload.release_date_note,
            "category": payload.category,
            "target_audience": payload.target_audience,
            "official_link": payload.official_link,
            "manual_link": payload.manual_link,
            "tone_preference": payload.tone_preference,
            "api_key": payload.api_key,
            "api_provider": payload.api_provider,
            "api_base_url": payload.api_base_url,
            "api_model": payload.api_model
        }
        
        # 1. Regenerate content via LLM
        generated = generate_descriptions(
            game_name=payload.product_name,
            resolved_facts=resolved_facts,
            user_inputs=user_inputs,
            force_tone=payload.tone_preference
        )
        
        # 2. Extract facts sources mapping (if available in original payload, or default)
        # For validation, we need to know what sources were mapped.
        # We can construct a mock fact_sources based on sources list
        fact_sources = {}
        for field in ["players", "age", "play_time"]:
            fact_sources[field] = "cache"
            
        # 3. Validate
        validation_warnings = validate_generated_content(
            short_desc=generated.get("short_description", ""),
            meta_desc=generated.get("meta_description", ""),
            seo_title=generated.get("seo_title", ""),
            html_desc=generated.get("extended_description_html", ""),
            is_preorder=payload.is_preorder,
            additional_info=resolved_facts,
            fact_sources=fact_sources,
            box_contents=resolved_facts.get("box_contents", [])
        )
        
        # 4. Form final product structure
        product_name_final = payload.product_name
        if payload.is_preorder and not (payload.product_name.lower().startswith("przedsprzedaz") or payload.product_name.lower().startswith("przedsprzedaż")):
            product_name_final = f"Przedsprzedaż {payload.product_name}"
            
        final_output = {
            "product_name": product_name_final,
            "original_title": payload.original_title or resolved_facts.get("original_title", ""),
            "is_preorder": payload.is_preorder,
            "release_date_note": resolved_facts.get("release_date", "") if payload.is_preorder else "",
            "short_description": generated.get("short_description", ""),
            "seo_title": generated.get("seo_title", ""),
            "meta_description": generated.get("meta_description", ""),
            "tags": generated.get("tags", []),
            "extended_description_html": generated.get("extended_description_html", ""),
            "box_contents": resolved_facts.get("box_contents", []),
            "additional_info": {
                "publisher": resolved_facts.get("publisher", ""),
                "designer": resolved_facts.get("designer", ""),
                "illustrator": resolved_facts.get("illustrator", ""),
                "edition_language": resolved_facts.get("edition_language") or "polski",
                "manual_language": resolved_facts.get("manual_language") or "polski",
                "players": resolved_facts.get("players", ""),
                "age": resolved_facts.get("age", ""),
                "play_time": resolved_facts.get("play_time", ""),
                "instruction_pdf": resolved_facts.get("instruction_pdf", "")
            },
            # Keep original sources
            "sources": resolved_facts.get("original_sources", []),
            "warnings": validation_warnings
        }
        normalize_product_metadata(final_output)
        
        # 5. Export
        export_results(final_output)
        
        return final_output
        
    except Exception as e:
        logger.exception("Error during API regenerate")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.web.main:app", host=HOST, port=PORT, reload=True)
