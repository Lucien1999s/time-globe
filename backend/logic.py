# backend/logic.py
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# routers
from .services.revgeo import router as revgeo_router
from .services.wiki_place import router as wiki_router
from .services.history_llm import router as history_router
from .utils.assets import ensure_assets

app = FastAPI(title="Time-Globe MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(FRONTEND_DIR / "index.html")

# APIs
app.include_router(revgeo_router, prefix="/api", tags=["revgeo"])
app.include_router(wiki_router, prefix="/api", tags=["place"])
app.include_router(history_router, prefix="/api", tags=["history"])

@app.on_event("startup")
def _startup():
    ensure_assets(FRONTEND_DIR)

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
