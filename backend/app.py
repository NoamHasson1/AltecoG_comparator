import json
import os
import re
import uvicorn
import pandas as pd
from fastapi import FastAPI, File, Form, UploadFile, Request, HTTPException
import traceback
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from src.data_loader import load_alteco_data
from src.dynamic_loader import inspect_workbook, load_mapped_data
from src.reconciliation_engine import ReconciliationEngine

# Initialize the FastAPI application
app = FastAPI()

# --- Path Configuration for Backend/Frontend Structure ---

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BACKEND_DIR), "frontend")
MAPPINGS_DIR = os.path.join(BACKEND_DIR, "mappings")

# Bundled preset that main.py and the test suite depend on always existing —
# protected from deletion so "Reset All" / single-delete can't take it out.
PROTECTED_MAPPING_NAME = "electra_default"

# Mount the 'static' directory to serve CSS and JS files
app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_DIR, "static")), name="static")

# Set up Jinja2 to render the HTML template
templates = Jinja2Templates(directory=os.path.join(FRONTEND_DIR, "templates"))


def _safe_mapping_filename(name):
    """Restricts a user-supplied mapping name to a safe filename (no path traversal)."""
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


@app.get("/mappings")
async def list_mappings():
    """Lists saved mapping names (without the .json extension)."""
    if not os.path.isdir(MAPPINGS_DIR):
        return JSONResponse(content=[])
    names = sorted(f[:-5] for f in os.listdir(MAPPINGS_DIR) if f.endswith(".json"))
    return JSONResponse(content=names)


@app.get("/mappings/{name}")
async def get_mapping(name: str):
    """Returns a previously saved mapping config by name."""
    filename = _safe_mapping_filename(name)
    path = os.path.join(MAPPINGS_DIR, f"{filename}.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"No saved mapping named '{name}'")
    with open(path, "r", encoding="utf-8") as f:
        return JSONResponse(content=json.load(f))


@app.post("/mappings/{name}")
async def save_mapping(name: str, mapping: dict):
    """Saves a mapping config under the given name, overwriting any existing one."""
    filename = _safe_mapping_filename(name)
    os.makedirs(MAPPINGS_DIR, exist_ok=True)
    path = os.path.join(MAPPINGS_DIR, f"{filename}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    return JSONResponse(content={"status": "saved", "name": filename})


@app.delete("/mappings/{name}")
async def delete_mapping(name: str):
    """Deletes a single saved mapping by name."""
    filename = _safe_mapping_filename(name)
    if filename == PROTECTED_MAPPING_NAME:
        raise HTTPException(status_code=400, detail="The bundled default mapping can't be deleted.")
    path = os.path.join(MAPPINGS_DIR, f"{filename}.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"No saved mapping named '{name}'")
    os.remove(path)
    return JSONResponse(content={"status": "deleted", "name": filename})


@app.delete("/mappings")
async def delete_all_mappings():
    """Deletes every saved mapping except the bundled default (main.py and the tests depend on it existing)."""
    if os.path.isdir(MAPPINGS_DIR):
        for f in os.listdir(MAPPINGS_DIR):
            if f.endswith(".json") and f[:-5] != PROTECTED_MAPPING_NAME:
                os.remove(os.path.join(MAPPINGS_DIR, f))
    return JSONResponse(content={"status": "cleared"})


@app.post("/reconcile")
async def reconcile_files(
    alteco_file: UploadFile = File(...),
    electra_file: UploadFile = File(...),
    mapping: str = Form(...),
):
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

        return JSONResponse(content=jsonable_encoder(response_data))

    except Exception as e:
        print("--- DETAILED ERROR ---")
        traceback.print_exc()
        print("----------------------")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

if __name__ == '__main__':
    # Runs the FastAPI app with Uvicorn, a high-performance ASGI server.
    # reload=True enables auto-reloading on code changes, similar to Flask's debug mode.
    uvicorn.run("app:app", host="127.0.0.1", port=5001, reload=True)
