import os
import uvicorn
import pandas as pd
from fastapi import FastAPI, File, UploadFile, Request, HTTPException
import traceback
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from src.data_loader import load_alteco_data, load_electra_data
from src.reconciliation_engine import ReconciliationEngine

# Initialize the FastAPI application
app = FastAPI()

# --- Path Configuration for Backend/Frontend Structure ---

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BACKEND_DIR), "frontend")

# Mount the 'static' directory to serve CSS and JS files
app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_DIR, "static")), name="static")

# Set up Jinja2 to render the HTML template
templates = Jinja2Templates(directory=os.path.join(FRONTEND_DIR, "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """
    Serves the main HTML page of the UI.
    """
    return templates.TemplateResponse(request, "index.html")

@app.post("/reconcile")
async def reconcile_files(alteco_file: UploadFile = File(...), electra_file: UploadFile = File(...)):
    try:
        df_alteco = load_alteco_data(alteco_file.file)
        df_electra = load_electra_data(electra_file.file)

        engine = ReconciliationEngine(df_alteco, df_electra)
        
        results_dict = engine.run_all_steps()

        response_data = {
            "step0": results_dict["step0"].to_dict(orient='records'),
            "step1": results_dict["step1"].to_dict(orient='records'),
            "step2": results_dict["step2"].to_dict(orient='records')
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