from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# 本專案根目錄（backend/ 的上一層）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# 本地模組
from .services.revgeo import router as revgeo_router
from .utils.assets import ensure_assets

app = FastAPI(title="Time-Globe MVP")

# CORS（方便未來把前端拆出去或跨網域使用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# 前端靜態 & 首頁
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(FRONTEND_DIR / "index.html")

# API 路由
app.include_router(revgeo_router, prefix="/api", tags=["revgeo"])

# 啟動時確保必要資源存在（三方檔案會下載到 frontend/assets & vendor）
@app.on_event("startup")
def _startup():
    ensure_assets(FRONTEND_DIR)

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
