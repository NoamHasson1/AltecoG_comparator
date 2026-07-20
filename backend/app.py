import os
import uvicorn
import pandas as pd
from fastapi import FastAPI, File, UploadFile, Request, HTTPException
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
    """
    API endpoint that receives the two uploaded files, runs the reconciliation,
    and returns the discrepancies as JSON.
    """
    try:
        # 2. Load data directly from the uploaded file objects
        # The UploadFile object has a file-like .file attribute that pandas can read
        df_alteco = load_alteco_data(alteco_file.file)
        df_electra = load_electra_data(electra_file.file)

        # 3. Run the existing reconciliation engine
        engine = ReconciliationEngine(df_alteco, df_electra)
        df_errors = engine.run_step_1_metadata()

        # 4. Convert the results to a JSON format for the frontend
        # FastAPI will automatically handle the conversion of this list of dicts to JSON
        results_list = df_errors.to_dict(orient='records')
        
        return JSONResponse(content=jsonable_encoder(results_list))

    except Exception as e:
        # Return a structured error if anything goes wrong during processing
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

if __name__ == '__main__':
    # Runs the FastAPI app with Uvicorn, a high-performance ASGI server.
    # reload=True enables auto-reloading on code changes, similar to Flask's debug mode.
    uvicorn.run("app:app", host="127.0.0.1", port=5001, reload=True)