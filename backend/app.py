import json
import logging
import os
import re
import uvicorn
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile, Request, HTTPException
import traceback
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from src.ai_mapping import suggest_field_mapping
from src.data_loader import load_alteco_data
from src.dynamic_loader import inspect_workbook, load_mapped_data
from src.export_report import build_discrepancy_workbook
from src.reconciliation_engine import ReconciliationEngine
from src import mapping_store

# Full pipeline visibility in the terminal: every loaded DataFrame (shape +
# full content), every field-by-field comparison (not just mismatches), and
# the overall flow through each reconciliation step. DEBUG is very verbose —
# on a large real client file this can print thousands of lines per request.
# Drop to logging.INFO here (keeps the flow/shape logs, drops the per-field
# comparison dump and full DataFrame printouts) if that's too much.
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# --- Path Configuration for Backend/Frontend Structure ---

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BACKEND_DIR), "frontend")

load_dotenv(os.path.join(os.path.dirname(BACKEND_DIR), ".env"))

# Initialize the FastAPI application
app = FastAPI()

# Bundled preset that main.py and the test suite depend on always existing —
# protected from deletion so "Reset All" / single-delete can't take it out.
PROTECTED_MAPPING_NAME = "electra_default"

# Mount the 'static' directory to serve CSS and JS files
app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_DIR, "static")), name="static")

# Set up Jinja2 to render the HTML template
templates = Jinja2Templates(directory=os.path.join(FRONTEND_DIR, "templates"))


def _clean_mapping_name(name):
    """Restricts a user-supplied mapping name to a safe, predictable set of characters."""
    sanitized = re.sub(r"[^A-Za-z0-9_\- ]", "", name).strip()
    if not sanitized:
        raise HTTPException(status_code=400, detail="Invalid mapping name")
    return sanitized


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """
    Serves the main HTML page of the UI.
    """
    return templates.TemplateResponse(request, "index.html")


@app.post("/inspect-file")
async def inspect_file(file: UploadFile = File(...)):
    """
    Reads an uploaded client billing file and returns its sheet/column
    structure (plus a few sample rows per sheet) so the mapping UI can be
    built against the file's real shape.
    """
    try:
        return JSONResponse(content=jsonable_encoder(inspect_workbook(file.file)))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Could not read file: {str(e)}")


@app.post("/suggest-mapping")
async def suggest_mapping(payload: dict):
    """
    Given the already-inspected client sheets, asks Claude to suggest matches
    for the 13 direct fields. Scoped to direct fields only — calculated
    fields still require manual configuration.
    """
    sheets = payload.get("sheets")
    if not sheets:
        raise HTTPException(status_code=400, detail="Missing 'sheets'")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503, detail="AI suggestions are not configured (set ANTHROPIC_API_KEY in .env)")
    try:
        return JSONResponse(content=jsonable_encoder(suggest_field_mapping(sheets)))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=502, detail=f"AI suggestion failed: {str(e)}")


def _mapping_store_error(e: RuntimeError):
    raise HTTPException(status_code=503, detail=str(e))


@app.get("/mappings")
async def list_mappings():
    """Lists saved mapping names."""
    try:
        return JSONResponse(content=mapping_store.list_mapping_names())
    except RuntimeError as e:
        _mapping_store_error(e)


@app.get("/mappings/{name}")
async def get_mapping(name: str):
    """Returns a previously saved mapping config by name."""
    clean_name = _clean_mapping_name(name)
    try:
        config = mapping_store.get_mapping(clean_name)
    except RuntimeError as e:
        _mapping_store_error(e)
    if config is None:
        raise HTTPException(status_code=404, detail=f"No saved mapping named '{name}'")
    return JSONResponse(content=config)


@app.post("/mappings/{name}")
async def save_mapping(name: str, mapping: dict):
    """Saves a mapping config under the given name, overwriting any existing one."""
    clean_name = _clean_mapping_name(name)
    try:
        mapping_store.save_mapping(clean_name, mapping)
    except RuntimeError as e:
        _mapping_store_error(e)
    return JSONResponse(content={"status": "saved", "name": clean_name})


@app.delete("/mappings/{name}")
async def delete_mapping(name: str):
    """Deletes a single saved mapping by name."""
    clean_name = _clean_mapping_name(name)
    if clean_name == PROTECTED_MAPPING_NAME:
        raise HTTPException(status_code=400, detail="The bundled default mapping can't be deleted.")
    try:
        deleted = mapping_store.delete_mapping(clean_name)
    except RuntimeError as e:
        _mapping_store_error(e)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No saved mapping named '{name}'")
    return JSONResponse(content={"status": "deleted", "name": clean_name})


@app.delete("/mappings")
async def delete_all_mappings():
    """Deletes every saved mapping except the bundled default (main.py and the tests depend on it existing)."""
    try:
        mapping_store.delete_all_mappings(except_name=PROTECTED_MAPPING_NAME)
    except RuntimeError as e:
        _mapping_store_error(e)
    return JSONResponse(content={"status": "cleared"})


@app.post("/reconcile")
async def reconcile_files(
    alteco_file: UploadFile = File(...),
    electra_file: UploadFile = File(...),
    mapping: str = Form(...),
):
    logger = logging.getLogger("app.reconcile")
    logger.info("RECONCILE REQUEST: alteco_file=%r electra_file=%r", alteco_file.filename, electra_file.filename)
    try:
        mapping_config = json.loads(mapping)

        df_alteco = load_alteco_data(alteco_file.file)
        df_electra = load_mapped_data(electra_file.file, mapping_config)

        engine = ReconciliationEngine(df_alteco, df_electra)

        results_dict = engine.run_all_steps()

        response_data = {
            "step0": results_dict["step0"].to_dict(orient='records'),
            "step1": results_dict["step1"].to_dict(orient='records'),
            "step2": results_dict["step2"].to_dict(orient='records'),
            "step3": results_dict["step3"].to_dict(orient='records')
        }
        logger.info(
            "RECONCILE RESPONSE: step0=%d step1=%d step2=%d step3=%d",
            len(response_data["step0"]), len(response_data["step1"]),
            len(response_data["step2"]), len(response_data["step3"]),
        )

        return JSONResponse(content=jsonable_encoder(response_data))

    except Exception as e:
        logger.exception("RECONCILE FAILED")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

@app.post("/export-discrepancies")
async def export_discrepancies(results: dict):
    """
    Rebuilds the reconciliation results (as already returned by /reconcile)
    into a formatted, downloadable .xlsx report — a Summary sheet plus one
    sheet per phase, bold header row, frozen header, auto-sized columns.
    """
    try:
        buffer = build_discrepancy_workbook(results)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Could not build report: {str(e)}")

    filename = f"reconciliation_mismatches_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == '__main__':
    # Runs the FastAPI app with Uvicorn, a high-performance ASGI server.
    # reload=True enables auto-reloading on code changes, similar to Flask's debug mode.
    uvicorn.run("app:app", host="127.0.0.1", port=5001, reload=True)
